#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 bbxx365 源与 hotel_tvn 源按白名单合并成一个 m3u。

输入（均由同一次流水线的前序步骤生成，不依赖任何外部站点）：
    m3u/bbxx365.m3u    <- main.py 生成
    m3u/hotel_tvn.m3u  <- pnpm m3u 生成（可能不存在，缺失时跳过酒店源部分）
输出：
    m3u/bbxx365_hotel.m3u

用法：python scripts/merge_bbxx365_hotel.py
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BBXX = os.path.join(ROOT, "m3u", "bbxx365.m3u")
HOTEL = os.path.join(ROOT, "m3u", "hotel_tvn.m3u")
OUT = os.path.join(ROOT, "m3u", "bbxx365_hotel.m3u")

HEADER = '#EXTM3U x-tvg-url="https://live.fanmingming.cn/e.xml,https://tv.whyun.com/epg/51zmt.xml"\n'

# 更新时间分组只保留一条，播放地址固定为这个
UPDATE_URL = (
    "https://txmov2.a.kwimgs.com/upic/2024/01/09/12/"
    "BMjAyNDAxMDkxMjA2MDdfMzQ4MzI0MjA1OF8xMjE2Nzg4Mjk4NTZfMF8z_b_"
    "Bc9f7d3b0c4b69136e61d8328a8538bd2.mp4?clientCacheKey=3xajh8b4u5j6uva_b.mp4"
)

# 白名单：(分组关键词, 统一后的分组名)。关键词按“包含”匹配，先到先得。
GROUPS = [
    ("央视频道", "❤️央视频道"),
    ("卫视频道", "❤️卫视频道"),
    ("专享卫视", "❤️专享卫视"),
    ("专享央视", "❤️专享央视"),
    ("儿童专享", "💓儿童专享"),
    ("电影点播", "❤️电影点播"),
    ("电视剧", "💓电视剧"),
    ("台湾台", "💓台湾台"),
    ("港澳台", "💓港澳台"),   # 同时覆盖“港澳台”与“💓港澳台📶”
    ("国际台", "💕国际台"),
    ("4K(Auto)", "💓4K(Auto)"),
    ("4K(Test)", "💓4K(Test)"),
    ("更新时间", "❤️更新时间"),
]

HOTEL_GROUPS = ["央视频道", "卫视频道", "其他频道"]

GROUP_RE = re.compile(r'group-title="([^"]*)"')


def read_lines(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read().splitlines()


def get_group(line):
    m = GROUP_RE.search(line)
    return m.group(1) if m else ""


def set_group(line, name):
    if GROUP_RE.search(line):
        return GROUP_RE.sub('group-title="%s"' % name, line, count=1)
    return line.replace("#EXTINF:-1", '#EXTINF:-1 group-title="%s"' % name, 1)


def match_group(group_title):
    for idx, (keyword, new_name) in enumerate(GROUPS):
        if keyword.lower() in group_title.lower():
            return idx, new_name
    return -1, None


def build_bbxx(lines):
    buckets = {i: [] for i in range(len(GROUPS))}
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("#EXTINF"):
            idx, new_name = match_group(get_group(line))
            if idx >= 0:
                url = lines[i + 1] if i + 1 < len(lines) else ""
                buckets[idx].append((set_group(line, new_name), url))
            i += 2
        else:
            i += 1

    # 更新时间分组：只留第一条，地址替换为固定播放地址
    update_idx = next(i for i, (k, _) in enumerate(GROUPS) if k == "更新时间")
    if buckets[update_idx]:
        first_extinf = buckets[update_idx][0][0]
        buckets[update_idx] = [(first_extinf, UPDATE_URL)]

    return buckets


def build_hotel(lines):
    buckets = {g: [] for g in HOTEL_GROUPS}
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("#EXTINF"):
            group = get_group(line)
            matched = None
            for g in HOTEL_GROUPS:
                if g in group or g in line:
                    matched = g
                    break
            if matched:
                url = lines[i + 1] if i + 1 < len(lines) else ""
                buckets[matched].append((set_group(line, "🌹" + group), url))
            i += 2
        else:
            i += 1
    return buckets


def main():
    if not os.path.exists(BBXX):
        print("缺少 %s，请先运行 main.py" % BBXX, file=sys.stderr)
        return 1

    bbxx_buckets = build_bbxx(read_lines(BBXX))

    if os.path.exists(HOTEL) and os.path.getsize(HOTEL) > 0:
        hotel_buckets = build_hotel(read_lines(HOTEL))
        hotel_count = sum(len(v) for v in hotel_buckets.values())
    else:
        print("警告：未找到 %s，本次只输出 bbxx365 部分" % HOTEL)
        hotel_buckets = {g: [] for g in HOTEL_GROUPS}
        hotel_count = 0

    result = []
    for g in HOTEL_GROUPS:
        for extinf, url in hotel_buckets[g]:
            result.append(extinf)
            result.append(url)
    for idx in range(len(GROUPS)):
        for extinf, url in bbxx_buckets[idx]:
            result.append(extinf)
            result.append(url)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(HEADER)
        f.write("\n".join(result))
        f.write("\n")

    total = sum(1 for l in result if l.startswith("#EXTINF"))
    print("酒店源频道数: %d" % hotel_count)
    print("bbxx365 白名单频道数: %d" % sum(len(v) for v in bbxx_buckets.values()))
    print("合并完成: %s（共 %d 个频道）" % (OUT, total))

    for idx, (_, name) in enumerate(GROUPS):
        print("  %-12s %d" % (name, len(bbxx_buckets[idx])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
