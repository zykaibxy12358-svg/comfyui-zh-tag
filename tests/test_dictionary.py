# -*- coding: utf-8 -*-
"""ZHTag 词典与翻译的单测（不需要 ComfyUI，直接用 python 跑）。

    python comfyui-zh-tag/tests/test_dictionary.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from py.dictionary import TagDictionary, default_data_dirs, has_cjk  # noqa: E402
from py.translator import FallbackTranslator  # noqa: E402

PASS = FAIL = 0


def ok(cond, label, extra=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f'  ✓ {label}' + (f'  {extra}' if extra else ''))
    else:
        FAIL += 1
        print(f'  ✗ {label}  {extra}')


def main():
    print('\n[1] 词典加载')
    d = TagDictionary(default_data_dirs()).load_all()
    ok(d.size > 3000, '内置词典条数', f'{d.size} 条（来源 {", ".join(d.sources)}）')
    ok(len(d.ts_map) > 4000, '繁→简表已加载', f'{len(d.ts_map)} 字')
    ok(d.dropped < d.size, '脏行被过滤', f'丢弃 {d.dropped} 行')

    print('\n[2] 精确与同义词')
    ok(d.lookup('双马尾') == ['bunches', 'twintails'] or 'twintails' in d.lookup('双马尾'),
       '精确命中：双马尾', '/'.join(d.lookup('双马尾')))
    ok('smile' in d.lookup('微笑'), '精确命中：微笑', '/'.join(d.lookup('微笑'))) 

    print('\n[3] 繁体输入（繁→简自动归一）')
    zh_trad = '雙馬尾'
    ok('twintails' in d.lookup(zh_trad), '繁体「雙馬尾」也能查到', '/'.join(d.lookup(zh_trad)))

    print('\n[4] 最长匹配切分（词库没有整词也能拼）')
    seg = d.longest_match('红色长发')
    hit = [zh for zh, ens in seg if ens]
    ok(len(hit) >= 2, '「红色长发」被拆成多段', ' + '.join(f'{zh}→{"/".join(ens)}' for zh, ens in seg if ens))
    out, rep = d.translate('一个女孩站在樱花树下微笑，长发，黄昏')
    ok('girl' in out and 'smile' in out, '整句可翻译', out)
    ok(rep['matched'] >= 3, '命中段数统计', f"{rep['matched']} 段")

    print('\n[5] 权重与括号保留')
    out2, _ = d.translate('(微笑:1.2), [[长发]]')
    ok('smile' in out2 and '1.2' in out2, '(xxx:1.2) 权重保留', out2)
    ok('long hair' in out2 or 'long_hair' in out2, '[[xxx]] 括号内的词也翻了', out2)

    print('\n[6] 去重 / 未命中 / 英文原样保留')
    out3, rep3 = d.translate('微笑, 微笑, smile, 完全未知词XYZ', unknown_mode='keep')
    ok(out3.lower().count('smile') == 1, '去重生效', out3)
    ok('完全未知词XYZ' in out3 and rep3['unknown'], '未命中保留原文并报告（keep 模式）', '/'.join(rep3['unknown']))
    out3b, rep3b = d.translate('微笑, 微笑, smile, 完全未知词XYZ')
    ok('完全未知词XYZ' not in out3b and rep3b['dropped'] == 1,
       '默认 drop 模式：未命中只进报告不写进提示词', out3b)
    out4, _ = d.translate('1girl, masterpiece, 微笑')
    ok('1girl' in out4 and 'masterpiece' in out4, '本来就是英文的 tag 原样保留', out4)

    print('\n[6.1] 同义词策略（社区词库里混着脏别名）')
    out5, _ = d.translate('红色长发')
    ok('red long upper shan' not in out5, '默认只输出最佳英文，脏别名不跟着输出', out5)
    out6, _ = d.translate('红色长发', first_only=False)
    ok('red long upper shan' in out6, '需要时可切换为输出全部同义写法', out6)

    print('\n[6.2] 自然语言整句（用户报过的问题：一个蓝发漂亮姑娘）')
    out_nl, rep_nl = d.translate('一个蓝发漂亮姑娘')
    ok(out_nl == 'blue hair, beautiful, girl', '「一个蓝发漂亮姑娘」→ 干净三个 tag', out_nl)
    ok('一个' not in out_nl and '的' not in out_nl, '量词「一个」与「的」不会变成 tag', out_nl)
    ok(all(has_cjk(x) is False for x in out_nl.split(', ')), '输出里没有残留中文')
    out_nl2, rep_nl2 = d.translate('一个蓝发漂亮姑娘站在樱花树下微笑')
    for need in ('girl', 'blue hair', 'smile', 'cherry blossoms'):
        ok(need in out_nl2, f'长句里包含 {need}', out_nl2)
    ok(rep_nl2['dropped'] == 0, '自然口语长句无丢词', f"丢弃 {rep_nl2['dropped']}")
    ok(rep_nl2['function'] >= 1, '功能词被识别并跳过', f"功能词 {rep_nl2['function']}")

    print('\n[6.3] 功能词 / 人称代词 / 数量短语')
    out_fw, rep_fw = d.translate('她非常缓慢地闭上眼睛')
    ok('她' not in out_fw and '非常' not in out_fw, '人称代词与程度副词被丢掉', out_fw)
    ok('closed eyes' in out_fw, '「闭上眼睛」翻成 closed eyes', out_fw)
    out_num, _ = d.translate('两个女孩')
    ok(out_num == '2girls', '「两个女孩」→ 2girls', out_num)
    ok(d.translate('一个男孩')[0] == '1boy', '「一个男孩」→ 1boy')
    ok(d.translate('三个人物')[0] in ('3people', '3people'), '「三个人物」→ 3people',
       d.translate('三个人物')[0])
    ok(d.is_function_word('的') and d.is_function_word('她') and d.is_function_word('突然'),
       'is_function_word 覆盖虚词/代词/副词')
    ok(not d.is_function_word('女孩'), '实词不会被误判为功能词')

    print('\n[6.4] 未命中处理 unknown_mode')
    src = '一个蓝发姑娘骑着完全未知词XYZ'
    out_drop, rep_drop = d.translate(src, unknown_mode='drop')
    ok('完全未知词XYZ' not in out_drop, 'drop：丢掉未命中词', out_drop)
    ok(rep_drop['dropped'] == 1 and rep_drop['unknown'], 'drop：仍上报未命中词', '/'.join(rep_drop['unknown']))
    out_keep, _ = d.translate(src, unknown_mode='keep')
    ok('完全未知词XYZ' in out_keep, 'keep：保留中文原文', out_keep)
    calls = []

    def fake_fb(word):
        calls.append(word)
        return 'mystery tag'

    out_fb, rep_fb = d.translate(src, unknown_mode='fallback', fallback=fake_fb)
    ok('mystery tag' in out_fb and calls, 'fallback：交给翻译器处理', out_fb)
    ok(d.translate(src, fallback=fake_fb)[0].find('mystery tag') < 0,
       '默认 drop 模式下不会偷偷调用翻译器')

    print('\n[6.5] Danbooru 规范化与热度排序')
    ok(d.canonical_en('longhair') == 'long_hair', '别名归一：longhair → long_hair', str(d.canonical_en('longhair')))
    ok(d.normalize_en('long_hair') == 'long hair', 'normalize 默认空格风格', d.normalize_en('long_hair'))
    ok(d.normalize_en('long_hair', underscore=True) == 'long_hair', 'underscore=True 保留下划线',
       d.normalize_en('long_hair', underscore=True))
    ok(d.popularity('long_hair') > d.popularity('impasto'), '热度可比较', 
       f"{d.popularity('long_hair')} > {d.popularity('impasto')}")
    out_p1, _ = d.translate('微笑，长发，蓝发，女孩')
    out_p2, _ = d.translate('女孩，蓝发，长发，微笑')
    ok(out_p1 == out_p2, '输出顺序与输入顺序无关（按热度稳定排序）', out_p1)
    ok(out_p1.split(', ')[0] in ('long hair', 'girl'), '最热的 tag 排在最前', out_p1)
    raw, _ = d.translate('红色长发', normalize=False)
    ok('red' in raw, 'normalize=False 也能出结果', raw)

    print('\n[7] 兜底翻译（不联网：用假配置验证链路）')
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        fb = FallbackTranslator(tmp)
        ok(fb.config['fallback'] == 'keep', '默认兜底策略=保留原文', fb.config['fallback'])
        ok(fb('完全未知词XYZ') is None, 'keep 模式下不翻译，交给上层保留原文')
        fb.cache['测试词'] = 'test tag'
        ok(fb('测试词') == 'test tag', '缓存命中直接返回')
        fb.config['fallback'] = 'llm'
        fb.config['base_url'] = 'http://127.0.0.1:1/v1'      # 肯定连不上
        ok(fb('另一个未知词') is None, 'LLM 连不上时安全失败（不抛异常）')
        ok(os.path.isfile(os.path.join(tmp, 'config.json')), 'config.json 已生成，方便用户改')

    print('\n[8] 自定义词典目录（用户丢进来的文件要能被加载）')
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, 'my.csv'), 'w', encoding='utf-8') as f:
            f.write('# 我的词典\n我的自定义词,my custom tag\n表情包|表情,sticker,meme\n')
        with open(os.path.join(tmp, 'my.json'), 'w', encoding='utf-8') as f:
            f.write('{"另一个自定义词": "another custom tag"}')
        d2 = TagDictionary([tmp]).load_all()
        ok('my custom tag' in d2.lookup('我的自定义词'), 'CSV 自定义词典生效')
        ok('sticker' in d2.lookup('表情包') and 'sticker' in d2.lookup('表情'), '同义词（|）生效')
        ok('another custom tag' in d2.lookup('另一个自定义词'), 'JSON 自定义词典生效')

        # 兜底翻译的 config.json / cache.json 与 README 不能被当成词典来源
        with open(os.path.join(tmp, 'config.json'), 'w', encoding='utf-8') as f:
            f.write('{"fallback": "keep", "base_url": "http://127.0.0.1:11434/v1"}')
        with open(os.path.join(tmp, 'README.txt'), 'w', encoding='utf-8') as f:
            f.write('这是说明文件\nfallback,keep\n')
        d3 = TagDictionary([tmp]).load_all()
        ok('config.json' not in d3.sources and 'README.txt' not in d3.sources,
           '配置文件/说明文件不会被当成词典', ', '.join(d3.sources))

    print('\n[9] 性能（词典近 4000 条，整句翻译）')
    import time
    text = '一个女孩站在樱花树下微笑，长发飘动，黄昏，电影感光线，高质量，杰作，' * 10
    t0 = time.time()
    for _ in range(50):
        d.translate(text)
    dt = (time.time() - t0) / 50 * 1000
    ok(dt < 50, '单次整句翻译耗时 < 50ms', f'{dt:.1f} ms/次、{len(text)} 字')

    print('\n[10] ComfyUI 节点层（脱离 ComfyUI 也能跑，CLIP 节点自动跳过）')
    from py.nodes import ZHTagTranslate, ZHTagQuery, unknown_mode_of  # noqa: E402
    types = ZHTagTranslate.INPUT_TYPES()
    ok('未命中处理' in types['optional'] and 'Danbooru 规范化' in types['optional'],
       '新增输入都放在 optional（老工作流缺这两项也能跑）', ', '.join(types['optional'].keys()))
    ok('未命中时保留中文' in types['required'],
       'v1.0.0 就有的输入仍是 required（位置不变）', ', '.join(types['required'].keys()))
    ok(unknown_mode_of('保留中文原文') == 'keep' and unknown_mode_of('丢弃未命中（推荐，只写进报告）') == 'drop'
       and unknown_mode_of('交给兜底翻译（LLM/在线）') == 'fallback', '下拉文字能映射成策略')
    out, report = ZHTagTranslate().run(**{
        '中文提示词': '一个蓝发漂亮姑娘站在樱花树下微笑',
        '输出模式': 'tags（逗号分隔的 tag 串）', '未命中处理': '丢弃未命中（推荐，只写进报告）',
        '去重': True, '同义词': '只输出最佳英文', 'Danbooru 规范化': True,
        '用兜底翻译（LLM/在线）': False,
    })
    ok('blue hair' in out and '一个' not in out, '节点的默认设置就能出干净结果', out)
    ok('命中' in report and '词库' in report, '第二个输出是给人看的报告', report.splitlines()[0])
    q, st = ZHTagQuery().run('双马尾')
    ok('twintails' in q, '词典查询节点可用', q)

    print('\n[11] 老工作流兼容（ComfyUI 的 widgets_values 是按位置存的！）')
    OLD_ORDER = ['中文提示词', '输出模式', '去重', '未命中时保留中文', '用兜底翻译（LLM/在线）', '同义词']

    def widget_keys(cls):
        """按 ComfyUI 的规则列出「会出现在 widgets_values 里的输入」（排除 CLIP 这类连线输入）。"""
        types = cls.INPUT_TYPES()
        keys = []
        for section in ('required', 'optional'):
            for name, spec in types.get(section, {}).items():
                t = spec[0]
                if isinstance(t, list) or t in ('STRING', 'BOOLEAN', 'INT', 'FLOAT'):
                    keys.append((name, spec))
        return keys

    def emulate_frontend(cls, values):
        """复刻前端：把 widgets_values 按位置贴到输入上；返回 (kwargs, 会校验失败的项)。"""
        kw, bad = {}, []
        for (name, spec), v in zip(widget_keys(cls), values):
            t = spec[0]
            if isinstance(t, list):
                (kw.__setitem__(name, v) if v in t else bad.append((name, v)))
            elif t == 'BOOLEAN':
                kw[name] = bool(v)          # 服务端也是 bool(val)，不会校验失败
            else:
                kw[name] = v
        return kw, bad

    new_keys = [n for n, _ in widget_keys(ZHTagTranslate)]
    ok(new_keys[:len(OLD_ORDER)] == OLD_ORDER,
       'v1.0.0 的 6 个输入位置原封不动（老工作流不会错位）', ' / '.join(new_keys))
    combos = [n for n, s in widget_keys(ZHTagTranslate) if isinstance(s[0], list)]
    ok(new_keys[-1] == '未命中处理' and isinstance(dict(widget_keys(ZHTagTranslate))['未命中处理'][0], list),
       '新增的 COMBO 一律追加到最后（只有 COMBO 会因取值不在列表而失败）',
       f'COMBO 顺序：{" / ".join(combos)}')

    # 用户真实工作流 ONE 通用成熟.json 里存下来的 widgets_values
    user_values = ['skirt, wearing, white long upper shan, beautiful, girl',
                   'tags（逗号分隔的 tag 串）', True, False, False, '输出全部同义写法', False]
    kw_user, bad_user = emulate_frontend(ZHTagTranslate, user_values)
    ok(bad_user == [], '用户现有工作流不再校验失败（这是 prompt_outputs_failed_validation 的根因）',
       str(bad_user))
    out_user, _ = ZHTagTranslate().run(**kw_user)
    ok('girl' in out_user, '老工作流照样能跑出结果', out_user)

    # v1.0.0 时代只有 6 个值的老工作流
    kw_old, bad_old = emulate_frontend(ZHTagTranslate, ['一个蓝发漂亮姑娘', 'tags（逗号分隔的 tag 串）',
                                                        True, False, False, '只输出最佳英文'])
    ok(bad_old == [] and 'blue hair' in ZHTagTranslate().run(**kw_old)[0],
       'v1.0.0 时代的 6 值工作流也能直接跑', ZHTagTranslate().run(**kw_old)[0])
    # 老工作流里「未命中时保留中文」= True 的，语义要原样保留（仍然保留中文）
    kw_keep, _ = emulate_frontend(ZHTagTranslate, ['完全未知词XYZ', 'tags（逗号分隔的 tag 串）',
                                                   True, True, False, '只输出最佳英文'])
    ok('完全未知词XYZ' in ZHTagTranslate().run(**kw_keep)[0],
       '老开关「未命中时保留中文」=True 时行为不变', ZHTagTranslate().run(**kw_keep)[0])
    kw_nokeep, _ = emulate_frontend(ZHTagTranslate, ['完全未知词XYZ', 'tags（逗号分隔的 tag 串）',
                                                     True, False, False, '只输出最佳英文'])
    ok('完全未知词XYZ' not in ZHTagTranslate().run(**kw_nokeep)[0],
       '老开关 =False 时未命中被丢弃', repr(ZHTagTranslate().run(**kw_nokeep)[0]))
    ok(unknown_mode_of('跟随「未命中时保留中文」开关（推荐）') is None
       and unknown_mode_of('丢弃未命中（推荐，只写进报告）') == 'drop',
       '新旧两版下拉文字都能识别（老工作流里存的旧文案也认）')

    print(f'\n结果：{PASS} 通过 / {FAIL} 失败')
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
