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

ALLOWED_STATUS = {"proposed", "todo", "in_progress", "blocked", "review", "done", "cancelled"}

WP_ID = r"WP-[A-Z0-9]+(?:-[A-Z0-9]+)?-\d{3}"
AC_ID = r"AC-[A-Z0-9]+(?:-[A-Z0-9]+)?-\d{3}"
WP_ID_RE = re.compile(WP_ID)
WP_ID_FULL_RE = re.compile(rf"^{WP_ID}$")


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text()


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


def parse_wbs_rows(path: Path) -> tuple[list[str], list[tuple[int, dict[str, str]]]]:
    """Parse the work-package table by column name, not column position.

    A pack file may hold more than one Markdown table (an initiative index, a
    legend); the work-package table is the first one carrying a ``wp_id``
    column. Falls back to the first table so a pack that genuinely lacks the
    column still reports the missing-column error.
    """
    tables: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = []
    for line_number, line in enumerate(read_text(path).splitlines(), start=1):
        if line.strip().startswith("|"):
            current.append((line_number, line))
        elif current:
            tables.append(current)
            current = []
    if current:
        tables.append(current)

    candidates = [table for table in tables if len(table) >= 3]
    if not candidates:
        return [], []
    table = next(
        (t for t in candidates if "wp_id" in [h.lower() for h in split_markdown_row(t[0][1])]),
        candidates[0],
    )

    headers = [header.lower() for header in split_markdown_row(table[0][1])]
    rows: list[tuple[int, dict[str, str]]] = []
    for line_number, line in table[2:]:
        cells = split_markdown_row(line)
        rows.append((line_number, {
            header: cells[index] if index < len(cells) else ""
            for index, header in enumerate(headers)
        }))
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
    if not rows:
        errors.append("02-wbs.md should contain a Markdown table with at least one work package")
        return errors

    required_headers = ["wp_id", "title_cn", "title_en", "type", "owner", "status", "depends_on", "acceptance_ref"]
    for header in required_headers:
        if header not in headers:
            errors.append(f"02-wbs.md missing required column: {header}")

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
        errors.append("06-acceptance.md should contain at least one acceptance id like AC-FE-001")
    if "verification" not in text.lower() and "验收" not in text and "验证" not in text:
        errors.append("06-acceptance.md missing Verification / 验收 instructions")
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
    pack_reports: list[dict[str, object]] = []

    if not pack_dir.exists():
        errors.append(f"pack directory does not exist: {pack_dir}")
    elif not pack_dir.is_dir():
        errors.append(f"pack path is not a directory: {pack_dir}")
    else:
        packs = discover_packs(pack_dir)
        for label, directory, required in packs:
            pack_errors: list[str] = []
            pack_errors.extend(check_required_files(directory, required))
            pack_errors.extend(check_brief(directory))
            pack_errors.extend(check_wbs(directory))
            pack_errors.extend(check_acceptance(directory))
            prefix = f"[{label}] " if label else ""
            errors.extend(f"{prefix}{error}" for error in pack_errors)
            pack_reports.append({
                "label": label or ".",
                "dir": str(directory),
                "valid": not pack_errors,
                "errors": pack_errors,
            })
        errors.extend(check_across_packs(packs))

    return {
        "pack_dir": str(pack_dir),
        "packs": pack_reports,
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
        labels = ", ".join(str(pack["label"]) for pack in result["packs"])
        print(f"OK: {result['pack_dir']} (packs: {labels})")
    else:
        print(f"INVALID: {result['pack_dir']}")
        for error in result["errors"]:
            print(f"- {error}")
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
