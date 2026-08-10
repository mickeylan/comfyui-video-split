import { app } from "../../scripts/app.js";
import { ComfyWidgets } from "../../scripts/widgets.js";

/**
 * ComfyUI Video Split Extension
 * 
 * Provides custom UI enhancements for video split nodes with VHS-style help system.
 */

// 帮助文本容器
const helpTexts = {
    "VideoSegmentInfo": {
        "en": `<div id=VHS_shortdesc>Calculate segment information for video splitting</div>
<div style="font-size: 0.8em"><b>Inputs:</b>
<div>• <b>images</b>: Frame tensor, connect to VHS Load Video's image output</div>
<div>• <b>fps</b>: Video frame rate</div>
<div>• <b>split_mode</b>: by_duration or by_frames</div>
<div>• <b>segment_duration</b>: Duration per segment (seconds)</div>
<div>• <b>segment_frames</b>: Frames per segment</div>
</div>
<div style="font-size: 0.8em"><b>Outputs:</b>
<div>• <b>total_segments</b>: Total segment count → forLoopStart</div>
<div>• <b>total_frames</b>: Total frame count</div>
<div>• <b>frames_per_segment</b>: Frames per segment → GetVideoSegment</div>
</div>`,
        "zh": `<div id=VHS_shortdesc>计算视频分段信息，配合循环节点使用</div>
<div style="font-size: 0.8em"><b>输入:</b>
<div>• <b>images</b>: 帧张量，连接 VHS Load Video 的 image 输出</div>
<div>• <b>fps</b>: 视频帧率</div>
<div>• <b>split_mode</b>: by_duration 按时长 / by_frames 按帧数</div>
<div>• <b>segment_duration</b>: 每段时长（秒）</div>
<div>• <b>segment_frames</b>: 每段帧数</div>
</div>
<div style="font-size: 0.8em"><b>输出:</b>
<div>• <b>total_segments</b>: 总分段数 → forLoopStart</div>
<div>• <b>total_frames</b>: 视频总帧数</div>
<div>• <b>frames_per_segment</b>: 每段帧数 → GetVideoSegment</div>
</div>`,
    },
    "GetVideoSegment": {
        "en": `<div id=VHS_shortdesc>Extract a video segment by index</div>
<div style="font-size: 0.8em"><b>Inputs:</b>
<div>• <b>images</b>: Frame tensor (same source as VideoSegmentInfo)</div>
<div>• <b>segment_index</b>: Segment index (0-based) → forLoopStart.index</div>
<div>• <b>frames_per_segment</b>: From VideoSegmentInfo</div>
</div>
<div style="font-size: 0.8em"><b>Outputs:</b>
<div>• <b>segment_images</b>: Current segment's frame tensor</div>
<div>• <b>segment_frame_count</b>: Frame count in this segment</div>
<div>• <b>start_frame</b>: Starting frame index</div>
</div>`,
        "zh": `<div id=VHS_shortdesc>按索引提取单个视频分段</div>
<div style="font-size: 0.8em"><b>输入:</b>
<div>• <b>images</b>: 帧张量（与 VideoSegmentInfo 同源）</div>
<div>• <b>segment_index</b>: 分段索引（从0开始）→ forLoopStart.index</div>
<div>• <b>frames_per_segment</b>: 来自 VideoSegmentInfo</div>
</div>
<div style="font-size: 0.8em"><b>输出:</b>
<div>• <b>segment_images</b>: 当前分段的帧张量</div>
<div>• <b>segment_frame_count</b>: 当前分段帧数</div>
<div>• <b>start_frame</b>: 起始帧索引</div>
</div>`,
    },
    "ImageCollect": {
        "en": `<div id=VHS_shortdesc>Collect images in a for loop</div>
<div style="font-size: 0.8em"><b>Inputs:</b>
<div>• <b>new_images</b>: Images to add from current iteration</div>
<div>• <b>images</b>: (Optional) Previous accumulated. Leave empty for first iteration</div>
</div>
<div style="font-size: 0.8em"><b>Outputs:</b>
<div>• <b>accumulated</b>: Accumulated frames → forLoopEnd</div>
<div>• <b>total_frames</b>: Current total frame count</div>
</div>
<div style="font-size: 0.8em"><b>Features:</b>
<div>• Smart type detection (tensor or list)</div>
</div>`,
        "zh": `<div id=VHS_shortdesc>在循环中收集图像帧</div>
<div style="font-size: 0.8em"><b>输入:</b>
<div>• <b>new_images</b>: 当前迭代要添加的图像帧</div>
<div>• <b>images</b>: (可选) 之前累积的图像帧，第一次迭代留空</div>
</div>
<div style="font-size: 0.8em"><b>输出:</b>
<div>• <b>accumulated</b>: 累积的帧 → forLoopEnd</div>
<div>• <b>total_frames</b>: 当前总帧数</div>
</div>
<div style="font-size: 0.8em"><b>特性:</b>
<div>• 智能类型检测（张量或列表）</div>
</div>`,
    },
};

// 获取语言
function getLang() {
    const locale = localStorage['Comfy.Settings.Comfy.Locale'] || 'en';
    if (locale.startsWith('zh')) return 'zh';
    return 'en';
}

// 帮助面板管理
let activeHelp = null;

function hideHelp() {
    if (activeHelp) {
        activeHelp.remove();
        activeHelp = null;
    }
}

function showHelp(node, html) {
    hideHelp();
    
    const help = document.createElement("div");
    help.className = "VHS_floatinghelp";
    help.style.cssText = `
        position: absolute;
        background: #1e1e1e;
        color: #fff;
        padding: 10px;
        border-radius: 8px;
        max-width: 350px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.5);
        z-index: 9999;
        font-size: 12px;
        line-height: 1.5;
    `;
    help.innerHTML = html;
    
    // 点击其他地方关闭
    help.addEventListener("mousedown", (e) => {
        e.stopPropagation();
    });
    
    document.body.appendChild(help);
    activeHelp = help;
    
    // 点击任意位置关闭
    const closeHandler = (e) => {
        if (!help.contains(e.target)) {
            hideHelp();
            document.removeEventListener("mousedown", closeHandler);
        }
    };
    setTimeout(() => {
        document.addEventListener("mousedown", closeHandler);
    }, 10);
}

// 为节点添加帮助功能
function addHelp(node) {
    const nodeType = node.type || node.constructor?.type || node.constructor?.name;
    const lang = getLang();
    const helpText = helpTexts[nodeType]?.[lang] || helpTexts[nodeType]?.["en"];
    
    if (!helpText) return;
    
    node.description = helpText;
    
    // 绘制 ? 按钮
    const onDrawForeground = node.onDrawForeground;
    node.onDrawForeground = function(ctx) {
        if (onDrawForeground) onDrawForeground.apply(this, arguments);
        
        // 绘制 ? 按钮
        ctx.save();
        ctx.font = "bold 14px Arial";
        ctx.fillStyle = "#888";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        
        // 位置：右上角
        const x = this.size[0] - 15;
        const y = 8;
        
        // 绘制圆形背景
        ctx.beginPath();
        ctx.arc(x, y, 8, 0, Math.PI * 2);
        ctx.fillStyle = "rgba(100,100,100,0.3)";
        ctx.fill();
        
        // 绘制 ?
        ctx.fillStyle = "#ccc";
        ctx.fillText("?", x, y);
        ctx.restore();
    };
    
    // 处理点击
    const onMouseDown = node.onMouseDown;
    node.onMouseDown = function(e, pos) {
        if (onMouseDown) onMouseDown.apply(this, arguments);
        
        // 检查是否点击了 ? 按钮
        const x = this.size[0] - 15;
        const y = 8;
        const dx = pos[0] - x;
        const dy = pos[1] - y;
        
        if (dx * dx + dy * dy < 100) { // 半径 10 内
            showHelp(this, this.description);
            return true;
        }
    };
}

// 扩展注册
app.registerExtension({
    name: "comfyui-video-split",
    
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function() {
            const r = onNodeCreated ? onNodeCreated.apply(this, arguments) : undefined;
            
            // 设置节点颜色
            this.color = "#2d5a27";
            
            // 添加帮助功能
            addHelp(this);
            
            return r;
        };
    },
    
    async setup(app) {
        console.log("[Video Split] Extension loaded with help system");
    },
});