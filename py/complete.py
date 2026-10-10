# -*- coding: utf-8 -*-
"""IDE 式补全引擎：输入中文、拼音或英文词 → 直接给出英文 Danbooru tag 候选。

四类匹配，分数从高到低（同分按 Danbooru 热度）：
    100  中文精确        蓝发
     98  中文词组（命中真实 Danbooru 标签）  巨大乳房 → huge_breasts
     97  中文词组（词表里拼出来的）          黑色蕾丝 → black lace
     95  拼音全拼精确（含多音字变体）        lanfa / changfa / zhangfa
     90  拼音首字母精确                      smw（双马尾）
     88  中文现场拆词拼词组                  红裙子 → red pleated skirt
     85  英文 tag 精确                       breasts
     80  中文前缀                            双马
     72/66/62 英文**整词联想**               breasts → large breasts / huge breasts
     70  拼音全拼前缀                        lanf
     60  拼音首字母前缀                      sm
     55  英文 tag 前缀                       long_h → long_hair
     45  英文词前缀                           breast → breasts

「词组制度」怎么来的（全部本地、零依赖）：
  1. 直接词条：词典里本来就是单词的条目（蕾丝→lace）
  2. 对齐挖掘：把「红发→red hair」这种 1:1 的条目按字对词对齐，攒出 白↔white、发↔hair
  3. 拼装：拿 Danbooru 索引里 2~3 个词的标签（white_thighhighs），
     用上面两张表把每个英文词换成中文再拼起来（白+长筒袜），得到中文词组 → 真实 tag
     这样 3 千多条多词标签不用人工写中文就能被中文查到，而且是**带热度**的真实标签。
  4. 现场拆词：查不到词组时，把中文切成词典里的词，按顺序拼成英文短语（黑色蕾丝 → black lace）
"""
from __future__ import annotations

import os
import re
from collections import Counter, defaultdict
from itertools import product
from typing import Dict, List, Optional, Sequence, Tuple

MAX_VARIANTS = 8                     # 拼音变体上限
MAX_INITIAL_VARIANTS = 4
WORD_HITS_PER_WORD = 40              # 每个英文词最多留多少个热门标签
PHRASE_MIN_COUNT = 50                # 参与拼装的标签至少要有这么多热度
PHRASE_MAX_WORDS = 3                 # 只拼 2~3 个词的标签
PHRASE_VARIANTS = 3                  # 一个标签最多生成几个中文说法
PHRASE_PER_QUERY = 3                 # 一个查询最多给几个词组候选
ALIGN_MIN_VOTES = 2                  # 对齐挖掘：至少两票才算数，避免单个脏词条带偏
# 英文功能词不参与「字↔词」对齐（with/of 这种当名词用会污染词组）
ALIGN_STOPWORDS = {'with', 'of', 'on', 'in', 'and', 'at', 'for', 'to', 'a', 'an', 'the',
                   'by', 'from', 'over', 'under', 'as', 'is', 'no', 'or', 'into'}


def _zh_rank(zh: str) -> tuple:
    """中文候选的排序键。

    优先级：不是动词短语（戴眼镜 ✗）→ 不含数字/序号/符号垃圾（双马尾二 ✗）→ 更长更具体
    （乳房 优于 乳、巨大 优于 超）。同分时保持词典里的原始顺序。
    """
    verbish = zh[:1] in VERB_PREFIXES
    junky = bool(re.search(r'[0-9①-⑩|/（）()\[\]「」]|^[一二三四五六七八九十]+$', zh)) or zh.endswith('二')
    return (1 if verbish else 0, 1 if junky else 0, -len(zh))


def _pick_zh(cands: Sequence[str]) -> str:
    cleaned: List[str] = []
    for c in cands:
        for piece in re.split(r'[|/、;；]', str(c or '')):
            piece = piece.strip()
            if piece and piece not in cleaned:
                cleaned.append(piece)
    return sorted(cleaned, key=_zh_rank)[0] if cleaned else ''


def _is_cjk(ch: str) -> bool:
    return '\u3400' <= ch <= '\u9fff'


# 中文里以这些字开头的多半是动词短语（戴眼镜/穿裙子），当「名词注释」不合适
VERB_PREFIXES = set('戴穿拿握抱牵抓举打踢跑走站坐躺跪摸舔咬吃喝看读写画踩靠在有被用把做')

# 这些字结尾的中文本身已经是方位词了，拼介词时不要再叠一个（地上 + 上 = 地上上 ✗）
POS_CHARS = set('上下里中内间前后旁外左右side')


def _add_pos(base: str, suffix: str) -> str:
    """给中文名词加方位后缀；已经有方位词就不叠。"""
    if not base:
        return base
    if suffix and base[-1] in POS_CHARS and suffix[0] in POS_CHARS:
        return base
    return base + suffix

# 逐词拼中文注释时，遇到这些结构词就放弃（`cum_on_breasts` → 「精液上乳房」这种不如不写）
GLOSS_STOPWORDS = {
    'on', 'in', 'at', 'of', 'with', 'from', 'over', 'under', 'behind', 'near', 'into',
    'to', 'for', 'by', 'against', 'and', 'or', 'the', 'a', 'an', 'as', 'off', 'out', 'up',
}

# 介词：`A_介词_B` 这类标签按中文语序拼。
# 值是 (名词式, 动词式)——动词在前的（standing_on_floor）读「站在地面上」更自然，
# 名词在前的（cum_on_breasts）读「乳房上的精液」更自然。
PREP_PATTERNS = {
    'on': (lambda a, b: f'{_add_pos(b, "上")}的{a}', lambda a, b: f'在{_add_pos(b, "上")}{a}'),
    'in': (lambda a, b: f'{_add_pos(b, "里")}的{a}', lambda a, b: f'在{_add_pos(b, "里")}{a}'),
    'at': (lambda a, b: f'在{b}的{a}', lambda a, b: f'在{b}{a}'),
    'of': (lambda a, b: f'{b}的{a}', lambda a, b: f'{b}的{a}'),
    'with': (lambda a, b: f'带{b}的{a}', lambda a, b: f'带着{b}{a}'),
    'and': (lambda a, b: f'{a}和{b}', lambda a, b: f'{a}和{b}'),
    'or': (lambda a, b: f'{a}或{b}', lambda a, b: f'{a}或{b}'),
    'from': (lambda a, b: f'从{b}的{a}', lambda a, b: f'从{b}{a}'),
    'over': (lambda a, b: f'{_add_pos(b, "上方")}的{a}', lambda a, b: f'{a}在{_add_pos(b, "上方")}'),
    'under': (lambda a, b: f'{_add_pos(b, "下方")}的{a}', lambda a, b: f'{a}在{_add_pos(b, "下方")}'),
    'between': (lambda a, b: f'{_add_pos(b, "之间")}的{a}', lambda a, b: f'{a}在{_add_pos(b, "之间")}'),
    'behind': (lambda a, b: f'{_add_pos(b, "后面")}的{a}', lambda a, b: f'{a}在{_add_pos(b, "后面")}'),
    'near': (lambda a, b: f'{_add_pos(b, "附近")}的{a}', lambda a, b: f'{a}靠近{b}'),
    'against': (lambda a, b: f'贴着{b}的{a}', lambda a, b: f'{a}贴着{b}'),
    'into': (lambda a, b: f'进入{b}的{a}', lambda a, b: f'{a}进入{b}'),
    'by': (lambda a, b: f'被{b}的{a}', lambda a, b: f'被{b}{a}'),
    'to': (lambda a, b: f'朝{b}的{a}', lambda a, b: f'{a}朝向{b}'),
    'for': (lambda a, b: f'为{b}的{a}', lambda a, b: f'为{b}{a}'),
    'off': (lambda a, b: f'脱下{b}的{a}', lambda a, b: f'{a}脱下{b}'),
    'through': (lambda a, b: f'穿过{b}的{a}', lambda a, b: f'{a}穿过{b}'),
}

# 两词标签的介词后缀：under_skirt → 裙子下面
PREP_AFFIX = {
    'on': lambda b: _add_pos(b, '上'), 'in': lambda b: _add_pos(b, '里'),
    'at': lambda b: f'在{b}', 'of': lambda b: f'{b}的', 'with': lambda b: f'带{b}',
    'under': lambda b: _add_pos(b, '下面'), 'over': lambda b: _add_pos(b, '上方'),
    'between': lambda b: _add_pos(b, '之间'), 'behind': lambda b: _add_pos(b, '后面'),
    'near': lambda b: _add_pos(b, '附近'), 'from': lambda b: f'从{b}',
    'to': lambda b: f'朝{b}', 'for': lambda b: f'为{b}', 'by': lambda b: f'被{b}',
    'against': lambda b: f'贴着{b}', 'into': lambda b: f'进入{b}',
    'off': lambda b: f'脱下{b}', 'through': lambda b: f'穿过{b}',
    'and': lambda b: b, 'or': lambda b: b,
}

# 判定「动词在前」的常见词（决定用哪种语序）；-ing 结尾的词一律按动词处理
VERB_HINTS = {
    'tied', 'bound', 'seated', 'dressed', 'undressed', 'covered', 'wet', 'open', 'closed',
    'spread', 'crossed', 'raised', 'lowered', 'bent', 'cut', 'torn', 'blindfolded',
}

# 「被…盖住/沾满」这类词 + 介词 → 更自然的中文
PARTICIPLE_HEADS = {
    'covered': '沾满', 'wet': '被弄湿的', 'soaked': '浸透', 'stained': '沾着',
    'dripping': '滴着', 'full': '满是', 'smelling': '闻着', 'smeared': '涂满',
}

# 词典里没有（或不该当词条收）的英文结构词/方位词，拼注释时用这份兜底
GLOSS_WORDS = {
    'below': '下面', 'above': '上面', 'bottom': '底部', 'left': '左', 'right': '右',
    'front': '前面', 'back': '后面', 'side': '侧面', 'top': '上面', 'under': '下面',
    'over': '上方', 'upper': '上部', 'lower': '下部', 'inner': '内侧', 'outer': '外侧',
    'full': '完整', 'half': '一半', 'part': '部分', 'multi': '多个', 'multiiple': '多个',
    'own': '自己的', 'another': '别人', 'other': '其他', 'same': '相同', 'only': '只有',
    'no': '无', 'not': '非', 'plus': '加', 'extra': '额外', 'alt': '替代', 'alternate': '替代',
    'in': '里', 'on': '上', 'at': '在', 'of': '的', 'with': '带', 'from': '从',
    'overall': '整体', 'close': '近', 'close-up': '特写', 'closeup': '特写', 'wide': '宽',
    'long': '长', 'short': '短', 'big': '大', 'large': '大', 'huge': '巨大', 'small': '小',
    'medium': '中等', 'tiny': '微小', 'thick': '厚', 'thin': '薄', 'slim': '纤细',
}


def _has_cjk(text: str) -> bool:
    return any(_is_cjk(c) for c in (text or ''))


class Completer:
    """中文 / 拼音 / 英文 → tag 候选。词典变了就重建（reload）。"""

    def __init__(self, dictionary, pinyin_path: Optional[str] = None):
        self.dic = dictionary
        self.pinyin: Dict[str, List[str]] = {}
        self.entries: List[Tuple[str, Tuple[str, ...], Tuple[str, ...], str, int]] = []
        self.en_tags: List[Tuple[str, int]] = []
        self.word_index: Dict[str, List[Tuple[str, int]]] = {}
        self.phrase_map: Dict[str, List[Tuple[str, int]]] = {}
        self.en2zh: Dict[str, List[str]] = {}
        self.en_zh: Dict[str, str] = {}          # 英文标签 → 中文（候选里的中文注释）
        self._en_sorted: List[str] = []
        self._words_sorted: List[str] = []
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

    def _build_entries(self) -> None:
        for zh, ens in self.dic.zh2en.items():
            if not zh or not ens or not _has_cjk(zh):
                continue                        # 纯英文键交给英文侧匹配
            best = max((self.dic.popularity(e) for e in ens), default=0)
            en = min(ens, key=lambda s: -self.dic.popularity(s)) if ens else ens[0]
            fulls = self._variants(zh, MAX_VARIANTS)
            inis = self._variants(zh, MAX_INITIAL_VARIANTS, initials=True)
            self.entries.append((zh.lower(), fulls, inis, en, best))

    def _build_en_words(self) -> None:
        """英文 tag → 按词切开建索引：输入 breasts 就能联想到 large breasts / huge breasts。"""
        idx: Dict[str, List[Tuple[str, int]]] = defaultdict(list)
        for tag, count in self.dic.en_count.items():
            for w in set(tag.split('_')):
                if w:
                    idx[w].append((tag, count))
        for w, lst in idx.items():
            lst.sort(key=lambda t: -t[1])
            del lst[WORD_HITS_PER_WORD:]
        self.word_index = dict(idx)
        self._words_sorted = sorted(idx)

    def _direct_word_pairs(self) -> Dict[str, List[str]]:
        """词典里本来就是「中文 → 单个英文词」的条目，最可靠。"""
        direct: Dict[str, List[str]] = {}
        for zh, ens in self.dic.zh2en.items():
            if not (1 <= len(zh) <= 4):
                continue
            for en in ens[:2]:
                e = en.strip().lower()
                if not e or ' ' in e or '_' in e:
                    continue
                bucket = direct.setdefault(e, [])
                if zh not in bucket and len(bucket) < 2:
                    bucket.append(zh)
        return direct

    def _aligned_word_pairs(self) -> Dict[str, List[str]]:
        """把「红发→red hair」这类 1:1 条目按字对词对齐，攒出 白↔white、发↔hair。"""
        votes: Dict[str, Counter] = defaultdict(Counter)
        for zh, ens in self.dic.zh2en.items():
            z = zh.strip()
            if not (2 <= len(z) <= 4) or not all(_is_cjk(c) for c in z):
                continue
            for en in ens[:2]:
                words = [w for w in en.strip().lower().replace('_', ' ').split()
                         if w and w not in ALIGN_STOPWORDS]
                if len(words) != len(z):
                    continue
                for c, w in zip(z, words):
                    votes[c][w] += 1
        mined: Dict[str, List[str]] = {}
        for zh_char, cnt in votes.items():
            word, n = cnt.most_common(1)[0]
            if n < ALIGN_MIN_VOTES:
                continue
            # 有别的候选票数追平/更高就放弃这个字，避免把歧义带进词组
            others = sorted(cnt.values(), reverse=True)[1:]
            if others and others[0] >= n:
                continue
            bucket = mined.setdefault(word, [])
            if zh_char not in bucket and len(bucket) < 2:
                bucket.append(zh_char)
        return mined

    def _build_phrases(self) -> None:
        """把 Danbooru 里的多词标签拼成中文词组（白 + 长筒袜 → white_thighhighs）。"""
        mined = self._aligned_word_pairs()
        direct = self._direct_word_pairs()
        en2zh = dict(mined)
        en2zh.update(direct)                 # 直接词条优先
        # 每个英文词的中文候选按「名词优先、更具体优先」重排，取第一个用来拼注释
        for w, zhs in list(en2zh.items()):
            en2zh[w] = sorted(set(zhs), key=_zh_rank)
        self.en2zh = en2zh

        phrases: Dict[str, List[Tuple[str, int]]] = defaultdict(list)
        for tag, count in self.dic.en_count.items():
            if count < PHRASE_MIN_COUNT:
                continue
            words = tag.split('_')
            if not (2 <= len(words) <= PHRASE_MAX_WORDS):
                continue
            cands = [en2zh.get(w) for w in words]
            if any(not c for c in cands):
                continue
            made = 0
            for combo in product(*cands):
                zh_phrase = ''.join(combo)
                if not zh_phrase or len(zh_phrase) > 12:
                    continue
                bucket = phrases[zh_phrase]
                if any(t == tag for t, _ in bucket):
                    continue
                if len(bucket) < 2:
                    bucket.append((tag, count))
                made += 1
                if made >= PHRASE_VARIANTS:
                    break
        self.phrase_map = dict(phrases)

    def _build_en_zh(self) -> None:
        """英文标签 → 中文，给「只有英文的候选」补上中文注释。

        三个来源，按优先级：
          1. 词表里现成的整条翻译（词典里 中↔英 反向查；用户下载的社区中文表也在这个池子里）
          2. 逐词拼：huge(巨大) + breasts(乳房) → 巨大乳房（有任何一个词不认识就放弃，免得拼出怪话）
          3. 拼不出来就不写（界面会退化成只显示英文 + 来源标签）
        """
        buckets: Dict[str, List[str]] = {}
        for zh, ens in self.dic.zh2en.items():
            z = (zh or '').strip()
            if not (1 <= len(z) <= 14) or not _has_cjk(z):
                continue
            for en in ens:
                key = en.strip().lower().replace(' ', '_')
                if not key:
                    continue
                bucket = buckets.setdefault(key, [])
                if z not in bucket:
                    bucket.append(z)
        # 同一个英文有多个中文说法时，挑最像「名词注释」的那个（排掉戴眼镜这类动词短语）
        self.en_zh = {k: _pick_zh(v) for k, v in buckets.items() if v}

    def gloss(self, tag_en: str) -> str:
        """给一个英文标签配中文注释（没有就返回空串）。"""
        key = (tag_en or '').strip().lower().replace(' ', '_')
        if not key:
            return ''
        hit = self.en_zh.get(key)
        if hit:
            return hit
        words = [w for w in key.split('_') if w]
        if len(words) < 2:
            return ''
        # ① 找到介词位置，按中文语序拼：
        #    cum_on_breasts → 乳房上的精液、standing_on_floor → 站在地面上、hands_on_another's_face → 他人的脸上的双手
        for idx in range(1, len(words) - 1):
            prep = words[idx]
            if prep not in PREP_PATTERNS:
                continue
            tail = self._gloss_words(words[idx + 1:], partial=False)
            if not tail:
                break
            # 「沾满/满是」这类被动语态的词先单独处理，读起来更自然（covered_in_cum → 沾满精液）
            if words[0] in PARTICIPLE_HEADS and prep in ('in', 'with', 'of', 'on'):
                return f'{PARTICIPLE_HEADS[words[0]]}{tail}'
            head = self._gloss_words(words[:idx], partial=False)
            if head:
                noun_fn, verb_fn = PREP_PATTERNS[prep]
                is_verb = words[0].endswith('ing') or words[0] in VERB_HINTS
                return (verb_fn if is_verb else noun_fn)(head, tail)
            break
        # ①' 两个词的介词开头：under_skirt → 裙子下面
        if len(words) == 2 and words[0] in PREP_AFFIX:
            tail = self._gloss_words(words[1:], partial=False)
            if tail:
                return PREP_AFFIX[words[0]](tail)
        # ② 逐词拼（顺序照抄英文）
        full = self._gloss_words(words, partial=False)
        if full:
            return full
        # ③ 兜底：把认识的词拼出来（总比没有中文强）
        return self._gloss_words(words, partial=True)

    def _gloss_words(self, words: Sequence[str], partial: bool = False) -> str:
        """把一串英文词逐词翻成中文并拼起来。

        partial=False：有词不认识就返回空串（不硬拼，保证意思准确）
        partial=True ：跳过不认识的词（用于兜底，至少给出一部分中文）
        """
        parts: List[str] = []
        for raw in words:
            w = raw.strip()
            if not w:
                continue
            possessive = w.endswith("'s") or w.endswith('’s')
            if possessive:
                w = w[:-2]
            zs = self.en2zh.get(w) or ([GLOSS_WORDS[w]] if w in GLOSS_WORDS else None)
            if not zs:
                if partial:
                    continue
                return ''
            parts.append(zs[0] + ('的' if possessive else ''))
        if partial and len(parts) < 1:
            return ''
        return ''.join(parts)

    def build(self) -> 'Completer':
        self.load_pinyin()
        self._build_entries()
        self.en_tags = list(self.dic.en_count.items())
        self._en_sorted = sorted(self.dic.en_count.keys())
        self._build_en_words()
        self._build_phrases()
        self._build_en_zh()
        return self

    # ------------------------------------------------------------------ 英文侧
    def _en_prefix(self, q: str, limit: int) -> List[Tuple[int, int, str, str]]:
        """英文 tag 前缀：long_h → long_hair"""
        import bisect
        out = []
        i = bisect.bisect_left(self._en_sorted, q)
        while i < len(self._en_sorted) and len(out) < limit * 3:
            tag = self._en_sorted[i]
            if not tag.startswith(q):
                break
            score = 85 if tag == q else 55
            out.append((score, self.dic.en_count.get(tag, 0), tag, ''))
            i += 1
        return out

    def _en_word(self, q: str, limit: int) -> List[Tuple[int, int, str, str]]:
        """英文整词联想：breasts → large breasts / huge breasts；breast → breasts"""
        out: List[Tuple[int, int, str, str]] = []
        for tag, count in self.word_index.get(q, [])[:limit * 4]:
            if tag == q:
                continue                                   # 精确命中另有 85 分
            words = tag.split('_')
            if words[-1] == q:
                score = 72                                 # 被修饰的那个词：huge_breasts
            elif words[0] == q:
                score = 66                                 # 修饰别人：breasts_squeeze
            else:
                score = 62
            out.append((score, count, tag, ''))
        # 词前缀（breast → breasts / breastfeeding），用二分找区间，别全表扫
        import bisect
        i = bisect.bisect_left(self._words_sorted, q)
        seen = 0
        while i < len(self._words_sorted) and seen < 12:
            w = self._words_sorted[i]
            if not w.startswith(q):
                break
            if w != q:
                for tag, count in self.word_index.get(w, [])[:2]:
                    if tag != q:
                        out.append((45, count, tag, ''))
                seen += 1
            i += 1
        return out

    # ------------------------------------------------------------------ 中文侧
    def _cn_phrases(self, q: str) -> List[Tuple[int, int, str, str]]:
        """词组制度：先查拼装好的中文词组表，再现场把这句话拆词拼英文。"""
        out: List[Tuple[int, int, str, str]] = []
        for tag, count in self.phrase_map.get(q, [])[:PHRASE_PER_QUERY]:
            out.append((98, count, tag, q))                # 命中真实 Danbooru 标签
        seg = self.dic.longest_match(q)
        matched = [ens[0] for _zh, ens in seg if ens]
        covered = sum(len(zh) for zh, ens in seg if ens)
        if len(matched) >= 2:
            phrase = ' '.join(matched)
            key = phrase.replace(' ', '_').lower()
            canon = self.dic.canonical_en(key) or key
            count = self.dic.en_count.get(canon, 0)
            en = self.dic.normalize_en(canon)
            if en and en.lower() != q.lower():
                out.append((88, count, en, q))             # 现场拼出来的短语
        elif len(matched) == 1 and covered >= len(q) - 1:
            # 「红裙子」= 红裙（命中）+ 子（尾字）→ 把命中的那个给出来，别让用户白等
            en = matched[0]
            out.append((75, self.dic.popularity(en), en, q))
        return out

    # ------------------------------------------------------------------ 查询
    def complete(self, query: str, limit: int = 10) -> List[dict]:
        q = (query or '').strip().lower()
        if not q:
            return []
        has_cjk = _has_cjk(q)
        scored: List[Tuple[int, int, str, str, str]] = []   # (score, count, en, zh, kind)

        for zh, fulls, inis, en, count in self.entries:
            s = 0
            kind = 'zh'
            if q == zh:
                s = 100
            elif q == zh[:len(q)] and has_cjk:
                s = 80
            elif has_cjk and q in zh:
                s = 40
            elif not has_cjk and fulls:
                kind = 'pinyin'
                if q in fulls:
                    s = 95
                elif q in inis:
                    s = 90
                elif any(f.startswith(q) for f in fulls):
                    s = 70
                elif any(i2.startswith(q) for i2 in inis):
                    s = 60
            if s:
                scored.append((s, count, en, zh, kind))

        if has_cjk:
            for s, count, en, zh in self._cn_phrases(q):
                scored.append((s, count, en, zh, 'phrase'))

        if not has_cjk and len(q) >= 2:
            # 英文也可以带空格写（red dress = red_dress），统一成下划线再匹配
            q_us = q.replace(' ', '_')
            for s, count, en, zh in self._en_prefix(q_us, limit):
                scored.append((s, count, en, zh, 'en'))
            for s, count, en, zh in self._en_word(q_us, limit):
                scored.append((s, count, en, zh, 'enword'))

        # 同一个英文 tag（下划线/空格写法算同一个）只留分最高的那个，再按 (分数, 热度) 排
        best: Dict[str, Tuple[int, int, str, str]] = {}
        for s, count, en, zh, kind in scored:
            key = en.strip().lower().replace(' ', '_')
            cur = best.get(key)
            if cur is None or (s, count) > (cur[0], cur[1]):
                best[key] = (s, count, zh, kind)
        ranked = sorted(best.items(), key=lambda kv: (-kv[1][0], -kv[1][1], kv[0]))
        out = []
        for _key, (s, count, zh, kind) in ranked[:max(1, limit)]:
            display = _key.replace('_', ' ')
            # 没有中文的候选（英文联想/英文前缀）补一个中文注释：现成翻译 → 逐词拼 → 留空
            if not zh:
                zh = self.gloss(_key)
            out.append({'en': display, 'zh': zh, 'score': s, 'count': count, 'kind': kind})
        return out


_COMPLETER: Optional[Completer] = None


def get_completer(reload: bool = False) -> Completer:
    global _COMPLETER
    if _COMPLETER is None or reload:
        from .dictionary import get_dictionary
        _COMPLETER = Completer(get_dictionary(reload=reload))
        print(f'[ZHTag] 补全索引就绪：{len(_COMPLETER.entries)} 条中文词条 / '
              f'拼音表 {len(_COMPLETER.pinyin)} 字 / 英文索引 {len(_COMPLETER.en_tags)} 条 / '
              f'英文词联想 {len(_COMPLETER.word_index)} 词 / 中文词组 {len(_COMPLETER.phrase_map)} 条 / '
              f'英文中文注释 {len(_COMPLETER.en_zh)} 条')
    return _COMPLETER
