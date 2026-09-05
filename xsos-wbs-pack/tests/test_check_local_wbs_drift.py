"""check_local_wbs_drift.py 的回归测试。

1) 里复现的就是 2026-09-05 那次事故：develop 上躺着两个没推的提交，
带进来一个远端根本不存在的工作包。当时 CI 每次都绿，因为 CI 看的是远端。
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts/check_local_wbs_drift.py"

HEADER = (
    "# WBS\n\n"
    "| wp_id | title_cn | title_en | type | owner | status | depends_on | "
    "scope | non_goals | acceptance_ref | outputs |\n"
    "|---|---|---|---|---|---|---|---|---|---|---|\n"
)
BASE_ROW = (
    "| WP-BE-001 | 已有的包 | Existing | backend | owner | done | none | "
    "s | n | AC-BE-001 | api |\n"
)


def row(wp_id: str, status: str) -> str:
    return (f"| {wp_id} | 只在本地的包 | Local only | backend | owner | {status} | none | "
            f"s | n | AC-{wp_id[3:]} | api |\n")


class LocalWBSDriftTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.repo = root / "work"
        self.remote = root / "remote.git"
        self.pack = self.repo / "docs/wbs"
        self.pack.mkdir(parents=True)

        self.git("init", "-b", "develop", cwd=self.repo)
        self.git("config", "user.email", "t@e.st")
        self.git("config", "user.name", "test")
        self.write(HEADER + BASE_ROW)
        self.git("add", "-A")
        self.git("commit", "-m", "docs(wbs): seed pack")
        subprocess.run(["git", "init", "--bare", str(self.remote)], capture_output=True, check=True)
        self.git("remote", "add", "origin", str(self.remote))
        self.git("push", "-u", "origin", "develop")

    def tearDown(self):
        self.temp.cleanup()

    def git(self, *args, cwd=None):
        return subprocess.run(["git", "-C", str(cwd or self.repo), *args],
                              capture_output=True, text=True, check=False)

    def write(self, text):
        (self.pack / "02-wbs.md").write_text(text, encoding="utf-8")

    def commit_local(self, text, message="docs(wbs): local only"):
        self.write(text)
        self.git("add", "-A")
        self.git("commit", "-m", message)

    def run_script(self, *extra):
        proc = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(self.repo), *extra],
                              capture_output=True, text=True)
        return proc

    # ---- 1) 事故复现 ----
    def test_unpushed_commit_on_shared_branch_is_reported(self):
        self.commit_local(HEADER + BASE_ROW + row("WP-BE-082", "in_progress"))
        out = self.run_script().stdout
        self.assertIn("共享分支 develop", out)
        self.assertIn("1 个未推的 WBS 提交", out)

    def test_ghost_package_on_shared_branch_is_reported(self):
        self.commit_local(HEADER + BASE_ROW + row("WP-BE-082", "in_progress"))
        out = self.run_script().stdout
        self.assertIn("幽灵包 WP-BE-082", out)
        self.assertIn("在共享分支上", out)

    def test_fail_flag_sets_exit_code(self):
        self.commit_local(HEADER + BASE_ROW + row("WP-BE-082", "in_progress"))
        self.assertEqual(self.run_script().returncode, 0)
        self.assertEqual(self.run_script("--fail").returncode, 1)

    # ---- 2) 干净仓库不该喊 ----
    def test_clean_repo_reports_nothing(self):
        out = self.run_script().stdout
        self.assertIn("没有发现", out)
        self.assertEqual(self.run_script("--fail").returncode, 0)

    # ---- 3) 在途分支是正常的，不能当失真 ----
    def test_fresh_feature_branch_is_not_drift(self):
        self.git("checkout", "-b", "feature/WP-BE-083-x")
        self.commit_local(HEADER + BASE_ROW + row("WP-BE-083", "in_progress"))
        out = self.run_script().stdout
        self.assertIn("在途分支", out)
        self.assertNotIn("! 幽灵包 WP-BE-083", out)
        self.assertIn("没有发现", out)

    # ---- 4) 但 feature 分支上标 done 的必须喊 ----
    def test_done_ghost_on_feature_branch_is_reported(self):
        self.git("checkout", "-b", "feature/WP-BE-084-x")
        self.commit_local(HEADER + BASE_ROW + row("WP-BE-084", "done"))
        out = self.run_script().stdout
        self.assertIn("幽灵包 WP-BE-084", out)
        self.assertIn("标 done", out)

    # ---- 5) 同一个包出现在多条分支上只报一次 ----
    def test_ghost_deduped_across_branches(self):
        content = HEADER + BASE_ROW + row("WP-BE-085", "done")
        for name in ("feature/a", "feature/b"):
            self.git("checkout", "-b", name, "develop")
            self.commit_local(content)
        out = self.run_script().stdout
        self.assertEqual(out.count("幽灵包 WP-BE-085"), 1)
        self.assertIn("2 条分支", out)

    # ---- 6) 远端已有的包不是幽灵 ----
    def test_pushed_package_is_not_a_ghost(self):
        self.commit_local(HEADER + BASE_ROW + row("WP-BE-086", "in_progress"))
        self.git("push", "origin", "develop")
        out = self.run_script().stdout
        self.assertNotIn("! 幽灵包", out)
        self.assertIn("没有发现", out)


if __name__ == "__main__":
    unittest.main()
