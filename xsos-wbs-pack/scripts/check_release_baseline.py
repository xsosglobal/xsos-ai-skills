#!/usr/bin/env python3
"""发布时按基线核对:这次上线的包,验收证据是否齐全,状态是否如实。

起因(2026-10-16):WP-BE-177 已经上了生产,master 上的 02-wbs.md 还写着 todo。
提交带包号只能让人判断「上没上线」,改不了表里手填的 status;状态得在发布那一刻
对着基线确定。顾昊定的口径:

- **基线** = 包确认时 06-acceptance.md 里它的验收条目,加上 Verification 列出的测试。
- 发布时逐包核对:测试都在 → 这个包的范围交付了,应当标 done;
  缺测试却标 done → 错误;只交付了一部分 → 不设模糊状态,**拆包**:
  已交付部分收窄为本包标 done,剩余拆成新包,来源行指向本包。
- 一个包只做一件事;一个需求/BUG 可以拆成多个包。

只核对**存在性**(测试文件与测试函数在发布版本里存在)。测试是否通过由仓库自己的
CI 测试步骤保证——这里再跑一遍既慢又重复。

判据:

- 范围内只看非 merge、改了 docs/ 以外文件、且 subject 不以 docs 开头的提交
  (立包提交常顺手改两行代码,subject 前缀比文件后缀更能说明意图)。
- 只认 subject 里点名、且在本仓库 02-wbs.md 里存在的包号;别的仓库的包号忽略。
- docs/wbs 从**范围末端提交**读,不读工作树——本机工作树陈旧时会读到旧状态。

按仓库开启:`<pack>/release-check.enabled` 在范围末端存在才以非零退出阻断,
否则只报告。

用法:
    python3 check_release_baseline.py origin/master..HEAD [--pack docs/wbs] [--repo .] [--json]
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

ENABLE_FILE = "release-check.enabled"
WP_IN_SUBJECT = re.compile(r"(?<![A-Z0-9-])WP-[A-Z]+(?:-[A-Z0-9]+)*-\d{3,5}(?![0-9])")
GO_TEST = r"^func ({name})\s*\("
PY_TEST = r"^\s*def ({name})\s*\("


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


def range_end(rev_range: str) -> str:
    return rev_range.split("..")[-1].lstrip(".") or "HEAD"


def released_packages(repo: Path, rev_range: str) -> dict[str, list[str]]:
    """包号 -> 点名它的提交(短 sha + subject)。"""
    found: dict[str, list[str]] = {}
    for sha in git(repo, "rev-list", "--no-merges", rev_range).split():
        subject = git(repo, "log", "-1", "--format=%s", sha).strip()
        if subject.lower().startswith("docs"):
            continue
        files = git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "--root", sha).split()
        if not files or all(f.startswith("docs/") for f in files):
            continue
        for wp_id in dict.fromkeys(WP_IN_SUBJECT.findall(subject)):
            found.setdefault(wp_id, []).append(f"{sha[:8]} {subject}")
    return found


def materialize_pack(repo: Path, rev: str, pack: str, into: Path) -> Path | None:
    result = subprocess.run(["git", "-C", str(repo), "archive", rev, pack], capture_output=True)
    if result.returncode != 0:
        return None
    with tarfile.open(fileobj=io.BytesIO(result.stdout)) as archive:
        archive.extractall(into)
    return into / pack


def file_at(repo: Path, rev: str, rel: str) -> str | None:
    result = subprocess.run(["git", "-C", str(repo), "show", f"{rev}:{rel}"], capture_output=True)
    if result.returncode != 0:
        return None
    return result.stdout.decode("utf-8", errors="replace")


def has_symbol(text: str, rel: str, symbol: str) -> bool:
    name = re.escape(symbol)
    if rel.endswith(".go"):
        return re.search(GO_TEST.format(name=name), text, re.M) is not None
    if rel.endswith(".py"):
        return re.search(PY_TEST.format(name=name), text, re.M) is not None
    # TS/JS/shell 的测试没有统一的函数形状,按名字出现即可。
    return re.search(rf"(?<![\w$]){name}(?![\w$])", text) is not None


def chinese_items(section: str) -> list[str]:
    chinese = re.split(r"\nEnglish:|\n\nVerification:", section)[0]
    return [line.strip()[2:].strip() for line in chinese.splitlines() if line.strip().startswith("- ")]


def check(repo: Path, rev_range: str, pack: str = "docs/wbs") -> dict:
    end = range_end(rev_range)
    released = released_packages(repo, rev_range)
    report: dict = {"range": rev_range, "end": git(repo, "rev-parse", "--short", end).strip(),
                    "enabled": False, "packages": [], "ignored": [], "errors": [], "warnings": []}
    with tempfile.TemporaryDirectory() as tmp:
        pack_dir = materialize_pack(repo, end, pack, Path(tmp))
        if pack_dir is None or not (pack_dir / "02-wbs.md").exists():
            report["warnings"].append(f"{end} 上没有 {pack}/02-wbs.md,跳过发布核对")
            return report
        report["enabled"] = (pack_dir / ENABLE_FILE).exists()
        _, rows = V.parse_wbs_rows(pack_dir / "02-wbs.md")
        by_id = {V.clean_cell(r.get("wp_id", "")): r for _, r in rows}
        sections = V.collect_acceptance_sections(pack_dir / "06-acceptance.md")
        verification = V._acceptance_verification_blocks(pack_dir / "06-acceptance.md")

    for wp_id, commits in sorted(released.items()):
        row = by_id.get(wp_id)
        if row is None:
            report["ignored"].append(wp_id)
            continue
        status = V.clean_cell(row.get("status", "")).lower()
        entry = {"wp_id": wp_id, "title": V.clean_cell(row.get("title_cn", "")), "status": status,
                 "commits": commits, "evidence": [], "missing": [], "manual": [], "unverified_items": [],
                 "verdict": "", "message": ""}
        for ac_id in V.split_refs(row.get("acceptance_ref", "")):
            block = verification.get(ac_id, "")
            locators = V.EVIDENCE_LOCATOR_RE.findall(block)
            for rel, symbol in locators:
                label = f"{rel}:{symbol}" if symbol else rel
                text = file_at(repo, end, rel)
                if text is not None and (not symbol or has_symbol(text, rel, symbol)):
                    entry["evidence"].append(label)
                else:
                    entry["missing"].append(label)
            manual = [line.strip() for line in block.splitlines() if V.EVIDENCE_MANUAL_RE.match(line.strip())]
            entry["manual"].extend(f"{ac_id} {line}" for line in manual)
            if not locators and not manual:
                entry["unverified_items"].extend(f"{ac_id} {item}" for item in chinese_items(sections.get(ac_id, "")))

        split_hint = ("如果这次只交付了一部分:把本包范围收窄为已交付的部分并标 done,"
                      "剩余拆成新包、来源行指向本包")
        if entry["missing"]:
            if status == "done":
                entry["verdict"] = "error"
                entry["message"] = f"标了 done,但基线里的测试在发布版本中找不到;{split_hint}"
            else:
                entry["verdict"] = "warning"
                entry["message"] = f"基线里有测试还不存在,本包不能标 done;{split_hint}"
        elif not entry["evidence"]:
            if status == "done" and not entry["manual"]:
                entry["verdict"] = "error"
                entry["message"] = "标了 done,但验收没有任何可核对的测试,也没有标注人工验收"
            else:
                entry["verdict"] = "warning"
                entry["message"] = "验收没有可核对的测试,下列条目需要人工逐条确认后再标 done"
        elif status != "done":
            entry["verdict"] = "warning"
            entry["message"] = f"基线测试都在,本包随这次发布上线,02-wbs.md 状态应改为 done(现在是 {status or '空'})"
        else:
            entry["verdict"] = "ok"
            entry["message"] = "基线测试都在,状态为 done"
        if entry["verdict"] == "ok" and entry["unverified_items"]:
            entry["message"] += ";另有验收没有测试,需人工确认"
        report["packages"].append(entry)
        bucket = report["errors"] if entry["verdict"] == "error" else report["warnings"] if entry["verdict"] == "warning" else None
        if bucket is not None:
            bucket.append(f"{wp_id}: {entry['message']}")
    return report


def render(report: dict) -> str:
    lines = [f"发布核对 {report['range']}(末端 {report['end']},"
             f"{'阻断已开启' if report['enabled'] else '只报告,未开启阻断'})"]
    if not report["packages"]:
        lines.append("范围内没有点名本仓库包号的代码提交。")
    mark = {"ok": "✓", "warning": "!", "error": "✗"}
    for p in report["packages"]:
        lines.append(f"{mark.get(p['verdict'], '?')} {p['wp_id']} {p['title']} [status={p['status'] or '空'}] {p['message']}")
        for e in p["evidence"]:
            lines.append(f"    已交付证据: {e}")
        for e in p["missing"]:
            lines.append(f"    缺少: {e}")
        for e in p["manual"]:
            lines.append(f"    人工验收: {e}")
        for e in p["unverified_items"][:12]:
            lines.append(f"    待人工确认: {e}")
        if len(p["unverified_items"]) > 12:
            lines.append(f"    …另有 {len(p['unverified_items']) - 12} 条待人工确认")
    if report["ignored"]:
        lines.append(f"不在本仓库 02-wbs.md 的包号(多为别的仓库,已忽略): {', '.join(report['ignored'])}")
    for w in [w for w in report["warnings"] if not re.match(r"^WP-", w)]:
        lines.append(f"! {w}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="发布时按基线核对工作包的验收证据与状态。")
    parser.add_argument("range", help="发布范围,如 origin/master..HEAD")
    parser.add_argument("--pack", default="docs/wbs", help="WBS pack 相对仓库根的路径")
    parser.add_argument("--repo", default=".", help="仓库根目录")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = check(Path(args.repo), args.range, args.pack)
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else render(report))
    return 1 if report["enabled"] and report["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
