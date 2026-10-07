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
    out3, rep3 = d.translate('微笑, 微笑, smile, 完全未知词XYZ')
    ok(out3.lower().count('smile') == 1, '去重生效', out3)
    ok('完全未知词XYZ' in out3 and rep3['unknown'], '未命中保留原文并报告', '/'.join(rep3['unknown']))
    out4, _ = d.translate('1girl, masterpiece, 微笑')
    ok('1girl' in out4 and 'masterpiece' in out4, '本来就是英文的 tag 原样保留', out4)

    print('\n[6.1] 同义词策略（社区词库里混着脏别名）')
    out5, _ = d.translate('红色长发')
    ok('red long upper shan' not in out5, '默认只输出最佳英文，脏别名不跟着输出', out5)
    out6, _ = d.translate('红色长发', first_only=False)
    ok('red long upper shan' in out6, '需要时可切换为输出全部同义写法', out6)

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

    print('\n[9] 性能（词典 3600 条，整句翻译）')
    import time
    text = '一个女孩站在樱花树下微笑，长发飘动，黄昏，电影感光线，高质量，杰作，' * 10
    t0 = time.time()
    for _ in range(50):
        d.translate(text)
    dt = (time.time() - t0) / 50 * 1000
    ok(dt < 50, '单次整句翻译耗时 < 50ms', f'{dt:.1f} ms/次、{len(text)} 字')

    print(f'\n结果：{PASS} 通过 / {FAIL} 失败')
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
