# XSOS Acceptance Rules

Use acceptance criteria as the bridge between product intent, AI execution, and human review.

## Rules

1. Write acceptance criteria before implementation.
2. Use stable IDs such as `AC-FE-001`.
3. Make every criterion observable.
4. Include loading, empty, error, and permission states for UI work.
5. Include positive and negative cases for API work.
6. State what is not verified if a check cannot run locally.
7. Do not describe code, merge, deployment, release verification, and business acceptance as the same event.
8. In a v2 pack, a production-target work package reaches `done` only with a completed `RUN-*`, `actual_finish`, and a verified `REL-*` record with `environment=production`.
9. `delivery_counted=yes` is reserved for the current baseline's production delivery rate and requires `delivery_target=production`.

## Format

```md
## AC-FE-001: App Center renders registered apps

中文：
- 应用中心从 API 或 mock 数据读取应用列表。
- 禁用应用可见但不能打开。
- 接口失败时显示错误状态。

English:
- App Center reads apps from API or mock data.
- Disabled apps are visible but cannot be launched.
- API failure shows an error state.

Verification:
- Run frontend tests.
- Manually open `/app-center`.
```

## V2 Evidence Boundary

Acceptance criteria say what must be observable. `10-handoff.md` says what actually happened.

Keep these evidence levels separate:

| level | meaning | evidence example |
|---|---|---|
| implementation | Code or document exists | commit, changed files |
| verification | Automated or manual check passed | test log, screenshot, command output |
| release | Artifact reached an environment | deployment ID, release record |
| production verification | Production behavior was checked | verified `REL-*`, environment, date, evidence |
| business acceptance | Authorized person accepted the outcome | approver and acceptance record |

For v2 production delivery:

1. The acceptance heading still resolves from `acceptance_ref`.
2. The AI run closes with `outcome=completed`; its ISO `actual_finish` matches the work-package row.
3. The work package points to a `REL-*` row with `status=verified`.
4. The release row records `verified_at`, `environment=production`, and a reproducible evidence locator (URI, path, commit, controlled evidence ID, or `command:`/`cmd:` prefix).
5. Only then may `02-wbs.md` set a production-target package to `done`.

If verification cannot be completed, keep the package in `review` or close the run as `blocked`. If execution discovers work outside the current baseline, close it as `change_required` and raise a proposed `CR-*`; do not silently expand acceptance criteria.

## Bad Criteria

Avoid vague criteria:

```text
页面好看。
功能正常。
权限没问题。
```

Use observable criteria:

```text
When `/api/v1/apps/my` returns an empty array, `/app-center` shows the empty state.
When an app has `status=disabled`, its launch button is disabled.
```
