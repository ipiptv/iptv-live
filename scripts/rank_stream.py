#!/usr/bin/env python3
"""衡量一条流的质量，用于给同一个频道挑「又快又高清」的线路。

返回 dict：
  kind   live / vod / mp4 / junk / dead
  ttfb   拉取播放列表的首字节耗时（毫秒），越小越快打开
  height 分辨率高度（1080/720/480…），拿不到为 0
  kbps   估算码率（kbps），拿不到为 0
"""
import re
import ssl
import time
import urllib.request

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE
UA = "AptvPlayer/1.0"
JUNK_HOSTS = ("youtube.com", "youtu.be", "twitch.tv", "bilibili.com/video")

_RES = re.compile(r"RESOLUTION=\d+x(\d+)", re.I)
_BW = re.compile(r"BANDWIDTH=(\d+)", re.I)
_EXT = re.compile(r"#EXTINF:([\d.]+)")


def _get(url, timeout, read_bytes=65536):
    t0 = time.monotonic()
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    r = urllib.request.urlopen(req, timeout=timeout, context=_CTX)
    t_ttfb = (time.monotonic() - t0) * 1000
    body = r.read(read_bytes).decode("utf-8", "ignore")
    return body, t_ttfb, r.headers


def _first_segment(body):
    for ln in body.splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("#"):
            return ln
    return None


def analyze(url, timeout=6):
    low = url.lower()
    if low.split("?")[0].endswith(".mp4"):
        return {"kind": "mp4", "ttfb": 0, "height": 0, "kbps": 0}
    if any(h in low for h in JUNK_HOSTS):
        return {"kind": "junk", "ttfb": 0, "height": 0, "kbps": 0}
    try:
        body, ttfb, _ = _get(url, timeout)
    except Exception:
        return {"kind": "dead", "ttfb": 99999, "height": 0, "kbps": 0}

    if "#EXT-X-ENDLIST" in body or "PLAYLIST-TYPE:VOD" in body.upper():
        return {"kind": "vod", "ttfb": ttfb, "height": 0, "kbps": 0}
    if "#EXTINF" not in body and "#EXTM3U" not in body:
        return {"kind": "junk", "ttfb": ttfb, "height": 0, "kbps": 0}

    height, kbps = 0, 0
    if "#EXT-X-STREAM-INF" in body:              # 主播放列表，直接有分辨率/码率
        hs = [int(x) for x in _RES.findall(body)]
        bs = [int(x) for x in _BW.findall(body)]
        height = max(hs) if hs else 0
        kbps = max(bs) // 1000 if bs else 0
    else:                                        # 媒体播放列表，用首片大小估码率
        seg = _first_segment(body)
        dur = float(_EXT.search(body).group(1)) if _EXT.search(body) else 0
        if seg and dur:
            try:
                seg_url = seg if seg.startswith("http") else urllib.request.urljoin(url, seg)
                req = urllib.request.Request(seg_url, headers={"User-Agent": UA, "Range": "bytes=0-0"})
                t0 = time.monotonic()
                r = urllib.request.urlopen(req, timeout=timeout, context=_CTX)
                r.read(1)
                ttfb = min(ttfb, (time.monotonic() - t0) * 1000)
                cl = r.headers.get("Content-Range", "")
                total = int(cl.split("/")[-1]) if "/" in cl else int(r.headers.get("Content-Length") or 0)
                if total and dur:
                    kbps = int(total * 8 / dur / 1000)
            except Exception:
                pass

    if height >= 2000:
        tier = 4
    elif height >= 1000:
        tier = 3
    elif height >= 700:
        tier = 2
    elif height:
        tier = 1
    else:                                        # 拿不到分辨率，用码率估
        tier = 4 if kbps >= 4000 else 3 if kbps >= 2000 else 2 if kbps >= 1000 else 1 if kbps else 0

    return {"kind": "live", "ttfb": int(ttfb), "height": height, "kbps": kbps, "tier": tier}
