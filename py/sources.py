# -*- coding: utf-8 -*-
"""社区词典下载器。

为什么不直接把大词典打包进来：那几份大表（尤其 BooruTagCart 的 5 万条中文）是 **GPL-3.0**，
而本插件是 MIT，直接打包会把许可混在一起。所以改成**你自己的机器运行时从上游拉取**，
存到 data/user/ 下（属于你的本地数据，不随插件分发），并附上来源与许可说明。

内置的 data/zh_tags.csv（prompt-all-in-one 派生，MIT）与 data/zh_extra.csv（本插件补充）
已经够日常使用；下载只是为了覆盖到 5 万条的那个量级。
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import urllib.request
from typing import Dict, List, Optional

SOURCES: List[Dict] = [
    {
        'id': 'boorucart_zh',
        'name': 'BooruTagCart 中文对照表（约 5 万条中文，推荐）',
        'url': 'https://cdn.jsdelivr.net/gh/xhoxye/BooruTagCart@main/assets/danbooru_%E7%BF%BB%E8%AF%91%E5%8F%82%E8%80%83%E6%96%87%E6%A1%A3.csv',
        'save': 'community_boorucart_zh.csv',
        'license': 'GPL-3.0',
        'note': '格式：tag,中文|同义词,分类',
        'default': True,
    },
    {
        'id': 'pai_zh_yaml',
        'name': 'prompt-all-in-one 中文分组表（约 3.6 千条）',
        'url': 'https://cdn.jsdelivr.net/gh/Physton/sd-webui-prompt-all-in-one@main/group_tags/zh_CN.yaml',
        'save': 'community_pai_zh.yaml',
        'license': 'MIT',
        'note': '本插件内置的那份就是它的派生，下载可拿到最新版',
        'default': True,
    },
    {
        'id': 'db_zh_characters',
        'name': 'Danbooru 角色中文名（约 4 万角色，含作品名）',
        'url': 'https://cdn.jsdelivr.net/gh/SANLVZHETANG/danbooru-tag-list-zh@main/%E7%BF%BB%E8%AF%91/%E8%A7%92%E8%89%B2%E6%A0%87%E7%AD%BE.csv',
        'save': 'community_characters_zh.csv',
        'license': '仓库未声明许可',
        'note': '格式：tag,分类,热度,"别名,中文名-作品"',
        'transform': 'characters',
    },
    {
        'id': 'tagcomplete_danbooru',
        'name': 'Danbooru 英文标签表（重建规范化/热度索引）',
        'url': 'https://cdn.jsdelivr.net/gh/DominikDoom/a1111-sd-webui-tagcomplete@main/tags/danbooru.csv',
        'save': 'danbooru_raw.csv',
        'license': 'MIT',
        'note': '下载后会在 data/ 重建 danbooru_index.tsv',
        'transform': 'danbooru_index',
    },
]

CJK = re.compile(r'[\u3400-\u9fff]')


def list_sources() -> List[Dict]:
    out = []
    for s in SOURCES:
        item = dict(s)
        item['downloaded'] = False
        item['size'] = 0
        for d in ('data/user', 'data'):
            p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), d, s['save'])
            if os.path.isfile(p):
                item['downloaded'] = True
                item['size'] = os.path.getsize(p)
                break
        out.append(item)
    return out


def _plugin_dir() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _fetch(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={'User-Agent': 'ZHTag/1.1 (+comfyui)'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _transform_characters(raw_path: str, out_path: str) -> int:
    """tag,cat,count,"别名,中文名-作品" → 中文名,tag"""
    n = 0
    with open(raw_path, 'r', encoding='utf-8-sig', errors='replace') as fi, \
            open(out_path, 'w', encoding='utf-8', newline='\n') as fo:
        fo.write('# 由 danbooru-tag-list-zh 的角色标签表转换：中文名,tag\n')
        for line in fi:
            line = line.rstrip('\n')
            if not line:
                continue
            parts = line.split(',', 3)
            if len(parts) < 4:
                continue
            tag = parts[0].strip().strip('"')
            local = parts[3].strip().strip('"')
            if not tag or not local:
                continue
            for piece in re.split(r'[,|]', local):
                piece = piece.strip()
                if not piece or not CJK.search(piece):
                    continue
                zh = piece.split('-')[0].strip()      # 中文名-作品 → 中文名
                if zh and CJK.search(zh) and len(zh) <= 30:
                    fo.write('%s,%s\n' % (zh, tag))
                    n += 1
    return n


def _transform_danbooru_index(raw_path: str, out_path: str) -> int:
    """重建 danbooru_index.tsv（只留 category 0/5）。"""
    rows = []
    with open(raw_path, 'r', encoding='utf-8-sig', errors='replace') as f:
        for line in f:
            line = line.rstrip('\n')
            if not line:
                continue
            parts = line.split(',', 3)
            if len(parts) < 3:
                continue
            tag, cat, cnt = parts[0].strip(), parts[1].strip(), parts[2].strip()
            if cat not in ('0', '5') or not tag:
                continue
            try:
                count = int(cnt)
            except ValueError:
                count = 0
            aliases = [a.strip() for a in (parts[3].strip().strip('"') if len(parts) > 3 else '').split(',')
                       if a.strip() and not a.strip().startswith('/')]
            rows.append((tag, count, aliases))
    rows.sort(key=lambda r: -r[1])
    with open(out_path, 'w', encoding='utf-8', newline='\n') as fo:
        fo.write('# canonical<TAB>count<TAB>aliases —— 由 a1111-sd-webui-tagcomplete 的 danbooru.csv（MIT）派生\n')
        for tag, count, aliases in rows:
            fo.write('%s\t%d\t%s\n' % (tag, count, '|'.join(aliases)))
    return len(rows)


def download(source_ids: Optional[List[str]] = None, only_default: bool = False) -> Dict:
    """下载指定（或默认一组）词典。返回 {ok, results:[{id, ok, message, entries, bytes}]}"""
    base = _plugin_dir()
    user_dir = os.path.join(base, 'data', 'user')
    os.makedirs(user_dir, exist_ok=True)
    picked = []
    for s in SOURCES:
        if source_ids:
            if s['id'] in source_ids:
                picked.append(s)
        elif only_default and s.get('default'):
            picked.append(s)
        elif not only_default and not source_ids:
            picked.append(s)
    results = []
    for s in picked:
        entry = {'id': s['id'], 'name': s['name'], 'ok': False, 'message': ''}
        try:
            data = _fetch(s['url'])
            entry['bytes'] = len(data)
            with tempfile.TemporaryDirectory() as tmp:
                raw = os.path.join(tmp, 'raw')
                with open(raw, 'wb') as f:
                    f.write(data)
                if s.get('transform') == 'danbooru_index':
                    target = os.path.join(base, 'data', 'danbooru_index.tsv')
                    entry['entries'] = _transform_danbooru_index(raw, target)
                    entry['message'] = '已重建 Danbooru 索引：%d 条' % entry['entries']
                    entry['ok'] = True
                elif s.get('transform') == 'characters':
                    target = os.path.join(user_dir, s['save'])
                    entry['entries'] = _transform_characters(raw, target)
                    entry['message'] = '已转换 %d 条中文角色名' % entry['entries']
                    entry['ok'] = True
                else:
                    target = os.path.join(user_dir, s['save'])
                    with open(raw, 'rb') as fi, open(target, 'wb') as fo:
                        fo.write(fi.read())
                    entry['message'] = '已保存 %s（%.1f MB）' % (s['save'], len(data) / 1048576)
                    entry['ok'] = True
            entry['license'] = s.get('license', '')
        except Exception as e:
            entry['message'] = '下载失败：%s' % e
        results.append(entry)
    return {'ok': any(r['ok'] for r in results), 'results': results}


def readme_text() -> str:
    lines = ['# 社区词典来源（点面板的「下载/更新社区词典」即可自动获取）', '']
    for s in SOURCES:
        lines.append('- **%s**' % s['name'])
        lines.append('  - 许可：%s' % s.get('license', '未知'))
        lines.append('  - 说明：%s' % s.get('note', ''))
        lines.append('  - 地址：%s' % s['url'].split('@')[0])
    return '\n'.join(lines) + '\n'
