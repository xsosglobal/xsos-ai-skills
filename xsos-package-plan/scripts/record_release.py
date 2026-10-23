#!/usr/bin/env python3
"""发布登记（xsos-package-plan）：每次发到测试或生产后，登记这次发出去了哪些工作包。

为什么要有这个脚本：02-wbs 的状态靠手填，总是落后于真实发布；看板想知道一个包是不是
已经发到测试、发到生产，只能猜分支。这里在每次发布的最后一步，按提交里的
`Work-Package: WP-…` 尾注算出「这次比上次多发出去的包」，登记到需求讨论
（POST /releases），所有人的看板、会话卡片、需求与 BUG 都读这一份。

只说明「发到哪了」，不改 02-wbs 的 status、不判 done（done 仍按上生产时的基线比对）。
登记失败只告警、退出码 0，不让发布失败（加 --strict 才会失败）。

用法:
    record_release.py --repo-dir . --env test --version $(git rev-parse HEAD)
    record_release.py --repo-dir . --env production --version <sha> --dry-run
环境变量:
    XSOS_DISCUSSION_URL   需求讨论接口根地址，默认 https://platform.szsyforging.com/api/v1/discussion
    XSOS_RELEASE_KEY      发布登记密钥（Bearer），由顾昊配置到各仓库 CI secret / 发布机
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_URL = "https://platform.szsyforging.com/api/v1/discussion"
WP_RE = re.compile(r"\bWP-[A-Z]+-\d{3,5}\b")
TRAILER_RE = re.compile(r"^Work-Package:\s*(WP-[A-Z]+-\d{3,5})\s*$", re.M)


class LedgerError(Exception):
    pass


def git(repo: Path, *args: str) -> str:
    p = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    if p.returncode != 0:
        raise LedgerError(f"git {' '.join(args[:2])} 失败：{p.stderr.strip()[:300]}")
    return p.stdout


def repo_name(repo: Path) -> str:
    url = git(repo, "config", "--get", "remote.origin.url").strip()
    return re.sub(r"\.git$", "", url.rstrip("/").split("/")[-1].split(":")[-1])


def packages_between(repo: Path, previous: str, version: str) -> list[str]:
    """previous..version 之间提交里的包：Work-Package 尾注，以及标题里 feat(WP-…) 这类写法。"""
    rng = f"{previous}..{version}" if previous else version
    log = git(repo, "log", "--format=%s%n%b%n--", rng)
    found = set(TRAILER_RE.findall(log))
    for subject in git(repo, "log", "--format=%s", rng).splitlines():
        m = re.match(r"^\w+\((WP-[A-Z]+-\d{3,5})\)", subject)
        if m:
            found.add(m.group(1))
    return sorted(found)


def packages_in_pack(repo: Path, version: str) -> list[str]:
    """第一次登记：没有上一次可比，按这个版本 02-wbs 里已有的全部包算。"""
    p = subprocess.run(["git", "show", f"{version}:docs/wbs/02-wbs.md"], cwd=repo, capture_output=True, text=True)
    if p.returncode != 0:
        return []
    return sorted({m for line in p.stdout.splitlines() if line.startswith("| WP-") for m in WP_RE.findall(line.split("|")[1])})


def http(method: str, url: str, key: str, body: dict | None = None):
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Accept": "application/json", "Authorization": f"Bearer {key}",
        **({"Content-Type": "application/json"} if data else {})})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise LedgerError(f"需求讨论返回 {e.code}：{e.read()[:200].decode(errors='replace')}")
    except (urllib.error.URLError, TimeoutError) as e:
        raise LedgerError(f"连不上需求讨论：{e}")


def previous_version(base: str, key: str, repo: str, env: str) -> str:
    q = urllib.parse.urlencode({"repo": repo, "environment": env})
    items = http("GET", f"{base}/releases?{q}", key).get("items") or []
    return str(items[0].get("version", "")) if items else ""


def record(args) -> dict:
    repo = Path(args.repo_dir).resolve()
    version = git(repo, "rev-parse", args.version).strip()
    name = args.repo or repo_name(repo)
    base = (args.url or os.environ.get("XSOS_DISCUSSION_URL") or DEFAULT_URL).rstrip("/")
    key = os.environ.get("XSOS_RELEASE_KEY", "")
    if not key and not args.dry_run:
        raise LedgerError("没有发布登记密钥（XSOS_RELEASE_KEY）")
    prev = "" if args.dry_run and not key else previous_version(base, key, name, args.env)
    if prev and subprocess.run(["git", "merge-base", "--is-ancestor", prev, version], cwd=repo).returncode != 0:
        # 回滚或换了历史：上一次不在这次的祖先里，没法算差，不登记包，只登记版本。
        packages, note = [], f"上次登记的 {prev[:8]} 不在这次版本的历史里（回滚？），只登记版本"
    elif prev:
        packages, note = packages_between(repo, prev, version), f"比上次 {prev[:8]} 多发出去的包"
    else:
        packages, note = packages_in_pack(repo, version), "第一次登记，按这个版本 02-wbs 里已有的包算"
    body = {"repo": name, "environment": args.env, "version": version, "packages": packages,
            "deployedAt": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    if not args.dry_run:
        http("POST", f"{base}/releases", key, body)
    return {**body, "note": note, "dryRun": args.dry_run}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo-dir", default=".")
    ap.add_argument("--repo", help="仓库名，默认取 origin 地址最后一段")
    ap.add_argument("--env", required=True, choices=["test", "production"])
    ap.add_argument("--version", default="HEAD", help="这次发布的提交（默认 HEAD）")
    ap.add_argument("--url", help=f"需求讨论接口根地址（默认 {DEFAULT_URL}）")
    ap.add_argument("--dry-run", action="store_true", help="只算出这次的包，不登记")
    ap.add_argument("--strict", action="store_true", help="登记失败时退出码非 0（默认只告警）")
    args = ap.parse_args(argv)
    try:
        out = record(args)
        print(json.dumps(out, ensure_ascii=False))
        print(f"发布登记：{out['repo']} {args.env} {out['version'][:8]} · {len(out['packages'])} 个包（{out['note']}）",
              file=sys.stderr)
        return 0
    except LedgerError as e:
        print(f"::warning::发布登记失败（不影响发布）：{e}", file=sys.stderr)
        return 1 if args.strict else 0


if __name__ == "__main__":
    sys.exit(main())
