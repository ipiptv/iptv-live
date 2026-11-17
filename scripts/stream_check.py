#!/usr/bin/env python3
"""批量检测直播源，维护 data/stream-check 下的失效缓存与主机信誉库。

与 tools/stream-check-state.js 同构（字段、过期规则、主机晋升条件全部对齐），
但不依赖 node，本机和 GitHub Actions 用同一份代码。

用法：
    python3 scripts/stream_check.py                      # 复检已知失效 + 顺带发现新失效
    python3 scripts/stream_check.py --budget 3000 --discover 600
    python3 scripts/stream_check.py --discover 3000 --discover-only   # 只做发现（不做已知复检）

设计取舍：
1. 复检模式（默认）：把失效缓存里已经过期的地址重新测一遍，恢复的立刻放行，
   仍然失败的续期。这些地址本来就已被判定失效，误判代价是"多关一段时间"，
   所以允许按 timeout 记录。
2. 发现模式：从 m3u 里轮转抽样测一批新地址，只有"连接失败/404/5xx"这种
   **与网络位置无关的硬错误**才记失效；超时一律忽略——跑在海外 CI 上的超时
   不能证明国内看不了，这也是当初否掉云端测速的原因。
"""

import argparse
import json
import os
import socket
import ssl
import sys
import zlib
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

STATE_DIR = "data/stream-check"
CONFIG_SEED = "assets/stream-check/config.json"   # 仓库里的基线配置（data/ 被 .gitignore 忽略）
CONFIG_PATH = os.path.join(STATE_DIR, "config.json")
FAILURE_PATH = os.path.join(STATE_DIR, "failure-cache.json")
HOST_PATH = os.path.join(STATE_DIR, "host-reputation.json")
M3U_PATH = "m3u/bbxx365.m3u"
RESULT_PATH = "/tmp/stream-check-results.json"

UA = "AptvPlayer/1.0"
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

DEFAULT_CONFIG = {
    "retryHours": {
        "timeout": 12, "server_error": 24, "not_found": 168,
        "connection_error": 168, "no_signal": 168, "other": 24,
    },
    "staleRecordDays": 90,
    "longFailure": {
        "minFailCount": 5, "minFailureDays": 7, "retryHours": 720,
        "strongReasons": ["not_found", "connection_error", "no_signal"],
    },
    "hostReputation": {
        "minDistinctUrls": 10, "minObservationDays": 2, "minStrongFailures": 8,
        "temporarySkipHours": 72, "candidateReviewDays": 30, "historyDays": 90,
    },
}


# ---------------------------------------------------------------- 状态读写（对齐 JS）
def read_json(path, fallback):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, OSError, ValueError):
        return fallback


def write_json_atomic(path, value):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def normalize_url(url):
    return str(url or "").strip().replace("video://", "").split("$", 1)[0]


def host_key(url):
    try:
        return urlparse(normalize_url(url)).netloc.lower()
    except ValueError:
        return ""


def parse_ts(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def day_key(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")


class State:
    def __init__(self):
        if not os.path.exists(CONFIG_PATH) and os.path.exists(CONFIG_SEED):
            os.makedirs(STATE_DIR, exist_ok=True)
            with open(CONFIG_SEED, encoding="utf-8") as src, open(CONFIG_PATH, "w", encoding="utf-8") as dst:
                dst.write(src.read())
        self.config = read_json(CONFIG_PATH, DEFAULT_CONFIG)
        for key, value in DEFAULT_CONFIG.items():
            self.config.setdefault(key, value)
        self.failure = read_json(FAILURE_PATH, {"version": 1, "records": {}})
        self.host = read_json(HOST_PATH, {"version": 1, "records": {}})
        self.failure.setdefault("records", {})
        self.host.setdefault("records", {})

    # --- 过期判断（JS isUrlInRetryPeriod）
    def in_retry_period(self, url, now):
        record = self.failure["records"].get(normalize_url(url))
        if not record:
            return False
        checked_at = parse_ts(record.get("lastChecked"))
        if not checked_at:
            return False
        retry = self.config["retryHours"]
        hours = retry.get(record.get("reason"), retry.get("other", 24))
        long_failure = self.config["longFailure"]
        first_failed = parse_ts(record.get("firstFailedAt"))
        if (first_failed
                and record.get("failCount", 0) >= long_failure.get("minFailCount", 5)
                and now - first_failed >= timedelta(days=long_failure.get("minFailureDays", 7))):
            hours = max(hours, long_failure.get("retryHours", 720))
        return now - checked_at < timedelta(hours=hours)

    # --- 主机晋升（JS updateHostEligibility）
    def update_host_eligibility(self, host, now):
        record = self.host["records"].get(host)
        if not record:
            return
        settings = self.config["hostReputation"]
        entries = list((record.get("urls") or {}).values())
        observation_days = {d for e in entries for d in e.get("failureDays") or []}
        successes = sum(e.get("successCount", 0) for e in entries)
        strong_failures = sum(e.get("strongFailCount", 0) for e in entries)
        record["summary"] = {
            "distinctUrls": len(entries),
            "observationDays": len(observation_days),
            "successes": successes,
            "strongFailures": strong_failures,
        }
        eligible = (len(entries) >= settings.get("minDistinctUrls", 10)
                    and len(observation_days) >= settings.get("minObservationDays", 2)
                    and successes == 0
                    and strong_failures >= settings.get("minStrongFailures", 8))
        if not eligible:
            record.pop("skipUntil", None)
            record.pop("candidateSince", None)
            record["permanentCandidate"] = False
            return
        record.setdefault("candidateSince", now.isoformat())
        record["skipUntil"] = (now + timedelta(hours=settings.get("temporarySkipHours", 72))).isoformat()
        candidate_since = parse_ts(record.get("candidateSince"))
        record["permanentCandidate"] = bool(
            candidate_since
            and now - candidate_since >= timedelta(days=settings.get("candidateReviewDays", 30)))

    def record_failure(self, url, reason, now):
        key = normalize_url(url)
        if not key:
            return
        ts = now.isoformat()
        old = self.failure["records"].get(key) or {}
        self.failure["records"][key] = {
            "firstFailedAt": old.get("firstFailedAt") or ts,
            "lastChecked": ts,
            "failCount": old.get("failCount", 0) + 1,
            "reason": reason,
        }
        host = host_key(key)
        if not host:
            return
        record = self.host["records"].setdefault(host, {"urls": {}})
        urls = record.setdefault("urls", {})
        entry = urls.setdefault(key, {
            "firstSeen": ts, "failCount": 0, "successCount": 0,
            "strongFailCount": 0, "failureDays": [],
        })
        entry["lastChecked"] = ts
        entry["lastReason"] = reason
        entry["failCount"] = entry.get("failCount", 0) + 1
        if reason in self.config["longFailure"].get("strongReasons", []):
            entry["strongFailCount"] = entry.get("strongFailCount", 0) + 1
        days = entry.setdefault("failureDays", [])
        if day_key(now) not in days:
            days.append(day_key(now))
        self.update_host_eligibility(host, now)

    def record_success(self, url, now):
        key = normalize_url(url)
        self.failure["records"].pop(key, None)
        host = host_key(key)
        if not host:
            return
        record = self.host["records"].setdefault(host, {"urls": {}})
        urls = record.setdefault("urls", {})
        entry = urls.setdefault(key, {
            "firstSeen": now.isoformat(), "failCount": 0, "successCount": 0,
            "strongFailCount": 0, "failureDays": [],
        })
        entry["lastChecked"] = now.isoformat()
        entry["successCount"] = entry.get("successCount", 0) + 1
        self.update_host_eligibility(host, now)

    def prune(self, now):
        cutoff = now - timedelta(days=self.config.get("staleRecordDays", 90))
        for url, record in list(self.failure["records"].items()):
            checked = parse_ts(record.get("lastChecked"))
            if not checked or checked < cutoff:
                del self.failure["records"][url]
        history_cutoff = now - timedelta(days=self.config["hostReputation"].get("historyDays", 90))
        for record in self.host["records"].values():
            urls = record.get("urls") or {}
            for url, entry in list(urls.items()):
                checked = parse_ts(entry.get("lastChecked"))
                if not checked or checked < history_cutoff:
                    del urls[url]

    def save(self, now):
        self.prune(now)
        self.failure["updatedAt"] = now.isoformat()
        self.host["updatedAt"] = now.isoformat()
        write_json_atomic(FAILURE_PATH, self.failure)
        write_json_atomic(HOST_PATH, self.host)


# ---------------------------------------------------------------- 探测
def probe(url, timeout):
    """返回 (ok, reason)。reason 与配置里的 retryHours 键一致。"""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Range": "bytes=0-2047",
                                               "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
            body = resp.read(65536).decode("utf-8", "ignore")
    except urllib.error.HTTPError as error:
        code = error.code
        if code in (404, 410):
            return False, "not_found"
        if code >= 500:
            return False, "server_error"
        return False, "no_signal"
    except socket.timeout:
        return False, "timeout"
    except (urllib.error.URLError, ConnectionError, OSError) as error:
        reason = getattr(error, "reason", error)
        if isinstance(reason, socket.timeout) or "timed out" in str(reason).lower():
            return False, "timeout"
        return False, "connection_error"
    except Exception:
        return False, "other"

    if "#EXTINF" in body or "#EXTM3U" in body or body.lstrip().startswith("#EXT"):
        return True, ""
    if len(body) < 32:
        return False, "no_signal"
    # 有内容但不是播放列表：m3u8 片段或二进制流，视为可播
    return True, ""


# ---------------------------------------------------------------- 候选选择
def load_m3u_urls(path):
    urls = set()
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "://" not in line:
                continue
            urls.add(normalize_url(line))
    return urls


def pick_candidates(state, all_urls, budget, discover, discover_only, now):
    """复检已知失效（已过期）+ 轮转抽样发现新失效。"""
    recheck = []
    if not discover_only:
        for url in state.failure["records"].keys():
            if state.in_retry_period(url, now):
                continue  # 还没到复检时间，省流量
            recheck.append(url)
        recheck = recheck[:budget]

    discovered = []
    remaining = max(0, budget - len(recheck)) + discover
    if remaining > 0:
        pool = sorted(all_urls - set(state.failure["records"].keys()))
        if pool:
            # 按 crc32 分片（而不是切连续区段）：同一域名的地址会散到不同班里，
            # 避免某一班整批落在同一个已经死掉的主机上。
            shard = int(now.timestamp() // (3 * 3600))
            size = min(remaining, len(pool))
            slots = max(1, len(pool) // max(size, 1))
            discovered = [u for u in pool if zlib.crc32(u.encode()) % slots == shard % slots]
            discovered = discovered[:size]
    return recheck, discovered


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--budget", type=int, default=2500, help="复检已知失效的条数上限")
    parser.add_argument("--discover", type=int, default=600, help="每班顺带发现的新地址条数")
    parser.add_argument("--discover-only", action="store_true")
    parser.add_argument("--record-all", action="store_true",
                        help="按所有失败原因记账（含 timeout/no_signal），仅建议在本机实测时用")
    parser.add_argument("--workers", type=int, default=64)
    parser.add_argument("--timeout", type=float, default=4.0)
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    state = State()

    if not os.path.exists(M3U_PATH):
        print(f"缺少 {M3U_PATH}，先跑 main.py")
        return 1
    all_urls = load_m3u_urls(M3U_PATH)
    recheck, discovered = pick_candidates(
        state, all_urls, args.budget, args.discover, args.discover_only, now)

    targets = [(u, "recheck") for u in recheck] + [(u, "discover") for u in discovered]
    print(f"总地址 {len(all_urls)}｜复检 {len(recheck)}｜发现 {len(discovered)}")

    with ThreadPoolExecutor(args.workers) as pool:
        results = list(pool.map(lambda t: (t[0], t[1], *probe(t[0], args.timeout)), targets))

    # 默认只认"与网络位置无关"的硬错误：超时、403/空流、5xx 在海外跑容易误伤国内源
    hard_reasons = {"not_found", "connection_error"}
    stat = {"ok": 0, "fail": 0}
    ignored = {"timeout": 0, "no_signal": 0, "server_error": 0, "other": 0}
    detail = []
    for url, mode, ok, reason in results:
        if ok:
            state.record_success(url, now)
            stat["ok"] += 1
            detail.append({"url": url, "ok": True, "mode": mode})
            continue
        if not args.record_all and reason not in hard_reasons:
            ignored[reason] = ignored.get(reason, 0) + 1
            continue
        state.record_failure(url, reason, now)
        stat["fail"] += 1
        detail.append({"url": url, "ok": False, "reason": reason, "mode": mode})

    state.save(now)

    with open(RESULT_PATH, "w", encoding="utf-8") as f:
        json.dump({"checkedAt": now.isoformat(), "stat": stat,
                   "ignored": ignored, "results": detail},
                  f, ensure_ascii=False, indent=2)

    skipped = sum(1 for r in state.host["records"].values()
                  if parse_ts(r.get("skipUntil")) and parse_ts(r["skipUntil"]) > now)
    print(f"可播 {stat['ok']}｜记失效 {stat['fail']}｜忽略 " +
          " ".join(f"{k}={v}" for k, v in ignored.items() if v))
    print(f"失效缓存 {len(state.failure['records'])} 条｜主机 {len(state.host['records'])} 个"
          f"｜临时跳过 {skipped} 个｜待人工复核 "
          f"{sum(1 for r in state.host['records'].values() if r.get('permanentCandidate'))} 个")
    return 0


if __name__ == "__main__":
    sys.exit(main())
