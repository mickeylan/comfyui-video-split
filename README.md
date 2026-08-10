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
| video | VIDEO | - | 输入视频 |
| split_mode | 选择 | by_duration | 分段模式：by_duration（按时长）或 by_frames（按帧数） |
| segment_duration | FLOAT | 5.0 | 每段时长（秒），split_mode=by_duration 时使用 |
| segment_frames | INT | 120 | 每段帧数，split_mode=by_frames 时使用 |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| total_segments | INT | 总分段数 |
| fps | FLOAT | 视频帧率 |
| total_frames | INT | 视频总帧数 |
| frames_per_segment | INT | 每段帧数 |

---

### Get Video Segment

按索引提取单个视频分段，配合循环节点使用。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| video | VIDEO | - | 输入视频 |
| segment_index | INT | 0 | 分段索引（从0开始） |
| frames_per_segment | INT | 120 | 每段帧数（来自 Video Segment Info） |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| video_segment | VIDEO | 当前分段的视频 |
| segment_frame_count | INT | 当前分段帧数 |
| start_frame | INT | 当前分段起始帧索引 |

**特性：**
- 支持**懒加载裁剪**，只解码当前分段，不加载整个视频到内存
- 对于已加载到内存的视频，回退到张量切片

---

### Video Split (Multiple)

一次性分割视频为所有分段，输出为列表。

**输入：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| video | VIDEO | - | 输入视频 |
| split_mode | 选择 | by_duration | 分段模式 |
| segment_duration | FLOAT | 5.0 | 每段时长（秒） |
| segment_frames | INT | 120 | 每段帧数 |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| video_segments | VIDEO (列表) | 所有分段的视频列表 |
| total_segments | INT | 总分段数 |

---

### Merge Video Segments

合并多个视频分段为单个视频。

**输入：**
| 参数 | 类型 | 说明 |
|------|------|------|
| video_segments | VIDEO (列表) | 要合并的视频分段 |

**输出：**
| 输出 | 类型 | 说明 |
|------|------|------|
| merged_video | VIDEO | 合并后的视频 |
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

### 方案：配合 for 循环节点分段处理

使用 `comfyui-easy-use` 插件的 `forLoopStart` 和 `forLoopEnd` 节点。

```
Load Video → Video Segment Info → forLoopStart(total)
     │                               │
     │                          index (0,1,2...)
     │                               │
     └──→ Get Video Segment ←────────┘
                │
          video_segment
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

1. `Video Segment Info` 的 `total_segments` → `forLoopStart` 的 `total`
2. `forLoopStart` 的 `index` → `Get Video Segment` 的 `segment_index`
3. `Get Video Segment` 的 `video_segment` → 放大处理节点
4. `Image Collect` 的 `accumulated` → `forLoopEnd` 的 `initial_value1`
5. `forLoopEnd` 的 `value1` → `VHS_VideoCombine` 的 `images`

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

## 内存优化

`Get Video Segment` 节点支持**懒加载裁剪**：

- 从 `Load Video` 节点加载的视频（`VideoFromFile` 类型）只解码当前分段，不加载整个视频
- 对于已在内存中的视频，回退到张量切片

这确保了处理长视频时不会因为一次性加载全部帧而爆内存。

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

---

## 版本

- v1.0 - 初始版本
  - 视频分段基础功能
  - 懒加载裁剪支持
  - 图像收集节点