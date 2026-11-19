import gzip, os, shutil

SRC = "m3u/cc.xml"
if not os.path.exists(SRC):
    raise SystemExit(0)
data = open(SRC, "rb").read()
shutil.copyfile(SRC, "m3u/t-cc.txt")
shutil.copyfile(SRC, "m3u/t-cc.m3u")
with gzip.open("m3u/t-cc.xml.gz", "wb") as fh:
    fh.write(data)
print("变体已生成", len(data))
