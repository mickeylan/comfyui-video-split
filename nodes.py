"""
Video Split Nodes - Split video into segments by duration or frame count.
"""
import torch
from fractions import Fraction
from typing import Optional, Tuple

# Lazy imports for ComfyUI new API
_InputImpl = None
_Types = None
io = None
ui = None

def _get_native_video():
    global _InputImpl, _Types, io, ui
    if _InputImpl is None:
        try:
            from comfy_api.latest import InputImpl, Types, io as _io, ui as _ui
            _InputImpl = InputImpl
            _Types = Types
            io = _io
            ui = _ui
        except Exception:
            pass
    return _InputImpl, _Types, io, ui


class VideoFromTensors:
    """Wraps a torch tensor as a ComfyUI-compatible video object."""
    def __init__(self, images: torch.Tensor, frame_rate: Fraction = Fraction(30, 1)):
        if images.ndim == 3:
            images = images.unsqueeze(0)
        self._images = images.float()
        self._frame_rate = frame_rate

    @property
    def images(self):
        return self._images

    @property
    def frame_rate(self):
        return self._frame_rate

    def get_components(self):
        _, Types, _, _ = _get_native_video()
        if Types is not None:
            return Types.VideoComponents(
                images=self._images,
                frame_rate=self._frame_rate,
            )
        class _C:
            pass
        c = _C()
        c.images = self._images
        c.frame_rate = self._frame_rate
        c.audio = None
        c.metadata = None
        c.alpha = None
        return c

    def get_dimensions(self) -> tuple:
        h, w = self._images.shape[1], self._images.shape[2]
        return w, h

    def get_duration(self) -> float:
        return float(self._images.shape[0] / self._frame_rate)

    def get_frame_count(self) -> int:
        return int(self._images.shape[0])

    def get_frame_rate(self) -> Fraction:
        return self._frame_rate

    def save_to(self, path, format="AUTO", codec="AUTO", metadata=None):
        import av
        ext = "mp4"
        if not str(path).endswith(ext):
            path = f"{path}.{ext}"
        container = av.open(path, mode="w")
        stream = container.add_stream("libx264", rate=self._frame_rate)
        h, w = self._images.shape[1], self._images.shape[2]
        stream.width = w
        stream.height = h
        stream.pix_fmt = "yuv420p"
        for frame in self._images:
            arr = torch.clamp(frame[..., :3] * 255, min=0, max=255).to(
                device=torch.device("cpu"), dtype=torch.uint8
            ).numpy()
            vf = av.VideoFrame.from_ndarray(arr, format="rgb24")
            for pkt in stream.encode(vf):
                container.mux(pkt)
        container.mux(stream.encode())
        container.close()

    def as_trimmed(self, start_time=None, duration=None, strict_duration=False):
        return None


def _extract_tensor(video) -> Tuple[torch.Tensor, Fraction]:
    """Extract tensor and frame rate from video object."""
    if isinstance(video, torch.Tensor):
        return video, Fraction(30, 1)
    if hasattr(video, "get_components"):
        components = video.get_components()
        return components.images, components.frame_rate
    if hasattr(video, "images") and hasattr(video, "frame_rate"):
        return video.images, video.frame_rate
    raise TypeError(f"Unsupported video type: {type(video)}")


def _video_meta(video) -> Tuple[int, Fraction]:
    """Get frame count and frame rate WITHOUT materializing frames."""
    if hasattr(video, "get_frame_count") and hasattr(video, "get_frame_rate"):
        return int(video.get_frame_count()), video.get_frame_rate()
    tensor, frame_rate = _extract_tensor(video)
    return tensor.shape[0], frame_rate


def _wrap_output(images: torch.Tensor, frame_rate: Fraction) -> VideoFromTensors:
    if images.ndim == 3:
        images = images.unsqueeze(0)
    if images.dtype != torch.float32:
        images = images.float()
    return VideoFromTensors(images, frame_rate)


class VideoSegmentInfo:
    """
    Provides segment information for video splitting.
    Outputs total segment count and segment boundaries.
    """
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "video": ("VIDEO",),
                "split_mode": (["by_duration", "by_frames"], {"default": "by_duration"}),
                "segment_duration": ("FLOAT", {
                    "default": 5.0,
                    "min": 0.1,
                    "max": 3600.0,
                    "step": 0.1,
                    "tooltip": "Duration of each segment in seconds (used when split_mode='by_duration')"
                }),
                "segment_frames": ("INT", {
                    "default": 120,
                    "min": 1,
                    "max": 100000,
                    "step": 1,
                    "tooltip": "Number of frames per segment (used when split_mode='by_frames')"
                }),
            },
        }

    RETURN_TYPES = ("INT", "FLOAT", "INT", "INT")
    RETURN_NAMES = ("total_segments", "fps", "total_frames", "frames_per_segment")
    FUNCTION = "get_info"
    CATEGORY = "video/split"
    DESCRIPTION = "Calculate segment information for video splitting. Use with GetVideoSegment to iterate through segments."

    def get_info(self, video, split_mode: str, segment_duration: float, segment_frames: int) -> tuple:
        total_frames, frame_rate = _video_meta(video)
        fps = float(frame_rate)

        if split_mode == "by_duration":
            frames_per_seg = max(1, int(segment_duration * fps))
        else:
            frames_per_seg = segment_frames

        # Calculate total segments (ceiling division)
        total_segments = (total_frames + frames_per_seg - 1) // frames_per_seg

        return (total_segments, fps, total_frames, frames_per_seg)


class GetVideoSegment:
    """
    Extract a specific segment from video by index.
    Use after VideoSegmentInfo to get segment boundaries.
    Supports lazy loading - only decodes the requested segment, not the entire video.
    """
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "video": ("VIDEO",),
                "segment_index": ("INT", {
                    "default": 0,
                    "min": 0,
                    "max": 10000,
                    "step": 1,
                    "tooltip": "Index of segment to extract (0-based)"
                }),
                "frames_per_segment": ("INT", {
                    "default": 120,
                    "min": 1,
                    "max": 100000,
                    "step": 1,
                    "tooltip": "Frames per segment (from VideoSegmentInfo)"
                }),
            },
        }

    RETURN_TYPES = ("VIDEO", "INT", "INT")
    RETURN_NAMES = ("video_segment", "segment_frame_count", "start_frame")
    FUNCTION = "get_segment"
    CATEGORY = "video/split"
    DESCRIPTION = "Extract a video segment by index. Uses lazy loading - only decodes the requested segment."

    def get_segment(self, video, segment_index: int, frames_per_segment: int) -> tuple:
        total_frames, frame_rate = _video_meta(video)
        fps = float(frame_rate)

        start_frame = segment_index * frames_per_segment
        end_frame = min(start_frame + frames_per_segment, total_frames)

        if start_frame >= total_frames:
            raise ValueError(f"Segment index {segment_index} out of range. Video has {total_frames} frames.")

        segment_frame_count = end_frame - start_frame

        # Try lazy trim first (for VideoFromFile - no full decode)
        if hasattr(video, 'as_trimmed') and hasattr(video, 'get_stream_source'):
            start_time = start_frame / fps
            duration = segment_frame_count / fps
            try:
                trimmed = video.as_trimmed(start_time=start_time, duration=duration, strict_duration=False)
                if trimmed is not None:
                    return (trimmed, segment_frame_count, start_frame)
            except Exception:
                pass  # Fall back to tensor extraction

        # Fallback: extract from tensor (materializes video)
        tensor, _ = _extract_tensor(video)
        segment_tensor = tensor[start_frame:end_frame]

        return (_wrap_output(segment_tensor, frame_rate), segment_frame_count, start_frame)


class VideoSplitMultiple:
    """
    Split video into multiple segments at once.
    Returns a list of video segments for batch processing.
    """
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "video": ("VIDEO",),
                "split_mode": (["by_duration", "by_frames"], {"default": "by_duration"}),
                "segment_duration": ("FLOAT", {
                    "default": 5.0,
                    "min": 0.1,
                    "max": 3600.0,
                    "step": 0.1,
                    "tooltip": "Duration of each segment in seconds"
                }),
                "segment_frames": ("INT", {
                    "default": 120,
                    "min": 1,
                    "max": 100000,
                    "step": 1,
                    "tooltip": "Number of frames per segment"
                }),
            },
        }

    RETURN_TYPES = ("VIDEO", "INT")
    RETURN_NAMES = ("video_segments", "total_segments")
    OUTPUT_IS_LIST = (True, False)
    FUNCTION = "split_video"
    CATEGORY = "video/split"
    DESCRIPTION = "Split video into multiple segments. Returns all segments as a list."

    def split_video(self, video, split_mode: str, segment_duration: float, segment_frames: int) -> tuple:
        total_frames, frame_rate = _video_meta(video)
        fps = float(frame_rate)

        if split_mode == "by_duration":
            frames_per_seg = max(1, int(segment_duration * fps))
        else:
            frames_per_seg = segment_frames

        # Calculate total segments
        total_segments = (total_frames + frames_per_seg - 1) // frames_per_seg

        # Extract tensor once
        tensor, _ = _extract_tensor(video)

        segments = []
        for i in range(total_segments):
            start_frame = i * frames_per_seg
            end_frame = min(start_frame + frames_per_seg, total_frames)
            segment_tensor = tensor[start_frame:end_frame]
            segments.append(_wrap_output(segment_tensor, frame_rate))

        return (segments, total_segments)


class MergeVideoSegments:
    """
    Merge multiple video segments back into a single video.
    Use after processing segments individually.
    """
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "video_segments": ("VIDEO",),
            },
        }

    RETURN_TYPES = ("VIDEO", "INT")
    RETURN_NAMES = ("merged_video", "total_frames")
    INPUT_IS_LIST = True
    FUNCTION = "merge_segments"
    CATEGORY = "video/split"
    DESCRIPTION = "Merge video segments back into a single video."

    def merge_segments(self, video_segments: list) -> tuple:
        if not video_segments:
            raise ValueError("No video segments provided")

        # Extract all tensors and get frame rate from first segment
        tensors = []
        frame_rate = Fraction(30, 1)

        for i, seg in enumerate(video_segments):
            tensor, fr = _extract_tensor(seg)
            tensors.append(tensor)
            if i == 0:
                frame_rate = fr

        # Concatenate all tensors
        merged_tensor = torch.cat(tensors, dim=0)
        total_frames = merged_tensor.shape[0]

        return (_wrap_output(merged_tensor, frame_rate), total_frames)


class ImageCollect:
    """
    Collect images in a for loop.
    Pass 'accumulated' output to next iteration's 'images' input.
    First iteration: leave 'images' unconnected.
    Outputs accumulated images for use with VHS_VideoCombine.
    """
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "new_images": ("IMAGE", {"tooltip": "Images to add (from this iteration)"}),
            },
            "optional": {
                "images": ("IMAGE", {"tooltip": "Previously accumulated images (from previous iteration)"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "INT")
    RETURN_NAMES = ("accumulated", "total_frames")
    FUNCTION = "collect"
    CATEGORY = "video/split"
    DESCRIPTION = "Collect images in a for loop. Pass 'accumulated' to next iteration's 'images'."

    def collect(self, new_images: torch.Tensor, images: torch.Tensor = None) -> tuple:
        if images is None:
            return (new_images, new_images.shape[0])
        
        # Concatenate along the frame dimension (dim 0)
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

WEB_DIRECTORY = "."