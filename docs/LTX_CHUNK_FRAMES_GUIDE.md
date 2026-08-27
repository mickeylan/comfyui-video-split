# LTX 2.3 `chunk_frames` 与外层分段计算

[English](LTX_CHUNK_FRAMES_GUIDE_EN.md) | [返回 README](../README.md)

> 参数名是 `chunk_frames`，不是 `trunk_frames`。

## 1. LTX时间网格

LTX视频帧数必须使用：

```text
像素帧数 = 8 × N + 1
latent时间步 = N + 1
```

合法值包括：

```text
9, 17, 25, 33, 41, 49, 57, 65, 73, 81, 89, 97, ...
```

换算公式：

```text
latent_steps = (pixel_frames - 1) / 8 + 1
pixel_frames = (latent_steps - 1) × 8 + 1
```

## 2. LTXVUnlimitedSampler内部 `chunk_frames`

该参数控制**一次送入扩散模型的最大像素帧数**，不是最终视频总帧数。

后端会向下对齐：

```text
实际chunk_frames = 输入值 - ((输入值 - 1) mod 8)
```

例如：

| 输入 | 实际使用 |
|---:|---:|
| 9 | 9 |
| 16 | 9 |
| 17 | 17 |
| 24 | 17 |
| 25 | 25 |
| 33 | 33 |

因此应直接填写合法的`8N+1`值，避免界面值和实际值不同。

### 内部重叠与输出贡献

相邻内部chunk固定共享1个latent时间步，即8个像素帧区间。拼接时删除后续chunk的这个重复latent步。

若`chunk_frames=17`：

```text
每块采样：17帧等价范围（3个latent时间步）
第1块贡献：17帧
后续每块贡献：16帧
```

81帧示例：

```text
Chunk 1: 17帧，贡献17
Chunk 2: 17帧，贡献16
Chunk 3: 17帧，贡献16
Chunk 4: 17帧，贡献16
Chunk 5: 17帧，贡献16
总计：17 + 16 × 4 = 81
```

内部块数可按下式估算：

```text
总帧数 <= chunk_frames：1块
否则：1 + ceil((总帧数 - chunk_frames) / (chunk_frames - 1))
```

此公式要求总帧数和`chunk_frames`都位于`8N+1`网格。

### 取值建议

| 场景 | 建议值 | 说明 |
|---|---:|---|
| LTX 2.3 720p低显存重绘 | 17 | 当前质量/显存优先基线 |
| 显存非常紧张 | 9 | 块数最多，速度较慢，接缝风险更高 |
| 显存充足、希望减少块数 | 25或33 | 先监控峰值显存 |
| 禁用内部细分 | 大于等于本次输入总帧数的合法值 | 例如161帧输入可设161 |

`chunk_frames`越小，峰值显存通常越低，但采样块数、调度开销和连续性压力越大。它不会增加SIGMAS数量；实际采样步数仍由`SIGMAS长度 - 1`决定。

## 3. 外层LTX视频分段

`LTXVVideoSegmentInfo`用于在外部循环中切原始视频。它与内部`LTXVUnlimitedSampler.chunk_frames`是两个不同层级：

```text
外层segment：控制一次重绘多少原始视频帧
内层chunk：控制一次扩散模型处理多少帧
```

### 外层段长

节点先计算：

```text
requested = round(segment_duration × fps)
frames_per_segment = max(9, floor((requested - 1) / 8) × 8 + 1)
```

即向下对齐到`8N+1`。

例：

```text
fps=16, segment_duration=10秒
requested=160
frames_per_segment=floor(159/8)×8+1=153
```

如果希望精确得到161帧，应使`round(segment_duration × fps)`至少为161，例如16 FPS下使用`161/16 = 10.0625秒`。

### 外层重叠

```text
实际overlap = max(1, floor((overlap_frames - 1) / 8) × 8 + 1)
stride = frames_per_segment - actual_overlap
```

合法重叠值同样是：

```text
1, 9, 17, 25, 33, ...
```

默认`overlap_frames=17`。后续段保存时会裁掉重复的17帧。必须满足：

```text
overlap_frames < frames_per_segment
```

外层总段数：

```text
总帧数 <= frames_per_segment：1段
否则：1 + ceil((总帧数 - frames_per_segment) / stride)
```

最后一段不足时会复制最后一帧补到完整段长；保存阶段使用`valid_frames`裁掉补帧，并裁掉非首段的overlap。

## 4. 推荐组合

720p LTX 2.3重绘建议从以下组合开始：

```text
外层 frames_per_segment：按7–10秒并对齐到8N+1
外层 overlap_frames：17
内层 LTXVUnlimitedSampler chunk_frames：17
progressive_decode：False（使用独立流式解码/保存链时）
```

不要把外层段长和内层`chunk_frames`都设为161后再叠加额外for-loop细分，否则可能造成重复执行、显存上升和质量不稳定。

## 5. 快速检查

- [ ] 总帧数或段长是否为`8N+1`？
- [ ] 内层`chunk_frames`是否为9、17、25、33等合法值？
- [ ] 外层overlap是否为1、9、17、25等合法值？
- [ ] overlap是否小于外层段长？
- [ ] 是否同时存在不必要的外层循环和过大的内层chunk？
- [ ] SIGMAS是否有效，步数是否等于`SIGMAS长度 - 1`？
