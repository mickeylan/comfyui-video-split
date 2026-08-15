"""
文字/字幕处理节点
"""
import torch
import numpy as np
from PIL import Image, ImageColor, ImageDraw, ImageFont
import os
import platform
import folder_paths


# ============================================================
# 中文字体加载辅助函数
# ============================================================

def _is_allowed_font_path(font_path):
    """
    检查字体路径是否在允许的目录内（系统字体目录或 ComfyUI input 目录）。

    Args:
        font_path: 要检查的字体路径

    Returns:
        bool: 路径是否允许
    """
    if not font_path or not os.path.isabs(font_path):
        return False

    # 系统字体目录
    system = platform.system()
    system_font_dirs = []
    if system == "Windows":
        system_font_dirs = ["C:/Windows/Fonts"]
    elif system == "Darwin":
        system_font_dirs = ["/System/Library/Fonts", "/Library/Fonts"]
    elif system == "Linux":
        system_font_dirs = ["/usr/share/fonts", "/usr/local/share/fonts"]

    # ComfyUI input 目录
    try:
        input_dir = folder_paths.get_input_directory()
        system_font_dirs.append(input_dir)
    except Exception:
        pass

    # 检查路径是否在允许的目录内
    for allowed_dir in system_font_dirs:
        if os.path.isdir(allowed_dir):
            if folder_paths.is_within_directory(os.path.abspath(allowed_dir), os.path.abspath(font_path)):
                return True

    return False


def get_chinese_font(font_size=32, font_path=None):
    """
    获取支持中文的字体。

    Args:
        font_size: 字体大小
        font_path: 用户指定的字体路径（必须在系统字体目录或 ComfyUI input 目录内）

    Returns:
        PIL ImageFont 对象
    """
    # 如果用户指定了字体路径，验证并尝试加载
    if font_path and _is_allowed_font_path(font_path) and os.path.exists(font_path):
        try:
            return ImageFont.truetype(font_path, font_size)
        except Exception as e:
            print(f"[Video Split] Failed to load font {font_path}: {e}")

    # 尝试系统自带的中文字体
    system = platform.system()

    chinese_fonts = []

    if system == "Windows":
        # Windows 系统中文字体
        chinese_fonts = [
            "C:/Windows/Fonts/msyh.ttc",      # 微软雅黑
            "C:/Windows/Fonts/msyhbd.ttc",    # 微软雅黑粗体
            "C:/Windows/Fonts/simhei.ttf",    # 黑体
            "C:/Windows/Fonts/simsun.ttc",    # 宋体
            "C:/Windows/Fonts/simkai.ttf",    # 楷体
            "C:/Windows/Fonts/STZHONGS.TTF",  # 华文中宋
            "C:/Windows/Fonts/STFANGSO.TTF",  # 华文仿宋
        ]
    elif system == "Darwin":  # macOS
        chinese_fonts = [
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/STHeiti Light.ttc",
            "/System/Library/Fonts/Hiragino Sans GB.ttc",
        ]
    elif system == "Linux":
        chinese_fonts = [
            "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
            "/usr/share/fonts/truetype/arphic/uming.ttc",
        ]

    # 尝试加载系统中文字体
    for font_file in chinese_fonts:
        if os.path.exists(font_file):
            try:
                return ImageFont.truetype(font_file, font_size)
            except Exception as e:
                continue

    # 如果都失败了，返回默认字体并警告
    print("[Video Split] Warning: No Chinese font found. Chinese text may not display correctly.")
    print("[Video Split] Please specify a Chinese font path, e.g.: C:/Windows/Fonts/msyh.ttc")
    return ImageFont.load_default()


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

        def process_chunk(chunk):
            result_frames = []

            # 使用支持中文的字体
            font = get_chinese_font(font_size, font_path)

            for i in range(chunk.shape[0]):
                # 转换为 PIL Image
                frame = chunk[i].cpu().numpy()
                frame = (frame * 255).astype('uint8')
                pil_image = Image.fromarray(frame)

                # 创建绘图对象
                draw = ImageDraw.Draw(pil_image)

                # 解析颜色
                fill_color = font_color if font_color else "#FFFFFF"
                stroke_fill = stroke_color if stroke_color else "#000000"

                # 绘制文字
                draw.text(
                    (x, y),
                    text,
                    font=font,
                    fill=fill_color,
                    stroke_width=stroke_width,
                    stroke_fill=stroke_fill
                )

                # 转回张量，保留输入的 device/dtype
                frame_array = np.array(pil_image).astype(np.float32) / 255.0
                frame_tensor = torch.from_numpy(frame_array).to(device=chunk.device, dtype=chunk.dtype)
                result_frames.append(frame_tensor)

            return torch.stack(result_frames)

        result = torch.cat([process_chunk(images[start:start + 32]) for start in range(0, images.shape[0], 32)])
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

        animation_frames = int(animation_duration * fps)

        def process_chunk(chunk, frame_offset):
            result_frames = []
            # 使用支持中文的字体
            font = get_chinese_font(font_size)

            for i in range(chunk.shape[0]):
                frame = chunk[i].cpu().numpy()
                frame = (frame * 255).astype('uint8')
                pil_image = Image.fromarray(frame)
                draw = ImageDraw.Draw(pil_image)

                # 分块处理时仍使用整段视频中的绝对帧索引。
                frame_index = frame_offset + i
                progress = min(1.0, frame_index / animation_frames) if animation_frames > 0 else 1.0

                # 根据动画类型生成当前显示的文字
                if animation_type == "typewriter":
                    # 打字机效果：逐字显示
                    char_count = int(len(text) * progress)
                    current_text = text[:char_count]
                    draw.text((x, y), current_text, font=font, fill=font_color)

                elif animation_type == "fade_in":
                    rgba = ImageColor.getrgb(font_color) + (round(progress * 255),)
                    temp_layer = Image.new("RGBA", pil_image.size, (0, 0, 0, 0))
                    ImageDraw.Draw(temp_layer).text((x, y), text, font=font, fill=rgba)
                    pil_image = Image.alpha_composite(pil_image.convert("RGBA"), temp_layer).convert("RGB")
                    # 转回张量，保留输入的 device/dtype
                    frame_array = np.array(pil_image).astype(np.float32) / 255.0
                    frame_tensor = torch.from_numpy(frame_array).to(device=chunk.device, dtype=chunk.dtype)
                    result_frames.append(frame_tensor)
                    continue

                elif animation_type == "slide_in":
                    # 滑入效果：改变位置
                    current_text = text
                    slide_x = int((1 - progress) * 200)  # 从右侧滑入
                    x_pos = x + slide_x
                    draw.text((x_pos, y), current_text, font=font, fill=font_color)
                    # 转回张量，保留输入的 device/dtype
                    frame_array = np.array(pil_image).astype(np.float32) / 255.0
                    frame_tensor = torch.from_numpy(frame_array).to(device=chunk.device, dtype=chunk.dtype)
                    result_frames.append(frame_tensor)
                    continue
                else:
                    draw.text((x, y), text, font=font, fill=font_color)

                # 转回张量，保留输入的 device/dtype
                frame_array = np.array(pil_image).astype(np.float32) / 255.0
                frame_tensor = torch.from_numpy(frame_array).to(device=chunk.device, dtype=chunk.dtype)
                result_frames.append(frame_tensor)

            return torch.stack(result_frames)

        result = torch.cat([
            process_chunk(images[start:start + 32], start)
            for start in range(0, images.shape[0], 32)
        ])
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
        """解析标准 SRT 字幕格式

        标准 SRT 时间码格式: 00:00:00,000 --> 00:00:02,000
        - 小时:分钟:秒,毫秒 (用逗号分隔秒和毫秒)
        """
        subtitles = []
        blocks = srt_content.strip().split('\n\n')

        for block in blocks:
            lines = block.strip().split('\n')
            if len(lines) >= 3:
                try:
                    # 解析时间码
                    time_line = lines[1]
                    start_time, end_time = time_line.split(' --> ')

                    # 转换为毫秒 - 标准 SRT 使用逗号分隔秒和毫秒
                    def time_to_ms(time_str):
                        # 移除可能的空格
                        time_str = time_str.strip()
                        # 分离秒和毫秒（用逗号）
                        if ',' in time_str:
                            seconds_part, ms_part = time_str.split(',')
                        elif '.' in time_str:
                            # 也支持点号作为分隔符
                            seconds_part, ms_part = time_str.split('.')
                        else:
                            seconds_part = time_str
                            ms_part = '0'

                        # 分离时:分:秒
                        h, m, s = seconds_part.split(':')
                        return int(h) * 3600000 + int(m) * 60000 + int(s) * 1000 + int(ms_part)

                    start_ms = time_to_ms(start_time)
                    end_ms = time_to_ms(end_time)

                    # 解析文字
                    text = '\n'.join(lines[2:])

                    subtitles.append({
                        'start_ms': start_ms,
                        'end_ms': end_ms,
                        'text': text
                    })
                except (ValueError, IndexError, AttributeError) as e:
                    # 只捕获特定异常，不使用裸 except
                    print(f"[Video Split] Failed to parse SRT block: {e}")
                    continue

        return subtitles

    def execute(self, images: torch.Tensor, srt_content: str, fps: float,
                font_size: int, y_offset: int, font_color: str):

        # 解析字幕
        subtitles = self.parse_srt(srt_content) if srt_content else []

        if not subtitles:
            return (images,)

        height = images.shape[1]
        width = images.shape[2]

        # 使用支持中文的字体
        font = get_chinese_font(font_size)

        def process_chunk(chunk, frame_offset):
            result_frames = []

            for i in range(chunk.shape[0]):
                frame = chunk[i].cpu().numpy()
                frame = (frame * 255).astype('uint8')
                pil_image = Image.fromarray(frame)
                draw = ImageDraw.Draw(pil_image)

                # 分块处理时仍使用整段视频中的绝对帧索引。
                current_ms = int((frame_offset + i) * 1000 / fps)

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

                # 转回张量，保留输入的 device/dtype
                frame_array = np.array(pil_image).astype(np.float32) / 255.0
                frame_tensor = torch.from_numpy(frame_array).to(device=chunk.device, dtype=chunk.dtype)
                result_frames.append(frame_tensor)

            return torch.stack(result_frames)

        result = torch.cat([
            process_chunk(images[start:start + 32], start)
            for start in range(0, images.shape[0], 32)
        ])
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

        # 直接处理，不调用 TextOverlay（因为 TextOverlay 不支持 anchor）
        # 使用支持中文的字体
        font = get_chinese_font(font_size)

        def process_chunk(chunk):
            result_frames = []
            for i in range(chunk.shape[0]):
                frame = chunk[i].cpu().numpy()
                frame = (frame * 255).astype('uint8')
                pil_image = Image.fromarray(frame)
                draw = ImageDraw.Draw(pil_image)

                # 使用 anchor 进行居中对齐
                draw.text((x, y), text, font=font, fill=font_color, anchor=anchor)

                # 转回张量，保留输入的 device/dtype
                frame_array = np.array(pil_image).astype(np.float32) / 255.0
                frame_tensor = torch.from_numpy(frame_array).to(device=chunk.device, dtype=chunk.dtype)
                result_frames.append(frame_tensor)

            return torch.stack(result_frames)

        result = torch.cat([process_chunk(images[start:start + 32]) for start in range(0, images.shape[0], 32)])
        return (result,)


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
