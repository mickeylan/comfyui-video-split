"""
VLM Prompt Enhancer - Vision Language Model Prompt Enhancement Node

A ComfyUI custom node that uses Vision Language Models (VLM) like Qwen-VL
to enhance prompts based on image content.

Features:
- Supports Qwen-VL, Qwen2-VL, Qwen2.5-VL models
- Image-aware prompt enhancement
- Strict text rendering policy compliance
"""

import torch
from PIL import Image
import base64
import io
import httpx
import json
import re
from typing import Optional, Tuple

# =============================================================================
# Node Metadata
# =============================================================================

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

# =============================================================================
# System Prompt
# =============================================================================

SYSTEM_PROMPT = """Write the complete descriptive prompt in English.
Do not infer or change this setting from the language of the user request.
User-supplied proper nouns, exact quoted text, brand names, interface labels,
and other text explicitly requested to appear in the image must remain exactly as supplied and must not be translated.

Text rendering policy is strict:
- Only include readable text in the generated image when the user explicitly supplied that exact text or explicitly requested text with a definite wording.
- If the user did not specify a title, magazine name, logo, subtitle, label, sign, watermark, caption, decorative lettering, or other readable text, do not invent any. Describe the relevant area as having no readable text, blank typography space, or an unlettered design when needed.
- Do not add example titles, placeholder words, generic magazine mastheads, random letters, numbers, symbols, or extra text merely to make the composition look complete.
- For image editing, existing readable text in the input image may remain unchanged when the user did not ask to edit it. Do not add any new text unless its exact wording is supplied by the user. If the user requests a replacement or new text, use only the exact wording requested.
- Never translate, paraphrase, complete, or embellish user-supplied visible text.

These node-level rules override any conflicting language or text rule earlier in the template.
Return only the final rewritten prompt as plain text, with no JSON, field names, Markdown code block, analysis, or explanation.

Reasoning visibility is strict:
- Do not output chain-of-thought, hidden reasoning, analysis, self-correction, task restatement, or planning notes.
- Do not write phrases such as "The task", "Wait", "Let me think", "I need to", or an explanation of how the prompt was composed.
- Begin directly with the final rewritten prompt and stop immediately after it."""

# =============================================================================
# Model Configurations
# =============================================================================

VLM_MODELS = {
    "qwen2.5-vl": {
        "name": "Qwen2.5-VL",
        "default_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
    },
    "qwen2-vl": {
        "name": "Qwen2-VL",
        "default_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
    },
    "qwen-vl": {
        "name": "Qwen-VL",
        "default_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
    },
    "qwen2.5": {
        "name": "Qwen2.5",
        "default_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
    },
}


# =============================================================================
# Utility Functions
# =============================================================================

def tensor_to_pil(image_tensor: torch.Tensor) -> Image.Image:
    """Convert tensor [B,H,W,C] or [H,W,C] to PIL Image."""
    if image_tensor.dim() == 4:
        image_tensor = image_tensor[0]
    
    # Handle both float [0,1] and int [0,255] tensors
    if image_tensor.dtype in [torch.float32, torch.float64]:
        if image_tensor.max() <= 1.0:
            image_np = (image_tensor.cpu().numpy() * 255).clip(0, 255).astype("uint8")
        else:
            image_np = image_tensor.cpu().numpy().astype("uint8")
    else:
        image_np = image_tensor.cpu().numpy().astype("uint8")
    
    return Image.fromarray(image_np)


def pil_to_jpeg_base64(image: Image.Image, quality: int = 95) -> str:
    """Convert PIL Image to JPEG base64 string."""
    buffer = io.BytesIO()
    # Convert RGBA to RGB if needed
    if image.mode == "RGBA":
        rgb = Image.new("RGB", image.size, (255, 255, 255))
        rgb.paste(image, mask=image.split()[3])
        image = rgb
    image.save(buffer, format="JPEG", quality=quality)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def resize_image_max_pixels(image: Image.Image, max_pixels: int = 1280 * 1280) -> Image.Image:
    """Resize image to not exceed max_pixels while maintaining aspect ratio."""
    pixels = image.width * image.height
    if pixels <= max_pixels:
        return image
    
    scale = (max_pixels / pixels) ** 0.5
    new_width = int(image.width * scale)
    new_height = int(image.height * scale)
    
    return image.resize((new_width, new_height), Image.LANCZOS)


def clean_response(text: str) -> str:
    """Clean and extract response text."""
    # Repair mojibake
    mojibake_fixes = {
        "\\u00e2\\u20ac\\u201e": '"',
        "\\u00e2\\u20ac\\u201c": '"',
        "\\u00e2\\u20ac\\u201d": '"',
        "\\u00e2\\u20ac\\u2122": "'",
        "\\u00c2\\u00a0": " ",
    }
    for broken, fixed in mojibake_fixes.items():
        text = text.replace(broken, fixed)
    
    # Remove think blocks
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    
    # Remove markdown code fences
    text = re.sub(r"^```(?:json|prompt|text)?\n?", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n?```$", "", text)
    
    return text.strip()


# =============================================================================
# API Client
# =============================================================================

async def call_vlm_api(
    api_url: str,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    image_b64: Optional[str] = None,
    temperature: float = 1.0,
    max_tokens: int = 2000,
    timeout: int = 120,
) -> str:
    """Call VLM API and return response text."""
    
    # Build messages
    if image_b64:
        content = [
            {"type": "text", "text": user_prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
        ]
    else:
        content = user_prompt
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": content},
    ]
    
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(api_url, json=payload, headers=headers)
        response.raise_for_status()
        result = response.json()
    
    # Extract text from response
    if "choices" in result:
        return result["choices"][0]["message"]["content"]
    elif "output" in result:
        return result["output"]
    elif "text" in result:
        return result["text"]
    else:
        return str(result)


# =============================================================================
# ComfyUI Nodes
# =============================================================================

class VLMPromptEnhancerNode:
    """
    VLM Prompt Enhancer Node
    
    Uses Vision Language Models to enhance prompts based on image context.
    """
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE", {"tooltip": "Input image for context"}),
                "text": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "Prompt to enhance"
                }),
                "model_family": (list(VLM_MODELS.keys()), {
                    "default": "qwen2.5-vl",
                    "tooltip": "VLM model family"
                }),
                "api_url": ("STRING", {
                    "default": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
                    "tooltip": "API endpoint URL"
                }),
                "api_key": ("STRING", {
                    "default": "",
                    "tooltip": "API key"
                }),
            },
            "optional": {
                "temperature": ("FLOAT", {
                    "default": 1.0,
                    "min": 0.0,
                    "max": 2.0,
                    "step": 0.1,
                    "tooltip": "Sampling temperature"
                }),
                "max_tokens": ("INT", {
                    "default": 2000,
                    "min": 100,
                    "max": 8000,
                    "tooltip": "Max tokens to generate"
                }),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("enhanced_prompt",)
    FUNCTION = "enhance"
    CATEGORY = "prompt"
    OUTPUT_NODE = True

    def enhance(
        self,
        image: torch.Tensor,
        text: str,
        model_family: str,
        api_url: str,
        api_key: str,
        temperature: float = 1.0,
        max_tokens: int = 2000,
    ) -> Tuple[str]:
        """Enhance prompt using VLM."""
        import asyncio
        
        # Validate inputs
        if not api_key:
            return ("Error: API key is required",)
        if not text.strip():
            return ("",)
        
        # Process image
        pil_image = tensor_to_pil(image)
        pil_image = resize_image_max_pixels(pil_image, max_pixels=1280 * 1280)
        image_b64 = pil_to_jpeg_base64(pil_image)
        
        # Get model name
        model_info = VLM_MODELS.get(model_family, VLM_MODELS["qwen2.5-vl"])
        model_name = model_info["name"]
        
        # Build prompt
        if model_family in ["qwen2.5", "qwen2", "qwen"]:
            # Text-only model, no image
            image_b64 = None
            user_prompt = text
        else:
            # Vision model
            user_prompt = f"Enhance this prompt based on the image: {text}"
        
        # Make API request
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        response = loop.run_until_complete(
            call_vlm_api(
                api_url=api_url,
                api_key=api_key,
                model=model_name,
                system_prompt=SYSTEM_PROMPT,
                user_prompt=user_prompt,
                image_b64=image_b64,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        )
        
        # Clean and return
        enhanced = clean_response(response)
        return (enhanced,)


class VLMStorageNode:
    """
    VLM API Storage Node
    
    Stores API configuration for reuse across workflows.
    """
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "api_key": ("STRING", {
                    "default": "",
                    "tooltip": "API key for VLM service"
                }),
                "api_url": ("STRING", {
                    "default": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
                    "tooltip": "API endpoint URL"
                }),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("api_url", "api_key")
    FUNCTION = "store"
    CATEGORY = "model"

    def store(self, api_key: str, api_url: str) -> Tuple[str, str]:
        """Store API configuration."""
        return (api_url, api_key)


# =============================================================================
# Register Nodes
# =============================================================================

NODE_CLASS_MAPPINGS["VLMPromptEnhancerNode"] = VLMPromptEnhancerNode
NODE_CLASS_MAPPINGS["VLMStorageNode"] = VLMStorageNode

NODE_DISPLAY_NAME_MAPPINGS["VLMPromptEnhancerNode"] = "VLM Prompt Enhancer"
NODE_DISPLAY_NAME_MAPPINGS["VLMStorageNode"] = "VLM API Storage"


# =============================================================================
# Entry Point
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("VLM Prompt Enhancer - ComfyUI Node")
    print("=" * 60)
    print("\nSupported Models:")
    for key, info in VLM_MODELS.items():
        print(f"  • {key}: {info['name']}")
    print("\nSystem Prompt (preview):")
    print(SYSTEM_PROMPT[:300] + "...")
