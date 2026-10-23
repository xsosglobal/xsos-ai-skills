"""开工落包脚本（start_package.py）的测试——对应基线 S2–S6。

用真的 git：一个裸仓库当远端、一个克隆当「本机仓库主目录」；gh 换成测试里的假脚本，
记下开 PR 的调用、按文件返回 PR 列表。
"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
START = SCRIPTS / "start_package.py"
AUTHOR_TESTS = HERE.parents[1] / "xsos-wbs-author" / "tests" / "test_wp_id_ledger.py"

spec = importlib.util.spec_from_file_location("ledger_fixture", AUTHOR_TESTS)
fixture = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = fixture
spec.loader.exec_module(fixture)

FAKE_GH = r'''#!/usr/bin/env python3
import json, os, sys
d = os.environ["FAKE_GH_DIR"]
args = sys.argv[1:]
log = os.path.join(d, "calls.jsonl")
open(log, "a").write(json.dumps(args) + "\n")
if os.path.exists(os.path.join(d, "fail")):
    sys.stderr.write("gh: network down\n"); sys.exit(1)
prs = os.path.join(d, "prs.json")
items = json.load(open(prs)) if os.path.exists(prs) else []
if args[:2] == ["pr", "list"]:
    print(json.dumps(items)); sys.exit(0)
if args[:2] == ["pr", "view"]:
    hit = [p for p in items if p.get("headRefName") == args[2]]
    if not hit: sys.stderr.write("no pull requests found\n"); sys.exit(1)
    print(json.dumps({"url": hit[0]["url"], "number": hit[0]["number"]})); sys.exit(0)
if args[:2] == ["pr", "create"]:
    if os.path.exists(os.path.join(d, "fail-create")):
        os.remove(os.path.join(d, "fail-create")); sys.stderr.write("gh: 502\n"); sys.exit(1)
    head = args[args.index("-H") + 1]; title = args[args.index("-t") + 1]
    n = 300 + len(items)
    items.append({"title": title, "headRefName": head, "number": n, "url": f"https://github.com/o/r/pull/{n}", "draft": "--draft" in args})
    json.dump(items, open(prs, "w")); print(items[-1]["url"]); sys.exit(0)
sys.exit(0)
'''

TASK = {
    "source": "REQ-7F3A92C1D0B4",
    "taskIndex": 2,
    "proposer": "顾昊",
    "summary": {"title": "送货单打印后状态不更新", "problem": "打完标签，送货单列表仍显示「待打印」。", "evidence": []},
    "task": {"project": "xsos-admin", "layer": "backend", "title": "打印回调回写送货单状态",
             "why": "delivery_print.go:212 只写了打印记录", "ownerId": "lu", "ownerName": "卢宗康",
             "baseline": {"scenario": "仓库打完标签，列表马上显示已打印", "nonGoals": "不改打印队列",
                          "items": [{"text": "打完全部标签，状态变「已打印」", "test": "TestPrintCallbackMarksPrinted"}]}},
}


def sh(cwd, *args):
    return subprocess.run(list(args), cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class StartPackageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        seed = self.tmp / "seed"
        fixture.make_pack(seed / "docs" / "wbs", rows=("WP-BE-001", "WP-BE-003"))
        sh(seed, "git", "init", "-q", "-b", "develop")
        sh(seed, "git", "-c", "user.name=t", "-c", "user.email=t@t", "add", ".")
        sh(seed, "git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
        self.origin = self.tmp / "origin.git"
        sh(self.tmp, "git", "clone", "-q", "--bare", str(seed), str(self.origin))
        self.repo = self.tmp / "xsos_admin"
        sh(self.tmp, "git", "clone", "-q", str(self.origin), str(self.repo))
        sh(self.repo, "git", "config", "user.name", "t")
        sh(self.repo, "git", "config", "user.email", "t@t")
        # 远端地址要像 GitHub，脚本才肯查 PR 标题；push 实际走本地裸仓库。
        sh(self.repo, "git", "remote", "set-url", "origin", "git@github.com:xsosglobal/xsos-admin.git")
        sh(self.repo, "git", "config", "url." + str(self.origin) + ".insteadOf", "git@github.com:xsosglobal/xsos-admin.git")
        self.gh = self.tmp / "ghdir"
        self.gh.mkdir()
        bin_ = self.tmp / "bin"
        bin_.mkdir()
        (bin_ / "gh").write_text(FAKE_GH)
        (bin_ / "gh").chmod(0o755)
        self.env = {**os.environ, "PATH": f"{bin_}{os.pathsep}{os.environ['PATH']}", "FAKE_GH_DIR": str(self.gh),
                    "XSOS_SKILLS_SKIP_UPDATE_CHECK": "1", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        self.task = self.tmp / "task.json"
        self.task.write_text(json.dumps(TASK, ensure_ascii=False))

    def start(self, *extra, env=None):
        p = subprocess.run([sys.executable, str(START), "--repo-dir", str(self.repo), "--task", str(self.task),
                            "--worktrees", str(self.tmp / "wt"), "--state-dir", str(self.tmp / "state"), *extra],
                           capture_output=True, text=True, env={**self.env, **(env or {})})
        events = [json.loads(line) for line in p.stdout.splitlines() if line.startswith("{")]
        return p.returncode, events

    def remote_refs(self):
        return sh(self.origin, "git", "for-each-ref", "--format=%(refname)")

    def test_next_id_takes_max_of_all_sources(self):
        """S2：集成分支、远端分支、预留标记、PR 标题、本机五处取最大 +1。"""
        sh(self.repo, "git", "push", "-q", "origin", "develop:refs/heads/feat/WP-BE-007-x")
        sh(self.repo, "git", "push", "-q", "origin", "develop:refs/xsos/wp/WP-BE-009")
        (self.gh / "prs.json").write_text(json.dumps([{"title": "WP-BE-005 别的", "headRefName": "x"}]))
        code, ev = self.start("--dry-run")
        self.assertEqual(code, 0, ev)
        self.assertEqual(ev[-1]["wpId"], "WP-BE-010")
        self.assertIn("WP-BE-010", ev[-1]["diff"])

    def test_stops_when_a_source_is_unavailable(self):
        """S2：任何一处查不到就停下说明，不猜。"""
        (self.gh / "fail").write_text("1")
        code, ev = self.start("--dry-run")
        self.assertEqual(code, 1)
        self.assertEqual(ev[-1]["event"], "failed")
        self.assertIn("PR 标题", ev[-1]["error"])

    def test_dry_run_writes_nothing(self):
        """S5：预演不写盘、不加锁、不建工作树。"""
        code, ev = self.start("--dry-run")
        self.assertEqual(code, 0, ev)
        self.assertNotIn("refs/xsos/wp/", self.remote_refs())
        self.assertFalse((self.tmp / "wt").exists())
        self.assertEqual(sh(self.repo, "git", "status", "--porcelain"), "")

    def test_start_copies_baseline_and_opens_draft_pr(self):
        """S4–S6：独立工作树、照抄基线、提交带尾注、推送、草稿 PR；主工作目录不动。"""
        head = sh(self.repo, "git", "rev-parse", "HEAD")
        code, ev = self.start()
        self.assertEqual(code, 0, ev)
        done = ev[-1]
        self.assertEqual(done["wpId"], "WP-BE-004")
        wt = Path(done["worktree"])
        acc = (wt / "docs" / "wbs" / "06-acceptance.md").read_text(encoding="utf-8")
        req = (wt / "docs" / "wbs" / "01-requirements.md").read_text(encoding="utf-8")
        self.assertIn("打完全部标签，状态变「已打印」（测试：TestPrintCallbackMarksPrinted）", acc)
        self.assertIn("REQ-7F3A92C1D0B4 任务 2", req)
        self.assertIn("Work-Package: WP-BE-004", sh(wt, "git", "log", "-1", "--format=%B"))
        self.assertIn("refs/heads/feat/WP-BE-004-", self.remote_refs())
        self.assertIn("refs/xsos/wp/WP-BE-004", self.remote_refs())
        prs = json.loads((self.gh / "prs.json").read_text())
        self.assertTrue(prs[-1]["draft"])
        self.assertTrue(prs[-1]["title"].startswith("WP-BE-004 "))
        # 主工作目录：文件、分支、HEAD 都没变。
        self.assertEqual(sh(self.repo, "git", "status", "--porcelain"), "")
        self.assertEqual(sh(self.repo, "git", "rev-parse", "--abbrev-ref", "HEAD"), "develop")
        self.assertEqual(sh(self.repo, "git", "rev-parse", "HEAD"), head)

    def test_resume_after_failure_without_duplicates(self):
        """S6：开 PR 失败后再跑一次，从失败处继续，不重复建包、不重复提交。"""
        (self.gh / "fail-create").write_text("1")
        code, ev = self.start()
        self.assertEqual(code, 1)
        self.assertEqual(ev[-1]["step"], "pr")
        code, ev = self.start()
        self.assertEqual(code, 0, ev)
        skipped = [e["step"] for e in ev if e.get("detail", "").startswith("已完成")]
        self.assertEqual(skipped, ["fetch", "number", "worktree", "write", "commit", "push"])
        wt = Path(ev[-1]["worktree"])
        self.assertEqual(sh(wt, "git", "rev-list", "--count", "origin/develop..HEAD"), "1")
        self.assertEqual(len(json.loads((self.gh / "prs.json").read_text())), 1)

    def test_renumbers_when_lock_is_taken_before_push(self):
        """S3：推送前发现预留标记被别人改了，换下一个号重写重提。"""
        code, ev = self.start(env={"XSOS_PKG_STOP_AFTER": "commit"})
        self.assertEqual(code, 1)
        # 模拟别人抢走 WP-BE-004：把预留标记改成别的提交。
        other = sh(self.repo, "git", "commit-tree", sh(self.repo, "git", "rev-parse", "origin/develop^{tree}"), "-m", "other")
        sh(self.repo, "git", "push", "-q", "-f", "origin", f"{other}:refs/xsos/wp/WP-BE-004")
        code, ev = self.start()
        self.assertEqual(code, 0, ev)
        self.assertEqual(ev[-1]["wpId"], "WP-BE-005")
        acc = (Path(ev[-1]["worktree"]) / "docs" / "wbs" / "06-acceptance.md").read_text(encoding="utf-8")
        self.assertIn("AC-BE-005", acc)
        self.assertNotIn("AC-BE-004", acc)

    def test_lock_is_exclusive(self):
        """WP-INTEG-030 预留锁：同一个号只有第一个推得上去。"""
        spec_ = importlib.util.spec_from_file_location("start_package", START)
        mod = importlib.util.module_from_spec(spec_)
        spec_.loader.exec_module(mod)
        sh(self.repo, "git", "fetch", "-q", "origin")
        self.assertTrue(mod.reserve(self.repo, "origin", "develop", "WP-BE-020", "a"))
        self.assertIsNone(mod.reserve(self.repo, "origin", "develop", "WP-BE-020", "b"))

    def test_incomplete_baseline_is_rejected(self):
        """基线缺项（如测试名）不能开工。"""
        bad = json.loads(self.task.read_text())
        bad["task"]["baseline"]["items"][0]["test"] = ""
        self.task.write_text(json.dumps(bad, ensure_ascii=False))
        code, ev = self.start("--dry-run")
        self.assertEqual(code, 1)
        self.assertIn("第 1 条验收的测试", ev[-1]["error"])


if __name__ == "__main__":
    unittest.main()
