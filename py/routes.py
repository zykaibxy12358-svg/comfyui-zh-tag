# -*- coding: utf-8 -*-
"""给前端用的 HTTP 接口：文本框里输入中文时，前端调用它拿英文 tag。

路由：
  POST /zhtag/translate   {text, mode, fallback}  → {english, unknown, info}
  GET  /zhtag/status                              → 词库信息
  POST /zhtag/reload                              → 重新加载词典
失败不影响 ComfyUI 启动（拿不到 server 就直接跳过）。
"""
from __future__ import annotations

from .dictionary import get_dictionary
from .nodes import do_translate, translator
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

    print('[ZHTag] HTTP 接口已注册：/zhtag/translate, /zhtag/status, /zhtag/reload, /zhtag/dict/download, /zhtag/dict/sources')
    return True
