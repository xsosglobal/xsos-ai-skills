#!/usr/bin/env python3
"""Validate and build a traceable XSOS task Context Pack."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ContextError(Exception):
    pass


@dataclass
class Resolution:
    project_root: Path
    context_root: Path
    work_package: dict[str, str]
    acceptance: dict[str, str]
    scenario: dict[str, Any]
    baseline: dict[str, Any]
    capabilities: list[dict[str, Any]]
    sources: list[dict[str, str]]
    repository_revisions: dict[str, str]


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ContextError(f"missing file: {path}")
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ContextError(f"invalid YAML {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContextError(f"YAML root must be a mapping: {path}")
    return value


def load_catalog(root: Path, kind: str) -> dict[str, tuple[dict[str, Any], Path]]:
    folder = root / kind
    if not folder.is_dir():
        raise ContextError(f"missing context folder: {folder}")
    catalog: dict[str, tuple[dict[str, Any], Path]] = {}
    for path in sorted([*folder.glob("*.yaml"), *folder.glob("*.yml")]):
        item = load_yaml(path)
        item_id = str(item.get("id", "")).strip()
        if not item_id:
            raise ContextError(f"missing id: {path}")
        if item_id in catalog:
            raise ContextError(f"duplicate {kind} id: {item_id}")
        catalog[item_id] = (item, path)
    return catalog


def parse_work_packages(path: Path) -> dict[str, dict[str, str]]:
    if not path.is_file():
        raise ContextError(f"missing WBS file: {path}")
    result: dict[str, dict[str, str]] = {}
    aliases = {
        "id": "id", "wp_id": "id", "cn": "title_cn", "title_cn": "title_cn",
        "en": "title_en", "title_en": "title_en", "type": "type", "owner": "owner",
        "status": "status", "depends": "depends_on", "depends_on": "depends_on",
        "ac": "acceptance", "acceptance_ref": "acceptance", "outputs": "outputs",
    }
    headers: list[str] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.split("|")[1:-1]]
        normalized = [cell.lower() for cell in cells]
        if "wp_id" in normalized or normalized[:1] == ["id"]:
            headers = [aliases.get(name, name) for name in normalized]
            continue
        if not cells or not re.fullmatch(r"WP-[A-Z]+-\d{3}", cells[0]):
            continue
        if headers is None:
            raise ContextError(f"WBS table header not found before {cells[0]}")
        item = {name: cells[index] if index < len(cells) else "" for index, name in enumerate(headers)}
        for required in ("id", "title_cn", "title_en", "type", "owner", "status", "depends_on", "acceptance", "outputs"):
            item.setdefault(required, "")
        if item["id"] in result:
            raise ContextError(f"duplicate WBS id: {item['id']}")
        result[item["id"]] = item
    return result


def parse_acceptance(path: Path) -> dict[str, dict[str, str]]:
    if not path.is_file():
        raise ContextError(f"missing acceptance file: {path}")
    lines = path.read_text(encoding="utf-8").splitlines()
    result: dict[str, dict[str, str]] = {}
    current_id: str | None = None
    current_title = ""
    body: list[str] = []
    for line in lines + ["## EOF"]:
        match = re.match(r"^##\s+(AC-[A-Z0-9-]+):?\s*(.*)$", line)
        if match or line == "## EOF":
            if current_id:
                if current_id in result:
                    raise ContextError(f"duplicate acceptance id: {current_id}")
                result[current_id] = {"id": current_id, "title": current_title, "body": "\n".join(body).strip()}
            if line == "## EOF":
                break
            current_id, current_title, body = match.group(1), match.group(2).strip(), []
        elif current_id:
            body.append(line)
    return result


def version_map(value: Any, field: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ContextError(f"baseline {field} must be a mapping")
    return {str(key): str(version) for key, version in value.items()}


def participant_id(value: Any) -> tuple[str, str | None]:
    if isinstance(value, str):
        return value, None
    if isinstance(value, dict):
        return str(value.get("capability_id", "")).strip(), str(value.get("required_version", "")).strip() or None
    return "", None


def require_fields(item: dict[str, Any], fields: list[str], label: str) -> None:
    missing = [field for field in fields if not item.get(field)]
    if missing:
        raise ContextError(f"{label} missing required fields: {', '.join(missing)}")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


SENSITIVE_PARTS = {".env", "secrets", "secret", "credentials", "tokens", "token"}


def parse_repo_roots(project_root: Path, values: list[str] | None) -> dict[str, Path]:
    roots = {"project": project_root}
    for value in values or []:
        if "=" not in value:
            raise ContextError(f"repository root must be alias=path: {value}")
        alias, raw_path = value.split("=", 1)
        alias = alias.strip()
        if not re.fullmatch(r"[a-zA-Z0-9._-]+", alias) or alias == "project":
            raise ContextError(f"invalid or reserved repository alias: {alias}")
        root = Path(raw_path).expanduser().resolve()
        if not root.is_dir():
            raise ContextError(f"missing repository root {alias}: {root}")
        roots[alias] = root
    return roots


def parse_source_ref(value: Any, default_repo: str = "project") -> tuple[str, str]:
    if isinstance(value, str):
        if ":" in value:
            candidate_repo, candidate_path = value.split(":", 1)
            if re.fullmatch(r"[a-zA-Z0-9._-]+", candidate_repo):
                return candidate_repo, candidate_path
        return default_repo, value
    if isinstance(value, dict):
        return str(value.get("repo", default_repo)).strip(), str(value.get("path", "")).strip()
    raise ContextError(f"invalid source reference: {value!r}")


def safe_source_path(repo_roots: dict[str, Path], repo: str, relative: str) -> Path:
    if repo not in repo_roots:
        raise ContextError(f"unknown repository alias: {repo}")
    if not relative or Path(relative).is_absolute():
        raise ContextError(f"source path must be relative: {repo}:{relative}")
    parts = Path(relative).parts
    if ".." in parts:
        raise ContextError(f"source path escapes repository: {repo}:{relative}")
    if {part.lower() for part in parts} & SENSITIVE_PARTS or any(part.lower().startswith(".env") for part in parts):
        raise ContextError(f"sensitive source is forbidden: {repo}:{relative}")
    root = repo_roots[repo]
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ContextError(f"source path escapes repository: {repo}:{relative}") from exc
    return path


def safe_context_path(context_root: Path, relative: str) -> Path:
    if not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ContextError(f"context path escapes repository: {relative}")
    path = (context_root / relative).resolve()
    try:
        path.relative_to(context_root)
    except ValueError as exc:
        raise ContextError(f"context path escapes repository: {relative}") from exc
    return path


def git_revision(root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True, capture_output=True, check=False
    )
    if result.returncode != 0:
        raise ContextError(f"formal baseline repository is not git-backed: {root}")
    return result.stdout.strip()


def assert_clean_repository(root: Path, alias: str) -> None:
    result = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain"], text=True, capture_output=True, check=False
    )
    if result.returncode != 0:
        raise ContextError(f"formal baseline repository is not git-backed: {root}")
    if result.stdout.strip():
        raise ContextError(f"formal baseline repository is dirty: {alias}")


def add_source(
    sources: dict[str, dict[str, str]], repo_roots: dict[str, Path], repo: str, relative: str, owner: str
) -> None:
    path = safe_source_path(repo_roots, repo, relative)
    if path.is_file():
        key = f"{repo}:{relative}"
        sources[key] = {
            "repo": repo,
            "relative_path": relative,
            "path": str(path),
            "owner": owner,
            "sha256": sha256(path),
        }


def resolve(args: argparse.Namespace) -> Resolution:
    project_root = Path(args.project_root).expanduser().resolve()
    context_root = Path(args.context_root).expanduser().resolve()
    if not project_root.is_dir():
        raise ContextError(f"missing project root: {project_root}")
    repo_roots = parse_repo_roots(project_root, getattr(args, "repo", None))

    work_packages = parse_work_packages(project_root / "docs/wbs/02-wbs.md")
    acceptances = parse_acceptance(project_root / "docs/wbs/06-acceptance.md")
    if args.wp not in work_packages:
        raise ContextError(f"work package not found: {args.wp}")
    work_package = work_packages[args.wp]
    acceptance_id = work_package.get("acceptance", "").strip()
    if not acceptance_id:
        raise ContextError(f"work package has no acceptance reference: {args.wp}")
    if acceptance_id not in acceptances:
        raise ContextError(f"acceptance criterion not found: {acceptance_id}")

    scenarios = load_catalog(context_root, "scenarios")
    capabilities = load_catalog(context_root, "capabilities")
    baselines = load_catalog(context_root, "baselines")
    if args.scenario not in scenarios:
        raise ContextError(f"scenario not found: {args.scenario}")
    if args.baseline not in baselines:
        raise ContextError(f"baseline not found: {args.baseline}")
    scenario, scenario_path = scenarios[args.scenario]
    baseline, baseline_path = baselines[args.baseline]

    require_fields(scenario, ["id", "version", "status", "owner", "goal", "participants"], "scenario")
    require_fields(baseline, ["id", "status", "approved_by", "approved_at", "scenario_versions", "capability_versions"], "baseline")
    if scenario["status"] != "accepted":
        raise ContextError(f"scenario is not accepted: {scenario['id']}")
    if baseline["status"] != "active":
        raise ContextError(f"baseline is not active: {baseline['id']}")
    formal = baseline.get("mode", "draft") == "formal"
    if formal and not baseline.get("approval_ref"):
        raise ContextError("formal baseline missing approval_ref")

    scenario_versions = version_map(baseline["scenario_versions"], "scenario_versions")
    capability_versions = version_map(baseline["capability_versions"], "capability_versions")
    pinned_scenario = scenario_versions.get(args.scenario)
    if pinned_scenario != str(scenario["version"]):
        raise ContextError(f"scenario version mismatch: baseline={pinned_scenario or 'missing'} actual={scenario['version']}")

    resolved_capabilities: list[dict[str, Any]] = []
    sources: dict[str, dict[str, str]] = {}
    add_source(sources, repo_roots, "project", "AGENTS.md", "project")
    for relative in ["docs/wbs/00-brief.md", "docs/wbs/02-wbs.md", "docs/wbs/06-acceptance.md"]:
        path = safe_source_path(repo_roots, "project", relative)
        if not path.is_file():
            raise ContextError(f"missing project source: {relative}")
        add_source(sources, repo_roots, "project", relative, "project")
    sources[f"business-context:scenarios/{scenario_path.name}"] = {
        "repo": "business-context", "relative_path": f"scenarios/{scenario_path.name}",
        "path": str(scenario_path.resolve()), "owner": "business-context", "sha256": sha256(scenario_path),
    }
    sources[f"business-context:baselines/{baseline_path.name}"] = {
        "repo": "business-context", "relative_path": f"baselines/{baseline_path.name}",
        "path": str(baseline_path.resolve()), "owner": "business-context", "sha256": sha256(baseline_path),
    }
    if formal:
        approval_relative = str(baseline["approval_ref"])
        approval_path = safe_context_path(context_root, approval_relative)
        if not approval_path.is_file():
            raise ContextError(f"formal baseline approval evidence not found: {approval_relative}")
        sources[f"business-context:{approval_relative}"] = {
            "repo": "business-context", "relative_path": approval_relative,
            "path": str(approval_path), "owner": "human-approval", "sha256": sha256(approval_path),
        }

    participants = scenario.get("participants")
    if not isinstance(participants, list) or not participants:
        raise ContextError("scenario participants must be a non-empty list")
    for participant in participants:
        capability_id, required_version = participant_id(participant)
        if not capability_id:
            raise ContextError("scenario participant missing capability_id")
        if capability_id not in capabilities:
            raise ContextError(f"capability not found: {capability_id}")
        capability, capability_path = capabilities[capability_id]
        require_fields(capability, ["id", "version", "status", "domain", "owner"], f"capability {capability_id}")
        if capability["status"] != "active":
            raise ContextError(f"capability is not active: {capability_id}")
        actual_version = str(capability["version"])
        pinned_version = capability_versions.get(capability_id)
        if pinned_version != actual_version:
            raise ContextError(f"capability version mismatch {capability_id}: baseline={pinned_version or 'missing'} actual={actual_version}")
        if required_version and required_version != actual_version:
            raise ContextError(f"scenario requires {capability_id}@{required_version}, actual={actual_version}")
        resolved_capabilities.append(capability)
        sources[f"business-context:capabilities/{capability_path.name}"] = {
            "repo": "business-context", "relative_path": f"capabilities/{capability_path.name}",
            "path": str(capability_path.resolve()), "owner": "domain", "sha256": sha256(capability_path),
        }

        default_repo = str(capability.get("repository", "project"))
        for source_ref in [*(capability.get("contract_refs") or []), *(capability.get("source_refs") or [])]:
            repo, relative = parse_source_ref(source_ref, default_repo)
            path = safe_source_path(repo_roots, repo, relative)
            if not path.is_file():
                raise ContextError(f"missing capability source {capability_id}: {repo}:{relative}")
            add_source(sources, repo_roots, repo, relative, "domain")

    for source_ref in scenario.get("source_refs") or []:
        repo, relative = parse_source_ref(source_ref)
        path = safe_source_path(repo_roots, repo, relative)
        if not path.is_file():
            raise ContextError(f"missing scenario source: {repo}:{relative}")
        add_source(sources, repo_roots, repo, relative, "business-scenario")

    source_hashes = baseline.get("source_hashes") or {}
    if not isinstance(source_hashes, dict):
        raise ContextError("baseline source_hashes must be a mapping")
    for source_ref, expected in source_hashes.items():
        repo, relative = parse_source_ref(str(source_ref))
        path = safe_source_path(repo_roots, repo, relative)
        if not path.is_file():
            raise ContextError(f"baseline source missing: {repo}:{relative}")
        actual = sha256(path)
        if actual != str(expected):
            raise ContextError(f"source hash drift: {repo}:{relative} expected={expected} actual={actual}")
        add_source(sources, repo_roots, repo, relative, "baseline")

    repository_revisions: dict[str, str] = {}
    if formal:
        pinned_revisions = baseline.get("repository_revisions")
        if not isinstance(pinned_revisions, dict):
            raise ContextError("formal baseline repository_revisions must be a mapping")
        used_repositories = {item["repo"] for item in sources.values() if item["repo"] != "business-context"}
        for repo in sorted(used_repositories):
            expected = str(pinned_revisions.get(repo, ""))
            if not expected:
                raise ContextError(f"formal baseline missing repository revision: {repo}")
            assert_clean_repository(repo_roots[repo], repo)
            actual = git_revision(repo_roots[repo])
            if actual != expected:
                raise ContextError(f"repository revision drift: {repo} expected={expected} actual={actual}")
            repository_revisions[repo] = actual

    return Resolution(
        project_root=project_root,
        context_root=context_root,
        work_package=work_package,
        acceptance=acceptances[acceptance_id],
        scenario=scenario,
        baseline=baseline,
        capabilities=resolved_capabilities,
        sources=sorted(sources.values(), key=lambda item: item["path"]),
        repository_revisions=repository_revisions,
    )


def render_markdown(resolution: Resolution) -> str:
    wp = resolution.work_package
    scenario = resolution.scenario
    baseline = resolution.baseline
    lines = [
        "# XSOS Task Context Pack",
        "",
        "## Resolution",
        "",
        f"- Project: `{resolution.project_root.name}`",
        f"- WBS: `{wp['id']}`",
        f"- Scenario: `{scenario['id']}@{scenario['version']}`",
        f"- Baseline: `{baseline['id']}`",
        f"- Approved by: `{baseline['approved_by']}` at `{baseline['approved_at']}`",
        f"- Approval evidence: `{baseline.get('approval_ref', '-')}`",
        "",
        "## Task",
        "",
        f"- Title: {wp['title_cn'] or wp['title_en']}",
        f"- Owner: `{wp['owner']}`",
        f"- Status: `{wp['status']}`",
        f"- Depends on: `{wp['depends_on'] or '-'}`",
        f"- Outputs: {wp['outputs'] or '-'}",
        "",
        f"## Acceptance `{resolution.acceptance['id']}`",
        "",
        resolution.acceptance["title"],
        "",
        resolution.acceptance["body"] or "- No acceptance body.",
        "",
        "## Business Scenario",
        "",
        f"- Goal: {scenario['goal']}",
        f"- Trigger: {scenario.get('trigger', '-')}",
        f"- Outcome: {scenario.get('outcome', '-')}",
        "",
        "### Steps",
        "",
    ]
    lines.extend([f"{index}. {step}" for index, step in enumerate(scenario.get("steps") or [], 1)] or ["- Not declared."])
    lines.extend(["", "## Resolved Capabilities", ""])
    for capability in resolution.capabilities:
        lines.extend([
            f"### `{capability['id']}@{capability['version']}`",
            "",
            f"- Domain: `{capability['domain']}`",
            f"- Owner: `{capability['owner']}`",
            f"- Description: {capability.get('description', '-')}",
            f"- Contracts: {', '.join(f'`{item}`' for item in capability.get('contract_refs') or []) or '-'}",
            "",
        ])
    if resolution.repository_revisions:
        lines.extend(["## Repository Revisions", ""])
        for repo, revision in sorted(resolution.repository_revisions.items()):
            lines.append(f"- `{repo}`: `{revision}`")
        lines.append("")
    lines.extend(["## Source Evidence", "", "| owner | repository | path | sha256 |", "|---|---|---|---|"])
    for source in resolution.sources:
        lines.append(
            f"| {source['owner']} | `{source['repo']}` | `{source['relative_path']}` | `{source['sha256']}` |"
        )
    lines.extend(["", "> Generated artifact. Regenerate after any source change; do not edit as a fact source.", ""])
    return "\n".join(lines)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)
    for command in ("validate", "build"):
        item = sub.add_parser(command)
        item.add_argument("--project-root", required=True)
        item.add_argument("--wp", required=True)
        item.add_argument("--context-root", required=True)
        item.add_argument("--scenario", required=True)
        item.add_argument("--baseline", required=True)
        item.add_argument("--repo", action="append", default=[], help="Additional repository root as alias=path")
        if command == "build":
            item.add_argument("--output", required=True)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        resolution = resolve(args)
        payload = {
            "status": "pass",
            "work_package": resolution.work_package["id"],
            "scenario": f"{resolution.scenario['id']}@{resolution.scenario['version']}",
            "baseline": resolution.baseline["id"],
            "capabilities": [f"{item['id']}@{item['version']}" for item in resolution.capabilities],
            "sources": len(resolution.sources),
            "repository_revisions": resolution.repository_revisions,
        }
        if args.command == "build":
            output = Path(args.output).expanduser().resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(render_markdown(resolution), encoding="utf-8")
            payload["output"] = str(output)
            payload["output_sha256"] = sha256(output)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except ContextError as exc:
        print(json.dumps({"status": "fail", "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
