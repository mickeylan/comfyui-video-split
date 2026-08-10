"""
Video Split Nodes - Split video into segments by duration or frame count.
"""
import torch


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


# Node mappings
NODE_CLASS_MAPPINGS = {
    "VideoSegmentInfo": VideoSegmentInfo,
    "GetVideoSegment": GetVideoSegment,
    "VideoSplitMultiple": VideoSplitMultiple,
    "MergeVideoSegments": MergeVideoSegments,
    "ImageCollect": ImageCollect,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "VideoSegmentInfo": "Video Segment Info",
    "GetVideoSegment": "Get Video Segment",
    "VideoSplitMultiple": "Video Split (Multiple)",
    "MergeVideoSegments": "Merge Video Segments",
    "ImageCollect": "Image Collect",
}

WEB_DIRECTORY = "./web"