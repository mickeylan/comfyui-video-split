"""
国际化文档模块
根据 ComfyUI 的语言设置显示不同语言的节点参数说明
"""

# 语言配置
# ComfyUI 使用 'Comfy.Locale' 或 'Comfy.Settings.Comfy.Locale' 存储语言设置
# 常见值: 'zh-CN' (中文), 'en' (英文), 'ja' (日语), 'ko' (韩语) 等

def short_desc(desc):
    """简短描述样式"""
    return f'<div id=VHS_shortdesc>{desc}</div>'

# 多语言文本
LANGUAGES = {
    "en": {
        "title": "Video Segment Info",
        "short_desc": "Calculate segment information for video splitting",
        "inputs": {
            "images": "Frame tensor, connect to VHS Load Video's image output",
            "fps": "Video frame rate, used to calculate frames per segment by duration. Can be obtained from VHS Video Info",
            "split_mode": "Split mode: by_duration splits by time, by_frames splits by frame count",
            "segment_duration": "Duration of each segment in seconds, used when split_mode=by_duration",
            "segment_frames": "Number of frames per segment, used when split_mode=by_frames",
        },
        "outputs": {
            "total_segments": "Total number of segments, connect to forLoopStart's total input",
            "total_frames": "Total number of frames in the video",
            "frames_per_segment": "Frames per segment, connect to Get Video Segment",
        },
    },
    "zh": {
        "title": "视频分段信息",
        "short_desc": "计算视频分段数量，配合循环节点使用",
        "inputs": {
            "images": "帧张量，连接 VHS Load Video 的 image 输出",
            "fps": "视频帧率，用于计算按时长分段的帧数。可以从 VHS Video Info 获取",
            "split_mode": "分段模式：by_duration 按时长分段，by_frames 按帧数分段",
            "segment_duration": "每段时长（秒），当 split_mode=by_duration 时使用",
            "segment_frames": "每段帧数，当 split_mode=by_frames 时使用",
        },
        "outputs": {
            "total_segments": "总分段数，连接到 forLoopStart 的 total 输入",
            "total_frames": "视频总帧数",
            "frames_per_segment": "每段帧数，连接到 Get Video Segment 的 frames_per_segment",
        },
    },
    "ja": {
        "title": "動画セグメント情報",
        "short_desc": "動画分割のためのセグメント情報を計算",
        "inputs": {
            "images": "フレームテンソル、VHS Load Videoのimage出力に接続",
            "fps": "動画のフレームレート、時間による分割の計算に使用",
            "split_mode": "分割モード：by_durationは時間で分割、by_framesはフレーム数で分割",
            "segment_duration": "各セグメントの長さ（秒）、split_mode=by_durationの時に使用",
            "segment_frames": "各セグメントのフレーム数、split_mode=by_framesの時に使用",
        },
        "outputs": {
            "total_segments": "セグメント総数、forLoopStartのtotalに入力",
            "total_frames": "動画の総フレーム数",
            "frames_per_segment": "セグメントごとのフレーム数",
        },
    },
    "ko": {
        "title": "동영상 세그먼트 정보",
        "short_desc": "동영상 분할을 위한 세그먼트 정보 계산",
        "inputs": {
            "images": "프레임 텐서, VHS Load Video의 image 출력에 연결",
            "fps": "동영상 프레임 속도, 시간 기준 분할 계산에 사용",
            "split_mode": "분할 모드: by_duration은 시간 기준, by_frames는 프레임 수 기준",
            "segment_duration": "각 세그먼트 길이(초), split_mode=by_duration일 때 사용",
            "segment_frames": "각 세그먼트의 프레임 수, split_mode=by_frames일 때 사용",
        },
        "outputs": {
            "total_segments": "총 세그먼트 수, forLoopStart의 total에 연결",
            "total_frames": "동영상의 총 프레임 수",
            "frames_per_segment": "세그먼트당 프레임 수",
        },
    },
}

# 所有节点的文档定义
NODE_DOCS = {
    "VideoSegmentInfo": ["inputs", "outputs"],
    "GetVideoSegment": {
        "en": {
            "title": "Get Video Segment",
            "short_desc": "Extract a video segment by index",
            "inputs": {
                "images": "Frame tensor, connect to VHS Load Video's image output (same source as VideoSegmentInfo)",
                "segment_index": "Segment index (0-based), connect to forLoopStart's index output",
                "frames_per_segment": "Frames per segment, connect to VideoSegmentInfo's frames_per_segment output",
            },
            "outputs": {
                "segment_images": "Current segment's frame tensor, connect to upscaling node",
                "segment_frame_count": "Number of frames in current segment",
                "start_frame": "Starting frame index of current segment",
            },
        },
        "zh": {
            "title": "获取视频分段",
            "short_desc": "按索引提取单个视频分段",
            "inputs": {
                "images": "帧张量，连接 VHS Load Video 的 image 输出（与 VideoSegmentInfo 使用同一个）",
                "segment_index": "分段索引（从0开始），连接 forLoopStart 的 index 输出",
                "frames_per_segment": "每段帧数，连接 VideoSegmentInfo 的 frames_per_segment 输出",
            },
            "outputs": {
                "segment_images": "当前分段的帧张量，连接到放大处理节点",
                "segment_frame_count": "当前分段的帧数",
                "start_frame": "当前分段起始帧索引",
            },
        },
        "ja": {
            "title": "動画セグメント取得",
            "short_desc": "インデックスで動画セグメントを抽出",
            "inputs": {
                "images": "フレームテンソル、VHS Load Videoのimage出力に接続",
                "segment_index": "セグメントインデックス（0始まり）、forLoopStartのindexに接続",
                "frames_per_segment": "セグメントごとのフレーム数",
            },
            "outputs": {
                "segment_images": "現在のセグメントのフレームテンソル",
                "segment_frame_count": "現在のセグメントのフレーム数",
                "start_frame": "現在のセグメントの開始フレームインデックス",
            },
        },
        "ko": {
            "title": "동영상 세그먼트 가져오기",
            "short_desc": "인덱스로 동영상 세그먼트 추출",
            "inputs": {
                "images": "프레임 텐서, VHS Load Video의 image 출력에 연결",
                "segment_index": "세그먼트 인덱스(0부터), forLoopStart의 index에 연결",
                "frames_per_segment": "세그먼트당 프레임 수",
            },
            "outputs": {
                "segment_images": "현재 세그먼트의 프레임 텐서",
                "segment_frame_count": "현재 세그먼트의 프레임 수",
                "start_frame": "현재 세그먼트의 시작 프레임 인덱스",
            },
        },
    },
    "VideoSplitMultiple": {
        "en": {
            "title": "Video Split (Multiple)",
            "short_desc": "Split video into all segments at once",
            "inputs": {
                "images": "Frame tensor, connect to VHS Load Video's image output",
                "split_mode": "Split mode: by_duration or by_frames",
                "fps": "Video frame rate",
                "segment_duration": "Duration of each segment in seconds",
                "segment_frames": "Number of frames per segment",
            },
            "outputs": {
                "segments": "List of frame tensors for all segments",
                "total_segments": "Total number of segments",
            },
        },
        "zh": {
            "title": "视频分段（批量）",
            "short_desc": "一次性分割视频为所有分段",
            "inputs": {
                "images": "帧张量，连接 VHS Load Video 的 image 输出",
                "split_mode": "分段模式：by_duration 或 by_frames",
                "fps": "视频帧率",
                "segment_duration": "每段时长（秒）",
                "segment_frames": "每段帧数",
            },
            "outputs": {
                "segments": "所有分段的帧张量列表",
                "total_segments": "总分段数",
            },
        },
    },
    "MergeVideoSegments": {
        "en": {
            "title": "Merge Video Segments",
            "short_desc": "Merge multiple segments into a single video",
            "inputs": {
                "segments": "List of frame tensor segments to merge (input is a list)",
            },
            "outputs": {
                "merged_images": "Merged frame tensor",
                "total_frames": "Total number of frames",
            },
        },
        "zh": {
            "title": "合并视频分段",
            "short_desc": "将多个分段合并为单个视频",
            "inputs": {
                "segments": "要合并的帧张量分段列表（输入类型为列表）",
            },
            "outputs": {
                "merged_images": "合并后的帧张量",
                "total_frames": "总帧数",
            },
        },
    },
    "ImageCollect": {
        "en": {
            "title": "Image Collect",
            "short_desc": "Collect image frames in a loop",
            "inputs": {
                "new_images": "Image frames to add from current iteration (connect to upscaling output)",
                "images": "(Optional) Previously accumulated frames, connect to previous iteration's accumulated output. Leave empty for first iteration",
            },
            "outputs": {
                "accumulated": "Accumulated frames, connect to forLoopEnd's initial_value1",
                "total_frames": "Current total frame count",
            },
        },
        "zh": {
            "title": "图像收集",
            "short_desc": "在循环中收集图像帧",
            "inputs": {
                "new_images": "当前迭代要添加的图像帧（连接放大处理的输出）",
                "images": "（可选）之前累积的图像帧，连接上一轮的 accumulated 输出。第一次迭代留空",
            },
            "outputs": {
                "accumulated": "累积的图像帧，连接 forLoopEnd 的 initial_value1",
                "total_frames": "当前累积的总帧数",
            },
        },
    },
}


def get_language():
    """获取当前语言设置，默认返回英文"""
    # 这里无法直接访问前端的 localStorage
    # ComfyUI 会在前端处理语言，后端节点默认使用英文
    # DESCRIPTION 会在前端根据 Comfy.Locale 设置显示对应语言
    return "en"


def as_html(entry, depth=0):
    """将说明字典转换为 HTML 格式"""
    if isinstance(entry, dict):
        size = 0.8 if depth < 2 else 1
        html = ''
        for k in entry:
            collapse_single = k.endswith("_collapsed")
            if collapse_single:
                name = k[:-len("_collapsed")]
            else:
                name = k
            collapse_flag = ' VHS_precollapse' if entry.get("collapsed", False) or collapse_single else ''
            html += f'<div vhs_title=\"{name}\" style=\"display: flex; font-size: {size}em\" class=\"VHS_collapse{collapse_flag}\"><div style=\"color: #AAA; height: 1.5em;\">[<span style=\"font-family: monospace\">-</span>]</div><div style=\"width: 100%\">{name}: {as_html(entry[k], depth=depth+1)}</div></div>'
        return html
    if isinstance(entry, list):
        if depth == 0:
            depth += 1
            size = .8
        else:
            size = 1
        html = ''
        html += entry[0]
        for i in entry[1:]:
            html += f'<div style=\"font-size: {size}em\">{as_html(i, depth=depth)}</div>'
        return html
    return str(entry)


def build_description(node_id, lang="en"):
    """构建指定语言的节点说明"""
    if node_id not in NODE_DOCS:
        return None
    
    doc = NODE_DOCS[node_id]
    
    # 如果是多语言字典（如 VideoSegmentInfo）
    if isinstance(doc, list):
        # 使用全局语言包
        if lang not in LANGUAGES:
            lang = "en"
        texts = LANGUAGES[lang]
        entry = [texts["title"], short_desc(texts["short_desc"]), {}]
        for section in doc:
            if section in texts:
                entry[2][section.capitalize()] = texts[section]
        return as_html(entry)
    
    # 如果是节点特定的多语言配置（如 GetVideoSegment）
    if isinstance(doc, dict):
        if lang not in doc:
            lang = "en"
        texts = doc[lang]
        entry = [texts["title"], short_desc(texts["short_desc"]), {}]
        for section in ["inputs", "outputs"]:
            if section in texts:
                entry[2][section.capitalize()] = texts[section]
        return as_html(entry)
    
    return None


def format_descriptions(nodes):
    """将说明应用到节点（默认使用英文，前端会根据语言设置显示）"""
    for node_id in NODE_DOCS:
        if node_id in nodes:
            # 后端设置默认英文说明，前端可以根据语言切换
            nodes[node_id].DESCRIPTION = build_description(node_id, "en")