# -*- coding: utf-8 -*-
"""ZHTag —— ComfyUI 中文提示词插件（v1.2.0）

像 IDE 一样写提示词：在文本框里打中文或拼音，光标下方直接列出英文 Danbooru tag
候选（↑↓ 选、Enter 采用、Esc 关），词库里没有的词给一行「在线翻译」。
整句翻译（失焦/停顿自动翻）仍然保留，两种用法可以同时开着。

- 补全：中文（蓝发）/ 全拼（lanfa）/ 首字母（lf）/ 多音字（changfa、zhangfa）/ 英文前缀（long_h）
- 数据：data/zh_tags.csv + data/zh_extra.csv（中英词条）、data/danbooru_index.tsv（正名与热度）、
        data/pinyin_chars.tsv（汉字→拼音；构建期用 pypinyin 生成，运行时零依赖）
- 节点：ZHTag 中文→英文Tag / ZHTag 中文CLIP编码 / ZHTag 词典查询
- 大词典（约 5 万条社区中文表）不随插件分发，右键菜单「下载/更新社区词典」按需拉取
"""
__version__ = '1.2.0'

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
