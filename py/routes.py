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
        english, report = do_translate(text, mode=mode, dedupe=True,
                                       keep_unknown=True, use_fallback=use_fb,
                                       first_only=first_only)
        return web.json_response({
            'ok': True,
            'english': english,
            'unknown': report.get('unknown') or [],
            'matched': report.get('matched', 0),
            'translated': report.get('translated', 0),
            'entries': report.get('entries', 0),
            'info': f"命中 {report.get('matched', 0)} / 兜底 {report.get('translated', 0)} / 词库 {report.get('entries', 0)}",
        })

    @routes.get('/zhtag/status')
    async def zhtag_status(request):
        dic = get_dictionary()
        return web.json_response({
            'ok': True,
            'entries': dic.size,
            'sources': dic.sources,
            'dropped': dic.dropped,
            'translator': translator().stats(),
        })

    @routes.post('/zhtag/reload')
    async def zhtag_reload(request):
        dic = get_dictionary(reload=True)
        return web.json_response({'ok': True, 'entries': dic.size, 'sources': dic.sources})

    print('[ZHTag] HTTP 接口已注册：/zhtag/translate, /zhtag/status, /zhtag/reload')
    return True
