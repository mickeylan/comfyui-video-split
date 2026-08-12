"""
音频处理节点 - 使用 PyAV 实现
"""
import torch
import numpy as np
import tempfile
import os
import io

try:
    import av
    PYAV_AVAILABLE = True
except ImportError:
    PYAV_AVAILABLE = False
    print("[Video Split] Warning: PyAV not installed. Audio nodes will not work.")
    print("[Video Split] Install with: pip install av")


# ============================================================
# Audio Extract - 从视频提取音频
# ============================================================

class AudioExtract:
    """
    从视频中提取音频数据。
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video_path": ("STRING", {"default": "", "tooltip": "视频文件路径"}),
            },
        }

    RETURN_TYPES = ("AUDIO", "INT", "INT")
    RETURN_NAMES = ("audio", "sample_rate", "duration_ms")
    FUNCTION = "execute"
    CATEGORY = "video/audio"
    OUTPUT_IS_LIST = (False, False, False)

    def execute(self, video_path: str):
        if not PYAV_AVAILABLE:
            raise ImportError("PyAV is required for audio processing. Install with: pip install av")
        
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")
        
        container = av.open(video_path)
        
        # 查找音频流
        audio_stream = None
        for stream in container.streams:
            if stream.type == 'audio':
                audio_stream = stream
                break
        
        if audio_stream is None:
            container.close()
            raise ValueError(f"No audio stream found in {video_path}")
        
        # 提取音频数据
        audio_frames = []
        for frame in container.decode(audio_stream):
            audio_data = frame.to_ndarray()
            audio_frames.append(audio_data)
        
        if not audio_frames:
            container.close()
            raise ValueError("Failed to decode audio frames")
        
        # 合并所有帧
        audio_array = np.concatenate(audio_frames, axis=1)
        
        # 转为 torch 张量
        audio_tensor = torch.from_numpy(audio_array).float()
        
        sample_rate = audio_stream.rate
        duration_ms = int(container.duration / 1000)
        
        container.close()
        
        return (audio_tensor, sample_rate, duration_ms)


# ============================================================
# Audio From Video - 从视频张量提取音频（需要临时文件）
# ============================================================

class AudioFromVideo:
    """
    从视频张量提取音频（通过临时文件）。
    配合 VHS Load Video 使用。
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video_path": ("STRING", {"default": "", "tooltip": "视频文件路径（来自 VHS Load Video）"}),
            },
        }

    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ("audio",)
    FUNCTION = "execute"
    CATEGORY = "video/audio"

    def execute(self, video_path: str):
        if not PYAV_AVAILABLE:
            raise ImportError("PyAV is required. Install with: pip install av")
        
        if not video_path or not os.path.exists(video_path):
            # 返回空音频
            return (torch.zeros(1, 1),)
        
        try:
            container = av.open(video_path)
            
            audio_stream = None
            for stream in container.streams:
                if stream.type == 'audio':
                    audio_stream = stream
                    break
            
            if audio_stream is None:
                container.close()
                return (torch.zeros(1, 1),)
            
            audio_frames = []
            for frame in container.decode(audio_stream):
                audio_data = frame.to_ndarray()
                audio_frames.append(audio_data)
            
            container.close()
            
            if not audio_frames:
                return (torch.zeros(1, 1),)
            
            audio_array = np.concatenate(audio_frames, axis=1)
            audio_tensor = torch.from_numpy(audio_array).float()
            
            return (audio_tensor,)
            
        except Exception as e:
            print(f"[Video Split] Audio extraction error: {e}")
            return (torch.zeros(1, 1),)


# ============================================================
# Audio Merge - 音频合并到视频
# ============================================================

class AudioMerge:
    """
    将音频合并到视频（输出为视频文件）。
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "视频帧张量"}),
                "audio": ("AUDIO", {"tooltip": "音频数据"}),
                "fps": ("FLOAT", {"default": 24.0, "min": 1.0, "max": 120.0, "tooltip": "视频帧率"}),
                "output_path": ("STRING", {"default": "output.mp4", "tooltip": "输出文件路径"}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("video_path",)
    FUNCTION = "execute"
    CATEGORY = "video/audio"

    def execute(self, images: torch.Tensor, audio: torch.Tensor, 
                fps: float, output_path: str):
        if not PYAV_AVAILABLE:
            raise ImportError("PyAV is required. Install with: pip install av")
        
        # 确保输出目录存在
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)
        
        total_frames = images.shape[0]
        height = images.shape[1]
        width = images.shape[2]
        
        # 创建输出容器
        container = av.open(output_path, 'w')
        
        # 添加视频流
        video_stream = container.add_stream('h264', rate=fps)
        video_stream.width = width
        video_stream.height = height
        video_stream.pix_fmt = 'yuv420p'
        
        # 添加音频流
        if audio is not None and audio.numel() > 0:
            audio_stream = container.add_stream('aac')
            audio_stream.rate = 44100
            audio_stream.channels = 2 if audio.shape[0] > 1 else 1
        
        # 编码视频帧
        for i in range(total_frames):
            frame = images[i].cpu().numpy()
            # RGB to uint8
            frame = (frame * 255).astype('uint8')
            
            # 创建视频帧
            video_frame = av.VideoFrame.from_ndarray(frame, format='rgb24')
            video_frame.pict_type = 'I' if i == 0 else None
            
            for packet in video_stream.encode(video_frame):
                container.mux(packet)
        
        # 编码音频帧
        if audio is not None and audio.numel() > 0:
            audio_np = audio.cpu().numpy()
            if audio_np.dtype != np.float32:
                audio_np = audio_np.astype(np.float32)
            
            # 创建音频帧
            audio_frame = av.AudioFrame.from_ndarray(audio_np, format='flt', layout='stereo' if audio_np.shape[0] > 1 else 'mono')
            
            for packet in audio_stream.encode(audio_frame):
                container.mux(packet)
            
            # 刷新音频编码器
            for packet in audio_stream.encode():
                container.mux(packet)
        
        # 刷新视频编码器
        for packet in video_stream.encode():
            container.mux(packet)
        
        container.close()
        
        return (output_path,)


# ============================================================
# Audio Volume - 音量调节
# ============================================================

class AudioVolume:
    """
    调节音频音量。
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "audio": ("AUDIO", {"tooltip": "音频数据"}),
                "volume": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 10.0, "step": 0.1,
                    "tooltip": "音量倍数（1.0=原始，2.0=两倍音量）"}),
            },
        }

    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ("audio",)
    FUNCTION = "execute"
    CATEGORY = "video/audio"

    def execute(self, audio: torch.Tensor, volume: float):
        if audio is None or audio.numel() == 0:
            return (audio,)
        
        # 调节音量
        adjusted = audio * volume
        
        # 限制在有效范围
        adjusted = torch.clamp(adjusted, -1.0, 1.0)
        
        return (adjusted,)


# ============================================================
# Audio Fade - 音频淡入淡出
# ============================================================

class AudioFade:
    """
    音频淡入淡出效果。
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "audio": ("AUDIO", {"tooltip": "音频数据"}),
                "fade_in_ms": ("INT", {"default": 500, "min": 0, "max": 60000,
                    "tooltip": "淡入时长（毫秒）"}),
                "fade_out_ms": ("INT", {"default": 500, "min": 0, "max": 60000,
                    "tooltip": "淡出时长（毫秒）"}),
                "sample_rate": ("INT", {"default": 44100, "min": 1, "max": 192000,
                    "tooltip": "采样率"}),
            },
        }

    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ("audio",)
    FUNCTION = "execute"
    CATEGORY = "video/audio"

    def execute(self, audio: torch.Tensor, fade_in_ms: int, fade_out_ms: int, 
                sample_rate: int):
        if audio is None or audio.numel() == 0:
            return (audio,)
        
        audio = audio.clone()
        
        # 计算淡入淡出采样数
        fade_in_samples = int(fade_in_ms * sample_rate / 1000)
        fade_out_samples = int(fade_out_ms * sample_rate / 1000)
        
        total_samples = audio.shape[-1]
        
        # 淡入
        if fade_in_samples > 0 and fade_in_samples < total_samples:
            fade_in_curve = torch.linspace(0, 1, fade_in_samples)
            audio[:, :fade_in_samples] *= fade_in_curve
        
        # 淡出
        if fade_out_samples > 0 and fade_out_samples < total_samples:
            fade_out_start = total_samples - fade_out_samples
            fade_out_curve = torch.linspace(1, 0, fade_out_samples)
            audio[:, fade_out_start:] *= fade_out_curve
        
        return (audio,)


# ============================================================
# Audio Info - 获取音频信息
# ============================================================

class AudioInfo:
    """
    获取音频信息。
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "audio": ("AUDIO", {"tooltip": "音频数据"}),
            },
        }

    RETURN_TYPES = ("INT", "INT", "FLOAT")
    RETURN_NAMES = ("channels", "samples", "duration_seconds")
    FUNCTION = "execute"
    CATEGORY = "video/audio"

    def execute(self, audio: torch.Tensor):
        if audio is None or audio.numel() == 0:
            return (0, 0, 0.0)
        
        channels = audio.shape[0] if len(audio.shape) > 0 else 1
        samples = audio.shape[-1] if len(audio.shape) > 0 else 0
        
        # 假设采样率为 44100
        duration_seconds = samples / 44100.0
        
        return (channels, samples, duration_seconds)


# ============================================================
# Node Mappings
# ============================================================

AUDIO_NODE_CLASS_MAPPINGS = {
    "AudioExtract": AudioExtract,
    "AudioFromVideo": AudioFromVideo,
    "AudioMerge": AudioMerge,
    "AudioVolume": AudioVolume,
    "AudioFade": AudioFade,
    "AudioInfo": AudioInfo,
}

AUDIO_NODE_DISPLAY_NAME_MAPPINGS = {
    "AudioExtract": "Audio Extract",
    "AudioFromVideo": "Audio From Video",
    "AudioMerge": "Audio Merge",
    "AudioVolume": "Audio Volume",
    "AudioFade": "Audio Fade",
    "AudioInfo": "Audio Info",
}