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
- v1 的 spec 必须带 `source`（写进需求章节的「来源：」行）：小源反馈写 `BUG-xxxxxxxxxxxx`，需求讨论帖子写 `REQ-xxxxxxxxxxxx`，都没有时写「内部：<原因>」。**不知道编号就问人，不得编造**；仓库自编的 `REQ-001` 不算。
- `page`、`api`、`data` 必须逐项明确为 `required` 或 `not_applicable` 并写原因；不得从 `type` 或标题猜测。
- v2 转换只能创建 `proposed` WP。
- 不得把 proposed WP 自动加入 `BL-*`，不得批准 `BL-*` 或 `CR-*`。
- 不得创建 `RUN-*`、`REL-*`，也不得填写实际开始/结束时间。
- 已登记的 `REQ-*@vN` 内容发生语义变化时创建新版本，不原地改写历史。
- 本 skill 不实现代码、不部署、不把 WP 标为 `done`。

## 一个包只做一件事

顾昊 2026-10-16 定，立包时就要守：

- **一个 WBS 包只做一件事。** 验收条目都围绕同一个功能；标题里用「、」「和」「与」并列了几个动作，通常就是几件事。
- **owner 只写一个负责人；提出人、协作人写在需求章节里**（顾昊 2026-10-20 定）：spec 可带 `proposer`（谁发现或提出，常是业务同事或联调的前端，不要求在 `OWNERS.md` 登记）和 `collaborators`（还有谁一起做或验收，最多 3 人，不写负责人本人），分别写成「来源：」下面的「提出人：」「协作人：」两行，多人用顿号分隔。自己发现的 BUG 没有反馈时，来源写「内部：<谁哪天发现了什么>」，提出人写发现的人。
- **一个需求或 BUG 含几件事，就拆成几个包，** 每个包的「来源：」行写**同一个** `BUG-`/`REQ-` 编号，反查时能一次找全。
- **只交付了一部分时拆包，不设「部分完成」状态：** 已交付的部分收窄为原包（发布后标 `done`），剩余拆成新包，新包「来源：」行写原来的 BUG/REQ 编号并注明「拆自 WP-XX-NNN」。
- `add_work_package.py` 发现标题并列多个动作、或验收超过 8 条时会提示（不拒绝写入），validator 对未完工的包给出同样的警告。拆不拆由人决定，但要有理由。

## 执行

1. 从最新 `develop` 读取并验证目标 WBS Pack。
2. **先看同模块的已有包再动手**：建包前用重复扫描列出同业务词的已有包，
   按 `references/module-aggregation.md` 判断——同一模块不代表同一需求，
   比较它们的交付范围和验收：范围重叠就改原包并留变更记录，独立新能力才新建。
3. 把原始材料整理为来源、需求约束、scope、non-goals、outputs 和可观察验收（结构见下文「立包基线」）。
4. v2 按转换 SOP 创建/复用 Source Register 与稳定 REQ 版本，并登记七类交付物就绪度。
5. 先 dry-run；脚本在临时副本应用候选变更、运行 canonical validator，并输出逐文件 diff，不修改原 pack。
   输出开头若有「建包体检」，逐条处理或说明为什么不改，再重跑 dry-run：

```bash
python3 scripts/add_work_package.py <pack_dir> --spec - --dry-run <<'JSON'
{ "wp_id": "WP-BE-091", "title_cn": "…", "type": "backend", "owner": "…", "status": "todo", … }
JSON
```

**走 stdin，不要落一个 spec 文件。** 写成文件之后没有任何东西会删它：脚本只读不管、
本文档以前也没说要清、被测仓库的 `.gitignore` 也不挡它 —— 它会一直挂在 `git status`
里，然后被某一次 `git add -A` 顺手提交进去。2026-09-05 实测就留下过一个
`wbs-test-spec.json`。

6. 确认转换内容后落盘，再运行 pack validator：

```bash
python3 scripts/add_work_package.py <pack_dir> --spec - <<'JSON'
{ …与上面 dry-run 完全相同的 spec… }
JSON
```

脚本拒绝非法 ID、悬空依赖、重复 WP、破坏 Markdown 表格的字符，以及 v2
中的非 `proposed` 状态或 BL/CR 自动批准请求。结构门禁失败时所有写入回滚。

## 立包基线

所有人（含同事的 AI 会话）立包都按这一节，不因人而异。

**时机与粒度**

- **先立包再写代码。** 需求和方案一确认，第一步就是立包；哪怕「先试一下」也先立。
  先写后补，包就成了照着代码写的说明，起不到事先约束范围的作用。
  验收条目目前不需要先等负责人看过，立完即可开工。
- **跨仓库的需求每个仓库各立一个包**，各自在本仓 `docs/wbs` 里；仓库之间的依赖写进
  `scope`（例如「对接 xsos_admin 仓 WP-BE-177 的 DELETE …」），不写进 `depends_on`
  （`depends_on` 只能引用本 pack 里的包，否则是悬空依赖）。
- 一个包 = 一件事 = 一个可独立验收的交付物（见上文「一个包只做一件事」），不是一次动作；迁移、联调、测试是包内工作项（见模块聚合规范）。
  一个需求或 BUG 可以拆出多个包，各包「来源：」行写同一个编号。
- 编号由脚本分配（两段式 `WP-<系列>-<三位数>`，验收号 `AC-…` 自动派生），不要手填；
  push 前若集成分支已被别人占了同号，回滚 `docs/wbs` 后在最新 develop 上重新立。

**一个包的基本结构（v1，当前所有仓库都是 v1）**

脚本一次写三处，缺一处门禁会红：

| 文件 | 写什么 |
|---|---|
| `02-wbs.md` 一行 | `wp_id` `title_cn` `title_en` `type` `owner` `status` `depends_on` `scope` `non_goals` `acceptance_ref` `outputs` |
| `01-requirements.md` 一节 `## WP-… 标题` | 来源（谁、哪天、因为什么提出）与业务口径；spec 的 `requirements` |
| `06-acceptance.md` 一节 `## AC-… 标题` | `中文：` / `English:` / `Verification:` 三段；spec 的 `acceptance` / `acceptance_en` / `verification` |

传了 `changelog` 时另写 `CHANGELOG.md`。各字段的要求：

- `type`：`backend` `frontend` `fullstack` `integration` `documentation` `qa` `poc` `release`，决定系列（BE/FE/FS/INTEG/DOC/QA/POC/REL）。
- `owner`：必须能在 `OWNERS.md` 解析到具体人。
- `scope`：做什么，写到能当越界判据——改哪个仓、哪个页面/接口、对接谁。
- `non_goals`：不做什么，必须写；不能是「无」「待定」。
- 验收：每条是一个能判定真假的可观察结果（按钮出现/不出现、请求参数、提示文案、刷新与否），
  不写「显示正常」「体验良好」；一个包不超过 8 条，超过就拆包。中英文条数一一对应。
- `Verification:`：**立包时就要写**，和 scope、non_goals、验收一起构成这个包的「完成标准」（基线），
  先写完成标准再写代码。每条验收对应到测试：测试文件路径和测试名立包时先定下，实现时落地；
  **每条中文验收末尾标「（测试：测试名）」**，一条可挂几个（顿号分隔），一个测试也可覆盖几条，
  名称必须出现在 `Verification:` 列表里；人工验收标「（测试：人工）」并在列表写 `- 人工：…`。
  也可以在 `Verification:` 那行末尾写「（验收 1、3）」按编号覆盖。玄枢修复对话按此逐条核对，
  缺的会列进「待补资料」；2026-10-21（立包标准定下那天）结束时已是 `done` 的包视同已覆盖（顾昊 2026-10-22 定）。
  发布时 `check_release_baseline.py` 按它核对能否标 `done`。自动化证据写成
  ``- `相对路径` 测试名``（反引号只包路径，测试名放外面）；人工证据以 `- 人工：` 开头，
  写清做了什么、没做什么（例如「真实后端联调与线上发布未做」）。

脚本 dry-run 的「建包体检」会点出缺字段和含糊措辞，只提醒不拦。

**生命周期**：见 `xsos-wbs-pack` 的「v1 生命周期」——立包时 `status` 一般是 `todo`
（项目 owner 本人提的本项目需求），非 owner 提的或改全局规则的用 `proposed`。

## 职责分离

```text
raw evidence -> xsos-wbs-author -> proposed WP + artifact readiness
proposed WP  -> owner baseline approval -> todo
todo         -> xsos-wbs-pack execution -> review
release PR + baseline check (check_release_baseline.py) -> done
```

详细的来源登记、REQ 版本决策、v1/v2 spec 和 owner 审批交接见
[references/wbs-conversion-sop.md](references/wbs-conversion-sop.md)。
