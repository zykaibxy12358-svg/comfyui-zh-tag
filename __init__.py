# -*- coding: utf-8 -*-
"""ZHTag —— ComfyUI 中文提示词插件（v1.2.7）

像 IDE 一样写提示词：在文本框里打中文、拼音或英文词，光标下方直接列出英文 Danbooru tag
候选（↑↓ 选、Enter 采用、Esc 关），**每一行都带中文**（英文候选也会补中文注释）；
词库里没有的词给一行「在线翻译」。

- 翻译方式一档到底：**词典（不联网）/ 谷歌 / 微软 / 百度 / 有道 / LLM**，弹层右上角点一下即切
- **跑图不干等**：纯英文输入原样通过、执行时网络超时只 6 秒、失败一次就不再试；
  按 ComfyUI 的「中断」会立刻放弃正在进行的翻译
- 补全：中文（蓝发）/ 拼音（lanfa、smw、多音字 changfa）/ 英文 tag 前缀（long_h）/ 英文整词联想
- **词组制度**：巨大乳房 → huge breasts（真实 Danbooru 标签）；黑色蕾丝 → black lace
- **中文注释**：每一行都有中文；带介词的按中文语序拼（cum on breasts → 乳房上的精液）
- **词族联想**：输入 breasts 或 乳房，会把 large breasts / huge breasts / cum on breasts … 整个词族列出来
- **点别的地方就关**：候选框在点画布/别的节点/侧栏时立刻收起
- **子图友好**：有个纯插口输入「提示词(连线优先)」——在子图里连它，中文文本框照样能打字
- 数据：data/zh_tags.csv + data/zh_extra.csv（中英词条）、data/danbooru_index.tsv（正名与热度）、
        data/pinyin_chars.tsv（汉字→拼音；构建期用 pypinyin 生成，运行时零依赖）
- 节点：ZHTag 中文→英文Tag / ZHTag 中文CLIP编码 / ZHTag 词典查询
"""
__version__ = '1.2.7'

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
