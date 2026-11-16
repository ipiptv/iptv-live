"""生成站点上的 bbxx365 独立列表页（照抄上游 /list/*.md 的表格写法）。

上游站点把 /list/xxx.list 映射到 /list/xxx.md，渲染时把「文本以 .m3u/.txt 结尾」的
链接自动变成带拷贝按钮的小方块。所以这里只要按同样格式写 Markdown 即可。
"""
import os
import re

OUT = "m3u/list/bbxx365.md"

FILES = [
    ("bbxx365_mini_home.m3u", "家用实测版（推荐）", "只留能播的源，每台最多 10 条，按实际起播速度排序"),
    ("bbxx365_mini.m3u", "云端精编版", "云端验活 + 按源类型排序，每台 5 条"),
    ("bbxx365_hotel.m3u", "央视 · 卫视 · 酒店合并版", "白名单合并，未验活"),
    ("bbxx365_lite.m3u", "上游瘦身版", "只保留优质组合，未验活"),
    ("bbxx365.m3u", "全集", "全部抓取结果，未验活、未测速"),
]


def count_entries(path):
    try:
        with open(path, encoding="utf-8") as f:
            return sum(1 for ln in f if ln.startswith("#EXTINF"))
    except FileNotFoundError:
        return None


def main():
    rows = []
    for filename, title, desc in FILES:
        n = count_entries(os.path.join("m3u", filename))
        count = str(n) if n else "—"
        txt = filename[:-4] + ".txt"
        links = f"[{filename}](/{filename})"
        if os.path.exists(os.path.join("m3u", txt)):
            links += f" <br> [{txt}](/{txt})"
        rows.append(f"| {title} | {links} | {desc} | {count} |")

    md = "\n".join(
        [
            "# bbxx365 订阅地址",
            "",
            "> 本页由 `scripts/build_site_page.py` 每次发布时自动生成，条数为生成当次的实际数量。",
            "",
            "| 名称 | url | 说明 | 条数 |",
            "| --- | --- | --- | --- |",
            *rows,
            "",
        ]
    )
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"已生成 {OUT}")


if __name__ == "__main__":
    main()
