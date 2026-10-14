#!/usr/bin/env bash
# 一键把本仓库的 XSOS skills 装进 Claude Code 和 Codex。
#
# 用法（任选其一）：
#   curl -fsSL https://raw.githubusercontent.com/xsosglobal/xsos-ai-skills/main/install.sh | bash
#   ./install.sh               # 已经克隆过时，在仓库里直接跑
#   ./install.sh --dry-run     # 只打印要做的事，不改任何文件
#   ./install.sh --uninstall   # 只删除指向本仓库的软链，别的不动
#
# 做法与 README 一致：每个 skill 软链到 ~/.claude/skills 和 ~/.codex/skills，
# 仓库是唯一真源，以后 git pull 即全员同步。凡是带 SKILL.md 的一级目录都会装，
# 新增 skill 不用改本脚本。
#
# 可用环境变量覆盖位置：
#   XSOS_SKILLS_DIR            克隆位置，默认 ~/work/gitee/xsos-ai-skills
#   CLAUDE_CONFIG_DIR          Claude Code 配置目录，默认 ~/.claude
#   CODEX_HOME                 Codex 配置目录，默认 ~/.codex
#   XSOS_DELIVERY_CONTROL_ROOT xsos-delivery-control 位置（xsos-project-guard 要用）
#
# 只支持 macOS / Linux（含 WSL）。克隆走 HTTPS：公司网络 22 端口不通。
set -euo pipefail

REPO_URL="https://github.com/xsosglobal/xsos-ai-skills.git"
DC_URL="https://github.com/xsosglobal/xsos-delivery-control.git"

DRY_RUN=0
UNINSTALL=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --uninstall) UNINSTALL=1 ;;
    -h|--help) sed -n '2,20p' "$0" 2>/dev/null || true; exit 0 ;;
    *) echo "未知参数：${arg}（可用 --dry-run / --uninstall）" >&2; exit 2 ;;
  esac
done

WARNINGS=0
info() { printf '  %s\n' "$*"; }
warn() { printf '  ⚠ %s\n' "$*"; WARNINGS=$((WARNINGS + 1)); }
run() {
  if [ "$DRY_RUN" = 1 ]; then printf '  [dry-run] %s\n' "$*"; else "$@"; fi
}

# ---- 1. 定位仓库：在仓库里跑就用它，否则克隆或更新到 XSOS_SKILLS_DIR ----
script_dir=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

if [ -n "$script_dir" ] && [ -f "$script_dir/xsos-wbs-pack/SKILL.md" ]; then
  REPO_DIR="$script_dir"
else
  REPO_DIR="${XSOS_SKILLS_DIR:-$HOME/work/gitee/xsos-ai-skills}"
fi

echo "== 仓库：$REPO_DIR"
if [ "$UNINSTALL" = 0 ]; then
  if [ ! -e "$REPO_DIR/.git" ]; then
    command -v git >/dev/null || { echo "需要先安装 git" >&2; exit 1; }
    run mkdir -p "$(dirname "$REPO_DIR")"
    run git clone "$REPO_URL" "$REPO_DIR"
  elif [ -z "$(git -C "$REPO_DIR" status --porcelain 2>/dev/null)" ] \
       && [ "$(git -C "$REPO_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null)" = "main" ]; then
    # 只在干净的 main 上快进更新；有本地改动或在别的分支就不碰，免得冲掉别人的东西。
    if [ "$DRY_RUN" = 1 ]; then
      info "[dry-run] git pull --ff-only"
    elif ! git -C "$REPO_DIR" pull -q --ff-only; then
      warn "git pull 失败，继续用本地现有版本"
    fi
  else
    warn "仓库有未提交改动或不在 main 分支，跳过更新，直接用现有内容"
  fi
fi

# ---- 2. 找出所有 skill ----
SKILLS=""
if [ -d "$REPO_DIR" ]; then
  for d in "$REPO_DIR"/*/; do
    [ -f "$d/SKILL.md" ] && SKILLS="$SKILLS $(basename "$d")"
  done
fi
if [ "$UNINSTALL" = 0 ] && [ -z "$SKILLS" ]; then
  if [ "$DRY_RUN" = 1 ] && [ ! -d "$REPO_DIR" ]; then
    echo "[dry-run] 仓库尚未克隆，克隆后才能列出要链接的 skill。"; exit 0
  fi
  echo "在 $REPO_DIR 里没找到任何 SKILL.md" >&2; exit 1
fi

# ---- 3. 软链到两个工具 ----
CLAUDE_SKILLS="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills"
CODEX_SKILLS="${CODEX_HOME:-$HOME/.codex}/skills"
STAMP="$(date +%Y%m%d-%H%M%S)"

link_into() {
  local dest_root="$1" tool="$2" name src dest current
  echo "== ${tool}：$dest_root"
  run mkdir -p "$dest_root"
  for name in $SKILLS; do
    src="$REPO_DIR/$name"
    dest="$dest_root/$name"
    if [ -L "$dest" ]; then
      current="$(readlink "$dest")"
      if [ "$current" = "$src" ]; then info "✓ ${name}（已是最新链接）"; continue; fi
      run ln -sfn "$src" "$dest"
      info "↻ ${name}（原链接指向 ${current}，已改指本仓库）"
    elif [ -e "$dest" ]; then
      # 真实目录/文件：多半是以前手工拷进去的旧版，先备份，绝不直接覆盖。
      run mv "$dest" "$dest.bak-$STAMP"
      run ln -s "$src" "$dest"
      info "↻ ${name}（原有同名目录已备份为 $name.bak-${STAMP}）"
    else
      run ln -s "$src" "$dest"
      info "+ $name"
    fi
  done
}

unlink_from() {
  local dest_root="$1" tool="$2" entry target
  echo "== ${tool}：$dest_root"
  [ -d "$dest_root" ] || { info "目录不存在，跳过"; return; }
  for entry in "$dest_root"/*; do
    [ -L "$entry" ] || continue
    target="$(readlink "$entry")"
    case "$target" in
      "$REPO_DIR"/*) run rm "$entry"; info "- $(basename "$entry")" ;;
    esac
  done
}

if [ "$UNINSTALL" = 1 ]; then
  unlink_from "$CLAUDE_SKILLS" "Claude Code"
  unlink_from "$CODEX_SKILLS" "Codex"
  echo "已卸载软链；仓库本身保留在 ${REPO_DIR}。"
  exit 0
fi

link_into "$CLAUDE_SKILLS" "Claude Code"
link_into "$CODEX_SKILLS" "Codex"

# ---- 4. 运行依赖 ----
echo "== 依赖检查"
if ! command -v python3 >/dev/null; then
  warn "没有 python3：建包、校验脚本都跑不了，请先安装 Python 3"
elif ! python3 -c 'import yaml' 2>/dev/null; then
  warn "python3 缺 PyYAML（xsos-context-pack 要用），请执行：python3 -m pip install --user PyYAML"
else
  info "✓ python3 + PyYAML"
fi

# xsos-project-guard 要读 xsos-delivery-control（私有仓库，没权限不影响其他 skill）。
DC_DIR="${XSOS_DELIVERY_CONTROL_ROOT:-$(dirname "$REPO_DIR")/xsos-delivery-control}"
if [ -d "$DC_DIR" ]; then
  info "✓ xsos-delivery-control：$DC_DIR"
elif [ "$DRY_RUN" = 1 ]; then
  info "[dry-run] 尝试克隆 xsos-delivery-control 到 $DC_DIR"
elif GIT_TERMINAL_PROMPT=0 git clone -q "$DC_URL" "$DC_DIR" 2>/dev/null; then
  info "+ 已克隆 xsos-delivery-control 到 $DC_DIR"
else
  warn "没能克隆 xsos-delivery-control（私有仓库，需要 GitHub 权限）；只影响 xsos-project-guard"
fi

echo
echo "完成：已装 $(echo $SKILLS | wc -w | tr -d ' ') 个 skill：$SKILLS"
echo "请重启 Claude Code / Codex 生效。以后更新：cd \"$REPO_DIR\" && git pull"
[ "$WARNINGS" -gt 0 ] && echo "有 $WARNINGS 条提示需要处理，见上方 ⚠。"
exit 0
