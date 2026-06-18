# XSOS Acceptance Rules

Use acceptance criteria as the contract between product intent, AI execution, and human review.

## Rules

1. Write acceptance criteria before implementation.
2. Use stable IDs such as `AC-FE-001`.
3. Make every criterion observable.
4. Include loading, empty, error, and permission states for UI work.
5. Include positive and negative cases for API work.
6. State what is not verified if a check cannot run locally.

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
