const { app } = window.comfyAPI.app;

const STYLE = `
.narration-director { display:flex; flex-direction:column; gap:8px; width:100%; padding:6px; box-sizing:border-box; color:#ddd; font:12px sans-serif; }
.narration-director canvas { width:100%; height:110px; background:#181818; border:1px solid #444; border-radius:5px; }
.narration-director table { width:100%; border-collapse:collapse; }
.narration-director th,.narration-director td { padding:4px; border-bottom:1px solid #333; text-align:left; }
.narration-director input { width:100%; box-sizing:border-box; background:#222; color:#ddd; border:1px solid #444; border-radius:3px; padding:3px; }
.narration-director button { background:#292929; color:#ddd; border:1px solid #555; border-radius:4px; padding:5px 9px; cursor:pointer; }
.narration-director .actions { display:flex; gap:6px; }
.narration-director .hint { color:#999; }
`;

function installStyle() {
    if (document.getElementById("video-split-narration-style")) return;
    const style = document.createElement("style");
    style.id = "video-split-narration-style";
    style.textContent = STYLE;
    document.head.appendChild(style);
}

function hideWidget(widget) {
    widget.hidden = true;
    widget.computeSize = () => [0, -4];
    widget.draw = () => {};
    if (widget.element) widget.element.style.display = "none";
}

function parseTimeline(widget) {
    if (!widget?.value) return [];
    try {
        const data = JSON.parse(widget.value);
        return Array.isArray(data.segments) ? data.segments : [];
    } catch (_) {
        return [];
    }
}

function durationSeconds(node) {
    const frames = Number(node.widgets?.find(w => w.name === "total_frames")?.value) || 1440;
    const fps = Number(node.widgets?.find(w => w.name === "fps")?.value) || 24;
    return frames / fps;
}

function createDirector(node) {
    installStyle();
    const timelineWidget = node.widgets?.find(w => w.name === "timeline_data");
    if (!timelineWidget) return;
    hideWidget(timelineWidget);

    const root = document.createElement("div");
    root.className = "narration-director";
    const hint = document.createElement("div");
    hint.className = "hint";
    hint.textContent = "Connect IndexTTS2 AUDIO through Narration Cue nodes. Cue IDs link rows to inputs.";
    root.appendChild(hint);

    const canvas = document.createElement("canvas");
    canvas.width = 760;
    canvas.height = 110;
    root.appendChild(canvas);

    const table = document.createElement("table");
    table.innerHTML = "<thead><tr><th>ID</th><th>Start</th><th>End</th><th>Volume</th><th>Script label</th><th></th></tr></thead>";
    const body = document.createElement("tbody");
    table.appendChild(body);
    root.appendChild(table);

    const actions = document.createElement("div");
    actions.className = "actions";
    const add = document.createElement("button");
    add.textContent = "Add cue override";
    const clear = document.createElement("button");
    clear.textContent = "Clear overrides";
    actions.append(add, clear);
    root.appendChild(actions);

    let segments = parseTimeline(timelineWidget);
    let drag = null;

    function save() {
        timelineWidget.value = JSON.stringify({segments});
        timelineWidget.callback?.(timelineWidget.value);
        node.setDirtyCanvas?.(true, true);
    }

    function draw() {
        const ctx = canvas.getContext("2d");
        const duration = Math.max(0.001, durationSeconds(node));
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = "#181818";
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.strokeStyle = "#555";
        ctx.fillStyle = "#aaa";
        ctx.font = "11px monospace";
        const step = duration <= 60 ? 5 : duration <= 300 ? 30 : 60;
        for (let time = 0; time <= duration; time += step) {
            const x = time / duration * canvas.width;
            ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, 18); ctx.stroke();
            ctx.fillText(`${Math.floor(time / 60)}:${String(Math.floor(time % 60)).padStart(2, "0")}`, x + 2, 12);
        }
        segments.forEach((segment, index) => {
            const start = Math.max(0, Number(segment.start) || 0);
            const end = Math.min(duration, Number(segment.end) || start);
            const x = start / duration * canvas.width;
            const width = Math.max(3, (end - start) / duration * canvas.width);
            ctx.fillStyle = `hsl(${(index * 67) % 360} 60% 45%)`;
            ctx.fillRect(x, 28, width, 64);
            ctx.fillStyle = "white";
            ctx.fillText(segment.id || `cue_${index + 1}`, x + 4, 46);
            segment._x = x; segment._width = width;
        });
    }

    function renderRows() {
        body.replaceChildren();
        segments.forEach((segment, index) => {
            const row = document.createElement("tr");
            for (const [key, type, step] of [["id", "text"], ["start", "number", "0.01"], ["end", "number", "0.01"], ["volume", "number", "0.05"], ["text", "text"]]) {
                const cell = document.createElement("td");
                const input = document.createElement("input");
                input.type = type;
                if (step) input.step = step;
                input.value = segment[key] ?? (key === "volume" ? 1 : "");
                input.addEventListener("change", () => {
                    segment[key] = type === "number" ? Number(input.value) : input.value;
                    save(); draw();
                });
                cell.appendChild(input);
                row.appendChild(cell);
            }
            const cell = document.createElement("td");
            const remove = document.createElement("button");
            remove.textContent = "×";
            remove.addEventListener("click", () => { segments.splice(index, 1); save(); renderRows(); draw(); });
            cell.appendChild(remove); row.appendChild(cell); body.appendChild(row);
        });
    }

    canvas.addEventListener("mousedown", event => {
        const x = (event.offsetX / canvas.clientWidth) * canvas.width;
        const index = segments.findIndex(segment => x >= segment._x && x <= segment._x + segment._width);
        if (index >= 0) drag = {index, x, start: Number(segments[index].start) || 0, end: Number(segments[index].end) || 0};
    });
    canvas.addEventListener("mousemove", event => {
        if (!drag) return;
        const duration = durationSeconds(node);
        const x = (event.offsetX / canvas.clientWidth) * canvas.width;
        const delta = (x - drag.x) / canvas.width * duration;
        const length = drag.end - drag.start;
        const start = Math.max(0, Math.min(duration - length, drag.start + delta));
        segments[drag.index].start = Math.round(start * 100) / 100;
        segments[drag.index].end = Math.round((start + length) * 100) / 100;
        draw();
    });
    window.addEventListener("mouseup", () => { if (drag) { drag = null; save(); renderRows(); } });
    add.addEventListener("click", () => {
        const index = segments.length + 1;
        segments.push({id:`cue_${index}`, start:0, end:5, volume:1, text:""});
        save(); renderRows(); draw();
    });
    clear.addEventListener("click", () => { segments = []; save(); renderRows(); draw(); });

    node.addDOMWidget("narration_director", "div", root, {serialize:false});
    node.setSize([Math.max(node.size[0], 780), Math.max(node.size[1], 420)]);
    renderRows(); draw();
}

app.registerExtension({
    name: "comfyui-video-split.narration-director",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "VideoSplitNarrationDirector") return;
        const original = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function() {
            original?.apply(this, arguments);
            createDirector(this);
        };
    },
});
