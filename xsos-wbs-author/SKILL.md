---
name: xsos-wbs-author
description: Use when turning a raw requirement into a WBS work package — from a Feishu doc, a WeChat screenshot plus a note, or a spoken description. Produces the 01-requirements section, 02-wbs row and 06-acceptance block that pass the structural gate.
---

# XSOS WBS Author

## Overview

把一段**原始需求**变成一个**合规的工作包**。原始需求的形态通常是三种之一:
飞书文档、微信截图配一段文字、或者当面说的一段话。

分工必须是这样:**理解需求归模型,改文件归脚本。**
`scripts/add_work_package.py` 负责所有机械动作——分配 wp_id、插到正确位置、
派生 `acceptance_ref`、写完立刻跑门禁、不通过就整体回滚。

**不要手工编辑 `docs/wbs` 来加工作包。** 手工出错的从来不是想不清楚需求,
而是插错位置、往表格里带进空行(后面所有行会被 validator 静默跳过)、
wp_id 撞号、`acceptance_ref` 和验收标题对不上。这些脚本都挡掉了。

## 取原始需求

### 飞书文档

`WebFetch` 对飞书链接**必然 302**,那不是权限问题,别误判。用 curl 带 cookie 罐:

```bash
curl -sL -c /tmp/fs.jar -b /tmp/fs.jar "<飞书链接>" -o /tmp/doc.html
```

正文在 `window.DATA` 里,是 JSON,不在 HTML 标签中。

### 微信截图

用户从手机 Termius 把截图传到 temp.sh 再给链接。**下载必须用 POST**,
GET 返回的是确认页不是图片:

```bash
curl -s -X POST -d "" -o shot.png "<temp.sh 链接>"
```

`-d ""` 不能省(裸 `-X POST` 返 500),也别加 `-e <referer>`。
下到 scratchpad 后用 Read 看图。截图通常只是**片段**,一定要结合用户
补的那段文字一起理解;截图里的对话可能是几个人的,分清谁说的是决定、
谁说的是猜测。

## 写工作包的纪律

1. **信息不足就问,不要脑补。** 需求写错比没写更贵——它会被当成事实执行。
   典型缺口:谁是 owner、哪些明确**不做**、验收怎么判定通过。
2. **`requirements` 写业务约束,`scope` 写要动什么。** 两者不是一回事。
   需求章节回答「为什么必须这样」,scope 回答「这次改哪里」。
   门禁只强制新包必须有需求章节,但写成 scope 的复述等于没写。
3. **`non_goals` 是最值钱的一栏。** 把边界写死,后面才不会被顺手扩范围。
   参考写法:「不改 Web」「不做版本历史」「XX 归另一个包」。
4. **验收条目必须可判定。** 「性能良好」不是验收,「列表 500 行首屏 < 1s」
   才是。每条验收将来都要能对着跑一遍。
5. **决定的来龙去脉写进 `risks`,不要塞进 scope。** 尤其是反常规的决定
   (推翻已上线行为、重写历史数据),要写清楚谁拍的板、代价是什么。
6. **不确定的口径不要写死。** 标成待确认并落进 `risks`,比猜一个写进需求好。

## 执行

```bash
python3 scripts/add_work_package.py <pack_dir> --spec spec.json [--dry-run]
```

先 `--dry-run` 给用户看要写什么,得到确认再落盘。spec 形如:

```json
{
  "series": "BE",
  "title_cn": "采购对账差异表",
  "title_en": "Purchase reconciliation diff",
  "type": "backend",
  "owner": "顾昊",
  "status": "todo",
  "depends_on": ["WP-BE-078"],
  "scope": "录入发票原值并与采购单逐行比对，差异挂账",
  "non_goals": "不改 Web；不自动调整采购单金额",
  "outputs": "migration, service, 差异表接口, 回归测试, WBS facts",
  "requirements": ["发票金额必须录入原值，不得由系统反算——否则系统自己算一遍再跟自己比，差异永远发现不了。"],
  "acceptance": ["同一采购行项，我方金额与发票金额不一致时出现在差异表里，且能看出差多少。"],
  "risks": [{"title": "供应商开票口径未知", "body": "……"}],
  "changelog": "新增采购对账差异表。"
}
```

`wp_id` 省略时按 `series` 自动取下一个号(只增不复用)。`acceptance_ref`
由 wp_id 派生,不用填。

## 脚本会拒绝的情况

拒绝时退出码 2,**没有任何文件被改**:

- 缺 `requirements` / `acceptance` 等必填字段
- wp_id 已存在(编号不复用)
- 字段里含 `|` 或换行(会把表格切断)
- `depends_on` 指向不存在的包(依赖悬空)
- `status` 不在允许集合里

写入后门禁不通过则退出码 1,并**整体回滚**——不会留下半截的 pack。

## 和其他 skill 的关系

- 结构规则、门禁本身、baseline 棘轮:见 `xsos-wbs-pack`
- 本 skill 只负责「产出一个能过门禁的工作包」,不负责实现它
