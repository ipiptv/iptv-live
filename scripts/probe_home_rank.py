#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在「本机（家用网络）」实测每条线路的真实速度，生成 assets/home-rank.json。

为什么需要：CI 跑在海外，它探测出来的"能用/高清"和家里联通的实际情况经常相反——
海外能通的线路，国内可能死；测出来的高码率线路，家里带宽扛不住反而卡。
所以排序要以本机实测为准，CI 只做兜底。

产出格式（提交到仓库，CI 排序时读取）：
{
  "at": "2026-11-25T...",
  "channels": {
     "❤️央视频道|CCTV1": {"order": [url1, url2, ...],
                          "detail": {url1: {"kbs": 2596, "ttfb": 89, "stall": 0}}}
  }
}

用法：
    python scripts/probe_home_rank.py                          # 默认主力源，央视/卫视/少儿
    python scripts/probe_home_rank.py --groups 央视,卫视 --top 12 --channels CCTV1,CCTV5
"""
import argparse
import json
import os
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M3U_DIR = os.path.join(ROOT, "m3u")
DEFAULT_FILE = os.path.join(M3U_DIR, "bbxx365_hotel.m3u")
OUT_PATH = os.path.join(ROOT, "assets", "home-rank.json")

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
UA = "AptvPlayer/1.0"

GET_BYTES = 1_500_000        # 每条线路最多拉 1.5MB 估算速度
MIN_KBPS = 300               # 低于这个"KB/s"认为家里根本放不动
STALL_MS = 8000


def parse_m3u(path):
    header, entries, pending = [], [], None
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
                entries.append({"extinf": pending, "url": line.strip()})
                pending = None
    return header, entries


def entry_meta(e):
    first = e["extinf"].split("\n")[0]
    name = first.rsplit(",", 1)[-1].strip()
    m = re.search(r'group-title="([^"]*)"', first)
    group = m.group(1).strip() if m else ""
    return group, name


def measure(url, timeout=6):
    """返回 (kbs, ttfb, stall)；失败返回 None。"""
    try:
        t0 = time.monotonic()
        body = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}),
                                      timeout=timeout, context=CTX).read(65536).decode("utf-8", "ignore")
        ttfb = int((time.monotonic() - t0) * 1000)
        seg = None
        for ln in body.splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#"):
                seg = ln
                break
        if not seg:
            return None
        seg = urllib.parse.urljoin(url, seg)
        t1 = time.monotonic()
        r = urllib.request.urlopen(urllib.request.Request(seg, headers={"User-Agent": UA}),
                                  timeout=timeout, context=CTX)
        got = 0
        while got < GET_BYTES:
            chunk = r.read(65536)
            if not chunk:
                break
            got += len(chunk)
        dt = max(0.001, time.monotonic() - t1)
        kbs = int(got / dt / 1024)
        stall = 0 if dt < 5 else 1
        return kbs, ttfb, stall
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=DEFAULT_FILE)
    ap.add_argument("--groups", default="央视,卫视,少儿", help="只测这些分组（逗号分隔，空=全部）")
    ap.add_argument("--channels", default="", help="只测这些频道名（逗号分隔，空=全部）")
    ap.add_argument("--top", type=int, default=12, help="每个频道最多测几条")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--budget", type=int, default=3000, help="总探测条数上限")
    args = ap.parse_args()

    if not os.path.exists(args.file):
        print("找不到 %s" % args.file)
        sys.exit(1)

    _, entries = parse_m3u(args.file)
    want_groups = [g.strip() for g in args.groups.split(",") if g.strip()]
    want_names = [n.strip() for n in args.channels.split(",") if n.strip()]

    buckets = {}
    for e in entries:
        g, n = entry_meta(e)
        if want_groups and not any(w in g for w in want_groups):
            continue
        if want_names and n not in want_names:
            continue
        buckets.setdefault((g, n), []).append(e["url"])

    # 轮转取样：每个频道先测第 1 条，再第 2 条……保证每个台都能覆盖到，
    # 不会出现"前几个台吃满预算、后面的台一条没测"
    tasks = []
    for r in range(args.top):
        for key, urls in buckets.items():
            if r < len(urls):
                tasks.append((key, urls[r]))
                if len(tasks) >= args.budget:
                    break
        if len(tasks) >= args.budget:
            break

    print("[home] 频道 %d，待测线路 %d 条，并发 %d" % (len(buckets), len(tasks), args.workers))
    results = {}
    t_start = time.time()

    def one(t):
        return t[0], t[1], measure(t[1])

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for i, (key, u, r) in enumerate(pool.map(one, tasks), 1):
            if r:
                results.setdefault(key, {})[u] = {"kbs": r[0], "ttfb": r[1], "stall": r[2]}
            if i % 100 == 0:
                print("  已测 %d/%d，用时 %.1f 分" % (i, len(tasks), (time.time() - t_start) / 60))

    # 与已有结果合并：多次只测某几个分组时，不要把之前测过的其它台冲掉
    old = {}
    try:
        with open(OUT_PATH, encoding="utf-8") as f:
            old = (json.load(f) or {}).get("channels") or {}
    except Exception:
        pass

    channels = {}
    for key, detail in results.items():
        good = {u: d for u, d in detail.items() if d["kbs"] >= MIN_KBPS}
        bad = [u for u in detail if u not in good]
        order = sorted(good, key=lambda u: (-good[u]["kbs"], good[u]["ttfb"]))
        order += sorted(bad, key=lambda u: (detail[u]["stall"], -detail[u]["kbs"]))
        channels["%s|%s" % key] = {"order": order, "detail": detail}

    for k, v in old.items():
        if k not in channels:
            channels[k] = v

    payload = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "minKBs": MIN_KBPS,
        "channels": channels,
    }
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    ok = sum(1 for c in channels.values() for d in c["detail"].values() if d["kbs"] >= MIN_KBPS)
    print("[home] 完成：%d 个频道有实测，可用线路 %d 条，写入 %s" % (len(channels), ok, OUT_PATH))


if __name__ == "__main__":
    main()
