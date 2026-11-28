#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把主源里散落在央视/卫视分组内的咪咕线路，单独抽出来生成
❤️咪咕央视 / ❤️咪咕卫视 两个分组（原分组保留，不动备线）。

为什么：咪咕线路本来就混在 ❤️央视频道 / ❤️卫视频道 里（CCTV1 就有十几条），
想看“纯咪咕线路”得翻半天。这里按原分组归类，不靠猜频道名。

用法：
    python scripts/make_migu_groups.py m3u/bbxx365_hotel.m3u
    python scripts/make_migu_groups.py "m3u/*.m3u" --top 15
"""
import argparse
import glob
import os
import re
import sys

G_CCTV = "❤️咪咕央视"
G_SAT = "❤️咪咕卫视"
MIGU_GROUPS = (G_CCTV, G_SAT)

RE_URL = re.compile(r"^https?://", re.I)
RE_GROUP = re.compile(r'group-title="([^"]*)"')
RE_MIGU = re.compile(r"migu", re.I)


def parse_blocks(lines):
    """切成 (属性行列表, url)，保留 #EXTM3U 头。"""
    header, blocks, tail = [], [], []
    attrs = []
    started = False
    for line in lines:
        s = line.strip()
        if s.startswith("#EXTM3U"):
            header.append(line)
            started = True
            continue
        if RE_URL.match(s):
            if attrs:
                blocks.append((attrs, line))
            else:
                blocks.append(([], line))
            attrs = []
            started = True
        elif s.startswith("#"):
            attrs.append(line)
        elif s == "":
            continue
        else:
            tail.append(line)
    if attrs:
        tail.extend(attrs)
    return header, blocks, tail


def group_of(attrs):
    for a in attrs:
        m = RE_GROUP.search(a)
        if m:
            return m.group(1)
    return ""


def with_group(attrs, target):
    out = []
    done = False
    for a in attrs:
        if not done and RE_GROUP.search(a):
            out.append(RE_GROUP.sub('group-title="%s"' % target, a, count=1))
            done = True
        else:
            out.append(a)
    if not done:
        if out and out[0].startswith("#EXTINF"):
            out[0] = out[0].replace("#EXTINF:-1", '#EXTINF:-1 group-title="%s"' % target, 1)
        else:
            out.insert(0, '#EXTINF:-1 group-title="%s"' % target)
    return out


def process(path, top, dry_run):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    trailing = text.endswith("\n")
    lines = text.split("\n")
    if trailing and lines and lines[-1] == "":
        lines = lines[:-1]

    header, blocks, tail = parse_blocks(lines)

    migu = {G_CCTV: [], G_SAT: []}
    seen = {G_CCTV: set(), G_SAT: set()}
    kept = []

    for attrs, url in blocks:
        g = group_of(attrs)
        if g in MIGU_GROUPS:
            # 上一次生成的旧分组：不再放进 kept（避免叠加），但里面的线路要收回来
            if url not in seen[g]:
                seen[g].add(url)
                migu[g].append((attrs, url))
            continue
        kept.append((attrs, url))

    for attrs, url in blocks:
        g = group_of(attrs)
        if g in MIGU_GROUPS:
            continue
        if not RE_MIGU.search(url):
            continue
        if "央视频道" in g:
            tgt = G_CCTV
        elif "卫视频道" in g:
            tgt = G_SAT
        else:
            continue
        if url in seen[tgt]:
            continue
        seen[tgt].add(url)
        migu[tgt].append((with_group(attrs, tgt), url))

    out = list(header)
    for attrs, url in kept:
        out.extend(attrs)
        out.append(url)

    added = 0
    for tgt in MIGU_GROUPS:
        items = migu[tgt][:top] if top else migu[tgt]
        for attrs, url in items:
            out.extend(attrs)
            out.append(url)
            added += 1

    if not dry_run and added:
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(out) + ("\n" if trailing else ""))

    print(f"[migu] {os.path.basename(path)}：央视 {len(migu[G_CCTV])} 条 / 卫视 {len(migu[G_SAT])} 条，"
          f"原条目 {len(kept)} 条，最终 {len(out) - len(header)} 行条目"
          f"{'（dry-run 未写回）' if dry_run else ''}")
    return added


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("targets", nargs="+")
    ap.add_argument("--top", type=int, default=0, help="每个分组最多保留几条（0=不限）")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    files = []
    for t in args.targets:
        files.extend(sorted(glob.glob(t)))
    total = 0
    for p in files:
        if os.path.isfile(p):
            total += process(p, args.top, args.dry_run)
    print(f"[migu] 合计写入 {total} 条")


if __name__ == "__main__":
    sys.exit(main())
