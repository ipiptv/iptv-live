#!/usr/bin/env python3
"""从 hotel 版 m3u 生成体积很小的「必看频道」版本。

用法：
    python3 scripts/make_mini.py            # 不验活，每频道取前 2 条
    python3 scripts/make_mini.py --verify   # 先验真直播，再挑源（慢几十秒）

规则：
1. 只保留白名单分组（央视/卫视/专享/4K/国际台）
2. 每频道最多保留 2 条源
3. --verify 时优先选直播型 m3u8，剔除点播(#EXT-X-ENDLIST)、mp4、网页链接
4. 剔除会被国内托管判违规、或明显是聚合接口的域名
输入 m3u/bbxx365_hotel.m3u，输出 m3u/bbxx365_mini.m3u
"""
import concurrent.futures
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SRC = "m3u/bbxx365_hotel.m3u"
OUT = "m3u/bbxx365_mini.m3u"
PER = 2          # 每频道最终保留条数
CANDIDATES = 5   # 每频道最多探测的候选数

# 只保留「打开就是台」的分组，地方台/杂项不进迷你版
GROUPS = {
    "❤️央视频道", "❤️卫视频道", "❤️专享央视", "❤️专享卫视",
    "💓4K(Auto)", "💕国际台",
}

# 国内托管会做内容过滤：快手 kwimgs、聚合站 api.php 这类链接会被判违规（451），
# 而「更新时间」那条本来只是挂个视频链接当占位，不要进迷你版。
BAD_URL = ("kwimgs.com", "jiduo.me", "kwai")


def parse(path):
    lines = open(path, encoding="utf-8").read().splitlines()
    entries, i = [], 0
    while i < len(lines):
        if lines[i].strip().startswith("#EXTINF"):
            j = i + 1
            while j < len(lines) and lines[j].strip().startswith("#"):
                j += 1
            if j < len(lines):
                entries.append((lines[i].strip(), lines[j].strip()))
            i = j + 1
        else:
            i += 1
    return entries


def build(entries, verify):
    grp_re = re.compile(r'group-title="([^"]*)"')
    buckets = {}
    for extinf, url in entries:
        if not url or any(b in url for b in BAD_URL):
            continue
        m = grp_re.search(extinf)
        grp = m.group(1) if m else ""
        if grp not in GROUPS:
            continue
        name = extinf.split(",", 1)[1].strip() if "," in extinf else extinf
        key = (grp, name)
        lst = buckets.setdefault(key, [])
        if len(lst) < CANDIDATES and url not in [u for _, u in lst]:
            lst.append((extinf, url))

    order = list(GROUPS)

    if not verify:
        out = ["#EXTM3U"]
        for key in sorted(buckets, key=lambda k: (order.index(k[0]), k[1])):
            for extinf, url in buckets[key][:PER]:
                out += [extinf, url]
        return out, {}

    from probe_stream import classify

    cand = [(key, extinf, url) for key, lst in buckets.items() for extinf, url in lst]
    with concurrent.futures.ThreadPoolExecutor(32) as ex:
        verdicts = list(ex.map(lambda t: classify(t[2]), cand))

    picks, stat = {}, {}
    for (key, extinf, url), v in zip(cand, verdicts):
        stat[v] = stat.get(v, 0) + 1
        picks.setdefault(key, []).append((v, extinf, url))
    rank = {"live": 0, "dead": 1, "junk": 2, "vod": 3, "mp4": 3}
    out, used = ["#EXTM3U"], set()
    for key in sorted(picks, key=lambda k: (order.index(k[0]), k[1])):
        kept = 0
        for v, extinf, url in sorted(picks[key], key=lambda t: rank.get(t[0], 2)):
            if v in ("vod", "mp4", "junk"):   # 点播片子、网页/非 HLS 一律不要
                continue
            if kept >= PER or url in used:
                continue
            out += [extinf, url]
            used.add(url)
            kept += 1
    return out, stat


def main() -> int:
    verify = "--verify" in sys.argv
    if not os.path.exists(SRC):
        print(f"缺少 {SRC}，先跑 merge_bbxx365_hotel.py")
        return 1
    out, stat = build(parse(SRC), verify)
    open(OUT, "w", encoding="utf-8").write("\n".join(out) + "\n")
    print(f"{OUT}: {len(out) // 2} 条 / {os.path.getsize(OUT) // 1024}KB"
          + (f" / 探测 {stat}" if stat else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
