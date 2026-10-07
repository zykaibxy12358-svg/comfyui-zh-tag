# -*- coding: utf-8 -*-
"""词典未命中时的兜底翻译。

优先级（可在 data/user/config.json 里改）：
  1. 缓存（data/user/cache.json）—— 同一个词只翻一次
  2. LLM：任何 OpenAI 兼容接口（Ollama / LM Studio / DeepSeek / 本地 vLLM…）
  3. 在线翻译接口（默认关闭：translate.googleapis.com 免 key 端点，可能不稳定）
  4. 保留原文（默认兜底，绝不丢信息）

只用标准库（urllib），不引入额外依赖。
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.parse
import urllib.request
from typing import Dict, Optional

DEFAULT_CONFIG = {
    'fallback': 'keep',          # keep | llm | google
    'base_url': 'http://127.0.0.1:11434/v1',   # OpenAI 兼容地址（Ollama 默认）
    'api_key': '',
    'model': 'qwen2.5:7b',
    'timeout': 20,
    'system_prompt': (
        '你是 Stable Diffusion 提示词翻译器。把用户给出的中文短语翻译成最合适的英文 tag：'
        '只用小写英文单词，用下划线连接词组内的词，不要解释，不要标点，不要引号。'
        '若它已经是英文则原样返回。'
    ),
}

LLM_CACHE_LIMIT = 4000


class FallbackTranslator:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.config_path = os.path.join(data_dir, 'config.json')
        self.cache_path = os.path.join(data_dir, 'cache.json')
        self.config: Dict = dict(DEFAULT_CONFIG)
        self.cache: Dict[str, str] = {}
        self._neg: Dict[str, float] = {}          # 失败过的词，短时间内不再重试
        self._lock = threading.Lock()
        self._dirty = False
        os.makedirs(data_dir, exist_ok=True)
        self._load()

    # ------------------------------------------------------------------ 配置
    def _load(self) -> None:
        if os.path.isfile(self.config_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    self.config.update(json.load(f) or {})
            except Exception as e:
                print(f'[ZHTag] 配置读取失败：{e}')
        else:
            try:
                with open(self.config_path, 'w', encoding='utf-8') as f:
                    json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
        if os.path.isfile(self.cache_path):
            try:
                with open(self.cache_path, 'r', encoding='utf-8') as f:
                    self.cache = json.load(f) or {}
            except Exception:
                self.cache = {}

    def save_cache(self) -> None:
        if not self._dirty:
            return
        try:
            with self._lock:
                if len(self.cache) > LLM_CACHE_LIMIT:
                    for k in list(self.cache.keys())[:len(self.cache) - LLM_CACHE_LIMIT]:
                        self.cache.pop(k, None)
                with open(self.cache_path, 'w', encoding='utf-8') as f:
                    json.dump(self.cache, f, ensure_ascii=False)
                self._dirty = False
        except Exception as e:
            print(f'[ZHTag] 缓存写入失败：{e}')

    # ------------------------------------------------------------------ 翻译
    def __call__(self, fragment: str) -> Optional[str]:
        frag = (fragment or '').strip()
        if not frag:
            return None
        hit = self.cache.get(frag)
        if hit:
            return hit
        if self._neg.get(frag, 0) > time.time():
            return None
        mode = (self.config.get('fallback') or 'keep').lower()
        result = None
        if mode == 'llm':
            result = self._via_llm(frag)
        elif mode == 'google':
            result = self._via_google(frag)
        if result and result.strip():
            result = result.strip().strip('.,"\'')
            self.cache[frag] = result
            self._dirty = True
            return result
        self._neg[frag] = time.time() + 120            # 2 分钟内不再重试
        return None

    def _via_llm(self, frag: str) -> Optional[str]:
        base = (self.config.get('base_url') or '').rstrip('/')
        model = self.config.get('model') or ''
        if not base or not model:
            return None
        payload = {
            'model': model,
            'messages': [
                {'role': 'system', 'content': self.config.get('system_prompt', DEFAULT_CONFIG['system_prompt'])},
                {'role': 'user', 'content': frag},
            ],
            'temperature': 0.1,
            'max_tokens': 48,
            'stream': False,
        }
        req = urllib.request.Request(
            base + '/chat/completions',
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json',
                     **({'Authorization': 'Bearer ' + self.config['api_key']} if self.config.get('api_key') else {})},
            method='POST',
        )
        try:
            with urllib.request.urlopen(req, timeout=float(self.config.get('timeout', 20))) as resp:
                data = json.loads(resp.read().decode('utf-8', 'replace'))
            text = (data.get('choices') or [{}])[0].get('message', {}).get('content', '')
            return text.strip().splitlines()[0] if text.strip() else None
        except Exception as e:
            print(f'[ZHTag] LLM 兜底翻译失败（{frag}）：{e}')
            return None

    def _via_google(self, frag: str) -> Optional[str]:
        url = ('https://translate.googleapis.com/translate_a/single?client=gtx&sl=zh-CN&tl=en&dt=t&q='
               + urllib.parse.quote(frag))
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=float(self.config.get('timeout', 20))) as resp:
                data = json.loads(resp.read().decode('utf-8', 'replace'))
            parts = data[0] if data and isinstance(data[0], list) else []
            text = ''.join(p[0] for p in parts if p and p[0])
            return text.strip() or None
        except Exception as e:
            print(f'[ZHTag] 在线翻译失败（{frag}）：{e}')
            return None

    def stats(self) -> Dict:
        return {'fallback': self.config.get('fallback'), 'cached': len(self.cache),
                'model': self.config.get('model') if self.config.get('fallback') == 'llm' else None}
