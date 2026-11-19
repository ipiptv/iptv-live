#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""推送 Gitee 之前的清洗步骤。

Gitee 的内容审核会按关键词把整份文件打成 451（The content may contain
violation information），一旦命中，播放器整份订阅都拉不下来。这里按两类处理：

  * m3u：整条 #EXTINF 条目（连同它下面的地址）命中就丢掉（历史规则，VOA/美国之音）。
  * xmltv：只丢掉命中的 <programme> 节目条目，频道定义和其余节目全部保留，
    这样文件能正常访问，节目单只少几条。

用法：python3 scripts/gitee_filter.py <源文件> <目标文件>
"""
import re
import shutil
import sys

# m3u 条目级别的关键词
DROP_M3U = ("VOA", "美国之音")

# 节目单条目级别的关键词（涉赌、涉毒等，会让整份 xml 变 451）
DROP_XML = ("赌", "毒", "枪", "嫖", "妓", "淫")


def filter_m3u(src, dst):
    out, pending = [], False
    with open(src, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            if line.startswith("#EXTINF"):
                pending = any(w in line for w in DROP_M3U)
                if not pending:
                    out.append(line)
                continue
            if pending:
                if not line.startswith("#"):
                    pending = False
                continue
            out.append(line)
    with open(dst, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")
    print("%s: %d 行" % (dst, len(out)))


def filter_xml(src, dst):
    with open(src, encoding="utf-8") as fh:
        text = fh.read()
    kept, dropped = [], 0
    for m in re.finditer(r"<programme [\s\S]*?</programme\s*>", text):
        block = m.group(0)
        if any(k in block for k in DROP_XML):
            dropped += 1
            continue
        kept.append(block)
    head_end = text.index("<channel") if "<channel" in text else 0
    tail_start = text.rindex("</tv>") if "</tv>" in text else len(text)
    body = text[head_end:tail_start]
    chans = re.findall(r"<channel [\s\S]*?</channel\s*>", body)
    out = text[:head_end] + "".join(chans) + "".join(kept) + text[tail_start:]
    with open(dst, "w", encoding="utf-8") as fh:
        fh.write(out)
    print("%s: 剔除 %d 条命中节目，保留 %d 条" % (dst, dropped, len(kept)))


def main():
    src, dst = sys.argv[1], sys.argv[2]
    low = dst.lower()
    if low.endswith(".gz"):
        shutil.copyfile(src, dst)
        print("%s: gz 直接复制" % dst)
    elif low.endswith(".xml"):
        filter_xml(src, dst)
    else:
        filter_m3u(src, dst)


if __name__ == "__main__":
    main()
