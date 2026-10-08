# -*- coding: utf-8 -*-
"""构建 data/pinyin_chars.tsv —— 汉字 → 拼音表（IDE 式补全要用它做拼音匹配）。

为什么是构建期脚本而不是运行时依赖：
    插件本体必须「零第三方依赖」（用户装插件时不该被迫 pip install），
    所以用 pypinyin 在本机把表算好、以数据文件形式随插件分发；
    运行时只查表拼拼音（纯 dict 查询，几万次/毫秒级）。

用法（本机）：
    python -m pip install pypinyin -t <临时目录>
    python _build/build_pinyin_table.py <临时目录> [输出文件]

输出格式（TSV，每行一个字）：
    字<TAB>pinyin1,pinyin2,...      # 多音字按常用度排序，最多 3 个
"""
import os
import sys

MAX_READINGS = 3


def main():
    lib = sys.argv[1] if len(sys.argv) > 1 else None
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'pinyin_chars.tsv')
    if lib:
        sys.path.insert(0, lib)
    from pypinyin import pinyin, Style  # noqa: E402

    rows = []
    for cp in range(0x3400, 0xA000):            # CJK 基本区 + 扩展A（常用汉字全覆盖）
        ch = chr(cp)
        try:
            readings = pinyin(ch, style=Style.NORMAL, heteronym=True, errors=lambda x: [None])[0]
        except Exception:
            continue
        if not readings:
            continue
        cleaned, seen = [], set()
        for r in readings:
            if not r or r in seen:
                continue
            seen.add(r)
            cleaned.append(r)
            if len(cleaned) >= MAX_READINGS:
                break
        if cleaned:
            rows.append((ch, ','.join(cleaned)))

    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'w', encoding='utf-8', newline='\n') as f:
        f.write('# 汉字<TAB>拼音(多音字用逗号分隔) —— 由 pypinyin 生成，供拼音补全用（本插件零运行时依赖）\n')
        for ch, py in rows:
            f.write('%s\t%s\n' % (ch, py))
    size = os.path.getsize(out)
    print('写入 %s：%d 个字，%.1f KB' % (out, len(rows), size / 1024))


if __name__ == '__main__':
    main()
