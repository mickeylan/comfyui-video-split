const { app } = window.comfyAPI.app;

// 帮助文本
const helpTexts = {
    "VideoSegmentInfo": {
        "en": "Calculate segment information for video splitting\n\n**Inputs:**\n- images: Frame tensor from VHS Load Video\n- fps: Video frame rate\n- split_mode: by_duration or by_frames\n- segment_duration: Duration per segment (seconds)\n- segment_frames: Frames per segment\n\n**Outputs:**\n- total_segments → forLoopStart.total\n- total_frames: Total frame count\n- frames_per_segment → GetVideoSegment",
        "zh": "计算视频分段信息，配合循环节点使用\n\n**输入:**\n- images: 帧张量，连接 VHS Load Video\n- fps: 视频帧率\n- split_mode: by_duration 按时长 / by_frames 按帧数\n- segment_duration: 每段时长（秒）\n- segment_frames: 每段帧数\n\n**输出:**\n- total_segments → forLoopStart.total\n- total_frames: 视频总帧数\n- frames_per_segment → GetVideoSegment"
    },
    "GetVideoSegment": {
        "en": "Extract a video segment by index\n\n**Inputs:**\n- images: Frame tensor (same source as VideoSegmentInfo)\n- segment_index: Segment index (0-based) → forLoopStart.index\n- frames_per_segment: From VideoSegmentInfo\n\n**Outputs:**\n- segment_images: Current segment's frame tensor\n- segment_frame_count: Frame count in this segment\n- start_frame: Starting frame index",
        "zh": "按索引提取单个视频分段\n\n**输入:**\n- images: 帧张量（与 VideoSegmentInfo 同源）\n- segment_index: 分段索引（从0开始）→ forLoopStart.index\n- frames_per_segment: 来自 VideoSegmentInfo\n\n**输出:**\n- segment_images: 当前分段的帧张量\n- segment_frame_count: 当前分段帧数\n- start_frame: 起始帧索引"
    },
    "ImageCollect": {
        "en": "Collect images in a for loop\n\n**Inputs:**\n- new_images: Images to add from current iteration\n- images: (Optional) Previous accumulated images\n\n**Outputs:**\n- accumulated → forLoopEnd.initial_value1\n- total_frames: Current total frame count\n\n**Features:**\n- Smart type detection (tensor or list)",
        "zh": "在循环中收集图像帧\n\n**输入:**\n- new_images: 当前迭代要添加的图像帧\n- images: (可选) 之前累积的图像帧\n\n**输出:**\n- accumulated → forLoopEnd.initial_value1\n- total_frames: 当前总帧数\n\n**特性:**\n- 智能类型检测（张量或列表）"
    }
};

const HELP_NODES = new Set(["VideoSegmentInfo", "GetVideoSegment", "ImageCollect"]);
const nodeDescriptions = new Map();

// 创建样式表
const create_documentation_stylesheet = () => {
    const tag = 'video-split-documentation-stylesheet';
    let styleTag = document.getElementById(tag);
    if (!styleTag) {
        styleTag = document.createElement('style');
        styleTag.type = 'text/css';
        styleTag.id = tag;
        styleTag.innerHTML = `
        .video-split-documentation-popup {
            background: var(--comfy-menu-bg);
            position: absolute;
            color: var(--fg-color);
            font: 12px monospace;
            line-height: 1.5em;
            padding: 10px;
            border-radius: 10px;
            border-style: solid;
            border-width: medium;
            border-color: var(--border-color);
            z-index: 5;
            overflow: hidden;
            max-width: 380px;
        }
        .content-wrapper {
            overflow: auto;
            max-height: 100%;
        }
        `;
        document.head.appendChild(styleTag);
    }
};

// 创建弹出窗口
function createDocPopup(description, signal, onClose) {
    create_documentation_stylesheet();
    
    const docElement = document.createElement('div');
    const contentWrapper = document.createElement('div');
    docElement.appendChild(contentWrapper);
    
    contentWrapper.classList.add('content-wrapper');
    docElement.classList.add('video-split-documentation-popup');
    
    // 简单的 Markdown 渲染
    const escaped = description
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>')
        .replace(/\n\n/g, '<br><br>')
        .replace(/\n/g, '<br>');
    contentWrapper.innerHTML = escaped;
    
    // 关闭按钮
    const closeButton = document.createElement('div');
    closeButton.textContent = '❌';
    closeButton.style.cssText = 'position: absolute; top: 0; right: 0; cursor: pointer; padding: 5px; color: red; font-size: 12px;';
    docElement.appendChild(closeButton);
    
    closeButton.addEventListener('mousedown', (e) => {
        e.stopPropagation();
        onClose();
    }, { signal });
    
    document.body.appendChild(docElement);
    return { docElement, contentWrapper };
}

// 添加文档功能（参考 KJNodes）
const addDocumentation = (nodeData, nodeType, opts = { icon_size: 14, icon_margin: 4 }) => {
    opts = opts || {};
    const iconSize = opts.icon_size ? opts.icon_size : 14;
    const iconMargin = opts.icon_margin ? opts.icon_margin : 4;
    let docElement = null;
    let contentWrapper = null;
    
    const description = nodeData.description;
    if (!description) return;
    
    const drawFg = nodeType.prototype.onDrawForeground;
    nodeType.prototype.onDrawForeground = function(ctx) {
        const r = drawFg ? drawFg.apply(this, arguments) : undefined;
        if (this.flags.collapsed) return r;
        
        const x = this.size[0] - iconSize - iconMargin;
        
        // 创建弹出窗口
        if (this.show_doc && docElement === null) {
            const popup = createDocPopup(
                description,
                this.docCtrl.signal,
                () => {
                    this.show_doc = !this.show_doc;
                    if (docElement.parentNode) {
                        docElement.parentNode.removeChild(docElement);
                    }
                    docElement = null;
                    contentWrapper = null;
                }
            );
            docElement = popup.docElement;
            contentWrapper = popup.contentWrapper;
        }
        // 关闭弹出窗口
        else if (!this.show_doc && docElement !== null) {
            if (docElement.parentNode) {
                docElement.parentNode.removeChild(docElement);
            }
            docElement = null;
        }
        // 更新弹出窗口位置
        if (this.show_doc && docElement !== null) {
            const rect = ctx.canvas.getBoundingClientRect();
            const scaleX = rect.width / ctx.canvas.width;
            const scaleY = rect.height / ctx.canvas.height;
            
            const transform = new DOMMatrix()
                .scaleSelf(scaleX, scaleY)
                .multiplySelf(ctx.getTransform())
                .translateSelf(this.size[0] * scaleX * Math.max(1.0, window.devicePixelRatio), 0)
                .translateSelf(10, -32);
            
            const scale = new DOMMatrix().scaleSelf(transform.a, transform.d);
            const bcr = app.canvas.canvas.getBoundingClientRect();
            
            Object.assign(docElement.style, {
                transformOrigin: '0 0',
                transform: scale,
                left: `${transform.a + bcr.x + transform.e}px`,
                top: `${transform.d + bcr.y + transform.f}px`,
            });
        }
        
        // 绘制 ? 图标
        ctx.save();
        ctx.translate(x - 2, iconSize - 34);
        ctx.scale(iconSize / 32, iconSize / 32);
        ctx.strokeStyle = 'rgba(255,255,255,0.3)';
        ctx.lineCap = 'round';
        ctx.lineJoin = 'round';
        ctx.lineWidth = 2.4;
        ctx.font = 'bold 36px monospace';
        ctx.fillStyle = 'orange';
        ctx.fillText('?', 0, 24);
        ctx.restore();
        
        return r;
    };
    
    // 处理点击
    const mouseDown = nodeType.prototype.onMouseDown;
    nodeType.prototype.onMouseDown = function(e, localPos, canvas) {
        const r = mouseDown ? mouseDown.apply(this, arguments) : undefined;
        const iconX = this.size[0] - iconSize - iconMargin;
        const iconY = iconSize - 34;
        
        if (localPos[0] > iconX && localPos[0] < iconX + iconSize &&
            localPos[1] > iconY && localPos[1] < iconY + iconSize) {
            if (this.show_doc === undefined) {
                this.show_doc = true;
            } else {
                this.show_doc = !this.show_doc;
            }
            if (this.show_doc) {
                this.docCtrl = new AbortController();
            } else {
                this.docCtrl.abort();
            }
            return true;
        }
        return r;
    };
    
    // 清理
    const onRem = nodeType.prototype.onRemoved;
    nodeType.prototype.onRemoved = function() {
        const r = onRem ? onRem.apply(this, []) : undefined;
        if (docElement) {
            docElement.remove();
            docElement = null;
            contentWrapper = null;
        }
        return r;
    };
};

// 获取语言
function getLang() {
    const locale = localStorage['Comfy.Settings.Comfy.Locale'] || 'en';
    return locale.startsWith('zh') ? 'zh' : 'en';
}

app.registerExtension({
    name: "comfyui-video-split",
    
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        try {
            if (HELP_NODES.has(nodeData.name)) {
                // 设置节点颜色
                const onNodeCreated = nodeType.prototype.onNodeCreated;
                nodeType.prototype.onNodeCreated = function() {
                    if (onNodeCreated) onNodeCreated.apply(this, arguments);
                    this.color = "#2d5a27";
                };
                
                // 获取帮助文本
                const lang = getLang();
                let description = helpTexts[nodeData.name]?.[lang] || helpTexts[nodeData.name]?.["en"];
                if (description) {
                    nodeData.description = description;
                    nodeDescriptions.set(nodeData.name, description);
                    addDocumentation(nodeData, nodeType);
                }
            }
        } catch (error) {
            console.error("Error in registering comfyui-video-split", error);
        }
    },
    
    nodeCreated(node) {
        const description = nodeDescriptions.get(node.type) || nodeDescriptions.get(node.comfyClass);
        if (!description) return;
        node._videoSplitHelpDescription = description;
    }
});