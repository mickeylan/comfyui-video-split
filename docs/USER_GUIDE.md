# ComfyUI Video Split 使用文档

> 版本：v0.9.0 | 最后更新：2026年8月
>
> Wan 2.2 / Bernini 两阶段无限采样请参阅：[专项操作手册](WAN_BERNINI_GUIDE.md)（[English](WAN_BERNINI_GUIDE_EN.md)）。

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
11. [工作流示例](#11-工作流示例)
12. [常见问题](#12-常见问题)

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

---

## 2. 节点总览

| 分类 | 节点数 | 说明 |
|------|--------|------|
| 核心分段 | 5 | 视频分割、合并、循环收集 |
| 基础编辑 | 6 | 帧提取、裁剪、缩放 |
| 剪映功能 | 9 | 变速、倒放、拼接、淡入淡出 |
| 音频处理 | 13 | 提取、合并、音量、多轨混合、定位合成、时间轴编辑 |
| 文字/字幕 | 4 | 文字叠加、动画、SRT导入 |
| 滤镜/调色 | 4 | 亮度、对比度、预设滤镜 |
| 转场效果 | 4 | 滑动、缩放、擦除、溶解 |
| 特效 | 4 | 抠像、背景替换 |

**总计：49 个节点**

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

### 6.11 Audio Compose（帧级对齐）

**功能：** 将多段音频分别放置在视频的指定位置，实现精确的时间轴对齐。

**特性：**
- 采用帧数作为统一时间基准，确保音画精确同步
- 每段音频可在任意时间点开始播放
- 多段音频可叠加在同一时间段
- 自动处理不同采样率的音频

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| total_frames | INT | 1440 | 视频总帧数 |
| fps | FLOAT | 24.0 | 视频帧率，用于时间轴转换 |
| sample_rate | INT | 44100 | 采样率 |
| audio1 | AUDIO (可选) | - | 第一段音频 |
| start_frame1 | INT | 0 | 第一段音频的起始帧 |
| audio2 | AUDIO (可选) | - | 第二段音频 |
| start_frame2 | INT | 0 | 第二段音频的起始帧 |
| audio3 | AUDIO (可选) | - | 第三段音频 |
| start_frame3 | INT | 0 | 第三段音频的起始帧 |
| audio4 | AUDIO (可选) | - | 第四段音频 |
| start_frame4 | INT | 0 | 第四段音频的起始帧 |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| audio | AUDIO | 合成后的音频 |
| duration_seconds | FLOAT | 精确时长（秒） |
| total_samples | INT | 总采样数 |

**使用场景：**
- 视频配音：不同角色的台词在不同时间点播放
- BGM + 配音混合：背景音乐在某段时间播放，配音在特定时间点插入
- 音效叠加：特定时间点添加音效

**时间转换公式：**
```
采样数 = round(帧数 × 采样率 / fps)
帧数 = round(采样数 × fps / 采样率)
```

---

### 6.12 Audio Compose (Advanced)

**功能：** 高级音频合成，支持更多音频段和音量控制。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| total_duration | FLOAT | 60.0 | 总音频时长（秒） |
| sample_rate | INT | 44100 | 采样率 |
| audio_list | AUDIO (可选) | - | 音频列表 |
| start_times | STRING | "0,10,20,30" | 起始时间列表（逗号分隔） |
| volumes | STRING | "1.0,0.8,1.0,0.6" | 音量列表（逗号分隔） |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| audio | AUDIO | 合成后的音频 |

**示例配置：**
```
start_times: "0,10,25,40"    # 4段音频分别在 0秒、10秒、25秒、40秒开始
volumes: "1.0,0.8,1.0,0.6"   # 对应的音量
```

---

### 6.13 Audio Timeline Editor 🎬

**功能：** 可视化时间轴编辑器，通过拖拽操作校准音频位置。

**特性：**
- 🎯 拖拽音频块调整位置
- ↔️ 拖拽边缘调整时长
- 📐 精确到帧级对齐
- 🔍 支持缩放和平移
- 📋 导入导出配置

**界面说明：**

```
┌──────────────────────────────────────────────────────────────────────┐
│  🎵 Audio Timeline Editor                     [+ 添加轨道] [导出] [导入] │
├──────────────────────────────────────────────────────────────────────┤
│  0:00    0:05    0:10    0:15    0:20    0:25    0:30                │
│  ▼────────────────────────────────────────────────────────────────   │
│  音频轨道 1   │████████ BGM ████████│                                  │
│  音频轨道 2   │      │████ 配音1 ████│                                  │
│  音频轨道 3   │           │███ 音效 ██│                                  │
│              ▼                                                        │
│              播放头                                                    │
├──────────────────────────────────────────────────────────────────────┤
│  FPS: 24  总帧数: 720  时长: 30.00s  播放头: 145 (0:06.04)            │
└──────────────────────────────────────────────────────────────────────┘
```

**交互操作：**

| 操作 | 功能 |
|------|------|
| 拖拽音频块 | 移动音频到指定位置 |
| 拖拽边缘 | 调整音频时长 |
| 双击空白处 | 添加新音频块 |
| 滚轮 | 水平滚动时间轴 |
| Ctrl + 滚轮 | 缩放时间轴 |
| Delete / Backspace | 删除选中的音频块 |
| ← / → 方向键 | 微调选中音频块位置（1帧） |
| 导出按钮 | 复制配置 JSON 到剪贴板 |
| 导入按钮 | 从剪贴板导入配置 |

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| fps | FLOAT | 24.0 | 视频帧率 |
| video_images | IMAGE (可选) | - | 视频帧（自动获取 fps 和帧数） |
| timeline_config | STRING | - | 时间轴配置 JSON |
| sample_rate | INT | 44100 | 采样率 |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| config | TIMELINE_CONFIG | 时间轴配置对象 |
| config_json | STRING | JSON 格式的配置 |
| total_frames | INT | 总帧数 |
| duration_seconds | FLOAT | 时长（秒） |

**工作流：**

```
┌─────────────────┐
│  Load Video     │
│  (VHS)          │
└────────┬────────┘
         │
         ├──→ images ──────────────────────────────────────────────────┐
         │                                                              │
         └──→ audio ─┐                                                 ▼
                    │                                              ┌────────────┐
                    ▼                                              │ Video Info │
              ┌────────────┐                                        │ (fps,frames)│
              │ Audio      │                                        └─────┬──────┘
              │ Timeline   │                                              │
              │ Editor     │                                              │
              │ (可视化)    │                                              │
              └─────┬──────┘                                              │
                    │ config_json                                         │
                    ▼                                                     │
              ┌─────────────────────────────────────────────┐             │
              │ Audio Timeline Composer                     │             │
              │                                             │             │
              │  audio1: [背景音乐]    audio3: [配音2]       │             │
              │  audio2: [配音1]      audio4: [音效]        │             │
              │  timeline_config: ←来自时间轴编辑器         │             │
              └─────────────────────┬───────────────────────┘             │
                                    │ audio                               │
                                    ▼                                     │
                              ┌─────────────┐                             │
                              │ Audio Merge │ ←───────────────────────────┘
                              │ (合并到视频) │
                              └─────────────┘
                                    │
                                    ▼
                              最终视频输出
```

---

### 6.14 Audio Timeline Composer

**功能：** 根据时间轴配置，将多段音频合成到指定位置。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| total_frames | INT | 1440 | 视频总帧数 |
| fps | FLOAT | 24.0 | 视频帧率 |
| sample_rate | INT | 44100 | 采样率 |
| timeline_config | TIMELINE_CONFIG (可选) | - | 时间轴配置 |
| audio1-8 | AUDIO (可选) | - | 最多8段音频 |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| audio | AUDIO | 合成后的音频 |

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

## 11. 工作流示例

### 11.1 长视频分段放大

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

### 11.2 漫剧制作流程

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

### 11.3 音频时间轴校准（可视化）

使用可视化编辑器拖拽校准多段音频的位置：

```
1. 加载视频
   VHS Load Video → Video Info (获取 fps, total_frames)
                           ↓
                    Video Images → Audio Timeline Editor (可视化)
                                          ↓
                                    拖拽调整音频位置
                                          ↓
                                    导出配置 JSON
                                          ↓
2. 加载音频文件
   Load Audio (BGM) → audio1
   Load Audio (配音1) → audio2
   Load Audio (配音2) → audio3
   Load Audio (音效) → audio4

3. 合成音频
   Audio Timeline Composer → 合成音频

4. 合并视频
   Audio Merge → 最终视频
```

**详细步骤：**

1. 添加 `Audio Timeline Editor` 节点
2. 连接视频获取 fps 和帧数
3. 在编辑器中点击空白处添加音频块
4. 拖拽音频块到期望位置
5. 点击「导出」按钮复制配置
6. 将音频文件连接到 `Audio Timeline Composer`
7. 最后用 `Audio Merge` 合并视频

---

## 12. Wan22 / Bernini 分块采样器

### 12.1 节点列表

| 节点 | 接口 | 说明 |
|------|------|------|
| **Wan22 Sampler Unlimited** | CustomAdvanced | 高级接口，需要连接 BasicGuider |
| **Wan22 Low Noise Sampler Unlimited** | KSamplerAdvanced | 标准接口，从低噪节点输入 |
| **Wan22 High Noise Sampler Unlimited** | KSamplerAdvanced | 标准接口，输出接高噪节点 |
| **Wan22 Unlimited Preview** | 预览 | 实时预览，使用 TAESD 解码 |

### 12.2 分块原理

Wan22 的帧结构：**像素帧数 = 1 + 4 × N**（1 latent 步 = 4 像素帧）

```
chunk_frames = 129 → 129 像素帧 / 4 = 32 latent 步 + 1 起始帧
```

**重叠引导**：
- `overlap_frames = 8` → 重叠 8 像素帧 = 2 latent 步
- 后续段落 position 0 注入上一段的尾帧
- 连续引导确保画面平滑过渡

### 12.3 典型工作流

**基础配置**：
```
Load Checkpoint
    ↓
CLIP Text Encode (positive)
    ↓
CLIP Text Encode (negative)
    ↓
Empty Latent Video (via Encode LotteGhost/Wan22 I2V)
    ↓                              ↓
Positive                      Negative
    ↓                              ↓
Basic Guider ──────────────→ Wan22 Sampler Unlimited
    ↑                              ↓
Model                      VAE Decode
    ↓                              ↓
Load Checkpoint             Save Image / Preview
```

**分块参数**：
| 参数 | 默认值 | 12GB VRAM | 说明 |
|------|--------|-----------|------|
| chunk_frames | 128 | 128 | 每块像素帧数 |
| overlap_frames | 8 | 8 | 重叠像素帧数 |
| progressive_decode | False | True | 启用 tiled 解码 |

### 12.4 I2V 连续性

**问题**：分段生成时，后续段落会完全乱生成。

**解决方案**：Wan22 Sampler Unlimited 会自动处理：

1. **Latent 注入**：后续段落 position 0 = 上一段尾帧
2. **Conditioning 注入**：`concat_latent_image` position 0 = 上一段尾帧
3. **零噪声引导**：position 0 噪声设为 0，不参与 denoise

```
Chunk 1: [参考图] + [新生成] → 输出
Chunk 2: [Chunk1尾帧] + [新生成] → 输出  ← 自动接续
Chunk 3: [Chunk2尾帧] + [新生成] → 输出  ← 自动接续
```

### 12.5 VRAM 优化

| 优化方式 | VRAM 节省 | 说明 |
|---------|-----------|------|
| 分块采样 | ~50% | 每块独立采样 |
| 渐进式解码 | ~30% | 边采样边解码 |
| --lowvram | ~40% | ComfyUI 自动 offload |

**12GB VRAM 推荐配置**：
```
chunk_frames: 128 (720p)
overlap_frames: 8
progressive_decode: True
--lowvram
```

---

## 13. LTX Video 分块采样器

### 13.1 节点列表

| 节点 | 说明 |
|------|------|
| **LTX VRAM Manager** | VRAM 模式配置，自动检测显卡 |
| **LTX Video Optimized Decode** | bf16 强制 VAE 解码 |
| **LTX Video Optimized Audio Decode** | 音频 VAE 解码 |

### 13.2 VRAM 管理器

**功能**：
- 自动检测显卡型号和显存
- 推荐 VRAM 模式（16GB-safe / 24GB-fast / balanced）
- 打印推荐分辨率和 chunk_frames

**VRAM 模式**：
| 模式 | 适用显存 | 策略 |
|------|---------|------|
| 16GB-safe | 14-22GB | 激进 offload |
| 24GB-fast | ≥22GB | 全部驻留 GPU |
| balanced | <14GB | 平衡 offloading |

### 13.3 bf16 优化解码

**支持显卡**：
- RTX 30/40 系列 (Ampere+) ✅
- RTX 50 系列 (Blackwell) ✅
- 更老的显卡：自动禁用

**优势**：
- Ampere+ GPU 显著加速
- 降低显存占用
- 不影响采样质量

### 13.4 12GB VRAM 配置

```
chunk_frames: 33
resolution: 1280x720
--lowvram
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

### Q3: Image Collect 只保存最后一帧？

**A:** 确保连接 `forLoopStart.value1` 到 `Image Collect.images`，不是 `initial_value1`！

### Q4: 如何查看节点帮助？

**A:** 每个节点右上角有 `?` 按钮，点击显示中英文帮助。

### Q5: 如何精确对齐音频和视频？

**A:** 使用 `Audio Timeline Editor` 可视化编辑器：
1. 在编辑器中拖拽音频块到精确位置
2. 点击「导出」复制配置 JSON
3. 将配置传给后续节点

或者使用 `Audio Compose` 节点，直接指定帧数：
```
start_frame = round(target_time_seconds * fps)
```

### Q6: 时间轴编辑器不显示？

**A:** 确保：
1. 重启 ComfyUI 加载新节点
2. 浏览器刷新缓存（Ctrl+F5）
3. 检查控制台是否有 JS 错误

### Q7: 多段音频叠加时音量太大？

**A:** 在 `Audio Timeline Editor` 中降低各音频块的音量，或在 `Audio Timeline Composer` 中调整整体音量。

---

## 附录

### 节点分类速查

| 分类 | 节点 |
|------|------|
| **分段** | VideoSegmentInfo, GetVideoSegment, VideoSplitMultiple, MergeVideoSegments, ImageCollect |
| **编辑** | GetVideoFrame, GetVideoFramesRange, VideoCrop, ImageToVideo, VideoScale, VideoInfo |
| **剪映** | VideoReverse, VideoResample, VideoSampleFrames, VideoTimeRemap, VideoConcat, VideoFade, VideoOverlay, FrameInterpolate, FrameDeduplicate |
| **音频** | AudioExtract, AudioFromVideo, AudioMerge, AudioVolume, AudioFade, AudioInfo, AudioMix, AudioFitToVideo, AudioLoop, AudioCut, AudioCompose, AudioComposeAdvanced, AudioTimelineEditor, AudioTimelineComposer |
| **文字** | TextOverlay, TextAnimation, SubtitleImport, TextPositionPreset |
| **滤镜** | ColorAdjust, ColorTemperature, ColorGradePreset, Vignette |
| **转场** | TransitionSlide, TransitionZoom, TransitionWipe, TransitionDissolve |
| **特效** | BackgroundRemove, BackgroundReplace, ColorKey, SimpleBackgroundRemove |

---

**文档版本：** v2.0  
**最后更新：** 2026年8月  
**仓库地址：** https://github.com/mickeylan/comfyui-video-split
