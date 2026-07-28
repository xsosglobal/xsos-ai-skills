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

    def test_distinct_work_package_ids_pass(self):
        result = MODULE.validate(self.pack)
        self.assertTrue(result["valid"], result["errors"])

    def test_duplicate_work_package_id_fails_with_all_line_numbers(self):
        (self.pack / "02-wbs.md").write_text(self.wbs_rows([
            "| WP-BE-006 | 任务一 | Task one | backend | owner | done | none | AC-BE-001 | code |",
            "| WP-BE-036 | 任务二 | Task two | backend | owner | review | none | AC-BE-002 | tests |",
            "| WP-BE-006 | 任务三 | Task three | backend | owner | todo | none | AC-BE-001 | docs |",
            "| WP-BE-036 | 任务四 | Task four | backend | owner | todo | none | AC-BE-002 | api |",
        ]), encoding="utf-8")

        result = MODULE.validate(self.pack)

        self.assertFalse(result["valid"])
        self.assertIn("02-wbs.md duplicate wp_id: WP-BE-006 (lines 5, 7)", result["errors"])
        self.assertIn("02-wbs.md duplicate wp_id: WP-BE-036 (lines 6, 8)", result["errors"])

    def test_missing_acceptance_and_local_dependency_fail(self):
        (self.pack / "02-wbs.md").write_text(self.wbs_rows([
            "| WP-BE-001 | 任务一 | Task one | backend | owner | todo | WP-BE-099 | AC-BE-099 | code |",
        ]), encoding="utf-8")

        result = MODULE.validate(self.pack)

        self.assertFalse(result["valid"])
        self.assertTrue(any("missing local dependency: WP-BE-001 -> WP-BE-099" in item for item in result["errors"]))
        self.assertTrue(any("acceptance reference not found: WP-BE-001 -> AC-BE-099" in item for item in result["errors"]))

    def test_cross_project_dependency_is_not_treated_as_local(self):
        (self.pack / "02-wbs.md").write_text(self.wbs_rows([
            "| WP-BE-001 | 任务一 | Task one | backend | owner | todo | xsos-masterdata WP-INTEG-002 | AC-BE-001 | code |",
        ]), encoding="utf-8")

        result = MODULE.validate(self.pack)

        self.assertTrue(result["valid"], result["errors"])

    def test_duplicate_acceptance_and_dependency_cycle_fail(self):
        (self.pack / "02-wbs.md").write_text(self.wbs_rows([
            "| WP-BE-001 | 任务一 | Task one | backend | owner | todo | WP-BE-002 | AC-BE-001 | code |",
            "| WP-BE-002 | 任务二 | Task two | backend | owner | todo | WP-BE-001 | AC-BE-002 | tests |",
        ]), encoding="utf-8")
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


if __name__ == "__main__":
    unittest.main()
