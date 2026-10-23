# 立包方案格式

小源出方案、玄枢卡片、需求讨论 `/plans` 用同一份结构（与需求讨论后端 `PlanSummary` / `PlanTask` 一致）。

```json
{
  "summary": {
    "title": "送货单打印后状态不更新",
    "problem": "打完标签，送货单列表仍显示「待打印」。",
    "evidence": ["打印记录 3 条已打印（查询结果）", "回调没回写送货单（delivery_print.go:212）"]
  },
  "tasks": [
    {
      "id": "t1",
      "project": "xsos-admin",
      "layer": "backend",
      "title": "打印回调回写送货单状态",
      "why": "delivery_print.go:212 只写了打印记录",
      "ownerId": "legacy_user_4",
      "ownerName": "顾昊",
      "ownerReason": "近 30 天这个仓库提交最多",
      "baseline": {
        "scenario": "仓库打完标签，列表马上显示已打印",
        "items": [{"text": "打完全部标签，状态变「已打印」", "test": "TestPrintCallbackMarksPrinted"}],
        "nonGoals": "不改打印队列"
      }
    }
  ],
  "questions": ["回调要不要重试？"]
}
```

## 开工用的任务文件（start_package.py --task）

方案提交后，每个任务单独开工。任务文件是方案里的一个任务加上来源：

```json
{
  "source": "REQ-7F3A92C1D0B4",
  "taskIndex": 1,
  "proposer": "卢宗康",
  "summary": {"title": "…", "problem": "…", "evidence": []},
  "task": { "…": "同上面 tasks 里的一项；可加 series（包号中段，如 UI）、titleEn、outputs" }
}
```

## 缺项（plan_check.py）

与需求讨论 `planMissing` 逐字一致：标题、项目、前端/后端、责任人、场景、验收条目、每条验收的测试、不做什么。
例：「任务 2的项目」「任务 2的第 1 条验收的测试」。
