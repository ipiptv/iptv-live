#!/usr/bin/env python3
"""把成品 m3u 的 #EXTM3U 头 x-tvg-url 指到家里自建的 EPG xml"""
import sys, os, re, glob

OUT = sys.argv[1] if len(sys.argv) > 1 else "/vol1/iptv/out"
URLS = [
    "http://fhh-home.dynv6.net:18080/epg/cc.xml",
    "http://fhh-home.dynv6.net:18080/epg/difang.xml",
    "http://fhh-home.dynv6.net:18080/epg/e.xml",
    "http://fhh-home.dynv6.net:18080/epg/gat.xml",
]

def fix(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.read().split("\n")
    if not lines or not lines[0].startswith("#EXTM3U"):
        return False
    attrs = [a for a in re.split(r"\s+", lines[0]) if a and not a.lower().startswith("x-tvg-url=")]
    lines[0] = " ".join(attrs) + ' x-tvg-url="' + ",".join(URLS) + '"'
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return True

ok = 0
for p in sorted(glob.glob(os.path.join(OUT, "bbxx365*.m3u"))):
    if fix(p):
        ok += 1
        print("改", os.path.basename(p))
    else:
        print("跳过", os.path.basename(p))
print("共改", ok, "个文件")
