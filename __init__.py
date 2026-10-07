# -*- coding: utf-8 -*-
"""ZHTag —— ComfyUI 中文提示词插件

在文本框里打中文，自动查 tag 词典翻成英文 tag；词典没有的片段走兜底翻译
（本地/远程 OpenAI 兼容接口，或在线翻译），再兜不住就保留中文不丢信息。

- 节点：ZHTag 中文→英文Tag / ZHTag 中文CLIP编码 / ZHTag 词典查询
- 前端：给所有文本输入框加「中文→英文Tag」右键菜单，可选自动翻译
- 词库：data/zh_tags.csv（内置 3600+ 条）+ data/user/ 下你自己的词典，全部自动加载
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

try:                                    # 常规：以包的形式加载（ComfyUI 默认行为）
    from .py.nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
    from .py.routes import register_routes
except Exception:                       # 兜底：被当成普通目录加载时
    from py.nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS  # type: ignore
    from py.routes import register_routes  # type: ignore

register_routes()

WEB_DIRECTORY = './web'                 # 前端扩展（web/js/zhtag.js）

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS', 'WEB_DIRECTORY']
