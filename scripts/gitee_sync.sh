#!/usr/bin/env bash
# 把 m3u 产物同步到 Gitee 仓库（gitee.com/IptvIptv/Iptv 的 master 分支）。
#
# 为什么要有这个脚本：
#   Gitee 对仓库内容有自动审查，含“VOA / 美国之音”的条目会让整个 m3u 文件返回
#   451（The content may contain violation information），且改后缀、改文件名都无效。
#   因此这里在推送前把这些条目剔掉，Gitee 侧留一份“干净版”，其他平台（GitHub raw、
#   Cloudflare 站点）仍然保留完整版本。
#
# 依赖：
#   secrets.GITEE_SSH_KEY —— 与 Gitee 账号里已添加的公钥配对的私钥（无口令）。
#   未配置时脚本直接跳过，流水线不会失败。
set -euo pipefail

# 节目单：EPG 仓 output 分支有多少分类就同步多少（e.xml/cc.xml/difang.xml/gat.xml…）
XML_FILES=""
for x in "$WORK"/m3u/*.xml "$WORK"/m3u/*.xml.gz; do
  [ -f "$x" ] && XML_FILES="$XML_FILES $(basename "$x")"
done
FILES="bbxx365.m3u bbxx365_hotel.m3u bbxx365_ott.m3u bbxx365_lite.m3u bbxx365_mini.m3u bbxx365_mini_home.m3u hotel_tvn.m3u sources.json$XML_FILES"
GITEE_REPO="git@gitee.com:IptvIptv/Iptv.git"
WORK="${GITHUB_WORKSPACE:-$(pwd)}"

if [ -z "${GITEE_SSH_KEY:-}" ]; then
  echo "GITEE_SSH_KEY 未配置，跳过 Gitee 同步。"
  exit 0
fi

KEY="$RUNNER_TEMP/gitee_key"
printf '%s\n' "$GITEE_SSH_KEY" > "$KEY"
chmod 600 "$KEY"

export GIT_SSH_COMMAND="ssh -i $KEY -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
export GIT_AUTHOR_NAME="github-actions[bot]"
export GIT_AUTHOR_EMAIL="41898282+github-actions[bot]@users.noreply.github.com"
export GIT_COMMITTER_NAME="$GIT_AUTHOR_NAME"
export GIT_COMMITTER_EMAIL="$GIT_AUTHOR_EMAIL"

rm -rf /tmp/gitee && mkdir -p /tmp/gitee
# 拉回旧分支再覆盖，保留本流水线在云端产不出的文件（mini_home 只能在家里网络实测产出）
git clone -q --depth 1 -b master "$GITEE_REPO" /tmp/gitee

for f in $FILES; do
  src=""
  [ -f "$WORK/m3u/$f" ] && src="$WORK/m3u/$f"
  # mini_home 由 publish 分支带回来，本地 m3u 里不一定有
  [ -z "$src" ] && [ -f "/tmp/pub/$f" ] && src="/tmp/pub/$f"
  [ -z "$src" ] && { echo "跳过（无产物）: $f"; continue; }

  python3 - "$src" "/tmp/gitee/$f" <<'PY'
import sys
src, dst = sys.argv[1], sys.argv[2]
drop = ("VOA", "美国之音")
out, pending = [], False
for raw in open(src, encoding="utf-8"):
    line = raw.rstrip("\n")
    if line.startswith("#EXTINF"):
        pending = any(w in line for w in drop)
        if not pending:
            out.append(line)
        continue
    if pending:
        # 被丢弃条目下面的 URL 行（以及它自己的附属标签）一起丢掉
        if not line.startswith("#"):
            pending = False
        continue
    out.append(line)
open(dst, "w", encoding="utf-8").write("\n".join(out) + "\n")
print(f"{dst}: {len(out)} 行")
PY
done

# 后台管理页：从仓库根目录直接复制（不过滤频道，它不是 m3u）
if [ -f "$WORK/admin.html" ]; then
  cp "$WORK/admin.html" /tmp/gitee/admin.html
  echo "admin.html: 已复制到 Gitee 根目录"
fi

cd /tmp/gitee
git add -A
if git diff --cached --quiet; then
  echo "Gitee 侧无变化，跳过推送。"
  exit 0
fi
git commit -q -m "sync $(date -u +%Y-%m-%dT%H:%MZ)"

push_once() {
  git push origin master 2>&1 | tail -20
  return ${PIPESTATUS[0]}
}

if push_once; then
  echo "已推送 Gitee master"
else
  echo "首次推送失败，尝试剔除 gat.xml 后重推（港澳台节目单可能触发 Gitee 内容审查）"
  for f in gat.xml; do
    if [ -f "/tmp/gitee/$f" ]; then
      git rm -q --cached "$f" || true
      rm -f "/tmp/gitee/$f"
      echo "已剔除: $f"
    fi
  done
  if git diff --cached --quiet && [ -z "$(git status --porcelain)" ]; then
    echo "剔除后无可推送内容"
  else
    git add -A
    git commit -q --amend --no-edit
  fi
  if push_once; then
    echo "已推送 Gitee master（不含 gat.xml）"
  else
    echo "Gitee 推送失败，请查看上面的 git 报错"
    exit 1
  fi
fi
