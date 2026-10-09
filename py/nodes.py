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
                 first_only: bool = True, unknown_mode: str = None,
                 normalize: bool = True, underscore: bool = False):
    dic = get_dictionary()
    fb = translator() if use_fallback else None
    if unknown_mode is None:
        unknown_mode = 'keep' if keep_unknown else 'drop'
    result, report = dic.translate(text, mode=mode, dedupe=dedupe,
                                   keep_unknown=keep_unknown, fallback=fb,
                                   first_only=first_only, unknown_mode=unknown_mode,
                                   normalize=normalize, underscore=underscore)
    if fb is not None:
        fb.save_cache()
    return result, report


UNKNOWN_MODES = ['跟随「未命中时保留中文」开关（推荐）',
                 '丢弃未命中（只写进报告）',
                 '保留中文原文',
                 '交给兜底翻译（LLM/在线）']


def unknown_mode_of(value):
    """下拉文字 → 策略。返回 None 表示「跟随旧开关」。

    兼容旧值：v1.1.0 的下拉写法（'丢弃未命中（推荐，…）'/'保留中文原文'/…）前缀相同，
    所以老工作流里存下来的值也能正确识别；存的是 bool 则返回 None，走旧开关。
    """
    v = str(value or '')
    if v.startswith('保留'):
        return 'keep'
    if v.startswith('交给'):
        return 'fallback'
    if v.startswith('丢弃'):
        return 'drop'
    return None


class ZHTagTranslate:
    """中文提示词 → 英文 tag 串。未命中词典的片段按配置兜底翻译，兜不住就原样保留。

    ⚠ 输入顺序不能改：ComfyUI 的工作流里 widgets_values 是**按位置**存的，
    在中间插入新输入会让老工作流的取值整体错位（v1.1.0 踩过这个坑：
    老工作流把 True 塞进了「未命中处理」下拉 → prompt_outputs_failed_validation）。
    新增输入一律追加到最后，并且 BOOLEAN 放前面、COMBO 放最后
    （BOOLEAN 会被 bool(val) 兜住，COMBO 是唯一会因取值不在列表而校验失败的）。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            'required': {
                '中文提示词': ('STRING', {'multiline': True, 'dynamicPrompts': False,
                                          'default': '一个蓝发漂亮姑娘站在樱花树下微笑，长发，黄昏，电影感光线'}),
                '输出模式': (['tags（逗号分隔的 tag 串）', 'raw（保留换行与顺序）'],),
                '去重': ('BOOLEAN', {'default': True}),
                '未命中时保留中文': ('BOOLEAN', {'default': False,
                                                 'tooltip': '默认关：没查到的中文片段直接丢掉，只写进「未命中报告」'}),
                '用兜底翻译（LLM/在线）': ('BOOLEAN', {'default': False}),
                '同义词': (['只输出最佳英文', '输出全部同义写法'],),
            },
            # 新加的输入一律放 optional：老工作流里没有这两项时也能直接跑，不会被
            # required_input_missing 拦住（缺失时按「跟随旧开关 / 规范化开」处理）。
            'optional': {
                'Danbooru 规范化': ('BOOLEAN', {'default': True}),
                '未命中处理': (UNKNOWN_MODES,),
                # 单独的「连线用」输入口（forceInput = 只做插口，不占小部件位置）：
                # 在子图里把它提升成子图输入并连线，中文文本框依然能直接打字
                # ——因为被连线的不是那个文本框本身（ComfyUI 会把连了线的文本框藏起来）。
                '提示词(连线优先)': ('STRING', {'forceInput': True,
                                                'tooltip': '接了这条线就用它的内容；不接就用上面的「中文提示词」文本框'}),
            },
        }

    RETURN_TYPES = ('STRING', 'STRING')
    RETURN_NAMES = ('英文提示词', '未命中报告')
    FUNCTION = 'run'
    CATEGORY = CATEGORY
    DESCRIPTION = ('把中文提示词翻成英文 tag：功能词过滤 + 词典最长匹配 + 数字人物规则 + Danbooru 规范化；'
                   '未命中默认丢弃并列在报告里。放子图里请用「提示词(连线优先)」这个口，'
                   '别把「中文提示词」提升成输入，否则 ComfyUI 会把文本框藏起来。')

    def run(self, **kw):
        # 连线优先：接了线就用线里的内容，否则用文本框
        text = kw.get('提示词(连线优先)') or kw.get('中文提示词', '')
        mode = 'raw' if str(kw.get('输出模式', '')).startswith('raw') else 'tags'
        keep = bool(kw.get('未命中时保留中文', False))
        use_fb = bool(kw.get('用兜底翻译（LLM/在线）', False))
        umode = unknown_mode_of(kw.get('未命中处理'))
        if umode is None:                       # 「跟随旧开关」：老工作流的语义原样保留
            umode = 'fallback' if use_fb else ('keep' if keep else 'drop')
        out, report = do_translate(text, mode=mode, dedupe=bool(kw.get('去重', True)),
                                   use_fallback=use_fb,
                                   first_only=not str(kw.get('同义词', '')).startswith('输出全部'),
                                   unknown_mode=umode,
                                   normalize=bool(kw.get('Danbooru 规范化', True)),
                                   keep_unknown=(umode == 'keep'))
        unknown = report.get('unknown') or []
        info = (f"命中 {report['matched']} 段；兜底 {report['translated']} 段；"
                f"丢弃 {report['dropped']} 段；功能词 {report['function']} 段；"
                f"词库 {report['entries']} 条 + Danbooru {report['index']} 条")
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
            # 顺序同 ZHTagTranslate：老输入不动，新输入追加在后，BOOLEAN 在前 COMBO 在后
            return {
                'required': {
                    'clip': ('CLIP',),
                    '中文提示词': ('STRING', {'multiline': True, 'dynamicPrompts': False, 'default': ''}),
                    '用兜底翻译（LLM/在线）': ('BOOLEAN', {'default': False}),
                },
                'optional': {
                    '未命中时保留中文': ('BOOLEAN', {'default': False}),
                    '去重': ('BOOLEAN', {'default': True}),
                    'Danbooru 规范化': ('BOOLEAN', {'default': True}),
                    '同义词': (['只输出最佳英文', '输出全部同义写法'],),
                    '未命中处理': (UNKNOWN_MODES,),
                    '提示词(连线优先)': ('STRING', {'forceInput': True,
                                                    'tooltip': '接了这条线就用它的内容；不接就用上面的「中文提示词」文本框'}),
                },
            }

        RETURN_TYPES = ('CONDITIONING', 'STRING')
        RETURN_NAMES = ('条件', '英文提示词')
        FUNCTION = 'run'
        CATEGORY = CATEGORY
        DESCRIPTION = ('中文提示词 → 英文 tag → 直接编码，省掉中间一个节点。'
                       '放子图里请用「提示词(连线优先)」这个口，别把文本框提升成输入。')

        def run(self, clip=None, **kw):
            text = kw.get('提示词(连线优先)') or kw.get('中文提示词', '')
            keep = bool(kw.get('未命中时保留中文', False))
            use_fb = bool(kw.get('用兜底翻译（LLM/在线）', False))
            umode = unknown_mode_of(kw.get('未命中处理'))
            if umode is None:
                umode = 'fallback' if use_fb else ('keep' if keep else 'drop')
            english, _report = do_translate(text, mode='tags',
                                            dedupe=bool(kw.get('去重', True)),
                                            use_fallback=use_fb,
                                            first_only=not str(kw.get('同义词', '')).startswith('输出全部'),
                                            unknown_mode=umode,
                                            normalize=bool(kw.get('Danbooru 规范化', True)),
                                            keep_unknown=(umode == 'keep'))
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
