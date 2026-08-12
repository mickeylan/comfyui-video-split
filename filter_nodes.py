"""
滤镜/调色处理节点
"""
import torch
import numpy as np


# ============================================================
# Color Adjust - 亮度/对比度/饱和度调节
# ============================================================

class ColorAdjust:
    """
    调节亮度、对比度、饱和度。
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "帧张量"}),
                "brightness": ("FLOAT", {"default": 0.0, "min": -1.0, "max": 1.0, "step": 0.01,
                    "tooltip": "亮度调整（-1~1）"}),
                "contrast": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 3.0, "step": 0.01,
                    "tooltip": "对比度（1.0=原始）"}),
                "saturation": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 3.0, "step": 0.01,
                    "tooltip": "饱和度（1.0=原始）"}),
                "gamma": ("FLOAT", {"default": 1.0, "min": 0.1, "max": 3.0, "step": 0.01,
                    "tooltip": "Gamma值（1.0=原始）"}),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    FUNCTION = "execute"
    CATEGORY = "video/filter"

    def execute(self, images: torch.Tensor, brightness: float, contrast: float,
                saturation: float, gamma: float):
        
        # 分块处理
        def process_chunk(chunk):
            result = chunk.clone()
            
            # 亮度调整
            if brightness != 0:
                result = result + brightness
            
            # 对比度调整
            if contrast != 1.0:
                result = (result - 0.5) * contrast + 0.5
            
            # Gamma 调整
            if gamma != 1.0:
                result = torch.pow(result, 1.0 / gamma)
            
            # 饱和度调整
            if saturation != 1.0:
                # 转换为灰度
                gray = 0.299 * result[..., 0] + 0.587 * result[..., 1] + 0.114 * result[..., 2]
                gray = gray.unsqueeze(-1).expand_as(result)
                result = gray + (result - gray) * saturation
            
            # 限制范围
            result = torch.clamp(result, 0.0, 1.0)
            
            return result
        
        return (process_chunk(images),)


# ============================================================
# Color Temperature - 色温调节
# ============================================================

class ColorTemperature:
    """
    调节色温（冷暖色调）。
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "帧张量"}),
                "temperature": ("FLOAT", {"default": 0.0, "min": -1.0, "max": 1.0, "step": 0.01,
                    "tooltip": "色温（-1冷色调，1暖色调）"}),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    FUNCTION = "execute"
    CATEGORY = "video/filter"

    def execute(self, images: torch.Tensor, temperature: float):
        
        if temperature == 0:
            return (images,)
        
        def process_chunk(chunk):
            result = chunk.clone()
            
            if temperature > 0:
                # 暖色调：增加红色，减少蓝色
                result[..., 0] = result[..., 0] + temperature * 0.1
                result[..., 2] = result[..., 2] - temperature * 0.1
            else:
                # 冷色调：减少红色，增加蓝色
                result[..., 0] = result[..., 0] + temperature * 0.1
                result[..., 2] = result[..., 2] - temperature * 0.1
            
            return torch.clamp(result, 0.0, 1.0)
        
        return (process_chunk(images),)


# ============================================================
# Color Grade Preset - 色彩分级预设
# ============================================================

class ColorGradePreset:
    """
    预设色彩分级效果。
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "帧张量"}),
                "preset": (["none", "vintage", "cinematic", "cold", "warm", 
                            "noir", "sepia", "vivid", "muted", "cyberpunk"],
                    {"default": "none", "tooltip": "预设效果"}),
                "intensity": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01,
                    "tooltip": "效果强度"}),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    FUNCTION = "execute"
    CATEGORY = "video/filter"

    def execute(self, images: torch.Tensor, preset: str, intensity: float):
        
        if preset == "none" or intensity == 0:
            return (images,)
        
        def process_chunk(chunk):
            result = chunk.clone()
            
            if preset == "vintage":
                # 复古：降低饱和度，增加暖色调
                gray = 0.299 * result[..., 0] + 0.587 * result[..., 1] + 0.114 * result[..., 2]
                gray = gray.unsqueeze(-1).expand_as(result)
                result = gray + (result - gray) * 0.7
                result[..., 0] = result[..., 0] + 0.05 * intensity
                result[..., 1] = result[..., 1] + 0.02 * intensity
            
            elif preset == "cinematic":
                # 电影感：高对比度，暗角效果
                result = (result - 0.5) * 1.3 + 0.5
                # 添加轻微蓝调
                result[..., 2] = result[..., 2] + 0.05 * intensity
            
            elif preset == "cold":
                # 冷色调
                result[..., 0] = result[..., 0] - 0.1 * intensity
                result[..., 2] = result[..., 2] + 0.1 * intensity
            
            elif preset == "warm":
                # 暖色调
                result[..., 0] = result[..., 0] + 0.1 * intensity
                result[..., 1] = result[..., 1] + 0.05 * intensity
                result[..., 2] = result[..., 2] - 0.05 * intensity
            
            elif preset == "noir":
                # 黑白高对比
                gray = 0.299 * result[..., 0] + 0.587 * result[..., 1] + 0.114 * result[..., 2]
                gray = gray.unsqueeze(-1).expand_as(result)
                result = gray
                result = (result - 0.5) * 1.5 + 0.5
            
            elif preset == "sepia":
                # 棕褐色调
                gray = 0.299 * result[..., 0] + 0.587 * result[..., 1] + 0.114 * result[..., 2]
                result[..., 0] = gray + 0.15 * intensity
                result[..., 1] = gray + 0.05 * intensity
                result[..., 2] = gray - 0.1 * intensity
            
            elif preset == "vivid":
                # 鲜艳：增加饱和度和对比度
                gray = 0.299 * result[..., 0] + 0.587 * result[..., 1] + 0.114 * result[..., 2]
                gray = gray.unsqueeze(-1).expand_as(result)
                result = gray + (result - gray) * 1.5
                result = (result - 0.5) * 1.2 + 0.5
            
            elif preset == "muted":
                # 柔和：降低饱和度
                gray = 0.299 * result[..., 0] + 0.587 * result[..., 1] + 0.114 * result[..., 2]
                gray = gray.unsqueeze(-1).expand_as(result)
                result = gray + (result - gray) * 0.6
            
            elif preset == "cyberpunk":
                # 赛博朋克：霓虹色调
                result[..., 0] = result[..., 0] * 0.8 + 0.2 * intensity
                result[..., 2] = result[..., 2] * 1.3
                result = (result - 0.5) * 1.3 + 0.5
            
            return torch.clamp(result, 0.0, 1.0)
        
        return (process_chunk(images),)


# ============================================================
# Vignette - 暗角效果
# ============================================================

class Vignette:
    """
    添加暗角效果。
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "帧张量"}),
                "intensity": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.01,
                    "tooltip": "暗角强度"}),
                "radius": ("FLOAT", {"default": 0.8, "min": 0.1, "max": 2.0, "step": 0.01,
                    "tooltip": "暗角半径"}),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    FUNCTION = "execute"
    CATEGORY = "video/filter"

    def execute(self, images: torch.Tensor, intensity: float, radius: float):
        
        if intensity == 0:
            return (images,)
        
        height = images.shape[1]
        width = images.shape[2]
        
        # 创建暗角 mask
        y = torch.linspace(-1, 1, height)
        x = torch.linspace(-1, 1, width)
        Y, X = torch.meshgrid(y, x, indexing='ij')
        
        # 计算距离中心的距离
        dist = torch.sqrt(X**2 + Y**2)
        
        # 创建渐变 mask
        mask = torch.clamp(1 - dist / radius, 0, 1)
        mask = mask.unsqueeze(0).unsqueeze(-1)  # [1, H, W, 1]
        
        # 应用暗角
        result = images * (1 - intensity * (1 - mask))
        
        return (result,)


# ============================================================
# Node Mappings
# ============================================================

FILTER_NODE_CLASS_MAPPINGS = {
    "ColorAdjust": ColorAdjust,
    "ColorTemperature": ColorTemperature,
    "ColorGradePreset": ColorGradePreset,
    "Vignette": Vignette,
}

FILTER_NODE_DISPLAY_NAME_MAPPINGS = {
    "ColorAdjust": "Color Adjust",
    "ColorTemperature": "Color Temperature",
    "ColorGradePreset": "Color Grade Preset",
    "Vignette": "Vignette",
}