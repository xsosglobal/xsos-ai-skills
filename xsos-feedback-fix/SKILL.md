---
name: xsos-feedback-fix
description: Fix a production issue reported through Xiaoyuan feedback (问题反馈) end to end inside a Xuanshu fix chat — locate the root cause, open one fix WBS package per affected repository, implement with tests, and invite the reporter to verify after release. Use when a chat is bound to a feedback item or the user says "修这条反馈 / 修 BUG-xxxx". Do not use it to deploy to production or change production data.
---

# XSOS 反馈修复

一条问题反馈从定位到提交人验证的完整做法。修复对话的工作目录是**代码根目录**，
不是某一个仓库；一个问题可能要改多个仓库。

## 边界（先读）

- 生产：**不连、不查、不改**。需要生产数据或日志时，写出**只读**查询（SQL / grep），
  说明要看什么、为什么，请用户执行后把结果贴回来。
- 上生产、改生产数据：只写方案和脚本，由用户确认并执行。
- 对提交人说的话：只写结果和请对方怎么验证，**不写 WP 编号、PR 号、提交号**。
- 结论先查证再说：「接口有问题」要有日志或代码行作证，别凭文档或记忆下结论。

## 步骤

### 1. 定位根因

1. 读对话上下文里的反馈原文、模块、页面、处理记录；开场消息附带的截图逐张看。
2. 从页面路由找到前端页面，顺着接口找到后端 handler / service，确认数据怎么流。
3. 能复现就复现；复现不了就写出需要用户执行的只读查询。
4. 向用户说明：**现象 → 根因（带文件:行号或日志证据）→ 要改哪几个仓库、各改什么**。
   影响范围（多少条数据、从哪天开始）要给出数字或给出查数字的查询。

用户认可根因和改法之后再进入第 2 步。

### 2. 每个仓库各立一个修复包

- 对每个要改的仓库调用 `wbs_draft`，**必须带 `repo`**（仓库目录名，如 `xsos_admin`、
  `xsos-platform-portal`），不要填 `wp_id`。
- `requirements` 写反馈编号与现象；`scope` 写根因与修法；`non_goals` 写不做的事
  （例如「不改前端」「不修存量数据」）；验收每条都要能判真假，最多 8 条。
- diff 给用户看过、没有异议再调 `wbs_commit`（会弹框，用户点「落盘」才写）。
- 落盘后工作包会**自动关联**到这条反馈；输出里提示关联失败时，用
  `feedback_link_fix(repo, wpId)` 补关联。事先已经建好的包也用它关联。

### 3. 修代码

- 每个仓库在独立分支或 worktree 里改，别动别人的工作区（`local` 分支、`.worktrees/` 下的目录）。
- 补测试，并做反证：把修复换回旧代码，新测试必须失败。
- 按各仓库自己的规矩走（例如 xsos_admin 先 local 实跑再合 develop；有 AI_RULES.md 的先读）。
- 存量数据要修：写成「导出只读 → 生成预览与带原值条件的 UPDATE → 用户确认后执行」三步，
  不要写一步到位的写库脚本。

### 4. 上线后邀请提交人验证

- 用户确认修复已上生产后，调用 `feedback_invite_verify`：
  - `evidence`：生产发布证据的 HTTPS 链接（发布 PR 或流水线）。
  - `note`：给提交人的说明，例如「问题已修复并上线，S62 的数据也已恢复。请刷新后再复制一次试试，没问题点『已恢复正常』即可。」
- 工具会弹框请用户确认；提交人在小源收到验证卡片，点「已恢复正常」反馈自动关闭，
  点「仍有问题」反馈重开，回到第 1 步。
- **不要**自己关闭反馈，也不要用「说明原因并关闭」代替验证。
