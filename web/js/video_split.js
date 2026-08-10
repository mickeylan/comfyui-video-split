import { app } from "../../scripts/app.js";
import { ComfyWidgets } from "../../scripts/widgets.js";

/**
 * ComfyUI Video Split Extension
 * 
 * Provides custom UI enhancements for video split nodes.
 */
app.registerExtension({
    name: "comfyui-video-split",
    
    /**
     * Called before node type is registered
     */
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        // Add custom styling for video split nodes
        if (nodeData.name.startsWith("Video") || nodeData.name.startsWith("Image Collect")) {
            const onNodeCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                const r = onNodeCreated ? onNodeCreated.apply(this, arguments) : undefined;
                
                // Add category color hint
                this.color = "#2d5a27";  // Green theme for video/split category
                
                return r;
            };
        }
    },
    
    /**
     * Called after graph is configured
     */
    async setup(app) {
        // Console log for debugging
        console.log("[Video Split] Extension loaded");
    },
    
    /**
     * Custom node descriptions and help text
     */
    async getCustomNodeHelp(nodeType, nodeData) {
        const helpMap = {
            "Video Segment Info": {
                description: "Calculate segment information for video splitting.",
                usage: [
                    "1. Connect your video input",
                    "2. Choose split mode: by_duration (seconds) or by_frames (frame count)",
                    "3. Set segment duration or frame count",
                    "4. Connect 'total_segments' output to forLoopStart node"
                ]
            },
            "Get Video Segment": {
                description: "Extract a video segment by index. Supports lazy loading.",
                usage: [
                    "1. Connect the same video as Video Segment Info",
                    "2. Connect 'segment_index' from forLoopStart",
                    "3. Connect 'frames_per_segment' from Video Segment Info",
                    "4. Output goes to your processing nodes"
                ]
            },
            "Image Collect": {
                description: "Collect images in a for loop. Pass accumulated to next iteration.",
                usage: [
                    "1. First iteration: leave 'images' input empty",
                    "2. Connect 'accumulated' output to forLoopEnd",
                    "3. ForLoopEnd will pass accumulated images to next iteration"
                ]
            },
            "Merge Video Segments": {
                description: "Merge multiple video segments back into a single video.",
                usage: [
                    "1. Input accepts a list of VIDEO segments",
                    "2. Outputs merged video with all frames concatenated"
                ]
            },
            "Video Split (Multiple)": {
                description: "Split video into all segments at once. Returns a list.",
                usage: [
                    "1. Connect video input",
                    "2. Configure split mode and segment size",
                    "3. Output is a list of video segments",
                    "4. Use with nodes that accept VIDEO list input"
                ]
            }
        };
        
        if (helpMap[nodeData.name]) {
            return helpMap[nodeData.name];
        }
    }
});