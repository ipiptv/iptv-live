#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把上游 collect-txt 的源列表（主频道/专区/地方台/手工区 下的 .txt）同步到本仓库。

⚠ 关键：默认不会覆盖你在本地改过、而上游又更新的文件。

靠 data/upstream_sync_state.json 记录「上次同步时上游那版内容的 sha」：
    - 上游 sha 和记录一致        → 上游没变，直接跳过（不下载）
    - 上游变了，本地 sha 也等于记录 → 本地没被改过 → 安全覆盖，并更新记录
    - 上游变了，本地 sha 不等于记录 → 本地手工改过 → 跳过覆盖，只打印提示
这样上游新增源地址能自动吃到，你手工加的东西不会被冲掉。

环境变量：
    UPSTREAM_REPO   默认 kimwang1978/collect-txt
    UPSTREAM_BRANCH 默认 main
    UPSTREAM_DIRS   默认 主频道,专区,地方台,手工区
    UPSTREAM_FORCE  设为 1 时无视本地改动，强制覆盖
"""

import hashlib
import json
import os
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, "data", "upstream_sync_state.json")
REPO = os.environ.get("UPSTREAM_REPO", "kimwang1978/collect-txt")
BRANCH = os.environ.get("UPSTREAM_BRANCH", "main")
FORCE = os.environ.get("UPSTREAM_FORCE", "0") == "1"
DIRS = [
    d.strip()
    for d in os.environ.get("UPSTREAM_DIRS", "主频道,专区,地方台,手工区").split(",")
    if d.strip()
]

UA = "iptv-sources-sync/1.0"


def get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def blob_sha(data):
    """按 git 的 blob 规则算 sha，和 GitHub API 返回的 sha 可直接比较。"""
    h = hashlib.sha1()
    h.update(b"blob %d\0" % len(data))
    h.update(data)
    return h.hexdigest()


def load_state():
    if os.path.exists(STATE):
        try:
            with open(STATE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_state(state):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)


def tree_map():
    api = "https://api.github.com/repos/%s/git/trees/%s?recursive=1" % (REPO, BRANCH)
    data = json.loads(get(api).decode("utf-8"))
    if data.get("truncated"):
        print("警告：上游目录树被截断，可能漏掉部分文件", file=sys.stderr)
    return {
        item["path"]: item["sha"]
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
        upstream = tree_map()
    except Exception as exc:
        print("警告：读取上游目录失败（%s），本轮跳过同步" % exc, file=sys.stderr)
        return 0

    targets = {p: sha for p, sha in upstream.items() if p.split("/", 1)[0] in DIRS}
    if not targets:
        print("警告：上游没有匹配到任何源列表文件，跳过", file=sys.stderr)
        return 0

    state = load_state()
    prev_state = json.loads(json.dumps(state))

    to_download = []
    for path, sha in targets.items():
        if state.get(path) == sha:
            continue  # 上游没变
        to_download.append(path)

    def fetch(path):
        try:
            return path, get(raw_url(path), timeout=45), None
        except Exception as exc:
            return path, None, str(exc)

    results = []
    if to_download:
        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(fetch, to_download))

    added, updated, same, skipped_local, failed = [], [], 0, [], []
    for path, remote, err in results:
        if err or remote is None:
            failed.append((path, err or "下载失败"))
            continue
        if remote.lstrip().startswith(b"404"):
            failed.append((path, "上游 404"))
            continue

        remote_sha = blob_sha(remote)
        local = os.path.join(ROOT, path)
        local_data = None
        if os.path.exists(local):
            with open(local, "rb") as f:
                local_data = f.read()

        if local_data is None:
            os.makedirs(os.path.dirname(local), exist_ok=True)
            with open(local, "wb") as f:
                f.write(remote)
            state[path] = remote_sha
            added.append(path)
            continue

        if local_data == remote:
            state[path] = remote_sha
            same += 1
            continue

        local_sha = blob_sha(local_data)
        recorded = state.get(path)

        if FORCE or recorded is None or local_sha == recorded:
            # 本地没被改过（或强制覆盖）→ 安全同步上游新版
            with open(local, "wb") as f:
                f.write(remote)
            state[path] = remote_sha
            updated.append(path)
        else:
            # 本地改动过，且上游也变了 → 保留本地，不覆盖
            skipped_local.append(path)

    unchanged_upstream = len(targets) - len(to_download)
    if state != prev_state:
        save_state(state)

    print("上游 %s@%s：共 %d 个源列表文件" % (REPO, BRANCH, len(targets)))
    print(
        "  上游无变化 %d，新增 %d，更新 %d，内容相同 %d，保留本地改动 %d，失败 %d"
        % (unchanged_upstream, len(added), len(updated), same, len(skipped_local), len(failed))
    )
    for p in added:
        print("  + %s" % p)
    for p in updated:
        print("  ~ %s" % p)
    for p in skipped_local:
        print("  保留本地改动（未被上游覆盖）：%s" % p)
    for p, why in failed[:10]:
        print("  ! %s（%s）" % (p, why), file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
