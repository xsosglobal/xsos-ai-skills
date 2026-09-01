#!/usr/bin/env python3
"""Validate an XSOS WBS Pack structure.

A pack directory is either:
  - the repository-level root pack (``docs/wbs``), which also carries the
    unified CHANGELOG and OWNERS, or
  - a business-line initiative pack under ``<root>/initiatives/<domain>/``,
    which owns its own brief/requirements/WBS/acceptance facts and inherits
    CHANGELOG and OWNERS from the root.

Work-package IDs come in two shapes:
  - legacy   ``WP-{TYPE}-{NNN}``          e.g. WP-BE-068
  - current  ``WP-{DOMAIN}-{TYPE}-{NNN}`` e.g. WP-PUR-BE-001

wp_id uniqueness, dependency resolution and cycle detection run across every
pack, so an initiative may depend on a work package owned by another pack.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path


FACT_FILES = [
    "00-brief.md",
    "01-requirements.md",
    "02-wbs.md",
    "03-page-spec.md",
    "04-api-contract.md",
    "05-data-contract.md",
    "06-acceptance.md",
    "07-risks.md",
    "08-implementation-rules.md",
]

# The root pack additionally owns the repository-level control plane.
REQUIRED_FILES = FACT_FILES + ["CHANGELOG.md", "OWNERS.md"]

# Initiative packs inherit CHANGELOG.md and OWNERS.md from the root pack.
INITIATIVE_REQUIRED_FILES = FACT_FILES

INITIATIVES_DIRNAME = "initiatives"
REQUIREMENTS_BASELINE = "requirements-baseline.txt"
V2_CONTROL_FILES = ["09-baselines.md", "10-handoff.md", "11-change-requests.md"]

ALLOWED_STATUS = {"proposed", "todo", "in_progress", "blocked", "review", "done", "cancelled"}
ACTIVE_BASELINE_STATUS = {"todo", "in_progress", "blocked", "review"}
V2_WBS_HEADERS = [
    "requirement_refs",
    "scope",
    "non_goals",
    "outputs",
    "delivery_target",
    "delivery_counted",
    "baseline_ref",
    "planned_start",
    "planned_finish",
    "forecast_finish",
    "actual_start",
    "actual_finish",
    "change_ref",
    "run_ref",
    "release_ref",
]
DELIVERY_TARGETS = {"none", "review", "production"}
BOOLEAN_VALUES = {"yes", "no"}
BASELINE_STATUS = {"draft", "approved", "superseded"}
RUN_STATUS = {"active", "closed"}
RUN_OUTCOME = {"completed", "blocked", "change_required"}
RELEASE_STATUS = {"planned", "deployed", "verified", "failed"}
CHANGE_STATUS = {"proposed", "approved", "rejected", "implemented"}
REQUIREMENT_STATUS = {"draft", "proposed", "approved", "baselined", "superseded", "cancelled"}
PROJECT_STATUS = {"draft", "planning", "active", "on_hold", "closing", "closed", "cancelled"}
PROJECT_STATUS_REQUIRING_BASELINE = {"active", "on_hold", "closing", "closed"}
ARTIFACT_TYPES = {"requirement", "page", "api", "data", "acceptance", "risk", "handoff"}
ARTIFACT_APPLICABILITY = {"required", "not_applicable"}
ARTIFACT_READINESS = {
    "not_applicable", "not_started", "draft", "ready", "verified",
    "change_pending", "superseded",
}
ARTIFACT_CONTRACT_STATUS = {"draft", "approved", "verified", "change_pending", "superseded"}
RISK_STATUS = {"open", "mitigating", "accepted", "closed"}
RISK_LEVEL = {"low", "medium", "high"}
BASELINE_VERSION_RE = re.compile(r"^v[1-9]\d*$")

WP_ID = r"WP-[A-Z0-9]+(?:-[A-Z0-9]+)?-\d{3}"
AC_ID = r"AC-[A-Z0-9]+(?:-[A-Z0-9]+)?-\d{3}"
CONTROL_ID_SUFFIX = r"(?:[A-Z0-9]+-)*\d{3}"
REQ_ID = rf"REQ-{CONTROL_ID_SUFFIX}"
REQ_REF = rf"{REQ_ID}@v[1-9]\d*"
SRC_ID = rf"SRC-{CONTROL_ID_SUFFIX}"
RISK_ID = rf"RISK-{CONTROL_ID_SUFFIX}"
BL_ID = rf"BL-{CONTROL_ID_SUFFIX}"
CR_ID = rf"CR-{CONTROL_ID_SUFFIX}"
RUN_ID = rf"RUN-{CONTROL_ID_SUFFIX}"
REL_ID = rf"REL-{CONTROL_ID_SUFFIX}"
WP_ID_RE = re.compile(WP_ID)
WP_ID_FULL_RE = re.compile(rf"^{WP_ID}$")
AC_ID_FULL_RE = re.compile(rf"^{AC_ID}$")
REQ_REF_FULL_RE = re.compile(rf"^{REQ_REF}$")
REQ_ID_FULL_RE = re.compile(rf"^{REQ_ID}$")
SRC_ID_FULL_RE = re.compile(rf"^{SRC_ID}$")
RISK_ID_FULL_RE = re.compile(rf"^{RISK_ID}$")
BL_ID_FULL_RE = re.compile(rf"^{BL_ID}$")
CR_ID_FULL_RE = re.compile(rf"^{CR_ID}$")
RUN_ID_FULL_RE = re.compile(rf"^{RUN_ID}$")
REL_ID_FULL_RE = re.compile(rf"^{REL_ID}$")
EVIDENCE_URI_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9+.-]*://\S+")
EVIDENCE_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"/[^\s,;]+|\.\.?/[^\s,;]+|[A-Za-z]:[\\/][^\s,;]+|"
    r"(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+\.[A-Za-z][A-Za-z0-9]{0,15}|"
    r"[A-Za-z0-9_.-]+\.[A-Za-z][A-Za-z0-9]{0,15}"
    r")(?![A-Za-z0-9])"
)
EVIDENCE_ID_RE = re.compile(
    r"\b(?:EVIDENCE|EVD|BUILD|DEPLOY|RELEASE|CI|JOB|ARTIFACT)[-_:#]"
    r"[A-Z0-9][A-Z0-9._:-]*\b",
    re.IGNORECASE,
)
EVIDENCE_COMMAND_RE = re.compile(r"\b(?:command|cmd):\s*\S.{1,}", re.IGNORECASE)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text()


def inherited_pack_file(pack_dir: Path, name: str) -> Path:
    """Initiatives inherit repository-level OWNERS/CHANGELOG from the root pack."""
    local = pack_dir / name
    if local.exists() or pack_dir.parent.name != INITIATIVES_DIRNAME:
        return local
    return pack_dir.parent.parent / name


def check_required_files(pack_dir: Path, required: list[str]) -> list[str]:
    errors: list[str] = []
    for name in required:
        path = pack_dir / name
        if not path.exists():
            errors.append(f"missing required file: {name}")
        elif path.is_file() and path.stat().st_size == 0:
            errors.append(f"empty required file: {name}")
    return errors


def check_brief(pack_dir: Path) -> list[str]:
    path = pack_dir / "00-brief.md"
    if not path.exists():
        return []
    text = read_text(path).lower()
    errors: list[str] = []
    if "goal" not in text and "项目目标" not in text:
        errors.append("00-brief.md missing Goal / 项目目标 section")
    if "non-goals" not in text and "非目标" not in text:
        errors.append("00-brief.md missing Non-goals / 非目标 section")
    return errors


def split_markdown_row(line: str) -> list[str]:
    stripped = line.strip().strip("|")
    return [cell.strip() for cell in stripped.split("|")]


def parse_markdown_tables(text: str) -> list[tuple[list[str], list[tuple[int, dict[str, str]]]]]:
    """Parse every contiguous Markdown table and preserve data-row line numbers."""
    raw_tables: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if line.strip().startswith("|"):
            current.append((line_number, line))
        elif current:
            raw_tables.append(current)
            current = []
    if current:
        raw_tables.append(current)

    tables: list[tuple[list[str], list[tuple[int, dict[str, str]]]]] = []
    for table in raw_tables:
        if len(table) < 2:
            continue
        headers = [header.lower() for header in split_markdown_row(table[0][1])]
        rows: list[tuple[int, dict[str, str]]] = []
        for line_number, line in table[2:]:
            cells = split_markdown_row(line)
            rows.append((line_number, {
                header: cells[index] if index < len(cells) else ""
                for index, header in enumerate(headers)
            }))
        tables.append((headers, rows))
    return tables


def find_named_table(path: Path, id_header: str) -> tuple[list[str], list[tuple[int, dict[str, str]]], list[str]]:
    """Find one table by its identifier column; duplicate tables are ambiguous."""
    if not path.exists():
        return [], [], []
    matches = [
        (headers, rows)
        for headers, rows in parse_markdown_tables(read_text(path))
        if id_header in headers
    ]
    if not matches:
        return [], [], [f"{path.name} missing {id_header} table"]
    if len(matches) > 1:
        return matches[0][0], matches[0][1], [
            f"{path.name} has multiple {id_header} tables; keep one unbroken table"
        ]
    return matches[0][0], matches[0][1], []


def clean_cell(value: str) -> str:
    return value.strip().strip("`").strip()


def is_none(value: str) -> bool:
    return clean_cell(value).lower() in {"", "none", "tbd", "n/a", "-"}


def split_refs(value: str) -> list[str]:
    if is_none(value):
        return []
    return [
        clean_cell(token)
        for token in re.split(r"\s*(?:,|;|<br\s*/?>)\s*", value, flags=re.IGNORECASE)
        if clean_cell(token)
    ]


def check_headers(filename: str, headers: list[str], required: list[str]) -> list[str]:
    return [f"{filename} missing required column: {header}" for header in required if header not in headers]


def check_iso_date(value: str, label: str, *, required: bool = False) -> list[str]:
    value = clean_cell(value)
    if is_none(value):
        return [f"{label} is required and must use YYYY-MM-DD"] if required else []
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return [f"{label} has invalid ISO date: {value} (expected YYYY-MM-DD)"]
    if parsed.isoformat() != value:
        return [f"{label} has invalid ISO date: {value} (expected YYYY-MM-DD)"]
    return []


def parse_iso_temporal(value: str) -> date | datetime | None:
    value = clean_cell(value)
    if is_none(value):
        return None
    try:
        if "T" in value:
            return datetime.fromisoformat(value)
        parsed = date.fromisoformat(value)
        return parsed if parsed.isoformat() == value else None
    except ValueError:
        return None


def check_iso_temporal(value: str, label: str, *, required: bool = False) -> list[str]:
    value = clean_cell(value)
    if is_none(value):
        return [f"{label} is required and must use ISO 8601"] if required else []
    if parse_iso_temporal(value) is None:
        return [
            f"{label} has invalid ISO date/datetime: {value} "
            f"(expected YYYY-MM-DD or ISO 8601 datetime)"
        ]
    return []


def same_temporal_value(left: str, right: str) -> bool:
    """Treat a date and a datetime on that same local calendar date as consistent."""
    left_value = parse_iso_temporal(left)
    right_value = parse_iso_temporal(right)
    if left_value is None or right_value is None:
        return False
    if isinstance(left_value, datetime) and isinstance(right_value, datetime):
        return left_value == right_value
    left_date = left_value.date() if isinstance(left_value, datetime) else left_value
    right_date = right_value.date() if isinstance(right_value, datetime) else right_value
    return left_date == right_date


def temporal_is_after(left: str, right: str) -> bool:
    left_value = parse_iso_temporal(left)
    right_value = parse_iso_temporal(right)
    if left_value is None or right_value is None:
        return False
    if isinstance(left_value, datetime) and isinstance(right_value, datetime):
        try:
            return left_value > right_value
        except TypeError:
            return False
    left_date = left_value.date() if isinstance(left_value, datetime) else left_value
    right_date = right_value.date() if isinstance(right_value, datetime) else right_value
    return left_date > right_date


def has_stable_evidence_locator(value: str) -> bool:
    """Require a reproducible locator, not merely a long prose assertion."""
    evidence = clean_cell(value)
    if is_none(evidence) or len(evidence) < 8:
        return False
    if (
        EVIDENCE_URI_RE.search(evidence)
        or EVIDENCE_PATH_RE.search(evidence)
        or EVIDENCE_ID_RE.search(evidence)
        or EVIDENCE_COMMAND_RE.search(evidence)
    ):
        return True
    for token in re.findall(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{7,40}(?![0-9A-Fa-f])", evidence):
        if re.search(r"[a-fA-F]", token):
            return True
    return False


def collect_control_headings(path: Path, pattern: str) -> set[str]:
    if not path.exists():
        return set()
    result: set[str] = set()
    for line in read_text(path).splitlines():
        match = re.match(rf"^##\s+`?({pattern})`?(?:\s|:|$)", line)
        if match:
            result.add(match.group(1))
    return result


def collect_risk_ids(path: Path) -> set[str]:
    """Read legacy risk headings and the v2 Risk Register."""
    result = collect_control_headings(path, RISK_ID)
    if not path.exists():
        return result
    for headers, rows in parse_markdown_tables(read_text(path)):
        if "risk_id" not in headers:
            continue
        for _, row in rows:
            risk_id = clean_cell(row.get("risk_id", ""))
            if RISK_ID_FULL_RE.fullmatch(risk_id):
                result.add(risk_id)
    return result


def collect_acceptance_sections(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    sections: dict[str, list[str]] = {}
    current = ""
    for line in read_text(path).splitlines():
        heading = re.match(rf"^##\s+`?({AC_ID})`?(?:\s|:|$)", line)
        if heading:
            current = heading.group(1)
            sections.setdefault(current, []).append(line)
            continue
        if current and re.match(r"^##\s+", line):
            current = ""
        elif current:
            sections[current].append(line)
    return {key: "\n".join(lines) for key, lines in sections.items()}


def project_control_text(path: Path) -> str:
    """Return the Markdown section headed by Project Control, if present."""
    if not path.exists():
        return ""
    lines = read_text(path).splitlines()
    selected: list[str] = []
    inside = False
    for line in lines:
        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading:
            title = heading.group(2).lower()
            if "project control" in title:
                inside = True
                selected.append(line)
                continue
            if inside:
                break
        elif inside:
            selected.append(line)
    return "\n".join(selected)


def project_control_values(pack_dir: Path) -> tuple[dict[str, str], list[str]]:
    """Read either a field/value table or one wide row under Project Control."""
    text = project_control_text(pack_dir / "00-brief.md")
    if not text:
        return {}, []
    values: dict[str, str] = {}
    errors: list[str] = []
    for headers, rows in parse_markdown_tables(text):
        if "wbs_schema" in headers:
            if len(rows) != 1:
                errors.append("00-brief.md Project Control wide table must contain exactly one data row")
                continue
            values.update({key: clean_cell(value) for key, value in rows[0][1].items()})
        elif "field" in headers and "value" in headers:
            for _, row in rows:
                key = clean_cell(row.get("field", "")).lower().replace("-", "_").replace(" ", "_")
                if not key:
                    continue
                if key in values:
                    errors.append(f"00-brief.md Project Control duplicate field: {key}")
                values[key] = clean_cell(row.get("value", ""))
    return values, errors


def detect_wbs_schema(pack_dir: Path) -> tuple[int, list[str]]:
    values, errors = project_control_values(pack_dir)
    raw = values.get("wbs_schema", "")
    if not raw:
        return 1, errors
    if raw not in {"1", "2"}:
        errors.append(f"00-brief.md Project Control has unsupported wbs_schema: {raw}")
        return 1, errors
    return int(raw), errors


def collect_requirement_versions(path: Path) -> tuple[dict[str, dict[str, object]], list[str]]:
    """Read the v2 Requirement Register, with legacy REQ-*@vN headings as fallback."""
    records: dict[str, dict[str, object]] = {}
    errors: list[str] = []
    if not path.exists():
        return records, errors

    tables = parse_markdown_tables(read_text(path))
    requirement_tables = [
        (headers, rows) for headers, rows in tables if "req_id" in headers and "version" in headers
    ]
    if len(requirement_tables) > 1:
        errors.append("01-requirements.md has multiple Requirement Register tables")
    if requirement_tables:
        headers, rows = requirement_tables[0]
        required_headers = [
            "req_id", "version", "requirement_cn", "requirement_en", "priority",
            "owner", "status", "baseline_ref", "change_ref", "acceptance_refs",
            "source_refs", "approved_at", "supersedes",
        ]
        errors.extend(check_headers("01-requirements.md Requirement Register", headers, required_headers))

        source_tables = [
            (source_headers, source_rows)
            for source_headers, source_rows in tables
            if "source_id" in source_headers
        ]
        sources: dict[str, int] = {}
        if not source_tables:
            errors.append("01-requirements.md missing Source Register table")
        else:
            if len(source_tables) > 1:
                errors.append("01-requirements.md has multiple Source Register tables")
            source_headers, source_rows = source_tables[0]
            source_required = ["source_id", "source_type", "source_ref", "captured_at", "note"]
            errors.extend(check_headers("01-requirements.md Source Register", source_headers, source_required))
            source_sites: dict[str, list[int]] = {}
            for line_number, row in source_rows:
                source_id = clean_cell(row.get("source_id", ""))
                if not SRC_ID_FULL_RE.fullmatch(source_id):
                    errors.append(
                        f"01-requirements.md Source Register has invalid source_id: "
                        f"{source_id or '<empty>'} (line {line_number})"
                    )
                    continue
                source_sites.setdefault(source_id, []).append(line_number)
                sources.setdefault(source_id, line_number)
                for field in source_required[1:]:
                    if not clean_cell(row.get(field, "")):
                        errors.append(
                            f"01-requirements.md {source_id} has empty {field} (line {line_number})"
                        )
                errors.extend(check_iso_date(
                    row.get("captured_at", ""),
                    f"01-requirements.md {source_id} captured_at",
                    required=True,
                ))
            for source_id, line_numbers in source_sites.items():
                if len(line_numbers) > 1:
                    errors.append(
                        f"01-requirements.md duplicate source_id: {source_id} "
                        f"(lines {', '.join(str(number) for number in line_numbers)})"
                    )

        requirement_sites: dict[str, list[int]] = {}
        for line_number, row in rows:
            req_id = clean_cell(row.get("req_id", ""))
            version = clean_cell(row.get("version", ""))
            if not REQ_ID_FULL_RE.fullmatch(req_id):
                errors.append(
                    f"01-requirements.md Requirement Register has invalid req_id: "
                    f"{req_id or '<empty>'} (line {line_number})"
                )
                continue
            if not BASELINE_VERSION_RE.fullmatch(version):
                errors.append(
                    f"01-requirements.md {req_id} has invalid version: "
                    f"{version or '<empty>'} (line {line_number})"
                )
                continue
            requirement_ref = f"{req_id}@{version}"
            requirement_sites.setdefault(requirement_ref, []).append(line_number)
            status = clean_cell(row.get("status", "")).lower()
            for field in required_headers[2:]:
                if not clean_cell(row.get(field, "")):
                    errors.append(
                        f"01-requirements.md {requirement_ref} has empty {field} "
                        f"(line {line_number})"
                    )
            if status not in REQUIREMENT_STATUS:
                errors.append(
                    f"01-requirements.md {requirement_ref} has invalid status: {status}"
                )
            errors.extend(check_iso_date(
                row.get("approved_at", ""),
                f"01-requirements.md {requirement_ref} approved_at",
                required=status in {"approved", "baselined", "superseded"},
            ))
            acceptance_refs = checked_refs(
                row.get("acceptance_refs", ""), AC_ID_FULL_RE,
                f"01-requirements.md {requirement_ref} acceptance_refs (line {line_number})",
                errors,
                required=status != "cancelled",
            )
            baseline_refs = checked_refs(
                row.get("baseline_ref", ""), BL_ID_FULL_RE,
                f"01-requirements.md {requirement_ref} baseline_ref (line {line_number})",
                errors,
                required=status == "baselined",
            )
            if len(baseline_refs) > 1:
                errors.append(
                    f"01-requirements.md {requirement_ref} baseline_ref must contain at most one BL reference"
                )
            change_refs = checked_refs(
                row.get("change_ref", ""), CR_ID_FULL_RE,
                f"01-requirements.md {requirement_ref} change_ref (line {line_number})",
                errors,
            )
            if len(change_refs) > 1:
                errors.append(
                    f"01-requirements.md {requirement_ref} change_ref must contain at most one CR reference"
                )
            supersedes_refs = checked_refs(
                row.get("supersedes", ""), REQ_REF_FULL_RE,
                f"01-requirements.md {requirement_ref} supersedes (line {line_number})",
                errors,
            )
            version_number = int(version[1:])
            expected_prior = f"{req_id}@v{version_number - 1}" if version_number > 1 else ""
            if version_number == 1 and supersedes_refs:
                errors.append(f"01-requirements.md {requirement_ref} v1 must not supersede another version")
            if version_number > 1 and supersedes_refs != [expected_prior]:
                errors.append(
                    f"01-requirements.md {requirement_ref} must supersede immediate prior version {expected_prior}"
                )
            source_refs = checked_refs(
                row.get("source_refs", ""), SRC_ID_FULL_RE,
                f"01-requirements.md {requirement_ref} source_refs (line {line_number})",
                errors,
                required=True,
            )
            for source_ref in source_refs:
                if source_ref not in sources:
                    errors.append(
                        f"01-requirements.md source reference not found: "
                        f"{requirement_ref} -> {source_ref}"
                    )
            records.setdefault(requirement_ref, {
                "line": line_number,
                "status": status,
                "source": "register",
                "owner": clean_cell(row.get("owner", "")),
                "acceptance_refs": acceptance_refs,
                "baseline_refs": baseline_refs,
                "change_refs": change_refs,
                "supersedes_refs": supersedes_refs,
            })
        for requirement_ref, line_numbers in requirement_sites.items():
            if len(line_numbers) > 1:
                errors.append(
                    f"01-requirements.md duplicate requirement version: {requirement_ref} "
                    f"(lines {', '.join(str(number) for number in line_numbers)})"
                )
        for requirement_ref, record in records.items():
            for supersedes_ref in record.get("supersedes_refs", []):
                if supersedes_ref not in records:
                    errors.append(
                        f"01-requirements.md {requirement_ref} supersedes reference not found: {supersedes_ref}"
                    )
        return records, errors

    # Compatibility for early v2 packs that used requirement-version headings.
    heading_sites: dict[str, list[int]] = {}
    for line_number, line in enumerate(read_text(path).splitlines(), start=1):
        match = re.match(rf"^##\s+`?({REQ_REF})`?(?:\s|:|$)", line)
        if match:
            requirement_ref = match.group(1)
            heading_sites.setdefault(requirement_ref, []).append(line_number)
            records.setdefault(requirement_ref, {
                "line": line_number,
                "status": "legacy",
                "source": "heading",
            })
    for requirement_ref, line_numbers in heading_sites.items():
        if len(line_numbers) > 1:
            errors.append(
                f"01-requirements.md duplicate requirement version: {requirement_ref} "
                f"(lines {', '.join(str(number) for number in line_numbers)})"
            )
    if not records:
        errors.append(
            "01-requirements.md v2 requires a Requirement Register or a heading like "
            "## REQ-001@v1"
        )
    return records, errors


def parse_wbs_rows(path: Path) -> tuple[list[str], list[tuple[int, dict[str, str]]]]:
    """Parse the work-package table by column name, not column position.

    A pack file may hold more than one Markdown table (an initiative index, a
    legend); the work-package table is the first one carrying a ``wp_id``
    column. Falls back to the first table so a pack that genuinely lacks the
    column still reports the missing-column error.
    """
    tables = parse_markdown_tables(read_text(path))
    candidates = list(tables)
    if not candidates:
        return [], []
    headers, rows = next(
        (table for table in candidates if "wp_id" in table[0]),
        candidates[0],
    )
    return headers, rows


def local_dependency_ids(value: str) -> list[str]:
    """Only bare dependency tokens are resolvable; qualified tokens are external refs."""
    result: list[str] = []
    for token in value.split(","):
        candidate = token.strip().strip("`")
        if WP_ID_FULL_RE.fullmatch(candidate):
            result.append(candidate)
    return result


def find_cycles(graph: dict[str, list[str]]) -> list[list[str]]:
    cycles: list[list[str]] = []
    state: dict[str, int] = {}
    stack: list[str] = []

    def visit(node: str) -> None:
        state[node] = 1
        stack.append(node)
        for dependency in graph.get(node, []):
            if state.get(dependency, 0) == 0:
                visit(dependency)
            elif state.get(dependency) == 1:
                start = stack.index(dependency)
                cycle = stack[start:] + [dependency]
                signature = tuple(sorted(cycle[:-1]))
                if not any(tuple(sorted(item[:-1])) == signature for item in cycles):
                    cycles.append(cycle)
        stack.pop()
        state[node] = 2

    for node in graph:
        if state.get(node, 0) == 0:
            visit(node)
    return cycles


def check_wbs(pack_dir: Path) -> list[str]:
    """Per-pack structural checks. Cross-pack checks run in check_across_packs."""
    path = pack_dir / "02-wbs.md"
    if not path.exists():
        return []
    text = read_text(path)
    errors: list[str] = []
    headers, rows = parse_wbs_rows(path)
    required_headers = ["wp_id", "title_cn", "title_en", "type", "owner", "status", "depends_on", "acceptance_ref"]
    for header in required_headers:
        if header not in headers:
            errors.append(f"02-wbs.md missing required column: {header}")

    if not rows:
        schema_version, _ = detect_wbs_schema(pack_dir)
        project_status = clean_cell(project_control_values(pack_dir)[0].get("project_status", "")).lower()
        if schema_version == 2 and project_status in {"draft", "planning"} and headers:
            return errors
        errors.append("02-wbs.md should contain a Markdown table with at least one work package")
        return errors

    if "status" in headers:
        for _, row in rows:
            status = row.get("status", "")
            if status and status not in ALLOWED_STATUS:
                errors.append(f"02-wbs.md has invalid status: {status}")

    if not WP_ID_RE.search(text):
        errors.append("02-wbs.md should contain at least one wp_id like WP-FE-001 or WP-PUR-BE-001")
    return errors


def check_acceptance(pack_dir: Path) -> list[str]:
    path = pack_dir / "06-acceptance.md"
    if not path.exists():
        return []
    text = read_text(path)
    errors: list[str] = []
    seen: dict[str, list[int]] = {}
    for line_number, line in enumerate(text.splitlines(), start=1):
        match = re.match(r"^##\s+(AC-[A-Z0-9-]+)\b", line)
        if match:
            seen.setdefault(match.group(1), []).append(line_number)
    for acceptance_id, line_numbers in seen.items():
        if len(line_numbers) > 1:
            errors.append(
                f"06-acceptance.md duplicate acceptance id: {acceptance_id} "
                f"(lines {', '.join(str(number) for number in line_numbers)})"
            )

    wbs_path = pack_dir / "02-wbs.md"
    if wbs_path.exists():
        _, rows = parse_wbs_rows(wbs_path)
        for line_number, row in rows:
            wp_id = row.get("wp_id", "")
            acceptance_ref = row.get("acceptance_ref", "").strip().strip("`")
            if acceptance_ref and acceptance_ref not in seen:
                errors.append(
                    f"02-wbs.md acceptance reference not found: {wp_id} -> {acceptance_ref} "
                    f"(line {line_number})"
                )
    if not re.search(AC_ID, text):
        wbs_rows = parse_wbs_rows(wbs_path)[1] if wbs_path.exists() else []
        schema_version, _ = detect_wbs_schema(pack_dir)
        project_status = clean_cell(project_control_values(pack_dir)[0].get("project_status", "")).lower()
        if wbs_rows or schema_version != 2 or project_status not in {"draft", "planning"}:
            errors.append("06-acceptance.md should contain at least one acceptance id like AC-FE-001")
    if "verification" not in text.lower() and "验收" not in text and "验证" not in text:
        errors.append("06-acceptance.md missing Verification / 验收 instructions")
    return errors


def check_wbs_table_integrity(pack_dir: Path) -> list[str]:
    """Every work-package row must land inside the parsed table.

    parse_wbs_rows 按空行切表并只取第一个带 wp_id 表头的表。若有人在表格
    中间插入空行，后半段就成了一张无表头的表，被静默丢弃——唯一性、依赖
    解析和环检测都不再覆盖那些行。这里让它显式失败，而不是少查一半。
    """
    path = pack_dir / "02-wbs.md"
    if not path.exists():
        return []
    row_line_numbers = {
        line_number
        for line_number, line in enumerate(read_text(path).splitlines(), start=1)
        if re.match(rf"^\|\s*{WP_ID}\s*\|", line)
    }
    if not row_line_numbers:
        return []
    tables = parse_markdown_tables(read_text(path))
    _, rows = parse_wbs_rows(path)
    parsed = {line_number for line_number, _ in rows}
    artifact_rows = {
        line_number
        for headers, rows in tables
        if "wp_id" in headers and "artifact" in headers
        for line_number, _ in rows
    }
    orphans = sorted(row_line_numbers - parsed - artifact_rows)
    if not orphans:
        return []
    return [
        f"02-wbs.md has {len(orphans)} work-package row(s) outside the parsed table "
        f"(lines {', '.join(str(n) for n in orphans[:5])}"
        f"{' ...' if len(orphans) > 5 else ''}); a blank line inside the table splits it "
        f"and the rows after it are silently skipped by uniqueness, dependency and cycle checks"
    ]


def read_requirements_baseline(pack_dir: Path) -> set[str]:
    """Grandfathered wp_ids allowed to miss a requirements section.

    存量工作包记账用。这个清单只减不增：一旦某个包补上了需求条目，
    validator 会提示把它从 baseline 移除，形成单向棘轮。
    """
    path = pack_dir / REQUIREMENTS_BASELINE
    if not path.exists():
        return set()
    ids: set[str] = set()
    for line in read_text(path).splitlines():
        entry = line.split("#", 1)[0].strip()
        if entry:
            ids.add(entry)
    return ids


def check_requirements(pack_dir: Path) -> tuple[list[str], list[str]]:
    """Every work package needs a requirements section, unless grandfathered.

    返回 (errors, warnings)。新包缺需求是错误；存量包在 baseline 里的记为
    警告，不阻断——否则门禁一上线就全红，只会被关掉。
    """
    wbs_path = pack_dir / "02-wbs.md"
    req_path = pack_dir / "01-requirements.md"
    if not wbs_path.exists():
        return [], []

    _, rows = parse_wbs_rows(wbs_path)
    wp_ids = [row.get("wp_id", "").strip() for _, row in rows]
    wp_ids = [wp_id for wp_id in wp_ids if wp_id]
    if not wp_ids:
        return [], []

    covered: set[str] = set()
    if req_path.exists():
        for line in read_text(req_path).splitlines():
            match = re.match(rf"^##\s+({WP_ID})\b", line)
            if match:
                covered.add(match.group(1))

    baseline = read_requirements_baseline(pack_dir)
    errors: list[str] = []
    warnings: list[str] = []

    missing = [wp_id for wp_id in wp_ids if wp_id not in covered]
    for wp_id in missing:
        if wp_id in baseline:
            continue
        errors.append(
            f"01-requirements.md missing requirements section for {wp_id} "
            f"(add '## {wp_id} <title>', or record it in {REQUIREMENTS_BASELINE})"
        )

    grandfathered = [wp_id for wp_id in missing if wp_id in baseline]
    if grandfathered:
        warnings.append(
            f"{len(grandfathered)}/{len(wp_ids)} work packages still have no requirements "
            f"section and are grandfathered by {REQUIREMENTS_BASELINE}"
        )

    # 棘轮：baseline 里已经补上需求的，提示移除
    resolved = sorted(wp_id for wp_id in baseline if wp_id in covered)
    for wp_id in resolved:
        warnings.append(
            f"{REQUIREMENTS_BASELINE} entry {wp_id} now has requirements — remove it from the baseline"
        )
    stale = sorted(wp_id for wp_id in baseline if wp_id not in wp_ids)
    for wp_id in stale:
        warnings.append(
            f"{REQUIREMENTS_BASELINE} entry {wp_id} is not in 02-wbs.md — remove it from the baseline"
        )
    return errors, warnings


def index_control_rows(
    filename: str,
    rows: list[tuple[int, dict[str, str]]],
    id_header: str,
    id_re: re.Pattern[str],
) -> tuple[dict[str, tuple[int, dict[str, str]]], list[str]]:
    records: dict[str, tuple[int, dict[str, str]]] = {}
    sites: dict[str, list[int]] = {}
    errors: list[str] = []
    for line_number, row in rows:
        record_id = clean_cell(row.get(id_header, ""))
        if not record_id:
            errors.append(f"{filename} {id_header} is empty (line {line_number})")
            continue
        if not id_re.fullmatch(record_id):
            errors.append(f"{filename} has invalid {id_header}: {record_id} (line {line_number})")
            continue
        sites.setdefault(record_id, []).append(line_number)
        records.setdefault(record_id, (line_number, row))
    for record_id, line_numbers in sites.items():
        if len(line_numbers) > 1:
            errors.append(
                f"{filename} duplicate {id_header}: {record_id} "
                f"(lines {', '.join(str(number) for number in line_numbers)})"
            )
    return records, errors


def index_named_rows(
    filename: str,
    rows: list[tuple[int, dict[str, str]]],
    id_header: str,
) -> tuple[dict[str, tuple[int, dict[str, str]]], list[str]]:
    """Index a header-driven contract table whose IDs are project-defined."""
    records: dict[str, tuple[int, dict[str, str]]] = {}
    sites: dict[str, list[int]] = {}
    errors: list[str] = []
    for line_number, row in rows:
        record_id = clean_cell(row.get(id_header, ""))
        if not record_id:
            errors.append(f"{filename} {id_header} is empty (line {line_number})")
            continue
        sites.setdefault(record_id, []).append(line_number)
        records.setdefault(record_id, (line_number, row))
    for record_id, line_numbers in sites.items():
        if len(line_numbers) > 1:
            errors.append(
                f"{filename} duplicate {id_header}: {record_id} "
                f"(lines {', '.join(str(number) for number in line_numbers)})"
            )
    return records, errors


def checked_refs(
    value: str,
    pattern: re.Pattern[str],
    label: str,
    errors: list[str],
    *,
    required: bool = False,
) -> list[str]:
    refs = split_refs(value)
    if required and not refs:
        errors.append(f"{label} is required")
        return []
    for ref in refs:
        if not pattern.fullmatch(ref):
            errors.append(f"{label} has invalid reference: {ref}")
    return [ref for ref in refs if pattern.fullmatch(ref)]


def check_v2(pack_dir: Path) -> list[str]:
    """Validate lifecycle controls enabled by Project Control wbs_schema=2."""
    errors: list[str] = []
    wbs_path = pack_dir / "02-wbs.md"
    wbs_headers, wbs_rows = parse_wbs_rows(wbs_path) if wbs_path.exists() else ([], [])
    required_wbs_headers = [
        "wp_id", "title_cn", "title_en", "type", "owner", "status", "depends_on",
        "acceptance_ref", *V2_WBS_HEADERS,
    ]
    errors.extend(check_headers("02-wbs.md", wbs_headers, required_wbs_headers))

    requirement_versions, requirement_errors = collect_requirement_versions(pack_dir / "01-requirements.md")
    errors.extend(requirement_errors)
    project_control, _ = project_control_values(pack_dir)
    for field in (
        "project_id", "project_status", "product_owner", "current_baseline",
        "planned_start", "planned_finish", "forecast_finish", "actual_start",
        "actual_finish",
    ):
        if field not in project_control or not clean_cell(project_control.get(field, "")):
            errors.append(f"00-brief.md Project Control missing or empty required field: {field}")
    project_status = clean_cell(project_control.get("project_status", "")).lower()
    if project_status and project_status not in PROJECT_STATUS:
        errors.append(
            f"00-brief.md Project Control has invalid project_status: {project_status}"
        )

    owners_path = inherited_pack_file(pack_dir, "OWNERS.md")
    owner_headers, owner_rows, owner_table_errors = find_named_table(owners_path, "role")
    errors.extend(owner_table_errors)
    if owner_headers:
        errors.extend(check_headers("OWNERS.md", owner_headers, ["role", "name", "responsibility"]))
    configured_roles: dict[str, str] = {}
    configured_names: set[str] = set()
    owner_sites: dict[str, list[int]] = {}
    for line_number, row in owner_rows:
        role = clean_cell(row.get("role", ""))
        name = clean_cell(row.get("name", ""))
        if not role:
            errors.append(f"OWNERS.md has empty role (line {line_number})")
            continue
        owner_sites.setdefault(role, []).append(line_number)
        if not is_none(name) and name.lower() != "owner":
            configured_roles[role] = name
            configured_names.add(name)
    for role, line_numbers in owner_sites.items():
        if len(line_numbers) > 1:
            errors.append(
                f"OWNERS.md duplicate role: {role} "
                f"(lines {', '.join(str(number) for number in line_numbers)})"
            )

    def owner_resolves(value: str) -> bool:
        owner = clean_cell(value)
        return owner in configured_roles or owner in configured_names

    def resolves_role(value: str, role: str) -> bool:
        actor = clean_cell(value)
        configured_name = configured_roles.get(role, "")
        return bool(configured_name) and actor in {role, configured_name}

    if project_status in PROJECT_STATUS_REQUIRING_BASELINE:
        for role in (
            "product_owner", "baseline_approver", "change_approver", "acceptance_owner",
        ):
            if role not in configured_roles:
                errors.append(f"OWNERS.md project_status={project_status} requires configured {role}")
        if not owner_resolves(project_control.get("product_owner", "")):
            errors.append(
                "00-brief.md Project Control product_owner must resolve to a configured OWNERS.md role or name"
            )

    work_packages: dict[str, tuple[int, dict[str, str]]] = {}
    work_package_requirements: dict[str, list[str]] = {}
    for line_number, row in wbs_rows:
        wp_id = clean_cell(row.get("wp_id", ""))
        if WP_ID_FULL_RE.fullmatch(wp_id):
            work_packages.setdefault(wp_id, (line_number, row))
        for header in required_wbs_headers:
            if header in wbs_headers and not clean_cell(row.get(header, "")):
                errors.append(f"02-wbs.md {wp_id or '<empty wp_id>'} has empty {header} (line {line_number})")

        status = clean_cell(row.get("status", "")).lower()
        if status != "cancelled" and not owner_resolves(row.get("owner", "")):
            errors.append(
                f"02-wbs.md {wp_id} owner must resolve to a configured OWNERS.md role or name "
                f"(line {line_number})"
            )

        requirement_refs = checked_refs(
            row.get("requirement_refs", ""),
            REQ_REF_FULL_RE,
            f"02-wbs.md {wp_id} requirement_refs (line {line_number})",
            errors,
            required=True,
        )
        work_package_requirements[wp_id] = requirement_refs
        for requirement_ref in requirement_refs:
            if requirement_ref not in requirement_versions:
                errors.append(
                    f"02-wbs.md requirement reference not found: {wp_id} -> {requirement_ref} "
                    f"(line {line_number})"
                )

        delivery_target = clean_cell(row.get("delivery_target", "")).lower()
        if delivery_target and delivery_target not in DELIVERY_TARGETS:
            errors.append(
                f"02-wbs.md {wp_id} has invalid delivery_target: {delivery_target} "
                f"(expected none, review, or production)"
            )
        delivery_counted = clean_cell(row.get("delivery_counted", "")).lower()
        if delivery_counted and delivery_counted not in BOOLEAN_VALUES:
            errors.append(
                f"02-wbs.md {wp_id} has invalid delivery_counted: {delivery_counted} "
                f"(expected yes or no)"
            )
        if delivery_counted == "yes" and delivery_target != "production":
            errors.append(
                f"02-wbs.md {wp_id} delivery_counted=yes requires "
                f"delivery_target=production"
            )

        for field in ("planned_start", "planned_finish", "forecast_finish", "actual_start", "actual_finish"):
            value = row.get(field, "")
            date_required = (
                status in ACTIVE_BASELINE_STATUS
                and field in {"planned_start", "planned_finish", "forecast_finish"}
            ) or (
                status == "in_progress" and field == "actual_start"
            ) or (
                status == "done" and delivery_target == "production" and field == "actual_finish"
            )
            date_checker = check_iso_temporal if field in {"actual_start", "actual_finish"} else check_iso_date
            errors.extend(date_checker(
                value, f"02-wbs.md {wp_id} {field}", required=date_required,
            ))
        planned_start = clean_cell(row.get("planned_start", ""))
        planned_finish = clean_cell(row.get("planned_finish", ""))
        if not check_iso_date(planned_start, "") and not check_iso_date(planned_finish, ""):
            if not is_none(planned_start) and not is_none(planned_finish) and planned_start > planned_finish:
                errors.append(f"02-wbs.md {wp_id} planned_start is after planned_finish")

        baseline_refs = checked_refs(
            row.get("baseline_ref", ""), BL_ID_FULL_RE,
            f"02-wbs.md {wp_id} baseline_ref (line {line_number})", errors,
            required=status in ACTIVE_BASELINE_STATUS
            or (status == "done" and delivery_target == "production"),
        )
        if len(baseline_refs) > 1:
            errors.append(f"02-wbs.md {wp_id} baseline_ref must contain exactly one BL reference")
        change_refs = checked_refs(
            row.get("change_ref", ""), CR_ID_FULL_RE,
            f"02-wbs.md {wp_id} change_ref (line {line_number})", errors,
        )
        if len(change_refs) > 1:
            errors.append(f"02-wbs.md {wp_id} change_ref must contain at most one CR reference")

    risk_path = pack_dir / "07-risks.md"
    risk_headers, risk_rows, risk_table_errors = find_named_table(risk_path, "risk_id")
    errors.extend(risk_table_errors)
    risk_required_headers = [
        "risk_id", "risk_cn", "risk_en", "probability", "impact", "owner",
        "trigger", "response", "due_date", "related_wp", "residual_risk",
        "status", "accepted_by",
    ]
    if risk_headers:
        errors.extend(check_headers("07-risks.md", risk_headers, risk_required_headers))
    risk_records, risk_record_errors = index_control_rows(
        "07-risks.md", risk_rows, "risk_id", RISK_ID_FULL_RE
    )
    errors.extend(risk_record_errors)
    risk_refs_by_wp: dict[str, set[str]] = {}
    for risk_id, (line_number, row) in risk_records.items():
        for field in (
            "risk_cn", "risk_en", "probability", "impact", "owner", "trigger",
            "response", "due_date", "related_wp", "residual_risk", "status",
            "accepted_by",
        ):
            if not clean_cell(row.get(field, "")):
                errors.append(f"07-risks.md {risk_id} has empty {field} (line {line_number})")
        probability = clean_cell(row.get("probability", "")).lower()
        impact = clean_cell(row.get("impact", "")).lower()
        status = clean_cell(row.get("status", "")).lower()
        if probability not in RISK_LEVEL:
            errors.append(f"07-risks.md {risk_id} has invalid probability: {probability}")
        if impact not in RISK_LEVEL:
            errors.append(f"07-risks.md {risk_id} has invalid impact: {impact}")
        if status not in RISK_STATUS:
            errors.append(f"07-risks.md {risk_id} has invalid status: {status}")
        if not owner_resolves(row.get("owner", "")):
            errors.append(
                f"07-risks.md {risk_id} owner must resolve to a configured OWNERS.md role or name"
            )
        if status == "accepted" and not owner_resolves(row.get("accepted_by", "")):
            errors.append(
                f"07-risks.md {risk_id} accepted risk requires accepted_by to resolve in OWNERS.md"
            )
        related_wps = checked_refs(
            row.get("related_wp", ""), WP_ID_FULL_RE,
            f"07-risks.md {risk_id} related_wp (line {line_number})", errors,
            required=True,
        )
        for related_wp in related_wps:
            if related_wp not in work_packages:
                errors.append(
                    f"07-risks.md {risk_id} related work package not found: {related_wp}"
                )
            risk_refs_by_wp.setdefault(related_wp, set()).add(risk_id)

    def contract_records(
        path: Path, id_header: str,
    ) -> dict[str, tuple[int, dict[str, str]]]:
        matches = [
            (headers, rows)
            for headers, rows in parse_markdown_tables(read_text(path))
            if headers and headers[0] == id_header
        ] if path.exists() else []
        headers, rows = matches[0] if matches else ([], [])
        if not matches:
            errors.append(f"{path.name} missing {id_header} table")
        elif len(matches) > 1:
            errors.append(
                f"{path.name} has multiple primary {id_header} tables; keep one unbroken table"
            )
        if headers:
            errors.extend(check_headers(path.name, headers, [id_header, "status"]))
        records, record_errors = index_named_rows(path.name, rows, id_header)
        errors.extend(record_errors)
        for record_id, (line_number, row) in records.items():
            status = clean_cell(row.get("status", "")).lower()
            if status not in ARTIFACT_CONTRACT_STATUS:
                errors.append(
                    f"{path.name} {record_id} has invalid status: {status} "
                    f"(line {line_number})"
                )
        return records

    page_records = contract_records(pack_dir / "03-page-spec.md", "page_id")
    api_records = contract_records(pack_dir / "04-api-contract.md", "api_id")
    model_records = contract_records(pack_dir / "05-data-contract.md", "model_id")
    machine_records = contract_records(pack_dir / "05-data-contract.md", "machine_id")
    data_records = {**model_records, **machine_records}

    acceptance_sections = collect_acceptance_sections(pack_dir / "06-acceptance.md")
    acceptance_metadata_labels = [
        "requirement refs:", "baseline:", "acceptance owner:", "delivery target:",
        "english:", "verification:", "required evidence:", "decision:",
    ]
    for wp_id, (line_number, row) in work_packages.items():
        status = clean_cell(row.get("status", "")).lower()
        delivery_target = clean_cell(row.get("delivery_target", "")).lower()
        # Migrated, already-done non-delivery facts may retain their legacy AC shape.
        # Every proposed or executable v2 package uses the full managed AC contract.
        if status == "cancelled" or (
            status == "done"
            and delivery_target == "none"
            and is_none(row.get("change_ref", ""))
        ):
            continue
        acceptance_ref = clean_cell(row.get("acceptance_ref", ""))
        section = acceptance_sections.get(acceptance_ref, "")
        if not section:
            continue  # check_acceptance reports the missing reference.
        lowered = section.lower()
        for label in acceptance_metadata_labels:
            if label not in lowered:
                errors.append(
                    f"06-acceptance.md {acceptance_ref} missing managed field: {label.rstrip(':')}"
                )
        if "中文：" not in section and "中文:" not in section:
            errors.append(f"06-acceptance.md {acceptance_ref} missing managed field: 中文")
        acceptance_owner_match = re.search(
            r"Acceptance owner:\s*-?\s*`?([^`\n]+)`?",
            section,
            flags=re.IGNORECASE,
        )
        if acceptance_owner_match and not owner_resolves(acceptance_owner_match.group(1).strip()):
            errors.append(
                f"06-acceptance.md {acceptance_ref} acceptance owner must resolve to "
                "a configured OWNERS.md role or name"
            )
        for requirement_ref in work_package_requirements.get(wp_id, []):
            if requirement_ref not in section:
                errors.append(
                    f"06-acceptance.md {acceptance_ref} missing requirement ref {requirement_ref}"
                )
        if delivery_target and f"`{delivery_target}`" not in section:
            errors.append(
                f"06-acceptance.md {acceptance_ref} does not record delivery target {delivery_target}"
            )

    artifact_headers, artifact_rows, artifact_table_errors = find_named_table(
        wbs_path, "artifact"
    )
    errors.extend(artifact_table_errors)
    artifact_required_headers = [
        "wp_id", "artifact", "applicability", "readiness", "owner", "refs",
        "reason", "change_ref",
    ]
    if artifact_headers:
        errors.extend(check_headers(
            "02-wbs.md Artifact Readiness Register",
            artifact_headers,
            artifact_required_headers,
        ))
    artifact_records: dict[tuple[str, str], tuple[int, dict[str, str]]] = {}
    artifact_change_refs: dict[tuple[str, str], list[str]] = {}
    artifact_sites: dict[tuple[str, str], list[int]] = {}
    for line_number, artifact_row in artifact_rows:
        wp_id = clean_cell(artifact_row.get("wp_id", ""))
        artifact = clean_cell(artifact_row.get("artifact", "")).lower()
        key = (wp_id, artifact)
        artifact_sites.setdefault(key, []).append(line_number)
        artifact_records.setdefault(key, (line_number, artifact_row))
        if wp_id not in work_packages:
            errors.append(
                f"02-wbs.md artifact row references unknown work package: {wp_id or '<empty>'} "
                f"(line {line_number})"
            )
        if artifact not in ARTIFACT_TYPES:
            errors.append(
                f"02-wbs.md {wp_id} has invalid artifact: {artifact or '<empty>'} "
                f"(line {line_number})"
            )
        applicability = clean_cell(artifact_row.get("applicability", "")).lower()
        readiness = clean_cell(artifact_row.get("readiness", "")).lower()
        if applicability not in ARTIFACT_APPLICABILITY:
            errors.append(
                f"02-wbs.md {wp_id}/{artifact} has invalid applicability: {applicability}"
            )
        if readiness not in ARTIFACT_READINESS:
            errors.append(
                f"02-wbs.md {wp_id}/{artifact} has invalid readiness: {readiness}"
            )
        if applicability == "not_applicable" and readiness != "not_applicable":
            errors.append(
                f"02-wbs.md {wp_id}/{artifact} not_applicable must use readiness=not_applicable"
            )
        if applicability == "required" and readiness == "not_applicable":
            errors.append(
                f"02-wbs.md {wp_id}/{artifact} required artifact cannot be not_applicable"
            )
        if is_none(artifact_row.get("reason", "")):
            errors.append(f"02-wbs.md {wp_id}/{artifact} requires a concrete reason")
        if not owner_resolves(artifact_row.get("owner", "")):
            errors.append(
                f"02-wbs.md {wp_id}/{artifact} owner must resolve to a configured "
                "OWNERS.md role or name"
            )
        refs = split_refs(artifact_row.get("refs", ""))
        if readiness == "verified" and not refs:
            errors.append(f"02-wbs.md {wp_id}/{artifact} verified readiness requires refs")
        change_refs = checked_refs(
            artifact_row.get("change_ref", ""), CR_ID_FULL_RE,
            f"02-wbs.md {wp_id}/{artifact} change_ref (line {line_number})", errors,
            required=readiness == "change_pending",
        )
        artifact_change_refs[key] = change_refs
        if artifact == "requirement":
            expected = set(work_package_requirements.get(wp_id, []))
            if set(refs) != expected:
                errors.append(
                    f"02-wbs.md {wp_id}/requirement refs must equal WBS requirement_refs"
                )
        if artifact == "acceptance" and wp_id in work_packages:
            expected_acceptance = clean_cell(work_packages[wp_id][1].get("acceptance_ref", ""))
            if refs != [expected_acceptance]:
                errors.append(
                    f"02-wbs.md {wp_id}/acceptance refs must equal {expected_acceptance}"
                )
        if artifact == "risk":
            expected_risks = risk_refs_by_wp.get(wp_id, set())
            if set(refs) != expected_risks:
                errors.append(
                    f"02-wbs.md {wp_id}/risk refs must equal related 07-risks.md records"
                )
        contract_map = {
            "page": page_records,
            "api": api_records,
            "data": data_records,
        }.get(artifact)
        if contract_map is not None:
            for ref in refs:
                record = contract_map.get(ref)
                if record is None:
                    errors.append(
                        f"02-wbs.md {wp_id}/{artifact} reference not found: {ref}"
                    )
                elif readiness == "verified":
                    contract_status = clean_cell(record[1].get("status", "")).lower()
                    if contract_status != "verified":
                        errors.append(
                            f"02-wbs.md {wp_id}/{artifact} verified readiness requires "
                            f"{ref} status=verified"
                        )
    for key, line_numbers in artifact_sites.items():
        if len(line_numbers) > 1:
            errors.append(
                f"02-wbs.md duplicate artifact readiness row: {key[0]}/{key[1]} "
                f"(lines {', '.join(str(number) for number in line_numbers)})"
            )
    for wp_id, (_, row) in work_packages.items():
        status = clean_cell(row.get("status", "")).lower()
        delivery_target = clean_cell(row.get("delivery_target", "")).lower()
        if (
            status == "done"
            and delivery_target == "none"
            and is_none(row.get("change_ref", ""))
        ):
            continue
        missing_artifacts = sorted(
            artifact for artifact in ARTIFACT_TYPES
            if (wp_id, artifact) not in artifact_records
        )
        if missing_artifacts:
            errors.append(
                f"02-wbs.md {wp_id} missing artifact readiness rows: "
                + ", ".join(missing_artifacts)
            )

    baseline_path = pack_dir / "09-baselines.md"
    baseline_headers, baseline_rows, table_errors = find_named_table(baseline_path, "baseline_id")
    errors.extend(table_errors)
    baseline_required = [
        "baseline_id", "version", "status", "current", "approved_by", "approved_at",
        "planned_start", "planned_finish", "forecast_finish", "requirement_refs", "wp_refs",
        "change_ref", "supersedes",
    ]
    if baseline_headers:
        errors.extend(check_headers(baseline_path.name, baseline_headers, baseline_required))
    baselines, record_errors = index_control_rows(
        baseline_path.name, baseline_rows, "baseline_id", BL_ID_FULL_RE
    )
    errors.extend(record_errors)

    handoff_path = pack_dir / "10-handoff.md"
    run_headers, run_rows, table_errors = find_named_table(handoff_path, "run_id")
    errors.extend(table_errors)
    run_required = [
        "run_id", "wp_id", "baseline_ref", "status", "actual_start", "actual_finish",
        "outcome", "change_ref", "next_action",
    ]
    if run_headers:
        errors.extend(check_headers(handoff_path.name, run_headers, run_required))
    runs, record_errors = index_control_rows(handoff_path.name, run_rows, "run_id", RUN_ID_FULL_RE)
    errors.extend(record_errors)

    release_headers, release_rows, table_errors = find_named_table(handoff_path, "release_id")
    errors.extend(table_errors)
    release_required = [
        "release_id", "wp_id", "run_ref", "baseline_ref", "status",
        "verified_at", "environment", "evidence", "verified_by",
    ]
    if release_headers:
        errors.extend(check_headers(handoff_path.name, release_headers, release_required))
    releases, record_errors = index_control_rows(
        handoff_path.name, release_rows, "release_id", REL_ID_FULL_RE
    )
    errors.extend(record_errors)

    change_path = pack_dir / "11-change-requests.md"
    change_headers, change_rows, table_errors = find_named_table(change_path, "cr_id")
    errors.extend(table_errors)
    change_required = [
        "cr_id", "status", "requested_at", "decided_at", "affected_refs",
        "baseline_from", "baseline_to", "decision", "approver",
    ]
    if change_headers:
        errors.extend(check_headers(change_path.name, change_headers, change_required))
    changes, record_errors = index_control_rows(change_path.name, change_rows, "cr_id", CR_ID_FULL_RE)
    errors.extend(record_errors)
    for (wp_id, artifact), change_refs in artifact_change_refs.items():
        for change_ref in change_refs:
            if change_ref not in changes:
                errors.append(
                    f"02-wbs.md {wp_id}/{artifact} change reference not found: {change_ref}"
                )

    # Validate baseline records before resolving cross-file references.
    current_rows: list[str] = []
    current_approved_baselines: list[str] = []
    baseline_requirement_refs: dict[str, list[str]] = {}
    baseline_wp_refs: dict[str, list[str]] = {}
    baseline_versions: dict[int, str] = {}
    baseline_change_refs: dict[str, list[str]] = {}
    baseline_supersedes_refs: dict[str, list[str]] = {}
    baseline_statuses: dict[str, str] = {}
    for baseline_id, (line_number, row) in baselines.items():
        for field in baseline_required:
            if field in baseline_headers and not clean_cell(row.get(field, "")):
                errors.append(
                    f"09-baselines.md {baseline_id} has empty {field} (line {line_number})"
                )
        version = clean_cell(row.get("version", ""))
        status = clean_cell(row.get("status", "")).lower()
        current = clean_cell(row.get("current", "")).lower()
        if not BASELINE_VERSION_RE.fullmatch(version):
            errors.append(
                f"09-baselines.md {baseline_id} has invalid version: {version} (expected v1, v2, ...)"
            )
        else:
            version_number = int(version[1:])
            if version_number in baseline_versions:
                errors.append(
                    f"09-baselines.md duplicate baseline version: {version} "
                    f"({baseline_versions[version_number]}, {baseline_id})"
                )
            else:
                baseline_versions[version_number] = baseline_id
        if status not in BASELINE_STATUS:
            errors.append(f"09-baselines.md {baseline_id} has invalid status: {status}")
        baseline_statuses[baseline_id] = status
        if current not in BOOLEAN_VALUES:
            errors.append(f"09-baselines.md {baseline_id} has invalid current: {current} (expected yes or no)")
        if current == "yes":
            current_rows.append(baseline_id)
            if status != "approved":
                errors.append(f"09-baselines.md current baseline must be approved: {baseline_id}")
            else:
                current_approved_baselines.append(baseline_id)
        approved_record = status in {"approved", "superseded"}
        if approved_record and is_none(row.get("approved_by", "")):
            errors.append(f"09-baselines.md {baseline_id} approved_by is required for {status}")
        elif approved_record and not resolves_role(row.get("approved_by", ""), "baseline_approver"):
            errors.append(
                f"09-baselines.md {baseline_id} approved_by must resolve to baseline_approver"
            )
        errors.extend(check_iso_date(
            row.get("approved_at", ""), f"09-baselines.md {baseline_id} approved_at",
            required=approved_record,
        ))
        errors.extend(check_iso_date(
            row.get("planned_start", ""), f"09-baselines.md {baseline_id} planned_start",
            required=approved_record,
        ))
        errors.extend(check_iso_date(
            row.get("planned_finish", ""), f"09-baselines.md {baseline_id} planned_finish",
            required=approved_record,
        ))
        errors.extend(check_iso_date(
            row.get("forecast_finish", ""), f"09-baselines.md {baseline_id} forecast_finish",
            required=approved_record,
        ))
        planned_start = clean_cell(row.get("planned_start", ""))
        planned_finish = clean_cell(row.get("planned_finish", ""))
        forecast_finish = clean_cell(row.get("forecast_finish", ""))
        if not check_iso_date(planned_start, "") and not check_iso_date(planned_finish, ""):
            if not is_none(planned_start) and not is_none(planned_finish) and planned_start > planned_finish:
                errors.append(
                    f"09-baselines.md {baseline_id} planned_start is after planned_finish"
                )
        if not check_iso_date(planned_start, "") and not check_iso_date(forecast_finish, ""):
            if not is_none(planned_start) and not is_none(forecast_finish) and planned_start > forecast_finish:
                errors.append(
                    f"09-baselines.md {baseline_id} planned_start is after forecast_finish"
                )
        req_refs = checked_refs(
            row.get("requirement_refs", ""), REQ_REF_FULL_RE,
            f"09-baselines.md {baseline_id} requirement_refs (line {line_number})", errors,
            required=approved_record,
        )
        wp_refs = checked_refs(
            row.get("wp_refs", ""), WP_ID_FULL_RE,
            f"09-baselines.md {baseline_id} wp_refs (line {line_number})", errors,
            required=approved_record,
        )
        baseline_requirement_refs[baseline_id] = req_refs
        baseline_wp_refs[baseline_id] = wp_refs
        for ref in req_refs:
            if ref not in requirement_versions:
                errors.append(f"09-baselines.md requirement reference not found: {baseline_id} -> {ref}")
        for ref in wp_refs:
            if ref not in work_packages:
                errors.append(f"09-baselines.md work-package reference not found: {baseline_id} -> {ref}")
        change_refs = checked_refs(
            row.get("change_ref", ""), CR_ID_FULL_RE,
            f"09-baselines.md {baseline_id} change_ref (line {line_number})", errors,
        )
        baseline_change_refs[baseline_id] = change_refs
        for change_ref in change_refs:
            if change_ref not in changes:
                errors.append(f"09-baselines.md change reference not found: {baseline_id} -> {change_ref}")
            elif approved_record:
                change_status = clean_cell(changes[change_ref][1].get("status", "")).lower()
                if change_status not in {"approved", "implemented"}:
                    errors.append(
                        f"09-baselines.md {baseline_id} requires approved change_ref, "
                        f"but {change_ref} is {change_status or '<empty>'}"
                    )

        supersedes_refs = checked_refs(
            row.get("supersedes", ""), BL_ID_FULL_RE,
            f"09-baselines.md {baseline_id} supersedes (line {line_number})", errors,
        )
        baseline_supersedes_refs[baseline_id] = supersedes_refs
        if len(supersedes_refs) > 1:
            errors.append(f"09-baselines.md {baseline_id} supersedes must contain at most one BL reference")
        for supersedes_ref in supersedes_refs:
            if supersedes_ref == baseline_id:
                errors.append(f"09-baselines.md {baseline_id} cannot supersede itself")
            elif supersedes_ref not in baselines:
                errors.append(
                    f"09-baselines.md supersedes reference not found: {baseline_id} -> {supersedes_ref}"
                )

    for version_number, baseline_id in sorted(baseline_versions.items()):
        status = baseline_statuses.get(baseline_id, "")
        change_refs = baseline_change_refs.get(baseline_id, [])
        supersedes_refs = baseline_supersedes_refs.get(baseline_id, [])
        if version_number == 1:
            if supersedes_refs:
                errors.append(
                    f"09-baselines.md {baseline_id} v1 must not supersede another baseline"
                )
            continue
        prior_id = baseline_versions.get(version_number - 1)
        if prior_id is None:
            errors.append(
                f"09-baselines.md baseline versions cannot skip v{version_number - 1} "
                f"before {baseline_id} v{version_number}"
            )
            continue
        if supersedes_refs != [prior_id]:
            errors.append(
                f"09-baselines.md {baseline_id} v{version_number} must supersede "
                f"immediate prior baseline {prior_id}"
            )
        if len(change_refs) != 1:
            errors.append(
                f"09-baselines.md {baseline_id} v{version_number} requires exactly one CR"
            )
        else:
            change_row = changes.get(change_refs[0])
            if change_row is not None:
                baseline_from = split_refs(change_row[1].get("baseline_from", ""))
                baseline_to = split_refs(change_row[1].get("baseline_to", ""))
                if baseline_from != [prior_id] or baseline_to != [baseline_id]:
                    errors.append(
                        f"11-change-requests.md {change_refs[0]} must link "
                        f"baseline_from={prior_id} and baseline_to={baseline_id}"
                    )
        if status in {"approved", "superseded"} and baseline_statuses.get(prior_id) != "superseded":
            errors.append(
                f"09-baselines.md {baseline_id} is {status}; prior baseline {prior_id} "
                f"must be superseded"
            )

    if len(current_rows) > 1:
        errors.append(
            f"09-baselines.md allows at most one current approved baseline; "
            f"found {len(current_rows)} current row(s)"
        )
    if project_status in PROJECT_STATUS_REQUIRING_BASELINE and len(current_approved_baselines) != 1:
        errors.append(
            f"09-baselines.md project_status={project_status} requires exactly one current "
            f"approved baseline; found {len(current_approved_baselines)}"
        )
    current_baseline = (
        current_approved_baselines[0] if len(current_approved_baselines) == 1 else ""
    )

    # Project Control may repeat the current baseline for fast AI startup; if present it must agree.
    declared_current = clean_cell(project_control.get("current_baseline", ""))
    if not is_none(declared_current):
        if not BL_ID_FULL_RE.fullmatch(declared_current):
            errors.append(f"00-brief.md Project Control has invalid current_baseline: {declared_current}")
        elif current_baseline and declared_current != current_baseline:
            errors.append(
                f"00-brief.md current_baseline {declared_current} does not match "
                f"09-baselines.md current baseline {current_baseline}"
            )
        elif not current_baseline:
            errors.append(
                f"00-brief.md current_baseline {declared_current} has no current approved row "
                f"in 09-baselines.md"
            )
    elif current_baseline:
        errors.append(
            f"00-brief.md current_baseline is none but 09-baselines.md marks {current_baseline} current"
        )
    if project_status in PROJECT_STATUS_REQUIRING_BASELINE and is_none(declared_current):
        errors.append(
            f"00-brief.md project_status={project_status} requires current_baseline"
        )
    for field in ("planned_start", "planned_finish", "forecast_finish", "actual_start", "actual_finish"):
        if field in project_control:
            errors.extend(check_iso_date(
                project_control[field], f"00-brief.md Project Control {field}", required=False
            ))

    # Validate change requests and their references.
    acceptance_ids = collect_control_headings(pack_dir / "06-acceptance.md", AC_ID)
    risk_ids = set(risk_records)
    for requirement_ref, requirement in requirement_versions.items():
        if requirement.get("source") != "register":
            continue
        if not owner_resolves(str(requirement.get("owner", ""))):
            errors.append(
                f"01-requirements.md {requirement_ref} owner must resolve to a configured "
                "OWNERS.md role or name"
            )
        for acceptance_ref in requirement.get("acceptance_refs", []):
            if acceptance_ref not in acceptance_ids:
                errors.append(
                    f"01-requirements.md {requirement_ref} acceptance reference not found: "
                    f"{acceptance_ref}"
                )
        for baseline_ref in requirement.get("baseline_refs", []):
            if baseline_ref not in baselines:
                errors.append(
                    f"01-requirements.md {requirement_ref} baseline reference not found: "
                    f"{baseline_ref}"
                )
        for change_ref in requirement.get("change_refs", []):
            if change_ref not in changes:
                errors.append(
                    f"01-requirements.md {requirement_ref} change reference not found: "
                    f"{change_ref}"
                )
    all_reference_maps = {
        "WP": work_packages,
        "REQ": requirement_versions,
        "AC": acceptance_ids,
        "RISK": risk_ids,
        "BL": baselines,
        "RUN": runs,
        "REL": releases,
    }
    for cr_id, (line_number, row) in changes.items():
        status = clean_cell(row.get("status", "")).lower()
        if status not in CHANGE_STATUS:
            errors.append(f"11-change-requests.md {cr_id} has invalid status: {status}")
        errors.extend(check_iso_date(
            row.get("requested_at", ""), f"11-change-requests.md {cr_id} requested_at", required=True
        ))
        decided = status in {"approved", "rejected", "implemented"}
        errors.extend(check_iso_date(
            row.get("decided_at", ""), f"11-change-requests.md {cr_id} decided_at", required=decided
        ))
        if decided:
            for field in ("decision", "approver"):
                if is_none(row.get(field, "")):
                    errors.append(f"11-change-requests.md {cr_id} {field} is required for {status}")
            if not is_none(row.get("approver", "")) and not resolves_role(
                row.get("approver", ""), "change_approver"
            ):
                errors.append(
                    f"11-change-requests.md {cr_id} approver must resolve to change_approver"
                )
        affected_refs = split_refs(row.get("affected_refs", ""))
        if not affected_refs:
            errors.append(f"11-change-requests.md {cr_id} affected_refs is required")
        for ref in affected_refs:
            ref_type = ref.split("-", 1)[0]
            if ref_type == "REQ":
                valid_syntax = REQ_REF_FULL_RE.fullmatch(ref)
            elif ref_type == "WP":
                valid_syntax = WP_ID_FULL_RE.fullmatch(ref)
            elif ref_type == "AC":
                valid_syntax = AC_ID_FULL_RE.fullmatch(ref)
            elif ref_type == "RISK":
                valid_syntax = RISK_ID_FULL_RE.fullmatch(ref)
            elif ref_type == "BL":
                valid_syntax = BL_ID_FULL_RE.fullmatch(ref)
            elif ref_type == "RUN":
                valid_syntax = RUN_ID_FULL_RE.fullmatch(ref)
            elif ref_type == "REL":
                valid_syntax = REL_ID_FULL_RE.fullmatch(ref)
            else:
                valid_syntax = None
            if not valid_syntax:
                errors.append(
                    f"11-change-requests.md {cr_id} affected_refs has invalid reference: {ref}"
                )
            elif ref not in all_reference_maps[ref_type]:
                errors.append(
                    f"11-change-requests.md {cr_id} affected reference not found: {ref}"
                )
        for field in ("baseline_from", "baseline_to"):
            refs = checked_refs(
                row.get(field, ""), BL_ID_FULL_RE,
                f"11-change-requests.md {cr_id} {field} (line {line_number})", errors,
            )
            if len(refs) > 1:
                errors.append(f"11-change-requests.md {cr_id} {field} must contain at most one BL reference")
            for ref in refs:
                if ref not in baselines:
                    errors.append(f"11-change-requests.md {cr_id} baseline reference not found: {ref}")

    # Validate AI run and release evidence.
    active_runs_by_wp: dict[str, list[str]] = {}
    for run_id, (line_number, row) in runs.items():
        wp_id = clean_cell(row.get("wp_id", ""))
        if not WP_ID_FULL_RE.fullmatch(wp_id):
            errors.append(f"10-handoff.md {run_id} has invalid wp_id: {wp_id}")
        elif wp_id not in work_packages:
            errors.append(f"10-handoff.md {run_id} work package not found: {wp_id}")
        baseline_ref = clean_cell(row.get("baseline_ref", ""))
        if not BL_ID_FULL_RE.fullmatch(baseline_ref):
            errors.append(f"10-handoff.md {run_id} has invalid baseline_ref: {baseline_ref}")
        elif baseline_ref not in baselines:
            errors.append(f"10-handoff.md {run_id} baseline reference not found: {baseline_ref}")
        elif baseline_statuses.get(baseline_ref) not in {"approved", "superseded"}:
            errors.append(
                f"10-handoff.md {run_id} baseline_ref must be approved or superseded: "
                f"{baseline_ref} is {baseline_statuses.get(baseline_ref) or '<empty>'}"
            )
        status = clean_cell(row.get("status", "")).lower()
        outcome = clean_cell(row.get("outcome", "")).lower()
        if status not in RUN_STATUS:
            errors.append(f"10-handoff.md {run_id} has invalid status: {status}")
        errors.extend(check_iso_temporal(
            row.get("actual_start", ""), f"10-handoff.md {run_id} actual_start", required=True
        ))
        errors.extend(check_iso_temporal(
            row.get("actual_finish", ""), f"10-handoff.md {run_id} actual_finish",
            required=status == "closed",
        ))
        actual_start = clean_cell(row.get("actual_start", ""))
        actual_finish = clean_cell(row.get("actual_finish", ""))
        if not is_none(actual_finish) and temporal_is_after(actual_start, actual_finish):
            errors.append(f"10-handoff.md {run_id} actual_start is after actual_finish")
        if status == "active" and not is_none(outcome):
            errors.append(f"10-handoff.md {run_id} active run must not have a terminal outcome")
        if status == "active":
            active_runs_by_wp.setdefault(wp_id, []).append(run_id)
            if current_baseline and baseline_ref != current_baseline:
                errors.append(
                    f"10-handoff.md active {run_id} must use current baseline {current_baseline}"
                )
            wp_record = work_packages.get(wp_id)
            if wp_record and clean_cell(wp_record[1].get("status", "")).lower() != "in_progress":
                errors.append(
                    f"10-handoff.md active {run_id} requires {wp_id} status=in_progress"
                )
        if status == "closed" and outcome not in RUN_OUTCOME:
            errors.append(
                f"10-handoff.md {run_id} closed run needs outcome completed, blocked, or change_required"
            )
        if outcome in {"blocked", "change_required"} and is_none(row.get("next_action", "")):
            errors.append(f"10-handoff.md {run_id} {outcome} outcome requires next_action")
        change_refs = checked_refs(
            row.get("change_ref", ""), CR_ID_FULL_RE,
            f"10-handoff.md {run_id} change_ref (line {line_number})", errors,
        )
        for ref in change_refs:
            if ref not in changes:
                errors.append(f"10-handoff.md {run_id} change reference not found: {ref}")

    for wp_id, active_run_ids in active_runs_by_wp.items():
        if len(active_run_ids) > 1:
            errors.append(
                f"10-handoff.md {wp_id} has multiple active RUNs: "
                + ", ".join(active_run_ids)
            )

    # A closed RUN describes a historical execution. When a later RUN for the
    # same work package is active, the current WP status follows that active RUN
    # (`in_progress`) instead of the historical outcome. Without a newer active
    # RUN, the terminal outcome must still agree with the current WP status.
    for run_id, (_, row) in runs.items():
        if clean_cell(row.get("status", "")).lower() != "closed":
            continue
        wp_id = clean_cell(row.get("wp_id", ""))
        if active_runs_by_wp.get(wp_id):
            continue
        wp_record = work_packages.get(wp_id)
        if not wp_record:
            continue
        outcome = clean_cell(row.get("outcome", "")).lower()
        wp_status = clean_cell(wp_record[1].get("status", "")).lower()
        if outcome == "completed" and wp_status not in {"review", "done"}:
            errors.append(
                f"10-handoff.md completed {run_id} requires {wp_id} status=review or done"
            )
        if outcome in {"blocked", "change_required"} and wp_status != "blocked":
            errors.append(
                f"10-handoff.md {outcome} {run_id} requires {wp_id} status=blocked"
            )

    if project_status == "closed":
        errors.extend(check_iso_temporal(
            project_control.get("actual_start", ""),
            "00-brief.md closed project actual_start", required=True,
        ))
        errors.extend(check_iso_temporal(
            project_control.get("actual_finish", ""),
            "00-brief.md closed project actual_finish", required=True,
        ))
        if temporal_is_after(
            project_control.get("actual_start", ""),
            project_control.get("actual_finish", ""),
        ):
            errors.append("00-brief.md project actual_start is after actual_finish")
        if active_runs_by_wp:
            errors.append("10-handoff.md closed project must not have active RUNs")
        for wp_id, (_, row) in work_packages.items():
            status = clean_cell(row.get("status", "")).lower()
            if status not in {"done", "cancelled"}:
                errors.append(
                    f"02-wbs.md closed project requires done/cancelled work packages: "
                    f"{wp_id} is {status}"
                )

    for release_id, (line_number, row) in releases.items():
        wp_id = clean_cell(row.get("wp_id", ""))
        if not WP_ID_FULL_RE.fullmatch(wp_id):
            errors.append(f"10-handoff.md {release_id} has invalid wp_id: {wp_id}")
        elif wp_id not in work_packages:
            errors.append(f"10-handoff.md {release_id} work package not found: {wp_id}")
        status = clean_cell(row.get("status", "")).lower()
        if status not in RELEASE_STATUS:
            errors.append(f"10-handoff.md {release_id} has invalid status: {status}")
        errors.extend(check_iso_temporal(
            row.get("verified_at", ""), f"10-handoff.md {release_id} verified_at",
            required=status == "verified",
        ))
        run_refs = checked_refs(
            row.get("run_ref", ""), RUN_ID_FULL_RE,
            f"10-handoff.md {release_id} run_ref (line {line_number})", errors,
            required=status == "verified",
        )
        baseline_refs = checked_refs(
            row.get("baseline_ref", ""), BL_ID_FULL_RE,
            f"10-handoff.md {release_id} baseline_ref (line {line_number})", errors,
            required=status == "verified",
        )
        if len(run_refs) > 1:
            errors.append(f"10-handoff.md {release_id} run_ref must contain exactly one RUN")
        if len(baseline_refs) > 1:
            errors.append(f"10-handoff.md {release_id} baseline_ref must contain exactly one BL")
        if status == "verified":
            for field in ("environment", "evidence", "verified_by"):
                if is_none(row.get(field, "")):
                    errors.append(f"10-handoff.md {release_id} {field} is required when verified")
            evidence = clean_cell(row.get("evidence", ""))
            if not is_none(evidence) and not has_stable_evidence_locator(evidence):
                errors.append(
                    f"10-handoff.md {release_id} evidence is too vague; record a stable command, URI, path, commit, or controlled evidence ID"
                )
            if not is_none(row.get("verified_by", "")) and not resolves_role(
                row.get("verified_by", ""), "acceptance_owner"
            ):
                errors.append(
                    f"10-handoff.md {release_id} verified_by must resolve to acceptance_owner"
                )
            wp_record = work_packages.get(wp_id)
            if (
                clean_cell(row.get("environment", "")).lower() == "production"
                and wp_record is not None
                and clean_cell(wp_record[1].get("delivery_target", "")).lower() == "production"
            ):
                wp_status = clean_cell(wp_record[1].get("status", "")).lower()
                if wp_status != "done":
                    errors.append(
                        f"10-handoff.md verified production {release_id} requires {wp_id} status=done"
                    )
                if release_id not in split_refs(wp_record[1].get("release_ref", "")):
                    errors.append(
                        f"10-handoff.md verified production {release_id} must be referenced by {wp_id} release_ref"
                    )

            run_record = runs.get(run_refs[0]) if len(run_refs) == 1 else None
            if run_record is None and len(run_refs) == 1:
                errors.append(
                    f"10-handoff.md {release_id} run reference not found: {run_refs[0]}"
                )
            if run_record is not None:
                run_row = run_record[1]
                if clean_cell(run_row.get("wp_id", "")) != wp_id:
                    errors.append(
                        f"10-handoff.md {release_id} run_ref {run_refs[0]} belongs to another work package"
                    )
                if clean_cell(run_row.get("status", "")).lower() != "closed" or clean_cell(
                    run_row.get("outcome", "")
                ).lower() != "completed":
                    errors.append(
                        f"10-handoff.md verified {release_id} requires a closed completed RUN"
                    )
                verified_at = clean_cell(row.get("verified_at", ""))
                run_finish = clean_cell(run_row.get("actual_finish", ""))
                if not is_none(verified_at) and not is_none(run_finish) and temporal_is_after(
                    run_finish, verified_at
                ):
                    errors.append(
                        f"10-handoff.md {release_id} verified_at is before {run_refs[0]} actual_finish"
                    )
                if len(baseline_refs) == 1 and clean_cell(
                    run_row.get("baseline_ref", "")
                ) != baseline_refs[0]:
                    errors.append(
                        f"10-handoff.md {release_id} baseline_ref does not match {run_refs[0]}"
                    )
            if len(baseline_refs) == 1:
                baseline_ref = baseline_refs[0]
                if baseline_ref not in baselines:
                    errors.append(
                        f"10-handoff.md {release_id} baseline reference not found: {baseline_ref}"
                    )
                elif baseline_statuses.get(baseline_ref) not in {"approved", "superseded"}:
                    errors.append(
                        f"10-handoff.md {release_id} baseline_ref must be approved or superseded"
                    )

    for (wp_id, artifact), (_, artifact_row) in artifact_records.items():
        if artifact != "handoff":
            continue
        readiness = clean_cell(artifact_row.get("readiness", "")).lower()
        for ref in split_refs(artifact_row.get("refs", "")):
            run_record = runs.get(ref)
            release_record = releases.get(ref)
            if run_record is None and release_record is None:
                errors.append(
                    f"02-wbs.md {wp_id}/handoff reference not found: {ref}"
                )
                continue
            record_row = (run_record or release_record)[1]
            if clean_cell(record_row.get("wp_id", "")) != wp_id:
                errors.append(
                    f"02-wbs.md {wp_id}/handoff reference {ref} belongs to another work package"
                )
            if readiness == "verified" and run_record is not None:
                if clean_cell(record_row.get("status", "")).lower() != "closed":
                    errors.append(
                        f"02-wbs.md {wp_id}/handoff verified readiness requires {ref} status=closed"
                    )
            if readiness == "verified" and release_record is not None:
                if clean_cell(record_row.get("status", "")).lower() != "verified":
                    errors.append(
                        f"02-wbs.md {wp_id}/handoff verified readiness requires {ref} status=verified"
                    )

    # Current baseline is the executable scope boundary.
    current_wp_refs = set(baseline_wp_refs.get(current_baseline, []))
    current_req_refs = set(baseline_requirement_refs.get(current_baseline, []))
    for requirement_ref in current_req_refs:
        requirement = requirement_versions.get(requirement_ref)
        if requirement and requirement.get("source") == "register":
            requirement_status = str(requirement.get("status", ""))
            if requirement_status not in {"approved", "baselined"}:
                errors.append(
                    f"09-baselines.md current baseline cannot use requirement "
                    f"{requirement_ref} with status={requirement_status}"
                )
    for wp_id in current_wp_refs:
        work_package = work_packages.get(wp_id)
        if work_package is None:
            continue
        status = clean_cell(work_package[1].get("status", "")).lower()
        if status in {"proposed", "cancelled"}:
            errors.append(
                f"09-baselines.md current baseline cannot include {status} work package: {wp_id}"
            )
        for requirement_ref in work_package_requirements.get(wp_id, []):
            if requirement_ref not in current_req_refs:
                errors.append(
                    f"09-baselines.md current work-package requirement is outside baseline: "
                    f"{wp_id} -> {requirement_ref}"
                )
    for wp_id, (line_number, row) in work_packages.items():
        status = clean_cell(row.get("status", "")).lower()
        delivery_target = clean_cell(row.get("delivery_target", "")).lower()
        delivery_counted = clean_cell(row.get("delivery_counted", "")).lower()
        baseline_refs = [ref for ref in split_refs(row.get("baseline_ref", "")) if BL_ID_FULL_RE.fullmatch(ref)]
        for baseline_ref in baseline_refs:
            if baseline_ref not in baselines:
                errors.append(f"02-wbs.md baseline reference not found: {wp_id} -> {baseline_ref}")
        change_refs = [ref for ref in split_refs(row.get("change_ref", "")) if CR_ID_FULL_RE.fullmatch(ref)]
        for change_ref in change_refs:
            if change_ref not in changes:
                errors.append(f"02-wbs.md change reference not found: {wp_id} -> {change_ref}")
            elif status in ACTIVE_BASELINE_STATUS | {"done"}:
                change_status = clean_cell(changes[change_ref][1].get("status", "")).lower()
                if change_status not in {"approved", "implemented"}:
                    errors.append(
                        f"02-wbs.md {wp_id} requires approved change_ref, "
                        f"but {change_ref} is {change_status or '<empty>'}"
                    )

        if project_status in {"draft", "planning"} and status not in {"proposed", "cancelled"}:
            errors.append(
                f"02-wbs.md project_status={project_status} allows only proposed or cancelled "
                f"work packages: {wp_id} is {status}"
            )
        if (
            current_baseline
            and delivery_counted == "yes"
            and status not in {"proposed", "cancelled"}
            and wp_id not in current_wp_refs
        ):
            errors.append(
                f"02-wbs.md production-counted work package is outside current baseline: "
                f"{wp_id} -> {current_baseline}"
            )
        if status == "done" and delivery_target == "production" and len(baseline_refs) == 1:
            baseline_status = baseline_statuses.get(baseline_refs[0], "")
            if baseline_status not in {"approved", "superseded"}:
                errors.append(
                    f"02-wbs.md production done {wp_id} must retain an approved or superseded baseline_ref"
                )
        if status not in ACTIVE_BASELINE_STATUS:
            continue
        if len(baseline_refs) != 1 or baseline_refs[0] != current_baseline:
            errors.append(
                f"02-wbs.md {status} work package must use current baseline_ref: "
                f"{wp_id} -> {current_baseline or 'none'}"
            )
        if current_baseline:
            if wp_id not in current_wp_refs:
                errors.append(
                    f"02-wbs.md active work package is outside current baseline: "
                    f"{wp_id} -> {current_baseline} (line {line_number})"
                )

    # Conditional AI start/finish gates reference RUN and REL records from 02-wbs.md.
    for wp_id, (line_number, row) in work_packages.items():
        status = clean_cell(row.get("status", "")).lower()
        delivery_target = clean_cell(row.get("delivery_target", "")).lower()
        run_refs = checked_refs(
            row.get("run_ref", ""), RUN_ID_FULL_RE,
            f"02-wbs.md {wp_id} run_ref (line {line_number})", errors,
            required=status == "in_progress" or (status == "done" and delivery_target == "production"),
        )
        release_refs = checked_refs(
            row.get("release_ref", ""), REL_ID_FULL_RE,
            f"02-wbs.md {wp_id} release_ref (line {line_number})", errors,
            required=status == "done" and delivery_target == "production",
        )
        if len(run_refs) > 1:
            errors.append(f"02-wbs.md {wp_id} run_ref must contain exactly one RUN reference")
        if len(release_refs) > 1:
            errors.append(f"02-wbs.md {wp_id} release_ref must contain exactly one REL reference")
        run_record = runs.get(run_refs[0]) if len(run_refs) == 1 else None
        if len(run_refs) == 1 and run_record is None:
            errors.append(f"02-wbs.md run reference not found: {wp_id} -> {run_refs[0]}")
        if run_record is not None:
            _, run_row = run_record
            if clean_cell(run_row.get("wp_id", "")) != wp_id:
                errors.append(f"02-wbs.md {wp_id} run_ref {run_refs[0]} belongs to another work package")
            wp_baseline_refs = [
                ref for ref in split_refs(row.get("baseline_ref", "")) if BL_ID_FULL_RE.fullmatch(ref)
            ]
            if len(wp_baseline_refs) == 1 and clean_cell(run_row.get("baseline_ref", "")) != wp_baseline_refs[0]:
                errors.append(
                    f"02-wbs.md {wp_id} baseline_ref does not match {run_refs[0]} baseline_ref"
                )
            if status == "in_progress":
                if clean_cell(run_row.get("status", "")).lower() != "active":
                    errors.append(f"02-wbs.md in_progress {wp_id} requires an active RUN")
                if is_none(run_row.get("actual_start", "")):
                    errors.append(f"02-wbs.md in_progress {wp_id} RUN has no actual_start")
                if current_baseline and clean_cell(run_row.get("baseline_ref", "")) != current_baseline:
                    errors.append(
                        f"02-wbs.md in_progress {wp_id} RUN is not tied to current baseline {current_baseline}"
                    )
                if not same_temporal_value(row.get("actual_start", ""), run_row.get("actual_start", "")):
                    errors.append(
                        f"02-wbs.md in_progress {wp_id} actual_start does not match {run_refs[0]}"
                    )
            if status == "done" and delivery_target == "production":
                if clean_cell(run_row.get("status", "")).lower() != "closed":
                    errors.append(f"02-wbs.md production done {wp_id} requires a closed RUN")
                if clean_cell(run_row.get("outcome", "")).lower() != "completed":
                    errors.append(f"02-wbs.md production done {wp_id} requires RUN outcome=completed")
                if is_none(run_row.get("actual_finish", "")):
                    errors.append(f"02-wbs.md production done {wp_id} RUN has no actual_finish")
                elif not same_temporal_value(row.get("actual_finish", ""), run_row.get("actual_finish", "")):
                    errors.append(
                        f"02-wbs.md production done {wp_id} actual_finish does not match {run_refs[0]}"
                    )
        release_record = releases.get(release_refs[0]) if len(release_refs) == 1 else None
        if len(release_refs) == 1 and release_record is None:
            errors.append(f"02-wbs.md release reference not found: {wp_id} -> {release_refs[0]}")
        if release_record is not None:
            _, release_row = release_record
            if clean_cell(release_row.get("wp_id", "")) != wp_id:
                errors.append(
                    f"02-wbs.md {wp_id} release_ref {release_refs[0]} belongs to another work package"
                )
            if status == "done" and delivery_target == "production":
                release_run_refs = split_refs(release_row.get("run_ref", ""))
                if len(run_refs) == 1 and release_run_refs != run_refs:
                    errors.append(
                        f"02-wbs.md production done {wp_id} REL must reference {run_refs[0]}"
                    )
                wp_baseline_refs = [
                    ref for ref in split_refs(row.get("baseline_ref", ""))
                    if BL_ID_FULL_RE.fullmatch(ref)
                ]
                release_baseline_refs = split_refs(release_row.get("baseline_ref", ""))
                if len(wp_baseline_refs) == 1 and release_baseline_refs != wp_baseline_refs:
                    errors.append(
                        f"02-wbs.md production done {wp_id} REL baseline_ref must match WBS baseline_ref"
                    )
                if clean_cell(release_row.get("status", "")).lower() != "verified":
                    errors.append(f"02-wbs.md production done {wp_id} requires a verified REL")
                if is_none(release_row.get("verified_at", "")):
                    errors.append(f"02-wbs.md production done {wp_id} REL has no verified_at")
                if clean_cell(release_row.get("environment", "")).lower() != "production":
                    errors.append(
                        f"02-wbs.md production done {wp_id} requires REL environment=production"
                    )

    return errors


def discover_packs(root_dir: Path) -> list[tuple[str, Path, list[str]]]:
    """Return (label, directory, required files) for the root pack and every initiative."""
    packs: list[tuple[str, Path, list[str]]] = [("", root_dir, REQUIRED_FILES)]
    initiatives_dir = root_dir / INITIATIVES_DIRNAME
    if initiatives_dir.is_dir():
        for child in sorted(initiatives_dir.iterdir()):
            if child.is_dir() and not child.name.startswith("."):
                label = f"{INITIATIVES_DIRNAME}/{child.name}"
                packs.append((label, child, INITIATIVE_REQUIRED_FILES))
    return packs


def check_across_packs(packs: list[tuple[str, Path, list[str]]]) -> list[str]:
    """wp_id uniqueness, dependency resolution and cycles across every pack."""
    errors: list[str] = []
    owners: dict[str, list[str]] = {}
    graph: dict[str, list[str]] = {}
    dependency_sites: list[tuple[str, str, str, int]] = []

    for label, pack_dir, _ in packs:
        wbs_path = pack_dir / "02-wbs.md"
        if not wbs_path.exists():
            continue
        headers, rows = parse_wbs_rows(wbs_path)
        if "wp_id" not in headers:
            continue
        for line_number, row in rows:
            wp_id = row.get("wp_id", "")
            if not WP_ID_FULL_RE.fullmatch(wp_id):
                continue
            owners.setdefault(wp_id, []).append(
                f"{label + '/' if label else ''}02-wbs.md:{line_number}"
            )
            dependencies = local_dependency_ids(row.get("depends_on", ""))
            graph[wp_id] = dependencies
            for dependency in dependencies:
                dependency_sites.append((label, wp_id, dependency, line_number))

    for wp_id, locations in sorted(owners.items()):
        if len(locations) > 1:
            errors.append(f"duplicate wp_id across packs: {wp_id} ({', '.join(locations)})")

    for label, wp_id, dependency, line_number in dependency_sites:
        if dependency not in owners:
            prefix = f"{label}/" if label else ""
            errors.append(
                f"{prefix}02-wbs.md missing dependency: {wp_id} -> {dependency} (line {line_number})"
            )

    for cycle in find_cycles(graph):
        errors.append(f"02-wbs.md dependency cycle: {' -> '.join(cycle)}")
    return errors


def validate(pack_dir: Path) -> dict[str, object]:
    pack_dir = pack_dir.resolve()
    errors: list[str] = []
    warnings: list[str] = []
    pack_reports: list[dict[str, object]] = []

    if not pack_dir.exists():
        errors.append(f"pack directory does not exist: {pack_dir}")
    elif not pack_dir.is_dir():
        errors.append(f"pack path is not a directory: {pack_dir}")
    else:
        packs = discover_packs(pack_dir)
        for label, directory, required in packs:
            pack_errors: list[str] = []
            pack_warnings: list[str] = []
            schema_version, schema_errors = detect_wbs_schema(directory)
            pack_errors.extend(schema_errors)
            required_for_schema = required + (V2_CONTROL_FILES if schema_version == 2 else [])
            pack_errors.extend(check_required_files(directory, required_for_schema))
            pack_errors.extend(check_brief(directory))
            pack_errors.extend(check_wbs(directory))
            pack_errors.extend(check_wbs_table_integrity(directory))
            pack_errors.extend(check_acceptance(directory))
            if schema_version == 2:
                pack_errors.extend(check_v2(directory))
            else:
                requirement_errors, requirement_warnings = check_requirements(directory)
                pack_errors.extend(requirement_errors)
                pack_warnings.extend(requirement_warnings)
            prefix = f"[{label}] " if label else ""
            errors.extend(f"{prefix}{error}" for error in pack_errors)
            warnings.extend(f"{prefix}{warning}" for warning in pack_warnings)
            pack_reports.append({
                "label": label or ".",
                "dir": str(directory),
                "schema_version": schema_version,
                "valid": not pack_errors,
                "errors": pack_errors,
                "warnings": pack_warnings,
            })
        errors.extend(check_across_packs(packs))

    return {
        "pack_dir": str(pack_dir),
        "packs": pack_reports,
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate an XSOS WBS Pack.")
    parser.add_argument("pack_dir", nargs="?", default="docs/wbs", help="Path to WBS pack directory.")
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    args = parser.parse_args()

    result = validate(Path(args.pack_dir))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif result["valid"]:
        labels = ", ".join(str(pack["label"]) for pack in result["packs"])
        print(f"OK: {result['pack_dir']} (packs: {labels})")
    else:
        print(f"INVALID: {result['pack_dir']}")
        for error in result["errors"]:
            print(f"- {error}")
    if not args.json:
        for warning in result.get("warnings", []):
            print(f"! {warning}")
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
