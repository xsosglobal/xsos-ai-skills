---
name: xsos-package-plan
description: Turn a development conversation into a package plan (one-sentence requirement plus tasks split by repository × frontend/backend, each with an owner and a baseline whose acceptance items name their tests), check it for missing fields, submit it through the XSOS MCP server (submit_plan), list my tasks (my_tasks), start work on a submitted task (reserve a global package number, isolated worktree, copy the baseline into a WBS package, draft PR), report package progress (update_progress / get_progress), and record which packages a deploy shipped. Use when the user says "立包 / 把这次聊的整理成方案 / 提交方案 / 我的任务 / 开工 / 落包 / 更新进度 / 把某个包改成… / 发布登记", or when Xuanshu calls draft_package_plan. Do not use it to approve baselines, write implementation code, merge, or deploy.
---

# XSOS 立包（会话立包 · 开工落包 · 发布登记）

一套规则、三个脚本，所有 AI（玄枢小源、Claude Code、Codex）都用这一份，不各写一套。
玄枢只做界面（方案卡片、看板按钮），规则和机械动作都在这里。

| 做什么 | 用什么 |
|---|---|
| 把这次会话聊清楚的问题整理成方案 | 本文「出方案」一节 + `references/plan-format.md` |
| 检查方案缺什么 | `scripts/plan_check.py` |
| 提交方案（拿 REQ 编号，任务进看板） | XSOS MCP 工具 `submit_plan`（玄枢里是方案卡片的「提交」） |
| 看分给我的任务 | XSOS MCP 工具 `my_tasks` |
| 更新 / 查看包进度 | XSOS MCP 工具 `update_progress` / `get_progress` |
| 负责人开工：取号、建分支、写包、草稿 PR | `scripts/start_package.py` |
| 发布后登记发出去了哪些包 | `scripts/record_release.py` |
| 称呼仓库 | `scripts/repo_names.py`（仓库中文名表 `references/repo-names.json`） |

## 边界（先读）

- **只起草，不替人拍板。** 方案由发起人在卡片上改完点「提交」才生效；开工由负责人点「开工」并确认预演才执行。不要声称已提交、已开工。
- **依据只用这次会话里有的**：对话、截图、查询结果、代码位置、同事回复。没有出处的不写；拿不准的写进 `questions`，不要自己定。
- **不改基线、不写业务代码、不合并、不发布。** 开工落包照抄已提交的基线；要改基线由发起人改方案重新提交。
- 来源必须是可反查的编号：`REQ-` / `BUG-` 加 12 位十六进制。不知道就问人，不许编。

## 出方案

1. 一句话需求（`title`）、问题（`problem`）、依据（`evidence`，每条写出处）。
2. **按「项目 × 前端/后端」拆任务**，一个任务只做一件事；同一仓库前后端是两个任务。
3. 每个任务写：
   - `project`：仓库名（称呼时用中文名，`repo_names.py xsos_admin` → 「业务后端 · xsos_admin」）
   - `layer`：`frontend` 或 `backend`
   - `title`、`why`（为什么改这个项目：引用代码位置或讨论原话）
   - `owner` + `ownerReason`：只从同公司开发人员里选（看最近谁改这段代码、谁在会话里回答过），没把握就留空
   - 基线：`scenario`（从用户场景写）、`items`（验收条目，**每条配一个测试名**）、`nonGoals`（不做什么）
4. 跑 `plan_check.py` 看缺什么；缺的在卡片上标红，填完才能提交。

方案 JSON 的完整格式见 [references/plan-format.md](references/plan-format.md)。

## 在 Codex / Claude Code 里用（XSOS 插件）

装了 XSOS 插件的同事，这几件事通过插件自带的 `xsos` MCP 服务以**本人身份**完成，不需要玄枢：

1. **先确认身份**：调 `whoami`。报「请先登录 XSOS / 登录已失效」或看不到 `xsos` 的工具时，**不要自己想办法绕过**，告诉用户登录：
   - Codex 桌面版：插件 → XSOS → 连接（弹出浏览器登录 XSOS）；Codex 命令行：`codex mcp login xsos`
   - Claude Code：输入 `/mcp`，选 xsos → Authenticate
   `developer` 为 false 时立包、报进度都会被拒，直接告诉用户需要开通开发平台。
2. **提交方案**：按上面「出方案」整理好，先跑 `plan_check.py` 补齐缺项，**把方案给用户看、用户说提交再调 `submit_plan`**（提交即生效，不能替人拍板）。负责人不知道 ID 时填 `ownerName`（必须是本公司开发人员）。返回的 REQ 编号告诉用户。
3. **我的任务**：`my_tasks`（默认分给我的；`as=creator` 看我发起的）。
4. **开工落包**：仍在本机跑下面的 `start_package.py`（要在用户电脑上建分支、写包、开草稿 PR，MCP 做不了）；任务文件的 `source` 用提交返回的 REQ 编号。
5. **更新进度**：要仓库名（GitHub 仓库名，如 xsos-admin）、包号、状态（todo 待开始 / in_progress 进行中 / review 待验收 / done 已完成 / blocked 阻塞）和一句说明，缺哪个就问，**不要编**；调 `update_progress`，再 `get_progress` 给用户看。进度只记「谁在什么时候说了什么」，不改仓库 02-wbs；包真的做完仍按上生产时的基线比对判 done。

## 开工落包

负责人在任务看板点「开工」后，玄枢调用；不走玄枢时也可以直接跑：

```bash
python3 scripts/start_package.py --repo-dir ~/work/gitee/xsos_admin --task task.json --dry-run   # 先预演
python3 scripts/start_package.py --repo-dir ~/work/gitee/xsos_admin --task task.json             # 确认后执行
```

- 取号查五处：集成分支 WBS、远端分支名、远端预留标记 `refs/xsos/wp/*`、PR 标题、本机已有的包；任何一处查不到就停。
- 往远端推预留标记 `refs/xsos/wp/<包号>` 当全局锁，只有第一个推得上去；被占就顺延。推送前再核对一次锁还是自己的，被抢就换号重写（最多 3 次）。
- 在独立工作树（默认 `~/.xsos/worktrees/<仓库>-<包号>`）建分支 `feat/<包号>-<简称>`，**主工作目录不动**。
- 写包调用 `xsos-wbs-author/scripts/add_work_package.py`，体检不过整体回滚；来源行写「REQ-… 任务 n」，看板靠它把任务和包对上。
- 提交、推送、开**草稿 PR** 占号；代码写完再转正式 PR。
- 每步输出一行 JSON；失败停在那一步，**再跑一次从断处继续**，不会重复建包（状态在 `~/.xsos/package-start/`）。
- 玄枢那类每个 PR 要带交付说明的仓库，自动补一份 `docs/wbs/changes/<包号>-package.json`。

## 发布登记

每次发到测试或生产的**最后一步**调用（CI 和手动发布脚本都一样）：

```bash
XSOS_RELEASE_KEY=*** python3 scripts/record_release.py --repo-dir . --env test --version "$GITHUB_SHA"
```

- 按提交里的 `Work-Package: WP-…` 尾注（和 `feat(WP-…)` 标题）算出这次比上次多发出去的包，登记到需求讨论 `POST /releases`。
- 第一次登记按这个版本 02-wbs 里已有的包算；上次登记的版本不在这次历史里（回滚）就只登记版本。
- **登记失败只告警，不让发布失败**；只说明「发到哪了」，不改 02-wbs status、不判 done（done 仍按上生产时的基线比对）。
