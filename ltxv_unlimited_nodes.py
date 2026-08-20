"""
LTX Video Sampler Unlimited - AV 联合分块采样器

基于 MiniMax H3 Unlimited 架构，支持 LTX Video 的 AV 联合 latent 分块采样。

核心原理:
1. 处理 AV 联合 NestedTensor latent
2. 分离 video 和 audio 分别处理
3. 使用重叠 latent 作为连续引导
4. 重新组合 video 和 audio
"""

import copy
import logging
from dataclasses import dataclass

import torch

import comfy
import comfy.nested_tensor
import comfy.patcher_extension
import comfy_extras.nodes_custom_sampler

from .preview import begin_preview_execution, PREVIEW_WRAPPER_KEY


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
    """
    生成分块计划 (来自 MiniMax H3 Unlimited)
    
    Args:
        video_t: video latent 步数
        audio_t: audio latent 步数
        chunk_frames: 每块最大像素帧数
        time_scale_factor: 8 (LTX 固定)
    
    Returns:
        分块计划列表
    """
    # 计算每块最大 video latent 步数
    max_chunk_frames = chunk_frames - (chunk_frames - 1) % time_scale_factor
    max_chunk_t = ((max_chunk_frames - 1) // time_scale_factor) * time_scale_factor + 1
    
    # 验证 video latent 格式
    if video_t < 1 or (video_t - 1) % time_scale_factor != 0:
        raise ValueError(f"LTX video latent must be on 8n+1 frame grid, got video_t={video_t}")
    
    total_pixel_frames = latent_steps_to_pixel_frames(video_t)
    
    plan = []
    video_end = 0
    audio_end = 0
    output_frames = 0
    remaining = video_t
    overlap_video_steps = 1  # 重叠 1 video latent 步 = 8 像素帧
    
    while remaining:
        if not plan:
            # 第一个分块
            chunk_t = min(max_chunk_t, remaining)
            video_start = 0
            new_video_t = chunk_t
            chunk_frame_count = latent_steps_to_pixel_frames(chunk_t)
            context_audio_t = 0
        else:
            # 后续分块
            new_video_t = min(max_chunk_t - overlap_video_steps, remaining)
            chunk_t = new_video_t + overlap_video_steps
            video_start = video_end - overlap_video_steps
            chunk_frame_count = latent_steps_to_pixel_frames(chunk_t)
            # 计算 audio 上下文
            chunk_audio_t = round(chunk_frame_count * audio_t / total_pixel_frames)
            context_audio_t = chunk_audio_t - (round(new_video_t * audio_t / total_pixel_frames))
        
        output_frames += chunk_frame_count if not plan else chunk_frame_count - 8
        next_audio_end = round(output_frames * audio_t / total_pixel_frames)
        audio_start = 0 if not plan else audio_end - context_audio_t
        
        plan.append(ChunkPlan(
            chunk_index=len(plan),
            video_start=video_start,
            video_end=video_start + chunk_t,
            audio_start=audio_start,
            audio_end=next_audio_end,
            frame_start=0 if not plan else output_frames - chunk_frame_count,
            frame_end=output_frames,
            is_first=(len(plan) == 0),
            overlap_video_steps=overlap_video_steps if len(plan) > 0 else 0,
            context_audio_steps=context_audio_t,
        ))
        
        video_end += new_video_t
        audio_end = next_audio_end
        remaining -= new_video_t
    
    return plan


# ============================================================================
# 噪声生成器
# ============================================================================

class _FixedNoise:
    """固定噪声生成器"""
    def __init__(self, seed: int, noise_tensor):
        self.seed = seed
        self.noise_tensor = noise_tensor
    
    def generate_noise(self, latent):
        return self.noise_tensor


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
                "vae": ("VAE", {"tooltip": "VAE (用于渐进式解码)"}),
                "chunk_frames": ("INT", {
                    "default": 33,
                    "min": 17,
                    "max": 513,
                    "step": 8,
                    "tooltip": "每块最大像素帧数 (8n+1 格式), 12GB 建议 33"
                }),
                "progressive_decode": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "启用渐进式解码: 边采样边解码，降低峰值显存"
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
        chunk_frames=33,
        progressive_decode=False,
        debug=False,
    ) -> tuple:
        """执行 AV 联合分块采样"""
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
        else:
            # 纯视频 latent
            video = samples
            audio = None
        
        # 获取形状
        video_t = video.shape[2]
        audio_t = audio.shape[-1] if audio is not None else 0
        
        if debug:
            logging.info(f"Video latent: {video.shape}")
            if audio is not None:
                logging.info(f"Audio latent: {audio.shape}")
        
        # 生成分块计划
        try:
            chunks = _chunk_plan(video_t, audio_t, chunk_frames)
        except ValueError as e:
            if debug:
                logging.warning(f"分块计划失败: {e}")
            # 回退到标准采样
            return comfy_extras.nodes_custom_sampler.SamplerCustomAdvanced.execute(
                noise, guider, sampler, sigmas, latent_image
            )
        
        if debug:
            logging.info(f"分块数量: {len(chunks)}")
            for chunk in chunks:
                logging.info(f"  Chunk {chunk.chunk_index}: video [{chunk.video_start}, {chunk.video_end}), "
                           f"audio [{chunk.audio_start}, {chunk.audio_end})")
        
        # 单块直接委托
        if len(chunks) == 1:
            return comfy_extras.nodes_custom_sampler.SamplerCustomAdvanced.execute(
                noise, guider, sampler, sigmas, latent_image
            )
        
        # 分块时拒绝 denoise mask
        if "noise_mask" in latent_image:
            raise ValueError("LTXVUnlimitedSampler 分块时不支持 denoise mask")
        
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
        
        # 生成完整噪声
        full_noise = noise.generate_noise(fixed_latent)
        if hasattr(full_noise, 'is_nested') and full_noise.is_nested:
            video_noise, audio_noise = full_noise.unbind()
        else:
            video_noise = full_noise
            audio_noise = None
        
        # 收集输出
        output_video = []
        output_audio = []
        denoised_video = []
        denoised_audio = []
        all_decoded_images = []  # 渐进式解码收集
        previous_video = None
        previous_audio = None
        chunk_infos = []
        
        # 保存原始 guider 条件
        original_conds = None
        if hasattr(guider, 'original_conds'):
            original_conds = copy.deepcopy(guider.original_conds)
        
        # 开始预览执行
        preview_execution = begin_preview_execution(guider.model_patcher, len(chunks))
        
        try:
            for chunk_idx, chunk in enumerate(chunks):
                if debug:
                    logging.info(f"\n处理 Chunk {chunk_idx + 1}/{len(chunks)}")
                
                # 准备分块 latent
                vs, ve = chunk.video_start, chunk.video_end
                aus, aue = chunk.audio_start, chunk.audio_end
                
                if is_av_latent:
                    chunk_latent = comfy.nested_tensor.NestedTensor((
                        video[:, :, vs:ve],
                        audio[..., aus:aue],
                    ))
                    chunk_noise = comfy.nested_tensor.NestedTensor((
                        video_noise[:, :, vs:ve],
                        audio_noise[..., aus:aue],
                    ))
                else:
                    chunk_latent = video[:, :, vs:ve].clone()
                    chunk_noise = video_noise[:, :, vs:ve].clone()
                
                # 添加连续引导 (来自前一块)
                if not chunk.is_first:
                    # Video 引导: 拼接前一块末尾 latent
                    overlap_video = previous_video[:, :, -chunk.overlap_video_steps:].clone()
                    # Audio 引导: 拼接前一块末尾 audio
                    overlap_audio = previous_audio[..., -chunk.context_audio_steps:].clone()
                    
                    chunk_latent_with_guide = comfy.nested_tensor.NestedTensor((
                        torch.cat([overlap_video, video[:, :, vs:ve].clone()], dim=2),
                        torch.cat([overlap_audio, audio[..., aus:aue].clone()], dim=-1),
                    ))
                    chunk_noise_with_guide = comfy.nested_tensor.NestedTensor((
                        torch.cat([torch.zeros_like(overlap_video), video_noise[:, :, vs:ve].clone()], dim=2),
                        torch.cat([torch.zeros_like(overlap_audio), audio_noise[..., aus:aue].clone()], dim=-1),
                    ))
                    chunk_latent = chunk_latent_with_guide
                    chunk_noise = chunk_noise_with_guide
                
                # 构建 latent 字典
                chunk_latent_dict = {"samples": chunk_latent}
                
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
                
                # 执行采样
                try:
                    result = comfy_extras.nodes_custom_sampler.SamplerCustomAdvanced.execute(
                        noise=_FixedNoise((noise.seed + chunk_idx) & 0xffffffffffffffff, chunk_noise),
                        guider=guider,
                        sampler=sampler,
                        sigmas=sigmas,
                        latent_image=chunk_latent_dict,
                    )
                finally:
                    if preview_execution is not None:
                        preview_execution.clear_chunk()
                
                if hasattr(result, '_asdict'):
                    output, denoised = result[0], result[1]
                else:
                    output, denoised = result[0], result[1]
                
                # 分离输出
                if is_av_latent:
                    out_video, out_audio = output["samples"].unbind()
                    den_video, den_audio = denoised["samples"].unbind()
                else:
                    out_video = output["samples"]
                    out_audio = None
                    den_video = denoised["samples"]
                    den_audio = None
                
                # 更新前一块引用
                previous_video = out_video
                previous_audio = out_audio
                
                # 移除引导部分
                video_trim = 0 if chunk.is_first else chunk.overlap_video_steps
                audio_trim = 0 if chunk.is_first else chunk.context_audio_steps
                
                output_video.append(out_video[:, :, video_trim:].clone())
                if out_audio is not None:
                    output_audio.append(out_audio[..., audio_trim:].clone())
                denoised_video.append(den_video[:, :, video_trim:].clone())
                if den_audio is not None:
                    denoised_audio.append(den_audio[..., audio_trim:].clone())
                
                # 渐进式解码：每个 chunk 完成后立即解码
                if progressive_decode and vae is not None:
                    try:
                        chunk_video = out_video[:, :, video_trim:].clone()
                        images = vae.decode(chunk_video)
                        if len(images.shape) == 5:
                            images = images.reshape(-1, images.shape[-3], images.shape[-2], images.shape[-1])
                        all_decoded_images.append(images)
                        
                        if debug:
                            logging.info(f"  渐进式解码: {images.shape}")
                    except Exception as e:
                        if debug:
                            logging.warning(f"  渐进式解码失败: {e}")
                
                chunk_info = f"Chunk {chunk_idx + 1}/{len(chunks)}: " \
                           f"video [{chunk.video_start}, {chunk.video_end}), " \
                           f"audio [{chunk.audio_start}, {chunk.audio_end})"
                chunk_infos.append(chunk_info)
                
                if debug:
                    logging.info(f"  输出 video 形状: {out_video[:, :, video_trim:].shape}")
        
        finally:
            # 恢复原始 guider 条件
            if original_conds is not None and hasattr(guider, 'original_conds'):
                guider.original_conds = original_conds
            # 关闭预览
            if preview_execution is not None:
                preview_execution.close()
        
        # 组装最终输出
        final_video = torch.cat(output_video, dim=2)
        if is_av_latent and output_audio:
            final_audio = torch.cat(output_audio, dim=-1)
            final_output_samples = comfy.nested_tensor.NestedTensor((final_video, final_audio))
            final_denoised_samples = comfy.nested_tensor.NestedTensor((
                torch.cat(denoised_video, dim=2),
                torch.cat(denoised_audio, dim=-1),
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
        
        # 拼接渐进式解码的图像
        if progressive_decode and all_decoded_images:
            progressive_images = torch.cat(all_decoded_images, dim=0)
        else:
            progressive_images = torch.zeros(1, 256, 256, 3)  # 空图像占位
        
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
