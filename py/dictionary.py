# -*- coding: utf-8 -*-
"""中文 → 英文 tag 词典：加载、索引、最长匹配切分、功能词过滤、Danbooru 规范化、翻译。

不依赖 ComfyUI，可单独用 python 跑（便于测试）。

四层处理：
  1) 功能词/量词过滤：一个/的/站着… 这类不查词典也不当 tag 输出
  2) 词典匹配：精确 → 繁简归一 → 最长匹配切分（「蓝发漂亮姑娘」→ 蓝发 + 漂亮 + 姑娘）
  3) 数字人物规则：「两个女孩」→ 2girls、「三个男孩」→ 3boys
  4) 英文输出规范化 + Danbooru 热度排序：longhair → long_hair，多候选时取最热的
未命中处理可选：drop（默认，丢弃并报告）/ keep（保留中文）/ fallback（交给兜底翻译）
"""
from __future__ import annotations

import json
import os
import re
from typing import Dict, Iterable, List, Optional, Tuple

CJK = re.compile(r'[\u3400-\u9fff\uf900-\ufaff]')
WEIGHTED = re.compile(r'^(\s*)([(\[]+)(.*?)(?:\s*[:：]\s*([\d.]+))?([)\]]+)(\s*)$')
SEPARATORS = re.compile(r'[,，、;；\n\r]+')
TAG_KEY_OK = re.compile(r"^[0-9A-Za-z][0-9A-Za-z _\-\.'&()/]*$")

# 中文数词 → 阿拉伯数字
CN_NUM = {'一': 1, '两': 2, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6,
          '七': 7, '八': 8, '九': 9, '十': 10, '半': 0}
RE_PERSON = re.compile(r'^\s*([0-9]+|[一二两三四五六七八九十]+)\s*(?:个|位|名|只)?\s*'
                       r'(女孩|女子|少女|女人|女性|姑娘|女的|男生|男孩|男子|少年|男性|男孩子|女孩子)\s*$')
RE_PEOPLE = re.compile(r'^\s*([0-9]+|[一二两三四五六七八九十]+)\s*(?:个|位|名)\s*(人|人物|角色)\s*$')

# 功能词/量词/虚词：不查词典、不输出（否则会出现「一个, blue hair, 的漂亮姑娘」这种结果）
FUNCTION_WORDS = [
    '的', '地', '得', '了', '着', '是', '在', '和', '与', '及', '以及', '还有', '或者', '或是',
    '一个', '一位', '一名', '这个', '那个', '这些', '那些', '一些', '某个', '某些', '一种',
    '非常', '十分', '很', '太', '更', '最', '挺', '有点', '稍微', '略微', '比较',
    '似乎', '好像', '大概', '或许', '也许', '其实', '总是', '从来', '一直',
    '然后', '而且', '但是', '可是', '因为', '所以', '如果', '那么', '只是', '不过', '于是', '因此',
    '就是', '不是', '没有', '可以', '能够', '想要', '正在', '已经', '将要', '并且', '而', '则',
    '便', '就', '也', '都', '才', '又', '再', '还', '只', '仅', '却', '竟然', '居然',
    '之', '其', '把', '被', '给', '对', '从', '到', '向', '往', '以', '为', '于', '用', '等', '等等', '之类',
    '上', '下', '里', '中', '内', '外', '里外', '之下', '之上', '之中', '里面', '外面', '上面', '下面',
    # 动态助词/语气词/时间副词：自然语言里到处是，留着只会污染 tag
    '过', '起来', '下来', '下去', '出来', '进去', '开来',
    '呢', '吗', '吧', '啊', '呀', '哦', '嗯', '唉', '嘿', '喂', '么', '嘛',
    '的时候', '之际', '此时', '那时', '当时', '之后', '之前', '以后', '以前',
    '突然', '忽然', '猛然', '缓缓', '慢慢', '轻轻', '静静', '悄悄', '默默', '渐渐', '微微',
    '终于', '依然', '仍然', '始终', '仿佛', '宛如', '像是', '如同', '好像',
    '一起', '一同', '一块', '各自', '互相', '分别', '立刻', '马上', '随即', '接着', '继续',
    # 人称代词：人物描述里出现频率极高，但本身不是 tag
    '我', '你', '您', '他', '她', '它', '咱', '我们', '你们', '他们', '她们', '它们',
    '咱们', '大家', '自己', '别人', '对方', '彼此', '有人', '某人',
]
FUNCTION_WORDS = sorted(set(FUNCTION_WORDS), key=len, reverse=True)


def has_cjk(text: str) -> bool:
    return bool(CJK.search(text or ''))


def _norm(text: str) -> str:
    return ' '.join((text or '').replace('\u3000', ' ').split())


def _cn_number(token: str) -> Optional[int]:
    token = (token or '').strip()
    if token.isdigit():
        return int(token)
    if token == '十':
        return 10
    if token.startswith('十'):
        return 10 + CN_NUM.get(token[1:], 0)
    if token.endswith('十'):
        return CN_NUM.get(token[:-1], 0) * 10
    if '十' in token:
        a, _, b = token.partition('十')
        return CN_NUM.get(a, 0) * 10 + CN_NUM.get(b, 0)
    total = 0
    for ch in token:
        total += CN_NUM.get(ch, 0)
    return total or None


class TagDictionary:
    """中文 tag 词典 + Danbooru 英文索引。"""

    def __init__(self, data_dirs: Iterable[str] = ()):
        self.zh2en: Dict[str, List[str]] = {}
        self.en2zh: Dict[str, List[str]] = {}
        self.ts_map: Dict[str, str] = {}
        self.en_canon: Dict[str, str] = {}          # 英文别名 → Danbooru 正名
        self.en_count: Dict[str, int] = {}          # 正名 → 热度
        self._by_len: Dict[int, set] = {}
        self.max_key_len = 0
        self.sources: List[str] = []
        self.dropped = 0
        self.index_tags = 0
        self._simp_cache: Dict[str, str] = {}
        self.data_dirs = [d for d in data_dirs if d and os.path.isdir(d)]

    # ------------------------------------------------------------------ 加载
    def load_all(self) -> 'TagDictionary':
        for d in self.data_dirs:
            for name in sorted(os.listdir(d)):
                path = os.path.join(d, name)
                if not os.path.isfile(path):
                    continue
                low = name.lower()
                if low.startswith(('readme', 'license', 'licence', 'notice', 'changelog', 'sources')):
                    continue                      # 说明文件不要当成词典来源
                if low in ('config.json', 'cache.json', 'settings.json'):
                    continue                      # 兜底翻译的配置/缓存，不是词典
                if 'pinyin' in low:
                    continue                      # 拼音表是「字→拼音」，由补全引擎单独读取，别当词典
                if 'danbooru_index' in low and low.endswith(('.tsv', '.txt')):
                    self._load_danbooru_index(path)
                elif low.startswith('ts_') or 'tscharacters' in low or 'ts_characters' in low:
                    self._load_ts_file(path)
                elif low.endswith(('.csv', '.txt', '.tsv')):
                    self._load_text(path)
                elif low.endswith('.json'):
                    self._load_json(path)
                elif low.endswith(('.yaml', '.yml')):
                    self._load_yaml(path)
                else:
                    continue
                self.sources.append(name)
        self._finalize()
        return self

    def _load_danbooru_index(self, path: str) -> None:
        """canonical<TAB>count<TAB>aliases|aliases"""
        try:
            with open(path, 'r', encoding='utf-8-sig') as f:
                for line in f:
                    line = line.rstrip('\n')
                    if not line or line.startswith('#'):
                        continue
                    parts = line.split('\t')
                    if len(parts) < 2:
                        continue
                    tag = parts[0].strip().lower()
                    if not tag:
                        continue
                    try:
                        self.en_count[tag] = int(parts[1])
                    except ValueError:
                        self.en_count[tag] = 0
                    self.index_tags += 1
                    if len(parts) > 2 and parts[2].strip():
                        for a in parts[2].split('|'):
                            a = a.strip().lower()
                            if a and a != tag:
                                self.en_canon.setdefault(a, tag)
        except Exception as e:
            print(f'[ZHTag] 读取 Danbooru 索引失败 {path}: {e}')

    def _load_text(self, path: str) -> None:
        try:
            with open(path, 'r', encoding='utf-8-sig') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    parts = [p.strip() for p in line.split(',')]
                    if len(parts) < 2:
                        continue
                    a, rest = parts[0], [p for p in parts[1:] if p]
                    if not rest:
                        continue
                    # 中文侧允许用 | 分同义词
                    if has_cjk(a) and not has_cjk(rest[0]):
                        for zh in a.split('|'):
                            for en in rest:
                                self._add(zh, en)
                    elif not has_cjk(a) and has_cjk(rest[0]):
                        for chunk in rest:
                            for zh in chunk.split('|'):
                                self._add(zh, a)
                    else:
                        self.dropped += 1
        except Exception as e:
            print(f'[ZHTag] 读取失败 {path}: {e}')

    def _load_json(self, path: str) -> None:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            print(f'[ZHTag] 读取失败 {path}: {e}')
            return
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, list):
                    for item in v:
                        self._pair(k, item)
                else:
                    self._pair(k, v)
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    zh = item.get('zh') or item.get('cn') or item.get('中文')
                    en = item.get('en') or item.get('english') or item.get('英文')
                    if zh and en:
                        self._pair(zh, en)

    def _pair(self, a, b) -> None:
        a, b = _norm(str(a)), _norm(str(b))
        if not a or not b:
            return
        if has_cjk(a) and not has_cjk(b):
            self._add(a, b)
        elif has_cjk(b) and not has_cjk(a):
            self._add(b, a)

    def _load_yaml(self, path: str) -> None:
        """兼容 sd-webui-prompt-all-in-one 的 group_tags/*.yaml（只取 tags 块）。"""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                text = f.read()
        except Exception as e:
            print(f'[ZHTag] 读取失败 {path}: {e}')
            return
        in_tags = False
        for raw in text.splitlines():
            if not raw.strip() or raw.lstrip().startswith('#'):
                continue
            if re.match(r'^\s*tags:\s*$', raw):
                in_tags = True
                continue
            m = re.match(r'^(\s+)([^:\s][^:]*?):(?:\s*(.*))?$', raw)
            if not m:
                if re.match(r'^\s*-\s', raw) or re.match(r'^\s{0,3}\S', raw):
                    in_tags = False
                continue
            indent, key, val = m.group(1), m.group(2).strip(), _norm(m.group(3) or '')
            if not in_tags:
                continue
            if len(indent) < 4:
                in_tags = False
                continue
            if not val or not has_cjk(val) or not key or not TAG_KEY_OK.match(key):
                continue
            if len(key) > 48 or len(val) > 40 or re.search(r'[(),\[\]{}:;"]', val):
                continue
            for zh in val.split('|'):
                self._add(zh, key)

    def _load_ts_file(self, path: str) -> None:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                self._load_ts_table(f.read())
        except Exception as e:
            print(f'[ZHTag] 读取繁简表失败 {path}: {e}')

    def _load_ts_table(self, text: str) -> None:
        for line in text.splitlines():
            if not line.strip() or line.startswith('#'):
                continue
            parts = line.split('\t')
            if len(parts) >= 2 and parts[0] and parts[1]:
                self.ts_map[parts[0]] = parts[1].split(' ')[0]

    def _add(self, zh: str, en: str) -> None:
        zh, en = _norm(zh), _norm(en)
        if not zh or not en or not has_cjk(zh) or has_cjk(en):
            return
        if len(zh) > 60 or len(en) > 120:
            self.dropped += 1
            return
        bucket = self.zh2en.setdefault(zh, [])
        if en not in bucket:
            bucket.append(en)
        rev = self.en2zh.setdefault(en, [])
        if zh not in rev:
            rev.append(zh)

    def _finalize(self) -> None:
        self.sources = list(dict.fromkeys(self.sources))
        self._by_len = {}
        self.max_key_len = 0
        for zh in self.zh2en:
            n = len(zh)
            self._by_len.setdefault(n, set()).add(zh)
            if n > self.max_key_len:
                self.max_key_len = n
        # 多条英文候选时：先看 Danbooru 热度，其次短的/无下划线的
        for zh, lst in self.zh2en.items():
            lst.sort(key=lambda s: (-self.en_count.get(self.canonical_en(s) or '', 0), len(s), '_' in s, s))

    @property
    def size(self) -> int:
        return len(self.zh2en)

    # ------------------------------------------------------------------ 英文规范化
    def canonical_en(self, tag: str) -> Optional[str]:
        """把英文写法换成 Danbooru 正名（longhair → long_hair）；不是已知标签就返回 None。"""
        t = _norm(tag).lower().replace(' ', '_')
        if not t:
            return None
        if t in self.en_count:
            return t
        return self.en_canon.get(t)

    def normalize_en(self, tag: str, underscore: bool = False) -> str:
        """输出用：命中 Danbooru 就换正名，否则原样。underscore=False 时把下划线换回空格。"""
        c = self.canonical_en(tag)
        if not c:
            return tag
        return c if underscore else c.replace('_', ' ')

    def popularity(self, tag: str) -> int:
        c = self.canonical_en(tag)
        return self.en_count.get(c or '', 0)

    # ------------------------------------------------------------------ 繁简
    def to_simplified(self, text: str) -> str:
        if not self.ts_map or not text:
            return text
        cached = self._simp_cache.get(text)
        if cached is not None:
            return cached
        out = ''.join(self.ts_map.get(ch, ch) for ch in text)
        if len(self._simp_cache) < 4096:
            self._simp_cache[text] = out
        return out

    # ------------------------------------------------------------------ 查询
    def lookup(self, zh: str) -> List[str]:
        zh = _norm(zh)
        if not zh:
            return []
        hit = self.zh2en.get(zh)
        if hit:
            return list(hit)
        simp = self.to_simplified(zh)
        if simp != zh:
            hit = self.zh2en.get(simp)
            if hit:
                return list(hit)
        if self.is_function_word(zh):
            return []
        return []

    # ------------------------------------------------------------------ 功能词
    @staticmethod
    def is_function_word(text: str) -> bool:
        t = _norm(text)
        if not t:
            return True
        for w in FUNCTION_WORDS:
            if t == w:
                return True
        return False

    @staticmethod
    def strip_fillers(fragment: str) -> str:
        """去掉片段首尾的功能词（不动中间，避免破坏「目的」这类词）。"""
        t = _norm(fragment)
        changed = True
        while changed and t:
            changed = False
            for w in FUNCTION_WORDS:
                if t.startswith(w) and len(t) > len(w):
                    t = t[len(w):].strip()
                    changed = True
                    break
                if t.endswith(w) and len(t) > len(w):
                    t = t[:-len(w)].strip()
                    changed = True
                    break
        return t

    # ------------------------------------------------------------------ 匹配
    def longest_match(self, fragment: str) -> List[Tuple[str, List[str]]]:
        """在片段内做最长优先贪心匹配；未命中的字符按原样返回（交给上层处理）。"""
        frag = _norm(fragment)
        if not frag:
            return []
        out: List[Tuple[str, List[str]]] = []
        buf = ''
        i, n = 0, len(frag)
        while i < n:
            ch = frag[i]
            if ch == ' ':
                if buf:
                    out.append((buf, []))
                    buf = ''
                buf = ' '
                i += 1
                continue
            matched = None
            top = min(self.max_key_len, n - i)
            for length in range(top, 0, -1):
                cand = frag[i:i + length]
                bucket = self._by_len.get(length)
                if not bucket:
                    continue
                if cand in bucket:
                    matched = (cand, self.zh2en[cand])
                    break
                simp = self.to_simplified(cand)
                if simp != cand and simp in bucket:
                    matched = (cand, self.zh2en[simp])
                    break
            if matched:
                if buf:
                    out.append((buf, []))
                    buf = ''
                out.append(matched)
                i += len(matched[0])
            else:
                buf += ch
                i += 1
        if buf:
            out.append((buf, []))
        return out

    @staticmethod
    def number_tag(fragment: str) -> Optional[str]:
        """「两个女孩」→ 2girls；「一个男孩」→ 1boy"""
        t = _norm(fragment)
        m = RE_PERSON.match(t)
        if m:
            num = _cn_number(m.group(1))
            if num:
                female = m.group(2) in ('女孩', '女子', '少女', '女人', '女性', '姑娘', '女的', '女孩子')
                if num == 1:
                    return '1girl' if female else '1boy'
                return '%d%s' % (num, 'girls' if female else 'boys')
        m2 = RE_PEOPLE.match(t)
        if m2:
            num = _cn_number(m2.group(1))
            if num and num > 1:
                return '%dpeople' % num
        return None

    # ------------------------------------------------------------------ 翻译
    def translate(self, text: str, mode: str = 'tags', dedupe: bool = True,
                  keep_unknown: bool = True, fallback=None, first_only: bool = True,
                  unknown_mode: str = 'drop', normalize: bool = True,
                  underscore: bool = False) -> Tuple[str, dict]:
        """把中文提示词翻译成英文 tag 串。

        unknown_mode: 'drop'（默认，丢弃未命中项，只写进报告）
                      'keep'（保留中文原文）
                      'fallback'（交给 fallback 翻译器，失败则丢弃）
        normalize:    True（默认）把英文换成 Danbooru 正名并按热度排序
        """
        report = {'matched': 0, 'unknown': [], 'translated': 0, 'kept': 0, 'dropped': 0,
                  'function': 0, 'entries': self.size, 'index': self.index_tags}
        if not text or not text.strip():
            return '', report
        if unknown_mode == 'keep':
            keep_unknown = True
        elif unknown_mode in ('drop', 'fallback'):
            keep_unknown = False

        out_parts: List[str] = []

        # 只有「整句就是一个字」时才允许把这个单字送去在线翻译；
        # 否则「红裙子」被切成 红裙 + 子 时，孤零零的「子」会被翻成 child 之类的噪音。
        single_char_input = len(_norm(text)) <= 1

        def emit(tags: Iterable[str]) -> None:
            for t in tags:
                if t:
                    out_parts.append(self.normalize_en(t, underscore) if normalize else t)

        for block in SEPARATORS.split(text):
            block = block.strip()
            if not block:
                continue
            w = WEIGHTED.match(block)
            prefix = suffix = weight = ''
            if w and has_cjk(w.group(3)):
                prefix, suffix, weight = w.group(2), w.group(5), (':' + w.group(4) if w.group(4) else '')
                block = w.group(3).strip()
            for zh, ens in self.longest_match(block):
                if ens:
                    emit(ens[:1] if first_only else ens)
                    report['matched'] += 1
                    continue
                frag = self.strip_fillers(zh)
                if not frag or self.is_function_word(frag):
                    report['function'] += 1
                    continue
                if not has_cjk(frag):
                    emit([frag])                    # 本来就是英文/数字/符号
                    continue
                numbered = self.number_tag(frag)
                if numbered:
                    emit([numbered])
                    report['matched'] += 1
                    continue
                hit = self.lookup(frag)
                if hit:
                    emit(hit[:1] if first_only else hit)
                    report['matched'] += 1
                    continue
                allow_online = len(frag) >= 2 or single_char_input
                if unknown_mode == 'fallback' and fallback and allow_online:
                    en = fallback(frag)
                    if en:
                        emit([en])
                        report['translated'] += 1
                        continue
                if keep_unknown:
                    emit([frag])
                    report['kept'] += 1
                    report['unknown'].append(frag)
                else:
                    report['dropped'] += 1
                    report['unknown'].append(frag)
                    if not allow_online:
                        report['skipped_online'] = report.get('skipped_online', 0) + 1
            if weight and out_parts:
                out_parts[-1] = f'{prefix}{out_parts[-1]}{weight}{suffix}'

        if mode == 'raw':
            result = ' '.join(p for p in out_parts if p).strip()
        else:
            seen, cleaned = set(), []
            for p in out_parts:
                tag = p.strip().strip(',')
                if not tag:
                    continue
                key = tag.lower()
                if dedupe and key in seen:
                    continue
                seen.add(key)
                cleaned.append(tag)
            if normalize:
                # 按 Danbooru 热度排序（最热/最标准的放前面），未知热度的保持原顺序在后
                known = [t for t in cleaned if self.popularity(t) > 0]
                rest = [t for t in cleaned if self.popularity(t) <= 0]
                known.sort(key=lambda t: -self.popularity(t))
                cleaned = known + rest
            result = ', '.join(cleaned)
        report['result'] = result
        return result, report


_DEFAULT: Optional[TagDictionary] = None


def default_data_dirs() -> List[str]:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return [os.path.join(here, 'data'), os.path.join(here, 'data', 'user')]


def get_dictionary(reload: bool = False) -> TagDictionary:
    global _DEFAULT
    if _DEFAULT is None or reload:
        _DEFAULT = TagDictionary(default_data_dirs()).load_all()
        print(f'[ZHTag] 词典就绪：{_DEFAULT.size} 条中文词条 / Danbooru 索引 {_DEFAULT.index_tags} 条 '
              f'（来源：{", ".join(_DEFAULT.sources) or "无"}）')
    return _DEFAULT
