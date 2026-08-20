"""
LTX Video Unlimited Preview - 实时预览系统

在分块采样过程中实时预览，支持 Latent2RGB 和 Tiny VAE 两种解码模式。
来自 ComfyUI-MiniMax-H3-Sampler-Unlimited 的架构设计。
"""

import base64
import io as pyio
import logging
import math
import queue
import threading

import torch
import torch.nn as nn
from PIL import Image, ImageOps

import comfy.model_management
import comfy.patcher_extension
import comfy.utils
import folder_paths
from comfy.taesd.taesd import Block, Clamp, conv

try:
    from server import PromptServer
except ImportError:
    PromptServer = None


PREVIEW_WRAPPER_KEY = "ltxv_unlimited_preview"
# LTX Video 帧结构: 每个 latent 步 = 8 像素帧
FRAME_PER_TOKEN = (8,) * 4  # 每个 latent 步对应 8 帧


class _LatestEncoder:
    """异步 WebP 编码器"""
    def __init__(self):
        self.tasks = queue.Queue(maxsize=1)
        self.stopping = False
        self.thread = threading.Thread(target=self._run, name="ltxv_preview_encoder", daemon=True)
        self.thread.start()

    def submit(self, task):
        try:
            self.tasks.put_nowait(task)
        except queue.Full:
            try:
                self.tasks.get_nowait()
            except queue.Empty:
                pass
            try:
                self.tasks.put_nowait(task)
            except queue.Full:
                pass

    def _run(self):
        while True:
            try:
                task = self.tasks.get(timeout=0.1)
            except queue.Empty:
                if self.stopping:
                    return
                continue
            try:
                task()
            except Exception:
                logging.exception("LTX Video preview encoding failed")
            if self.stopping and self.tasks.empty():
                return

    def close(self):
        self.stopping = True
        self.thread.join(timeout=10.0)


def _build_tiny_decoder(state_dict):
    """从 state_dict 构建 Tiny VAE 解码器"""
    first_key = next(iter(state_dict))
    if not first_key.split(".", 1)[0].isdigit():
        prefix = first_key.split(".", 1)[0] + "."
        state_dict = {key[len(prefix):]: value for key, value in state_dict.items() if key.startswith(prefix)}

    entries = {}
    for key, value in state_dict.items():
        index, separator, tail = key.partition(".")
        if not separator or not index.isdigit():
            raise ValueError(f"unsupported tiny VAE key: {key}")
        entries.setdefault(int(index), {})[tail] = value

    layers = []
    for index in range(max(entries) + 1):
        values = entries.get(index)
        if values is None:
            layers.append(Clamp() if index == 0 else nn.ReLU() if index == 2 else nn.Upsample(scale_factor=2))
        elif "conv.0.weight" in values:
            weight = values["conv.0.weight"]
            layers.append(Block(weight.shape[1], weight.shape[0], use_midblock_gn="pool.0.weight" in values))
        elif "weight" in values:
            weight = values["weight"]
            layers.append(conv(weight.shape[1], weight.shape[0], bias="bias" in values))
        else:
            raise ValueError(f"unsupported tiny VAE layer {index}")
    decoder = nn.Sequential(*layers)
    decoder.load_state_dict(state_dict)
    return decoder


class _TinyDecoder:
    """Tiny VAE 解码器"""
    def __init__(self, name):
        path = folder_paths.get_full_path("vae_approx", name)
        if path is None:
            raise ValueError(f"tiny VAE '{name}' was not found in models/vae_approx")
        state_dict = comfy.utils.load_torch_file(path, safe_load=True)
        self.model = _build_tiny_decoder(state_dict)
        self.latent_channels = self.model[1].weight.shape[1]
        self.device = comfy.model_management.vae_device()
        self.dtype = comfy.model_management.vae_dtype(self.device, [torch.float16, torch.bfloat16])
        self.model = self.model.eval().to(device=self.device, dtype=self.dtype)
        if torch.device(self.device).type == "cuda":
            self.model.to(memory_format=torch.channels_last)

    def decode_frame(self, latent):
        decoded = self.model(latent.to(device=self.device, dtype=self.dtype))
        return decoded[0].movedim(0, -1).to(device="cpu", dtype=torch.float32)


def _packed_video(x0, latent_shapes):
    """提取视频张量"""
    if getattr(x0, "is_nested", False):
        return x0.unbind()[0]
    if latent_shapes and x0.ndim == 3:
        target = latent_shapes[0]
        count = math.prod(int(size) for size in target[1:])
        return x0[:, :, :count].reshape([x0.shape[0]] + list(target)[1:])
    return x0


def _resize_pil(image, max_resolution):
    """调整图像大小"""
    if max_resolution > 0 and (image.width > max_resolution or image.height > max_resolution):
        return ImageOps.contain(image, (max_resolution, max_resolution), Image.Resampling.LANCZOS)
    return image


def _tensor_image(tensor, max_resolution):
    """张量转图像"""
    pixels = tensor.mul(255.0).clamp(0, 255).to(torch.uint8).numpy()
    return _resize_pil(Image.fromarray(pixels), max_resolution)


def _latent_rgb_frames(video, latent_format, indices, max_resolution):
    """使用 Latent2RGB 预览"""
    factors = getattr(latent_format, "latent_rgb_factors", None)
    if factors is None or video.ndim != 5:
        return []
    reshape = getattr(latent_format, "latent_rgb_factors_reshape", None)
    if reshape is not None:
        video = reshape(video)
    bias = getattr(latent_format, "latent_rgb_factors_bias", None)
    factor_tensor = torch.tensor(factors, device=video.device, dtype=video.dtype).transpose(0, 1)
    bias_tensor = torch.tensor(bias, device=video.device, dtype=video.dtype) if bias is not None else None
    selected = video[0, :, indices].movedim(0, -1)
    rgb = torch.nn.functional.linear(selected, factor_tensor, bias=bias_tensor)
    rgb = rgb.add(1.0).mul(0.5).clamp(0, 1).to(device="cpu", dtype=torch.float32)
    return [_tensor_image(frame, max_resolution) for frame in rgb]


def _tiny_frames(video, decoder, indices, max_resolution):
    """使用 Tiny VAE 解码预览"""
    if decoder.latent_channels != video.shape[1]:
        raise ValueError(f"tiny VAE expects {decoder.latent_channels} latent channels, but LTX Video uses {video.shape[1]}")
    return [_tensor_image(decoder.decode_frame(video[0, :, index].unsqueeze(0)), max_resolution) for index in indices]


def _frame_selection(video_t, trim_steps, stride, fps):
    """选择预览帧"""
    indices = list(range(trim_steps, video_t, stride))
    durations = []
    preview_frames = 0
    for index in indices:
        # LTX: 每个 latent 步 = 8 像素帧
        span = sum(FRAME_PER_TOKEN[position % len(FRAME_PER_TOKEN)] for position in range(index, min(video_t, index + stride)))
        next_preview_frames = preview_frames + span
        durations.append(max(1, round(next_preview_frames * 1000.0 / fps) - round(preview_frames * 1000.0 / fps)))
        preview_frames = next_preview_frames
    return indices, durations


def _encode_webp(frames, durations, quality):
    """编码 WebP 动画"""
    if not frames:
        return None
    buffer = pyio.BytesIO()
    frames[0].save(
        buffer,
        format="WEBP",
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        quality=quality,
        method=3,
    )
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _send(payload):
    """发送 WebSocket 事件"""
    if PromptServer is not None and PromptServer.instance is not None:
        try:
            PromptServer.instance.send_sync("ltxv_unlimited_preview", payload, PromptServer.instance.client_id)
        except Exception as error:
            logging.warning(f"LTX Video preview could not send update: {error}")


class _PreviewExecution:
    """预览执行管理器"""
    def __init__(self, wrappers, chunk_count):
        self.items = [(wrapper, wrapper.begin(chunk_count)) for wrapper in wrappers]

    def set_chunk(self, index, sampled_start, sampled_end, output_start, output_end, trim_steps):
        for wrapper, execution_id in self.items:
            wrapper.set_chunk(execution_id, index, sampled_start, sampled_end, output_start, output_end, trim_steps)

    def clear_chunk(self):
        for wrapper, execution_id in self.items:
            wrapper.clear_chunk(execution_id)

    def close(self):
        for wrapper, execution_id in self.items:
            wrapper.finish(execution_id)


def begin_preview_execution(model_patcher, chunk_count):
    """开始预览执行"""
    wrappers = model_patcher.get_wrappers(comfy.patcher_extension.WrappersMP.OUTER_SAMPLE, PREVIEW_WRAPPER_KEY)
    return _PreviewExecution(wrappers, chunk_count) if wrappers else None


class _AccumulatedPreviewWrapper:
    """累积预览包装器"""
    def __init__(self, node_id, max_resolution, quality, fps, frame_stride, tiny_vae):
        self.node_id = str(node_id) if node_id is not None else None
        self.max_resolution = max_resolution
        self.quality = quality
        self.fps = fps
        self.frame_stride = frame_stride
        self.tiny_vae_name = tiny_vae
        self.execution_id = 0
        self.chunk_count = 0
        self.current_chunk = None
        self.decoder = None
        self.decoder_failed = False

    def begin(self, chunk_count):
        self.execution_id += 1
        self.chunk_count = chunk_count
        self.current_chunk = None
        self.decoder = None
        self.decoder_failed = False
        _send({"node_id": self.node_id, "action": "reset", "execution": self.execution_id, "chunk_count": chunk_count})
        return self.execution_id

    def set_chunk(self, execution_id, index, sampled_start, sampled_end, output_start, output_end, trim_steps):
        if execution_id == self.execution_id:
            self.current_chunk = {
                "index": index,
                "sampled_start": sampled_start,
                "sampled_end": sampled_end,
                "output_start": output_start,
                "output_end": output_end,
                "trim_steps": trim_steps,
            }

    def clear_chunk(self, execution_id):
        if execution_id == self.execution_id:
            self.current_chunk = None

    def finish(self, execution_id):
        if execution_id != self.execution_id:
            return
        _send({"node_id": self.node_id, "action": "complete", "execution": execution_id})
        self.current_chunk = None
        self.decoder = None

    def _decoder(self):
        if self.tiny_vae_name == "none" or self.decoder_failed:
            return None
        if self.decoder is None:
            try:
                self.decoder = _TinyDecoder(self.tiny_vae_name)
            except Exception as error:
                logging.warning(f"LTX Video preview could not load '{self.tiny_vae_name}', using Latent2RGB: {error}")
                self.decoder_failed = True
        return self.decoder

    def __call__(self, executor, noise, latent_image, sampler, sigmas, denoise_mask, callback, disable_pbar, seed, latent_shapes):
        chunk = self.current_chunk
        if chunk is None:
            return executor(noise, latent_image, sampler, sigmas, denoise_mask, callback, disable_pbar, seed, latent_shapes=latent_shapes)

        model_patcher = executor.class_obj.model_patcher
        latent_format = model_patcher.model.latent_format
        encoder = _LatestEncoder()
        original_callback = callback
        execution_id = self.execution_id
        chunk_index = chunk["index"]

        def preview_callback(step, x0, x, callback_total):
            try:
                video = _packed_video(x0, latent_shapes)
                if video.ndim == 5:
                    indices, durations = _frame_selection(video.shape[2], chunk["trim_steps"], self.frame_stride, self.fps)
                    decoder = self._decoder()
                    if decoder is not None:
                        try:
                            frames = _tiny_frames(video, decoder, indices, self.max_resolution)
                        except Exception as error:
                            logging.warning(f"LTX Video tiny VAE preview failed, using Latent2RGB: {error}")
                            self.decoder = None
                            self.decoder_failed = True
                            frames = _latent_rgb_frames(video, latent_format, indices, self.max_resolution)
                    else:
                        frames = _latent_rgb_frames(video, latent_format, indices, self.max_resolution)
                    if frames:
                        payload = {
                            "node_id": self.node_id,
                            "action": "chunk",
                            "execution": execution_id,
                            "chunk": chunk_index,
                            "chunk_count": self.chunk_count,
                            "step": step + 1,
                            "steps": callback_total,
                            "sampled_start": chunk["sampled_start"],
                            "sampled_end": chunk["sampled_end"],
                            "output_start": chunk["output_start"],
                            "output_end": chunk["output_end"],
                            "duration_ms": sum(durations),
                        }

                        def encode_and_send(frames=frames, durations=durations, payload=payload):
                            encoded = _encode_webp(frames, durations, self.quality)
                            if encoded is not None:
                                payload["image"] = encoded
                                _send(payload)

                        encoder.submit(encode_and_send)
            except Exception as error:
                logging.warning(f"LTX Video preview failed for chunk {chunk_index + 1}: {error}")
            if original_callback is not None:
                original_callback(step, x0, x, callback_total)

        try:
            return executor(noise, latent_image, sampler, sigmas, denoise_mask, preview_callback, disable_pbar, seed, latent_shapes=latent_shapes)
        finally:
            encoder.close()
