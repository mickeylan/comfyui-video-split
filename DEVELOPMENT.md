# ComfyUI 定制节点开发文档

基于 comfyui-video-split 项目实际开发经验总结。

---

## 目录

1. [项目结构](#项目结构)
2. [后端节点开发](#后端节点开发)
3. [前端扩展开发](#前端扩展开发)
4. [帮助系统实现](#帮助系统实现)
5. [常见问题与解决方案](#常见问题与解决方案)
6. [最佳实践](#最佳实践)

---

## 项目结构

```
comfyui-video-split/
├── __init__.py          # 入口文件，导出节点映射
├── nodes.py             # 节点实现
├── documentation.py     # 帮助文档（可选，也可放在 JS 中）
├── README.md            # 中文文档
├── README_EN.md         # 英文文档
├── .gitignore           # Git 忽略配置
└── web/
    └── js/
        └── video_split.js  # 前端扩展
```

### 关键文件说明

| 文件 | 作用 |
|------|------|
| `__init__.py` | 导出 `NODE_CLASS_MAPPINGS`、`NODE_DISPLAY_NAME_MAPPINGS`、`WEB_DIRECTORY` |
| `nodes.py` | 定义节点类，包含输入/输出定义和执行逻辑 |
| `web/js/*.js` | 前端扩展，用于 UI 增强、帮助系统、自定义小部件 |

---

## 后端节点开发

### 基本节点结构

```python
class MyNode:
    """节点类文档字符串"""
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "input1": ("IMAGE", {"tooltip": "输入说明"}),
                "input2": ("INT", {"default": 0, "min": 0, "max": 100}),
            },
            "optional": {
                "optional_input": ("IMAGE", {"tooltip": "可选输入"}),
            },
        }
    
    RETURN_TYPES = ("IMAGE", "INT")
    RETURN_NAMES = ("output1", "output2")
    FUNCTION = "execute"  # 执行方法名
    CATEGORY = "video/split"  # 节点分类
    
    def execute(self, input1, input2, optional_input=None):
        # 执行逻辑
        result = do_something(input1, input2)
        return (result, count)
```

### 输入类型

```python
# 基本类型
("IMAGE", {...})      # 图像张量 [B, H, W, C]
("VIDEO", {...})      # 视频对象（新版 API）
("INT", {...})        # 整数
("FLOAT", {...})      # 浮点数
("STRING", {...})     # 字符串

# 下拉选择
("MODE", (["option1", "option2"], {"default": "option1"}))

# 带参数的输入
("INT", {
    "default": 120,
    "min": 1,
    "max": 100000,
    "step": 1,
    "tooltip": "参数说明"
})
```

### 输出列表

```python
# 输出为列表（批量输出）
RETURN_TYPES = ("IMAGE", "INT")
RETURN_NAMES = ("segments", "count")
OUTPUT_IS_LIST = (True, False)  # 第一个是列表，第二个不是

def execute(self, images):
    segments = [...]
    count = len(segments)
    return (segments, count)
```

### 输入为列表

```python
# 接收列表输入
RETURN_TYPES = ("IMAGE", "INT")
INPUT_IS_LIST = True

def execute(self, segments):
    # segments 是列表
    merged = torch.cat(segments, dim=0)
    return (merged, merged.shape[0])
```

### 异常处理

```python
def execute(self, images, segment_index):
    total_frames = images.shape[0]
    
    if segment_index >= total_frames:
        raise ValueError(f"Segment index {segment_index} out of range. Video has {total_frames} frames.")
    
    # 正常处理
    return (images[segment_index],)
```

### 节点映射

```python
# nodes.py 末尾
NODE_CLASS_MAPPINGS = {
    "VideoSegmentInfo": VideoSegmentInfo,
    "GetVideoSegment": GetVideoSegment,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "VideoSegmentInfo": "Video Segment Info",
}

WEB_DIRECTORY = "./web"  # 前端文件目录
```

### 入口文件

```python
# __init__.py
from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS, WEB_DIRECTORY

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS', 'WEB_DIRECTORY']
```

---

## 前端扩展开发

### 基本结构

```javascript
// 获取 app 对象
const { app } = window.comfyAPI.app;

app.registerExtension({
    name: "my-extension",
    
    // 节点定义前调用
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        // 修改节点类型
    },
    
    // 节点创建后调用
    nodeCreated(node) {
        // 修改节点实例
    },
    
    // 应用启动后调用
    async setup(app) {
        // 全局设置
    }
});
```

### 修改节点样式

```javascript
async beforeRegisterNodeDef(nodeType, nodeData, app) {
    if (nodeData.name === "MyNode") {
        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function() {
            if (onNodeCreated) onNodeCreated.apply(this, arguments);
            this.color = "#2d5a27";  // 节点颜色
        };
    }
}
```

### 绘制自定义内容

```javascript
async beforeRegisterNodeDef(nodeType, nodeData, app) {
    const drawFg = nodeType.prototype.onDrawForeground;
    nodeType.prototype.onDrawForeground = function(ctx) {
        if (drawFg) drawFg.apply(this, arguments);
        if (this.flags?.collapsed) return;
        
        // 使用节点相对坐标绘制
        const x = this.size[0] - 20;  // 右侧
        const y = -10;                 // 标题栏
        
        ctx.save();
        ctx.fillStyle = "orange";
        ctx.font = "bold 14px Arial";
        ctx.fillText("?", x, y);
        ctx.restore();
    };
}
```

### 处理点击事件

```javascript
async beforeRegisterNodeDef(nodeType, nodeData, app) {
    const mouseDown = nodeType.prototype.onMouseDown;
    nodeType.prototype.onMouseDown = function(e, localPos, canvas) {
        if (mouseDown) mouseDown.apply(this, arguments);
        
        // localPos 是节点相对坐标！
        const x = this.size[0] - 20;
        const y = -10;
        
        // 检查点击区域
        if (localPos[0] > x - 10 && localPos[0] < x + 10 &&
            localPos[1] > y - 10 && localPos[1] < y + 10) {
            console.log("Clicked!");
            return true;  // 消费事件
        }
    };
}
```

### 坐标系统理解

| 坐标类型 | 说明 | 使用场景 |
|---------|------|---------|
| 画布坐标 | `node.pos[0]`, `node.pos[1]` | 画布级别操作 |
| 节点相对坐标 | `localPos[0]`, `localPos[1]` | `onMouseDown` 参数，相对于节点左上角 |
| 绘制坐标 | `ctx.fillText(x, y)` | 在 `onDrawForeground` 中，原点是节点左上角 |

**关键点**：
- `onDrawForeground` 中绘制使用的是**节点相对坐标**
- `onMouseDown` 的 `localPos` 也是**节点相对坐标**
- 两边坐标系统一致，才能正确检测点击

---

## 帮助系统实现

### 方案一：Python DESCRIPTION（简单）

```python
class MyNode:
    DESCRIPTION = "节点帮助文本，支持简单HTML"
```

**缺点**：不支持复杂 HTML 样式。

### 方案二：前端 JS 实现（推荐）

参考 KJNodes 的实现：

```javascript
const { app } = window.comfyAPI.app;

const helpTexts = {
    "MyNode": {
        "en": "English help text",
        "zh": "中文帮助文本"
    }
};

// 创建样式表
const createStylesheet = () => {
    const style = document.createElement('style');
    style.innerHTML = `
    .my-help-popup {
        background: #333;
        color: #fff;
        padding: 10px;
        border-radius: 8px;
        max-width: 380px;
        position: absolute;
        z-index: 1000;
    }
    `;
    document.head.appendChild(style);
};

// 创建弹出窗口
function createHelpPopup(text, onClose) {
    createStylesheet();
    
    const popup = document.createElement('div');
    popup.className = 'my-help-popup';
    popup.innerHTML = text;  // 用 innerHTML 渲染 HTML
    
    const closeBtn = document.createElement('div');
    closeBtn.textContent = '❌';
    closeBtn.style.cssText = 'position: absolute; top: 0; right: 0; cursor: pointer;';
    closeBtn.onclick = onClose;
    popup.appendChild(closeBtn);
    
    document.body.appendChild(popup);
    return popup;
}

app.registerExtension({
    name: "my-extension",
    
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (!helpTexts[nodeData.name]) return;
        
        let helpPopup = null;
        
        // 绘制 ? 按钮
        const drawFg = nodeType.prototype.onDrawForeground;
        nodeType.prototype.onDrawForeground = function(ctx) {
            if (drawFg) drawFg.apply(this, arguments);
            if (this.flags?.collapsed) return;
            
            // 绘制 ? 图标
            ctx.save();
            ctx.fillStyle = "orange";
            ctx.font = "bold 14px Arial";
            ctx.fillText("?", this.size[0] - 15, -10);
            ctx.restore();
            
            // 更新弹窗位置
            if (helpPopup && this._showHelp) {
                const rect = ctx.canvas.getBoundingClientRect();
                helpPopup.style.left = (this.pos[0] + this.size[0] + 15) + rect.x + "px";
                helpPopup.style.top = (this.pos[1] - 20) + rect.y + "px";
            }
        };
        
        // 处理点击
        const mouseDown = nodeType.prototype.onMouseDown;
        nodeType.prototype.onMouseDown = function(e, localPos, canvas) {
            if (mouseDown) mouseDown.apply(this, arguments);
            
            const iconX = this.size[0] - 15;
            const iconY = -10;
            
            if (localPos[0] > iconX - 10 && localPos[0] < iconX + 10 &&
                localPos[1] > iconY - 10 && localPos[1] < iconY + 10) {
                
                if (this._showHelp) {
                    this._showHelp = false;
                    if (helpPopup) helpPopup.remove();
                    helpPopup = null;
                } else {
                    this._showHelp = true;
                    const lang = localStorage['Comfy.Settings.Comfy.Locale']?.startsWith('zh') ? 'zh' : 'en';
                    const text = helpTexts[this.type]?.[lang] || helpTexts[this.type]?.["en"];
                    helpPopup = createHelpPopup(text, () => {
                        this._showHelp = false;
                        helpPopup.remove();
                        helpPopup = null;
                    });
                }
                return true;
            }
        };
    }
});
```

### 获取用户语言设置

```javascript
function getLang() {
    const locale = localStorage['Comfy.Settings.Comfy.Locale'] || 'en';
    if (locale.startsWith('zh')) return 'zh';
    if (locale.startsWith('ja')) return 'ja';
    if (locale.startsWith('ko')) return 'ko';
    return 'en';
}
```

---

## 常见问题与解决方案

### 1. JS 文件不加载

**症状**：控制台没有 `[Extension] Extension loaded` 日志

**原因**：
- `WEB_DIRECTORY` 路径错误
- import 路径错误

**解决**：
```python
# nodes.py
WEB_DIRECTORY = "./web"  # 正确
```

```javascript
// 正确的 import 路径
import { app } from "../../../scripts/app.js";
```

### 2. 点击检测无效

**症状**：点击没有反应

**原因**：绘制坐标和点击检测坐标不一致

**解决**：统一使用节点相对坐标
```javascript
// 绘制
ctx.fillText("?", this.size[0] - 15, -10);

// 点击检测（必须一致！）
if (localPos[0] > this.size[0] - 25 && localPos[0] < this.size[0] - 5 &&
    localPos[1] > -20 && localPos[1] < 0) {
    // 点击到了
}
```

### 3. HTML 不渲染

**症状**：显示 `<b>text</b>` 原始文本

**原因**：使用了 `textContent` 而不是 `innerHTML`

**解决**：
```javascript
element.innerHTML = htmlText;  // 正确
// element.textContent = htmlText;  // 错误
```

### 4. 节点类型不匹配

**症状**：JS 中判断节点类型无效

**原因**：节点类型名称可能带有前缀

**解决**：
```javascript
// 检查节点类型
console.log(node.type);  // 可能是 "VideoSegmentInfo" 或 "custom_nodes.VideoSegmentInfo"

// 使用 Set 存储，方便检查
const HELP_NODES = new Set(["VideoSegmentInfo", "GetVideoSegment"]);
if (HELP_NODES.has(nodeData.name)) { ... }
```

### 5. 帮助面板位置错误

**症状**：帮助面板显示在错误位置

**解决**：参考 KJNodes 的位置计算
```javascript
const rect = ctx.canvas.getBoundingClientRect();
const scale = app.canvas.ds.scale;

helpPopup.style.left = (node.pos[0] + node.size[0] + 15) * scale + rect.x + "px";
helpPopup.style.top = (node.pos[1] - 20) * scale + rect.y + "px";
```

---

## 最佳实践

### 1. 参考成熟插件

| 插件 | 参考内容 |
|------|---------|
| **KJNodes** | UI 增强、帮助系统、自定义小部件 |
| **VHS** | 视频处理、批量操作 |
| **ComfyUI-Impact-Pack** | 循环节点、复杂交互 |

### 2. 职责分离

- **Python**：节点逻辑、数据处理
- **JavaScript**：UI 增强、帮助系统、交互

### 3. 版本号从低开始

```markdown
## 版本

- v0.1.0 - 初始版本
- v0.1.1 - 修复问题
- v0.2.0 - 新增功能
```

### 4. 文档同步更新

- 修改代码后，同步更新 README.md
- 如果改变节点输入/输出，必须更新文档

### 5. 测试充分

- 改完代码后自己测试
- 检查控制台是否有错误
- 确认功能是否正常

---

## 参考资源

- [ComfyUI 源码](https://github.com/comfyanonymous/ComfyUI)
- [KJNodes 源码](https://github.com/comfyanonymous/ComfyUI-KJNodes)
- [VHS 源码](https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite)
- [ComfyUI 中文社区](https://github.com/comfyanonymous/ComfyUI)

---

**文档版本**: v1.0  
**最后更新**: 2024年