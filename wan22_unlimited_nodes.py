"""
Wan22UnlimitedSampler - Wan 2.2 / Bernini 分块采样器

基于 MiniMax H3 Unlimited 架构设计，针对 Wan22 latent 格式优化。

Wan22 关键参数:
- 空间压缩比: 16
- 时间压缩比: 4
- Latent 通道: 48
- 帧结构: 1 + 4*N (每组 4 帧)
- TAESD: lighttaew2_2

与 LTX 的主要区别:
- 帧结构: 8n+1 (LTX) vs 1+4N (Wan22)
- Latent 通道: 128 (LTX) vs 48 (Wan22)
- 无 AV 联合采样，纯视频
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
import latent_preview

from .preview import begin_preview_execution


# ============================================================================
# Wan22 帧结构常量
# ============================================================================

# Wan22 帧结构: 像素帧数 = 1 + 4 * N
# 每编码组 = 4 帧
# 时间压缩比 = 4 (每个 latent 步 = 4 像素帧)


def pixel_frames_to_latent_steps(pixel_frames: int) -> int:
    """将像素帧数转换为 latent 步数 (Wan22 1+4N 模式)"""
    if pixel_frames < 1:
        raise ValueError(f"Wan22 minimum is 1 pixel frame, got {pixel_frames}")
    if pixel_frames == 1:
        return 1
    # N = (pixel_frames - 1) // 4
    # latent_steps = 1 + N
    return 1 + (pixel_frames - 1) // 4


def latent_steps_to_pixel_frames(latent_steps: int) -> int:
    """将 latent 步数转换为像素帧数"""
    if latent_steps < 1:
        raise ValueError(f"Latent steps must be at least 1, got {latent_steps}")
    if latent_steps == 1:
        return 1
    return 1 + (latent_steps - 1) * 4


def align_pixel_frames_to_chunk(pixel_frames: int) -> int:
    """将像素帧数对齐到 Wan22 的 1+4N 约束"""
    if pixel_frames <= 1:
        return 1
    return 1 + ((pixel_frames - 1) // 4) * 4


# ============================================================================
# 分块规划
# ============================================================================

@dataclass
class ChunkPlan:
    """单个分块的规划信息"""
    chunk_index: int
    video_start: int       # latent 步级别起始
    video_end: int         # latent 步级别结束
    frame_start: int       # 像素帧级别起始
    frame_end: int         # 像素帧级别结束
    is_first: bool
    overlap_steps: int     # 重叠 latent 步数
    overlap_frames: int    # 重叠像素帧数


def _chunk_plan(video_t: int, chunk_frames: int, overlap_frames: int = 8) -> list[ChunkPlan]:
    """
    为 Wan22 视频规划分块

    Args:
        video_t: 视频总 latent 步数
        chunk_frames: 每块最大像素帧数 (用户参数)
        overlap_frames: 重叠像素帧数 (默认 8 帧 = 2 latent 步)

    Returns:
        分块规划列表
    """
    if video_t < 1:
        raise ValueError(f"Wan22 video latent must have at least 1 step, got {video_t}")

    # 对齐到 Wan22 约束
    max_chunk_frames = align_pixel_frames_to_chunk(chunk_frames)
    # 转换: 像素帧 → latent 步
    max_chunk_t = pixel_frames_to_latent_steps(max_chunk_frames)

    if overlap_frames < 0:
        raise ValueError(f"overlap_frames must be >= 0, got {overlap_frames}")
    # Overlap is a count of shared pixel frames, not a 1+4N video length.
    # Keep zero as zero and align positive values down to latent steps.
    overlap_t = min(overlap_frames // 4, max_chunk_t - 1)
    effective_overlap_frames = overlap_t * 4

    if max_chunk_t < 2:
        raise ValueError(
            f"Chunk too small: max_chunk_frames={max_chunk_frames} -> max_chunk_t={max_chunk_t}. "
            "Increase chunk_frames to at least 5."
        )

    plan = []
    video_end = 0
    while video_end < video_t:
        video_start = 0 if not plan else video_end - overlap_t
        next_video_end = min(video_start + max_chunk_t, video_t)

        frame_start = 0 if not plan else latent_steps_to_pixel_frames(video_start)
        frame_end = latent_steps_to_pixel_frames(next_video_end)

        plan.append(ChunkPlan(
            chunk_index=len(plan),
            video_start=video_start,
            video_end=next_video_end,
            frame_start=frame_start,
            frame_end=frame_end,
            is_first=not plan,
            overlap_steps=0 if not plan else overlap_t,
            overlap_frames=0 if not plan else effective_overlap_frames,
        ))
        video_end = next_video_end

    return plan


# ============================================================================
# 工具函数
# ============================================================================

def _slice_mask(mask, start, end, reference):
    if mask is None:
        return torch.ones_like(reference[:, :1, start:end])
    mask = comfy.utils.reshape_mask(mask, reference.shape)
    return mask[:, :1, start:end].clone()


def _copy_conds(conds):
    return {name: [cond.copy() for cond in values] for name, values in conds.items()}


def _conditioning_for_chunk(original_conds, video_start, video_end, tokens_per_frame):
    """裁剪条件到当前分块的时间范围"""
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
            entries.append(cond)
        chunk_conds[name] = entries
    return chunk_conds


# ============================================================================
# Guider 会话管理
# ============================================================================

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
# 主节点: Wan22 / Bernini 分块采样器
# ============================================================================

class Wan22UnlimitedSampler:
    """
    Wan 2.2 / Bernini 分块采样器

    支持:
    - Wan 2.2 latent 格式 (48 通道, 16× 空间压缩, 4× 时间压缩)
    - Bernini (使用相同的 Wan22 latent 格式)
    - 分块处理长视频，降低峰值显存
    - 重叠引导机制，消除分块接缝
    - 渐进式解码 (可选)
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "noise": ("NOISE", {"tooltip": "噪声生成器"}),
                "guider": ("GUIDER", {"tooltip": "引导器"}),
                "sampler": ("SAMPLER", {"tooltip": "采样器"}),
                "sigmas": ("SIGMAS", {"tooltip": "噪声调度"}),
                "latent_image": ("LATENT", {"tooltip": "输入 latent"}),
            },
            "optional": {
                "vae": ("VAE", {"tooltip": "Wan22 VAE (lighttaew2_2)，用于渐进式解码"}),
                "chunk_frames": ("INT", {
                    "default": 128,
                    "min": 5,
                    "max": 1024,
                    "step": 4,
                    "tooltip": "每块最大像素帧数；内部对齐到 1+4N，最低 5 帧。建议 720p 用 128，540p 用 256"
                }),
                "overlap_frames": ("INT", {
                    "default": 8,
                    "min": 0,
                    "max": 256,
                    "step": 4,
                    "tooltip": "重叠像素帧数（引导前一块的末帧），默认 8 帧 (2 latent 步)；设为 0 禁用重叠"
                }),
                "progressive_decode": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "采样完成后使用 tiled VAE 解码到 CPU；必须连接 vae 输入"
                }),
                "vae_tile_size": ("INT", {
                    "default": 256,
                    "min": 128,
                    "max": 1024,
                    "step": 32,
                    "tooltip": "VAE 空间瓦片像素尺寸；显存不足时降低"
                }),
                "vae_temporal_size": ("INT", {
                    "default": 4,
                    "min": 1,
                    "max": 64,
                    "step": 1,
                    "tooltip": "VAE 每次解码的 latent 时间步数；显存不足时降低"
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
        chunk_frames=128,
        overlap_frames=8,
        progressive_decode=False,
        vae_tile_size=256,
        vae_temporal_size=4,
        debug=False,
    ) -> tuple:
        if progressive_decode and vae is None:
            raise ValueError("progressive_decode requires the Wan22 VAE connected to the vae input")

        if debug:
            logging.info("=" * 60)
            logging.info("Wan22UnlimitedSampler 开始执行")
            logging.info(f"chunk_frames={chunk_frames}, overlap_frames={overlap_frames}")
            logging.info(f"progressive_decode={progressive_decode}")
            logging.info("=" * 60)

        samples = latent_image["samples"]

        # 处理 NestedTensor (理论上 Wan22 不使用，但保持兼容)
        is_nested = hasattr(samples, 'is_nested') and samples.is_nested
        if is_nested:
            streams = samples.unbind()
            video = streams[0]
            if debug:
                logging.info(f"NestedTensor detected: {len(streams)} streams")
        else:
            video = samples

        video_t = video.shape[2]
        if debug:
            logging.info(f"Video latent shape: {tuple(video.shape)}")
            logging.info(f"Video latent steps: {video_t}")

        # Chunk length uses the 1+4N grid. Zero overlap remains disabled.
        chunk_frames = max(5, align_pixel_frames_to_chunk(chunk_frames))
        overlap_frames = min(overlap_frames, chunk_frames - 5)

        chunks = _chunk_plan(video_t, chunk_frames, overlap_frames)
        if debug:
            logging.info(f"分块数量: {len(chunks)}")
            for chunk in chunks:
                logging.info(
                    f"  Chunk {chunk.chunk_index}: "
                    f"latent [{chunk.video_start}, {chunk.video_end}), "
                    f"frames [{chunk.frame_start}, {chunk.frame_end}), "
                    f"overlap={chunk.overlap_frames}f"
                )

        # 修复空 latent 通道
        fixed_latent = latent_image.copy()
        fixed_latent["samples"] = comfy.sample.fix_empty_latent_channels(
            guider.model_patcher,
            samples,
            latent_image.get("downscale_ratio_spacial"),
            latent_image.get("downscale_ratio_temporal"),
        )
        samples = fixed_latent["samples"]

        if hasattr(samples, 'is_nested') and samples.is_nested:
            streams = samples.unbind()
            video = streams[0]

        full_noise = noise.generate_noise(fixed_latent)
        if hasattr(full_noise, 'is_nested') and full_noise.is_nested:
            video_noise = full_noise.unbind()[0]
        else:
            video_noise = full_noise

        input_mask = latent_image.get("noise_mask")
        if input_mask is not None and hasattr(input_mask, "is_nested") and input_mask.is_nested:
            input_mask = input_mask.unbind()[0]

        original_conds = guider.original_conds

        # 收集输出
        output_video = []
        denoised_video = []
        previous_video = None
        chunk_infos = []

        # 开始预览
        preview_execution = begin_preview_execution(guider.model_patcher, len(chunks))

        # 选择最大的块作为代表性块（显存最紧张的情况）
        representative = max(
            chunks,
            key=lambda item: (item.video_end - item.video_start) * video[0, 0, 0].numel()
        )
        representative_video_noise = video_noise[:, :, representative.video_start:representative.video_end]
        representative_conds = _conditioning_for_chunk(
            original_conds,
            representative.video_start,
            representative.video_end,
            video.shape[3] * video.shape[4],
        )

        prepared = _PreparedGuiderSession(
            guider, sampler, sigmas, representative_video_noise, representative_conds
        )
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
                        "CUDA model prep peak: allocated=%.2f GiB reserved=%.2f GiB",
                        prepare_peak_allocated / 1024 ** 3,
                        prepare_peak_reserved / 1024 ** 3,
                    )

            for chunk_idx, chunk in enumerate(chunks):
                if cuda_stats:
                    torch.cuda.reset_peak_memory_stats()

                vs, ve = chunk.video_start, chunk.video_end

                # 准备分块 latent
                chunk_video = video[:, :, vs:ve].clone()
                chunk_video_noise = video_noise[:, :, vs:ve].clone()
                video_mask = _slice_mask(input_mask, vs, ve, video)

                # Reuse exactly the planned context from the previous chunk.
                if chunk.overlap_steps and previous_video is not None:
                    chunk_video[:, :, :chunk.overlap_steps] = previous_video.to(chunk_video)
                    chunk_video_noise[:, :, :chunk.overlap_steps] = 0
                    video_mask[:, :, :chunk.overlap_steps] = 0

                # 设置预览分块
                if preview_execution is not None:
                    trim_steps = chunk.overlap_steps
                    preview_execution.set_chunk(
                        chunk_idx,
                        chunk.frame_start,
                        chunk.frame_end - 1,
                        chunk.frame_start + (chunk.overlap_frames if not chunk.is_first else 0),
                        chunk.frame_end - 1,
                        trim_steps,
                    )

                chunk_conds = _conditioning_for_chunk(
                    original_conds,
                    vs,
                    ve,
                    chunk_video.shape[3] * chunk_video.shape[4],
                )

                try:
                    sampled, denoised = prepared.sample(
                        chunk_video_noise,
                        chunk_video,
                        video_mask,
                        chunk_conds,
                        (noise.seed + chunk_idx) & 0xffffffffffffffff,
                    )
                finally:
                    if preview_execution is not None:
                        preview_execution.clear_chunk()

                if sampled.is_nested or denoised.is_nested:
                    raise ValueError("Wan22UnlimitedSampler requires a single video latent stream")
                out_video = sampled
                den_video = denoised

                output_video.append(out_video[:, :, chunk.overlap_steps:].detach().cpu())
                denoised_video.append(den_video[:, :, chunk.overlap_steps:].detach().cpu())
                # Save overlap for next chunk. First chunk still needs to save overlap for chunk 2.
                if not chunk.is_first:
                    save_steps = chunk.overlap_steps
                elif overlap_frames > 0:
                    save_steps = min(overlap_frames // 4, out_video.shape[2])
                else:
                    save_steps = 0
                previous_video = out_video[:, :, -save_steps:].detach().cpu() if save_steps else None

                chunk_info = (
                    f"Chunk {chunk_idx + 1}/{len(chunks)}: "
                    f"latent [{chunk.video_start}, {chunk.video_end}), "
                    f"frames [{chunk.frame_start}, {chunk.frame_end}), "
                    f"overlap={chunk.overlap_frames}f"
                )
                chunk_infos.append(chunk_info)

                del sampled, denoised, out_video, den_video, chunk_video, chunk_video_noise, video_mask

                if cuda_stats:
                    chunk_peak_allocated = torch.cuda.max_memory_allocated()
                    chunk_peak_reserved = torch.cuda.max_memory_reserved()
                    sampling_peak_allocated = max(sampling_peak_allocated, chunk_peak_allocated)
                    sampling_peak_reserved = max(sampling_peak_reserved, chunk_peak_reserved)
                if debug:
                    logging.info(f"  完成 Chunk {chunk_idx + 1}/{len(chunks)}")
                    if cuda_stats:
                        logging.info(
                            "  CUDA chunk peak: allocated=%.2f GiB reserved=%.2f GiB",
                            torch.cuda.max_memory_allocated() / 1024 ** 3,
                            torch.cuda.max_memory_reserved() / 1024 ** 3,
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
        final_samples = torch.cat(output_video, dim=2)
        final_denoised = torch.cat(denoised_video, dim=2)

        final_output = latent_image.copy()
        final_output.pop("downscale_ratio_spacial", None)
        final_output.pop("downscale_ratio_temporal", None)
        final_output["samples"] = final_samples
        final_denoised_output = final_output.copy()
        final_denoised_output["samples"] = final_denoised

        if debug:
            logging.info(f"最终输出形状: {final_samples.shape}")

        # 渐进式解码
        if progressive_decode and vae is not None:
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
            original_vae_output_device = vae.output_device
            try:
                vae.output_device = torch.device("cpu")
                progressive_images = vae.decode_tiled(
                    final_denoised,
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

        return (final_output, final_denoised_output, progressive_images, "\n".join(chunk_infos))

    sample = execute


def _encode_video_frames(vae, frames):
    return torch.cat([vae.encode(video) for video in frames], dim=0)


def _slice_standard_conditioning(conditioning, video_start, video_end, reference_latent=None):
    sliced = []
    for cross_attn, metadata in conditioning:
        metadata = metadata.copy()
        if "audio_embed" in metadata:
            raise ValueError("Wan22 unlimited sampler does not support audio conditioning")
        for key in ("concat_latent_image", "concat_mask", "control_video", "camera_conditions", "denoise_mask", "pose_video_latent"):
            value = metadata.get(key)
            if torch.is_tensor(value) and value.ndim == 5 and value.shape[2] >= video_end:
                metadata[key] = value[:, :, video_start:video_end].clone()
        if reference_latent is not None:
            concat_image = metadata.get("concat_latent_image")
            concat_mask = metadata.get("concat_mask")
            if torch.is_tensor(concat_image) and concat_image.shape[1] == reference_latent.shape[1]:
                reference_steps = min(reference_latent.shape[2], concat_image.shape[2])
                concat_image[:, :, :reference_steps] = reference_latent[:, :, :reference_steps].to(concat_image)
                if torch.is_tensor(concat_mask):
                    concat_mask[:, :, :reference_steps] = 0
        for key in ("vace_frames", "vace_mask"):
            value = metadata.get(key)
            if value is not None:
                metadata[key] = [item[:, :, video_start:video_end].clone() if item.ndim == 5 and item.shape[2] >= video_end else item for item in value]
        sliced.append([cross_attn, metadata])
    return sliced


class _Wan22StandardUnlimitedSampler:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "model": ("MODEL",),
            "add_noise": (["enable", "disable"], {"advanced": True}),
            "noise_seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff, "control_after_generate": True}),
            "steps": ("INT", {"default": 20, "min": 1, "max": 10000}),
            "cfg": ("FLOAT", {"default": 8.0, "min": 0.0, "max": 100.0, "step": 0.1, "round": 0.01}),
            "sampler_name": (comfy.samplers.KSampler.SAMPLERS,),
            "scheduler": (comfy.samplers.KSampler.SCHEDULERS,),
            "positive": ("CONDITIONING",),
            "negative": ("CONDITIONING",),
            "latent_image": ("LATENT",),
            "start_at_step": ("INT", {"default": 0, "min": 0, "max": 10000, "advanced": True}),
            "end_at_step": ("INT", {"default": 10000, "min": 0, "max": 10000, "advanced": True}),
            "return_with_leftover_noise": (["disable", "enable"], {"advanced": True}),
            "chunk_frames": ("INT", {"default": 33, "min": 5, "max": 1024, "step": 4}),
            "overlap_frames": ("INT", {"default": 8, "min": 0, "max": 256, "step": 4}),
        }, "optional": {"debug": ("BOOLEAN", {"default": False})}}

    RETURN_TYPES = ("LATENT", "STRING")
    RETURN_NAMES = ("output", "chunk_info")
    FUNCTION = "execute"
    CATEGORY = "video/split"

    def execute(self, model, add_noise, noise_seed, steps, cfg, sampler_name, scheduler, positive, negative,
                latent_image, start_at_step, end_at_step, return_with_leftover_noise, chunk_frames, overlap_frames,
                debug=False):
        if not 0 <= start_at_step <= end_at_step:
            raise ValueError("Sampling steps must satisfy 0 <= start_at_step <= end_at_step")
        fixed_latent = latent_image.copy()
        samples = comfy.sample.fix_empty_latent_channels(
            model,
            latent_image["samples"],
            latent_image.get("downscale_ratio_spacial"),
            latent_image.get("downscale_ratio_temporal"),
        )
        if samples.is_nested or samples.ndim != 5:
            raise ValueError("Wan22 unlimited sampler requires one video latent [B,C,T,H,W]")
        fixed_latent["samples"] = samples
        if add_noise == "disable":
            full_noise = comfy.sample.prepare_empty_noise(samples)
        else:
            full_noise = comfy.sample.prepare_noise(samples, noise_seed, latent_image.get("batch_index"))
        chunks = _chunk_plan(samples.shape[2], max(5, align_pixel_frames_to_chunk(chunk_frames)), overlap_frames)
        output_video = []
        previous_video = None
        chunk_infos = []
        force_full_denoise = return_with_leftover_noise == "disable"
        for chunk in chunks:
            vs, ve = chunk.video_start, chunk.video_end
            chunk_latent = samples[:, :, vs:ve].clone()
            chunk_noise = full_noise[:, :, vs:ve].clone()
            chunk_mask = _slice_mask(latent_image.get("noise_mask"), vs, ve, samples)
            # For non-first chunks: inject overlap context from previous chunk
            if chunk.overlap_steps and previous_video is not None:
                chunk_latent[:, :, :chunk.overlap_steps] = previous_video.to(chunk_latent)
                chunk_noise[:, :, :chunk.overlap_steps] = 0
                chunk_mask[:, :, :chunk.overlap_steps] = 0
            output = comfy.sample.sample(
                model, chunk_noise, steps, cfg, sampler_name, scheduler,
                _slice_standard_conditioning(positive, vs, ve),
                _slice_standard_conditioning(negative, vs, ve),
                chunk_latent, disable_noise=add_noise == "disable", start_step=start_at_step,
                last_step=end_at_step, force_full_denoise=force_full_denoise, noise_mask=chunk_mask,
                disable_pbar=not comfy.utils.PROGRESS_BAR_ENABLED, seed=noise_seed,
            )
            trim_steps = chunk.overlap_steps
            # Save overlap for next chunk. First chunk still needs to save overlap for chunk 2.
            if not chunk.is_first:
                save_steps = trim_steps
            elif overlap_frames > 0:
                save_steps = min(overlap_frames // 4, output.shape[2])
            else:
                save_steps = 0
            if save_steps:
                previous_video = output[:, :, -save_steps:].detach().cpu()
            output_video.append(output[:, :, trim_steps:].detach().cpu())
            chunk_infos.append(f"Chunk {chunk.chunk_index + 1}/{len(chunks)}: latent [{vs}, {ve}), overlap={chunk.overlap_frames}f")

        final_output = latent_image.copy()
        final_output.pop("downscale_ratio_spacial", None)
        final_output.pop("downscale_ratio_temporal", None)
        final_output["samples"] = torch.cat(output_video, dim=2)
        if debug:
            logging.info("Wan22 unlimited sampler:\n%s", "\n".join(chunk_infos))
        return (final_output, "\n".join(chunk_infos))


class Wan22TwoStageUnlimitedSampler:
    @classmethod
    def INPUT_TYPES(cls):
        stage_noise = (["enable", "disable"], {"advanced": True})
        stage_leftover = (["disable", "enable"], {"advanced": True})
        return {"required": {
            "high_model": ("MODEL",),
            "low_model": ("MODEL",),
            "vae": ("VAE",),
            "positive": ("CONDITIONING",),
            "negative": ("CONDITIONING",),
            "latent_image": ("LATENT",),
            "noise_seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff, "control_after_generate": True}),
            "steps": ("INT", {"default": 20, "min": 1, "max": 10000}),
            "cfg": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 100.0, "step": 0.1, "round": 0.01}),
            "sampler_name": (comfy.samplers.KSampler.SAMPLERS,),
            "scheduler": (comfy.samplers.KSampler.SCHEDULERS,),
            "high_add_noise": stage_noise,
            "high_start_at_step": ("INT", {"default": 0, "min": 0, "max": 10000, "advanced": True}),
            "high_end_at_step": ("INT", {"default": 10, "min": 0, "max": 10000, "advanced": True}),
            "high_return_with_leftover_noise": stage_leftover,
            "low_add_noise": stage_noise,
            "low_start_at_step": ("INT", {"default": 10, "min": 0, "max": 10000, "advanced": True}),
            "low_end_at_step": ("INT", {"default": 10000, "min": 0, "max": 10000, "advanced": True}),
            "low_return_with_leftover_noise": stage_leftover,
            "chunk_frames": ("INT", {"default": 33, "min": 5, "max": 1024, "step": 4}),
            "overlap_frames": ("INT", {"default": 8, "min": 0, "max": 256, "step": 4}),
        }, "optional": {"debug": ("BOOLEAN", {"default": False})}}

    RETURN_TYPES = ("LATENT", "STRING")
    RETURN_NAMES = ("output", "chunk_info")
    FUNCTION = "execute"
    CATEGORY = "video/split"

    def execute(self, high_model, low_model, vae, positive, negative, latent_image, noise_seed, steps, cfg,
                sampler_name, scheduler, high_add_noise, high_start_at_step, high_end_at_step,
                high_return_with_leftover_noise, low_add_noise, low_start_at_step, low_end_at_step,
                low_return_with_leftover_noise, chunk_frames, overlap_frames, debug=False):
        if not 0 <= high_start_at_step <= high_end_at_step:
            raise ValueError("High-noise steps must satisfy 0 <= start_at_step <= end_at_step")
        if not 0 <= low_start_at_step <= low_end_at_step:
            raise ValueError("Low-noise steps must satisfy 0 <= start_at_step <= end_at_step")

        samples = comfy.sample.fix_empty_latent_channels(
            high_model,
            latent_image["samples"],
            latent_image.get("downscale_ratio_spacial"),
            latent_image.get("downscale_ratio_temporal"),
        )
        if samples.is_nested or samples.ndim != 5:
            raise ValueError("Wan22 two-stage unlimited sampler requires one video latent [B,C,T,H,W]")
        if vae.latent_dim != 3 or vae.latent_channels != samples.shape[1]:
            raise ValueError(
                f"The connected Wan VAE must encode {samples.shape[1]}-channel video latents; "
                f"got {vae.latent_channels} channels with latent_dim={vae.latent_dim}"
            )

        full_noise = (comfy.sample.prepare_empty_noise(samples) if high_add_noise == "disable"
                      else comfy.sample.prepare_noise(samples, noise_seed, latent_image.get("batch_index")))
        chunks = _chunk_plan(samples.shape[2], max(5, align_pixel_frames_to_chunk(chunk_frames)), overlap_frames)
        output_video = []
        reference_latent = None
        chunk_infos = []

        for chunk in chunks:
            vs, ve = chunk.video_start, chunk.video_end
            chunk_latent = samples[:, :, vs:ve].clone()
            chunk_noise = full_noise[:, :, vs:ve].clone()
            chunk_mask = _slice_mask(latent_image.get("noise_mask"), vs, ve, samples)
            if reference_latent is not None:
                reference_steps = min(chunk.overlap_steps, reference_latent.shape[2], chunk_latent.shape[2])
                chunk_latent[:, :, :reference_steps] = reference_latent[:, :, -reference_steps:].to(chunk_latent)
                chunk_noise[:, :, :reference_steps] = 0
                chunk_mask[:, :, :reference_steps] = 0

            positive_chunk = _slice_standard_conditioning(positive, vs, ve, reference_latent)
            negative_chunk = _slice_standard_conditioning(negative, vs, ve, reference_latent)
            high_output = comfy.sample.sample(
                high_model, chunk_noise, steps, cfg, sampler_name, scheduler,
                positive_chunk, negative_chunk, chunk_latent,
                disable_noise=high_add_noise == "disable", start_step=high_start_at_step,
                last_step=high_end_at_step,
                force_full_denoise=high_return_with_leftover_noise == "disable",
                noise_mask=chunk_mask, disable_pbar=not comfy.utils.PROGRESS_BAR_ENABLED, seed=noise_seed,
            )
            low_noise = (comfy.sample.prepare_empty_noise(high_output) if low_add_noise == "disable"
                         else comfy.sample.prepare_noise(high_output, noise_seed, latent_image.get("batch_index")))
            low_output = comfy.sample.sample(
                low_model, low_noise, steps, cfg, sampler_name, scheduler,
                positive_chunk, negative_chunk, high_output,
                disable_noise=low_add_noise == "disable", start_step=low_start_at_step,
                last_step=low_end_at_step,
                force_full_denoise=low_return_with_leftover_noise == "disable",
                noise_mask=chunk_mask, disable_pbar=not comfy.utils.PROGRESS_BAR_ENABLED, seed=noise_seed,
            )

            output_video.append(low_output[:, :, chunk.overlap_steps:].detach().cpu())
            if chunk.chunk_index + 1 < len(chunks) and chunk.overlap_steps:
                decoded = vae.decode(low_output)
                context_frames = 1 + 4 * (chunk.overlap_steps - 1)
                reference_latent = _encode_video_frames(vae, decoded[:, -context_frames:]).detach().cpu()
            else:
                reference_latent = None
            chunk_infos.append(
                f"Chunk {chunk.chunk_index + 1}/{len(chunks)}: latent [{vs}, {ve}), "
                f"overlap={chunk.overlap_frames}f"
            )

        final_output = latent_image.copy()
        final_output.pop("downscale_ratio_spacial", None)
        final_output.pop("downscale_ratio_temporal", None)
        final_output["samples"] = torch.cat(output_video, dim=2)
        if debug:
            logging.info("Wan22 two-stage unlimited sampler:\n%s", "\n".join(chunk_infos))
        return (final_output, "\n".join(chunk_infos))


class Wan22LowNoiseUnlimitedSampler(_Wan22StandardUnlimitedSampler):
    pass


class Wan22HighNoiseUnlimitedSampler(_Wan22StandardUnlimitedSampler):
    pass


# ============================================================================
# 预览节点
# ============================================================================

try:
    from comfy_api.latest import io
    HAS_IO_LATEST = True
except ImportError:
    HAS_IO_LATEST = False

if HAS_IO_LATEST:
    import folder_paths

    class Wan22UnlimitedPreview(io.ComfyNode):
        """Wan22 / Bernini Unlimited Preview - 实时预览节点"""

        @classmethod
        def define_schema(cls):
            return io.Schema(
                node_id="Wan22UnlimitedPreview",
                display_name="Wan22 Unlimited Preview",
                category="video/split",
                description="为 Wan22 分块采样添加实时预览包装。使用 lighttaew2_2 TAESD 解码。",
                inputs=[
                    io.Model.Input("model"),
                    io.Int.Input("max_resolution", default=512, min=64, max=2048, step=64),
                    io.Int.Input("quality", default=75, min=30, max=100, step=1),
                    io.Float.Input("fps", default=24.0, min=1.0, max=60.0, step=0.001),
                    io.Int.Input("frame_stride", default=4, min=1, max=16, step=1),
                    io.Combo.Input(
                        "tiny_vae",
                        options=["none"] + folder_paths.get_filename_list("vae_approx"),
                        default="lighttaew2_2",
                    ),
                ],
                outputs=[io.Model.Output()],
                hidden=[io.Hidden.unique_id],
                is_experimental=True,
            )

        @classmethod
        def execute(cls, model, max_resolution, quality, fps, frame_stride, tiny_vae="lighttaew2_2"):
            from .preview import _AccumulatedPreviewWrapper, WAN22_PREVIEW_WRAPPER_KEY

            patched = model.clone()
            patched.add_wrapper_with_key(
                comfy.patcher_extension.WrappersMP.OUTER_SAMPLE,
                WAN22_PREVIEW_WRAPPER_KEY,
                _AccumulatedPreviewWrapper(
                    cls.hidden.unique_id, max_resolution, quality, fps, frame_stride, tiny_vae,
                    temporal_ratio=4,  # Wan22 时间压缩比
                    taesd_name="lighttaew2_2",
                ),
            )
            return io.NodeOutput(patched)


# ============================================================================
# 节点映射
# ============================================================================

WAN22_NODE_CLASS_MAPPINGS = {
    "Wan22UnlimitedSampler": Wan22UnlimitedSampler,
    "Wan22TwoStageUnlimitedSampler": Wan22TwoStageUnlimitedSampler,
    "Wan22LowNoiseUnlimitedSampler": Wan22LowNoiseUnlimitedSampler,
    "Wan22HighNoiseUnlimitedSampler": Wan22HighNoiseUnlimitedSampler,
}
WAN22_NODE_DISPLAY_NAME_MAPPINGS = {
    "Wan22UnlimitedSampler": "Wan22 / Bernini Sampler Unlimited",
    "Wan22TwoStageUnlimitedSampler": "Wan22 Two-Stage I2V Sampler Unlimited",
    "Wan22LowNoiseUnlimitedSampler": "Wan22 / Bernini Low Noise Sampler Unlimited",
    "Wan22HighNoiseUnlimitedSampler": "Wan22 / Bernini High Noise Sampler Unlimited",
}

if HAS_IO_LATEST:
    WAN22_NODE_CLASS_MAPPINGS["Wan22UnlimitedPreview"] = Wan22UnlimitedPreview
    WAN22_NODE_DISPLAY_NAME_MAPPINGS["Wan22UnlimitedPreview"] = "Wan22 Unlimited Preview"
