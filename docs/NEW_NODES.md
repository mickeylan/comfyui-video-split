# 新增节点文档

## 新增节点

### 1. VLM Prompt Enhancer (prompt_enhancer.py)

**功能**：使用视觉语言模型（VLM）增强提示词

#### 节点列表

| 节点名 | 显示名 | 功能 |
|--------|--------|------|
| `VLMPromptEnhancerNode` | VLM Prompt Enhancer | 核心增强节点 |
| `VLMStorageNode` | VLM API Storage | API 配置存储 |

#### 支持的模型

| 模型 ID | 模型名 |
|---------|--------|
| `qwen2.5-vl` | Qwen2.5-VL (推荐) |
| `qwen2-vl` | Qwen2-VL |
| `qwen-vl` | Qwen-VL |
| `qwen2.5` | Qwen2.5 (文本) |
| `qwen2` | Qwen2 (文本) |

#### 参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `image` | IMAGE | 必需 | 输入图片 |
| `text` | STRING | 必需 | 待增强的提示词 |
| `model_family` | 选择 | `qwen2.5-vl` | VLM 模型 |
| `api_url` | STRING | 阿里云 | API 地址 |
| `api_key` | STRING | 必需 | API 密钥 |
| `temperature` | FLOAT | 1.0 | 采样温度 |
| `max_tokens` | INT | 2000 | 最大生成长度 |

#### 使用示例

```
[VLM API Storage] → api_url, api_key
                          ↓
[Load Image] → image
                          ↓
[VLM Prompt Enhancer] → enhanced_prompt
                          ↓
[Anything] → 使用增强后的提示词
```

#### 系统提示词

节点使用优化的系统提示词，支持：
- ✅ 保留原文中的专有名词
- ✅ 严格的文字渲染策略
- ✅ 去除推理过程可见性
- ✅ 多语言支持

---

### 2. Video Scale (video_scale.py)

**功能**：视频/图片超分辨率放大

#### 节点列表

| 节点名 | 显示名 | 功能 |
|--------|--------|------|
| `VideoScaleNode` | Video Scale (Advanced) | 高级超分 |
| `VideoScaleSimpleNode` | Video Scale | 简单超分 |
| `VideoScaleInfoNode` | Video Scale Info | 超分信息 |

#### 放大方法

| 方法 | 说明 | 质量 | 速度 |
|------|------|------|------|
| `realesrgan` | Real-ESRGAN (最佳) | ⭐⭐⭐⭐⭐ | 慢 |
| `bicubic` | 双三次插值 | ⭐⭐⭐ | 中 |
| `lanczos` | Lanczos 插值 | ⭐⭐⭐⭐ | 中 |
| `nearest` | 最近邻 (快速) | ⭐⭐ | 快 |

#### 参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `images` | IMAGE | 必需 | 输入图片/视频帧 |
| `scale` | 选择 | 2x | 放大倍数 (2, 4) |
| `method` | 选择 | `bicubic` | 放大方法 |
| `denoise_strength` | FLOAT | 0.5 | 降噪强度 |

> **注意**：使用 Real-ESRGAN 需要安装：
> ```bash
> pip install realesrgan
> ```

#### 使用示例

```
[Load Video] → frames
                    ↓
[Video Scale (Advanced)]
  - scale: 2
  - method: realesrgan
                    ↓
[Upscaled Video]
```

---

## 安装依赖

```bash
# 核心依赖
pip install torch pillow numpy

# 可选：Real-ESRGAN (高质量放大)
pip install realesrgan

# 可选：httpx (VLM API 调用)
pip install httpx
```

---

## 技术说明

### VLM Prompt Enhancer

基于逆向分析的 API 调用逻辑开发，使用标准 httpx 进行 HTTP 请求：

1. **图片预处理**：缩放到 1280x1280 以内
2. **Base64 编码**：转换为 JPEG 并编码
3. **API 调用**：构造符合 VLM API 格式的请求
4. **响应清洗**：去除思维链、代码块等干扰内容

### Video Scale

提供多种放大算法：

1. **Real-ESRGAN**：深度学习超分，需要模型文件
2. **插值算法**：使用 PIL 库的经典算法，无需额外依赖

---

## 与原始模块对比

| 原始模块 | 新模块 | 关系 |
|----------|--------|------|
| TE_Qwen_Image_2_1_Prompt_Enhancer | VLMPromptEnhancerNode | 功能等价，API 兼容 |
| TE-Speed-VOSR2 | VideoScaleNode | 功能等价，支持 Real-ESRGAN |

---

## 技术参考

- ComfyUI 官方节点开发规范
- Qwen VL 模型开放 API 文档
- Real-ESRGAN 开源项目
