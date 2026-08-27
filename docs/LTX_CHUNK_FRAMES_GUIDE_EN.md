# LTX 2.3 `chunk_frames` and Outer Segmentation

[中文](LTX_CHUNK_FRAMES_GUIDE.md) | [Back to README](../README_EN.md)

> The parameter is named `chunk_frames`, not `trunk_frames`.

## 1. LTX temporal grid

LTX video frame counts use:

```text
pixel frames = 8 × N + 1
latent temporal steps = N + 1
```

Valid values include:

```text
9, 17, 25, 33, 41, 49, 57, 65, 73, 81, 89, 97, ...
```

Conversions:

```text
latent_steps = (pixel_frames - 1) / 8 + 1
pixel_frames = (latent_steps - 1) × 8 + 1
```

## 2. Internal `LTXVUnlimitedSampler.chunk_frames`

This is the maximum number of pixel frames sent to the diffusion model at once. It is not the final video length.

The backend aligns the value down:

```text
effective chunk_frames = input - ((input - 1) mod 8)
```

| Input | Effective value |
|---:|---:|
| 9 | 9 |
| 16 | 9 |
| 17 | 17 |
| 24 | 17 |
| 25 | 25 |
| 33 | 33 |

Enter a valid `8N+1` value directly to avoid a mismatch between the UI value and actual execution.

### Internal overlap and contribution

Adjacent chunks share one latent temporal step, equivalent to an eight-frame pixel interval. The repeated latent step is removed when chunks are assembled.

With `chunk_frames=17`:

```text
Each chunk samples a 17-frame equivalent range (3 latent steps)
First chunk contributes 17 frames
Each later chunk contributes 16 frames
```

For 81 frames:

```text
17 + 16 + 16 + 16 + 16 = 81
```

Estimated chunk count:

```text
total_frames <= chunk_frames: 1
otherwise: 1 + ceil((total_frames - chunk_frames) / (chunk_frames - 1))
```

Both values must be on the `8N+1` grid.

### Recommendations

| Scenario | Value | Notes |
|---|---:|---|
| LTX 2.3 720p low-memory redraw | 17 | Current quality/VRAM baseline |
| Extremely limited VRAM | 9 | More chunks, slower, greater seam pressure |
| More VRAM, fewer chunks | 25 or 33 | Monitor peak VRAM first |
| Disable internal subdivision | A valid value at least as large as the input | Use 161 for a 161-frame input |

Smaller chunks generally lower peak VRAM but increase chunk count, scheduling overhead, and continuity pressure. They do not change the sampling-step count; steps remain `SIGMAS length - 1`.

## 3. Outer LTX video segmentation

`LTXVVideoSegmentInfo` slices the source video for an outer loop. This is separate from internal sampler chunking:

```text
outer segment: source frames redrawn per loop iteration
internal chunk: frames processed by diffusion at once
```

### Outer segment length

```text
requested = round(segment_duration × fps)
frames_per_segment = max(9, floor((requested - 1) / 8) × 8 + 1)
```

The length is aligned down to `8N+1`.

Example:

```text
fps=16, segment_duration=10
requested=160
frames_per_segment=floor(159/8)×8+1=153
```

To request exactly 161 frames at 16 FPS, use at least `161/16 = 10.0625` seconds.

### Outer overlap

```text
effective overlap = max(1, floor((overlap_frames - 1) / 8) × 8 + 1)
stride = frames_per_segment - effective overlap
```

Valid overlap values are:

```text
1, 9, 17, 25, 33, ...
```

The default is 17. Later saved segments drop the repeated 17 frames. The overlap must be smaller than the segment length.

Outer segment count:

```text
total_frames <= frames_per_segment: 1
otherwise: 1 + ceil((total_frames - frames_per_segment) / stride)
```

A short final segment is padded by repeating its final frame. The save path uses `valid_frames` to remove padding and removes overlap from non-first segments.

## 4. Recommended combination

Start a 720p LTX 2.3 redraw workflow with:

```text
outer frames_per_segment: 7–10 seconds aligned to 8N+1
outer overlap_frames: 17
internal LTXVUnlimitedSampler chunk_frames: 17
progressive_decode: False when using the separate streaming decode/save chain
```

Avoid combining an outer loop with an unnecessarily large internal chunk such as 161. Nested segmentation configured incorrectly can cause repeated execution, higher memory use, and unstable quality.

## 5. Checklist

- [ ] Is the total or segment length on the `8N+1` grid?
- [ ] Is internal `chunk_frames` one of 9, 17, 25, 33, and so on?
- [ ] Is outer overlap one of 1, 9, 17, 25, and so on?
- [ ] Is overlap smaller than the outer segment length?
- [ ] Are an outer loop and an oversized internal chunk both active unnecessarily?
- [ ] Are SIGMAS valid, with steps equal to `SIGMAS length - 1`?
