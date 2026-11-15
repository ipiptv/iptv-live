#!/usr/bin/env python3
"""探测一个 m3u8 地址是「真直播」还是「点播片子 / 失效」。

返回：
  live   —— 直播型 m3u8（没有 ENDLIST，媒体序列会滚动）
  vod    —— 点播：plist 带 #EXT-X-ENDLIST 或声明 PLAYLIST-TYPE:VOD，播完就停/每次从头
  mp4    —— 直接是 mp4 文件，必然是点播
  junk   —— 网页链接（youtube 等）或非 HLS 内容
  dead   —— 连不上 / 超时 / 4xx5xx
"""
import ssl
import urllib.request

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE
UA = "AptvPlayer/1.0"
JUNK_HOSTS = ("youtube.com", "youtu.be", "twitch.tv", "bilibili.com/video")


def classify(url, timeout=6):
    low = url.lower()
    if low.split("?")[0].endswith(".mp4"):
        return "mp4"
    if any(h in low for h in JUNK_HOSTS):
        return "junk"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
            body = r.read(65536).decode("utf-8", "ignore")
    except Exception:
        return "dead"
    if "#EXT-X-ENDLIST" in body or "PLAYLIST-TYPE:VOD" in body.upper().replace(" ", ""):
        return "vod"
    if "#EXTINF" in body or "#EXTM3U" in body:
        return "live"
    return "junk"
