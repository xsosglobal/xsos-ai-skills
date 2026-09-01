# Raw Requirement to WBS Conversion SOP

本 SOP 只负责把原始需求转换为待审批交付草案。它不批准项目范围，不启动实现，
也不把任何工作视为已生产交付。

## 1. 输入与证据边界

可接受输入包括飞书文档、会议纪要、微信截图、用户口述、已有 WBS/代码事实。
先区分：

- 原始证据：谁在什么时候说了什么，原文件或链接在哪里。
- 业务解释：模型从证据中整理出的需求含义。
- 执行授权：owner 明确批准进入哪个基线；不能从附件内容推断。

飞书优先使用对应的 lark skill/CLI 读取结构化正文。公开链接或 CLI 不可用时再用
其他只读方式。截图必须结合用户补充文字理解；对话中的猜测不能写成已批准事实。

## 2. 启动门禁

1. 从最新 `develop` 读取 `docs/wbs`。
2. 运行现有 WBS validator；结构已坏时先停止并报告。
3. 读取 `OWNERS.md`、`00-brief.md`、当前需求、WBS、验收、风险和 CHANGELOG。
4. 确认本次只转换一个可独立审批的业务变化。
5. 缺 owner、明确边界或可观察验收时先询问，不生成猜测性 WP；owner 和 acceptance owner 必须能在 `OWNERS.md` 解析到具体人员。

## 3. Schema 路由

v2 只能由 `00-brief.md` 的 Project Control 表显式开启：

```md
## Project Control / 项目控制

| field | value |
|---|---|
| wbs_schema | 2 |
```

没有这个表格标记就是 v1。不得为了使用新功能自动修改 pack schema；迁移本身是
单独的 owner 决策。

## 4. 来源登记

v2 的每条新需求必须引用 Source Register。canonical 表为：

```md
## Source Register / 来源登记

| source_id | source_type | source_ref | captured_at | note |
|---|---|---|---|---|
```

规则：

- `source_id` 使用 `SRC-001` 或带有限领域段的稳定 ID。
- `source_ref` 可以是文档 URL、仓库路径、会议记录或稳定的对话引用。
- `captured_at` 使用 `YYYY-MM-DD`。
- 同一来源复用原 `SRC-*`；同 ID 不得改指向另一个来源。
- `note` 说明证据类型和边界，不能把摘要声称为逐字稿。

`source_refs` spec 可以直接引用已登记的 `SRC-*`，也可以传来源对象让脚本登记：

```json
{
  "source_refs": [{
    "source_type": "feishu",
    "source_ref": "https://example.feishu.cn/docx/xxx",
    "captured_at": "2026-09-01",
    "note": "客户确认的原始需求文档"
  }]
}
```

## 5. 稳定需求版本

Requirement Register canonical 表头：

```md
| req_id | version | requirement_cn | requirement_en | priority | owner | status | baseline_ref | change_ref | acceptance_refs | source_refs | approved_at | supersedes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
```

稳定引用形式是 `REQ-001@v1`、`REQ-PUR-001@v2`。

版本判断：

- 新业务目标：新 `req_id@v1`。
- 已批准需求的行为、范围或验收语义变化：同 `req_id` 新版本。
- 只是错别字或不改变行为的解释补充：保留版本，记录 CHANGELOG。
- 实现不符合现有需求：复用原 REQ，新增缺陷修复 WP，不改需求版本。
- 已登记版本内容不同：脚本拒绝原地覆盖，要求显式选择新版本。
- 新版本必须连续；创建 `vN` 时脚本要求 `vN-1` 已登记，并自动写入 `supersedes=REQ-...@vN-1`。

Author 创建的新 REQ 固定为 `draft`，`baseline_ref=none`。审批和纳入基线由 owner
完成。一个 WP 可以复用多个已登记 `requirement_refs`，但一次转换最多自动创建
一个新 REQ。

## 6. proposed WP

v2 的 `02-wbs.md` 按实际表头写入，列顺序可以变化。canonical 生命周期字段是：

```text
requirement_refs
delivery_target
delivery_counted
baseline_ref
planned_start
planned_finish
forecast_finish
actual_start
actual_finish
change_ref
run_ref
release_ref
```

转换输出固定满足：

- `status=proposed`
- `baseline_ref=none`
- `planned_start/planned_finish/forecast_finish=TBD`，除非 spec 提供计划值
- `actual_start/actual_finish=none`
- `run_ref/release_ref=none`
- `change_ref=none`，除非只是引用一个已有 CR
- `delivery_target` 只能是 `none`、`review`、`production`
- `delivery_counted` 只能是 `yes/no`；`yes` 只允许搭配 `delivery_target=production`

`delivery_counted=yes` 表示 owner 纳入基线后可进入生产交付率分母。`review` 和
`none` 永远不进入生产交付率。Author 只提出该属性，不改变当前批准基线的分母。

## 7. 七类交付物就绪度

每个 v2 WP 在 `02-wbs.md` 的 Artifact Readiness Register 中固定登记七类对象：
`requirement`、`page`、`api`、`data`、`acceptance`、`risk`、`handoff`。

- `applicability` 只有 `required`、`not_applicable`。
- `readiness` 只有 `not_applicable`、`not_started`、`draft`、`ready`、
  `verified`、`change_pending`、`superseded`。
- `verified` 必须有稳定 `refs`；`change_pending` 必须引用 `CR-*`。
- `not_applicable` 不是缺失，必须有具体理由。
- 这张表表示需求、页面、接口、数据等合同和交接物是否齐备，不是 WP 的执行进度，
  也不进入生产交付率。

Author 自动生成 requirement、acceptance、risk、handoff 行；调用者必须显式给出
page、api、data 的适用性和原因，不能根据 `type` 猜测。

## 8. v2 spec

```json
{
  "series": "BE",
  "title_cn": "采购对账差异表",
  "title_en": "Purchase reconciliation diff",
  "type": "backend",
  "owner": "顾昊",
  "depends_on": ["WP-BE-078"],
  "scope": "录入发票原值并逐行比对采购单",
  "non_goals": "不改 Web；不自动调整采购单金额",
  "outputs": "migration, service, API, tests, WBS facts",
  "requirements": ["发票金额必须保留原值，不得由系统反算。"],
  "requirement_en": "Invoice amounts preserve the supplied source value.",
  "priority": "P0",
  "source_refs": [{
    "source_type": "feishu",
    "source_ref": "https://example.feishu.cn/docx/xxx",
    "captured_at": "2026-09-01",
    "note": "原始需求"
  }],
  "acceptance": ["金额不一致的采购行项出现在差异表，并显示差额。"],
  "acceptance_en": ["Purchase lines with mismatched amounts appear in the diff table with the variance."],
  "artifact_applicability": {
    "page": {"applicability": "not_applicable", "reason": "本工作包不改变页面。"},
    "api": {"applicability": "required", "reason": "查询合同需要新增差异字段。"},
    "data": {"applicability": "required", "reason": "需要保存发票原始金额。"}
  },
  "verification": ["运行后端测试并以一组不等金额做接口 smoke check。"],
  "delivery_target": "production",
  "delivery_counted": "yes",
  "changelog": "登记采购对账需求并生成待审批工作包。"
}
```

有已识别风险时，`risks` 每项至少提供中英文风险、概率、影响、触发条件和响应：

```json
{
  "risks": [{
    "risk_cn": "供应商发票口径可能改变",
    "risk_en": "The supplier invoice convention may change",
    "probability": "medium",
    "impact": "high",
    "trigger": "供应商改变金额定义",
    "response": "停止实现并提交 CR 重新基线"
  }]
}
```

Author 只创建 `open` 风险，不能替 owner 接受剩余风险。

省略 `requirement_refs` 时，脚本根据新 WP ID 创建 `REQ-...@v1`。复用已有需求：

```json
{
  "requirement_refs": ["REQ-001@v1"],
  "source_refs": ["SRC-001"]
}
```

复用时可省略 `requirements`；如果提供的内容与已登记单一 REQ 不同，脚本拒绝，
防止静默改写版本。

## 9. v1 兼容

未启用 v2 的 pack 继续使用原 spec 和原默认值：

- 默认 `status=todo`。
- 写入 WP 对应需求章节、固定 v1 WBS 列和验收块。
- 不要求 Source/Requirement Register 或生命周期控制文件。

这条兼容路径用于存量 pack；不要以批量开启 v2 的方式让所有仓库门禁同时变红。

## 10. Owner 基线审批交接

Author 完成后向 owner 交付：

- 原始 `SRC-*` 证据和不确定项
- 新建/复用的 `REQ-*@vN`
- proposed WP 的 scope、non-goals、输出、依赖和验收
- `OWNERS.md` 中已解析的 WP owner 与 acceptance owner
- 建议的 delivery target/count
- 七类交付物的 applicability、readiness、owner、refs 和未决项
- 风险、计划日期缺口和可能需要的 CR
- dry-run 的候选 diff、canonical validator 结果和变更文件

owner 审批时才可以：

1. 批准需求版本和验收。
2. 确认范围、计划日期、依赖、风险和交付率分母。
3. 新建或更新批准的 `BL-*`；已有基线发生正式变化时先批准 `CR-*`。
4. 把 WP 的 `baseline_ref` 和计划日期绑定到批准基线。
5. 将 WP 从 `proposed` 改为 `todo`。

上述审批动作不属于 `add_work_package.py`。审批完成前，AI 不得开始实现。

## 11. 停止条件

遇到以下任一情况停止转换并报告：

- 来源不可访问或相互冲突。
- 无法判断是新需求、需求新版本还是缺陷。
- scope/non-goals/验收不足以形成工作包。
- owner 或 acceptance owner 不能在 `OWNERS.md` 解析到具体人员。
- 目标 pack 的 v2 canonical 表头缺失。
- 用户要求 Author 顺便批准 BL/CR、创建 RUN/REL 或开始实现。
- validator 失败且不能在本次 author 范围内安全修复。
