#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把酒店源（hotel_tvn.m3u）里全量没有的频道补进全量 bbxx365.m3u，
让全量成为真正的“全集”，之后主力再从全量里筛。

规则：
- 只看酒店源里的国内分组（央视频道 / 卫视频道 / 其他频道 / 专享等，由 HOTEL_GROUPS 决定）
- 频道名在全量里已存在的不重复添加
- 新补进来的条目按主力同一套规则改 group-title
- (频道名, 地址) 完全重复的丢掉

用法：python scripts/augment_full.py [全量路径] [酒店源路径]
"""

import importlib.util
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_rules():
    path = os.path.join(ROOT, "scripts", "merge_bbxx365_hotel.py")
    spec = importlib.util.spec_from_file_location("merge_rules", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def parse(path):
    """读出 (extinf, url) 列表，保留 #EXTM3U 头。"""
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.read().splitlines()
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
    rules = load_rules()
    full_path = argv[1] if len(argv) > 1 else os.path.join(ROOT, "m3u", "bbxx365.m3u")
    hotel_path = argv[2] if len(argv) > 2 else os.path.join(ROOT, "m3u", "hotel_tvn.m3u")
    if not os.path.exists(hotel_path):
        print("没有酒店源 %s，跳过补全" % hotel_path)
        return 0

    header, full = parse(full_path)
    _, hotel = parse(hotel_path)

    full_names = {rules.channel_name(e).strip() for e, _ in full}
    seen = {(rules.channel_name(e).strip(), u) for e, u in full}

    added = 0
    for extinf, url in hotel:
        name = rules.channel_name(extinf).strip()
        if not name or rules.HOTEL_DROP_PATTERN.search(name):
            continue
        if name.lower() in rules.HOTEL_DROP_NAMES:
            continue
        if name in full_names:
            continue
        if (name, url) in seen:
            continue
        target = rules.NAME_TARGET.get(name)
        if not target and rules.SPORT_NAME_RE.search(name):
            target = rules.SPORT_GROUP
        if not target and rules.KID_NAME_RE.search(name):
            target = rules.KID_GROUP
        if not target:
            idx, mapped = rules.match_group(rules.get_group(extinf))
            target = mapped if idx >= 0 else "🏙️地方频道"
        full.append((rules.set_group(extinf, target), url))
        seen.add((name, url))
        full_names.add(name)
        added += 1

    with open(full_path, "w", encoding="utf-8") as f:
        out = [header or "#EXTM3U"]
        for extinf, url in full:
            out.append(extinf)
            if url:
                out.append(url)
        f.write("\n".join(out) + "\n")

    print("全量补全：新增 %d 条，全量现有 %d 条 / %d 个台" % (added, len(full), len(full_names)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
