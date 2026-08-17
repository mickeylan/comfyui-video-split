"""
音频时间轴校准节点 - 可视化界面

提供一个交互式时间轴编辑器，支持：
- 拖拽调整音频位置和时长
- 帧级精确对齐
- 多轨道管理
- 导入导出配置
"""

import json
import torch
import numpy as np
from typing import Dict, List, Optional, Any

# Web 目录路径
import os
WEB_DIRECTORY = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web").replace("\\", "/")

try:
    import av
    PYAV_AVAILABLE = True
except ImportError:
    PYAV_AVAILABLE = False


def _audio(waveform, sample_rate):
    """创建 AUDIO 格式数据"""
    if waveform.ndim == 2:
        waveform = waveform.unsqueeze(0)
    return {"waveform": waveform, "sample_rate": int(sample_rate)}


def _parts(audio):
    """读取 AUDIO 数据"""
    waveform = audio.get("waveform") or audio.get("samples")
    sample_rate = audio.get("sample_rate") or audio.get("rate")
    if waveform is None or sample_rate is None:
        raise ValueError("Invalid AUDIO payload")
    return waveform, int(sample_rate)


class AudioTimelineConfig:
    """时间轴配置数据结构"""
    def __init__(self, fps=24.0, total_frames=1440, tracks=None):
        self.fps = fps
        self.total_frames = total_frames
        self.tracks = tracks or []

    @classmethod
    def from_json(cls, json_str: str) -> "AudioTimelineConfig":
        """从 JSON 字符串解析"""
        data = json.loads(json_str)
        return cls(
            fps=data.get("fps", 24.0),
            total_frames=data.get("totalFrames", data.get("total_frames", 1440)),
            tracks=data.get("tracks", [])
        )

    def to_json(self) -> str:
        """序列化为 JSON 字符串"""
        return json.dumps({
            "fps": self.fps,
            "totalFrames": self.total_frames,
            "tracks": self.tracks
        }, indent=2)

    def get_block_configs(self) -> List[Dict]:
        """获取所有音频块配置"""
        configs = []
        for track in self.tracks:
            for block in track.get("blocks", []):
                configs.append({
                    "startFrame": block.get("startFrame", 0),
                    "endFrame": block.get("endFrame", 0),
                    "volume": block.get("volume", 1.0)
                })
        return configs


class AudioTimelineEditorNode:
    """
    音频时间轴校准编辑器节点
    
    提供可视化界面用于校准多段音频在时间轴上的位置。
    用户可以通过拖拽操作来精确调整音频的对齐。
    
    输入：
    - video_images: 视频帧（用于获取 fps 和总帧数）
    - fps: 帧率（当没有视频时使用）
    
    配置输入（JSON 字符串）：
    - timeline_config: 时间轴配置（从可视化界面导出）
    - 或者通过前端界面直接交互
    
    输出：
    - 配置数据，可传递给后续处理节点
    """

    # CSS/JS 文件
    EXTENSION_JS = "web/js/audio_timeline.js"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "fps": ("FLOAT", {"default": 24.0, "min": 1.0, "max": 240.0, "step": 0.01,
                    "tooltip": "视频帧率，用于时间轴转换"}),
            },
            "optional": {
                "video_images": ("IMAGE", {"tooltip": "视频帧（自动获取 fps 和帧数）"}),
                "timeline_config": ("STRING", {"default": "", "multiline": True,
                    "tooltip": "时间轴配置 JSON，可从可视化界面复制过来"}),
                "sample_rate": ("INT", {"default": 44100, "min": 8000, "max": 192000}),
            },
            "hidden": {
                "unique_id": "UNIQUE_ID",
            }
        }

    RETURN_TYPES = ("TIMELINE_CONFIG", "STRING", "INT", "INT")
    RETURN_NAMES = ("config", "config_json", "total_frames", "duration_seconds")
    FUNCTION = "execute"
    CATEGORY = "video/audio"
    OUTPUT_NODE = True
    DESCRIPTION = "可视化音频时间轴校准编辑器"
    
    # 自定义前端组件
    CUSTOM_NODE = True

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")

    def execute(self, fps, video_images=None, timeline_config="", sample_rate=44100, unique_id=None, **kwargs):
        # 如果有视频帧，获取帧信息
        if video_images is not None:
            total_frames = video_images.shape[0]
        else:
            total_frames = 1440  # 默认值

        duration_seconds = total_frames / fps

        # 解析配置
        if timeline_config and timeline_config.strip():
            try:
                config = AudioTimelineConfig.from_json(timeline_config)
                # 更新帧信息
                config.fps = fps
                config.total_frames = total_frames
            except json.JSONDecodeError:
                # 如果解析失败，创建默认配置
                config = AudioTimelineConfig(fps=fps, total_frames=total_frames)
        else:
            # 创建默认配置
            config = AudioTimelineConfig(fps=fps, total_frames=total_frames)

        config_json = config.to_json()

        return (config, config_json, total_frames, duration_seconds)


class AudioTimelineComposer:
    """
    音频时间轴合成器
    
    根据时间轴配置，将多段音频合成到指定位置。
    支持精确帧级对齐。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "total_frames": ("INT", {"default": 1440, "min": 1, "max": 864000}),
                "fps": ("FLOAT", {"default": 24.0, "min": 1.0, "max": 240.0}),
                "sample_rate": ("INT", {"default": 44100, "min": 8000, "max": 192000}),
            },
            "optional": {
                "timeline_config": ("TIMELINE_CONFIG",),
                "audio1": ("AUDIO",),
                "audio2": ("AUDIO",),
                "audio3": ("AUDIO",),
                "audio4": ("AUDIO",),
                "audio5": ("AUDIO",),
                "audio6": ("AUDIO",),
                "audio7": ("AUDIO",),
                "audio8": ("AUDIO",),
            }
        }

    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ("audio",)
    FUNCTION = "execute"
    CATEGORY = "video/audio"
    DESCRIPTION = "根据时间轴配置合成多段音频"

    def execute(self, total_frames, fps, sample_rate, timeline_config=None,
                audio1=None, audio2=None, audio3=None, audio4=None,
                audio5=None, audio6=None, audio7=None, audio8=None):
        
        # 收集所有音频
        audio_list = [audio1, audio2, audio3, audio4, audio5, audio6, audio7, audio8]
        audio_list = [a for a in audio_list if a is not None]

        if not audio_list:
            # 返回静音
            total_samples = round(total_frames / fps * sample_rate)
            waveform = torch.zeros(1, 1, total_samples, dtype=torch.float32)
            return (_audio(waveform, sample_rate),)

        # 获取参考设备
        ref_waveform, ref_rate = _parts(audio_list[0])
        device = ref_waveform.device
        dtype = ref_waveform.dtype

        # 计算总采样数
        total_samples = round(total_frames / fps * sample_rate)

        # 创建结果轨道
        result = torch.zeros(1, 1, total_samples, device=device, dtype=dtype)

        # 如果有配置，按配置放置音频
        if timeline_config is not None:
            if isinstance(timeline_config, dict):
                config = AudioTimelineConfig.from_json(json.dumps(timeline_config))
            else:
                config = timeline_config

            # 遍历配置的轨道和音频块
            audio_index = 0
            for track in config.tracks:
                for block in track.get("blocks", []):
                    if audio_index < len(audio_list):
                        audio = audio_list[audio_index]
                        waveform, audio_rate = _parts(audio)

                        # 转为单声道
                        if waveform.shape[1] > 1:
                            waveform = waveform.mean(dim=1, keepdim=True)

                        # 重采样
                        if audio_rate != sample_rate:
                            import torch.nn.functional as F
                            new_length = round(waveform.shape[-1] * sample_rate / audio_rate)
                            waveform = F.interpolate(
                                waveform, size=new_length, mode="linear", align_corners=False
                            )

                        # 计算放置位置（帧 → 采样）
                        start_frame = block.get("startFrame", 0)
                        end_frame = block.get("endFrame", start_frame + len(waveform[0, 0]) * fps / sample_rate)

                        start_sample = int(round(start_frame * sample_rate / fps))
                        end_sample = int(round(end_frame * sample_rate / fps))

                        # 裁剪
                        actual_start = max(0, start_sample)
                        actual_end = min(total_samples, end_sample)

                        audio_start = actual_start - start_sample
                        audio_end = audio_start + (actual_end - actual_start)

                        if audio_end > audio_start and audio_end <= waveform.shape[-1]:
                            volume = block.get("volume", 1.0)
                            result[..., actual_start:actual_end] += (
                                waveform[..., audio_start:audio_end] * volume
                            ).to(device=device, dtype=dtype)

                        audio_index += 1

        else:
            # 没有配置，所有音频从头到尾依次拼接
            import torch.nn.functional as F
            current_pos = 0
            for audio in audio_list:
                waveform, audio_rate = _parts(audio)

                if waveform.shape[1] > 1:
                    waveform = waveform.mean(dim=1, keepdim=True)

                if audio_rate != sample_rate:
                    new_length = round(waveform.shape[-1] * sample_rate / audio_rate)
                    waveform = F.interpolate(
                        waveform, size=new_length, mode="linear", align_corners=False
                    )

                end_pos = min(current_pos + waveform.shape[-1], total_samples)
                copy_len = end_pos - current_pos

                if copy_len > 0:
                    result[..., current_pos:end_pos] = waveform[..., :copy_len].to(device=device, dtype=dtype)
                    current_pos = end_pos

                if current_pos >= total_samples:
                    break

        # 限制振幅
        result = result.clamp(-1, 1)

        return (_audio(result, sample_rate),)


class AudioTimelineFromJSON:
    """
    从 JSON 配置创建时间轴合成音频

    简化版本：直接接收 JSON 格式的配置。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "fps": ("FLOAT", {"default": 24.0, "min": 1.0, "max": 240.0}),
                "total_frames": ("INT", {"default": 1440, "min": 1, "max": 864000}),
                "sample_rate": ("INT", {"default": 44100, "min": 8000, "max": 192000}),
                "audio_json": ("STRING", {"default": "[]", "multiline": True,
                    "tooltip": "JSON 格式的音频配置：[{\"audio\": audio_data, \"startFrame\": 0, \"endFrame\": 240, \"volume\": 1.0}]"}),
            }
        }

    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ("audio",)
    FUNCTION = "execute"
    CATEGORY = "video/audio"
    DESCRIPTION = "从 JSON 配置合成音频"

    def execute(self, fps, total_frames, sample_rate, audio_json):
        try:
            audio_configs = json.loads(audio_json)
        except json.JSONDecodeError:
            audio_configs = []

        total_samples = round(total_frames / fps * sample_rate)
        result = torch.zeros(1, 1, total_samples, dtype=torch.float32)

        for config in audio_configs:
            # 这里需要从外部传入实际的音频数据
            # 简化版本：只返回静音
            pass

        return (_audio(result, sample_rate),)


# 节点映射
TIMELINE_NODE_CLASS_MAPPINGS = {
    "AudioTimelineEditor": AudioTimelineEditorNode,
    "AudioTimelineComposer": AudioTimelineComposer,
}

TIMELINE_NODE_DISPLAY_NAME_MAPPINGS = {
    "AudioTimelineEditor": "Audio Timeline Editor",
    "AudioTimelineComposer": "Audio Timeline Composer",
}

__all__ = [
    "TIMELINE_NODE_CLASS_MAPPINGS",
    "TIMELINE_NODE_DISPLAY_NAME_MAPPINGS",
    "AudioTimelineConfig",
    "WEB_DIRECTORY",
]
