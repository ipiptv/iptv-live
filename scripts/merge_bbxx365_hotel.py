#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 bbxx365 源与 hotel_tvn 源按白名单合并成一个 m3u。

输入（均由同一次流水线的前序步骤生成，不依赖任何外部站点）：
    m3u/bbxx365.m3u    <- main.py 生成
    m3u/hotel_tvn.m3u  <- pnpm m3u 生成（可能不存在，缺失时跳过酒店源部分）
输出：
    m3u/bbxx365_hotel.m3u

用法：python scripts/merge_bbxx365_hotel.py
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BBXX = os.path.join(ROOT, "m3u", "bbxx365.m3u")
HOTEL = os.path.join(ROOT, "m3u", "hotel_tvn.m3u")
OUT = os.path.join(ROOT, "m3u", "bbxx365_hotel.m3u")
OTT_OUT = os.path.join(ROOT, "m3u", "bbxx365_ott.m3u")

HEADER = '#EXTM3U x-tvg-url="https://live.fanmingming.cn/e.xml,https://tv.whyun.com/epg/51zmt.xml"\n'

# ottiptv 付费订阅源：需要 UA=qqlive 才能播，缓存到 m3u/ottiptv.m3u 供下次兜底
# 订阅地址含账号凭证，不能写进公开仓库：优先读环境变量 OTT_SUB_URL（云端用 GitHub Secret），
# 本地可放在 data/ott_sub_url.txt（已 gitignore）
OTT_URL_FILE = os.path.join(ROOT, "data", "ott_sub_url.txt")
OTT_CACHE = os.path.join(ROOT, "m3u", "ottiptv.m3u")
OTT_UA = "qqlive"
OTT_PREFIX = "🎯"


def ott_sub_url():
    url = os.environ.get("OTT_SUB_URL", "").strip()
    if url:
        return url
    if os.path.exists(OTT_URL_FILE):
        try:
            with open(OTT_URL_FILE, "r", encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            pass
    return ""

# 更新时间分组只保留一条，播放地址固定为这个
UPDATE_URL = (
    "https://txmov2.a.kwimgs.com/upic/2024/01/09/12/"
    "BMjAyNDAxMDkxMjA2MDdfMzQ4MzI0MjA1OF8xMjE2Nzg4Mjk4NTZfMF8z_b_"
    "Bc9f7d3b0c4b69136e61d8328a8538bd2.mp4?clientCacheKey=3xajh8b4u5j6uva_b.mp4"
)

# 主力源最终保留的分组（其余一律不输出）
TARGET_ORDER = [
    "❤️央视频道",
    "❤️卫视频道",
    "💓少儿频道",
    "🏨酒店央视",
    "🏨酒店卫视",
    "❤️更新时间",
]

# 酒店源单独成组（只放它的央视/卫视，其他频道（HOTEL_GROUPS 里的“其他频道”）不要）
HOTEL_CCTV_GROUP = "🏨酒店央视"
HOTEL_SAT_GROUP = "🏨酒店卫视"
HOTEL_TARGETS = (HOTEL_CCTV_GROUP, HOTEL_SAT_GROUP)

# 按台名归类（上游 bbxx365 的分组名很乱，央视/卫视常被塞进“电视剧”之类，
# 酒店源又把央视/卫视/其他分开成组，所以统一按台名判断，不看来源分组）
RE_4K = re.compile(r'(4K|UHD|2160|超高清)', re.I)
RE_KID = re.compile(r'(儿童|少儿|卡通|动漫|CCTV[\-—]?1[4４]|卡酷|金鹰卡通|优漫|嘉佳|哈哈|炫动|小当家|亲子|宝宝|贝贝|动画)', re.I)
RE_CCTV = re.compile(r'^(CCTV|CGTN|央视|中央)', re.I)
# CCTV-14 单独回央视组（它本质是央视频道，只是名字里带“少儿”）
RE_CCTV14 = re.compile(r'^CCTV[\-—\s]?1[4４]', re.I)
# 国内少儿台白名单：只认这些，境外的（Cartoon Network/Baby TV/Nickelodeon/迪士尼、
# 台湾的东森幼幼、靖天卡通，以及聚合站拼出来的“儿童|xxx”点播剧名）全部不要。
RE_KID_DOMESTIC = re.compile(
    r'(少儿|金鹰卡通|卡酷|优漫|嘉佳卡通|哈哈炫动|炫动卡通|动漫秀场|新动漫|北京卡通|'
    r'家庭少儿|成长少儿|亲子|宝贝|宝宝|贝贝|酷卡|快乐卡通|动漫|动画)',
    re.I,
)
# 境外/非国内少儿台的特征词，命中就丢
RE_KID_FOREIGN = re.compile(
    r'(Cartoon ?Network|Baby ?TV|CBeebies|Nickelodeon|Nick ?Jr|Disney|迪士尼|Animax|'
    r'3ABN|Japanim|Kuriakos|MOMO|靖天|東森|东森|幼幼|Cartoonito|Boomerang|Tooncast|'
    r'\bKids\b|BabyFirst|First ?Kids)',
    re.I,
)
# 聚合站的点播剧名（“名侦探柯南”“熊出没”这类挂着儿童剧目的假台）
RE_KID_EPISODE = re.compile(
    r'(名侦探柯南|熊出没|海绵宝宝|中华小当家|双月之城|萌鸡小队|宇宙护卫队|黑莓动画|'
    r'猫和老鼠|小猪佩奇|汪汪队|奥特曼|数码宝贝|灌篮高手|火影忍者|海贼王|'
    r'精选动漫|经典动漫|动漫精选|热门动漫)',
    re.I,
)
# 儿童组走白名单：只保留国内的少儿/卡通台。聚合站生成的“儿童|xxx”、境外台
# （3ABN Kids / Japanim TV / Kuriakos Kids / MOMO亲子 / 靖天卡通）和剧集点播（
# 名侦探柯南、熊出没、海绵宝宝这类）实测都播不了或不稳定，一律不要。
RE_KID_KEEP = re.compile(r'(CCTV[\-—]?1[4４]|CCTV少儿|金鹰卡通|嘉佳卡通|动漫秀场|优漫卡通|卡酷|哈哈炫动|炫动卡通|新动漫|北京卡通|少儿|少儿家庭)', re.I)
RE_SAT = re.compile(r'卫视', re.I)
RE_GROUP_4K = re.compile(r'(4K|UHD|2160)', re.I)
RE_GROUP_KID = re.compile(r'(儿童|少儿|卡通)', re.I)
RE_GROUP_CCTV = re.compile(r'央视', re.I)
RE_GROUP_SAT = re.compile(r'卫视', re.I)
RE_GROUP_UPDATE = re.compile(r'更新时间')
# 公共/广告垫播通道：同一主机下多台共用同一路信号（实测浙江卫视首条源播的就是广告），
# 特征是路径里带 pub 段（如 gslb/dsdqpub/xxx.m3u8?auth=testpub）。注意 dsdqbv 那套
# （auth=test20251009）是各台独立的正式线路，不能一起误杀。
RE_PUB_URL = re.compile(r'(dsdqpub|\.pub|/pub/)', re.I)
URL_KEY_RE = re.compile(r'(https?://[^/]+/[^?]*)', re.I)
HOST_RE = re.compile(r'https?://([^/:]+)', re.I)

# 手工拉黑的主机（一行一个，可用 # 注释），放在 data/host-blocklist.txt
HOST_BLOCKLIST_FILE = os.path.join(ROOT, "data", "host-blocklist.txt")
# 境外 4K（不属于央视/卫视，也没有对应分组）直接丢弃
RE_FOREIGN_4K = re.compile(r'(Love Nature|Nature|Discovery|Nat Geo|National Geographic|BBC|Insight|Travel)', re.I)
# 4K 后缀剥掉后再判断归属：CCTV4K → 央视，北京卫视4K/河北4K → 卫视
RE_4K_SUFFIX = re.compile(r'(4K|4k|UHD|2160P?|超高清)', re.I)
REGION_WORDS = (
    "北京", "上海", "天津", "重庆", "河北", "山西", "辽宁", "吉林", "黑龙江", "江苏",
    "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南", "广东", "广西",
    "海南", "四川", "贵州", "云南", "陕西", "甘肃", "青海", "内蒙古", "宁夏", "新疆",
    "西藏", "苏州", "深圳", "南国都市", "无锡", "常州", "南京", "杭州", "青岛", "大连",
    "厦门", "宁波", "成都", "武汉", "西安", "长沙", "郑州", "合肥", "昆明", "贵阳",
    "太原", "济南", "石家庄", "哈尔滨", "沈阳", "长春", "福州", "南宁", "海口",
)

HOTEL_GROUPS = ["央视频道", "卫视频道", "其他频道"]

GROUP_RE = re.compile(r'group-title="([^"]*)"')

def read_lines(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read().splitlines()


def get_group(line):
    m = GROUP_RE.search(line)
    return m.group(1) if m else ""


def set_group(line, name):
    if GROUP_RE.search(line):
        return GROUP_RE.sub('group-title="%s"' % name, line, count=1)
    return line.replace("#EXTINF:-1", '#EXTINF:-1 group-title="%s"' % name, 1)


def match_group(group_title):
    for idx, (keyword, new_name) in enumerate(GROUPS):
        if keyword.lower() in group_title.lower():
            return idx, new_name
    return -1, None


def name_group(extinf):
    """按台名归到央视/卫视组，匹配不到返回 (-1, None)。"""
    name = channel_name(extinf)
    cctv_idx = next(i for i, (k, _) in enumerate(GROUPS) if k == "央视频道")
    sat_idx = next(i for i, (k, _) in enumerate(GROUPS) if k == "卫视频道")
    if CCTV_NAME_RE.match(name):
        return cctv_idx, "❤️央视频道"
    if SATELLITE_NAME_RE.search(name):
        return sat_idx, "❤️卫视频道"
    return -1, None


def classify(extinf, source="bbxx"):
    """按台名 + 来源分组名归到目标分组，归不进去返回 None（直接丢弃）。

    4K 频道不再单独成堆：剥掉 4K 后缀先看它本来是哪个台——
    CCTV4K 归央视，北京卫视4K / 河北4K / 苏州4K 这类带地名的归卫视，
    境外 4K（Love Nature 之类）没有归属，直接丢弃；4K 组不再保留。

    source="hotel" 时只认央视/卫视，分别进酒店专用的两组；酒店源的“其他频道”不要。
    """
    name = channel_name(extinf)
    group = get_group(extinf)
    is_4k = bool(RE_4K.search(name) or RE_GROUP_4K.search(group))
    base = RE_4K_SUFFIX.sub("", name).strip()

    is_cctv = bool(
        RE_CCTV14.match(base)
        or RE_CCTV14.match(name)
        or RE_CCTV.match(base)
        or RE_CCTV.match(name)
        or RE_GROUP_CCTV.search(group)
    )
    is_sat = bool(
        RE_SAT.search(name)
        or RE_SAT.search(base)
        or RE_GROUP_SAT.search(group)
    )

    if source == "hotel":
        # 酒店源：央视 → 酒店央视，卫视 → 酒店卫视；其他频道一律不要
        if is_cctv:
            return HOTEL_CCTV_GROUP
        if is_sat:
            return HOTEL_SAT_GROUP
        if is_4k and RE_FOREIGN_4K.search(name):
            return None
        return None

    # 少儿类：CCTV14 回央视；国内少儿台进“少儿频道”；境外/点播剧名丢掉
    if RE_KID.search(name) or RE_KID.search(base) or RE_GROUP_KID.search(group):
        if RE_CCTV14.match(base) or RE_CCTV14.match(name):
            return "❤️央视频道"
        if (
            RE_KID_FOREIGN.search(name)
            or RE_KID_EPISODE.search(name)
            or "|" in name
            or not (RE_KID_DOMESTIC.search(name) or RE_KID_DOMESTIC.search(base))
        ):
            return None
        return "💓少儿频道"

    if is_cctv:
        return "❤️央视频道"
    if is_sat:
        return "❤️卫视频道"
    if is_4k and base and len(base) <= 6 and any(w in base for w in REGION_WORDS):
        # 只有“带地名的 4K 台”（北京4K/河北4K/苏州4K）才按卫视处理，
        # 普通地方台不要被这条规则误拉进卫视组
        return "❤️卫视频道"
    if is_4k:
        # 4K 组取消：境外 4K（Love Nature 之类）直接丢，其余 4K 都并入卫视组
        if RE_FOREIGN_4K.search(name):
            return None
        return "❤️卫视频道"
    if RE_GROUP_UPDATE.search(group):
        return "❤️更新时间"
    return None


def load_host_blocklist():
    hosts = set()
    if os.path.exists(HOST_BLOCKLIST_FILE):
        for line in open(HOST_BLOCKLIST_FILE, encoding="utf-8"):
            line = line.strip().lower()
            if line and not line.startswith("#"):
                hosts.add(line)
    return hosts


def spam_hosts(extinf_urls, threshold=8):
    """整机拉黑：某个主机下“同一条路径”挂了 >=threshold 个不同台。

    这类主机就是一台机器只放一路（或几路）公共信号，靠 URL 参数冒充上百个台，
    实测拉下来不同台是同一段切片，播的是广告/垫播。整机拉黑最干净。
    """
    paths = {}
    for name, url in extinf_urls:
        m = URL_KEY_RE.match(url)
        h = HOST_RE.match(url)
        if not (m and h):
            continue
        paths.setdefault(m.group(1).lower(), set()).add(name)
    bad = set()
    for key, teams in paths.items():
        if len(teams) >= threshold:
            m = HOST_RE.match(key)
            if m:
                bad.add(m.group(1).lower())
    return bad


def shared_paths(extinf_urls, threshold=3):
    """找出被 >=threshold 个不同台名共用的 host+path。

    实测 63.141.230.178:82/gslb/zbdq5.m3u8 这同一个路径被 75 个台挂着，只靠 id 参数
    区分，拉下来 cctv1 和 zjwshd 全是同一段切片（byt/segment_30399.ts），播的是广告。
    这类“一台地址挂几十个台”的公共垫播流统一判掉。
    """
    seen = {}
    for name, url in extinf_urls:
        m = URL_KEY_RE.match(url)
        if not m:
            continue
        seen.setdefault(m.group(1).lower(), set()).add(name)
    return {k for k, v in seen.items() if len(v) >= threshold}


def collect(lines, source="bbxx", shared=frozenset(), blocked_hosts=frozenset()):
    """把一份 m3u 的条目按目标分组收进来，返回 {分组: [(extinf, url)]}。"""
    buckets = {g: [] for g in TARGET_ORDER}
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("#EXTINF"):
            url = lines[i + 1] if i + 1 < len(lines) else ""
            target = classify(line, source)
            key = URL_KEY_RE.match(url)
            hm = HOST_RE.match(url)
            if target and (
                RE_PUB_URL.search(url)
                or (key and key.group(1).lower() in shared)
                or (hm and hm.group(1).lower() in blocked_hosts)
            ):
                target = None
            if target:
                buckets[target].append((set_group(line, target), url))
            i += 2
        else:
            i += 1
    return buckets


def merge_and_dedupe(bucket_list):
    """多份来源合并：同一分组内「同名+同址」只留一条；跨分组同名只留优先组里的。

    酒店两组例外：它们本来就是同一批台单独再放一份，不参与跨组“抢台名”。
    """
    merged = {g: [] for g in TARGET_ORDER}
    for buckets in bucket_list:
        for g in TARGET_ORDER:
            merged[g].extend(buckets[g])

    result = {g: [] for g in TARGET_ORDER}
    claimed = set()
    for g in TARGET_ORDER:
        if g == "❤️更新时间":
            # 更新时间只留一条，播放地址固定
            if merged[g]:
                first = merged[g][0][0]
                result[g] = [(first, UPDATE_URL)]
            continue
        is_hotel = g in HOTEL_TARGETS
        seen = set()
        out = []
        for extinf, url in merged[g]:
            name = channel_name(extinf)
            if not is_hotel and name in claimed:
                continue
            key = (name, url)
            if key in seen:
                continue
            seen.add(key)
            out.append((extinf, url))
        result[g] = out
        if not is_hotel:
            claimed |= {channel_name(e) for e, _ in out}
    return result


def channel_name(extinf):
    return extinf.split(",", 1)[1].strip() if "," in extinf else extinf


def fetch_ott():
    """抓 ottiptv 订阅；失败时回退到上次缓存。返回行列表或 None。"""
    import urllib.request

    url = ott_sub_url()
    if not url or not url.lower().startswith(("http://", "https://")):
        print(
            "警告：OTT_SUB_URL 未配置或不是完整网址（当前长度 %d），跳过付费源拉取" % len(url),
            file=sys.stderr,
        )
        if os.path.exists(OTT_CACHE) and os.path.getsize(OTT_CACHE) > 0:
            print("使用缓存 %s" % OTT_CACHE, file=sys.stderr)
            return read_lines(OTT_CACHE)
        return None

    req = urllib.request.Request(url, headers={"User-Agent": OTT_UA})
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = resp.read().decode("utf-8", "ignore")
        if "#EXTINF" not in data:
            raise ValueError("返回内容不是 m3u")
        os.makedirs(os.path.dirname(OTT_CACHE), exist_ok=True)
        with open(OTT_CACHE, "w", encoding="utf-8") as f:
            f.write(data)
        print("ottiptv 拉取成功：%d 字节" % len(data.encode("utf-8")))
        return data.splitlines()
    except Exception as exc:
        print("警告：ottiptv 拉取失败（%s），尝试使用缓存" % exc, file=sys.stderr)
        if os.path.exists(OTT_CACHE) and os.path.getsize(OTT_CACHE) > 0:
            print("使用缓存 %s" % OTT_CACHE, file=sys.stderr)
            return read_lines(OTT_CACHE)
        return None


def build_ott(lines):
    """按原分组归桶，分组名统一加 🎯 前缀；每条注入 UA，避免播放器手动设置。"""
    buckets = {}
    order = []
    i = 0
    while i < len(lines):
        if lines[i].startswith("#EXTINF"):
            extinf = lines[i]
            j = i + 1
            while j < len(lines) and lines[j].startswith("#"):
                j += 1
            if j < len(lines):
                url = lines[j].strip()
                if url.startswith("http"):
                    group = get_group(extinf) or "其他"
                    target = OTT_PREFIX + group
                    if target not in buckets:
                        buckets[target] = []
                        order.append(target)
                    buckets[target].append(
                        (
                            set_group(extinf, target)
                            + (
                                "\n#EXTVLCOPT:http-user-agent=" + OTT_UA
                                if os.environ.get("OTT_UA_INJECT", "0") != "0"
                                else ""
                            ),
                            url,
                        )
                    )
                i = j + 1
                continue
        i += 1
    return buckets, order


def dedupe_buckets(buckets):
    """按目标分组去重。

    1) 同一分组内「同名 + 同址」重复的只保留一条（同一个网址只出现一次）；
    2) 跨分组同名的频道只保留在优先级最高的分组里（GROUPS 顺序即优先级，
       例如 CCTV4K 同时出现在 4K 组与央视组时，只留在央视组）。
    同一频道在同一分组内的多条不同地址全部保留（那是备选源，不是重复）。
    """
    merged = {}
    order = []
    for idx, (_, target) in enumerate(GROUPS):
        if target not in merged:
            merged[target] = []
            order.append(target)
        merged[target].extend(buckets[idx])

    result = {target: [] for target in order}
    claimed_prev = set()
    for target in order:
        seen_key = set()
        out = []
        for extinf, url in merged[target]:
            name = channel_name(extinf)
            if name in claimed_prev:
                continue
            key = (name, url)
            if key in seen_key:
                continue
            seen_key.add(key)
            out.append((extinf, url))
        result[target] = out
        claimed_prev |= {channel_name(e) for e, _ in out}
    return result, order


def main():
    if not os.path.exists(BBXX):
        print("缺少 %s，请先运行 main.py" % BBXX, file=sys.stderr)
        return 1

    bbxx_lines = read_lines(BBXX)
    raw = [(channel_name(l), bbxx_lines[i + 1]) for i, l in enumerate(bbxx_lines) if l.startswith("#EXTINF")]
    hotel_lines = []
    if os.path.exists(HOTEL) and os.path.getsize(HOTEL) > 0:
        hotel_lines = read_lines(HOTEL)
        raw += [(channel_name(l), hotel_lines[i + 1]) for i, l in enumerate(hotel_lines) if l.startswith("#EXTINF")]
    else:
        print("警告：未找到 %s，本次只输出 bbxx365 部分" % HOTEL)
    shared = shared_paths(raw)
    block = load_host_blocklist() | spam_hosts(raw)
    if block - load_host_blocklist():
        print("自动拉黑的整机（一条路径挂多个台）: %s" % ", ".join(sorted(block - load_host_blocklist())))
    print("共用同一路径的垫播源路径: %d 个 / 拉黑主机 %d 个" % (len(shared), len(block)))

    sources = [collect(bbxx_lines, "bbxx", shared, block)]
    if hotel_lines:
        sources.append(collect(hotel_lines, "hotel", shared, block))

    buckets = merge_and_dedupe(sources)

    result = []
    for target in TARGET_ORDER:
        for extinf, url in buckets[target]:
            result.append(extinf)
            result.append(url)

    # ottiptv 付费源单独成一份（bbxx365_ott.m3u），不再混进主力源
    # OTT_ENABLE=0 可临时关掉
    ott_raw = fetch_ott() if os.environ.get("OTT_ENABLE", "1") != "0" else None
    ott_buckets, ott_order = ({}, [])
    ott_lines = []
    if ott_raw:
        ott_buckets, ott_order = build_ott(ott_raw)
        for target in ott_order:
            for extinf, url in ott_buckets[target]:
                ott_lines.append(extinf)
                ott_lines.append(url)
    else:
        print("警告：本次没有 ottiptv 内容，付费源文件保持上一版", file=sys.stderr)


    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(HEADER)
        f.write("\n".join(result))
        f.write("\n")

    ott_total = 0
    if ott_lines:
        with open(OTT_OUT, "w", encoding="utf-8") as f:
            f.write(HEADER)
            f.write("\n".join(ott_lines))
            f.write("\n")
        ott_total = sum(1 for l in ott_lines if l.startswith("#EXTINF"))

    total = sum(1 for l in result if l.startswith("#EXTINF"))
    print("ottiptv 频道数: %d（已单列到 %s）" % (ott_total, OTT_OUT))
    print("合并完成: %s（共 %d 条）" % (OUT, total))
    for target in TARGET_ORDER:
        n = len({channel_name(e) for e, _ in buckets[target]})
        print("  %-12s %d 台 / %d 条" % (target, n, len(buckets[target])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
