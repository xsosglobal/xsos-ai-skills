"""check_commit_packages.py 的用例：规则本身 + 造真 git 仓库跑端到端（含开关文件）。"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts/check_commit_packages.py"
SPEC = spec_from_file_location("check_commit_packages", SCRIPT)
check = module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(check)

WBS = (
    "# WBS\n\n| wp_id | title_cn | type |\n|---|---|---|\n"
    "| WP-BE-001 | 一 | backend |\n| WP-FE-002 | 二 | frontend |\n"
)
KNOWN = check.known_packages(WBS)
CODE = ["internal/app.go"]
DOCS = ["docs/wbs/02-wbs.md"]


class RuleTest(unittest.TestCase):
    def test_known_packages_reads_table_rows_only(self):
        self.assertEqual(KNOWN, {"WP-BE-001", "WP-FE-002"})
        self.assertEqual(check.known_packages("见 WP-BE-009\n"), set())

    def test_code_commit_with_known_package_passes(self):
        self.assertEqual(check.commit_problems("feat(WP-BE-001): 加字段\n", CODE, KNOWN), [])

    def test_code_commit_without_package_fails(self):
        problems = check.commit_problems("fix: 修个 bug\n", CODE, KNOWN)
        self.assertEqual(len(problems), 1)
        self.assertIn("没写包号", problems[0])

    def test_docs_only_commit_is_skipped(self):
        self.assertEqual(check.commit_problems("docs: 改文案\n", DOCS, KNOWN), [])
        self.assertEqual(check.commit_problems("chore: 空提交\n", [], KNOWN), [])

    def test_other_repo_package_alone_does_not_satisfy_code_commit(self):
        problems = check.commit_problems("feat(WP-BE-999): x\n", CODE, KNOWN)
        self.assertEqual(len(problems), 1)
        self.assertIn("都不在本仓库", problems[0])

    def test_mentioning_other_repo_packages_is_fine(self):
        msg = "feat(WP-BE-001): 对接 discussion 的 WP-FS-037\n"
        self.assertEqual(check.commit_problems(msg, CODE, KNOWN), [])
        self.assertEqual(check.commit_problems("docs: 记录 WP-FS-037 的联动\n", DOCS, KNOWN), [])

    def test_package_pattern_does_not_match_inside_longer_ids(self):
        self.assertEqual(check.WP_RE.findall("XWP-BE-001 WP-BE-0012 WP-BE-001"), ["WP-BE-0012", "WP-BE-001"])

    def test_bug_fix_with_work_package_passes(self):
        msg = "fix(WP-BE-001): 修复\n\nBug-Fix: BUG-60F08645390F\nWork-Package: WP-BE-001\n"
        self.assertEqual(check.commit_problems(msg, CODE, KNOWN), [])

    def test_bug_fix_without_work_package_fails(self):
        msg = "fix(WP-BE-001): 修复\n\nBug-Fix: BUG-60F08645390F\n"
        problems = check.commit_problems(msg, CODE, KNOWN)
        self.assertEqual(len(problems), 1)
        self.assertIn("Work-Package", problems[0])

    def test_bug_fix_value_must_be_twelve_upper_hex(self):
        for value in ("BUG-60f08645390f", "BUG-123", "60F08645390F", ""):
            msg = f"fix(WP-BE-001): x\n\nBug-Fix: {value}\nWork-Package: WP-BE-001\n"
            problems = check.commit_problems(msg, CODE, KNOWN)
            self.assertTrue(any("Bug-Fix" in p for p in problems), value)

    def test_bug_fix_may_name_several_bugs(self):
        msg = "fix(WP-BE-001): x\n\nBug-Fix: BUG-60F08645390F, BUG-E0A3CE5C4B2F\nWork-Package: WP-BE-001\n"
        self.assertEqual(check.commit_problems(msg, CODE, KNOWN), [])

    def test_work_package_trailer_must_name_known_package(self):
        msg = "fix(WP-BE-001): x\n\nBug-Fix: BUG-60F08645390F\nWork-Package: WP-BE-777\n"
        problems = check.commit_problems(msg, CODE, KNOWN)
        self.assertTrue(any("Work-Package 尾注的包号不在" in p for p in problems))


class EndToEndTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}
        self.git("init", "-q", "-b", "main")
        self.write("docs/wbs/02-wbs.md", WBS)
        self.commit("docs: init pack")
        self.git("branch", "base")

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, env=self.env, check=True, capture_output=True, text=True).stdout

    def write(self, path, text):
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def commit(self, message, path=None):
        if path:
            self.write(path, message)
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", message)

    def run_script(self):
        return subprocess.run([sys.executable, str(SCRIPT), "base..HEAD", "--pack", str(self.repo / "docs/wbs")], cwd=self.repo, capture_output=True, text=True)

    def test_clean_range_passes(self):
        self.commit("feat(WP-BE-001): 代码", "internal/a.go")
        self.commit("docs: 只改文档", "docs/wbs/CHANGELOG.md")
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("通过", result.stdout)

    def test_missing_package_only_warns_without_switch(self):
        self.commit("fix: 没写包号", "internal/a.go")
        result = self.run_script()
        self.assertEqual(result.returncode, 0)
        self.assertIn("提示，不失败", result.stdout)

    def test_missing_package_blocks_with_switch(self):
        self.write("docs/wbs/commit-check.enabled", "")
        self.commit("docs: 开启提交包号检查")
        self.commit("fix: 没写包号", "internal/a.go")
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertIn("没写包号", result.stderr)

    def test_merge_commits_are_skipped(self):
        self.write("docs/wbs/commit-check.enabled", "")
        self.commit("docs: 开启")
        self.git("checkout", "-q", "-b", "side")
        self.commit("feat(WP-FE-002): 前端", "web/a.ts")
        self.git("checkout", "-q", "main")
        self.commit("feat(WP-BE-001): 后端", "internal/b.go")
        self.git("merge", "-q", "--no-ff", "side", "-m", "Merge branch side")
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_package_added_in_same_range_is_known(self):
        self.write("docs/wbs/commit-check.enabled", "")
        self.write("docs/wbs/02-wbs.md", WBS + "| WP-BE-003 | 三 | backend |\n")
        self.commit("docs(WP-BE-003): 立包")
        self.commit("feat(WP-BE-003): 实现", "internal/c.go")
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_package_table_is_read_from_range_tip_not_worktree(self):
        self.write("docs/wbs/02-wbs.md", WBS + "| WP-BE-004 | 四 | backend |\n")
        self.commit("docs(WP-BE-004): 立包")
        self.commit("feat(WP-BE-004): 实现", "internal/d.go")
        tip = self.git("rev-parse", "HEAD").strip()
        # 工作树回到旧的 02-wbs.md（模拟本机陈旧工作区），按末端提交读仍能认出 WP-BE-004。
        self.git("checkout", "-q", "base")
        self.write("docs/wbs/commit-check.enabled", "")
        result = subprocess.run([sys.executable, str(SCRIPT), f"base..{tip}", "--pack", str(self.repo / "docs/wbs")], cwd=self.repo, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
