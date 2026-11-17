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

# ottiptv 付费订阅源：需要 UA=qqlive 才能播，缓存到 m3u/ottiptv.m3u 供下次兜底
# 订阅地址含账号凭证，不能写进公开仓库：优先读环境变量 OTT_SUB_URL（云端用 GitHub Secret），
# 本地可放在 data/ott_sub_url.txt（已 gitignore）
OTT_URL_FILE = os.path.join(ROOT, "data", "ott_sub_url.txt")
OTT_CACHE = os.path.join(ROOT, "m3u", "ottiptv.m3u")
OTT_UA = "qqlive"
OTT_PREFIX = "🎯"


def ott_sub_url():
    url = os.environ.get("OTT_SUB_URL", "").strip()
    if url:
        return url
    if os.path.exists(OTT_URL_FILE):
        try:
            with open(OTT_URL_FILE, "r", encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            pass
    return ""

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
    # 专享卫视/专享央视不再单独成组：卫视类并入卫视频道，央视类并入央视频道
    ("专享卫视", "❤️卫视频道"),
    ("专享央视", "❤️央视频道"),
    ("儿童专享", "💓儿童专享"),
    ("电影点播", "❤️电影点播"),
    ("电视剧", "💓电视剧"),
    ("台湾台", "💓台湾台"),
    ("港澳台", "💓港澳台"),   # 同时覆盖“港澳台”与“💓港澳台📶”
    ("国际台", "💕国际台"),
    ("4K(Auto)", "💓4K(Auto)"),
    # 4K 只保留一组：4K(Test) 并入 4K(Auto)
    ("4K(Test)", "💓4K(Auto)"),
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


def channel_name(extinf):
    return extinf.split(",", 1)[1].strip() if "," in extinf else extinf


def fetch_ott():
    """抓 ottiptv 订阅；失败时回退到上次缓存。返回行列表或 None。"""
    import urllib.request

    url = ott_sub_url()
    if not url or not url.lower().startswith(("http://", "https://")):
        print(
            "警告：OTT_SUB_URL 未配置或不是完整网址（当前长度 %d），跳过付费源拉取" % len(url),
            file=sys.stderr,
        )
        if os.path.exists(OTT_CACHE) and os.path.getsize(OTT_CACHE) > 0:
            print("使用缓存 %s" % OTT_CACHE, file=sys.stderr)
            return read_lines(OTT_CACHE)
        return None

    req = urllib.request.Request(url, headers={"User-Agent": OTT_UA})
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = resp.read().decode("utf-8", "ignore")
        if "#EXTINF" not in data:
            raise ValueError("返回内容不是 m3u")
        os.makedirs(os.path.dirname(OTT_CACHE), exist_ok=True)
        with open(OTT_CACHE, "w", encoding="utf-8") as f:
            f.write(data)
        print("ottiptv 拉取成功：%d 字节" % len(data.encode("utf-8")))
        return data.splitlines()
    except Exception as exc:
        print("警告：ottiptv 拉取失败（%s），尝试使用缓存" % exc, file=sys.stderr)
        if os.path.exists(OTT_CACHE) and os.path.getsize(OTT_CACHE) > 0:
            print("使用缓存 %s" % OTT_CACHE, file=sys.stderr)
            return read_lines(OTT_CACHE)
        return None


def build_ott(lines):
    """按原分组归桶，分组名统一加 🎯 前缀；每条注入 UA，避免播放器手动设置。"""
    buckets = {}
    order = []
    i = 0
    while i < len(lines):
        if lines[i].startswith("#EXTINF"):
            extinf = lines[i]
            j = i + 1
            while j < len(lines) and lines[j].startswith("#"):
                j += 1
            if j < len(lines):
                url = lines[j].strip()
                if url.startswith("http"):
                    group = get_group(extinf) or "其他"
                    target = OTT_PREFIX + group
                    if target not in buckets:
                        buckets[target] = []
                        order.append(target)
                    buckets[target].append(
                        (
                            set_group(extinf, target)
                            + (
                                "\n#EXTVLCOPT:http-user-agent=" + OTT_UA
                                if os.environ.get("OTT_UA_INJECT", "0") != "0"
                                else ""
                            ),
                            url,
                        )
                    )
                i = j + 1
                continue
        i += 1
    return buckets, order


def dedupe_buckets(buckets):
    """按目标分组去重。

    1) 同一分组内「同名 + 同址」重复的只保留一条（同一个网址只出现一次）；
    2) 跨分组同名的频道只保留在优先级最高的分组里（GROUPS 顺序即优先级，
       例如 CCTV4K 同时出现在 4K 组与央视组时，只留在央视组）。
    同一频道在同一分组内的多条不同地址全部保留（那是备选源，不是重复）。
    """
    merged = {}
    order = []
    for idx, (_, target) in enumerate(GROUPS):
        if target not in merged:
            merged[target] = []
            order.append(target)
        merged[target].extend(buckets[idx])

    result = {target: [] for target in order}
    claimed_prev = set()
    for target in order:
        seen_key = set()
        out = []
        for extinf, url in merged[target]:
            name = channel_name(extinf)
            if name in claimed_prev:
                continue
            key = (name, url)
            if key in seen_key:
                continue
            seen_key.add(key)
            out.append((extinf, url))
        result[target] = out
        claimed_prev |= {channel_name(e) for e, _ in out}
    return result, order


def main():
    if not os.path.exists(BBXX):
        print("缺少 %s，请先运行 main.py" % BBXX, file=sys.stderr)
        return 1

    bbxx_raw = build_bbxx(read_lines(BBXX))
    bbxx_buckets, group_order = dedupe_buckets(bbxx_raw)

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
    for target in group_order:
        for extinf, url in bbxx_buckets[target]:
            result.append(extinf)
            result.append(url)

    # ottiptv 付费源放最后，分组保留原结构，分组名加 🎯
    # OTT_ENABLE=0 可临时关掉（播放器不支持 #EXTVLCOPT 时用）
    ott_raw = fetch_ott() if os.environ.get("OTT_ENABLE", "1") != "0" else None
    ott_buckets, ott_order = ({}, [])
    if ott_raw:
        ott_buckets, ott_order = build_ott(ott_raw)
        for target in ott_order:
            for extinf, url in ott_buckets[target]:
                result.append(extinf)
                result.append(url)
    else:
        print("警告：本次没有 ottiptv 内容", file=sys.stderr)


    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(HEADER)
        f.write("\n".join(result))
        f.write("\n")

    total = sum(1 for l in result if l.startswith("#EXTINF"))
    print("酒店源频道数: %d" % hotel_count)
    print("bbxx365 白名单频道数: %d" % sum(len(v) for v in bbxx_buckets.values()))
    print("ottiptv 频道数: %d" % sum(len(v) for v in ott_buckets.values()))
    print("合并完成: %s（共 %d 个频道）" % (OUT, total))

    for target in group_order:
        print("  %-12s %d" % (target, len(bbxx_buckets[target])))
    for target in ott_order:
        print("  %-12s %d" % (target, len(ott_buckets[target])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
