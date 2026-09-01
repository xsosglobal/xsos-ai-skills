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
13. For module navigation, treat `module.yaml.nav_entries` as module-owned entry metadata. Registry/platform placement only owns `parent_key`, `sort_order`, and `status`; Portal renders the approved navigation tree.
14. Require every `wp_id` in `02-wbs.md` to be unique. A duplicate ID is a blocking ambiguity even when the titles or acceptance references differ.
15. Require every `acceptance_ref` to resolve to one unique heading in `06-acceptance.md`.
16. Bare local `depends_on` IDs must exist and the local dependency graph must be acyclic. Qualify cross-project dependencies with the project name.
17. In v1, require every `wp_id` in `02-wbs.md` to have a matching `## <wp_id> …` section in `01-requirements.md`. A work package with no recorded requirement has no basis to be built. Packages predating this rule may be listed in `requirements-baseline.txt`; that list is a one-way ratchet — entries are removed as requirements are backfilled, never added. V2 instead resolves `requirement_refs` through the Requirement Register.
18. Keep the work-package table as one unbroken Markdown table. A blank line inside it splits the table, and every row after the break is silently skipped by the uniqueness, dependency and cycle checks.
19. Keep v1 packs compatible. A pack becomes v2 only when the `Project Control` table in `00-brief.md` explicitly sets `wbs_schema` to `2`.
20. In an executable v2 project, execute only work packages inside the one current approved baseline. An AI run does not gain authority to expand that baseline.
21. In v2, preserve baseline history. A post-baseline scope or schedule change uses an approved `CR-*` and a new `BL-*`; do not overwrite an old baseline or rewrite a completed work package.
22. V2 baseline versions are contiguous. `v2+` resolves one approved/implemented CR, immediately supersedes the prior BL, and uses the configured baseline/change approvers.
23. The current baseline excludes proposed/cancelled work and retains every non-cancelled, non-proposed `delivery_counted=yes` WP, including already delivered work.
24. A WP has at most one active RUN. A verified REL resolves that WP's closed/completed RUN, approved/superseded BL, acceptance owner, stable evidence locator, and an ordered verification time.

## Schema Compatibility and V2 Activation

Packs without a v2 marker continue to use the v1 rules and files. Do not infer v2 from the presence of a lifecycle file.

Activate v2 with a header-driven field/value table under a heading containing `Project Control`:

```md
## 项目控制 / Project Control

| field | value |
|---|---|
| wbs_schema | 2 |
| project_status | planning |
| current_baseline | none |
| planned_start | TBD |
| planned_finish | TBD |
| forecast_finish | TBD |
| actual_start | none |
| actual_finish | none |
```

V2 additionally requires:

- `09-baselines.md`: immutable baseline register and approved scope membership.
- `10-handoff.md`: AI `RUN-*` records and `REL-*` release evidence.
- `11-change-requests.md`: `CR-*` decisions and baseline transitions.

Project, baseline, change-request, and release dates use `YYYY-MM-DD`; RUN actual times may also use ISO 8601 datetimes with offsets. Planning placeholders use `none` or `TBD`. `project_status` is `draft`, `planning`, `active`, `on_hold`, `closing`, `closed`, or `cancelled`. `draft` and `planning` may have zero current baselines and only `proposed`/`cancelled` work. `active`, `on_hold`, `closing`, and `closed` require exactly one current approved baseline.

V2 `01-requirements.md` uses a Source Register (`SRC-*`) and a Requirement Register. The validator composes `req_id=REQ-001` plus `version=v1` into `REQ-001@v1`, requires every `source_refs` value to resolve, and allows only `approved` or `baselined` requirement versions in the current baseline. Early `## REQ-001@v1` headings remain a compatibility fallback.

Baseline, change, run, and release IDs use `BL-001`, `CR-001`, `RUN-001`, and `REL-001` respectively; domain segments may appear before the final three digits.

## Global Standards

Global standards define cross-project rules. WBS Packs define project-local delivery work.

Read standards in this order when they exist:

1. Project root `AGENTS.md`.
2. Current repo `standards/README.md`.
3. Current repo `docs/standards/README.md`.
4. Global delivery-control repo resolved from `XSOS_DELIVERY_CONTROL_ROOT`, a sibling of the `xsos-ai-skills` checkout, or `$HOME/work/gitee/xsos-delivery-control`; then read `standards/README.md`.
5. Project-instance fallback `$HOME/work/gitee/xsos-platform/docs/standards/README.md`.
6. Task-relevant standard files referenced by the entrypoint, such as:
   - `rules/constitution.md`
   - `rules/wbs-rule.md`
   - `rules/module-rule.md`
   - `rules/file-service-rule.md`
   - `rules/operation-trace-rule.md`
   - `rules/qa-rule.md`
   - `rules/ai-agent-rule.md`

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

For git-backed XSOS projects, `origin/develop` is the default WBS reading entrypoint.
Never switch, clean, or overwrite the user's active worktree merely to read WBS.

Fetch the integration ref, then inspect it from an existing clean integration worktree or a short detached worktree:

```bash
git fetch origin develop
git worktree add --detach <temporary-worktree> origin/develop
cd <temporary-worktree>
python3 <xsos-wbs-pack-dir>/scripts/validate_wbs_pack.py docs/wbs
# return to the original directory, then:
git worktree remove <temporary-worktree>
```

Rules:

- Read `docs/wbs` from latest `origin/develop`, not stale `main`, old feature branches, screenshots, or chat history.
- Before creating `feature/*`, confirm the target `wp_id` exists in latest `origin/develop` `docs/wbs/02-wbs.md`.
- If fetch fails, stop and report the sync issue before doing WBS-based work; do not silently fall back to a stale ref.
- Remove only the exact temporary worktree created for this check. Preserve every pre-existing worktree and uncommitted file.
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
- Baseline truth: `09-baselines.md` in v2
- AI run, handoff, and release truth: `10-handoff.md` in v2
- Formal change truth: `11-change-requests.md` in v2
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
3. Read `00-brief.md` and detect the schema from its `Project Control` table.
4. For v2, read the current approved baseline in `09-baselines.md` and confirm the target `wp_id` is a member.
5. Read `01-requirements.md`, then resolve the target work package's versioned `requirement_refs` in v2.
6. Read `02-wbs.md` and find the requested `wp_id`.
7. Read `06-acceptance.md`.
8. Read task-specific files:
   - Frontend: `03-page-spec.md`, `04-api-contract.md`, `08-implementation-rules.md`
   - Backend: `04-api-contract.md`, `05-data-contract.md`, `08-implementation-rules.md`
   - Test/QA: `06-acceptance.md`, `07-risks.md`
   - Documentation: `00-brief.md`, `01-requirements.md`, `CHANGELOG.md`
9. In v2, read relevant `CR-*`, prior `RUN-*`, and `REL-*` records from `11-change-requests.md` and `10-handoff.md`.
10. Check `Non-goals / 非目标`, dependencies, owner, acceptance references, and global-standard constraints.
11. Execute only the selected work package.
12. Verify acceptance using the `Verification Gate`.
13. Update the relevant fact spec and `CHANGELOG.md` if behavior, API agreement, workflow, or acceptance changed.

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

V2 additionally requires these non-empty columns:

- `requirement_refs`: comma-separated versioned requirement references such as `REQ-001@v1`
- `scope`
- `non_goals`
- `delivery_target`: `none`, `review`, or `production`
- `delivery_counted`: `yes` or `no`; `yes` means this WP is in the current baseline's **production delivery rate** denominator and therefore requires `delivery_target=production`
- `baseline_ref`
- `planned_start`
- `planned_finish`
- `forecast_finish`
- `actual_start`
- `actual_finish`
- `change_ref`
- `run_ref`
- `release_ref`

Lifecycle values are state-dependent:

- `proposed` and `cancelled` may use `none` or `TBD` for unresolved lifecycle values.
- `todo`, `blocked`, `review`, and `in_progress` require the current `baseline_ref` plus ISO `planned_start`, `planned_finish`, and `forecast_finish`.
- `in_progress` requires ISO `actual_start` and exactly one matching active `RUN-*`.
- production-target `done` requires ISO `actual_finish`, exactly one closed/completed `RUN-*`, and exactly one verified `REL-*`.

An `in_progress` package must point to its only active run with `actual_start` under the current baseline. A production-target `done` package must point to a closed run with `outcome=completed` and `actual_finish`, plus a release that resolves the same RUN/baseline, `verified_by=acceptance_owner`, `status=verified`, ordered `verified_at`, `environment=production`, and a stable evidence locator. Conversely, a verified production REL requires the WP to be `done`.

Production delivery rate is calculated only inside the current approved baseline:

```text
verified production deliveries where delivery_counted=yes
----------------------------------------------------------
all non-cancelled work packages where delivery_counted=yes
```

`review` and `none` targets may still have lifecycle status, but they never enter this production metric.

## Artifact Readiness / 七类交付物就绪度

Every newly authored or currently managed v2 work package has exactly one row for each artifact in the Artifact Readiness Register:
`requirement`, `page`, `api`, `data`, `acceptance`, `risk`, and `handoff`.

Migration exception: an untouched historical WP with `status=done` and `delivery_target=none`
may retain its legacy AC shape and omit these rows only while `change_ref=none`. The board
displays it as missing legacy readiness, and the exception does not create delivery evidence.
Reopening the WP or attaching a change request removes the exemption and requires the managed
AC metadata plus all seven rows before execution.

- `applicability`: `required` or `not_applicable`.
- `readiness`: `not_applicable`, `not_started`, `draft`, `ready`, `verified`,
  `change_pending`, or `superseded`.
- `verified` requires stable evidence/reference IDs. `change_pending` requires a resolving `CR-*`.
- Page/API/data refs resolve to their canonical contract tables; handoff refs resolve to RUN/REL. Verified readiness requires the referenced fact itself to be verified or closed.
- `not_applicable` is an explicit scope decision with a concrete reason, not a missing artifact.
- Artifact readiness describes contract/evidence completeness. It is not WP lifecycle progress and is never used as the production-delivery-rate numerator or denominator.

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
8. In v2, link at least one current `REQ-*@vN`, state `scope` and `non_goals`, classify delivery, and place approved work in the current baseline before execution.
9. In v2, post-baseline additions require an approved `CR-*` and a new approved baseline; proposed work stays outside executable scope.
10. In v2, register all seven artifact rows. Decide page/API/data applicability explicitly; do not infer applicability from the WP type.

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
   - V1: the original 00-08 fact files, `CHANGELOG.md`, and `OWNERS.md`.
   - V2: the v1 files plus `09-baselines.md`, `10-handoff.md`, and `11-change-requests.md`.
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
5. In v2, confirm the package and its requirement versions belong to the current approved baseline.
6. In v2, create or select the WP's only active `RUN-*`, record `actual_start`, and keep its `baseline_ref` on the current baseline.
7. Create feature work from `develop`, not from stale local branches.
8. Implement the smallest change that satisfies the work package.
9. Run relevant tests, smoke checks, or manual verification.
10. If work crosses the approved boundary, stop with `outcome=change_required`, record `next_action`, and create a proposed `CR-*`; do not implement the extra scope.
11. Keep applicable artifact rows current. Use `change_pending` plus a `CR-*` when the artifact contract must change; use `verified` only with stable refs/evidence.
12. For a production-target completion, record a closed completed run, `actual_finish`, and a verified `REL-*` before setting the work package to `done`.
13. Update relevant fact spec files when implementation changes current truth.
14. Add a concise `CHANGELOG.md` entry.
15. Report changed files, checks run, and any remaining risk.

## Review Checklist

Before final response, check:

- Did the answer follow the requested `wp_id`?
- Did the agent read WBS from latest `develop`, or clearly report the non-git/no-develop exception?
- Did implementation stay inside scope?
- Did non-goals remain untouched?
- For v2, was the work package inside the current approved baseline?
- For v2, did `in_progress` and production `done` satisfy the RUN/REL evidence gates?
- For v2, did any baseline change resolve through an approved `CR-*` and a new baseline?
- For v2, are BL/CR approvers configured, versions contiguous, and the current counted scope complete?
- For v2, does each verified REL resolve the same WP/RUN/BL, acceptance owner, stable evidence locator, and ordered timestamps?
- For v2, are all seven artifact rows present, with explicit applicability and evidence-backed readiness?
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
- Run `scripts/render_wbs_board.py <pack-dir> [output.html]` for the read-only board. In v2 it reads the header-driven WP table, the seven-row Artifact Readiness Register, the current approved baseline, and verified production REL evidence as separate layers; v1 keeps the legacy heading-based coverage fallback.
