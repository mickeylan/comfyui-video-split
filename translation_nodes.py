"""
翻译相关节点：人声分离、语音识别、翻译、TTS、音频替换
支持本地 Ollama、DeepLX、OpenAI API 多种翻译后端
"""
import os
import json
import tempfile
import asyncio
from typing import Dict, List, Optional, Tuple, Any

import numpy as np
import torch
import torch.nn.functional as F

import folder_paths

try:
    import av
    PYAV_AVAILABLE = True
except ImportError:
    PYAV_AVAILABLE = False

try:
    import whisper
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False

try:
    import edge_tts
    EDGE_TTS_AVAILABLE = True
except ImportError:
    EDGE_TTS_AVAILABLE = False


# ============================================================
# 辅助函数
# ============================================================

def _audio(waveform, sample_rate):
    """构建 ComfyUI 标准 AUDIO 格式"""
    if waveform.ndim == 2:
        waveform = waveform.unsqueeze(0)
    return {"waveform": waveform, "sample_rate": int(sample_rate)}


def _audio_field(audio, name):
    """读取 AUDIO 字段，兼容多种格式"""
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
    """解析 AUDIO 获取 waveform 和 sample_rate"""
    if not isinstance(audio, dict) and not hasattr(audio, "__getitem__"):
        raise TypeError(f"AUDIO must be dict-like, got {type(audio).__name__}")
    
    waveform = _audio_field(audio, "waveform")
    if waveform is None:
        waveform = _audio_field(audio, "samples")
    sample_rate = _audio_field(audio, "sample_rate")
    if sample_rate is None:
        sample_rate = _audio_field(audio, "rate")
    if waveform is None or sample_rate is None:
        raise TypeError("Unsupported AUDIO payload")
    return waveform, int(sample_rate)


def _safe_output_path(path: str) -> str:
    """安全获取输出路径"""
    output_dir = folder_paths.get_output_directory()
    full_path = os.path.abspath(path if os.path.isabs(path) else os.path.join(output_dir, path))
    if not folder_paths.is_within_directory(output_dir, full_path):
        raise ValueError("Output path must be inside ComfyUI output directory")
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    return full_path


def _run_async(coro):
    """在同步函数中安全运行异步代码"""
    try:
        loop = asyncio.get_running_loop()
        # 已经在事件循环中，创建一个新任务
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, coro)
            return future.result()
    except RuntimeError:
        # 没有运行中的事件循环
        return asyncio.run(coro)


def _check_ffmpeg():
    """检查 ffmpeg 是否可用"""
    import subprocess
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"], 
            capture_output=True, 
            text=True, 
            timeout=5
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _cleanup_temp_file(path: str):
    """安全清理临时文件"""
    try:
        if path and os.path.exists(path):
            os.unlink(path)
    except Exception:
        pass  # 忽略清理失败


# ============================================================
# 节点：Voice Separator (人声分离)
# ============================================================

class VoiceSeparator:
    """
    使用 Demucs 分离人声和背景音乐
    """
    _models = {}  # 缓存不同尺寸的模型

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "audio": ("AUDIO", {"tooltip": "输入音频"}),
                "model_size": (["small", "medium", "large"], {"default": "medium", 
                    "tooltip": "模型大小：small最快，large效果最好"}),
            },
        }

    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ("vocals",)
    FUNCTION = "separate"
    CATEGORY = "video/translation"

    @classmethod
    def load_model(cls, model_size: str):
        """加载 Demucs 模型（按尺寸缓存）"""
        if model_size in cls._models:
            return cls._models[model_size]
        
        try:
            from demucs.pretrained import get_model
            model = get_model(f'htdemucs_{model_size}')
            cls._models[model_size] = model
            return model
        except ImportError:
            raise ImportError("请安装 demucs: pip install demucs")
        except Exception as e:
            raise RuntimeError(f"加载 Demucs 模型失败: {e}")

    def separate(self, audio: Dict, model_size: str) -> Tuple[Dict]:
        """分离人声"""
        waveform, sample_rate = _parts(audio)
        
        # 转换为 numpy
        if isinstance(waveform, torch.Tensor):
            waveform = waveform.squeeze(0).cpu().numpy()
        else:
            waveform = np.array(waveform).squeeze()
        
        # 加载模型
        model = self.load_model(model_size)
        
        # Demucs 需要 (channels, samples) 格式，float32，范围 [-1, 1]
        if waveform.ndim == 1:
            waveform = np.stack([waveform, waveform])
        else:
            waveform = waveform.T  # (channels, samples)
        
        waveform = waveform.astype(np.float32)
        
        # 分离
        with torch.no_grad():
            sources = model.forward(torch.from_numpy(waveform).unsqueeze(0))
        
        # sources 格式: (1, 4, channels, samples) -> (4, channels, samples)
        # 4 个音轨: drums, bass, other, vocals
        sources = sources.squeeze(0).cpu().numpy()
        vocals = sources[3]  # vocals 是最后一个音轨
        
        # 转回 (channels, samples) 并合并为立体声
        vocals = vocals.mean(axis=0)  # 平均通道
        
        # 转换回 (2, samples) 立体声
        if vocals.ndim == 1:
            vocals = np.stack([vocals, vocals])
        
        # 转换回 tensor 格式
        vocals_tensor = torch.from_numpy(vocals.T).float().unsqueeze(0)
        
        return (_audio(vocals_tensor, sample_rate),)


class VoiceSeparatorV2:
    """
    人声分离节点 V2 - 支持多音轨输出
    
    使用 Demucs 分离出 4 个音轨：
    - drums: 鼓点
    - bass: 低音
    - other: 其他伴奏
    - vocals: 人声
    """
    _models = {}  # 缓存不同尺寸的模型

    # 音轨名称映射
    TRACK_NAMES = ["drums", "bass", "other", "vocals"]

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "audio": ("AUDIO", {"tooltip": "输入音频"}),
                "model_size": (["small", "medium", "large"], {"default": "medium", 
                    "tooltip": "模型大小：small最快，large效果最好"}),
                "output_mode": (["all", "vocals_only", "instrumental"], {"default": "all",
                    "tooltip": "输出模式：all(全部4轨), vocals_only(仅人声), instrumental(伴奏混合)"}),
            },
        }

    RETURN_TYPES = ("AUDIO", "AUDIO", "AUDIO", "AUDIO")
    RETURN_NAMES = ("drums", "bass", "other", "vocals")
    FUNCTION = "separate"
    CATEGORY = "video/translation"

    @classmethod
    def load_model(cls, model_size: str):
        """加载 Demucs 模型（按尺寸缓存）"""
        if model_size in cls._models:
            return cls._models[model_size]
        
        try:
            from demucs.pretrained import get_model
            model = get_model(f'htdemucs_{model_size}')
            cls._models[model_size] = model
            return model
        except ImportError:
            raise ImportError("请安装 demucs: pip install demucs")
        except Exception as e:
            raise RuntimeError(f"加载 Demucs 模型失败: {e}")

    def _create_stereo_audio(self, track_data: np.ndarray, sample_rate: int) -> Dict:
        """将单个音轨转换为立体声 AUDIO 格式"""
        # 平均通道
        if track_data.ndim == 2:
            track_data = track_data.mean(axis=0)
        
        # 转换为立体声
        if track_data.ndim == 1:
            track_data = np.stack([track_data, track_data])
        
        # 转换回 tensor 格式 (channels, samples) -> (1, channels, samples)
        track_tensor = torch.from_numpy(track_data.T).float().unsqueeze(0)
        return _audio(track_tensor, sample_rate)

    def separate(self, audio: Dict, model_size: str, output_mode: str) -> Tuple[Dict, Dict, Dict, Dict]:
        """分离多音轨"""
        waveform, sample_rate = _parts(audio)
        
        # 转换为 numpy
        if isinstance(waveform, torch.Tensor):
            waveform = waveform.squeeze(0).cpu().numpy()
        else:
            waveform = np.array(waveform).squeeze()
        
        # 加载模型
        model = self.load_model(model_size)
        
        # Demucs 需要 (channels, samples) 格式，float32，范围 [-1, 1]
        if waveform.ndim == 1:
            waveform = np.stack([waveform, waveform])
        else:
            waveform = waveform.T  # (channels, samples)
        
        waveform = waveform.astype(np.float32)
        
        # 分离
        with torch.no_grad():
            sources = model.forward(torch.from_numpy(waveform).unsqueeze(0))
        
        # sources 格式: (1, 4, channels, samples) -> (4, channels, samples)
        sources = sources.squeeze(0).cpu().numpy()
        
        # 提取各音轨
        drums = sources[0]
        bass = sources[1]
        other = sources[2]
        vocals = sources[3]
        
        # 根据输出模式处理
        if output_mode == "vocals_only":
            # 只输出人声，其他返回静音
            drums_audio = _audio(torch.zeros(1, 2, 1), sample_rate)
            bass_audio = _audio(torch.zeros(1, 2, 1), sample_rate)
            other_audio = _audio(torch.zeros(1, 2, 1), sample_rate)
        elif output_mode == "instrumental":
            # 输出伴奏（不含人声）
            drums_audio = self._create_stereo_audio(drums, sample_rate)
            bass_audio = self._create_stereo_audio(bass, sample_rate)
            other_audio = self._create_stereo_audio(other, sample_rate)
            vocals_audio = _audio(torch.zeros(1, 2, 1), sample_rate)
        else:  # "all"
            drums_audio = self._create_stereo_audio(drums, sample_rate)
            bass_audio = self._create_stereo_audio(bass, sample_rate)
            other_audio = self._create_stereo_audio(other, sample_rate)
            vocals_audio = self._create_stereo_audio(vocals, sample_rate)
        
        return (drums_audio, bass_audio, other_audio, vocals_audio)


# ============================================================
# 节点：EN Speech Recognizer (英文语音识别)
# ============================================================

class ENSpeechRecognizer:
    """
    使用 Whisper 进行英文语音识别，输出带时间戳的文本
    """
    _models = {}  # 缓存不同尺寸的模型

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "audio": ("AUDIO", {"tooltip": "输入音频（人声）"}),
                "whisper_model": (["tiny", "base", "small", "medium", "large"], {"default": "base",
                    "tooltip": "Whisper 模型大小，越大越准确但越慢"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")  # (json_str, srt_str)
    RETURN_NAMES = ("transcript_json", "srt_content")
    OUTPUT_TOOLTIPS = ["JSON 格式的识别结果，包含时间戳", "SRT 字幕格式"]
    FUNCTION = "recognize"
    CATEGORY = "video/translation"

    @classmethod
    def load_model(cls, model_name: str):
        """加载 Whisper 模型（按尺寸缓存）"""
        if model_name in cls._models:
            return cls._models[model_name]
        
        if not WHISPER_AVAILABLE:
            raise ImportError("请安装 whisper: pip install openai-whisper")
        
        try:
            model = whisper.load_model(model_name)
            cls._models[model_name] = model
            return model
        except Exception as e:
            raise RuntimeError(f"加载 Whisper 模型失败: {e}")

    def _create_srt(self, segments: List[Dict]) -> str:
        """生成 SRT 字幕"""
        srt_lines = []
        for i, seg in enumerate(segments, 1):
            start = self._format_timestamp(seg["start"])
            end = self._format_timestamp(seg["end"])
            srt_lines.append(f"{i}\n{start} --> {end}\n{seg['text']}\n")
        return "\n".join(srt_lines)

    def _format_timestamp(self, seconds: float) -> str:
        """格式化时间戳为 SRT 格式"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    def recognize(self, audio: Dict, whisper_model: str) -> Tuple[str, str]:
        """识别英文语音"""
        waveform, sample_rate = _parts(audio)
        
        # 转换为 numpy
        if isinstance(waveform, torch.Tensor):
            waveform_np = waveform.squeeze(0).cpu().numpy()
        else:
            waveform_np = np.array(waveform).squeeze()
        
        # 转换为 float32，范围 [-1, 1]
        if waveform_np.dtype != np.float32:
            waveform_np = waveform_np.astype(np.float32)
        if waveform_np.max() > 1.0:
            waveform_np = waveform_np / 32768.0
        
        # 保存为临时 wav 文件（Whisper 需要）
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            import scipy.io.wavfile as wavfile
            # Whisper 需要 (samples,) 或 (samples, channels)
            if waveform_np.ndim == 2:
                waveform_np = waveform_np.T
            wavfile.write(f.name, sample_rate, waveform_np)
            temp_path = f.name
        
        try:
            # 加载模型
            model = self.load_model(whisper_model)
            
            # 识别
            result = model.transcribe(
                temp_path,
                language="en",
                word_timestamps=True,
                condition_on_previous_text=False,
            )
            
            # 整理结果
            segments = []
            for seg in result.get("segments", []):
                segments.append({
                    "start": seg["start"],
                    "end": seg["end"],
                    "text": seg["text"].strip(),
                    "language": "en"
                })
            
            # 返回 JSON 和 SRT
            transcript_json = json.dumps({
                "segments": segments,
                "full_text": result["text"]
            }, ensure_ascii=False, indent=2)
            
            srt_content = self._create_srt(segments)
            
            return (transcript_json, srt_content)
            
        finally:
            os.unlink(temp_path)


# ============================================================
# 节点：Translator (翻译)
# ============================================================

class Translator:
    """
    翻译节点，支持 Ollama、DeepLX、OpenAI API 三种后端
    """
    # Ollama 客户端单例
    _ollama_client = None

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {"multiline": True, "tooltip": "待翻译的文本（支持 JSON 格式的段落列表）"}),
                "translation_mode": (["ollama", "deeplx", "openai"], {"default": "ollama",
                    "tooltip": "翻译后端：ollama（本地免费）、deeplx（自建免费）、openai（付费）"}),
            },
            "optional": {
                "ollama_url": ("STRING", {"default": "http://localhost:11434"}),
                "ollama_model": ("STRING", {"default": "qwen3.5"}),
                "deeplx_url": ("STRING", {"default": ""}),
                "openai_api_key": ("STRING", {"default": ""}),
                "openai_model": ("STRING", {"default": "gpt-4o-mini"}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("translated_text",)
    FUNCTION = "translate"
    CATEGORY = "video/translation"

    async def _translate_ollama(self, text: str, url: str, model: str) -> str:
        """使用 Ollama 翻译"""
        try:
            import httpx
        except ImportError:
            raise ImportError("请安装 httpx: pip install httpx")
        
        prompt = f"""将以下英文翻译成中文，保持简洁自然：

{text}

翻译要求：
1. 翻译准确，符合中文表达习惯
2. 保持原文的语气和风格
3. 只输出翻译结果，不要其他内容
"""
        
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{url}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False}
            )
            response.raise_for_status()
            result = response.json()
            return result.get("response", "").strip()

    async def _translate_deeplx(self, text: str, url: str) -> str:
        """使用 DeepLX 翻译"""
        try:
            import httpx
        except ImportError:
            raise ImportError("请安装 httpx: pip install httpx")
        
        if not url:
            raise ValueError("DeepLX URL 未设置")
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                url,
                json={"text": text, "source_lang": "EN", "target_lang": "ZH"}
            )
            response.raise_for_status()
            result = response.json()
            return result.get("data", "").strip()

    async def _translate_openai(self, text: str, api_key: str, model: str) -> str:
        """使用 OpenAI API 翻译"""
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("请安装 openai: pip install openai")
        
        if not api_key:
            raise ValueError("OpenAI API Key 未设置")
        
        client = OpenAI(api_key=api_key)
        
        prompt = f"""将以下英文翻译成中文，保持简洁自然：

{text}

翻译要求：
1. 翻译准确，符合中文表达习惯
2. 保持原文的语气和风格
3. 只输出翻译结果，不要其他内容
"""
        
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        return response.choices[0].message.content.strip()

    async def _translate_openai_batch(self, texts: List[str], api_key: str, model: str) -> List[str]:
        """使用 OpenAI API 批量翻译"""
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("请安装 openai: pip install openai")
        
        if not api_key:
            raise ValueError("OpenAI API Key 未设置")
        
        # 合并所有文本为批量请求
        combined_text = "\n---\n".join(texts)
        
        prompt = f"""将以下英文翻译成中文，保持简洁自然。每个段落用 --- 分隔：

{combined_text}

翻译要求：
1. 翻译准确，符合中文表达习惯
2. 保持原文的语气和风格
3. 每个段落翻译后用 --- 分隔
4. 只输出翻译结果，不要其他内容
"""
        
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        
        result = response.choices[0].message.content.strip()
        
        # 分割翻译结果
        translations = result.split("---")
        translations = [t.strip() for t in translations]
        
        # 确保返回数量匹配
        while len(translations) < len(texts):
            translations.append("")
        while len(translations) > len(texts):
            translations.pop()
        
        return translations

    async def _translate_text(self, text: str, mode: str, **kwargs) -> str:
        """异步翻译主逻辑"""
        if mode == "ollama":
            return await self._translate_ollama(
                text, 
                kwargs.get("ollama_url", "http://localhost:11434"),
                kwargs.get("ollama_model", "qwen3.5")
            )
        elif mode == "deeplx":
            return await self._translate_deeplx(
                text,
                kwargs.get("deeplx_url", "")
            )
        elif mode == "openai":
            return await self._translate_openai(
                text,
                kwargs.get("openai_api_key", ""),
                kwargs.get("openai_model", "gpt-4o-mini")
            )
        else:
            raise ValueError(f"不支持的翻译模式: {mode}")

    def _parse_text_input(self, text: str) -> List[Dict]:
        """解析输入文本，支持 JSON 段落格式"""
        # 尝试解析为 JSON
        try:
            data = json.loads(text)
            if isinstance(data, dict) and "segments" in data:
                return data["segments"]
            elif isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass
        
        # 纯文本，返回单个段落
        return [{"text": text.strip()}]

    def _format_output(self, translations: List[str], original: str) -> str:
        """格式化输出"""
        # 尝试恢复原始格式
        try:
            data = json.loads(original)
            if isinstance(data, dict) and "segments" in data:
                for i, seg in enumerate(data["segments"]):
                    if i < len(translations):
                        seg["text_zh"] = translations[i]
                return json.dumps(data, ensure_ascii=False, indent=2)
        except (json.JSONDecodeError, KeyError):
            pass
        
        # 纯文本格式，返回翻译结果
        return "\n".join(translations)

    def translate(self, text: str, translation_mode: str, 
                  ollama_url: str = "http://localhost:11434",
                  ollama_model: str = "qwen3.5",
                  deeplx_url: str = "",
                  openai_api_key: str = "",
                  openai_model: str = "gpt-4o-mini") -> Tuple[str]:
        """翻译主函数（支持批量优化）"""
        segments = self._parse_text_input(text)
        
        # 收集需要翻译的文本
        texts_to_translate = []
        original_indices = []
        for i, seg in enumerate(segments):
            seg_text = seg.get("text", seg.get("text_zh", "")) if isinstance(seg, dict) else str(seg)
            if seg_text:
                texts_to_translate.append(seg_text)
                original_indices.append(i)
        
        if not texts_to_translate:
            return (self._format_output([], text),)
        
        # OpenAI 支持批量翻译
        if translation_mode == "openai" and len(texts_to_translate) > 1:
            translations = _run_async(
                self._translate_openai_batch(
                    texts_to_translate,
                    openai_api_key,
                    openai_model
                )
            )
        else:
            # 其他模式或单段翻译，逐个翻译
            translations = []
            for seg_text in texts_to_translate:
                translated = _run_async(
                    self._translate_text(
                        seg_text, 
                        translation_mode,
                        ollama_url=ollama_url,
                        ollama_model=ollama_model,
                        deeplx_url=deeplx_url,
                        openai_api_key=openai_api_key,
                        openai_model=openai_model
                    )
                )
                translations.append(translated)
        
        # 构建完整翻译列表（包含空段落）
        full_translations = [""] * len(segments)
        for i, idx in enumerate(original_indices):
            full_translations[idx] = translations[i] if i < len(translations) else ""
        
        result = self._format_output(full_translations, text)
        return (result,)


# ============================================================
# 节点：ZH TTS (中文语音合成)
# ============================================================

class ZHTTS:
    """
    使用 Edge TTS 进行中文语音合成
    """
    # 可用的中文音色
    VOICE_OPTIONS = [
        "zh-CN-XiaoxiaoNeural",    # 晓晓 - 女声，自然
        "zh-CN-YunxiNeural",       # 云希 - 男声，青年
        "zh-CN-YunyangNeural",     # 云扬 - 男声，新闻
        "zh-CN-XiaoyiNeural",      # 小艺 - 女声
        "zh-CN-liaoning-XiaobaiNeural",  # 辽宁小白 - 女声
        "zh-CN-shaanxi-XiaobaiNeural",   # 陕西小白 - 女声
    ]

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {"multiline": True, "tooltip": "待合成的文本"}),
                "voice": (["xiaoxiao", "yunxi", "yunyang", "xiaoyi", "xiaobai_ln", "xiaobai_sx"], 
                    {"default": "xiaoxiao", "tooltip": "语音音色"}),
                "rate": ("FLOAT", {"default": 0.0, "min": -1.0, "max": 1.0, "step": 0.1,
                    "tooltip": "语速调整：-0.5 减速50%，0 正常，0.5 加速50%"}),
            },
        }

    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ("audio",)
    FUNCTION = "synthesize"
    CATEGORY = "video/translation"

    VOICE_MAP = {
        "xiaoxiao": "zh-CN-XiaoxiaoNeural",
        "yunxi": "zh-CN-YunxiNeural",
        "yunyang": "zh-CN-YunyangNeural",
        "xiaoyi": "zh-CN-XiaoyiNeural",
        "xiaobai_ln": "zh-CN-liaoning-XiaobaiNeural",
        "xiaobai_sx": "zh-CN-shaanxi-XiaobaiNeural",
    }

    def synthesize(self, text: str, voice: str, rate: float) -> Tuple[Dict]:
        """合成中文语音"""
        if not EDGE_TTS_AVAILABLE:
            raise ImportError("请安装 edge-tts: pip install edge-tts")
        
        voice_name = self.VOICE_MAP.get(voice, "zh-CN-XiaoxiaoNeural")
        
        # 转换 rate 格式：-1~1 -> edge-tts 格式 (如 "-10%", "+20%")
        if rate < 0:
            rate_str = f"{int(rate * 100)}%"
        elif rate > 0:
            rate_str = f"+{int(rate * 100)}%"
        else:
            rate_str = "+0%"
        
        # 保存为临时文件
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            temp_path = f.name
        
        try:
            # 合成语音（使用线程池避免事件循环冲突）
            import edge_tts
            _run_async(edge_tts.Communicate(text, voice_name, rate=rate_str).save(temp_path))
            
            # 读取音频并转换为 tensor
            container = av.open(temp_path)
            audio_stream = container.streams.audio[0]
            sample_rate = audio_stream.rate
            
            frames = []
            for frame in container.decode(audio_stream):
                frames.append(torch.from_numpy(frame.to_ndarray()).float())
            
            waveform = torch.cat(frames, dim=-1)
            container.close()
            
            # 转换为立体声
            if waveform.dim() == 1:
                waveform = torch.stack([waveform, waveform])
            else:
                waveform = waveform.T
            
            return (_audio(waveform.unsqueeze(0), sample_rate),)
            
        finally:
            _cleanup_temp_file(temp_path)


# ============================================================
# 节点：Audio Replacer (音频替换)
# ============================================================

class AudioReplacer:
    """
    将视频的音频替换为新的音频
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video_path": ("STRING", {"default": "", "tooltip": "原始视频路径（ComfyUI input 目录）"}),
                "new_audio": ("AUDIO", {"tooltip": "新音频（将替换原视频音频）"}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("output_path",)
    OUTPUT_TOOLTIPS = ["输出视频路径"]
    FUNCTION = "replace"
    CATEGORY = "video/translation"

    def replace(self, video_path: str, new_audio: Dict) -> Tuple[str]:
        """替换视频音频"""
        if not PYAV_AVAILABLE:
            raise ImportError("请安装 pyav: pip install av")
        
        # 检查 ffmpeg
        if not _check_ffmpeg():
            raise RuntimeError("未安装 ffmpeg，请先安装: https://ffmpeg.org/download.html")
        
        # 获取完整路径
        input_dir = folder_paths.get_input_directory()
        full_video_path = os.path.abspath(
            video_path if os.path.isabs(video_path) 
            else os.path.join(input_dir, video_path)
        )
        
        if not os.path.exists(full_video_path):
            raise FileNotFoundError(f"视频文件不存在: {full_video_path}")
        
        # 获取音频数据
        waveform, sample_rate = _parts(new_audio)
        
        if isinstance(waveform, torch.Tensor):
            waveform = waveform.squeeze(0).cpu().numpy()
        else:
            waveform = np.array(waveform).squeeze()
        
        # 转换为 float32
        if waveform.dtype != np.float32:
            waveform = waveform.astype(np.float32)
        
        # 处理形状
        if waveform.ndim == 1:
            waveform = np.stack([waveform, waveform])
        
        # 保存新音频为临时文件
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            temp_audio_path = f.name
            import scipy.io.wavfile as wavfile
            # 转换为 (samples, channels)
            wavfile.write(temp_audio_path, sample_rate, waveform.T.astype(np.float32))
        
        # 生成输出文件名
        base_name = os.path.splitext(os.path.basename(video_path))[0]
        output_name = f"{base_name}_zh.mp4"
        output_path = _safe_output_path(output_name)
        
        try:
            # 使用 ffmpeg 替换音频
            import subprocess
            
            cmd = [
                "ffmpeg", "-y",
                "-i", full_video_path,
                "-i", temp_audio_path,
                "-c:v", "copy",           # 复制视频流
                "-c:a", "aac",            # 编码音频为 AAC
                "-b:a", "192k",           # 音频比特率
                "-shortest",              # 以短的那个为准
                output_path
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5分钟超时
            )
            
            if result.returncode != 0:
                raise RuntimeError(f"FFmpeg 错误: {result.stderr}")
            
            # 返回相对路径
            return (os.path.basename(output_path),)
            
        finally:
            _cleanup_temp_file(temp_audio_path)


# ============================================================
# 节点：Video Translate Pipeline (一站式翻译流水线)
# ============================================================

class VideoTranslatePipeline:
    """
    一站式视频翻译流水线：
    1. 提取音频
    2. 人声分离
    3. 英文识别
    4. 翻译
    5. 中文 TTS
    6. 音频替换
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video_path": ("STRING", {"default": "", "tooltip": "原始视频路径"}),
                "whisper_model": (["tiny", "base", "small", "medium", "large"], {"default": "base"}),
                "translation_mode": (["ollama", "deeplx", "openai"], {"default": "ollama"}),
                "tts_voice": (["xiaoxiao", "yunxi", "yunyang", "xiaoyi", "xiaobai_ln", "xiaobai_sx"], 
                    {"default": "xiaoxiao"}),
                "tts_rate": ("FLOAT", {"default": -0.1, "min": -0.5, "max": 0.5, "step": 0.05}),
            },
            "optional": {
                "ollama_url": ("STRING", {"default": "http://localhost:11434"}),
                "ollama_model": ("STRING", {"default": "qwen3.5"}),
                "deeplx_url": ("STRING", {"default": ""}),
                "openai_api_key": ("STRING", {"default": ""}),
                "openai_model": ("STRING", {"default": "gpt-4o-mini"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("output_path", "transcript", "srt")
    OUTPUT_TOOLTIPS = ["输出视频路径", "识别和翻译的文本", "字幕文件"]
    FUNCTION = "process"
    CATEGORY = "video/translation"

    def process(self, video_path: str, whisper_model: str, translation_mode: str,
                tts_voice: str, tts_rate: float,
                ollama_url: str = "http://localhost:11434",
                ollama_model: str = "qwen3.5",
                deeplx_url: str = "",
                openai_api_key: str = "",
                openai_model: str = "gpt-4o-mini") -> Tuple[str, str, str]:
        """执行完整流水线"""
        
        # 检查依赖
        if not _check_ffmpeg():
            raise RuntimeError("未安装 ffmpeg，请先安装: https://ffmpeg.org/download.html")
        
        # 步骤 1: 读取视频
        input_dir = folder_paths.get_input_directory()
        full_video_path = os.path.abspath(
            video_path if os.path.isabs(video_path) 
            else os.path.join(input_dir, video_path)
        )
        
        if not os.path.exists(full_video_path):
            raise FileNotFoundError(f"视频文件不存在: {full_video_path}")
        
        # 步骤 2: 提取音频
        container = av.open(full_video_path)
        audio_stream = None
        for stream in container.streams:
            if stream.type == 'audio':
                audio_stream = stream
                break
        
        if audio_stream is None:
            raise ValueError("视频中没有音频流")
        
        sample_rate = audio_stream.rate
        frames = []
        for frame in container.decode(audio_stream):
            frames.append(torch.from_numpy(frame.to_ndarray()).float())
        container.close()
        
        if not frames:
            raise ValueError("无法解码音频")
        
        waveform = torch.cat(frames, dim=-1)
        if waveform.dim() == 1:
            waveform = torch.stack([waveform, waveform])
        audio = _audio(waveform.unsqueeze(0), sample_rate)
        
        # 步骤 3: 人声分离（简化版，直接用原始音频）
        # TODO: 启用人声分离以提高识别准确率
        # vocals = VoiceSeparator().separate(audio, "medium")[0]
        vocals = audio
        
        # 步骤 4: 英文识别
        recognizer = ENSpeechRecognizer()
        transcript_json, srt_content = recognizer.recognize(vocals, whisper_model)
        
        # 步骤 5: 翻译
        translator = Translator()
        translated_json = translator.translate(
            transcript_json,
            translation_mode,
            ollama_url=ollama_url,
            ollama_model=ollama_model,
            deeplx_url=deeplx_url,
            openai_api_key=openai_api_key,
            openai_model=openai_model
        )[0]
        
        # 步骤 6: 提取翻译后的文本进行 TTS
        try:
            translated_data = json.loads(translated_json)
            # 合并所有翻译文本
            zh_texts = []
            for seg in translated_data.get("segments", []):
                if "text_zh" in seg:
                    zh_texts.append(seg["text_zh"])
            full_zh_text = "".join(zh_texts)
        except (json.JSONDecodeError, KeyError):
            full_zh_text = translated_json
        
        # 步骤 7: 中文 TTS
        tts = ZHTTS()
        zh_audio = tts.synthesize(full_zh_text, tts_voice, tts_rate)[0]
        
        # 步骤 8: 替换音频
        replacer = AudioReplacer()
        output_path = replacer.replace(video_path, zh_audio)[0]
        
        return (output_path, translated_json, srt_content)


# ============================================================
# 节点映射
# ============================================================

TRANSLATION_NODE_CLASS_MAPPINGS = {
    "VideoSplitVoiceSeparator": VoiceSeparator,
    "VideoSplitVoiceSeparatorV2": VoiceSeparatorV2,
    "VideoSplitENSpeechRecognizer": ENSpeechRecognizer,
    "VideoSplitTranslator": Translator,
    "VideoSplitZHTTS": ZHTTS,
    "VideoSplitAudioReplacer": AudioReplacer,
    "VideoSplitTranslatePipeline": VideoTranslatePipeline,
}

TRANSLATION_NODE_DISPLAY_NAME_MAPPINGS = {
    "VideoSplitVoiceSeparator": "Voice Separator",
    "VideoSplitVoiceSeparatorV2": "Voice Separator (Multi-track)",
    "VideoSplitENSpeechRecognizer": "EN Speech Recognizer",
    "VideoSplitTranslator": "Translator",
    "VideoSplitZHTTS": "ZH TTS",
    "VideoSplitAudioReplacer": "Audio Replacer",
    "VideoSplitTranslatePipeline": "Video Translate Pipeline",
}
