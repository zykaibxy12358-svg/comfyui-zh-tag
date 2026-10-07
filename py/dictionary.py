# -*- coding: utf-8 -*-
"""中文 → 英文 tag 词典：加载、索引、最长匹配切分、翻译。

不依赖 ComfyUI，可单独用 python 跑（便于测试）。

词典文件格式（放在 data/ 或 data/user/ 下，自动全部加载）：
  · .csv / .txt  每行 `中文,english tag` 或 `中文[|同义词],english tag[,english tag 2]`
                 也接受反过来的 `english tag,中文`
  · .json        {中文: 英文} / {英文: 中文} / [{"zh":"…","en":"…"}, …]
  · .yaml/.yml   兼容 sd-webui-prompt-all-in-one 的 group_tags 格式（tags: 下的 `英文: 中文`）
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


def has_cjk(text: str) -> bool:
    return bool(CJK.search(text or ''))


def _norm(text: str) -> str:
    return ' '.join((text or '').replace('\u3000', ' ').split())


class TagDictionary:
    """中文 tag 词典。

    - zh2en: 中文 → [英文 tag, …]（同一条中文可对应多个英文写法）
    - 匹配策略：先按分隔符切片段，再在片段内做「最长优先」贪心匹配，
      因此「红色长发」可以拆成「红色」+「长发」两个 tag。
    """

    def __init__(self, data_dirs: Iterable[str] = ()):
        self.zh2en: Dict[str, List[str]] = {}
        self.en2zh: Dict[str, List[str]] = {}
        self.ts_map: Dict[str, str] = {}          # 繁体字 → 简体字
        self._by_len: Dict[int, set] = {}
        self.max_key_len = 0
        self.sources: List[str] = []
        self.dropped = 0
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
                if low.startswith('ts_') or 'tscharacters' in low or 'ts_characters' in low:
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
                    if has_cjk(a) and not has_cjk(rest[0]):
                        # 中文,英文[,英文2…]；中文可用 | 分隔同义词
                        for zh in a.split('|'):
                            for en in rest:
                                self._add(zh, en)
                    elif not has_cjk(a) and has_cjk(rest[0]):
                        # 英文,中文[,中文2…]
                        for zh in rest:
                            self._add(zh, a)
                    else:
                        self.dropped += 1
        except Exception as e:                      # 坏文件不影响启动
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
        if 'ts_characters' in os.path.basename(path).lower():
            self._load_ts_table(text)
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
            self._add(val, key)

    def _load_ts_file(self, path: str) -> None:
        """读取 OpenCC 的 TSCharacters.txt（繁体 → 简体）。"""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                self._load_ts_table(f.read())
        except Exception as e:
            print(f'[ZHTag] 读取繁简表失败 {path}: {e}')

    def _load_ts_table(self, text: str) -> None:
        """OpenCC 的 TSCharacters.txt：繁体 → 简体（制表符分隔）。"""
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
        # 同一条中文有多个英文时，短的/无下划线的排前面（更像 tag）
        for zh, lst in self.zh2en.items():
            lst.sort(key=lambda s: (len(s), '_' in s, s))

    @property
    def size(self) -> int:
        return len(self.zh2en)

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
        return []

    def longest_match(self, fragment: str) -> List[Tuple[str, List[str]]]:
        """在片段内做最长优先贪心匹配，返回 [(中文, [英文…]), …]；未命中的字符按原样返回。"""
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

    # ------------------------------------------------------------------ 翻译
    def translate(self, text: str, mode: str = 'tags', dedupe: bool = True,
                  keep_unknown: bool = True, fallback=None, first_only: bool = True) -> Tuple[str, dict]:
        """把中文提示词翻译成英文 tag 串。

        first_only=True（默认）：一条中文只取词典里排序最靠前的那个英文 tag，
        避免社区词库里个别脏别名（如「红色」同时挂着 red 和 red long upper shan）一起被输出。
        返回 (英文文本, 报告)；报告含 unknown（未命中词典的片段）与计数。
        """
        report = {'matched': 0, 'unknown': [], 'translated': 0, 'kept': 0, 'entries': self.size}
        if not text or not text.strip():
            return '', report

        out_parts: List[str] = []
        for block in SEPARATORS.split(text):
            block = block.strip()
            if not block:
                continue
            w = WEIGHTED.match(block)
            prefix = suffix = ''
            weight = ''
            if w and has_cjk(w.group(3)):
                prefix, suffix, weight = w.group(2), w.group(5), (':' + w.group(4) if w.group(4) else '')
                block = w.group(3).strip()
            for zh, ens in self.longest_match(block):
                if ens:
                    out_parts.extend(ens[:1] if first_only else ens)
                    report['matched'] += 1
                    continue
                frag = zh.strip()
                if not frag:
                    continue
                if not has_cjk(frag):
                    out_parts.append(frag)          # 本来就是英文/数字/符号，原样保留
                    continue
                en = fallback(frag) if fallback else None
                if en:
                    out_parts.append(en)
                    report['translated'] += 1
                elif keep_unknown:
                    out_parts.append(frag)
                    report['kept'] += 1
                    report['unknown'].append(frag)
                else:
                    report['unknown'].append(frag)
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
            result = ', '.join(cleaned)
        report['result'] = result
        return result, report


_DEFAULT: Optional[TagDictionary] = None


def default_data_dirs() -> List[str]:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 插件根目录
    return [os.path.join(here, 'data'), os.path.join(here, 'data', 'user')]


def get_dictionary(reload: bool = False) -> TagDictionary:
    global _DEFAULT
    if _DEFAULT is None or reload:
        _DEFAULT = TagDictionary(default_data_dirs()).load_all()
        print(f'[ZHTag] 词典就绪：{_DEFAULT.size} 条中文词条 '
              f'（来源：{", ".join(_DEFAULT.sources) or "无"}，过滤 {_DEFAULT.dropped} 行）')
    return _DEFAULT
