# -*- coding: utf-8 -*-
"""ZHTag —— ComfyUI 中文提示词插件（v1.1.1）

在文本框里打中文（甚至直接写一句自然语言），自动翻成英文 tag：
先在本地词典里做最长匹配，词典没有的片段按设置丢弃/保留/交给兜底翻译，
最后所有英文都用 Danbooru 正名归一并按热度排序，输出干净、可直接喂给模型。

- 节点：ZHTag 中文→英文Tag / ZHTag 中文CLIP编码 / ZHTag 词典查询
- 前端：所有文本输入框支持「失焦自动翻译」，节点右键菜单可手动翻译
- 词库：data/zh_tags.csv（内置 3600+ 条）+ data/zh_extra.csv（日常用语补充）
        + data/danbooru_index.tsv（3 万条正名与热度）+ data/user/ 你自己的词典
- 大词典（约 5 万条社区中文表）不随插件分发，右键菜单「下载/更新社区词典」按需拉取
"""
__version__ = '1.1.1'

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

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS', 'WEB_DIRECTORY', '__version__']
