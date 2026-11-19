import gzip, os, shutil

SRC = "m3u/cc.xml"
if not os.path.exists(SRC):
    raise SystemExit(0)
data = open(SRC, "rb").read()
# 1) 原样复制，只改后缀
shutil.copyfile(SRC, "m3u/t-cc.txt")
# 2) 再压一份 gz（二进制，文本扫描可能不读）
with gzip.open("m3u/t-cc.xml.gz", "wb") as fh:
    fh.write(data)
print("变体已生成", len(data))
