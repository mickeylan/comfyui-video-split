"""
转场效果处理节点。
"""
import torch
import torch.nn.functional as F


def _prepare_transition(images1, images2, transition_frames):
    if images1.shape[1:] != images2.shape[1:]:
        raise ValueError(
            f"Transition inputs must have the same frame shape, got {tuple(images1.shape[1:])} and {tuple(images2.shape[1:])}."
        )

    overlap = min(transition_frames, images1.shape[0], images2.shape[0])
    first = images1[:-overlap]
    tail1 = images1[-overlap:]
    head2 = images2[:overlap]
    last = images2[overlap:]
    progress = torch.linspace(0.0, 1.0, overlap + 2, device=images1.device, dtype=images1.dtype)[1:-1]
    return first, tail1, head2, last, progress


def _finish_transition(first, transition, last):
    return (torch.cat((first, transition, last), dim=0),)


def _scale_frame(frame, scale):
    height, width = frame.shape[:2]
    channels_first = frame.permute(2, 0, 1).unsqueeze(0)
    scaled_height = max(1, round(height * scale))
    scaled_width = max(1, round(width * scale))
    scaled = F.interpolate(channels_first, size=(scaled_height, scaled_width), mode="bilinear", align_corners=False)

    if scale >= 1.0:
        top = (scaled_height - height) // 2
        left = (scaled_width - width) // 2
        scaled = scaled[:, :, top:top + height, left:left + width]
    else:
        pad_height = height - scaled_height
        pad_width = width - scaled_width
        scaled = F.pad(scaled, (pad_width // 2, pad_width - pad_width // 2, pad_height // 2, pad_height - pad_height // 2))

    return scaled.squeeze(0).permute(1, 2, 0)


class TransitionSlide:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images1": ("IMAGE", {"tooltip": "视频1帧张量"}),
                "images2": ("IMAGE", {"tooltip": "视频2帧张量"}),
                "transition_frames": ("INT", {"default": 30, "min": 1, "max": 300, "tooltip": "转场帧数"}),
                "direction": (["left", "right", "up", "down"], {"default": "left", "tooltip": "滑动方向"}),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    FUNCTION = "execute"
    CATEGORY = "video/transition"

    def execute(self, images1, images2, transition_frames, direction):
        first, tail1, head2, last, progress = _prepare_transition(images1, images2, transition_frames)
        height, width = images1.shape[1:3]
        frames = []
        for frame1, frame2, amount in zip(tail1, head2, progress):
            result = torch.empty_like(frame1)
            if direction in ("left", "right"):
                offset = min(width, round(width * amount.item()))
                if direction == "left":
                    result[:, :width - offset] = frame1[:, offset:]
                    result[:, width - offset:] = frame2[:, :offset]
                else:
                    result[:, offset:] = frame1[:, :width - offset]
                    result[:, :offset] = frame2[:, width - offset:]
            else:
                offset = min(height, round(height * amount.item()))
                if direction == "up":
                    result[:height - offset] = frame1[offset:]
                    result[height - offset:] = frame2[:offset]
                else:
                    result[offset:] = frame1[:height - offset]
                    result[:offset] = frame2[height - offset:]
            frames.append(result)
        return _finish_transition(first, torch.stack(frames), last)


class TransitionZoom:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images1": ("IMAGE", {"tooltip": "视频1帧张量"}),
                "images2": ("IMAGE", {"tooltip": "视频2帧张量"}),
                "transition_frames": ("INT", {"default": 30, "min": 1, "max": 300, "tooltip": "转场帧数"}),
                "mode": (["zoom_in", "zoom_out", "cross_zoom"], {"default": "cross_zoom", "tooltip": "缩放模式"}),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    FUNCTION = "execute"
    CATEGORY = "video/transition"

    def execute(self, images1, images2, transition_frames, mode):
        first, tail1, head2, last, progress = _prepare_transition(images1, images2, transition_frames)
        frames = []
        for frame1, frame2, amount in zip(tail1, head2, progress):
            value = amount.item()
            if mode == "zoom_in":
                scaled1 = _scale_frame(frame1, 1.0 + value * 0.5)
                scaled2 = frame2
            elif mode == "zoom_out":
                scaled1 = _scale_frame(frame1, 1.0 - value * 0.5)
                scaled2 = frame2
            else:
                scaled1 = _scale_frame(frame1, 1.0 + value * 0.35)
                scaled2 = _scale_frame(frame2, 0.65 + value * 0.35)
            frames.append(scaled1 * (1.0 - amount) + scaled2 * amount)
        return _finish_transition(first, torch.stack(frames), last)


class TransitionWipe:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images1": ("IMAGE", {"tooltip": "视频1帧张量"}),
                "images2": ("IMAGE", {"tooltip": "视频2帧张量"}),
                "transition_frames": ("INT", {"default": 30, "min": 1, "max": 300, "tooltip": "转场帧数"}),
                "direction": (["left_to_right", "right_to_left", "top_to_bottom", "bottom_to_top"], {"default": "left_to_right", "tooltip": "擦除方向"}),
                "softness": ("FLOAT", {"default": 0.1, "min": 0.0, "max": 1.0, "tooltip": "边缘柔和度"}),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    FUNCTION = "execute"
    CATEGORY = "video/transition"

    def execute(self, images1, images2, transition_frames, direction, softness):
        first, tail1, head2, last, progress = _prepare_transition(images1, images2, transition_frames)
        height, width = images1.shape[1:3]
        horizontal = direction in ("left_to_right", "right_to_left")
        length = width if horizontal else height
        positions = torch.linspace(0.0, 1.0, length, device=images1.device, dtype=images1.dtype)
        if direction in ("right_to_left", "bottom_to_top"):
            positions = positions.flip(0)

        frames = []
        edge = max(softness, 1.0 / length)
        for frame1, frame2, amount in zip(tail1, head2, progress):
            mask = ((amount - positions) / edge + 0.5).clamp(0.0, 1.0)
            mask = mask.view(1, width, 1) if horizontal else mask.view(height, 1, 1)
            frames.append(frame1 * (1.0 - mask) + frame2 * mask)
        return _finish_transition(first, torch.stack(frames), last)


class TransitionDissolve:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images1": ("IMAGE", {"tooltip": "视频1帧张量"}),
                "images2": ("IMAGE", {"tooltip": "视频2帧张量"}),
                "transition_frames": ("INT", {"default": 30, "min": 1, "max": 300, "tooltip": "转场帧数"}),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    FUNCTION = "execute"
    CATEGORY = "video/transition"

    def execute(self, images1, images2, transition_frames):
        first, tail1, head2, last, progress = _prepare_transition(images1, images2, transition_frames)
        weights = progress.view(-1, 1, 1, 1)
        transition = tail1 * (1.0 - weights) + head2 * weights
        return _finish_transition(first, transition, last)


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
