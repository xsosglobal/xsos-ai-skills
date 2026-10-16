#!/usr/bin/env bash
# 一条命令安装或更新 XSOS skills（Claude Code 与 Codex 共用一份克隆）。
#
#   curl -fsSL https://raw.githubusercontent.com/xsosglobal/xsos-ai-skills/main/install.sh | bash
#   bash ~/.xsos-ai-skills/install.sh          # 已装过时更新
#
# 只做安全的事：本地有未提交改动、不在 main 上、或无法快进时提示原因并停止，
# 绝不覆盖改动、不切分支；目标位置已被别的目录或软链占用时不覆盖，只提示。
#
# 环境变量：
#   XSOS_SKILLS_DIR       克隆位置（默认：沿用已链接的克隆，否则 ~/.xsos-ai-skills）
#   XSOS_SKILLS_REPO_URL  仓库地址（默认 GitHub 公开仓库，测试时可指向本地克隆）
#   XSOS_SKILLS_TARGETS   软链目标目录，空格分隔（默认 ~/.claude/skills ~/.codex/skills）
set -eu

REPO_URL="${XSOS_SKILLS_REPO_URL:-https://github.com/xsosglobal/xsos-ai-skills.git}"
SKILLS="xsos-context-pack xsos-feedback-fix xsos-project-guard xsos-wbs-author xsos-wbs-pack"
TARGETS="${XSOS_SKILLS_TARGETS:-$HOME/.claude/skills $HOME/.codex/skills}"

say() { printf '%s\n' "$*"; }
die() { printf '停止：%s\n' "$*" >&2; exit 1; }

command -v git >/dev/null 2>&1 || die "没有找到 git，请先安装 git"

# 没指定位置时，沿用已经链接好的那份克隆（按旧 README 装在 ~/work/gitee 下的同事不会多出第二份）。
existing_clone() {
  for target in $TARGETS; do
    link="$target/xsos-wbs-pack"
    if [ -L "$link" ]; then
      dest=$(cd "$link" 2>/dev/null && pwd -P) || continue
      root=$(dirname "$dest")
      if [ -d "$root/.git" ] && [ -f "$root/xsos-wbs-pack/SKILL.md" ]; then
        printf '%s\n' "$root"
        return 0
      fi
    fi
  done
  return 1
}

if [ -n "${XSOS_SKILLS_DIR:-}" ]; then
  DIR="$XSOS_SKILLS_DIR"
elif DIR=$(existing_clone); then
  :
else
  DIR="$HOME/.xsos-ai-skills"
fi

if [ ! -e "$DIR" ]; then
  say "== 首次安装：克隆到 $DIR"
  git clone -q "$REPO_URL" "$DIR" || die "克隆失败：$REPO_URL"
else
  [ -d "$DIR/.git" ] || die "$DIR 已存在但不是 git 仓库，请换个位置（XSOS_SKILLS_DIR）或先移走它"
  say "== 更新 $DIR"
  branch=$(git -C "$DIR" symbolic-ref --quiet --short HEAD 2>/dev/null || echo "")
  [ "$branch" = "main" ] || die "$DIR 当前在「${branch:-游离提交}」而不是 main。为免影响你的工作不会切分支，请自行处理后重跑"
  [ -z "$(git -C "$DIR" status --porcelain)" ] || die "$DIR 有未提交的改动，不会覆盖。请提交或暂存后重跑"
  git -C "$DIR" fetch -q origin main || die "拉取远端失败，检查网络后重跑"
  git -C "$DIR" merge -q --ff-only origin/main || die "本地 main 有远端没有的提交，无法快进。请自行处理后重跑"
fi

VERSION=$(git -C "$DIR" rev-parse --short HEAD)
ROOT=$(cd "$DIR" && pwd -P)
status=0
for target in $TARGETS; do
  mkdir -p "$target"
  for skill in $SKILLS; do
    src="$ROOT/$skill"
    link="$target/$skill"
    [ -d "$src" ] || { say "  ✗ $link  仓库里没有 $skill"; status=1; continue; }
    if [ -L "$link" ]; then
      current=$(cd "$link" 2>/dev/null && pwd -P || echo "")
      if [ "$current" = "$src" ]; then
        say "  ✓ $link"
      else
        say "  ! $link  已指向 $(readlink "$link")，没有覆盖；要改用本克隆请先删掉这个软链再重跑"
        status=1
      fi
    elif [ -e "$link" ]; then
      say "  ! $link  已是真实目录或文件，没有覆盖；请先备份移走再重跑"
      status=1
    else
      ln -s "$src" "$link"
      say "  + $link"
    fi
  done
done
say "== 当前版本 $VERSION（$ROOT）"
[ "$status" = 0 ] || say "有条目没有处理，见上方 ! 标记。"
exit "$status"
