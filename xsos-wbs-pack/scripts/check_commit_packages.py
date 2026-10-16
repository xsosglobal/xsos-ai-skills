#!/usr/bin/env python3
"""提交必须点名工作包：玄枢判断「已上测试 / 已上生产 / 确定相关」都靠提交信息。

为什么需要：玄枢在生产、测试分支的提交里找包号，判断一个包上没上线；修小源 BUG 的
提交带 `Bug-Fix:` 与 `Work-Package:` 尾注，玄枢才能把这个包认成该 BUG 的「确定相关」
修复包（dsh-delivery lib/feedback-release-trace.js 的 bugPackagesFromLog）。提交里不写，
状态就只能靠人手动改，反馈也只能靠猜「可能相关」。

规则（逐个非合并提交检查）：
  1. 改了 docs/ 以外文件的提交，提交信息里必须出现至少一个本仓库的包号 WP-XX-NNN，
     即在 docs/wbs/02-wbs.md 表格里存在（以范围末端提交里的 02-wbs.md 为准）；
     同时提到别的仓库的包号不算错。只改 docs/ 的提交跳过。
  2. 带 `Bug-Fix:` 尾注的提交，尾注值必须是 BUG-<12 位大写十六进制>，并且同时有
     `Work-Package:` 尾注，点名 02-wbs.md 里存在的包号。

按仓库开启（与来源门禁一致）：pack 目录里有 `commit-check.enabled` 才阻断（退出码 1）；
没有只打印警告、退出码 0，方便先接进 CI 看存量再开闸。

用法：
  python3 check_commit_packages.py origin/develop..HEAD
  python3 check_commit_packages.py origin/develop..HEAD --pack docs/wbs
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ENABLE_FILE = "commit-check.enabled"
ROW_ID_RE = re.compile(r"^\|\s*(WP-[A-Z]+-\d+)\s*\|", re.M)
# 与玄枢 feedback-release-trace.js 的 wpPattern 同形：前后不能贴着编号字符。
WP_RE = re.compile(r"(?<![A-Z0-9-])WP-[A-Z]+-\d{1,5}(?![0-9])")
BUG_VALUE_RE = re.compile(r"^BUG-[0-9A-F]{12}$")
TRAILER_RE = re.compile(r"^(Bug-Fix|Work-Package):\s*(.*)$", re.M)


def known_packages(wbs_text: str) -> set[str]:
    return set(ROW_ID_RE.findall(wbs_text or ""))


def needs_package(paths: list[str]) -> bool:
    """改了 docs/ 以外的文件才需要点名包号；空提交不需要。"""
    return any(not p.startswith("docs/") for p in paths)


def commit_problems(message: str, paths: list[str], known: set[str]) -> list[str]:
    problems: list[str] = []
    mentioned = list(dict.fromkeys(WP_RE.findall(message)))
    # 提到别的仓库的包号很正常（跨仓库联动），只要求至少点名一个本仓库的包。
    if needs_package(paths) and not any(wp in known for wp in mentioned):
        if mentioned:
            problems.append(f"提交信息里的包号都不在本仓库 02-wbs.md 里：{', '.join(mentioned)}")
        else:
            problems.append("改了 docs/ 以外的文件，但提交信息没写包号（例：feat(WP-BE-123): …）")
    trailers: dict[str, list[str]] = {}
    for key, value in TRAILER_RE.findall(message):
        trailers.setdefault(key, []).append(value.strip())
    for value in trailers.get("Bug-Fix", []):
        bugs = [v.strip() for v in re.split(r"[,，、\s]+", value) if v.strip()]
        bad = [b for b in bugs if not BUG_VALUE_RE.match(b)]
        if not bugs or bad:
            problems.append(f"Bug-Fix 尾注要写 BUG-<12位大写十六进制>：{value or '（空）'}")
    if "Bug-Fix" in trailers:
        wps = [wp for v in trailers.get("Work-Package", []) for wp in WP_RE.findall(v)]
        if not wps:
            problems.append("有 Bug-Fix 尾注就必须同时写 Work-Package: WP-XX-NNN 尾注")
        elif not any(wp in known for wp in wps):
            problems.append(f"Work-Package 尾注的包号不在 02-wbs.md 里：{', '.join(wps)}")
    return problems


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True, encoding="utf-8").stdout


def wbs_at_tip(repo: Path, wbs: Path, rev_range: str) -> str:
    """包号表以范围末端提交里的 02-wbs.md 为准，不读工作树（本机工作树可能是旧的）。"""
    tip = "HEAD"
    if ".." in rev_range:
        tip = rev_range.split("..")[-1].lstrip(".") or "HEAD"
    relative = wbs.resolve().relative_to(repo.resolve()).as_posix()
    try:
        return git(repo, "show", f"{tip}:{relative}")
    except subprocess.CalledProcessError:
        return wbs.read_text(encoding="utf-8")


def check_range(repo: Path, rev_range: str, known: set[str]) -> list[tuple[str, str, list[str]]]:
    failures = []
    for sha in git(repo, "rev-list", "--no-merges", "--reverse", rev_range).split():
        paths = [p for p in git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "--root", sha).splitlines() if p]
        message = git(repo, "log", "-1", "--format=%B", sha)
        problems = commit_problems(message, paths, known)
        if problems:
            failures.append((sha[:10], message.splitlines()[0] if message.strip() else "", problems))
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("range", help="要检查的提交范围，例如 origin/develop..HEAD")
    parser.add_argument("--pack", default="docs/wbs", help="WBS pack 目录（默认 docs/wbs）")
    args = parser.parse_args()
    pack = Path(args.pack).resolve()
    wbs = pack / "02-wbs.md"
    if not wbs.exists():
        print(f"提交包号检查失败：找不到 {wbs}", file=sys.stderr)
        return 1
    enforce = (pack / ENABLE_FILE).exists()
    try:
        repo = Path(git(pack, "rev-parse", "--show-toplevel").strip())
        failures = check_range(repo, args.range, known_packages(wbs_at_tip(repo, wbs, args.range)))
    except subprocess.CalledProcessError as exc:
        print(f"提交包号检查失败：git 执行出错（{(exc.stderr or '').strip()}）；CI 里先 fetch 对比分支", file=sys.stderr)
        return 1
    if not failures:
        print(f"提交包号检查通过（{args.range}）")
        return 0
    head = "提交包号检查失败" if enforce else "提交包号检查（提示，不失败；仓库未放 " + ENABLE_FILE + "）"
    out = sys.stderr if enforce else sys.stdout
    for sha, subject, problems in failures:
        for problem in problems:
            print(f"{head}：{sha} {subject} —— {problem}", file=out)
    return 1 if enforce else 0


if __name__ == "__main__":
    sys.exit(main())
