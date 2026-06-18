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


def check_wbs(pack_dir: Path) -> list[str]:
    path = pack_dir / "02-wbs.md"
    if not path.exists():
        return []
    text = read_text(path)
    errors: list[str] = []
    lines = [line for line in text.splitlines() if line.strip().startswith("|")]
    if len(lines) < 3:
        errors.append("02-wbs.md should contain a Markdown table with at least one work package")
        return errors

    headers = [h.lower() for h in split_markdown_row(lines[0])]
    required_headers = ["wp_id", "title_cn", "title_en", "type", "owner", "status", "depends_on", "acceptance_ref"]
    for header in required_headers:
        if header not in headers:
            errors.append(f"02-wbs.md missing required column: {header}")

    if "status" in headers:
        status_idx = headers.index("status")
        for line in lines[2:]:
            cells = split_markdown_row(line)
            if len(cells) <= status_idx:
                continue
            status = cells[status_idx]
            if status and status not in ALLOWED_STATUS:
                errors.append(f"02-wbs.md has invalid status: {status}")

    if not re.search(r"\bWP-[A-Z]+-\d{3}\b", text):
        errors.append("02-wbs.md should contain at least one wp_id like WP-FE-001")
    return errors


def check_acceptance(pack_dir: Path) -> list[str]:
    path = pack_dir / "06-acceptance.md"
    if not path.exists():
        return []
    text = read_text(path)
    errors: list[str] = []
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
