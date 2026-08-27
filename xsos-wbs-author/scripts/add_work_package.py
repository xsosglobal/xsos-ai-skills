#!/usr/bin/env python3
"""把一个工作包写进 WBS Pack，并保证写完之后结构门禁仍然通过。

为什么要有这个脚本：手工往 `docs/wbs` 里加工作包，出错的从来不是想不清楚
需求，而是机械动作——插错位置、往表格中间带进一个空行(后面所有行会被
validator 静默跳过)、wp_id 撞号、`acceptance_ref` 和 `06-acceptance.md` 的
标题对不上、忘了写 `01-requirements.md` 章节导致门禁直接红。

所以这里的分工是：**理解需求交给人或模型，改文件交给这个脚本。**
脚本只做确定性的事，做完立刻跑一遍 validator；不通过就整体回滚，
绝不留下半截的 pack。

用法:
    add_work_package.py <pack_dir> --spec spec.json
    add_work_package.py <pack_dir> --spec -            # 从 stdin 读
    add_work_package.py <pack_dir> --spec spec.json --dry-run
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = SKILL_ROOT.parent / "xsos-wbs-pack" / "scripts" / "validate_wbs_pack.py"

WP_ID_RE = re.compile(r"WP-[A-Z0-9]+(?:-[A-Z0-9]+)?-\d{3}")
ALLOWED_STATUS = {
    "proposed", "todo", "in_progress", "blocked", "review", "done", "cancelled",
}

# 02-wbs.md 的列序。顺序错了整张表就串位，所以写死在这里。
COLUMNS = [
    "wp_id", "title_cn", "title_en", "type", "owner", "status",
    "depends_on", "scope", "non_goals", "acceptance_ref", "outputs",
]
REQUIRED = [
    "title_cn", "title_en", "type", "owner", "scope",
    "requirements", "acceptance",
]


class SpecError(Exception):
    pass


def read_spec(source: str) -> dict:
    raw = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SpecError(f"spec 不是合法 JSON: {exc}") from exc
    if not isinstance(spec, dict):
        raise SpecError("spec 顶层必须是对象")
    return spec


def next_wp_id(wbs_text: str, series: str) -> str:
    """取该系列的最大编号 + 1。编号只增不复用——复用会让历史引用指向别的包。"""
    prefix = f"WP-{series}-"
    used = [
        int(m.group(1))
        for m in re.finditer(rf"^\| {re.escape(prefix)}(\d{{3}}) \|", wbs_text, re.M)
    ]
    return f"{prefix}{max(used, default=0) + 1:03d}"


def table_cell(value: str, field: str) -> str:
    """表格单元格不能含 | 或换行，否则整行结构被破坏。不静默替换，直接报错。"""
    if "|" in value:
        raise SpecError(f"字段 {field} 含 `|`，会把表格切断。请改写这段文字后重试。")
    if "\n" in value:
        raise SpecError(f"字段 {field} 含换行，表格行必须是一行。请改写后重试。")
    return " ".join(value.split())


def bullets(items, field: str) -> str:
    if isinstance(items, str):
        items = [items]
    if not isinstance(items, list) or not items:
        raise SpecError(f"{field} 必须是非空的字符串数组")
    out = []
    for item in items:
        text = str(item).strip()
        if not text:
            raise SpecError(f"{field} 里有空条目")
        out.append("- " + text if not text.startswith("-") else text)
    return "\n".join(out)


def insert_after_heading(text: str, heading: str, block: str, path: Path) -> str:
    """插在一级标题之后，成为最新的一节。新东西放最上面，翻文件的人先看到。"""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.strip() == heading:
            rest = lines[index + 1:]
            while rest and not rest[0].strip():
                rest.pop(0)
            return "\n".join([line, "", block.rstrip(), ""] + rest) + "\n"
    raise SpecError(f"{path.name} 里找不到标题 `{heading}`，文件结构和预期不符")


def insert_wbs_row(text: str, row: str, path: Path) -> str:
    """插在分隔行的正下方。绝不引入空行——空行会把表格切成两张，
    validator 只认第一张，后面的工作包会被静默跳过。"""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if re.match(r"^\|\s*-{2,}", line.replace(" ", "")) or re.match(r"^\|(\s*---+\s*\|)+$", line):
            lines.insert(index + 1, row)
            return "\n".join(lines) + "\n"
    raise SpecError(f"{path.name} 里找不到表格分隔行，文件结构和预期不符")


def build(pack: Path, spec: dict) -> tuple[dict[Path, str], str]:
    wbs_path = pack / "02-wbs.md"
    req_path = pack / "01-requirements.md"
    acc_path = pack / "06-acceptance.md"
    for path in (wbs_path, req_path, acc_path):
        if not path.exists():
            raise SpecError(f"缺少 {path.name}，这不像一个 WBS Pack")

    missing = [f for f in REQUIRED if not spec.get(f)]
    if missing:
        raise SpecError("spec 缺字段: " + ", ".join(missing))

    wbs_text = wbs_path.read_text(encoding="utf-8")
    series = str(spec.get("series", "BE")).upper()
    wp_id = str(spec.get("wp_id") or next_wp_id(wbs_text, series)).strip()
    if not WP_ID_RE.fullmatch(wp_id):
        raise SpecError(f"wp_id 格式不合法: {wp_id}(应形如 WP-BE-079)")
    if re.search(rf"^\| {re.escape(wp_id)} \|", wbs_text, re.M):
        raise SpecError(f"{wp_id} 在 02-wbs.md 里已存在。编号只增不复用，换一个。")

    ac_id = "AC-" + wp_id[len("WP-"):]
    acc_text = acc_path.read_text(encoding="utf-8")
    if re.search(rf"^## {re.escape(ac_id)}\b", acc_text, re.M):
        raise SpecError(f"{ac_id} 在 06-acceptance.md 里已存在")

    status = str(spec.get("status", "todo")).strip()
    if status not in ALLOWED_STATUS:
        raise SpecError(f"status 不合法: {status}(可选 {sorted(ALLOWED_STATUS)})")

    depends = spec.get("depends_on") or "none"
    if isinstance(depends, list):
        depends = ", ".join(str(d).strip() for d in depends) or "none"
    for dep in WP_ID_RE.findall(str(depends)):
        if not re.search(rf"^\| {re.escape(dep)} \|", wbs_text, re.M):
            raise SpecError(f"depends_on 里的 {dep} 不在 02-wbs.md 中，依赖会悬空")

    values = {
        "wp_id": wp_id,
        "title_cn": spec["title_cn"],
        "title_en": spec["title_en"],
        "type": spec["type"],
        "owner": spec["owner"],
        "status": status,
        "depends_on": depends,
        "scope": spec["scope"],
        "non_goals": spec.get("non_goals", "无"),
        "acceptance_ref": ac_id,
        "outputs": spec.get("outputs", "代码, 测试, WBS facts"),
    }
    row = "| " + " | ".join(table_cell(str(values[c]), c) for c in COLUMNS) + " |"

    title = table_cell(str(spec["title_cn"]), "title_cn")
    writes: dict[Path, str] = {
        wbs_path: insert_wbs_row(wbs_text, row, wbs_path),
        req_path: insert_after_heading(
            req_path.read_text(encoding="utf-8"), "# 需求 / Requirements",
            f"## {wp_id} {title}\n\n" + bullets(spec["requirements"], "requirements"), req_path),
        acc_path: insert_after_heading(
            acc_text, "# 验收 / Acceptance",
            f"## {ac_id} {title}\n\n" + bullets(spec["acceptance"], "acceptance"), acc_path),
    }

    if spec.get("risks"):
        risk_path = pack / "07-risks.md"
        if not risk_path.exists():
            raise SpecError("spec 里有 risks，但 pack 里没有 07-risks.md")
        blocks = []
        for index, risk in enumerate(spec["risks"], start=1):
            rid = risk.get("id") or f"RISK-{wp_id[len('WP-'):]}-{index:03d}"
            blocks.append(f"## {rid} {risk['title']}\n\n{risk['body'].strip()}")
        writes[risk_path] = insert_after_heading(
            risk_path.read_text(encoding="utf-8"), "# 风险 / Risks",
            "\n\n".join(blocks), risk_path)

    if spec.get("changelog"):
        log_path = pack / "CHANGELOG.md"
        if not log_path.exists():
            raise SpecError("spec 里有 changelog，但 pack 里没有 CHANGELOG.md")
        day = spec.get("date") or datetime.date.today().isoformat()
        text = log_path.read_text(encoding="utf-8")
        entry = f"- `{wp_id}` {spec['changelog'].strip()}"
        if f"## {day}" in text:
            text = text.replace(f"## {day}\n", f"## {day}\n\n{entry}\n", 1)
            text = re.sub(r"\n\n\n+", "\n\n", text)
        else:
            text = insert_after_heading(text, "# CHANGELOG", f"## {day}\n\n{entry}", log_path)
        writes[log_path] = text

    return writes, wp_id


def run_validator(pack: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), str(pack)], capture_output=True, text=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pack_dir")
    parser.add_argument("--spec", required=True, help="JSON 文件路径，或 - 表示 stdin")
    parser.add_argument("--dry-run", action="store_true", help="只打印将写入的内容，不落盘")
    args = parser.parse_args()

    pack = Path(args.pack_dir).expanduser().resolve()
    try:
        writes, wp_id = build(pack, read_spec(args.spec))
    except SpecError as exc:
        print(f"拒绝写入: {exc}", file=sys.stderr)
        return 2

    if args.dry_run:
        print(f"[dry-run] {wp_id} 将写入 {len(writes)} 个文件:")
        for path in writes:
            print(f"  - {path.name}")
        return 0

    backup = Path(tempfile.mkdtemp(prefix="wbs-author-"))
    for path in writes:
        shutil.copy2(path, backup / path.name)
    try:
        for path, text in writes.items():
            path.write_text(text, encoding="utf-8")
        result = run_validator(pack)
        if result.returncode != 0:
            for path in writes:
                shutil.copy2(backup / path.name, path)
            print("写入后门禁不通过，已整体回滚:", file=sys.stderr)
            print(result.stdout + result.stderr, file=sys.stderr)
            return 1
    finally:
        shutil.rmtree(backup, ignore_errors=True)

    print(f"已写入 {wp_id}: " + ", ".join(sorted(p.name for p in writes)))
    print(result.stdout.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
