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

# 白名单：(分组关键词, 统一后的分组名)。关键词按“包含”匹配，先到先得。
GROUPS = [
    ("央视频道", "❤️央视频道"),
    ("卫视频道", "❤️卫视频道"),
    # 专享卫视/专享央视不再单独成组：卫视类并入卫视频道，央视类并入央视频道
    ("专享卫视", "❤️卫视频道"),
    ("专享央视", "❤️央视频道"),
    # 少儿/儿童/动画类全部并到一个分组
    ("儿童专享", "🧸少儿动画"),
    ("动画片", "🧸少儿动画"),
    # 直播电影频道优先级要高于点播组，否则 CHC 这类频道会被点播组先占走
    ("电影频道", "🎬电影频道"),
    ("电影点播", "❤️电影点播"),
    # 主题片（按题材轮播的电影频道）并入点播组
    ("主题片", "❤️电影点播"),
    # 明星轮播房（按演员分的电影轮播）同样并入点播组
    ("明星", "❤️电影点播"),
    # 专享源🅰️/🅱️ 基本是电影轮播与演员房，并入点播组
    ("专享源", "❤️电影点播"),
    # 优质个源以境外纪录片为主
    ("优质个源", "🎭专题频道"),
    ("电视剧", "💓电视剧场"),
    # 港澳台 + 台湾 + 国际台 合成一个“境外频道”分组
    ("台湾台", "🌏境外频道"),
    ("港澳台", "🌏境外频道"),   # 同时覆盖“港澳台”与“💓港澳台📶”
    ("国际台", "🌏境外频道"),
    ("4K(Auto)", "💓4K(Auto)"),
    # 4K 只保留一组：4K(Test) 并入 4K(Auto)
    ("4K(Test)", "💓4K(Auto)"),
    ("更新时间", "❤️更新时间"),
    # 专题/综艺类统一并进“专题频道”
    ("直播中国", "🎭专题频道"),
    ("MTV", "🎭专题频道"),
    ("春晚", "🎭专题频道"),
    ("戏曲频道", "🎭专题频道"),
    ("纪录片", "🎭专题频道"),
    ("解说频道", "🎭专题频道"),
    ("游戏频道", "🎭专题频道"),
    ("收音机频道", "🎭专题频道"),
    ("综艺频道", "🎭专题频道"),
    # 补掉零散分组的归属
    ("SPORTS", "⚽体育频道"),
    ("咪咕直播", "⚽体育频道"),
    ("英语频道", "🌏境外频道"),
    ("定制台", "🌏境外频道"),
    # 单剧分集（甄嬛传/以家人之名/雪中悍刀行 这类按集拆分的点播）单独成组
    ("甄嬛传", "🎬剧集点播"),
    ("以家人之名", "🎬剧集点播"),
    ("雪中悍刀行", "🎬剧集点播"),
    # 下面两个是收纳目标（关键词不会命中全量分组，只用来承接按台名归属的频道）
    # 体育类全部并成一个分组
    ("体育频道", "⚽体育频道"),
    ("剧集点播", "🎬剧集点播"),
    ("地方频道", "🏙️地方频道"),
    ("专题频道", "🎭专题频道"),
]

# 省级/直辖市地方台分组：统一并进“地方频道”
PROVINCE_NAMES = [
    "广东", "浙江", "湖南", "上海", "湖北", "河北", "江苏", "山东", "黑龙江",
    "四川", "福建", "吉林", "河南", "安徽", "甘肃", "广西", "辽宁", "陕西",
    "北京", "新疆", "山西", "重庆", "海南", "青海", "江西", "云南", "宁夏",
    "内蒙", "天津", "贵州",
]
GROUPS += [(name + "频道", "🏙️地方频道") for name in PROVINCE_NAMES]

HOTEL_GROUPS = ["央视频道", "卫视频道", "其他频道"]

# 主力只保留这些分组（用户在清单上勾选的）
MAIN_KEEP_GROUPS = {
    "❤️央视频道",
    "❤️卫视频道",
    "🧸少儿动画",
    "💓电视剧场",
    "🎬电影频道",
    "⚽体育频道",
    "🌏境外频道",
    "🎭专题频道",
    "❤️更新时间",
}

# 兜底分组：命中不了任何规则的频道统一放这里
OTHER_GROUP = "🧩其他频道"

# 输出时各分组的排列顺序（更新时间固定排最后）
OUTPUT_ORDER = [
    "❤️央视频道",
    "❤️卫视频道",
    "🧸少儿动画",
    "💓电视剧场",
    "🎬电影频道",
    "⚽体育频道",
    "🌏境外频道",
    "🎬剧集点播",
    "❤️电影点播",
    "🎭专题频道",
    "🏙️地方频道",
    "🧩其他频道",
    "❤️更新时间",
]

# 频道名命中这些关键词的，不管原来在哪个分组，统一进“少儿动画”
KID_NAME_RE = re.compile(r"少儿|卡通|动画|儿童|动漫", re.IGNORECASE)
KID_GROUP = "🧸少儿动画"

# 频道名命中这些关键词的，不论原分组，统一进“体育频道”
SPORT_NAME_RE = re.compile(r"体育|足球|篮球|赛事|NBA|网球|羽毛球|排球|乒乓", re.IGNORECASE)
SPORT_GROUP = "⚽体育频道"

# 个别散落在地方台/影视组里的台，按台名单独收进指定分组（主力原本不收地方台）
NAME_TARGET = {
    # 散落在地方台/影视组里的电视剧台
    "湖南电视剧": "💓电视剧场",
    "福建电视剧": "💓电视剧场",
    "武汉二台电视剧": "💓电视剧场",
    "辽宁影视剧": "💓电视剧场",
    # 教育/央媒系
    "CETV2": "❤️央视频道",
    "CETV4": "❤️央视频道",
    "中国交通": "❤️央视频道",
    # 港澳台/境外
    "翡翠台": "🌏境外频道",
    "凤凰中文": "🌏境外频道",
    "凤凰资讯": "🌏境外频道",
    # 省市地方台
    "广东公共": "🏙️地方频道",
    "广东影视": "🏙️地方频道",
    "广东新闻": "🏙️地方频道",
    "广东珠江": "🏙️地方频道",
    "广州台": "🏙️地方频道",
    "廉江公共": "🏙️地方频道",
    "五华台": "🏙️地方频道",
    "安徽经视": "🏙️地方频道",
    "山东教育": "🏙️地方频道",
    "现代教育": "🏙️地方频道",
    "湖南公共": "🏙️地方频道",
    "河南公共": "🏙️地方频道",
    "河南新农村": "🏙️地方频道",
    "河南新闻": "🏙️地方频道",
    "河南民生": "🏙️地方频道",
    "河南法制": "🏙️地方频道",
    "黑龙江影视": "🏙️地方频道",
    "黑龙江文体": "🏙️地方频道",
    "黑龙江新闻法治": "🏙️地方频道",
    "黑龙江都市": "🏙️地方频道",
    "松原": "🏙️地方频道",
    "松原公共": "🏙️地方频道",
    # 4K 频道按归属拆走，不再单独成组
    "CCTV4K": "❤️央视频道",
    "湖南卫视4K": "❤️卫视频道",
    "东方卫视4K": "❤️卫视频道",
    "浙江卫视4K": "❤️卫视频道",
    "北京卫视4K": "❤️卫视频道",
    "深圳卫视4K": "❤️卫视频道",
    "广东卫视4K": "❤️卫视频道",
    "翡翠台4K": "🌏境外频道",
    "北京4K": "🏙️地方频道",
    "苏州4K": "🏙️地方频道",
    "河北4K": "🏙️地方频道",
    "南国都市4K": "🏙️地方频道",
    "Love Nature 4K": "🎭专题频道",
    "🐼直播熊猫": "🎭专题频道",
    # 戏曲/武术/财富/纪实等专题与付费频道
    "梨园": "🎭专题频道",
    "岭南戏曲": "🎭专题频道",
    "武术世界": "🎭专题频道",
    "汽摩": "🎭专题频道",
    "财富天下": "🎭专题频道",
    "金鹰纪实": "🎭专题频道",
    "星河": "🎭专题频道",
    "茶": "🎭专题频道",
    "移动": "🎭专题频道",
    "IPTV8": "🎭专题频道",
}

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


def build_bbxx(lines):
    buckets = {i: [] for i in range(len(GROUPS))}
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("#EXTINF"):
            name = channel_name(line)
            is_kid = bool(KID_NAME_RE.search(name))
            idx, new_name = match_group(get_group(line))
            target = NAME_TARGET.get(name)
            if not target and SPORT_NAME_RE.search(name):
                target = SPORT_GROUP
            if target:
                idx = next(j for j, (k, v) in enumerate(GROUPS) if v == target)
                new_name = target
            elif is_kid:
                # 名字带少儿/卡通/动画的，不论原分组、也不论是否在白名单，统一并到少儿动画组
                idx = next(j for j, (k, v) in enumerate(GROUPS) if v == KID_GROUP)
                new_name = KID_GROUP
            if idx >= 0:
                url = lines[i + 1] if i + 1 < len(lines) else ""
                buckets[idx].append((set_group(line, new_name), url))
            i += 2
        else:
            i += 1

    # 更新时间分组：只留第一条，地址替换为固定播放地址
    update_idx = next(i for i, (k, _) in enumerate(GROUPS) if k == "更新时间")
    if buckets[update_idx]:
        first_extinf = buckets[update_idx][0][0]
        buckets[update_idx] = [(first_extinf, UPDATE_URL)]

    return buckets


# 酒店源（hotel_tvn）进主力时的分组归并：央视、卫视各自合成一个分组，不再带 🌹 前缀分家
HOTEL_GROUP_TARGET = {
    "央视频道": "❤️央视频道",
    "卫视频道": "❤️卫视频道",
    "其他频道": "🌹其他频道",
}

# 酒店源里要剔掉的脏数据：测试占位项 + 外文频道（中文台如“旅游卫视”保留）
HOTEL_DROP_PATTERN = re.compile(r"测试")
HOTEL_DROP_NAMES = {
    "abaitv",
    "mtkr",
    "qazsport",
    "qazaqstantv",
    "новое телевидение",
    "новоетелевидение",
    "рикатв",
}


def should_drop_hotel(extinf):
    name = channel_name(extinf).strip()
    if not name:  # 空频道名
        return True
    if HOTEL_DROP_PATTERN.search(name):
        return True
    return name.lower() in HOTEL_DROP_NAMES


def build_hotel(lines):
    buckets = {g: [] for g in HOTEL_GROUPS}
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("#EXTINF"):
            group = get_group(line)
            matched = None
            for g in HOTEL_GROUPS:
                if g in group or g in line:
                    matched = g
                    break
            if matched:
                if should_drop_hotel(line):
                    i += 2
                    continue
                url = lines[i + 1] if i + 1 < len(lines) else ""
                name = channel_name(line)
                target = (
                    NAME_TARGET.get(name)
                    or (SPORT_GROUP if SPORT_NAME_RE.search(name) else None)
                    or (KID_GROUP if KID_NAME_RE.search(name) else None)
                    or HOTEL_GROUP_TARGET[matched]
                )
                buckets[matched].append((set_group(line, target), url))
            i += 2
        else:
            i += 1
    return buckets


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

    bbxx_raw = build_bbxx(read_lines(BBXX))
    bbxx_buckets, group_order = dedupe_buckets(bbxx_raw)

    if os.path.exists(HOTEL) and os.path.getsize(HOTEL) > 0:
        hotel_buckets = build_hotel(read_lines(HOTEL))
        hotel_count = sum(len(v) for v in hotel_buckets.values())
    else:
        print("警告：未找到 %s，本次只输出 bbxx365 部分" % HOTEL)
        hotel_buckets = {g: [] for g in HOTEL_GROUPS}
        hotel_count = 0

    # 先按分组名汇总两边的条目，再按 OUTPUT_ORDER 规定的顺序输出
    merged: dict = {}
    order: list = []
    seen = set()
    for g in HOTEL_GROUPS:
        for extinf, url in hotel_buckets[g]:
            target = get_group(extinf)
            key = (channel_name(extinf), url)
            if key in seen:
                continue
            seen.add(key)
            if target not in merged:
                merged[target] = []
                order.append(target)
            merged[target].append((extinf, url))
    for target in group_order:
        for extinf, url in bbxx_buckets[target]:
            key = (channel_name(extinf), url)
            if key in seen:
                continue
            seen.add(key)
            if target not in merged:
                merged[target] = []
                order.append(target)
            merged[target].append((extinf, url))

    # 输出顺序：央视 → 卫视 → 少儿动画 → 电视剧 → 其余按 OUTPUT_ORDER 依次排，更新时间放最后
    final_order = [g for g in OUTPUT_ORDER if g in merged]
    final_order += [g for g in order if g not in final_order and g not in OUTPUT_ORDER]

    result = []
    for g in final_order:
        # 主力只留白名单里的分组，其余（地方/点播/剧集/其他）不进主力
        if g not in MAIN_KEEP_GROUPS:
            continue
        for extinf, url in merged[g]:
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
    print("酒店源频道数: %d" % hotel_count)
    print("bbxx365 白名单频道数: %d" % sum(len(v) for v in bbxx_buckets.values()))
    print("ottiptv 频道数: %d（已单列到 %s）" % (ott_total, OTT_OUT))
    print("合并完成: %s（共 %d 个频道）" % (OUT, total))

    for target in group_order:
        print("  %-12s %d" % (target, len(bbxx_buckets[target])))
    for target in ott_order:
        print("  %-12s %d" % (target, len(ott_buckets[target])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
