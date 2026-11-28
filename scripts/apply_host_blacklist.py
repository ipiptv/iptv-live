#!/usr/bin/env python3
"""按主机名整条剔除（主机清单见 assets/blacklist_hosts.txt）"""
import sys, os, glob
from urllib.parse import urlparse

def load_blacklist():
    cands = [os.environ.get("HOST_BLACKLIST", ""), "assets/blacklist_hosts.txt",
             os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "blacklist_hosts.txt")]
    for p in cands:
        if p and os.path.exists(p):
            bl = set()
            with open(p, encoding="utf-8") as f:
                for line in f:
                    line = line.split("#")[0].strip().lower()
                    if line:
                        bl.add(line)
            return bl, p
    raise SystemExit("找不到 blacklist_hosts.txt")

def process(path, bl):
    L = open(path, encoding="utf-8", errors="replace").read().split("\n")
    out, removed, i = [], 0, 0
    while i < len(L):
        l = L[i]
        if not l.startswith("#EXTINF"):
            out.append(l); i += 1; continue
        blk, j = [l], i + 1
        while j < len(L) and not L[j].startswith("http") and not L[j].startswith("#EXTINF"):
            if L[j].strip():
                blk.append(L[j])
            j += 1
        if j < len(L) and L[j].startswith("http"):
            blk.append(L[j]); j += 1
        host = (urlparse(blk[-1]).hostname or "").lower()
        if host in bl:
            removed += 1; i = j; continue
        out.extend(blk); i = j
    if removed:
        while out and out[-1] == "":
            out.pop()
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(out) + "\n")
    return removed

bl, src = load_blacklist()
total = 0
for a in sys.argv[1:]:
    for p in sorted(glob.glob(a)):
        r = process(p, bl)
        total += r
        if r:
            print("{} 剔除 {} 条（主机黑名单）".format(os.path.basename(p), r))
print("合计剔除 {} 条，黑名单 {} 个主机".format(total, len(bl)))
