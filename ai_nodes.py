"""
AI 辅助节点 - 自动字幕、自动配音
"""
import torch
import numpy as np
import os
import tempfile
import subprocess
import json


# ============================================================
# Auto Subtitle (Whisper) - 自动字幕
# ============================================================

class AutoSubtitle:
    """
    自动字幕：使用 Whisper 模型从音频生成字幕。
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "audio": ("AUDIO", {"tooltip": "音频数据"}),
                "language": (["auto", "zh", "en", "ja", "ko"], {"default": "auto",
                    "tooltip": "语言选择"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("srt_content", "segments_json")
    FUNCTION = "execute"
    CATEGORY = "video/ai"

    def execute(self, audio: torch.Tensor, language: str):
        
        # 检查是否安装了 whisper
        try:
            import whisper
        except ImportError:
            return ("", "[]")
        
        if audio is None or audio.numel() == 0:
            return ("", "[]")
        
        # 转换音频格式
        audio_np = audio.cpu().numpy()
        if audio_np.dtype != np.float32:
            audio_np = audio_np.astype(np.float32)
        
        # 合并为单声道
        if len(audio_np.shape) > 1:
            audio_np = audio_np.mean(axis=0)
        
        # 加载模型（使用最小的模型以提高速度）
        try:
            model = whisper.load_model("base")
        except Exception as e:
            print(f"[Video Split] Whisper model load error: {e}")
            return ("", "[]")
        
        # 识别语言
        if language == "auto":
            # 简单的语言检测
            detect_lang = "zh"  # 默认中文
        else:
            detect_lang = language
        
        # 转录
        try:
            result = model.transcribe(audio_np, language=detect_lang)
        except Exception as e:
            print(f"[Video Split] Transcription error: {e}")
            return ("", "[]")
        
        # 生成 SRT 格式
        srt_content = self.generate_srt(result.get("segments", []))
        
        # 生成 JSON 格式
        segments_json = json.dumps(result.get("segments", []), ensure_ascii=False)
        
        return (srt_content, segments_json)
    
    def generate_srt(self, segments):
        """生成 SRT 字幕格式"""
        srt_lines = []
        
        for i, seg in enumerate(segments, 1):
            start = self.format_timestamp(seg.get("start", 0))
            end = self.format_timestamp(seg.get("end", 0))
            text = seg.get("text", "")
            
            srt_lines.append(f"{i}")
            srt_lines.append(f"{start} --> {end}")
            srt_lines.append(text)
            srt_lines.append("")
        
        return "\n".join(srt_lines)
    
    def format_timestamp(self, seconds):
        """格式化时间戳为 SRT 格式"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


# ============================================================
# Auto Subtitle From File - 从音频文件生成字幕
# ============================================================

class AutoSubtitleFromFile:
    """
    从音频文件生成字幕（更稳定）。
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "audio_path": ("STRING", {"default": "", "tooltip": "音频文件路径"}),
                "language": (["auto", "zh", "en", "ja", "ko"], {"default": "auto"}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("srt_content",)
    FUNCTION = "execute"
    CATEGORY = "video/ai"

    def execute(self, audio_path: str, language: str):
        
        if not audio_path or not os.path.exists(audio_path):
            return ("",)
        
        # 检查是否安装了 whisper
        try:
            import whisper
        except ImportError:
            print("[Video Split] Whisper not installed. Install with: pip install openai-whisper")
            return ("",)
        
        try:
            model = whisper.load_model("base")
            result = model.transcribe(audio_path, language=language if language != "auto" else None)
            
            srt_content = self.generate_srt(result.get("segments", []))
            return (srt_content,)
        except Exception as e:
            print(f"[Video Split] Subtitle generation error: {e}")
            return ("",)
    
    def generate_srt(self, segments):
        """生成 SRT 字幕格式"""
        srt_lines = []
        
        for i, seg in enumerate(segments, 1):
            start = self.format_timestamp(seg.get("start", 0))
            end = self.format_timestamp(seg.get("end", 0))
            text = seg.get("text", "")
            
            srt_lines.append(f"{i}")
            srt_lines.append(f"{start} --> {end}")
            srt_lines.append(text)
            srt_lines.append("")
        
        return "\n".join(srt_lines)
    
    def format_timestamp(self, seconds):
        """格式化时间戳"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


# ============================================================
# Auto TTS (Edge-TTS) - 自动配音
# ============================================================

class AutoTTS:
    """
    自动配音：使用 Edge-TTS 将文字转为语音。
    免费、无需 API Key。
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {"default": "你好，这是一个测试。", "multiline": True,
                    "tooltip": "要转换的文字"}),
                "voice": (["zh-CN-XiaoxiaoNeural", "zh-CN-YunxiNeural", "zh-CN-YunjianNeural",
                           "zh-CN-XiaoyiNeural", "zh-CN-YunyangNeural", "zh-CN-langbcNeural"],
                    {"default": "zh-CN-XiaoxiaoNeural", "tooltip": "音色选择"}),
                "rate": ("INT", {"default": 0, "min": -50, "max": 50,
                    "tooltip": "语速调整（-50慢，50快）"}),
            },
        }

    RETURN_TYPES = ("AUDIO", "STRING")
    RETURN_NAMES = ("audio", "audio_path")
    FUNCTION = "execute"
    CATEGORY = "video/ai"

    def execute(self, text: str, voice: str, rate: int):
        
        # 检查是否安装了 edge-tts
        try:
            import edge_tts
        except ImportError:
            print("[Video Split] edge-tts not installed. Install with: pip install edge-tts")
            return (torch.zeros(1, 1), "")
        
        if not text.strip():
            return (torch.zeros(1, 1), "")
        
        # 创建临时文件
        temp_audio = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        temp_audio.close()
        
        try:
            # 生成语音
            rate_str = f"+{rate}%" if rate > 0 else f"{rate}%"
            communicate = edge_tts.Communicate(text, voice, rate=rate_str)
            communicate.save(temp_audio.name)
            
            # 读取音频文件
            audio_tensor = self.load_audio(temp_audio.name)
            
            return (audio_tensor, temp_audio.name)
            
        except Exception as e:
            print(f"[Video Split] TTS error: {e}")
            return (torch.zeros(1, 1), "")
    
    def load_audio(self, audio_path):
        """加载音频文件为张量"""
        try:
            import av
            
            container = av.open(audio_path)
            audio_stream = container.streams.audio[0]
            
            audio_frames = []
            for frame in container.decode(audio_stream):
                audio_data = frame.to_ndarray()
                audio_frames.append(audio_data)
            
            container.close()
            
            if not audio_frames:
                return torch.zeros(1, 1)
            
            audio_array = np.concatenate(audio_frames, axis=1)
            audio_tensor = torch.from_numpy(audio_array).float()
            
            return audio_tensor
            
        except Exception as e:
            print(f"[Video Split] Audio load error: {e}")
            return torch.zeros(1, 1)


# ============================================================
# Auto TTS Simple - 简化版配音
# ============================================================

class AutoTTSSimple:
    """
    简化版配音：直接输出音频文件路径。
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {"default": "", "multiline": True}),
                "voice": (["zh-CN-XiaoxiaoNeural", "zh-CN-YunxiNeural"],
                    {"default": "zh-CN-XiaoxiaoNeural"}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("audio_path",)
    FUNCTION = "execute"
    CATEGORY = "video/ai"

    def execute(self, text: str, voice: str):
        
        try:
            import edge_tts
        except ImportError:
            return ("",)
        
        if not text.strip():
            return ("",)
        
        temp_audio = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        temp_audio.close()
        
        try:
            communicate = edge_tts.Communicate(text, voice)
            communicate.save(temp_audio.name)
            return (temp_audio.name,)
        except Exception as e:
            print(f"[Video Split] TTS error: {e}")
            return ("",)


# ============================================================
# Node Mappings
# ============================================================

AI_NODE_CLASS_MAPPINGS = {
    "AutoSubtitle": AutoSubtitle,
    "AutoSubtitleFromFile": AutoSubtitleFromFile,
    "AutoTTS": AutoTTS,
    "AutoTTSSimple": AutoTTSSimple,
}

AI_NODE_DISPLAY_NAME_MAPPINGS = {
    "AutoSubtitle": "Auto Subtitle (Whisper)",
    "AutoSubtitleFromFile": "Auto Subtitle From File",
    "AutoTTS": "Auto TTS (Edge-TTS)",
    "AutoTTSSimple": "Auto TTS Simple",
}