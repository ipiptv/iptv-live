#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 assets/select-direct.m3u 与 assets/select-overseas.m3u（4K 卫视、海外精选）前置进主力源。

- 排在官方 64 台之后：本脚本在 append_ysp_group.py 之前跑，官方组最后再前置一次
- 清单不存在或条目已存在就跳过
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN = os.path.join(ROOT, "m3u", "bbxx365_hotel.m3u")
SRC = [os.path.join(ROOT, "assets", "select-direct.m3u"),
       os.path.join(ROOT, "assets", "select-overseas.m3u")]


def entries_of(path):
    header, items, pending = [], [], None
    with open(path, encoding="utf-8", errors="ignore") as f:
        for raw in f:
            line = raw.rstrip("\n").rstrip("\r")
            if not line.strip():
                continue
            if line.startswith("#EXTM3U"):
                header.append(line)
                continue
            if line.startswith("#EXTINF"):
                pending = line
                continue
            if line.startswith("#"):
                continue
            if pending:
                items.append((pending, line.strip()))
                pending = None
    return header, items


def main():
    if not os.path.exists(MAIN):
        print("[select] 缺少主力源，跳过")
        return
    srcs = [p for p in SRC if os.path.exists(p)]
    if not srcs:
        print("[select] 没有精选清单，跳过")
        return

    m_header, m_items = entries_of(MAIN)
    s_items = []
    for p in srcs:
        _, it = entries_of(p)
        s_items.extend(it)

    exist = {(e.rsplit(",", 1)[-1].strip(), u) for e, u in m_items}
    add = [(e, u) for e, u in s_items if (e.rsplit(",", 1)[-1].strip(), u) not in exist]
    if not add:
        print("[select] 精选频道已全部存在，跳过")
        return

    # 官方 64 台（url 指向本机 8767 网关）保持最前，精选组紧随其后
    lead = 0
    for ext, url in m_items:
        if "8767/" in url:
            lead += 1
        else:
            break

    header = m_header[0] if m_header else "#EXTM3U"
    out = [header]
    for ext, url in m_items[:lead]:
        out.append(ext)
        out.append(url)
    for ext, url in add:
        out.append(ext)
        out.append(url)
    for ext, url in m_items[lead:]:
        out.append(ext)
        out.append(url)

    with open(MAIN, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")

    print("[select] 主力源前置了 %d 个精选直连频道（共 %d 条）" % (len(add), len(m_items) + len(add)))


if __name__ == "__main__":
    main()
