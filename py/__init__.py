# -*- coding: utf-8 -*-
"""ZHTag —— ComfyUI 中文提示词插件（中文 → 英文 tag）。"""
from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
from .routes import register_routes

register_routes()

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']
