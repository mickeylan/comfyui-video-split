# ComfyUI Video Split Nodes

视频分段节点，用于将长视频按时长或帧数分割成多个片段，配合循环节点实现分段处理后再合并。

## 安装

将 `comfyui-video-split` 文件夹放入 `custom_nodes/` 目录，重启 ComfyUI 即可。

## 节点列表

| 节点名称 | 功能 |
|---------|------|
| **Video Segment Info** | 计算视频分段信息 |
| **Get Video Segment** | 按索引提取单个视频分段 |
| **Video Split (Multiple)** | 一次性分割所有分段 |
| **Merge Video Segments** | 合并多个视频分段 |
| **Image Collect** | 在循环中收集图像帧 |

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

**输入：**
| 参数 | 类型 | 说明 |
|------|------|------|
| new_images | IMAGE | 当前迭代的图像帧 |
| images | IMAGE (可选) | 之前累积的图像帧（来自上一轮的 accumulated） |

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

### 关键连接

1. `VHS Load Video` 的 **image** 输出 → `Video Segment Info` 的 **images** 输入
2. `Video Segment Info` 的 **total_segments** → `forLoopStart` 的 **total**
3. `forLoopStart` 的 **index** → `Get Video Segment` 的 **segment_index**
4. `VHS Load Video` 的 **image** 输出 → `Get Video Segment` 的 **images** 输入
5. `Get Video Segment` 的 **segment_images** → 放大处理节点
6. `Image Collect` 的 **accumulated** → `forLoopEnd` 的 **initial_value1**
7. `forLoopEnd` 的 **value1** → `VHS_VideoCombine` 的 **images**

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

- v1.1 - 改用 IMAGE 类型，兼容 VHS Load Video
- v1.0 - 初始版本