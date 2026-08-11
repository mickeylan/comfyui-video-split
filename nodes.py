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
                "frame_index": ("INT", {"default": 0, "min": 0, "max": 1000000, "step": 1,
                    "tooltip": "帧索引（从0开始）"}),
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
    # 新增节点
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
    # 新增节点
    "GetVideoFrame": "Get Video Frame",
    "GetVideoFramesRange": "Get Video Frames Range",
    "VideoCrop": "Video Crop",
    "ImageToVideo": "Image To Video",
    "VideoScale": "Video Scale",
    "VideoInfo": "Video Info",
}