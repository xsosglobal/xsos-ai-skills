import re
import tempfile
import unittest
from pathlib import Path

from importlib.util import module_from_spec, spec_from_file_location


SCRIPT = Path(__file__).parents[1] / "scripts/validate_wbs_pack.py"
SPEC = spec_from_file_location("validate_wbs_pack", SCRIPT)
MODULE = module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class ValidateWBSPackTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.pack = Path(self.temp.name) / "docs/wbs"
        self.pack.mkdir(parents=True)
        content = {
            "00-brief.md": "# Brief\n\n## Goal\nTest.\n\n## Non-goals\nNone.\n",
            "01-requirements.md": "# Requirements\n",
            "02-wbs.md": self.wbs_rows([
                "| WP-BE-001 | 任务一 | Task one | backend | owner | todo | none | AC-BE-001 | code |",
                "| WP-BE-002 | 任务二 | Task two | backend | owner | todo | WP-BE-001 | AC-BE-002 | tests |",
            ]),
            "03-page-spec.md": "# Page Spec\n\nNot applicable.\n",
            "04-api-contract.md": "# API Contract\n",
            "05-data-contract.md": "# Data Contract\n",
            "06-acceptance.md": "# Acceptance\n\n## AC-BE-001: One\n\nVerification: test.\n\n## AC-BE-002: Two\n\nVerification: test.\n",
            "07-risks.md": "# Risks\n",
            "08-implementation-rules.md": "# Rules\n",
            "CHANGELOG.md": "# Changelog\n",
            "OWNERS.md": "# Owners\n",
        }
        for name, text in content.items():
            (self.pack / name).write_text(text, encoding="utf-8")
        self.write_wbs([
            "| WP-BE-001 | 任务一 | Task one | backend | owner | todo | none | AC-BE-001 | code |",
            "| WP-BE-002 | 任务二 | Task two | backend | owner | todo | WP-BE-001 | AC-BE-002 | tests |",
        ])


    def write_wbs(self, rows, *, sync_requirements=True):
        """Write the work-package table, keeping 01-requirements.md in sync.

        需求覆盖是一项独立门禁；测其他检查的用例不应因为夹具缺需求而失败。
        用 sync_requirements=False 显式构造「缺需求」的场景。
        """
        (self.pack / "02-wbs.md").write_text(self.wbs_rows(rows), encoding="utf-8")
        if not sync_requirements:
            (self.pack / "01-requirements.md").write_text("# Requirements\n", encoding="utf-8")
            return
        ids = sorted({
            match.group(1)
            for row in rows
            if (match := re.match(r"\|\s*(WP-[A-Z0-9-]+\d)", row))
        })
        body = "".join(f"## {wp_id} placeholder\n\n- requirement item.\n\n" for wp_id in ids)
        (self.pack / "01-requirements.md").write_text("# Requirements\n\n" + body, encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def wbs_rows(rows):
        return "\n".join([
            "# WBS",
            "",
            "| wp_id | title_cn | title_en | type | owner | status | depends_on | acceptance_ref | outputs |",
            "|---|---|---|---|---|---|---|---|---|",
            *rows,
            "",
        ])

    def test_short_row_fails_instead_of_being_padded(self):
        """一行少一列必须报错，不能被静默补空。

        2026-09-06 之前，parse_markdown_tables 对缺失单元格填空串，于是
        「这一行少了一列」和「那一列的值是空的」在下游完全无法区分——
        砍掉整整一列，validator 仍然 rc=0。实际踩到过：给一个 9 列的表
        插入两列时脚本只匹配了部分行，一半行 11 列、一半行 9 列，validator
        一声不吭。
        """
        self.write_wbs([
            "| WP-BE-001 | 任务一 | Task one | backend | owner | todo | none | AC-BE-001 |",
            "| WP-BE-002 | 任务二 | Task two | backend | owner | todo | WP-BE-001 | AC-BE-002 | tests |",
        ])
        result = MODULE.validate(self.pack)
        self.assertFalse(result["valid"], result["errors"])
        self.assertTrue(
            any("cells but the header has" in item for item in result["errors"]),
            result["errors"],
        )

    def test_long_row_also_fails(self):
        """多一列同样是形状错误：它会把后面所有列的值整体错位。"""
        self.write_wbs([
            "| WP-BE-001 | 任务一 | Task one | backend | owner | todo | none | AC-BE-001 | code | 多余 |",
            "| WP-BE-002 | 任务二 | Task two | backend | owner | todo | WP-BE-001 | AC-BE-002 | tests |",
        ])
        result = MODULE.validate(self.pack)
        self.assertFalse(result["valid"], result["errors"])
        self.assertTrue(any("cells but the header has" in item for item in result["errors"]))

    def test_consistent_rows_still_pass(self):
        """形状一致的表不受这条新检查影响。"""
        result = MODULE.validate(self.pack)
        self.assertTrue(result["valid"], result["errors"])

    def wbs_with_boundaries(self, rows):
        """写一张带 scope / non_goals 两列的表。"""
        header = ("| wp_id | title_cn | title_en | type | owner | status | depends_on "
                  "| scope | non_goals | acceptance_ref | outputs |\n"
                  "|---|---|---|---|---|---|---|---|---|---|---|\n")
        (self.pack / "02-wbs.md").write_text("# WBS\n\n" + header + "\n".join(rows) + "\n",
                                             encoding="utf-8")
        ids = sorted({re.match(r"\|\s*(WP-[A-Z0-9-]+\d)", r).group(1) for r in rows})
        body = "".join(f"## {i} placeholder\n\n- requirement item.\n\n" for i in ids)
        (self.pack / "01-requirements.md").write_text("# Requirements\n\n" + body, encoding="utf-8")

    FULL = ("| WP-BE-001 | 一 | One | backend | owner | todo | none "
            "| 做这个 | 不做那个 | AC-BE-001 | code |")
    BLANK = ("| WP-BE-002 | 二 | Two | backend | owner | todo | none "
             "|  |  | AC-BE-002 | tests |")

    def test_no_baseline_file_only_warns(self):
        """没有 boundary-baseline.txt 时只警告——门禁按仓库自愿加入。

        上线时全公司 13 个仓库、约 175 个包一个边界都没声明，一次性变红
        只会让人把门禁关掉。转换 SOP 自己也写着不要让所有仓库门禁同时变红。
        """
        self.wbs_with_boundaries([self.FULL, self.BLANK])
        result = MODULE.validate(self.pack)
        self.assertTrue(result["valid"], result["errors"])
        self.assertTrue(any("empty scope or non_goals" in w for w in result["warnings"]),
                        result["warnings"])

    def test_baseline_file_turns_it_into_a_gate(self):
        """建了 baseline 就等于开启门禁：不在清单里的缺边界直接失败。"""
        self.wbs_with_boundaries([self.FULL, self.BLANK])
        (self.pack / "boundary-baseline.txt").write_text("# 存量\n", encoding="utf-8")
        result = MODULE.validate(self.pack)
        self.assertFalse(result["valid"])
        self.assertTrue(any("WP-BE-002 has an empty scope or non_goals" in e
                            for e in result["errors"]), result["errors"])

    def test_grandfathered_package_passes_with_warning(self):
        self.wbs_with_boundaries([self.FULL, self.BLANK])
        (self.pack / "boundary-baseline.txt").write_text("WP-BE-002\n", encoding="utf-8")
        result = MODULE.validate(self.pack)
        self.assertTrue(result["valid"], result["errors"])
        self.assertTrue(any("grandfathered by boundary-baseline.txt" in w
                            for w in result["warnings"]), result["warnings"])

    def test_baseline_only_shrinks(self):
        """包补上边界后，提示把它从清单里删掉——单向棘轮。"""
        self.wbs_with_boundaries([self.FULL])
        (self.pack / "boundary-baseline.txt").write_text("WP-BE-001\n", encoding="utf-8")
        result = MODULE.validate(self.pack)
        self.assertTrue(result["valid"], result["errors"])
        self.assertTrue(any("remove them so the list only shrinks" in w
                            for w in result["warnings"]), result["warnings"])

    # ---- 颗粒度门禁 ----

    def wbs_with_acceptance(self, packages):
        """packages: [(wp_id, status, 验收条目数)]，写出配套的 02-wbs 与 06-acceptance。"""
        header = ("| wp_id | title_cn | title_en | type | owner | status | depends_on "
                  "| acceptance_ref | outputs |\n"
                  "|---|---|---|---|---|---|---|---|---|\n")
        rows = "\n".join(
            f"| {wp} | 包 | Package | backend | owner | {status} | none | AC-{wp[3:]} | code |"
            for wp, status, _ in packages
        )
        (self.pack / "02-wbs.md").write_text("# WBS\n\n" + header + rows + "\n", encoding="utf-8")
        (self.pack / "01-requirements.md").write_text(
            "# Requirements\n\n" + "".join(
                f"## {wp} placeholder\n\n- requirement item.\n\n" for wp, _, _ in packages),
            encoding="utf-8")
        body = ""
        for wp, _, count in packages:
            items = "".join(f"- 第 {i} 条验收。\n" for i in range(1, count + 1))
            # 英文段落一并写上:计数必须只数中文那一半,否则每个包的规模凭空翻倍。
            body += (f"## AC-{wp[3:]}: 标题\n\n{items}\n"
                     f"English:\n{items}\nVerification: run tests.\n\n")
        (self.pack / "06-acceptance.md").write_text("# Acceptance\n\n" + body, encoding="utf-8")

    def test_granularity_no_baseline_only_warns(self):
        """没有 granularity-baseline.txt 时只警告——与边界门禁同一套自愿加入语义。"""
        self.wbs_with_acceptance([("WP-BE-001", "todo", 12)])
        result = MODULE.validate(self.pack)
        self.assertTrue(result["valid"], result["errors"])
        self.assertTrue(any("exceed 8 acceptance items" in w for w in result["warnings"]),
                        result["warnings"])

    def test_granularity_counts_chinese_half_only(self):
        """中英文各写一遍时只数中文那半。

        实测:两边都数会把 auth-center 从「6 个超标」变成「32 个超标」,
        门禁会立刻失去可信度。
        """
        self.wbs_with_acceptance([("WP-BE-001", "todo", 5)])   # 中文 5 条,英文另 5 条
        result = MODULE.validate(self.pack)
        self.assertFalse(any("acceptance items" in w for w in result["warnings"]),
                         result["warnings"])

    def test_granularity_baseline_turns_it_into_a_gate(self):
        self.wbs_with_acceptance([("WP-BE-001", "todo", 12)])
        (self.pack / "granularity-baseline.txt").write_text("# 存量\n", encoding="utf-8")
        result = MODULE.validate(self.pack)
        self.assertFalse(result["valid"])
        self.assertTrue(any("WP-BE-001 has 12 acceptance items" in e for e in result["errors"]),
                        result["errors"])

    def test_granularity_frozen_package_passes(self):
        """已完工的超标包记账后放行——拆一个已交付的包是纯文档考古。"""
        self.wbs_with_acceptance([("WP-BE-001", "done", 12)])
        (self.pack / "granularity-baseline.txt").write_text(
            "WP-BE-001  四个可独立验收的行为，上线前已交付\n", encoding="utf-8")
        result = MODULE.validate(self.pack)
        self.assertTrue(result["valid"], result["errors"])

    def test_granularity_exemption_dies_when_reopened(self):
        """状态退回重做,豁免立刻失效——否则「先记个账」会变成绕过规则的默认路径。"""
        self.wbs_with_acceptance([("WP-BE-001", "in_progress", 12)])
        (self.pack / "granularity-baseline.txt").write_text("WP-BE-001  存量\n", encoding="utf-8")
        result = MODULE.validate(self.pack)
        self.assertFalse(result["valid"])
        self.assertTrue(any("no longer applies" in e for e in result["errors"]), result["errors"])

    def test_granularity_baseline_only_shrinks_but_does_not_block(self):
        """包被拆小之后提示删条目,但不阻断:变红等于惩罚好行为。"""
        self.wbs_with_acceptance([("WP-BE-001", "done", 3)])
        (self.pack / "granularity-baseline.txt").write_text("WP-BE-001  存量\n", encoding="utf-8")
        result = MODULE.validate(self.pack)
        self.assertTrue(result["valid"], result["errors"])
        self.assertTrue(any("remove them so the list only shrinks" in w
                            for w in result["warnings"]), result["warnings"])

    def test_granularity_sees_non_wp_prefixes(self):
        """非 WP- 前缀的包也要量。

        搬进规则源之前这道门禁在 auth-center 本地,过滤 `wp_id.startswith("WP-")`,
        于是 xsos-platform-core 的 21 个 P2-/P3-/P4- 包被整体跳过,只量到 10 个。
        """
        self.wbs_with_acceptance([("P2-BE-001", "todo", 12)])
        result = MODULE.validate(self.pack)
        self.assertTrue(any("1/1 work packages exceed" in w for w in result["warnings"]),
                        result["warnings"])

    def test_nine_column_table_is_skipped(self):
        """没有这两列的旧形状跳过：那是「该加列」不是「该填内容」。"""
        result = MODULE.validate(self.pack)   # setUp 写的是 9 列表
        self.assertFalse(any("scope or non_goals" in w for w in result["warnings"]),
                         result["warnings"])

    def test_distinct_work_package_ids_pass(self):
        result = MODULE.validate(self.pack)
        self.assertTrue(result["valid"], result["errors"])

    def test_duplicate_work_package_id_fails_with_all_line_numbers(self):
        self.write_wbs([
            "| WP-BE-006 | 任务一 | Task one | backend | owner | done | none | AC-BE-001 | code |",
            "| WP-BE-036 | 任务二 | Task two | backend | owner | review | none | AC-BE-002 | tests |",
            "| WP-BE-006 | 任务三 | Task three | backend | owner | todo | none | AC-BE-001 | docs |",
            "| WP-BE-036 | 任务四 | Task four | backend | owner | todo | none | AC-BE-002 | api |",
        ])

        result = MODULE.validate(self.pack)

        self.assertFalse(result["valid"])
        self.assertIn(
            "duplicate wp_id across packs: WP-BE-006 (02-wbs.md:5, 02-wbs.md:7)", result["errors"]
        )
        self.assertIn(
            "duplicate wp_id across packs: WP-BE-036 (02-wbs.md:6, 02-wbs.md:8)", result["errors"]
        )

    def test_missing_acceptance_and_local_dependency_fail(self):
        self.write_wbs([
            "| WP-BE-001 | 任务一 | Task one | backend | owner | todo | WP-BE-099 | AC-BE-099 | code |",
        ])

        result = MODULE.validate(self.pack)

        self.assertFalse(result["valid"])
        self.assertTrue(any("missing dependency: WP-BE-001 -> WP-BE-099" in item for item in result["errors"]))
        self.assertTrue(any("acceptance reference not found: WP-BE-001 -> AC-BE-099" in item for item in result["errors"]))

    def test_cross_project_dependency_is_not_treated_as_local(self):
        self.write_wbs([
            "| WP-BE-001 | 任务一 | Task one | backend | owner | todo | xsos-masterdata WP-INTEG-002 | AC-BE-001 | code |",
        ])

        result = MODULE.validate(self.pack)

        self.assertTrue(result["valid"], result["errors"])

    def test_duplicate_acceptance_and_dependency_cycle_fail(self):
        self.write_wbs([
            "| WP-BE-001 | 任务一 | Task one | backend | owner | todo | WP-BE-002 | AC-BE-001 | code |",
            "| WP-BE-002 | 任务二 | Task two | backend | owner | todo | WP-BE-001 | AC-BE-002 | tests |",
        ])
        (self.pack / "06-acceptance.md").write_text(
            "# Acceptance\n\n## AC-BE-001: One\n\nVerification: test.\n\n"
            "## AC-BE-001: Duplicate\n\nVerification: test.\n\n"
            "## AC-BE-002: Two\n\nVerification: test.\n",
            encoding="utf-8",
        )

        result = MODULE.validate(self.pack)

        self.assertFalse(result["valid"])
        self.assertTrue(any("dependency cycle: WP-BE-001 -> WP-BE-002 -> WP-BE-001" in item for item in result["errors"]))
        self.assertTrue(any("duplicate acceptance id: AC-BE-001" in item for item in result["errors"]))


    def test_missing_requirements_section_fails(self):
        self.write_wbs([
            "| WP-BE-001 | 任务一 | Task one | backend | owner | todo | none | AC-BE-001 | code |",
        ], sync_requirements=False)

        result = MODULE.validate(self.pack)

        self.assertFalse(result["valid"])
        self.assertTrue(any(
            "missing requirements section for WP-BE-001" in item for item in result["errors"]
        ), result["errors"])

    def test_requirements_baseline_grandfathers_existing_packages(self):
        self.write_wbs([
            "| WP-BE-001 | 任务一 | Task one | backend | owner | todo | none | AC-BE-001 | code |",
        ], sync_requirements=False)
        (self.pack / "requirements-baseline.txt").write_text(
            "# legacy\nWP-BE-001\n", encoding="utf-8")

        result = MODULE.validate(self.pack)

        self.assertTrue(result["valid"], result["errors"])
        self.assertTrue(any("grandfathered" in item for item in result["warnings"]), result["warnings"])

    def test_resolved_baseline_entry_is_reported_for_removal(self):
        self.write_wbs([
            "| WP-BE-001 | 任务一 | Task one | backend | owner | todo | none | AC-BE-001 | code |",
        ])
        (self.pack / "requirements-baseline.txt").write_text("WP-BE-001\n", encoding="utf-8")

        result = MODULE.validate(self.pack)

        self.assertTrue(result["valid"], result["errors"])
        self.assertTrue(any(
            "WP-BE-001 now has requirements" in item for item in result["warnings"]
        ), result["warnings"])

    def test_blank_line_inside_table_is_reported_not_silently_skipped(self):
        self.write_wbs([
            "| WP-BE-001 | 任务一 | Task one | backend | owner | todo | none | AC-BE-001 | code |",
        ])
        text = (self.pack / "02-wbs.md").read_text(encoding="utf-8")
        text += "\n| WP-BE-002 | 任务二 | Task two | backend | owner | todo | none | AC-BE-002 | tests |\n"
        (self.pack / "02-wbs.md").write_text(text, encoding="utf-8")

        result = MODULE.validate(self.pack)

        self.assertFalse(result["valid"])
        self.assertTrue(any(
            "outside the parsed table" in item for item in result["errors"]
        ), result["errors"])


if __name__ == "__main__":
    unittest.main()
