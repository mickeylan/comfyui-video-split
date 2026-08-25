# Wan22/LTX I2V 分段连续性问题 - 调试报告

**日期**: 2026-08-25  
**问题**: 分段生成视频时，后续段落完全乱生成，没有接续

---

## 问题描述

### 现象
- 第一段视频：✅ 正常按照提供的图片生成
- 第二段及之后：❌ 完全 AI 乱生成，与第一段没有任何关联
- 预期行为：第二段应接续第一段末尾，第三段接续第二段末尾

### 影响版本
- `wan22_unlimited_nodes.py` - Wan22UnlimitedSampler
- `ltxv_unlimited_nodes.py` - LTXVUnlimitedSampler

---

## 根本原因分析

### 三种视频模型的 I2V 机制对比

| 模型 | I2V 机制 | 条件注入方式 | 需要重新编码? |
|------|-----------|-------------|--------------|
| **MiniMax H3** | `minimax_keyframes` | CLIP 编码 + 显式 frame index | ✅ 需要 |
| **LTX 2.3** | `generated_keyframes` + `concat_latent_image` | VAE 编码 + frame index | ✅ 需要 |
| **Wan22** | `concat_latent_image` | latent 通道拼接 | ❓ 理论上不需要 |

### 核心问题

对于 Wan22 的 I2V 工作流：

1. **Latent 注入**（已正确实现）
   ```python
   # 后续段落 position 0 替换为上一段尾帧
   chunk_video[:, :, :1] = reference_frame
   chunk_video_noise[:, :, :1] = 0  # 零噪声
   video_mask[:, :, :1] = 0        # 不 denoise
   ```

2. **Conditioning 注入**（之前缺失，已修复）
   ```python
   # concat_latent_image position 0 也需要替换
   chunk_image[:, :, :1] = reference_latent[:, :16, :1]
   ```

**问题根因**：后续段落只更新了 latent position 0，但没有更新 `concat_latent_image` 条件。导致模型看到的条件和 latent 不一致：
- Latent position 0 = 上一段尾帧 ✅
- Conditioning position 0 = 原始输入图片 ❌

---

## 修复内容

### 1. Wan22UnlimitedSampler (`wan22_unlimited_nodes.py`)

#### 修复 A: Wrapper Key 匹配

**问题**: `Wan22UnlimitedSampler` 调用 `begin_preview_execution` 时没有指定 `wrapper_key`，导致用了错误的 key，预览不生效。

```python
# 之前（错误）
preview_execution = begin_preview_execution(guider.model_patcher, len(chunks))
# 默认使用 "ltxv_unlimited_preview"

# 现在（正确）
from .preview import begin_preview_execution, WAN22_PREVIEW_WRAPPER_KEY
preview_execution = begin_preview_execution(guider.model_patcher, len(chunks), WAN22_PREVIEW_WRAPPER_KEY)
```

#### 修复 B: Overlap 边界保护

**问题**: 当 chunk 帧数少于 `overlap_steps + 1` 时，`save_len` 会 wrap around 取错误的帧。

```python
# 之前（错误）
save_len = min(overlap_frames // 4 + 1, out_video.shape[2])
saved_frames = out_video[:, :, -save_len:]  # 帧数不足时会取错

# 现在（正确）
save_len = chunk.overlap_steps + 1
if out_video.shape[2] >= save_len:
    saved_frames = out_video[:, :, -save_len:]
else:
    # 帧数不足时，用最后一帧填充
    last_frame = out_video[:, :, -1:]
    saved_frames = torch.cat([last_frame] * save_len, dim=2)
```

#### 修复 C: I2V 参考帧传递到 Conditioning

**问题**: 后续段落只更新了 latent position 0，没有更新 `concat_latent_image` 条件。

新增函数 `_conditioning_for_chunk_with_reference`：

```python
def _conditioning_for_chunk_with_reference(original_conds, video_start, video_end, 
                                         tokens_per_frame, reference_latent):
    """裁剪条件到当前分块的时间范围，并用上一块最后一帧更新 I2V 参考"""
    # ... 处理 generated_keyframes 裁剪 ...
    
    # Handle concat_latent_image for I2V continuity
    concat_image = cond.get("concat_latent_image")
    if torch.is_tensor(concat_image) and concat_image.ndim == 5:
        if concat_image.shape[2] >= video_end:
            chunk_image = concat_image[:, :, video_start:video_end].clone()
            # 替换 position 0 为参考帧（上一块的尾帧）
            if video_start > 0 and reference_latent is not None:
                chunk_image[:, :, :1] = reference_latent[:, :16, :1].to(chunk_image)
            cond["concat_latent_image"] = chunk_image
```

调用处修改：

```python
# 首块：正常裁剪
if chunk.is_first:
    chunk_conds = _conditioning_for_chunk(...)
# 后续块：传入参考帧
else:
    chunk_conds = _conditioning_for_chunk_with_reference(
        ..., reference_frame
    )
```

### 2. LTXVUnlimitedSampler (`ltxv_unlimited_nodes.py`)

同样的 I2V 参考帧传递问题，也已修复。

新增函数 `_conditioning_for_chunk_with_reference`，调用处根据 `chunk.is_first` 判断是否传入参考帧。

---

## 添加的调试日志

为了诊断问题，在 `_conditioning_for_chunk_with_reference` 中添加了详细日志：

```python
# 首块信息
if video_start == 0:
    orig_mean = concat_image[:, :4, :1].mean().item()
    logging.info(f"  [首块] concat_latent_image: shape={...}, pos0 mean={orig_mean:.4f}")

# 后续块替换信息
logging.info(f"  [Chunk N] concat_latent_image: shape={...}, video_start={video_start}")
logging.info(f"  chunk_image after slice: shape={...}, pos0 mean={...:.4f}")
logging.info(f"  Replacing position 0 with reference: ref_shape={...}, ref_pos0_mean={...:.4f}")
logging.info(f"  After replacement: chunk_image pos0 mean={...:.4f}")
```

---

## 测试步骤

### 1. 拉取最新代码

```bash
git pull origin main
```

### 2. 启用调试模式

在 ComfyUI 中使用 Wan22UnlimitedSampler 时：
- 设置 `debug=True`

### 3. 查看控制台日志

关注以下日志输出：

#### 预期正确的日志（首块）
```
[首块] concat_latent_image: shape=[B, C, T, H, W], pos0 mean=0.1234
```

#### 预期正确的日志（后续块）
```
[Chunk N] concat_latent_image: shape=[B, C, T, H, W], video_start=33
  chunk_image after slice: shape=[B, C, T, H, W], pos0 mean=0.1234  # 原始图片的均值
  Replacing position 0 with reference: ref_shape=[B, C, 1, H, W], ref_pos0_mean=0.9876  # 参考帧的均值
  After replacement: chunk_image pos0 mean=0.9876  # 已替换为参考帧
```

#### 问题日志示例

如果 `concat_latent_image` 的 shape 不足以覆盖 `video_end`：
```
WARNING: concat_latent_image has 9 frames, need 41, skipping replacement
```

如果 reference_latent 为 None：
```
  Replacing position 0 with reference: ref_shape=None
```
（说明参考帧没有正确传递）

---

## 关键代码位置

### wan22_unlimited_nodes.py

| 功能 | 行号 | 说明 |
|------|------|------|
| `_conditioning_for_chunk_with_reference` | 196-252 | 新增：带参考帧的条件处理 |
| 调用处 | 604-619 | 根据 `chunk.is_first` 选择函数 |
| overlap 保存逻辑 | 645-657 | 修复后的边界保护 |
| preview wrapper key | 527 | 修复后的 key 传递 |

### ltxv_unlimited_nodes.py

| 功能 | 行号 | 说明 |
|------|------|------|
| `_conditioning_for_chunk_with_reference` | 157-202 | 新增：带参考帧的条件处理 |
| 调用处 | 591-608 | 根据 `chunk.is_first` 选择函数 |

---

## 可能的潜在问题

### 1. concat_latent_image 的 ndim

代码假设 `concat_latent_image` 是 5D `[B, C, T, H, W]`。

如果 ComfyUI 中某些节点的输出是 4D `[B, C, H, W]`，需要添加处理：

```python
if concat_image.ndim == 4:
    # 4D 图像：unsqueeze 到 5D
    concat_image = concat_image.unsqueeze(2)  # [B, C, 1, H, W]
```

### 2. 通道数假设

代码假设 reference_latent 的通道数 >= 16：

```python
ref_frame = reference_latent[:, :16, -1:]
```

如果实际通道数不同，需要调整。

### 3. 后续段落的 prompt

目前我们只处理了 `concat_latent_image`，没有处理：
- `control_video`（控制视频）
- `pose_video_latent`（姿态 latent）
- `camera_conditions`（相机条件）

这些条件目前只是简单裁剪，可能也需要类似处理。

---

## 提交记录

```
d881ee7 - debug: 添加详细日志到 I2V 参考帧替换逻辑
178d1ac - fix: I2V 参考帧传递到 conditioning
63f47e9 - fix: Wan22 I2V 参考帧传递到条件
86e3873 - fix: Wan22 overlap 边界保护
3e84d18 - fix: Wan22UnlimitedSampler preview wrapper key
```

---

## 后续步骤

1. **测试验证**: 在 ComfyUI 中测试分段 I2V 工作流
2. **检查日志**: 确认参考帧正确传递
3. **验证结果**: 检查生成的视频是否正确接续
4. **如有其他问题**: 请提供控制台日志

---

## 相关文件

- `wan22_unlimited_nodes.py` - Wan22 分块采样器
- `ltxv_unlimited_nodes.py` - LTX 分块采样器  
- `preview.py` - 预览系统
- `__init__.py` - 节点注册

---

**备注**: 如果测试后发现问题依然存在，请提供：
1. 完整的控制台日志（从开始到结束）
2. 使用的工作流 JSON（脱敏后）
3. Wan22 模型版本
4. ComfyUI 版本
