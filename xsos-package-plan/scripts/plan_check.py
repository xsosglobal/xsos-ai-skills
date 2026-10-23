#!/usr/bin/env python3
"""立包方案的缺项检查（xsos-package-plan）。

方案格式见 references/plan-format.md。缺项说法与需求讨论后端 planMissing 逐字一致，
玄枢、原生客户端、Claude Code / Codex 都只用这一份，不各写一套。

用法:
    plan_check.py < plan.json            # 输出 {"missing": [...], "ok": bool}
    plan_check.py --tasks < tasks.json   # 输入直接是任务数组
"""
from __future__ import annotations

import argparse
import json
import sys

LAYERS = ("frontend", "backend")


def _text(v) -> str:
    return v.strip() if isinstance(v, str) else ""


def missing(tasks: list) -> list[str]:
    """还没填完的地方；空列表表示可以提交。"""
    out: list[str] = []
    if not tasks:
        return ["至少一个任务"]
    for i, t in enumerate(tasks):
        t = t if isinstance(t, dict) else {}
        n = f"任务 {i + 1}的"
        base = t.get("baseline") if isinstance(t.get("baseline"), dict) else {}
        items = [x for x in (base.get("items") or []) if isinstance(x, dict)]
        if not _text(t.get("title")):
            out.append(n + "标题")
        if not _text(t.get("project")):
            out.append(n + "项目")
        if t.get("layer") not in LAYERS:
            out.append(n + "前端/后端")
        if not _text(t.get("ownerId")):
            out.append(n + "责任人")
        if not _text(base.get("scenario")):
            out.append(n + "场景")
        if not items:
            out.append(n + "验收条目")
        for j, it in enumerate(items):
            if not _text(it.get("test")):
                out.append(f"{n}第 {j + 1} 条验收的测试")
        if not _text(base.get("nonGoals")):
            out.append(n + "不做什么")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tasks", action="store_true", help="输入是任务数组而不是整份方案")
    args = ap.parse_args(argv)
    try:
        value = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": f"不是合法 JSON：{e}"}, ensure_ascii=False))
        return 2
    tasks = value if args.tasks else (value.get("tasks") if isinstance(value, dict) else None)
    if not isinstance(tasks, list):
        print(json.dumps({"ok": False, "error": "缺少 tasks 数组"}, ensure_ascii=False))
        return 2
    miss = missing(tasks)
    print(json.dumps({"ok": not miss, "missing": miss}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
