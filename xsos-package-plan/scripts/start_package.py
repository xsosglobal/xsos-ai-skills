#!/usr/bin/env python3
"""开工落包（xsos-package-plan）：把一个已提交的立包任务落成工作包，开分支、开草稿 PR。

为什么要有这个脚本：以前建包号码按「本机仓库里最大号 +1」取，几个会话、几台机器同时立包
天天撞号；包直接写进主工作目录，和别人没提交的改动混在一起；写完也不推，别人不知道号被占了。
这里把这些机械动作做成确定的步骤，任何人、任何 AI 都用同一套。

步骤（每步完成都记进状态文件，失败后再跑一次从断处继续，不会重复建包）:
  fetch     拉取远端最新（集成分支、远端分支、预留标记）
  number    取号：集成分支 WBS、远端分支名、预留标记、PR 标题、本机已有的包，五处取最大 +1；
            往远端推预留标记 refs/xsos/wp/<包号> 当全局锁，被占就顺延（WP-INTEG-030）
  worktree  在独立工作树建分支 feat/<包号>-<简称>，主工作目录的文件和分支都不动
  write     照抄基线写包（调用 xsos-wbs-author 的 add_work_package.py，体检不过整体回滚）
  commit    提交「docs(wbs): 立包 <包号> <标题>」，带 Work-Package 尾注
  push      推送前再核对预留标记仍是自己的；被抢就换号重写，最多 3 次
  pr        开草稿 PR 占号

用法:
    start_package.py --repo-dir ~/work/gitee/xsos_admin --task task.json --dry-run
    start_package.py --repo-dir ~/work/gitee/xsos_admin --task task.json
任务文件格式见 references/plan-format.md。每一步输出一行 JSON（event: step / done / failed）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import io
from pathlib import Path

HERE = Path(__file__).resolve().parent
AUTHOR = Path(os.environ.get("XSOS_WBS_AUTHOR") or HERE.parents[1] / "xsos-wbs-author" / "scripts" / "add_work_package.py")
STEPS = ["fetch", "number", "worktree", "write", "commit", "push", "pr"]
SERIES_BY_LAYER = {"frontend": "FE", "backend": "BE"}
LOCK_PREFIX = "refs/xsos/wp/"
MAX_LOCK_TRIES = 5
MAX_PUSH_TRIES = 3


class StepError(Exception):
    pass


def emit(event: str, **kw) -> None:
    print(json.dumps({"event": event, **kw}, ensure_ascii=False), flush=True)


def run(cmd: list[str], cwd: Path | None = None, input: str | None = None, check: bool = True) -> subprocess.CompletedProcess:
    p = subprocess.run(cmd, cwd=cwd, input=input, capture_output=True, text=True)
    if check and p.returncode != 0:
        raise StepError(f"{' '.join(cmd[:3])} 失败：{(p.stderr or p.stdout).strip()[:400]}")
    return p


def git(repo: Path, *args: str, check: bool = True, input: str | None = None) -> str:
    return run(["git", *args], cwd=repo, check=check, input=input).stdout.strip()


# ---------- 取号 ----------

def ids_in(text: str, series: str) -> list[int]:
    return [int(n) for n in re.findall(rf"WP-{re.escape(series)}-(\d+)", text or "")]


def github_slug(repo: Path, remote: str) -> str:
    # 读配置里的原始地址：get-url 会套用 insteadOf 改写，认不出是 GitHub。
    url = git(repo, "config", "--get", f"remote.{remote}.url")
    m = re.search(r"github\.com[:/]+([^/]+/[^/]+?)(?:\.git)?/?$", url)
    if not m:
        raise StepError(f"远端 {url} 不是 GitHub 仓库，查不了 PR 标题")
    return m.group(1)


def pr_titles(slug: str) -> str:
    p = run(["gh", "pr", "list", "-R", slug, "--state", "all", "-L", "300", "--json", "title,headRefName"], check=False)
    if p.returncode != 0:
        raise StepError(f"查不到 PR 标题（gh：{(p.stderr or p.stdout).strip()[:200]}），停止取号，不猜")
    return "\n".join(f"{x.get('title', '')} {x.get('headRefName', '')}" for x in json.loads(p.stdout or "[]"))


def lock_refs(repo: Path, remote: str) -> str:
    p = run(["git", "ls-remote", remote, LOCK_PREFIX + "*"], cwd=repo, check=False)
    if p.returncode != 0:
        raise StepError(f"读不到远端预留标记（{p.stderr.strip()[:200]}），停止取号")
    return p.stdout


def number_sources(repo: Path, remote: str, integration: str, series: str) -> dict[str, int]:
    """五处各自的最大号；任何一处查不到就抛错（S2：不猜）。"""
    wbs = git(repo, "show", f"{remote}/{integration}:docs/wbs/02-wbs.md", check=False)
    if not wbs:
        raise StepError(f"读不到 {remote}/{integration} 上的 docs/wbs/02-wbs.md")
    branches = git(repo, "for-each-ref", "--format=%(refname)", f"refs/remotes/{remote}")
    local = (repo / "docs" / "wbs" / "02-wbs.md")
    found = {
        "集成分支": ids_in(wbs, series),
        "远端分支": ids_in(branches, series),
        "预留标记": ids_in(lock_refs(repo, remote), series),
        "PR 标题": ids_in(pr_titles(github_slug(repo, remote)), series),
        "本机": ids_in(local.read_text(encoding="utf-8") if local.exists() else "", series),
    }
    return {k: max(v) if v else 0 for k, v in found.items()}


def wp_id(series: str, n: int) -> str:
    return f"WP-{series}-{n:03d}"


def reserve(repo: Path, remote: str, integration: str, wp: str, note: str) -> str | None:
    """推预留标记：只有这个引用在远端不存在时才推得上去。成功返回标记提交号，被占返回 None。"""
    base = git(repo, "rev-parse", f"{remote}/{integration}")
    tree = git(repo, "rev-parse", f"{base}^{{tree}}")
    sha = git(repo, "commit-tree", tree, "-p", base, "-m", f"reserve {wp}\n\n{note}")
    ref = LOCK_PREFIX + wp
    p = run(["git", "push", "--porcelain", f"--force-with-lease={ref}:", remote, f"{sha}:{ref}"], cwd=repo, check=False)
    if p.returncode == 0:
        return sha
    text = p.stderr + p.stdout
    if "stale info" in text or "rejected" in text or "already exists" in text or "fetch first" in text:
        return None
    raise StepError(f"推预留标记失败：{text.strip()[:300]}")


def lock_holder(repo: Path, remote: str, wp: str) -> str:
    out = lock_refs(repo, remote)
    for line in out.splitlines():
        sha, _, ref = line.partition("\t")
        if ref.strip() == LOCK_PREFIX + wp:
            return sha.strip()
    return ""


# ---------- 包内容 ----------

def slug(task: dict) -> str:
    src = re.sub(r"[^0-9A-Za-z]", "", str(task.get("source", "")))[3:9].lower() or "plan"
    return f"{src}-t{task.get('taskIndex', 1)}"


def build_spec(task: dict, wp: str, series: str) -> dict:
    """方案 → add_work_package 的 spec。基线逐字照抄，不改写（S5）。"""
    t = task["task"]
    base = t.get("baseline") or {}
    items = [x for x in base.get("items") or [] if str(x.get("text", "")).strip()]
    summary = task.get("summary") or {}
    n = task.get("taskIndex", 1)
    source = f"{task['source']} 任务 {n}「{summary.get('title', '').strip()}」（AI 立包）"
    reqs = [x for x in [summary.get("problem", "").strip(), f"场景：{base.get('scenario', '').strip()}",
                        f"为什么改这里：{t.get('why', '').strip()}" if t.get("why") else ""] if x and not x.endswith("：")]
    return {
        "wp_id": wp, "series": series,
        "title_cn": t["title"].strip(),
        "title_en": (t.get("titleEn") or f"{task['source']} task {n}").strip(),
        "type": t.get("type") or t.get("layer") or "backend",
        "owner": (t.get("ownerName") or "").strip(),
        "proposer": (task.get("proposer") or "").strip() or None,
        "status": "todo",
        "depends_on": "none",
        "scope": base.get("scenario", "").strip() + (f"；为什么改这里：{t['why'].strip()}" if t.get("why") else ""),
        "non_goals": base.get("nonGoals", "").strip(),
        "requirements": reqs or [t["title"].strip()],
        "acceptance": [f"{x['text'].strip()}（测试：{x['test'].strip()}）" for x in items],
        "source": source,
        "outputs": t.get("outputs") or "待开发时补充",
    }


def check_task(task: dict) -> None:
    sys.path.insert(0, str(HERE))
    from plan_check import missing  # noqa: E402
    if not re.search(r"\b(REQ|BUG)-[0-9A-F]{12}\b", str(task.get("source", ""))):
        raise StepError("任务没有来源编号（REQ-/BUG- 加 12 位十六进制）")
    miss = missing([task.get("task") or {}])
    if miss:
        raise StepError("基线还有没填完的地方：" + "、".join(m.replace("任务 1的", "") for m in miss))


def author(pack: Path, spec: dict, dry: bool) -> str:
    if not AUTHOR.exists():
        raise StepError(f"找不到 add_work_package.py（{AUTHOR}），请装好 xsos-wbs-author")
    cmd = [sys.executable, str(AUTHOR), str(pack), "--spec", "-"] + (["--dry-run"] if dry else [])
    p = run(cmd, input=json.dumps({k: v for k, v in spec.items() if v is not None}, ensure_ascii=False), check=False)
    if p.returncode != 0:
        raise StepError("写包没通过体检：" + (p.stderr or p.stdout).strip()[-800:])
    return p.stdout


def changes_note(wt: Path, wp: str, spec: dict) -> None:
    """玄枢这类要求每个 PR 带交付说明的仓库，补一份立包说明。"""
    d = wt / "docs" / "wbs" / "changes"
    if not d.is_dir():
        return
    tests = [p for p in ("test/wbs.mjs",) if (wt / p).is_file()]
    if not tests:
        return
    name = f"{wp.lower()}-package.json"
    files = sorted({str(p.relative_to(wt)) for p in (wt / "docs" / "wbs").glob("*.md")
                    if git(wt, "status", "--porcelain", str(p.relative_to(wt)))} | {f"docs/wbs/changes/{name}"})
    (d / name).write_text(json.dumps({"schema": 1, "project": wt.name, "packages": [{
        "wpId": wp, "implementation": "partial", "summary": f"立包（todo）：{spec['title_cn']}",
        "remaining": ["按 06-acceptance 的验收条目逐条实现"], "files": files, "tests": tests}]},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ---------- 主流程 ----------

class Start:
    def __init__(self, args):
        self.args = args
        self.repo = Path(args.repo_dir).expanduser().resolve()
        self.task = json.loads(Path(args.task).read_text(encoding="utf-8")) if args.task != "-" else json.load(sys.stdin)
        self.remote = args.remote
        t = self.task.get("task") or {}
        self.series = (args.series or t.get("series") or SERIES_BY_LAYER.get(t.get("layer"), "BE")).upper()
        key = f"{self.repo.name}-{self.task.get('source', 'x')}-t{self.task.get('taskIndex', 1)}"
        self.state_path = Path(args.state_dir).expanduser() / f"{key}.json"
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() and not args.dry_run else {"done": []}

    def save(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.state, ensure_ascii=False, indent=2))

    @property
    def integration(self) -> str:
        if self.args.integration:
            return self.args.integration
        has = git(self.repo, "rev-parse", "-q", "--verify", f"{self.remote}/develop", check=False)
        return "develop" if has else "main"

    def step(self, name, fn):
        if name in self.state["done"]:
            emit("step", step=name, status="ok", detail="已完成（继续开工时跳过）")
            return
        emit("step", step=name, status="run")
        detail = fn()
        self.state["done"].append(name)
        if not self.args.dry_run:
            self.save()
        emit("step", step=name, status="ok", detail=detail or "")
        # 只给测试用：做完这一步就停，模拟中途失败。
        if os.environ.get("XSOS_PKG_STOP_AFTER") == name:
            raise StepError(f"测试中断于 {name}")

    def s_fetch(self):
        git(self.repo, "fetch", "--prune", self.remote)
        return f"{self.remote}/{self.integration} @ {git(self.repo, 'rev-parse', '--short', f'{self.remote}/{self.integration}')}"

    def s_number(self):
        srcs = number_sources(self.repo, self.remote, self.integration, self.series)
        n = max(srcs.values()) + 1
        seen = "、".join(f"{k} {wp_id(self.series, v) if v else '无'}" for k, v in srcs.items())
        if self.args.dry_run:
            self.state["wp"] = wp_id(self.series, n)
            return f"预计 {self.state['wp']}（已查：{seen}；确认后加锁时若被占会顺延）"
        note = f"{self.task.get('source')} 任务 {self.task.get('taskIndex', 1)} · {self.task['task'].get('ownerName', '')}"
        for _ in range(MAX_LOCK_TRIES):
            wp = wp_id(self.series, n)
            sha = reserve(self.repo, self.remote, self.integration, wp, note)
            if sha:
                self.state.update(wp=wp, lock=sha)
                return f"{wp}（已查：{seen}；预留标记已推）"
            n += 1
        raise StepError(f"连续 {MAX_LOCK_TRIES} 个号都被占，停止")

    def s_worktree(self):
        wp = self.state["wp"]
        branch = f"feat/{wp}-{slug(self.task)}"
        wt = Path(self.args.worktrees).expanduser() / f"{self.repo.name}-{wp}"
        if not wt.exists():
            wt.parent.mkdir(parents=True, exist_ok=True)
            git(self.repo, "worktree", "add", "-b", branch, str(wt), f"{self.remote}/{self.integration}")
        self.state.update(branch=branch, worktree=str(wt))
        return f"{branch} · {wt}"

    def s_write(self):
        wt = Path(self.state["worktree"])
        spec = build_spec(self.task, self.state["wp"], self.series)
        if git(wt, "log", "-1", "--format=%s").find(f"立包 {self.state['wp']}") >= 0:
            return "包已写过"
        if git(wt, "status", "--porcelain", "docs/wbs"):
            git(wt, "checkout", "--", "docs/wbs")
            git(wt, "clean", "-fdq", "docs/wbs")
        author(wt / "docs" / "wbs", spec, dry=False)
        changes_note(wt, self.state["wp"], spec)
        return "体检通过"

    def s_commit(self):
        wt = Path(self.state["worktree"])
        wp = self.state["wp"]
        if f"立包 {wp}" in git(wt, "log", "-1", "--format=%s"):
            return "已提交"
        title = self.task["task"]["title"].strip()
        git(wt, "add", "docs/wbs")
        git(wt, "commit", "-q", "-m", f"docs(wbs): 立包 {wp} {title}\n\n来源：{self.task['source']} 任务 {self.task.get('taskIndex', 1)}\n\nWork-Package: {wp}")
        return git(wt, "rev-parse", "--short", "HEAD")

    def renumber(self):
        """推送前发现号被抢：换号、重建分支、重写重提。"""
        wt = Path(self.state["worktree"])
        old = self.state["wp"]
        git(self.repo, "worktree", "remove", "--force", str(wt))
        git(self.repo, "branch", "-D", self.state["branch"], check=False)
        self.state["done"] = ["fetch"]
        self.s_fetch()
        emit("step", step="number", status="run", detail=f"{old} 被别人抢先，换号")
        self.s_number()
        for name, fn in (("worktree", self.s_worktree), ("write", self.s_write), ("commit", self.s_commit)):
            fn()
        self.state["done"] = ["fetch", "number", "worktree", "write", "commit"]
        self.save()

    def s_push(self):
        for attempt in range(MAX_PUSH_TRIES):
            if lock_holder(self.repo, self.remote, self.state["wp"]) == self.state.get("lock"):
                git(Path(self.state["worktree"]), "push", "-q", "-u", self.remote, self.state["branch"])
                return f"已推送 {self.state['branch']}"
            self.renumber()
        raise StepError(f"推送前核对包号连续 {MAX_PUSH_TRIES} 次被抢，停止")

    def s_pr(self):
        slug_ = github_slug(self.repo, self.remote)
        branch = self.state["branch"]
        view = run(["gh", "pr", "view", branch, "-R", slug_, "--json", "url,number"], check=False)
        if view.returncode == 0 and view.stdout.strip():
            pr = json.loads(view.stdout)
        else:
            t = self.task["task"]
            body = (f"开工落包（草稿，占号）。\n\n- 来源：{self.task['source']} 任务 {self.task.get('taskIndex', 1)}"
                    f"「{(self.task.get('summary') or {}).get('title', '')}」\n- 负责人：{t.get('ownerName', '')}\n\n"
                    "代码写完再转为正式 PR。")
            run(["gh", "pr", "create", "--draft", "-R", slug_, "-B", self.integration, "-H", branch,
                 "-t", f"{self.state['wp']} {t['title'].strip()}", "-b", body])
            pr = json.loads(run(["gh", "pr", "view", branch, "-R", slug_, "--json", "url,number"]).stdout)
        self.state.update(pr=pr.get("number"), prUrl=pr.get("url"))
        return pr.get("url", "")

    def dry(self):
        check_task(self.task)
        self.step("fetch", self.s_fetch)
        self.step("number", self.s_number)
        with tempfile.TemporaryDirectory() as tmp:
            raw = subprocess.run(["git", "archive", f"{self.remote}/{self.integration}", "docs/wbs"], cwd=self.repo, capture_output=True).stdout
            tarfile.open(fileobj=io.BytesIO(raw)).extractall(tmp)
            diff = author(Path(tmp) / "docs" / "wbs", build_spec(self.task, self.state["wp"], self.series), dry=True)
        emit("done", dryRun=True, wpId=self.state["wp"], branch=f"feat/{self.state['wp']}-{slug(self.task)}",
             integration=self.integration, diff=diff)

    def go(self):
        check_task(self.task)
        for name in STEPS:
            self.step(name, getattr(self, f"s_{name}"))
        emit("done", wpId=self.state["wp"], branch=self.state["branch"], worktree=self.state["worktree"],
             pr=self.state.get("pr"), prUrl=self.state.get("prUrl"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo-dir", required=True, help="本机仓库主目录（只借它的 .git 建工作树，不改它）")
    ap.add_argument("--task", required=True, help="任务 JSON 文件，或 - 从标准输入读")
    ap.add_argument("--dry-run", action="store_true", help="只预演：取号（不加锁）并显示将要写入的内容")
    ap.add_argument("--series", help="包号中段，如 UI；默认按前端/后端取 FE/BE")
    ap.add_argument("--integration", help="集成分支；默认有 develop 用 develop，否则 main")
    ap.add_argument("--remote", default="origin")
    ap.add_argument("--worktrees", default="~/.xsos/worktrees")
    ap.add_argument("--state-dir", default="~/.xsos/package-start")
    args = ap.parse_args(argv)
    s = Start(args)
    current = None
    try:
        if args.dry_run:
            s.dry()
        else:
            s.go()
        return 0
    except (StepError, KeyError, json.JSONDecodeError) as e:
        current = next((n for n in STEPS if n not in s.state["done"]), "")
        if not args.dry_run:
            s.save()
        emit("failed", step=current, error=str(e), resumable=not args.dry_run)
        return 1


if __name__ == "__main__":
    sys.exit(main())
