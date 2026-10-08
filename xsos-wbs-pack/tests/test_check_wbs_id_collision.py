"""check_wbs_id_collision.py 的用例。

重点是端到端那几条：造一个真的 git 仓库、造一个 base 分支，看脚本会不会在
「本次新增的行用了 base 里已有的号」时失败 —— 那正是三次撞号事故的形态。
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts/check_wbs_id_collision.py"
SPEC = spec_from_file_location("check_wbs_id_collision", SCRIPT)
check = module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(check)

ROW = "| {wp_id} | {title} | Title | frontend | portal-owner | todo | none | scope text | non-goal text | AC-X | out.md |\n"
HEADER = "| wp_id | title_cn | title_en | type | owner | status | depends_on | scope | non_goals | acceptance_ref | outputs |\n|---|---|---|---|---|---|---|---|---|---|---|\n"


def pack_text(*wp_ids: str) -> str:
    return "# WBS\n\n" + HEADER + "".join(ROW.format(wp_id=wp, title=f"包 {wp}") for wp in wp_ids)


class ParseTest(unittest.TestCase):
    def test_parse_reads_rows_in_order_and_keeps_duplicates(self):
        text = pack_text("WP-FE-001", "WP-FE-002", "WP-FE-001")
        self.assertEqual(check.parse_wbs_ids(text), ["WP-FE-001", "WP-FE-002", "WP-FE-001"])

    def test_parse_ignores_non_row_mentions(self):
        text = "见 WP-FE-009 的说明\n" + pack_text("WP-FE-010")
        self.assertEqual(check.parse_wbs_ids(text), ["WP-FE-010"])

    def test_parse_section_ids_matches_requirements_and_acceptance(self):
        text = "## WP-FE-004 标题\n\n## AC-FE-004 验收\n\n## 别的标题\n"
        self.assertEqual(check.parse_section_ids(text, "WP"), ["WP-FE-004"])
        self.assertEqual(check.parse_section_ids(text, "AC"), ["AC-FE-004"])

    def test_duplicates_of_reports_each_id_once(self):
        self.assertEqual(check.duplicates_of(["a", "b", "a", "a"]), ["a"])


class ConflictTest(unittest.TestCase):
    def test_new_id_is_not_a_conflict(self):
        duplicated, stolen = check.find_wbs_id_conflicts(["WP-FE-001", "WP-FE-002"], ["WP-FE-001"])
        self.assertEqual(duplicated, [])
        self.assertEqual(stolen, [])
        self.assertEqual(check.added_ids_of(["WP-FE-001", "WP-FE-002"], ["WP-FE-001"]), ["WP-FE-002"])

    def test_same_id_twice_in_one_file_is_duplicated(self):
        duplicated, stolen = check.find_wbs_id_conflicts(["WP-FE-001", "WP-FE-001"], [])
        self.assertEqual(duplicated, ["WP-FE-001"])
        self.assertEqual(stolen, [])

    def test_second_row_for_an_id_taken_in_base_is_stolen(self):
        duplicated, stolen = check.find_wbs_id_conflicts(["WP-FE-001", "WP-FE-001"], ["WP-FE-001"])
        self.assertEqual(duplicated, ["WP-FE-001"])
        self.assertEqual(stolen, ["WP-FE-001"])

    def test_base_mentioning_an_id_without_row_is_not_a_take(self):
        # base 里只提到过号（段落标题），表格里没占 —— 不算抢号。
        duplicated, stolen = check.find_wbs_id_conflicts(["WP-FE-005"], [])
        self.assertEqual((duplicated, stolen), ([], []))

    def test_added_section_ids_only_counts_newly_repeated(self):
        # base 里两段同名（既有「同包多段」写法）不算本次新增，不提示；
        # 本次又多出一段同名才提示。
        base = ["WP-FE-001", "WP-FE-001"]
        self.assertEqual(check.find_added_section_ids(base, base), [])
        self.assertEqual(check.find_added_section_ids(base + ["WP-FE-001"], base), ["WP-FE-001"])

    def test_added_section_ids_ignores_brand_new_ids(self):
        # 全新号在 base 里没有同名段，就不是"新增同名段"，不提示。
        self.assertEqual(check.find_added_section_ids(["WP-FE-002"], []), [])


class EndToEndTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="wbs-collision-")
        self.repo = Path(self._tmp.name)
        self.git("init", "-q", "-b", "main", ".")
        (self.repo / "docs" / "wbs").mkdir(parents=True)
        self.write_pack(pack_text("WP-FE-001"))
        (self.repo / "docs" / "wbs" / "01-requirements.md").write_text("# 需求\n\n## WP-FE-001 段\n", encoding="utf-8")
        (self.repo / "docs" / "wbs" / "06-acceptance.md").write_text("# 验收\n\n## AC-FE-001 段\n", encoding="utf-8")
        self.git("add", "-A")
        self.commit("base")
        self.base = self.git("rev-parse", "HEAD").strip()

    def tearDown(self):
        self._tmp.cleanup()

    def git(self, *args: str) -> str:
        done = subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def commit(self, message: str) -> None:
        subprocess.run(["git", "-C", str(self.repo), "-c", "user.email=t@example.com",
                        "-c", "user.name=t", "commit", "-q", "-m", message], check=True)

    def write_pack(self, text: str) -> None:
        (self.repo / "docs" / "wbs" / "02-wbs.md").write_text(text, encoding="utf-8")

    def run_check(self, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(SCRIPT), "docs/wbs", "--base", self.base, *extra],
                              cwd=self.repo, capture_output=True, text=True)

    def test_clean_new_id_passes(self):
        self.write_pack(pack_text("WP-FE-001", "WP-FE-002"))
        done = self.run_check()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("WP-FE-002", done.stdout)

    def test_reusing_an_id_taken_in_base_fails(self):
        self.write_pack(pack_text("WP-FE-001", "WP-FE-001"))
        done = self.run_check()
        self.assertEqual(done.returncode, 1)
        self.assertIn("抢号", done.stderr)

    def test_new_row_for_an_id_only_in_base_fails(self):
        self.write_pack(pack_text("WP-FE-001") + ROW.format(wp_id="WP-FE-001", title="重复"))
        done = self.run_check()
        self.assertEqual(done.returncode, 1)
        self.assertIn("WP-FE-001", done.stderr)

    def test_unreadable_base_skips_instead_of_failing(self):
        self.write_pack(pack_text("WP-FE-001", "WP-FE-002"))
        done = subprocess.run([sys.executable, str(SCRIPT), "docs/wbs", "--base", "origin/不存在"],
                              cwd=self.repo, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0)
        self.assertIn("跳过", done.stdout)

    def test_repeated_section_id_is_a_hint_not_a_failure(self):
        (self.repo / "docs" / "wbs" / "06-acceptance.md").write_text(
            "# 验收\n\n## AC-FE-001 段\n\n## AC-FE-001 又一段\n", encoding="utf-8")
        done = self.run_check()
        self.assertEqual(done.returncode, 0)
        self.assertIn("提示，不失败", done.stdout)

    def test_missing_pack_file_fails(self):
        (self.repo / "docs" / "wbs" / "02-wbs.md").unlink()
        done = self.run_check()
        self.assertEqual(done.returncode, 1)

    def test_no_git_repo_skips(self):
        with tempfile.TemporaryDirectory(prefix="wbs-nogit-") as loose:
            (Path(loose) / "02-wbs.md").write_text(pack_text("WP-FE-001"), encoding="utf-8")
            done = subprocess.run([sys.executable, str(SCRIPT), loose, "--base", self.base],
                                  capture_output=True, text=True)
        self.assertEqual(done.returncode, 0)
        self.assertIn("不在 git 仓库里", done.stdout)


if __name__ == "__main__":
    unittest.main()
