#!/usr/bin/env python3
"""检测 02-wbs.md 的 status 与代码现实是否脱节。

结构门禁校验的是**形状**(唯一性、依赖、需求章节、验收引用),它管不到
「这个包到底做完没有」。2026-08-27 的盘点结果:81 个包里 7 个后端包代码
早已上生产,看板上仍显示 `in_progress`;WP-INTEG-010 阶段一上线了还标
`proposed`。根因是发版流程里没有「回填状态」这一步,所以状态只增不改。

这个脚本把「回填」从"要人记得"变成"机器会喊"。

判据(都是踩过坑之后定的):

- **只认 wp_id 出现在**提交 subject **里的提交。** `--grep` 连正文一起搜,
  而正文里经常写"前端部分归 WP-FS-065"这类交叉引用——那是别人的包在提到
  它,不是它自己在被实现。按你们的规范,归属包写在 subject 的 scope 里。
- **只看含代码改动、且不是 `docs(...)` 的提交。** 立包那次
  `docs(WP-FS-059,WP-FS-060,WP-FS-061): 立三个前端包并写交接说明` 既带
  wp_id、又顺手改了两个 `.go` 文件——光看"有没有碰代码"会把立包当成实现。
  提交类型前缀是比文件后缀更可靠的意图信号。
- **前端包要把 web 仓库一起传进来(`--repo`)。** 它们的代码不在后端仓库,
  只查后端必然查不到。注意 web 仓库在 gitee 和 GitHub 各有一个 remote,
  gitee 那个本地取不到、引用是陈旧的——2026-08-27 我就因为查了 `origin/*`
  得出"web 从不写 wp_id"的错误结论,实际 `github/master` 上有 28 条。
  **配 `--prod-ref` 时务必指到活的那个 remote。**
  没传对应仓库时,该包会被标为"无法验证",而不是当成没做。
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


DOC_COMMIT = re.compile(r"^\s*docs?[(:]")


def code_commits(repo: Path, ref: str, wp_id: str, exts: tuple[str, ...]) -> list[str]:
    """返回既提到该 wp_id、又真的在实现它的提交。

    两道过滤缺一不可:文件后缀挡掉纯文档提交,提交类型前缀挡掉"立包时顺手
    动了两行 DTO"这种——后者文件后缀是 `.go`,但它显然不是实现。
    """
    out = git(repo, "log", "--format=%h%x1f%s", ref, f"--grep={wp_id}").stdout
    hits = []
    for line in out.splitlines():
        if "\x1f" not in line:
            continue
        sha, subject = line.split("\x1f", 1)
        if wp_id not in subject or DOC_COMMIT.match(subject):
            continue
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
        else:
            # 一个仓库都没命中。前端/全栈包如果没把 web 仓库传进来,
            # 这里的"没命中"说明不了任何事,单独记一笔而不是当成没做。
            if wtype in ("frontend", "fullstack") and len(repos) < 2:
                skipped.append(row)

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
        print(f"- 无法验证 {len(skipped)} 个前端/全栈包:只传了一个仓库,"
              f"前端代码不在其中。用 --repo <web 仓库> --prod-ref <活的远端> 补上。")

    if not drift and not ambiguous:
        print(f"状态与代码一致:{len(rows)} 个工作包无失真")
    else:
        print(f"\n共 {len(drift)} 个确凿失真、{len(ambiguous)} 个待人工判断"
              f"(总 {len(rows)} 个)")

    return 1 if (args.fail and drift) else 0


if __name__ == "__main__":
    raise SystemExit(main())
