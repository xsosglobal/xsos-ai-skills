# xsos-ai-skills

XSOS 团队共享的 AI Agent Skills(跨 Claude Code / Codex / Hermes)。

单一真源:本仓库。每个人/每个工具本地用**软链接**指过来,改了 skill `git push`,同事 `git pull` 即同步,不会各用各的版本。

## 包含的 Skills

| Skill | 说明 |
|------|------|
| `xsos-wbs-pack` | 读/校验/创建/执行 XSOS 双语 WBS Pack(work package、page spec、API/data contract、acceptance、AI 交接) |
| `xsos-wbs-author` | 把文档、截图或口述原始需求转成带来源、稳定 REQ 版本、验收标准的 proposed WBS 工作包，交由 owner 批准基线 |
| `xsos-project-guard` | 检查/修复/验证 XSOS 项目标准文件、WBS、SOP、change-control、OWNERS、CHANGELOG |
| `xsos-context-pack` | 按 WBS、业务场景、领域能力和有效基线生成可追溯任务上下文；支持动态 WBS 表头、显式跨仓库、Git revision/hash、人工审批证据与敏感路径门禁 |
| `xsos-feedback-fix` | 在玄枢修复对话里处理一条小源问题反馈：定位根因、每个仓库各立一个修复包、改代码与反证、上线后邀请提交人验证；不连生产、不上生产 |

## 一条命令安装或更新（推荐）

```bash
curl -fsSL https://raw.githubusercontent.com/xsosglobal/xsos-ai-skills/main/install.sh | bash
```

- 首次运行克隆到 `~/.xsos-ai-skills`，把五个 skill 软链进 `~/.claude/skills`（Claude Code）和 `~/.codex/skills`（Codex）；已经按下面手工方式装过的，会沿用原来那份克隆。
- 再次运行就是更新：只在克隆位于 `main`、没有未提交改动时快进；否则提示原因并停止，不会覆盖你的改动或切分支。
- 目标位置已被别的目录或软链占用时不覆盖，只提示。
- 立包脚本 `add_work_package.py` 每次运行会检查本机是否落后 GitHub main，落后就提示更新命令（只提示不自动拉，离线时静默跳过；设 `XSOS_SKILLS_SKIP_UPDATE_CHECK=1` 可关闭）。

## 安装(本地软链接)

```bash
git clone git@github.com:xsosglobal/xsos-ai-skills.git ~/work/gitee/xsos-ai-skills
git clone git@github.com:xsosglobal/xsos-delivery-control.git ~/work/gitee/xsos-delivery-control
cd ~/work/gitee/xsos-ai-skills

# Claude Code
ln -sfn "$(pwd)/xsos-wbs-pack" ~/.claude/skills/xsos-wbs-pack
ln -sfn "$(pwd)/xsos-wbs-author" ~/.claude/skills/xsos-wbs-author
ln -sfn "$(pwd)/xsos-project-guard" ~/.claude/skills/xsos-project-guard
ln -sfn "$(pwd)/xsos-context-pack" ~/.claude/skills/xsos-context-pack
# Codex
ln -sfn "$(pwd)/xsos-wbs-pack" ~/.codex/skills/xsos-wbs-pack
ln -sfn "$(pwd)/xsos-wbs-author" ~/.codex/skills/xsos-wbs-author
ln -sfn "$(pwd)/xsos-project-guard" ~/.codex/skills/xsos-project-guard
ln -sfn "$(pwd)/xsos-context-pack" ~/.codex/skills/xsos-context-pack
# Hermes(如用)
# ln -sfn "$(pwd)/xsos-wbs-pack" ~/.hermes/skills/xsos-wbs-pack
# ln -sfn "$(pwd)/xsos-wbs-author" ~/.hermes/skills/xsos-wbs-author
# ln -sfn "$(pwd)/xsos-project-guard" ~/.hermes/skills/xsos-project-guard
```

> `ln -sfn` 会覆盖已有的同名软链(幂等)。若原来是**真实目录**(不是软链),请先备份再链:
> `mv ~/.codex/skills/xsos-wbs-pack ~/.codex/skills/xsos-wbs-pack.bak`

## 更新

```bash
cd ~/work/gitee/xsos-ai-skills && git pull   # 所有软链过来的工具自动用上新版
```

## 可移植路径

- Skill 和脚本不得硬编码个人 home 目录。
- `xsos-project-guard` 只从线上 `xsosglobal/xsos-delivery-control` 的 `main` 读规则与模板（经 `gh api`，需要组织权限并 `gh auth login`），不找、也不回退本机克隆。
- WBS validator 从当前 `xsos-ai-skills` 仓库内部解析，不依赖安装用户名。

## 约定

- 改 skill → 在本仓库改 → `git commit` + `git push`。
- 不在各自的 `~/.claude/skills` / `~/.codex/skills` 里直接改(那只是软链)。
- 新增团队 skill → 在本仓库新建子目录,更新上面的表 + 安装段。
