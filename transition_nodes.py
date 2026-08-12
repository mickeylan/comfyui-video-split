"""
转场效果处理节点
"""
import torch
import numpy as np
import math


# ============================================================
# Transition Slide - 滑动转场
# ============================================================

class TransitionSlide:
    """
    滑动转场效果。
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images1": ("IMAGE", {"tooltip": "视频1帧张量"}),
                "images2": ("IMAGE", {"tooltip": "视频2帧张量"}),
                "transition_frames": ("INT", {"default": 30, "min": 1, "max": 300,
                    "tooltip": "转场帧数"}),
                "direction": (["left", "right", "up", "down"], {"default": "left",
                    "tooltip": "滑动方向"}),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    FUNCTION = "execute"
    CATEGORY = "video/transition"

    def execute(self, images1: torch.Tensor, images2: torch.Tensor,
                transition_frames: int, direction: str):
        
        # 取两个视频的最小帧数
        min_frames = min(images1.shape[0], images2.shape[0])
        
        height = images1.shape[1]
        width = images1.shape[2]
        
        result_frames = []
        
        # 前 50% 显示视频1
        half_frames = min_frames // 2
        
        for i in range(half_frames):
            result_frames.append(images1[i])
        
        # 转场效果
        for i in range(transition_frames):
            progress = i / transition_frames
            
            # 获取当前帧
            frame1_idx = min(half_frames + i, images1.shape[0] - 1)
            frame2_idx = min(i, images2.shape[0] - 1)
            
            frame1 = images1[frame1_idx]
            frame2 = images2[frame2_idx]
            
            # 创建转场帧
            result = torch.zeros_like(frame1)
            
            if direction == "left":
                offset = int(width * progress)
                result[:, :width-offset, :] = frame1[:, offset:, :]
                result[:, width-offset:, :] = frame2[:, :offset, :]
            elif direction == "right":
                offset = int(width * progress)
                result[:, offset:, :] = frame1[:, :width-offset, :]
                result[:, :offset, :] = frame2[:, width-offset:, :]
            elif direction == "up":
                offset = int(height * progress)
                result[:height-offset, :, :] = frame1[offset:, :, :]
                result[height-offset:, :, :] = frame2[:offset, :, :]
            elif direction == "down":
                offset = int(height * progress)
                result[offset:, :, :] = frame1[:height-offset, :, :]
                result[:offset, :, :] = frame2[height-offset:, :, :]
            
            result_frames.append(result)
        
        # 剩余帧显示视频2
        remaining_start = half_frames + transition_frames
        for i in range(remaining_start, min_frames):
            idx = min(i, images2.shape[0] - 1)
            result_frames.append(images2[idx])
        
        return (torch.stack(result_frames),)


# ============================================================
# Transition Zoom - 缩放转场
# ============================================================

class TransitionZoom:
    """
    缩放转场效果。
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images1": ("IMAGE", {"tooltip": "视频1帧张量"}),
                "images2": ("IMAGE", {"tooltip": "视频2帧张量"}),
                "transition_frames": ("INT", {"default": 30, "min": 1, "max": 300,
                    "tooltip": "转场帧数"}),
                "mode": (["zoom_in", "zoom_out", "cross_zoom"], {"default": "cross_zoom",
                    "tooltip": "缩放模式"}),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    FUNCTION = "execute"
    CATEGORY = "video/transition"

    def execute(self, images1: torch.Tensor, images2: torch.Tensor,
                transition_frames: int, mode: str):
        
        min_frames = min(images1.shape[0], images2.shape[0])
        height = images1.shape[1]
        width = images1.shape[2]
        
        result_frames = []
        half_frames = min_frames // 2
        
        # 前半段显示视频1
        for i in range(half_frames):
            result_frames.append(images1[i])
        
        # 转场效果
        for i in range(transition_frames):
            progress = i / transition_frames
            
            frame1_idx = min(half_frames + i, images1.shape[0] - 1)
            frame2_idx = min(i, images2.shape[0] - 1)
            
            frame1 = images1[frame1_idx]
            frame2 = images2[frame2_idx]
            
            result = torch.zeros_like(frame1)
            
            if mode == "zoom_in":
                # 视频1 放大消失，视频2 从中心出现
                scale = 1 + progress
                # 简化处理：使用 alpha 混合
                alpha = 1 - progress
                result = frame1 * alpha + frame2 * (1 - alpha)
            
            elif mode == "zoom_out":
                # 视频1 缩小消失，视频2 放大出现
                alpha = progress
                result = frame1 * (1 - alpha) + frame2 * alpha
            
            elif mode == "cross_zoom":
                # 交叉缩放
                scale1 = 1 + progress * 0.5
                scale2 = 1 + (1 - progress) * 0.5
                # 简化：使用混合
                result = frame1 * (1 - progress) + frame2 * progress
            
            result_frames.append(result)
        
        # 后半段显示视频2
        remaining_start = half_frames + transition_frames
        for i in range(remaining_start, min_frames):
            idx = min(i, images2.shape[0] - 1)
            result_frames.append(images2[idx])
        
        return (torch.stack(result_frames),)


# ============================================================
# Transition Wipe - 擦除转场
# ============================================================

class TransitionWipe:
    """
    擦除转场效果。
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images1": ("IMAGE", {"tooltip": "视频1帧张量"}),
                "images2": ("IMAGE", {"tooltip": "视频2帧张量"}),
                "transition_frames": ("INT", {"default": 30, "min": 1, "max": 300,
                    "tooltip": "转场帧数"}),
                "direction": (["left_to_right", "right_to_left", "top_to_bottom", "bottom_to_top"],
                    {"default": "left_to_right", "tooltip": "擦除方向"}),
                "softness": ("FLOAT", {"default": 0.1, "min": 0.0, "max": 1.0,
                    "tooltip": "边缘柔和度"}),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    FUNCTION = "execute"
    CATEGORY = "video/transition"

    def execute(self, images1: torch.Tensor, images2: torch.Tensor,
                transition_frames: int, direction: str, softness: float):
        
        min_frames = min(images1.shape[0], images2.shape[0])
        height = images1.shape[1]
        width = images1.shape[2]
        
        result_frames = []
        half_frames = min_frames // 2
        
        # 前半段
        for i in range(half_frames):
            result_frames.append(images1[i])
        
        # 转场
        for i in range(transition_frames):
            progress = i / transition_frames
            
            frame1_idx = min(half_frames + i, images1.shape[0] - 1)
            frame2_idx = min(i, images2.shape[0] - 1)
            
            frame1 = images1[frame1_idx]
            frame2 = images2[frame2_idx]
            
            result = frame1.clone()
            
            # 创建 mask
            if direction == "left_to_right":
                split = int(width * progress)
                soft_width = int(width * softness)
                result[:, :split, :] = frame2[:, :split, :]
            elif direction == "right_to_left":
                split = int(width * (1 - progress))
                result[:, split:, :] = frame2[:, split:, :]
            elif direction == "top_to_bottom":
                split = int(height * progress)
                result[:split, :, :] = frame2[:split, :, :]
            elif direction == "bottom_to_top":
                split = int(height * (1 - progress))
                result[split:, :, :] = frame2[split:, :, :]
            
            result_frames.append(result)
        
        # 后半段
        remaining_start = half_frames + transition_frames
        for i in range(remaining_start, min_frames):
            idx = min(i, images2.shape[0] - 1)
            result_frames.append(images2[idx])
        
        return (torch.stack(result_frames),)


# ============================================================
# Transition Dissolve - 溶解转场
# ============================================================

class TransitionDissolve:
    """
    溶解转场效果（淡入淡出混合）。
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images1": ("IMAGE", {"tooltip": "视频1帧张量"}),
                "images2": ("IMAGE", {"tooltip": "视频2帧张量"}),
                "transition_frames": ("INT", {"default": 30, "min": 1, "max": 300,
                    "tooltip": "转场帧数"}),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    FUNCTION = "execute"
    CATEGORY = "video/transition"

    def execute(self, images1: torch.Tensor, images2: torch.Tensor,
                transition_frames: int):
        
        min_frames = min(images1.shape[0], images2.shape[0])
        result_frames = []
        half_frames = min_frames // 2
        
        # 前半段
        for i in range(half_frames):
            result_frames.append(images1[i])
        
        # 转场：淡入淡出混合
        for i in range(transition_frames):
            progress = i / transition_frames
            
            frame1_idx = min(half_frames + i, images1.shape[0] - 1)
            frame2_idx = min(i, images2.shape[0] - 1)
            
            frame1 = images1[frame1_idx]
            frame2 = images2[frame2_idx]
            
            # 混合
            result = frame1 * (1 - progress) + frame2 * progress
            result_frames.append(result)
        
        # 后半段
        remaining_start = half_frames + transition_frames
        for i in range(remaining_start, min_frames):
            idx = min(i, images2.shape[0] - 1)
            result_frames.append(images2[idx])
        
        return (torch.stack(result_frames),)


# ============================================================
# Node Mappings
# ============================================================

TRANSITION_NODE_CLASS_MAPPINGS = {
    "TransitionSlide": TransitionSlide,
    "TransitionZoom": TransitionZoom,
    "TransitionWipe": TransitionWipe,
    "TransitionDissolve": TransitionDissolve,
}

TRANSITION_NODE_DISPLAY_NAME_MAPPINGS = {
    "TransitionSlide": "Transition Slide",
    "TransitionZoom": "Transition Zoom",
    "TransitionWipe": "Transition Wipe",
    "TransitionDissolve": "Transition Dissolve",
}