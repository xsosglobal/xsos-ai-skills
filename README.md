# xsos-ai-skills

XSOS 团队共享的 AI Agent Skills(跨 Claude Code / Codex / Hermes)。

单一真源:本仓库。每个人/每个工具本地用**软链接**指过来,改了 skill `git push`,同事 `git pull` 即同步,不会各用各的版本。

## 包含的 Skills

| Skill | 说明 |
|------|------|
| `xsos-wbs-pack` | 读/校验/创建/执行 XSOS 双语 WBS Pack(work package、page spec、API/data contract、acceptance、AI 交接) |
| `xsos-project-guard` | 检查/修复/验证 XSOS 项目标准文件、WBS、SOP、change-control、OWNERS、CHANGELOG |
| `xsos-context-pack` | 按 WBS、业务场景、领域能力和有效基线生成可追溯任务上下文；支持动态 WBS 表头、显式跨仓库、Git revision/hash、人工审批证据与敏感路径门禁 |

## 安装(本地软链接)

```bash
git clone git@github.com:xsosglobal/xsos-ai-skills.git ~/work/gitee/xsos-ai-skills
git clone git@github.com:xsosglobal/xsos-delivery-control.git ~/work/gitee/xsos-delivery-control
cd ~/work/gitee/xsos-ai-skills

# Claude Code
ln -sfn "$(pwd)/xsos-wbs-pack" ~/.claude/skills/xsos-wbs-pack
ln -sfn "$(pwd)/xsos-project-guard" ~/.claude/skills/xsos-project-guard
ln -sfn "$(pwd)/xsos-context-pack" ~/.claude/skills/xsos-context-pack
# Codex
ln -sfn "$(pwd)/xsos-wbs-pack" ~/.codex/skills/xsos-wbs-pack
ln -sfn "$(pwd)/xsos-project-guard" ~/.codex/skills/xsos-project-guard
ln -sfn "$(pwd)/xsos-context-pack" ~/.codex/skills/xsos-context-pack
# Hermes(如用)
# ln -sfn "$(pwd)/xsos-wbs-pack" ~/.hermes/skills/xsos-wbs-pack
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
- `xsos-project-guard` 优先读取 `XSOS_DELIVERY_CONTROL_ROOT`，否则查找 `xsos-ai-skills` 同级的 `xsos-delivery-control`，最后回退到 `$HOME/work/gitee/xsos-delivery-control`。
- WBS validator 从当前 `xsos-ai-skills` 仓库内部解析，不依赖安装用户名。

## 约定

- 改 skill → 在本仓库改 → `git commit` + `git push`。
- 不在各自的 `~/.claude/skills` / `~/.codex/skills` 里直接改(那只是软链)。
- 新增团队 skill → 在本仓库新建子目录,更新上面的表 + 安装段。
