"""
Upscaler Nodes - 基于 LTX Video 的高清放大采样器

将长视频分块采样以解决高分辨率放大时的 VRAM 问题。

核心设计理念 (来自 ComfyUI-MiniMax-H3-Sampler-Unlimited):
1. 时序分块 - 将长视频分成多个段落
2. 空间分块 - 将高分辨率帧分成多个小块
3. 平滑拼接 - 在边界处进行线性混合

适用于:
- 12GB VRAM 用户放大 4K 视频
- 1分钟+ 长视频处理
"""

import copy
import logging
from dataclasses import dataclass
from typing import Optional

import torch

import comfy
import comfy.sample
import comfy.samplers
import comfy.utils
import comfy_extras.nodes_custom_sampler
from comfy_api.latest import io


# ============================================================================
# 帧结构转换
# ============================================================================

def pixel_frames_to_latent_steps(pixel_frames: int) -> int:
    """
    将像素帧数转换为 latent 步数
    
    LTX 帧结构: 像素帧数 = 8 * n + 1, latent 步数 = n + 1
    例如: 257 -> 33, 129 -> 17, 17 -> 3, 9 -> 2
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
# 分块规划
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
    # 重叠帧数必须是 8 的倍数
    if overlap_frames < 8 or overlap_frames % 8 != 0:
        raise ValueError(f"Overlap frames must be 8n (8, 16, 24, ...), got {overlap_frames}")
    
    # 转换为 latent 步数
    total_latent_steps = pixel_frames_to_latent_steps(total_pixel_frames)
    max_chunk_latent = pixel_frames_to_latent_steps(chunk_frames)
    overlap_latent = pixel_frames_to_latent_steps(overlap_frames) if overlap_frames > 0 else 0
    
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
# 噪声生成器
# ============================================================================

class _FixedNoise:
    """固定噪声生成器 - 为每个分块生成固定切片"""
    def __init__(self, seed: int, noise_tensor: torch.Tensor):
        self.seed = seed
        self.noise_tensor = noise_tensor
    
    def generate_noise(self, latent):
        return self.noise_tensor


# ============================================================================
# 线性混合
# ============================================================================

def linear_blend_overlap(
    tensor1: torch.Tensor,
    tensor2: torch.Tensor,
    overlap_steps: int,
    dim: int = 2,
) -> torch.Tensor:
    """
    在重叠区域进行线性混合
    
    Args:
        tensor1: 前一块的输出 [B, C, T, H, W]
        tensor2: 后一块的输出 [B, C, T, H, W]
        overlap_steps: 重叠的步数
        dim: 时间维度
    
    Returns:
        混合后的张量
    """
    if overlap_steps <= 0:
        return torch.cat([tensor1, tensor2], dim=dim)
    
    # 创建混合权重
    alpha = torch.linspace(0, 1, overlap_steps, device=tensor1.device, dtype=tensor1.dtype)
    
    # 调整形状用于广播
    for _ in range(dim):
        alpha = alpha.unsqueeze(0)
    for _ in range(tensor1.ndim - alpha.ndim):
        alpha = alpha.unsqueeze(-1)
    
    # 获取重叠区域
    overlap1 = tensor1[:, :, -overlap_steps:]
    overlap2 = tensor2[:, :, :overlap_steps]
    
    # 线性混合
    blended_overlap = (1 - alpha) * overlap1 + alpha * overlap2
    
    # 组装最终结果
    result = torch.cat([
        tensor1[:, :, :-overlap_steps] if overlap_steps < tensor1.shape[dim] else tensor1[:, :, :0],
        blended_overlap,
        tensor2[:, :, overlap_steps:],
    ], dim=dim)
    
    return result


# ============================================================================
# 主节点: 分块采样器
# ============================================================================

class VideoSplitSamplerCustomAdvanced:
    """
    分块采样的 SamplerCustomAdvanced 替代节点
    
    继承自 MiniMax H3 Unlimited 的设计理念:
    - 将长视频 latent 分成多个时序块
    - 使用重叠 latent 作为连续引导
    - 在重叠区域进行线性混合
    - 解决高分辨率长视频采样时的 VRAM 问题
    
    使用场景:
    - 12GB VRAM 用户放大 4K 视频
    - 1分钟+ 长视频处理
    - 任何会爆显存的高分辨率长视频
    
    参数说明:
    - chunk_frames: 每块最大像素帧数 (必须是 8n+1, 如 9, 17, 25, 33...)
      建议值: 16-33, 取决于你的 VRAM
    - overlap_frames: 重叠像素帧数 (用于连续引导)
      建议值: 8 (最小有效值)
    - overlap_strength: 重叠区域的混合强度
      建议值: 0.5-0.7
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
                    "tooltip": "重叠像素帧数（必须是8的倍数），用于分块间的连续引导. 8=推荐值"
                }),
                "overlap_strength": ("FLOAT", {
                    "default": 0.5,
                    "min": 0.0,
                    "max": 1.0,
                    "step": 0.1,
                    "tooltip": "重叠区域的混合强度. 0.5=线性混合"
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
    分块采样器 - 将长视频 latent 分块处理以解决 VRAM 问题。
    
    工作原理:
    1. 将长视频 latent 分成多个时序块
    2. 每个分块独立采样
    3. 在重叠区域进行线性混合
    4. 拼接成完整输出
    
    示例:
    - 1分钟 24fps 视频 = 1440帧
    - chunk_frames=16, overlap_frames=8
    - 分成约 90 个分块
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
        5. 线性混合重叠区域
        6. 拼接输出
        """
        if debug:
            logging.info("=" * 60)
            logging.info("VideoSplitSamplerCustomAdvanced 开始执行")
            logging.info("=" * 60)
        
        # 获取 latent 样本
        samples = latent_image["samples"]
        
        # 验证是普通视频 latent (5D) 而非嵌套 AV latent
        if hasattr(samples, 'is_nested') and samples.is_nested:
            raise ValueError(
                "VideoSplitSamplerCustomAdvanced 不支持嵌套 AV latent。"
                "请使用纯视频 latent (LATENT 类型)。"
            )
        
        if samples.ndim != 5:
            raise ValueError(f"VideoSplitSamplerCustomAdvanced 需要 5D 视频 latent, got {samples.ndim}D")
        
        batch, channels, latent_steps, height, width = samples.shape
        
        # 转换为像素帧数
        total_pixel_frames = latent_steps_to_pixel_frames(latent_steps)
        
        if debug:
            logging.info(f"Latent 形状: {samples.shape}")
            logging.info(f"总像素帧数: {total_pixel_frames}")
            logging.info(f"每块最大帧数: {chunk_frames}")
            logging.info(f"重叠帧数: {overlap_frames}")
        
        # 生成完整的噪声
        full_noise = noise.generate_noise(latent_image)
        
        # 分块规划
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
        
        # 收集输出
        output_frames = []
        denoised_frames = []
        chunk_infos = []
        
        # 原始 guider 条件保存
        original_conds = None
        if hasattr(guider, 'original_conds'):
            original_conds = copy.deepcopy(guider.original_conds)
        
        try:
            for chunk_idx, chunk in enumerate(chunks):
                if debug:
                    logging.info(f"\n处理 Chunk {chunk_idx + 1}/{len(chunks)}")
                
                # 准备分块 latent
                chunk_latent = samples[:, :, chunk.latent_start:chunk.latent_end].clone()
                
                # 准备分块噪声
                chunk_noise = full_noise[:, :, chunk.latent_start:chunk.latent_end].clone()
                
                # 如果不是第一个分块，需要添加连续引导
                # 这是关键修复：将前一块的输出作为引导拼接到当前块
                if not chunk.is_first and chunk.overlap_latent_steps > 0:
                    # 从前一分块的输出中获取重叠部分
                    prev_output = output_frames[-1]
                    overlap_start_idx = prev_output.shape[2] - chunk.overlap_latent_steps
                    overlap_latent = prev_output[:, :, overlap_start_idx:].clone()
                    
                    if debug:
                        logging.info(f"  连续引导: 将前一块末尾 {overlap_latent.shape} 拼接到当前块")
                    
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
                if "noise_mask" in latent_image:
                    noise_mask = latent_image["noise_mask"]
                    chunk_mask = noise_mask[:, :, chunk.latent_start:chunk.latent_end].clone()
                    
                    # 如果有连续引导，也需要处理 mask
                    if not chunk.is_first and chunk.overlap_latent_steps > 0:
                        prev_mask = output_frames[-1]
                        overlap_start_idx = prev_mask.shape[2] - chunk.overlap_latent_steps
                        prev_overlap_mask = prev_mask[:, :, overlap_start_idx:].clone()
                        chunk_mask = torch.cat([prev_overlap_mask, chunk_mask], dim=2)
                    
                    chunk_latent_dict["noise_mask"] = chunk_mask
                
                # 执行采样
                try:
                    result = comfy_extras.nodes_custom_sampler.SamplerCustomAdvanced.execute(
                        noise=_FixedNoise(noise.seed + chunk_idx, chunk_noise),
                        guider=guider,
                        sampler=sampler,
                        sigmas=sigmas,
                        latent_image=chunk_latent_dict,
                    )
                    
                    if hasattr(result, '_asdict'):
                        output, denoised = result[0], result[1]
                    else:
                        output, denoised = result[0], result[1]
                        
                except Exception as e:
                    if debug:
                        logging.error(f"  采样失败: {e}")
                    raise
                
                # 提取输出
                output_samples = output["samples"]
                denoised_samples = denoised["samples"]
                
                # 如果有连续引导，移除引导部分（只保留新生成的内容）
                if not chunk.is_first and chunk.overlap_latent_steps > 0:
                    trim_steps = chunk.overlap_latent_steps
                    output_samples = output_samples[:, :, trim_steps:]
                    denoised_samples = denoised_samples[:, :, trim_steps:]
                    
                    if debug:
                        logging.info(f"  移除引导 {trim_steps} 步后形状: {output_samples.shape}")
                
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
# VRAM 估算工具
# ============================================================================

class VideoSplitVRAMEstimator:
    """
    VRAM 估算器 - 帮助估算分块采样所需的显存
    """
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video_frames": ("INT", {
                    "default": 1440,
                    "min": 9,
                    "max": 10000,
                    "step": 1,
                    "tooltip": "视频总帧数 (1分钟@24fps = 1440帧)"
                }),
                "target_resolution": ("STRING", {
                    "default": "3840x2160",
                    "tooltip": "目标分辨率 (宽x高), 如 3840x2160 表示 4K"
                }),
                "vram_gb": ("FLOAT", {
                    "default": 12.0,
                    "min": 4.0,
                    "max": 80.0,
                    "step": 0.5,
                    "tooltip": "你的显卡显存大小 (GB)"
                }),
                "chunk_frames": ("INT", {
                    "default": 16,
                    "min": 9,
                    "max": 129,
                    "step": 8,
                    "tooltip": "每块最大像素帧数"
                }),
            },
        }
    
    RETURN_TYPES = ("INT", "INT", "STRING")
    RETURN_NAMES = ("total_chunks", "estimated_vram_gb", "recommendation")
    FUNCTION = "execute"
    CATEGORY = "video/split"
    
    def execute(
        self,
        video_frames: int,
        target_resolution: str,
        vram_gb: float,
        chunk_frames: int,
    ) -> tuple:
        """估算分块数量和 VRAM"""
        # 解析分辨率
        try:
            width, height = map(int, target_resolution.split('x'))
        except:
            width, height = 1920, 1080
        
        # 计算 latent 大小
        latent_h = height // 16
        latent_w = width // 16
        latent_per_frame = latent_h * latent_w
        
        # 计算分块数
        # chunk_frames 必须是 8n+1 格式
        valid_chunk_frames = ((chunk_frames - 1) // 8) * 8 + 1
        if valid_chunk_frames < 9:
            valid_chunk_frames = 9
        
        # 计算重叠 (8帧重叠是标准)
        overlap_frames = 8
        effective_frames_per_chunk = valid_chunk_frames - overlap_frames
        
        # 总分块数
        total_chunks = (video_frames + effective_frames_per_chunk - 1) // effective_frames_per_chunk
        
        # 估算 VRAM
        # 单帧 latent 位置数
        positions_per_frame = latent_per_frame
        # 单块总位置 (简化估算)
        positions_per_chunk = positions_per_frame * valid_chunk_frames
        
        # 注意力开销 (简化: 与位置数成正比)
        # 假设模型占 vram_gb - 2GB (预留)
        model_vram = vram_gb - 2.0
        activation_per_million_positions = 0.01  # 粗略估算
        
        million_positions = positions_per_chunk / 1_000_000
        estimated_activation_gb = million_positions * activation_per_million_positions
        
        estimated_total = model_vram + estimated_activation_gb
        
        # 建议
        if estimated_total <= vram_gb:
            recommendation = f"✅ 配置可行! 预计 VRAM ~{estimated_total:.1f}GB"
        else:
            suggestion_frames = max(9, int(model_vram * 1_000_000 / activation_per_million_positions // positions_per_frame) - 5)
            suggestion_frames = ((suggestion_frames - 1) // 8) * 8 + 1
            if suggestion_frames < 9:
                suggestion_frames = 9
            recommendation = f"⚠️ 可能爆显存，建议 chunk_frames ≤ {suggestion_frames}"
        
        return (total_chunks, round(estimated_total, 1), recommendation)


# ============================================================================
# 节点映射
# ============================================================================

UPSCALER_NODE_CLASS_MAPPINGS = {
    "VideoSplitSamplerCustomAdvanced": VideoSplitSamplerCustomAdvanced,
    "VideoSplitVRAMEstimator": VideoSplitVRAMEstimator,
}

UPSCALER_NODE_DISPLAY_NAME_MAPPINGS = {
    "VideoSplitSamplerCustomAdvanced": "Video Split Sampler (Custom Advanced)",
    "VideoSplitVRAMEstimator": "Video Split VRAM Estimator",
}
