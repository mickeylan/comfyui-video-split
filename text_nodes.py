"""
文字/字幕处理节点
"""
import torch
import numpy as np
import math
from PIL import Image, ImageDraw, ImageFont
import os


# ============================================================
# Text Overlay - 文字叠加
# ============================================================

class TextOverlay:
    """
    在视频帧上叠加文字。
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "帧张量"}),
                "text": ("STRING", {"default": "文字内容", "multiline": True, "tooltip": "要显示的文字"}),
                "x": ("INT", {"default": 50, "min": 0, "max": 4096, "tooltip": "X位置"}),
                "y": ("INT", {"default": 50, "min": 0, "max": 4096, "tooltip": "Y位置"}),
                "font_size": ("INT", {"default": 32, "min": 8, "max": 200, "tooltip": "字体大小"}),
                "font_color": ("STRING", {"default": "#FFFFFF", "tooltip": "字体颜色（十六进制）"}),
                "font_path": ("STRING", {"default": "", "tooltip": "字体文件路径（留空使用默认字体）"}),
                "stroke_width": ("INT", {"default": 0, "min": 0, "max": 10, "tooltip": "描边宽度"}),
                "stroke_color": ("STRING", {"default": "#000000", "tooltip": "描边颜色"}),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    FUNCTION = "execute"
    CATEGORY = "video/text"

    def execute(self, images: torch.Tensor, text: str, x: int, y: int,
                font_size: int, font_color: str, font_path: str,
                stroke_width: int, stroke_color: str):
        
        total_frames = images.shape[0]
        height = images.shape[1]
        width = images.shape[2]
        
        # 分块处理
        def process_chunk(chunk):
            result_frames = []
            
            # 加载字体
            try:
                if font_path and os.path.exists(font_path):
                    font = ImageFont.truetype(font_path, font_size)
                else:
                    # 尝试加载系统字体
                    font = ImageFont.load_default()
            except:
                font = ImageFont.load_default()
            
            for i in range(chunk.shape[0]):
                # 转换为 PIL Image
                frame = chunk[i].cpu().numpy()
                frame = (frame * 255).astype('uint8')
                pil_image = Image.fromarray(frame)
                
                # 创建绘图对象
                draw = ImageDraw.Draw(pil_image)
                
                # 解析颜色
                try:
                    fill_color = font_color
                    stroke_fill = stroke_color
                except:
                    fill_color = "#FFFFFF"
                    stroke_fill = "#000000"
                
                # 绘制文字
                draw.text(
                    (x, y),
                    text,
                    font=font,
                    fill=fill_color,
                    stroke_width=stroke_width,
                    stroke_fill=stroke_fill
                )
                
                # 转回张量
                frame_array = np.array(pil_image).astype(np.float32) / 255.0
                result_frames.append(torch.from_numpy(frame_array))
            
            return torch.stack(result_frames)
        
        # 处理
        result = process_chunk(images)
        
        return (result,)


# ============================================================
# Text Animation - 文字动画（打字机效果）
# ============================================================

class TextAnimation:
    """
    文字动画效果（打字机、淡入等）。
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "帧张量"}),
                "text": ("STRING", {"default": "文字内容", "multiline": True, "tooltip": "要显示的文字"}),
                "x": ("INT", {"default": 50, "min": 0, "max": 4096, "tooltip": "X位置"}),
                "y": ("INT", {"default": 50, "min": 0, "max": 4096, "tooltip": "Y位置"}),
                "font_size": ("INT", {"default": 32, "min": 8, "max": 200, "tooltip": "字体大小"}),
                "animation_type": (["typewriter", "fade_in", "slide_in"], {"default": "typewriter", "tooltip": "动画类型"}),
                "animation_duration": ("FLOAT", {"default": 2.0, "min": 0.1, "max": 30.0, "tooltip": "动画时长（秒）"}),
                "fps": ("FLOAT", {"default": 24.0, "tooltip": "视频帧率"}),
                "font_color": ("STRING", {"default": "#FFFFFF", "tooltip": "字体颜色"}),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    FUNCTION = "execute"
    CATEGORY = "video/text"

    def execute(self, images: torch.Tensor, text: str, x: int, y: int,
                font_size: int, animation_type: str, animation_duration: float,
                fps: float, font_color: str):
        
        total_frames = images.shape[0]
        animation_frames = int(animation_duration * fps)
        
        # 分块处理
        def process_chunk(chunk):
            result_frames = []
            font = ImageFont.load_default()
            
            for i in range(chunk.shape[0]):
                frame = chunk[i].cpu().numpy()
                frame = (frame * 255).astype('uint8')
                pil_image = Image.fromarray(frame)
                draw = ImageDraw.Draw(pil_image)
                
                # 计算动画进度
                progress = min(1.0, i / animation_frames) if animation_frames > 0 else 1.0
                
                # 根据动画类型生成当前显示的文字
                if animation_type == "typewriter":
                    # 打字机效果：逐字显示
                    char_count = int(len(text) * progress)
                    current_text = text[:char_count]
                
                elif animation_type == "fade_in":
                    # 淡入效果：改变透明度
                    current_text = text
                    # 这里可以通过调整颜色透明度实现
                
                elif animation_type == "slide_in":
                    # 滑入效果：改变位置
                    current_text = text
                    slide_x = int((1 - progress) * 200)  # 从右侧滑入
                    x_pos = x + slide_x
                    draw.text((x_pos, y), current_text, font=font, fill=font_color)
                    result_frames.append(torch.from_numpy(np.array(pil_image).astype(np.float32) / 255.0))
                    continue
                
                # 绘制文字
                draw.text((x, y), current_text, font=font, fill=font_color)
                
                # 转回张量
                frame_array = np.array(pil_image).astype(np.float32) / 255.0
                result_frames.append(torch.from_numpy(frame_array))
            
            return torch.stack(result_frames)
        
        result = process_chunk(images)
        
        return (result,)


# ============================================================
# Subtitle Import - 导入 SRT 字幕
# ============================================================

class SubtitleImport:
    """
    导入 SRT 字幕文件并显示在视频上。
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "帧张量"}),
                "srt_content": ("STRING", {"default": "", "multiline": True, "tooltip": "SRT字幕内容"}),
                "fps": ("FLOAT", {"default": 24.0, "tooltip": "视频帧率"}),
                "font_size": ("INT", {"default": 28, "min": 8, "max": 100, "tooltip": "字体大小"}),
                "y_offset": ("INT", {"default": -50, "min": -1000, "max": 1000, "tooltip": "Y偏移（负数表示底部）"}),
                "font_color": ("STRING", {"default": "#FFFFFF", "tooltip": "字体颜色"}),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    FUNCTION = "execute"
    CATEGORY = "video/text"

    def parse_srt(self, srt_content: str):
        """解析 SRT 字幕格式"""
        subtitles = []
        blocks = srt_content.strip().split('\n\n')
        
        for block in blocks:
            lines = block.strip().split('\n')
            if len(lines) >= 3:
                try:
                    # 解析时间码
                    time_line = lines[1]
                    start_time, end_time = time_line.split(' --> ')
                    
                    # 转换为毫秒
                    def time_to_ms(time_str):
                        h, m, s = time_str.replace(',', ':').split(':')
                        return int(h) * 3600000 + int(m) * 60000 + int(float(s) * 1000)
                    
                    start_ms = time_to_ms(start_time)
                    end_ms = time_to_ms(end_time)
                    
                    # 解析文字
                    text = '\n'.join(lines[2:])
                    
                    subtitles.append({
                        'start_ms': start_ms,
                        'end_ms': end_ms,
                        'text': text
                    })
                except:
                    continue
        
        return subtitles

    def execute(self, images: torch.Tensor, srt_content: str, fps: float,
                font_size: int, y_offset: int, font_color: str):
        
        # 解析字幕
        subtitles = self.parse_srt(srt_content) if srt_content else []
        
        if not subtitles:
            return (images,)
        
        total_frames = images.shape[0]
        height = images.shape[1]
        width = images.shape[2]
        
        font = ImageFont.load_default()
        
        def process_chunk(chunk):
            result_frames = []
            
            for i in range(chunk.shape[0]):
                frame = chunk[i].cpu().numpy()
                frame = (frame * 255).astype('uint8')
                pil_image = Image.fromarray(frame)
                draw = ImageDraw.Draw(pil_image)
                
                # 计算当前帧时间（毫秒）
                current_ms = int(i * 1000 / fps)
                
                # 查找当前应显示的字幕
                current_text = ""
                for sub in subtitles:
                    if sub['start_ms'] <= current_ms <= sub['end_ms']:
                        current_text = sub['text']
                        break
                
                # 绘制字幕
                if current_text:
                    # 计算 Y 位置
                    y_pos = height + y_offset - font_size if y_offset < 0 else y_offset
                    x_pos = width // 2
                    
                    draw.text(
                        (x_pos, y_pos),
                        current_text,
                        font=font,
                        fill=font_color,
                        anchor="mm"  # 居中对齐
                    )
                
                frame_array = np.array(pil_image).astype(np.float32) / 255.0
                result_frames.append(torch.from_numpy(frame_array))
            
            return torch.stack(result_frames)
        
        result = process_chunk(images)
        
        return (result,)


# ============================================================
# Text Position Preset - 文字位置预设
# ============================================================

class TextPositionPreset:
    """
    文字位置预设（标题、底部字幕、左下角等）。
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "帧张量"}),
                "text": ("STRING", {"default": "文字内容", "multiline": True, "tooltip": "文字"}),
                "position": (["top_center", "top_left", "top_right", 
                              "center", "bottom_center", "bottom_left", "bottom_right"],
                    {"default": "bottom_center", "tooltip": "位置预设"}),
                "font_size": ("INT", {"default": 32, "min": 8, "max": 200}),
                "font_color": ("STRING", {"default": "#FFFFFF"}),
                "margin": ("INT", {"default": 50, "min": 0, "max": 500, "tooltip": "边距"}),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    FUNCTION = "execute"
    CATEGORY = "video/text"

    def execute(self, images: torch.Tensor, text: str, position: str,
                font_size: int, font_color: str, margin: int):
        
        height = images.shape[1]
        width = images.shape[2]
        
        # 计算位置
        positions = {
            "top_center": (width // 2, margin, "mm"),
            "top_left": (margin, margin, "lt"),
            "top_right": (width - margin, margin, "rt"),
            "center": (width // 2, height // 2, "mm"),
            "bottom_center": (width // 2, height - margin, "mm"),
            "bottom_left": (margin, height - margin, "lb"),
            "bottom_right": (width - margin, height - margin, "rb"),
        }
        
        x, y, anchor = positions.get(position, (width // 2, height - margin, "mm"))
        
        # 使用 TextOverlay
        overlay = TextOverlay()
        return overlay.execute(images, text, x, y, font_size, font_color, "", 0, "#000000")


# ============================================================
# Node Mappings
# ============================================================

TEXT_NODE_CLASS_MAPPINGS = {
    "TextOverlay": TextOverlay,
    "TextAnimation": TextAnimation,
    "SubtitleImport": SubtitleImport,
    "TextPositionPreset": TextPositionPreset,
}

TEXT_NODE_DISPLAY_NAME_MAPPINGS = {
    "TextOverlay": "Text Overlay",
    "TextAnimation": "Text Animation",
    "SubtitleImport": "Subtitle Import",
    "TextPositionPreset": "Text Position Preset",
}