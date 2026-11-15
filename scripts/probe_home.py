"""从本机（家里联通宽带）实测候选源，生成「本地实测版」精编清单。

用法： python3 scripts/probe_home.py            # 只探测并缓存
       python3 scripts/probe_home.py --build    # 用缓存生成 m3u/bbxx365_mini_home.m3u
"""
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(__file__))
import make_mini  # noqa: E402
from rank_stream import analyze  # noqa: E402

CACHE = "/tmp/home_probe.json"
WORKERS = 40
TIMEOUT = 6


def candidates():
    grp_re = re.compile(r'group-title="([^"]*)"')
    buckets = {}
    for extinf, url in make_mini.parse(make_mini.SRC):
        if not url or any(b in url for b in make_mini.BAD_URL):
            continue
        m = grp_re.search(extinf)
        g = m.group(1) if m else ""
        if g not in make_mini.GROUPS:
            continue
        name = extinf.split(",", 1)[1].strip() if "," in extinf else extinf
        if any(b in name for b in make_mini.BAD_NAME):
            continue
        lst = buckets.setdefault((g, name), [])
        if len(lst) < make_mini.CANDIDATES and url not in [u for _, u in lst]:
            lst.append((extinf, url))
    return buckets


def probe_all(urls):
    def one(u):
        try:
            r = analyze(u, timeout=TIMEOUT)
        except Exception:
            r = {"kind": "error", "ttfb": 0, "height": 0, "kbps": 0, "tier": 0}
        r["url"] = u
        return r

    done = {}
    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for i, r in enumerate(ex.map(one, urls), 1):
            done[r["url"]] = r
            if i % 200 == 0:
                print(f"  已测 {i}/{len(urls)}  {time.monotonic()-t0:.0f}s", flush=True)
                json.dump(done, open(CACHE, "w"))
    json.dump(done, open(CACHE, "w"))
    return done


def main() -> int:
    buckets = candidates()
    urls = [u for lst in buckets.values() for _, u in lst]
    if "--build" in sys.argv:
        done = json.load(open(CACHE))
    else:
        print(f"候选 {len(urls)} 条，开始本机实测（{WORKERS} 并发，超时 {TIMEOUT}s）")
        done = probe_all(urls)

    stat = {}
    for r in done.values():
        stat[r["kind"]] = stat.get(r["kind"], 0) + 1
    print("本机探测结果:", stat)

    # 按本机实测：真直播优先 → 首字节越快越前 → 画质档位
    picked, total = {}, 0
    for k, lst in buckets.items():
        rows = []
        for extinf, url in lst:
            r = done.get(url)
            if not r or r["kind"] in ("dead", "junk", "vod", "mp4", "error"):
                continue
            rows.append((r, extinf, url))
        rows.sort(key=lambda t: (t[0]["ttfb"], -t[0].get("tier", 0)))
        chosen = rows[:5]
        if chosen:
            picked[k] = chosen
            total += len(chosen)

    out = ["#EXTM3U"]
    order = make_mini.GROUP_ORDER

    def name_key(k):
        n = k[1]
        m = re.search(r"CCTV\s*[-－—]?\s*(\d+)", n, re.I)
        if m:
            return (order.index(k[0]), 0, int(m.group(1)), len(n), n)
        return (order.index(k[0]), 1, 999, len(n), n)

    for k in sorted(picked, key=name_key):
        for r, extinf, url in picked[k]:
            out.append(f"#EXTINF:-1 {extinf.split(' ', 1)[1] if ' ' in extinf else extinf}")
            out.append(url)

    path = "m3u/bbxx365_mini_home.m3u"
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    size = os.path.getsize(path) // 1024
    print(f"{path}: {total} 条 / {size}KB / 频道 {len(picked)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
