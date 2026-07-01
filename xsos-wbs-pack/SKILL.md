---
name: xsos-wbs-pack
description: Use when working with XSOS docs/wbs, work packages, requirements, page specs, API/data agreements, acceptance criteria, CHANGELOG, OWNERS, WBS-first SOP checks, AI handoffs, or module task execution.
---

# XSOS WBS Pack

## Overview

Use this skill to make AI agents read global XSOS standards and execute project work from a standard WBS Pack.

WBS Pack is the project delivery source of truth. Global rules and accepted cross-module consensus stay above local WBS Packs.

## Core Rules

1. Read the WBS Pack before coding.
2. Treat `docs/wbs` as the default pack location unless the user gives another path.
3. Do not treat chat history as stronger than the pack. If they conflict, report the conflict.
4. Do not expand scope beyond the selected work package.
5. Do not implement a task without clear acceptance criteria.
6. Keep Chinese and English together in the same files. Do not split `*-cn.md` and `*-en.md`.
7. When implementation changes behavior, update the fact spec and `CHANGELOG.md`.
8. Let the project owner have maximum authority inside their own project. Escalate only global rules or accepted cross-module consensus.
9. Read applicable global XSOS standards before executing or creating a WBS Pack.
10. Do not let project-local WBS content override global platform rules, accepted cross-module consensus, or constitution-level rules.
11. For git-backed XSOS projects, read WBS from the latest `develop` branch before analysis, planning, or implementation.
12. Do not start feature work from stale local WBS.

## Global Standards

Global standards define cross-project rules. WBS Packs define project-local delivery work.

Read standards in this order when they exist:

1. Project root `AGENTS.md`.
2. Current repo `standards/README.md`.
3. Current repo `docs/standards/README.md`.
4. Global delivery-control repo `/Users/coldtree/work/gitee/xsos-delivery-control/standards/README.md`.
5. Project-instance fallback `/Users/coldtree/work/gitee/xsos-platform/docs/standards/README.md`.
6. Task-relevant standard files referenced by the entrypoint, such as:
   - `constitution.md`
   - `wbs-standard.md`
   - `module-rule.md`
   - `file-service-standard.md`
   - `audit-trace-standard.md`
   - `qa-standard.md`
   - `ai-workflow-standard.md`

Only read standards relevant to the requested work package. Do not load every standard file by default.

If no global standards are found, continue with the local WBS Pack and report that the global standards entrypoint is missing.

Conflict order:

```text
global constitution / standards
> accepted cross-module consensus
> project WBS Pack
> chat history
```

## Start-of-Work WBS Sync

For git-backed XSOS projects, `develop` is the default WBS reading entrypoint.

Before analysis, planning, implementation, or handoff:

```bash
git checkout develop
git pull --ff-only
python3 /Users/coldtree/work/gitee/xsos-delivery-control/scripts/validate_wbs_pack.py docs/wbs
```

When using worktrees:

```bash
git worktree add <repo>/.worktrees/develop develop
cd <repo>/.worktrees/develop
git pull --ff-only
python3 /Users/coldtree/work/gitee/xsos-delivery-control/scripts/validate_wbs_pack.py docs/wbs
```

Rules:

- Read `docs/wbs` from latest `develop`, not stale `main`, old feature branches, screenshots, or chat history.
- Before creating `feature/*`, confirm the target `wp_id` exists in latest `develop` `docs/wbs/02-wbs.md`.
- If local `develop` is behind or pull fails, stop and report the sync issue before doing WBS-based work.
- If the project is not a git repository yet, explicitly report "no develop branch" and read current-directory `docs/wbs`.

## Fact Spec and Plan Loop

Plan loop is temporary. Fact spec is durable.

Use plan loop for exploration:

```text
expectation
> implementation attempt
> verification
> correction
> accepted fact
```

Do not keep temporary plans as long-term truth unless the user explicitly asks for a plan document.

When a behavior, API agreement, data shape, workflow, or acceptance rule becomes the current truth, update the relevant fact spec:

- Requirement truth: `01-requirements.md`
- Work package truth: `02-wbs.md`
- Page or interaction truth: `03-page-spec.md`
- API agreement truth: `04-api-contract.md`
- Data agreement truth: `05-data-contract.md`
- Acceptance truth: `06-acceptance.md`
- Risk truth: `07-risks.md`
- Implementation rule truth: `08-implementation-rules.md`
- Change truth: `CHANGELOG.md`

At minimum, every accepted behavior change must update `CHANGELOG.md`.

Temporary scripts, local experiments, and one-off planning notes should be deleted or explicitly marked temporary after use.

## WBS-First Change Gate

Behavior, API, data, workflow, UI, or acceptance changes must pass this gate before implementation review:

1. Confirm the work is covered by an existing `wp_id` in latest `develop`. If not, add or update the work package first.
2. Every new work package must update `02-wbs.md`, add or reference `06-acceptance.md`, and record the decision in `CHANGELOG.md` before or in the same change as implementation.
3. Update all affected fact specs, not only `CHANGELOG.md`. Common files are `03-page-spec.md`, `04-api-contract.md`, `05-data-contract.md`, `07-risks.md`, and `08-implementation-rules.md`.
4. For large or risky work, prefer two commits: WBS contract first, implementation second. A single commit is acceptable only when the final artifact contains the complete WBS, acceptance, fact-spec, and changelog updates.
5. If one change touches multiple work packages, either split the commits or document the acceptance impact for every affected `wp_id`.

Review red flags:

- Code or UI behavior changed without a matching `wp_id`, acceptance reference, and `CHANGELOG.md` entry.
- `CHANGELOG.md` claims verification that is not listed in the referenced acceptance criteria.
- `WP-*`, `AC-*`, or `RISK-*` references point to the wrong package.
- One commit mixes unrelated work packages without an explicit reason.
- Verification wording depends on stale state, such as "before syncing latest develop".

## Verification Gate

Testing is progressive during early platform construction. Do not block all work on perfect test coverage.

Minimum verification:

1. Run available automated tests when the repo already has them.
2. If automated tests do not exist or are not mature, run a smoke check or manual verification and record it.
3. If verification is skipped or incomplete, record the reason and remaining risk in the final response or `07-risks.md`.

Higher-risk work needs stronger verification:

- Auth, token, permission, scope, and session changes.
- Registry, module manifest, app launch, and navigation changes.
- File storage, upload, download, delete, preview, and OSS changes.
- Audit, trace, operation history, and cross-module calls.
- Data writes, migrations, and destructive operations.

For higher-risk work, add automated tests or negative tests when feasible. If not feasible in the current phase, state the gap clearly and update risk or acceptance notes.

## Required Read Order

For any execution task:

1. Read applicable global standards using the `Global Standards` order.
2. Sync and validate latest `develop` WBS using `Start-of-Work WBS Sync`.
3. Read `00-brief.md`.
4. Read `02-wbs.md`.
5. Find the requested `wp_id`.
6. Read `06-acceptance.md`.
7. Read task-specific files:
   - Frontend: `03-page-spec.md`, `04-api-contract.md`, `08-implementation-rules.md`
   - Backend: `04-api-contract.md`, `05-data-contract.md`, `08-implementation-rules.md`
   - Test/QA: `06-acceptance.md`, `07-risks.md`
   - Documentation: `00-brief.md`, `01-requirements.md`, `CHANGELOG.md`
8. Check `Non-goals / 非目标`, dependencies, owner, acceptance references, and global-standard constraints.
9. Execute only the selected work package.
10. Verify acceptance using the `Verification Gate`.
11. Update the relevant fact spec and `CHANGELOG.md` if behavior, API agreement, workflow, or acceptance changed.

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

1. If the requester is the project owner, module owner, or tech owner in `OWNERS.md`, they may add project-local work directly as `todo`.
2. If the requester is not an owner, add it as `proposed`.
3. If the work changes global platform rules or accepted cross-module consensus, add it as `proposed` even when requested by a project owner.
4. Do not execute `proposed` work packages until an owner changes them to `todo`.
5. Every new work package must include `acceptance_ref`, `depends_on`, and `outputs`.
6. Every new work package must add or reference acceptance criteria in `06-acceptance.md`.
7. Record the reason in `CHANGELOG.md`.

Use this default:

```text
Project owner local change -> status=todo
Global rule or accepted cross-module consensus change -> status=proposed
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

1. Read applicable global standards using the `Global Standards` order.
2. Read `references/wbs-pack-schema.md`.
3. Create `docs/wbs/` if it does not exist.
4. Create the required files with concise content.
5. Use stable IDs:
   - Work package: `WP-FE-001`, `WP-BE-001`, `WP-QA-001`
   - Acceptance: `AC-FE-001`, `AC-BE-001`
   - Risk: `RISK-001`
6. Reference applicable standards in `08-implementation-rules.md`.
7. Run `scripts/validate_wbs_pack.py <pack-dir>`.
8. Fix validation errors before reporting completion.

## Executing A Work Package

When asked to implement a work package:

1. Sync latest `develop` and validate `docs/wbs`.
2. Confirm the selected `wp_id` exists in latest `develop` and is not `done`.
3. Confirm dependencies are done or explicitly waived.
4. Read the referenced acceptance criteria.
5. Create feature work from `develop`, not from stale local branches.
6. Implement the smallest change that satisfies the work package.
7. Run relevant tests, smoke checks, or manual verification.
8. Update relevant fact spec files when implementation changes current truth.
9. Add a concise `CHANGELOG.md` entry.
10. Report changed files, checks run, and any remaining risk.

## Review Checklist

Before final response, check:

- Did the answer follow the requested `wp_id`?
- Did the agent read WBS from latest `develop`, or clearly report the non-git/no-develop exception?
- Did implementation stay inside scope?
- Did non-goals remain untouched?
- Did applicable global standards get read or reported as missing?
- Did local WBS content respect global rules and accepted cross-module consensus?
- Did accepted behavior changes update the relevant fact spec?
- Did `CHANGELOG.md` record the accepted change?
- Did tests, smoke checks, or manual verification run or get clearly reported as incomplete?
- Did unverified or partially verified work get recorded as risk?

## Resources

- Read `references/wbs-pack-schema.md` when creating or auditing pack structure.
- Read `references/acceptance-rules.md` when writing acceptance criteria.
- Run `scripts/validate_wbs_pack.py <pack-dir>` for deterministic structure checks.
