# ComfyUI Video Split Nodes

[English Documentation](README_EN.md)

视频分段节点，用于将长视频按时长或帧数分割成多个片段，配合循环节点实现分段处理后再合并。

## 安装

将 `comfyui-video-split` 文件夹放入 `custom_nodes/` 目录，重启 ComfyUI 即可。

## 节点列表

### 核心分段节点

| 节点名称 | 功能 |
|---------|------|
| **Video Segment Info** | 计算视频分段信息 |
| **Get Video Segment** | 按索引提取单个视频分段 |
| **Video Split (Multiple)** | 一次性分割所有分段 |
| **Merge Video Segments** | 合并多个视频分段 |
| **Image Collect** | 在循环中收集图像帧 |

### 基础编辑节点

| 节点名称 | 功能 |
|---------|------|
| **Get Video Frame** | 获取单帧图像 |
| **Get Video Frames Range** | 获取帧范围 |
| **Video Crop** | 视频裁剪 |
| **Image To Video** | 图片转视频 |
| **Video Scale** | 视频缩放 |
| **Video Info** | 获取视频信息 |

### 剪映功能节点 🎬

| 节点名称 | 功能 | 漫剧用途 |
|---------|------|---------|
| **Video Reverse** | 视频倒放 | 回忆镜头、特效 |
| **Video Resample** | 帧率转换 | 调整流畅度 |
| **Video Sample Frames** | 抽帧提取 | 延时摄影效果 |
| **Video Time Remap** | 时间重映射 | 变速播放 |
| **Video Concat** | 视频拼接 | 画中画、对比 |
| **Video Fade** | 淡入淡出 | 转场效果 |
| **Video Overlay** | 视频叠加 | 水印、特效 |
| **Frame Interpolate** | 帧插值 | 慢动作 |
| **Frame Deduplicate** | 帧去重 | 减小体积 |

### 音频处理节点 🎵

| 节点名称 | 功能 |
|---------|------|
| **Audio Extract** | 从视频文件提取音频 |
| **Audio From Video** | 从视频张量提取音频 |
| **Audio Merge** | 音频合并到视频 |
| **Audio Volume** | 音量调节 |
| **Audio Fade** | 音频淡入淡出 |
| **Audio Info** | 获取音频信息 |
| **Audio Mix** | 多音轨混合（BGM+配音+音效） |
| **Audio Fit To Video** | 音频时长匹配视频 |
| **Audio Loop** | 音频循环 |
| **Audio Cut** | 音频切割 |

### 文字/字幕节点 📝

| 节点名称 | 功能 |
|---------|------|
| **Text Overlay** | 文字叠加到视频帧 |
| **Text Animation** | 文字动画（打字机效果等） |
| **Subtitle Import** | 导入 SRT 字幕 |
| **Text Position Preset** | 文字位置预设 |

### 滤镜/调色节点 🎨

| 节点名称 | 功能 |
|---------|------|
| **Color Adjust** | 亮度/对比度/饱和度调节 |
| **Color Temperature** | 色温调节 |
| **Color Grade Preset** | 预设滤镜效果 |
| **Vignette** | 暗角效果 |

### 转场效果节点 ✨

| 节点名称 | 功能 |
|---------|------|
| **Transition Slide** | 滑动转场 |
| **Transition Zoom** | 缩放转场 |
| **Transition Wipe** | 擦除转场 |
| **Transition Dissolve** | 溶解转场 |

### 特效节点 🌟

| 节点名称 | 功能 | 漫剧用途 |
|---------|------|---------|
| **Background Remove** | 角色抠像 | AI 生成角色背景不干净 |
| **Background Replace** | 背景替换 | 把角色放到新背景上 |
| **Color Key** | 色键抠像 | 绿幕/蓝幕抠像 |
| **Simple Background Remove** | 简单背景移除 | 纯色背景快速移除 |

### AI 辅助节点 🤖

| 节点名称 | 功能 | 漫剧用途 |
|---------|------|---------|
| **Auto Subtitle (Whisper)** | 自动字幕 | 配音后自动生成字幕 |
| **Auto Subtitle From File** | 从音频文件生成字幕 | 处理外部音频 |
| **Auto TTS (Edge-TTS)** | 自动配音 | 文字转语音 |
| **Auto TTS Simple** | 简化版配音 | 快速生成配音 |

**注意**：AI 辅助节点需要额外安装依赖：
```bash
pip install edge-tts        # 自动配音
pip install openai-whisper  # 自动字幕
```

### 批量渲染节点 📦

| 节点名称 | 功能 | 漫剧用途 |
|---------|------|---------|
| **Batch Render Queue** | 批量渲染队列 | 添加多个工作流到队列 |
| **Batch Render Status** | 批量渲染状态 | 查看当前渲染进度 |
| **Batch Render Execute** | 批量渲染执行 | 执行渲染队列 |
| **Batch Workflow From Images** | 从图像创建批次 | 批量处理图像 |
| **Batch Process Images** | 批量处理图像 | 处理图像批次 |

**使用方法**：
1. 使用 `Batch Render Queue` 添加工作流路径（每行一个 JSON 文件路径）
2. 使用 `Batch Render Status` 查看队列状态
3. 配合 ComfyUI API 或前端执行批量渲染

## 节点详情

### Video Segment Info

计算视频的分段信息，供循环节点使用。

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

---

### Get Video Segment

按索引提取单个视频分段，配合循环节点使用。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| images | IMAGE | - | 帧张量（连接 VHS Load Video 的 image 输出） |
| segment_index | INT | 0 | 分段索引（从0开始） |
| frames_per_segment | INT | 120 | 每段帧数（来自 Video Segment Info） |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| segment_images | IMAGE | 当前分段的帧张量 |
| segment_frame_count | INT | 当前分段帧数 |
| start_frame | INT | 当前分段起始帧索引 |

---

### Video Split (Multiple)

一次性分割视频为所有分段，输出为列表。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| images | IMAGE | - | 帧张量（连接 VHS Load Video 的 image 输出） |
| split_mode | 选择 | by_duration | 分段模式 |
| fps | FLOAT | 24.0 | 视频帧率 |
| segment_duration | FLOAT | 5.0 | 每段时长（秒） |
| segment_frames | INT | 120 | 每段帧数 |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| segments | IMAGE (列表) | 所有分段的帧张量列表 |
| total_segments | INT | 总分段数 |

---

### Merge Video Segments

合并多个视频分段为单个视频。

**输入：**
| 参数 | 类型 | 说明 |
|------|------|------|
| segments | IMAGE (列表) | 要合并的帧张量分段 |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| merged_images | IMAGE | 合并后的帧张量 |
| total_frames | INT | 总帧数 |

---

### Image Collect

在 for 循环中收集图像帧，循环结束后输出完整帧序列。

**特性：**
- ✅ 智能类型检测：自动识别输入是张量还是列表
- ✅ 兼容不同循环节点的输出类型

**输入：**
| 参数 | 类型 | 说明 |
|------|------|------|
| new_images | IMAGE | 当前迭代的图像帧 |
| images | IMAGE (可选) | 之前累积的图像帧（来自上一轮的 accumulated）。第一次迭代留空 |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| accumulated | IMAGE | 累积的图像帧 |
| total_frames | INT | 当前总帧数 |

---

## 工作流示例

### 配合 VHS Load Video 和 for 循环节点

使用 `comfyui-easy-use` 插件的 `forLoopStart` 和 `forLoopEnd` 节点。

```
VHS Load Video ──┬──→ Video Segment Info ──→ forLoopStart(total)
   (image输出)   │            │                       │
                 │            │ total_segments        │ index
                 │            ▼                       ▼
                 │     forLoopStart            forLoopStart
                 │            │                       │
                 │            │ index                 │
                 │            ▼                       │
                 └──→ Get Video Segment ←────────────┘
                           │
                     segment_images
                           │
                           ▼
                     [放大处理节点]
                           │
                        IMAGE
                           │
                           ▼
                     Image Collect ←──┐
                     (accumulated) ────┘ (传给下一次迭代)
                           │
                     forLoopEnd
                           │
                        value1
                           │
                           ▼
                     VHS_VideoCombine
                           │
                           ▼
                      最终视频
```

### 重要说明：images 输入的连接

**Video Segment Info 和 Get Video Segment 都需要连接同一个 images 数据源！**

```
                    ┌──→ Video Segment Info 的 images 输入
VHS Load Video ─────┤
     (image输出)     └──→ Get Video Segment 的 images 输入
```

**原因：**
- `Video Segment Info` 需要帧张量来计算总帧数和分段信息
- `Get Video Segment` 需要帧张量来切片提取当前分段
- 两者必须使用同一个数据源，否则分段索引会不匹配

### 关键连接步骤

1. `VHS Load Video` 的 **image** 输出 → `Video Segment Info` 的 **images** 输入
2. `VHS Load Video` 的 **image** 输出 → `Get Video Segment` 的 **images** 输入（⚠️ 同一数据源）
3. `Video Segment Info` 的 **total_segments** → `forLoopStart` 的 **total**
4. `Video Segment Info` 的 **frames_per_segment** → `Get Video Segment` 的 **frames_per_segment**
5. `forLoopStart` 的 **index** → `Get Video Segment` 的 **segment_index**
6. `Get Video Segment` 的 **segment_images** → 放大处理节点
7. `forLoopStart` 的 **value1** → `Image Collect` 的 **images**（⚠️ 必须连 value1，不是 initial_value1）
8. `Image Collect` 的 **accumulated** → `forLoopEnd` 的 **initial_value1**
9. `forLoopEnd` 的 **value1** → `VHS_VideoCombine` 的 **images**

### ⚠️ 最容易出错的连线

**错误**：`forLoopStart.initial_value1` → `Image Collect.images`
- 结果：每次迭代都收到空值，最后只保存最后一帧

**正确**：`forLoopStart.value1` → `Image Collect.images`
- 结果：正确传递累积结果

**原因**：
- `initial_value1` = 循环开始时的初始值（第一次迭代为空）
- `value1` = 传递给循环内的当前值（包括累积结果）

---

## 新增节点

### Get Video Frame

获取视频的单帧图像。

**输入：**
| 参数 | 类型 | 说明 |
|------|------|------|
| images | IMAGE | 帧张量 |
| frame_index | INT | 帧索引（支持负索引，-1 表示最后一帧） |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| frame | IMAGE | 单帧图像 |

---

### Get Video Frames Range

获取视频指定范围的帧。

**输入：**
| 参数 | 类型 | 说明 |
|------|------|------|
| images | IMAGE | 帧张量 |
| start_frame | INT | 起始帧索引 |
| end_frame | INT | 结束帧索引（-1 表示到最后一帧） |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| frames | IMAGE | 帧范围 |
| frame_count | INT | 帧数 |

---

### Video Crop

视频裁剪，支持上下左右裁剪。

**输入：**
| 参数 | 类型 | 说明 |
|------|------|------|
| images | IMAGE | 帧张量 |
| crop_top | INT | 顶部裁剪像素 |
| crop_bottom | INT | 底部裁剪像素 |
| crop_left | INT | 左侧裁剪像素 |
| crop_right | INT | 右侧裁剪像素 |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| cropped_images | IMAGE | 裁剪后的帧张量 |
| new_height | INT | 新高度 |
| new_width | INT | 新宽度 |

---

### Image To Video

将单张图片转换为视频（复制帧）。

**输入：**
| 参数 | 类型 | 说明 |
|------|------|------|
| image | IMAGE | 单张图片 |
| frame_count | INT | 输出帧数 |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| video | IMAGE | 视频帧张量 |

---

### Video Scale

视频缩放，使用分块处理避免内存峰值。

**输入：**
| 参数 | 类型 | 说明 |
|------|------|------|
| images | IMAGE | 帧张量 |
| width | INT | 目标宽度 |
| height | INT | 目标高度 |
| method | 选择 | 缩放方法：nearest-exact, bilinear, bicubic, area, bicubic-lanczos |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| scaled_images | IMAGE | 缩放后的帧张量 |

---

### Video Info

获取视频信息。

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

## 分段逻辑

### 按时长分段

例：8秒视频（24fps = 192帧），每段5秒（120帧）

| 分段索引 | 起始帧 | 结束帧 | 帧数 | 时长 |
|---------|--------|--------|------|------|
| 0 | 0 | 120 | 120 | 5秒 |
| 1 | 120 | 192 | 72 | 3秒 |

总段数：`(192 + 120 - 1) // 120 = 2`

### 按帧数分段

例：300帧视频，每段100帧

| 分段索引 | 起始帧 | 结束帧 | 帧数 |
|---------|--------|--------|------|
| 0 | 0 | 100 | 100 |
| 1 | 100 | 200 | 100 |
| 2 | 200 | 300 | 100 |

总段数：`(300 + 100 - 1) // 100 = 3`

---

## 应用场景

- 长视频高清放大（分段处理避免显存不足）
- 批量处理视频片段
- 视频分段降噪/增强
- 按固定时长提取视频片段

---

## 注意事项

1. 需要安装 `comfyui-easy-use` 插件才能使用循环节点
2. 循环次数过多时注意 ComfyUI 的执行时间限制
3. 分段时长建议根据显存大小调整，5秒/段是常用配置
4. VHS Load Video 需要手动设置 fps 参数，或者用 `VHS Video Info` 节点获取帧率

---

## 版本

- v0.7.0 - 新增批量渲染节点：队列管理、状态查询、批量处理
- v0.6.0 - 新增 AI 辅助节点：自动字幕、自动配音（Edge-TTS）
- v0.5.0 - 新增音频增强（多轨混合、时长匹配）、特效节点（抠像、背景替换）
- v0.4.0 - 新增音频处理、文字字幕、滤镜调色、转场效果节点，打造完整剪映功能
- v0.3.0 - 新增剪映功能节点：VideoReverse、VideoResample、VideoSampleFrames、VideoTimeRemap、VideoConcat、VideoFade、VideoOverlay、FrameInterpolate、FrameDeduplicate
- v0.2.0 - 新增 GetVideoFrame、GetVideoFramesRange、VideoCrop、ImageToVideo、VideoScale、VideoInfo 节点；添加分块处理功能
- v0.1.0 - 初始版本，支持视频分段、循环收集、国际化帮助文档