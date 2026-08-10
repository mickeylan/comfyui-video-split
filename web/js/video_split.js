import { app } from "../../../scripts/app.js";

/**
 * ComfyUI Video Split Extension
 */

// 帮助文本 (HTML格式)
const helpTexts = {
    "VideoSegmentInfo": {
        "en": "<b>Calculate segment information for video splitting</b><br><br><b>Inputs:</b><br>• <b>images</b>: Frame tensor from VHS Load Video<br>• <b>fps</b>: Video frame rate<br>• <b>split_mode</b>: by_duration or by_frames<br>• <b>segment_duration</b>: Duration per segment (seconds)<br>• <b>segment_frames</b>: Frames per segment<br><br><b>Outputs:</b><br>• <b>total_segments</b> → forLoopStart.total<br>• <b>total_frames</b>: Total frame count<br>• <b>frames_per_segment</b> → GetVideoSegment",
        "zh": "<b>计算视频分段信息，配合循环节点使用</b><br><br><b>输入:</b><br>• <b>images</b>: 帧张量，连接 VHS Load Video<br>• <b>fps</b>: 视频帧率<br>• <b>split_mode</b>: by_duration 按时长 / by_frames 按帧数<br>• <b>segment_duration</b>: 每段时长（秒）<br>• <b>segment_frames</b>: 每段帧数<br><br><b>输出:</b><br>• <b>total_segments</b> → forLoopStart.total<br>• <b>total_frames</b>: 视频总帧数<br>• <b>frames_per_segment</b> → GetVideoSegment"
    },
    "GetVideoSegment": {
        "en": "<b>Extract a video segment by index</b><br><br><b>Inputs:</b><br>• <b>images</b>: Frame tensor (same source as VideoSegmentInfo)<br>• <b>segment_index</b>: Segment index (0-based) → forLoopStart.index<br>• <b>frames_per_segment</b>: From VideoSegmentInfo<br><br><b>Outputs:</b><br>• <b>segment_images</b>: Current segment's frame tensor<br>• <b>segment_frame_count</b>: Frame count in this segment<br>• <b>start_frame</b>: Starting frame index",
        "zh": "<b>按索引提取单个视频分段</b><br><br><b>输入:</b><br>• <b>images</b>: 帧张量（与 VideoSegmentInfo 同源）<br>• <b>segment_index</b>: 分段索引（从0开始）→ forLoopStart.index<br>• <b>frames_per_segment</b>: 来自 VideoSegmentInfo<br><br><b>输出:</b><br>• <b>segment_images</b>: 当前分段的帧张量<br>• <b>segment_frame_count</b>: 当前分段帧数<br>• <b>start_frame</b>: 起始帧索引"
    },
    "ImageCollect": {
        "en": "<b>Collect images in a for loop</b><br><br><b>Inputs:</b><br>• <b>new_images</b>: Images to add from current iteration<br>• <b>images</b>: (Optional) Previous accumulated images<br><br><b>Outputs:</b><br>• <b>accumulated</b> → forLoopEnd.initial_value1<br>• <b>total_frames</b>: Current total frame count<br><br><b>Features:</b><br>• Smart type detection (tensor or list)",
        "zh": "<b>在循环中收集图像帧</b><br><br><b>输入:</b><br>• <b>new_images</b>: 当前迭代要添加的图像帧<br>• <b>images</b>: (可选) 之前累积的图像帧<br><br><b>输出:</b><br>• <b>accumulated</b> → forLoopEnd.initial_value1<br>• <b>total_frames</b>: 当前总帧数<br><br><b>特性:</b><br>• 智能类型检测（张量或列表）"
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
        helpPanel.style.cssText = "position:absolute;left:-5000px;max-width:380px;padding:12px;background:#222;color:#eee;font-size:13px;line-height:1.6;border-radius:8px;box-shadow:0 4px 20px rgba(0,0,0,0.6);z-index:1000;font-family:-apple-system,sans-serif;pointer-events:none;";
        document.body.appendChild(helpPanel);
    }
    
    helpPanel.innerHTML = text;
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
                // 始终绘制 ? 按钮
                
                var x = node.pos[0] + node.size[0] - 15;
                var y = node.pos[1] - 10;
                
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
            
            var x = node.pos[0] + node.size[0] - 18;
            var y = node.pos[1] + 10;
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