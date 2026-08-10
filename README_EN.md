# ComfyUI Video Split Nodes

[中文文档](README.md)

Video segmentation nodes for splitting long videos by duration or frame count, designed to work with loop nodes for segment-by-segment processing.

## Installation

Place the `comfyui-video-split` folder into the `custom_nodes/` directory and restart ComfyUI.

## Nodes

| Node | Description |
|------|-------------|
| **Video Segment Info** | Calculate segment information |
| **Get Video Segment** | Extract a single segment by index |
| **Video Split (Multiple)** | Split video into all segments at once |
| **Merge Video Segments** | Merge multiple segments |
| **Image Collect** | Collect images in a loop |

## Node Details

### Video Segment Info

Calculate video segment information for use with loop nodes.

**Inputs:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| images | IMAGE | - | Frame tensor (connect to VHS Load Video's image output) |
| fps | FLOAT | 24.0 | Video frame rate |
| split_mode | Choice | by_duration | Split mode: by_duration (by time) or by_frames (by frame count) |
| segment_duration | FLOAT | 5.0 | Duration of each segment in seconds |
| segment_frames | INT | 120 | Number of frames per segment |

**Outputs:**
| Output | Type | Description |
|---------|------|-------------|
| total_segments | INT | Total number of segments |
| total_frames | INT | Total frame count |
| frames_per_segment | INT | Frames per segment |

---

### Get Video Segment

Extract a specific segment by index, designed for use with loop nodes.

**Inputs:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| images | IMAGE | - | Frame tensor (connect to VHS Load Video's image output) |
| segment_index | INT | 0 | Segment index (0-based) |
| frames_per_segment | INT | 120 | Frames per segment (from Video Segment Info) |

**Outputs:**
| Output | Type | Description |
|---------|------|-------------|
| segment_images | IMAGE | Current segment's frame tensor |
| segment_frame_count | INT | Frame count in current segment |
| start_frame | INT | Starting frame index |

---

### Video Split (Multiple)

Split video into all segments at once, output as a list.

**Inputs:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| images | IMAGE | - | Frame tensor |
| split_mode | Choice | by_duration | Split mode |
| fps | FLOAT | 24.0 | Video frame rate |
| segment_duration | FLOAT | 5.0 | Duration per segment (seconds) |
| segment_frames | INT | 120 | Frames per segment |

**Outputs:**
| Output | Type | Description |
|---------|------|-------------|
| segments | IMAGE (list) | List of segment frame tensors |
| total_segments | INT | Total segment count |

---

### Merge Video Segments

Merge multiple video segments into a single video.

**Inputs:**
| Parameter | Type | Description |
|-----------|------|-------------|
| segments | IMAGE (list) | Frame tensor segments to merge |

**Outputs:**
| Output | Type | Description |
|---------|------|-------------|
| merged_images | IMAGE | Merged frame tensor |
| total_frames | INT | Total frame count |

---

### Image Collect

Collect image frames in a for loop.

**Features:**
- ✅ Smart type detection: automatically identifies tensor or list inputs
- ✅ Compatible with different loop node output types

**Inputs:**
| Parameter | Type | Description |
|-----------|------|-------------|
| new_images | IMAGE | Images to add from current iteration |
| images | IMAGE (optional) | Previously accumulated images. Leave empty for first iteration |

**Outputs:**
| Output | Type | Description |
|---------|------|-------------|
| accumulated | IMAGE | Accumulated frames |
| total_frames | INT | Current total frame count |

---

## Workflow Example

### Using with VHS Load Video and for loop nodes

Requires `comfyui-easy-use` plugin's `forLoopStart` and `forLoopEnd` nodes.

```
VHS Load Video ──┬──→ Video Segment Info ──→ forLoopStart(total)
   (image output) │            │                       │
                 │            │ total_segments        │ index
                 │            ▼                       ▼
                 │     forLoopStart            forLoopStart
                 │            │                       │
                 │            │ index                 │
                 │            ▼                       │
                 └──→ Get Video Segment ←────────────┘
                           │
                     segment_images
                           │
                           ▼
                     [Upscale Processing]
                           │
                        IMAGE
                           │
                           ▼
                     Image Collect ←──┐
                     (accumulated) ────┘ (pass to next iteration)
                           │
                     forLoopEnd
                           │
                        value1
                           │
                           ▼
                     VHS_VideoCombine
                           │
                           ▼
                      Final Video
```

### Important: Connecting the images Input

**Video Segment Info and Get Video Segment must connect to the same images source!**

```
                    ┌──→ Video Segment Info's images input
VHS Load Video ─────┤
     (image output)  └──→ Get Video Segment's images input
```

**Why:**
- `Video Segment Info` needs the frame tensor to calculate total frames and segment info
- `Get Video Segment` needs the frame tensor to slice and extract the current segment
- Both must use the same data source, otherwise segment indices won't match

### Connection Steps

1. `VHS Load Video` **image** output → `Video Segment Info` **images** input
2. `VHS Load Video` **image** output → `Get Video Segment` **images** input (⚠️ same source)
3. `Video Segment Info` **total_segments** → `forLoopStart` **total**
4. `Video Segment Info` **frames_per_segment** → `Get Video Segment` **frames_per_segment**
5. `forLoopStart` **index** → `Get Video Segment` **segment_index**
6. `Get Video Segment` **segment_images** → Upscale processing node
7. `forLoopStart` **value1** → `Image Collect` **images** (⚠️ must connect value1, not initial_value1)
8. `Image Collect` **accumulated** → `forLoopEnd` **initial_value1**
9. `forLoopEnd` **value1** → `VHS_VideoCombine` **images**

### ⚠️ Most Common Wiring Mistake

**Wrong**: `forLoopStart.initial_value1` → `Image Collect.images`
- Result: Each iteration receives empty value, only last frame saved

**Correct**: `forLoopStart.value1` → `Image Collect.images`
- Result: Accumulated results passed correctly

**Reason**:
- `initial_value1` = Initial value when loop starts (empty on first iteration)
- `value1` = Current value passed to loop body (includes accumulated results)

---

## Segmentation Logic

### By Duration

Example: 8-second video (24fps = 192 frames), 5 seconds per segment (120 frames)

| Segment Index | Start Frame | End Frame | Frames | Duration |
|--------------|-------------|-----------|--------|----------|
| 0 | 0 | 120 | 120 | 5s |
| 1 | 120 | 192 | 72 | 3s |

Total segments: `(192 + 120 - 1) // 120 = 2`

### By Frame Count

Example: 300-frame video, 100 frames per segment

| Segment Index | Start Frame | End Frame | Frames |
|--------------|-------------|-----------|--------|
| 0 | 0 | 100 | 100 |
| 1 | 100 | 200 | 100 |
| 2 | 200 | 300 | 100 |

Total segments: `(300 + 100 - 1) // 100 = 3`

---

## Use Cases

- Long video upscaling (process in segments to avoid OOM)
- Batch processing video clips
- Video segment denoising/enhancement
- Extract video clips by fixed duration

---

## Requirements

- ComfyUI
- `comfyui-easy-use` plugin (for loop nodes)
- `comfyui-videohelpersuite` plugin (for VHS Load Video)

---

## Version

- v0.1.0 - Initial release with video segmentation, loop collection, and i18n help documentation