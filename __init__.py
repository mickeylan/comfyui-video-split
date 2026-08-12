from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS, WEB_DIRECTORY

# 导入音频节点
try:
    from .audio_nodes import AUDIO_NODE_CLASS_MAPPINGS, AUDIO_NODE_DISPLAY_NAME_MAPPINGS
    NODE_CLASS_MAPPINGS.update(AUDIO_NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(AUDIO_NODE_DISPLAY_NAME_MAPPINGS)
except ImportError as e:
    print(f"[Video Split] Warning: Audio nodes not loaded: {e}")

# 导入文字节点
try:
    from .text_nodes import TEXT_NODE_CLASS_MAPPINGS, TEXT_NODE_DISPLAY_NAME_MAPPINGS
    NODE_CLASS_MAPPINGS.update(TEXT_NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(TEXT_NODE_DISPLAY_NAME_MAPPINGS)
except ImportError as e:
    print(f"[Video Split] Warning: Text nodes not loaded: {e}")

# 导入滤镜节点
try:
    from .filter_nodes import FILTER_NODE_CLASS_MAPPINGS, FILTER_NODE_DISPLAY_NAME_MAPPINGS
    NODE_CLASS_MAPPINGS.update(FILTER_NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(FILTER_NODE_DISPLAY_NAME_MAPPINGS)
except ImportError as e:
    print(f"[Video Split] Warning: Filter nodes not loaded: {e}")

# 导入转场节点
try:
    from .transition_nodes import TRANSITION_NODE_CLASS_MAPPINGS, TRANSITION_NODE_DISPLAY_NAME_MAPPINGS
    NODE_CLASS_MAPPINGS.update(TRANSITION_NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(TRANSITION_NODE_DISPLAY_NAME_MAPPINGS)
except ImportError as e:
    print(f"[Video Split] Warning: Transition nodes not loaded: {e}")

# 导入特效节点
try:
    from .effect_nodes import EFFECT_NODE_CLASS_MAPPINGS, EFFECT_NODE_DISPLAY_NAME_MAPPINGS
    NODE_CLASS_MAPPINGS.update(EFFECT_NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(EFFECT_NODE_DISPLAY_NAME_MAPPINGS)
except ImportError as e:
    print(f"[Video Split] Warning: Effect nodes not loaded: {e}")

# 导入 AI 辅助节点
try:
    from .ai_nodes import AI_NODE_CLASS_MAPPINGS, AI_NODE_DISPLAY_NAME_MAPPINGS
    NODE_CLASS_MAPPINGS.update(AI_NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(AI_NODE_DISPLAY_NAME_MAPPINGS)
except ImportError as e:
    print(f"[Video Split] Warning: AI nodes not loaded: {e}")

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS', 'WEB_DIRECTORY']