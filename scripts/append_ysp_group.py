#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 assets/ysp-official.m3u（本机央视频网关导出的官方频道）追加进主力源。

- 只在 CI 里跑：读仓库里已提交的清单，插到主力源的最前面（官方源优先展示）
- 清单不存在就跳过，不影响原有流程
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN = os.path.join(ROOT, "m3u", "bbxx365_hotel.m3u")
YSP = os.path.join(ROOT, "assets", "ysp-official.m3u")


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
        print("[ysp] 缺少主力源，跳过")
        return
    if not os.path.exists(YSP):
        print("[ysp] 没有 assets/ysp-official.m3u，跳过（想加就在本机跑 export_ysp_lan.py）")
        return

    m_header, m_items = entries_of(MAIN)
    _, y_items = entries_of(YSP)

    # 去重：同一个频道名 + 同一个地址不重复插入
    exist = set()
    for ext, url in m_items:
        exist.add((ext.rsplit(",", 1)[-1].strip(), url))

    add = [(e, u) for e, u in y_items if (e.rsplit(",", 1)[-1].strip(), u) not in exist]
    if not add:
        print("[ysp] 官方频道已全部存在，跳过")
        return

    header = m_header[0] if m_header else "#EXTM3U"
    out = [header]
    for ext, url in add:            # 官方源放最前面
        out.append(ext)
        out.append(url)
    for ext, url in m_items:
        out.append(ext)
        out.append(url)

    with open(MAIN, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")

    print("[ysp] 主力源前置了 %d 个官方频道（共 %d 条）" % (len(add), len(m_items) + len(add)))


if __name__ == "__main__":
    main()
