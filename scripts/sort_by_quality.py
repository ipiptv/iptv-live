#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""主力源整理：按清晰度重排每个频道的线路 + 去掉所有测试频道。

排序规则（同一频道名下的多条线路）：
    tier 降序（4=4K/高码率，3=1080p，2=720p，1=SD）
    → 实测 height 降序 → kbps 降序 → ttfb 升序
    → 探测失败的排到最后，未探测的保持原相对顺序

探测预算：每个频道只测前 N 条（默认 10），总预算默认 800 条 URL，
结果缓存在 data/stream-check/quality-cache.json（7 天有效，失败结果 6 小时）。

用法：
    python scripts/sort_and_clean.py                    # 清测试台 + 排主力源
    python scripts/sort_and_clean.py --clean-only       # 只清测试台（所有 m3u）
    python scripts/sort_and_clean.py --max-probe 10 --budget 800
"""
import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

M3U_DIR = os.path.join(ROOT, "m3u")
MAIN_FILE = os.path.join(M3U_DIR, "bbxx365_hotel.m3u")
CACHE_PATH = os.path.join(ROOT, "data", "stream-check", "quality-cache.json")
FAILURE_PATH = os.path.join(ROOT, "data", "stream-check", "failure-cache.json")

TEST_RE = re.compile(r"(测试|測試|test)", re.I)
# 4K/8K 台只保留本机央视频网关（8767）那几条官方线路；外网那些
# 107.150.x / 山东移动 8089 / 过期 auth_key 的地址在家里网络全连不上，整组清掉。
UHD_RE = re.compile(r"(4K|8K)", re.I)
OFFICIAL_PORT = ":8767"
CACHE_TTL_OK = 7 * 24 * 3600
CACHE_TTL_FAIL = 6 * 3600
FAIL_TTLB = 99999

# 和 stream_check.py 保持一致的"硬失败"口径：只有这类错误才算死链。
# timeout / server_error / other（含 403 区域限制）一律不动，避免把国内可用、
# 海外 CI 连不上的线路误杀。
HARD_REASONS = {"not_found", "connection_error"}
PURGE_FAIL_COUNT = 1          # 硬错误（连接失败/404）与网络位置无关，一次即剔除


# ---------- m3u 解析 ----------
def parse_m3u(path):
    """返回 (header_lines, entries[{'extinf','url'}]）"""
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
                # 其它 # 行（如 #EXTGRP）挂到当前条目
                if pending:
                    pending += "\n" + line
                continue
            if pending:
                entries.append({"extinf": pending, "url": line.strip()})
                pending = None
    return header, entries


def entry_group(e):
    m = re.search(r'group-title="([^"]*)"', e["extinf"])
    return m.group(1).strip() if m else ""


def entry_name(e):
    extinf = e["extinf"].split("\n")[0]
    name = extinf.rsplit(",", 1)[-1].strip()
    if name:
        return name
    m = re.search(r'tvg-name="([^"]*)"', extinf)
    return m.group(1).strip() if m else ""


def write_m3u(path, header, entries):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for h in header or ['#EXTM3U']:
            f.write(h + "\n")
        for e in entries:
            f.write(e["extinf"] + "\n")
            f.write(e["url"] + "\n")
    os.replace(tmp, path)


# ---------- 4K/8K 只留官方线路 ----------
def is_official_uhd(e):
    return OFFICIAL_PORT in e["url"]


def drop_fake_uhd(files, enabled=True):
    removed_total = 0
    if not enabled:
        print("[uhd] 保留全部 4K/8K 线路（不再只认 8767 官方线）")
        return 0
    for path in files:
        if not os.path.exists(path):
            continue
        header, entries = parse_m3u(path)
        keep = [e for e in entries
                if not (UHD_RE.search(entry_name(e)) and not is_official_uhd(e))]
        n = len(entries) - len(keep)
        if n:
            write_m3u(path, header, keep)
            removed_total += n
            print(f"[uhd] {os.path.basename(path)} 去掉非官方 4K/8K 线路 {n} 条")
    print(f"[uhd] 合计去掉非官方 4K/8K 线路 {removed_total} 条")
    return removed_total


# ---------- 测试频道清理 ----------
def clean_tests(files):
    removed_total = 0
    for path in files:
        if not os.path.exists(path):
            continue
        header, entries = parse_m3u(path)
        keep = [e for e in entries if not TEST_RE.search(entry_name(e))]
        n = len(entries) - len(keep)
        if n:
            write_m3u(path, header, keep)
            removed_total += n
            print(f"[clean] {os.path.basename(path)} 去掉测试频道 {n} 条")
    print(f"[clean] 合计去掉测试频道 {removed_total} 条")
    return removed_total


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


def save_cache(cache):
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    cache["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    tmp = CACHE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)
    os.replace(tmp, CACHE_PATH)


def load_failure_cache():
    try:
        with open(FAILURE_PATH, encoding="utf-8") as f:
            d = json.load(f)
            if isinstance(d.get("records"), dict):
                return d
    except Exception:
        pass
    return {"version": 1, "records": {}, "updatedAt": ""}


def save_failure_cache(d):
    os.makedirs(os.path.dirname(FAILURE_PATH), exist_ok=True)
    d["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    tmp = FAILURE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, FAILURE_PATH)


def _iso_now():
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())


def update_failure_state(fail, probed):
    """把本轮探测结果并进失效缓存：成功则销账，硬失败则累计次数。"""
    now = _iso_now()
    for url, rec in probed.items():
        reason = rec.get("reason", "")
        if rec.get("tier", 0) > 0:
            fail["records"].pop(url, None)
            continue
        if reason not in HARD_REASONS:
            continue                     # 超时/5xx/403 不计入死链
        old = fail["records"].get(url) or {}
        fail["records"][url] = {
            "firstFailedAt": old.get("firstFailedAt") or now,
            "lastChecked": now,
            "failCount": int(old.get("failCount", 0)) + 1,
            "reason": reason,
        }


def dead_urls(fail):
    """返回确认死链的 URL 集合（硬失败且累计到阈值）。"""
    out = set()
    for url, rec in fail["records"].items():
        if rec.get("reason") in HARD_REASONS and int(rec.get("failCount", 0)) >= PURGE_FAIL_COUNT:
            out.add(url)
    return out


HOME_RANK_PATH = os.path.join(ROOT, "assets", "home-rank.json")


def load_home_rank():
    """本机实测的排序结果（assets/home-rank.json，由 probe_home_rank.py 在本机生成）。
    有实测的频道，直接按实测顺序排；没有的走海外探测的清晰度排序。"""
    try:
        with open(HOME_RANK_PATH, encoding="utf-8") as f:
            d = json.load(f)
            if isinstance(d.get("channels"), dict):
                return d["channels"]
    except Exception:
        pass
    return {}


def cache_get(cache, url):
    rec = cache["records"].get(url)
    if not rec:
        return None
    age = time.time() - rec.get("at", 0)
    ttl = CACHE_TTL_FAIL if rec.get("tier", 0) <= 0 else CACHE_TTL_OK
    if age > ttl:
        return None
    return rec


# ---------- 探测 ----------
def probe_batch(urls, cache, workers=16):
    from rank_stream import analyze  # 复用已有的质量探测

    def one(u):
        try:
            r = analyze(u, timeout=6)
            return u, {
                "tier": int(r.get("tier", 0)),
                "height": int(r.get("height", 0)),
                "kbps": int(r.get("kbps", 0)),
                "ttfb": int(r.get("ttfb", FAIL_TTLB)),
                "kind": r.get("kind", ""),
                "reason": r.get("reason", ""),
                "at": int(time.time()),
            }
        except Exception:
            return u, {"tier": 0, "height": 0, "kbps": 0, "ttfb": FAIL_TTLB,
                       "kind": "error", "reason": "other", "at": int(time.time())}

    done = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for u, rec in pool.map(one, urls):
            done[u] = rec
            cache["records"][u] = rec
    return done


def score(rec, idx):
    if not rec:
        return (-1, 0, 0, 0, idx)          # 未探测：排在探测过的后面
    tier = rec.get("tier", 0)
    if tier <= 0 and rec.get("kind") in ("dead", "junk", "error"):
        return (-2, 0, 0, 0, idx)          # 死链：垫底
    # 升序排序即可让"清晰度高、码率高、打开快"的排前面
    return (-tier, -rec.get("height", 0), -rec.get("kbps", 0), rec.get("ttfb", FAIL_TTLB), idx)


def sort_file(path, max_probe, budget, cache):
    header, entries = parse_m3u(path)
    if not entries:
        print(f"[sort] {path} 为空，跳过")
        return

    by_name = {}
    for i, e in enumerate(entries):
        # 同一分组内同名频道才互换线路，避免把「酒店央视」的线路挪进「央视频道」组
        by_name.setdefault((entry_group(e), entry_name(e)), []).append(i)

    todo = []
    for key, idxs in by_name.items():
        if len(idxs) < 2:                  # 只有一条线路，没什么可排
            continue
        for i in idxs[:max_probe]:
            url = entries[i]["url"]
            if cache_get(cache, url):
                continue
            if len(todo) < budget:
                todo.append(url)

    print(f"[sort] 待探测 {len(todo)} 条（预算 {budget}，每频道最多 {max_probe} 条）")
    probed = probe_batch(todo, cache) if todo else {}
    save_cache(cache)

    # ---- 死链剔除：硬失败累计两次的地址直接删掉（每频道至少留一条）----
    fail = load_failure_cache()
    update_failure_state(fail, probed)
    save_failure_cache(fail)
    dead = dead_urls(fail)
    if dead:
        keep_idx = set()
        for key, idxs in by_name.items():
            alive = [i for i in idxs if entries[i]["url"] not in dead]
            if not alive:                       # 整组都死了，至少留一条，别让频道消失
                alive = idxs[:1]
            keep_idx.update(alive)
        removed = len(entries) - len(keep_idx)
        if removed:
            print(f"[purge] 剔除死链 {removed} 条（死链池 {len(dead)} 条）")
            entries = [e for i, e in enumerate(entries) if i in keep_idx]
            by_name = {}
            for i, e in enumerate(entries):
                by_name.setdefault((entry_group(e), entry_name(e)), []).append(i)

    home = load_home_rank()
    home_hit = 0
    changed = 0
    for key, idxs in by_name.items():
        if len(idxs) < 2:
            continue
        hkey = "%s|%s" % key
        if hkey in home:
            rank = home[hkey].get("order") or []
            pos = {u: i for i, u in enumerate(rank)}
            order = sorted(idxs, key=lambda i: (pos.get(entries[i]["url"], len(rank) + i)))
            orig = [entries[i] for i in idxs]
            new = [entries[i] for i in order]
            if new != orig:
                changed += 1
            home_hit += 1
            for p_, e_ in zip(idxs, new):
                entries[p_] = e_
            continue
        good, rest = [], []
        for k, i in enumerate(idxs):
            rec = cache_get(cache, entries[i]["url"]) or probed.get(entries[i]["url"])
            # 只"升"不"降"：CI 在海外，超时/失败不代表国内看不了，
            # 没拿到正结果的线路保持原位，绝不因为探测失败被踢下去
            if rec and rec.get("tier", 0) > 0:
                good.append((score(rec, k), i))
            else:
                rest.append(i)
        good.sort(key=lambda x: x[0])
        new_idx = [i for _, i in good] + rest
        orig = [entries[i] for i in idxs]
        new = [entries[i] for i in new_idx]
        if new != orig:
            changed += 1
        for pos, e in zip(idxs, new):
            entries[pos] = e

    write_m3u(path, header, entries)
    sorted_ch = sum(1 for k, i in by_name.items() if len(i) > 1)
    print(f"[sort] {os.path.basename(path)}：{sorted_ch} 个多线路频道，{changed} 个顺序有变化"
          + (f"（其中 {home_hit} 个用了本机实测顺序）" if home_hit else ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=MAIN_FILE, help="要排序的 m3u（默认主力源）")
    ap.add_argument("--max-probe", type=int, default=10, help="每个频道最多探测几条")
    ap.add_argument("--budget", type=int, default=800, help="单次总探测预算（条 URL）")
    ap.add_argument("--drop-uhd", action="store_true", help="去掉非官方(非 :8767)的 4K/8K 线路（默认保留）")
    ap.add_argument("--clean-only", action="store_true", help="只清测试频道，不排序")
    ap.add_argument("--skip-clean", action="store_true", help="只排序，不清测试频道")
    ap.add_argument("--quiet-files", default="", help="逗号分隔，额外要清测试频道的文件")
    args = ap.parse_args()

    targets = [os.path.join(M3U_DIR, f) for f in sorted(os.listdir(M3U_DIR)) if f.endswith(".m3u")] \
        if os.path.isdir(M3U_DIR) else []
    if args.quiet_files:
        targets += [p.strip() for p in args.quiet_files.split(",") if p.strip()]

    if not args.skip_clean:
        clean_tests(targets)
        # 4K/8K 清理默认关闭（用户要求保留所有 4K/8K 线路），需要时加 --drop-uhd
        if getattr(args, "drop_uhd", False):
            drop_fake_uhd([args.file], enabled=False)   # 4K 保留，交给「💓4K频道」分组
    if args.clean_only:
        return

    cache = load_cache()
    sort_file(args.file, args.max_probe, args.budget, cache)


if __name__ == "__main__":
    main()
