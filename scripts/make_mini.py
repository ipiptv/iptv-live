#!/usr/bin/env python3
"""从 hotel 版 m3u 生成「必看频道」的精编版本。

用法：
    python3 scripts/make_mini.py --verify            # 每频道 5 条，按直播/画质/速度排序
    python3 scripts/make_mini.py --verify --per 3    # 改每频道保留条数

规则：
1. 只保留白名单分组（央视/卫视/专享/4K/国际台）
2. 只留真直播：剔除点播(ENDLIST/VOD)、mp4、网页链接
3. 同频道内按 画质档位 → 首字节耗时 排序，取最快的几条
4. 剔除会被国内托管判违规的域名
输入 m3u/bbxx365_hotel.m3u，输出 m3u/bbxx365_mini.m3u
"""
import concurrent.futures
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SRC = "m3u/bbxx365_hotel.m3u"
OUT = "m3u/bbxx365_mini.m3u"
CANDIDATES = 6    # 每频道最多探测的候选数

GROUPS = {
    "❤️央视频道", "❤️卫视频道", "❤️专享央视", "❤️专享卫视",
    "💓4K(Auto)", "💕国际台",
}

BAD_URL = ("kwimgs.com", "jiduo.me", "kwai")

# 名字里带这些的，基本不是真频道：移动传媒、购物台、测试台、轮播台——进去常年放广告
BAD_NAME = ("测试", "移动传媒", "轮播", "广告", "试播", "Demo", "demo")


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


def main() -> int:
    per = 5
    if "--per" in sys.argv:
        per = int(sys.argv[sys.argv.index("--per") + 1])
    verify = "--verify" in sys.argv

    if not os.path.exists(SRC):
        print(f"缺少 {SRC}，先跑 merge_bbxx365_hotel.py")
        return 1

    grp_re = re.compile(r'group-title="([^"]*)"')
    buckets = {}
    for extinf, url in parse(SRC):
        if not url or any(b in url for b in BAD_URL):
            continue
        m = grp_re.search(extinf)
        g = m.group(1) if m else ""
        if g not in GROUPS:
            continue
        name = extinf.split(",", 1)[1].strip() if "," in extinf else extinf
        if any(b in name for b in BAD_NAME):
            continue
        lst = buckets.setdefault((g, name), [])
        if len(lst) < CANDIDATES and url not in [u for _, u in lst]:
            lst.append((extinf, url))

    order = list(GROUPS)
    keys = sorted(buckets, key=lambda k: (order.index(k[0]), k[1]))

    if not verify:
        out = ["#EXTM3U"]
        for k in keys:
            for extinf, url in buckets[k][:per]:
                out += [extinf, url]
        open(OUT, "w", encoding="utf-8").write("\n".join(out) + "\n")
        print(f"{OUT}: {len(out) // 2} 条 / {os.path.getsize(OUT) // 1024}KB")
        return 0

    from rank_stream import analyze

    flat = [(k, extinf, url) for k in keys for extinf, url in buckets[k]]
    with concurrent.futures.ThreadPoolExecutor(40) as ex:
        info = list(ex.map(lambda t: analyze(t[2]), flat))

    picked, stat = {}, {}
    for (k, extinf, url), d in zip(flat, info):
        stat[d["kind"]] = stat.get(d["kind"], 0) + 1
        # 不在这里砍掉：云上探测（海外 IP）会把国内源误判成 dead，
        # 保留它们做兜底，只在排序上排在直播源后面。
        if d["kind"] in ("vod", "mp4", "junk"):
            continue
        picked.setdefault(k, []).append((d, extinf, url))

    out, used = ["#EXTM3U"], set()
    for k in keys:
        items = sorted(
            picked.get(k, []),
            key=lambda t: (0 if t[0]["kind"] == "live" else 1,
                           -t[0].get("tier", 0), t[0]["ttfb"]),
        )
        kept = 0
        for d, extinf, url in items:
            if kept >= per or url in used:
                continue
            out += [extinf, url]
            used.add(url)
            kept += 1

    open(OUT, "w", encoding="utf-8").write("\n".join(out) + "\n")
    print(f"{OUT}: {len(out) // 2} 条 / {os.path.getsize(OUT) // 1024}KB / 探测 {stat}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
