# required-files.json 的来历与边界

## 它为什么在这里

「哪些文件是必需的」是一条**规则**，规则住在规则源里。

它此前住在 `xsos-delivery-control`，而那个仓库是 PRIVATE。后果是 `audit` 在 CI 上
根本跑不起来：2026-09-06 首次真跑，两个仓库同时 `FileNotFoundError`，因为脚本
回落到 `$HOME/work/gitee/xsos-delivery-control`，而 runner 上那个路径不存在。
加 token 检出私有仓与「规则源公开仓库、别再加 token」的既定口径冲突。

切分依据：**`audit` 只需要清单里的 `path`，`repair` 才需要 `template` 指向的模板文件。**
所以清单（规则）在本仓，12 个模板（内容）仍留在治理仓——`repair` 依旧需要它，
找不到时明确报错，不静默降级。

## 一颗还没爆的地雷

搬迁时按 `xsos-delivery-control` 的 **`main`** 分支取，不是 `develop`。两者不同：

```
main      20 条，没有 module.yaml
develop   21 条，多一条 module.yaml，带 "appliesTo": "module"
```

**`appliesTo` 这个字段代码完全没有实现。** `RequiredFile` 只有 `path` 和 `template`，
`load_required_files` 从不读它。`module.yaml` 实际是由 `audit_project` 里另一行硬编码
的 warning 处理的（"required only for runtime modules"）。

所以 `develop` 那一条一旦合进 `main`，`module.yaml` 会变成**所有仓库无条件必需**——
实测 25 个仓库全部多缺 1 个，其中 8 个原本 pass 的直接转 fail，而那行硬编码 warning
还会同时说它「只有运行时模块才需要」，自相矛盾。

清单和读它的代码此前住在两个仓库，所以清单能单方面加字段而代码不知道。搬进同一个仓
之后，加字段和实现字段落在同一个 PR 里，改一边不改另一边会被测试挡住。

**要支持 `appliesTo`，得先定义清楚「什么算运行时模块」——那是设计决定，另立工作包。**
