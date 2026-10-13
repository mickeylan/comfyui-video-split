"""
TE Qwen Image 2.1 Prompt Enhancer Node

A ComfyUI custom node that uses Qwen multimodal model to enhance prompts.
Based on reverse engineering of TE_Qwen_Image_2_1_Prompt_Enhancer.pyd

Author: Compatible Implementation
"""

import torch
from PIL import Image
import base64
import io
import json
import httpx
from typing import Optional, Tuple, Union

# =============================================================================
# System Prompt (extracted from .pyd)
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
# Model Families (extracted from .pyd)
# =============================================================================

MODEL_FAMILIES = {
    "qwen2.5-vl": "Qwen2.5-VL",
    "qwen2-vl": "Qwen2-VL",
    "qwen-vl": "Qwen-VL",
    "qwen2.5": "Qwen2.5",
    "qwen2": "Qwen2",
    "qwen": "Qwen",
}

OFFICIAL_PE_CHOICES = ["wanx", "qwen-vl"]  # Official Prompt Enhancement

# =============================================================================
# Helper Functions (extracted from .pyd)
# =============================================================================

def _image_to_jpeg_base64(image: Image.Image) -> str:
    """Convert PIL Image to JPEG base64 string."""
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=95)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def _resize_image_tensor_max_pixels(
    image_tensor: torch.Tensor,
    max_pixels: int = 1280 * 1280
) -> torch.Tensor:
    """Resize image tensor to not exceed max pixels while maintaining aspect ratio."""
    _, h, w = image_tensor.shape[-3:]
    pixels = h * w
    
    if pixels <= max_pixels:
        return image_tensor
    
    scale = (max_pixels / pixels) ** 0.5
    new_h = int(h * scale)
    new_w = int(w * scale)
    
    # Use PIL for resizing
    pil_image = Image.fromarray((image_tensor.cpu().numpy() * 255).astype("uint8"))
    pil_image = pil_image.resize((new_w, new_h), Image.LANCZOS)
    
    return torch.from_numpy(np.array(pil_image) / 255.0)


def _repair_mojibake(text: str) -> str:
    """Repair common mojibake (encoding errors) in text."""
    replacements = {
        "\\u00e2\\u20ac\\u201e": '"',
        "\\u00e2\\u20ac\\u201c": '"',
        "\\u00e2\\u20ac\\u201d": '"',
        "\\u00e2\\u20ac\\u2122": "'",
        "\\u00c2\\u00a0": " ",
    }
    for broken, fixed in replacements.items():
        text = text.replace(broken, fixed)
    return text


def _clean_think_blocks(text: str) -> str:
    """Remove think/chain-of-thought blocks from response."""
    import re
    # Remove content between think tags if any
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    # Remove common thinking phrases
    thinking_phrases = [
        "The task:",
        "Wait, let me think",
        "I need to",
        "Let me think",
    ]
    for phrase in thinking_phrases:
        if phrase in text:
            # Find the first period after the phrase and cut from there
            idx = text.find(phrase)
            period_idx = text.find(".", idx)
            if period_idx != -1:
                text = text[period_idx + 1:].strip()
    return text.strip()


def _strip_code_fence(text: str) -> str:
    """Remove markdown code fences from text."""
    import re
    text = re.sub(r"^```(?:json|prompt|text)?\n?", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n?```$", "", text)
    return text.strip()


def _extract_response_text(response: str) -> str:
    """Extract and clean the response text."""
    text = _repair_mojibake(response)
    text = _clean_think_blocks(text)
    text = _strip_code_fence(text)
    return text


# =============================================================================
# API Request Functions (extracted from .pyd)
# =============================================================================

def _build_api_input(
    model: str,
    system_prompt: str,
    user_prompt: str,
    image_b64: Optional[str] = None,
    temperature: float = 1.0,
    max_tokens: int = 2000,
) -> dict:
    """Build API request payload."""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": []},
    ]
    
    if image_b64:
        messages[1]["content"] = [
            {"type": "text", "text": user_prompt},
            {"type": "image", "image": f"data:image/jpeg;base64,{image_b64}"},
        ]
    else:
        messages[1]["content"] = user_prompt
    
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    
    return payload


async def _request_api(
    api_url: str,
    api_key: str,
    payload: dict,
    timeout: int = 120,
) -> str:
    """Make API request and return response text."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(api_url, json=payload, headers=headers)
        response.raise_for_status()
        result = response.json()
    
    # Extract text from response based on common API formats
    if "choices" in result:
        return result["choices"][0]["message"]["content"]
    elif "output" in result:
        return result["output"]
    elif "text" in result:
        return result["text"]
    else:
        return str(result)


# =============================================================================
# Qwen Prompt Enhancer Node
# =============================================================================

class TEQwenImage21PromptEnhancer:
    """
    Qwen Image 2.1 Prompt Enhancer Node
    
    Uses Qwen multimodal model to enhance prompts based on image content.
    
    Extracted from: TE_Qwen_Image_2_1_Prompt_Enhancer.pyd
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE", {"tooltip": "Input image for context"}),
                "text": ("STRING", {
                    "multiline": True,
                    "tooltip": "Prompt text to enhance"
                }),
                "model_family": (list(MODEL_FAMILIES.keys()), {
                    "default": "qwen2.5-vl",
                    "tooltip": "Qwen model family"
                }),
                "api_url": ("STRING", {"tooltip": "API endpoint URL"}),
                "api_key": ("STRING", {"tooltip": "API key"}),
            },
            "optional": {
                "temperature": ("FLOAT", {
                    "default": 1.0,
                    "min": 0.0,
                    "max": 2.0,
                    "step": 0.1,
                }),
                "max_tokens": ("INT", {
                    "default": 2000,
                    "min": 100,
                    "max": 8000,
                }),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("enhanced_prompt",)
    FUNCTION = "enhance_prompt"
    CATEGORY = "prompt/enhance"
    OUTPUT_NODE = True

    # Enable concurrent execution
    TE_MAN_CONCURRENT_ELIGIBLE = True

    def enhance_prompt(
        self,
        image: torch.Tensor,
        text: str,
        model_family: str,
        api_url: str,
        api_key: str,
        temperature: float = 1.0,
        max_tokens: int = 2000,
    ) -> Tuple[str]:
        """
        Enhance prompt using Qwen multimodal model.
        
        Args:
            image: Image tensor [B, H, W, C] in range [0, 1]
            text: Original prompt text
            model_family: Qwen model family to use
            api_url: API endpoint URL
            api_key: API key
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
        
        Returns:
            Enhanced prompt text
        """
        import numpy as np
        
        # Convert image tensor to PIL Image
        if image.dim() == 4:
            image = image[0]  # Take first frame if batched
        
        image_np = (image.cpu().numpy() * 255).astype("uint8")
        pil_image = Image.fromarray(image_np)
        
        # Resize if too large
        if pil_image.width * pil_image.height > 1280 * 1280:
            pil_image.thumbnail((1280, 1280), Image.LANCZOS)
        
        # Convert to base64
        image_b64 = _image_to_jpeg_base64(pil_image)
        
        # Build system prompt with user text
        system_prompt = SYSTEM_PROMPT
        
        # Build user prompt
        user_prompt = f"Enhance this prompt based on the image: {text}"
        
        # Build API payload
        payload = _build_api_input(
            model=MODEL_FAMILIES.get(model_family, model_family),
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            image_b64=image_b64,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        
        # Make API request
        import asyncio
        response = asyncio.get_event_loop().run_until_complete(
            _request_api(api_url, api_key, payload)
        )
        
        # Extract and clean response
        enhanced = _extract_response_text(response)
        
        return (enhanced,)


# =============================================================================
# Official Storage Nodes (extracted from .pyd)
# =============================================================================

class TEQwenImage21OfficialStorage:
    """
    Storage node for official API keys and URLs.
    """
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "api_key": ("STRING", {"tooltip": "Official API key"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("api_url", "api_key")
    FUNCTION = "load"
    CATEGORY = "model/prompt"

    def load(self, api_key: str) -> Tuple[str, str]:
        # Official API endpoint (extracted from .pyd)
        official_url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
        return (official_url, api_key)


class TEQwenImage21LocalStorage:
    """
    Storage node for local/custom API endpoints.
    """
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "api_url": ("STRING", {"tooltip": "Custom API URL"}),
                "api_key": ("STRING", {"tooltip": "API key"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("api_url", "api_key")
    FUNCTION = "load"
    CATEGORY = "model/prompt"

    def load(self, api_url: str, api_key: str) -> Tuple[str, str]:
        return (api_url, api_key)


# =============================================================================
# Node Mappings for ComfyUI
# =============================================================================

NODE_CLASS_MAPPINGS = {
    "TEQwenImage21PromptEnhancer": TEQwenImage21PromptEnhancer,
    "TEQwenImage21OfficialStorage": TEQwenImage21OfficialStorage,
    "TEQwenImage21LocalStorage": TEQwenImage21LocalStorage,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "TEQwenImage21PromptEnhancer": "Qwen Image 2.1 Prompt Enhancer",
    "TEQwenImage21OfficialStorage": "Qwen Official Storage",
    "TEQwenImage21LocalStorage": "Qwen Local Storage",
}


# =============================================================================
# Entry Point
# =============================================================================

if __name__ == "__main__":
    # Test code
    print("TE Qwen Image 2.1 Prompt Enhancer Node")
    print("=" * 50)
    print("System Prompt (truncated):")
    print(SYSTEM_PROMPT[:200] + "...")
    print("\nAvailable Model Families:")
    for key, name in MODEL_FAMILIES.items():
        print(f"  - {key}: {name}")
