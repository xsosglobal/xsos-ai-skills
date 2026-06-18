# XSOS WBS Pack Schema

This reference defines the standard bilingual WBS Pack for XSOS projects.

## Default Location

```text
docs/wbs/
```

Use another location only when the user provides it.

## Required Files

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

For backend-only projects, `03-page-spec.md` may contain `Not applicable / 不适用`.
For frontend-only projects, `05-data-contract.md` may contain only consumed DTOs and state enums.

## File Purpose

| file | purpose_cn | purpose_en |
|---|---|---|
| `00-brief.md` | 项目目标、背景、非目标 | Goal, context, non-goals |
| `01-requirements.md` | 业务需求和范围 | Business requirements and scope |
| `02-wbs.md` | 工作包、依赖、状态 | Work packages, dependencies, status |
| `03-page-spec.md` | 页面、状态、交互 | Pages, states, interactions |
| `04-api-contract.md` | 接口和 mock 合同 | API and mock contract |
| `05-data-contract.md` | 数据模型、字段、状态机 | Data models, fields, state machines |
| `06-acceptance.md` | 验收标准和测试场景 | Acceptance criteria and test scenarios |
| `07-risks.md` | 风险、假设、阻塞项 | Risks, assumptions, blockers |
| `08-implementation-rules.md` | 技术约束和编码规则 | Technical constraints and coding rules |
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

## 02-wbs.md Template

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
Use `proposed` for non-owner requests, global platform rule changes, or cross-module contract changes.

Required for every new work package:

- `acceptance_ref`
- `depends_on`
- `outputs`
- matching acceptance criteria in `06-acceptance.md`
- a reason entry in `CHANGELOG.md`

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
| developer | <name> | Delivery |
```
