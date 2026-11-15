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
MIN_SPEED = 150
CAND_CAP = 25  # 每频道最多纳入多少候选来实测（候选越多越可能凑出 10 条）  # 低于此吞吐（KB/s）的源直接不要，避免“能连上但打开要等”
WORKERS = 40
TIMEOUT = 6


def operator_entries():
    """路一：国内运营商单播源（河南移动 / 河南电信；联通暂无公开清单）。"""
    import urllib.request
    base = "https://raw.githubusercontent.com/xisohi/CHINA-IPTV/main/Unicast/henan"
    out = []
    for isp in ("mobile", "telecom", "unicom"):
        try:
            txt = urllib.request.urlopen(f"{base}/{isp}.txt", timeout=15).read().decode("utf-8", "ignore")
        except Exception as e:
            print(f"  {isp} 拉取失败: {e}")
            continue
        for ln in txt.splitlines():
            if "," not in ln or "http" not in ln:
                continue
            name, url = ln.split(",", 1)
            name, url = name.strip(), url.strip()
            if not name or name.startswith("【"):
                continue
            out.append((isp, name, url))
    print(f"  运营商源拉到 {len(out)} 条")
    return out


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
        if len(lst) < CAND_CAP and url not in [u for _, u in lst]:
            lst.append((extinf, url))
    return buckets


def _fetch(url, seconds=3.0, limit=2_000_000):
    """下载指定地址，返回 (字节数, 首字节耗时ms)。"""
    import ssl
    import urllib.request
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    t0 = time.monotonic()
    got, ttfb = 0, None
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as r:
            while got < limit and time.monotonic() - t0 < seconds:
                chunk = r.read(65536)
                if not chunk:
                    break
                if ttfb is None:
                    ttfb = (time.monotonic() - t0) * 1000
                got += len(chunk)
    except Exception:
        pass
    dt = max(time.monotonic() - t0, 0.001)
    return got, (ttfb or int(dt * 1000)), int(got / dt / 1024)


def hls_probe(url):
    """真按“能不能出画面”测：取 playlists 里的真实分片下载，算起播耗时与码率。"""
    from urllib.parse import urljoin
    import ssl
    import urllib.request
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        body = urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}),
            timeout=TIMEOUT, context=ctx).read(200_000).decode("utf-8", "ignore")
    except Exception:
        return {"seg_ttfb": 0, "seg_kbps": 0, "seg_time": 0}
    if "#EXTM3U" not in body:
        # 不是 m3u8（直接是流/ts），退回直连测速
        b, t, k = _fetch(url)
        return {"seg_ttfb": t, "seg_kbps": k, "seg_time": int(t / 1000)}
    # 若是多码率主列表，先选一条子列表
    segs = [ln.strip() for ln in body.splitlines() if ln.strip() and not ln.startswith("#")]
    if not segs:
        return {"seg_ttfb": 0, "seg_kbps": 0, "seg_time": 0}
    target = urljoin(url, segs[0])
    if target.split("?")[0].endswith(".m3u8"):
        try:
            sub = urllib.request.urlopen(
                urllib.request.Request(target, headers={"User-Agent": "Mozilla/5.0"}),
                timeout=TIMEOUT, context=ctx).read(200_000).decode("utf-8", "ignore")
            segs = [ln.strip() for ln in sub.splitlines() if ln.strip() and not ln.startswith("#")]
            target = urljoin(target, segs[0]) if segs else target
        except Exception:
            pass
    b, t, k = _fetch(target, seconds=2.5, limit=1_000_000)
    return {"seg_ttfb": t, "seg_kbps": k,
            "seg_time": round(b / max(k, 1) / 1024, 1) if k else 99}


def probe_all(urls):
    def one(u):
        try:
            r = analyze(u, timeout=TIMEOUT)
        except Exception:
            r = {"kind": "error", "ttfb": 0, "height": 0, "kbps": 0, "tier": 0}
        if r["kind"] == "live":
            r.update(hls_probe(u))
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
    per = 10
    if "--per" in sys.argv:
        per = int(sys.argv[sys.argv.index("--per") + 1])

    buckets = candidates()
    urls = [u for lst in buckets.values() for _, u in lst]

    ops = operator_entries()
    # 运营商源并入同名频道（放在最前），没有同名频道的单列一组
    by_name = {}
    for k in buckets:
        by_name.setdefault(k[1], []).append(k)
    op_extra = {}
    for isp, name, url in ops:
        if url in urls:
            continue
        extinf = f' tvg-name="{name}" group-title="🇨🇳运营商源",{name}'
        hits = by_name.get(name)
        if hits:
            buckets[hits[0]].append((extinf, url))
            urls.append(url)
        else:
            op_extra.setdefault(name, []).append((extinf, url))
            urls.append(url)
    for name, lst in op_extra.items():
        buckets[("🇨🇳运营商源", name)] = lst[:6]
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
        # 起播 ≤3 秒且码率够 → 排最前；不满 per 条的再用“能播但慢一点”的补齐
        fast = [t for t in rows
                if t[0].get("seg_kbps", 0) >= MIN_SPEED and t[0].get("seg_time", 99) <= 3]
        fast.sort(key=lambda t: (-t[0].get("seg_kbps", 0), t[0].get("seg_time", 99)))
        rest = [t for t in rows if t not in fast]
        rest.sort(key=lambda t: (t[0].get("seg_time", 99), -t[0].get("seg_kbps", 0)))
        chosen = (fast + rest)[:per]
        if chosen:
            picked[k] = chosen
            total += len(chosen)

    out = ["#EXTM3U"]
    order = make_mini.GROUP_ORDER

    def gorder(g):
        return order.index(g) if g in order else len(order)

    def name_key(k):
        n = k[1]
        m = re.search(r"CCTV\s*[-－—]?\s*(\d+)", n, re.I)
        if m:
            return (gorder(k[0]), 0, int(m.group(1)), len(n), n)
        return (gorder(k[0]), 1, 999, len(n), n)

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
