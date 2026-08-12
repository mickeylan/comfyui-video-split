"""
特效处理节点 - 抠像、背景替换等
"""
import torch
import numpy as np


# ============================================================
# Background Remove - 角色抠像
# ============================================================

class BackgroundRemove:
    """
    角色抠像：移除背景，生成透明背景。
    支持多种抠像模式。
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "帧张量"}),
                "mode": (["color_key", "luma_key", "edge_detect"], {"default": "color_key",
                    "tooltip": "抠像模式：color_key=色键, luma_key=亮度键, edge_detect=边缘检测"}),
                "key_color": ("STRING", {"default": "#00FF00", "tooltip": "色键颜色（十六进制）"}),
                "threshold": ("FLOAT", {"default": 0.3, "min": 0.0, "max": 1.0, "step": 0.01,
                    "tooltip": "抠像阈值"}),
                "edge_softness": ("FLOAT", {"default": 0.1, "min": 0.0, "max": 1.0, "step": 0.01,
                    "tooltip": "边缘柔和度"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "MASK")
    RETURN_NAMES = ("images", "mask")
    FUNCTION = "execute"
    CATEGORY = "video/effect"

    def hex_to_rgb(self, hex_color):
        """十六进制颜色转 RGB"""
        hex_color = hex_color.lstrip('#')
        return tuple(int(hex_color[i:i+2], 16) / 255.0 for i in (0, 2, 4))

    def execute(self, images: torch.Tensor, mode: str, key_color: str, 
                threshold: float, edge_softness: float):
        
        total_frames = images.shape[0]
        
        # 解析色键颜色
        try:
            r, g, b = self.hex_to_rgb(key_color)
        except:
            r, g, b = 0.0, 1.0, 0.0  # 默认绿色
        
        def process_chunk(chunk):
            batch_size = chunk.shape[0]
            height = chunk.shape[1]
            width = chunk.shape[2]
            
            result_frames = []
            result_masks = []
            
            for i in range(batch_size):
                frame = chunk[i]
                
                if mode == "color_key":
                    # 色键抠像：移除指定颜色
                    # 计算每个像素与色键颜色的距离
                    color_dist = torch.sqrt(
                        (frame[..., 0] - r) ** 2 +
                        (frame[..., 1] - g) ** 2 +
                        (frame[..., 2] - b) ** 2
                    )
                    
                    # 创建 mask
                    mask = (color_dist > threshold).float()
                    
                    # 边缘柔和化
                    if edge_softness > 0:
                        # 简单的边缘模糊
                        mask = mask.unsqueeze(0).unsqueeze(0)
                        kernel_size = int(edge_softness * 20) + 1
                        # 使用平均池化模糊边缘
                        from torch.nn.functional import avg_pool2d
                        mask = avg_pool2d(mask, kernel_size, stride=1, padding=kernel_size//2)
                        mask = mask.squeeze()
                    
                    # 应用 mask
                    mask_3d = mask.unsqueeze(-1).expand_as(frame)
                    result = frame * mask_3d
                    
                elif mode == "luma_key":
                    # 亮度键：移除暗色背景
                    brightness = frame.mean(dim=-1)
                    mask = (brightness > threshold).float()
                    
                    # 边缘柔和化
                    if edge_softness > 0:
                        mask = mask.unsqueeze(0).unsqueeze(0)
                        kernel_size = int(edge_softness * 20) + 1
                        from torch.nn.functional import avg_pool2d
                        mask = avg_pool2d(mask, kernel_size, stride=1, padding=kernel_size//2)
                        mask = mask.squeeze()
                    
                    mask_3d = mask.unsqueeze(-1).expand_as(frame)
                    result = frame * mask_3d
                    
                elif mode == "edge_detect":
                    # 边缘检测抠像：保留边缘，移除中心
                    # 简单的边缘检测
                    gray = 0.299 * frame[..., 0] + 0.587 * frame[..., 1] + 0.114 * frame[..., 2]
                    
                    # Sobel 边缘检测
                    sobel_x = torch.tensor([[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]], dtype=torch.float32)
                    sobel_y = sobel_x.T
                    
                    # 简化处理：使用梯度检测边缘
                    grad_x = torch.abs(gray[:, 1:] - gray[:, :-1])
                    grad_y = torch.abs(gray[1:, :] - gray[:-1, :])
                    
                    # 填充使尺寸一致
                    grad_x = torch.nn.functional.pad(grad_x, (0, 1))
                    grad_y = torch.nn.functional.pad(grad_y, (0, 0, 0, 1))
                    
                    edge = torch.sqrt(grad_x ** 2 + grad_y ** 2)
                    mask = (edge > threshold).float()
                    
                    mask_3d = mask.unsqueeze(-1).expand_as(frame)
                    result = frame * mask_3d
                    
                else:
                    result = frame
                    mask = torch.ones(frame.shape[0], frame.shape[1])
                
                result_frames.append(result)
                result_masks.append(mask)
            
            return torch.stack(result_frames), torch.stack(result_masks)
        
        images_result, mask_result = process_chunk(images)
        
        return (images_result, mask_result)


# ============================================================
# Background Replace - 背景替换
# ============================================================

class BackgroundReplace:
    """
    背景替换：将抠像后的角色放到新背景上。
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "foreground": ("IMAGE", {"tooltip": "前景（角色）帧张量"}),
                "background": ("IMAGE", {"tooltip": "背景帧张量"}),
            },
            "optional": {
                "mask": ("MASK", {"tooltip": "抠像 mask（来自 Background Remove）"}),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    FUNCTION = "execute"
    CATEGORY = "video/effect"

    def execute(self, foreground: torch.Tensor, background: torch.Tensor, 
                mask: torch.Tensor = None):
        
        # 确保背景和前景帧数一致
        min_frames = min(foreground.shape[0], background.shape[0])
        fg = foreground[:min_frames]
        bg = background[:min_frames]
        
        # 调整背景大小以匹配前景
        if bg.shape[1] != fg.shape[1] or bg.shape[2] != fg.shape[2]:
            # 需要缩放背景
            from comfy.utils import common_upscale
            bg = common_upscale(bg.movedim(-1, 1), fg.shape[2], fg.shape[1], 'bilinear', 'center').movedim(1, -1)
        
        # 如果没有 mask，使用简单的亮度键
        if mask is None:
            # 简单的亮度键作为默认
            brightness = fg.mean(dim=-1)
            mask = (brightness > 0.05).float()
        
        # 确保 mask 维度正确
        if len(mask.shape) == 2:
            mask = mask.unsqueeze(0).expand(min_frames, -1, -1)
        elif mask.shape[0] < min_frames:
            # mask 帧数不够，复制最后一帧
            pad_frames = min_frames - mask.shape[0]
            mask = torch.cat([mask, mask[-1:].expand(pad_frames, -1, -1)], dim=0)
        
        # 确保 mask 维度正确
        mask = mask[:min_frames]
        mask_3d = mask.unsqueeze(-1).expand_as(fg)
        
        # 合成
        result = fg * mask_3d + bg * (1 - mask_3d)
        
        return (result,)


# ============================================================
# Color Key - 色键抠像（简化版）
# ============================================================

class ColorKey:
    """
    色键抠像：移除指定颜色背景。
    常用于绿幕/蓝幕抠像。
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "帧张量"}),
                "key_color": (["green", "blue", "red", "white", "black"], 
                    {"default": "green", "tooltip": "要移除的颜色"}),
                "tolerance": ("FLOAT", {"default": 0.3, "min": 0.0, "max": 1.0, "step": 0.01,
                    "tooltip": "颜色容差"}),
                "softness": ("FLOAT", {"default": 0.1, "min": 0.0, "max": 1.0, "step": 0.01,
                    "tooltip": "边缘柔和度"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "MASK")
    RETURN_NAMES = ("images", "mask")
    FUNCTION = "execute"
    CATEGORY = "video/effect"

    def execute(self, images: torch.Tensor, key_color: str, 
                tolerance: float, softness: float):
        
        # 预设颜色
        colors = {
            "green": (0.0, 1.0, 0.0),
            "blue": (0.0, 0.0, 1.0),
            "red": (1.0, 0.0, 0.0),
            "white": (1.0, 1.0, 1.0),
            "black": (0.0, 0.0, 0.0),
        }
        
        r, g, b = colors.get(key_color, (0.0, 1.0, 0.0))
        
        def process_chunk(chunk):
            result_frames = []
            result_masks = []
            
            for i in range(chunk.shape[0]):
                frame = chunk[i]
                
                # 计算颜色距离
                color_dist = torch.sqrt(
                    (frame[..., 0] - r) ** 2 +
                    (frame[..., 1] - g) ** 2 +
                    (frame[..., 2] - b) ** 2
                )
                
                # 创建 mask（距离小于阈值为背景，要移除）
                mask = (color_dist > tolerance).float()
                
                # 边缘柔和化
                if softness > 0:
                    # 计算软边缘
                    soft_threshold = tolerance + softness
                    hard_mask = (color_dist > soft_threshold).float()
                    soft_mask = (color_dist > tolerance).float()
                    
                    # 在硬边界和软边界之间渐变
                    mask = hard_mask + (soft_mask - hard_mask) * torch.clamp(
                        (color_dist - tolerance) / softness, 0, 1
                    )
                
                # 应用 mask
                mask_3d = mask.unsqueeze(-1).expand_as(frame)
                result = frame * mask_3d
                
                result_frames.append(result)
                result_masks.append(mask)
            
            return torch.stack(result_frames), torch.stack(result_masks)
        
        images_result, mask_result = process_chunk(images)
        
        return (images_result, mask_result)


# ============================================================
# Simple Background Remove - 简单背景移除
# ============================================================

class SimpleBackgroundRemove:
    """
    简单背景移除：移除纯色背景。
    适用于纯色背景的 AI 生成图像。
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "帧张量"}),
                "bg_color": ("STRING", {"default": "#FFFFFF", "tooltip": "背景颜色（十六进制）"}),
                "tolerance": ("FLOAT", {"default": 0.1, "min": 0.0, "max": 0.5, "step": 0.01,
                    "tooltip": "颜色容差"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "MASK")
    RETURN_NAMES = ("images", "mask")
    FUNCTION = "execute"
    CATEGORY = "video/effect"

    def execute(self, images: torch.Tensor, bg_color: str, tolerance: float):
        
        # 解析颜色
        try:
            hex_color = bg_color.lstrip('#')
            r = int(hex_color[0:2], 16) / 255.0
            g = int(hex_color[2:4], 16) / 255.0
            b = int(hex_color[4:6], 16) / 255.0
        except:
            r, g, b = 1.0, 1.0, 1.0  # 默认白色
        
        def process_chunk(chunk):
            result_frames = []
            result_masks = []
            
            for i in range(chunk.shape[0]):
                frame = chunk[i]
                
                # 计算与背景颜色的差异
                diff = torch.abs(frame - torch.tensor([r, g, b]))
                max_diff = diff.max(dim=-1)[0]
                
                # 创建 mask
                mask = (max_diff > tolerance).float()
                
                # 应用 mask
                mask_3d = mask.unsqueeze(-1).expand_as(frame)
                result = frame * mask_3d
                
                result_frames.append(result)
                result_masks.append(mask)
            
            return torch.stack(result_frames), torch.stack(result_masks)
        
        images_result, mask_result = process_chunk(images)
        
        return (images_result, mask_result)


# ============================================================
# Node Mappings
# ============================================================

EFFECT_NODE_CLASS_MAPPINGS = {
    "BackgroundRemove": BackgroundRemove,
    "BackgroundReplace": BackgroundReplace,
    "ColorKey": ColorKey,
    "SimpleBackgroundRemove": SimpleBackgroundRemove,
}

EFFECT_NODE_DISPLAY_NAME_MAPPINGS = {
    "BackgroundRemove": "Background Remove",
    "BackgroundReplace": "Background Replace",
    "ColorKey": "Color Key",
    "SimpleBackgroundRemove": "Simple Background Remove",
}