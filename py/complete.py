# -*- coding: utf-8 -*-
"""IDE 式补全引擎：输入中文或拼音 → 直接给出英文 Danbooru tag 候选。

匹配顺序（分数越高越靠前，同分按 Danbooru 热度）：
    100  中文精确        蓝发
     95  拼音全拼精确（含多音字变体）  lanfa / changfa / zhangfa
     90  拼音首字母精确    smw（双马尾）
     85  英文 tag 精确    long_hair
     80  中文前缀         双马
     70  拼音全拼前缀     lanf
     60  拼音首字母前缀    sm
     55  英文 tag 前缀    long_h
     40  中文子串         马

拼音表来自 data/pinyin_chars.tsv（构建期用 pypinyin 生成，运行时零依赖）。
一个词里可能有多个多音字（长/尾/蓝…），所以按「每字取一个读音做笛卡尔积」生成变体，
但最多保留 8 个（按读音常见度排序），既覆盖 changfa/zhangfa 这类，又不会爆内存。
"""
from __future__ import annotations

import os
from itertools import product
from typing import Dict, List, Optional, Sequence, Tuple

MAX_VARIANTS = 8
MAX_INITIAL_VARIANTS = 4


def _is_cjk(ch: str) -> bool:
    return '\u3400' <= ch <= '\u9fff'


class Completer:
    """中文/拼音/英文 → tag 候选。词典变了就重建（reload）。"""

    def __init__(self, dictionary, pinyin_path: Optional[str] = None):
        self.dic = dictionary
        self.pinyin: Dict[str, List[str]] = {}
        self.entries: List[Tuple[str, Tuple[str, ...], Tuple[str, ...], str, int]] = []
        self.en_tags: List[Tuple[str, int]] = []
        self._en_sorted: List[str] = []
        self.pinyin_path = pinyin_path or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'pinyin_chars.tsv')
        self.build()

    # ------------------------------------------------------------------ 构建
    def load_pinyin(self) -> int:
        path = self.pinyin_path
        if not os.path.isfile(path):
            return 0
        n = 0
        try:
            with open(path, 'r', encoding='utf-8-sig') as f:
                for line in f:
                    if line.startswith('#') or '\t' not in line:
                        continue
                    ch, pys = line.rstrip('\n').split('\t', 1)
                    if not ch:
                        continue
                    self.pinyin[ch[0]] = [p.strip() for p in pys.split(',') if p.strip()]
                    n += 1
        except Exception as e:
            print(f'[ZHTag] 拼音表读取失败（拼音补全将不可用）：{e}')
        return n

    def _variants(self, zh: str, cap: int, initials: bool = False) -> Tuple[str, ...]:
        """每字取一个读音/首字母做笛卡尔积，按「常用度」排序后截断。"""
        per_char: List[List[str]] = []
        for ch in zh:
            readings = self.pinyin.get(ch)
            if not readings:
                return ()                      # 有字没有拼音 → 整个词不给拼音匹配
            per_char.append([r[0] if initials else r for r in readings])
        combos = []
        for combo in product(*per_char):
            combos.append((''.join(combo), sum(per_char[i].index(combo[i]) for i in range(len(combo)))))
        combos.sort(key=lambda c: (c[1], len(c[0])))
        seen, out = set(), []
        for text, _rank in combos:
            if text in seen:
                continue
            seen.add(text)
            out.append(text)
            if len(out) >= cap:
                break
        return tuple(out)

    def build(self) -> 'Completer':
        self.load_pinyin()
        self.entries = []
        for zh, ens in self.dic.zh2en.items():
            if not zh or not ens:
                continue
            if not any(_is_cjk(c) for c in zh):
                continue                        # 纯英文键交给英文前缀匹配
            best = max((self.dic.popularity(e) for e in ens), default=0)
            en = min(ens, key=lambda s: -self.dic.popularity(s)) if ens else ens[0]
            fulls = self._variants(zh, MAX_VARIANTS)
            inis = self._variants(zh, MAX_INITIAL_VARIANTS, initials=True)
            self.entries.append((zh.lower(), fulls, inis, en, best))
        # 英文前缀补全用（Danbooru 索引里的正名）
        self.en_tags = list(self.dic.en_count.items())
        self._en_sorted = sorted(self.dic.en_count.keys())
        return self

    # ------------------------------------------------------------------ 查询
    def _en_prefix(self, q: str, limit: int) -> List[Tuple[int, int, str, str]]:
        """英文 tag 前缀匹配：返回 (score, count, en, zh)"""
        import bisect
        out = []
        i = bisect.bisect_left(self._en_sorted, q)
        while i < len(self._en_sorted) and len(out) < limit * 3:
            tag = self._en_sorted[i]
            if not tag.startswith(q):
                break
            count = self.dic.en_count.get(tag, 0)
            score = 85 if tag == q else 55
            out.append((score, count, tag, ''))
            i += 1
        return out

    def complete(self, query: str, limit: int = 10) -> List[dict]:
        q = (query or '').strip().lower()
        if not q:
            return []
        has_cjk = any(_is_cjk(c) for c in q)
        scored: List[Tuple[int, int, str, str]] = []   # (score, count, en, zh)

        for zh, fulls, inis, en, count in self.entries:
            zh_l = zh                              # 构建时已 lower
            s = 0
            if q == zh_l:
                s = 100
            elif q == zh_l[:len(q)] and has_cjk:
                s = 80
            elif has_cjk and q in zh_l:
                s = 40
            elif not has_cjk and fulls:
                if q in fulls:
                    s = 95
                elif q in inis:
                    s = 90
                elif any(f.startswith(q) for f in fulls):
                    s = 70
                elif any(i2.startswith(q) for i2 in inis):
                    s = 60
            if s:
                scored.append((s, count, en, zh))

        if not has_cjk and len(q) >= 2:
            scored.extend(self._en_prefix(q, limit))

        # 同一个英文 tag 只留分最高的那个，再按 (分数, 热度) 排
        best: Dict[str, Tuple[int, int, str]] = {}
        for s, count, en, zh in scored:
            key = en.lower()
            cur = best.get(key)
            if cur is None or (s, count) > (cur[0], cur[1]):
                best[key] = (s, count, zh)
        ranked = sorted(best.items(), key=lambda kv: (-kv[1][0], -kv[1][1], kv[0]))
        out = []
        for en, (s, count, zh) in ranked[:max(1, limit)]:
            out.append({'en': en, 'zh': zh, 'score': s, 'count': count,
                        'kind': ('en' if not zh else ('zh' if any(_is_cjk(c) for c in (query or '')) else 'pinyin'))})
        return out


_COMPLETER: Optional[Completer] = None


def get_completer(reload: bool = False) -> Completer:
    global _COMPLETER
    if _COMPLETER is None or reload:
        from .dictionary import get_dictionary
        _COMPLETER = Completer(get_dictionary(reload=reload))
        print(f'[ZHTag] 补全索引就绪：{len(_COMPLETER.entries)} 条中文词条 / '
              f'拼音表 {len(_COMPLETER.pinyin)} 字 / 英文索引 {len(_COMPLETER.en_tags)} 条')
    return _COMPLETER
