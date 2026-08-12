# ComfyUI Video Split 使用文档

> 版本：v0.7.0 | 最后更新：2024年

---

## 目录

1. [安装与依赖](#1-安装与依赖)
2. [节点总览](#2-节点总览)
3. [核心分段节点](#3-核心分段节点)
4. [基础编辑节点](#4-基础编辑节点)
5. [剪映功能节点](#5-剪映功能节点)
6. [音频处理节点](#6-音频处理节点)
7. [文字/字幕节点](#7-文字字幕节点)
8. [滤镜/调色节点](#8-滤镜调色节点)
9. [转场效果节点](#9-转场效果节点)
10. [特效节点](#10-特效节点)
11. [AI 辅助节点](#11-ai-辅助节点)
12. [批量渲染节点](#12-批量渲染节点)
13. [工作流示例](#13-工作流示例)
14. [常见问题](#14-常见问题)

---

## 1. 安装与依赖

### 安装

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/mickeylan/comfyui-video-split.git
```

### 依赖

**必需依赖：**
```bash
pip install av          # 音频处理
pip install Pillow      # 文字渲染
```

**可选依赖：**
```bash
pip install edge-tts        # 自动配音
pip install openai-whisper  # 自动字幕
```

---

## 2. 节点总览

| 分类 | 节点数 | 说明 |
|------|--------|------|
| 核心分段 | 5 | 视频分割、合并、循环收集 |
| 基础编辑 | 6 | 帧提取、裁剪、缩放 |
| 剪映功能 | 9 | 变速、倒放、拼接、淡入淡出 |
| 音频处理 | 10 | 提取、合并、音量、多轨混合 |
| 文字/字幕 | 4 | 文字叠加、动画、SRT导入 |
| 滤镜/调色 | 4 | 亮度、对比度、预设滤镜 |
| 转场效果 | 4 | 滑动、缩放、擦除、溶解 |
| 特效 | 4 | 抠像、背景替换 |
| AI 辅助 | 4 | 自动字幕、自动配音 |
| 批量渲染 | 5 | 队列管理、批量处理 |

**总计：55 个节点**

---

## 3. 核心分段节点

### 3.1 Video Segment Info

**功能：** 计算视频分段信息，供循环节点使用。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| images | IMAGE | - | 帧张量（连接 VHS Load Video 的 image 输出） |
| fps | FLOAT | 24.0 | 视频帧率 |
| split_mode | 选择 | by_duration | 分段模式：by_duration（按时长）或 by_frames（按帧数） |
| segment_duration | FLOAT | 5.0 | 每段时长（秒），split_mode=by_duration 时使用 |
| segment_frames | INT | 120 | 每段帧数，split_mode=by_frames 时使用 |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| total_segments | INT | 总分段数 |
| total_frames | INT | 视频总帧数 |
| frames_per_segment | INT | 每段帧数 |

**使用场景：** 配合 forLoopStart 节点，计算循环次数。

---

### 3.2 Get Video Segment

**功能：** 按索引提取单个视频分段。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| images | IMAGE | - | 帧张量（与 VideoSegmentInfo 同源） |
| segment_index | INT | 0 | 分段索引（从0开始），连接 forLoopStart 的 index |
| frames_per_segment | INT | 120 | 每段帧数，来自 VideoSegmentInfo |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| segment_images | IMAGE | 当前分段的帧张量 |
| segment_frame_count | INT | 当前分段帧数 |
| start_frame | INT | 起始帧索引 |

**使用场景：** 在循环中逐段处理视频。

---

### 3.3 Video Split (Multiple)

**功能：** 一次性分割视频为所有分段。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| images | IMAGE | - | 帧张量 |
| split_mode | 选择 | by_duration | 分段模式 |
| fps | FLOAT | 24.0 | 视频帧率 |
| segment_duration | FLOAT | 5.0 | 每段时长（秒） |
| segment_frames | INT | 120 | 每段帧数 |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| segments | IMAGE (列表) | 分段列表 |
| total_segments | INT | 总分段数 |

**使用场景：** 不需要循环，一次性获取所有分段。

---

### 3.4 Merge Video Segments

**功能：** 合并多个视频分段。

**输入：**
| 参数 | 类型 | 说明 |
|------|------|------|
| segments | IMAGE (列表) | 要合并的帧张量分段 |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| merged_images | IMAGE | 合并后的帧张量 |
| total_frames | INT | 总帧数 |

**使用场景：** 将处理后的分段合并为完整视频。

---

### 3.5 Image Collect

**功能：** 在循环中收集图像帧。

**输入：**
| 参数 | 类型 | 说明 |
|------|------|------|
| new_images | IMAGE | 当前迭代要添加的图像帧 |
| images | IMAGE (可选) | 之前累积的图像帧，第一次迭代留空 |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| accumulated | IMAGE | 累积的帧张量 |
| total_frames | INT | 当前总帧数 |

**使用场景：** 在循环中逐步收集处理后的帧。

**⚠️ 重要：** 必须连接 `forLoopStart.value1` 到 `images`，不是 `initial_value1`！

---

## 4. 基础编辑节点

### 4.1 Get Video Frame

**功能：** 获取视频的单帧图像。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| images | IMAGE | - | 帧张量 |
| frame_index | INT | 0 | 帧索引（支持负索引，-1 = 最后一帧） |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| frame | IMAGE | 单帧图像 |

---

### 4.2 Get Video Frames Range

**功能：** 获取视频指定范围的帧。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| images | IMAGE | - | 帧张量 |
| start_frame | INT | 0 | 起始帧索引 |
| end_frame | INT | -1 | 结束帧索引（-1 = 到最后一帧） |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| frames | IMAGE | 帧范围张量 |
| frame_count | INT | 帧数 |

---

### 4.3 Video Crop

**功能：** 视频裁剪（上下左右）。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| images | IMAGE | - | 帧张量 |
| crop_top | INT | 0 | 顶部裁剪像素 |
| crop_bottom | INT | 0 | 底部裁剪像素 |
| crop_left | INT | 0 | 左侧裁剪像素 |
| crop_right | INT | 0 | 右侧裁剪像素 |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| cropped_images | IMAGE | 裁剪后的帧张量 |
| new_height | INT | 新高度 |
| new_width | INT | 新宽度 |

---

### 4.4 Image To Video

**功能：** 将单张图片转换为视频（复制帧）。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| image | IMAGE | - | 单张图片 |
| frame_count | INT | 30 | 输出帧数 |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| video | IMAGE | 视频帧张量 |

---

### 4.5 Video Scale

**功能：** 视频缩放到目标分辨率。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| images | IMAGE | - | 帧张量 |
| width | INT | 1920 | 目标宽度 |
| height | INT | 1080 | 目标高度 |
| method | 选择 | bilinear | 缩放方法：nearest-exact, bilinear, bicubic, area, bicubic-lanczos |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| scaled_images | IMAGE | 缩放后的帧张量 |

---

### 4.6 Video Info

**功能：** 获取视频信息。

**输入：**
| 参数 | 类型 | 说明 |
|------|------|------|
| images | IMAGE | 帧张量 |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| total_frames | INT | 总帧数 |
| height | INT | 高度 |
| width | INT | 宽度 |
| channels | INT | 通道数 |

---

## 5. 剪映功能节点

### 5.1 Video Reverse

**功能：** 视频倒放。

**输入：**
| 参数 | 类型 | 说明 |
|------|------|------|
| images | IMAGE | 帧张量 |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| reversed_images | IMAGE | 倒放后的帧张量 |

**使用场景：** 回忆镜头、特效。

---

### 5.2 Video Resample

**功能：** 帧率转换。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| images | IMAGE | - | 帧张量 |
| source_fps | FLOAT | 24.0 | 原始帧率 |
| target_fps | FLOAT | 30.0 | 目标帧率 |
| mode | 选择 | blend | drop（抽帧）/ duplicate（复制）/ blend（混合） |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| resampled_images | IMAGE | 转换后的帧 |
| new_frame_count | INT | 新帧数 |

**使用场景：** 调整视频流畅度。

---

### 5.3 Video Sample Frames

**功能：** 抽帧提取（每隔N帧取1帧）。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| images | IMAGE | - | 帧张量 |
| sample_interval | INT | 2 | 采样间隔（每隔N帧取1帧） |
| offset | INT | 0 | 起始偏移帧 |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| sampled_images | IMAGE | 采样后的帧 |
| frame_count | INT | 帧数 |

**使用场景：** 延时摄影效果。

---

### 5.4 Video Time Remap

**功能：** 时间重映射（变速播放）。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| images | IMAGE | - | 帧张量 |
| speed | FLOAT | 1.0 | 播放速度（0.5=慢放2倍，2.0=快放2倍） |
| mode | 选择 | blend | drop/duplicate/blend |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| remapped_images | IMAGE | 重映射后的帧 |
| new_frame_count | INT | 新帧数 |

**使用场景：** 快动作、慢动作。

---

### 5.5 Video Concat

**功能：** 视频拼接。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| images1 | IMAGE | - | 视频1 |
| mode | 选择 | sequence | sequence（顺序）/ horizontal（左右）/ vertical（上下） |
| images2-4 | IMAGE (可选) | - | 视频2-4 |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| concatenated_images | IMAGE | 拼接后的帧 |
| total_frames | INT | 总帧数 |

**使用场景：** 画中画、对比。

---

### 5.6 Video Fade

**功能：** 淡入淡出效果。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| images | IMAGE | - | 帧张量 |
| fade_in_frames | INT | 10 | 淡入帧数 |
| fade_out_frames | INT | 10 | 淡出帧数 |
| fade_color | 选择 | black | 淡入淡出颜色：black/white |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| faded_images | IMAGE | 淡入淡出后的帧 |

**使用场景：** 转场效果。

---

### 5.7 Video Overlay

**功能：** 视频叠加。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| background | IMAGE | - | 背景视频 |
| overlay | IMAGE | - | 叠加视频 |
| opacity | FLOAT | 1.0 | 叠加透明度 |
| x | INT | 0 | X位置 |
| y | INT | 0 | Y位置 |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| output_images | IMAGE | 合成后的帧 |

**使用场景：** 水印、特效。

---

### 5.8 Frame Interpolate

**功能：** 帧插值（慢动作）。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| images | IMAGE | - | 帧张量 |
| interpolate_factor | INT | 2 | 插值倍数（2=每帧之间插入1帧） |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| interpolated_images | IMAGE | 插值后的帧 |
| new_frame_count | INT | 新帧数 |

**使用场景：** 慢动作效果。

---

### 5.9 Frame Deduplicate

**功能：** 帧去重。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| images | IMAGE | - | 帧张量 |
| threshold | FLOAT | 0.01 | 相似度阈值（越小越严格） |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| deduplicated_images | IMAGE | 去重后的帧 |
| frame_count | INT | 帧数 |

**使用场景：** 减小视频体积。

---

## 6. 音频处理节点

### 6.1 Audio Extract

**功能：** 从视频文件提取音频。

**输入：**
| 参数 | 类型 | 说明 |
|------|------|------|
| video_path | STRING | 视频文件路径 |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| audio | AUDIO | 音频数据 |
| sample_rate | INT | 采样率 |
| duration_ms | INT | 时长（毫秒） |

---

### 6.2 Audio From Video

**功能：** 从视频张量提取音频。

**输入：**
| 参数 | 类型 | 说明 |
|------|------|------|
| video_path | STRING | 视频文件路径（来自 VHS Load Video） |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| audio | AUDIO | 音频数据 |

---

### 6.3 Audio Merge

**功能：** 音频合并到视频。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| images | IMAGE | - | 视频帧张量 |
| audio | AUDIO | - | 音频数据 |
| fps | FLOAT | 24.0 | 视频帧率 |
| output_path | STRING | output.mp4 | 输出文件路径 |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| video_path | STRING | 输出视频路径 |

---

### 6.4 Audio Volume

**功能：** 音量调节。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| audio | AUDIO | - | 音频数据 |
| volume | FLOAT | 1.0 | 音量倍数（1.0=原始，2.0=两倍） |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| audio | AUDIO | 调节后的音频 |

---

### 6.5 Audio Fade

**功能：** 音频淡入淡出。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| audio | AUDIO | - | 音频数据 |
| fade_in_ms | INT | 500 | 淡入时长（毫秒） |
| fade_out_ms | INT | 500 | 淡出时长（毫秒） |
| sample_rate | INT | 44100 | 采样率 |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| audio | AUDIO | 淡入淡出后的音频 |

---

### 6.6 Audio Info

**功能：** 获取音频信息。

**输入：**
| 参数 | 类型 | 说明 |
|------|------|------|
| audio | AUDIO | 音频数据 |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| channels | INT | 声道数 |
| samples | INT | 采样数 |
| duration_seconds | FLOAT | 时长（秒） |

---

### 6.7 Audio Mix

**功能：** 多音轨混合（BGM + 配音 + 音效）。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| audio1 | AUDIO | - | 音轨1（如配音） |
| volume1 | FLOAT | 1.0 | 音轨1音量 |
| audio2 | AUDIO (可选) | - | 音轨2（如BGM） |
| volume2 | FLOAT | 0.5 | 音轨2音量 |
| audio3 | AUDIO (可选) | - | 音轨3（如音效） |
| volume3 | FLOAT | 1.0 | 音轨3音量 |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| audio | AUDIO | 混合后的音频 |

**使用场景：** BGM + 配音 + 音效混合。

---

### 6.8 Audio Fit To Video

**功能：** 音频时长匹配视频。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| audio | AUDIO | - | 音频数据 |
| target_frames | INT | 100 | 目标帧数 |
| fps | FLOAT | 24.0 | 视频帧率 |
| mode | 选择 | stretch | stretch（变速）/ loop（循环）/ cut（切割） |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| audio | AUDIO | 匹配后的音频 |

**使用场景：** 配音和视频同步。

---

### 6.9 Audio Loop

**功能：** 音频循环到指定时长。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| audio | AUDIO | - | 音频数据 |
| duration_seconds | FLOAT | 60.0 | 目标时长（秒） |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| audio | AUDIO | 循环后的音频 |

**使用场景：** BGM 循环播放。

---

### 6.10 Audio Cut

**功能：** 音频切割。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| audio | AUDIO | - | 音频数据 |
| start_seconds | FLOAT | 0.0 | 起始时间（秒） |
| end_seconds | FLOAT | 10.0 | 结束时间（秒） |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| audio | AUDIO | 切割后的音频 |
| duration | FLOAT | 时长 |

---

## 7. 文字/字幕节点

### 7.1 Text Overlay

**功能：** 文字叠加到视频帧。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| images | IMAGE | - | 帧张量 |
| text | STRING | 文字内容 | 要显示的文字 |
| x | INT | 50 | X位置 |
| y | INT | 50 | Y位置 |
| font_size | INT | 32 | 字体大小 |
| font_color | STRING | #FFFFFF | 字体颜色（十六进制） |
| font_path | STRING | - | 字体文件路径（留空使用默认中文字体） |
| stroke_width | INT | 0 | 描边宽度 |
| stroke_color | STRING | #000000 | 描边颜色 |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| images | IMAGE | 叠加文字后的帧 |

**注意：** 自动检测系统中文字体（Windows: 微软雅黑、黑体、宋体等）

---

### 7.2 Text Animation

**功能：** 文字动画（打字机效果等）。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| images | IMAGE | - | 帧张量 |
| text | STRING | 文字内容 | 要显示的文字 |
| x | INT | 50 | X位置 |
| y | INT | 50 | Y位置 |
| font_size | INT | 32 | 字体大小 |
| animation_type | 选择 | typewriter | 动画类型：typewriter/fade_in/slide_in |
| animation_duration | FLOAT | 2.0 | 动画时长（秒） |
| fps | FLOAT | 24.0 | 视频帧率 |
| font_color | STRING | #FFFFFF | 字体颜色 |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| images | IMAGE | 动画效果后的帧 |

---

### 7.3 Subtitle Import

**功能：** 导入 SRT 字幕。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| images | IMAGE | - | 帧张量 |
| srt_content | STRING | - | SRT字幕内容 |
| fps | FLOAT | 24.0 | 视频帧率 |
| font_size | INT | 28 | 字体大小 |
| y_offset | INT | -50 | Y偏移（负数表示底部） |
| font_color | STRING | #FFFFFF | 字体颜色 |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| images | IMAGE | 叠加字幕后的帧 |

---

### 7.4 Text Position Preset

**功能：** 文字位置预设。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| images | IMAGE | - | 帧张量 |
| text | STRING | 文字内容 | 文字 |
| position | 选择 | bottom_center | 位置预设：top_center/top_left/top_right/center/bottom_center/bottom_left/bottom_right |
| font_size | INT | 32 | 字体大小 |
| font_color | STRING | #FFFFFF | 字体颜色 |
| margin | INT | 50 | 边距 |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| images | IMAGE | 叠加文字后的帧 |

---

## 8. 滤镜/调色节点

### 8.1 Color Adjust

**功能：** 亮度/对比度/饱和度调节。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| images | IMAGE | - | 帧张量 |
| brightness | FLOAT | 0.0 | 亮度调整（-1~1） |
| contrast | FLOAT | 1.0 | 对比度（1.0=原始） |
| saturation | FLOAT | 1.0 | 饱和度（1.0=原始） |
| gamma | FLOAT | 1.0 | Gamma值（1.0=原始） |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| images | IMAGE | 调整后的帧 |

---

### 8.2 Color Temperature

**功能：** 色温调节。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| images | IMAGE | - | 帧张量 |
| temperature | FLOAT | 0.0 | 色温（-1冷色调，1暖色调） |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| images | IMAGE | 调整后的帧 |

---

### 8.3 Color Grade Preset

**功能：** 预设滤镜效果。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| images | IMAGE | - | 帧张量 |
| preset | 选择 | none | 预设效果：none/vintage/cinematic/cold/warm/noir/sepia/vivid/muted/cyberpunk |
| intensity | FLOAT | 1.0 | 效果强度 |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| images | IMAGE | 滤镜效果后的帧 |

---

### 8.4 Vignette

**功能：** 暗角效果。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| images | IMAGE | - | 帧张量 |
| intensity | FLOAT | 0.5 | 暗角强度 |
| radius | FLOAT | 0.8 | 暗角半径 |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| images | IMAGE | 暗角效果后的帧 |

---

## 9. 转场效果节点

### 9.1 Transition Slide

**功能：** 滑动转场。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| images1 | IMAGE | - | 视频1帧张量 |
| images2 | IMAGE | - | 视频2帧张量 |
| transition_frames | INT | 30 | 转场帧数 |
| direction | 选择 | left | 滑动方向：left/right/up/down |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| images | IMAGE | 转场后的帧 |

---

### 9.2 Transition Zoom

**功能：** 缩放转场。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| images1 | IMAGE | - | 视频1帧张量 |
| images2 | IMAGE | - | 视频2帧张量 |
| transition_frames | INT | 30 | 转场帧数 |
| mode | 选择 | cross_zoom | 缩放模式：zoom_in/zoom_out/cross_zoom |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| images | IMAGE | 转场后的帧 |

---

### 9.3 Transition Wipe

**功能：** 擦除转场。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| images1 | IMAGE | - | 视频1帧张量 |
| images2 | IMAGE | - | 视频2帧张量 |
| transition_frames | INT | 30 | 转场帧数 |
| direction | 选择 | left_to_right | 擦除方向：left_to_right/right_to_left/top_to_bottom/bottom_to_top |
| softness | FLOAT | 0.1 | 边缘柔和度 |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| images | IMAGE | 转场后的帧 |

---

### 9.4 Transition Dissolve

**功能：** 溶解转场（淡入淡出混合）。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| images1 | IMAGE | - | 视频1帧张量 |
| images2 | IMAGE | - | 视频2帧张量 |
| transition_frames | INT | 30 | 转场帧数 |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| images | IMAGE | 转场后的帧 |

---

## 10. 特效节点

### 10.1 Background Remove

**功能：** 角色抠像。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| images | IMAGE | - | 帧张量 |
| mode | 选择 | color_key | 抠像模式：color_key/luma_key/edge_detect |
| key_color | STRING | #00FF00 | 色键颜色（十六进制） |
| threshold | FLOAT | 0.3 | 抠像阈值 |
| edge_softness | FLOAT | 0.1 | 边缘柔和度 |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| images | IMAGE | 抠像后的帧 |
| mask | MASK | 抠像 mask |

**使用场景：** AI 生成角色背景不干净。

---

### 10.2 Background Replace

**功能：** 背景替换。

**输入：**
| 参数 | 类型 | 说明 |
|------|------|------|
| foreground | IMAGE | 前景（角色）帧张量 |
| background | IMAGE | 背景帧张量 |
| mask | MASK (可选) | 抠像 mask（来自 Background Remove） |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| images | IMAGE | 合成后的帧 |

**使用场景：** 把角色放到新背景上。

---

### 10.3 Color Key

**功能：** 色键抠像（绿幕/蓝幕）。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| images | IMAGE | - | 帧张量 |
| key_color | 选择 | green | 要移除的颜色：green/blue/red/white/black |
| tolerance | FLOAT | 0.3 | 颜色容差 |
| softness | FLOAT | 0.1 | 边缘柔和度 |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| images | IMAGE | 抠像后的帧 |
| mask | MASK | 抠像 mask |

---

### 10.4 Simple Background Remove

**功能：** 简单背景移除。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| images | IMAGE | - | 帧张量 |
| bg_color | STRING | #FFFFFF | 背景颜色（十六进制） |
| tolerance | FLOAT | 0.1 | 颜色容差 |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| images | IMAGE | 移除背景后的帧 |
| mask | MASK | 抠像 mask |

**使用场景：** 纯色背景快速移除。

---

## 11. AI 辅助节点

### 11.1 Auto Subtitle (Whisper)

**功能：** 自动字幕（使用 Whisper 模型）。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| audio | AUDIO | - | 音频数据 |
| language | 选择 | auto | 语言选择：auto/zh/en/ja/ko |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| srt_content | STRING | SRT字幕内容 |
| segments_json | STRING | 分段信息（JSON格式） |

**依赖：** `pip install openai-whisper`

**使用场景：** 配音后自动生成字幕。

---

### 11.2 Auto Subtitle From File

**功能：** 从音频文件生成字幕。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| audio_path | STRING | - | 音频文件路径 |
| language | 选择 | auto | 语言选择 |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| srt_content | STRING | SRT字幕内容 |

**依赖：** `pip install openai-whisper`

---

### 11.3 Auto TTS (Edge-TTS)

**功能：** 自动配音（使用 Edge-TTS）。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| text | STRING | 你好，这是一个测试。 | 要转换的文字 |
| voice | 选择 | zh-CN-XiaoxiaoNeural | 音色选择 |
| rate | INT | 0 | 语速调整（-50慢，50快） |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| audio | AUDIO | 生成的音频 |
| audio_path | STRING | 音频文件路径 |

**可用音色：**
- zh-CN-XiaoxiaoNeural (晓晓)
- zh-CN-YunxiNeural (云希)
- zh-CN-YunjianNeural (云健)
- zh-CN-XiaoyiNeural (晓伊)
- zh-CN-YunyangNeural (云扬)
- zh-CN-langbcNeural (澜波)

**依赖：** `pip install edge-tts`

---

### 11.4 Auto TTS Simple

**功能：** 简化版配音。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| text | STRING | - | 文字 |
| voice | 选择 | zh-CN-XiaoxiaoNeural | 音色 |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| audio_path | STRING | 音频文件路径 |

**依赖：** `pip install edge-tts`

---

## 12. 批量渲染节点

### 12.1 Batch Render Queue

**功能：** 批量渲染队列。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| workflow_paths | STRING | - | 工作流 JSON 文件路径，每行一个 |
| output_dir | STRING | ./output/batch | 输出目录 |
| clear_previous | BOOLEAN | True | 是否清空之前的队列 |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| status | STRING | 状态信息 |
| queue_count | INT | 队列中的任务数 |

---

### 12.2 Batch Render Status

**功能：** 批量渲染状态。

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| current | INT | 当前任务索引 |
| total | INT | 总任务数 |
| status_json | STRING | 状态信息（JSON格式） |

---

### 12.3 Batch Render Execute

**功能：** 批量渲染执行。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| execute | BOOLEAN | False | 设为 True 开始执行 |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| instructions | STRING | 执行指令 |

---

### 12.4 Batch Workflow From Images

**功能：** 从图像批次创建工作流。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| images | IMAGE | - | 图像批次 |
| batch_name | STRING | batch | 批次名称 |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| batch_info | BATCH_INFO | 批次信息 |

---

### 12.5 Batch Process Images

**功能：** 批量处理图像。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| images | IMAGE | - | 图像批次 |
| process_all | BOOLEAN | True | True: 处理整个批次; False: 仅处理第一张 |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| processed_images | IMAGE | 处理后的图像 |
| processed_count | INT | 处理数量 |

---

## 13. 工作流示例

### 13.1 长视频分段放大

```
VHS Load Video
      ↓
Video Segment Info (计算分段)
      ↓
forLoopStart (循环)
      ↓
Get Video Segment (提取分段)
      ↓
[放大处理节点]
      ↓
Image Collect (收集)
      ↓
forLoopEnd
      ↓
VHS Video Combine
```

### 13.2 漫剧制作流程

```
1. 素材准备
   VHS Load Video → Video Info

2. 视频处理
   Video Crop → Video Scale → Color Adjust

3. 音频处理
   Audio Extract → Audio Volume → Audio Fade

4. 文字叠加
   Text Overlay / Subtitle Import

5. 转场效果
   Transition Dissolve / Transition Slide

6. 合成输出
   Audio Merge → VHS Video Combine
```

### 13.3 批量渲染

```
1. 准备多个工作流 JSON 文件
2. Batch Render Queue (添加队列)
3. Batch Render Status (查看状态)
4. Batch Render Execute (执行)
```

---

## 14. 常见问题

### Q1: 中文文字显示乱码？

**A:** 确保系统中文字体已安装，或手动指定字体路径：
```
font_path = "C:/Windows/Fonts/msyh.ttc"
```

### Q2: 音频节点不工作？

**A:** 安装 PyAV：
```bash
pip install av
```

### Q3: 自动字幕/配音不工作？

**A:** 安装依赖：
```bash
pip install openai-whisper  # 自动字幕
pip install edge-tts        # 自动配音
```

### Q4: Image Collect 只保存最后一帧？

**A:** 确保连接 `forLoopStart.value1` 到 `Image Collect.images`，不是 `initial_value1`！

### Q5: 如何查看节点帮助？

**A:** 每个节点右上角有 `?` 按钮，点击显示中英文帮助。

---

## 附录

### 节点分类速查

| 分类 | 节点 |
|------|------|
| **分段** | VideoSegmentInfo, GetVideoSegment, VideoSplitMultiple, MergeVideoSegments, ImageCollect |
| **编辑** | GetVideoFrame, GetVideoFramesRange, VideoCrop, ImageToVideo, VideoScale, VideoInfo |
| **剪映** | VideoReverse, VideoResample, VideoSampleFrames, VideoTimeRemap, VideoConcat, VideoFade, VideoOverlay, FrameInterpolate, FrameDeduplicate |
| **音频** | AudioExtract, AudioFromVideo, AudioMerge, AudioVolume, AudioFade, AudioInfo, AudioMix, AudioFitToVideo, AudioLoop, AudioCut |
| **文字** | TextOverlay, TextAnimation, SubtitleImport, TextPositionPreset |
| **滤镜** | ColorAdjust, ColorTemperature, ColorGradePreset, Vignette |
| **转场** | TransitionSlide, TransitionZoom, TransitionWipe, TransitionDissolve |
| **特效** | BackgroundRemove, BackgroundReplace, ColorKey, SimpleBackgroundRemove |
| **AI** | AutoSubtitle, AutoSubtitleFromFile, AutoTTS, AutoTTSSimple |
| **批量** | BatchRenderQueue, BatchRenderStatus, BatchRenderExecute, BatchWorkflowFromImages, BatchProcessImages |

---

**文档版本：** v1.0  
**最后更新：** 2024年  
**仓库地址：** https://github.com/mickeylan/comfyui-video-split
