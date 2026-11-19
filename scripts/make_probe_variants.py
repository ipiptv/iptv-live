import os, re

SRC = "m3u/e.xml"
if not os.path.exists(SRC):
    raise SystemExit(0)
s = open(SRC, encoding="utf-8").read()
head = s[:s.index("<channel")]
blocks = [b for b in re.split(r'(?=<channel id=")', s) if b.startswith("<channel")]


def progs(cid):
    return re.findall(r'<programme [^>]*channel="%s"[\s\S]*?</programme>' % re.escape(cid), s)


def build(name, cids, strip_desc=False, rename=False):
    body = []
    for cid in cids:
        b = [x for x in blocks if x.startswith('<channel id="%s"' % cid)][0]
        if strip_desc:
            b = re.sub(r'<desc>[\s\S]*?</desc>', '', b)
        if rename:
            b = b.replace('<channel id="%s"' % cid, '<channel id="P%s"' % abs(hash(cid)) % 100000)
            b = re.sub(r'<display-name>[\s\S]*?</display-name>', '', b)
        body.append(b)
        for p in progs(cid):
            if strip_desc:
                p = re.sub(r'<desc>[\s\S]*?</desc>', '', p)
            if rename:
                p = p.replace('channel="%s"' % cid, 'channel="P%s"' % abs(hash(cid)) % 100000)
            body.append(p)
    open("m3u/" + name, "w", encoding="utf-8").write(head + "".join(body) + "</tv>")


ws = [re.search(r'<channel id="([^"]+)"', b).group(1) for b in blocks]
ws = [c for c in ws if c.endswith("卫视")]
print("卫视频道数", len(ws), "前三个", ws[:3])
for i, cid in enumerate(ws[:3], 1):
    build("d%d.xml" % i, [cid])
build("d4.xml", ws, strip_desc=True)
build("d5.xml", ws, rename=True)
build("d6.xml", ws[:3], strip_desc=True)
print("变体已生成")
