/**
 * LTX Video Unlimited Preview - 前端预览组件
 * 
 * 在浏览器中实时预览分块采样过程。
 * 来自 ComfyUI-MiniMax-H3-Sampler-Unlimited 的架构设计。
 */

const { app } = window.comfyAPI.app;
const { api } = window.comfyAPI.api;


/**
 * 在嵌套图中查找节点
 */
function findNode(rootGraph, qualifiedId) {
    const parts = String(qualifiedId).split(":");
    let graph = rootGraph;
    for (let index = 0; index < parts.length - 1; index++) {
        const node = graph?.getNodeById?.(Number(parts[index]));
        if (!node?.subgraph) return null;
        graph = node.subgraph;
    }
    return graph?.getNodeById?.(Number(parts[parts.length - 1])) || null;
}


/**
 * 监听预览事件
 */
api.addEventListener("ltxv_unlimited_preview", event => {
    const data = event.detail;
    const node = data?.node_id == null ? null : findNode(app.graph, data.node_id);
    node?._ltxvUnlimitedPreview?.(data);
});


/**
 * 注册预览扩展
 */
app.registerExtension({
    name: "VideoSplit.LTXVUnlimitedPreview",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData?.name !== "LTXVUnlimitedPreview") return;

        const previousCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            previousCreated?.apply(this, arguments);

            const node = this;

            // 创建预览容器
            const root = document.createElement("div");
            root.style.cssText = `
                display: flex;
                flex-direction: column;
                width: 100%;
                height: 100%;
                min-height: 280px;
                background: #111;
                border-radius: 6px;
                overflow: hidden;
            `;

            // 预览图像
            const image = document.createElement("img");
            image.style.cssText = `
                display: block;
                width: 100%;
                height: calc(100% - 34px);
                object-fit: contain;
                background: #090909;
            `;
            image.draggable = false;
            root.appendChild(image);

            // 状态栏
            const status = document.createElement("div");
            status.style.cssText = `
                height: 34px;
                box-sizing: border-box;
                padding: 8px 10px;
                color: #ddd;
                font: 12px sans-serif;
                background: #1b1b1b;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            `;
            status.textContent = "Waiting for LTXVUnlimitedSampler...";
            root.appendChild(status);

            // 状态变量
            let execution = null;
            let chunkCount = 0;
            let chunks = [];
            let durations = [];
            let playing = 0;
            let timer = null;
            let imageUpdate = 0;

            /**
             * 停止播放
             */
            function stop() {
                if (timer != null) clearTimeout(timer);
                timer = null;
            }

            /**
             * 检查分块是否可用
             */
            function available(index) {
                return typeof chunks[index] === "string" && chunks[index].length > 0;
            }

            /**
             * 显示指定分块
             */
            function show(index) {
                if (!available(index)) return;
                playing = index;
                const update = ++imageUpdate;
                image.removeAttribute("src");
                requestAnimationFrame(() => {
                    if (update === imageUpdate) image.src = chunks[index];
                });
                stop();
                timer = setTimeout(() => {
                    let next = index + 1;
                    while (next < chunkCount && !available(next)) next++;
                    if (next >= chunkCount) next = 0;
                    while (next < chunkCount && !available(next)) next++;
                    if (next < chunkCount) show(next);
                }, Math.max(100, durations[index] || 1000));
            }

            /**
             * 处理预览数据
             */
            node._ltxvUnlimitedPreview = data => {
                if (data.action === "reset") {
                    // 重置状态
                    execution = data.execution;
                    chunkCount = data.chunk_count || 0;
                    chunks = new Array(chunkCount);
                    durations = new Array(chunkCount);
                    playing = 0;
                    stop();
                    imageUpdate++;
                    image.removeAttribute("src");
                    status.textContent = `Preparing ${chunkCount} chunks...`;
                    return;
                }

                if (data.execution !== execution) return;

                if (data.action === "complete") {
                    // 完成
                    status.textContent = `Complete - ${chunkCount} chunks`;
                    if (timer == null && available(0)) show(0);
                    return;
                }

                if (data.action !== "chunk" || !data.image) return;

                // 更新分块
                const index = data.chunk;
                chunks[index] = `data:image/webp;base64,${data.image}`;
                durations[index] = data.duration_ms;
                status.textContent = `Chunk ${index + 1}/${data.chunk_count} - step ${data.step}/${data.steps} - output frames ${data.output_start}-${data.output_end}`;

                if (timer == null || index === playing) {
                    show(index === playing ? index : 0);
                }
            };

            // 添加 DOM widget
            node.addDOMWidget("preview", "ltxv_unlimited_preview", root, { serialize: false });
            node.setSize([
                Math.max(node.size?.[0] || 420, 420),
                Math.max(node.size?.[1] || 420, 420)
            ]);

            // 节点移除时清理
            const previousRemoved = node.onRemoved;
            node.onRemoved = function () {
                stop();
                imageUpdate++;
                node._ltxvUnlimitedPreview = null;
                previousRemoved?.apply(this, arguments);
            };
        };
    },
});
