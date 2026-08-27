#!/usr/bin/env python3
"""检测 02-wbs.md 的 status 与代码现实是否脱节。

结构门禁校验的是**形状**(唯一性、依赖、需求章节、验收引用),它管不到
「这个包到底做完没有」。2026-08-27 的盘点结果:81 个包里 7 个后端包代码
早已上生产,看板上仍显示 `in_progress`;WP-INTEG-010 阶段一上线了还标
`proposed`。根因是发版流程里没有「回填状态」这一步,所以状态只增不改。

这个脚本把「回填」从"要人记得"变成"机器会喊"。

判据(都是踩过坑之后定的):

- **只看含代码改动的提交。** 立包时那次 `docs(WP-FS-059,...)` 提交也带
  wp_id,但它只改文档,不代表实现——按提交数判断会把立包当成完成。
- **`type=frontend` 的包跳过。** 它们的代码在 web 仓库,而 web 仓库从来
  没在提交信息里写过 wp_id(实测 0 条),在这里查必然查不到,报出来只是
  噪音。
- **`type=fullstack` 单独归一类。** 后端上生产不等于整包完成,前端可能
  还没做,`in_progress` 很可能是准确的——只提示,不断言。
- **不查「标 done 却没提交」。** 早期包(WP-BE-001~004、007)是提交规范
  上线前做的,代码都在,查出来全是假阳性。

默认只警告不阻断:状态滞后不该拦住别人合并代码。要在 CI 里变成硬门禁
加 `--fail`。
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

WP_ROW = re.compile(r"^\|\s*(WP-[A-Z0-9]+(?:-[A-Z0-9]+)?-\d{3})\s*\|")
UNFINISHED = {"todo", "proposed", "in_progress", "blocked"}
DEFAULT_CODE_EXT = (".go", ".ts", ".tsx", ".vue", ".js", ".py", ".java", ".sql")


def parse_rows(wbs_path: Path) -> list[dict]:
    rows = []
    header: list[str] = []
    for line in wbs_path.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not header and cells and cells[0] == "wp_id":
            header = cells
            continue
        if header and WP_ROW.match(line):
            rows.append(dict(zip(header, cells)))
    return rows


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def resolve_ref(repo: Path, preferred: str) -> str | None:
    """CI 上远端引用未必叫 origin/master,逐个试;都没有就明说跳过,不静默。"""
    for ref in (preferred, preferred.split("/")[-1], f"refs/remotes/{preferred}"):
        if git(repo, "rev-parse", "--verify", "--quiet", ref).returncode == 0:
            return ref
    return None


def code_commits(repo: Path, ref: str, wp_id: str, exts: tuple[str, ...]) -> list[str]:
    """返回既提到该 wp_id、又真的改了代码的提交。"""
    shas = git(repo, "log", "--format=%h", ref, f"--grep={wp_id}").stdout.split()
    hits = []
    for sha in shas:
        files = git(repo, "show", "--name-only", "--format=", "-1", sha).stdout.split()
        if any(f.endswith(exts) for f in files):
            hits.append(sha)
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pack_dir")
    parser.add_argument("--repo", action="append", default=None,
                        help="要搜的代码仓库,可重复;默认是 pack 所在仓库")
    parser.add_argument("--prod-ref", default="origin/master", help="生产分支引用")
    parser.add_argument("--code-ext", default=",".join(DEFAULT_CODE_EXT))
    parser.add_argument("--fail", action="store_true", help="发现失真时以非零退出")
    args = parser.parse_args()

    pack = Path(args.pack_dir).expanduser().resolve()
    wbs = pack / "02-wbs.md"
    if not wbs.exists():
        print(f"跳过:{wbs} 不存在", file=sys.stderr)
        return 0

    repos = [Path(r).expanduser().resolve() for r in (args.repo or [])]
    if not repos:
        probe = pack
        while probe != probe.parent and not (probe / ".git").exists():
            probe = probe.parent
        if not (probe / ".git").exists():
            print("跳过:找不到 git 仓库,状态漂移无法检测", file=sys.stderr)
            return 0
        repos = [probe]

    exts = tuple(e if e.startswith(".") else "." + e for e in args.code_ext.split(","))
    rows = parse_rows(wbs)
    drift, ambiguous, skipped = [], [], []

    for row in rows:
        wp_id, status, wtype = row.get("wp_id", ""), row.get("status", ""), row.get("type", "")
        if status not in UNFINISHED:
            continue
        if wtype == "frontend":
            skipped.append(row)
            continue
        for repo in repos:
            ref = resolve_ref(repo, args.prod_ref)
            if ref is None:
                print(f"跳过 {repo.name}:解析不到 {args.prod_ref},"
                      f"CI 里请确认 checkout 带了 fetch-depth: 0", file=sys.stderr)
                continue
            hits = code_commits(repo, ref, wp_id, exts)
            if hits:
                (ambiguous if wtype == "fullstack" else drift).append((row, repo.name, hits))
                break

    # 只有一个仓库时不打仓库名 —— worktree 的目录名和仓库名往往对不上,
    # 打出来反而让人以为查错了地方。
    def where(repo_name: str) -> str:
        return f"{repo_name} " if len(repos) > 1 else ""

    for row, repo_name, hits in drift:
        print(f"! {row['wp_id']} 标 {row['status']},但代码已上生产"
              f"({where(repo_name)}{args.prod_ref} 有 {len(hits)} 次代码提交):"
              f"{row.get('title_cn','')}")
    for row, repo_name, hits in ambiguous:
        print(f"? {row['wp_id']} 标 {row['status']},后端已上生产"
              f"({where(repo_name)}{len(hits)} 次),但这是 fullstack 包,前端未必完成:"
              f"{row.get('title_cn','')}")
    if skipped:
        print(f"- 跳过 {len(skipped)} 个 frontend 包:代码不在本仓库,"
              f"且 web 仓库不写 wp_id,查不到")

    if not drift and not ambiguous:
        print(f"状态与代码一致:{len(rows)} 个工作包无失真")
    else:
        print(f"\n共 {len(drift)} 个确凿失真、{len(ambiguous)} 个待人工判断"
              f"(总 {len(rows)} 个)")

    return 1 if (args.fail and drift) else 0


if __name__ == "__main__":
    raise SystemExit(main())
