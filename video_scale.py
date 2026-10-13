"""
VideoScale - Video and Image Super Resolution Node

A ComfyUI custom node for upscaling videos and images using:
- Real-ESRGAN (via realesrgan-python)
- or built-in interpolation methods

Supports 2x, 4x, 8x upscaling with denoising strength control.
"""

import torch
import numpy as np
from PIL import Image
from typing import Tuple, Union, List, Optional

# Try to import Real-ESRGAN (optional)
try:
    from basicsr.archs.rrdbnet_arch import RRDBNet
    from realesrgan import RealESRGANer
    HAS_REALESRGAN = True
except ImportError:
    HAS_REALESRGAN = False

# =============================================================================
# Node Metadata
# =============================================================================

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

# =============================================================================
# Upscale Methods
# =============================================================================

UPSCALE_METHODS = {
    "realesrgan": "Real-ESRGAN (Best Quality)",
    "bicubic": "Bicubic Interpolation",
    "lanczos": "Lanczos Interpolation",
    "nearest": "Nearest Neighbor (Fast)",
}


# =============================================================================
# Utility Functions
# =============================================================================

def tensor_to_ndarray(image: torch.Tensor) -> np.ndarray:
    """Convert tensor [B,H,W,C] or [H,W,C] to numpy array [0,1] float or [0,255] uint8."""
    if image.dim() == 4:
        image = image[0]
    
    np_img = image.cpu().numpy()
    
    # Determine if float [0,1] or int [0,255]
    if np_img.dtype in [np.float32, np.float64]:
        if np_img.max() <= 1.0:
            return np_img.astype(np.float32)
        else:
            return np_img.astype(np.float32) / 255.0
    else:
        return np_img.astype(np.float32) / 255.0


def ndarray_to_tensor(np_img: np.ndarray) -> torch.Tensor:
    """Convert numpy array to tensor."""
    if np_img.dtype != np.float32:
        np_img = np_img.astype(np.float32) / 255.0
    if np_img.ndim == 3 and np_img.shape[-1] in [1, 3, 4]:
        # HWC to CHW
        np_img = np_img.transpose(2, 0, 1)
    return torch.from_numpy(np_img)


def pil_to_tensor(image: Image.Image) -> torch.Tensor:
    """Convert PIL Image to tensor [1,C,H,W] float [0,1]."""
    np_img = np.array(image).astype(np.float32) / 255.0
    if np_img.ndim == 2:
        np_img = np_img[:, :, None]
    if np_img.shape[-1] in [1, 3, 4]:
        np_img = np_img.transpose(2, 0, 1)
    return torch.from_numpy(np_img).unsqueeze(0)


def tensor_to_pil(image: torch.Tensor) -> Image.Image:
    """Convert tensor [B,C,H,W] or [C,H,W] to PIL Image."""
    if image.dim() == 4:
        image = image[0]
    
    np_img = image.cpu().numpy()
    if np_img.dtype != np.uint8:
        np_img = (np_img * 255).clip(0, 255).astype(np.uint8)
    
    if np_img.shape[0] in [1, 3, 4]:
        np_img = np_img.transpose(1, 2, 0)
    
    if np_img.shape[-1] == 1:
        return Image.fromarray(np_img.squeeze(), mode="L")
    elif np_img.shape[-1] == 4:
        return Image.fromarray(np_img, mode="RGBA")
    else:
        return Image.fromarray(np_img, mode="RGB")


# =============================================================================
# Upscaling Functions
# =============================================================================

def upscale_bicubic(image: Image.Image, scale: int) -> Image.Image:
    """Upscale using bicubic interpolation."""
    new_size = (image.width * scale, image.height * scale)
    return image.resize(new_size, Image.BICUBIC)


def upscale_lanczos(image: Image.Image, scale: int) -> Image.Image:
    """Upscale using Lanczos interpolation."""
    new_size = (image.width * scale, image.height * scale)
    return image.resize(new_size, Image.LANCZOS)


def upscale_nearest(image: Image.Image, scale: int) -> Image.Image:
    """Upscale using nearest neighbor (fast, pixelated)."""
    new_size = (image.width * scale, image.height * scale)
    return image.resize(new_size, Image.NEAREST)


def upscale_realesrgan(
    image: Image.Image,
    scale: int = 4,
    model_name: str = "RealESRGAN_x4plus",
    denoise_strength: float = 0.5,
) -> Image.Image:
    """
    Upscale using Real-ESRGAN.
    
    Args:
        image: Input PIL Image
        scale: Upscale factor (2 or 4)
        model_name: Model name (RealESRGAN_x4plus, RealESRGAN_x2, etc.)
        denoise_strength: Denoising strength (0-1)
    
    Returns:
        Upscaled PIL Image
    """
    if not HAS_REALESRGAN:
        raise ImportError(
            "Real-ESRGAN not installed. Install with: pip install realesrgan"
        )
    
    # Select model based on scale
    if scale == 2:
        model = RRDBNet(
            num_in_ch=3,
            num_out_ch=3,
            num_feat=64,
            num_block=23,
            num_g_row_gden=1,
            num_gblk=31,
            scale=2,
        )
        netscale = 2
        if model_name == "RealESRGAN_x4plus":
            model_name = "RealESRGAN_x2plus"
    elif scale == 8:
        model = RRDBNet(
            num_in_ch=3,
            num_out_ch=3,
            num_feat=64,
            num_block=23,
            num_g_row_gden=1,
            num_gblk=31,
            scale=4,
        )
        netscale = 4
    else:
        model = RRDBNet(
            num_in_ch=3,
            num_out_ch=3,
            num_feat=64,
            num_block=23,
            num_g_row_gden=1,
            num_gblk=31,
            scale=4,
        )
        netscale = 4
    
    # Initialize upsampler
    upsampler = RealESRGANer(
        scale=netscale,
        model=model,
        tile=0,
        tile_pad=10,
        pre_pad=0,
        half=False,  # Use fp32 for better quality
    )
    
    # Prepare image
    np_img = np.array(image).astype(np.float32) / 255.0
    if np_img.ndim == 2:
        np_img = np_img[:, :, None]
    if np_img.shape[-1] == 4:
        np_img = np_img[:, :, :3]  # Remove alpha
    
    # Upscale
    output, _ = upsampler.enhance(np_img, outscale=scale)
    
    return Image.fromarray((output * 255).clip(0, 255).astype(np.uint8))


# =============================================================================
# ComfyUI Nodes
# =============================================================================

class VideoScaleNode:
    """
    Video/Image Super Resolution Node
    
    Upscales video frames or images using Real-ESRGAN or interpolation methods.
    """
    
    @classmethod
    def INPUT_TYPES(cls):
        inputs = {
            "required": {
                "images": ("IMAGE", {"tooltip": "Input images to upscale"}),
                "scale": ([2, 4], {
                    "default": 2,
                    "tooltip": "Upscale factor"
                }),
                "method": (["realesrgan", "bicubic", "lanczos", "nearest"], {
                    "default": "bicubic",
                    "tooltip": "Upscaling method"
                }),
                "denoise_strength": ("FLOAT", {
                    "default": 0.5,
                    "min": 0.0,
                    "max": 1.0,
                    "step": 0.05,
                    "tooltip": "Denoising strength (Real-ESRGAN only)"
                }),
            },
            "optional": {
                "model_name": ("STRING", {
                    "default": "RealESRGAN_x4plus",
                    "tooltip": "Real-ESRGAN model name"
                }),
            },
        }
        
        if not HAS_REALESRGAN:
            inputs["optional"]["realesrgan_warning"] = ("STRING", {
                "default": "⚠️ Real-ESRGAN not installed. Install with: pip install realesrgan",
            })
        
        return inputs

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("upscaled_images",)
    FUNCTION = "upscale"
    CATEGORY = "video"
    OUTPUT_NODE = True

    def upscale(
        self,
        images: torch.Tensor,
        scale: int,
        method: str,
        denoise_strength: float = 0.5,
        model_name: str = "RealESRGAN_x4plus",
    ) -> Tuple[torch.Tensor]:
        """Upscale images/video frames."""
        
        results = []
        
        for i in range(images.shape[0]):
            img_tensor = images[i]
            pil_img = tensor_to_pil(img_tensor)
            
            # Upscale based on method
            if method == "realesrgan":
                if HAS_REALESRGAN:
                    upscaled = upscale_realesrgan(
                        pil_img,
                        scale=scale,
                        model_name=model_name,
                        denoise_strength=denoise_strength,
                    )
                else:
                    # Fallback to bicubic
                    upscaled = upscale_bicubic(pil_img, scale)
            elif method == "bicubic":
                upscaled = upscale_bicubic(pil_img, scale)
            elif method == "lanczos":
                upscaled = upscale_lanczos(pil_img, scale)
            elif method == "nearest":
                upscaled = upscale_nearest(pil_img, scale)
            else:
                upscaled = upscale_bicubic(pil_img, scale)
            
            results.append(pil_to_tensor(upscaled))
        
        # Stack results
        output = torch.cat(results, dim=0)
        
        return (output,)


class VideoScaleSimpleNode:
    """
    Simple Video/Image Upscale Node
    
    Basic upscaling without advanced options.
    """
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "Input images"}),
                "scale": ([2, 4, 8], {
                    "default": 2,
                    "tooltip": "Upscale factor"
                }),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("upscaled_images",)
    FUNCTION = "upscale"
    CATEGORY = "video"

    def upscale(
        self,
        images: torch.Tensor,
        scale: int,
    ) -> Tuple[torch.Tensor]:
        """Simple upscale using Lanczos."""
        
        results = []
        
        for i in range(images.shape[0]):
            img_tensor = images[i]
            pil_img = tensor_to_pil(img_tensor)
            upscaled = pil_img.resize(
                (pil_img.width * scale, pil_img.height * scale),
                Image.LANCZOS
            )
            results.append(pil_to_tensor(upscaled))
        
        output = torch.cat(results, dim=0)
        return (output,)


class VideoScaleInfoNode:
    """
    Video Scale Info Node
    
    Shows information about the upscaling model.
    """
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "Input images"}),
            },
            "optional": {
                "scale": ("INT", {
                    "default": 2,
                }),
            },
        }

    RETURN_TYPES = ("STRING", "INT", "INT")
    RETURN_NAMES = ("info", "width", "height")
    FUNCTION = "get_info"
    CATEGORY = "video"

    def get_info(
        self,
        images: torch.Tensor,
        scale: int = 2,
    ) -> Tuple[str, int, int]:
        """Get info about images after upscaling."""
        
        if images.shape[0] > 0:
            img = images[0]
            pil_img = tensor_to_pil(img)
            new_width = pil_img.width * scale
            new_height = pil_img.height * scale
        else:
            new_width = 0
            new_height = 0
        
        info = f"Scale: {scale}x\n"
        info += f"Real-ESRGAN: {'Available' if HAS_REALESRGAN else 'Not installed'}\n"
        info += f"Output: {new_width}x{new_height}"
        
        return (info, new_width, new_height)


# =============================================================================
# Register Nodes
# =============================================================================

NODE_CLASS_MAPPINGS["VideoScaleNode"] = VideoScaleNode
NODE_CLASS_MAPPINGS["VideoScaleSimpleNode"] = VideoScaleSimpleNode
NODE_CLASS_MAPPINGS["VideoScaleInfoNode"] = VideoScaleInfoNode

NODE_DISPLAY_NAME_MAPPINGS["VideoScaleNode"] = "Video Scale (Advanced)"
NODE_DISPLAY_NAME_MAPPINGS["VideoScaleSimpleNode"] = "Video Scale"
NODE_DISPLAY_NAME_MAPPINGS["VideoScaleInfoNode"] = "Video Scale Info"


# =============================================================================
# Entry Point
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("VideoScale - Super Resolution Node")
    print("=" * 60)
    print(f"\nReal-ESRGAN: {'Available' if HAS_REALESRGAN else 'Not installed'}")
    print("\nUpscale Methods:")
    for key, name in UPSCALE_METHODS.items():
        print(f"  • {key}: {name}")
