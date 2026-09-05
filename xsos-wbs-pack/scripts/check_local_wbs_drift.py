#!/usr/bin/env python3
"""检测「只存在于本地、没推上去」的 WBS 改动。

`check_status_drift.py` 比对的是**远端**：拿远端 pack 的状态和远端历史对账。
这意味着有一整类失真它天生看不见——**改动还躺在本地没推**。

2026-09-05 踩到的实例：`xsos_admin` 的 develop worktree 停在 8-30，本地
develop 领先远端 2 个提交，其中带进来一个 `WP-BE-082 status=in_progress`。
那条打印批次路线 9-04 已经决定判废，但**决定没有人执行**。这个包在远端
根本不存在，于是成了一个永远 `in_progress`、永不收敛的幽灵包，在本地漂了
六天没人发现——而 CI 每次都是绿的，因为 CI 看的就是远端。

所以这个检查**只能在本机跑，放进 CI 没有意义**：CI 检出的就是远端，它没有
「本地未推」这个概念。

判据（都是那次事故推出来的）：

- **判定「未推」用 `--not --remotes`。** 一条提交只要没被任何 remote-tracking
  ref 够到，它对 CI、看板、状态漂移检测就都是隐形的。这比 ahead/behind 准：
  分支的上游可能压根没设，或者指着一个陈旧的 remote（web 仓库的 `origin`
  就是这种情况）。
- **共享分支按名字认，不按有没有上游。** 第一版拿 upstream 当判据，结果一堆
  feature 分支也设了上游，9 条"事故"里大半是正常在途工作。真正区分那次事故的
  是分支角色：它发生在 `develop` 上。
- **幽灵包的基线是集成分支，不是「任何远端」。** 第一版拿所有 153 个 remote ref
  比对，`WP-BE-082` 就"消失"了——它躺在 `feature/wbs-purchase-standardize` 那条
  远端分支上。但看板和交付率统计读的是 develop/master，包在某条 feature 分支上
  存在，统计照样看不见。基线只取集成分支才对得上真实后果。
- **幽灵包按 wp_id 去重。** 同一个包会出现在好几条本地分支上（`WP-BE-040` 实测
  在 5 条上），逐条报等于把一个问题说五遍。
- **在途分支上的幽灵包默认不报。** feature 分支在合并前引入新包是正常流程。
  只有三种情况才喊：落在共享分支上、状态标了 `done`（交付率统计会算它，
  而集成分支根本没有这个包）、或者分支已经陈旧。
- **在途分支按「陈旧」筛。** feature 分支没推是正常的，但两个月前的未推 WBS
  改动是另一回事——那通常意味着一个决定做了没执行。默认 30 天。
- **remote-tracking ref 陈旧会造成假阳性，所以宁可跳过也不猜。** `--not --remotes`
  查的是**本地**的 remote-tracking ref。仓库久没 fetch，一条早就推上去的分支
  在本地看起来就像"没推"——2026-09-05 实测踩到：xsos-gallery 的
  `hotfix/gallery-frontend-base-20260717` 被报成未推，实际它的 PR #8 从 7-17
  就开着、分支一直在远端，只是本地从没 fetch 过那条 ref。所以超过
  `--max-fetch-age` 没 fetch 的仓库**直接跳过并说明**，而不是报一个不可靠的结论。
  要一次性拿准结果加 `--fetch`。
- **worktree 不用特殊处理，但要按 `.git` 去重。** worktree 里检出的分支同样是
  本仓的本地 ref，`for-each-ref refs/heads` 一并扫到——事故就发生在一个 worktree
  里。反过来，主克隆和它的 worktree 共享同一个 `.git`，逐个传进来会把同一条分支
  报两遍，所以按 `--git-common-dir` 去重。

默认只警告不阻断；要在钩子里变成硬失败加 `--fail`。
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_status_drift import WP_ROW, git  # noqa: E402

SHARED_NAMES = {"develop", "master", "main", "trunk"}
SHARED_PREFIXES = ("release/", "hotfix/")


def is_shared(branch: str) -> bool:
    return branch in SHARED_NAMES or branch.startswith(SHARED_PREFIXES)


def parse_rows_text(text: str) -> list[dict]:
    """和 check_status_drift.parse_rows 同一套解析，只是喂的是 `git show` 的输出。"""
    rows: list[dict] = []
    header: list[str] = []
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not header and cells and cells[0] == "wp_id":
            header = cells
            continue
        if header and WP_ROW.match(line):
            rows.append(dict(zip(header, cells)))
    return rows


def has_any_unpushed(repo: Path, pack: str) -> bool:
    """一次调用回答「这个仓库有没有未推的 pack 改动」。

    干净的仓库是常态，而逐分支扫在 xsos_admin 上要 5 秒（49 条本地分支）。
    先用一次 `--branches --not --remotes` 判空，干净就直接返回——
    这样它才快到可以挂在开工路径上，而不是变成一个没人跑的脚本。
    """
    out = git(repo, "log", "-1", "--format=%h", "--branches", "--not", "--remotes", "--", pack)
    return bool(out.stdout.strip())


def branches(repo: Path) -> list[str]:
    """本地分支。worktree 里检出的也在内。"""
    out = git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads")
    return [b for b in out.stdout.splitlines() if b.strip()]


def unpushed(repo: Path, branch: str, pack: str) -> list[tuple[str, str, str]]:
    """这条分支上碰过 pack、且**任何远端都够不到**的提交，新的在前。"""
    out = git(repo, "log", "--format=%h\t%ad\t%s", "--date=short",
              branch, "--not", "--remotes", "--", pack)
    rows = []
    for line in out.stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            rows.append((parts[0], parts[1], parts[2]))
    return rows


def baseline_ids(repo: Path, pack: str) -> set[str]:
    """集成分支（远端 develop/master/main/release-*）上已知的 wp_id。

    刻意不取全部 remote ref：包躺在某条远端 feature 分支上，看板和交付率
    统计一样看不见它，那不该算"已知"。
    """
    ids: set[str] = set()
    refs = git(repo, "for-each-ref", "--format=%(refname:short)", "refs/remotes")
    for ref in refs.stdout.splitlines():
        ref = ref.strip()
        if not ref or ref.endswith("/HEAD"):
            continue
        branch = ref.split("/", 1)[1] if "/" in ref else ref
        if not is_shared(branch):
            continue
        shown = git(repo, "show", f"{ref}:{pack}/02-wbs.md")
        if shown.returncode == 0:
            ids.update(r["wp_id"] for r in parse_rows_text(shown.stdout) if r.get("wp_id"))
    return ids


def ghost_rows(repo: Path, branch: str, pack: str, known: set[str]) -> list[dict]:
    """本地这条分支的 pack 里有、而集成分支上没有的工作包行。"""
    if not known:
        return []
    local = git(repo, "show", f"{branch}:{pack}/02-wbs.md")
    if local.returncode != 0:
        return []
    return [r for r in parse_rows_text(local.stdout) if r.get("wp_id") and r["wp_id"] not in known]


def hours_since_fetch(repo: Path) -> float | None:
    """上次 fetch 距今多少小时；判断不了返回 None。"""
    common = git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
    if not common:
        return None
    for name in ("FETCH_HEAD", "refs/remotes"):
        target = Path(common) / name
        if target.exists():
            return (time.time() - target.stat().st_mtime) / 3600
    return None


def days_since(iso: str) -> int:
    try:
        y, m, d = (int(x) for x in iso.split("-"))
        return (date.today() - date(y, m, d)).days
    except ValueError:
        return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="找出只存在于本地、没推上去的 WBS 改动")
    ap.add_argument("--repo", action="append", type=Path, default=None,
                    help="要检查的仓库，可重复；默认当前目录")
    ap.add_argument("--pack", default="docs/wbs", help="pack 目录的仓内相对路径")
    ap.add_argument("--stale-days", type=int, default=30,
                    help="在途分支超过这个天数才逐条列出（默认 30）")
    ap.add_argument("--fetch", action="store_true",
                    help="检查前先 git fetch --all --prune（慢，但结论最可靠）")
    ap.add_argument("--max-fetch-age", type=float, default=24.0,
                    help="超过这么多小时没 fetch 的仓库直接跳过（默认 24；结论会不可靠）")
    ap.add_argument("--fail", action="store_true",
                    help="发现共享分支未推改动或幽灵包时退出码 1")
    args = ap.parse_args()

    repos = args.repo or [Path.cwd()]
    shared: list[tuple[str, str, list]] = []
    inflight: list[tuple[str, str, list]] = []
    ghosts: dict[str, dict] = {}   # wp_id → 聚合信息

    seen_gitdirs: set[str] = set()
    stale_repos: list[tuple[str, float]] = []
    for repo in repos:
        if git(repo, "rev-parse", "--git-dir").returncode != 0:
            print(f"跳过 {repo}：不是 git 仓库", file=sys.stderr)
            continue
        # 主克隆和它的 worktree 共享同一个 .git，扫两遍会把同一条分支报两次
        common = git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
        if common:
            if common in seen_gitdirs:
                continue
            seen_gitdirs.add(common)
        if git(repo, "cat-file", "-e", f"HEAD:{args.pack}/02-wbs.md").returncode != 0 \
                and not (repo / args.pack / "02-wbs.md").exists():
            print(f"跳过 {repo.name}：没有 {args.pack}/02-wbs.md", file=sys.stderr)
            continue

        if args.fetch:
            git(repo, "fetch", "--all", "--prune", "-q")
        age = hours_since_fetch(repo)
        if age is not None and age > args.max_fetch_age:
            stale_repos.append((repo.name, age))
            continue

        if not has_any_unpushed(repo, args.pack):
            continue

        known = baseline_ids(repo, args.pack)
        if not known:
            print(f"跳过 {repo.name} 的幽灵包检查：没有可用的集成分支基线"
                  f"（fetch 一下，或用 --pack 指对目录）", file=sys.stderr)

        for branch in branches(repo):
            commits = unpushed(repo, branch, args.pack)
            if not commits:
                continue
            on_shared = is_shared(branch)
            (shared if on_shared else inflight).append((repo.name, branch, commits))
            stale = days_since(commits[0][1]) >= args.stale_days
            for row in ghost_rows(repo, branch, args.pack, known):
                g = ghosts.setdefault(row["wp_id"], {
                    "row": row, "repo": repo.name, "branches": [],
                    "shared": False, "stale": False,
                })
                g["branches"].append(branch)
                g["shared"] = g["shared"] or on_shared
                g["stale"] = g["stale"] or stale

    for repo_name, branch, commits in shared:
        print(f"! {repo_name} 的共享分支 {branch} 有 {len(commits)} 个未推的 WBS 提交"
              f"——远端、CI、看板都看不到：")
        for sha, when, subject in commits:
            print(f"    {sha} {when} {subject}")

    # 只报"真该看见"的：共享分支上的、标 done 的、或分支已陈旧的。
    # 在途分支上刚立的新包是正常流程，报出来只会淹掉上面三类。
    worth = [g for g in ghosts.values()
             if g["shared"] or g["row"].get("status") == "done" or g["stale"]]
    quiet = len(ghosts) - len(worth)
    for g in sorted(worth, key=lambda g: (not g["shared"], g["row"].get("status") != "done")):
        row = g["row"]
        where = g["branches"][0] if len(g["branches"]) == 1 else f"{len(g['branches'])} 条分支"
        why = "在共享分支上" if g["shared"] else ("标 done" if row.get("status") == "done" else "分支已陈旧")
        print(f"! 幽灵包 {row['wp_id']} 标 {row.get('status', '?')} 集成分支上没有"
              f"（{g['repo']} {where}，{why}）：{row.get('title_cn', '')}")
    if quiet:
        print(f"- 另有 {quiet} 个新包只在在途分支上（合并前立包是正常流程，不报）")

    stale = [x for x in inflight if x[2] and days_since(x[2][0][1]) >= args.stale_days]
    if inflight:
        print(f"- {len(inflight)} 条在途分支带着未推的 WBS 改动"
              f"（没推是正常的，不算失真）")
    if stale:
        print(f"- 其中 {len(stale)} 条已超过 {args.stale_days} 天没动"
              f"——通常意味着一个决定做了没执行：")
        for repo_name, branch, commits in sorted(stale, key=lambda x: x[2][0][1]):
            print(f"    {commits[0][1]}（{days_since(commits[0][1])} 天前）"
                  f" {repo_name} {branch}")

    if stale_repos:
        print(f"? {len(stale_repos)} 个仓库太久没 fetch，跳过了——本地的 remote-tracking ref"
              f"陈旧会让早就推上去的分支看起来像没推：")
        for name, age in sorted(stale_repos, key=lambda x: -x[1]):
            print(f"    {name}（{age / 24:.0f} 天没 fetch）")
        print("    加 --fetch 让它自己先取，或手动 git fetch --all --prune")

    if not shared and not worth:
        print(f"没有发现共享分支上的未推 WBS 改动，也没有该管的幽灵包"
              f"（检查了 {len(repos)} 个仓库）")
    else:
        print(f"\n共 {len(shared)} 条共享分支有未推改动、{len(worth)} 个幽灵包该处理")

    return 1 if (args.fail and (shared or worth)) else 0


if __name__ == "__main__":
    raise SystemExit(main())
