"""
批量渲染节点
"""
import torch
import numpy as np
import os
import json
import time
import asyncio
import threading
from typing import List, Dict, Any, Optional


# ============================================================
# Batch Render Manager - 批量渲染管理器
# ============================================================

class BatchRenderManager:
    """
    批量渲染管理器（单例模式）
    用于跨节点共享渲染状态
    """
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance.queue = []
                    cls._instance.results = []
                    cls._instance.current_index = 0
                    cls._instance.is_running = False
                    cls._instance.stop_flag = False
        return cls._instance
    
    def add_task(self, task: Dict):
        """添加任务到队列"""
        self.queue.append(task)
    
    def clear_queue(self):
        """清空队列"""
        self.queue = []
        self.results = []
        self.current_index = 0
    
    def get_status(self) -> Dict:
        """获取当前状态"""
        return {
            "total": len(self.queue),
            "current": self.current_index,
            "is_running": self.is_running,
            "results": self.results,
        }


# ============================================================
# Batch Render Queue - 批量渲染队列节点
# ============================================================

class BatchRenderQueue:
    """
    批量渲染队列节点。
    接收工作流路径列表，添加到渲染队列。
    """
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "workflow_paths": ("STRING", {
                    "default": "",
                    "multiline": True,
                    "tooltip": "工作流 JSON 文件路径，每行一个"
                }),
                "output_dir": ("STRING", {
                    "default": "./output/batch",
                    "tooltip": "输出目录"
                }),
                "clear_previous": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "是否清空之前的队列"
                }),
            },
        }

    RETURN_TYPES = ("STRING", "INT")
    RETURN_NAMES = ("status", "queue_count")
    FUNCTION = "execute"
    CATEGORY = "video/batch"

    def execute(self, workflow_paths: str, output_dir: str, clear_previous: bool):
        
        manager = BatchRenderManager()
        
        # 清空之前的队列
        if clear_previous:
            manager.clear_queue()
        
        # 解析工作流路径
        paths = [p.strip() for p in workflow_paths.strip().split('\n') if p.strip()]
        
        if not paths:
            return ("No workflow paths provided", 0)
        
        # 验证路径
        valid_paths = []
        invalid_paths = []
        
        for path in paths:
            # 支持相对路径和绝对路径
            if not os.path.isabs(path):
                # 尝试多个可能的基目录
                possible_paths = [
                    path,
                    os.path.join(os.getcwd(), path),
                    os.path.join(os.getcwd(), "workflows", path),
                ]
                found = False
                for p in possible_paths:
                    if os.path.exists(p):
                        path = p
                        found = True
                        break
                if not found:
                    invalid_paths.append(path)
                    continue
            
            if os.path.exists(path) and path.endswith('.json'):
                valid_paths.append(path)
            else:
                invalid_paths.append(path)
        
        # 添加到队列
        for i, path in enumerate(valid_paths):
            manager.add_task({
                "index": len(manager.queue),
                "path": path,
                "output_dir": output_dir,
                "status": "pending",
            })
        
        status_msg = f"Added {len(valid_paths)} workflows to queue"
        if invalid_paths:
            status_msg += f"\nInvalid paths: {len(invalid_paths)}"
        
        return (status_msg, len(manager.queue))


# ============================================================
# Batch Render Status - 批量渲染状态节点
# ============================================================

class BatchRenderStatus:
    """
    获取批量渲染状态。
    """
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {},
        }

    RETURN_TYPES = ("INT", "INT", "STRING")
    RETURN_NAMES = ("current", "total", "status_json")
    FUNCTION = "execute"
    CATEGORY = "video/batch"

    def execute(self):
        
        manager = BatchRenderManager()
        status = manager.get_status()
        
        import json
        status_json = json.dumps(status, ensure_ascii=False, indent=2)
        
        return (status["current"], status["total"], status_json)


# ============================================================
# Batch Render Execute - 批量渲染执行节点
# ============================================================

class BatchRenderExecute:
    """
    执行批量渲染队列。
    
    注意：这个节点会按顺序执行队列中的所有工作流，
    可能需要很长时间，请确保队列设置正确。
    
    由于 ComfyUI 节点执行的限制，这个节点实际上是
    一个"模拟"执行，它只返回队列信息。
    
    真正的批量渲染需要通过 ComfyUI 的 API 或前端触发。
    """
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "execute": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "设为 True 开始执行（注意：实际需要配合前端/API）"
                }),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("instructions",)
    FUNCTION = "execute"
    CATEGORY = "video/batch"

    def execute(self, execute: bool):
        
        manager = BatchRenderManager()
        status = manager.get_status()
        
        if not execute:
            return ("Set 'execute' to True to start batch rendering\n\n"
                    f"Queue: {status['total']} workflows pending",)
        
        # 生成执行指令
        instructions = f"""
批量渲染队列已准备就绪：

总任务数: {status['total']}

执行方式：
1. 使用 ComfyUI API 批量提交：
   POST /prompt 多次，每次传递一个工作流

2. 使用 Python 脚本：
   ```python
   import requests
   import json
   
   for i, task in enumerate(queue):
       with open(task['path']) as f:
           workflow = json.load(f)
       requests.post('http://127.0.0.1:8188/prompt', json={'prompt': workflow})
   ```

3. 使用 ComfyUI 前端：
   多次点击 Queue Prompt 按钮添加任务

队列状态会在每次渲染完成后更新。
"""
        return (instructions,)


# ============================================================
# Batch Workflow From Images - 从图像批次创建工作流
# ============================================================

class BatchWorkflowFromImages:
    """
    将图像批次转换为可批量处理的工作流配置。
    
    这个节点不直接创建工作流文件，而是将批次信息
    传递给后续节点进行批量处理。
    """
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "图像批次"}),
                "batch_name": ("STRING", {"default": "batch", "tooltip": "批次名称"}),
            },
        }

    RETURN_TYPES = ("BATCH_INFO",)
    RETURN_NAMES = ("batch_info",)
    FUNCTION = "execute"
    CATEGORY = "video/batch"

    def execute(self, images: torch.Tensor, batch_name: str):
        
        if images is None or images.numel() == 0:
            return ({"count": 0, "name": batch_name},)
        
        batch_info = {
            "count": images.shape[0],
            "name": batch_name,
            "shape": list(images.shape),
        }
        
        return (batch_info,)


# ============================================================
# Batch Process Images - 批量处理图像
# ============================================================

class BatchProcessImages:
    """
    批量处理图像节点。
    对输入的每个图像批次应用处理。
    """
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "图像批次"}),
                "process_all": ("BOOLEAN", {"default": True, 
                    "tooltip": "True: 处理整个批次; False: 仅处理第一张"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "INT")
    RETURN_NAMES = ("processed_images", "processed_count")
    FUNCTION = "execute"
    CATEGORY = "video/batch"

    def execute(self, images: torch.Tensor, process_all: bool):
        
        if images is None or images.numel() == 0:
            return (torch.zeros(1, 64, 64, 3), 0)
        
        if not process_all:
            # 只处理第一张
            return (images[0:1], 1)
        
        # 处理整个批次（直接返回，实际处理由下游节点完成）
        count = images.shape[0]
        return (images, count)


# ============================================================
# Node Mappings
# ============================================================

BATCH_NODE_CLASS_MAPPINGS = {
    "BatchRenderQueue": BatchRenderQueue,
    "BatchRenderStatus": BatchRenderStatus,
    "BatchRenderExecute": BatchRenderExecute,
    "BatchWorkflowFromImages": BatchWorkflowFromImages,
    "BatchProcessImages": BatchProcessImages,
}

BATCH_NODE_DISPLAY_NAME_MAPPINGS = {
    "BatchRenderQueue": "Batch Render Queue",
    "BatchRenderStatus": "Batch Render Status",
    "BatchRenderExecute": "Batch Render Execute",
    "BatchWorkflowFromImages": "Batch Workflow From Images",
    "BatchProcessImages": "Batch Process Images",
}