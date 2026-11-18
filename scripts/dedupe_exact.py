#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
只删「完全重复」的条目：同一个频道名（#EXTINF 行一致）且同一 URL。

不做任何其他处理：同频道不同地址的备用源全部保留，顺序也不动。

用法：python scripts/dedupe_exact.py m3u/bbxx365.m3u [更多文件...]
原地改写，并打印删掉多少条。
"""

import re
import sys


def parse(lines):
    """把 m3u 切成块：每块 = [EXTINF 行, 中间附属行(#EXTVLC…），URL 行]"""
    blocks, head, cur = [], [], None
    for line in lines:
        s = line.rstrip("\n")
        if s.startswith("#EXTINF"):
            if cur:
                blocks.append(cur)
            cur = [s]
        elif cur is not None:
            cur.append(s)
            if s and not s.startswith("#"):
                blocks.append(cur)
                cur = None
        else:
            head.append(s)
    if cur:
        blocks.append(cur)
    return head, blocks


NAME_RE = re.compile(r'tvg-name="([^"]*)"')


def key_of(block):
    """完全重复 = 同一个频道名 + 同一个播放地址。
    分组标签、logo、显示名写法的差异不算不同频道，因此不参与比较。"""
    extinf = block[0]
    m = NAME_RE.search(extinf)
    name = m.group(1).strip() if m else extinf.split(",")[-1].strip()
    url = next((l.strip() for l in block if l and not l.startswith("#")), "")
    return name, url


def dedupe(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
    head, blocks = parse(lines)
    seen, out = set(), []
    dropped = 0
    for b in blocks:
        k = key_of(b)
        if k[1] and k in seen:
            dropped += 1
            continue
        seen.add(k)
        out.append(b)
    body = []
    for b in out:
        body.extend(b)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(head))
        if head:
            f.write("\n")
        f.write("\n".join(body))
        f.write("\n")
    return len(blocks), len(out), dropped


def main(argv):
    if not argv:
        print("用法：python scripts/dedupe_exact.py <m3u 文件> [...]", file=sys.stderr)
        return 2
    total_dropped = 0
    for path in argv:
        try:
            before, after, dropped = dedupe(path)
        except OSError as exc:
            print("跳过 %s（%s）" % (path, exc), file=sys.stderr)
            continue
        total_dropped += dropped
        print("%s：%d → %d 条（删掉完全重复 %d 条）" % (path, before, after, dropped))
    print("合计删掉完全重复 %d 条" % total_dropped)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
