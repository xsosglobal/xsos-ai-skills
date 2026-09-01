# XSOS WBS Pack Schema

This reference defines the standard bilingual WBS Pack for XSOS projects.

## Default Location

```text
docs/wbs/
```

Use another location only when the user provides it.

## V1 Required Files

```text
00-brief.md
01-requirements.md
02-wbs.md
03-page-spec.md
04-api-contract.md
05-data-contract.md
06-acceptance.md
07-risks.md
08-implementation-rules.md
CHANGELOG.md
OWNERS.md
```

For v1 backend-only projects, `03-page-spec.md` may contain `Not applicable / 不适用`.
V2 keeps the canonical empty `page_id` table and records the explicit not-applicable decision in Artifact Readiness. The same rule applies to v2 API/data tables.

Packs without an explicit v2 marker remain v1. This preserves all existing packs and validators.

## V2 Activation and Required Files

V2 is opt-in. Add a `Project Control` field/value table to `00-brief.md` and set `wbs_schema` to `2`:

```md
## 项目控制 / Project Control

| field | value |
|---|---|
| wbs_schema | 2 |
| project_id | <stable-project-id> |
| project_status | planning |
| product_owner | product_owner |
| current_baseline | none |
| planned_start | TBD |
| planned_finish | TBD |
| forecast_finish | TBD |
| actual_start | none |
| actual_finish | none |
```

The parser is header-driven. A one-row wide table containing a `wbs_schema` column is also accepted, but the field/value form is preferred.

V2 requires every v1 file plus:

```text
09-baselines.md
10-handoff.md
11-change-requests.md
```

Project, baseline, change-request, and release dates use `YYYY-MM-DD`. AI run `actual_start` and `actual_finish` also accept ISO 8601 datetimes with an offset, such as `2026-09-01T00:28:34-07:00`. Use `none` for an optional value that does not apply and `TBD` for an unresolved planning value.

`project_status` is one of `draft`, `planning`, `active`, `on_hold`, `closing`, `closed`, or `cancelled`. `draft` and `planning` may have no current approved baseline and may contain only `proposed` or `cancelled` work packages. `active`, `on_hold`, `closing`, and `closed` require exactly one current approved baseline.

V2 stable reference forms:

```text
Requirement version: REQ-001@v1, REQ-PUR-001@v2
Baseline:            BL-001, BL-PUR-001
Change request:      CR-001, CR-PUR-001
AI run:              RUN-001, RUN-PUR-001
Release evidence:    REL-001, REL-PUR-001
```

## File Purpose

| file | purpose_cn | purpose_en |
|---|---|---|
| `00-brief.md` | 项目目标、背景、非目标 | Goal, context, non-goals |
| `01-requirements.md` | 业务需求和范围 | Business requirements and scope |
| `02-wbs.md` | 工作包、依赖、状态 | Work packages, dependencies, status |
| `03-page-spec.md` | 页面、状态、交互 | Pages, states, interactions |
| `04-api-contract.md` | 接口和 mock 约定 | API and mock agreement |
| `05-data-contract.md` | 数据模型、字段、状态机 | Data models, fields, state machines |
| `06-acceptance.md` | 验收标准和测试场景 | Acceptance criteria and test scenarios |
| `07-risks.md` | 风险、假设、阻塞项 | Risks, assumptions, blockers |
| `08-implementation-rules.md` | 技术约束和编码规则 | Technical constraints and coding rules |
| `09-baselines.md` | V2 当前及历史基线 | V2 current and historical baselines |
| `10-handoff.md` | V2 AI 执行、停止、交接和发布证据 | V2 AI runs, stop/handoff, and release evidence |
| `11-change-requests.md` | V2 正式变更申请和审批 | V2 formal change requests and decisions |
| `CHANGELOG.md` | 需求和实现变更记录 | Requirement and implementation change log |
| `OWNERS.md` | owner、reviewer、验收人 | Owner, reviewer, approver |

## 00-brief.md Template

```md
# <Project Name> WBS Brief

## 项目目标 / Goal

<Chinese goal>

<English goal>

## 背景 / Context

<Short background.>

## 非目标 / Non-goals

- <Chinese non-goal>
- <English non-goal>

## 一期范围 / Phase 1 Scope

- <scope item>
```

## 02-wbs.md V1 Template

Prefer a Markdown table for small packs.

```md
# WBS

| wp_id | title_cn | title_en | type | owner | status | depends_on | acceptance_ref | outputs |
|---|---|---|---|---|---|---|---|---|
| WP-FE-001 | 门户布局壳 | Portal layout shell | frontend | frontend-owner | todo | none | AC-FE-001 | AppLayout, Sidebar, Topbar |
```

Use these status values:

```text
proposed
todo
in_progress
blocked
review
done
cancelled
```

Status meaning:

| status | meaning_cn | meaning_en |
|---|---|---|
| `proposed` | 提议中，不能执行 | Proposed, not executable |
| `todo` | 已批准，待执行 | Approved and ready |
| `in_progress` | 执行中 | In progress |
| `blocked` | 阻塞 | Blocked |
| `review` | 待验收 | Waiting for review |
| `done` | 完成 | Done |
| `cancelled` | 取消 | Cancelled |

Project owners have maximum authority inside their own project and may add project-local work packages directly as `todo`.
Use `proposed` for non-owner requests, global platform rule changes, or accepted cross-module consensus changes.

Required for every new work package:

- a `wp_id` that is unique across the entire `02-wbs.md` file
- an `acceptance_ref` that exists exactly once in `06-acceptance.md`
- `depends_on`; bare local IDs must exist and must not form a cycle, while cross-project references include the project name
- `outputs`
- matching acceptance criteria in `06-acceptance.md`
- a reason entry in `CHANGELOG.md`

## 01-requirements.md V2 Registers

V2 separates source evidence, business requirement versions, and implementation work packages. The Source Register and Requirement Register are header-driven:

```md
# Requirements

## Source Register

| source_id | source_type | source_ref | captured_at | note |
|---|---|---|---|---|
| SRC-001 | user_request | conversation | 2026-08-31 | Approved scope discussion |

## Requirement Register

| req_id | version | requirement_cn | requirement_en | priority | owner | status | baseline_ref | change_ref | acceptance_refs | source_refs | approved_at | supersedes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| REQ-001 | v1 | 用户可以按生产单号查询 | Users can query by production order number | P0 | product-owner | baselined | BL-001 | none | AC-BE-001 | SRC-001 | 2026-08-31 | none |
```

The validator combines `req_id` and `version` into `REQ-001@v1`. Each pair is unique. `source_id` uses `SRC-*`, is unique, and records an ISO `captured_at`. Every `source_refs` value resolves to the Source Register.

Requirement status is `draft`, `proposed`, `approved`, `baselined`, `superseded`, or `cancelled`. A current approved baseline may reference only `approved` or `baselined` requirement versions. Early v2 packs using `## REQ-001@v1` headings remain readable as a compatibility fallback; new packs use the registers.

## 02-wbs.md V2 Template

All added lifecycle columns are mandatory in the header. Planning placeholders use `none` or `TBD`; executable states use resolving references and ISO dates.

```md
# WBS

| wp_id | title_cn | title_en | type | owner | status | depends_on | requirement_refs | scope | non_goals | baseline_ref | run_ref | release_ref | planned_start | planned_finish | forecast_finish | actual_start | actual_finish | change_ref | acceptance_ref | outputs | delivery_target | delivery_counted |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| WP-BE-001 | 生产单查询 | Production order search | backend | backend-owner | todo | none | REQ-001@v1 | Query API | Export report | BL-001 | none | none | 2026-09-01 | 2026-09-15 | 2026-09-15 | none | none | none | AC-BE-001 | API, tests | production | yes |
```

V2 field rules:

- `requirement_refs`: one or more comma-separated `REQ-*@vN` references.
- `scope`, `non_goals`, and `outputs`: non-empty; use `none` only when it is an explicit decision.
- `delivery_target`: `none`, `review`, or `production`.
- `delivery_counted`: `yes` or `no`; `yes` enters the current baseline's production-delivery-rate denominator and therefore requires `delivery_target=production`.
- `baseline_ref`, `planned_start`, `planned_finish`, and `forecast_finish`: required and current for `todo`, `blocked`, `review`, and `in_progress`.
- `actual_start`: required for `in_progress` and must match the active `RUN-*`; a work-package date and a RUN datetime on the same local date are consistent.
- `actual_finish`: required for production-target `done` and must match the completed `RUN-*` under the same rule.
- `change_ref`: `none` or one resolving `CR-*`.
- `run_ref`: one `RUN-*` is required for `in_progress` and for production-target `done`.
- `release_ref`: one verified `REL-*` is required for production-target `done`.

`proposed` and `cancelled` are outside executable current scope and may use `none` or `TBD` in lifecycle fields. `todo`, `in_progress`, `blocked`, and `review` must be members of the current baseline and use it in `baseline_ref`. Completed production work retains the baseline and evidence under which it finished.

### Artifact Readiness Register

Keep this second table in `02-wbs.md`. Every newly authored or currently managed v2 WP has exactly one row for each of the seven artifact types. An untouched migrated historical WP with `status=done`, `delivery_target=none`, and `change_ref=none` may retain its legacy AC shape and omit the rows; the board shows missing legacy readiness. Reopening it or attaching a change request removes the exemption and requires managed AC metadata plus all seven rows.

```md
| wp_id | artifact | applicability | readiness | owner | refs | reason | change_ref |
|---|---|---|---|---|---|---|---|
| WP-BE-001 | requirement | required | verified | product-owner | REQ-001@v1 | Approved requirement version | none |
| WP-BE-001 | page | not_applicable | not_applicable | frontend-owner | none | Backend-only change | none |
| WP-BE-001 | api | required | draft | backend-owner | API-BE-001 | Contract drafted | none |
| WP-BE-001 | data | required | ready | backend-owner | DATA-BE-001 | Migration contract ready for verification | none |
| WP-BE-001 | acceptance | required | draft | product-owner | AC-BE-001 | Observable acceptance drafted | none |
| WP-BE-001 | risk | required | ready | backend-owner | none | Risk assessment completed; no identified risk | none |
| WP-BE-001 | handoff | required | not_started | backend-owner | none | Execution has not started | none |
```

Artifact types are `requirement`, `page`, `api`, `data`, `acceptance`, `risk`, and `handoff`.
Applicability is `required` or `not_applicable`. Readiness is `not_applicable`,
`not_started`, `draft`, `ready`, `verified`, `change_pending`, or `superseded`.
`verified` requires stable refs; `change_pending` requires a resolving `CR-*`.
This register measures artifact/contract completeness only. WP status measures execution;
verified production REL evidence measures production delivery. Do not combine the three.

## 09-baselines.md V2 Template

Keep prior rows. When an approved change alters committed scope or dates, create a new baseline row, mark the old row `superseded/current=no`, and link the new row to an approved `CR-*`.

```md
# Baselines

| baseline_id | version | status | current | approved_by | approved_at | planned_start | planned_finish | forecast_finish | requirement_refs | wp_refs | change_ref | supersedes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BL-001 | v1 | approved | yes | baseline-approver | 2026-08-31 | 2026-09-01 | 2026-09-30 | 2026-09-30 | REQ-001@v1 | WP-BE-001 | none | none |
```

Rules:

- `status`: `draft`, `approved`, or `superseded`.
- `current`: `yes` or `no`.
- `version`: `v1`, `v2`, and so on.
- Approved and superseded rows preserve `approved_by`, `approved_at`, planned dates, and `forecast_finish`; draft rows may use `none` or `TBD`.
- There is at most one current row, and it must be approved. Projects in `active`, `on_hold`, `closing`, or `closed` require exactly one; `draft` and `planning` may have zero.
- Current active work packages and their requirement versions must appear in that row.
- The current baseline excludes proposed/cancelled WPs and retains every non-cancelled, non-proposed counted WP, including already delivered work.
- `approved_by` resolves to `baseline_approver`.
- `change_ref` may be `none` for the initial baseline; every `v2+` baseline references exactly one CR. Approved/superseded `v2+` rows require that CR to be approved or implemented.
- Versions cannot skip. `supersedes` is `none` for the initial baseline and points to the immediately prior version for every replacement.

## 10-handoff.md V2 Template

The run table controls AI start and stop. The release table records deployment verification separately from code completion.

```md
# AI Runs and Release Evidence

| run_id | wp_id | baseline_ref | status | actual_start | actual_finish | outcome | change_ref | next_action |
|---|---|---|---|---|---|---|---|---|
| RUN-001 | WP-BE-001 | BL-001 | active | 2026-09-01T00:28:34-07:00 | none | none | none | Run acceptance checks |

| release_id | wp_id | run_ref | baseline_ref | status | verified_at | environment | evidence | verified_by |
|---|---|---|---|---|---|---|---|---|
```

Run rules:

- `status`: `active` or `closed`.
- Every run has an ISO date or datetime `actual_start` and an approved `baseline_ref`.
- An active run has no terminal outcome.
- One WP has at most one active RUN, and that RUN uses the current approved baseline.
- A closed run has `actual_finish` and one outcome: `completed`, `blocked`, or `change_required`.
- `blocked` and `change_required` require a concrete `next_action`.
- An `in_progress` work package points to an active run under the current baseline.

Release rules:

- `status`: `planned`, `deployed`, `verified`, or `failed`.
- A verified release resolves one closed/completed `run_ref`, its approved or superseded `baseline_ref`, an acceptance owner in `verified_by`, `verified_at`, `environment`, and a stable evidence locator.
- `evidence` is not free-form success prose. It contains at least one reproducible locator: a URI, repository/absolute path, 7-40 character hexadecimal commit containing `a-f`, a controlled `EVIDENCE/EVD/BUILD/DEPLOY/RELEASE/CI/JOB/ARTIFACT-*` ID, or a `command:`/`cmd:` prefix.
- `verified_at` cannot be earlier than the referenced RUN finish.
- A production-target work package cannot be `done` until its run is closed/completed with `actual_finish` and its referenced release is verified in `environment=production`.
- Production delivery rate is `verified production REL for current-baseline delivery_counted=yes WP / all non-cancelled current-baseline delivery_counted=yes WP`. `review` and `none` targets are excluded.

## 11-change-requests.md V2 Template

The file is required even when no change has been raised; keep the header-only table in that case.

```md
# Change Requests

| cr_id | status | requested_at | decided_at | affected_refs | baseline_from | baseline_to | decision | approver |
|---|---|---|---|---|---|---|---|---|
```

Use `proposed`, `approved`, `rejected`, or `implemented`. Approved, rejected, and implemented rows require `decided_at`, `decision`, and an `approver` resolving to `change_approver`. `affected_refs` accepts resolving `REQ-*@vN`, `WP-*`, `AC-*`, canonical Risk Register `RISK-*`, `BL-*`, `RUN-*`, and `REL-*` references. A baseline may use a `change_ref` only when the referenced CR is approved or implemented.

## CHANGELOG.md Template

```md
# CHANGELOG

## 2026-06-18

- `WP-FE-001`: Created Portal layout shell requirements.
```

## OWNERS.md Template

```md
# OWNERS

| role | name | responsibility |
|---|---|---|
| product_owner | <name> | Requirements and acceptance |
| tech_owner | <name> | Architecture and implementation review |
| baseline_approver | <name> | Approve and activate BL |
| change_approver | <name> | Approve or reject CR |
| acceptance_owner | <name> | Verify delivery evidence and closure |
| developer | <name> | Delivery |
```
