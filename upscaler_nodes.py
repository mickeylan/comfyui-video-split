"""
Upscaler Nodes - VRAM 管理器 + 估算工具 + 优化解码

功能:
1. LTXVRAMManager - VRAM 模式配置
2. VideoSplitVRAMEstimator - 分块 VRAM 估算
3. LTXVOptimizedDecode - bf16 强制 VAE 解码
4. LTXVOptimizedAudioDecode - Audio VAE 解码

分块采样器已移至 ltxv_unlimited_nodes.py (LTXVUnlimitedSampler)
"""

import gc
import logging
import torch


class VideoSplitVRAMEstimator:
    """
    VRAM 估算器 - 帮助估算分块采样所需的显存
    
    基于以下参数估算:
    - 视频帧数
    - 目标分辨率
    - 显卡显存大小
    - 每块最大帧数
    
    12GB VRAM 参考配置:
    - 720p (1280x720): chunk_frames=33 可用
    - 1080p (1920x1080): chunk_frames=17 勉强可用
    - 更高分辨率需要分块或 offload
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
                    "default": "1280x720",
                    "tooltip": "目标分辨率 (宽x高), 12GB 建议 1280x720"
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
                    "tooltip": "每块最大像素帧数 (8n+1 格式), 12GB 建议 33"
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
# VRAM 管理器
# ============================================================================

class LTXVRAMManager:
    """
    LTX Video VRAM 管理器
    
    配置 ComfyUI 显存设置，类似于 MiniMaxH3VRAMManager:
    - 16GB-safe: 激进 offload
    - 24GB-fast: 全部驻留 GPU
    - balanced: 平衡策略
    
    自动检测显卡并推荐分辨率和帧数。
    """
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL",),
                "vram_mode": (
                    ["auto", "16GB-safe", "24GB-fast", "balanced"],
                    {"default": "auto", "tooltip": "16GB-safe: 激进 offload; 24GB-fast: 全部驻留 GPU"}
                ),
                "resolution_hint": (
                    ["auto", "4K (3840x2160)", "2K (2560x1440)", "1080p (1920x1080)", "720p (1280x720)"],
                    {"default": "auto"}
                ),
            }
        }
    
    RETURN_TYPES = ("MODEL", "STRING")
    RETURN_NAMES = ("model", "vram_info")
    FUNCTION = "configure"
    CATEGORY = "video/split"
    
    def configure(self, model, vram_mode="auto", resolution_hint="auto"):
        """配置 VRAM 模式"""
        if not torch.cuda.is_available():
            return (model, "CUDA not available")
        
        props = torch.cuda.get_device_properties(0)
        total_vram = props.total_memory / (1024**3)
        
        # 自动检测 VRAM 模式
        if vram_mode == "auto":
            if total_vram >= 22:
                vram_mode = "24GB-fast"
            elif total_vram >= 14:
                vram_mode = "16GB-safe"
            else:
                vram_mode = "balanced"
        
        # 自动检测分辨率 (基于 12GB 实测优化)
        if resolution_hint == "auto":
            if total_vram >= 24:
                resolution_hint = "4K (3840x2160)"
            elif total_vram >= 16:
                resolution_hint = "2K (2560x1440)"
            elif total_vram >= 12:
                resolution_hint = "720p (1280x720)"  # 12GB 建议 720p
            else:
                resolution_hint = "720p (1280x720)"
        
        # 清理显存
        torch.cuda.empty_cache()
        gc.collect()
        
        # 生成信息
        info_lines = [
            f"GPU: {props.name}",
            f"Total VRAM: {total_vram:.1f} GB",
            f"VRAM mode: {vram_mode}",
            f"Recommended resolution: {resolution_hint}",
        ]
        
        if vram_mode == "16GB-safe":
            info_lines.append("Strategy: 激进 offload，适合 16GB 显卡")
            info_lines.append("建议使用 --lowvram 或 --normalvram 启动")
        elif vram_mode == "24GB-fast":
            info_lines.append("Strategy: 全部驻留 GPU，最高速率")
        else:
            info_lines.append("Strategy: 平衡 offloading")
        
        # LTX Video 特有建议 (12GB 实测优化)
        info_lines.append("")
        info_lines.append("LTX Video 分块采样建议:")
        if total_vram >= 24:
            info_lines.append(f"  chunk_frames: 129 (4K@24fps 可用)")
        elif total_vram >= 16:
            info_lines.append(f"  chunk_frames: 65 (2K@24fps 可用)")
        elif total_vram >= 12:
            info_lines.append(f"  chunk_frames: 33 (720p@24fps 可用)")
            info_lines.append(f"  chunk_frames: 17 (1080p@24fps 勉强可用)")
            info_lines.append("  建议使用 --lowvram 启动 ComfyUI")
        
        info_text = "\n".join(info_lines)
        print(f"[ltx-vram] {info_text}", flush=True)
        
        return (model, info_text)


# ============================================================================
# 优化解码器
# ============================================================================

class LTXVOptimizedDecode:
    """
    LTX Video 优化解码器
    
    类似于 MiniMaxH3OptimizedDecode:
    1. 强制 bf16 VAE 解码 (Ampere+ GPU 显著加速)
    2. 解码后恢复 VAE dtype
    3. 处理 AV 联合 latent (提取 video 部分)
    
    注意: 不移动 diffusion model，避免 --lowvram 模式下 OOM
    """
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "samples": ("LATENT",),
                "vae": ("VAE",),
                "force_bf16": (
                    ["auto", "enable", "disable"],
                    {"default": "auto", "tooltip": "auto: Ampere+ 启用 bf16; enable: 强制 bf16; disable: 保持原样"}
                ),
            },
        }
    
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    FUNCTION = "decode"
    CATEGORY = "video/split"
    
    def decode(self, samples, vae, force_bf16="auto"):
        """优化解码"""
        latent = samples["samples"]
        
        # 处理 AV 联合 latent - 提取 video 部分
        is_av = hasattr(latent, 'is_nested') and latent.is_nested
        if is_av:
            video_latent, _ = latent.unbind()
        else:
            video_latent = latent
        
        # 确定 bf16 策略
        use_bf16 = False
        if force_bf16 == "enable":
            use_bf16 = torch.cuda.is_available() and torch.cuda.is_bf16_supported()
        elif force_bf16 == "auto":
            if torch.cuda.is_available():
                props = torch.cuda.get_device_properties(0)
                use_bf16 = props.major >= 8  # Ampere+ 支持 bf16
        
        orig_dtype = getattr(vae, "vae_dtype", None)
        
        try:
            # 强制 bf16
            if use_bf16:
                target_dtype = torch.bfloat16
                try:
                    vae.vae_dtype = target_dtype
                    if hasattr(vae, "first_stage_model") and vae.first_stage_model is not None:
                        vae.first_stage_model.to(target_dtype)
                    print(f"[ltx-decode] VAE decode forced to {target_dtype}", flush=True)
                except Exception as e:
                    print(f"[ltx-decode] bf16 note: {e}", flush=True)
            
            # 解码
            images = vae.decode(video_latent)
            if len(images.shape) == 5:
                images = images.reshape(-1, images.shape[-3], images.shape[-2], images.shape[-1])
        
        finally:
            # 恢复 VAE dtype
            if orig_dtype is not None:
                try:
                    vae.vae_dtype = orig_dtype
                    if hasattr(vae, "first_stage_model") and vae.first_stage_model is not None:
                        vae.first_stage_model.to(orig_dtype)
                except Exception:
                    pass
            
            # 不移动 diffusion model，避免 --lowvram OOM
            gc.collect()
            torch.cuda.empty_cache()
            
            if torch.cuda.is_available():
                free_gb = torch.cuda.mem_get_info()[0] / (1024**3)
                print(f"[ltx-decode] Done, VRAM free: {free_gb:.1f}GB", flush=True)
        
        return (images,)


class LTXVOptimizedAudioDecode:
    """
    LTX Video 优化音频解码器
    
    处理 AV 联合 latent 的 audio 部分解码。
    """
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "samples": ("LATENT",),
                "vae": ("VAE",),
            },
        }
    
    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ("audio",)
    FUNCTION = "decode"
    CATEGORY = "video/split"
    
    def decode(self, samples, vae):
        """优化音频解码"""
        latent = samples["samples"]
        
        # 检查是否是 AV 联合 latent
        is_av = hasattr(latent, 'is_nested') and latent.is_nested
        if not is_av:
            # 无音频 latent - 返回静音
            audio_out = {"waveform": torch.zeros(1, 2, 32000), "sample_rate": 32000}
            return (audio_out,)
        
        # 提取 audio latent
        _, audio_latent = latent.unbind()
        
        try:
            # 解码音频
            waveform = vae.decode(audio_latent).movedim(-1, 1)
            
            # 归一化
            std = torch.std(waveform, dim=[1, 2], keepdim=True) * 5.0
            std[std < 1.0] = 1.0
            waveform /= std
            
            audio_out = {
                "waveform": waveform,
                "sample_rate": getattr(vae, "audio_sample_rate", 32000)
            }
        
        except Exception as e:
            print(f"[ltx-audio-decode] Error: {e}", flush=True)
            # 估算音频长度并返回静音
            t = int(audio_latent.shape[-1] / 40 * 32000) if audio_latent.ndim >= 4 else 32000
            audio_out = {"waveform": torch.zeros(1, 2, t), "sample_rate": 32000}
        
        finally:
            gc.collect()
            torch.cuda.empty_cache()
            if torch.cuda.is_available():
                free_gb = torch.cuda.mem_get_info()[0] / (1024**3)
                print(f"[ltx-audio-decode] Done, VRAM free: {free_gb:.1f}GB", flush=True)
        
        return (audio_out,)


# ============================================================================
# 节点映射
# ============================================================================

UPSCALER_NODE_CLASS_MAPPINGS = {
    "VideoSplitVRAMEstimator": VideoSplitVRAMEstimator,
    "LTXVRAMManager": LTXVRAMManager,
    "LTXVOptimizedDecode": LTXVOptimizedDecode,
    "LTXVOptimizedAudioDecode": LTXVOptimizedAudioDecode,
}

UPSCALER_NODE_DISPLAY_NAME_MAPPINGS = {
    "VideoSplitVRAMEstimator": "Video Split VRAM Estimator",
    "LTXVRAMManager": "LTX VRAM Manager",
    "LTXVOptimizedDecode": "LTX Video Optimized Decode",
    "LTXVOptimizedAudioDecode": "LTX Video Optimized Audio Decode",
}
