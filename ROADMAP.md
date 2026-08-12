# Video Split 开发规划

## 目标

打造一个**简化版剪映**，支持漫剧制作的核心功能。

---

## 当前状态 (v0.3.0)

### 已有节点 (20个)

#### 核心分段节点 (5个)
- Video Segment Info
- Get Video Segment
- Video Split (Multiple)
- Merge Video Segments
- Image Collect

#### 基础编辑节点 (6个)
- Get Video Frame
- Get Video Frames Range
- Video Crop
- Image To Video
- Video Scale
- Video Info

#### 剪映功能节点 (9个)
- Video Reverse
- Video Resample
- Video Sample Frames
- Video Time Remap
- Video Concat
- Video Fade
- Video Overlay
- Frame Interpolate
- Frame Deduplicate

---

## 开发规划

### Phase 1: 音频处理 (核心) ⭐⭐⭐⭐⭐

**目标**: 解决视频放大后音频丢失问题

| 节点 | 功能 | 实现方案 | 优先级 |
|------|------|---------|--------|
| Audio Extract | 从视频提取音频 | PyAV decode audio stream | P0 |
| Audio Merge | 音频合并到视频 | PyAV encode + mux | P0 |
| Audio Volume | 音量调节 | PyAV filter volume | P0 |
| Audio Fade | 音频淡入淡出 | PyAV filter afade | P0 |
| Audio Resample | 音频重采样 | PyAV resample | P1 |
| Audio Info | 获取音频信息 | PyAV stream info | P1 |

**依赖**: `av` (PyAV)

**预计工作量**: 4小时

---

### Phase 2: 字幕/文字 (核心) ⭐⭐⭐⭐⭐

**目标**: 支持漫剧对白、标题、说明文字

| 节点 | 功能 | 实现方案 | 优先级 |
|------|------|---------|--------|
| Text Overlay | 文字叠加到视频帧 | PIL/Pillow 生成文字图片 | P0 |
| Text Style | 文字样式设置 | PIL + 参数配置 | P0 |
| Subtitle Import | 导入 SRT/ASS 字幕 | 解析字幕文件 | P1 |
| Subtitle Timing | 字幕时间对齐 | 根据时间戳显示 | P1 |
| Text Animation | 文字动画（打字机等） | 自定义动画逻辑 | P2 |

**依赖**: `PIL` (Pillow), `srt` (可选)

**预计工作量**: 6小时

---

### Phase 3: 滤镜/调色 (重要) ⭐⭐⭐⭐

**目标**: 统一画面色调，提升质感

| 节点 | 功能 | 实现方案 | 优先级 |
|------|------|---------|--------|
| Color Adjust | 亮度/对比度/饱和度 | PyAV filter eq | P0 |
| Color Grade | 色彩分级 | PyAV filter colorbalance | P1 |
| Filters Preset | 预设滤镜 | 组合多个 filter | P1 |
| Color Match | 色彩匹配 | 直方图匹配 | P2 |

**依赖**: `av` (PyAV), `numpy`

**预计工作量**: 4小时

---

### Phase 4: 转场效果 (重要) ⭐⭐⭐⭐

**目标**: 专业转场效果

| 节点 | 功能 | 实现方案 | 优先级 |
|------|------|---------|--------|
| Transition Fade | 淡入淡出转场 | 已有 Video Fade | - |
| Transition Slide | 滑动转场 | 帧位移动画 | P0 |
| Transition Zoom | 缩放转场 | 帧缩放动画 | P0 |
| Transition Wipe | 擦除转场 | mask 动画 | P1 |
| Transition Dissolve | 溶解转场 | alpha 混合 | P1 |
| Transition XFade | ffmpeg xfade 滤镜 | PyAV filter xfade | P1 |

**依赖**: `av` (PyAV)

**预计工作量**: 5小时

---

### Phase 5: 特效功能 (可选) ⭐⭐⭐

**目标**: 高级特效支持

| 节点 | 功能 | 实现方案 | 优先级 |
|------|------|---------|--------|
| Green Screen | 绿幕抠像 | 色键抠像 | P1 |
| Mask Overlay | 蒙版叠加 | alpha channel | P1 |
| Motion Blur | 运动模糊 | 帧混合 | P2 |
| Glitch Effect | 故障效果 | 随机像素操作 | P2 |

**依赖**: `numpy`, `torch`

**预计工作量**: 6小时

---

## 技术架构

### 依赖管理

```python
# requirements.txt
av>=10.0.0      # PyAV - ffmpeg Python 绑定
Pillow>=9.0.0   # PIL - 图像处理
numpy>=1.20.0   # 数值计算
torch>=2.0.0    # 张量处理
```

### 文件结构

```
comfyui-video-split/
├── __init__.py
├── nodes.py              # 所有节点定义
├── audio_nodes.py        # 音频处理节点
├── text_nodes.py         # 文字/字幕节点
├── filter_nodes.py       # 滤镜/调色节点
├── transition_nodes.py   # 转场效果节点
├── effect_nodes.py       # 特效节点
├── utils/
│   ├── audio.py          # 音频处理工具
│   ├── text.py           # 文字处理工具
│   └── ffmpeg.py         # ffmpeg 命令封装
└── web/js/video_split.js # 前端扩展
```

---

## 开发时间表

| 阶段 | 内容 | 预计时间 | 目标版本 |
|------|------|---------|---------|
| Phase 1 | 音频处理 | 4小时 | v0.4.0 |
| Phase 2 | 字幕/文字 | 6小时 | v0.5.0 |
| Phase 3 | 滤镜/调色 | 4小时 | v0.6.0 |
| Phase 4 | 转场效果 | 5小时 | v0.7.0 |
| Phase 5 | 特效功能 | 6小时 | v0.8.0 |
| **总计** | **全部功能** | **25小时** | **v0.8.0** |

---

## 验收标准

### Phase 1 验收
- [ ] 可以从视频中提取音频
- [ ] 可以将音频合并到视频
- [ ] 可以调节音量
- [ ] 可以添加音频淡入淡出

### Phase 2 验收
- [ ] 可以在视频上叠加文字
- [ ] 支持文字样式（字体、大小、颜色、位置）
- [ ] 可以导入 SRT 字幕文件
- [ ] 字幕可以正确对齐时间

### Phase 3 验收
- [ ] 可以调节亮度、对比度、饱和度
- [ ] 支持预设滤镜效果
- [ ] 处理速度可接受

### Phase 4 验收
- [ ] 支持至少 5 种转场效果
- [ ] 转场时长可调
- [ ] 效果流畅

### Phase 5 验收
- [ ] 绿幕抠像效果可用
- [ ] 蒙版功能可用

---

## 风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| PyAV 兼容性问题 | 中 | 提供 ffmpeg 命令行备选方案 |
| 文字渲染性能 | 低 | 使用 GPU 加速或缓存 |
| 音频同步问题 | 高 | 基于时间戳精确对齐 |
| 内存占用 | 中 | 分块处理，及时释放 |

---

## 更新日志

### v0.3.0 (当前)
- 新增 9 个剪映功能节点
- 支持视频倒放、变速、拼接等基础编辑功能

### v0.4.0 (计划)
- 新增音频处理节点
- 解决视频放大后音频丢失问题

### v0.5.0 (计划)
- 新增字幕/文字节点
- 支持漫剧对白、标题显示

---

**文档版本**: v1.0
**最后更新**: 2024年