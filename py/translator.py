# -*- coding: utf-8 -*-
"""词典未命中时的兜底翻译。

优先级（可在 data/user/config.json 里改，也可以在补全弹层里点一下切）：
  1. 缓存（data/user/cache.json）—— 同一个词只翻一次
  2. LLM：任何 OpenAI 兼容接口（Ollama / LM Studio / DeepSeek / 本地 vLLM…）
  3. 在线翻译：google / microsoft（免 key）、baidu / youdao（需要自己填 appid+key）
  4. off：只用词典，完全不联网

两个和「跑图不干等」有关的机制：
  · exec_timeout：节点执行时的网络超时（默认 6 秒，比打字时的 20 秒短得多）
  · interrupt_check：ComfyUI 的「中断」回调；你一按中断，翻译立刻放弃并抛中断异常，不再等网络
只用标准库（urllib / hashlib），不引入额外依赖。
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import threading
import time
import urllib.parse
import urllib.request
from typing import Callable, Dict, Optional

# 在线翻译的服务商（前端「词典 / 谷歌 / 微软 / 百度 / 有道」切的就是它）
PROVIDERS = ('google', 'microsoft', 'baidu', 'youdao')
OFF_MODE = 'off'
OFF_ALIASES = ('off', 'keep', 'none', 'dictionary')      # keep 是旧名字，保留兼容
NEEDS_KEYS = {'baidu': ('baidu_appid', 'baidu_key'), 'youdao': ('youdao_appid', 'youdao_key')}
MODE_DESC = {
    'off': '只用词典（不联网）',
    'google': '谷歌在线翻译',
    'microsoft': '微软在线翻译',
    'baidu': '百度在线翻译',
    'youdao': '有道在线翻译',
    'llm': '本地/远程 LLM',
}

DEFAULT_CONFIG = {
    'fallback': 'google',        # off | google | microsoft | baidu | youdao | llm
    'base_url': 'http://127.0.0.1:11434/v1',   # OpenAI 兼容地址（Ollama 默认）
    'api_key': '',
    'model': 'qwen2.5:7b',
    'timeout': 20,               # 打字/补全时用的超时
    'exec_timeout': 6,           # 跑图执行节点时的超时（短一点，别让跑图干等）
    'baidu_appid': '',           # 百度翻译开放平台 https://fanyi-api.baidu.com
    'baidu_key': '',
    'youdao_appid': '',          # 有道智云 https://ai.youdao.com
    'youdao_key': '',
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
BAIDU_API = 'https://fanyi-api.baidu.com/api/trans/vip/translate'
YOUDAO_API = 'https://openapi.youdao.com/api'


def baidu_sign(appid: str, query: str, salt: str, key: str) -> str:
    """百度翻译签名：md5(appid + q + salt + key)。拎出来是为了能单测。"""
    return hashlib.md5(f'{appid}{query}{salt}{key}'.encode('utf-8')).hexdigest()


def youdao_sign(appid: str, query: str, salt: str, curtime: str, key: str) -> str:
    """有道 v3 签名：sha256(appKey + truncate(q) + salt + curtime + appSecret)。

    truncate(q)：长度 ≤20 原样；否则 前10 + 长度 + 后10。
    """
    trunc = query if len(query) <= 20 else query[:10] + str(len(query)) + query[-10:]
    return hashlib.sha256(f'{appid}{trunc}{salt}{curtime}{key}'.encode('utf-8')).hexdigest()


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
        self.in_execution = False                 # 跑图执行中 → 用短超时
        self.interrupt_check: Optional[Callable[[], None]] = None   # ComfyUI 的中断回调
        self._exec_failed = False                 # 本次执行里已经失败过 → 后面就别再等了
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
        m = str(self.config.get('fallback') or OFF_MODE).lower()
        if m in OFF_ALIASES:
            return OFF_MODE
        return m if m in ('llm',) + PROVIDERS else OFF_MODE

    def configured(self, provider: str) -> bool:
        """这个服务商现在能用吗（百度/有道要先在 config.json 里填 appid + key）。"""
        p = str(provider or '').lower()
        if p in ('google', 'microsoft'):
            return True
        for field in NEEDS_KEYS.get(p, ()):
            if not str(self.config.get(field) or '').strip():
                return False
        return p in NEEDS_KEYS

    def set_mode(self, mode: str, save: bool = True) -> str:
        """切换翻译方式（off / google / microsoft / baidu / youdao / llm），并写回 config.json。"""
        m = str(mode or '').lower()
        if m in OFF_ALIASES:
            m = OFF_MODE
        elif m not in ('llm',) + PROVIDERS:
            return self.mode()
        self.config['fallback'] = m
        self._neg.clear()                          # 换了翻译方式，之前失败过的词要重新试
        if m != 'microsoft':
            self._ms_token = ''                    # 换走了就把 token 丢掉
        if save:
            try:
                with open(self.config_path, 'w', encoding='utf-8') as f:
                    json.dump(self.config, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f'[ZHTag] 配置写入失败：{e}')
        print(f'[ZHTag] 翻译方式已切换为：{MODE_DESC.get(m, m)}')
        return m

    def state(self) -> Dict:
        cur = self.mode()
        return {
            'mode': cur,
            'mode_desc': MODE_DESC.get(cur, cur),
            'providers': [{'id': p, 'desc': MODE_DESC[p], 'configured': self.configured(p)}
                          for p in PROVIDERS],
            'off': {'id': OFF_MODE, 'desc': MODE_DESC[OFF_MODE]},
            'status': self.status,
            'cached': len(self.cache),
            'model': self.config.get('model') if self.mode() == 'llm' else None,
        }

    def _mark(self, provider: str, ok: bool, msg: str = '') -> None:
        self.status[provider] = {'ok': bool(ok), 'at': time.time(), 'msg': (msg or '')[:200]}

    # ------------------------------------------------------------------ 中断 / 超时
    def begin_execution(self) -> None:
        """一次节点执行开始：清掉「本轮已失败」标记（跑图最多只等一次超时）。"""
        self.in_execution = True
        self._exec_failed = False

    def _timeout(self) -> float:
        """跑图执行时用短超时，打字/补全时用长超时。"""
        if self.in_execution:
            return float(self.config.get('exec_timeout', 6) or 6)
        return float(self.config.get('timeout', 20) or 20)

    def _check_interrupt(self) -> None:
        """ComfyUI 的中断回调：按了「中断」就立刻放弃翻译，不再干等网络。"""
        cb = self.interrupt_check
        if cb is None:
            return
        try:
            cb()                       # 命中中断时会抛 comfy 的 InterruptProcessingException
        except Exception as e:
            if type(e).__name__ in ('InterruptProcessingException', 'ProcessingInterrupted'):
                raise
            # 其它异常（比如中断功能没启用）就不要影响正常翻译

    def _call(self, provider: str, fn: Callable[[str], Optional[str]], frag: str) -> Optional[str]:
        if not self.configured(provider):
            self._mark(provider, False, '还没有填 appid / key（见 data/user/config.json）')
            return None
        if self.in_execution and self._exec_failed:
            return None                    # 本轮执行已经失败过一次：不再让跑图干等第二次
        self._check_interrupt()
        out = fn(frag)
        if self.in_execution and not out:
            self._exec_failed = True
        return out

    def test(self, provider: Optional[str] = None) -> Dict:
        """真发一次翻译请求，看看这个服务商现在通不通（前端按钮上的状态灯用）。

        测试路径把超时压到 8 秒——按钮点下去不该等 20 秒才有反馈。
        """
        p = (provider or self.mode()).lower()
        if p not in PROVIDERS:
            return {'ok': False, 'provider': p, 'message': '只有在线服务商能测'}
        if not self.configured(p):
            need = ' / '.join(NEEDS_KEYS.get(p, ()))
            msg = f'{MODE_DESC[p]}还没配置（需要填 {need}）'
            self._mark(p, False, msg)
            return {'ok': False, 'provider': p, 'message': msg, 'status': self.status}
        sample = '蓝色裙子'
        fn = {'google': self._via_google, 'microsoft': self._via_microsoft,
              'baidu': self._via_baidu, 'youdao': self._via_youdao}[p]
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
        if mode == OFF_MODE:
            return None                                # 只用词典模式：一个字都不联网
        result = None
        if mode == 'llm':
            result = self._via_llm(frag)
        elif mode in PROVIDERS:
            fn = {'google': self._via_google, 'microsoft': self._via_microsoft,
                  'baidu': self._via_baidu, 'youdao': self._via_youdao}[mode]
            result = self._call(mode, fn, frag)
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
            with urllib.request.urlopen(req, timeout=self._timeout()) as resp:
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
            with urllib.request.urlopen(req, timeout=self._timeout()) as resp:
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
            with urllib.request.urlopen(req, timeout=self._timeout()) as resp:
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
            with urllib.request.urlopen(req, timeout=self._timeout()) as resp:
                data = json.loads(resp.read().decode('utf-8', 'replace'))
            text = ((data or [{}])[0].get('translations') or [{}])[0].get('text', '').strip()
            self._mark('microsoft', bool(text), '' if text else '返回为空')
            return text or None
        except Exception as e:
            self._ms_token = ''                    # token 可能过期了，下次重取
            self._mark('microsoft', False, str(e))
            print(f'[ZHTag] 微软在线翻译失败（{frag}）：{e}')
            return None

    # ---------------------------------------------------------------- 百度
    def _via_baidu(self, frag: str) -> Optional[str]:
        """百度翻译开放平台（通用文本翻译）。需要 config.json 里的 baidu_appid / baidu_key。"""
        appid = str(self.config.get('baidu_appid') or '').strip()
        key = str(self.config.get('baidu_key') or '').strip()
        salt = str(random.randint(100000, 999999))
        params = {
            'q': frag, 'from': 'zh', 'to': 'en', 'appid': appid, 'salt': salt,
            'sign': baidu_sign(appid, frag, salt, key),
        }
        body = urllib.parse.urlencode(params).encode('utf-8')
        req = urllib.request.Request(
            BAIDU_API, data=body, method='POST',
            headers={'Content-Type': 'application/x-www-form-urlencoded',
                     'User-Agent': 'Mozilla/5.0'})
        try:
            with urllib.request.urlopen(req, timeout=self._timeout()) as resp:
                data = json.loads(resp.read().decode('utf-8', 'replace'))
            if data.get('error_code'):
                msg = f"{data.get('error_code')} {data.get('error_msg', '')}".strip()
                self._mark('baidu', False, msg)
                print(f'[ZHTag] 百度翻译失败（{frag}）：{msg}')
                return None
            text = ''.join(item.get('dst', '') for item in (data.get('trans_result') or [])).strip()
            self._mark('baidu', bool(text), '' if text else '返回为空')
            return text or None
        except Exception as e:
            self._mark('baidu', False, str(e))
            print(f'[ZHTag] 百度在线翻译失败（{frag}）：{e}')
            return None

    # ---------------------------------------------------------------- 有道
    def _via_youdao(self, frag: str) -> Optional[str]:
        """有道智云文本翻译 v3。需要 config.json 里的 youdao_appid / youdao_key。"""
        appid = str(self.config.get('youdao_appid') or '').strip()
        key = str(self.config.get('youdao_key') or '').strip()
        salt = str(random.randint(100000, 999999))
        curtime = str(int(time.time()))
        params = {
            'q': frag, 'from': 'zh-CHS', 'to': 'en', 'appKey': appid, 'salt': salt,
            'sign': youdao_sign(appid, frag, salt, curtime, key),
            'signType': 'v3', 'curtime': curtime,
        }
        body = urllib.parse.urlencode(params).encode('utf-8')
        req = urllib.request.Request(
            YOUDAO_API, data=body, method='POST',
            headers={'Content-Type': 'application/x-www-form-urlencoded',
                     'User-Agent': 'Mozilla/5.0'})
        try:
            with urllib.request.urlopen(req, timeout=self._timeout()) as resp:
                data = json.loads(resp.read().decode('utf-8', 'replace'))
            if str(data.get('errorCode', '0')) != '0':
                msg = f"{data.get('errorCode')} {data.get('errorMsg') or data.get('msg') or ''}".strip()
                self._mark('youdao', False, msg)
                print(f'[ZHTag] 有道翻译失败（{frag}）：{msg}')
                return None
            text = ''.join(data.get('translation') or []).strip()
            self._mark('youdao', bool(text), '' if text else '返回为空')
            return text or None
        except Exception as e:
            self._mark('youdao', False, str(e))
            print(f'[ZHTag] 有道在线翻译失败（{frag}）：{e}')
            return None

    def stats(self) -> Dict:
        return {'fallback': self.mode(), 'cached': len(self.cache),
                'model': self.config.get('model') if self.mode() == 'llm' else None}
