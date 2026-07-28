#!/usr/bin/env python3
"""Validate an XSOS WBS Pack structure."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


REQUIRED_FILES = [
    "00-brief.md",
    "01-requirements.md",
    "02-wbs.md",
    "03-page-spec.md",
    "04-api-contract.md",
    "05-data-contract.md",
    "06-acceptance.md",
    "07-risks.md",
    "08-implementation-rules.md",
    "CHANGELOG.md",
    "OWNERS.md",
]

ALLOWED_STATUS = {"proposed", "todo", "in_progress", "blocked", "review", "done", "cancelled"}


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text()


def check_required_files(pack_dir: Path) -> list[str]:
    errors: list[str] = []
    for name in REQUIRED_FILES:
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


def parse_wbs_rows(path: Path) -> tuple[list[str], list[tuple[int, dict[str, str]]]]:
    """Parse the first WBS markdown table by column name, not column position."""
    table_lines = [
        (line_number, line)
        for line_number, line in enumerate(read_text(path).splitlines(), start=1)
        if line.strip().startswith("|")
    ]
    if len(table_lines) < 3:
        return [], []
    headers = [header.lower() for header in split_markdown_row(table_lines[0][1])]
    rows: list[tuple[int, dict[str, str]]] = []
    for line_number, line in table_lines[2:]:
        cells = split_markdown_row(line)
        rows.append((line_number, {
            header: cells[index] if index < len(cells) else ""
            for index, header in enumerate(headers)
        }))
    return headers, rows


def local_dependency_ids(value: str) -> list[str]:
    """Only bare dependency tokens are local; qualified tokens are cross-project refs."""
    result: list[str] = []
    for token in value.split(","):
        candidate = token.strip().strip("`")
        if re.fullmatch(r"WP-[A-Z]+-\d{3}", candidate):
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
    path = pack_dir / "02-wbs.md"
    if not path.exists():
        return []
    text = read_text(path)
    errors: list[str] = []
    headers, rows = parse_wbs_rows(path)
    if not rows:
        errors.append("02-wbs.md should contain a Markdown table with at least one work package")
        return errors

    required_headers = ["wp_id", "title_cn", "title_en", "type", "owner", "status", "depends_on", "acceptance_ref"]
    for header in required_headers:
        if header not in headers:
            errors.append(f"02-wbs.md missing required column: {header}")

    if "wp_id" in headers:
        seen_wp_ids: dict[str, list[int]] = {}
        for line_number, row in rows:
            wp_id = row.get("wp_id", "")
            if not re.fullmatch(r"WP-[A-Z]+-\d{3}", wp_id):
                continue
            seen_wp_ids.setdefault(wp_id, []).append(line_number)
        for wp_id, line_numbers in seen_wp_ids.items():
            if len(line_numbers) > 1:
                locations = ", ".join(str(number) for number in line_numbers)
                errors.append(f"02-wbs.md duplicate wp_id: {wp_id} (lines {locations})")

    if "status" in headers:
        for _, row in rows:
            status = row.get("status", "")
            if status and status not in ALLOWED_STATUS:
                errors.append(f"02-wbs.md has invalid status: {status}")

    wp_ids = {row.get("wp_id", "") for _, row in rows}
    graph: dict[str, list[str]] = {}
    for line_number, row in rows:
        wp_id = row.get("wp_id", "")
        if not re.fullmatch(r"WP-[A-Z]+-\d{3}", wp_id):
            continue
        dependencies = local_dependency_ids(row.get("depends_on", ""))
        graph[wp_id] = dependencies
        for dependency in dependencies:
            if dependency not in wp_ids:
                errors.append(
                    f"02-wbs.md missing local dependency: {wp_id} -> {dependency} (line {line_number})"
                )
    for cycle in find_cycles(graph):
        errors.append(f"02-wbs.md dependency cycle: {' -> '.join(cycle)}")

    if not re.search(r"\bWP-[A-Z]+-\d{3}\b", text):
        errors.append("02-wbs.md should contain at least one wp_id like WP-FE-001")
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
    if not re.search(r"\bAC-[A-Z]+-\d{3}\b", text):
        errors.append("06-acceptance.md should contain at least one acceptance id like AC-FE-001")
    if "verification" not in text.lower() and "验收" not in text and "验证" not in text:
        errors.append("06-acceptance.md missing Verification / 验收 instructions")
    return errors


def validate(pack_dir: Path) -> dict[str, object]:
    pack_dir = pack_dir.resolve()
    errors: list[str] = []
    if not pack_dir.exists():
        errors.append(f"pack directory does not exist: {pack_dir}")
    elif not pack_dir.is_dir():
        errors.append(f"pack path is not a directory: {pack_dir}")
    else:
        errors.extend(check_required_files(pack_dir))
        errors.extend(check_brief(pack_dir))
        errors.extend(check_wbs(pack_dir))
        errors.extend(check_acceptance(pack_dir))

    return {
        "pack_dir": str(pack_dir),
        "valid": not errors,
        "errors": errors,
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
        print(f"OK: {result['pack_dir']}")
    else:
        print(f"INVALID: {result['pack_dir']}")
        for error in result["errors"]:
            print(f"- {error}")
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
