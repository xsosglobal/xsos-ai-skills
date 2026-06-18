# xsos-ai-skills

XSOS 团队共享的 AI Agent Skills(跨 Claude Code / Codex / Hermes)。

单一真源:本仓库。每个人/每个工具本地用**软链接**指过来,改了 skill `git push`,同事 `git pull` 即同步,不会各用各的版本。

## 包含的 Skills

| Skill | 说明 |
|------|------|
| `xsos-wbs-pack` | 读/校验/创建/执行 XSOS 双语 WBS Pack(work package、page spec、API/data contract、acceptance、AI 交接) |

## 安装(本地软链接)

```bash
git clone git@github.com:xsosglobal/xsos-ai-skills.git ~/work/gitee/xsos-ai-skills
cd ~/work/gitee/xsos-ai-skills

# Claude Code
ln -sfn "$(pwd)/xsos-wbs-pack" ~/.claude/skills/xsos-wbs-pack
# Codex
ln -sfn "$(pwd)/xsos-wbs-pack" ~/.codex/skills/xsos-wbs-pack
# Hermes(如用)
# ln -sfn "$(pwd)/xsos-wbs-pack" ~/.hermes/skills/xsos-wbs-pack
```

> `ln -sfn` 会覆盖已有的同名软链(幂等)。若原来是**真实目录**(不是软链),请先备份再链:
> `mv ~/.codex/skills/xsos-wbs-pack ~/.codex/skills/xsos-wbs-pack.bak`

## 更新

```bash
cd ~/work/gitee/xsos-ai-skills && git pull   # 所有软链过来的工具自动用上新版
```

## 约定

- 改 skill → 在本仓库改 → `git commit` + `git push`。
- 不在各自的 `~/.claude/skills` / `~/.codex/skills` 里直接改(那只是软链)。
- 新增团队 skill → 在本仓库新建子目录,更新上面的表 + 安装段。
