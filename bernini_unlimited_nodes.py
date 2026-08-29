"""Bernini-specific low-memory model patches."""

import torch

import comfy.context_windows
import comfy.model_management
import comfy.patcher_extension
from comfy_extras.nodes_custom_sampler import SamplerCustom


TEMPORAL_RATIO = 4


def _pixel_frames_to_latent_steps(frames):
    if frames < 1:
        raise ValueError("Bernini frame count must be positive")
    return ((frames - 1) // TEMPORAL_RATIO) + 1


def _patch_context_model(model, window_frames, overlap_frames, schedule, fuse_method):
    context_length = _pixel_frames_to_latent_steps(window_frames)
    context_overlap = max(overlap_frames // TEMPORAL_RATIO, 0)
    if context_overlap >= context_length:
        raise ValueError("Bernini context overlap must be smaller than the window")

    schedules = {
        "static": comfy.context_windows.ContextSchedules.STATIC_STANDARD,
        "uniform": comfy.context_windows.ContextSchedules.UNIFORM_STANDARD,
    }
    patched = model.clone()
    patched.model_options["context_handler"] = comfy.context_windows.IndexListContextHandler(
        context_schedule=comfy.context_windows.get_matching_context_schedule(schedules[schedule]),
        fuse_method=comfy.context_windows.get_matching_fuse_method(fuse_method),
        context_length=context_length,
        context_overlap=context_overlap,
        context_stride=1,
        closed_loop=False,
        dim=2,
        freenoise=False,
        cond_retain_index_list="",
        split_conds_to_windows=False,
        latent_retain_index_list="",
        causal_window_fix=False,
    )
    patched.remove_wrappers_with_key(
        comfy.patcher_extension.WrappersMP.PREPARE_SAMPLING,
        "ContextWindows_prepare_sampling",
    )
    comfy.context_windows.create_prepare_sampling_wrapper(patched)
    return patched


class BerniniSlidingContextWindows:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "model": ("MODEL",),
            "window_frames": ("INT", {"default": 61, "min": 5, "max": 1024, "step": 4}),
            "overlap_frames": ("INT", {"default": 17, "min": 1, "max": 1024, "step": 4}),
            "schedule": (["static", "uniform"], {"default": "static"}),
            "fuse_method": (["overlap-linear", "pyramid", "flat"], {"default": "overlap-linear"}),
        }}

    RETURN_TYPES = ("MODEL",)
    FUNCTION = "execute"
    CATEGORY = "model/patch/bernini"
    EXPERIMENTAL = True

    def execute(self, model, window_frames, overlap_frames, schedule, fuse_method):
        return (_patch_context_model(model, window_frames, overlap_frames, schedule, fuse_method),)


class BerniniTwoStageSlidingSampler:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "high_model": ("MODEL",),
            "low_model": ("MODEL",),
            "positive": ("CONDITIONING",),
            "negative": ("CONDITIONING",),
            "latent_image": ("LATENT",),
            "sampler": ("SAMPLER",),
            "high_sigmas": ("SIGMAS",),
            "low_sigmas": ("SIGMAS",),
            "high_add_noise": ("BOOLEAN", {"default": True, "advanced": True}),
            "high_noise_seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff, "control_after_generate": True}),
            "low_add_noise": ("BOOLEAN", {"default": False, "advanced": True}),
            "low_noise_seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff, "control_after_generate": True}),
            "high_cfg": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 100.0, "step": 0.1}),
            "low_cfg": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 100.0, "step": 0.1}),
            "window_frames": ("INT", {"default": 61, "min": 5, "max": 1024, "step": 4}),
            "overlap_frames": ("INT", {"default": 17, "min": 1, "max": 1024, "step": 4}),
            "schedule": (["static", "uniform"], {"default": "static"}),
            "fuse_method": (["overlap-linear", "pyramid", "flat"], {"default": "overlap-linear"}),
        }}

    RETURN_TYPES = ("LATENT", "STRING")
    RETURN_NAMES = ("latent", "info")
    FUNCTION = "execute"
    CATEGORY = "sampling/bernini"
    EXPERIMENTAL = True

    def execute(self, high_model, low_model, positive, negative, latent_image, sampler, high_sigmas, low_sigmas,
                high_add_noise, high_noise_seed, low_add_noise, low_noise_seed, high_cfg, low_cfg,
                window_frames, overlap_frames, schedule, fuse_method):
        context_count = 0
        for _, metadata in positive:
            context_count = max(context_count, len(metadata.get("context_latents", [])))
        if context_count == 0:
            raise ValueError("Connect positive, negative, and latent from the native Bernini Conditioning node")

        high_model = _patch_context_model(high_model, window_frames, overlap_frames, schedule, fuse_method)
        low_model = _patch_context_model(low_model, window_frames, overlap_frames, schedule, fuse_method)
        try:
            high_output = SamplerCustom.execute(
                high_model, high_add_noise, high_noise_seed, high_cfg, positive, negative,
                sampler, high_sigmas, latent_image,
            ).result[0]
        finally:
            comfy.model_management.unload_model_and_clones(high_model, all_devices=True)
            comfy.model_management.soft_empty_cache()

        try:
            low_output = SamplerCustom.execute(
                low_model, low_add_noise, low_noise_seed, low_cfg, positive, negative,
                sampler, low_sigmas, high_output,
            ).result[0]
        finally:
            comfy.model_management.unload_model_and_clones(low_model, all_devices=True)
            comfy.model_management.soft_empty_cache()

        total_frames = 1 + TEMPORAL_RATIO * (low_output["samples"].shape[2] - 1)
        info = f"Bernini sliding: {total_frames} frames, window {window_frames}, overlap {overlap_frames}, references {context_count}, schedule {schedule}"
        return (low_output, info)


class BerniniVAEDecodeSpatialTiled:
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
    CATEGORY = "model/latent/bernini"

    def decode(self, samples, vae, tile_size, tile_overlap):
        if tile_overlap >= tile_size:
            raise ValueError("Bernini VAE tile_overlap must be smaller than tile_size")
        latent = samples["samples"]
        if latent.is_nested:
            latent = latent.unbind()[0]
        if latent.ndim != 5:
            raise ValueError("Bernini spatial tiled decode requires a video latent")

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


BERNINI_NODE_CLASS_MAPPINGS = {
    "BerniniSlidingContextWindows": BerniniSlidingContextWindows,
    "BerniniTwoStageSlidingSampler": BerniniTwoStageSlidingSampler,
    "BerniniVAEDecodeSpatialTiled": BerniniVAEDecodeSpatialTiled,
}
BERNINI_NODE_DISPLAY_NAME_MAPPINGS = {
    "BerniniSlidingContextWindows": "Bernini Sliding Context Windows",
    "BerniniTwoStageSlidingSampler": "Bernini Two-Stage Sliding Sampler",
    "BerniniVAEDecodeSpatialTiled": "Bernini VAE Decode (Spatial Tiled)",
}
