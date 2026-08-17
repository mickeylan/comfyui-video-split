/**
 * Audio Timeline Editor - 可视化音频时间轴校准界面
 * 
 * 功能：
 * - 拖拽音频块到指定位置
 * - 实时预览时间轴
 * - 精确帧级对齐
 * - 缩放和平移
 */

const { app } = window.comfyAPI?.app || window.app || {};

// 配置常量
const TIMELINE_CONFIG = {
    minZoom: 0.1,        // 最小缩放（像素/帧）
    maxZoom: 10,         // 最大缩放
    defaultZoom: 1,      // 默认缩放
    trackHeight: 60,     // 轨道高度
    headerHeight: 30,    // 表头高度
    rulerHeight: 25,     // 时间尺高度
    snapThreshold: 10,   // 吸附阈值（像素）
    colors: {
        background: '#1a1a2e',
        trackBg: '#16213e',
        rulerBg: '#0f0f23',
        rulerLine: '#3a3a5a',
        rulerText: '#8888aa',
        audioBlock: '#4a90d9',
        audioBlockHover: '#5aa0e9',
        audioBlockSelected: '#7ab8ff',
        audioBlockBorder: '#2a5a8a',
        playhead: '#ff6b6b',
        gridLine: '#2a2a4a',
        snapLine: '#00ff88',
        text: '#ffffff',
    }
};

// 语言
function getLang() {
    const locale = localStorage['Comfy.Settings.Comfy.Locale'] || 'en';
    return locale.startsWith('zh') ? 'zh' : 'en';
}

// 翻译
const i18n = {
    zh: {
        title: '音频时间轴校准',
        addTrack: '添加音轨',
        removeTrack: '删除轨道',
        playhead: '播放头',
        frame: '帧',
        seconds: '秒',
        fps: 'FPS',
        totalFrames: '总帧数',
        duration: '时长',
        snapToGrid: '吸附网格',
        snapToPlayhead: '吸附播放头',
        zoom: '缩放',
        reset: '重置',
        export: '导出配置',
        import: '导入配置',
        noAudio: '拖拽音频文件到此处',
        audioTracks: '音频轨道',
        startFrame: '起始帧',
        endFrame: '结束帧',
        volume: '音量',
        delete: '删除',
        duplicate: '复制',
        confirmDelete: '确定删除此音频块?',
        exportSuccess: '配置已导出到剪贴板',
        importError: '导入配置格式错误',
        instructions: '💡 提示：拖拽音频块可调整位置，拖拽边缘调整时长',
    },
    en: {
        title: 'Audio Timeline Editor',
        addTrack: 'Add Track',
        removeTrack: 'Remove Track',
        playhead: 'Playhead',
        frame: 'Frame',
        seconds: 'Seconds',
        fps: 'FPS',
        totalFrames: 'Total Frames',
        duration: 'Duration',
        snapToGrid: 'Snap to Grid',
        snapToPlayhead: 'Snap to Playhead',
        zoom: 'Zoom',
        reset: 'Reset',
        export: 'Export Config',
        import: 'Import Config',
        noAudio: 'Drag audio files here',
        audioTracks: 'Audio Tracks',
        startFrame: 'Start Frame',
        endFrame: 'End Frame',
        volume: 'Volume',
        delete: 'Delete',
        duplicate: 'Duplicate',
        confirmDelete: 'Delete this audio block?',
        exportSuccess: 'Config exported to clipboard',
        importError: 'Invalid config format',
        instructions: '💡 Tip: Drag audio blocks to adjust position, drag edges to adjust duration',
    }
};

// 工具函数
function formatTime(frames, fps) {
    const seconds = frames / fps;
    const mins = Math.floor(seconds / 60);
    const secs = (seconds % 60).toFixed(2);
    return `${mins}:${secs.padStart(5, '0')}`;
}

function formatFrame(frames) {
    return frames.toString().padStart(6, '0');
}

// 音频块类
class AudioBlock {
    constructor(id, trackIndex, startFrame, endFrame, audioData = null) {
        this.id = id;
        this.trackIndex = trackIndex;
        this.startFrame = startFrame;
        this.endFrame = endFrame;
        this.audioData = audioData; // 音频数据或路径
        this.volume = 1.0;
        this.selected = false;
        this.dragging = false;
        this.resizing = false;
        this.resizeEdge = null; // 'left' | 'right'
    }

    get duration() {
        return this.endFrame - this.startFrame;
    }
}

// 轨道类
class AudioTrack {
    constructor(id, name) {
        this.id = id;
        this.name = name;
        this.blocks = [];
        this.muted = false;
        this.locked = false;
    }
}

// 时间轴编辑器主类
class AudioTimelineEditor {
    constructor(container, options = {}) {
        this.container = container;
        this.options = {
            fps: options.fps || 24,
            totalFrames: options.totalFrames || 1440,
            onChange: options.onChange || (() => {}),
            ...options
        };

        this.lang = getLang();
        this.t = i18n[this.lang];

        // 缩放和平移状态
        this.zoom = TIMELINE_CONFIG.defaultZoom;
        this.scrollX = 0;
        this.playheadFrame = 0;

        // 音频数据
        this.tracks = [];
        this.nextTrackId = 1;
        this.nextBlockId = 1;

        // 交互状态
        this.dragState = null;
        this.isDragging = false;
        this.selection = null;

        // 创建 UI
        this.createUI();

        // 添加默认轨道
        this.addTrack(this.t.audioTracks + ' 1');

        // 绑定事件
        this.bindEvents();
    }

    createUI() {
        // 样式
        const style = document.createElement('style');
        style.textContent = `
            .audio-timeline-container {
                font-family: 'Segoe UI', system-ui, sans-serif;
                background: ${TIMELINE_CONFIG.colors.background};
                border-radius: 8px;
                overflow: hidden;
                user-select: none;
            }
            .audio-timeline-header {
                display: flex;
                align-items: center;
                justify-content: space-between;
                padding: 8px 12px;
                background: ${TIMELINE_CONFIG.colors.rulerBg};
                border-bottom: 1px solid ${TIMELINE_CONFIG.colors.gridLine};
                color: ${TIMELINE_CONFIG.colors.text};
                font-size: 13px;
            }
            .audio-timeline-header h3 {
                margin: 0;
                font-size: 14px;
                font-weight: 600;
            }
            .audio-timeline-controls {
                display: flex;
                gap: 8px;
                align-items: center;
            }
            .audio-timeline-btn {
                padding: 4px 10px;
                border: 1px solid ${TIMELINE_CONFIG.colors.gridLine};
                background: ${TIMELINE_CONFIG.colors.trackBg};
                color: ${TIMELINE_CONFIG.colors.text};
                border-radius: 4px;
                cursor: pointer;
                font-size: 12px;
                transition: all 0.2s;
            }
            .audio-timeline-btn:hover {
                background: ${TIMELINE_CONFIG.colors.audioBlock};
                border-color: ${TIMELINE_CONFIG.colors.audioBlock};
            }
            .audio-timeline-btn.active {
                background: ${TIMELINE_CONFIG.colors.audioBlockSelected};
                border-color: ${TIMELINE_CONFIG.colors.audioBlockSelected};
            }
            .audio-timeline-canvas-wrapper {
                position: relative;
                height: 300px;
                overflow: hidden;
            }
            .audio-timeline-canvas {
                display: block;
                cursor: grab;
            }
            .audio-timeline-canvas.dragging {
                cursor: grabbing;
            }
            .audio-timeline-info {
                padding: 8px 12px;
                background: ${TIMELINE_CONFIG.colors.rulerBg};
                border-top: 1px solid ${TIMELINE_CONFIG.colors.gridLine};
                color: ${TIMELINE_CONFIG.colors.rulerText};
                font-size: 11px;
                font-family: monospace;
            }
            .audio-timeline-info span {
                margin-right: 16px;
            }
            .audio-timeline-zoom {
                display: flex;
                align-items: center;
                gap: 6px;
            }
            .audio-timeline-zoom input {
                width: 80px;
                accent-color: ${TIMELINE_CONFIG.colors.audioBlock};
            }
            .audio-timeline-zoom label {
                font-size: 11px;
                color: ${TIMELINE_CONFIG.colors.rulerText};
            }
            .audio-timeline-instructions {
                padding: 8px 12px;
                background: ${TIMELINE_CONFIG.colors.trackBg};
                color: ${TIMELINE_CONFIG.colors.rulerText};
                font-size: 11px;
                border-top: 1px solid ${TIMELINE_CONFIG.colors.gridLine};
            }
            .audio-timeline-modal {
                position: fixed;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                background: rgba(0,0,0,0.7);
                display: flex;
                align-items: center;
                justify-content: center;
                z-index: 10000;
            }
            .audio-timeline-modal-content {
                background: ${TIMELINE_CONFIG.colors.trackBg};
                border: 1px solid ${TIMELINE_CONFIG.colors.gridLine};
                border-radius: 8px;
                padding: 20px;
                max-width: 500px;
                width: 90%;
                color: ${TIMELINE_CONFIG.colors.text};
            }
            .audio-timeline-modal-content h4 {
                margin: 0 0 12px 0;
            }
            .audio-timeline-modal-content textarea {
                width: 100%;
                height: 200px;
                background: ${TIMELINE_CONFIG.colors.background};
                border: 1px solid ${TIMELINE_CONFIG.colors.gridLine};
                color: ${TIMELINE_CONFIG.colors.text};
                font-family: monospace;
                font-size: 11px;
                padding: 8px;
                border-radius: 4px;
                resize: vertical;
            }
            .audio-timeline-modal-content .buttons {
                display: flex;
                gap: 8px;
                margin-top: 12px;
                justify-content: flex-end;
            }
        `;
        document.head.appendChild(style);

        // 主容器
        this.wrapper = document.createElement('div');
        this.wrapper.className = 'audio-timeline-container';

        // 头部
        this.header = document.createElement('div');
        this.header.className = 'audio-timeline-header';
        this.header.innerHTML = `
            <h3>🎵 ${this.t.title}</h3>
            <div class="audio-timeline-controls">
                <button class="audio-timeline-btn" id="addTrackBtn">+ ${this.t.addTrack}</button>
                <button class="audio-timeline-btn" id="snapGridBtn">${this.t.snapToGrid}</button>
                <div class="audio-timeline-zoom">
                    <label>${this.t.zoom}:</label>
                    <input type="range" id="zoomSlider" min="0.1" max="5" step="0.1" value="1">
                    <span id="zoomValue">100%</span>
                </div>
                <button class="audio-timeline-btn" id="exportBtn">${this.t.export}</button>
                <button class="audio-timeline-btn" id="importBtn">${this.t.import}</button>
            </div>
        `;
        this.wrapper.appendChild(this.header);

        // 画布容器
        this.canvasWrapper = document.createElement('div');
        this.canvasWrapper.className = 'audio-timeline-canvas-wrapper';
        this.canvas = document.createElement('canvas');
        this.canvas.className = 'audio-timeline-canvas';
        this.canvasWrapper.appendChild(this.canvas);
        this.wrapper.appendChild(this.canvasWrapper);

        // 信息栏
        this.infoBar = document.createElement('div');
        this.infoBar.className = 'audio-timeline-info';
        this.wrapper.appendChild(this.infoBar);

        // 提示
        this.instructions = document.createElement('div');
        this.instructions.className = 'audio-timeline-instructions';
        this.instructions.textContent = this.t.instructions;
        this.wrapper.appendChild(this.instructions);

        this.container.appendChild(this.wrapper);

        // 获取上下文
        this.ctx = this.canvas.getContext('2d');

        // 尺寸
        this.resize();
    }

    resize() {
        const rect = this.canvasWrapper.getBoundingClientRect();
        const dpr = window.devicePixelRatio || 1;
        
        this.canvas.width = rect.width * dpr;
        this.canvas.height = rect.height * dpr;
        this.canvas.style.width = rect.width + 'px';
        this.canvas.style.height = rect.height + 'px';
        
        this.ctx.scale(dpr, dpr);
        this.width = rect.width;
        this.height = rect.height;
        
        this.render();
    }

    bindEvents() {
        // 窗口调整
        window.addEventListener('resize', () => this.resize());

        // 缩放滑块
        const zoomSlider = this.header.querySelector('#zoomSlider');
        const zoomValue = this.header.querySelector('#zoomValue');
        zoomSlider.addEventListener('input', (e) => {
            this.zoom = parseFloat(e.target.value);
            zoomValue.textContent = Math.round(this.zoom * 100) + '%';
            this.render();
        });

        // 添加轨道
        this.header.querySelector('#addTrackBtn').addEventListener('click', () => {
            this.addTrack(this.t.audioTracks + ' ' + this.nextTrackId);
        });

        // 吸附网格
        let snapEnabled = false;
        const snapBtn = this.header.querySelector('#snapGridBtn');
        snapBtn.addEventListener('click', () => {
            snapEnabled = !snapEnabled;
            snapBtn.classList.toggle('active', snapEnabled);
        });

        // 导出
        this.header.querySelector('#exportBtn').addEventListener('click', () => {
            this.exportConfig();
        });

        // 导入
        this.header.querySelector('#importBtn').addEventListener('click', () => {
            this.showImportModal();
        });

        // 画布鼠标事件
        this.canvas.addEventListener('mousedown', (e) => this.onMouseDown(e));
        this.canvas.addEventListener('mousemove', (e) => this.onMouseMove(e));
        this.canvas.addEventListener('mouseup', (e) => this.onMouseUp(e));
        this.canvas.addEventListener('mouseleave', (e) => this.onMouseUp(e));
        this.canvas.addEventListener('wheel', (e) => this.onWheel(e));
        this.canvas.addEventListener('dblclick', (e) => this.onDoubleClick(e));

        // 键盘事件
        document.addEventListener('keydown', (e) => this.onKeyDown(e));
    }

    // 帧/像素转换
    frameToX(frame) {
        return (frame * this.zoom) - this.scrollX;
    }

    xToFrame(x) {
        return Math.round((x + this.scrollX) / this.zoom);
    }

    // 轨道 Y 坐标
    trackToY(trackIndex) {
        return TIMELINE_CONFIG.headerHeight + TIMELINE_CONFIG.rulerHeight + 
               (trackIndex * (TIMELINE_CONFIG.trackHeight + 2));
    }

    yToTrack(y) {
        const trackArea = y - TIMELINE_CONFIG.headerHeight - TIMELINE_CONFIG.rulerHeight;
        return Math.floor(trackArea / (TIMELINE_CONFIG.trackHeight + 2));
    }

    // 渲染
    render() {
        const ctx = this.ctx;
        const w = this.width;
        const h = this.height;

        // 清空
        ctx.fillStyle = TIMELINE_CONFIG.colors.background;
        ctx.fillRect(0, 0, w, h);

        // 绘制时间尺
        this.drawRuler(ctx, w);

        // 绘制轨道
        this.tracks.forEach((track, index) => {
            this.drawTrack(ctx, track, index, w);
        });

        // 绘制播放头
        this.drawPlayhead(ctx, w);

        // 绘制选择框
        if (this.selection) {
            this.drawSelection(ctx);
        }

        // 更新信息栏
        this.updateInfo();
    }

    drawRuler(ctx, w) {
        const rulerY = TIMELINE_CONFIG.headerHeight;
        const rulerH = TIMELINE_CONFIG.rulerHeight;

        // 背景
        ctx.fillStyle = TIMELINE_CONFIG.colors.rulerBg;
        ctx.fillRect(0, rulerY, w, rulerH);

        // 计算刻度间隔
        const pixelsPerSecond = this.zoom * this.options.fps;
        let interval;
        if (pixelsPerSecond > 200) interval = this.options.fps / 4; // 每帧
        else if (pixelsPerSecond > 50) interval = this.options.fps; // 每秒
        else if (pixelsPerSecond > 10) interval = this.options.fps * 5; // 每5秒
        else interval = this.options.fps * 10; // 每10秒

        // 绘制刻度
        ctx.strokeStyle = TIMELINE_CONFIG.colors.rulerLine;
        ctx.fillStyle = TIMELINE_CONFIG.colors.rulerText;
        ctx.font = '10px monospace';
        ctx.textAlign = 'center';

        const startFrame = this.xToFrame(0);
        const endFrame = this.xToFrame(w);

        for (let frame = Math.floor(startFrame / interval) * interval; frame <= endFrame; frame += interval) {
            const x = this.frameToX(frame);
            if (x < 0 || x > w) continue;

            ctx.beginPath();
            ctx.moveTo(x, rulerY);
            ctx.lineTo(x, rulerY + rulerH);
            ctx.stroke();

            // 标签
            const time = formatTime(frame, this.options.fps);
            ctx.fillText(time, x, rulerY + rulerH - 6);
        }

        // 边界
        ctx.strokeStyle = TIMELINE_CONFIG.colors.audioBlockBorder;
        ctx.beginPath();
        ctx.moveTo(0, rulerY + rulerH);
        ctx.lineTo(w, rulerY + rulerH);
        ctx.stroke();
    }

    drawTrack(ctx, track, index, w) {
        const y = this.trackToY(index);
        const h = TIMELINE_CONFIG.trackHeight;

        // 轨道背景
        ctx.fillStyle = TIMELINE_CONFIG.colors.trackBg;
        ctx.fillRect(0, y, w, h);

        // 轨道边框
        ctx.strokeStyle = TIMELINE_CONFIG.colors.gridLine;
        ctx.strokeRect(0, y, w, h);

        // 轨道名称
        ctx.fillStyle = TIMELINE_CONFIG.colors.rulerText;
        ctx.font = '11px sans-serif';
        ctx.textAlign = 'left';
        ctx.fillText(track.name, 8, y + 16);

        // 绘制音频块
        track.blocks.forEach(block => {
            this.drawAudioBlock(ctx, block, y, h);
        });
    }

    drawAudioBlock(ctx, block, trackY, trackH) {
        const x = this.frameToX(block.startFrame);
        const width = (block.endFrame - block.startFrame) * this.zoom;

        // 如果完全在可视区域外，跳过
        if (x + width < 0 || x > this.width) return;

        // 颜色
        const baseColor = block.selected ? TIMELINE_CONFIG.colors.audioBlockSelected : 
                         block.dragging ? TIMELINE_CONFIG.colors.audioBlockHover : 
                         TIMELINE_CONFIG.colors.audioBlock;

        // 主体
        ctx.fillStyle = baseColor;
        ctx.beginPath();
        ctx.roundRect(Math.max(0, x), trackY + 4, Math.min(width, this.width - x), trackH - 8, 4);
        ctx.fill();

        // 边框
        ctx.strokeStyle = TIMELINE_CONFIG.colors.audioBlockBorder;
        ctx.lineWidth = 1;
        ctx.stroke();

        // 文字（如果宽度足够）
        if (width > 60) {
            ctx.fillStyle = '#fff';
            ctx.font = '11px sans-serif';
            ctx.textAlign = 'left';
            const text = block.audioData?.name || `Audio ${block.id}`;
            ctx.fillText(text, Math.max(4, x) + 4, trackY + trackH / 2 + 4, width - 8);
        }

        // 调整手柄
        if (block.selected) {
            ctx.fillStyle = 'rgba(255,255,255,0.8)';
            // 左边缘
            ctx.fillRect(Math.max(0, x), trackY + 8, 6, trackH - 16);
            // 右边缘
            ctx.fillRect(Math.min(this.width - 6, x + width - 6), trackY + 8, 6, trackH - 16);
        }
    }

    drawPlayhead(ctx, w) {
        const x = this.frameToX(this.playheadFrame);
        if (x < 0 || x > w) return;

        ctx.strokeStyle = TIMELINE_CONFIG.colors.playhead;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(x, TIMELINE_CONFIG.headerHeight);
        ctx.lineTo(x, this.height);
        ctx.stroke();

        // 三角形头部
        ctx.fillStyle = TIMELINE_CONFIG.colors.playhead;
        ctx.beginPath();
        ctx.moveTo(x - 6, TIMELINE_CONFIG.headerHeight);
        ctx.lineTo(x + 6, TIMELINE_CONFIG.headerHeight);
        ctx.lineTo(x, TIMELINE_CONFIG.headerHeight + 10);
        ctx.closePath();
        ctx.fill();
    }

    drawSelection(ctx) {
        const { x, y, width, height } = this.selection;
        ctx.strokeStyle = TIMELINE_CONFIG.colors.audioBlockSelected;
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 4]);
        ctx.strokeRect(x, y, width, height);
        ctx.setLineDash([]);
    }

    // 鼠标事件
    onMouseDown(e) {
        const rect = this.canvas.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        const frame = this.xToFrame(x);
        const trackIndex = this.yToTrack(y);

        // 检查是否点击在音频块上
        let clickedBlock = null;
        let clickType = null; // 'move' | 'resize-left' | 'resize-right'

        if (trackIndex >= 0 && trackIndex < this.tracks.length) {
            const track = this.tracks[trackIndex];
            for (const block of track.blocks) {
                const bx = this.frameToX(block.startFrame);
                const bw = (block.endFrame - block.startFrame) * this.zoom;

                if (x >= bx && x <= bx + bw && y >= this.trackToY(trackIndex) && 
                    y <= this.trackToY(trackIndex) + TIMELINE_CONFIG.trackHeight) {
                    clickedBlock = block;
                    
                    // 检查调整手柄
                    if (x < bx + 10) clickType = 'resize-left';
                    else if (x > bx + bw - 10) clickType = 'resize-right';
                    else clickType = 'move';
                    
                    break;
                }
            }
        }

        if (clickedBlock) {
            // 选中并开始拖拽
            this.tracks.forEach(t => t.blocks.forEach(b => b.selected = false));
            clickedBlock.selected = true;
            clickedBlock.dragging = true;
            clickedBlock.resizeEdge = clickType === 'resize-left' ? 'left' : 
                                      clickType === 'resize-right' ? 'right' : null;
            this.dragState = {
                block: clickedBlock,
                startX: x,
                startFrame: frame,
                originalStart: clickedBlock.startFrame,
                originalEnd: clickedBlock.endFrame
            };
            this.canvas.classList.add('dragging');
            this.render();
        } else if (y > TIMELINE_CONFIG.headerHeight + TIMELINE_CONFIG.rulerHeight) {
            // 点击空白区域，设置播放头
            this.playheadFrame = Math.max(0, Math.min(frame, this.options.totalFrames));
            this.render();
        }
    }

    onMouseMove(e) {
        const rect = this.canvas.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        const frame = this.xToFrame(x);

        // 更新播放头位置（如果不在拖拽）
        if (!this.dragState && y > TIMELINE_CONFIG.headerHeight + TIMELINE_CONFIG.rulerHeight) {
            this.playheadFrame = Math.max(0, Math.min(frame, this.options.totalFrames));
            this.render();
        }

        if (this.dragState) {
            const { block, startX, startFrame, originalStart, originalEnd } = this.dragState;
            const deltaFrames = frame - startFrame;

            if (block.resizeEdge === 'left') {
                // 调整左边缘
                block.startFrame = Math.max(0, originalStart + deltaFrames);
                if (block.startFrame >= block.endFrame) {
                    block.startFrame = block.endFrame - 1;
                }
            } else if (block.resizeEdge === 'right') {
                // 调整右边缘
                block.endFrame = Math.max(block.startFrame + 1, originalEnd + deltaFrames);
                if (block.endFrame > this.options.totalFrames) {
                    block.endFrame = this.options.totalFrames;
                }
            } else {
                // 移动
                const duration = originalEnd - originalStart;
                let newStart = originalStart + deltaFrames;
                
                // 边界检查
                if (newStart < 0) newStart = 0;
                if (newStart + duration > this.options.totalFrames) {
                    newStart = this.options.totalFrames - duration;
                }
                
                block.startFrame = newStart;
                block.endFrame = newStart + duration;
            }

            this.render();
        }

        // 改变鼠标样式
        if (!this.dragState) {
            let cursor = 'default';
            if (y > TIMELINE_CONFIG.headerHeight + TIMELINE_CONFIG.rulerHeight) {
                cursor = 'crosshair';
                // 检查是否在调整手柄上
                for (const track of this.tracks) {
                    for (const block of track.blocks) {
                        const bx = this.frameToX(block.startFrame);
                        const bw = (block.endFrame - block.startFrame) * this.zoom;
                        if (x >= bx && x <= bx + bw) {
                            if (x < bx + 10 || x > bx + bw - 10) {
                                cursor = 'ew-resize';
                            } else {
                                cursor = 'move';
                            }
                            break;
                        }
                    }
                }
            }
            this.canvas.style.cursor = cursor;
        }
    }

    onMouseUp(e) {
        if (this.dragState) {
            this.dragState.block.dragging = false;
            this.dragState = null;
            this.canvas.classList.remove('dragging');
            this.onChange();
        }
    }

    onWheel(e) {
        e.preventDefault();
        
        if (e.ctrlKey || e.metaKey) {
            // 缩放
            const delta = e.deltaY > 0 ? 0.9 : 1.1;
            this.zoom = Math.max(TIMELINE_CONFIG.minZoom, Math.min(TIMELINE_CONFIG.maxZoom, this.zoom * delta));
            
            // 更新滑块
            const zoomSlider = this.header.querySelector('#zoomSlider');
            const zoomValue = this.header.querySelector('#zoomValue');
            zoomSlider.value = this.zoom;
            zoomValue.textContent = Math.round(this.zoom * 100) + '%';
        } else {
            // 水平滚动
            this.scrollX += e.deltaX + e.deltaY;
            this.scrollX = Math.max(0, this.scrollX);
        }
        
        this.render();
    }

    onDoubleClick(e) {
        const rect = this.canvas.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        const frame = this.xToFrame(x);
        const trackIndex = this.yToTrack(y);

        if (trackIndex >= 0 && trackIndex < this.tracks.length) {
            const track = this.tracks[trackIndex];
            
            // 在点击位置添加一个 1 秒的音频块（占位）
            const startFrame = Math.max(0, frame);
            const durationFrames = this.options.fps; // 1秒
            const endFrame = Math.min(startFrame + durationFrames, this.options.totalFrames);
            
            const block = new AudioBlock(this.nextBlockId++, trackIndex, startFrame, endFrame, { name: 'New Audio' });
            track.blocks.push(block);
            block.selected = true;
            
            this.onChange();
            this.render();
        }
    }

    onKeyDown(e) {
        if (e.key === 'Delete' || e.key === 'Backspace') {
            // 删除选中的块
            for (const track of this.tracks) {
                const toDelete = track.blocks.filter(b => b.selected);
                if (toDelete.length > 0) {
                    track.blocks = track.blocks.filter(b => !b.selected);
                    this.onChange();
                    this.render();
                    break;
                }
            }
        } else if (e.key === 'Escape') {
            // 取消选择
            this.tracks.forEach(t => t.blocks.forEach(b => b.selected = false));
            this.render();
        } else if (e.key === 'ArrowLeft') {
            // 微调选中的块
            this.moveSelectedBlocks(-1);
        } else if (e.key === 'ArrowRight') {
            this.moveSelectedBlocks(1);
        }
    }

    moveSelectedBlocks(delta) {
        for (const track of this.tracks) {
            for (const block of track.blocks) {
                if (block.selected) {
                    const newStart = Math.max(0, Math.min(block.startFrame + delta, this.options.totalFrames - block.duration));
                    const duration = block.duration;
                    block.startFrame = newStart;
                    block.endFrame = newStart + duration;
                }
            }
        }
        this.onChange();
        this.render();
    }

    // 轨道操作
    addTrack(name) {
        const track = new AudioTrack(this.nextTrackId++, name);
        this.tracks.push(track);
        this.render();
    }

    removeTrack(index) {
        if (this.tracks.length > 1) {
            this.tracks.splice(index, 1);
            this.render();
        }
    }

    // 配置导入导出
    exportConfig() {
        const config = {
            fps: this.options.fps,
            totalFrames: this.options.totalFrames,
            tracks: this.tracks.map(track => ({
                id: track.id,
                name: track.name,
                blocks: track.blocks.map(block => ({
                    id: block.id,
                    startFrame: block.startFrame,
                    endFrame: block.endFrame,
                    volume: block.volume,
                    audioData: block.audioData
                }))
            }))
        };

        navigator.clipboard.writeText(JSON.stringify(config, null, 2)).then(() => {
            alert(this.t.exportSuccess);
        });
    }

    showImportModal() {
        const modal = document.createElement('div');
        modal.className = 'audio-timeline-modal';
        modal.innerHTML = `
            <div class="audio-timeline-modal-content">
                <h4>${this.t.import}</h4>
                <textarea id="importTextarea" placeholder='{"fps":24,"totalFrames":1440,"tracks":[...]}'></textarea>
                <div class="buttons">
                    <button class="audio-timeline-btn" id="importCancel">Cancel</button>
                    <button class="audio-timeline-btn" id="importConfirm">OK</button>
                </div>
            </div>
        `;

        document.body.appendChild(modal);

        const textarea = modal.querySelector('#importTextarea');
        textarea.focus();

        modal.querySelector('#importCancel').addEventListener('click', () => modal.remove());
        modal.querySelector('#importConfirm').addEventListener('click', () => {
            try {
                const config = JSON.parse(textarea.value);
                this.importConfig(config);
                modal.remove();
            } catch (err) {
                alert(this.t.importError);
            }
        });

        modal.addEventListener('click', (e) => {
            if (e.target === modal) modal.remove();
        });
    }

    importConfig(config) {
        this.options.fps = config.fps || this.options.fps;
        this.options.totalFrames = config.totalFrames || this.options.totalFrames;
        
        this.tracks = [];
        this.nextTrackId = 1;
        this.nextBlockId = 1;

        if (config.tracks) {
            config.tracks.forEach(trackData => {
                const track = new AudioTrack(trackData.id || this.nextTrackId++, trackData.name);
                this.tracks.push(track);

                if (trackData.blocks) {
                    trackData.blocks.forEach(blockData => {
                        const block = new AudioBlock(
                            blockData.id || this.nextBlockId++,
                            track.id,
                            blockData.startFrame,
                            blockData.endFrame,
                            blockData.audioData
                        );
                        block.volume = blockData.volume || 1.0;
                        track.blocks.push(block);
                    });
                }
            });
        }

        this.render();
        this.onChange();
    }

    // 更新信息栏
    updateInfo() {
        const totalDuration = this.options.totalFrames / this.options.fps;
        this.infoBar.innerHTML = `
            <span>${this.t.fps}: ${this.options.fps}</span>
            <span>${this.t.totalFrames}: ${this.options.totalFrames}</span>
            <span>${this.t.duration}: ${totalDuration.toFixed(2)}s</span>
            <span>${this.t.playhead}: ${this.playheadFrame} (${formatTime(this.playheadFrame, this.options.fps)})</span>
        `;
    }

    // 获取当前配置
    getConfig() {
        return {
            fps: this.options.fps,
            totalFrames: this.options.totalFrames,
            playheadFrame: this.playheadFrame,
            tracks: this.tracks.map(track => ({
                id: track.id,
                name: track.name,
                blocks: track.blocks.map(block => ({
                    startFrame: block.startFrame,
                    endFrame: block.endFrame,
                    volume: block.volume
                }))
            }))
        };
    }

    // 设置配置
    setConfig(config) {
        if (config.fps) this.options.fps = config.fps;
        if (config.totalFrames) this.options.totalFrames = config.totalFrames;
        if (config.tracks) this.importConfig(config);
    }

    // 回调
    onChange() {
        this.options.onChange(this.getConfig());
    }

    // 销毁
    destroy() {
        this.wrapper.remove();
    }
}

// 导出
window.AudioTimelineEditor = AudioTimelineEditor;
