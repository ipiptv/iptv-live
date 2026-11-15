#!/usr/bin/env python3
"""从 hotel 版 m3u 里抽出一个体积很小的「必看频道」版本，供国内弱网/播放器超时短的场景使用。

用法：python3 scripts/make_mini.py [每频道保留源数，默认 2]
输入 m3u/bbxx365_hotel.m3u，输出 m3u/bbxx365_mini.m3u
"""
import os
import re
import sys

SRC = "m3u/bbxx365_hotel.m3u"
OUT = "m3u/bbxx365_mini.m3u"
PER = int(sys.argv[1]) if len(sys.argv) > 1 else 2

# 只保留「打开就是台」的分组，地方台/杂项/点播不进迷你版
GROUPS = {
    "❤️央视频道", "❤️卫视频道", "❤️专享央视", "❤️专享卫视",
    "💓4K(Auto)", "💕国际台", "❤️更新时间",
}


def main() -> int:
    if not os.path.exists(SRC):
        print(f"缺少 {SRC}，先跑 merge_bbxx365_hotel.py")
        return 1

    lines = open(SRC, encoding="utf-8").read().splitlines()
    entries = []
    i = 0
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

    grp_re = re.compile(r'group-title="([^"]*)"')
    cnt, seen, out = {}, set(), ["#EXTM3U"]
    for extinf, url in entries:
        if not url:
            continue
        m = grp_re.search(extinf)
        grp = m.group(1) if m else ""
        if grp not in GROUPS:
            continue
        name = extinf.split(",", 1)[1].strip() if "," in extinf else extinf
        if url in seen:
            continue
        key = (grp, name)
        if cnt.get(key, 0) >= PER:
            continue
        cnt[key] = cnt.get(key, 0) + 1
        seen.add(url)
        out += [extinf, url]

    open(OUT, "w", encoding="utf-8").write("\n".join(out) + "\n")
    print(f"{OUT}: {len(out) // 2} 条 / {len(cnt)} 个频道名 / {os.path.getsize(OUT) // 1024}KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
