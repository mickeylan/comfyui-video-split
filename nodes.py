"""
Video Split Nodes - Split video into segments by duration or frame count.

Supports both:
- IMAGE input (from VHS Load Video) - frames already in memory
- VIDEO input (from ComfyUI native Load Video) - lazy loading support
"""
import torch
from fractions import Fraction
from typing import Optional, Tuple, Union

from comfy_api.latest import io, ui, InputImpl, Types


def _get_video_meta(video_or_images) -> Tuple[int, Fraction]:
    """Get frame count and frame rate from video or images."""
    if isinstance(video_or_images, torch.Tensor):
        # IMAGE type - tensor of frames
        return video_or_images.shape[0], Fraction(24, 1)  # Default 24fps for images
    
    # VIDEO type
    if hasattr(video_or_images, 'get_frame_count') and hasattr(video_or_images, 'get_frame_rate'):
        return int(video_or_images.get_frame_count()), video_or_images.get_frame_rate()
    
    # Fallback
    if hasattr(video_or_images, 'get_components'):
        components = video_or_images.get_components()
        return components.images.shape[0], components.frame_rate
    
    raise TypeError(f"Unsupported type: {type(video_or_images)}")


def _extract_segment(video_or_images, start_frame: int, end_frame: int, frame_rate: Fraction):
    """Extract a segment from video or images."""
    if isinstance(video_or_images, torch.Tensor):
        # IMAGE type - direct slice
        return video_or_images[start_frame:end_frame]
    
    # VIDEO type - try lazy trim
    fps = float(frame_rate)
    segment_frame_count = end_frame - start_frame
    
    if hasattr(video_or_images, 'as_trimmed'):
        start_time = start_frame / fps
        duration = segment_frame_count / fps
        try:
            trimmed = video_or_images.as_trimmed(start_time=start_time, duration=duration, strict_duration=False)
            if trimmed is not None:
                return trimmed
        except Exception:
            pass
    
    # Fallback: extract from tensor
    if hasattr(video_or_images, 'get_components'):
        components = video_or_images.get_components()
        return components.images[start_frame:end_frame]
    
    raise TypeError("Cannot extract segment from this type")


class VideoSegmentInfo(io.ComfyNode):
    """
    Calculate segment information for video splitting.
    Works with both IMAGE (from VHS) and VIDEO (from ComfyUI native) inputs.
    """
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="VideoSegmentInfo",
            display_name="Video Segment Info",
            category="video/split",
            inputs=[
                io.Image.Input("images", tooltip="Frames from VHS Load Video (IMAGE type)"),
                io.Float.Input("fps", default=24.0, min=1.0, max=120.0, step=1.0,
                    tooltip="Frame rate of the video"),
                io.Combo.Input("split_mode", options=["by_duration", "by_frames"], default="by_duration"),
                io.Float.Input("segment_duration", default=5.0, min=0.1, max=3600.0, step=0.1,
                    tooltip="Duration of each segment in seconds"),
                io.Int.Input("segment_frames", default=120, min=1, max=100000, step=1,
                    tooltip="Number of frames per segment"),
            ],
            outputs=[
                io.Int.Output("total_segments"),
                io.Int.Output("total_frames"),
                io.Int.Output("frames_per_segment"),
            ],
            description="Calculate segment information. Connect images from VHS Load Video.",
        )

    @classmethod
    def execute(cls, images: torch.Tensor, fps: float, split_mode: str, 
                segment_duration: float, segment_frames: int) -> tuple:
        total_frames = images.shape[0]
        frame_rate = Fraction(int(fps), 1)

        if split_mode == "by_duration":
            frames_per_seg = max(1, int(segment_duration * fps))
        else:
            frames_per_seg = segment_frames

        total_segments = (total_frames + frames_per_seg - 1) // frames_per_seg

        return (total_segments, total_frames, frames_per_seg)


class GetVideoSegment(io.ComfyNode):
    """
    Extract a specific segment from video frames by index.
    Connect to VHS Load Video's image output.
    """
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="GetVideoSegment",
            display_name="Get Video Segment",
            category="video/split",
            inputs=[
                io.Image.Input("images", tooltip="Frames from VHS Load Video"),
                io.Int.Input("segment_index", default=0, min=0, max=10000, step=1,
                    tooltip="Index of segment to extract (0-based)"),
                io.Int.Input("frames_per_segment", default=120, min=1, max=100000, step=1,
                    tooltip="Frames per segment (from VideoSegmentInfo)"),
            ],
            outputs=[
                io.Image.Output("segment_images"),
                io.Int.Output("segment_frame_count"),
                io.Int.Output("start_frame"),
            ],
            description="Extract a video segment by index from frame tensor.",
        )

    @classmethod
    def execute(cls, images: torch.Tensor, segment_index: int, frames_per_segment: int) -> tuple:
        total_frames = images.shape[0]

        start_frame = segment_index * frames_per_segment
        end_frame = min(start_frame + frames_per_segment, total_frames)

        if start_frame >= total_frames:
            raise ValueError(f"Segment index {segment_index} out of range. Video has {total_frames} frames.")

        segment_frame_count = end_frame - start_frame
        segment_images = images[start_frame:end_frame]

        return (segment_images, segment_frame_count, start_frame)


class VideoSplitMultiple(io.ComfyNode):
    """
    Split video frames into all segments at once.
    Returns a list of frame tensors.
    """
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="VideoSplitMultiple",
            display_name="Video Split (Multiple)",
            category="video/split",
            inputs=[
                io.Image.Input("images", tooltip="Frames from VHS Load Video"),
                io.Combo.Input("split_mode", options=["by_duration", "by_frames"], default="by_duration"),
                io.Float.Input("fps", default=24.0, min=1.0, max=120.0, step=1.0,
                    tooltip="Frame rate"),
                io.Float.Input("segment_duration", default=5.0, min=0.1, max=3600.0, step=0.1,
                    tooltip="Duration of each segment in seconds"),
                io.Int.Input("segment_frames", default=120, min=1, max=100000, step=1,
                    tooltip="Number of frames per segment"),
            ],
            outputs=[
                io.Image.Output("segments", is_output_list=True),
                io.Int.Output("total_segments"),
            ],
            description="Split video into all segments. Returns a list of frame tensors.",
        )

    @classmethod
    def execute(cls, images: torch.Tensor, split_mode: str, fps: float,
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


class MergeVideoSegments(io.ComfyNode):
    """
    Merge multiple video segments (frame tensors) back into a single video.
    """
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="MergeVideoSegments",
            display_name="Merge Video Segments",
            category="video/split",
            is_input_list=True,
            inputs=[
                io.Image.Input("segments", tooltip="Video segments to merge"),
            ],
            outputs=[
                io.Image.Output("merged_images"),
                io.Int.Output("total_frames"),
            ],
            description="Merge video segments back into a single frame tensor.",
        )

    @classmethod
    def execute(cls, segments: list) -> tuple:
        if not segments:
            raise ValueError("No video segments provided")

        merged = torch.cat(segments, dim=0)
        total_frames = merged.shape[0]

        return (merged, total_frames)


class ImageCollect(io.ComfyNode):
    """
    Collect images in a for loop.
    Pass 'accumulated' output to next iteration's 'images' input.
    """
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="ImageCollect",
            display_name="Image Collect",
            category="video/split",
            inputs=[
                io.Image.Input("new_images", tooltip="Images to add (from this iteration)"),
                io.Image.Input("images", optional=True, tooltip="Previously accumulated images"),
            ],
            outputs=[
                io.Image.Output("accumulated"),
                io.Int.Output("total_frames"),
            ],
            description="Collect images in a for loop. Pass 'accumulated' to next iteration's 'images'.",
        )

    @classmethod
    def execute(cls, new_images: torch.Tensor, images: torch.Tensor = None) -> tuple:
        if images is None:
            return (new_images, new_images.shape[0])

        accumulated = torch.cat([images, new_images], dim=0)
        return (accumulated, accumulated.shape[0])


# Legacy node mappings
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