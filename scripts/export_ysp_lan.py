#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把本机央视频网关（8767）的全频道订阅导出成一份「局域网可用」的 m3u，
交给 CI 追加进主力源，形成「❤️央视官方 / ❤️卫视官方」两个新分组。

为什么要在本机跑：网关只跑在你这台 Mac 上，CI（海外）连不到它，
所以先把清单落成文件提交进仓库，CI 每次只负责把这份清单塞进主力源。

用法：
    python scripts/export_ysp_lan.py                       # 默认 127.0.0.1:8767 -> 192.168.3.104
    python scripts/export_ysp_lan.py --host 192.168.3.104
"""
import argparse
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH = os.path.join(ROOT, "assets", "ysp-official.m3u")
UA = "AptvPlayer/1.0"

GROUP_MAP = {"央视": "❤️央视官方", "卫视": "❤️卫视官方"}
HEADER = ('#EXTM3U url-tvg="https://epg.zsdc.eu.org/t.xml.gz" '
          'x-tvg-url="https://epg.zsdc.eu.org/t.xml.gz"')


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", "ignore")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gateway", default="http://127.0.0.1:8767")
    ap.add_argument("--host", default="192.168.3.104", help="对外广播的局域网 IP")
    ap.add_argument("--out", default=OUT_PATH)
    args = ap.parse_args()

    try:
        body = fetch(args.gateway.rstrip("/") + "/all.m3u")
    except Exception as e:
        print("拉取网关订阅失败：%s（网关没在跑？）" % e)
        sys.exit(1)

    lines = body.split("\n")
    out = [HEADER]
    count = 0
    pending = None
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXTM3U"):
            continue
        if line.startswith("#EXTINF"):
            pending = line
            continue
        if line.startswith("#"):
            continue
        if not pending:
            continue
        m = re.search(r'group-title="([^"]*)"', pending)
        g = GROUP_MAP.get(m.group(1) if m else "")
        if not g:
            pending = None
            continue
        # 分组改成主力源用的名字
        if m:
            pending = re.sub(r'group-title="[^"]*"', 'group-title="%s"' % g, pending, count=1)
        # 播放地址换成本机局域网地址
        u = line
        u = re.sub(r"http://(127\.0\.0\.1|localhost)(:\d+)?", "http://%s:8767" % args.host, u)
        u = re.sub(r"http://[0-9.]+:8767", "http://%s:8767" % args.host, u)
        out.append(pending)
        out.append(u)
        pending = None
        count += 1

    if not count:
        print("网关订阅里没有央视/卫视频道，退出")
        sys.exit(1)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    print("[ysp] 导出 %d 个官方频道 -> %s（播放地址指向 %s:8767）" % (count, args.out, args.host))


if __name__ == "__main__":
    main()
