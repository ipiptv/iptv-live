#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按“本地实测出来的死链规律”筛一遍主力，产出 bbxx365_mini_home.m3u。

规则来源：2026-11-19 在本机（河南联通家宽）逐条实测 12542 条主力源后归纳
（结构性特征零误伤，主机黑名单来自 data/home-blocklist.txt）。

结构化规则（和网络环境无关，命中即丢）：
  1. 地址路径里含 /udp/ 或 /rtp/       —— 各省专网组播，公网必死
  2. 地址以 .php 结尾（忽略查询串）      —— 动态跳转脚本，基本全失效
  3. 协议是 rtsp:// / udp:// / rtp://   —— 非公网 HLS

主机黑名单：data/home-blocklist.txt 里列出的主机，一律丢弃（这些主机在本机实测中
从来没有出现过一条能播的源）。

其余照旧：每台最多保留 KEEP_PER_CHANNEL 条，按“地址短、非组播、优先 https”排序，
文件顺序沿用主力原顺序与分组。

用法：python3 scripts/filter_home.py [主力路径] [输出路径] [--keep N]
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "m3u", "bbxx365_hotel.m3u")
DST = os.path.join(ROOT, "m3u", "bbxx365_mini_home.m3u")
BLOCKLIST = os.path.join(ROOT, "data", "home-blocklist.txt")

UDP_PATH = re.compile(r"/(udp|rtp)/", re.I)
PHP_PATH = re.compile(r"\.php(?:$|[?#])", re.I)
BAD_SCHEME = re.compile(r"^(rtsp|udp|rtp)://", re.I)
HOST_RE = re.compile(r"(?:https?|rtsp|rtp|udp)://([^/:]+)", re.I)


def load_blocklist():
    hosts = set()
    if not os.path.exists(BLOCKLIST):
        return hosts
    with open(BLOCKLIST, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            hosts.add(line.lower())
    return hosts


def host_of(url):
    m = HOST_RE.match(url)
    return m.group(1).lower() if m else ""


def drop_reason(url, blocked):
    if UDP_PATH.search(url):
        return "组播路径"
    if PHP_PATH.search(url.split("?")[0]):
        return "php脚本"
    if BAD_SCHEME.match(url):
        return "rtsp/udp协议"
    if host_of(url) in blocked:
        return "坏主机"
    return None


def parse(path):
    with open(path, encoding="utf-8", errors="ignore") as fh:
        lines = fh.read().splitlines()
    header, entries, i = "", [], 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("#EXTM3U") and not header:
            header = line
            i += 1
            continue
        if line.startswith("#EXTINF"):
            j = i + 1
            while j < len(lines) and (lines[j].startswith("#") or not lines[j].strip()):
                j += 1
            url = lines[j].strip() if j < len(lines) else ""
            entries.append((line, url))
            i = j + 1
            continue
        i += 1
    return header, entries


def main(argv):
    src, dst, keep = SRC, DST, 3
    args = [a for a in argv[1:]]
    if "--keep" in args:
        k = args.index("--keep")
        keep = int(args[k + 1])
        del args[k:k + 2]
    if len(args) >= 1:
        src = args[0]
    if len(args) >= 2:
        dst = args[1]

    if not os.path.exists(src):
        print("缺少 %s，先跑 merge" % src)
        return 0

    blocked = load_blocklist()
    header, entries = parse(src)

    kept, dropped = [], {}
    order = []
    per_channel = {}
    for extinf, url in entries:
        reason = drop_reason(url, blocked)
        if reason:
            dropped[reason] = dropped.get(reason, 0) + 1
            continue
        name = extinf
        if name not in per_channel:
            per_channel[name] = []
            order.append(name)
        per_channel[name].append(url)

    out = [header or "#EXTM3U"]
    total = 0
    for name in order:
        urls = per_channel[name]
        urls.sort(key=lambda u: (0 if u.lower().startswith("https") else 1, len(u)))
        for url in urls[:keep]:
            out.append(name)
            out.append(url)
            total += 1

    with open(dst, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")

    print("主力 %d 条 → 可用版 %d 条 / %d 台（每台最多 %d 条）" % (
        len(entries), total, len(order), keep))
    for reason, cnt in sorted(dropped.items(), key=lambda x: -x[1]):
        print("  剔除 %-12s %d 条" % (reason, cnt))
    print("  黑名单主机 %d 个" % len(blocked))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
