---
name: xsos-project-guard
description: Use when auditing, standardizing, repairing, or verifying an XSOS project against delivery-control, WBS, standards, SOP, change-control, module.yaml, README, OWNERS, or CHANGELOG requirements.
---

# XSOS Project Guard

## Purpose

Keep an XSOS project compliant with the shared delivery-control baseline.

This skill checks project structure, facts, WBS pack, SOP, change-control, and runtime registration boundaries.

Rule and template source is `xsos-delivery-control`. This skill is only the executable guard.

## Single Authoritative Source

- Rules and templates are read **online** from `xsosglobal/xsos-delivery-control` on `main`, through `gh api`. That is the only authority.
- A local clone of `xsos-delivery-control` is never consulted by default and never used as a fallback. A stale clone would be a second authority.
- Prerequisite: GitHub CLI installed and `gh auth login` done with an account that belongs to the `xsosglobal` organization (the repository is private; an account without access gets HTTP 404).
- If the online source cannot be read (not logged in, no access, offline), the command fails with exit code 2. Fix access; do not point it at a local copy to get around the error.
- `--delivery-control-root <dir>` exists only for tests and offline troubleshooting. Its output is marked `使用本机副本，非权威源` and must not be treated as compliance evidence.
- `XSOS_DELIVERY_CONTROL_REPO` / `XSOS_DELIVERY_CONTROL_REF` override `owner/repo` and ref (default `main`), for testing a rules change before it merges. `XSOS_DELIVERY_CONTROL_ROOT` is no longer read.

## Hard Boundary

- `docs/wbs/` is the development spec and work package pack.
- `module.yaml` is runtime registration input.
- Do not mix them.
- Do not mark a project compliant if required standard files are missing.

## Workflow

1. Read project `AGENTS.md` if present.
2. Read project `docs/standards/README.md` if present.
3. Read global rules online, never from a local clone:

```bash
python3 <xsos-project-guard-dir>/scripts/xsos_project_guard.py rule standards/README.md
python3 <xsos-project-guard-dir>/scripts/xsos_project_guard.py rule rules/wbs-rule.md --lang en
```

`rule` prints the file from `main`. For bilingual rule files (`<!-- xsos-rule:zh -->` / `<!-- xsos-rule:en -->`) it validates the same format Xuanshu enforces and prints the requested block.

4. Run audit first. Audit only needs the required-file list in this skill, so it works offline and in CI:

```bash
python3 <xsos-project-guard-dir>/scripts/xsos_project_guard.py audit <project-root>
```

5. Check against the online templates (read-only; exit 1 when files are missing or a listed template is gone from `main`):

```bash
python3 <xsos-project-guard-dir>/scripts/xsos_project_guard.py sync <project-root> --check
```

6. If the user asks to fix standards, create the missing files from the online templates (`repair` is the old name of the same command):

```bash
python3 <xsos-project-guard-dir>/scripts/xsos_project_guard.py sync <project-root>
```

`sync` only creates missing required files. Templates are starting scaffolds owned by the project once created, so existing files are never compared, merged or overwritten.

7. Before handoff or release, run verify:

```bash
python3 <xsos-project-guard-dir>/scripts/xsos_project_guard.py verify <project-root>
```

## What To Check

- Required files from `<delivery-control-root>/templates/project-scaffold/required-files.json`
- `module.yaml` for runtime modules

## Rules

- Audit before edits.
- Sync/repair only creates missing scaffold files from the online `xsos-delivery-control` templates.
- Do not add long-lived standards directly inside this skill.
- Do not rewrite business requirements unless the user asks.
- If process changed, update SOP.
- If accepted requirement changed, update WBS and CHANGELOG.
- If module launch/auth/audit shape changed, update API/data contract and acceptance.

## Output

Return:

- compliance status
- missing files
- warnings
- created files if sync ran
- source (`github:xsosglobal/xsos-delivery-control@main`, or a local copy marked non-authoritative)
- verification commands and result
