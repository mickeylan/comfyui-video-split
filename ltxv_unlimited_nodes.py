"""
LTX Video Sampler Unlimited - AV 联合分块采样器

基于 MiniMax H3 Unlimited 架构，支持 LTX Video 的 AV 联合 latent 分块采样。

核心原理:
1. 处理 AV 联合 NestedTensor latent
2. 分离 video 和 audio 分别处理
3. 使用重叠 latent 作为连续引导
4. 重新组合 video 和 audio
"""

import logging
from dataclasses import dataclass

import torch

import comfy
import comfy.hooks
import comfy.model_patcher
import comfy.multigpu
import comfy.nested_tensor
import comfy.patcher_extension
import comfy.sampler_helpers
import comfy.samplers
import comfy_extras.nodes_custom_sampler
import latent_preview

from .preview import begin_preview_execution


# ============================================================================
# LTX Video 帧结构常量
# ============================================================================

# LTX Video 帧结构: 像素帧数 = 8 * n + 1
# latent 步数 = n + 1


def pixel_frames_to_latent_steps(pixel_frames: int) -> int:
    """将像素帧数转换为 latent 步数"""
    if pixel_frames < 9:
        raise ValueError(f"LTX minimum is 9 pixel frames, got {pixel_frames}")
    if (pixel_frames - 1) % 8 != 0:
        raise ValueError(f"LTX requires (frames-1) to be divisible by 8, got {pixel_frames}")
    return (pixel_frames - 1) // 8 + 1


def latent_steps_to_pixel_frames(latent_steps: int) -> int:
    """将 latent 步数转换为像素帧数"""
    return (latent_steps - 1) * 8 + 1


# ============================================================================
# 分块规划 (支持 AV 联合)
# ============================================================================

@dataclass
class ChunkPlan:
    """单个分块的规划信息"""
    chunk_index: int
    # Video latent 级别索引
    video_start: int
    video_end: int
    # Audio latent 级别索引
    audio_start: int
    audio_end: int
    # 像素帧级别
    frame_start: int
    frame_end: int
    # 是否是第一个分块
    is_first: bool
    # Video 重叠 latent 步数
    overlap_video_steps: int
    # Audio 上下文步数
    context_audio_steps: int


def _chunk_plan(video_t, audio_t, chunk_frames, time_scale_factor=8):
    chunk_frames = max(9, chunk_frames)
    max_chunk_frames = chunk_frames - (chunk_frames - 1) % time_scale_factor
    max_chunk_t = pixel_frames_to_latent_steps(max_chunk_frames)
    if video_t < 1:
        raise ValueError(f"LTX video latent must contain at least one step, got {video_t}")
    if max_chunk_t < 2:
        raise ValueError("LTX chunk must contain at least two latent steps")

    overlap_video_steps = 1
    plan = []
    video_end = 0
    previous_audio_end = 0
    while video_end < video_t:
        video_start = 0 if not plan else video_end - overlap_video_steps
        next_video_end = min(video_start + max_chunk_t, video_t)
        audio_start = round(video_start * audio_t / video_t) if audio_t else 0
        audio_end = round(next_video_end * audio_t / video_t) if audio_t else 0
        context_audio_steps = 0 if not plan else previous_audio_end - audio_start
        frame_start = 0 if not plan else latent_steps_to_pixel_frames(video_start)
        frame_end = latent_steps_to_pixel_frames(next_video_end)
        plan.append(ChunkPlan(
            chunk_index=len(plan),
            video_start=video_start,
            video_end=next_video_end,
            audio_start=audio_start,
            audio_end=audio_end,
            frame_start=frame_start,
            frame_end=frame_end,
            is_first=not plan,
            overlap_video_steps=0 if not plan else overlap_video_steps,
            context_audio_steps=context_audio_steps,
        ))
        video_end = next_video_end
        previous_audio_end = audio_end

    return plan


def _slice_mask(mask, start, end, reference):
    if mask is None:
        return torch.ones_like(reference[:, :1])
    mask = comfy.utils.reshape_mask(mask, reference.shape)
    return mask[:, :1, start:end].clone()


def _copy_conds(conds):
    return {name: [cond.copy() for cond in values] for name, values in conds.items()}


def _conditioning_for_chunk(original_conds, video_start, video_end, tokens_per_frame):
    chunk_conds = {}
    for name, conditioning in original_conds.items():
        entries = []
        for cond in conditioning:
            cond = cond.copy()
            # CFGGuider.original_conds contains converted conditioning dictionaries,
            # not the public [embedding, metadata] pairs.
            cond.pop("keyframe_idxs", None)
            cond.pop("guide_attention_entries", None)
            generated = cond.get("generated_keyframes")
            if generated is not None:
                first = generated["first_latent_frame"]
                last = first + generated["num_keyframes"]
                local_start = max(first, video_start)
                local_end = min(last, video_end)
                if local_start < local_end:
                    cond["generated_keyframes"] = {
                        **generated,
                        "first_latent_frame": local_start - video_start,
                        "num_keyframes": local_end - local_start,
                        "tokens_per_frame": tokens_per_frame,
                    }
                else:
                    cond.pop("generated_keyframes", None)
            entries.append(cond)
        chunk_conds[name] = entries
    return chunk_conds


def _conditioning_for_chunk_with_reference(original_conds, video_start, video_end, tokens_per_frame, reference_video):
    """裁剪条件到当前分块的时间范围，并用上一块的尾帧更新 I2V 参考"""
    chunk_conds = {}
    for name, conditioning in original_conds.items():
        entries = []
        for cond in conditioning:
            cond = cond.copy()
            cond.pop("keyframe_idxs", None)
            cond.pop("guide_attention_entries", None)
            generated = cond.get("generated_keyframes")
            if generated is not None:
                first = generated["first_latent_frame"]
                last = first + generated["num_keyframes"]
                local_start = max(first, video_start)
                local_end = min(last, video_end)
                if local_start < local_end:
                    cond["generated_keyframes"] = {
                        **generated,
                        "first_latent_frame": local_start - video_start,
                        "num_keyframes": local_end - local_start,
                        "tokens_per_frame": tokens_per_frame,
                    }
                else:
                    cond.pop("generated_keyframes", None)

            # Handle concat_latent_image for I2V continuity
            concat_image = cond.get("concat_latent_image")
            concat_mask = cond.get("concat_mask")
            if torch.is_tensor(concat_image) and concat_image.ndim == 5 and concat_image.shape[2] >= video_end:
                chunk_image = concat_image[:, :, video_start:video_end].clone()
                # 替换 position 0 为参考帧（上一块的尾帧）
                if video_start > 0 and reference_video is not None:
                    # 取参考帧的 latent 表示（通常是第一个通道）
                    ref_frame = reference_video[:, :16, -1:] if reference_video.shape[1] >= 16 else reference_video[:, :, -1:]
                    chunk_image[:, :, :1] = ref_frame.to(chunk_image)
                cond["concat_latent_image"] = chunk_image
            if torch.is_tensor(concat_mask) and concat_mask.ndim == 5 and concat_mask.shape[2] >= video_end:
                chunk_mask = concat_mask[:, :, video_start:video_end].clone()
                if video_start > 0:
                    chunk_mask[:, :, :1] = 0
                cond["concat_mask"] = chunk_mask

            entries.append(cond)
        chunk_conds[name] = entries
    return chunk_conds


class _PreparedGuiderSession:
    def __init__(self, guider, sampler, sigmas, representative_noise, representative_conds):
        self.guider = guider
        self.sampler = sampler
        self.sigmas = sigmas
        self.representative_noise = representative_noise
        self.representative_conds = representative_conds
        self.original_model_options = guider.model_options
        self.original_hook_mode = guider.model_patcher.hook_mode
        self.multigpu_patchers = []
        self.device_context = None

    @staticmethod
    def _pack(samples):
        if samples.is_nested:
            streams = samples.unbind()
            packed, shapes = comfy.utils.pack_latents(streams)
            return packed, shapes
        return samples, [samples.shape]

    @staticmethod
    def _pack_mask(mask, shapes, device):
        if mask is None:
            return None
        masks = list(mask.unbind()) if mask.is_nested else [mask]
        masks = masks[:len(shapes)]
        for index in range(len(masks), len(shapes)):
            masks.append(torch.ones(shapes[index]))
        masks = [comfy.sampler_helpers.prepare_mask(item, shape, device) for item, shape in zip(masks, shapes)]
        packed = comfy.utils.pack_latents(masks)[0] if len(masks) > 1 else masks[0]
        return packed.float()

    def __enter__(self):
        packed_noise, _ = self._pack(self.representative_noise)
        self.guider.conds = _copy_conds(self.representative_conds)
        comfy.samplers.preprocess_conds_hooks(self.guider.conds)
        self.guider.model_options = comfy.model_patcher.create_model_options_clone(self.original_model_options)
        if comfy.samplers.get_total_hook_groups_in_conds(self.guider.conds) <= 1:
            self.guider.model_patcher.hook_mode = comfy.hooks.EnumHookMode.MinVram
        comfy.sampler_helpers.prepare_model_patcher(self.guider.model_patcher, self.guider.conds, self.guider.model_options)
        comfy.samplers.filter_registered_hooks_on_conds(self.guider.conds, self.guider.model_options)
        self.guider.inner_model, self.guider.conds, self.guider.loaded_models = comfy.sampler_helpers.prepare_sampling(
            self.guider.model_patcher, packed_noise.shape, self.guider.conds, self.guider.model_options
        )
        self.device = self.guider.model_patcher.load_device
        self.multigpu_patchers = comfy.sampler_helpers.prepare_model_patcher_multigpu_clones(
            self.guider.model_patcher, self.guider.loaded_models, self.guider.model_options
        )
        if self.multigpu_patchers:
            devices = [self.device] + [patcher.load_device for patcher in self.multigpu_patchers]
            self.guider.model_options["multigpu_thread_pool"] = comfy.multigpu.MultiGPUThreadPool(devices)
        self.device_context = comfy.model_management.cuda_device_context(self.device)
        self.device_context.__enter__()
        comfy.samplers.cast_to_load_options(
            self.guider.model_options, device=self.device, dtype=self.guider.model_patcher.model_dtype()
        )
        self.guider.model_patcher.pre_run()
        for patcher in self.multigpu_patchers:
            patcher.pre_run()
        return self

    def sample(self, chunk_noise, chunk_latent, noise_mask, chunk_conds, seed):
        packed_noise, shapes = self._pack(chunk_noise)
        packed_latent, _ = self._pack(chunk_latent)
        packed_mask = self._pack_mask(noise_mask, shapes, self.device)
        self.guider.conds = _copy_conds(chunk_conds)
        comfy.samplers.preprocess_conds_hooks(self.guider.conds)
        comfy.samplers.filter_registered_hooks_on_conds(self.guider.conds, self.guider.model_options)

        x0_output = {}
        callback = latent_preview.prepare_callback(self.guider.model_patcher, self.sigmas.shape[-1] - 1, x0_output)
        if len(shapes) > 1 and callback is not None:
            packed_callback = callback
            def callback(step, x0, x, total_steps):
                x0 = comfy.nested_tensor.NestedTensor(comfy.utils.unpack_latents(x0, shapes))
                x = comfy.nested_tensor.NestedTensor(comfy.utils.unpack_latents(x, shapes))
                return packed_callback(step, x0, x, total_steps)

        packed_noise = packed_noise.to(device=self.device, dtype=torch.float32)
        packed_latent = packed_latent.to(device=self.device, dtype=torch.float32)
        sigmas = self.sigmas.to(self.device)
        output = self.guider.inner_sample(
            packed_noise, packed_latent, self.device, self.sampler, sigmas, packed_mask,
            callback, not comfy.utils.PROGRESS_BAR_ENABLED, seed, latent_shapes=shapes
        )
        streams = comfy.utils.unpack_latents(output, shapes) if len(shapes) > 1 else [output]
        samples = comfy.nested_tensor.NestedTensor(streams) if len(shapes) > 1 else streams[0]

        x0 = x0_output.get("x0")
        if x0 is None:
            denoised = samples
        else:
            if len(shapes) > 1 and not x0.is_nested:
                x0 = comfy.nested_tensor.NestedTensor(comfy.utils.unpack_latents(x0, shapes))
            denoised = self.guider.model_patcher.model.process_latent_out(x0.cpu())
        return samples, denoised

    def __exit__(self, exc_type, exc_value, traceback):
        pool = self.guider.model_options.pop("multigpu_thread_pool", None)
        if pool is not None:
            pool.shutdown()
        self.guider.model_patcher.cleanup()
        for patcher in self.multigpu_patchers:
            patcher.cleanup()
        comfy.sampler_helpers.cleanup_models(self.guider.conds, self.guider.loaded_models)
        comfy.samplers.cast_to_load_options(self.guider.model_options, device=self.guider.model_patcher.offload_device)
        self.guider.model_options = self.original_model_options
        self.guider.model_patcher.hook_mode = self.original_hook_mode
        self.guider.model_patcher.restore_hook_patches()
        if self.device_context is not None:
            self.device_context.__exit__(exc_type, exc_value, traceback)
        for attribute in ("conds", "inner_model", "loaded_models"):
            if hasattr(self.guider, attribute):
                delattr(self.guider, attribute)


# ============================================================================
# 主节点: LTX Video 分块采样器
# ============================================================================

class LTXVUnlimitedSampler:
    """
    LTX Video AV 联合分块采样器
    
    支持:
    - NestedTensor AV 联合 latent
    - 分块处理长视频
    - 视频和音频的连续引导
    - 渐进式解码（边采样边解码，降低峰值显存）
    """
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "noise": ("NOISE", {"tooltip": "噪声生成器"}),
                "guider": ("GUIDER", {"tooltip": "引导器"}),
                "sampler": ("SAMPLER", {"tooltip": "采样器"}),
                "sigmas": ("SIGMAS", {"tooltip": "噪声调度"}),
                "latent_image": ("LATENT", {"tooltip": "输入 latent (支持 AV 联合 NestedTensor)"}),
            },
            "optional": {
                "vae": ("VAE", {"tooltip": "LTX Video VAE（128 通道），不是 LTX Audio VAE"}),
                "chunk_frames": ("INT", {
                    "default": 9,
                    "min": 9,
                    "max": 513,
                    "step": 1,
                    "tooltip": "每块最大像素帧数；后端自动向下对齐为 8n+1，最低 9 帧"
                }),
                "progressive_decode": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "采样完成后使用 tiled VAE 解码到 CPU；必须连接 vae 输入"
                }),
                "vae_tile_size": ("INT", {
                    "default": 128,
                    "min": 128,
                    "max": 1024,
                    "step": 32,
                    "tooltip": "VAE 空间瓦片像素尺寸；显存不足时降低"
                }),
                "vae_temporal_size": ("INT", {
                    "default": 2,
                    "min": 2,
                    "max": 64,
                    "step": 1,
                    "tooltip": "VAE 每次解码的 latent 时间步数；显存不足时使用 2"
                }),
                "debug": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "打印调试信息"
                }),
            },
        }
    
    RETURN_TYPES = ("LATENT", "LATENT", "IMAGE", "STRING")
    RETURN_NAMES = ("output", "denoised_output", "progressive_images", "chunk_info")
    FUNCTION = "execute"
    CATEGORY = "video/split"
    
    def execute(
        self,
        noise,
        guider,
        sampler,
        sigmas,
        latent_image,
        vae=None,
        chunk_frames=9,
        progressive_decode=False,
        vae_tile_size=128,
        vae_temporal_size=2,
        debug=False,
    ) -> tuple:
        """执行 AV 联合分块采样"""
        if progressive_decode and vae is None:
            raise ValueError("progressive_decode requires the LTX Video VAE connected to the vae input")

        if debug:
            logging.info("=" * 60)
            logging.info("LTXVUnlimitedSampler 开始执行 (AV 联合)")
            logging.info(f"progressive_decode: {progressive_decode}")
            logging.info("=" * 60)
        
        samples = latent_image["samples"]
        
        # 检查是否是 NestedTensor (AV 联合)
        is_av_latent = hasattr(samples, 'is_nested') and samples.is_nested
        
        if is_av_latent:
            # AV 联合 latent - 获取 video 和 audio
            streams = samples.unbind()
            if len(streams) != 2:
                raise ValueError(f"LTX AV latent expected 2 streams (video, audio), got {len(streams)}")
            video, audio = streams
            if audio.shape[2] == 0:
                raise ValueError("LTX AV audio latent has no time steps. Use the video-only latent for video redraw, or provide a non-empty LTX Audio latent.")
        else:
            # 纯视频 latent
            video = samples
            audio = None

        if progressive_decode and (vae.latent_dim != 3 or vae.latent_channels != video.shape[1]):
            raise ValueError(
                f"progressive_decode requires an LTX Video VAE for {video.shape[1]}-channel video latents; "
                f"the connected VAE accepts {vae.latent_channels} channels with latent_dim={vae.latent_dim}. "
                "Do not connect the LTX Audio VAE."
            )
        
        # 获取形状
        video_t = video.shape[2]
        audio_t = audio.shape[2] if audio is not None else 0
        
        if debug:
            logging.info(f"Video latent: {video.shape}")
            if audio is not None:
                logging.info(f"Audio latent: {audio.shape}")
        
        chunks = _chunk_plan(video_t, audio_t, chunk_frames)
        
        if debug:
            logging.info(f"分块数量: {len(chunks)}")
            for chunk in chunks:
                logging.info(f"  Chunk {chunk.chunk_index}: video [{chunk.video_start}, {chunk.video_end}), "
                           f"audio [{chunk.audio_start}, {chunk.audio_end})")
        
        # 修复空 latent 通道
        fixed_latent = latent_image.copy()
        fixed_latent["samples"] = comfy.sample.fix_empty_latent_channels(
            guider.model_patcher,
            samples,
            latent_image.get("downscale_ratio_spacial"),
            latent_image.get("downscale_ratio_temporal"),
        )
        samples = fixed_latent["samples"]
        
        # 如果是 AV latent，重新获取分离的流
        if hasattr(samples, 'is_nested') and samples.is_nested:
            streams = samples.unbind()
            video, audio = streams
            if audio.shape[2] == 0:
                raise ValueError(
                    "LTX AV audio latent has no time steps after latent preparation. "
                    "Set LTXV Empty Latent Audio.frames_number to the segment length (161 by default), not 0."
                )
        
        # Noise is generated on CPU by ComfyUI. Keeping the full deterministic noise on
        # CPU preserves the standard seed sequence without increasing peak VRAM.
        full_noise = noise.generate_noise(fixed_latent)
        if hasattr(full_noise, 'is_nested') and full_noise.is_nested:
            video_noise, audio_noise = full_noise.unbind()
        else:
            video_noise = full_noise
            audio_noise = None
        
        input_mask = latent_image.get("noise_mask")
        if input_mask is not None and hasattr(input_mask, "is_nested") and input_mask.is_nested:
            mask_streams = input_mask.unbind()
            input_video_mask = mask_streams[0]
            input_audio_mask = mask_streams[1] if len(mask_streams) > 1 else None
        else:
            input_video_mask = input_mask
            input_audio_mask = None

        original_conds = guider.original_conds

        # 收集输出
        output_video = []
        output_audio = []
        denoised_video = []
        denoised_audio = []
        previous_video = None
        previous_audio = None
        chunk_infos = []
        
        # 开始预览执行
        preview_execution = begin_preview_execution(guider.model_patcher, len(chunks))
        representative = max(chunks, key=lambda item: (item.video_end - item.video_start) * video[0, 0, 0].numel() + (item.audio_end - item.audio_start) * (0 if audio is None else audio[0, 0, 0].numel()))
        representative_video_noise = video_noise[:, :, representative.video_start:representative.video_end]
        representative_conds = _conditioning_for_chunk(
            original_conds,
            representative.video_start,
            representative.video_end,
            video.shape[3] * video.shape[4],
        )
        if is_av_latent:
            representative_audio_noise = audio_noise[:, :, representative.audio_start:representative.audio_end]
            representative_noise = comfy.nested_tensor.NestedTensor((representative_video_noise, representative_audio_noise))
        else:
            representative_noise = representative_video_noise
        prepared = _PreparedGuiderSession(guider, sampler, sigmas, representative_noise, representative_conds)
        prepared_entered = False
        cuda_stats = torch.cuda.is_available()
        sampling_peak_allocated = 0
        sampling_peak_reserved = 0
        if cuda_stats:
            torch.cuda.reset_peak_memory_stats()

        try:
            prepared.__enter__()
            prepared_entered = True
            if cuda_stats:
                prepare_peak_allocated = torch.cuda.max_memory_allocated()
                prepare_peak_reserved = torch.cuda.max_memory_reserved()
                sampling_peak_allocated = prepare_peak_allocated
                sampling_peak_reserved = prepare_peak_reserved
                if debug:
                    logging.info(
                        "CUDA model preparation peak: allocated=%.2f GiB reserved=%.2f GiB",
                        prepare_peak_allocated / 1024 ** 3,
                        prepare_peak_reserved / 1024 ** 3,
                    )
            for chunk_idx, chunk in enumerate(chunks):
                if cuda_stats:
                    torch.cuda.reset_peak_memory_stats()
                if debug:
                    logging.info(f"\n处理 Chunk {chunk_idx + 1}/{len(chunks)}")
                    if torch.cuda.is_available():
                        logging.info(
                            "CUDA before chunk: allocated=%.2f GiB reserved=%.2f GiB",
                            torch.cuda.memory_allocated() / 1024 ** 3,
                            torch.cuda.memory_reserved() / 1024 ** 3,
                        )
                
                # 准备分块 latent
                vs, ve = chunk.video_start, chunk.video_end
                aus, aue = chunk.audio_start, chunk.audio_end
                
                chunk_video = video[:, :, vs:ve].clone()
                chunk_video_noise = video_noise[:, :, vs:ve].clone()
                video_mask = _slice_mask(input_video_mask, vs, ve, video)
                if not chunk.is_first:
                    video_context = previous_video[:, :, -chunk.overlap_video_steps:].to(chunk_video)
                    chunk_video[:, :, :chunk.overlap_video_steps] = video_context
                    chunk_video_noise[:, :, :chunk.overlap_video_steps] = 0
                    video_mask[:, :, :chunk.overlap_video_steps] = 0

                if is_av_latent:
                    chunk_audio = audio[:, :, aus:aue].clone()
                    chunk_audio_noise = audio_noise[:, :, aus:aue].clone()
                    audio_mask = _slice_mask(input_audio_mask, aus, aue, audio)
                    if not chunk.is_first and chunk.context_audio_steps:
                        audio_context = previous_audio[:, :, -chunk.context_audio_steps:].to(chunk_audio)
                        chunk_audio[:, :, :chunk.context_audio_steps] = audio_context
                        chunk_audio_noise[:, :, :chunk.context_audio_steps] = 0
                        audio_mask[:, :, :chunk.context_audio_steps] = 0
                    chunk_latent = comfy.nested_tensor.NestedTensor((chunk_video, chunk_audio))
                    chunk_noise = comfy.nested_tensor.NestedTensor((chunk_video_noise, chunk_audio_noise))
                    noise_mask = comfy.nested_tensor.NestedTensor((video_mask, audio_mask))
                else:
                    chunk_latent = chunk_video
                    chunk_noise = chunk_video_noise
                    noise_mask = video_mask

                # 设置预览分块
                if preview_execution is not None:
                    preview_execution.set_chunk(
                        chunk_idx,
                        chunk.frame_start,
                        chunk.frame_end - 1,
                        chunk.frame_start + (8 if not chunk.is_first else 0),
                        chunk.frame_end - 1,
                        0 if chunk.is_first else chunk.overlap_video_steps,
                    )
                
                # 后续段落需要传入参考帧更新条件
                if chunk.is_first:
                    chunk_conds = _conditioning_for_chunk(
                        original_conds,
                        vs,
                        ve,
                        chunk_video.shape[3] * chunk_video.shape[4],
                    )
                else:
                    # 传入上一块的尾帧作为参考
                    ref_video = previous_video if previous_video is not None else None
                    chunk_conds = _conditioning_for_chunk_with_reference(
                        original_conds,
                        vs,
                        ve,
                        chunk_video.shape[3] * chunk_video.shape[4],
                        ref_video,
                    )

                try:
                    sampled, denoised = prepared.sample(
                        chunk_noise,
                        chunk_latent,
                        noise_mask,
                        chunk_conds,
                        (noise.seed + chunk_idx) & 0xffffffffffffffff,
                    )
                finally:
                    if preview_execution is not None:
                        preview_execution.clear_chunk()

                if is_av_latent:
                    out_video, out_audio = sampled.unbind()
                    den_video, den_audio = denoised.unbind()
                else:
                    out_video = sampled
                    out_audio = None
                    den_video = denoised
                    den_audio = None
                
                video_trim = 0 if chunk.is_first else chunk.overlap_video_steps
                audio_trim = 0 if chunk.is_first else chunk.context_audio_steps
                previous_video = out_video[:, :, -max(1, chunk.overlap_video_steps):].detach().cpu()
                previous_audio = None if out_audio is None else out_audio[:, :, -max(1, chunk.context_audio_steps):].detach().cpu()

                output_video.append(out_video[:, :, video_trim:].detach().cpu())
                if out_audio is not None:
                    output_audio.append(out_audio[:, :, audio_trim:].detach().cpu())
                denoised_video.append(den_video[:, :, video_trim:].detach().cpu())
                if den_audio is not None:
                    denoised_audio.append(den_audio[:, :, audio_trim:].detach().cpu())
                
                chunk_info = f"Chunk {chunk_idx + 1}/{len(chunks)}: " \
                           f"video [{chunk.video_start}, {chunk.video_end}), " \
                           f"audio [{chunk.audio_start}, {chunk.audio_end})"
                chunk_infos.append(chunk_info)
                
                del sampled, denoised, out_video, den_video, chunk_latent, chunk_noise, noise_mask
                if is_av_latent:
                    del out_audio, den_audio, chunk_audio, chunk_audio_noise, audio_mask
                del chunk_video, chunk_video_noise, video_mask

                if cuda_stats:
                    chunk_peak_allocated = torch.cuda.max_memory_allocated()
                    chunk_peak_reserved = torch.cuda.max_memory_reserved()
                    sampling_peak_allocated = max(sampling_peak_allocated, chunk_peak_allocated)
                    sampling_peak_reserved = max(sampling_peak_reserved, chunk_peak_reserved)
                if debug:
                    logging.info(f"  已完成并转移 Chunk {chunk_idx + 1} 到 CPU")
                    if cuda_stats:
                        logging.info(
                            "CUDA chunk peak: allocated=%.2f GiB reserved=%.2f GiB; after: allocated=%.2f GiB reserved=%.2f GiB",
                            chunk_peak_allocated / 1024 ** 3,
                            chunk_peak_reserved / 1024 ** 3,
                            torch.cuda.memory_allocated() / 1024 ** 3,
                            torch.cuda.memory_reserved() / 1024 ** 3,
                        )
        
        finally:
            if prepared_entered:
                prepared.__exit__(None, None, None)
            guider.original_conds = original_conds
            if preview_execution is not None:
                preview_execution.close()
        
        if cuda_stats:
            sampling_summary = (
                f"Sampling CUDA peak: allocated={sampling_peak_allocated / 1024 ** 3:.2f} GiB, "
                f"reserved={sampling_peak_reserved / 1024 ** 3:.2f} GiB"
            )
            chunk_infos.append(sampling_summary)
            logging.info(sampling_summary)

        # 组装最终输出
        final_video = torch.cat(output_video, dim=2)
        if is_av_latent and output_audio:
            final_audio = torch.cat(output_audio, dim=2)
            final_output_samples = comfy.nested_tensor.NestedTensor((final_video, final_audio))
            final_denoised_samples = comfy.nested_tensor.NestedTensor((
                torch.cat(denoised_video, dim=2),
                torch.cat(denoised_audio, dim=2),
            ))
        else:
            final_output_samples = final_video
            final_denoised_samples = torch.cat(denoised_video, dim=2)
        
        # 构建输出字典
        final_output = {"samples": final_output_samples}
        final_denoised = {"samples": final_denoised_samples}
        
        if "batch_index" in latent_image:
            final_output["batch_index"] = latent_image["batch_index"]
            final_denoised["batch_index"] = latent_image["batch_index"]
        
        if debug:
            logging.info(f"\n最终输出形状: {final_output_samples.shape}")
            logging.info("=" * 60)
        
        if progressive_decode and vae is not None:
            # Sampling is complete and all retained latents are on CPU. Explicitly unload
            # LTXAV before loading the VideoVAE; normal guider cleanup leaves the model in
            # ComfyUI's loaded-model pool for reuse, which makes the two models compete for VRAM.
            comfy.model_management.unload_model_and_clones(guider.model_patcher, all_devices=True)
            comfy.model_management.soft_empty_cache()
            if cuda_stats:
                logging.info(
                    "CUDA before VAE load: allocated=%.2f GiB reserved=%.2f GiB",
                    torch.cuda.memory_allocated() / 1024 ** 3,
                    torch.cuda.memory_reserved() / 1024 ** 3,
                )
                torch.cuda.reset_peak_memory_stats()
            compression = vae.spacial_compression_decode()
            tile = max(1, vae_tile_size // compression)
            overlap = min(tile - 1, max(1, min(64, vae_tile_size // 4) // compression))
            decode_video = final_denoised_samples.unbind()[0] if is_av_latent else final_denoised_samples
            original_vae_output_device = vae.output_device
            try:
                # decode_tiled accumulates the complete decoded video on output_device.
                # Force that accumulator to CPU so only the VAE model and current tile use VRAM.
                vae.output_device = torch.device("cpu")
                progressive_images = vae.decode_tiled(
                    decode_video,
                    tile_x=tile,
                    tile_y=tile,
                    overlap=overlap,
                    tile_t=vae_temporal_size,
                    overlap_t=1,
                )
            finally:
                vae.output_device = original_vae_output_device
            if progressive_images.ndim == 5:
                progressive_images = progressive_images.flatten(0, 1)
            progressive_images = progressive_images.detach().cpu()
            if cuda_stats:
                vae_summary = (
                    f"VAE CUDA peak: allocated={torch.cuda.max_memory_allocated() / 1024 ** 3:.2f} GiB, "
                    f"reserved={torch.cuda.max_memory_reserved() / 1024 ** 3:.2f} GiB"
                )
                chunk_infos.append(vae_summary)
                logging.info(vae_summary)
        else:
            progressive_images = torch.zeros(1, 256, 256, 3, device="cpu")
        
        return (final_output, final_denoised, progressive_images, "\n".join(chunk_infos))
    
    sample = execute


# ============================================================================
# 辅助函数
# ============================================================================

def get_chunk_preview_frames(
    total_frames: int,
    chunk_frames: int,
    overlap_frames: int = 8,
) -> list[tuple[int, int, int]]:
    """计算预览用的帧索引范围"""
    try:
        video_t = pixel_frames_to_latent_steps(total_frames)
        # 估算 audio_t (需要从实际 latent 获取，这里用比例估算)
        chunks = _chunk_plan(video_t, video_t, chunk_frames)
        return [(c.chunk_index, c.frame_start, c.frame_end) for c in chunks]
    except ValueError:
        return [(0, 0, total_frames)]


# ============================================================================
# 预览节点
# ============================================================================

from comfy_api.latest import io
import folder_paths


class LTXVUnlimitedPreview(io.ComfyNode):
    """LTX Video Unlimited Preview - 实时预览节点"""
    
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="LTXVUnlimitedPreview",
            display_name="LTX Video Unlimited Preview",
            category="video/split",
            description="在分块采样过程中实时预览 LTX Video 输出。",
            inputs=[
                io.Model.Input("model"),
                io.Int.Input("max_resolution", default=512, min=64, max=2048, step=64),
                io.Int.Input("quality", default=75, min=30, max=100, step=1),
                io.Float.Input("fps", default=24.0, min=1.0, max=60.0, step=0.001),
                io.Int.Input("frame_stride", default=1, min=1, max=16, step=1),
                io.Combo.Input("tiny_vae", 
                             options=["none"] + folder_paths.get_filename_list("vae_approx"), 
                             default="none"),
            ],
            outputs=[io.Model.Output()],
            hidden=[io.Hidden.unique_id],
            is_experimental=True,
        )
    
    @classmethod
    def execute(cls, model, max_resolution, quality, fps, frame_stride, tiny_vae="none"):
        from .preview import _AccumulatedPreviewWrapper, PREVIEW_WRAPPER_KEY
        
        patched = model.clone()
        patched.add_wrapper_with_key(
            comfy.patcher_extension.WrappersMP.OUTER_SAMPLE,
            PREVIEW_WRAPPER_KEY,
            _AccumulatedPreviewWrapper(cls.hidden.unique_id, max_resolution, quality, fps, frame_stride, tiny_vae),
        )
        return io.NodeOutput(patched)


# ============================================================================
# 节点映射
# ============================================================================

LTXV_NODE_CLASS_MAPPINGS = {
    "LTXVUnlimitedSampler": LTXVUnlimitedSampler,
    "LTXVUnlimitedPreview": LTXVUnlimitedPreview,
}

LTXV_NODE_DISPLAY_NAME_MAPPINGS = {
    "LTXVUnlimitedSampler": "LTX Video Sampler Unlimited",
    "LTXVUnlimitedPreview": "LTX Video Unlimited Preview",
}
