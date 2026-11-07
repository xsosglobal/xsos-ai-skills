"""一个包一件事落到门禁(顾昊 2026-11-07):增量小节计数、增量续命、已上生产的包不许再长。"""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


V = load("validate_wbs_pack_gate", "validate_wbs_pack.py")
G = load("check_shipped_package_growth", "check_shipped_package_growth.py")

WBS_HEAD = ("| wp_id | title_cn | title_en | type | owner | status | depends_on "
            "| acceptance_ref | outputs |\n|---|---|---|---|---|---|---|---|---|\n")


def wbs(rows, extra=""):
    body = "".join(
        f"| {wp} | 包{wp[-3:]} | Package | frontend | 卢 | {status} | none | {ac} | code |\n"
        for wp, status, ac in rows
    )
    return "# WBS\n\n" + WBS_HEAD + body + extra


def bullets(n, prefix="条目"):
    return "".join(f"- {prefix} {i}。\n" for i in range(1, n + 1))


def ac_section(ac, n):
    return (f"## {ac} 标题\n\n{bullets(n)}\nEnglish:\n{bullets(n, 'item')}\n"
            f"Verification:\n- `src/a.test.ts` 用例\n\n")


class MeasureTest(unittest.TestCase):
    ROWS = [(1, {"wp_id": "WP-FE-266", "acceptance_ref": "AC-FE-266", "status": "review"}),
            (2, {"wp_id": "WP-FE-121", "acceptance_ref": "AC-FE-121", "status": "done"}),
            (3, {"wp_id": "WP-FE-122", "acceptance_ref": "AC-FE-121-LOCAL-PRINT", "status": "done"})]

    def measure(self, text):
        return {wp: m["items"] for wp, m in V.measure_package_acceptance(text, self.ROWS).items()}

    def test_increment_sections_are_counted(self):
        """AC 节内的 ###、以包号/AC 号开头的 ##/### 小节都算进该包;英文与证据不算。"""
        text = (
            "# Acceptance\n\n"
            + ac_section("AC-FE-266", 3)
            + "### 补充小节\n\n- 节内小节一条。\n\nEnglish:\n- en\n\n"
            + "## WP-FE-266 第二版接入（2026-11-04）\n\n- 增量一。\n- 增量二。\n\n"
            + "Verification:\n- `src/b.test.ts` 用例\n- 不该数\n\n"
            + "## 无关标题\n\n- 不属于任何包。\n\n"
            + "### WP-FE-266 一段话的增量（2026-11-05）\n\n分类页按原型对齐,目录与属性各自滚动。\n\n"
            + "## AC-FE-266-V9-INVENTORY（2026-11-06）\n\n- 后缀验收。\n\n"
        )
        # 3(AC 节)+1(节内 ###)+2(## 增量)+1(一段话至少算 1)+1(AC 号加后缀)
        self.assertEqual(self.measure(text)["WP-FE-266"], 8)

    def test_own_section_of_suffixed_ref_is_not_stolen(self):
        """AC-FE-121-LOCAL-PRINT 是 WP-FE-122 自己的 AC,不能当成 WP-FE-121 的增量。"""
        text = "# A\n\n" + ac_section("AC-FE-121", 2) + ac_section("AC-FE-121-LOCAL-PRINT", 4)
        counts = self.measure(text)
        self.assertEqual(counts["WP-FE-121"], 2)
        self.assertEqual(counts["WP-FE-122"], 4)

    def test_verification_heading_stops_counting(self):
        """`### Verification Results` 之后的 PASS 列表是证据,不是验收条目。"""
        text = ("# A\n\n## AC-FE-266 标题\n\n" + bullets(3)
                + "\n### Verification Results / 验证结果\n\n- PASS：一\n- PASS：二\n")
        self.assertEqual(self.measure(text)["WP-FE-266"], 3)


class PackTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pack = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rows, acceptance, wbs_extra="", baseline=None):
        (self.pack / "02-wbs.md").write_text(wbs(rows, wbs_extra), encoding="utf-8")
        (self.pack / "06-acceptance.md").write_text("# Acceptance\n\n" + acceptance, encoding="utf-8")
        if baseline is not None:
            (self.pack / "granularity-baseline.txt").write_text(baseline, encoding="utf-8")


class IncrementCheckTest(PackTestCase):
    INCREMENT = "## WP-FE-300 包装合并视图（2026-11-07）\n\n- 新增一条。\n\n"

    def test_without_baseline_only_warns(self):
        self.write([("WP-FE-300", "review", "AC-FE-300")], ac_section("AC-FE-300", 2) + self.INCREMENT)
        errors, warnings = V.check_increments(self.pack)
        self.assertEqual(errors, [])
        self.assertTrue(any("WP-FE-300(1)" in w for w in warnings), warnings)

    def test_increment_section_blocks_once_enabled(self):
        self.write([("WP-FE-300", "review", "AC-FE-300")], ac_section("AC-FE-300", 2) + self.INCREMENT,
                   baseline="# 存量\n")
        errors, _ = V.check_increments(self.pack)
        self.assertEqual(len(errors), 1)
        self.assertIn("WP-FE-300 has 1 increment section", errors[0])
        self.assertIn("06-acceptance.md:", errors[0])
        # validate() 也把它当错误
        self.assertTrue(any("increment section" in e for e in V.validate(self.pack)["errors"]))

    def test_dated_section_in_wbs_counts_but_detail_note_does_not(self):
        extra = ("\n### WP-FE-300 执行边界 / Execution Boundary\n\n只做前端。\n\n"
                 "### WP-FE-301 第十八版接口接入（2026-11-07）\n\n接入新版。\n")
        self.write([("WP-FE-300", "todo", "AC-FE-300"), ("WP-FE-301", "todo", "AC-FE-301")],
                   ac_section("AC-FE-300", 1) + ac_section("AC-FE-301", 1),
                   wbs_extra=extra, baseline="# 存量\n")
        errors, _ = V.check_increments(self.pack)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("WP-FE-301", errors[0])

    def test_baseline_exempts_existing_increments(self):
        self.write([("WP-FE-300", "review", "AC-FE-300")], ac_section("AC-FE-300", 2) + self.INCREMENT,
                   baseline="WP-FE-300  2026-11-07 开启门禁时存量\n")
        errors, _ = V.check_increments(self.pack)
        self.assertEqual(errors, [])
        # 豁免了增量的包不算过期条目
        _, warnings = V.check_granularity(self.pack)
        self.assertFalse(any("only shrinks" in w for w in warnings), warnings)

    def test_in_flight_marker_keeps_unfinished_backlog_exempt(self):
        """开门禁时就在途的超标包:理由以「未完工存量」开头才不随状态失效。"""
        acceptance = ac_section("AC-FE-300", 10) + ac_section("AC-FE-301", 10)
        self.write([("WP-FE-300", "in_progress", "AC-FE-300"), ("WP-FE-301", "todo", "AC-FE-301")],
                   acceptance,
                   baseline="WP-FE-300  未完工存量：2026-11-07 开启门禁时 in_progress\n"
                            "WP-FE-301  2026-11-07 开启门禁时存量\n")
        errors, _ = V.check_granularity(self.pack)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("WP-FE-301", errors[0])
        self.assertIn("no longer applies", errors[0])

    def test_increments_push_package_over_granularity_limit(self):
        """增量小节计数后超过 8 条,开启门禁时新包直接失败。"""
        many = "".join(f"### WP-FE-300 增量{i}（2026-11-0{i}）\n\n- 条目。\n\n" for i in range(1, 8))
        self.write([("WP-FE-300", "review", "AC-FE-300")], ac_section("AC-FE-300", 3) + many,
                   baseline="# 存量\n")
        errors, _ = V.check_granularity(self.pack)
        self.assertTrue(any("WP-FE-300 has 10 acceptance items" in e for e in errors), errors)


class Repo:
    def __init__(self, root: Path):
        self.root = root
        subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
        for k, v in (("user.name", "t"), ("user.email", "t@t")):
            subprocess.run(["git", "-C", str(root), "config", k, v], check=True)

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD")


class ShippedGrowthTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Repo(Path(self.tmp.name))
        rows = [("WP-FE-300", "review", "AC-FE-300"), ("WP-FE-301", "todo", "AC-FE-301")]
        self.repo.write("docs/wbs/02-wbs.md", wbs(rows))
        self.repo.write("docs/wbs/06-acceptance.md",
                        "# A\n\n" + ac_section("AC-FE-300", 2) + ac_section("AC-FE-301", 2))
        self.repo.write("docs/wbs/granularity-baseline.txt", "# 存量\n")
        self.repo.commit("docs(WP-FE-300): 立包")
        self.repo.write("src/a.ts", "a")
        self.repo.commit("feat(WP-FE-300): 基础页")
        # 只改文档、只在 docs 提交里点名的 WP-FE-301 不算上生产
        self.repo.write("docs/wbs/note.md", "x")
        self.repo.commit("feat(WP-FE-301): 只改了文档")
        self.repo.git("branch", "develop")
        self.repo.git("checkout", "-q", "develop")

    def tearDown(self):
        self.tmp.cleanup()

    def grow(self, ac, extra):
        path = self.repo.root / "docs/wbs/06-acceptance.md"
        path.write_text(path.read_text(encoding="utf-8") + extra, encoding="utf-8")
        return self.repo.commit(f"docs: 给 {ac} 加验收")

    def test_shipped_package_growth_is_blocked(self):
        base = self.repo.git("rev-parse", "HEAD")
        self.grow("WP-FE-300", "### WP-FE-300 包装合并视图（2026-11-07）\n\n- 新增一条。\n\n")
        report = G.check(self.repo.root, f"{base}..HEAD", "main")
        self.assertTrue(report["enabled"])
        self.assertEqual(len(report["errors"]), 1, report)
        self.assertIn("WP-FE-300 已上生产", report["errors"][0])
        self.assertIn("2 增到 3", report["errors"][0])

    def test_unshipped_package_may_grow(self):
        base = self.repo.git("rev-parse", "HEAD")
        self.grow("WP-FE-301", "### WP-FE-301 补一条（2026-11-07）\n\n- 新增一条。\n\n")
        report = G.check(self.repo.root, f"{base}..HEAD", "main")
        self.assertEqual(report["errors"], [], report)
        self.assertEqual([g["wp_id"] for g in report["grown"]], ["WP-FE-301"])

    def test_trailer_in_body_counts_as_shipped(self):
        self.repo.git("checkout", "-q", "main")
        self.repo.write("src/b.ts", "b")
        self.repo.commit("fix: 修个问题\n\nWork-Package: WP-FE-301")
        self.repo.git("checkout", "-q", "develop")
        self.repo.git("merge", "-q", "main")
        base = self.repo.git("rev-parse", "HEAD")
        self.grow("WP-FE-301", "## AC-FE-301-V2 第二版\n\n- 新增一条。\n\n")
        report = G.check(self.repo.root, f"{base}..HEAD", "main")
        self.assertEqual(len(report["errors"]), 1, report)
        self.assertIn("WP-FE-301", report["errors"][0])

    def test_release_pr_is_skipped(self):
        self.grow("WP-FE-300", "### WP-FE-300 包装合并视图（2026-11-07）\n\n- 新增一条。\n\n")
        report = G.check(self.repo.root, "main..HEAD", "main")
        self.assertTrue(report["skipped"])
        self.assertEqual(report["errors"], [])

    def test_missing_prod_ref_is_reported(self):
        base = self.repo.git("rev-parse", "HEAD")
        report = G.check(self.repo.root, f"{base}..HEAD", "origin/nope")
        self.assertTrue(any("取不到生产分支" in e for e in report["errors"]), report)

    def test_not_enabled_only_reports(self):
        base = self.repo.git("rev-parse", "HEAD")
        (self.repo.root / "docs/wbs/granularity-baseline.txt").unlink()
        self.grow("WP-FE-300", "### WP-FE-300 包装合并视图（2026-11-07）\n\n- 新增一条。\n\n")
        report = G.check(self.repo.root, f"{base}..HEAD", "main")
        self.assertFalse(report["enabled"])
        self.assertEqual(len(report["errors"]), 1)
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "check_shipped_package_growth.py"), f"{base}..HEAD",
             "--prod", "main", "--repo", str(self.repo.root)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
