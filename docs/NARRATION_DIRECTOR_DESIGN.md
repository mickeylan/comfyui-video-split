# Narration Director 配音导演台

> 更新日期：2026-09-07
> 状态：✅ 已完成开发（v0.10.01）

## 目标

为教学视频提供本地配音时间线。TTS 由现成的 ComfyUI IndexTTS2 节点负责；本插件不加载 TTS 模型、不下载模型、不调用云端接口。

## 工作流

```text
解说词 ───────────────┐
                      ▼
本地 IndexTTS2 ── AUDIO ── Narration Cue ──┐
本地 IndexTTS2 ── AUDIO ── Narration Cue ──┼─ Narration Director ─ AUDIO ─ AudioMerge
本地 IndexTTS2 ── AUDIO ── Narration Cue ──┘
                                              ▲
                                    可选原声或背景音乐
```

## 节点职责

### Narration Cue

把外部 TTS 节点输出的标准 `AUDIO` 与时间线元数据绑定：

- `audio`：连接 IndexTTS2 的 AUDIO 输出
- `text`：解说词标签，不参与 TTS
- `start_time` / `end_time`：时间范围
- `volume`：片段音量
- `cue_id`：可选稳定 ID，用于导演台覆盖时间
- 输出：`NARRATION_CUE`

### Narration Director

通过 `io.Autogrow` 接收任意数量的 Cue，输出一条完整 AUDIO：

- `total_frames`、`fps`：视频时间基准
- `sample_rate`：输出采样率
- `match_mode`
  - `natural`：保持生成语音原始长度
  - `trim`：超出 Cue 结束时间时裁剪
  - `fit`：重采样到 Cue 时间范围
- `cues`：动态 Cue 输入
- `background_audio` / `background_volume`：可选背景轨
- `timeline_data`：前端导演台保存的轻量 JSON；不保存音频数据

输出：

- `audio`：合成配音
- `duration`：视频时长
- `timeline_json`：本次执行使用的时间线

## 前端导演台

`web/js/narration_director.js` 使用 ComfyUI `app.registerExtension` 和 `addDOMWidget`：

- 添加、删除 Cue 覆盖行
- 编辑 ID、起止时间、音量和文本标签
- 可视化时间轴
- 拖动片段调整整体位置
- 工作流只保存 JSON 元数据

Cue 覆盖行必须使用与 `Narration Cue.cue_id` 相同的 ID。未填写 `cue_id` 时，执行阶段按连接顺序生成 `cue_1`、`cue_2` 等 ID。

## 安全与资源边界

- 无网络请求和 HTTP API 路由
- 不保存 base64 或音频文件到工作流
- 最多 1000 个 Cue
- 最大时间线长度 36000 秒
- 校验非有限值、负时间和反向时间段
- 仅支持单个 AUDIO batch；多声道输入在合成边界转为单声道
- 临时张量跟随输入 AUDIO 的设备和 dtype

## 复用

直接复用 `audio_nodes.py` 的 `_audio` 和 `_parts`，保持 ComfyUI AUDIO/LazyAudioMap 兼容。音频定位、重采样和混音由导演台承担，因为它们属于该节点自身的时间线合成职责。

## 文件

- `narration_director.py`：Cue 与导演台节点
- `web/js/narration_director.js`：可视化编辑器
- `__init__.py`：节点映射注册

## 验收清单

- [x] 删除 Edge TTS、云端 API、base64 和 SciPy 路径
- [x] IndexTTS2 通过标准 AUDIO 插口接入
- [x] 动态 Cue 输入
- [x] 时间线验证与边界裁剪
- [x] Python/JavaScript 语法检查
- [ ] 重启 ComfyUI，确认两个节点可搜索
- [ ] 连接实际 IndexTTS2 AUDIO，试听 natural/trim/fit
- [ ] 浏览器保存并重新载入工作流，确认导演台数据恢复
