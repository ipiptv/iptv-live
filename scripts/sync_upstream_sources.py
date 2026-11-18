#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把上游 collect-txt 的源列表（主频道/专区/地方台/手工区 下的 .txt）同步到本仓库。

背景：本仓库里这些 .txt 就是当初从上游整份搬过来的「原始源地址清单」，
      本地的 main.py 读它们自己解析生成 bbxx365.m3u，所以上游新增源地址时，
      这边要跟着更新才能吃到新源。

行为：
    - 只做「新增 / 更新」，上游删掉的文件本地保留（防止误删手工维护的内容）
    - 内容逐字节比对，没变化就不动文件（不会产生无意义的提交）
    - 网络失败不阻断流水线：打警告并以 0 退出，本轮继续用已有列表跑

环境变量：
    UPSTREAM_REPO   默认 kimwang1978/collect-txt
    UPSTREAM_BRANCH 默认 main
    UPSTREAM_DIRS   默认 主频道,专区,地方台,手工区
"""

import json
import os
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.environ.get("UPSTREAM_REPO", "kimwang1978/collect-txt")
BRANCH = os.environ.get("UPSTREAM_BRANCH", "main")
DIRS = [d.strip() for d in os.environ.get("UPSTREAM_DIRS", "主频道,专区,地方台,手工区").split(",") if d.strip()]

UA = "iptv-sources-sync/1.0"


def get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def tree_paths():
    api = "https://api.github.com/repos/%s/git/trees/%s?recursive=1" % (REPO, BRANCH)
    data = json.loads(get(api).decode("utf-8"))
    if data.get("truncated"):
        print("警告：上游目录树被截断，可能漏掉部分文件", file=sys.stderr)
    return {
        item["path"]
        for item in data.get("tree", [])
        if item.get("type") == "blob" and item["path"].endswith(".txt")
    }


def raw_url(path):
    return "https://raw.githubusercontent.com/%s/%s/%s" % (
        REPO,
        BRANCH,
        urllib.parse.quote(path),
    )


def main():
    try:
        paths = tree_paths()
    except Exception as exc:
        print("警告：读取上游目录失败（%s），本轮跳过同步" % exc, file=sys.stderr)
        return 0

    targets = sorted(p for p in paths if p.split("/", 1)[0] in DIRS)
    if not targets:
        print("警告：上游没有匹配到任何源列表文件，跳过", file=sys.stderr)
        return 0

    added, updated, same, failed = [], [], 0, []

    def fetch(path):
        try:
            return path, get(raw_url(path), timeout=45), None
        except Exception as exc:
            return path, None, str(exc)

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(fetch, targets))

    for path, remote, err in results:
        if err:
            failed.append((path, err))
            continue

        if remote.lstrip().startswith(b"404"):
            failed.append((path, "上游 404"))
            continue

        local = os.path.join(ROOT, path)
        if os.path.exists(local):
            with open(local, "rb") as f:
                current = f.read()
            if current == remote:
                same += 1
                continue
            with open(local, "wb") as f:
                f.write(remote)
            updated.append(path)
        else:
            os.makedirs(os.path.dirname(local), exist_ok=True)
            with open(local, "wb") as f:
                f.write(remote)
            added.append(path)

    print("上游 %s@%s：共 %d 个源列表文件" % (REPO, BRANCH, len(targets)))
    print("  新增 %d，更新 %d，未变 %d，失败 %d" % (len(added), len(updated), same, len(failed)))
    for p in added:
        print("  + %s" % p)
    for p in updated:
        print("  ~ %s" % p)
    for p, why in failed[:10]:
        print("  ! %s（%s）" % (p, why), file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
