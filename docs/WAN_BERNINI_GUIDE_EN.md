# Wan 2.2 / Bernini Two-Stage Unlimited Sampling Guide

[中文](WAN_BERNINI_GUIDE.md) | [Back to README](../README_EN.md)

## 1. Nodes and scope

| Node | Purpose | Output |
|---|---|---|
| `Wan22TwoStageSingleChunkSampler` | Single-segment Wan 2.2 High/Low baseline | `LATENT` |
| `Wan22TwoStageUnlimitedSampler` | Internal unlimited Wan 2.2 I2V continuation | `IMAGE`, `chunk_info` |
| `BerniniTwoStageUnlimitedSampler` | Chunked Bernini R2V/V2V/RV2V/ADS2V continuation | `IMAGE`, `chunk_info` |

Current scope: 16-channel Wan video latents, 8× spatial compression, and batch size 1. Audio, S2V, HuMo, and joint multi-stream NestedTensor sampling are not supported.

Every segment runs:

```text
High sample → unload High → Low sample → unload Low → VAE decode to CPU
```

## 2. Wan 2.2 I2V

### Wiring

```text
High model ───────────────→ high_model
Low model ────────────────→ low_model
Wan Image To Video (Low Memory) positive ─→ positive
Wan Image To Video (Low Memory) negative ─→ negative
Wan Image To Video (Low Memory) latent ───→ latent_image
Wan VAE ──────────────────→ vae
Optional CLIP Vision ─────→ clip_vision_output
frames ───────────────────→ VHS Video Combine or another saver
```

Keep the original workflow's `steps`, `cfg`, `sampler_name`, `scheduler`, High/Low step ranges, seed, and LoRAs unchanged.

At 1080p, replace the official `WanImageToVideo` with `Wan Image To Video (Low Memory)`. It constructs conditioning frames on CPU and performs spatial/temporal tiled VAE encode before sampling. Recommended encode settings are `tile=256`, `overlap=64`, `temporal=5`, and `temporal_overlap=1`.

The unlimited sampler uses this low-memory I2V task for segment one and the same tiled encode path when rebuilding later segments, removes duplicate boundary frames, and assembles CPU images.

### Recommendations

- Start with `chunk_frames=49`; try 33 when VRAM is tighter.
- Use the `1+4N` frame grid, such as 33, 49, 81, 113, or 161.
- Validate 33 or 49 frames before running 81 frames or more.

## 3. Bernini

### 3.1 SIGMAS and sampler

```text
BasicScheduler
  └─ SIGMAS → SplitSigmas
                 ├─ high_sigmas → node high_sigmas
                 └─ low_sigmas  → node low_sigmas
KSamplerSelect ─────────────────→ sampler
```

Typical official four-step setup:

```text
BasicScheduler: scheduler=simple, steps=4, denoise=1.0
SplitSigmas: step=2
high_add_noise=true
low_add_noise=false
high_cfg/low_cfg=match the official workflow
```

SIGMAS define the actual sampling steps. The node does not generate another scheduler internally.

### 3.2 R2V: reference images to video

```text
Bernini Studio positive/negative → node positive/negative
First reference  → image0
Second reference → image1
...
Eighth reference → image7
Leave source_video empty
Leave reference_video empty
```

Rules:

1. Keep `image0`–`image7` in exactly the same order as Bernini Studio and the prompt.
2. Reproduce every reference used by the known-good official task; do not connect only a subset.
3. Keep `width`, `height`, and `ref_max_size` identical to the known-good single-segment task.
4. `reference_images` is a legacy batch compatibility input. Prefer explicit `image0`–`image7` inputs for new workflows.

### 3.3 Video tasks

- V2V: connect `source_video`.
- RV2V: connect `source_video` plus `image0`–`image7`.
- ADS2V: connect `source_video` and `reference_video`, plus references when required.

Videos are sliced for each chunk and padded with their final frame when short. Native `BerniniConditioning` is rebuilt per segment instead of applying full-duration context streams to a shorter target latent.

### 3.4 Continuation

Later segments retain all original references. When a reference slot is available, the previous segment's final decoded frame is appended as the last reference stream. This is soft continuity guidance, not a hard first-frame anchor like Wan I2V.

## 4. Low-memory tiled VAE decode

Both Wan and Bernini unlimited nodes default to spatial and temporal tiled decode. This changes only VAE decoding; it does not change models, LoRAs, seeds, sampler, scheduler, SIGMAS, or sampled latents.

Start 1080p low-memory decoding with:

```text
tiled_decode = true
vae_tile_size = 256
vae_tile_overlap = 64
vae_temporal_size = 2
vae_temporal_overlap = 1
```

With more VRAM, increase `vae_tile_size` to 512 and `vae_temporal_size` to 3 or 4 to reduce decode time. The following must hold:

```text
vae_tile_overlap < vae_tile_size
vae_temporal_overlap < vae_temporal_size
```

Spatial tile values are pixels and are converted through Wan VAE's 8× compression. Temporal values are latent temporal steps.

Disabling `tiled_decode` restores full `vae.decode()`, which may run out of VRAM on long 1080p segments.

## 5. Parameters

| Parameter | Recommendation |
|---|---|
| `width`, `height` | Match the known-good official task; multiples of 16 |
| `total_frames` | Exact final frame count on the `1+4N` grid |
| `chunk_frames` | Per-segment frame count; default 49 |
| `ref_max_size` | Match the known-good Bernini Studio task |
| `high_sigmas`, `low_sigmas` | Use outputs from the same `SplitSigmas` node |
| `high_noise_seed`, `low_noise_seed` | Match the official workflow |
| `high_cfg`, `low_cfg` | Match the two official `SamplerCustom` stages |
| `tiled_decode` | Enabled by default; keep enabled for 1080p |
| `vae_tile_size/overlap` | Defaults to 256/64 pixels |
| `vae_temporal_size/overlap` | Defaults to 2/1 latent temporal steps |

## 6. Validation order

1. Restart ComfyUI and hard-refresh the browser.
2. After schema changes, delete and recreate the node to avoid shifted widget values.
3. Test one segment with `total_frames=chunk_frames=49`.
4. Compare against the official one-segment path using identical seeds, models, LoRAs, SIGMAS, CFG, dimensions, and references.
5. After the baseline passes, test 81 frames, then 113/161.
6. Check whether identity, clothing, background, color, or brightness drifts after segment two.

## 7. Troubleshooting

### Snow or noisy output

- Verify `high_add_noise=true` and `low_add_noise=false`.
- Verify High/Low models and `high_sigmas/low_sigmas` are not swapped.
- Feed both SIGMAS from one scheduler through `SplitSigmas`.

### Identity changes or malformed limbs

- Compare `image0`–`image7` against the official task; do not omit or reorder references.
- Ensure every `imageN` mentioned by the prompt maps to the same slot.
- Match dimensions and `ref_max_size` to the official baseline.
- Test 49 frames first. If segment one is already wrong, do not tune continuation parameters.

### Validation reports shifted strings or numbers

The workflow contains an old cached node schema. Restart ComfyUI, hard-refresh, delete the old node, and add it again.

## 8. Removed nodes

These legacy nodes are no longer registered:

```text
Wan22UnlimitedSampler
Wan22LowNoiseUnlimitedSampler
Wan22HighNoiseUnlimitedSampler
```

They could not preserve Bernini multi-reference semantics reliably. Migrate workflows to the two-stage unlimited nodes documented above.
