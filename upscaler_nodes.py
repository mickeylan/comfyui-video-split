"""
Upscaler Nodes - VRAM 估算工具

用于估算 LTX Video 分块采样所需的显存。
分块采样器已移至 ltxv_unlimited_nodes.py (LTXVUnlimitedSampler)
"""

import logging


class VideoSplitVRAMEstimator:
    """
    VRAM 估算器 - 帮助估算分块采样所需的显存
    
    基于以下参数估算:
    - 视频帧数
    - 目标分辨率
    - 显卡显存大小
    - 每块最大帧数
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
                    "default": 33,
                    "min": 17,
                    "max": 129,
                    "step": 8,
                    "tooltip": "每块最大像素帧数 (8n+1 格式)"
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
        positions_per_frame = latent_per_frame
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
    "VideoSplitVRAMEstimator": VideoSplitVRAMEstimator,
}

UPSCALER_NODE_DISPLAY_NAME_MAPPINGS = {
    "VideoSplitVRAMEstimator": "Video Split VRAM Estimator",
}
