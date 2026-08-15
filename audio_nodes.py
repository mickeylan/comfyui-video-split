"""音频处理节点。AUDIO 使用 ComfyUI 标准 {waveform, sample_rate} 结构。"""
import os

import numpy as np
import torch
import torch.nn.functional as F

import folder_paths

try:
    import av
    PYAV_AVAILABLE = True
except ImportError:
    PYAV_AVAILABLE = False


def _audio(waveform, sample_rate):
    if waveform.ndim == 2:
        waveform = waveform.unsqueeze(0)
    return {"waveform": waveform, "sample_rate": int(sample_rate)}


def _parts(audio):
    if not isinstance(audio, dict) or "waveform" not in audio or "sample_rate" not in audio:
        raise TypeError("AUDIO must contain waveform and sample_rate")
    return audio["waveform"], int(audio["sample_rate"])


def _decode_audio(path):
    if not PYAV_AVAILABLE:
        raise ImportError("PyAV is required for audio processing. Install with: pip install av")
    with av.open(path) as container:
        if not container.streams.audio:
            raise ValueError(f"No audio stream found in {path}")
        stream = container.streams.audio[0]
        frames = [torch.from_numpy(frame.to_ndarray()).float() for frame in container.decode(stream)]
        if not frames:
            raise ValueError(f"Failed to decode audio from {path}")
        return _audio(torch.cat(frames, dim=-1), stream.codec_context.sample_rate or stream.rate), int(container.duration / 1000)


def _safe_input_path(path):
    input_dir = folder_paths.get_input_directory()
    full_path = os.path.abspath(path if os.path.isabs(path) else os.path.join(input_dir, path))
    if not folder_paths.is_within_directory(input_dir, full_path):
        raise ValueError("Audio/video input must be inside the ComfyUI input directory")
    if not os.path.isfile(full_path):
        raise FileNotFoundError(full_path)
    return full_path


def _safe_output_path(path):
    output_dir = folder_paths.get_output_directory()
    full_path = os.path.abspath(path if os.path.isabs(path) else os.path.join(output_dir, path))
    if not folder_paths.is_within_directory(output_dir, full_path):
        raise ValueError("AudioMerge output must be inside the ComfyUI output directory")
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    return full_path


class AudioExtract:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"video_path": ("STRING", {"default": "", "tooltip": "ComfyUI input 目录内的视频路径"})}}

    RETURN_TYPES = ("AUDIO", "INT", "INT")
    RETURN_NAMES = ("audio", "sample_rate", "duration_ms")
    FUNCTION = "execute"
    CATEGORY = "video/audio"

    def execute(self, video_path):
        audio, duration_ms = _decode_audio(_safe_input_path(video_path))
        return audio, audio["sample_rate"], duration_ms


class AudioFromVideo:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"video_path": ("STRING", {"default": "", "tooltip": "ComfyUI input 目录内的视频路径"})}}

    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ("audio",)
    FUNCTION = "execute"
    CATEGORY = "video/audio"

    def execute(self, video_path):
        audio, _ = _decode_audio(_safe_input_path(video_path))
        return (audio,)


class AudioMerge:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "images": ("IMAGE", {"tooltip": "视频帧张量"}),
            "audio": ("AUDIO", {"tooltip": "音频数据"}),
            "fps": ("FLOAT", {"default": 24.0, "min": 1.0, "max": 120.0}),
            "output_path": ("STRING", {"default": "output.mp4", "tooltip": "ComfyUI output 目录内的输出路径"}),
        }}

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("video_path",)
    FUNCTION = "execute"
    CATEGORY = "video/audio"

    def execute(self, images, audio, fps, output_path):
        if not PYAV_AVAILABLE:
            raise ImportError("PyAV is required. Install with: pip install av")
        output_path = _safe_output_path(output_path)
        waveform, sample_rate = _parts(audio)
        if waveform.shape[0] != 1:
            raise ValueError("AudioMerge supports one audio batch at a time")
        waveform = waveform[0].detach().cpu().float().numpy()

        with av.open(output_path, "w") as container:
            video_stream = container.add_stream("h264", rate=fps)
            video_stream.width = images.shape[2]
            video_stream.height = images.shape[1]
            video_stream.pix_fmt = "yuv420p"
            for image in images:
                frame = av.VideoFrame.from_ndarray((image.detach().cpu().clamp(0, 1).numpy() * 255).astype(np.uint8), format="rgb24")
                for packet in video_stream.encode(frame):
                    container.mux(packet)
            for packet in video_stream.encode():
                container.mux(packet)

            if waveform.shape[-1] > 0:
                channels = waveform.shape[0]
                if channels not in (1, 2):
                    raise ValueError("AudioMerge supports mono or stereo audio")
                audio_stream = container.add_stream("aac", rate=sample_rate)
                audio_frame = av.AudioFrame.from_ndarray(waveform, format="fltp", layout="mono" if channels == 1 else "stereo")
                audio_frame.sample_rate = sample_rate
                for packet in audio_stream.encode(audio_frame):
                    container.mux(packet)
                for packet in audio_stream.encode():
                    container.mux(packet)
        return (output_path,)


class AudioVolume:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"audio": ("AUDIO",), "volume": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 10.0, "step": 0.1})}}

    RETURN_TYPES = ("AUDIO",)
    FUNCTION = "execute"
    CATEGORY = "video/audio"

    def execute(self, audio, volume):
        waveform, sample_rate = _parts(audio)
        return (_audio((waveform * volume).clamp(-1, 1), sample_rate),)


class AudioFade:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "audio": ("AUDIO",),
            "fade_in_ms": ("INT", {"default": 500, "min": 0, "max": 60000}),
            "fade_out_ms": ("INT", {"default": 500, "min": 0, "max": 60000}),
            "sample_rate": ("INT", {"default": 44100, "min": 1, "max": 192000, "tooltip": "保留以兼容旧工作流，实际使用 AUDIO 的采样率"}),
        }}

    RETURN_TYPES = ("AUDIO",)
    FUNCTION = "execute"
    CATEGORY = "video/audio"

    def execute(self, audio, fade_in_ms, fade_out_ms, sample_rate=44100):
        waveform, sample_rate = _parts(audio)
        result = waveform.clone()
        total = result.shape[-1]
        fade_in = min(total, round(fade_in_ms * sample_rate / 1000))
        fade_out = min(total, round(fade_out_ms * sample_rate / 1000))
        if fade_in:
            result[..., :fade_in] *= torch.linspace(0, 1, fade_in, device=result.device, dtype=result.dtype)
        if fade_out:
            result[..., -fade_out:] *= torch.linspace(1, 0, fade_out, device=result.device, dtype=result.dtype)
        return (_audio(result, sample_rate),)


class AudioInfo:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"audio": ("AUDIO",)}}

    RETURN_TYPES = ("INT", "INT", "FLOAT")
    RETURN_NAMES = ("channels", "samples", "duration_seconds")
    FUNCTION = "execute"
    CATEGORY = "video/audio"

    def execute(self, audio):
        waveform, sample_rate = _parts(audio)
        return waveform.shape[-2], waveform.shape[-1], waveform.shape[-1] / sample_rate


class AudioMix:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"audio1": ("AUDIO",), "volume1": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 5.0})}, "optional": {
            "audio2": ("AUDIO",), "volume2": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 5.0}),
            "audio3": ("AUDIO",), "volume3": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 5.0}),
        }}

    RETURN_TYPES = ("AUDIO",)
    FUNCTION = "execute"
    CATEGORY = "video/audio"

    def execute(self, audio1, volume1, audio2=None, volume2=0.5, audio3=None, volume3=1.0):
        tracks = [(audio1, volume1)] + [(audio, volume) for audio, volume in ((audio2, volume2), (audio3, volume3)) if audio is not None]
        reference, sample_rate = _parts(audio1)
        waveforms = []
        for audio, volume in tracks:
            waveform, track_rate = _parts(audio)
            waveform = waveform.to(device=reference.device, dtype=reference.dtype)
            if track_rate != sample_rate:
                new_length = round(waveform.shape[-1] * sample_rate / track_rate)
                waveform = F.interpolate(waveform.flatten(0, 1).unsqueeze(1), size=new_length, mode="linear", align_corners=False).squeeze(1).unflatten(0, waveform.shape[:2])
            waveforms.append(waveform * volume)
        max_length = max(waveform.shape[-1] for waveform in waveforms)
        waveforms = [F.pad(waveform, (0, max_length - waveform.shape[-1])) for waveform in waveforms]
        return (_audio(torch.stack(waveforms).sum(0).clamp(-1, 1), sample_rate),)


class AudioFitToVideo:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "audio": ("AUDIO",), "target_frames": ("INT", {"default": 100, "min": 1, "max": 100000}),
            "fps": ("FLOAT", {"default": 24.0, "min": 1.0, "max": 120.0}),
            "mode": (["stretch", "loop", "cut"], {"default": "stretch"}),
        }}

    RETURN_TYPES = ("AUDIO",)
    FUNCTION = "execute"
    CATEGORY = "video/audio"

    def execute(self, audio, target_frames, fps, mode):
        waveform, sample_rate = _parts(audio)
        target = round(target_frames / fps * sample_rate)
        if mode == "stretch":
            result = F.interpolate(waveform.flatten(0, 1).unsqueeze(1), size=target, mode="linear", align_corners=False).squeeze(1).unflatten(0, waveform.shape[:2])
        elif mode == "loop" and waveform.shape[-1] < target:
            result = waveform.repeat(1, 1, target // waveform.shape[-1] + 1)[..., :target]
        else:
            result = F.pad(waveform[..., :target], (0, max(0, target - waveform.shape[-1])))
        return (_audio(result, sample_rate),)


class AudioLoop:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"audio": ("AUDIO",), "duration_seconds": ("FLOAT", {"default": 60.0, "min": 0.1, "max": 3600.0})}}

    RETURN_TYPES = ("AUDIO",)
    FUNCTION = "execute"
    CATEGORY = "video/audio"

    def execute(self, audio, duration_seconds):
        waveform, sample_rate = _parts(audio)
        target = round(duration_seconds * sample_rate)
        if waveform.shape[-1] == 0:
            return (_audio(waveform, sample_rate),)
        result = waveform.repeat(1, 1, target // waveform.shape[-1] + 1)[..., :target]
        return (_audio(result, sample_rate),)


class AudioCut:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "audio": ("AUDIO",), "start_seconds": ("FLOAT", {"default": 0.0, "min": 0.0}),
            "end_seconds": ("FLOAT", {"default": 10.0, "min": 0.0}),
        }}

    RETURN_TYPES = ("AUDIO", "FLOAT")
    RETURN_NAMES = ("audio", "duration")
    FUNCTION = "execute"
    CATEGORY = "video/audio"

    def execute(self, audio, start_seconds, end_seconds):
        waveform, sample_rate = _parts(audio)
        start = min(waveform.shape[-1], round(start_seconds * sample_rate))
        end = min(waveform.shape[-1], round(end_seconds * sample_rate))
        if end < start:
            raise ValueError("end_seconds must be greater than or equal to start_seconds")
        result = waveform[..., start:end]
        return _audio(result, sample_rate), (end - start) / sample_rate


AUDIO_NODE_CLASS_MAPPINGS = {
    "AudioExtract": AudioExtract,
    "AudioFromVideo": AudioFromVideo,
    "AudioMerge": AudioMerge,
    "AudioVolume": AudioVolume,
    "AudioFade": AudioFade,
    "AudioInfo": AudioInfo,
    "AudioMix": AudioMix,
    "AudioFitToVideo": AudioFitToVideo,
    "AudioLoop": AudioLoop,
    "AudioCut": AudioCut,
}

AUDIO_NODE_DISPLAY_NAME_MAPPINGS = {
    "AudioExtract": "Audio Extract",
    "AudioFromVideo": "Audio From Video",
    "AudioMerge": "Audio Merge",
    "AudioVolume": "Audio Volume",
    "AudioFade": "Audio Fade",
    "AudioInfo": "Audio Info",
    "AudioMix": "Audio Mix",
    "AudioFitToVideo": "Audio Fit To Video",
    "AudioLoop": "Audio Loop",
    "AudioCut": "Audio Cut",
}
