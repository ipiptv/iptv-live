#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把三个“一起看”订阅源整理成一份 m3u（不经过 Gitee，只发布到 publish 分支）。

输入（上游 sub.ottiptv.cc，均为公开订阅）：
    huyayqk  虎牙一起看
    douyuyqk 斗鱼一起看
    yylunbo  YY 轮播
处理：
    - 去掉 4K 频道（分组或台名带 4K/UHD/2160/超高清）
    - 去掉“列表更新时间”那条时间戳
    - 分组名统一改成四个字：虎牙观影 / 虎牙原创 / 斗鱼观影 / 斗鱼原创 / YY轮播
    - 同名同址去重
输出：
    m3u/yiqikan.m3u

拉取失败的源会退回上次缓存（data/yiqikan-cache/，CI 里用 actions/cache 滚动保存）；
三个都拿不到时不写文件，让线上保留上一版。
"""

import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "m3u", "yiqikan.m3u")
CACHE_DIR = os.path.join(ROOT, "data", "yiqikan-cache")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"

# (上游文件名, 分组映射)
SOURCES = [
    ("huyayqk", {"一起看": "虎牙观影", "原创": "虎牙原创"}),
    ("douyuyqk", {"一起看": "斗鱼观影", "原创IP": "斗鱼原创"}),
    ("yylunbo", {"zonghe": "YY轮播", "car": "YY轮播"}),
]
GROUP_ORDER = ["虎牙观影", "虎牙原创", "斗鱼观影", "斗鱼原创", "YY轮播"]

RE_4K = re.compile(r"(4K|UHD|2160|超高清)", re.I)
RE_UPD = re.compile(r"(更新时间|列表更新)")
RE_TS = re.compile(r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}")
GROUP_RE = re.compile(r'group-title="([^"]*)"')


def fetch(name):
    url = "https://sub.ottiptv.cc/%s.m3u" % name
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = resp.read().decode("utf-8", "ignore")
        if "#EXTINF" not in data:
            raise ValueError("返回内容不是 m3u")
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(os.path.join(CACHE_DIR, name + ".m3u"), "w", encoding="utf-8") as f:
            f.write(data)
        print("%s 拉取成功：%d 条" % (name, data.count("#EXTINF")))
        return data.splitlines()
    except Exception as exc:
        cache = os.path.join(CACHE_DIR, name + ".m3u")
        if os.path.exists(cache) and os.path.getsize(cache) > 0:
            print("警告：%s 拉取失败（%s），用缓存" % (name, exc), file=sys.stderr)
            return open(cache, encoding="utf-8", errors="ignore").read().splitlines()
        print("警告：%s 拉取失败且无缓存（%s）" % (name, exc), file=sys.stderr)
        return None


def clean(lines, mapping):
    """过滤 4K/更新时间，分组改名，返回 [(分组, extinf, url)]。"""
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.startswith("#EXTINF"):
            i += 1
            continue
        j = i + 1
        while j < len(lines) and lines[j].startswith("#"):
            j += 1
        url = lines[j].strip() if j < len(lines) else ""
        name = line.split(",", 1)[1].strip() if "," in line else ""
        m = GROUP_RE.search(line)
        group = m.group(1) if m else ""
        if not url.startswith("http"):
            i = j + 1
            continue
        if RE_4K.search(group) or RE_4K.search(name):
            i = j + 1
            continue
        if RE_UPD.search(group) or RE_UPD.search(name) or RE_TS.match(name):
            i = j + 1
            continue
        target = mapping.get(group, "YY轮播" if group.lower() == "car" else group)
        if m:
            line = GROUP_RE.sub('group-title="%s"' % target, line, count=1)
        else:
            line = line.replace("#EXTINF:-1", '#EXTINF:-1 group-title="%s"' % target, 1)
        out.append((target, line, url))
        i = j + 1
    return out


def main():
    entries = []
    ok = 0
    for name, mapping in SOURCES:
        lines = fetch(name)
        if lines is None:
            continue
        ok += 1
        entries.extend(clean(lines, mapping))
    if ok == 0:
        print("三个源全部失败，保留线上上一版", file=sys.stderr)
        return 0

    seen = set()
    result = []
    for target in GROUP_ORDER:
        for g, extinf, url in entries:
            if g != target:
                continue
            key = (g, extinf.split(",", 1)[-1].strip(), url)
            if key in seen:
                continue
            seen.add(key)
            result.append(extinf)
            result.append(url)
    # 未映射到已知分组的（理论上没有）归到末尾，避免丢数据
    for g, extinf, url in entries:
        if g in GROUP_ORDER:
            continue
        key = (g, extinf.split(",", 1)[-1].strip(), url)
        if key in seen:
            continue
        seen.add(key)
        result.append(extinf)
        result.append(url)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        f.write("\n".join(result))
        f.write("\n")

    total = sum(1 for l in result if l.startswith("#EXTINF"))
    print("生成 %s：%d 条" % (OUT, total))
    for target in GROUP_ORDER:
        n = sum(1 for l in result if l.startswith("#EXTINF") and GROUP_RE.search(l) and GROUP_RE.search(l).group(1) == target)
        print("  %s %d 条" % (target, n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
