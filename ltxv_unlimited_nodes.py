"""
LTX Video Sampler Unlimited - 基于 MiniMax H3 Unlimited 架构的分块采样器

核心原理:
1. 将长视频 latent 分成多个时序块
2. 使用重叠 latent 作为连续引导 (来自前一块的输出)
3. 在重叠区域使用零噪声引导
4. 移除重叠引导部分后拼接输出

来自 ComfyUI-MiniMax-H3-Sampler-Unlimited 的架构设计。
"""

import copy
import logging
from dataclasses import dataclass

import torch

import comfy
import comfy.patcher_extension
import comfy_extras.nodes_custom_sampler

from .preview import begin_preview_execution, PREVIEW_WRAPPER_KEY


# ============================================================================
# LTX Video 帧结构常量
# ============================================================================

# LTX Video 帧结构: 像素帧数 = 8 * n + 1
# latent 步数 = n + 1
# 例如: 257 (n=32) -> 33 步, 129 (n=16) -> 17 步, 17 (n=2) -> 3 步, 9 (n=1) -> 2 步


def pixel_frames_to_latent_steps(pixel_frames: int) -> int:
    """
    将像素帧数转换为 latent 步数
    
    LTX 帧结构: 像素帧数 = 8 * n + 1, latent 步数 = n + 1
    例如: 257 -> 33, 129 -> 17, 97 -> 13
    """
    if pixel_frames < 9:
        raise ValueError(f"LTX minimum is 9 pixel frames, got {pixel_frames}")
    if (pixel_frames - 1) % 8 != 0:
        raise ValueError(f"LTX requires (frames-1) to be divisible by 8, got {pixel_frames}")
    return (pixel_frames - 1) // 8 + 1


def latent_steps_to_pixel_frames(latent_steps: int) -> int:
    """将 latent 步数转换为像素帧数"""
    return (latent_steps - 1) * 8 + 1


# ============================================================================
# 分块规划 (来自 MiniMax H3 Unlimited)
# ============================================================================

@dataclass
class ChunkPlan:
    """单个分块的规划信息"""
    chunk_index: int
    # Latent 级别的索引 (不是像素帧)
    latent_start: int
    latent_end: int
    # 像素帧级别
    pixel_start: int
    pixel_end: int
    # 是否是第一个分块
    is_first: bool
    # 重叠的 latent 步数 (用于引导)
    overlap_latent_steps: int


def plan_chunks(
    total_pixel_frames: int,
    chunk_frames: int,
    overlap_frames: int = 8,
) -> list[ChunkPlan]:
    """
    生成分块计划
    
    Args:
        total_pixel_frames: 总像素帧数 (必须是 8n+1)
        chunk_frames: 每块最大像素帧数 (必须是 8n+1)
        overlap_frames: 重叠像素帧数 (用于连续引导，必须是 8 的倍数)
    
    Returns:
        分块计划列表
    """
    # 验证帧数合法性
    if (total_pixel_frames - 1) % 8 != 0:
        raise ValueError(f"Total frames must be 8n+1, got {total_pixel_frames}")
    if (chunk_frames - 1) % 8 != 0:
        raise ValueError(f"Chunk frames must be 8n+1, got {chunk_frames}")
    if chunk_frames < 9:
        raise ValueError(f"Minimum chunk frames is 9, got {chunk_frames}")
    if overlap_frames < 8 or overlap_frames % 8 != 0:
        raise ValueError(f"Overlap frames must be 8n, got {overlap_frames}")
    
    # 转换为 latent 步数
    total_latent_steps = pixel_frames_to_latent_steps(total_pixel_frames)
    max_chunk_latent = pixel_frames_to_latent_steps(chunk_frames)
    overlap_latent = pixel_frames_to_latent_steps(overlap_frames)
    
    chunks = []
    latent_pos = 0
    chunk_index = 0
    
    while latent_pos < total_latent_steps:
        if chunk_index == 0:
            # 第一个分块: 尽可能多地采样
            chunk_latent_end = min(latent_pos + max_chunk_latent, total_latent_steps)
        else:
            # 后续分块: 包含重叠 + 新内容
            remaining = total_latent_steps - latent_pos
            # 新的 latent 步数 = min(最大块大小 - 重叠, 剩余)
            new_steps = min(max_chunk_latent - overlap_latent, remaining)
            chunk_latent_end = latent_pos + new_steps
        
        chunk = ChunkPlan(
            chunk_index=chunk_index,
            latent_start=latent_pos,
            latent_end=chunk_latent_end,
            pixel_start=latent_steps_to_pixel_frames(latent_pos),
            pixel_end=latent_steps_to_pixel_frames(chunk_latent_end),
            is_first=(chunk_index == 0),
            overlap_latent_steps=overlap_latent if chunk_index > 0 else 0,
        )
        chunks.append(chunk)
        
        # 下一个分块的起始位置 (跳过已生成的内容)
        if chunk_index == 0:
            latent_pos = chunk_latent_end
        else:
            latent_pos = chunk_latent_end
        
        chunk_index += 1
    
    return chunks


# ============================================================================
# 噪声生成器 (来自 MiniMax H3 Unlimited)
# ============================================================================

class _FixedNoise:
    """固定噪声生成器 - 为每个分块生成固定切片"""
    def __init__(self, seed: int, noise_tensor: torch.Tensor):
        self.seed = seed
        self.noise_tensor = noise_tensor
    
    def generate_noise(self, latent):
        return self.noise_tensor


# ============================================================================
# 主节点: LTX Video 分块采样器 (来自 ComfyUI-LTXVideo-Unlimited)
# ============================================================================

class LTXVUnlimitedSampler:
    """
    LTX Video 分块采样器 - Unlimited 版本
    
    继承自 MiniMax H3 Unlimited 的设计理念:
    - 分块处理长视频以减少 VRAM 占用
    - 使用重叠 latent 作为连续引导
    - 支持任意长度的视频生成
    
    工作原理:
    1. 将长视频 latent 分成多个时序块
    2. 每个分块包含 overlap_frames 像素帧的重叠引导
    3. 重叠区域使用零噪声，由前一块的输出引导
    4. 移除重叠引导部分后拼接输出
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
                "chunk_frames": ("INT", {
                    "default": 129,
                    "min": 17,
                    "max": 513,
                    "step": 8,
                    "tooltip": "每块最大像素帧数 (8n+1 格式，如17,33,65,129). 129帧适合高VRAM, 33帧适合12GB VRAM"
                }),
                "overlap_frames": ("INT", {
                    "default": 8,
                    "min": 8,
                    "max": 64,
                    "step": 8,
                    "tooltip": "重叠像素帧数（必须是8的倍数），用于连续引导. 8=推荐值"
                }),
                "overlap_strength": ("FLOAT", {
                    "default": 0.5,
                    "min": 0.0,
                    "max": 1.0,
                    "step": 0.01,
                    "tooltip": "重叠区域的引导强度"
                }),
                "debug": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "打印调试信息"
                }),
            },
        }
    
    RETURN_TYPES = ("LATENT", "LATENT", "STRING")
    RETURN_NAMES = ("output", "denoised_output", "chunk_info")
    FUNCTION = "execute"
    CATEGORY = "video/split"
    
    DESCRIPTION = """
    LTX Video 分块采样器 - 将长视频 latent 分块处理以解决 VRAM 问题。
    
    工作原理:
    1. 将长视频 latent 分成多个时序块
    2. 每个分块包含 overlap_frames 像素帧的重叠引导
    3. 重叠区域使用零噪声，由前一块的输出引导
    4. 移除重叠引导部分后拼接输出
    
    示例:
    - 1分钟 24fps 视频 = 1440帧
    - chunk_frames=129, overlap_frames=8
    - 分成约 12 个分块
    - 每块独立采样，VRAM 峰值 ≈ 单块大小
    """
    
    def execute(
        self,
        noise,
        guider,
        sampler,
        sigmas,
        latent_image,
        chunk_frames=129,
        overlap_frames=8,
        overlap_strength=0.5,
        debug=False,
    ) -> tuple:
        """
        执行分块采样
        
        流程:
        1. 验证 latent 格式
        2. 生成分块计划
        3. 循环处理每个分块
        4. 使用重叠引导
        5. 移除重叠部分
        6. 拼接输出
        """
        if debug:
            logging.info("=" * 60)
            logging.info("LTXVUnlimitedSampler 开始执行")
            logging.info("=" * 60)
        
        # 获取 latent 样本
        samples = latent_image["samples"]
        
        # 验证是普通视频 latent (5D) 而非嵌套 AV latent
        if hasattr(samples, 'is_nested') and samples.is_nested:
            raise ValueError(
                "LTXVUnlimitedSampler 不支持嵌套 AV latent。"
                "请使用纯视频 latent (LATENT 类型)。"
            )
        
        if samples.ndim != 5:
            raise ValueError(f"LTXVUnlimitedSampler 需要 5D 视频 latent, got {samples.ndim}D")
        
        batch, channels, latent_steps, height, width = samples.shape
        
        # 转换为像素帧数
        total_pixel_frames = latent_steps_to_pixel_frames(latent_steps)
        
        if debug:
            logging.info(f"Latent 形状: {samples.shape}")
            logging.info(f"总像素帧数: {total_pixel_frames}")
            logging.info(f"每块最大帧数: {chunk_frames}")
            logging.info(f"重叠帧数: {overlap_frames}")
        
        # 生成分块计划
        chunks = plan_chunks(
            total_pixel_frames=total_pixel_frames,
            chunk_frames=chunk_frames,
            overlap_frames=overlap_frames,
        )
        
        if debug:
            logging.info(f"分块数量: {len(chunks)}")
            for chunk in chunks:
                logging.info(f"  Chunk {chunk.chunk_index}: latent [{chunk.latent_start}, {chunk.latent_end}), "
                           f"pixel [{chunk.pixel_start}, {chunk.pixel_end})")
        
        # 如果只有一块，直接委托给标准采样器
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
        
        # 生成完整的噪声
        full_noise = noise.generate_noise(latent_image)
        
        # 收集输出
        output_frames = []
        denoised_frames = []
        chunk_infos = []
        
        # 原始 guider 条件保存
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
                chunk_latent = samples[:, :, chunk.latent_start:chunk.latent_end].clone()
                
                # 准备分块噪声
                chunk_noise = full_noise[:, :, chunk.latent_start:chunk.latent_end].clone()
                
                # 如果不是第一个分块，需要添加重叠引导
                # 核心机制：将前一块的输出作为引导拼接到当前块
                overlap_latent_steps = chunk.overlap_latent_steps
                if not chunk.is_first and overlap_latent_steps > 0:
                    # 从前一分块的输出中获取重叠部分
                    prev_output = output_frames[-1]
                    overlap_start_idx = prev_output.shape[2] - overlap_latent_steps
                    overlap_latent = prev_output[:, :, overlap_start_idx:].clone()
                    
                    if debug:
                        logging.info(f"  重叠 latent 形状: {overlap_latent.shape}")
                    
                    # 将重叠 latent 与当前 chunk 拼接
                    chunk_latent_with_overlap = torch.cat([overlap_latent, chunk_latent], dim=2)
                    # 重叠区域用零噪声（由前一块输出引导）
                    chunk_noise_with_overlap = torch.cat([
                        torch.zeros_like(overlap_latent),
                        chunk_noise
                    ], dim=2)
                    
                    chunk_latent = chunk_latent_with_overlap
                    chunk_noise = chunk_noise_with_overlap
                
                # 构建分块 latent 字典
                chunk_latent_dict = {
                    "samples": chunk_latent,
                }
                
                # 设置预览分块
                if preview_execution is not None:
                    preview_execution.set_chunk(
                        chunk_idx,
                        chunk.latent_start,
                        chunk.latent_end - 1,
                        chunk.latent_start + overlap_latent_steps,
                        chunk.latent_end - 1,
                        overlap_latent_steps,
                    )
                
                # 执行采样
                try:
                    result = comfy_extras.nodes_custom_sampler.SamplerCustomAdvanced.execute(
                        noise=_FixedNoise(noise.seed + chunk_idx, chunk_noise),
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
                
                # 提取输出
                output_samples = output["samples"]
                denoised_samples = denoised["samples"]
                
                # 如果有重叠引导，移除重叠部分
                if not chunk.is_first and chunk.overlap_latent_steps > 0:
                    trim_steps = chunk.overlap_latent_steps
                    output_samples = output_samples[:, :, trim_steps:]
                    denoised_samples = denoised_samples[:, :, trim_steps:]
                    
                    if debug:
                        logging.info(f"  移除 {trim_steps} 步重叠后形状: {output_samples.shape}")
                
                output_frames.append(output_samples)
                denoised_frames.append(denoised_samples)
                
                chunk_info = f"Chunk {chunk_idx + 1}/{len(chunks)}: " \
                           f"latents [{chunk.latent_start}, {chunk.latent_end}), " \
                           f"output shape {output_samples.shape}"
                chunk_infos.append(chunk_info)
                
                if debug:
                    logging.info(f"  输出形状: {output_samples.shape}")
        
        finally:
            # 恢复原始 guider 条件
            if original_conds is not None and hasattr(guider, 'original_conds'):
                guider.original_conds = original_conds
            # 关闭预览
            if preview_execution is not None:
                preview_execution.close()
        
        # 拼接所有分块输出
        final_output_samples = torch.cat(output_frames, dim=2)
        final_denoised_samples = torch.cat(denoised_frames, dim=2)
        
        if debug:
            logging.info(f"\n最终输出形状: {final_output_samples.shape}")
            logging.info("=" * 60)
        
        # 构建输出字典
        final_output = {
            "samples": final_output_samples,
        }
        final_denoised = {
            "samples": final_denoised_samples,
        }
        
        # 复制批次索引
        if "batch_index" in latent_image:
            final_output["batch_index"] = latent_image["batch_index"]
            final_denoised["batch_index"] = latent_image["batch_index"]
        
        chunk_info_text = "\n".join(chunk_infos)
        
        return (final_output, final_denoised, chunk_info_text)
    
    # 别名
    sample = execute


# ============================================================================
# 辅助函数
# ============================================================================

def get_chunk_preview_frames(
    total_frames: int,
    chunk_frames: int,
    overlap_frames: int = 8,
    frame_stride: int = 1,
) -> list[tuple[int, int, int]]:
    """
    计算预览用的帧索引范围
    
    Returns:
        [(chunk_idx, frame_start, frame_end), ...]
    """
    try:
        chunks = plan_chunks(total_frames, chunk_frames, overlap_frames)
        return [(c.chunk_index, c.pixel_start, c.pixel_end) for c in chunks]
    except ValueError:
        return [(0, 0, total_frames)]


# ============================================================================
# 预览节点
# ============================================================================

from comfy_api.latest import io
import folder_paths


class LTXVUnlimitedPreview(io.ComfyNode):
    """
    LTX Video Unlimited Preview - 实时预览节点
    
    在分块采样过程中实时预览生成的视频。
    使用 Latent2RGB 或 Tiny VAE 解码预览帧。
    """
    
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="LTXVUnlimitedPreview",
            display_name="LTX Video Unlimited Preview",
            category="video/split",
            description="在分块采样过程中实时预览 LTX Video 输出。支持 Latent2RGB 和 Tiny VAE 解码模式。",
            inputs=[
                io.Model.Input("model"),
                io.Int.Input("max_resolution", default=512, min=64, max=2048, step=64,
                            tooltip="预览最大分辨率"),
                io.Int.Input("quality", default=75, min=30, max=100, step=1,
                            tooltip="WebP 编码质量"),
                io.Float.Input("fps", default=24.0, min=1.0, max=60.0, step=0.001,
                            tooltip="预览帧率"),
                io.Int.Input("frame_stride", default=1, min=1, max=16, step=1,
                            tooltip="预览间隔（每 N 帧预览一次）"),
                io.Combo.Input("tiny_vae", 
                             options=["none"] + folder_paths.get_filename_list("vae_approx"), 
                             default="none",
                             tooltip="可选的 Tiny VAE 解码器。None 使用 Latent2RGB。"),
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
