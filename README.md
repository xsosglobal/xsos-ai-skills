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

## 安装(一键)

Claude Code 和 Codex 一起装好(macOS / Linux / WSL):

```bash
curl -fsSL https://raw.githubusercontent.com/xsosglobal/xsos-ai-skills/main/install.sh | bash
```

脚本做的事:

- 克隆本仓库到 `~/work/gitee/xsos-ai-skills`(已克隆则在干净的 main 上 `git pull --ff-only`;有本地改动不碰)。
- 把**所有带 `SKILL.md` 的一级目录**软链到 `~/.claude/skills/` 和 `~/.codex/skills/`;新增 skill 不用改脚本,重跑即可。
- 同名的**真实目录**先改名为 `<name>.bak-<时间>` 再链,不直接覆盖;别人的 skill 不动。
- 检查 python3 / PyYAML;尝试克隆 `xsos-delivery-control`(私有,没权限只影响 `xsos-project-guard`)。

已克隆过的可以直接 `./install.sh`;`--dry-run` 只打印不改动,`--uninstall` 只删除指向本仓库的软链。
位置可用 `XSOS_SKILLS_DIR`、`CLAUDE_CONFIG_DIR`、`CODEX_HOME`、`XSOS_DELIVERY_CONTROL_ROOT` 覆盖。

装完重启 Claude Code / Codex 生效。

<details>
<summary>手工安装(脚本不能用时)</summary>

```bash
git clone https://github.com/xsosglobal/xsos-ai-skills.git ~/work/gitee/xsos-ai-skills
cd ~/work/gitee/xsos-ai-skills
for d in */; do [ -f "$d/SKILL.md" ] || continue; n=${d%/}
  ln -sfn "$(pwd)/$n" ~/.claude/skills/$n
  ln -sfn "$(pwd)/$n" ~/.codex/skills/$n
done
```

`ln -sfn` 遇到同名**真实目录**会链进目录里面而不是替换它,先手工 `mv` 备份。Hermes 同理链到 `~/.hermes/skills/`。

</details>

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
- 新增团队 skill → 在本仓库新建子目录(带 `SKILL.md`),更新上面的表;安装脚本会自动发现,大家重跑 `./install.sh` 即可。
