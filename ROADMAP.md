# Video Split 开发规划

## 目标

打造一个**简化版剪映**，支持 AI 漫剧制作的核心功能。

---

## 当前状态 (v0.7.0)

### 已有节点 (55个)

#### 核心分段节点 (5个) ✅
- Video Segment Info
- Get Video Segment
- Video Split (Multiple)
- Merge Video Segments
- Image Collect

#### 基础编辑节点 (6个) ✅
- Get Video Frame
- Get Video Frames Range
- Video Crop
- Image To Video
- Video Scale
- Video Info

#### 剪映功能节点 (9个) ✅
- Video Reverse
- Video Resample
- Video Sample Frames
- Video Time Remap
- Video Concat
- Video Fade
- Video Overlay
- Frame Interpolate
- Frame Deduplicate

#### 音频处理节点 (10个) ✅
- Audio Extract
- Audio From Video
- Audio Merge
- Audio Volume
- Audio Fade
- Audio Info
- Audio Mix（多音轨混合）
- Audio Fit To Video（时长匹配）
- Audio Loop
- Audio Cut

#### 文字/字幕节点 (4个) ✅
- Text Overlay（支持中文）
- Text Animation（打字机效果）
- Subtitle Import（SRT 导入）
- Text Position Preset

#### 滤镜/调色节点 (4个) ✅
- Color Adjust（亮度/对比度/饱和度）
- Color Temperature（色温）
- Color Grade Preset（预设滤镜）
- Vignette（暗角）

#### 转场效果节点 (4个) ✅
- Transition Slide
- Transition Zoom
- Transition Wipe
- Transition Dissolve

#### 特效节点 (4个) ✅
- Background Remove（角色抠像）
- Background Replace（背景替换）
- Color Key（色键抠像）
- Simple Background Remove

---

## 版本历史

| 版本 | 内容 | 节点数 |
|------|------|--------|
| v0.5.0 | 音频增强、特效节点（抠像、背景替换） | 46 |
| v0.4.0 | 音频处理、文字字幕、滤镜调色、转场效果 | 42 |
| v0.3.0 | 剪映功能节点（倒放、变速、拼接等） | 20 |
| v0.2.0 | 帧处理、裁剪、缩放、分块处理 | 11 |
| v0.1.0 | 视频分段、循环收集 | 5 |

---

## 功能对比（vs 剪映）

| 功能 | 剪映 | video-split | 状态 |
|------|------|-------------|------|
| 视频分割/合并 | ✅ | ✅ | ✅ 完成 |
| 变速/倒放 | ✅ | ✅ | ✅ 完成 |
| 裁剪/缩放 | ✅ | ✅ | ✅ 完成 |
| 淡入淡出 | ✅ | ✅ | ✅ 完成 |
| 转场效果 | ✅ | ✅ | ✅ 完成 |
| 滤镜/调色 | ✅ | ✅ | ✅ 完成 |
| 音频提取/合并 | ✅ | ✅ | ✅ 完成 |
| 多音轨混合 | ✅ | ✅ | ✅ 完成 |
| 音频时长匹配 | ✅ | ✅ | ✅ 完成 |
| 字幕/文字 | ✅ | ✅ | ✅ 完成 |
| 中文字体支持 | ✅ | ✅ | ✅ 完成 |
| 抠像/背景替换 | ✅ | ✅ | ✅ 完成 |
**功能对齐以已注册并实际执行的节点为准。**

---

## 未来规划

### Phase 6: 高级功能（待评估）

| 功能 | 说明 | 优先级 |
|------|------|--------|
| 多角色字幕样式 | 按角色 ID 应用不同颜色/字体 | P2 |
| 表情动画 | 角色表情驱动 | P2 |
| 镜头运动 | 推拉摇移效果 | P2 |
| 关键帧动画 | 位置/缩放/旋转关键帧 | P2 |
| 蒙版动画 | 动态蒙版 | P3 |
| 运动模糊 | 帧混合实现 | P3 |
| 故障效果 | 赛博朋克风格 | P3 |

### 可选扩展

| 功能 | 实现方式 |
|------|---------|
| 口型同步 | 配合 SadTalker/Wav2Lip 工作流 |
| 自动字幕翻译 | Whisper + 翻译 API |
| 视频超分辨率 | 配合现有放大模型 |

---

## 技术架构

### 文件结构

```
comfyui-video-split/
├── __init__.py              # 节点注册
├── nodes.py                 # 核心分段 + 基础编辑 + 剪映功能
├── audio_nodes.py           # 音频处理节点
├── text_nodes.py            # 文字/字幕节点
├── filter_nodes.py          # 滤镜/调色节点
├── transition_nodes.py      # 转场效果节点
├── effect_nodes.py          # 特效节点（抠像/背景）
├── requirements.txt         # 依赖
├── docs/
│   └── USER_GUIDE.md        # 详细使用文档
├── web/js/video_split.js    # 前端帮助系统
├── workflows/               # 示例工作流
├── README.md                # 中文文档
├── README_EN.md             # 英文文档
└── ROADMAP.md               # 开发规划（本文件）
```

### 依赖

```
av>=10.0.0           # PyAV - 音频处理
```

---

## 风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| PyAV 兼容性问题 | 中 | 提供错误提示，引导安装 |
| 中文字体缺失 | 中 | 自动检测系统字体，提示安装 |
| 音频同步问题 | 高 | 基于时间戳精确对齐 |
| 内存占用 | 中 | 分块处理，及时释放 |
| Whisper 模型下载 | 低 | 使用 base 模型，体积小 |

---

**文档版本**: v2.0
**最后更新**: 2024年
**当前版本**: v0.7.0
