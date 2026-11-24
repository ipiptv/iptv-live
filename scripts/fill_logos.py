#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给主力源里缺台标的频道补上 tvg-logo。

台标来源（按顺序试，命中即用，结果缓存）：
  1. assets/logo.txt 里已有的 name->url 映射
  2. 自家 Cloudflare Pages 台标库 https://tv-res.pages.dev/logo/<name>.png
     （同一个台会试几种写法：原名 / 去掉 CCTV 前缀 / 小写 / 去掉「高清・4K」后缀）
  3. fanmingming 台标库 https://live.fanmingming.cn/tv/<name>.png

只补「没有 tvg-logo 或 tvg-logo 为空」的条目，已有的不动。

用法：
    python scripts/fill_logos.py                        # 补主力源
    python scripts/fill_logos.py --file m3u/xxx.m3u
"""
import argparse
import json
import os
import re
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M3U_DIR = os.path.join(ROOT, "m3u")
DEFAULT_FILE = os.path.join(M3U_DIR, "bbxx365_hotel.m3u")
LOGO_TXT = os.path.join(ROOT, "assets", "logo.txt")
CACHE_PATH = os.path.join(ROOT, "data", "stream-check", "logo-cache.json")

PAGES = "https://tv-res.pages.dev/logo/%s.png"
FMML = "https://live.fanmingming.cn/tv/%s.png"
FMML_INDEX_API = "https://api.github.com/repos/fanmingming/live/contents/tv"
FMML_INDEX_CACHE = os.path.join(ROOT, "data", "stream-check", "fmml-logo-index.json")
FMML_INDEX_TTL = 30 * 24 * 3600

HIT_TTL = 30 * 24 * 3600
MISS_TTL = 24 * 3600   # 没匹配上的台名每天重试一次，避免一次网络抖动就长期缺台标
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"

LOCK = threading.Lock()


# ---------- 名字归一 & 候选 ----------
def norm(s):
    s = unicodedata.normalize("NFKC", s).strip()
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"(高清|超清|标清|蓝光|超清4K|4K|HD|频道|电视台|台)$", "", s, flags=re.I)
    return s


def candidates(name):
    base = norm(name)
    out = []

    def add(x):
        x = x.strip()
        if x and x not in out:
            out.append(x)

    add(base)
    add(name.strip())
    # CCTV 频道：付费台在台标库里常不带 CCTV 前缀
    m = re.match(r"^CCTV[\-—\s]?", base, re.I)
    if m:
        add(base[m.end():])
    # 卫视/地方台：去掉「卫视」后缀再试一次
    if base.endswith("卫视"):
        add(base[:-2])
    # 小写兜底（台标库里有 cctv5+ 这种小写文件）
    low = base.lower()
    add(low)
    if m:
        rest = base[m.end():]
        if rest:
            add(rest.lower())
    return out


# ---------- 缓存 ----------
def load_cache():
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            d = json.load(f)
            if isinstance(d.get("records"), dict):
                return d
    except Exception:
        pass
    return {"version": 1, "updated": "", "records": {}}


def save_cache(c):
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    c["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    tmp = CACHE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(c, f, ensure_ascii=False)
    os.replace(tmp, CACHE_PATH)


def cache_get(c, name):
    rec = c["records"].get(name)
    if not rec:
        return None
    ttl = HIT_TTL if rec.get("url") else MISS_TTL
    if time.time() - rec.get("at", 0) > ttl:
        return None
    return rec.get("url") or ""


def cache_put(c, name, url):
    with LOCK:
        c["records"][name] = {"url": url or "", "at": int(time.time())}


# ---------- 探测 ----------
def head_ok(url):
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=8) as r:
            ct = (r.headers.get("Content-Type") or "").lower()
            return r.getcode() == 200 and ("image" in ct or not ct)
    except Exception:
        return False


def fmml_index():
    """fanmingming 台标库的文件名清单（用 GitHub API 拉，避开 raw 域名被墙）。
    有些网络直接访问 live.fanmingming.cn 会超时，但文件是否存在可以先由清单判定。"""
    try:
        with open(FMML_INDEX_CACHE, encoding="utf-8") as f:
            d = json.load(f)
            if time.time() - d.get("at", 0) < FMML_INDEX_TTL and d.get("names"):
                return d["names"]
    except Exception:
        pass
    try:
        raw = urllib.request.urlopen(urllib.request.Request(FMML_INDEX_API,
                                 headers={"User-Agent": UA}), timeout=25).read()
        d = json.loads(raw)
        names = [x["name"][:-4] for x in d if x.get("name", "").lower().endswith(".png")]
        os.makedirs(os.path.dirname(FMML_INDEX_CACHE), exist_ok=True)
        with open(FMML_INDEX_CACHE, "w", encoding="utf-8") as f:
            json.dump({"at": int(time.time()), "names": names}, f, ensure_ascii=False)
        return names
    except Exception:
        return []


def resolve(name, logo_map, fm_index=None):
    if name in logo_map:
        return logo_map[name]
    for cand in candidates(name):
        url = PAGES % urllib.parse.quote(cand)
        if head_ok(url):
            return url
    # 自家台标库没有 → 用 fanmingming 的文件清单判定，存在就直接给地址（不再现场 HEAD）
    if fm_index:
        by_norm = {norm(x): x for x in fm_index}
        for cand in candidates(name):
            real = cand if cand in fm_index else by_norm.get(norm(cand))
            if real:
                return FMML % urllib.parse.quote(real)
    for cand in candidates(name):
        url = FMML % urllib.parse.quote(cand)
        if head_ok(url):
            return url
    return ""


# ---------- m3u ----------
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
                if pending:
                    pending += "\n" + line
                continue
            if pending:
                entries.append({"extinf": pending, "url": line.strip()})
                pending = None
    return header, entries


def entry_name(e):
    first = e["extinf"].split("\n")[0]
    n = first.rsplit(",", 1)[-1].strip()
    if n:
        return n
    m = re.search(r'tvg-name="([^"]*)"', first)
    return m.group(1).strip() if m else ""


def has_logo(e):
    m = re.search(r'tvg-logo="([^"]*)"', e["extinf"])
    return bool(m and m.group(1).strip())


def set_logo(e, url):
    if re.search(r'tvg-logo="[^"]*"', e["extinf"]):
        e["extinf"] = re.sub(r'tvg-logo="[^"]*"', 'tvg-logo="%s"' % url, e["extinf"], count=1)
    elif re.search(r'group-title="', e["extinf"]):
        e["extinf"] = e["extinf"].replace('group-title="', 'tvg-logo="%s"  group-title="' % url, 1)
    else:
        e["extinf"] = e["extinf"].replace("#EXTINF:-1", '#EXTINF:-1 tvg-logo="%s"' % url, 1)


def load_logo_txt():
    m = {}
    try:
        with open(LOGO_TXT, encoding="utf-8") as f:
            for ln in f:
                if "," in ln:
                    k, v = ln.split(",", 1)
                    if k.strip() and v.strip():
                        m[k.strip()] = v.strip()
    except Exception:
        pass
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=DEFAULT_FILE)
    args = ap.parse_args()

    if not os.path.exists(args.file):
        print("找不到 %s" % args.file)
        sys.exit(1)

    header, entries = parse_m3u(args.file)
    missing = [e for e in entries if not has_logo(e)]
    print("[logo] 频道 %d 条，缺台标 %d 条" % (len(entries), len(missing)))
    if not missing:
        return

    names = sorted({entry_name(e) for e in missing if entry_name(e)})
    logo_map = load_logo_txt()
    cache = load_cache()

    todo = [n for n in names if cache_get(cache, n) is None]
    print("[logo] 待查 %d 个台名（缓存命中 %d）" % (len(todo), len(names) - len(todo)))

    resolved = {}
    for n in names:
        hit = cache_get(cache, n)
        if hit:
            resolved[n] = hit

    fm_index = fmml_index()
    print("[logo] fanmingming 清单 %d 个" % len(fm_index))
    if todo:
        with ThreadPoolExecutor(max_workers=16) as pool:
            for name, url in zip(todo, pool.map(lambda n: resolve(n, logo_map, fm_index), todo)):
                resolved[name] = url
                cache_put(cache, name, url)
        save_cache(cache)

    filled = 0
    for e in missing:
        n = entry_name(e)
        url = resolved.get(n) or ""
        if url:
            set_logo(e, url)
            filled += 1

    tmp = args.file + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for h in header or ["#EXTM3U"]:
            f.write(h + "\n")
        for e in entries:
            f.write(e["extinf"] + "\n")
            f.write(e["url"] + "\n")
    os.replace(tmp, args.file)

    still = len(missing) - filled
    print("[logo] 补上 %d 条，仍缺 %d 条（%d 个台名找不到台标）" % (filled, still, sum(1 for n in names if not resolved.get(n))))


if __name__ == "__main__":
    main()
