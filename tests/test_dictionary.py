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
from py.translator import FallbackTranslator, baidu_sign, youdao_sign  # noqa: E402

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

    # 切分残留的单字不要送去在线翻译（否则「红裙子」→ 红裙 + 子 → child 这种噪音）
    single_calls = []

    def spy(word):
        single_calls.append(word)
        return 'X'

    out_seg, rep_seg = d.translate('红裙子', unknown_mode='fallback', fallback=spy)
    ok('子' not in single_calls, '切分残留的单字不送在线翻译', f'送了：{single_calls}')
    ok('child' not in out_seg.lower() or 'child' not in out_seg, '不会冒出 child 这种噪音', out_seg)
    ok(d.translate('伞', unknown_mode='fallback', fallback=spy)[0].lower() == 'x',
       '整句就一个字时仍然允许在线翻译', repr(d.translate('伞', unknown_mode='fallback', fallback=spy)[0]))

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

    print('\n[7] 翻译方式切换 / 在线服务商 / 不联网模式（不真的联网）')
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        fb = FallbackTranslator(tmp)
        ok(fb.mode() == 'google', '默认在线翻译 = 谷歌', fb.mode())
        ok([p['id'] for p in fb.state()['providers']] == ['google', 'microsoft', 'baidu', 'youdao'],
           '四家在线服务商都在（谷歌/微软/百度/有道）', str([p['id'] for p in fb.state()['providers']]))
        ok(fb.state()['off']['id'] == 'off', '有「只用词典（不联网）」这一档')

        # 百度 / 有道：没填 key 就不该发请求
        ok(fb.configured('baidu') is False and fb.configured('youdao') is False,
           '百度/有道没填 key 时不算可用')
        ok(fb.configured('google') is True and fb.configured('microsoft') is True,
           '谷歌/微软不需要 key')
        fb.set_mode('baidu')
        ok('还没配置' in fb.test('baidu')['message'] or '配置' in fb.test('baidu')['message'],
           '百度没配 key 时给明确提示', fb.test('baidu')['message'][:34])
        fb.config['baidu_appid'] = 'appid123'
        fb.config['baidu_key'] = 'key456'
        ok(fb.configured('baidu') is True, '填了 appid+key 后百度变成可用')
        fb.config['youdao_appid'] = 'yapp'
        fb.config['youdao_key'] = 'ykey'
        ok(fb.configured('youdao') is True, '有道同理')

        # 签名算法（固定向量，防止以后改坏）
        import hashlib as _h
        ok(baidu_sign('appid123', '蓝发', '123456', 'key456')
           == _h.md5('appid123蓝发123456key456'.encode('utf-8')).hexdigest(),
           '百度签名 = md5(appid+q+salt+key)')
        short = '蓝色裙子'
        ok(youdao_sign('yapp', short, '111', '222', 'ykey')
           == _h.sha256(('yapp' + short + '111222' + 'ykey').encode('utf-8')).hexdigest(),
           '有道签名（短词原样） = sha256(appKey+q+salt+curtime+secret)')
        long_q = '一二三四五六七八九十一二三四五六七八九十一'
        trunc = long_q[:10] + str(len(long_q)) + long_q[-10:]
        ok(youdao_sign('yapp', long_q, '1', '2', 'ykey')
           == _h.sha256(('yapp' + trunc + '12' + 'ykey').encode('utf-8')).hexdigest(),
           '有道签名（长词要 truncate）', trunc)

        # 「只用词典」= 一个字都不联网
        calls = []
        fb.set_mode('off')
        fb._via_google = lambda frag: calls.append(frag) or 'SHOULD NOT HAPPEN'
        fb._via_microsoft = lambda frag: calls.append(frag) or 'SHOULD NOT HAPPEN'
        fb._via_baidu = lambda frag: calls.append(frag) or 'SHOULD NOT HAPPEN'
        fb._via_youdao = lambda frag: calls.append(frag) or 'SHOULD NOT HAPPEN'
        ok(fb('完全不认识的词ABC') is None and calls == [],
           '翻译方式=词典 时不发任何网络请求', f'调用 {calls}')

        # 缓存命中不走网络
        fb.cache['测试词'] = 'test tag'
        ok(fb('测试词') == 'test tag' and calls == [], '缓存命中直接用缓存')

        fb2 = FallbackTranslator(tmp)
        ok(fb2.mode() == 'off', '切换会写回 config.json（重载后仍是词典模式）', fb2.mode())
        ok(fb2.set_mode('乱写的') == 'off', '非法值被忽略，不会把配置写坏', fb2.mode())
        ok(fb2.set_mode('keep') == 'off', '旧的 keep 写法映射到词典模式（兼容）', fb2.mode())
        fb2.config['fallback'] = 'llm'
        fb2.config['base_url'] = 'http://127.0.0.1:1/v1'      # 肯定连不上
        ok(fb2('另一个未知词') is None, 'LLM 连不上时安全失败（不抛异常）')
        ok(os.path.isfile(os.path.join(tmp, 'config.json')), 'config.json 已生成，方便用户改')
        st = fb2.test('microsoft')                            # 真发一次请求（这里连不上）
        ok(st['provider'] == 'microsoft' and 'ok' in st and 'status' in st,
           '连通性自检接口有返回', f"ok={st['ok']} msg={st['message'][:30]}")

    print('\n[7.1] 跑图不干等：短超时 + 可中断')
    with tempfile.TemporaryDirectory() as tmp:
        fb = FallbackTranslator(tmp)
        fb.config['timeout'] = 20
        fb.config['exec_timeout'] = 6
        fb.in_execution = False
        ok(fb._timeout() == 20, '打字/补全时用长超时', str(fb._timeout()))
        fb.in_execution = True
        ok(fb._timeout() == 6, '跑图执行时用短超时（默认 6 秒）', str(fb._timeout()))
        fb.in_execution = False

        class InterruptProcessingException(Exception):
            pass

        called = []
        def interrupt():
            called.append(1)
            raise InterruptProcessingException('中断了')

        fb.set_mode('google')
        fb.interrupt_check = interrupt
        fb._via_google = lambda frag: 'never'
        raised = False
        try:
            fb('一个不该被翻译的词')
        except InterruptProcessingException:
            raised = True
        ok(raised and called, '一按中断，翻译立刻放弃（抛中断异常，不再等网络）')

        # 普通异常不该打断翻译
        fb.interrupt_check = lambda: (_ for _ in ()).throw(RuntimeError('中断功能没启用'))
        ok(fb('另一个词') == 'never', '中断检查本身出错时不影响翻译（继续翻）', repr(fb('另一个词')))

        # 跑图里「失败一次就不再等」：3 个陌生词最多只等一次超时
        fb.interrupt_check = None
        fb.set_mode('google')
        tries = []

        def slow_fail(frag):
            tries.append(frag)
            return None                     # 模拟连不上/超时

        fb._via_google = slow_fail
        fb.begin_execution()
        out3 = [fb(f'陌生词{i}') for i in range(3)]
        ok(tries == ['陌生词0'], '跑图时失败一次就不再继续等（本轮只尝试 1 次）', f'尝试 {tries}')
        ok(all(x is None for x in out3), '三个词都安全失败，不会卡住跑图')
        fb.in_execution = False
        fb._neg.clear()
        fb('陌生词A')
        ok(tries == ['陌生词0', '陌生词A'], '打字/补全时不受「本轮只等一次」限制', f'尝试 {tries}')

    print('\n[7.2] 纯英文输入不联网（跑图不等待）')
    calls = []
    def spy(frag):
        calls.append(frag)
        return 'X'

    for text in ['1girl, long hair, masterpiece', 'blue hair, smile', '(((best quality)))']:
        out, rep = d.translate(text, unknown_mode='fallback', fallback=spy)
        pass
    ok(calls == [], '整句都是英文时不调用翻译器（原样通过）', f'调用 {calls}')
    ok(d.translate('1girl, long hair, masterpiece')[0] == '1girl, long hair, masterpiece',
       '英文 tag 原样保留、不会被拆成两个 tag', d.translate('1girl, long hair, masterpiece')[0])


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
    ok('Danbooru 规范化' in types['optional'] and '提示词(连线优先)' in types['optional'],
       '新增输入都放在 optional（老工作流缺这些也能跑）', ', '.join(types['optional'].keys()))
    ok('未命中处理' not in types['optional'] and '未命中处理' not in types['required'],
       '删掉了重复的「未命中处理」下拉（节点更简洁）', ', '.join(types['optional'].keys()))
    ok(len(types['required']) == 6 and len(types['optional']) == 2,
       '节点输入数量精简为 6 + 2', f"{len(types['required'])} + {len(types['optional'])}")
    ok('未命中时保留中文' in types['required'],
       'v1.0.0 就有的输入仍是 required（位置不变）', ', '.join(types['required'].keys()))
    ok('提示词(连线优先)' in types['optional']
       and types['optional']['提示词(连线优先)'][1].get('forceInput') is True,
       '有纯插口版输入「提示词(连线优先)」（子图里连它，文本框照样能打字）')
    sock_out, _ = ZHTagTranslate().run(**{'中文提示词': '蓝发', '提示词(连线优先)': '红色长发'})
    ok('long hair' in sock_out and 'blue hair' not in sock_out,
       '插口接了线就用线里的内容（连线优先）', sock_out)
    sock_out2, _ = ZHTagTranslate().run(**{'中文提示词': '蓝发', '提示词(连线优先)': ''})
    ok('blue hair' in sock_out2, '插口空着就用文本框内容', sock_out2)
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
    # 老工作流/老 API 里仍可能带着「未命中处理」，节点要能接住（节点上已经没有这个输入了）
    out_legacy, _ = ZHTagTranslate().run(**{
        '中文提示词': '完全未知词XYZ', '未命中时保留中文': False,
        '未命中处理': '保留中文原文', '用兜底翻译（LLM/在线）': False,
    })
    ok('完全未知词XYZ' in out_legacy, '老请求里带的「未命中处理」仍然生效（兼容）', out_legacy)
    plain, _ = ZHTagTranslate().run(**{'中文提示词': '1girl, long hair, masterpiece'})
    ok(plain == '1girl, long hair, masterpiece', '纯英文输入原样通过（不拆词、不联网）', plain)
    q, st = ZHTagQuery().run('双马尾')
    ok('twintails' in q, '词典查询节点可用', q)

    print('\n[11] 老工作流兼容（ComfyUI 的 widgets_values 是按位置存的！）')
    OLD_ORDER = ['中文提示词', '输出模式', '去重', '未命中时保留中文', '用兜底翻译（LLM/在线）', '同义词']

    def widget_keys(cls):
        """按 ComfyUI 的规则列出「会出现在 widgets_values 里的输入」。
        forceInput 的输入是纯插口（比如「提示词(连线优先)」），不占小部件位置。"""
        types = cls.INPUT_TYPES()
        keys = []
        for section in ('required', 'optional'):
            for name, spec in types.get(section, {}).items():
                t = spec[0]
                opts = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
                if opts.get('forceInput'):
                    continue
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
    ok(len(new_keys) == len(OLD_ORDER) + 1 and set(combos) == {'输出模式', '同义词'},
       '小部件 = v1.0.0 的 6 个 + Danbooru 规范化；下拉只有老位置那两个（新输入不会插到中间）',
       f'{" / ".join(new_keys)}；COMBO：{" / ".join(combos)}')

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

    print('\n[12] IDE 式补全（中文 / 拼音 / 英文 → tag 候选）')
    from py.complete import get_completer  # noqa: E402
    c = get_completer()
    ok(len(c.entries) > 3000, '补全索引条目', f'{len(c.entries)} 条')
    ok(len(c.pinyin) > 20000, '拼音表已加载', f'{len(c.pinyin)} 字')
    ok('pinyin_chars.tsv' not in d.sources, '拼音表不会被当成中英词典加载',
       ', '.join(d.sources))

    def first(q, limit=5):
        r = c.complete(q, limit=limit)
        return r[0]['en'] if r else ''

    ok(first('lanfa') == 'blue hair', '全拼 lanfa → blue hair', first('lanfa'))
    ok(first('smw') == 'twintails', '首字母 smw → twintails', first('smw'))
    ok(first('shuangmawei') == 'twintails', '全拼 shuangmawei → twintails', first('shuangmawei'))
    ok(first('蓝发') == 'blue hair' and c.complete('蓝发')[0]['score'] == 100,
       '中文精确命中排第一', first('蓝发'))
    ok(first('一个女孩') == '1girl', '中文短语 一个女孩 → 1girl', first('一个女孩'))
    ok(first('yigenvhai') == '1girl', '全拼 yigenvhai → 1girl', first('yigenvhai'))
    # 多音字：长 = cháng/zhǎng，两种拼法都要能查到长发
    ok('long hair' in [r['en'] for r in c.complete('changfa')], '多音字 changfa → long hair',
       ' / '.join(r['en'] for r in c.complete('changfa')[:3]))
    ok('long hair' in [r['en'] for r in c.complete('zhangfa')], '多音字 zhangfa → long hair',
       ' / '.join(r['en'] for r in c.complete('zhangfa')[:3]))
    ok('long hair' in [r['en'] for r in c.complete('long_h')], '英文前缀 long_h → long hair',
       ' / '.join(r['en'] for r in c.complete('long_h')[:3]))
    ok(c.complete('') == [] and c.complete('   ') == [], '空查询返回空')
    ok(len(c.complete('lf', limit=2)) <= 2, 'limit 生效')
    ok(c.complete('qianziwoya') == [], '查不到的词返回空（交给在线翻译）')
    res_hong = c.complete('红色', limit=8)
    ok(all(res_hong[i]['score'] >= res_hong[i + 1]['score'] for i in range(len(res_hong) - 1)),
       '结果按匹配质量从高到低排', ' / '.join(f"{r['en']}({r['score']})" for r in res_hong[:4]))
    same_score = {}
    for r in res_hong:
        same_score.setdefault(r['score'], []).append(r['count'])
    ok(all(v == sorted(v, reverse=True) for v in same_score.values()),
       '同分数内按 Danbooru 热度排序',
       ' / '.join(f"{r['en']}({r['score']},{r['count']})" for r in res_hong[:5]))

    import time as _t
    t0 = _t.time()
    for q in ['lanfa', 'smw', '蓝发', 'changfa', 'long_h', 'yigenvhai', 'weixiao', 'hongsefa'] * 5:
        c.complete(q)
    avg = (_t.time() - t0) / 40 * 1000
    ok(avg < 30, '单次补全查询耗时 < 30ms', f'{avg:.1f} ms/次')

    print('\n[13] 全词联想（英文）与词组制度（中文）')
    ok(len(c.word_index) > 8000, '英文词联想索引已建', f'{len(c.word_index)} 个词')
    ok(len(c.phrase_map) > 3000, '中文词组表已建（拼装自 Danbooru 多词标签）', f'{len(c.phrase_map)} 条')
    ok(c.en2zh.get('breasts') == ['乳房'] or '乳房' in (c.en2zh.get('breasts') or []),
       '乳房 ↔ breasts 的单词级映射', str(c.en2zh.get('breasts')))
    ok('白' in (c.en2zh.get('white') or []), '对齐挖掘出 白 ↔ white', str(c.en2zh.get('white')))

    res_b = c.complete('breasts', limit=8)
    ok(res_b and res_b[0]['en'] == 'breasts' and res_b[0]['kind'] == 'en',
       'breasts：精确命中排第一', res_b[0]['en'] if res_b else '')
    names_b = [r['en'] for r in res_b]
    ok('huge breasts' in names_b, 'breasts → 联想到 huge breasts（用户举的例子）', ' / '.join(names_b))
    ok(any(r['kind'] == 'enword' for r in res_b), '联想行标成 enword（界面显示「英文联想」）')
    ok('large breasts' in names_b and names_b.index('large breasts') < names_b.index('huge breasts'),
       '联想按热度排（large 1.58M 在 huge 210k 前面）', ' / '.join(names_b[:5]))
    ok(len(set(names_b)) == len(names_b), '不会出现下划线/空格两个重复行', ' / '.join(names_b))

    # 词族：一个词要能带出「所有涉及它的词条」
    fam_b = [r['en'] for r in c.complete('breasts', limit=15)]
    ok(len(c.word_index.get('breasts', [])) > 60, '词索引里 breasts 相关标签够多',
       f"{len(c.word_index.get('breasts', []))} 个")
    ok(len(fam_b) >= 12 and 'cum on breasts' in fam_b,
       'breasts → 一次给出整个词族（含 cum on breasts）', ' / '.join(fam_b[:8]))
    fam_cn = c.complete('乳房', limit=15)
    ok(len(fam_cn) >= 8, '中文「乳房」也带出整个词族', ' / '.join(r['en'] for r in fam_cn[:6]))
    ok(any(r['en'] in ('large breasts', 'huge breasts') for r in fam_cn),
       '中文词族里含 large/huge breasts', ' / '.join(r['en'] for r in fam_cn[:6]))
    fam_hair = c.complete('头发', limit=12)
    ok(len(fam_hair) >= 8 and any('hair' in r['en'] for r in fam_hair),
       '中文「头发」带出 hair 家族', ' / '.join(r['en'] for r in fam_hair[:5]))
    ok(c.gloss('bag') == '袋子' and c.gloss('school bag') == '书包' and c.gloss('paper bag') == '纸袋',
       'bag 家族翻译修正：袋子 / 书包 / 纸袋',
       f"{c.gloss('bag')} / {c.gloss('school bag')} / {c.gloss('paper bag')}")
    ok('红' in c.gloss('red bag') and '袋' in c.gloss('red bag'),
       'red bag → 红袋子（不是「红包」）', c.gloss('red bag'))

    res_h = [r['en'] for r in c.complete('hair', limit=6)]
    ok('long hair' in res_h and 'blonde hair' in res_h, 'hair → long hair / blonde hair', ' / '.join(res_h))
    res_br = [r['en'] for r in c.complete('breast', limit=6)]
    ok(res_br, 'breast（少个 s）也能联想到', ' / '.join(res_br[:3]))
    res_rd = [r['en'] for r in c.complete('red dress', limit=4)]
    ok('red dress' in res_rd, '英文带空格也认（red dress = red_dress）', ' / '.join(res_rd))

    # 中文注释：英文候选也要尽量带上中文（现成翻译 → 逐词拼）
    ok(len(c.en_zh) > 3000, '英文→中文注释表已建', f'{len(c.en_zh)} 条')
    ok(('乳' in c.gloss('huge_breasts') or '胸' in c.gloss('huge_breasts')),
       '逐词拼：huge_breasts → 巨大/超大 + 乳房/胸部',
       c.gloss('huge_breasts'))
    ok(('乳' in c.gloss('breasts') or '胸' in c.gloss('breasts')),
       '现成翻译：breasts → 乳房/胸部', c.gloss('breasts'))
    ok(c.gloss('a_word_that_never_exists_xyz') == '', '拼不出来就返回空（界面退化成只显示英文）')
    # 带介词的标签也要有中文（按中文语序拼，不是照英文顺序硬贴）
    ok(('乳' in c.gloss('cum on breasts') or '胸' in c.gloss('cum on breasts'))
       and '精液' in c.gloss('cum on breasts'),
       'cum on breasts → 乳房/胸部上的精液', c.gloss('cum on breasts'))
    g_cum = c.gloss('cum on breasts')
    ok(g_cum.endswith('精液'), '语序是中文的（位置在前、主体在后）', g_cum)
    ok(c.gloss('covered in cum') == '沾满精液', 'covered in cum → 沾满精液', c.gloss('covered in cum'))
    ok('眼镜' in c.gloss('girl with glasses'), 'girl with glasses → 带眼镜的…', c.gloss('girl with glasses'))
    ok(c.gloss('standing on floor').startswith('在') and '站' in c.gloss('standing on floor'),
       '动词在前时换另一种语序：standing on floor', c.gloss('standing on floor'))
    ok('别人' in c.gloss("grabbing another's breast") or '他人' in c.gloss("grabbing another's breast"),
       "所有格也能翻：grabbing another's breast", c.gloss("grabbing another's breast"))
    ok(c.gloss('under skirt').endswith('下面') and '裙' in c.gloss('under skirt'),
       '两词介词：under skirt → 裙子下面', c.gloss('under skirt'))
    ok(c.gloss('legs crossed') and c.gloss('wet clothes'), '普通两词也能拼',
       f"{c.gloss('legs crossed')} / {c.gloss('wet clothes')}")
    glossed = [r for r in c.complete('breasts', limit=8) if r['zh']]
    ok(len(glossed) >= 5, 'breasts 的前几个候选大多带中文注释',
       ' / '.join(f"{r['en']}→{r['zh']}" for r in c.complete('breasts', limit=5)))
    top3000 = sorted(c.dic.en_count.items(), key=lambda kv: -kv[1])[:3000]
    covered = sum(1 for t, _ in top3000 if c.gloss(t))
    ok(covered > 2400, '最热 3000 个标签的中文注释覆盖率', f'{covered} 个（{covered / 30:.0f}%）')

    res_ls = c.complete('黑色蕾丝', limit=4)
    ok(res_ls and res_ls[0]['en'] == 'black lace' and res_ls[0]['kind'] == 'phrase',
       '黑色蕾丝 → black lace（用户举的例子）', str(res_ls[0]) if res_ls else '')
    res_qq = c.complete('巨大乳房', limit=4)
    ok(res_qq and res_qq[0]['en'] == 'huge breasts' and res_qq[0]['count'] > 100000,
       '巨大乳房 → huge breasts（词组命中真实 Danbooru 标签，带热度）',
       f"{res_qq[0]['en']}({res_qq[0]['kind']},{res_qq[0]['count']})" if res_qq else '')
    res_wt = c.complete('白色长筒袜', limit=3)
    ok(res_wt and res_wt[0]['en'] == 'white thighhighs',
       '白色长筒袜 → white thighhighs', res_wt[0]['en'] if res_wt else '')
    res_rd = c.complete('红裙子', limit=3)
    ok(res_rd and 'red' in res_rd[0]['en'],
       '红裙子 → red pleated skirt（命中一段也给出候选，不留空）',
       res_rd[0]['en'] if res_rd else '(空)')

    t0 = _t.time()
    for q in ['breasts', 'hair', '黑色蕾丝', '巨大乳房'] * 5:
        c.complete(q)
    avg2 = (_t.time() - t0) / 20 * 1000
    ok(avg2 < 30, '联想/词组查询耗时 < 30ms', f'{avg2:.1f} ms/次')

    print(f'\n结果：{PASS} 通过 / {FAIL} 失败')
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
