# Wan 2.2 无限分段采样器开发计划

## 目标

在单个 ComfyUI 节点内部按时间分块执行 Wan 2.2 双模型采样：

```text
Chunk 1: High → 卸载 High → Low → 保存上下文
Chunk 2: High → 卸载 High → Low → 保存上下文
...
```

保持用户现有工作流简单，保留用户控制的采样参数，并借鉴 MiniMax H3 Unlimited Sampler 的全局噪声、分块规划、上下文延续、重复区裁剪、状态恢复和预览生命周期设计。

明确排除：

- S2V
- HuMo
- `audio_embed`
- 音频同步
- NestedTensor 多流输入

## 阶段一：清理错误方向，恢复可靠基线

1. 撤销尚未提交的外部循环辅助节点：
   - `Wan22I2VChunkPlan`
   - `Wan22I2VChunkPrepare`
   - `Wan22I2VChunkContinue`
2. 保留独立 High/Low 节点作为行为基准。
3. 保留已确认必要的 conditioning 时间切片修复。
4. 保存当前工作流备份。
5. 不提交、不推送，直到真实推理通过。

验收：

- 33 帧单段正常；
- 49 帧不再出现 `10 vs 13` shape 报错；
- 插件编译和节点注册正常。

## 阶段二：建立可测试的单段参考实现

先不分块，实现新的内部调度节点，只处理一个 chunk：

```text
完整 LATENT
→ High 采样
→ 显式释放 High 模型
→ Low 采样
→ 输出
```

必须与原生双 `KSamplerAdvanced` 保持相同：

- 模型及模型补丁；
- conditioning；
- noise 和 seed；
- steps、CFG、sampler、scheduler；
- High/Low 起止步；
- leftover noise；
- LATENT 元数据和 mask。

模型生命周期：

```python
high_output = sample_high(...)
comfy.model_management.unload_model_and_clones(high_model)

low_output = sample_low(high_output)
comfy.model_management.unload_model_and_clones(low_model)
```

### 验收门槛

固定相同 seed，对 33 帧分别运行：

```text
A：原生 High KSamplerAdvanced → Low KSamplerAdvanced
B：新节点单段 High → Low
```

要求：

- High 输出张量统计一致；
- Low 输入与 High 输出一致；
- Low 最终输出统计一致；
- 最终视频视觉一致；
- 第一段不能模糊、花屏或脱离参考图。

未通过此门槛，不进入分块开发。

## 阶段三：实现全局分块基础

一次性进行全局准备：

```python
fixed_latent = comfy.sample.fix_empty_latent_channels(...)
full_noise = comfy.sample.prepare_noise(full_latent, seed, batch_index)
plan = _chunk_plan(...)
```

每段只从完整噪声中切片：

```python
chunk_noise = full_noise[:, :, start:end]
```

禁止每段根据局部 shape 重新生成噪声，以免相同 seed 下的全局噪声轨迹发生变化。

分块规则：

- `chunk_frames` 遵循 Wan 的 `1 + 4N` 帧网格；
- `overlap_frames` 按 4 像素帧对齐；
- 第一段没有前置 overlap；
- 后续段包含固定 overlap；
- oversized overlap 必须按当前 chunk 可用长度钳制；
- 最终输出 latent 时间长度必须与原输入一致。

覆盖测试：

- 33 帧单块；
- 49 帧；
- 81 帧；
- 113 帧；
- `overlap_frames=0`；
- overlap 大于可用长度；
- 最后一段短于标准 chunk。

## 阶段四：实现每段完整 High → Low

内部循环：

```python
for chunk in chunks:
    构造当前段 latent、noise 和 conditioning

    high_output = sample_high(...)
    unload_high()

    low_output = sample_low(high_output)
    unload_low()

    保存 Low 最终输出尾部
    裁掉重复 overlap
    累积输出
```

关键约束：

- High 中间结果不得作为下一时间段参考；
- 下一时间段只能使用当前段 Low 完成结果；
- Low 阶段禁止重新加噪；
- High 和 Low 使用用户提供的全部参数；
- 不写死步数、切换点或 sigma 范围；
- 中间阶段不得强制 sigma 归零；
- 保持 LoRA、ModelSamplingSD3、hooks、model patches 和 `wanBlockSwap` 行为。

## 阶段五：实现 Wan 专用跨段上下文

后续段需要同步构造三类数据。

### 1. Latent 上下文

```text
chunk_latent 前 overlap_steps
= 上一段 Low 最终输出尾部
```

### 2. Noise mask

```text
overlap 区域 = 0
新生成区域   = 1
```

### 3. Wan I2V conditioning

局部张量长度必须与当前 chunk 一致：

```text
concat_latent_image.shape[2] == chunk_latent.shape[2]
concat_mask.shape[2] == chunk_latent.shape[2]
```

后续段局部条件：

```text
concat_latent_image:
  overlap 区域 = 上一段完成结果对应的参考
  新区域       = 当前段原始 conditioning 切片

concat_mask:
  overlap 区域 = 0
  新区域       = 1
```

不得猜测或截取通道。如果 Low latent 与 `concat_latent_image` 的语义或通道不兼容，必须使用同一 VAE：

```text
Low latent 尾部
→ VAE decode
→ VAE encode
→ concat_latent_image
```

第一阶段只支持当前已确认的 16 通道 `WanImageToVideo`、batch 1 路径；其他 Wan/Bernini 路径通过独立验证后再启用。

## 阶段六：提示词遵从设计

借鉴 MiniMax H3 的全局时间范围处理，但不能假定普通 CONDITIONING 能自动保持跨段时间语义。

### 默认兼容模式

继续使用原始 positive/negative conditioning：

- 不改变现有工作流；
- 不重复编码 CLIP；
- 视觉连续性优先；
- 明确属于近似长视频续写，不能宣称与一次性完整采样严格等价。

### 可选时间提示模式

可选输入：

```text
clip
prompt
fps
```

仅在连接这些输入时：

1. 根据 chunk 的全局帧范围计算时间区间；
2. 选择与当前区间重叠的 shot；
3. 将全局时间戳转换为 chunk 局部时间；
4. 重新编码当前段提示词。

建议只支持明确格式，例如：

```text
[Shot 1] At 00:00.000 ...
[Shot 2] At 00:03.000 ...
```

不得对普通自然语言进行不可靠的自动时间解析。

## 阶段七：元数据、预览和异常恢复

最终 LATENT 必须保留：

- `batch_index`；
- `noise_mask`；
- downscale 元数据；
- hooks/patch 相关元数据；
- 其他未知 LATENT 键。

预览要求：

- 始终使用 `WAN22_PREVIEW_WRAPPER_KEY`；
- 每段更新全局帧范围；
- overlap 裁剪后再报告输出范围；
- 异常时关闭 preview execution 并恢复包装状态。

所有临时状态必须使用局部变量，并通过 `try/finally` 恢复：

```python
try:
    ...
finally:
    恢复 conditioning
    关闭 preview
    清理 High/Low 模型加载状态
```

不得把大 Tensor 保存在模块、类、单例或模型长期缓存中。

## 阶段八：验证矩阵

### 静态验证

```bash
python -m py_compile custom_nodes/comfyui-video-split/wan22_unlimited_nodes.py
git -C custom_nodes/comfyui-video-split diff --check
```

### 单段基准

- 33 帧；
- 固定 seed；
- 原生双节点与新节点 A/B 对比；
- 第一段必须正常。

### 两段测试

- 49 帧；
- 每段 conditioning 与 latent shape 一致；
- 第二段不报错；
- 第二段不是花屏；
- 边界没有明显跳变。

### 多段测试

- 81 帧和 113 帧；
- 最终帧数准确；
- overlap 不重复、不丢失；
- 主体、背景和运动能够延续。

### 参数覆盖

- overlap 为 0 和非 0；
- batch 1，之后再评估 batch 2；
- Wan I2V/FL2V；
- Fun Control；
- VACE；
- Bernini/context conditioning；
- preview 正常路径及异常恢复。

继续明确拒绝：

- NestedTensor 多流；
- S2V；
- HuMo；
- `audio_embed`；
- 音频同步。

## 开发顺序与停止条件

每一步只修改一个可验证行为：

1. 撤销外部循环节点；
2. 实现单段 High→Low 生命周期等价；
3. 完成单段 GPU A/B 验证；
4. 加入全局 noise 和 chunk plan；
5. 加入逐段 High→Low 顺序；
6. 加入 latent overlap；
7. 加入 Wan conditioning 重建；
8. 最后处理可选提示词时间切片和 preview。

任何一步真实推理失败，都停止在该步定位，不继续叠加后续功能。成功前不提交、不推送到 `main`。
