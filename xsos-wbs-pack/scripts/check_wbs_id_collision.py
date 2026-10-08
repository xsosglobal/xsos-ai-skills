#!/usr/bin/env python3
"""拦住「两条并行工作流取了同一个 WP 号」。

为什么需要：号池是 `docs/wbs/02-wbs.md`，而它是**每个 worktree 一份**的工作树副本。
未提交的占号行对别的 worktree、别的会话完全看不见；远端分支扫描也只能看见已推送的行。
`02-wbs.md` 又是单文件大表格，两处不同位置插入同号行 git 不报冲突 —— 三次事故都是
这么来的（2026-08-18 一天两次、2026-09-29 WP-FE-220、2026-10-07 WP-BE-163）。

取号本身已由 `xsos-wbs-author` 的 add_work_package.py 保证（并集本地 + base + 远端分支
+ 本机号段账，取号当刻原子占号）。这个脚本是**兜底门禁**：拦住绕开工具的手改、跨机窗口
以及"号被抢了但两边都以为没占用"的情况。

硬失败（能在合并前机械判定）：
  1. 02-wbs.md 内部 wp_id 重复；
  2. 相对 base 新出现的行，其 wp_id 在 base 里已经有人用了（= 抢号）。

软提示（既有惯例允许多段，不失败）：
  3. 本次新增的 01-requirements / 06-acceptance 段号与 base 同名。

可选：
  --check-open-prs 同时比对其它 open PR 新增的 wp_id（需要 gh 已登录；查询失败只提示不失败）。

用法：
  python3 check_wbs_id_collision.py docs/wbs                    # 与 origin/develop 比
  python3 check_wbs_id_collision.py docs/wbs --base origin/main
  python3 check_wbs_id_collision.py docs/wbs --check-open-prs --exclude-pr 194
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

WBS_RELATIVE = "02-wbs.md"
SECTIONS = (("01-requirements.md", "WP"), ("06-acceptance.md", "AC"))

ROW_ID_RE = re.compile(r"^\| (WP-[A-Z]+-\d+) \|", re.M)


def parse_wbs_ids(text: str) -> list[str]:
    """02-wbs 表格行里的 wp_id（按出现顺序，保留重复）。"""
    return ROW_ID_RE.findall(text or "")


def parse_section_ids(text: str, prefix: str) -> list[str]:
    """段标题里的编号令牌（用于软提示：既有惯例允许多段，所以不据此失败）。"""
    return re.findall(rf"^## .*?({prefix}-[A-Z]+-\d+[A-Z0-9-]*)", text or "", re.M)


def duplicates_of(values: list[str]) -> list[str]:
    return [value for value in dict.fromkeys(values) if values.count(value) > 1]


def find_wbs_id_conflicts(current: list[str], base: list[str]) -> tuple[list[str], list[str]]:
    """返回 (duplicated, stolen)。

    duplicated：当前文件里自己就出现两次以上；
    stolen：当前出现的次数多于 base，而 base 里这个号已经有人用了 —— 这就是抢号。
    """
    duplicated = duplicates_of(current)
    stolen = [value for value in dict.fromkeys(current)
              if value in base and current.count(value) > base.count(value)]
    return duplicated, stolen


def added_ids_of(current: list[str], base: list[str]) -> list[str]:
    return [value for value in dict.fromkeys(current) if value not in base]


def find_added_section_ids(current: list[str], base: list[str]) -> list[str]:
    """只关心「本次比 base 多出一段同名」；base 里原本就重复的属于既有写法。"""
    return [value for value in dict.fromkeys(current)
            if value in base and current.count(value) > base.count(value)]


def repo_root_of(pack: Path) -> Path | None:
    for candidate in (pack, *pack.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def git(repo: Path, *args: str) -> str | None:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    return result.stdout if result.returncode == 0 else None


def read_base(repo: Path, base: str, relative: str) -> str:
    return git(repo, "show", f"{base}:{relative}") or ""


def repo_slug(repo: Path) -> str:
    remote = (git(repo, "remote", "get-url", "origin") or "").strip()
    match = re.search(r"github\.com[:/]([^/]+/[^/.]+)(?:\.git)?$", remote)
    if not match:
        raise RuntimeError(f"无法从 origin 识别 GitHub 仓库：{remote}")
    return match.group(1)


def list_open_pr_ids(slug: str, relative: str, exclude_pr: str) -> tuple[list[tuple[int, str, list[str]]], int]:
    """返回 (能读到 pack 的 PR, 读不到 pack 的 PR 数)。"""
    raw = subprocess.run(["gh", "pr", "list", "--state", "open", "--limit", "100",
                          "--json", "number,title,headRefOid"], capture_output=True, text=True)
    if raw.returncode != 0:
        raise RuntimeError((raw.stderr or raw.stdout).strip() or "gh pr list 失败")
    readable, unreadable = [], 0
    for pr in json.loads(raw.stdout or "[]"):
        if str(pr.get("number")) == str(exclude_pr):
            continue
        shown = subprocess.run(
            ["gh", "api", "-H", "Accept: application/vnd.github.raw",
             f"repos/{slug}/contents/{relative}?ref={pr.get('headRefOid')}"],
            capture_output=True, text=True)
        if shown.returncode != 0:
            unreadable += 1
            continue
        readable.append((int(pr["number"]), str(pr.get("title", "")), parse_wbs_ids(shown.stdout)))
    return readable, unreadable


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pack_dir", nargs="?", default="docs/wbs", help="WBS pack 目录。")
    parser.add_argument("--base", default="origin/develop", help="比对的基准分支。")
    parser.add_argument("--check-open-prs", action="store_true",
                        help="同时比对其它 open PR 的 wp_id（需要 gh 已登录）。")
    parser.add_argument("--exclude-pr", default="", help="跳过这个 PR 号（通常是当前 PR 自己）。")
    args = parser.parse_args()

    pack = Path(args.pack_dir).expanduser().resolve()
    wbs_path = pack / WBS_RELATIVE
    if not wbs_path.is_file():
        print(f"WBS 撞号检查失败：找不到 {wbs_path}")
        return 1

    repo = repo_root_of(pack)
    if repo is None:
        print(f"WBS 撞号检查：{pack} 不在 git 仓库里，跳过")
        return 0

    relative = wbs_path.relative_to(repo).as_posix()
    base_text = read_base(repo, args.base, relative)
    if not base_text:
        print(f"WBS 撞号检查：取不到 {args.base}:{relative}，跳过（先在 CI/本地 fetch 该分支）")
        return 0

    current_ids = parse_wbs_ids(wbs_path.read_text(encoding="utf-8"))
    base_ids = parse_wbs_ids(base_text)
    duplicated, stolen = find_wbs_id_conflicts(current_ids, base_ids)
    added = added_ids_of(current_ids, base_ids)

    problems = []
    if duplicated:
        problems.append(f"02-wbs.md 内 wp_id 重复：{', '.join(duplicated)}")
    if stolen:
        problems.append(f"以下 wp_id 在 {args.base} 已存在，本次又新增了一行（抢号）：{', '.join(stolen)}")

    if args.check_open_prs and added:
        try:
            readable, unreadable = list_open_pr_ids(repo_slug(repo), relative, args.exclude_pr)
        except (RuntimeError, OSError) as exc:
            print(f"WBS 撞号检查：open PR 比对跳过（{exc}）")
            readable, unreadable = [], 0
        for number, title, ids in readable:
            hit = [value for value in ids if value in added]
            if hit:
                problems.append(f"与 open PR #{number}（{title}）抢同一个号：{', '.join(hit)}")
        if unreadable:
            print(f"WBS 撞号检查：{unreadable} 个 open PR 的 pack 读不到，未参与比对")

    for name, prefix in SECTIONS:
        repeated = find_added_section_ids(
            parse_section_ids((pack / name).read_text(encoding="utf-8"), prefix),
            parse_section_ids(read_base(repo, args.base, (pack / name).relative_to(repo).as_posix()), prefix))
        if repeated:
            print(f"WBS 撞号检查（提示，不失败）：{name} 本次新增了与 base 同名的段 "
                  f"{', '.join(repeated)}；若属于同包多段可忽略，否则请检查编号。")

    if problems:
        for problem in problems:
            print(f"WBS 撞号检查失败：{problem}", file=sys.stderr)
        return 1
    print(f"WBS 撞号检查通过（新增 wp_id：{', '.join(added) if added else '无'}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
