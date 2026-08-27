# Wan 2.2 / Bernini 两阶段无限采样操作手册

[English](WAN_BERNINI_GUIDE_EN.md) | [返回 README](../README.md)

## 1. 节点与适用范围

| 节点 | 用途 | 输出 |
|---|---|---|
| `Wan22TwoStageSingleChunkSampler` | Wan 2.2 单段 High/Low 基线 | `LATENT` |
| `Wan22TwoStageUnlimitedSampler` | Wan 2.2 I2V 单节点无限续写 | `IMAGE`, `chunk_info` |
| `BerniniTwoStageUnlimitedSampler` | Bernini R2V/V2V/RV2V/ADS2V 分段续写 | `IMAGE`, `chunk_info` |

当前限制：Wan 16 通道视频 latent、8× 空间压缩、batch 1；不支持音频、S2V、HuMo和多流 NestedTensor联合采样。

每段执行顺序固定为：

```text
High采样 → 卸载High → Low采样 → 卸载Low → VAE解码到CPU
```

## 2. Wan 2.2 I2V

### 接线

```text
High模型 ───────────────→ high_model
Low模型 ────────────────→ low_model
WanImageToVideo positive → positive
WanImageToVideo negative → negative
WanImageToVideo latent ─→ latent_image
Wan VAE ────────────────→ vae
可选CLIP Vision输出 ────→ clip_vision_output
frames ────────────────→ VHS Video Combine等保存节点
```

保持原工作流的 `steps`、`cfg`、`sampler_name`、`scheduler`、High/Low step范围、seed和LoRA不变。

节点会完成：首段使用原始I2V任务；解码最后一帧；后续段用该像素帧重建新的原生 `WanImageToVideo` 任务；删除重复边界帧并在CPU拼接。

### 建议

- `chunk_frames=49`作为常用起点；显存更紧张时尝试33。
- 总帧数和分段帧数使用`1+4N`，例如33、49、81、113、161。
- 先用33或49帧验证单段，再测试81帧以上。

## 3. Bernini

### 3.1 SIGMAS与采样器

```text
BasicScheduler
  └─ SIGMAS → SplitSigmas
                 ├─ high_sigmas → 节点 high_sigmas
                 └─ low_sigmas  → 节点 low_sigmas
KSamplerSelect ─────────────────→ sampler
```

官方4步常用配置：

```text
BasicScheduler: scheduler=simple, steps=4, denoise=1.0
SplitSigmas: step=2
high_add_noise=true
low_add_noise=false
high_cfg/low_cfg=保持官方值
```

SIGMAS决定实际采样步数；节点不会在内部重新生成scheduler。

### 3.2 R2V：参考图生视频

```text
Bernini Studio positive/negative → 节点 positive/negative
参考图1 → image0
参考图2 → image1
...
参考图8 → image7
source_video留空
reference_video留空
```

规则：

1. `image0`–`image7`顺序必须和Bernini Studio及提示词中的`image0`、`image1`完全一致。
2. 不要只连接提示词使用的部分图片；应复现官方成功任务使用的全部参考图。
3. `width`、`height`和`ref_max_size`必须与官方成功的单段任务一致。
4. `reference_images`是旧版batch兼容输入；新工作流优先使用显式`image0`–`image7`。

### 3.3 视频任务

- V2V：连接`source_video`。
- RV2V：连接`source_video`及`image0`–`image7`。
- ADS2V：连接`source_video`及`reference_video`；需要时再连接参考图。

视频会按当前chunk切片；短于目标段时以最后一帧补齐。每段重新执行原生 `BerniniConditioning`，避免将完整时长context直接套到短latent。

### 3.4 续接

后续段保留所有原始参考图，并在仍有参考槽位时把上一段最后像素帧作为末尾参考流。它是软连续参考，不等同于Wan I2V的首帧硬锚定。

## 4. 参数表

| 参数 | 建议/说明 |
|---|---|
| `width`, `height` | 与官方成功任务一致，16的倍数 |
| `total_frames` | 总输出帧数，必须为`1+4N` |
| `chunk_frames` | 每段帧数，默认49，必须按`1+4N`理解 |
| `ref_max_size` | 与Bernini Studio成功任务一致 |
| `high_sigmas`, `low_sigmas` | 直接来自同一个`SplitSigmas` |
| `high_noise_seed`, `low_noise_seed` | 保持官方工作流设置 |
| `high_cfg`, `low_cfg` | 分别匹配官方High/Low SamplerCustom |

## 5. 验证顺序

1. 重启ComfyUI并强制刷新浏览器。
2. 节点schema变化后删除旧节点实例并重新添加，避免widget值错位。
3. 用`total_frames=chunk_frames=49`测试单段。
4. 将同一seed、模型、LoRA、SIGMAS、CFG、尺寸和参考输入与官方单段结果对比。
5. 单段正常后测试81帧，再测试113/161帧。
6. 检查人物、服装、背景、颜色和亮度是否从第二段开始漂移。

## 6. 排错

### 画面雪花

- 确认`high_add_noise=true`、`low_add_noise=false`。
- 确认High/Low模型与`high_sigmas/low_sigmas`没有接反。
- 确认两个SIGMAS来自同一个scheduler的`SplitSigmas`。

### 人物换人或肢体异常

- 对照官方任务逐一检查`image0`–`image7`，不要遗漏或改变顺序。
- 检查提示词里的`imageN`是否对应同一个插槽。
- 检查尺寸和`ref_max_size`是否与官方单段不同。
- 先禁用长分段，用49帧单段比较；第一段已错误时不要继续调续接参数。

### 参数验证出现字符串错位

这是旧节点schema缓存。重启ComfyUI、强制刷新、删除旧节点并重新添加。

## 7. 已删除节点

以下旧节点不再注册：

```text
Wan22UnlimitedSampler
Wan22LowNoiseUnlimitedSampler
Wan22HighNoiseUnlimitedSampler
```

它们不能可靠保持Bernini多参考流语义，请迁移到上述两个两阶段Unlimited节点。
