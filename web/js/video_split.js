import { app } from "../../scripts/app.js";

/**
 * ComfyUI Video Split Extension
 * 
 * Provides custom UI enhancements for video split nodes with i18n support.
 */

// 语言包
const LANGUAGES = {
    "en": {
        "VideoSegmentInfo": {
            "title": "Video Segment Info",
            "short_desc": "Calculate segment information for video splitting",
            "Inputs": {
                "images": "Frame tensor, connect to VHS Load Video's image output",
                "fps": "Video frame rate, used to calculate frames per segment by duration",
                "split_mode": "Split mode: by_duration splits by time, by_frames splits by frame count",
                "segment_duration": "Duration of each segment in seconds",
                "segment_frames": "Number of frames per segment",
            },
            "Outputs": {
                "total_segments": "Total number of segments",
                "total_frames": "Total number of frames",
                "frames_per_segment": "Frames per segment",
            },
        },
        "GetVideoSegment": {
            "title": "Get Video Segment",
            "short_desc": "Extract a video segment by index",
            "Inputs": {
                "images": "Frame tensor from VHS Load Video",
                "segment_index": "Segment index (0-based)",
                "frames_per_segment": "Frames per segment",
            },
            "Outputs": {
                "segment_images": "Current segment's frame tensor",
                "segment_frame_count": "Number of frames in segment",
                "start_frame": "Starting frame index",
            },
        },
        "VideoSplitMultiple": {
            "title": "Video Split (Multiple)",
            "short_desc": "Split video into all segments at once",
            "Inputs": {
                "images": "Frame tensor from VHS Load Video",
                "split_mode": "Split mode",
                "fps": "Video frame rate",
                "segment_duration": "Duration per segment (seconds)",
                "segment_frames": "Frames per segment",
            },
            "Outputs": {
                "segments": "List of frame tensors",
                "total_segments": "Total segments",
            },
        },
        "MergeVideoSegments": {
            "title": "Merge Video Segments",
            "short_desc": "Merge segments into single video",
            "Inputs": {
                "segments": "Frame tensor segments to merge",
            },
            "Outputs": {
                "merged_images": "Merged frame tensor",
                "total_frames": "Total frames",
            },
        },
        "ImageCollect": {
            "title": "Image Collect",
            "short_desc": "Collect images in a loop",
            "Inputs": {
                "new_images": "Images to add",
                "images": "Previously accumulated images",
            },
            "Outputs": {
                "accumulated": "Accumulated frames",
                "total_frames": "Total frame count",
            },
        },
    },
    "zh": {
        "VideoSegmentInfo": {
            "title": "视频分段信息",
            "short_desc": "计算视频分段数量，配合循环节点使用",
            "Inputs": {
                "images": "帧张量，连接 VHS Load Video 的 image 输出",
                "fps": "视频帧率，用于计算按时长分段的帧数",
                "split_mode": "分段模式：by_duration 按时长，by_frames 按帧数",
                "segment_duration": "每段时长（秒）",
                "segment_frames": "每段帧数",
            },
            "Outputs": {
                "total_segments": "总分段数",
                "total_frames": "视频总帧数",
                "frames_per_segment": "每段帧数",
            },
        },
        "GetVideoSegment": {
            "title": "获取视频分段",
            "short_desc": "按索引提取单个视频分段",
            "Inputs": {
                "images": "帧张量，连接 VHS Load Video",
                "segment_index": "分段索引（从0开始）",
                "frames_per_segment": "每段帧数",
            },
            "Outputs": {
                "segment_images": "当前分段的帧张量",
                "segment_frame_count": "当前分段帧数",
                "start_frame": "起始帧索引",
            },
        },
        "VideoSplitMultiple": {
            "title": "视频分段（批量）",
            "short_desc": "一次性分割视频为所有分段",
            "Inputs": {
                "images": "帧张量",
                "split_mode": "分段模式",
                "fps": "帧率",
                "segment_duration": "每段时长",
                "segment_frames": "每段帧数",
            },
            "Outputs": {
                "segments": "分段列表",
                "total_segments": "总分段数",
            },
        },
        "MergeVideoSegments": {
            "title": "合并视频分段",
            "short_desc": "将多个分段合并为单个视频",
            "Inputs": {
                "segments": "要合并的分段",
            },
            "Outputs": {
                "merged_images": "合并后的帧张量",
                "total_frames": "总帧数",
            },
        },
        "ImageCollect": {
            "title": "图像收集",
            "short_desc": "在循环中收集图像帧",
            "Inputs": {
                "new_images": "要添加的图像",
                "images": "之前累积的图像",
            },
            "Outputs": {
                "accumulated": "累积的帧",
                "total_frames": "总帧数",
            },
        },
    },
};

// 支持的中文区域设置
const SUPPORTED_ZH_LOCALES = ['zh-CN', 'zh-TW', 'zh-HK', 'zh'];

function getLocale() {
    return localStorage['Comfy.Settings.Comfy.Locale'] || localStorage['Comfy.Locale'] || 'en';
}

function getLangCode(locale) {
    if (!locale) return 'en';
    if (SUPPORTED_ZH_LOCALES.some(zh => locale.startsWith('zh'))) return 'zh';
    if (locale.startsWith('ja')) return 'ja';
    if (locale.startsWith('ko')) return 'ko';
    return 'en';
}

function short_desc(desc) {
    return `<div id=VHS_shortdesc>${desc}</div>`;
}

function as_html(entry, depth = 0) {
    if (typeof entry === 'object' && !Array.isArray(entry)) {
        const size = depth < 2 ? 0.8 : 1;
        let html = '';
        for (const k in entry) {
            const name = k.replace('_collapsed', '');
            html += `<div vhs_title="${name}" style="display: flex; font-size: ${size}em" class="VHS_collapse"><div style="color: #AAA; height: 1.5em;">[<span style="font-family: monospace">-</span>]</div><div style="width: 100%">${name}: ${as_html(entry[k], depth + 1)}</div></div>`;
        }
        return html;
    }
    if (Array.isArray(entry)) {
        const size = depth === 0 ? 0.8 : 1;
        let html = entry[0];
        for (let i = 1; i < entry.length; i++) {
            html += `<div style="font-size: ${size}em">${as_html(entry[i], depth)}</div>`;
        }
        return html;
    }
    return String(entry);
}

function buildNodeDescription(nodeId, lang) {
    const langPack = LANGUAGES[lang] || LANGUAGES['en'];
    const texts = langPack[nodeId];
    if (!texts) return null;

    const entry = [texts.title, short_desc(texts.short_desc), {}];
    if (texts.Inputs) entry[2]['Inputs'] = texts.Inputs;
    if (texts.Outputs) entry[2]['Outputs'] = texts.Outputs;
    return as_html(entry);
}

function updateDescriptions() {
    const locale = getLocale();
    const lang = getLangCode(locale);
    
    // 更新节点描述
    const nodeIds = Object.keys(LANGUAGES[lang] || LANGUAGES['en']);
    for (const nodeId of nodeIds) {
        const nodeClass = LiteGraph.registered_node_types?.[nodeId];
        if (nodeClass) {
            nodeClass.DESCRIPTION = buildNodeDescription(nodeId, lang);
        }
    }
}

app.registerExtension({
    name: "comfyui-video-split",
    
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        // 设置节点颜色
        if (nodeData.name.includes("Video") || nodeData.name.includes("Image Collect")) {
            const onNodeCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                const r = onNodeCreated ? onNodeCreated.apply(this, arguments) : undefined;
                this.color = "#2d5a27";
                return r;
            };
        }
    },
    
    async setup(app) {
        // 监听语言变化
        if (app.ui?.settings?.settingsLookup?.['Comfy.Locale']) {
            const originalOnChange = app.ui.settings.settingsLookup['Comfy.Locale'].onChange;
            app.ui.settings.settingsLookup['Comfy.Locale'].onChange = function(is_now, was_before) {
                updateDescriptions();
                if (originalOnChange) return originalOnChange.apply(this, arguments);
            };
        }
        
        // 初始化时更新一次
        setTimeout(updateDescriptions, 1000);
        
        console.log("[Video Split] Extension loaded with i18n support");
    },
});