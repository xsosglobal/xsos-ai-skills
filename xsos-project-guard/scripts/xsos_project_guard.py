#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


DEFAULT_DELIVERY_CONTROL_ROOT = Path(
    os.environ.get("XSOS_DELIVERY_CONTROL_ROOT", "/Users/coldtree/work/gitee/xsos-delivery-control")
)
REQUIRED_FILES_MANIFEST = Path("templates/project-scaffold/required-files.json")
WBS_VALIDATOR = Path("/Users/coldtree/work/gitee/xsos-ai-skills/xsos-wbs-pack/scripts/validate_wbs_pack.py")


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


@dataclass(frozen=True)
class RequiredFile:
    path: str
    template: str | None = None


def resolve_delivery_control_root(delivery_control_root: Path | str | None = None) -> Path:
    return Path(delivery_control_root).resolve() if delivery_control_root else DEFAULT_DELIVERY_CONTROL_ROOT.resolve()


def load_required_files(delivery_control_root: Path | str | None = None) -> list[RequiredFile]:
    root = resolve_delivery_control_root(delivery_control_root)
    manifest_path = root / REQUIRED_FILES_MANIFEST
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    files: list[RequiredFile] = []
    for item in raw:
        if not isinstance(item, dict) or not item.get("path"):
            raise ValueError(f"Invalid required file spec in {manifest_path}: {item!r}")
        files.append(RequiredFile(path=str(item["path"]), template=item.get("template")))
    return files


def load_template(delivery_control_root: Path | str | None, spec: RequiredFile) -> str:
    if not spec.template:
        return "# TODO\n"
    root = resolve_delivery_control_root(delivery_control_root)
    template_path = root / spec.template
    return template_path.read_text(encoding="utf-8")


def _rel_exists(root: Path, rel_path: str) -> bool:
    return (root / rel_path).exists()


def _read_text(root: Path, rel_path: str) -> str:
    path = root / rel_path
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def audit_project(root: Path | str, delivery_control_root: Path | str | None = None) -> GuardReport:
    root_path = Path(root).resolve()
    required_files = load_required_files(delivery_control_root)
    missing = [spec.path for spec in required_files if not _rel_exists(root_path, spec.path)]
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


def repair_project(root: Path | str, delivery_control_root: Path | str | None = None) -> GuardReport:
    root_path = Path(root).resolve()
    created: list[str] = []

    for spec in load_required_files(delivery_control_root):
        rel_path = spec.path
        path = root_path / rel_path
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(load_template(delivery_control_root, spec), encoding="utf-8")
        created.append(rel_path)

    report = audit_project(root_path, delivery_control_root=delivery_control_root)
    report.status = "repaired" if created else report.status
    report.created = created
    return report


def verify_project(root: Path | str, delivery_control_root: Path | str | None = None) -> GuardReport:
    root_path = Path(root).resolve()
    report = audit_project(root_path, delivery_control_root=delivery_control_root)

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
    parser.add_argument("--delivery-control-root", default=None)
    args = parser.parse_args(argv)

    root = Path(args.project_root)
    if args.mode == "audit":
        report = audit_project(root, delivery_control_root=args.delivery_control_root)
    elif args.mode == "repair":
        report = repair_project(root, delivery_control_root=args.delivery_control_root)
    else:
        report = verify_project(root, delivery_control_root=args.delivery_control_root)

    print_report(report)
    return 0 if report.status in {"pass", "repaired"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
