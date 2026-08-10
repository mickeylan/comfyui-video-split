import { app } from "../../../scripts/app.js";

/**
 * ComfyUI Video Split Extension
 */

// 帮助文本
const helpTexts = {
    "VideoSegmentInfo": {
        "en": "Calculate segment information for video splitting\n\nInputs:\n  images: Frame tensor from VHS Load Video\n  fps: Video frame rate\n  split_mode: by_duration or by_frames\n  segment_duration: Duration per segment (seconds)\n  segment_frames: Frames per segment\n\nOutputs:\n  total_segments -> forLoopStart.total\n  total_frames: Total frame count\n  frames_per_segment -> GetVideoSegment",
        "zh": "计算视频分段信息，配合循环节点使用\n\n输入:\n  images: 帧张量，连接 VHS Load Video\n  fps: 视频帧率\n  split_mode: by_duration 按时长 / by_frames 按帧数\n  segment_duration: 每段时长（秒）\n  segment_frames: 每段帧数\n\n输出:\n  total_segments -> forLoopStart.total\n  total_frames: 视频总帧数\n  frames_per_segment -> GetVideoSegment"
    },
    "GetVideoSegment": {
        "en": "Extract a video segment by index\n\nInputs:\n  images: Frame tensor (same source as VideoSegmentInfo)\n  segment_index: Segment index (0-based) -> forLoopStart.index\n  frames_per_segment: From VideoSegmentInfo\n\nOutputs:\n  segment_images: Current segment's frame tensor\n  segment_frame_count: Frame count in this segment\n  start_frame: Starting frame index",
        "zh": "按索引提取单个视频分段\n\n输入:\n  images: 帧张量（与 VideoSegmentInfo 同源）\n  segment_index: 分段索引（从0开始）-> forLoopStart.index\n  frames_per_segment: 来自 VideoSegmentInfo\n\n输出:\n  segment_images: 当前分段的帧张量\n  segment_frame_count: 当前分段帧数\n  start_frame: 起始帧索引"
    },
    "ImageCollect": {
        "en": "Collect images in a for loop\n\nInputs:\n  new_images: Images to add from current iteration\n  images: (Optional) Previous accumulated images\n\nOutputs:\n  accumulated -> forLoopEnd.initial_value1\n  total_frames: Current total frame count\n\nFeatures:\n  Smart type detection (tensor or list)",
        "zh": "在循环中收集图像帧\n\n输入:\n  new_images: 当前迭代要添加的图像帧\n  images: (可选) 之前累积的图像帧\n\n输出:\n  accumulated -> forLoopEnd.initial_value1\n  total_frames: 当前总帧数\n\n特性:\n  智能类型检测（张量或列表）"
    }
};

// 帮助面板
let helpPanel = null;

function getLang() {
    var locale = localStorage['Comfy.Settings.Comfy.Locale'] || 'en';
    return locale.startsWith('zh') ? 'zh' : 'en';
}

function showHelp(node, text) {
    if (!helpPanel) {
        helpPanel = document.createElement("div");
        helpPanel.style.cssText = "position:absolute;left:-5000px;max-width:380px;padding:12px;background:#222;color:#eee;font-size:13px;line-height:1.6;border-radius:8px;box-shadow:0 4px 20px rgba(0,0,0,0.6);z-index:1000;white-space:pre-wrap;font-family:-apple-system,sans-serif;pointer-events:none;";
        document.body.appendChild(helpPanel);
    }
    
    helpPanel.textContent = text;
    helpPanel._node = node;
    
    var scale = app.canvas.ds.scale;
    var bcr = app.canvas.canvas.getBoundingClientRect();
    helpPanel.style.left = ((node.pos[0] + node.size[0] + 20) * scale + bcr.x) + "px";
    helpPanel.style.top = ((node.pos[1] - 20) * scale + bcr.y) + "px";
}

function hideHelp() {
    if (helpPanel) {
        helpPanel.style.left = "-5000px";
    }
}

var HELP_NODES = new Set(["VideoSegmentInfo", "GetVideoSegment", "ImageCollect"]);

app.registerExtension({
    name: "comfyui-video-split",
    
    beforeRegisterNodeDef: function(nodeType, nodeData, app) {
        var onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function() {
            if (onNodeCreated) onNodeCreated.apply(this, arguments);
            if (HELP_NODES.has(this.type)) {
                this.color = "#2d5a27";
            }
        };
    },
    
    setup: function(app) {
        // 绘制帮助按钮
        var origDraw = app.canvas.onDrawForeground;
        app.canvas.onDrawForeground = function(ctx) {
            if (origDraw) origDraw.apply(this, arguments);
            
            var nodes = app.graph._nodes;
            if (!nodes) return;
            
            for (var i = 0; i < nodes.length; i++) {
                var node = nodes[i];
                if (!HELP_NODES.has(node.type)) continue;
                if (!node.is_selected && !node.pointerOver) continue;
                
                var x = node.pos[0] + node.size[0] - 20;
                var y = node.pos[1] - LiteGraph.NODE_TITLE_HEIGHT + 6;
                
                ctx.save();
                ctx.font = "bold 12px Arial";
                ctx.textAlign = "center";
                ctx.textBaseline = "middle";
                
                ctx.beginPath();
                ctx.arc(x, y, 7, 0, Math.PI * 2);
                ctx.fillStyle = "rgba(60, 60, 60, 0.9)";
                ctx.fill();
                ctx.strokeStyle = "#888";
                ctx.lineWidth = 1;
                ctx.stroke();
                
                ctx.fillStyle = "#ddd";
                ctx.fillText("?", x, y + 1);
                ctx.restore();
            }
        };
        
        // 处理点击
        var origMouseDown = app.canvas.onMouseDown;
        app.canvas.onMouseDown = function(e, pos, node) {
            if (origMouseDown) origMouseDown.apply(this, arguments);
            
            if (!node || !HELP_NODES.has(node.type)) return;
            
            var x = node.pos[0] + node.size[0] - 20;
            var y = node.pos[1] - LiteGraph.NODE_TITLE_HEIGHT + 6;
            var dx = pos[0] - x;
            var dy = pos[1] - y;
            
            if (dx * dx + dy * dy < 100) {
                var lang = getLang();
                var text = helpTexts[node.type] && helpTexts[node.type][lang];
                if (!text) text = helpTexts[node.type] && helpTexts[node.type]["en"];
                if (text) showHelp(node, text);
                return true;
            } else {
                hideHelp();
            }
        };
        
        // 点击空白隐藏
        app.canvas.canvas.addEventListener("mousedown", function(e) {
            var node = app.canvas.getNodeAtPosition(e.offsetX, e.offsetY);
            if (!node || !HELP_NODES.has(node.type)) {
                hideHelp();
            }
        });
        
        console.log("[Video Split] Extension loaded");
    }
});