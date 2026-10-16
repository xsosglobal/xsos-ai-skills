import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_release_baseline.py"


def load():
    spec = importlib.util.spec_from_file_location("check_release_baseline", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


M = load()

WBS_HEAD = "| wp_id | title_cn | type | owner | status | acceptance_ref |\n|---|---|---|---|---|---|\n"


def wbs(rows):
    return "# WBS\n\n" + WBS_HEAD + "".join(f"| {wp} | {t} | backend | 顾昊 | {st} | {ac} |\n" for wp, t, st, ac in rows)


def acceptance(sections):
    out = "# Acceptance\n\n"
    for ac, items, verification in sections:
        out += f"## {ac} 标题\n\n中文：\n\n" + "".join(f"- {i}\n" for i in items)
        out += "\nEnglish:\n\n- item\n\nVerification:\n" + "".join(f"- {v}\n" for v in verification) + "\n"
    return out


class Repo:
    def __init__(self, root: Path):
        self.root = root
        subprocess.run(["git", "init", "-q", "-b", "master", str(root)], check=True)
        for k, v in (("user.name", "t"), ("user.email", "t@t")):
            subprocess.run(["git", "-C", str(root), "config", k, v], check=True)

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def commit(self, message):
        subprocess.run(["git", "-C", str(self.root), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-q", "--allow-empty", "-m", message], check=True)
        return subprocess.run(["git", "-C", str(self.root), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


GO_TEST = "package x\n\nfunc TestUndo(t *testing.T) {}\n"


class ReleaseBaselineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Repo(Path(self.tmp.name))
        self.repo.write("README.md", "x")
        self.base = self.repo.commit("init")

    def tearDown(self):
        self.tmp.cleanup()

    def pack(self, status, verification=("`x/undo_test.go:TestUndo`",), items=("能撤回",)):
        self.repo.write("docs/wbs/02-wbs.md", wbs([("WP-BE-177", "撤回", status, "AC-BE-177")]))
        self.repo.write("docs/wbs/06-acceptance.md", acceptance([("AC-BE-177", items, verification)]))

    def run_check(self, end="HEAD"):
        return M.check(self.repo.root, f"{self.base}..{end}")

    def only(self, report):
        self.assertEqual(len(report["packages"]), 1, report)
        return report["packages"][0]

    def test_done_with_all_tests_passes(self):
        self.pack("done")
        self.repo.write("x/undo_test.go", GO_TEST)
        self.repo.commit("feat(WP-BE-177): 撤回")
        p = self.only(self.run_check())
        self.assertEqual(p["verdict"], "ok")
        self.assertEqual(p["evidence"], ["x/undo_test.go:TestUndo"])

    def test_released_but_not_done_asks_to_mark_done(self):
        self.pack("todo")
        self.repo.write("x/undo_test.go", GO_TEST)
        self.repo.commit("feat(WP-BE-177): 撤回")
        report = self.run_check()
        p = self.only(report)
        self.assertEqual(p["verdict"], "warning")
        self.assertIn("应改为 done", p["message"])
        self.assertEqual(report["errors"], [])

    def test_done_with_missing_test_is_error_and_suggests_split(self):
        self.pack("done", verification=("`x/undo_test.go:TestUndo`", "`x/undo_test.go:TestGone`"))
        self.repo.write("x/undo_test.go", GO_TEST)
        self.repo.commit("feat(WP-BE-177): 撤回")
        report = self.run_check()
        p = self.only(report)
        self.assertEqual(p["verdict"], "error")
        self.assertEqual(p["missing"], ["x/undo_test.go:TestGone"])
        self.assertIn("拆成新包", p["message"])
        self.assertEqual(len(report["errors"]), 1)

    def test_no_test_items_need_manual_confirmation(self):
        self.pack("review", verification=("运行全部测试",), items=("能撤回", "写日志"))
        self.repo.write("x/a.go", "package x\n")
        self.repo.commit("feat(WP-BE-177): 撤回")
        p = self.only(self.run_check())
        self.assertEqual(p["verdict"], "warning")
        self.assertEqual(p["unverified_items"], ["AC-BE-177 能撤回", "AC-BE-177 写日志"])

    def test_manual_marked_done_is_not_error(self):
        self.pack("done", verification=("人工：现场走一遍撤回",))
        self.repo.write("x/a.go", "package x\n")
        self.repo.commit("feat(WP-BE-177): 撤回")
        report = self.run_check()
        self.assertEqual(report["errors"], [])
        self.assertEqual(len(self.only(report)["manual"]), 1)

    def test_skips_docs_only_docs_prefix_and_other_repo_ids(self):
        self.pack("todo")
        self.repo.commit("chore(WP-BE-177): 只改文档")  # 只有 docs/ 改动
        self.repo.write("x/a.go", "package x\n")
        self.repo.commit("docs(WP-BE-177): 立包顺手改代码")
        self.repo.write("x/b.go", "package x\n")
        self.repo.commit("feat(WP-FE-161): 别的仓库的包")
        report = self.run_check()
        self.assertEqual(report["packages"], [])
        self.assertEqual(report["ignored"], ["WP-FE-161"])

    def test_skips_merge_commits(self):
        self.pack("todo")
        self.repo.commit("docs: 立包")
        subprocess.run(["git", "-C", str(self.repo.root), "checkout", "-q", "-b", "side"], check=True)
        self.repo.write("x/a.go", "package x\n")
        self.repo.commit("feat: 无包号")
        subprocess.run(["git", "-C", str(self.repo.root), "checkout", "-q", "master"], check=True)
        subprocess.run(["git", "-C", str(self.repo.root), "merge", "-q", "--no-ff", "-m", "Merge WP-BE-177", "side"], check=True)
        self.assertEqual(self.run_check()["packages"], [])

    def test_reads_pack_from_range_end_not_worktree(self):
        self.pack("todo")
        self.repo.write("x/undo_test.go", GO_TEST)
        self.repo.commit("feat(WP-BE-177): 撤回")
        self.pack("done")  # 工作树改了但没提交
        self.assertEqual(self.only(self.run_check())["status"], "todo")

    def test_enable_file_makes_errors_blocking(self):
        self.pack("done", verification=("`x/undo_test.go:TestGone`",))
        self.repo.write("x/undo_test.go", GO_TEST)
        self.repo.commit("feat(WP-BE-177): 撤回")
        self.assertFalse(self.run_check()["enabled"])
        self.repo.write("docs/wbs/release-check.enabled", "")
        self.repo.commit("docs: 开启发布核对")
        cli = subprocess.run([sys.executable, str(SCRIPT), f"{self.base}..HEAD", "--repo", str(self.repo.root)],
                             capture_output=True, text=True)
        self.assertEqual(cli.returncode, 1, cli.stdout + cli.stderr)
        self.assertIn("✗ WP-BE-177", cli.stdout)

    def test_not_enabled_never_fails(self):
        self.pack("done", verification=("`x/undo_test.go:TestGone`",))
        self.repo.write("x/a.go", "package x\n")
        self.repo.commit("feat(WP-BE-177): 撤回")
        cli = subprocess.run([sys.executable, str(SCRIPT), f"{self.base}..HEAD", "--repo", str(self.repo.root)],
                             capture_output=True, text=True)
        self.assertEqual(cli.returncode, 0, cli.stdout + cli.stderr)
        self.assertIn("未开启阻断", cli.stdout)

    def test_ts_symbol_matches_by_name(self):
        self.pack("done", verification=("`web/a.test.tsx:rendersUndo`",))
        self.repo.write("web/a.test.tsx", "it('x', function rendersUndo() {})\n")
        self.repo.commit("feat(WP-BE-177): 撤回")
        self.assertEqual(self.only(self.run_check())["verdict"], "ok")


if __name__ == "__main__":
    unittest.main()
