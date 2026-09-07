#!/usr/bin/env python3
"""把一个工作包写进 WBS Pack，并保证写完之后结构门禁仍然通过。

为什么要有这个脚本：手工往 `docs/wbs` 里加工作包，出错的从来不是想不清楚
需求，而是机械动作——插错位置、往表格中间带进一个空行(后面所有行会被
validator 静默跳过)、wp_id 撞号、`acceptance_ref` 和 `06-acceptance.md` 的
标题对不上、忘了写 `01-requirements.md` 章节导致门禁直接红。

所以这里的分工是：**理解需求交给人或模型，改文件交给这个脚本。**
脚本只做确定性的事，做完立刻跑一遍 validator；不通过就整体回滚，
绝不留下半截的 pack。

用法（优先用 stdin，写成文件没人会删它）:
    add_work_package.py <pack_dir> --spec -            # 从 stdin 读，无残留
    add_work_package.py <pack_dir> --spec - --dry-run
    add_work_package.py <pack_dir> --spec spec.json    # 需要留档时才用文件
"""
from __future__ import annotations

import argparse
import datetime
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = SKILL_ROOT.parent / "xsos-wbs-pack" / "scripts" / "validate_wbs_pack.py"

WP_ID_RE = re.compile(r"WP-[A-Z0-9]+(?:-[A-Z0-9]+)?-\d{3}")
REQ_REF_RE = re.compile(
    r"^(REQ-(?:[A-Z0-9]+-)*\d{3})@v([1-9]\d*)$"
)
SRC_ID_RE = re.compile(r"^SRC-(?:[A-Z0-9]+-)*\d{3}$")
RISK_ID_RE = re.compile(r"^RISK-(?:[A-Z0-9]+-)*\d{3}$")
ALLOWED_STATUS = {
    "proposed", "todo", "in_progress", "blocked", "review", "done", "cancelled",
}

# 02-wbs.md 的列序。顺序错了整张表就串位，所以写死在这里。
COLUMNS = [
    "wp_id", "title_cn", "title_en", "type", "owner", "status",
    "depends_on", "scope", "non_goals", "acceptance_ref", "outputs",
]
COMMON_REQUIRED = ["title_cn", "title_en", "type", "owner", "scope", "acceptance"]

V2_REQUIRED_COLUMNS = {
    "wp_id", "title_cn", "title_en", "type", "owner", "status",
    "depends_on", "scope", "non_goals", "acceptance_ref", "outputs",
    "requirement_refs", "delivery_target", "delivery_counted", "baseline_ref",
    "planned_start", "planned_finish", "forecast_finish", "actual_start",
    "actual_finish", "change_ref", "run_ref", "release_ref",
}

SOURCE_HEADING = "## Source Register / 来源登记"
REQUIREMENT_HEADING = "## Requirement Register / 需求登记"
DELIVERY_TARGETS = {"none", "review", "production"}
ARTIFACT_TYPES = ("requirement", "page", "api", "data", "acceptance", "risk", "handoff")
ARTIFACT_DECISIONS = ("page", "api", "data")
SOURCE_REGISTER_COLUMNS = {
    "source_id", "source_type", "source_ref", "captured_at", "note",
}
REQUIREMENT_REGISTER_COLUMNS = {
    "req_id", "version", "requirement_cn", "requirement_en", "priority",
    "owner", "status", "source_refs", "acceptance_refs", "baseline_ref",
    "approved_at", "supersedes", "change_ref",
}
RISK_REGISTER_COLUMNS = {
    "risk_id", "risk_cn", "risk_en", "probability", "impact", "owner",
    "trigger", "response", "due_date", "related_wp", "residual_risk",
    "status", "accepted_by",
}


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


def split_markdown_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def is_separator_row(line: str) -> bool:
    if not line.strip().startswith("|"):
        return False
    cells = split_markdown_row(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def markdown_tables(text: str) -> list[tuple[list[str], int, int, list[list[str]]]]:
    """Return ``(headers, header_index, separator_index, rows)`` for tables.

    Schema v2 deliberately resolves values by header name. Column position may
    change without making the author write into the wrong field.
    """
    lines = text.splitlines()
    tables = []
    for index in range(len(lines) - 1):
        if not lines[index].strip().startswith("|") or not is_separator_row(lines[index + 1]):
            continue
        headers = [cell.lower() for cell in split_markdown_row(lines[index])]
        rows = []
        cursor = index + 2
        while cursor < len(lines) and lines[cursor].strip().startswith("|"):
            rows.append(split_markdown_row(lines[cursor]))
            cursor += 1
        tables.append((headers, index, index + 1, rows))
    return tables


def find_table(text: str, key: str, path: Path) -> tuple[list[str], int, int, list[list[str]]]:
    for table in markdown_tables(text):
        if key in table[0]:
            return table
    raise SpecError(f"{path.name} 里找不到含 `{key}` 列的 Markdown 表格")


def project_schema(pack: Path) -> int:
    """Read schema only from the 00-brief Project Control table.

    A prose mention such as ``wbs_schema: 2`` must not opt a legacy pack into
    stricter behavior. The explicit table row is the migration boundary.
    """
    brief = pack / "00-brief.md"
    if not brief.exists():
        return 1
    selected: list[str] = []
    inside = False
    for line in brief.read_text(encoding="utf-8").splitlines():
        heading = re.match(r"^#{1,6}\s+(.+)$", line)
        if heading:
            if "project control" in heading.group(1).lower():
                inside = True
                selected.append(line)
                continue
            if inside:
                break
        elif inside:
            selected.append(line)
    if not selected:
        return 1

    values: dict[str, str] = {}
    for headers, _, _, rows in markdown_tables("\n".join(selected)):
        if "wbs_schema" in headers:
            if len(rows) != 1:
                raise SpecError("00-brief.md Project Control 宽表必须只有一行数据")
            values.update({
                header: rows[0][index] if index < len(rows[0]) else ""
                for index, header in enumerate(headers)
            })
        elif "field" in headers and "value" in headers:
            field_index = headers.index("field")
            value_index = headers.index("value")
            for row in rows:
                if field_index < len(row):
                    key = row[field_index].strip().lower().replace("-", "_").replace(" ", "_")
                    values[key] = row[value_index].strip() if value_index < len(row) else ""
    raw = values.get("wbs_schema", "")
    if not raw:
        return 1
    try:
        schema = int(raw)
    except ValueError as exc:
        raise SpecError("00-brief.md Project Control 的 wbs_schema 必须是整数") from exc
    if schema not in (1, 2):
        raise SpecError(f"不支持 wbs_schema={schema}")
    return schema


def table_rows_by_key(text: str, key: str, path: Path) -> list[dict[str, str]]:
    headers, _, _, rows = find_table(text, key, path)
    return [
        {header: cells[index] if index < len(cells) else "" for index, header in enumerate(headers)}
        for cells in rows
    ]


def configured_owners(pack: Path) -> tuple[dict[str, str], set[str]]:
    path = pack / "OWNERS.md"
    if not path.exists():
        raise SpecError("wbs_schema=2 缺少 OWNERS.md，不能确认责任人")
    rows = table_rows_by_key(path.read_text(encoding="utf-8"), "role", path)
    roles: dict[str, str] = {}
    names: set[str] = set()
    placeholders = {"", "none", "tbd", "n/a", "-", "owner"}
    for row in rows:
        role = str(row.get("role", "")).strip()
        name = str(row.get("name", "")).strip()
        if not role or name.lower() in placeholders:
            continue
        roles[role] = name
        names.add(name)
    return roles, names


def require_configured_owner(pack: Path, value: object, field: str) -> str:
    owner = str(value or "").strip()
    roles, names = configured_owners(pack)
    if owner in roles or owner in names:
        return owner
    raise SpecError(
        f"{field}={owner or '<empty>'} 未在 OWNERS.md 解析到具体人员；"
        "先填写 owner，再生成 WBS 草案"
    )


def insert_named_table_row(
    text: str,
    key: str,
    values: dict[str, object],
    path: Path,
    *,
    default: str = "",
) -> str:
    headers, _, separator_index, _ = find_table(text, key, path)
    row = "| " + " | ".join(
        table_cell(str(values.get(header, default)), header) for header in headers
    ) + " |"
    lines = text.splitlines()
    lines.insert(separator_index + 1, row)
    return "\n".join(lines) + "\n"


def work_package_ids(text: str) -> set[str]:
    ids: set[str] = set()
    for headers, _, _, rows in markdown_tables(text):
        if "wp_id" not in headers:
            continue
        index = headers.index("wp_id")
        for cells in rows:
            if index < len(cells) and WP_ID_RE.fullmatch(cells[index].strip("` ")):
                ids.add(cells[index].strip("` "))
    return ids


def _used_numbers(text: str, prefix: str) -> list[int]:
    ids = work_package_ids(text)
    if ids:
        return [int(value[len(prefix):]) for value in ids if value.startswith(prefix)]
    # Backward-compatible fallback for small callers/tests that pass row snippets.
    return [int(m.group(1)) for m in re.finditer(rf"{re.escape(prefix)}(\d{{3}})", text)]


def remote_branch_wbs(pack: Path, limit: int = 60) -> str:
    """把所有远端分支上的 02-wbs.md 拼起来。

    只看集成分支还不够:**挂着的 PR 占了号,但那些号还没进 develop**。
    2026-08-27 我的 PR 用 080 等合并期间,并行会话把 080 也用了,两边都
    "看起来没占用"。扫远端分支能把这类冲突提前到写作时暴露,而不是等到
    合并那一刻。

    这挡不住两个会话在同一分钟各自分配的真竞态——那种只能靠门禁的重复
    wp_id 检查兜底。
    """
    repo = _repo_root(pack)
    if repo is None:
        return ""
    rel = (pack.relative_to(repo) / "02-wbs.md").as_posix()
    refs = subprocess.run(
        ["git", "-C", str(repo), "for-each-ref", "--sort=-committerdate",
         f"--count={limit}", "--format=%(refname)", "refs/remotes/origin"],
        capture_output=True, text=True).stdout.split()
    chunks = []
    for ref in refs:
        out = subprocess.run(["git", "-C", str(repo), "show", f"{ref}:{rel}"],
                             capture_output=True, text=True)
        if out.returncode == 0:
            chunks.append(out.stdout)
    return "\n".join(chunks)


def _repo_root(pack: Path) -> Path | None:
    repo = pack
    while repo != repo.parent and not (repo / ".git").exists():
        repo = repo.parent
    return repo if (repo / ".git").exists() else None


def base_ref_wbs(pack: Path, base_ref: str) -> str:
    """读集成分支上的 02-wbs.md。

    编号必须按**集成分支**取,不能只看当前工作树:功能分支往往落后 develop
    十几个提交,按本地文件算出来的号早被别人占了。2026-08-27 连着撞了两次
    ——一次是基于旧 develop 写的包,一次是 PR 挂着的期间号被并行会话抢走。
    """
    repo = _repo_root(pack)
    if repo is None:
        return ""
    rel = pack.relative_to(repo) / "02-wbs.md"
    subprocess.run(["git", "-C", str(repo), "fetch", "--quiet", "origin"],
                   capture_output=True)
    result = subprocess.run(["git", "-C", str(repo), "show", f"{base_ref}:{rel.as_posix()}"],
                            capture_output=True, text=True)
    return result.stdout if result.returncode == 0 else ""


def next_wp_id(wbs_text: str, series: str, base_text: str = "") -> str:
    """取该系列的最大编号 + 1,本地与集成分支取并集。

    编号只增不复用——复用会让历史引用指向别的包。取并集是因为两边都可能有
    对方没有的包:本地有未推的新包,集成分支有别人已合并的新包。
    """
    prefix = f"WP-{series}-"
    used = _used_numbers(wbs_text, prefix) + _used_numbers(base_text, prefix)
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


def insert_after_document_title(text: str, block: str, path: Path) -> str:
    """插在文档的一级标题之后，成为最新的一节。新东西放最上面，翻文件的人先看到。

    只认「第一个一级标题」，不认标题写什么。此前 V1 路径要求逐字匹配
    `# 需求 / Requirements`，而那是 xsos_admin 一家的写法：xsos-auth-center 是
    `# Requirements`，xsos-platform-core 是 `# XSOS Platform Core Requirements`，
    于是这个脚本在那两个仓库上一律拒绝写入——工具照着一个仓库做，把那个仓库的
    写法硬编码了进去。文件路径本来就是调用方给定的，再校验一次标题文本不增加
    任何安全性，只增加脆弱性。
    """
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if re.match(r"^#\s+\S", line):
            rest = lines[index + 1:]
            while rest and not rest[0].strip():
                rest.pop(0)
            return "\n".join([line, "", block.rstrip(), ""] + rest) + "\n"
    raise SpecError(f"{path.name} 里找不到一级标题")


def insert_wbs_row(text: str, row: str, path: Path) -> str:
    """插在分隔行的正下方。绝不引入空行——空行会把表格切成两张，
    validator 只认第一张，后面的工作包会被静默跳过。"""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if re.match(r"^\|\s*-{2,}", line.replace(" ", "")) or re.match(r"^\|(\s*---+\s*\|)+$", line):
            lines.insert(index + 1, row)
            return "\n".join(lines) + "\n"
    raise SpecError(f"{path.name} 里找不到表格分隔行，文件结构和预期不符")


def insert_v2_wbs_row(text: str, values: dict[str, object], path: Path) -> str:
    headers, _, separator_index, _ = find_table(text, "wp_id", path)
    missing = sorted(V2_REQUIRED_COLUMNS - set(headers))
    if missing:
        raise SpecError(
            "wbs_schema=2 的 02-wbs.md 缺少列: " + ", ".join(missing)
        )
    row = "| " + " | ".join(
        table_cell(str(values.get(header, "")), header) for header in headers
    ) + " |"
    lines = text.splitlines()
    lines.insert(separator_index + 1, row)
    return "\n".join(lines) + "\n"


def insert_wp_requirement_section(text: str, block: str) -> str:
    """Keep v2 registers first, then insert the newest WP before older WP sections."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if re.match(r"^##\s+WP-[A-Z0-9-]+\b", line):
            return "\n".join(lines[:index] + [block.rstrip(), ""] + lines[index:]) + "\n"
    return text.rstrip() + "\n\n" + block.rstrip() + "\n"


def ensure_v2_registers(text: str, path: Path) -> str:
    source_block = (
        f"{SOURCE_HEADING}\n\n"
        "| source_id | source_type | source_ref | captured_at | note |\n"
        "|---|---|---|---|---|"
    )
    requirement_block = (
        f"{REQUIREMENT_HEADING}\n\n"
        "| req_id | version | requirement_cn | requirement_en | priority | owner | status | baseline_ref | change_ref | acceptance_refs | source_refs | approved_at | supersedes |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|"
    )
    keys = {header for headers, _, _, _ in markdown_tables(text) for header in headers}
    # Detect by identifier columns, not translated heading order. Existing packs
    # may use either English-first or Chinese-first headings.
    if "req_id" not in keys:
        text = insert_after_document_title(text, requirement_block, path)
    keys = {header for headers, _, _, _ in markdown_tables(text) for header in headers}
    if "source_id" not in keys:
        text = insert_after_document_title(text, source_block, path)
    source_headers, _, _, _ = find_table(text, "source_id", path)
    requirement_headers, _, _, _ = find_table(text, "req_id", path)
    source_missing = sorted(SOURCE_REGISTER_COLUMNS - set(source_headers))
    requirement_missing = sorted(REQUIREMENT_REGISTER_COLUMNS - set(requirement_headers))
    if source_missing:
        raise SpecError("Source Register 缺少列: " + ", ".join(source_missing))
    if requirement_missing:
        raise SpecError("Requirement Register 缺少列: " + ", ".join(requirement_missing))
    return text


def next_source_id(text: str) -> str:
    used = [
        int(match.group(1))
        for match in re.finditer(r"\bSRC-(\d{3})\b", text)
    ]
    return f"SRC-{max(used, default=0) + 1:03d}"


def normalize_source_refs(
    req_text: str, raw_sources: object, req_path: Path, day: str,
) -> tuple[str, list[str]]:
    if isinstance(raw_sources, (str, dict)):
        raw_sources = [raw_sources]
    if not isinstance(raw_sources, list) or not raw_sources:
        raise SpecError("wbs_schema=2 的 source_refs 必须是非空数组")

    refs: list[str] = []
    for raw in raw_sources:
        rows = table_rows_by_key(req_text, "source_id", req_path)
        by_id = {row.get("source_id", ""): row for row in rows}
        by_ref = {row.get("source_ref", ""): row for row in rows if row.get("source_ref")}

        if isinstance(raw, str):
            raw = raw.strip()
            if SRC_ID_RE.fullmatch(raw):
                if raw not in by_id:
                    raise SpecError(f"source_refs 引用了未登记的 {raw}")
                refs.append(raw)
                continue
            source_id = by_ref.get(raw, {}).get("source_id") or next_source_id(req_text)
            source_type = "other"
            source_ref = raw
            captured_at = day
            note = "raw requirement source"
        elif isinstance(raw, dict):
            source_id = str(raw.get("source_id") or "").strip()
            source_ref = str(raw.get("source_ref") or raw.get("ref") or "").strip()
            if source_id and not SRC_ID_RE.fullmatch(source_id):
                raise SpecError(f"source_id 格式不合法: {source_id}")
            if source_id in by_id:
                recorded = by_id[source_id].get("source_ref", "")
                if source_ref and recorded and source_ref != recorded:
                    raise SpecError(f"{source_id} 已登记为另一个来源，不能原地改写")
                refs.append(source_id)
                continue
            if source_ref in by_ref:
                refs.append(by_ref[source_ref]["source_id"])
                continue
            if not source_ref:
                raise SpecError("新 source_refs 条目必须包含 source_ref")
            source_id = source_id or next_source_id(req_text)
            source_type = str(raw.get("source_type") or raw.get("type") or "other").strip()
            captured_at = str(raw.get("captured_at") or day).strip()
            note = str(raw.get("note") or "raw requirement source").strip()
        else:
            raise SpecError("source_refs 条目必须是来源字符串或对象")

        if not source_ref:
            raise SpecError("source_ref 不能为空")
        req_text = insert_named_table_row(req_text, "source_id", {
            "source_id": source_id,
            "source_type": source_type,
            "source_ref": source_ref,
            "captured_at": captured_at,
            "note": note,
        }, req_path)
        refs.append(source_id)

    return req_text, list(dict.fromkeys(refs))


def normalize_requirement_refs(value: object, wp_id: str) -> list[str]:
    if value is None:
        values = ["REQ-" + wp_id[len("WP-"):] + "@v1"]
    elif isinstance(value, str):
        values = [value]
    elif isinstance(value, list) and value:
        values = [str(item) for item in value]
    else:
        raise SpecError("requirement_refs 必须是非空字符串或数组")
    result = []
    for raw in values:
        req_ref = raw.strip()
        if not REQ_REF_RE.fullmatch(req_ref):
            raise SpecError(f"requirement_refs 格式不合法: {req_ref}(应形如 REQ-001@v1)")
        result.append(req_ref)
    if len(result) != len(set(result)):
        raise SpecError("requirement_refs 里有重复项")
    return result


def requirement_statement(items: object) -> str:
    if isinstance(items, str):
        items = [items]
    if not isinstance(items, list) or not items:
        raise SpecError("创建新 REQ 时 requirements 必须是非空字符串数组")
    values = [str(item).strip().removeprefix("-").strip() for item in items]
    if any(not value for value in values):
        raise SpecError("requirements 里有空条目")
    return "；".join(values)


def create_or_reuse_requirements(
    req_text: str,
    requirement_refs: list[str],
    source_refs: list[str],
    spec: dict,
    req_path: Path,
) -> tuple[str, bool]:
    rows = table_rows_by_key(req_text, "req_id", req_path)
    existing = {
        f"{row.get('req_id')}@{row.get('version')}": row
        for row in rows if row.get("req_id") and row.get("version")
    }
    missing = [req_ref for req_ref in requirement_refs if req_ref not in existing]
    if len(missing) > 1:
        raise SpecError("一次转换最多创建一个新 REQ；其余 requirement_refs 必须已登记")
    if not missing:
        if not spec.get("requirements"):
            return req_text, False
        statement = requirement_statement(spec["requirements"])
        if len(requirement_refs) == 1:
            recorded = existing[requirement_refs[0]].get("requirement_cn", "")
            if recorded and recorded != statement:
                raise SpecError(
                    f"{requirement_refs[0]} 已存在且内容不同；需求变化应创建新版本，不能原地改写"
                )
        return req_text, False

    req_ref = missing[0]
    match = REQ_REF_RE.fullmatch(req_ref)
    assert match is not None
    req_id = match.group(1)
    version_number = int(match.group(2))
    explicit_supersedes = str(spec.get("supersedes", "none")).strip()
    if version_number == 1:
        if explicit_supersedes.lower() not in {"", "none", "tbd", "n/a", "-"}:
            raise SpecError(f"{req_ref} 是 v1，supersedes 必须为 none")
        supersedes = "none"
    else:
        prior_ref = f"{req_id}@v{version_number - 1}"
        if prior_ref not in existing:
            raise SpecError(
                f"{req_ref} 必须紧接已登记的 {prior_ref}；需求版本不能跳号"
            )
        if explicit_supersedes.lower() not in {"", "none", "tbd", "n/a", "-"} \
                and explicit_supersedes != prior_ref:
            raise SpecError(f"{req_ref} 的 supersedes 必须是 {prior_ref}")
        supersedes = prior_ref
    statement = requirement_statement(spec.get("requirements"))
    requirement_en = str(spec.get("requirement_en") or "").strip()
    if not requirement_en:
        raise SpecError("创建新 REQ 时 requirement_en 不能为空")
    req_text = insert_named_table_row(req_text, "req_id", {
        **spec,
        "req_id": req_id,
        "version": f"v{match.group(2)}",
        "title_cn": spec["title_cn"],
        "title_en": spec["title_en"],
        "requirement_cn": statement,
        "requirement_en": requirement_en,
        "priority": spec.get("priority", "none"),
        "owner": spec["owner"],
        "status": "draft",
        "baseline_ref": "none",
        "change_ref": spec.get("change_ref", "none"),
        "acceptance_refs": spec.get("acceptance_refs", "none"),
        "source_refs": ", ".join(source_refs),
        "approved_at": "none",
        "supersedes": supersedes,
    }, req_path, default="none")
    return req_text, True


def delivery_counted(value: object) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    normalized = str(value).strip().lower()
    if normalized in {"yes", "true", "1"}:
        return "yes"
    if normalized in {"no", "false", "0"}:
        return "no"
    raise SpecError("delivery_counted 必须是 yes/no")


def add_v2_risks(
    pack: Path,
    risk_text: str,
    risks: object,
    wp_id: str,
    default_owner: str,
    risk_path: Path,
) -> tuple[str, list[str]]:
    if not isinstance(risks, list) or not risks:
        return risk_text, []
    headers, _, _, _ = find_table(risk_text, "risk_id", risk_path)
    missing = sorted(RISK_REGISTER_COLUMNS - set(headers))
    if missing:
        raise SpecError("wbs_schema=2 的 07-risks.md 缺少列: " + ", ".join(missing))

    existing = {
        row.get("risk_id", "")
        for row in table_rows_by_key(risk_text, "risk_id", risk_path)
    }
    risk_ids: list[str] = []
    for index, risk in enumerate(risks, start=1):
        if not isinstance(risk, dict):
            raise SpecError("v2 risks 条目必须是对象")
        risk_id = str(
            risk.get("risk_id") or risk.get("id")
            or f"RISK-{wp_id[len('WP-'):]}-{index:03d}"
        ).strip()
        if not RISK_ID_RE.fullmatch(risk_id):
            raise SpecError(f"risk_id 格式不合法: {risk_id}")
        if risk_id in existing or risk_id in risk_ids:
            raise SpecError(f"{risk_id} 在 07-risks.md 里已存在")

        risk_cn = str(risk.get("risk_cn") or risk.get("title") or "").strip()
        risk_en = str(risk.get("risk_en") or risk.get("title_en") or "").strip()
        probability = str(risk.get("probability") or "").strip().lower()
        impact = str(risk.get("impact") or "").strip().lower()
        trigger = str(risk.get("trigger") or "").strip()
        response = str(risk.get("response") or risk.get("body") or "").strip()
        missing_fields = [
            name for name, value in (
                ("risk_cn/title", risk_cn), ("risk_en/title_en", risk_en),
                ("probability", probability), ("impact", impact),
                ("trigger", trigger), ("response/body", response),
            ) if not value
        ]
        if missing_fields:
            raise SpecError(
                f"{risk_id} 缺少可管理的风险字段: " + ", ".join(missing_fields)
            )
        if probability not in {"low", "medium", "high"}:
            raise SpecError(f"{risk_id} probability 必须是 low/medium/high")
        if impact not in {"low", "medium", "high"}:
            raise SpecError(f"{risk_id} impact 必须是 low/medium/high")
        owner = require_configured_owner(
            pack, risk.get("owner") or default_owner, f"{risk_id}.owner"
        )
        status = str(risk.get("status") or "open").strip().lower()
        if status != "open":
            raise SpecError("Author 只能登记 status=open 的未审批风险")

        risk_text = insert_named_table_row(risk_text, "risk_id", {
            "risk_id": risk_id,
            "risk_cn": risk_cn,
            "risk_en": risk_en,
            "probability": probability,
            "impact": impact,
            "owner": owner,
            "trigger": trigger,
            "response": response,
            "due_date": risk.get("due_date", "TBD"),
            "related_wp": wp_id,
            "residual_risk": risk.get("residual_risk", "TBD"),
            "status": "open",
            "accepted_by": "none",
        }, risk_path, default="none")
        risk_ids.append(risk_id)
    return risk_text, risk_ids


def proposed_artifact_rows(
    spec: dict,
    wp_id: str,
    requirement_refs: list[str],
    ac_id: str,
    acceptance_owner: str,
    risk_ids: list[str],
) -> list[dict[str, str]]:
    raw = spec.get("artifact_applicability")
    if not isinstance(raw, dict):
        raise SpecError("artifact_applicability 必须明确包含 page/api/data 决策")
    decisions: dict[str, tuple[str, str]] = {}
    for artifact in ARTIFACT_DECISIONS:
        decision = raw.get(artifact)
        if isinstance(decision, str):
            applicability = decision.strip().lower()
            reason = "explicit authoring decision"
        elif isinstance(decision, dict):
            applicability = str(decision.get("applicability") or "").strip().lower()
            reason = str(decision.get("reason") or "").strip()
        else:
            raise SpecError(f"artifact_applicability.{artifact} 缺失")
        if applicability not in {"required", "not_applicable"}:
            raise SpecError(
                f"artifact_applicability.{artifact}.applicability 必须是 required/not_applicable"
            )
        if not reason:
            raise SpecError(f"artifact_applicability.{artifact}.reason 不能为空")
        decisions[artifact] = applicability, reason

    owner = str(spec["owner"])
    change_ref = str(spec.get("change_ref", "none"))
    rows = [{
        "wp_id": wp_id,
        "artifact": "requirement",
        "applicability": "required",
        "readiness": "draft",
        "owner": owner,
        "refs": ", ".join(requirement_refs),
        "reason": "Requirement version drafted from registered source evidence",
        "change_ref": change_ref,
    }]
    for artifact in ARTIFACT_DECISIONS:
        applicability, reason = decisions[artifact]
        rows.append({
            "wp_id": wp_id,
            "artifact": artifact,
            "applicability": applicability,
            "readiness": "not_started" if applicability == "required" else "not_applicable",
            "owner": owner,
            "refs": "none",
            "reason": reason,
            "change_ref": change_ref,
        })
    rows.extend([
        {
            "wp_id": wp_id,
            "artifact": "acceptance",
            "applicability": "required",
            "readiness": "draft",
            "owner": acceptance_owner,
            "refs": ac_id,
            "reason": "Observable acceptance drafted; owner decision pending",
            "change_ref": change_ref,
        },
        {
            "wp_id": wp_id,
            "artifact": "risk",
            "applicability": "required",
            "readiness": "draft" if risk_ids else "ready",
            "owner": owner,
            "refs": ", ".join(risk_ids) or "none",
            "reason": (
                "Risk details require review in 07-risks.md"
                if risk_ids else "Risk assessment completed; no identified risk"
            ),
            "change_ref": change_ref,
        },
        {
            "wp_id": wp_id,
            "artifact": "handoff",
            "applicability": "required",
            "readiness": "not_started",
            "owner": owner,
            "refs": "none",
            "reason": "RUN and handoff start only after baseline approval",
            "change_ref": change_ref,
        },
    ])
    return rows


def reject_approval_mutation(spec: dict) -> None:
    for key in ("approve_baseline", "baseline_approved", "approve_cr", "cr_approved"):
        if spec.get(key):
            raise SpecError("本脚本只生成 proposed WP，不能批准 BL 或 CR")
    for key in ("baseline_status", "cr_status"):
        if str(spec.get(key, "")).strip().lower() in {
            "approved", "implemented", "closed",
        }:
            raise SpecError("本脚本只生成 proposed WP，不能批准 BL 或 CR")


def build(pack: Path, spec: dict) -> tuple[dict[Path, str], str]:
    wbs_path = pack / "02-wbs.md"
    req_path = pack / "01-requirements.md"
    acc_path = pack / "06-acceptance.md"
    for path in (wbs_path, req_path, acc_path):
        if not path.exists():
            raise SpecError(f"缺少 {path.name}，这不像一个 WBS Pack")

    schema = project_schema(pack)
    missing = [field for field in COMMON_REQUIRED if not spec.get(field)]
    if schema == 1 and not spec.get("requirements"):
        missing.append("requirements")
    if schema == 2:
        reject_approval_mutation(spec)
        for field in (
            "source_refs", "delivery_target", "delivery_counted", "changelog",
            "acceptance_en", "artifact_applicability",
        ):
            if spec.get(field) in (None, "", []):
                missing.append(field)
    if missing:
        raise SpecError("spec 缺字段: " + ", ".join(missing))

    acceptance_owner = str(spec.get("acceptance_owner") or spec.get("owner") or "").strip()
    if schema == 2:
        require_configured_owner(pack, spec.get("owner"), "owner")
        require_configured_owner(pack, acceptance_owner, "acceptance_owner")

    wbs_text = wbs_path.read_text(encoding="utf-8")
    series = str(spec.get("series", "BE")).upper()
    base_ref = str(spec.get("base_ref", "origin/develop"))
    base_text = base_ref_wbs(pack, base_ref)
    if spec.get("scan_remote_branches", True):
        base_text += "\n" + remote_branch_wbs(pack)
    if base_text:
        prefix = f"WP-{series}-"
        local_max = max(_used_numbers(wbs_text, prefix), default=0)
        base_max = max(_used_numbers(base_text, prefix), default=0)
        if base_max > local_max:
            print(f"提示: {base_ref} 上的 {prefix.rstrip('-')} 已到 {base_max:03d},当前工作树只到 "
                  f"{local_max:03d}(落后)。编号按两边的并集取。", file=sys.stderr)
    else:
        print(f"警告: 读不到 {base_ref} 的 02-wbs.md,编号只能按本地取——"
              f"当前分支若落后集成分支,这个号很可能已被占用。", file=sys.stderr)
    wp_id = str(spec.get("wp_id") or next_wp_id(wbs_text, series, base_text)).strip()
    if not WP_ID_RE.fullmatch(wp_id):
        raise SpecError(f"wp_id 格式不合法: {wp_id}(应形如 WP-BE-079)")
    if wp_id in work_package_ids(wbs_text):
        raise SpecError(f"{wp_id} 在 02-wbs.md 里已存在。编号只增不复用，换一个。")
    if base_text and wp_id in work_package_ids(base_text):
        raise SpecError(f"{wp_id} 已存在于 {base_ref}(当前分支还没取回)。"
                        f"合并时必然冲突,换一个号。")

    ac_id = "AC-" + wp_id[len("WP-"):]
    acc_text = acc_path.read_text(encoding="utf-8")
    if re.search(rf"^## {re.escape(ac_id)}\b", acc_text, re.M):
        raise SpecError(f"{ac_id} 在 06-acceptance.md 里已存在")

    status = str(spec.get("status", "proposed" if schema == 2 else "todo")).strip()
    if status not in ALLOWED_STATUS:
        raise SpecError(f"status 不合法: {status}(可选 {sorted(ALLOWED_STATUS)})")
    if schema == 2 and status != "proposed":
        raise SpecError(
            "wbs_schema=2 的需求转换只能创建 proposed WP；"
            "owner 批准基线后再由批准流程改为 todo"
        )

    depends = spec.get("depends_on") or "none"
    if isinstance(depends, list):
        depends = ", ".join(str(d).strip() for d in depends) or "none"
    known_wp_ids = work_package_ids(wbs_text)
    for dep in WP_ID_RE.findall(str(depends)):
        if dep not in known_wp_ids:
            raise SpecError(f"depends_on 里的 {dep} 不在 02-wbs.md 中，依赖会悬空")

    day = str(spec.get("date") or datetime.date.today().isoformat())
    values = {
        **spec,
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

    title = table_cell(str(spec["title_cn"]), "title_cn")
    v2_risk_path: Path | None = None
    v2_risk_text: str | None = None
    risk_ids: list[str] = []
    if schema == 1:
        row = "| " + " | ".join(table_cell(str(values[column]), column) for column in COLUMNS) + " |"
        new_wbs_text = insert_wbs_row(wbs_text, row, wbs_path)
        new_req_text = insert_after_document_title(
            req_path.read_text(encoding="utf-8"),
            f"## {wp_id} {title}\n\n" + bullets(spec["requirements"], "requirements"), req_path)
    else:
        req_text = ensure_v2_registers(req_path.read_text(encoding="utf-8"), req_path)
        req_text, source_ids = normalize_source_refs(
            req_text, spec["source_refs"], req_path, day,
        )
        requirement_refs = normalize_requirement_refs(spec.get("requirement_refs"), wp_id)
        req_text, requirement_created = create_or_reuse_requirements(
            req_text, requirement_refs, source_ids,
            {**spec, "acceptance_refs": ac_id}, req_path,
        )
        if requirement_created:
            req_text = insert_wp_requirement_section(
                req_text,
                f"## {requirement_refs[0]}: {title}\n\n"
                "中文：\n\n" + bullets(spec["requirements"], "requirements")
                + "\n\nEnglish:\n\n"
                + bullets(spec["requirement_en"], "requirement_en"),
            )
        target = str(spec["delivery_target"]).strip()
        if target not in DELIVERY_TARGETS:
            raise SpecError("delivery_target 必须是 none/review/production")
        counted = delivery_counted(spec["delivery_counted"])
        if counted == "yes" and target != "production":
            raise SpecError(
                "delivery_counted=yes 只用于生产交付率，delivery_target 必须是 production"
            )
        values.update({
            "requirement_refs": ", ".join(requirement_refs),
            "delivery_target": target,
            "delivery_counted": counted,
            "baseline_ref": "none",
            "planned_start": spec.get("planned_start", "TBD"),
            "planned_finish": spec.get("planned_finish", "TBD"),
            "forecast_finish": spec.get("forecast_finish", "TBD"),
            "actual_start": "none",
            "actual_finish": "none",
            "change_ref": spec.get("change_ref", "none"),
            "run_ref": "none",
            "release_ref": "none",
        })
        if spec.get("risks"):
            v2_risk_path = pack / "07-risks.md"
            if not v2_risk_path.exists():
                raise SpecError("spec 里有 risks，但 pack 里没有 07-risks.md")
            v2_risk_text, risk_ids = add_v2_risks(
                pack,
                v2_risk_path.read_text(encoding="utf-8"),
                spec["risks"],
                wp_id,
                str(spec["owner"]),
                v2_risk_path,
            )
        new_wbs_text = insert_v2_wbs_row(wbs_text, values, wbs_path)
        artifact_rows = proposed_artifact_rows(
            spec, wp_id, requirement_refs, ac_id, acceptance_owner, risk_ids,
        )
        # insert_named_table_row always inserts directly after the separator;
        # reverse iteration preserves the canonical artifact order in the file.
        for artifact_row in reversed(artifact_rows):
            new_wbs_text = insert_named_table_row(
                new_wbs_text, "artifact", artifact_row, wbs_path, default="none",
            )
        requirement_lines = (
            bullets(spec["requirements"], "requirements")
            if spec.get("requirements")
            else "- 业务约束复用上述 requirement_refs；本工作包不改写需求版本。"
        )
        new_req_text = insert_wp_requirement_section(
            req_text,
            f"## {wp_id} {title}\n\n"
            f"- requirement_refs: `{', '.join(requirement_refs)}`\n"
            f"- source_refs: `{', '.join(source_ids)}`\n"
            f"- delivery_target: `{target}`\n"
            f"- delivery_counted: `{counted}`\n\n"
            f"### 需求约束 / Requirement Constraints\n\n{requirement_lines}",
        )

    writes: dict[Path, str] = {
        wbs_path: new_wbs_text,
        req_path: new_req_text,
        acc_path: (
            insert_after_document_title(
                acc_text,
                f"## {ac_id} {title}\n\n"
                + "Requirement refs:\n\n"
                + bullets([f"`{ref}`" for ref in requirement_refs], "requirement_refs")
                + "\n\nBaseline:\n\n- `none` (proposed; owner approval required)"
                + f"\n\nAcceptance owner:\n\n- `{acceptance_owner}`"
                + f"\n\nDelivery target:\n\n- `{target}`"
                + "\n\n中文：\n\n"
                + bullets(spec["acceptance"], "acceptance")
                + "\n\nEnglish:\n\n"
                + bullets(spec["acceptance_en"], "acceptance_en")
                + "\n\nVerification:\n\n"
                + bullets(
                    spec.get("verification", ["逐条验证上述可观察验收标准并保留证据。"]),
                    "verification",
                )
                + "\n\nRequired evidence:\n\n"
                + bullets(
                    spec.get("required_evidence", [
                        "Verification output.",
                        "For production delivery, a verified production REL.",
                    ]),
                    "required_evidence",
                )
                + "\n\nDecision:\n\n- `pending`",
                acc_path,
            )
            if schema == 2
            else insert_after_document_title(
                acc_text,
                f"## {ac_id} {title}\n\n" + bullets(spec["acceptance"], "acceptance"), acc_path)
        ),
    }

    if v2_risk_path is not None and v2_risk_text is not None:
        writes[v2_risk_path] = v2_risk_text

    if schema == 1 and spec.get("risks"):
        risk_path = pack / "07-risks.md"
        if not risk_path.exists():
            raise SpecError("spec 里有 risks，但 pack 里没有 07-risks.md")
        blocks = []
        for index, risk in enumerate(spec["risks"], start=1):
            rid = risk.get("id") or f"RISK-{wp_id[len('WP-'):]}-{index:03d}"
            blocks.append(f"## {rid} {risk['title']}\n\n{risk['body'].strip()}")
        writes[risk_path] = insert_after_document_title(
            risk_path.read_text(encoding="utf-8"),
            "\n\n".join(blocks), risk_path)

    if spec.get("changelog"):
        log_path = pack / "CHANGELOG.md"
        if not log_path.exists():
            raise SpecError("spec 里有 changelog，但 pack 里没有 CHANGELOG.md")
        text = log_path.read_text(encoding="utf-8")
        if schema == 2:
            entry = "\n".join([
                f"- Requirement: `{', '.join(requirement_refs)}`.",
                f"- Work package: `{wp_id}` (`proposed`).",
                f"- Baseline / CR: `none` / `{spec.get('change_ref', 'none')}`.",
                f"- Change: {spec['changelog'].strip()}",
                "- Verification: canonical validator passed; author transaction commits only after this check.",
                f"- Delivery evidence: `pending` (`delivery_target={target}`).",
                "- Remaining risk: " + str(spec.get(
                    "remaining_risk",
                    "owner baseline approval and target-stage verification pending.",
                )).strip(),
            ])
        else:
            entry = f"- `{wp_id}` {spec['changelog'].strip()}"
        if f"## {day}" in text:
            text = text.replace(f"## {day}\n", f"## {day}\n\n{entry}\n", 1)
            text = re.sub(r"\n\n\n+", "\n\n", text)
        else:
            # 两个 schema 的插法本来就一样，此前只是 V1 那支多校验了一次标题文本。
            text = insert_after_document_title(text, f"## {day}\n\n{entry}", log_path)
        writes[log_path] = text

    return writes, wp_id


def run_validator(pack: Path, evidence_root: Path | None = None) -> subprocess.CompletedProcess:
    """跑 canonical validator。

    候选校验时 pack 被复制到临时目录，那里没有源码，证据门禁会把每一条验收都
    报成「文件不存在」。所以要把真实仓库根显式传给它——校验的是 pack 的结构，
    证据存不存在得按真实仓库算。
    """
    env = dict(os.environ)
    if evidence_root is not None:
        env["XSOS_WBS_EVIDENCE_ROOT"] = str(evidence_root)
    return subprocess.run(
        [sys.executable, str(VALIDATOR), str(pack)], capture_output=True, text=True, env=env)


def validate_candidate(pack: Path, writes: dict[Path, str]) -> subprocess.CompletedProcess:
    temp_root = Path(tempfile.mkdtemp(prefix="wbs-author-candidate-"))
    candidate = temp_root / pack.name
    try:
        shutil.copytree(pack, candidate)
        for path, content in writes.items():
            relative = path.relative_to(pack)
            target = candidate / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        return run_validator(candidate, evidence_root=pack.parent.parent)
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


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
        result = validate_candidate(pack, writes)
        if result.returncode != 0:
            print("[dry-run] 候选 WBS 未通过 canonical validator:", file=sys.stderr)
            print(result.stdout + result.stderr, file=sys.stderr)
            return 1
        print(f"[dry-run] {wp_id} 将写入 {len(writes)} 个文件:")
        for path, content in writes.items():
            print(f"  - {path.name}")
            diff = difflib.unified_diff(
                path.read_text(encoding="utf-8").splitlines(),
                content.splitlines(),
                fromfile=str(path),
                tofile=f"{path} (candidate)",
                lineterm="",
            )
            for line in diff:
                print(line)
        print(result.stdout.strip())
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
