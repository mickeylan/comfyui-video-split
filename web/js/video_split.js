import { app } from "../../scripts/app.js";

/**
 * ComfyUI Video Split Extension
 * 
 * Provides VHS-style help system for video split nodes.
 */

// 帮助文本（纯文本，不使用 HTML）
const helpTexts = {
    "VideoSegmentInfo": {
        "en": `Calculate segment information for video splitting

Inputs:
  images: Frame tensor from VHS Load Video
  fps: Video frame rate
  split_mode: by_duration or by_frames
  segment_duration: Duration per segment (seconds)
  segment_frames: Frames per segment

Outputs:
  total_segments → forLoopStart.total
  total_frames: Total frame count
  frames_per_segment → GetVideoSegment`,
        "zh": `计算视频分段信息，配合循环节点使用

输入:
  images: 帧张量，连接 VHS Load Video
  fps: 视频帧率
  split_mode: by_duration 按时长 / by_frames 按帧数
  segment_duration: 每段时长（秒）
  segment_frames: 每段帧数

输出:
  total_segments → forLoopStart.total
  total_frames: 视频总帧数
  frames_per_segment → GetVideoSegment`,
    },
    "GetVideoSegment": {
        "en": `Extract a video segment by index

Inputs:
  images: Frame tensor (same source as VideoSegmentInfo)
  segment_index: Segment index (0-based) → forLoopStart.index
  frames_per_segment: From VideoSegmentInfo

Outputs:
  segment_images: Current segment's frame tensor
  segment_frame_count: Frame count in this segment
  start_frame: Starting frame index`,
        "zh": `按索引提取单个视频分段

输入:
  images: 帧张量（与 VideoSegmentInfo 同源）
  segment_index: 分段索引（从0开始）→ forLoopStart.index
  frames_per_segment: 来自 VideoSegmentInfo

输出:
  segment_images: 当前分段的帧张量
  segment_frame_count: 当前分段帧数
  start_frame: 起始帧索引`,
    },
    "ImageCollect": {
        "en": `Collect images in a for loop

Inputs:
  new_images: Images to add from current iteration
  images: (Optional) Previous accumulated images

Outputs:
  accumulated → forLoopEnd.initial_value1
  total_frames: Current total frame count

Features:
  Smart type detection (tensor or list)`,
        "zh": `在循环中收集图像帧

输入:
  new_images: 当前迭代要添加的图像帧
  images: (可选) 之前累积的图像帧

输出:
  accumulated → forLoopEnd.initial_value1
  total_frames: 当前总帧数

特性:
  智能类型检测（张量或列表）`,
    },
};

// 获取语言
function getLang() {
    const locale = localStorage['Comfy.Settings.Comfy.Locale'] || 'en';
    if (locale.startsWith('zh')) return 'zh';
    return 'en';
}

// 帮助 DOM 元素
let helpDOM = null;
let helpParent = null;

// 初始化帮助 DOM
function initHelp() {
    if (helpParent) return;
    
    helpParent = document.createElement("div");
    helpParent.style.cssText = `
        position: absolute;
        left: -5000px;
        max-width: 380px;
        padding: 12px;
        background: #222;
        color: #eee;
        font-size: 13px;
        line-height: 1.6;
        border-radius: 8px;
        box-shadow: 0 4px 20px rgba(0,0,0,0.6);
        z-index: 1000;
        white-space: pre-wrap;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        pointer-events: none;
    `;
    document.body.appendChild(helpParent);
    
    helpDOM = {
        node: null,
        setText: (text) => {
            helpParent.textContent = text;
        }
    };
}

// 显示帮助
function showHelp(node, text) {
    initHelp();
    helpDOM.node = node;
    helpDOM.setText(text);
    
    // 设置位置
    const scale = app.canvas.ds.scale;
    const canvas = app.canvas.canvas;
    const bcr = canvas.getBoundingClientRect();
    
    const x = (node.pos[0] + node.size[0] + 20) * scale + bcr.x;
    const y = (node.pos[1] - 20) * scale + bcr.y;
    
    helpParent.style.left = x + "px";
    helpParent.style.top = y + "px";
}

// 隐藏帮助
function hideHelp() {
    if (helpParent) {
        helpParent.style.left = '-5000px';
        helpDOM?.node = null;
    }
}

// 需要帮助的节点类型
const HELP_NODES = new Set(["VideoSegmentInfo", "GetVideoSegment", "ImageCollect"]);

// 注册扩展
app.registerExtension({
    name: "comfyui-video-split",
    
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function() {
            const r = onNodeCreated ? onNodeCreated.apply(this, arguments) : undefined;
            
            // 设置节点颜色
            if (HELP_NODES.has(this.type)) {
                this.color = "#2d5a27";
            }
            
            return r;
        };
    },
    
    async setup(app) {
        // 在画布绘制时检查并绘制 ? 按钮
        const onDrawForeground = app.canvas.onDrawForeground;
        app.canvas.onDrawForeground = function(ctx) {
            if (onDrawForeground) onDrawForeground.apply(this, arguments);
            
            // 遍历所有节点，绘制帮助按钮
            const nodes = app.graph._nodes;
            if (!nodes) return;
            
            for (const node of nodes) {
                if (!HELP_NODES.has(node.type)) continue;
                if (!node.is_selected && node.pointerOver === false) continue;
                
                const x = node.pos[0] + node.size[0] - 20;
                const y = node.pos[1] - LiteGraph.NODE_TITLE_HEIGHT + 6;
                
                ctx.save();
                ctx.font = "bold 12px Arial";
                ctx.textAlign = "center";
                ctx.textBaseline = "middle";
                
                // 圆形背景
                ctx.beginPath();
                ctx.arc(x, y, 7, 0, Math.PI * 2);
                ctx.fillStyle = "rgba(60, 60, 60, 0.9)";
                ctx.fill();
                ctx.strokeStyle = "#888";
                ctx.lineWidth = 1;
                ctx.stroke();
                
                // 问号
                ctx.fillStyle = "#ddd";
                ctx.fillText("?", x, y + 1);
                ctx.restore();
            }
        };
        
        // 处理点击事件
        const onMouseDown = app.canvas.onMouseDown;
        app.canvas.onMouseDown = function(e, pos, node) {
            if (onMouseDown) onMouseDown.apply(this, arguments);
            
            if (!node || !HELP_NODES.has(node.type)) return;
            
            // 检查是否点击了 ? 按钮
            const x = node.pos[0] + node.size[0] - 20;
            const y = node.pos[1] - LiteGraph.NODE_TITLE_HEIGHT + 6;
            const dx = pos[0] - x;
            const dy = pos[1] - y;
            
            if (dx * dx + dy * dy < 100) {
                const lang = getLang();
                const text = helpTexts[node.type]?.[lang] || helpTexts[node.type]?.["en"];
                if (text) {
                    showHelp(node, text);
                }
                return true;
            } else {
                hideHelp();
            }
        };
        
        // 点击空白处隐藏
        app.canvas.canvas.addEventListener("mousedown", (e) => {
            const node = app.canvas.getNodeAtPosition(e.offsetX, e.offsetY);
            if (!node || !HELP_NODES.has(node.type)) {
                hideHelp();
            }
        });
        
        console.log("[Video Split] Extension loaded with help system");
    },
});