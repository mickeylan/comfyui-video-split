"""Low-memory video collection for Easy Use For Loop."""

import math
import os
import shutil
import subprocess
import uuid

import torch

import folder_paths
import comfy.model_management
from comfy_api.latest import io, ui

from .audio_nodes import _parts


COLLECTION_TYPE = "VIDEO_SEGMENT_COLLECTION"


def _ffmpeg_path():
    path = shutil.which("ffmpeg")
    if path is not None:
        return path
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        raise ProcessLookupError("FFmpeg is required. Install FFmpeg or imageio-ffmpeg, then restart ComfyUI.")


def _run_ffmpeg(command, input_bytes=None):
    result = subprocess.run(command, input=input_bytes, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip() or "FFmpeg failed")


def _encode_images(images, path, fps, quality, skip_frames):
    if images.ndim != 4 or images.shape[-1] < 3:
        raise ValueError(f"Expected IMAGE frames [frames,height,width,channels], got {tuple(images.shape)}")
    if skip_frames >= images.shape[0]:
        raise ValueError(f"overlap_frames ({skip_frames}) removes all {images.shape[0]} frames from this segment")

    height, width = images.shape[1:3]
    if width % 2 or height % 2:
        raise ValueError(f"H.264 output requires even dimensions, got {width}x{height}")

    crf = {"高画质": "17", "标准": "20", "省空间": "24"}[quality]
    command = [
        _ffmpeg_path(), "-v", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}", "-r", str(fps), "-i", "pipe:0",
        "-an", "-c:v", "libx264", "-preset", "medium", "-crf", crf,
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", path,
    ]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        for frame in images[skip_frames:]:
            frame_bytes = frame[..., :3].detach().clamp(0, 1).mul(255).round().to(
                device="cpu", dtype=torch.uint8
            ).contiguous().numpy().tobytes()
            try:
                process.stdin.write(frame_bytes)
            except BrokenPipeError:
                error = process.stderr.read().decode("utf-8", errors="replace")
                raise RuntimeError(error.strip() or "FFmpeg stopped while writing video segment")
        process.stdin.close()
        error = process.stderr.read()
        return_code = process.wait()
        if return_code != 0:
            raise RuntimeError(error.decode("utf-8", errors="replace").strip() or "FFmpeg failed")
    except BaseException:
        process.kill()
        process.wait()
        if os.path.exists(path):
            os.remove(path)
        raise

    return width, height, images.shape[0] - skip_frames


class LTXVVideoSegmentInfo:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "images": ("IMAGE",),
            "fps": ("FLOAT", {"default": 24.0, "min": 1.0, "max": 120.0, "step": 0.001}),
            "segment_duration": ("FLOAT", {"default": 7.0, "min": 0.1, "max": 3600.0, "step": 0.1}),
            "overlap_frames": ("INT", {"default": 17, "min": 1, "max": 10001, "step": 8}),
        }}

    RETURN_TYPES = ("INT", "INT", "INT")
    RETURN_NAMES = ("total_segments", "total_frames", "frames_per_segment")
    FUNCTION = "execute"
    CATEGORY = "video/split"

    def execute(self, images, fps, segment_duration, overlap_frames):
        total_frames = images.shape[0]
        requested = round(segment_duration * fps)
        frames_per_segment = max(9, ((requested - 1) // 8) * 8 + 1)
        overlap = max(1, ((overlap_frames - 1) // 8) * 8 + 1)
        if overlap >= frames_per_segment:
            raise ValueError(f"LTX overlap ({overlap}) must be smaller than segment length ({frames_per_segment})")
        stride = frames_per_segment - overlap
        total_segments = 1 if total_frames <= frames_per_segment else (total_frames - frames_per_segment + stride - 1) // stride + 1
        return (total_segments, total_frames, frames_per_segment)


class LTXVGetVideoSegment:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "images": ("IMAGE",),
            "segment_index": ("INT", {"default": 0, "min": 0, "max": 10000}),
            "frames_per_segment": ("INT", {"default": 161, "min": 9, "max": 100000, "step": 8}),
            "overlap_frames": ("INT", {"default": 17, "min": 1, "max": 10001, "step": 8}),
        }}

    RETURN_TYPES = ("IMAGE", "INT", "INT")
    RETURN_NAMES = ("segment_images", "segment_frame_count", "start_frame")
    FUNCTION = "execute"
    CATEGORY = "video/split"

    def execute(self, images, segment_index, frames_per_segment, overlap_frames):
        overlap = max(1, ((overlap_frames - 1) // 8) * 8 + 1)
        if overlap >= frames_per_segment:
            raise ValueError(f"LTX overlap ({overlap}) must be smaller than segment length ({frames_per_segment})")
        start_frame = segment_index * (frames_per_segment - overlap)
        if start_frame >= images.shape[0]:
            raise ValueError(f"Segment index {segment_index} out of range. Video has {images.shape[0]} frames.")
        end_frame = min(start_frame + frames_per_segment, images.shape[0])
        valid_frames = end_frame - start_frame
        segment = images[start_frame:end_frame].clone()
        if valid_frames < frames_per_segment:
            padding = segment[-1:].expand(frames_per_segment - valid_frames, -1, -1, -1).clone()
            segment = torch.cat((segment, padding), dim=0)
        return (segment, valid_frames, start_frame)


class LTXVDecodeToVideoSegment:
    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "latent": ("LATENT", {"tooltip": "Connect LTXVUnlimitedSampler denoised_output."}),
                "video_vae": ("VAE", {"tooltip": "Connect the LTX Video VAE, not the Audio VAE."}),
                "fps": ("FLOAT", {"default": 24.0, "min": 1.0, "max": 120.0, "step": 0.001}),
                "quality": (["高画质", "标准", "省空间"], {"default": "标准"}),
                "overlap_frames": ("INT", {"default": 17, "min": 0}),
            },
            "optional": {
                "valid_frames": ("INT", {"default": 0, "min": 0, "tooltip": "Connect LTX Get Video Segment segment_frame_count."}),
                "segments": (COLLECTION_TYPE, {"tooltip": "Connect easy forLoopStart feedback value."}),
            },
        }

    RETURN_TYPES = (COLLECTION_TYPE, "INT")
    RETURN_NAMES = ("segments", "total_frames")
    FUNCTION = "execute"
    CATEGORY = "video/split"

    def execute(self, latent, video_vae, fps, quality, overlap_frames, valid_frames=0, segments=None):
        samples = latent["samples"]
        if getattr(samples, "is_nested", False):
            samples = samples.unbind()[0]
        if samples.ndim != 5 or samples.shape[0] != 1:
            raise ValueError(f"Expected one LTX video latent [1,C,T,H,W], got {tuple(samples.shape)}")
        if video_vae.latent_dim != 3 or video_vae.latent_channels != samples.shape[1]:
            raise ValueError("LTX Decode To Video Segment requires the matching LTX Video VAE, not an Audio VAE.")
        model = video_vae.first_stage_model
        if not getattr(model, "comfy_has_chunked_io", False) or not hasattr(model, "decode_output_shape"):
            raise ValueError("The connected VAE does not support continuous LTX decode to a disk buffer.")

        output_shape = tuple(model.decode_output_shape(samples.shape))
        if len(output_shape) != 5 or output_shape[0] != 1 or output_shape[1] < 3:
            raise ValueError(f"Unexpected LTX Video VAE output shape: {output_shape}")
        _, _, decoded_frames, height, width = output_shape
        if width % 2 or height % 2:
            raise ValueError(f"H.264 output requires even dimensions, got {width}x{height}")
        if valid_frames <= 0:
            valid_frames = decoded_frames
        if valid_frames > decoded_frames:
            raise ValueError(f"valid_frames ({valid_frames}) exceeds decoded frame count ({decoded_frames})")
        mmap_bytes = math.prod(output_shape) * torch.tensor([], dtype=torch.float32).element_size()
        temp_root = folder_paths.get_temp_directory()
        if shutil.disk_usage(temp_root).free < mmap_bytes + 1024 ** 3:
            raise OSError(
                f"Not enough temporary disk space for LTX decode: need {(mmap_bytes + 1024 ** 3) / 1024 ** 3:.1f} GiB, "
                f"available {shutil.disk_usage(temp_root).free / 1024 ** 3:.1f} GiB."
            )

        if segments is None:
            session_dir = os.path.join(folder_paths.get_temp_directory(), "video_segment_collection", uuid.uuid4().hex)
            os.makedirs(session_dir, exist_ok=False)
            segments = {"session_dir": session_dir, "paths": [], "fps": float(fps), "quality": quality,
                        "overlap_frames": int(overlap_frames), "width": None, "height": None, "total_frames": 0}
        else:
            segments = dict(segments)
            segments["paths"] = list(segments["paths"])
            if float(fps) != segments["fps"] or quality != segments["quality"] or int(overlap_frames) != segments["overlap_frames"]:
                raise ValueError("fps, quality, and overlap_frames must stay unchanged during the loop")

        temp_dir = os.path.join(segments["session_dir"], f"decode_{len(segments['paths']):06}")
        os.makedirs(temp_dir, exist_ok=False)
        mmap_path = os.path.join(temp_dir, "decoded.float32")
        decoded = None
        path = os.path.join(segments["session_dir"], f"segment_{len(segments['paths']):06}.mp4")
        try:
            with open(mmap_path, "wb") as handle:
                handle.truncate(mmap_bytes)
            decoded = torch.from_file(mmap_path, shared=True, size=math.prod(output_shape), dtype=torch.float32).reshape(output_shape)

            comfy.model_management.unload_all_models()
            comfy.model_management.soft_empty_cache()
            temporal_chunk_latents = samples.shape[2]
            spatial_chunk_latents = min(24, samples.shape[3], samples.shape[4])
            spatial_halo = min(4, spatial_chunk_latents // 4)
            memory_shape = (
                samples.shape[0], samples.shape[1], temporal_chunk_latents,
                min(samples.shape[3], spatial_chunk_latents + spatial_halo * 2),
                min(samples.shape[4], spatial_chunk_latents + spatial_halo * 2),
            )
            memory_used = video_vae.memory_used_decode(memory_shape, video_vae.vae_dtype)
            time_scale = (decoded_frames - 1) // (samples.shape[2] - 1)
            height_scale = height // samples.shape[3]
            width_scale = width // samples.shape[4]
            with comfy.model_management.cuda_device_context(video_vae.device):
                comfy.model_management.load_models_gpu([video_vae.patcher], memory_required=memory_used, force_full_load=video_vae.disable_offload)
                latent_start = 0
                while latent_start < samples.shape[2]:
                    latent_end = min(latent_start + temporal_chunk_latents, samples.shape[2])
                    output_start = latent_start * time_scale
                    for core_y in range(0, samples.shape[3], spatial_chunk_latents):
                        input_y = max(0, core_y - spatial_halo)
                        core_y_end = min(core_y + spatial_chunk_latents, samples.shape[3])
                        input_y_end = min(core_y_end + spatial_halo, samples.shape[3])
                        for core_x in range(0, samples.shape[4], spatial_chunk_latents):
                            input_x = max(0, core_x - spatial_halo)
                            core_x_end = min(core_x + spatial_chunk_latents, samples.shape[4])
                            input_x_end = min(core_x_end + spatial_halo, samples.shape[4])
                            chunk = samples[:, :, latent_start:latent_end, input_y:input_y_end, input_x:input_x_end].detach().to(device=video_vae.device, dtype=video_vae.vae_dtype)
                            tile_shape = tuple(model.decode_output_shape(chunk.shape))
                            tile_output = torch.empty(tile_shape, device="cpu", dtype=torch.float32)
                            model.decode(chunk, output_buffer=tile_output)
                            output_end = min(output_start + tile_shape[2], decoded_frames)
                            output_y = core_y * height_scale
                            output_y_end = core_y_end * height_scale
                            output_x = core_x * width_scale
                            output_x_end = core_x_end * width_scale
                            crop_y = (core_y - input_y) * height_scale
                            crop_x = (core_x - input_x) * width_scale
                            decoded[:, :, output_start:output_end, output_y:output_y_end, output_x:output_x_end].copy_(
                                tile_output[:, :, :output_end - output_start, crop_y:crop_y + output_y_end - output_y, crop_x:crop_x + output_x_end - output_x]
                            )
                            del chunk, tile_output
                    if latent_end == samples.shape[2]:
                        break
                    latent_start = latent_end - 1

            skip_frames = int(overlap_frames) if segments["paths"] else 0
            if skip_frames >= valid_frames:
                raise ValueError(f"overlap_frames ({skip_frames}) removes all {valid_frames} valid frames")
            crf = {"高画质": "17", "标准": "20", "省空间": "24"}[quality]
            command = [_ffmpeg_path(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}", "-r", str(fps), "-i", "pipe:0", "-an", "-c:v", "libx264", "-preset", "medium", "-crf", crf, "-pix_fmt", "yuv420p", "-movflags", "+faststart", path]
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            try:
                for index in range(skip_frames, valid_frames):
                    frame = video_vae.process_output(decoded[0, :3, index]).movedim(0, -1)
                    process.stdin.write(frame.mul(255).round().to(torch.uint8).contiguous().numpy().tobytes())
                process.stdin.close()
                error = process.stderr.read()
                if process.wait() != 0:
                    raise RuntimeError(error.decode("utf-8", errors="replace").strip() or "FFmpeg failed")
            except BaseException:
                process.kill()
                process.wait()
                raise
        except BaseException:
            if os.path.exists(path):
                os.remove(path)
            raise
        finally:
            del decoded
            shutil.rmtree(temp_dir, ignore_errors=True)

        if segments["width"] is not None and (width != segments["width"] or height != segments["height"]):
            os.remove(path)
            raise ValueError("All collected video segments must have the same resolution")
        frame_count = valid_frames - skip_frames
        segments["width"] = width
        segments["height"] = height
        segments["paths"].append(path)
        segments["total_frames"] += frame_count
        return (segments, segments["total_frames"])


class ImageCollectLowMemoryVideo:
    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "new_images": ("IMAGE", {"tooltip": "连接原来 Image Collect 的 new_images 线"}),
                "fps": ("FLOAT", {"default": 24.0, "min": 1.0, "max": 120.0, "step": 0.001}),
                "quality": (["高画质", "标准", "省空间"], {"default": "标准"}),
                "overlap_frames": ("INT", {"default": 17, "min": 0, "tooltip": "后续分段开头需要丢弃的重复帧数"}),
            },
            "optional": {
                "valid_frames": ("INT", {"default": 0, "min": 0, "tooltip": "连接 GetVideoSegment.segment_frame_count；0 表示全部有效"}),
                "segments": (COLLECTION_TYPE, {"tooltip": "连接 easy forLoopStart 的反馈 value"}),
            },
        }

    RETURN_TYPES = (COLLECTION_TYPE, "INT")
    RETURN_NAMES = ("segments", "total_frames")
    FUNCTION = "execute"
    CATEGORY = "video/split"

    def execute(self, new_images, fps, quality, overlap_frames, valid_frames=0, segments=None):
        if isinstance(new_images, list):
            if len(new_images) != 1:
                raise ValueError("Low-memory Image Collect expects one IMAGE segment per loop")
            new_images = new_images[0]
        if valid_frames:
            if valid_frames > new_images.shape[0]:
                raise ValueError(f"valid_frames ({valid_frames}) exceeds decoded segment length ({new_images.shape[0]})")
            new_images = new_images[:valid_frames]

        if segments is None:
            session_dir = os.path.join(folder_paths.get_temp_directory(), "video_segment_collection", uuid.uuid4().hex)
            os.makedirs(session_dir, exist_ok=False)
            segments = {
                "session_dir": session_dir,
                "paths": [],
                "fps": float(fps),
                "quality": quality,
                "overlap_frames": int(overlap_frames),
                "width": None,
                "height": None,
                "total_frames": 0,
            }
        else:
            segments = dict(segments)
            segments["paths"] = list(segments["paths"])
            if float(fps) != segments["fps"] or quality != segments["quality"] or int(overlap_frames) != segments["overlap_frames"]:
                raise ValueError("fps, quality, and overlap_frames must stay unchanged during the loop")

        index = len(segments["paths"])
        path = os.path.join(segments["session_dir"], f"segment_{index:06}.mp4")
        skip_frames = overlap_frames if index > 0 else 0
        width, height, frame_count = _encode_images(new_images, path, fps, quality, skip_frames)
        if segments["width"] is not None and (width != segments["width"] or height != segments["height"]):
            os.remove(path)
            raise ValueError("All collected video segments must have the same resolution")

        segments["width"] = width
        segments["height"] = height
        segments["paths"].append(path)
        segments["total_frames"] += frame_count
        return (segments, segments["total_frames"])


class FinalVideoSave(io.ComfyNode):
    @classmethod
    def fingerprint_inputs(cls, **kwargs):
        return float("nan")

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="FinalVideoSave",
            display_name="Final Video Save",
            category="video/split",
            description="替代 VHS Video Combine：拼接低内存收集的视频段并保存最终 MP4。",
            inputs=[
                io.Custom(COLLECTION_TYPE).Input("segments", tooltip="连接 easy forLoopEnd 的最终反馈 value"),
                io.String.Input("filename_prefix", default="video/ComfyUI"),
                io.Audio.Input("audio", optional=True, tooltip="可选；连接原视频的完整音频"),
            ],
            outputs=[io.String.Output(display_name="saved_path")],
            is_output_node=True,
        )

    @classmethod
    def execute(cls, segments, filename_prefix, audio=None):
        if not segments or not segments.get("paths"):
            raise ValueError("No collected video segments. Connect the Easy Use forLoopEnd feedback output.")
        missing = [index for index, path in enumerate(segments["paths"]) if not os.path.isfile(path)]
        if missing:
            raise RuntimeError(f"Cannot finish video because segments are missing: {missing}")

        full_folder, filename, counter, subfolder, _ = folder_paths.get_save_image_path(
            filename_prefix, folder_paths.get_output_directory(), segments["width"], segments["height"]
        )
        file = f"{filename}_{counter:05}_.mp4"
        final_path = os.path.join(full_folder, file)
        session_dir = segments["session_dir"]
        concat_list = os.path.join(session_dir, "segments.txt")
        with open(concat_list, "w", encoding="utf-8") as handle:
            for path in segments["paths"]:
                handle.write(f"file '{path.replace(os.sep, '/')}'\n")

        ffmpeg = _ffmpeg_path()
        video_only_path = final_path if audio is None else os.path.join(session_dir, "video_only.mp4")
        try:
            _run_ffmpeg([
                ffmpeg, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", concat_list,
                "-c", "copy", "-movflags", "+faststart", video_only_path,
            ])
            if audio is not None:
                waveform, sample_rate = _parts(audio)
                if waveform.ndim == 2:
                    waveform = waveform.unsqueeze(0)
                if waveform.shape[0] != 1:
                    raise ValueError("Audio must contain one batch")
                channels = waveform.shape[1]
                audio_bytes = waveform[0].detach().cpu().float().transpose(0, 1).contiguous().numpy().tobytes()
                _run_ffmpeg([
                    ffmpeg, "-v", "error", "-y", "-i", video_only_path,
                    "-f", "f32le", "-ar", str(sample_rate), "-ac", str(channels), "-i", "pipe:0",
                    "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
                    "-af", "apad", "-shortest", "-movflags", "+faststart", final_path,
                ], audio_bytes)
        except BaseException:
            if os.path.exists(final_path):
                os.remove(final_path)
            raise

        return io.NodeOutput(final_path, ui=ui.PreviewVideo([ui.SavedResult(file, subfolder, io.FolderType.output)]))


LTXV_STREAM_NODE_CLASS_MAPPINGS = {
    "LTXVVideoSegmentInfo": LTXVVideoSegmentInfo,
    "LTXVGetVideoSegment": LTXVGetVideoSegment,
    "LTXVDecodeToVideoSegment": LTXVDecodeToVideoSegment,
    "ImageCollectLowMemoryVideo": ImageCollectLowMemoryVideo,
    "FinalVideoSave": FinalVideoSave,
}

LTXV_STREAM_NODE_DISPLAY_NAME_MAPPINGS = {
    "LTXVVideoSegmentInfo": "LTX Video Segment Info",
    "LTXVGetVideoSegment": "LTX Get Video Segment",
    "LTXVDecodeToVideoSegment": "LTX Decode To Video Segment (Disk)",
    "ImageCollectLowMemoryVideo": "Image Collect (Low Memory Video)",
    "FinalVideoSave": "Final Video Save",
}
