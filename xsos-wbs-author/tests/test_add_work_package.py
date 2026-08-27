import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "add_work_package.py"


def load():
    spec = importlib.util.spec_from_file_location("add_work_package", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MINIMAL_SPEC = {
    "title_cn": "采购对账差异表",
    "title_en": "Purchase reconciliation diff",
    "type": "backend",
    "owner": "顾昊",
    "scope": "录入发票原值并与采购单逐行比对",
    "non_goals": "不改 Web",
    "requirements": ["发票金额必须录入原值，不得由系统反算。"],
    "acceptance": ["差异表能列出金额不一致的行项。"],
}


def make_pack(root: Path, rows=("WP-BE-001",)):
    root.mkdir(parents=True, exist_ok=True)
    header = "| wp_id | title_cn | title_en | type | owner | status | depends_on | scope | non_goals | acceptance_ref | outputs |"
    sep = "|---|---|---|---|---|---|---|---|---|---|---|"
    body = [
        f"| {wp} | 旧包 | Old | backend | 顾昊 | done | none | s | n | AC-{wp[3:]} | o |"
        for wp in rows
    ]
    (root / "02-wbs.md").write_text("# WBS\n\n" + "\n".join([header, sep] + body) + "\n", encoding="utf-8")
    (root / "01-requirements.md").write_text(
        "# 需求 / Requirements\n\n" + "".join(f"## {wp} 旧包\n\n- 旧需求。\n\n" for wp in rows),
        encoding="utf-8")
    (root / "06-acceptance.md").write_text(
        "# 验收 / Acceptance\n\n" + "".join(f"## AC-{wp[3:]} 旧包\n\n- 旧验收。\n\n" for wp in rows),
        encoding="utf-8")
    (root / "07-risks.md").write_text("# 风险 / Risks\n\n", encoding="utf-8")
    (root / "CHANGELOG.md").write_text("# CHANGELOG\n\n", encoding="utf-8")
    # validator 要求完整结构，缺一个文件就整包 INVALID
    for name, heading in [
        ("00-brief.md", "# 概述 / Brief\n\n## Goal / 项目目标\n\n- 让测试跑起来。\n\n## Non-goals / 非目标\n\n- 别的都不管。"),
        ("03-page-spec.md", "# 页面 / Page Spec"),
        ("04-api-contract.md", "# 接口 / API Contract"),
        ("05-data-contract.md", "# 数据 / Data Contract"),
        ("08-implementation-rules.md", "# 实现约定 / Implementation Rules"),
        ("10-handoff.md", "# 交接 / Handoff"),
        ("OWNERS.md", "# OWNERS"),
    ]:
        (root / name).write_text(heading + "\n\n", encoding="utf-8")
    return root


def run(pack: Path, spec: dict, *extra):
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(pack), "--spec", "-", *extra],
        input=json.dumps(spec, ensure_ascii=False), capture_output=True, text=True)


class AddWorkPackageTest(unittest.TestCase):
    def test_allocates_next_id_and_writes_three_files(self):
        with tempfile.TemporaryDirectory() as raw:
            pack = make_pack(Path(raw) / "wbs", rows=("WP-BE-001", "WP-BE-007"))
            result = run(pack, MINIMAL_SPEC)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

            wbs = (pack / "02-wbs.md").read_text(encoding="utf-8")
            self.assertIn("| WP-BE-008 |", wbs)
            self.assertIn("AC-BE-008", wbs)
            self.assertIn("## WP-BE-008 采购对账差异表", (pack / "01-requirements.md").read_text(encoding="utf-8"))
            self.assertIn("## AC-BE-008 采购对账差异表", (pack / "06-acceptance.md").read_text(encoding="utf-8"))

    def test_new_row_lands_inside_the_table(self):
        """插入不得在表格中间留空行——空行会让 validator 静默跳过后面所有行。"""
        with tempfile.TemporaryDirectory() as raw:
            pack = make_pack(Path(raw) / "wbs")
            self.assertEqual(0, run(pack, MINIMAL_SPEC).returncode)
            lines = (pack / "02-wbs.md").read_text(encoding="utf-8").splitlines()
            start = next(i for i, l in enumerate(lines) if l.startswith("| wp_id"))
            block = []
            for line in lines[start:]:
                if not line.strip():
                    break
                block.append(line)
            self.assertEqual(4, len(block), "表头 + 分隔 + 旧包 + 新包 应连成一片")
            self.assertTrue(block[2].startswith("| WP-BE-002 |"), block)

    def test_rejects_duplicate_wp_id(self):
        with tempfile.TemporaryDirectory() as raw:
            pack = make_pack(Path(raw) / "wbs")
            spec = dict(MINIMAL_SPEC, wp_id="WP-BE-001")
            result = run(pack, spec)
            self.assertEqual(2, result.returncode)
            self.assertIn("已存在", result.stderr)

    def test_rejects_pipe_in_field(self):
        with tempfile.TemporaryDirectory() as raw:
            pack = make_pack(Path(raw) / "wbs")
            spec = dict(MINIMAL_SPEC, scope="a | b")
            result = run(pack, spec)
            self.assertEqual(2, result.returncode)
            self.assertIn("表格切断", result.stderr)

    def test_rejects_dangling_dependency(self):
        with tempfile.TemporaryDirectory() as raw:
            pack = make_pack(Path(raw) / "wbs")
            spec = dict(MINIMAL_SPEC, depends_on=["WP-BE-999"])
            result = run(pack, spec)
            self.assertEqual(2, result.returncode)
            self.assertIn("悬空", result.stderr)

    def test_rejects_bad_status(self):
        with tempfile.TemporaryDirectory() as raw:
            pack = make_pack(Path(raw) / "wbs")
            result = run(pack, dict(MINIMAL_SPEC, status="doing"))
            self.assertEqual(2, result.returncode)

    def test_missing_requirements_is_refused(self):
        with tempfile.TemporaryDirectory() as raw:
            pack = make_pack(Path(raw) / "wbs")
            spec = {k: v for k, v in MINIMAL_SPEC.items() if k != "requirements"}
            result = run(pack, spec)
            self.assertEqual(2, result.returncode)
            self.assertIn("requirements", result.stderr)

    def test_risks_and_changelog_are_optional_but_wired(self):
        with tempfile.TemporaryDirectory() as raw:
            pack = make_pack(Path(raw) / "wbs")
            spec = dict(MINIMAL_SPEC,
                        risks=[{"title": "发票口径未确认", "body": "供应商开票方式未知。"}],
                        changelog="新增采购对账差异表。", date="2026-08-27")
            self.assertEqual(0, run(pack, spec).returncode)
            self.assertIn("RISK-BE-002-001", (pack / "07-risks.md").read_text(encoding="utf-8"))
            log = (pack / "CHANGELOG.md").read_text(encoding="utf-8")
            self.assertIn("## 2026-08-27", log)
            self.assertIn("`WP-BE-002`", log)

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as raw:
            pack = make_pack(Path(raw) / "wbs")
            before = (pack / "02-wbs.md").read_text(encoding="utf-8")
            result = run(pack, MINIMAL_SPEC, "--dry-run")
            self.assertEqual(0, result.returncode)
            self.assertEqual(before, (pack / "02-wbs.md").read_text(encoding="utf-8"))

    def test_next_wp_id_skips_gaps_and_never_reuses(self):
        module = load()
        text = "| WP-BE-001 |\n| WP-BE-004 |\n"
        self.assertEqual("WP-BE-005", module.next_wp_id(text, "BE"))
        self.assertEqual("WP-FS-001", module.next_wp_id(text, "FS"))

    def test_next_wp_id_takes_union_with_integration_branch(self):
        """当前工作树落后时,编号必须按集成分支/远端分支的并集取。

        2026-08-27 连撞两次:一次基于落后 12 个提交的 local 算出已被占用的
        076,一次是 PR 挂着期间 080 被并行会话抢走。只看本地文件必然复现。
        """
        module = load()
        local = "| WP-BE-001 |\n| WP-BE-075 |\n"
        remote = "| WP-BE-076 |\n| WP-BE-080 |\n"
        self.assertEqual("WP-BE-076", module.next_wp_id(local, "BE"))
        self.assertEqual("WP-BE-081", module.next_wp_id(local, "BE", remote))
        # 本地有未推的新包时,并集要把它也算上
        self.assertEqual("WP-BE-091", module.next_wp_id(local + "| WP-BE-090 |\n", "BE", remote))


if __name__ == "__main__":
    unittest.main()
