# -*- coding: utf-8 -*-
"""ComfyUI 节点定义。

1. ZHTag 中文→英文Tag      中文提示词 → 英文 tag 串（+ 未翻译项报告）
2. ZHTag 中文CLIP编码      中文 → 英文 → 直接编码成 CONDITIONING（省一个节点）
3. ZHTag 词典查询          查一个中文词对应哪些英文 tag（调试词库用）
"""
from __future__ import annotations

from .dictionary import get_dictionary
from .translator import FallbackTranslator
import os

CATEGORY = 'ZHTag/中文Tag'

_TRANSLATOR = None


def translator() -> FallbackTranslator:
    global _TRANSLATOR
    if _TRANSLATOR is None:
        from .dictionary import default_data_dirs
        dirs = default_data_dirs()
        user_dir = dirs[-1] if dirs else os.path.join(os.getcwd(), 'data', 'user')
        _TRANSLATOR = FallbackTranslator(user_dir)
    return _TRANSLATOR


def do_translate(text: str, mode: str = 'tags', dedupe: bool = True,
                 keep_unknown: bool = True, use_fallback: bool = False,
                 first_only: bool = True):
    dic = get_dictionary()
    fb = translator() if use_fallback else None
    result, report = dic.translate(text, mode=mode, dedupe=dedupe,
                                   keep_unknown=keep_unknown, fallback=fb,
                                   first_only=first_only)
    if fb is not None:
        fb.save_cache()
    return result, report


class ZHTagTranslate:
    """中文提示词 → 英文 tag 串。未命中词典的片段按配置兜底翻译，兜不住就原样保留。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            'required': {
                '中文提示词': ('STRING', {'multiline': True, 'dynamicPrompts': False,
                                          'default': '一个女孩站在樱花树下微笑，长发，黄昏，电影感光线'}),
                '输出模式': (['tags（逗号分隔的 tag 串）', 'raw（保留换行与顺序）'],),
                '去重': ('BOOLEAN', {'default': True}),
                '未命中时保留中文': ('BOOLEAN', {'default': True}),
                '用兜底翻译（LLM/在线）': ('BOOLEAN', {'default': False}),
                '同义词': (['只输出最佳英文', '输出全部同义写法'],),
            },
        }

    RETURN_TYPES = ('STRING', 'STRING')
    RETURN_NAMES = ('英文提示词', '未命中报告')
    FUNCTION = 'run'
    CATEGORY = CATEGORY
    DESCRIPTION = '把中文提示词按内置 tag 词典翻译成英文；词典没有的片段可选走兜底翻译。'

    def run(self, **kw):
        text = kw.get('中文提示词', '')
        mode = 'raw' if str(kw.get('输出模式', '')).startswith('raw') else 'tags'
        out, report = do_translate(text, mode=mode, dedupe=bool(kw.get('去重', True)),
                                   keep_unknown=bool(kw.get('未命中时保留中文', True)),
                                   use_fallback=bool(kw.get('用兜底翻译（LLM/在线）', False)),
                                   first_only=not str(kw.get('同义词', '')).startswith('输出全部'))
        unknown = report.get('unknown') or []
        info = (f"词典命中 {report['matched']} 段；兜底翻译 {report['translated']} 段；"
                f"保留原文 {report['kept']} 段；词库 {report['entries']} 条")
        if unknown:
            info += '\n未命中：' + '、'.join(dict.fromkeys(unknown))[:500]
        print('[ZHTag] ' + info.splitlines()[0])
        return (out, info)


class ZHTagQuery:
    """查词典：一个中文词 → 英文 tag 候选。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'中文': ('STRING', {'default': '双马尾'})}}

    RETURN_TYPES = ('STRING', 'STRING')
    RETURN_NAMES = ('英文候选', '状态')
    FUNCTION = 'run'
    CATEGORY = CATEGORY

    def run(self, 中文=''):
        dic = get_dictionary()
        hits = dic.lookup(中文)
        seg = dic.longest_match(中文) if not hits else []
        detail = '；'.join(f'{zh}→{"/".join(ens)}' for zh, ens in seg if ens)
        result = ', '.join(hits) if hits else detail
        status = f'词典 {dic.size} 条；{"精确命中" if hits else ("拆分命中" if result else "未命中")}'
        return (result, status)


def _build_clip_node():
    """中文 → 英文 → CLIPTextEncode。ComfyUI 结构变了就自动不注册这个节点。"""
    try:
        import nodes as comfy_nodes  # type: ignore
        CLIPTextEncode = getattr(comfy_nodes, 'CLIPTextEncode', None)
        if CLIPTextEncode is None:
            return None
    except Exception:
        return None

    class ZHTagClipEncode:
        @classmethod
        def INPUT_TYPES(cls):
            return {
                'required': {
                    'clip': ('CLIP',),
                    '中文提示词': ('STRING', {'multiline': True, 'dynamicPrompts': False, 'default': ''}),
                    '用兜底翻译（LLM/在线）': ('BOOLEAN', {'default': False}),
                },
            }

        RETURN_TYPES = ('CONDITIONING', 'STRING')
        RETURN_NAMES = ('条件', '英文提示词')
        FUNCTION = 'run'
        CATEGORY = CATEGORY
        DESCRIPTION = '中文提示词 → 英文 tag → 直接编码，省掉中间一个节点。'

        def run(self, clip=None, **kw):
            text = kw.get('中文提示词', '')
            use_fb = bool(kw.get('用兜底翻译（LLM/在线）', False))
            english, _report = do_translate(text, mode='tags', dedupe=True,
                                            keep_unknown=True, use_fallback=use_fb)
            node = CLIPTextEncode()
            cond, = node.encode(clip, english)
            return (cond, english)

    return ZHTagClipEncode


NODE_CLASS_MAPPINGS = {
    'ZHTagTranslate': ZHTagTranslate,
    'ZHTagQuery': ZHTagQuery,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    'ZHTagTranslate': 'ZHTag 中文→英文Tag',
    'ZHTagQuery': 'ZHTag 词典查询',
}

_clip_node = _build_clip_node()
if _clip_node is not None:
    NODE_CLASS_MAPPINGS['ZHTagClipEncode'] = _clip_node
    NODE_DISPLAY_NAME_MAPPINGS['ZHTagClipEncode'] = 'ZHTag 中文CLIP编码'
