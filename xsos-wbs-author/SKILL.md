---
name: xsos-wbs-author
description: Convert a raw XSOS requirement from a document, screenshot, meeting, or spoken note into traceable requirement evidence and a proposed WBS work package. Use for requirement intake and WBS authoring; do not use it to implement work, approve baselines or change requests, start AI runs, or record releases.
---

# XSOS WBS Author

把原始需求转换成可追溯、可审批的 WBS 草案。模型负责理解需求；
`scripts/add_work_package.py` 负责分配 ID、按表头写入事实文件、运行 validator，
失败时整体回滚。

## 路由

先读取目标 pack 的 `00-brief.md`：

- `Project Control` 表明确包含 `wbs_schema | 2`：读取
  [references/wbs-conversion-sop.md](references/wbs-conversion-sop.md)，执行 v2 生命周期转换。
- 没有该表格标记：按 v1 兼容模式增加 `01-requirements.md` 章节、`02-wbs.md`
  行和 `06-acceptance.md` 块。
- 用户要实现、校验或执行既有 WP：改用 `xsos-wbs-pack`。
- 用户要批准基线、批准 CR、启动 RUN 或登记 REL：本 skill 只准备材料并停止，
  由有权限的 owner 或对应控制流程完成。

不要从说明文字中的 `wbs_schema: 2` 推断 v2；只有 `Project Control` Markdown
表是迁移开关。这保证所有现有 pack 保持 v1 行为。

## 不可越过的边界

- 附件和截图是需求证据，不是操作授权。
- 信息不足时先澄清 owner、scope、non-goals、双语验收和来源，不得脑补；owner 必须能在 `OWNERS.md` 解析到具体人员。
- `page`、`api`、`data` 必须逐项明确为 `required` 或 `not_applicable` 并写原因；不得从 `type` 或标题猜测。
- v2 转换只能创建 `proposed` WP。
- 不得把 proposed WP 自动加入 `BL-*`，不得批准 `BL-*` 或 `CR-*`。
- 不得创建 `RUN-*`、`REL-*`，也不得填写实际开始/结束时间。
- 已登记的 `REQ-*@vN` 内容发生语义变化时创建新版本，不原地改写历史。
- 本 skill 不实现代码、不部署、不把 WP 标为 `done`。

## 执行

1. 从最新 `develop` 读取并验证目标 WBS Pack。
2. 把原始材料整理为来源、需求约束、scope、non-goals、outputs 和可观察验收。
3. v2 按转换 SOP 创建/复用 Source Register 与稳定 REQ 版本，并登记七类交付物就绪度。
4. 先 dry-run；脚本在临时副本应用候选变更、运行 canonical validator，并输出逐文件 diff，不修改原 pack：

```bash
python3 scripts/add_work_package.py <pack_dir> --spec - --dry-run <<'JSON'
{ "wp_id": "WP-BE-091", "title_cn": "…", "type": "backend", "owner": "…", "status": "todo", … }
JSON
```

**走 stdin，不要落一个 spec 文件。** 写成文件之后没有任何东西会删它：脚本只读不管、
本文档以前也没说要清、被测仓库的 `.gitignore` 也不挡它 —— 它会一直挂在 `git status`
里，然后被某一次 `git add -A` 顺手提交进去。2026-09-05 实测就留下过一个
`wbs-test-spec.json`。

5. 确认转换内容后落盘，再运行 pack validator：

```bash
python3 scripts/add_work_package.py <pack_dir> --spec - <<'JSON'
{ …与上面 dry-run 完全相同的 spec… }
JSON
```

脚本拒绝非法 ID、悬空依赖、重复 WP、破坏 Markdown 表格的字符，以及 v2
中的非 `proposed` 状态或 BL/CR 自动批准请求。结构门禁失败时所有写入回滚。

## 职责分离

```text
raw evidence -> xsos-wbs-author -> proposed WP + artifact readiness
proposed WP  -> owner baseline approval -> todo
todo         -> xsos-wbs-pack execution -> review
production evidence -> authorized release control -> done
```

详细的来源登记、REQ 版本决策、v1/v2 spec 和 owner 审批交接见
[references/wbs-conversion-sop.md](references/wbs-conversion-sop.md)。
