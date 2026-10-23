#!/usr/bin/env python3
"""仓库中文名（xsos-package-plan）：只用于显示与称呼，不改仓库真实名字。

用法:
    repo_names.py xsos_admin            # 输出「业务后端 · xsos_admin」
    repo_names.py --json xsos_admin     # 输出 {"repo": ..., "name": ..., "about": ..., "display": ...}
    repo_names.py --all                 # 输出整张表（键含别名）
名称表里没有的仓库照旧显示英文。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

TABLE = Path(__file__).resolve().parents[1] / "references" / "repo-names.json"


def load(path: Path = TABLE) -> dict[str, dict]:
    """返回 {仓库名或别名: {"repo", "name", "about"}}。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    for repo, info in data["repos"].items():
        entry = {"repo": repo, "name": info["name"], "about": info.get("about", "")}
        for key in [repo, *info.get("aliases", [])]:
            out[key] = entry
    return out


def lookup(key: str, table: dict | None = None) -> dict:
    table = load() if table is None else table
    hit = table.get(key)
    if not hit:
        return {"repo": key, "name": "", "about": "", "display": key}
    return {**hit, "display": f"{hit['name']} · {key}"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("repo", nargs="?")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args(argv)
    if args.all:
        print(json.dumps(load(), ensure_ascii=False, indent=2))
        return 0
    if not args.repo:
        ap.error("要给仓库名")
    hit = lookup(args.repo)
    print(json.dumps(hit, ensure_ascii=False) if args.json else hit["display"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
