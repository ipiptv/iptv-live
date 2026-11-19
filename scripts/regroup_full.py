#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把全量 m3u（bbxx365.m3u）按主力那一套规则重新规整分组：
- 复用 scripts/merge_bbxx365_hotel.py 里的 GROUPS / NAME_TARGET / 关键词规则与输出顺序
- 只改 group-title 与分组排列顺序，其余原样保留（频道名、地址、其它属性都不动）
- 命中 HOTEL_DROP_NAMES / “测试” / 空名的条目会被剔除

用法：python scripts/regroup_full.py [文件路径，默认 m3u/bbxx365.m3u]
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


def main(argv):
    rules = load_rules()
    target = argv[1] if len(argv) > 1 else os.path.join(ROOT, "m3u", "bbxx365.m3u")
    if not os.path.exists(target):
        print("缺少 %s" % target, file=sys.stderr)
        return 1

    with open(target, "r", encoding="utf-8", errors="ignore") as f:
        raw = f.read()
    lines = raw.splitlines()

    header = ""
    entries = []  # (extinf, url)
    dropped = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("#EXTM3U") and not header:
            header = line
            i += 1
            continue
        if line.startswith("#EXTINF"):
            name = rules.channel_name(line).strip()
            j = i + 1
            while j < len(lines) and (lines[j].startswith("#") or not lines[j].strip()):
                j += 1
            url = lines[j].strip() if j < len(lines) else ""
            if not name or rules.HOTEL_DROP_PATTERN.search(name) or name.lower() in rules.HOTEL_DROP_NAMES:
                dropped += 1
                i = j + 1
                continue
            entries.append((line, url))
            i = j + 1
            continue
        i += 1

    grouped = {}
    order = []
    for extinf, url in entries:
        name = rules.channel_name(extinf).strip()
        target_group = rules.NAME_TARGET.get(name)
        if not target_group and rules.SPORT_NAME_RE.search(name):
            target_group = rules.SPORT_GROUP
        if not target_group and rules.KID_NAME_RE.search(name):
            target_group = rules.KID_GROUP
        if not target_group:
            idx, mapped = rules.match_group(rules.get_group(extinf))
            # 命不中规则的原分组名，统一兜底到“其他频道”
            target_group = mapped if idx >= 0 else rules.OTHER_GROUP
        if target_group not in grouped:
            grouped[target_group] = []
            order.append(target_group)
        grouped[target_group].append((rules.set_group(extinf, target_group), url))

    # 更新时间组和主力保持一致：只留一条，地址换成固定播放地址
    if "❤️更新时间" in grouped and grouped["❤️更新时间"]:
        grouped["❤️更新时间"] = [(grouped["❤️更新时间"][0][0], rules.UPDATE_URL)]

    final_order = [g for g in rules.OUTPUT_ORDER if g in grouped]
    final_order += [g for g in order if g not in final_order]

    out = [header or "#EXTM3U"]
    for g in final_order:
        for extinf, url in grouped[g]:
            out.append(extinf)
            if url:
                out.append(url)

    with open(target, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")

    print("全量规整完成：%d 条（剔除 %d 条），%d 个分组" % (len(entries), dropped, len(final_order)))
    for g in final_order:
        print("  %-12s %d" % (g, len(grouped[g])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
