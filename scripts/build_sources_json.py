#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成 m3u/sources.json：给后台管理页（admin.html）用的订阅清单元数据。

每次流水线跑完生成一份，页面读它就能显示最新条数、更新时间和分组数，
不用人工改页面。订阅地址本身是固定的，内容由流水线自动覆盖。

输出：m3u/sources.json（随后随镜像同步到 publish 分支和 Gitee）
"""

import json
import os
import re
import sys
import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M3U = os.path.join(ROOT, "m3u")
OUT = os.path.join(M3U, "sources.json")

GITEE = "https://gitee.com/IptvIptv/Iptv/raw/master/%s"
GITHUB = "https://raw.githubusercontent.com/ipiptv/iptv-sources/publish/%s"

# (文件名, 显示名, 用途说明)
FILES = [
    ("bbxx365_hotel.m3u", "合并版（主力）", "常规分组 + 🌹酒店源，已按规则归并去重；付费源已单独一份"),
    ("bbxx365.m3u", "全集版", "全部源，不筛不并，条数最多，失效源也最多"),
    ("bbxx365_lite.m3u", "精简版", "挑过的常规源，比全集干净，比合并版杂"),
    ("bbxx365_mini.m3u", "迷你版", "只留央视/卫视/专享/4K/国际台，每台 2 条源，弱网和播放器超时短时用"),
    ("bbxx365_mini_home.m3u", "本机实测版", "家里联通网络实测出来的小清单，最贴合本地，只能在家里网络生成"),
    ("bbxx365_ott.m3u", "付费源（ottiptv）", "单独一份：🎯 分组，播放器需把 UA 设为 qqlive"),
    ("hotel_tvn.m3u", "酒店源", "酒店电视源单独一份，频道少但质量相对稳"),
]


def stats(path):
    if not os.path.exists(path):
        return None
    count = 0
    groups = set()
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.startswith("#EXTINF"):
                count += 1
                m = re.search(r'group-title="([^"]*)"', line)
                if m:
                    groups.add(m.group(1))
    return count, len(groups)


def main():
    items = []
    for filename, name, note in FILES:
        path = os.path.join(M3U, filename)
        s = stats(path)
        item = {
            "file": filename,
            "name": name,
            "note": note,
            "gitee": GITEE % filename,
            "github": GITHUB % filename,
        }
        if s:
            item["count"] = s[0]
            item["groups"] = s[1]
        else:
            item["missing"] = True
        items.append(item)

    now = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        "updated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "updated_at_cst": (now + datetime.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M"),
        "sources": items,
    }
    os.makedirs(M3U, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print("写入 %s" % OUT)
    for it in items:
        if it.get("missing"):
            print("  ! %s 缺失" % it["file"], file=sys.stderr)
        else:
            print("  %-22s %6d 条 / %2d 组" % (it["file"], it["count"], it["groups"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
