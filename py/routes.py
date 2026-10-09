# -*- coding: utf-8 -*-
"""给前端用的 HTTP 接口：文本框里输入中文时，前端调用它拿英文 tag。

路由：
  POST /zhtag/translate   {text, mode, fallback}  → {english, unknown, info}
  GET  /zhtag/complete    ?q=&limit=              → 拼音/中文/英文 补全候选
  GET  /zhtag/status                              → 词库信息
  POST /zhtag/reload                              → 重新加载词典
失败不影响 ComfyUI 启动（拿不到 server 就直接跳过）。
"""
from __future__ import annotations

from .dictionary import get_dictionary
from .nodes import do_translate, translator
from .complete import get_completer
from . import sources as community


def register_routes() -> bool:
    try:
        from aiohttp import web
        from server import PromptServer
    except Exception as e:
        print(f'[ZHTag] 未注册 HTTP 接口（{e}）')
        return False

    routes = PromptServer.instance.routes

    @routes.post('/zhtag/translate')
    async def zhtag_translate(request):
        try:
            data = await request.json()
        except Exception:
            data = {}
        text = str(data.get('text') or '')
        mode = 'raw' if str(data.get('mode') or '').startswith('raw') else 'tags'
        use_fb = bool(data.get('fallback'))
        first_only = data.get('firstOnly')
        first_only = True if first_only is None else bool(first_only)
        unknown_mode = str(data.get('unknownMode') or 'drop').lower()
        if unknown_mode not in ('drop', 'keep', 'fallback'):
            unknown_mode = 'drop'
        normalize = data.get('normalize')
        normalize = True if normalize is None else bool(normalize)
        english, report = do_translate(text, mode=mode, dedupe=True,
                                       keep_unknown=(unknown_mode == 'keep'),
                                       use_fallback=use_fb, first_only=first_only,
                                       unknown_mode=unknown_mode, normalize=normalize,
                                       underscore=bool(data.get('underscore')))
        return web.json_response({
            'ok': True,
            'english': english,
            'unknown': report.get('unknown') or [],
            'matched': report.get('matched', 0),
            'translated': report.get('translated', 0),
            'dropped': report.get('dropped', 0),
            'function': report.get('function', 0),
            'entries': report.get('entries', 0),
            'index': report.get('index', 0),
            'info': ('命中 %d / 兜底 %d / 丢弃 %d / 功能词 %d / 词库 %d+%d'
                     % (report.get('matched', 0), report.get('translated', 0),
                        report.get('dropped', 0), report.get('function', 0),
                        report.get('entries', 0), report.get('index', 0))),
        })

    @routes.get('/zhtag/complete')
    async def zhtag_complete(request):
        """IDE 式补全：输入 'lanfa' / 'smw' / '蓝发' → 直接给英文 tag 候选。"""
        q = request.query.get('q') or ''
        try:
            limit = int(request.query.get('limit') or 10)
        except Exception:
            limit = 10
        limit = max(1, min(30, limit))
        results = get_completer().complete(q, limit=limit)
        return web.json_response({'ok': True, 'q': q, 'results': results})

    @routes.get('/zhtag/online')
    async def zhtag_online_get(request):
        """当前翻译方式（词典/谷歌/微软/百度/有道/LLM）+ 各家最近一次连通状态。"""
        tr = translator()
        if request.query.get('test'):
            tr.test(request.query.get('test'))
        return web.json_response({'ok': True, **tr.state()})

    @routes.post('/zhtag/online')
    async def zhtag_online_set(request):
        """切换翻译方式：{mode: off|google|microsoft|baidu|youdao|llm, test?: bool}"""
        try:
            data = await request.json()
        except Exception:
            data = {}
        tr = translator()
        mode = tr.set_mode(data.get('mode') or '')
        out = {'ok': True, **tr.state()}
        if data.get('test') and mode not in ('off', 'llm'):
            out['result'] = tr.test(mode)
            out.update(tr.state())
        return web.json_response(out)

    @routes.get('/zhtag/config')
    async def zhtag_config_get(request):
        """翻译相关的配置（key 只回「填没填」，不回明文）。"""
        tr = translator()
        cfg = tr.config
        def filled(name):
            return bool(str(cfg.get(name) or '').strip())
        return web.json_response({
            'ok': True,
            'config_path': tr.config_path,
            'online': tr.state(),
            'llm': {'base_url': cfg.get('base_url'), 'model': cfg.get('model'), 'has_key': filled('api_key')},
            'baidu': {'has_appid': filled('baidu_appid'), 'has_key': filled('baidu_key')},
            'youdao': {'has_appid': filled('youdao_appid'), 'has_key': filled('youdao_key')},
            'timeout': cfg.get('timeout'),
            'exec_timeout': cfg.get('exec_timeout'),
        })

    @routes.get('/zhtag/status')
    async def zhtag_status(request):
        dic = get_dictionary()
        return web.json_response({
            'ok': True,
            'entries': dic.size,
            'index': dic.index_tags,
            'sources': dic.sources,
            'dropped': dic.dropped,
            'translator': translator().stats(),
            'community': community.list_sources(),
        })

    @routes.post('/zhtag/reload')
    async def zhtag_reload(request):
        dic = get_dictionary(reload=True)
        get_completer(reload=True)              # 补全索引跟着重建（用户加了自定义词典后要生效）
        return web.json_response({'ok': True, 'entries': dic.size,
                                  'index': dic.index_tags, 'sources': dic.sources})

    @routes.post('/zhtag/dict/download')
    async def zhtag_dict_download(request):
        """下载/更新社区词典（大表不随插件分发，由用户机器从上游拉取）。"""
        try:
            data = await request.json()
        except Exception:
            data = {}
        ids = data.get('ids')
        if isinstance(ids, str):
            ids = [ids]
        only_default = bool(data.get('defaultOnly'))
        result = community.download(source_ids=ids, only_default=only_default)
        if result.get('ok'):
            dic = get_dictionary(reload=True)
            result['entries'] = dic.size
            result['index'] = dic.index_tags
        return web.json_response(result)

    @routes.get('/zhtag/dict/sources')
    async def zhtag_dict_sources(request):
        return web.json_response({'ok': True, 'sources': community.list_sources()})

    print('[ZHTag] HTTP 接口已注册：/zhtag/translate, /zhtag/complete, /zhtag/online, /zhtag/status, '
          '/zhtag/reload, /zhtag/dict/download, /zhtag/dict/sources')
    return True
