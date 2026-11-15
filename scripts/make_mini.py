#!/usr/bin/env python3
"""从 hotel 版 m3u 生成「必看频道」的精编版本。

用法：
    python3 scripts/make_mini.py --verify            # 每频道 5 条，按直播/画质/速度排序
    python3 scripts/make_mini.py --verify --per 3    # 改每频道保留条数

规则：
1. 只保留白名单分组（央视/卫视/专享/4K/国际台）
2. 只留真直播：剔除点播(ENDLIST/VOD)、mp4、网页链接
3. 同频道内按 画质档位 → 首字节耗时 排序，取最快的几条
4. 剔除会被国内托管判违规的域名
输入 m3u/bbxx365_hotel.m3u，输出 m3u/bbxx365_mini.m3u
"""
import concurrent.futures
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SRC = "m3u/bbxx365_hotel.m3u"
OUT = "m3u/bbxx365_mini.m3u"
CANDIDATES = 6    # 每频道最多探测的候选数

GROUPS = {
    "❤️央视频道", "❤️卫视频道", "❤️专享央视", "❤️专享卫视",
    "💓4K(Auto)", "💕国际台",
}

# 分组在文件里的出场顺序（集合本身无序，必须显式写死）：央视打头
GROUP_ORDER = ["❤️央视频道", "❤️专享央视", "❤️卫视频道", "❤️专享卫视",
               "💓4K(Auto)", "💕国际台"]

BAD_URL = ("kwimgs.com", "jiduo.me", "kwai")

# 名字里带这些的，基本不是真频道：移动传媒、购物台、测试台、轮播台——进去常年放广告
BAD_NAME = ("测试", "移动传媒", "轮播", "广告", "试播", "Demo", "demo")


# ① 云上测速不可信：改成按「源的类型」打分，优先国内基础设施/CDN，降权裸 IP 小盒子。
HIGH_HINTS = (
    "migu", "cmcc", "chinaunicom", "chinanet", "chinatelecom", "bestv", "gotvt",
    "newcntv", "qcloudcdn", "myqcloud", "aliyuncs", "aliyun", "hwclouds",
    "myhuaweicloud", "ks-cdn", "tptv", "wasu", "jomodns", "cdntip", "zgdns",
)
GOOD_PORT = ("", "80", "443", "1935", "554", "8080", "8443", "9999")
_IPV4 = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")


def source_score(url, tier=0):
    from urllib.parse import urlparse
    p = urlparse(url)
    host, port, scheme = (p.hostname or "").lower(), str(p.port or ""), p.scheme
    score = tier * 2                     # 画质档位仍作为加分项
    if any(h in host for h in HIGH_HINTS):
        score += 4                       # 咪咕/运营商 CDN/腾讯云这级别
    if _IPV4.match(host):
        score -= 2                       # 裸 IP 多为个人盒子，跨省不稳
    if scheme == "https":
        score += 1
    if port and port not in GOOD_PORT:
        score -= 1
    return score


def parse(path):
    lines = open(path, encoding="utf-8").read().splitlines()
    entries, i = [], 0
    while i < len(lines):
        if lines[i].strip().startswith("#EXTINF"):
            j = i + 1
            while j < len(lines) and lines[j].strip().startswith("#"):
                j += 1
            if j < len(lines):
                entries.append((lines[i].strip(), lines[j].strip()))
            i = j + 1
        else:
            i += 1
    return entries


def main() -> int:
    per = 5
    if "--per" in sys.argv:
        per = int(sys.argv[sys.argv.index("--per") + 1])
    verify = "--verify" in sys.argv

    if not os.path.exists(SRC):
        print(f"缺少 {SRC}，先跑 merge_bbxx365_hotel.py")
        return 1

    grp_re = re.compile(r'group-title="([^"]*)"')
    buckets = {}
    for extinf, url in parse(SRC):
        if not url or any(b in url for b in BAD_URL):
            continue
        m = grp_re.search(extinf)
        g = m.group(1) if m else ""
        if g not in GROUPS:
            continue
        name = extinf.split(",", 1)[1].strip() if "," in extinf else extinf
        if any(b in name for b in BAD_NAME):
            continue
        lst = buckets.setdefault((g, name), [])
        if len(lst) < CANDIDATES and url not in [u for _, u in lst]:
            lst.append((extinf, url))

    order = GROUP_ORDER

    def name_key(k):
        """央视按编号排：CCTV1、CCTV2…CCTV17，纯 CCTV1 优先于 CCTV1高清；CCTV+ 等排最后。"""
        n = k[1]
        m = re.search(r"CCTV\s*[-－—]?\s*(\d+)", n, re.I)
        if m:
            return (order.index(k[0]), 0, int(m.group(1)), len(n), n)
        return (order.index(k[0]), 1, 999, len(n), n)

    keys = sorted(buckets, key=name_key)

    if not verify:
        out = ["#EXTM3U"]
        for k in keys:
            for extinf, url in buckets[k][:per]:
                out += [extinf, url]
        open(OUT, "w", encoding="utf-8").write("\n".join(out) + "\n")
        print(f"{OUT}: {len(out) // 2} 条 / {os.path.getsize(OUT) // 1024}KB")
        return 0

    from rank_stream import analyze

    flat = [(k, extinf, url) for k in keys for extinf, url in buckets[k]]
    with concurrent.futures.ThreadPoolExecutor(40) as ex:
        info = list(ex.map(lambda t: analyze(t[2]), flat))

    picked, stat = {}, {}
    for (k, extinf, url), d in zip(flat, info):
        stat[d["kind"]] = stat.get(d["kind"], 0) + 1
        # 不在这里砍掉：云上探测（海外 IP）会把国内源误判成 dead，
        # 保留它们做兜底，只在排序上排在直播源后面。
        if d["kind"] in ("vod", "mp4", "junk"):
            continue
        picked.setdefault(k, []).append((d, extinf, url))

    out, used = ["#EXTM3U"], set()
    for k in keys:
        # ③ 不按测速排（云上测出来的速度不等于用户家里的速度）：
        # 真直播优先，其次按源类型打分，同分保持原顺序交给播放器自己切换。
        items = sorted(
            picked.get(k, []),
            key=lambda t: (0 if t[0]["kind"] == "live" else 1,
                           -source_score(t[2], t[0].get("tier", 0)),
                           t[0]["ttfb"]),
        )
        kept = 0
        for d, extinf, url in items:
            if kept >= per or url in used:
                continue
            out += [extinf, url]
            used.add(url)
            kept += 1

    open(OUT, "w", encoding="utf-8").write("\n".join(out) + "\n")
    print(f"{OUT}: {len(out) // 2} 条 / {os.path.getsize(OUT) // 1024}KB / 探测 {stat}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
