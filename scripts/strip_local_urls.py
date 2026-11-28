#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""剔除产物里只在内网/本机可达的播放地址（云端发布用）。

背景：assets/ysp-official.m3u 是从家里 NAS 的央视频网关（192.168.3.101:8767）
导出的，混进云端产物后，外网用户播放器里就是死台。发布前把私有地址段的行
连同它前面的 #EXTINF 等属性行整条去掉。

判定：URL 主机为 10./127./172.16-31./192.168./169.254./localhost 即视为内网。

用法：
    python scripts/strip_local_urls.py m3u/bbxx365_hotel.m3u
    python scripts/strip_local_urls.py "m3u/*.m3u" --dry-run
"""
import argparse
import glob
import ipaddress
import os
import re
import sys
from urllib.parse import urlparse

RE_URL = re.compile(r"^https?://", re.I)


def is_private_host(url):
    try:
        host = (urlparse(url).hostname or "").strip()
    except ValueError:
        return False
    if not host:
        return False
    if host in ("localhost", "localhost.localdomain"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local


def strip_file(path, dry_run=False):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    trailing_nl = text.endswith("\n")
    lines = text.split("\n")
    if trailing_nl and lines and lines[-1] == "":
        lines = lines[:-1]

    out = []
    pending = []      # 已累积的 # 开头属性行（#EXTINF/#EXTGRP/#EXTVLCOPT…）
    dropped = 0

    for line in lines:
        s = line.strip()
        if RE_URL.match(s):
            if is_private_host(s):
                dropped += 1
                pending = []
                continue
            out.extend(pending)
            pending = []
            out.append(line)
        elif s.startswith("#"):
            pending.append(line)
        elif s == "":
            out.extend(pending)
            pending = []
            out.append(line)
        else:
            # 既不是 URL 也不是注释：原样保留
            out.extend(pending)
            pending = []
            out.append(line)

    if pending:
        out.extend(pending)

    if not dry_run and dropped:
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(out) + ("\n" if trailing_nl else ""))

    kept = sum(1 for l in out if l.startswith("#EXTINF"))
    return dropped, kept


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("targets", nargs="+")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    files = []
    for t in args.targets:
        files.extend(sorted(glob.glob(t)))
    total = 0
    for p in files:
        if not os.path.isfile(p):
            continue
        dropped, kept = strip_file(p, args.dry_run)
        total += dropped
        print(f"[strip] {os.path.basename(p)}：剔除 {dropped} 条内网地址，剩 {kept} 条")
    print(f"[strip] 合计剔除 {total} 条{'（dry-run 未写回）' if args.dry_run else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
