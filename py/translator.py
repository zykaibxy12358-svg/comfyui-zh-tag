# -*- coding: utf-8 -*-
"""词典未命中时的兜底翻译。

优先级（可在 data/user/config.json 里改，也可以在补全弹层里点按钮切）：
  1. 缓存（data/user/cache.json）—— 同一个词只翻一次
  2. LLM：任何 OpenAI 兼容接口（Ollama / LM Studio / DeepSeek / 本地 vLLM…）
  3. 在线翻译（免 key）：google（translate.googleapis.com）/ microsoft（Edge 翻译接口）
  4. keep：保留原文（不翻译）

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

# 在线翻译的两个可选服务商（前端「谷歌 / 微软」按钮切的就是它）
PROVIDERS = ('google', 'microsoft')
MODE_DESC = {
    'google': '谷歌在线翻译',
    'microsoft': '微软在线翻译',
    'llm': '本地/远程 LLM',
    'keep': '不翻译（保留原文）',
}

DEFAULT_CONFIG = {
    'fallback': 'google',        # google | microsoft | llm | keep
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
MS_AUTH_URL = 'https://edge.microsoft.com/translate/auth'
MS_API_URL = ('https://api-edge.cognitive.microsofttranslator.com/translate'
              '?api-version=3.0&from=zh-Hans&to=en')
MS_TOKEN_TTL = 8 * 60           # 微软的 token 大约 10 分钟过期，保守取 8 分钟


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
        self._ms_token = ''
        self._ms_token_at = 0.0
        self.status: Dict[str, Dict] = {}         # 服务商 → {ok, at, msg}，给前端画状态灯
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

    # ------------------------------------------------------------------ 服务商切换
    def mode(self) -> str:
        m = str(self.config.get('fallback') or 'keep').lower()
        return m if m in ('keep', 'llm') + PROVIDERS else 'keep'

    def set_mode(self, mode: str, save: bool = True) -> str:
        """切换兜底翻译方式（'google' / 'microsoft' / 'llm' / 'keep'），并写回 config.json。"""
        m = str(mode or '').lower()
        if m not in ('keep', 'llm') + PROVIDERS:
            return self.mode()
        self.config['fallback'] = m
        if m != 'microsoft':
            self._ms_token = ''                    # 换走了就把 token 丢掉
        if save:
            try:
                with open(self.config_path, 'w', encoding='utf-8') as f:
                    json.dump(self.config, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f'[ZHTag] 配置写入失败：{e}')
        print(f'[ZHTag] 在线翻译方式已切换为：{MODE_DESC.get(m, m)}')
        return m

    def state(self) -> Dict:
        return {
            'mode': self.mode(),
            'mode_desc': MODE_DESC.get(self.mode(), self.mode()),
            'providers': [{'id': p, 'desc': MODE_DESC[p]} for p in PROVIDERS],
            'status': self.status,
            'cached': len(self.cache),
            'model': self.config.get('model') if self.mode() == 'llm' else None,
        }

    def _mark(self, provider: str, ok: bool, msg: str = '') -> None:
        self.status[provider] = {'ok': bool(ok), 'at': time.time(), 'msg': (msg or '')[:200]}

    def test(self, provider: Optional[str] = None) -> Dict:
        """真发一次翻译请求，看看这个服务商现在通不通（前端按钮上的状态灯用）。

        测试路径把超时压到 8 秒——按钮点下去不该等 20 秒才有反馈。
        """
        p = (provider or self.mode()).lower()
        if p not in PROVIDERS:
            return {'ok': False, 'provider': p, 'message': '只有 google / microsoft 能测'}
        sample = '蓝色裙子'
        fn = self._via_google if p == 'google' else self._via_microsoft
        self._neg.pop(sample, None)
        full_timeout = float(self.config.get('timeout', 20) or 20)
        self.config['timeout'] = min(full_timeout, 8)
        try:
            out = fn(sample)
        finally:
            self.config['timeout'] = full_timeout
        self._mark(p, bool(out), '' if out else '连接失败或没有返回结果')
        return {'ok': bool(out), 'provider': p, 'message': (out or '连不上/超时'),
                'status': self.status}

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
        mode = self.mode()
        result = None
        if mode == 'llm':
            result = self._via_llm(frag)
        elif mode == 'google':
            result = self._via_google(frag)
        elif mode == 'microsoft':
            result = self._via_microsoft(frag)
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
        url = ('https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=en&dt=t&q='
               + urllib.parse.quote(frag))
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=float(self.config.get('timeout', 20))) as resp:
                data = json.loads(resp.read().decode('utf-8', 'replace'))
            parts = data[0] if data and isinstance(data[0], list) else []
            text = ''.join(p[0] for p in parts if p and p[0])
            text = text.strip()
            self._mark('google', bool(text), '' if text else '返回为空')
            return text or None
        except Exception as e:
            self._mark('google', False, str(e))
            print(f'[ZHTag] 谷歌在线翻译失败（{frag}）：{e}')
            return None

    # ---------------------------------------------------------------- 微软
    def _ms_get_token(self) -> Optional[str]:
        """微软 Edge 翻译的免 key token（约 10 分钟有效，这里缓存 8 分钟）。"""
        now = time.time()
        if self._ms_token and now - self._ms_token_at < MS_TOKEN_TTL:
            return self._ms_token
        try:
            req = urllib.request.Request(MS_AUTH_URL, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=float(self.config.get('timeout', 20))) as resp:
                token = resp.read().decode('utf-8', 'replace').strip()
            if token:
                self._ms_token, self._ms_token_at = token, now
                return token
        except Exception as e:
            print(f'[ZHTag] 微软翻译取 token 失败：{e}')
        return None

    def _via_microsoft(self, frag: str) -> Optional[str]:
        token = self._ms_get_token()
        if not token:
            self._mark('microsoft', False, '取 token 失败（edge.microsoft.com 连不上？）')
            return None
        body = json.dumps([{'Text': frag}], ensure_ascii=False).encode('utf-8')
        req = urllib.request.Request(
            MS_API_URL, data=body, method='POST',
            headers={'Content-Type': 'application/json; charset=UTF-8',
                     'Authorization': 'Bearer ' + token,
                     'User-Agent': 'Mozilla/5.0'})
        try:
            with urllib.request.urlopen(req, timeout=float(self.config.get('timeout', 20))) as resp:
                data = json.loads(resp.read().decode('utf-8', 'replace'))
            text = ((data or [{}])[0].get('translations') or [{}])[0].get('text', '').strip()
            self._mark('microsoft', bool(text), '' if text else '返回为空')
            return text or None
        except Exception as e:
            self._ms_token = ''                    # token 可能过期了，下次重取
            self._mark('microsoft', False, str(e))
            print(f'[ZHTag] 微软在线翻译失败（{frag}）：{e}')
            return None

    def stats(self) -> Dict:
        return {'fallback': self.mode(), 'cached': len(self.cache),
                'model': self.config.get('model') if self.mode() == 'llm' else None}
