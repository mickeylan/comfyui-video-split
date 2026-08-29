"""
Wan 2.2 I2V and Bernini two-stage unlimited samplers.
"""

import logging
import torch

import nodes
import node_helpers
import comfy
import comfy.clip_vision
import comfy.context_windows
import comfy.patcher_extension
import comfy.samplers
from comfy_extras.nodes_bernini import BerniniConditioning
from comfy_extras.nodes_custom_sampler import SamplerCustom


# ============================================================================
# Wan22 帧结构常量
# ============================================================================

# Wan22 帧结构: 像素帧数 = 1 + 4 * N
# 每编码组 = 4 帧
# 时间压缩比 = 4 (每个 latent 步 = 4 像素帧)


def pixel_frames_to_latent_steps(pixel_frames: int) -> int:
    """将像素帧数转换为 latent 步数 (Wan22 1+4N 模式)"""
    if pixel_frames < 1:
        raise ValueError(f"Wan22 minimum is 1 pixel frame, got {pixel_frames}")
    if pixel_frames == 1:
        return 1
    # N = (pixel_frames - 1) // 4
    # latent_steps = 1 + N
    return 1 + (pixel_frames - 1) // 4


def latent_steps_to_pixel_frames(latent_steps: int) -> int:
    """将 latent 步数转换为像素帧数"""
    if latent_steps < 1:
        raise ValueError(f"Latent steps must be at least 1, got {latent_steps}")
    if latent_steps == 1:
        return 1
    return 1 + (latent_steps - 1) * 4


def align_pixel_frames_to_chunk(pixel_frames: int) -> int:
    """将像素帧数对齐到 Wan22 的 1+4N 约束"""
    if pixel_frames <= 1:
        return 1
    return 1 + ((pixel_frames - 1) // 4) * 4


def _normalize_vae_tiles(tile_size, tile_overlap, temporal_size, temporal_overlap):
    if tile_overlap >= tile_size:
        raise ValueError("Wan VAE tile_overlap must be smaller than tile_size")
    temporal_size = max(2, temporal_size)
    temporal_overlap = min(max(1, temporal_overlap), temporal_size - 1)
    return temporal_size, temporal_overlap


def _decode_wan_video(vae, samples, tiled_decode, tile_size, tile_overlap, temporal_size, temporal_overlap):
    if not tiled_decode:
        return vae.decode(samples)[0].detach().cpu()
    temporal_size, temporal_overlap = _normalize_vae_tiles(
        tile_size, tile_overlap, temporal_size, temporal_overlap,
    )

    compression = vae.spacial_compression_decode()
    decoded = vae.decode_tiled(
        samples,
        tile_x=max(1, tile_size // compression),
        tile_y=max(1, tile_size // compression),
        overlap=max(1, tile_overlap // compression),
        tile_t=temporal_size,
        overlap_t=temporal_overlap,
    )
    return decoded[0].detach().cpu()


def _encode_wan_video_tiled(vae, pixel_samples, tile_size, tile_overlap, temporal_size, temporal_overlap):
    temporal_size, temporal_overlap = _normalize_vae_tiles(
        tile_size, tile_overlap, temporal_size, temporal_overlap,
    )
    vae.throw_exception_if_invalid()
    pixel_samples = vae.vae_encode_crop_pixels(pixel_samples).movedim(-1, 1)
    if pixel_samples.ndim < 5:
        pixel_samples = pixel_samples.movedim(1, 0).unsqueeze(0)

    tile_shape = (pixel_samples.shape[0], pixel_samples.shape[1], min(pixel_samples.shape[2], temporal_size),
                  min(pixel_samples.shape[3], tile_size), min(pixel_samples.shape[4], tile_size))
    memory_used = vae.memory_used_encode(tile_shape, vae.vae_dtype)
    comfy.model_management.load_models_gpu([vae.patcher], memory_required=memory_used, force_full_load=vae.disable_offload)
    with comfy.model_management.cuda_device_context(vae.device):
        if vae.handles_tiling:
            samples = vae._encode_tiled_owned(
                pixel_samples, tile_x=tile_size, tile_y=tile_size, overlap=tile_overlap,
                tile_t=temporal_size, overlap_t=temporal_overlap,
            )
        else:
            samples = vae.encode_tiled_3d(
                pixel_samples, tile_t=temporal_size, tile_x=tile_size, tile_y=tile_size,
                overlap=(temporal_overlap, tile_overlap, tile_overlap),
            )
    if vae.format_encoded is not None:
        samples = vae.format_encoded(samples)
    return samples


def _wan_image_to_video_low_memory(positive, negative, vae, width, height, length, batch_size, start_image,
                                   clip_vision_output, tile_size, tile_overlap, temporal_size, temporal_overlap):
    latent = torch.zeros(
        [batch_size, 16, ((length - 1) // 4) + 1, height // 8, width // 8],
        device=comfy.model_management.intermediate_device(),
    )
    if start_image is not None:
        start_image = comfy.utils.common_upscale(
            start_image[:length].movedim(-1, 1), width, height, "bilinear", "center"
        ).movedim(1, -1).detach().cpu()
        image = torch.full(
            (length, height, width, start_image.shape[-1]), 0.5,
            device="cpu", dtype=start_image.dtype,
        )
        image[:start_image.shape[0]] = start_image
        concat_latent_image = _encode_wan_video_tiled(
            vae, image[:, :, :, :3], tile_size, tile_overlap, temporal_size, temporal_overlap,
        )
        del image
        mask = torch.ones(
            (1, 1, latent.shape[2], concat_latent_image.shape[-2], concat_latent_image.shape[-1]),
            device="cpu", dtype=start_image.dtype,
        )
        mask[:, :, :((start_image.shape[0] - 1) // 4) + 1] = 0.0
        values = {"concat_latent_image": concat_latent_image, "concat_mask": mask}
        positive = node_helpers.conditioning_set_values(positive, values)
        negative = node_helpers.conditioning_set_values(negative, values)

    if clip_vision_output is not None:
        values = {"clip_vision_output": clip_vision_output}
        positive = node_helpers.conditioning_set_values(positive, values)
        negative = node_helpers.conditioning_set_values(negative, values)
    return positive, negative, {"samples": latent}


# ============================================================================
# 分块规划
# ============================================================================

def _slice_mask(mask, start, end, reference):
    if mask is None:
        return torch.ones_like(reference[:, :1, start:end])
    mask = comfy.utils.reshape_mask(mask, reference.shape)
    return mask[:, :1, start:end].clone()


def _slice_standard_conditioning(conditioning, video_start, video_end, reference_latent=None, clip_vision_output=None):
    sliced = []
    for cross_attn, metadata in conditioning:
        metadata = metadata.copy()
        if clip_vision_output is not None:
            metadata["clip_vision_output"] = clip_vision_output
        if "audio_embed" in metadata:
            raise ValueError("Wan22 unlimited sampler does not support audio conditioning")
        for key in ("concat_latent_image", "concat_mask", "control_video", "camera_conditions", "denoise_mask", "pose_video_latent"):
            value = metadata.get(key)
            if torch.is_tensor(value) and value.ndim == 5 and value.shape[2] >= video_end:
                metadata[key] = value[:, :, video_start:video_end].clone()
        if reference_latent is not None:
            concat_image = metadata.get("concat_latent_image")
            concat_mask = metadata.get("concat_mask")
            if torch.is_tensor(concat_image) and concat_image.shape[1] == reference_latent.shape[1]:
                reference_steps = min(reference_latent.shape[2], concat_image.shape[2])
                concat_image[:, :, :reference_steps] = reference_latent[:, :, -reference_steps:].to(concat_image)
                if torch.is_tensor(concat_mask):
                    concat_mask[:, :, :reference_steps] = 0
        for key in ("vace_frames", "vace_mask"):
            value = metadata.get(key)
            if value is not None:
                metadata[key] = [item[:, :, video_start:video_end].clone() if item.ndim == 5 and item.shape[2] >= video_end else item for item in value]
        context = metadata.get("context_latents")
        if context is not None:
            metadata["context_latents"] = [item[:, :, video_start:video_end].clone() if item.ndim == 5 and item.shape[2] >= video_end else item for item in context]
        sliced.append([cross_attn, metadata])
    return sliced


class WanImageToVideoLowMemory:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "positive": ("CONDITIONING",),
            "negative": ("CONDITIONING",),
            "vae": ("VAE",),
            "width": ("INT", {"default": 1920, "min": 16, "max": nodes.MAX_RESOLUTION, "step": 16}),
            "height": ("INT", {"default": 1088, "min": 16, "max": nodes.MAX_RESOLUTION, "step": 16}),
            "length": ("INT", {"default": 49, "min": 1, "max": nodes.MAX_RESOLUTION, "step": 4}),
            "batch_size": ("INT", {"default": 1, "min": 1, "max": 4096}),
            "vae_tile_size": ("INT", {"default": 256, "min": 128, "max": 2048, "step": 64}),
            "vae_tile_overlap": ("INT", {"default": 64, "min": 8, "max": 1024, "step": 8}),
            "vae_temporal_size": ("INT", {"default": 5, "min": 2, "max": 64}),
            "vae_temporal_overlap": ("INT", {"default": 1, "min": 1, "max": 63}),
        }, "optional": {
            "start_image": ("IMAGE",),
            "clip_vision_output": ("CLIP_VISION_OUTPUT",),
        }}

    RETURN_TYPES = ("CONDITIONING", "CONDITIONING", "LATENT")
    RETURN_NAMES = ("positive", "negative", "latent")
    FUNCTION = "execute"
    CATEGORY = "model/conditioning/wan"

    def execute(self, positive, negative, vae, width, height, length, batch_size, vae_tile_size,
                vae_tile_overlap, vae_temporal_size, vae_temporal_overlap, start_image=None,
                clip_vision_output=None):
        return _wan_image_to_video_low_memory(
            positive, negative, vae, width, height, length, batch_size, start_image, clip_vision_output,
            vae_tile_size, vae_tile_overlap, vae_temporal_size, vae_temporal_overlap,
        )


class WanThreeFrameToVideoLowMemory:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "positive": ("CONDITIONING",),
            "negative": ("CONDITIONING",),
            "vae": ("VAE",),
            "width": ("INT", {"default": 1920, "min": 16, "max": nodes.MAX_RESOLUTION, "step": 16}),
            "height": ("INT", {"default": 1088, "min": 16, "max": nodes.MAX_RESOLUTION, "step": 16}),
            "length": ("INT", {"default": 65, "min": 1, "max": nodes.MAX_RESOLUTION, "step": 4}),
            "batch_size": ("INT", {"default": 1, "min": 1, "max": 4096}),
            "vae_tile_size": ("INT", {"default": 256, "min": 128, "max": 2048, "step": 64}),
            "vae_tile_overlap": ("INT", {"default": 64, "min": 8, "max": 1024, "step": 8}),
            "vae_temporal_size": ("INT", {"default": 5, "min": 2, "max": 64}),
            "vae_temporal_overlap": ("INT", {"default": 1, "min": 1, "max": 63}),
        }, "optional": {
            "start_image": ("IMAGE",),
            "middle_image": ("IMAGE",),
            "end_image": ("IMAGE",),
            "clip_vision_start": ("CLIP_VISION_OUTPUT",),
            "clip_vision_middle": ("CLIP_VISION_OUTPUT",),
            "clip_vision_end": ("CLIP_VISION_OUTPUT",),
        }}

    RETURN_TYPES = ("CONDITIONING", "CONDITIONING", "LATENT")
    RETURN_NAMES = ("positive", "negative", "latent")
    FUNCTION = "execute"
    CATEGORY = "model/conditioning/wan"

    def execute(self, positive, negative, vae, width, height, length, batch_size, vae_tile_size,
                vae_tile_overlap, vae_temporal_size, vae_temporal_overlap, start_image=None,
                middle_image=None, end_image=None, clip_vision_start=None, clip_vision_middle=None,
                clip_vision_end=None):
        latent_steps = pixel_frames_to_latent_steps(length)
        latent = torch.zeros(
            (batch_size, vae.latent_channels, latent_steps, height // vae.spacial_compression_encode(), width // vae.spacial_compression_encode()),
            device=comfy.model_management.intermediate_device(),
        )
        images = [(0, start_image), (((length - 1) // 8) * 4, middle_image), (length - 1, end_image)]
        connected = [(index, image[:1]) for index, image in images if image is not None]
        if connected:
            dtype = connected[0][1].dtype
            video = torch.full((length, height, width, 3), 0.5, device="cpu", dtype=dtype)
            pixel_mask = torch.ones((1, 1, latent_steps * 4, height // vae.spacial_compression_encode(), width // vae.spacial_compression_encode()), device="cpu", dtype=dtype)
            for index, image in connected:
                resized = comfy.utils.common_upscale(
                    image.movedim(-1, 1), width, height, "bilinear", "center",
                ).movedim(1, -1).detach().cpu()
                video[index] = resized[0, :, :, :3]
                pixel_mask[:, :, index:index + 1] = 0.0
            concat_latent_image = _encode_wan_video_tiled(
                vae, video, vae_tile_size, vae_tile_overlap, vae_temporal_size, vae_temporal_overlap,
            )
            concat_mask = pixel_mask.view(1, latent_steps, 4, pixel_mask.shape[-2], pixel_mask.shape[-1]).transpose(1, 2)
            values = {"concat_latent_image": concat_latent_image, "concat_mask": concat_mask}
            positive = node_helpers.conditioning_set_values(positive, values)
            negative = node_helpers.conditioning_set_values(negative, values)

        clip_outputs = [x for x in (clip_vision_start, clip_vision_middle, clip_vision_end) if x is not None]
        if clip_outputs:
            clip_vision_output = comfy.clip_vision.Output()
            clip_vision_output.penultimate_hidden_states = torch.cat(
                [output.penultimate_hidden_states for output in clip_outputs], dim=-2,
            )
            values = {"clip_vision_output": clip_vision_output}
            positive = node_helpers.conditioning_set_values(positive, values)
            negative = node_helpers.conditioning_set_values(negative, values)
        return (positive, negative, {"samples": latent})


class Wan22TwoStageSingleChunkSampler:
    @classmethod
    def INPUT_TYPES(cls):
        stage_noise = (["enable", "disable"], {"advanced": True})
        stage_leftover = (["disable", "enable"], {"advanced": True})
        return {"required": {
            "high_model": ("MODEL",),
            "low_model": ("MODEL",),
            "positive": ("CONDITIONING",),
            "negative": ("CONDITIONING",),
            "latent_image": ("LATENT",),
            "noise_seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff, "control_after_generate": True}),
            "steps": ("INT", {"default": 20, "min": 1, "max": 10000}),
            "cfg": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 100.0, "step": 0.1, "round": 0.01}),
            "sampler_name": (comfy.samplers.KSampler.SAMPLERS,),
            "scheduler": (comfy.samplers.KSampler.SCHEDULERS,),
            "high_add_noise": stage_noise,
            "high_start_at_step": ("INT", {"default": 0, "min": 0, "max": 10000, "advanced": True}),
            "high_end_at_step": ("INT", {"default": 10, "min": 0, "max": 10000, "advanced": True}),
            "high_return_with_leftover_noise": stage_leftover,
            "low_add_noise": stage_noise,
            "low_start_at_step": ("INT", {"default": 10, "min": 0, "max": 10000, "advanced": True}),
            "low_end_at_step": ("INT", {"default": 10000, "min": 0, "max": 10000, "advanced": True}),
            "low_return_with_leftover_noise": stage_leftover,
        }}

    RETURN_TYPES = ("LATENT",)
    FUNCTION = "execute"
    CATEGORY = "video/split"

    def execute(self, high_model, low_model, positive, negative, latent_image, noise_seed, steps, cfg,
                sampler_name, scheduler, high_add_noise, high_start_at_step, high_end_at_step,
                high_return_with_leftover_noise, low_add_noise, low_start_at_step, low_end_at_step,
                low_return_with_leftover_noise):
        if not 0 <= high_start_at_step <= high_end_at_step:
            raise ValueError("High-noise steps must satisfy 0 <= start_at_step <= end_at_step")
        if not 0 <= low_start_at_step <= low_end_at_step:
            raise ValueError("Low-noise steps must satisfy 0 <= start_at_step <= end_at_step")

        try:
            high_output = nodes.common_ksampler(
                high_model, noise_seed, steps, cfg, sampler_name, scheduler,
                positive, negative, latent_image,
                disable_noise=high_add_noise == "disable",
                start_step=high_start_at_step,
                last_step=high_end_at_step,
                force_full_denoise=high_return_with_leftover_noise == "disable",
            )[0]
        finally:
            comfy.model_management.unload_model_and_clones(high_model, all_devices=True)
            comfy.model_management.soft_empty_cache()

        try:
            return nodes.common_ksampler(
                low_model, noise_seed, steps, cfg, sampler_name, scheduler,
                positive, negative, high_output,
                disable_noise=low_add_noise == "disable",
                start_step=low_start_at_step,
                last_step=low_end_at_step,
                force_full_denoise=low_return_with_leftover_noise == "disable",
            )
        finally:
            comfy.model_management.unload_model_and_clones(low_model, all_devices=True)
            comfy.model_management.soft_empty_cache()


class Wan22TwoStageUnlimitedSampler:
    @classmethod
    def INPUT_TYPES(cls):
        inputs = Wan22TwoStageSingleChunkSampler.INPUT_TYPES()
        inputs["required"] = inputs["required"].copy()
        inputs["required"]["vae"] = ("VAE",)
        inputs["required"]["chunk_frames"] = ("INT", {"default": 49, "min": 5, "max": 1024, "step": 4})
        inputs["optional"] = {
            "clip_vision_output": ("CLIP_VISION_OUTPUT",),
            "tiled_decode": ("BOOLEAN", {"default": True}),
            "vae_tile_size": ("INT", {"default": 256, "min": 128, "max": 2048, "step": 64}),
            "vae_tile_overlap": ("INT", {"default": 64, "min": 8, "max": 1024, "step": 8}),
            "vae_temporal_size": ("INT", {"default": 2, "min": 2, "max": 64}),
            "vae_temporal_overlap": ("INT", {"default": 1, "min": 1, "max": 63}),
            "vae_encode_temporal_size": ("INT", {"default": 5, "min": 2, "max": 64}),
            "chain_latent": (["disable", "enable"], {"default": "disable", "advanced": True}),
            "chain_denoise_strength": ("FLOAT", {"default": 0.3, "min": 0.0, "max": 1.0, "step": 0.05, "advanced": True}),
            "overlap_frames": ("INT", {"default": 0, "min": 0, "max": 32, "step": 4, "advanced": True}),
            "debug": ("BOOLEAN", {"default": False}),
        }
        return inputs

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("frames", "chunk_info")
    FUNCTION = "execute"
    CATEGORY = "video/split"

    def execute(self, high_model, low_model, vae, positive, negative, latent_image, noise_seed, steps, cfg,
                sampler_name, scheduler, high_add_noise, high_start_at_step, high_end_at_step,
                high_return_with_leftover_noise, low_add_noise, low_start_at_step, low_end_at_step,
                low_return_with_leftover_noise, chunk_frames, clip_vision_output=None, tiled_decode=True,
                vae_tile_size=256, vae_tile_overlap=64, vae_temporal_size=2, vae_temporal_overlap=1,
                vae_encode_temporal_size=5, chain_latent="disable", chain_denoise_strength=0.3,
                overlap_frames=0, debug=False, clip=None, positive_prompt="", negative_prompt="", fps=16.0):
        if chain_latent != "disable":
            logging.warning("Wan22 chain latent is disabled; using frame overlap continuation")
        if clip is not None or positive_prompt or negative_prompt or fps != 16.0:
            logging.warning("Wan22 legacy prompt inputs are ignored")
        if not 0 <= high_start_at_step <= high_end_at_step:
            raise ValueError("High-noise steps must satisfy 0 <= start_at_step <= end_at_step")
        if not 0 <= low_start_at_step <= low_end_at_step:
            raise ValueError("Low-noise steps must satisfy 0 <= start_at_step <= end_at_step")

        samples = comfy.sample.fix_empty_latent_channels(
            high_model,
            latent_image["samples"],
            latent_image.get("downscale_ratio_spacial"),
            latent_image.get("downscale_ratio_temporal"),
        )
        if samples.is_nested or samples.ndim != 5 or samples.shape[0] != 1:
            raise ValueError("Wan22 two-stage unlimited sampler requires one video latent with batch size 1")
        if samples.shape[1] != 16 or vae.latent_dim != 3 or vae.latent_channels != 16 or vae.spacial_compression_encode() != 8:
            raise ValueError("Wan22 internal I2V loop currently supports only 16-channel, 8x spatial Wan video latents and VAE")

        total_steps = samples.shape[2]
        max_steps = pixel_frames_to_latent_steps(max(5, align_pixel_frames_to_chunk(chunk_frames)))
        max_steps = max(2, max_steps)
        remaining_intervals = total_steps - 1
        overlap_intervals = min(overlap_frames // 4, max_steps - 2)
        frame_chunks = []
        chunk_infos = []
        previous_frames = None
        chunk_index = 0
        video_width = samples.shape[4] * vae.spacial_compression_encode()
        video_height = samples.shape[3] * vae.spacial_compression_encode()

        while chunk_index == 0 or remaining_intervals > 0:
            if chunk_index == 0:
                new_intervals = min(max_steps - 1, remaining_intervals)
                sampled_intervals = new_intervals
                context_frames = 0
            else:
                new_intervals = min(max_steps - 1 - overlap_intervals, remaining_intervals)
                sampled_intervals = overlap_intervals + new_intervals
                context_frames = latent_steps_to_pixel_frames(overlap_intervals + 1)
            chunk_steps = sampled_intervals + 1
            chunk_length = latent_steps_to_pixel_frames(chunk_steps)

            if chunk_index == 0:
                chunk_latent = latent_image.copy()
                chunk_latent["samples"] = samples[:, :, :chunk_steps].clone()
                if "noise_mask" in latent_image:
                    chunk_latent["noise_mask"] = _slice_mask(latent_image["noise_mask"], 0, chunk_steps, samples)
                positive_chunk = _slice_standard_conditioning(positive, 0, chunk_steps, clip_vision_output=clip_vision_output)
                negative_chunk = _slice_standard_conditioning(negative, 0, chunk_steps, clip_vision_output=clip_vision_output)
            else:
                context = previous_frames[-context_frames:]
                positive_chunk, negative_chunk, chunk_latent = _wan_image_to_video_low_memory(
                    positive, negative, vae, video_width, video_height, chunk_length, 1,
                    context, clip_vision_output, vae_tile_size, vae_tile_overlap,
                    vae_encode_temporal_size, vae_temporal_overlap,
                )

            low_output = Wan22TwoStageSingleChunkSampler().execute(
                high_model, low_model, positive_chunk, negative_chunk, chunk_latent, noise_seed, steps, cfg,
                sampler_name, scheduler, high_add_noise, high_start_at_step, high_end_at_step,
                high_return_with_leftover_noise, low_add_noise, low_start_at_step, low_end_at_step,
                low_return_with_leftover_noise,
            )[0]
            decoded = _decode_wan_video(
                vae, low_output["samples"], tiled_decode, vae_tile_size, vae_tile_overlap,
                vae_temporal_size, vae_temporal_overlap,
            )
            if chunk_index:
                frame_chunks.append(decoded[context_frames:])
            else:
                frame_chunks.append(decoded)
            previous_frames = decoded
            remaining_intervals -= new_intervals
            output_frames = chunk_length if chunk_index == 0 else chunk_length - context_frames
            chunk_infos.append(
                f"Chunk {chunk_index + 1}: {chunk_length} sampled frames, {output_frames} output frames"
            )
            if debug:
                logging.info(
                    "Wan two-stage I2V loop chunk %d sampled=%d output=%d identity_reference=%s last_frame_mean=%.5f last_frame_std=%.5f",
                    chunk_index + 1,
                    chunk_length,
                    output_frames,
                    clip_vision_output is not None,
                    decoded[-1:].float().mean().item(),
                    decoded[-1:].float().std().item(),
                )
            chunk_index += 1

        frames = torch.cat(frame_chunks, dim=0)
        expected_frames = latent_steps_to_pixel_frames(total_steps)
        if frames.shape[0] != expected_frames:
            raise RuntimeError(f"Wan22 I2V loop produced {frames.shape[0]} frames; expected {expected_frames}")
        return (frames, "\n".join(chunk_infos))


def _bernini_video_segment(video, start, length):
    if video is None:
        return None
    segment = video[start:start + length]
    if segment.shape[0] == 0:
        segment = video[-1:]
    if segment.shape[0] < length:
        segment = torch.cat([segment, segment[-1:].repeat(length - segment.shape[0], 1, 1, 1)], dim=0)
    return segment


def _remove_bernini_context(conditioning):
    cleaned = []
    context_count = 0
    for cross_attn, metadata in conditioning:
        metadata = metadata.copy()
        context = metadata.pop("context_latents", None)
        if context is not None:
            context_count = max(context_count, len(context))
        cleaned.append([cross_attn, metadata])
    return cleaned, context_count


class BerniniTwoStageUnlimitedSampler:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "high_model": ("MODEL",),
            "low_model": ("MODEL",),
            "positive": ("CONDITIONING", {"tooltip": "Text conditioning; existing Bernini context is replaced per chunk"}),
            "negative": ("CONDITIONING", {"tooltip": "Text conditioning; existing Bernini context is replaced per chunk"}),
            "sampler": ("SAMPLER",),
            "high_sigmas": ("SIGMAS",),
            "low_sigmas": ("SIGMAS",),
            "vae": ("VAE",),
            "width": ("INT", {"default": 832, "min": 16, "max": 8192, "step": 16}),
            "height": ("INT", {"default": 480, "min": 16, "max": 8192, "step": 16}),
            "total_frames": ("INT", {"default": 81, "min": 1, "max": 8192, "step": 4}),
            "high_add_noise": ("BOOLEAN", {"default": True, "advanced": True}),
            "high_noise_seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff, "control_after_generate": True}),
            "low_add_noise": ("BOOLEAN", {"default": False, "advanced": True}),
            "low_noise_seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff, "control_after_generate": True}),
            "high_cfg": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 100.0, "step": 0.1, "round": 0.01}),
            "low_cfg": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 100.0, "step": 0.1, "round": 0.01}),
            "chunk_frames": ("INT", {"default": 49, "min": 5, "max": 1024, "step": 4}),
            "ref_max_size": ("INT", {"default": 848, "min": 16, "max": 8192, "step": 16}),
        }, "optional": {
            "image0": ("IMAGE",),
            "image1": ("IMAGE",),
            "image2": ("IMAGE",),
            "image3": ("IMAGE",),
            "image4": ("IMAGE",),
            "image5": ("IMAGE",),
            "image6": ("IMAGE",),
            "image7": ("IMAGE",),
            "source_video": ("IMAGE",),
            "reference_video": ("IMAGE",),
            "reference_images": ("IMAGE", {"tooltip": "Legacy batch input; use image0-image7 to preserve Bernini slot order"}),
            "tiled_decode": ("BOOLEAN", {"default": True}),
            "vae_tile_size": ("INT", {"default": 256, "min": 128, "max": 2048, "step": 64}),
            "vae_tile_overlap": ("INT", {"default": 64, "min": 8, "max": 1024, "step": 8}),
            "vae_temporal_size": ("INT", {"default": 2, "min": 2, "max": 64}),
            "vae_temporal_overlap": ("INT", {"default": 1, "min": 1, "max": 63}),
            "chain_latent": (["disable", "enable"], {"default": "disable", "advanced": True}),
            "chain_denoise_strength": ("FLOAT", {"default": 0.3, "min": 0.0, "max": 1.0, "step": 0.05, "advanced": True}),
            "overlap_frames": ("INT", {"default": 0, "min": 0, "max": 32, "step": 4, "advanced": True}),
            "debug": ("BOOLEAN", {"default": False}),
        }}

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("frames", "chunk_info")
    FUNCTION = "execute"
    CATEGORY = "video/split"

    def execute(self, high_model, low_model, positive, negative, sampler, high_sigmas, low_sigmas, vae, width, height,
                total_frames, high_add_noise, high_noise_seed, low_add_noise, low_noise_seed, high_cfg, low_cfg,
                chunk_frames, ref_max_size, image0=None, image1=None, image2=None, image3=None, image4=None,
                image5=None, image6=None, image7=None, source_video=None, reference_video=None, reference_images=None,
                tiled_decode=True, vae_tile_size=256, vae_tile_overlap=64, vae_temporal_size=2,
                vae_temporal_overlap=1, chain_latent="disable", chain_denoise_strength=0.3,
                overlap_frames=0, debug=False):
        if chain_latent != "disable" or overlap_frames:
            logging.warning("Bernini chain latent and overlap are disabled; using the stable continuation path")
        if vae.latent_dim != 3 or vae.latent_channels != 16 or vae.spacial_compression_encode() != 8:
            raise ValueError("Bernini two-stage unlimited sampler requires a 16-channel, 8x spatial Wan video VAE")
        if (total_frames - 1) % 4:
            raise ValueError("Bernini total_frames must follow the 1+4N frame grid")
        images = [image0, image1, image2, image3, image4, image5, image6, image7]
        if source_video is None and reference_video is None and reference_images is None and not any(image is not None for image in images):
            raise ValueError("Connect at least one Bernini source or reference input")

        positive, original_context_count = _remove_bernini_context(positive)
        negative, _ = _remove_bernini_context(negative)
        total_steps = pixel_frames_to_latent_steps(total_frames)
        max_steps = max(2, pixel_frames_to_latent_steps(max(5, align_pixel_frames_to_chunk(chunk_frames))))
        remaining_intervals = total_steps - 1
        frame_start = 0
        frame_chunks = []
        chunk_infos = []
        continuation_frame = None
        chunk_index = 0

        while chunk_index == 0 or remaining_intervals > 0:
            new_intervals = min(max_steps - 1, remaining_intervals)
            chunk_length = latent_steps_to_pixel_frames(new_intervals + 1)
            source_chunk = _bernini_video_segment(source_video, frame_start, chunk_length)
            reference_video_chunk = _bernini_video_segment(reference_video, frame_start, chunk_length)
            reference_inputs = {
                f"reference_image_{index}": image
                for index, image in enumerate(images)
                if image is not None
            }
            if reference_images is not None:
                reference_inputs[f"reference_image_{len(reference_inputs)}"] = reference_images
            if continuation_frame is not None and len(reference_inputs) < 8:
                reference_inputs[f"reference_image_{len(reference_inputs)}"] = continuation_frame

            positive_chunk, negative_chunk, chunk_latent = BerniniConditioning.execute(
                positive, negative, vae, width, height, chunk_length, 1,
                source_video=source_chunk,
                reference_video=reference_video_chunk,
                reference_images=reference_inputs or None,
                ref_max_size=ref_max_size,
            ).result

            try:
                high_output = SamplerCustom.execute(
                    high_model, high_add_noise, high_noise_seed, high_cfg, positive_chunk, negative_chunk,
                    sampler, high_sigmas, chunk_latent,
                ).result[0]
            finally:
                comfy.model_management.unload_model_and_clones(high_model, all_devices=True)
                comfy.model_management.soft_empty_cache()

            try:
                low_output = SamplerCustom.execute(
                    low_model, low_add_noise, low_noise_seed, low_cfg, positive_chunk, negative_chunk,
                    sampler, low_sigmas, high_output,
                ).result[0]
            finally:
                comfy.model_management.unload_model_and_clones(low_model, all_devices=True)
                comfy.model_management.soft_empty_cache()

            decoded = _decode_wan_video(
                vae, low_output["samples"], tiled_decode, vae_tile_size, vae_tile_overlap,
                vae_temporal_size, vae_temporal_overlap,
            )
            frame_chunks.append(decoded if chunk_index == 0 else decoded[1:])
            continuation_frame = decoded[-1:]
            output_frames = chunk_length if chunk_index == 0 else chunk_length - 1
            chunk_infos.append(f"Chunk {chunk_index + 1}: {chunk_length} sampled frames, {output_frames} output frames")
            if debug:
                logging.info(
                    "Bernini chunk %d sampled=%d output=%d refs=%d original_contexts=%d",
                    chunk_index + 1, chunk_length, output_frames, len(reference_inputs), original_context_count,
                )

            remaining_intervals -= new_intervals
            frame_start += new_intervals * 4
            chunk_index += 1

        frames = torch.cat(frame_chunks, dim=0)
        if frames.shape[0] != total_frames:
            raise RuntimeError(f"Bernini chunk assembly produced {frames.shape[0]} frames; expected {total_frames}")
        return (frames, "\n".join(chunk_infos))


# ============================================================================
# 预览节点
# ============================================================================

try:
    from comfy_api.latest import io
    HAS_IO_LATEST = True
except ImportError:
    HAS_IO_LATEST = False

if HAS_IO_LATEST:
    import folder_paths

    class Wan22UnlimitedPreview(io.ComfyNode):
        """Wan22 / Bernini two-stage sampler preview."""

        @classmethod
        def define_schema(cls):
            return io.Schema(
                node_id="Wan22UnlimitedPreview",
                display_name="Wan22 Unlimited Preview",
                category="video/split",
                description="为 Wan22 分块采样添加实时预览包装。使用 lighttaew2_2 TAESD 解码。",
                inputs=[
                    io.Model.Input("model"),
                    io.Int.Input("max_resolution", default=512, min=64, max=2048, step=64),
                    io.Int.Input("quality", default=75, min=30, max=100, step=1),
                    io.Float.Input("fps", default=24.0, min=1.0, max=60.0, step=0.001),
                    io.Int.Input("frame_stride", default=4, min=1, max=16, step=1),
                    io.Combo.Input(
                        "tiny_vae",
                        options=["none"] + folder_paths.get_filename_list("vae_approx"),
                        default="lighttaew2_2",
                    ),
                ],
                outputs=[io.Model.Output()],
                hidden=[io.Hidden.unique_id],
                is_experimental=True,
            )

        @classmethod
        def execute(cls, model, max_resolution, quality, fps, frame_stride, tiny_vae="lighttaew2_2"):
            from .preview import _AccumulatedPreviewWrapper, WAN22_PREVIEW_WRAPPER_KEY

            patched = model.clone()
            patched.add_wrapper_with_key(
                comfy.patcher_extension.WrappersMP.OUTER_SAMPLE,
                WAN22_PREVIEW_WRAPPER_KEY,
                _AccumulatedPreviewWrapper(
                    cls.hidden.unique_id, max_resolution, quality, fps, frame_stride, tiny_vae,
                    temporal_ratio=4,  # Wan22 时间压缩比
                    taesd_name="lighttaew2_2",
                ),
            )
            return io.NodeOutput(patched)


class WanVAEDecodeSpatialTiled:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "samples": ("LATENT",),
            "vae": ("VAE",),
            "tile_size": ("INT", {"default": 256, "min": 128, "max": 2048, "step": 64}),
            "tile_overlap": ("INT", {"default": 64, "min": 8, "max": 1024, "step": 8}),
        }}

    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "decode"
    CATEGORY = "model/latent"

    def decode(self, samples, vae, tile_size, tile_overlap):
        if tile_overlap >= tile_size:
            raise ValueError("Wan VAE tile_overlap must be smaller than tile_size")
        latent = samples["samples"]
        if latent.is_nested:
            latent = latent.unbind()[0]
        if latent.ndim != 5:
            raise ValueError("Wan spatial tiled decode requires a video latent")

        compression = vae.spacial_compression_decode()
        tile = max(1, tile_size // compression)
        overlap = min(tile - 1, max(1, tile_overlap // compression))
        original_output_device = vae.output_device
        try:
            vae.output_device = torch.device("cpu")
            images = vae.decode_tiled(
                latent,
                tile_x=tile,
                tile_y=tile,
                overlap=overlap,
                tile_t=latent.shape[2],
                overlap_t=max(1, latent.shape[2] - 1),
            )
        finally:
            vae.output_device = original_output_device
        if images.ndim == 5:
            images = images.flatten(0, 1)
        return (images.detach().cpu(),)


class Wan22SlidingContextWindows:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "model": ("MODEL",),
            "window_frames": ("INT", {"default": 29, "min": 5, "max": 1024, "step": 4}),
            "overlap_frames": ("INT", {"default": 9, "min": 1, "max": 1024, "step": 4}),
            "retain_first_frame": ("BOOLEAN", {"default": False}),
            "fuse_method": (["overlap-linear", "pyramid", "flat"], {"default": "overlap-linear"}),
        }}

    RETURN_TYPES = ("MODEL",)
    FUNCTION = "execute"
    CATEGORY = "model/patch/wan"
    EXPERIMENTAL = True

    def execute(self, model, window_frames, overlap_frames, retain_first_frame, fuse_method):
        context_length = pixel_frames_to_latent_steps(align_pixel_frames_to_chunk(window_frames))
        context_overlap = max(overlap_frames // 4, 0)
        if context_overlap >= context_length:
            raise ValueError("Wan22 sliding context overlap must be smaller than the window")

        patched = model.clone()
        patched.model_options["context_handler"] = comfy.context_windows.IndexListContextHandler(
            context_schedule=comfy.context_windows.get_matching_context_schedule(
                comfy.context_windows.ContextSchedules.UNIFORM_STANDARD,
            ),
            fuse_method=comfy.context_windows.get_matching_fuse_method(fuse_method),
            context_length=context_length,
            context_overlap=context_overlap,
            context_stride=1,
            closed_loop=False,
            dim=2,
            freenoise=False,
            cond_retain_index_list="0" if retain_first_frame else "",
            split_conds_to_windows=False,
            latent_retain_index_list="",
            causal_window_fix=True,
        )
        patched.remove_wrappers_with_key(
            comfy.patcher_extension.WrappersMP.PREPARE_SAMPLING,
            "ContextWindows_prepare_sampling",
        )
        comfy.context_windows.create_prepare_sampling_wrapper(patched)
        return (patched,)


# ============================================================================
# 节点映射
# ============================================================================

WAN22_NODE_CLASS_MAPPINGS = {
    "WanImageToVideoLowMemory": WanImageToVideoLowMemory,
    "WanThreeFrameToVideoLowMemory": WanThreeFrameToVideoLowMemory,
    "Wan22TwoStageSingleChunkSampler": Wan22TwoStageSingleChunkSampler,
    "Wan22TwoStageUnlimitedSampler": Wan22TwoStageUnlimitedSampler,
    "BerniniTwoStageUnlimitedSampler": BerniniTwoStageUnlimitedSampler,
    "Wan22SlidingContextWindows": Wan22SlidingContextWindows,
    "WanVAEDecodeSpatialTiled": WanVAEDecodeSpatialTiled,
}
WAN22_NODE_DISPLAY_NAME_MAPPINGS = {
    "WanImageToVideoLowMemory": "Wan Image To Video (Low Memory)",
    "WanThreeFrameToVideoLowMemory": "Wan Three Frames To Video (Low Memory)",
    "Wan22TwoStageSingleChunkSampler": "Wan22 Two-Stage Single Chunk Sampler",
    "Wan22TwoStageUnlimitedSampler": "Wan22 Two-Stage I2V Sampler Unlimited",
    "BerniniTwoStageUnlimitedSampler": "Bernini Two-Stage Sampler Unlimited",
    "Wan22SlidingContextWindows": "Wan22 Sliding Context Windows",
    "WanVAEDecodeSpatialTiled": "Wan VAE Decode (Spatial Tiled)",
}

if HAS_IO_LATEST:
    WAN22_NODE_CLASS_MAPPINGS["Wan22UnlimitedPreview"] = Wan22UnlimitedPreview
    WAN22_NODE_DISPLAY_NAME_MAPPINGS["Wan22UnlimitedPreview"] = "Wan22 Unlimited Preview"
