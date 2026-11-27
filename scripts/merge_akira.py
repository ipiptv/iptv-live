#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把本机 akiralereal iptv（8900）输出的订阅并进主力源。

- 订阅地址默认 http://127.0.0.1:8900/interface.m3u，可用 AKIRA_URL 覆盖
- 去重按「频道名 + 地址」，已存在的跳过
- 分组统一改名「🌀智能源」，排在官方 64 台之后、社区源之前
- 拉不到就跳过，不影响原有流水线
"""
import os
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN = os.path.join(ROOT, "m3u", "bbxx365_hotel.m3u")
URL = os.environ.get("AKIRA_URL", "http://127.0.0.1:8900/interface.m3u")
GROUP = "🌀智能源"
LAN_HOST = "192.168.3.101:8900"


def entries_of_text(text):
    items, pending = [], None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXTINF"):
            pending = line
            continue
        if line.startswith("#"):
            continue
        if pending:
            items.append((pending, line))
            pending = None
    return items


def entries_of_file(path):
    with open(path, encoding="utf-8", errors="ignore") as f:
        text = f.read()
    header = []
    for ln in text.splitlines():
        if ln.startswith("#EXTM3U"):
            header.append(ln)
            break
    return header, entries_of_text(text)


def rename_group(ext):
    name = ext.rsplit(",", 1)[-1].strip()
    head = ext.rsplit(",", 1)[0]
    if 'group-title="' in head:
        head = head.split('group-title="', 1)[0] + 'group-title="%s"' % GROUP
    else:
        head = head + ' group-title="%s"' % GROUP
    return "%s,%s" % (head, name)


def main():
    if not os.path.exists(MAIN):
        print("[akira] 缺少主力源，跳过")
        return
    try:
        with urllib.request.urlopen(URL, timeout=20) as resp:
            remote = resp.read().decode("utf-8", "replace")
    except Exception as exc:
        print("[akira] 拉取订阅失败（%s），本轮跳过" % exc)
        return

    m_header, m_items = entries_of_file(MAIN)
    a_items = entries_of_text(remote)
    if not a_items:
        print("[akira] 订阅为空，跳过")
        return

    a_items = [(e.replace("127.0.0.1:8900", LAN_HOST), u.replace("127.0.0.1:8900", LAN_HOST)) for e, u in a_items]

    exist = {(e.rsplit(",", 1)[-1].strip(), u) for e, u in m_items}
    add = [(rename_group(e), u) for e, u in a_items if (e.rsplit(",", 1)[-1].strip(), u) not in exist]
    if not add:
        print("[akira] %d 条已全部存在，跳过" % len(a_items))
        return

    lead = 0
    for _, url in m_items:
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

    print("[akira] 合并 %d 条智能源（订阅 %d 条，共 %d 条）" % (len(add), len(a_items), len(m_items) + len(add)))


if __name__ == "__main__":
    main()
