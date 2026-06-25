---
name: xsos-project-guard
description: Use when auditing, standardizing, repairing, or verifying an XSOS project against delivery-control, WBS, standards, SOP, change-control, module.yaml, README, OWNERS, or CHANGELOG requirements.
---

# XSOS Project Guard

## Purpose

Keep an XSOS project compliant with the shared delivery-control baseline.

This skill checks project structure, facts, WBS pack, SOP, change-control, and runtime registration boundaries.

Rule and template source is `xsos-delivery-control`. This skill is only the executable guard.

## Hard Boundary

- `docs/wbs/` is the development spec and work package pack.
- `module.yaml` is runtime registration input.
- Do not mix them.
- Do not mark a project compliant if required standard files are missing.

## Workflow

1. Read project `AGENTS.md` if present.
2. Read project `docs/standards/README.md` if present.
3. Read global standards from `/Users/coldtree/work/gitee/xsos-delivery-control/standards/README.md` if present.
4. Run audit first:

```bash
python3 /Users/coldtree/work/gitee/xsos-ai-skills/xsos-project-guard/scripts/xsos_project_guard.py audit <project-root>
```

5. If the user asks to fix standards, run repair:

```bash
python3 /Users/coldtree/work/gitee/xsos-ai-skills/xsos-project-guard/scripts/xsos_project_guard.py repair <project-root>
```

6. Before handoff or release, run verify:

```bash
python3 /Users/coldtree/work/gitee/xsos-ai-skills/xsos-project-guard/scripts/xsos_project_guard.py verify <project-root>
```

## What To Check

- Required files from `/Users/coldtree/work/gitee/xsos-delivery-control/templates/project-scaffold/required-files.json`
- `module.yaml` for runtime modules

## Rules

- Audit before edits.
- Repair only missing scaffold files from `xsos-delivery-control` templates.
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
- created files if repair ran
- verification commands and result
