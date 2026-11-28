#!/usr/bin/env python3
"""按 group-title 整组剔除频道（默认删「少儿」「咪咕」两类分组）"""
import sys, os, re, glob
from collections import Counter

PATTERNS = [p.strip() for p in os.environ.get("DROP_PATTERNS", "少儿,咪咕").split(",") if p.strip()]

def process(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.read().split("\n")
    out, removed, i = [], Counter(), 0
    while i < len(lines):
        l = lines[i]
        if not l.startswith("#EXTINF"):
            out.append(l); i += 1; continue
        blk, j = [l], i + 1
        while j < len(lines) and not lines[j].startswith("http") and not lines[j].startswith("#EXTINF"):
            if lines[j].strip():
                blk.append(lines[j])
            j += 1
        if j < len(lines) and lines[j].startswith("http"):
            blk.append(lines[j]); j += 1
        g = re.search(r'group-title="([^"]*)"', l)
        grp = g.group(1) if g else ""
        if any(p in grp for p in PATTERNS):
            removed[grp] += 1
            i = j; continue
        out.extend(blk); i = j
    if removed:
        while out and out[-1] == "":
            out.pop()
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(out) + "\n")
    return removed

total = Counter()
targets = []
for a in sys.argv[1:]:
    targets.extend(sorted(glob.glob(a)))
for p in targets:
    r = process(p)
    if r:
        n = sum(r.values())
        total.update(r)
        print("{} 剔除 {} 条：{}".format(os.path.basename(p), n, dict(r)))
print("合计剔除", sum(total.values()), "条：", dict(total))
