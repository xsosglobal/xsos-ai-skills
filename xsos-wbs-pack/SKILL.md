---
name: xsos-wbs-pack
description: Read, validate, create, or execute XSOS bilingual WBS Packs. Use when working with docs/wbs, work packages, requirements, page specs, API contracts, data contracts, acceptance criteria, CHANGELOG, OWNERS, AI-driven development handoffs, or module task execution for XSOS projects.
---

# XSOS WBS Pack

## Overview

Use this skill to make AI agents read and execute XSOS project work from a standard WBS Pack.

WBS Pack is the source of truth. This skill only defines how to read it, validate it, and execute a requested work package.

## Core Rules

1. Read the WBS Pack before coding.
2. Treat `docs/wbs` as the default pack location unless the user gives another path.
3. Do not treat chat history as stronger than the pack. If they conflict, report the conflict.
4. Do not expand scope beyond the selected work package.
5. Do not implement a task without clear acceptance criteria.
6. Keep Chinese and English together in the same files. Do not split `*-cn.md` and `*-en.md`.
7. When implementation changes behavior, update `02-wbs.md` status and `CHANGELOG.md`.
8. Let the project owner manage their own WBS. Escalate only cross-project, platform-rule, security, data-contract, or shared-interface changes.

## Required Read Order

For any execution task:

1. Read `00-brief.md`.
2. Read `02-wbs.md`.
3. Find the requested `wp_id`.
4. Read `06-acceptance.md`.
5. Read task-specific files:
   - Frontend: `03-page-spec.md`, `04-api-contract.md`, `08-implementation-rules.md`
   - Backend: `04-api-contract.md`, `05-data-contract.md`, `08-implementation-rules.md`
   - Test/QA: `06-acceptance.md`, `07-risks.md`
   - Documentation: `00-brief.md`, `01-requirements.md`, `CHANGELOG.md`
6. Check `Non-goals / 非目标`, dependencies, owner, and acceptance references.
7. Execute only the selected work package.
8. Verify acceptance.
9. Update `02-wbs.md` and `CHANGELOG.md` if files were changed.

If a required file is missing, stop and create or request the missing pack file before implementing.

## Work Package Fields

Each row or block in `02-wbs.md` should expose these fields:

- `wp_id`
- `title_cn`
- `title_en`
- `type`
- `owner`
- `status`
- `depends_on`
- `scope`
- `non_goals`
- `acceptance_ref`
- `outputs`

Allowed status values:

- `proposed`
- `todo`
- `in_progress`
- `blocked`
- `review`
- `done`
- `cancelled`

## Adding Work Packages

When adding a work package:

1. If the requester is the project owner, module owner, or tech owner in `OWNERS.md`, they may add approved work directly as `todo`.
2. If the requester is not an owner, or the work changes cross-project contracts, platform rules, security, data models, shared APIs, or integration boundaries, add it as `proposed`.
3. Do not execute `proposed` work packages until an owner changes them to `todo`.
4. Every new work package must include `acceptance_ref`, `depends_on`, and `outputs`.
5. Every new work package must add or reference acceptance criteria in `06-acceptance.md`.
6. Record the reason in `CHANGELOG.md`.

Use this default:

```text
Owner-owned project change -> status=todo
Cross-boundary/platform-risk change -> status=proposed
```

## Bilingual Format

Use Chinese for business clarity and English for machine-readable structure.

Preferred style:

```md
## 项目目标 / Goal

建设 XSOS Portal 前端 V1。

Build XSOS Portal frontend V1.
```

For tables, keep field names in English and values bilingual when useful.

## Creating A New WBS Pack

When asked to create a pack:

1. Read `references/wbs-pack-schema.md`.
2. Create `docs/wbs/` if it does not exist.
3. Create the required files with concise content.
4. Use stable IDs:
   - Work package: `WP-FE-001`, `WP-BE-001`, `WP-QA-001`
   - Acceptance: `AC-FE-001`, `AC-BE-001`
   - Risk: `RISK-001`
5. Run `scripts/validate_wbs_pack.py <pack-dir>`.
6. Fix validation errors before reporting completion.

## Executing A Work Package

When asked to implement a work package:

1. Run or mentally perform pack validation first.
2. Confirm the selected `wp_id` exists and is not `done`.
3. Confirm dependencies are done or explicitly waived.
4. Read the referenced acceptance criteria.
5. Implement the smallest change that satisfies the work package.
6. Run relevant tests or checks.
7. Update `02-wbs.md` status.
8. Add a concise `CHANGELOG.md` entry.
9. Report changed files, checks run, and any remaining risk.

## Review Checklist

Before final response, check:

- Did the answer follow the requested `wp_id`?
- Did implementation stay inside scope?
- Did non-goals remain untouched?
- Did acceptance pass or get clearly reported as unverified?
- Did `CHANGELOG.md` and WBS status change when behavior changed?

## Resources

- Read `references/wbs-pack-schema.md` when creating or auditing pack structure.
- Read `references/acceptance-rules.md` when writing acceptance criteria.
- Run `scripts/validate_wbs_pack.py <pack-dir>` for deterministic structure checks.
