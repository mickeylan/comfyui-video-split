import { app } from "../../scripts/app.js";

/**
 * ComfyUI Video Split Extension
 * 
 * Provides custom UI enhancements for video split nodes.
 */

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
        console.log("[Video Split] Extension loaded");
    },
});