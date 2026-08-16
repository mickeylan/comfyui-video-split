"""
Video Split Nodes - Split video into segments by duration or frame count.
Enhanced with chunk processing and additional video editing features.
"""
import torch


# ============================================================
# Helper Functions
# ============================================================

def _process_in_chunks(tensor, process_func, chunk_size=64):
    """
    分块处理张量，避免内存峰值。

    Args:
        tensor: 输入张量 [B, H, W, C]
        process_func: 处理函数，接收 (chunk_tensor,) 返回处理后的张量
        chunk_size: 每块处理的帧数

    Returns:
        处理后的张量
    """
    total_frames = tensor.shape[0]
    if total_frames <= chunk_size:
        return process_func(tensor)

    chunks = []
    for start in range(0, total_frames, chunk_size):
        end = min(start + chunk_size, total_frames)
        chunk = tensor[start:end]
        processed = process_func(chunk)
        chunks.append(processed)

    return torch.cat(chunks, dim=0)


class VideoSegmentInfo:
    """
    计算视频分段信息，供循环节点使用。
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "帧张量，连接 VHS Load Video 的 image 输出"}),
                "fps": ("FLOAT", {"default": 24.0, "min": 1.0, "max": 120.0, "step": 1.0,
                    "tooltip": "视频帧率"}),
                "split_mode": (["by_duration", "by_frames"], {"default": "by_duration",
                    "tooltip": "分段模式：by_duration 按时长，by_frames 按帧数"}),
                "segment_duration": ("FLOAT", {"default": 5.0, "min": 0.1, "max": 3600.0, "step": 0.1,
                    "tooltip": "每段时长（秒）"}),
                "segment_frames": ("INT", {"default": 120, "min": 1, "max": 100000, "step": 1,
                    "tooltip": "每段帧数"}),
            },
        }

    RETURN_TYPES = ("INT", "INT", "INT")
    RETURN_NAMES = ("total_segments", "total_frames", "frames_per_segment")
    FUNCTION = "execute"
    CATEGORY = "video/split"

    def execute(self, images: torch.Tensor, fps: float, split_mode: str,
                segment_duration: float, segment_frames: int) -> tuple:
        total_frames = images.shape[0]

        if split_mode == "by_duration":
            frames_per_seg = max(1, int(segment_duration * fps))
        else:
            frames_per_seg = segment_frames

        total_segments = (total_frames + frames_per_seg - 1) // frames_per_seg

        return (total_segments, total_frames, frames_per_seg)


class GetVideoSegment:
    """
    按索引提取单个视频分段。
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "帧张量，连接 VHS Load Video 的 image 输出"}),
                "segment_index": ("INT", {"default": 0, "min": 0, "max": 10000, "step": 1,
                    "tooltip": "分段索引（从0开始），连接 forLoopStart 的 index"}),
                "frames_per_segment": ("INT", {"default": 120, "min": 1, "max": 100000, "step": 1,
                    "tooltip": "每段帧数，来自 VideoSegmentInfo"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "INT", "INT")
    RETURN_NAMES = ("segment_images", "segment_frame_count", "start_frame")
    FUNCTION = "execute"
    CATEGORY = "video/split"

    def execute(self, images: torch.Tensor, segment_index: int, frames_per_segment: int) -> tuple:
        total_frames = images.shape[0]

        start_frame = segment_index * frames_per_segment
        end_frame = min(start_frame + frames_per_segment, total_frames)

        if start_frame >= total_frames:
            raise ValueError(f"Segment index {segment_index} out of range. Video has {total_frames} frames.")

        segment_frame_count = end_frame - start_frame
        segment_images = images[start_frame:end_frame].clone()

        return (segment_images, segment_frame_count, start_frame)


class VideoSplitMultiple:
    """
    一次性分割视频为所有分段。
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "帧张量，连接 VHS Load Video"}),
                "split_mode": (["by_duration", "by_frames"], {"default": "by_duration"}),
                "fps": ("FLOAT", {"default": 24.0, "min": 1.0, "max": 120.0, "step": 1.0}),
                "segment_duration": ("FLOAT", {"default": 5.0, "min": 0.1, "max": 3600.0, "step": 0.1}),
                "segment_frames": ("INT", {"default": 120, "min": 1, "max": 100000, "step": 1}),
            },
        }

    RETURN_TYPES = ("IMAGE", "INT")
    RETURN_NAMES = ("segments", "total_segments")
    OUTPUT_IS_LIST = (True, False)
    FUNCTION = "execute"
    CATEGORY = "video/split"

    def execute(self, images: torch.Tensor, split_mode: str, fps: float,
                segment_duration: float, segment_frames: int) -> tuple:
        total_frames = images.shape[0]

        if split_mode == "by_duration":
            frames_per_seg = max(1, int(segment_duration * fps))
        else:
            frames_per_seg = segment_frames

        total_segments = (total_frames + frames_per_seg - 1) // frames_per_seg

        segments = []
        for i in range(total_segments):
            start_frame = i * frames_per_seg
            end_frame = min(start_frame + frames_per_seg, total_frames)
            segment = images[start_frame:end_frame]
            segments.append(segment)

        return (segments, total_segments)


class MergeVideoSegments:
    """
    合并多个视频分段。
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "segments": ("IMAGE", {"tooltip": "要合并的帧张量分段"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "INT")
    RETURN_NAMES = ("merged_images", "total_frames")
    INPUT_IS_LIST = True
    FUNCTION = "execute"
    CATEGORY = "video/split"

    def execute(self, segments: list) -> tuple:
        if not segments:
            raise ValueError("No video segments provided")

        merged = torch.cat(segments, dim=0)
        total_frames = merged.shape[0]

        return (merged, total_frames)


class ImageCollect:
    """
    在循环中收集图像帧。
    支持智能类型检测：可处理张量或列表类型的累积输入。
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "new_images": ("IMAGE", {"tooltip": "当前迭代要添加的图像帧"}),
            },
            "optional": {
                "images": ("IMAGE", {"tooltip": "之前累积的图像帧，第一次迭代留空"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "INT")
    RETURN_NAMES = ("accumulated", "total_frames")
    FUNCTION = "execute"
    CATEGORY = "video/split"

    def execute(self, new_images: torch.Tensor, images=None) -> tuple:
        # 处理 new_images 可能是列表的情况
        if isinstance(new_images, list):
            new_images = new_images[0] if len(new_images) == 1 else torch.cat(new_images, dim=0)

        # 第一次迭代，没有累积的图像
        if images is None:
            return (new_images, new_images.shape[0])

        # images 是张量，直接合并
        if isinstance(images, torch.Tensor):
            accumulated = torch.cat([images, new_images], dim=0)
            return (accumulated, accumulated.shape[0])

        # images 是列表，合并所有张量
        if isinstance(images, list):
            all_tensors = images + [new_images]
            accumulated = torch.cat(all_tensors, dim=0)
            return (accumulated, accumulated.shape[0])

        # 未知类型，尝试直接合并
        accumulated = torch.cat([images, new_images], dim=0)
        return (accumulated, accumulated.shape[0])


WEB_DIRECTORY = "./web"


# ============================================================
# Additional Nodes (from video-edit integration)
# ============================================================

class GetVideoFrame:
    """
    获取视频的单帧图像。
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "帧张量"}),
                "frame_index": ("INT", {"default": 0, "min": -1000000, "max": 1000000, "step": 1,
                    "tooltip": "帧索引（从0开始，支持负索引如-1表示最后一帧）"}),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("frame",)
    FUNCTION = "execute"
    CATEGORY = "video/split"

    def execute(self, images: torch.Tensor, frame_index: int) -> tuple:
        total_frames = images.shape[0]

        # 支持负索引
        if frame_index < 0:
            frame_index += total_frames

        if frame_index < 0 or frame_index >= total_frames:
            raise ValueError(f"Frame index {frame_index} out of range. Video has {total_frames} frames.")

        return (images[frame_index:frame_index+1].clone(),)


class GetVideoFramesRange:
    """
    获取视频指定范围的帧。
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "帧张量"}),
                "start_frame": ("INT", {"default": 0, "min": 0, "max": 1000000, "step": 1,
                    "tooltip": "起始帧索引（从0开始）"}),
                "end_frame": ("INT", {"default": -1, "min": -1, "max": 1000000, "step": 1,
                    "tooltip": "结束帧索引（-1表示到最后一帧）"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "INT")
    RETURN_NAMES = ("frames", "frame_count")
    FUNCTION = "execute"
    CATEGORY = "video/split"

    def execute(self, images: torch.Tensor, start_frame: int, end_frame: int) -> tuple:
        total_frames = images.shape[0]

        if start_frame < 0:
            start_frame += total_frames

        if end_frame < 0:
            end_frame = total_frames

        if start_frame < 0 or start_frame >= total_frames:
            raise ValueError(f"Start frame {start_frame} out of range. Video has {total_frames} frames.")

        if end_frame > total_frames:
            end_frame = total_frames

        if start_frame >= end_frame:
            raise ValueError(f"Start frame {start_frame} must be less than end frame {end_frame}.")

        result = images[start_frame:end_frame].clone()
        return (result, result.shape[0])


class VideoCrop:
    """
    视频裁剪，支持上下左右裁剪。使用分块处理避免内存峰值。
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "帧张量"}),
                "crop_top": ("INT", {"default": 0, "min": 0, "max": 4096, "step": 1,
                    "tooltip": "顶部裁剪像素"}),
                "crop_bottom": ("INT", {"default": 0, "min": 0, "max": 4096, "step": 1,
                    "tooltip": "底部裁剪像素"}),
                "crop_left": ("INT", {"default": 0, "min": 0, "max": 4096, "step": 1,
                    "tooltip": "左侧裁剪像素"}),
                "crop_right": ("INT", {"default": 0, "min": 0, "max": 4096, "step": 1,
                    "tooltip": "右侧裁剪像素"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "INT", "INT")
    RETURN_NAMES = ("cropped_images", "new_height", "new_width")
    FUNCTION = "execute"
    CATEGORY = "video/split"

    def execute(self, images: torch.Tensor, crop_top: int, crop_bottom: int,
                crop_left: int, crop_right: int) -> tuple:
        _, height, width, _ = images.shape

        new_height = height - crop_top - crop_bottom
        new_width = width - crop_left - crop_right

        if new_height <= 0 or new_width <= 0:
            raise ValueError(f"Invalid crop: result size {new_width}x{new_height} is invalid.")

        # 分块处理
        def crop_chunk(chunk):
            return chunk[:, crop_top:height - crop_bottom, crop_left:width - crop_right, :]

        result = _process_in_chunks(images, crop_chunk)
        return (result, new_height, new_width)


class ImageToVideo:
    """
    将单张图片转换为视频（复制帧）。
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE", {"tooltip": "单张图片"}),
                "frame_count": ("INT", {"default": 30, "min": 1, "max": 10000, "step": 1,
                    "tooltip": "输出帧数"}),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("video",)
    FUNCTION = "execute"
    CATEGORY = "video/split"

    def execute(self, image: torch.Tensor, frame_count: int) -> tuple:
        # 如果输入是多帧，只取第一帧
        if image.shape[0] > 1:
            image = image[0:1]

        # 复制帧
        video = image.repeat(frame_count, 1, 1, 1)
        return (video,)


class VideoScale:
    """
    视频缩放，使用分块处理避免内存峰值。
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "帧张量"}),
                "width": ("INT", {"default": 1920, "min": 1, "max": 8192, "step": 1,
                    "tooltip": "目标宽度"}),
                "height": ("INT", {"default": 1080, "min": 1, "max": 8192, "step": 1,
                    "tooltip": "目标高度"}),
                "method": (["nearest-exact", "bilinear", "bicubic", "area", "bicubic-lanczos"],
                    {"default": "bilinear", "tooltip": "缩放方法"}),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("scaled_images",)
    FUNCTION = "execute"
    CATEGORY = "video/split"

    def execute(self, images: torch.Tensor, width: int, height: int, method: str) -> tuple:
        from comfy.utils import common_upscale

        def scale_chunk(chunk):
            return common_upscale(chunk.movedim(-1, 1), width, height, method, "center").movedim(1, -1)

        result = _process_in_chunks(images, scale_chunk)
        return (result,)


class VideoInfo:
    """
    获取视频信息（帧数、宽高、通道数）。
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "帧张量"}),
            },
        }

    RETURN_TYPES = ("INT", "INT", "INT", "INT")
    RETURN_NAMES = ("total_frames", "height", "width", "channels")
    FUNCTION = "execute"
    CATEGORY = "video/split"

    def execute(self, images: torch.Tensor) -> tuple:
        return (images.shape[0], images.shape[1], images.shape[2], images.shape[3])


# 更新节点映射
NODE_CLASS_MAPPINGS = {
    # 核心节点
    "VideoSegmentInfo": VideoSegmentInfo,
    "GetVideoSegment": GetVideoSegment,
    "VideoSplitMultiple": VideoSplitMultiple,
    "MergeVideoSegments": MergeVideoSegments,
    "ImageCollect": ImageCollect,
    # 基础编辑节点
    "GetVideoFrame": GetVideoFrame,
    "GetVideoFramesRange": GetVideoFramesRange,
    "VideoCrop": VideoCrop,
    "ImageToVideo": ImageToVideo,
    "VideoScale": VideoScale,
    "VideoInfo": VideoInfo,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    # 核心节点
    "VideoSegmentInfo": "Video Segment Info",
    "GetVideoSegment": "Get Video Segment",
    "VideoSplitMultiple": "Video Split (Multiple)",
    "MergeVideoSegments": "Merge Video Segments",
    "ImageCollect": "Image Collect",
    # 基础编辑节点
    "GetVideoFrame": "Get Video Frame",
    "GetVideoFramesRange": "Get Video Frames Range",
    "VideoCrop": "Video Crop",
    "ImageToVideo": "Image To Video",
    "VideoScale": "Video Scale",
    "VideoInfo": "Video Info",
}


# ============================================================
# 剪映功能节点 (Video Editor Nodes)
# ============================================================

class VideoReverse:
    """
    视频倒放：将帧顺序反转。
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "帧张量"}),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("reversed_images",)
    FUNCTION = "execute"
    CATEGORY = "video/editor"

    def execute(self, images: torch.Tensor) -> tuple:
        # 反转帧顺序
        reversed_images = torch.flip(images, dims=[0])
        return (reversed_images.clone(),)


class VideoResample:
    """
    帧率转换：通过抽帧或复制帧调整视频帧率。
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "帧张量"}),
                "source_fps": ("FLOAT", {"default": 24.0, "min": 1.0, "max": 120.0, "step": 1.0,
                    "tooltip": "原始帧率"}),
                "target_fps": ("FLOAT", {"default": 30.0, "min": 1.0, "max": 120.0, "step": 1.0,
                    "tooltip": "目标帧率"}),
                "mode": (["drop", "duplicate", "blend"], {"default": "blend",
                    "tooltip": "drop=抽帧, duplicate=复制帧, blend=混合帧"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "INT")
    RETURN_NAMES = ("resampled_images", "new_frame_count")
    FUNCTION = "execute"
    CATEGORY = "video/editor"

    def execute(self, images: torch.Tensor, source_fps: float, target_fps: float, mode: str) -> tuple:
        total_frames = images.shape[0]

        # 计算目标帧数
        duration = total_frames / source_fps
        target_frames = int(duration * target_fps)

        if target_frames <= 0:
            target_frames = 1

        # 帧位置使用浮点数，索引和权重留在输入设备上。
        indices = torch.linspace(0, total_frames - 1, target_frames, device=images.device)

        if mode == "drop":
            # 直接取最近帧
            indices_int = indices.long()
            result = images[indices_int].clone()

        elif mode == "duplicate":
            # 复制最近帧
            indices_int = indices.long()
            result = images[indices_int].clone()

        elif mode == "blend":
            # 混合相邻帧（向量化实现）
            low_indices = indices.long()
            high_indices = (low_indices + 1).clamp(max=total_frames - 1)
            weights = (indices - low_indices).to(images.dtype).view(-1, 1, 1, 1)

            low_frames = images[low_indices]
            high_frames = images[high_indices]
            result = low_frames * (1 - weights) + high_frames * weights

        else:
            result = images[indices.long()].clone()

        return (result, result.shape[0])


class VideoSampleFrames:
    """
    抽帧提取：每隔 N 帧提取一帧，做延时效果。
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "帧张量"}),
                "sample_interval": ("INT", {"default": 2, "min": 1, "max": 1000000, "step": 1,
                    "tooltip": "采样间隔（每隔N帧取1帧，必须为正数）"}),
                # 用字符串输入避免 ComfyUI 前端对数字控件的隐式 0~100 限制。
                "offset": ("STRING", {"default": "0",
                    "tooltip": "起始偏移帧，支持负索引（-1表示最后一帧）和大于100的值"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "INT")
    RETURN_NAMES = ("sampled_images", "frame_count")
    FUNCTION = "execute"
    CATEGORY = "video/editor"

    def execute(self, images: torch.Tensor, sample_interval: int, offset) -> tuple:
        total_frames = images.shape[0]
        try:
            offset = int(str(offset).strip())
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Offset must be an integer, got {offset!r}.") from exc

        # 将负偏移转换为从视频末尾开始的索引；例如 -1 表示最后一帧。
        if offset < 0:
            offset += total_frames

        # 计算采样索引
        indices = list(range(offset, total_frames, sample_interval))

        if not indices:
            raise ValueError(
                f"Offset {offset} is outside the video. Video has {total_frames} frames."
            )

        result = images[indices].clone()
        return (result, result.shape[0])


class VideoTimeRemap:
    """
    时间重映射：调整视频播放速度。
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "帧张量"}),
                "speed": ("FLOAT", {"default": 1.0, "min": 0.1, "max": 10.0, "step": 0.1,
                    "tooltip": "播放速度（0.5=慢放2倍，2.0=快放2倍）"}),
                "mode": (["drop", "duplicate", "blend"], {"default": "blend",
                    "tooltip": "插帧模式"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "INT")
    RETURN_NAMES = ("remapped_images", "new_frame_count")
    FUNCTION = "execute"
    CATEGORY = "video/editor"

    def execute(self, images: torch.Tensor, speed: float, mode: str) -> tuple:
        total_frames = images.shape[0]

        # 计算新帧数
        new_frame_count = int(total_frames / speed)

        if new_frame_count <= 0:
            new_frame_count = 1

        # 帧位置使用浮点数，索引和权重留在输入设备上。
        indices = torch.linspace(0, total_frames - 1, new_frame_count, device=images.device)

        if mode == "drop" or mode == "duplicate":
            result = images[indices.long()].clone()
        else:  # blend - 向量化实现
            low_indices = indices.long()
            high_indices = (low_indices + 1).clamp(max=total_frames - 1)
            weights = (indices - low_indices).to(images.dtype).view(-1, 1, 1, 1)

            low_frames = images[low_indices]
            high_frames = images[high_indices]
            result = low_frames * (1 - weights) + high_frames * weights

        return (result, result.shape[0])


class VideoConcat:
    """
    视频拼接：将多个视频拼接在一起（水平/垂直/序列）。
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images1": ("IMAGE", {"tooltip": "视频1"}),
                "mode": (["sequence", "horizontal", "vertical"], {"default": "sequence",
                    "tooltip": "sequence=顺序拼接, horizontal=左右并排, vertical=上下并排"}),
            },
            "optional": {
                "images2": ("IMAGE", {"tooltip": "视频2"}),
                "images3": ("IMAGE", {"tooltip": "视频3"}),
                "images4": ("IMAGE", {"tooltip": "视频4"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "INT")
    RETURN_NAMES = ("concatenated_images", "total_frames")
    FUNCTION = "execute"
    CATEGORY = "video/editor"

    def execute(self, images1: torch.Tensor, mode: str,
                images2=None, images3=None, images4=None) -> tuple:
        videos = [images1]
        videos.extend(video for video in (images2, images3, images4) if video is not None)

        # 检查尺寸一致性（用于 horizontal/vertical 模式）
        if mode in ["horizontal", "vertical"]:
            ref_h, ref_w = videos[0].shape[1], videos[0].shape[2]
            for v in videos:
                if v.shape[1] != ref_h or v.shape[2] != ref_w:
                    raise ValueError(
                        f"All videos must have the same spatial dimensions for {mode} mode. "
                        f"Expected {ref_h}x{ref_w}, got {v.shape[1]}x{v.shape[2]}"
                    )

        if mode == "sequence":
            # 顺序拼接（前后连接）
            result = torch.cat(videos, dim=0)

        elif mode == "horizontal":
            # 水平拼接（左右并排）
            # 找到最小帧数
            min_frames = min(v.shape[0] for v in videos)
            # 截取到相同帧数
            videos = [v[:min_frames] for v in videos]
            # 拼接
            result = torch.cat(videos, dim=2)  # 在宽度维度拼接

        elif mode == "vertical":
            # 垂直拼接（上下并排）
            min_frames = min(v.shape[0] for v in videos)
            videos = [v[:min_frames] for v in videos]
            result = torch.cat(videos, dim=1)  # 在高度维度拼接

        else:
            result = torch.cat(videos, dim=0)

        return (result, result.shape[0])


class VideoFade:
    """
    淡入淡出：为视频添加淡入淡出效果。
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "帧张量"}),
                "fade_in_frames": ("INT", {"default": 10, "min": 0, "max": 1000, "step": 1,
                    "tooltip": "淡入帧数"}),
                "fade_out_frames": ("INT", {"default": 10, "min": 0, "max": 1000, "step": 1,
                    "tooltip": "淡出帧数"}),
                "fade_color": (["black", "white"], {"default": "black",
                    "tooltip": "淡入淡出颜色"}),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("faded_images",)
    FUNCTION = "execute"
    CATEGORY = "video/editor"

    def execute(self, images: torch.Tensor, fade_in_frames: int, fade_out_frames: int,
                fade_color: str) -> tuple:
        total_frames = images.shape[0]
        result = images.clone()

        # 淡入
        if fade_in_frames > 0:
            for i in range(min(fade_in_frames, total_frames)):
                alpha = i / fade_in_frames
                result[i] = images[i] * alpha
                if fade_color == "white":
                    result[i] = result[i] + (1 - alpha)

        # 淡出
        if fade_out_frames > 0:
            fade_start = max(0, total_frames - fade_out_frames)
            for i in range(fade_start, total_frames):
                alpha = (total_frames - i) / fade_out_frames
                result[i] = images[i] * alpha
                if fade_color == "white":
                    result[i] = result[i] + (1 - alpha)

        return (result,)


class VideoOverlay:
    """
    视频叠加：将一个视频叠加到另一个视频上。
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "background": ("IMAGE", {"tooltip": "背景视频"}),
                "overlay": ("IMAGE", {"tooltip": "叠加视频"}),
                "opacity": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.05,
                    "tooltip": "叠加透明度"}),
                "x": ("INT", {"default": 0, "min": -4096, "max": 4096, "step": 1,
                    "tooltip": "X位置"}),
                "y": ("INT", {"default": 0, "min": -4096, "max": 4096, "step": 1,
                    "tooltip": "Y位置"}),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("output_images",)
    FUNCTION = "execute"
    CATEGORY = "video/editor"

    def execute(self, background: torch.Tensor, overlay: torch.Tensor,
                opacity: float, x: int, y: int) -> tuple:
        # 取最小帧数
        min_frames = min(background.shape[0], overlay.shape[0])

        bg = background[:min_frames].clone()
        ol = overlay[:min_frames]

        _, bg_h, bg_w, _ = bg.shape
        _, ol_h, ol_w, _ = ol.shape

        # 计算叠加区域
        x1 = max(0, x)
        y1 = max(0, y)
        x2 = min(bg_w, x + ol_w)
        y2 = min(bg_h, y + ol_h)

        # 叠加区域大小
        ol_x1 = max(0, -x)
        ol_y1 = max(0, -y)
        ol_x2 = ol_x1 + (x2 - x1)
        ol_y2 = ol_y1 + (y2 - y1)

        if x2 > x1 and y2 > y1:
            # 混合
            bg_region = bg[:, y1:y2, x1:x2, :]
            ol_region = ol[:, ol_y1:ol_y2, ol_x1:ol_x2, :]

            blended = bg_region * (1 - opacity) + ol_region * opacity
            bg[:, y1:y2, x1:x2, :] = blended

        return (bg,)


class FrameInterpolate:
    """
    帧插值：在帧之间插入中间帧，用于慢动作效果。
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "帧张量"}),
                "interpolate_factor": ("INT", {"default": 2, "min": 1, "max": 10, "step": 1,
                    "tooltip": "插值倍数（2=每帧之间插入1帧）"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "INT")
    RETURN_NAMES = ("interpolated_images", "new_frame_count")
    FUNCTION = "execute"
    CATEGORY = "video/editor"

    def execute(self, images: torch.Tensor, interpolate_factor: int) -> tuple:
        if interpolate_factor <= 1:
            return (images.clone(), images.shape[0])

        total_frames = images.shape[0]
        new_frames = []

        for i in range(total_frames - 1):
            new_frames.append(images[i])

            # 插入中间帧
            for j in range(1, interpolate_factor):
                weight = j / interpolate_factor
                interpolated = images[i] * (1 - weight) + images[i + 1] * weight
                new_frames.append(interpolated)

        # 添加最后一帧
        new_frames.append(images[-1])

        result = torch.stack(new_frames)
        return (result, result.shape[0])


class FrameDeduplicate:
    """
    帧去重：去除相似帧，减小视频体积。
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "帧张量"}),
                "threshold": ("FLOAT", {"default": 0.01, "min": 0.001, "max": 0.5, "step": 0.001,
                    "tooltip": "相似度阈值（越小越严格）"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "INT")
    RETURN_NAMES = ("deduplicated_images", "frame_count")
    FUNCTION = "execute"
    CATEGORY = "video/editor"

    def execute(self, images: torch.Tensor, threshold: float) -> tuple:
        total_frames = images.shape[0]

        if total_frames <= 1:
            return (images.clone(), total_frames)

        # 分块处理避免内存峰值
        kept_frames = [images[0]]

        for i in range(1, total_frames):
            # 计算与上一帧的差异
            diff = torch.mean(torch.abs(images[i] - kept_frames[-1])).item()

            if diff > threshold:
                kept_frames.append(images[i])

        result = torch.stack(kept_frames)
        return (result, result.shape[0])


# 更新节点映射（包含所有节点）
NODE_CLASS_MAPPINGS.update({
    # 剪映功能节点
    "VideoReverse": VideoReverse,
    "VideoResample": VideoResample,
    "VideoSplitSampleFrames": VideoSampleFrames,
    "VideoTimeRemap": VideoTimeRemap,
    "VideoConcat": VideoConcat,
    "VideoFade": VideoFade,
    "VideoOverlay": VideoOverlay,
    "FrameInterpolate": FrameInterpolate,
    "FrameDeduplicate": FrameDeduplicate,
})

NODE_DISPLAY_NAME_MAPPINGS.update({
    # 剪映功能节点
    "VideoReverse": "Video Reverse",
    "VideoResample": "Video Resample",
    "VideoSplitSampleFrames": "Video Sample Frames (Video Split)",
    "VideoTimeRemap": "Video Time Remap",
    "VideoConcat": "Video Concat",
    "VideoFade": "Video Fade",
    "VideoOverlay": "Video Overlay",
    "FrameInterpolate": "Frame Interpolate",
    "FrameDeduplicate": "Frame Deduplicate",
})
