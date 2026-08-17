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


def _audio_field(audio, name):
    """Read a field from dict-like and lazy ComfyUI AUDIO payloads."""
    getter = getattr(audio, "get", None)
    if getter is not None:
        value = getter(name)
        if value is not None:
            return value
    try:
        return audio[name]
    except (KeyError, TypeError, AttributeError):
        return getattr(audio, name, None)


def _parts(audio):
    """读取 ComfyUI AUDIO，兼容 VHS 的 LazyAudioMap。"""
    if not isinstance(audio, dict) and not hasattr(audio, "__getitem__"):
        raise TypeError(
            f"AUDIO must be dict-like, got {type(audio).__name__}. "
            "Connect an AUDIO output such as VHS LoadVideo audio."
        )

    # VHS may defer decoding and pass LazyAudioMap rather than a dict.
    waveform = _audio_field(audio, "waveform")
    if waveform is None:
        waveform = _audio_field(audio, "samples")
    sample_rate = _audio_field(audio, "sample_rate")
    if sample_rate is None:
        sample_rate = _audio_field(audio, "rate")
    if waveform is None or sample_rate is None:
        raise TypeError(
            "Unsupported AUDIO payload. Expected waveform/samples and "
            f"sample_rate/rate; received {type(audio).__name__}"
        )
    return waveform, int(sample_rate)


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


class AudioConcat:
    """按时间顺序拼接多段音频。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"audio1": ("AUDIO",)}, "optional": {
            "audio2": ("AUDIO",),
            "audio3": ("AUDIO",),
            "audio4": ("AUDIO",),
        }}

    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ("audio",)
    FUNCTION = "execute"
    CATEGORY = "video/audio"

    def execute(self, audio1, audio2=None, audio3=None, audio4=None):
        tracks = [audio1] + [audio for audio in (audio2, audio3, audio4) if audio is not None]
        reference, sample_rate = _parts(tracks[0])
        if reference.ndim != 3 or reference.shape[0] != 1:
            raise ValueError("AudioConcat supports one audio batch at a time")

        target_channels = reference.shape[1]
        waveforms = []
        for audio in tracks:
            waveform, track_rate = _parts(audio)
            if waveform.ndim != 3 or waveform.shape[0] != 1:
                raise ValueError("AudioConcat supports one audio batch at a time")
            waveform = waveform.to(device=reference.device, dtype=reference.dtype)
            if track_rate != sample_rate:
                new_length = round(waveform.shape[-1] * sample_rate / track_rate)
                waveform = F.interpolate(
                    waveform, size=new_length, mode="linear", align_corners=False
                )
            if waveform.shape[1] != target_channels:
                if target_channels == 1:
                    waveform = waveform.mean(dim=1, keepdim=True)
                elif waveform.shape[1] == 1:
                    waveform = waveform.expand(-1, target_channels, -1)
                else:
                    raise ValueError(
                        f"AudioConcat cannot convert {waveform.shape[1]} channels to {target_channels}"
                    )
            waveforms.append(waveform)

        return (_audio(torch.cat(waveforms, dim=-1), sample_rate),)


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


class AudioCompose:
    """
    音频合成定位节点 - 严格时间轴对齐版。
    
    采用帧数作为统一时间基准，确保音画精确同步：
    - 输入使用浮点秒，但内部转换为精确的帧数/采样数
    - 视频帧率作为时间轴转换的桥梁
    - 所有时间点都对齐到采样网格
    
    使用场景：
    - 视频配音：不同角色的台词在不同时间点播放
    - BGM+配音混合：背景音乐贯穿全程，配音在特定时间点插入
    - 音效叠加：特定时间点添加音效
    """
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "total_frames": ("INT", {"default": 1440, "min": 1, "max": 864000,
                    "tooltip": "视频总帧数，用于精确时间计算"}),
                "fps": ("FLOAT", {"default": 24.0, "min": 1.0, "max": 240.0,
                    "tooltip": "视频帧率，作为时间轴转换的基准"}),
                "sample_rate": ("INT", {"default": 44100, "min": 8000, "max": 192000}),
            },
            "optional": {
                # 音频段1
                "audio1": ("AUDIO", {"tooltip": "第一段音频"}),
                "start_frame1": ("INT", {"default": 0, "min": 0, "max": 864000,
                    "tooltip": "第一段音频的起始帧（精确对齐视频）"}),
                # 音频段2
                "audio2": ("AUDIO",),
                "start_frame2": ("INT", {"default": 0, "min": 0, "max": 864000}),
                # 音频段3
                "audio3": ("AUDIO",),
                "start_frame3": ("INT", {"default": 0, "min": 0, "max": 864000}),
                # 音频段4
                "audio4": ("AUDIO",),
                "start_frame4": ("INT", {"default": 0, "min": 0, "max": 864000}),
            }
        }

    RETURN_TYPES = ("AUDIO", "FLOAT", "INT")
    RETURN_NAMES = ("audio", "duration_seconds", "total_samples")
    FUNCTION = "execute"
    CATEGORY = "video/audio"
    DESCRIPTION = "音频定位合成 - 严格帧级对齐"

    @staticmethod
    def _frame_to_sample(frame: int, fps: float, sample_rate: int) -> int:
        """帧数 → 采样数（精确转换）"""
        return int(round(frame * sample_rate / fps))
    
    @staticmethod
    def _sample_to_frame(sample: int, fps: float, sample_rate: int) -> int:
        """采样数 → 帧数（精确转换）"""
        return int(round(sample * fps / sample_rate))
    
    @staticmethod
    def _time_to_frame(time_seconds: float, fps: float) -> int:
        """秒 → 帧数（精确转换）"""
        return int(round(time_seconds * fps))
    
    @staticmethod
    def _frame_to_time(frame: int, fps: float) -> float:
        """帧数 → 秒（精确转换）"""
        return frame / fps

    def execute(self, total_frames, fps, sample_rate, audio1=None, start_frame1=0,
                audio2=None, start_frame2=0, audio3=None, start_frame3=0,
                audio4=None, start_frame4=0):
        
        # 收集所有音频段和对应的起始帧
        audio_segments = []
        for audio, start_frame in [
            (audio1, start_frame1),
            (audio2, start_frame2),
            (audio3, start_frame3),
            (audio4, start_frame4),
        ]:
            if audio is not None:
                audio_segments.append((audio, start_frame))
        
        if not audio_segments:
            # 没有音频段，返回静音
            total_samples = self._frame_to_sample(total_frames, fps, sample_rate)
            waveform = torch.zeros(1, 1, total_samples, dtype=torch.float32)
            return (_audio(waveform, sample_rate), total_frames / fps, total_samples)
        
        # 获取第一个音频的设备/dtype作为参考
        first_audio, _ = audio_segments[0]
        ref_waveform, ref_rate = _parts(first_audio)
        device = ref_waveform.device
        dtype = ref_waveform.dtype
        
        # 计算总采样数（精确）
        total_samples = self._frame_to_sample(total_frames, fps, sample_rate)
        
        # 创建空白轨道（静音）
        result = torch.zeros(1, 1, total_samples, device=device, dtype=dtype)
        
        # 放置每段音频到指定位置（严格帧级对齐）
        for audio, start_frame in audio_segments:
            waveform, audio_rate = _parts(audio)
            
            # 统一转为单声道
            if waveform.shape[1] > 1:
                waveform = waveform.mean(dim=1, keepdim=True)
            elif waveform.shape[1] == 0:
                continue
            
            # 如果采样率不同，进行重采样（保持精确长度）
            if audio_rate != sample_rate:
                new_length = round(waveform.shape[-1] * sample_rate / audio_rate)
                waveform = F.interpolate(
                    waveform, size=new_length, mode="linear", align_corners=False
                )
            
            # 精确计算起始位置（帧 → 采样）
            start_sample = self._frame_to_sample(start_frame, fps, sample_rate)
            end_sample = start_sample + waveform.shape[-1]
            
            # 裁剪到总长度范围内
            actual_start = max(0, start_sample)
            actual_end = min(total_samples, end_sample)
            
            # 对应的音频片段范围
            audio_start = actual_start - start_sample
            audio_end = audio_start + (actual_end - actual_start)
            
            if audio_end > audio_start:
                # 混合到结果中（允许叠加）
                result[..., actual_start:actual_end] += waveform[..., audio_start:audio_end].to(device=device, dtype=dtype)
        
        # 限制振幅
        result = result.clamp(-1, 1)
        
        # 返回音频、精确时长（秒）、总采样数
        duration_seconds = total_frames / fps  # 精确计算
        return (_audio(result, sample_rate), duration_seconds, total_samples)


class AudioComposeByTime:
    """
    音频合成定位节点 - 浮点秒输入版（带精度警告）。
    
    内部自动处理精度问题，但仍推荐使用 AudioCompose 的帧级版本。
    """
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "total_duration": ("FLOAT", {"default": 60.0, "min": 0.1, "max": 36000.0, "step": 0.001,
                    "tooltip": "总音频时长（秒），建议使用整数或精确分数"}),
                "fps": ("FLOAT", {"default": 24.0, "min": 1.0, "max": 240.0,
                    "tooltip": "视频帧率，用于时间基准转换"}),
                "sample_rate": ("INT", {"default": 44100, "min": 8000, "max": 192000}),
            },
            "optional": {
                "audio1": ("AUDIO",),
                "start_time1": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 36000.0, "step": 0.001}),
                "audio2": ("AUDIO",),
                "start_time2": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 36000.0, "step": 0.001}),
                "audio3": ("AUDIO",),
                "start_time3": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 36000.0, "step": 0.001}),
                "audio4": ("AUDIO",),
                "start_time4": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 36000.0, "step": 0.001}),
            }
        }

    RETURN_TYPES = ("AUDIO", "FLOAT", "INT")
    RETURN_NAMES = ("audio", "duration_seconds", "total_samples")
    FUNCTION = "execute"
    CATEGORY = "video/audio"
    DESCRIPTION = "音频定位合成 - 秒级输入（精度较低）"

    def execute(self, total_duration, fps, sample_rate, audio1=None, start_time1=0.0,
                audio2=None, start_time2=0.0, audio3=None, start_time3=0.0,
                audio4=None, start_time4=0.0):
        
        # 精确计算总帧数（避免浮点累积误差）
        total_frames = round(total_duration * fps)
        total_samples = round(total_frames * sample_rate / fps)
        
        audio_segments = []
        for audio, start_time in [
            (audio1, start_time1),
            (audio2, start_time2),
            (audio3, start_time3),
            (audio4, start_time4),
        ]:
            if audio is not None:
                audio_segments.append((audio, start_time))
        
        if not audio_segments:
            waveform = torch.zeros(1, 1, total_samples, dtype=torch.float32)
            return (_audio(waveform, sample_rate), total_frames / fps, total_samples)
        
        first_audio, _ = audio_segments[0]
        ref_waveform, ref_rate = _parts(first_audio)
        device = ref_waveform.device
        dtype = ref_waveform.dtype
        
        result = torch.zeros(1, 1, total_samples, device=device, dtype=dtype)
        
        for audio, start_time in audio_segments:
            waveform, audio_rate = _parts(audio)
            
            if waveform.shape[1] > 1:
                waveform = waveform.mean(dim=1, keepdim=True)
            elif waveform.shape[1] == 0:
                continue
            
            if audio_rate != sample_rate:
                new_length = round(waveform.shape[-1] * sample_rate / audio_rate)
                waveform = F.interpolate(waveform, size=new_length, mode="linear", align_corners=False)
            
            # 精确转换：秒 → 帧 → 采样
            start_frame = round(start_time * fps)
            start_sample = round(start_frame * sample_rate / fps)
            end_sample = start_sample + waveform.shape[-1]
            
            actual_start = max(0, start_sample)
            actual_end = min(total_samples, end_sample)
            
            audio_start = actual_start - start_sample
            audio_end = audio_start + (actual_end - actual_start)
            
            if audio_end > audio_start:
                result[..., actual_start:actual_end] += waveform[..., audio_start:audio_end].to(device=device, dtype=dtype)
        
        result = result.clamp(-1, 1)
        duration_seconds = total_frames / fps
        
        return (_audio(result, sample_rate), duration_seconds, total_samples)


class AudioComposeAdvanced:
    """
    高级音频合成节点 - 支持更多音频段和音量控制。
    
    使用场景：
    - 复杂的多轨音频合成
    - 需要精确控制每段音频的音量
    - 循环背景音乐 + 多次配音
    """
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "total_duration": ("FLOAT", {"default": 60.0, "min": 0.1, "max": 36000.0, "step": 0.1}),
                "sample_rate": ("INT", {"default": 44100, "min": 8000, "max": 192000}),
            },
            "optional": {
                "audio_list": ("AUDIO", {"tooltip": "音频列表（多个音频）"}),
                "start_times": ("STRING", {"default": "0,10,20,30", 
                    "tooltip": "每段音频的起始时间，用逗号分隔。例如: 0,10,20,30"}),
                "volumes": ("STRING", {"default": "1.0,0.8,1.0,0.6",
                    "tooltip": "每段音频的音量，用逗号分隔。例如: 1.0,0.8,1.0,0.6"}),
            }
        }

    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ("audio",)
    FUNCTION = "execute"
    CATEGORY = "video/audio"
    DESCRIPTION = "高级音频合成 - 支持多段音频定位和音量控制"

    def execute(self, total_duration, sample_rate, audio_list=None, 
                start_times="0,10,20,30", volumes="1.0,0.8,1.0,0.6"):
        
        # 解析参数
        try:
            start_time_list = [float(t.strip()) for t in start_times.split(",") if t.strip()]
        except ValueError:
            raise ValueError("start_times 必须是逗号分隔的数字列表，例如: 0,10,20,30")
        
        try:
            volume_list = [float(v.strip()) for v in volumes.split(",") if v.strip()]
        except ValueError:
            raise ValueError("volumes 必须是逗号分隔的数字列表，例如: 1.0,0.8,1.0,0.6")
        
        # 如果有音频列表
        if audio_list is not None:
            if isinstance(audio_list, dict):
                # 单个音频
                audio_segments = [(audio_list, start_time_list[0] if start_time_list else 0.0, 
                                  volume_list[0] if volume_list else 1.0)]
            else:
                # 音频列表
                audio_segments = []
                for i, audio in enumerate(audio_list):
                    if audio is not None:
                        start_time = start_time_list[i] if i < len(start_time_list) else 0.0
                        volume = volume_list[i] if i < len(volume_list) else 1.0
                        audio_segments.append((audio, start_time, volume))
        else:
            audio_segments = []
        
        if not audio_segments:
            total_samples = round(total_duration * sample_rate)
            waveform = torch.zeros(1, 1, total_samples, dtype=torch.float32)
            return (_audio(waveform, sample_rate),)
        
        # 创建结果轨道
        device = torch.device("cpu")
        dtype = torch.float32
        total_samples = round(total_duration * sample_rate)
        result = torch.zeros(1, 1, total_samples, dtype=dtype)
        
        for audio, start_time, volume in audio_segments:
            waveform, audio_rate = _parts(audio)
            
            if waveform.shape[1] > 1:
                waveform = waveform.mean(dim=1, keepdim=True)
            elif waveform.shape[1] == 0:
                continue
            
            if audio_rate != sample_rate:
                new_length = round(waveform.shape[-1] * sample_rate / audio_rate)
                waveform = F.interpolate(waveform, size=new_length, mode="linear", align_corners=False)
            
            # 应用音量
            waveform = waveform * volume
            
            start_sample = round(start_time * sample_rate)
            end_sample = start_sample + waveform.shape[-1]
            
            actual_start = max(0, start_sample)
            actual_end = min(total_samples, end_sample)
            
            audio_start = actual_start - start_sample
            audio_end = audio_start + (actual_end - actual_start)
            
            if audio_end > audio_start:
                result[..., actual_start:actual_end] += waveform[..., audio_start:audio_end]
        
        result = result.clamp(-1, 1)
        return (_audio(result, sample_rate),)


AUDIO_NODE_CLASS_MAPPINGS = {
    "AudioExtract": AudioExtract,
    "AudioFromVideo": AudioFromVideo,
    "AudioMerge": AudioMerge,
    "AudioVolume": AudioVolume,
    "AudioFade": AudioFade,
    "AudioInfo": AudioInfo,
    "AudioMix": AudioMix,
    "VideoSplitAudioConcat": AudioConcat,
    "AudioFitToVideo": AudioFitToVideo,
    "AudioLoop": AudioLoop,
    "AudioCut": AudioCut,
    "AudioCompose": AudioCompose,
    "AudioComposeByTime": AudioComposeByTime,
    "AudioComposeAdvanced": AudioComposeAdvanced,
}

AUDIO_NODE_DISPLAY_NAME_MAPPINGS = {
    "AudioExtract": "Audio Extract",
    "AudioFromVideo": "Audio From Video",
    "AudioMerge": "Audio Merge",
    "AudioVolume": "Audio Volume",
    "AudioFade": "Audio Fade",
    "AudioInfo": "Audio Info",
    "AudioMix": "Audio Mix",
    "VideoSplitAudioConcat": "Audio Concat (Video Split)",
    "AudioFitToVideo": "Audio Fit To Video",
    "AudioLoop": "Audio Loop",
    "AudioCut": "Audio Cut",
    "AudioCompose": "Audio Compose (Frame-aligned)",
    "AudioComposeByTime": "Audio Compose (Time-based)",
    "AudioComposeAdvanced": "Audio Compose (Advanced)",
}
