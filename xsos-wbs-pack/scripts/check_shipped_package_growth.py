#!/usr/bin/env python3
"""已上生产的包不许再长验收:PR 里给这样的包加验收条目,就是新需求,另立新包。

起因(顾昊 2026-11-07):Portal WP-FE-266 11-04 基础页上了生产,之后刀具前端的每次
改动都以 `### WP-FE-266 xxx(日期)` 追加进同一个包,06-acceptance 追加了 26 节、
CHANGELOG 24 节,包永远 review、结不了。规矩是「一个工作包只做一件事」(SKILL.md
「One Work Package, One Thing」):包里已有内容上过生产之后,再加验收条目 = 新需求。

判据:

- 比较 PR 范围两端 `<base>` 与 `<head>` 的 06-acceptance.md,每个包的验收条目数
  按 validate_wbs_pack.measure_package_acceptance 的口径算(含 AC 节内的 `###`
  小节、以包号或 AC 号开头的增量小节)。
- 条目数变多的包,若 `<prod>` 上已有点名该包号、改了 docs/ 以外文件、subject 不以
  docs 开头的非 merge 提交(与 check_release_baseline.py 认「上线」的口径一致;
  包号可以在 subject、正文或 Work-Package 尾注里)→ 报错「已上生产的包新增验收条目」。
  没上过生产的包随便长(颗粒度上限由 validate_wbs_pack 管)。
- `<base>` 就是生产分支本身(发布 PR)时跳过:发布是把已合入的东西带上去,不是加需求。
- docs/wbs 从两端提交读,不读工作树。

按仓库开启:`<head>` 上的 `<pack>/granularity-baseline.txt` 存在才以非零退出阻断
(与颗粒度、增量续命门禁同一个开关),否则只报告。

用法:
    python3 check_shipped_package_growth.py origin/develop..HEAD --prod origin/master \
        [--pack docs/wbs] [--repo .] [--json]
"""
from __future__ import annotations

import argparse
import importlib.util
import io
import json
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ENABLE_FILE = "granularity-baseline.txt"


def _load_validator():
    path = Path(__file__).resolve().parent / "validate_wbs_pack.py"
    spec = importlib.util.spec_from_file_location("validate_wbs_pack", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    return module


V = _load_validator()


def git(repo: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout


def split_range(rev_range: str) -> tuple[str, str]:
    if ".." not in rev_range:
        raise ValueError(f"范围要写成 <base>..<head>: {rev_range}")
    base, head = rev_range.split("..", 1)
    head = head.lstrip(".") or "HEAD"
    if not base:
        raise ValueError(f"范围缺 base: {rev_range}")
    return base, head


def same_ref(repo: Path, left: str, right: str) -> bool:
    """两个写法是不是同一个分支(不比 sha:develop 刚追平 master 时 sha 相同但不是发布)。"""
    if left == right:
        return True
    names = []
    for ref in (left, right):
        name = git(repo, "rev-parse", "--symbolic-full-name", ref, check=False).strip()
        names.append(name or ref)
    return names[0] == names[1]


def materialize_pack(repo: Path, rev: str, pack: str, into: Path) -> Path | None:
    result = subprocess.run(["git", "-C", str(repo), "archive", rev, pack], capture_output=True)
    if result.returncode != 0:
        return None
    with tarfile.open(fileobj=io.BytesIO(result.stdout)) as archive:
        archive.extractall(into)
    return into / pack


def measure(repo: Path, rev: str, pack: str) -> tuple[dict[str, int], bool]:
    """(包号 -> 验收条目数, 是否开启阻断)。该端没有 pack 时返回空。"""
    with tempfile.TemporaryDirectory() as tmp:
        pack_dir = materialize_pack(repo, rev, pack, Path(tmp))
        if pack_dir is None or not (pack_dir / "02-wbs.md").exists():
            return {}, False
        counts = {wp: int(m["items"]) for wp, m in V.measure_pack(pack_dir).items()}
        return counts, (pack_dir / ENABLE_FILE).exists()


def shipped_commits(repo: Path, prod: str, wp_ids: list[str]) -> dict[str, list[str]]:
    """包号 -> 生产分支上点名它的代码提交(短 sha + subject)。"""
    if not wp_ids:
        return {}
    patterns = {wp: re.compile(rf"(?<![A-Z0-9-]){re.escape(wp)}(?![0-9])") for wp in wp_ids}
    log = git(repo, "log", "--no-merges", "--full-history", "--format=%H%x1f%s%x1f%B%x1e",
              prod, "--", ".", ":(top,exclude)docs/")
    found: dict[str, list[str]] = {}
    for record in log.split("\x1e"):
        record = record.strip("\n")
        if not record:
            continue
        sha, subject, body = (record.split("\x1f") + ["", ""])[:3]
        if subject.lower().startswith("docs"):
            continue
        for wp, pattern in patterns.items():
            if pattern.search(body) or pattern.search(subject):
                found.setdefault(wp, []).append(f"{sha[:8]} {subject}")
    return found


def check(repo: Path, rev_range: str, prod: str, pack: str = "docs/wbs") -> dict:
    base, head = split_range(rev_range)
    report: dict = {"range": rev_range, "prod": prod, "enabled": False, "skipped": "",
                    "grown": [], "errors": [], "warnings": []}
    head_counts, enabled = measure(repo, head, pack)
    report["enabled"] = enabled
    if same_ref(repo, base, prod):
        report["skipped"] = f"base {base} 就是生产分支 {prod}(发布 PR),跳过"
        return report
    if git(repo, "rev-parse", "--verify", "--quiet", f"{prod}^{{commit}}", check=False).strip() == "":
        report["errors"].append(f"取不到生产分支 {prod}(CI 里先 git fetch 它),无法判断哪些包已上生产")
        return report
    if not head_counts:
        report["warnings"].append(f"{head} 上没有 {pack}/02-wbs.md,跳过")
        return report
    base_counts, _ = measure(repo, base, pack)
    grown = [(wp, base_counts.get(wp, 0), n) for wp, n in sorted(head_counts.items())
             if n > base_counts.get(wp, 0)]
    shipped = shipped_commits(repo, prod, [wp for wp, _, _ in grown])
    for wp, before, after in grown:
        commits = shipped.get(wp, [])
        report["grown"].append({"wp_id": wp, "before": before, "after": after, "shipped_by": commits[:3]})
        if commits:
            report["errors"].append(
                f"{wp} 已上生产(如 {commits[0]}),本 PR 把它的验收条目从 {before} 增到 {after}:"
                "已上生产的包新增验收条目,请另立新包(来源写同一个 BUG-/REQ- 编号,或注明拆自 "
                f"{wp});只修本包已有验收范围内的问题时不要加验收条目"
            )
    return report


def render(report: dict) -> str:
    mode = "阻断已开启" if report["enabled"] else f"只报告(未放 {ENABLE_FILE})"
    lines = [f"已上生产包增长检查 {report['range']} 生产={report['prod']}({mode})"]
    if report["skipped"]:
        lines.append(report["skipped"])
    elif not report["grown"] and not report["errors"]:
        lines.append("本范围没有包的验收条目变多。")
    for g in report["grown"]:
        state = "已上生产" if g["shipped_by"] else "未上生产,放行"
        lines.append(f"  {g['wp_id']}: {g['before']} -> {g['after']}({state})")
    for e in report["errors"]:
        lines.append(f"✗ {e}")
    for w in report["warnings"]:
        lines.append(f"! {w}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="PR 里已上生产的工作包不许新增验收条目。")
    parser.add_argument("range", help="PR 范围,如 origin/develop..HEAD")
    parser.add_argument("--prod", required=True, help="生产分支引用,如 origin/master 或 origin/main")
    parser.add_argument("--pack", default="docs/wbs", help="WBS pack 相对仓库根的路径")
    parser.add_argument("--repo", default=".", help="仓库根目录")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        report = check(Path(args.repo), args.range, args.prod, args.pack)
    except (RuntimeError, ValueError) as error:
        print(f"✗ {error}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else render(report))
    return 1 if report["enabled"] and report["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
