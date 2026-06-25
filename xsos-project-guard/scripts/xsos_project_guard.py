#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


REQUIRED_FILES = [
    "AGENTS.md",
    "README.md",
    ".env.example",
    "docs/standards/README.md",
    "docs/standards/project-rule.md",
    "docs/change-control.md",
    "docs/sops/core-development-sop.md",
    "docs/wbs/00-brief.md",
    "docs/wbs/01-requirements.md",
    "docs/wbs/02-wbs.md",
    "docs/wbs/03-page-spec.md",
    "docs/wbs/04-api-contract.md",
    "docs/wbs/05-data-contract.md",
    "docs/wbs/06-acceptance.md",
    "docs/wbs/07-risks.md",
    "docs/wbs/08-implementation-rules.md",
    "docs/wbs/10-handoff.md",
    "docs/wbs/CHANGELOG.md",
    "docs/wbs/OWNERS.md",
]

WBS_VALIDATOR = Path("/Users/coldtree/work/gitee/xsos-ai-skills/xsos-wbs-pack/scripts/validate_wbs_pack.py")


TEMPLATES = {
    "AGENTS.md": """# AGENTS.md

## XSOS Project Rules

- Read `docs/standards/README.md` before changing behavior.
- Read `docs/wbs/` before selecting or changing work.
- Use `xsos-wbs-pack` for WBS work.
- Use `xsos-project-guard` before handoff or release.
- Runtime registration uses `module.yaml`; WBS is development spec, not runtime config.
""",
    "README.md": """# XSOS Project

This project follows XSOS delivery control.

Start here:

- `docs/standards/README.md`
- `docs/wbs/`
- `docs/change-control.md`
""",
    ".env.example": """# Copy to .env for local development.

APP_ENV=local
APP_PORT=
""",
    "docs/standards/README.md": """# Project Standards / 项目事实规范

This project reads global standards first:

- `/Users/coldtree/work/gitee/xsos-delivery-control/standards/README.md`

Project-local standards:

- `docs/standards/project-rule.md`
- `docs/change-control.md`
- `docs/sops/core-development-sop.md`
- `docs/wbs/`
""",
    "docs/standards/project-rule.md": """# Project Rule / 项目规则

## Hard Rules

- Do not bypass Auth Center for platform identity.
- Do not bypass Registry for module launch metadata.
- Do not bypass Audit for required operation records.
- Do not treat WBS as runtime configuration.

## Local Overrides

Add project-specific rules here. They must not weaken global XSOS standards.
""",
    "docs/change-control.md": """# Change Control / 变更控制

## Rule

Accepted requirement, API, data, SOP, auth, registry, or audit changes must update:

- `docs/wbs/`
- `docs/wbs/CHANGELOG.md`

## Flow

1. Record the decision or accepted requirement.
2. Update WBS and acceptance.
3. Update implementation rules or SOP if process changed.
4. Add verification evidence before handoff.
""",
    "docs/sops/core-development-sop.md": """# Core Development SOP / 核心开发流程

1. Read `AGENTS.md`.
2. Read `docs/standards/README.md`.
3. Read `docs/wbs/`.
4. Select one work package.
5. Implement with the smallest useful scope.
6. Run relevant tests or smoke checks.
7. Update WBS facts and `CHANGELOG.md` for accepted changes.
8. Run `xsos-project-guard verify`.
9. Hand off with evidence and remaining risks.
""",
    "docs/wbs/00-brief.md": "# Brief / 项目简报\n\nTBD.\n",
    "docs/wbs/01-requirements.md": "# Requirements / 需求\n\nTBD.\n",
    "docs/wbs/02-wbs.md": "# WBS / 工作包\n\nTBD.\n",
    "docs/wbs/03-page-spec.md": "# Page Spec / 页面规格\n\nTBD.\n",
    "docs/wbs/04-api-contract.md": "# API Contract / API 共识\n\nTBD.\n",
    "docs/wbs/05-data-contract.md": "# Data Contract / 数据共识\n\nTBD.\n",
    "docs/wbs/06-acceptance.md": "# Acceptance / 验收标准\n\nTBD.\n",
    "docs/wbs/07-risks.md": "# Risks / 风险\n\nTBD.\n",
    "docs/wbs/08-implementation-rules.md": "# Implementation Rules / 实现规则\n\nTBD.\n",
    "docs/wbs/10-handoff.md": "# Handoff / 交接\n\nTBD.\n",
    "docs/wbs/CHANGELOG.md": "# Changelog / 变更记录\n\n## Unreleased\n\n- Initial scaffold.\n",
    "docs/wbs/OWNERS.md": "# Owners / 负责人\n\n| Area | Owner | Backup |\n|---|---|---|\n| Project | TBD | TBD |\n",
}


@dataclass
class GuardReport:
    status: str
    root: str
    missing_required: list[str]
    warnings: list[str]
    created: list[str]
    validator_status: str | None = None
    validator_output: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "root": self.root,
            "missing_required": self.missing_required,
            "warnings": self.warnings,
            "created": self.created,
            "validator_status": self.validator_status,
            "validator_output": self.validator_output,
        }


def _rel_exists(root: Path, rel_path: str) -> bool:
    return (root / rel_path).exists()


def _read_text(root: Path, rel_path: str) -> str:
    path = root / rel_path
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def audit_project(root: Path | str) -> GuardReport:
    root_path = Path(root).resolve()
    missing = [rel for rel in REQUIRED_FILES if not _rel_exists(root_path, rel)]
    warnings: list[str] = []

    if not _rel_exists(root_path, "module.yaml"):
        warnings.append("module.yaml is absent; required only for runtime modules.")

    standards = _read_text(root_path, "docs/standards/README.md").lower()
    if standards and "xsos-delivery-control" not in standards and "delivery-control" not in standards:
        warnings.append("docs/standards/README.md should reference xsos-delivery-control global standards.")

    change_control = _read_text(root_path, "docs/change-control.md").lower()
    if change_control and "changelog" not in change_control:
        warnings.append("docs/change-control.md should mention CHANGELOG update rules.")

    status = "pass" if not missing else "fail"
    return GuardReport(
        status=status,
        root=str(root_path),
        missing_required=missing,
        warnings=warnings,
        created=[],
    )


def repair_project(root: Path | str) -> GuardReport:
    root_path = Path(root).resolve()
    created: list[str] = []

    for rel_path in REQUIRED_FILES:
        path = root_path / rel_path
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(TEMPLATES.get(rel_path, "# TODO\n"), encoding="utf-8")
        created.append(rel_path)

    report = audit_project(root_path)
    report.status = "repaired" if created else report.status
    report.created = created
    return report


def verify_project(root: Path | str) -> GuardReport:
    root_path = Path(root).resolve()
    report = audit_project(root_path)

    if WBS_VALIDATOR.exists() and (root_path / "docs" / "wbs").exists():
        result = subprocess.run(
            [sys.executable, str(WBS_VALIDATOR), str(root_path / "docs" / "wbs")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        report.validator_status = "pass" if result.returncode == 0 else "fail"
        report.validator_output = result.stdout.strip()
        if result.returncode != 0:
            report.status = "fail"
    else:
        report.validator_status = "skipped"
        report.validator_output = "WBS validator or docs/wbs not found."

    return report


def print_report(report: GuardReport) -> None:
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit, repair, or verify XSOS project standards.")
    parser.add_argument("mode", choices=["audit", "repair", "verify"])
    parser.add_argument("project_root", nargs="?", default=".")
    args = parser.parse_args(argv)

    root = Path(args.project_root)
    if args.mode == "audit":
        report = audit_project(root)
    elif args.mode == "repair":
        report = repair_project(root)
    else:
        report = verify_project(root)

    print_report(report)
    return 0 if report.status in {"pass", "repaired"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
