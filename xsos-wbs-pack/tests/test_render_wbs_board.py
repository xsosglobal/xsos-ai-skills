import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts/render_wbs_board.py"


class RenderWBSBoardTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.pack = Path(self.temp.name) / "docs/wbs"
        self.pack.mkdir(parents=True)
        self.out = Path(self.temp.name) / "board.html"

    def tearDown(self):
        self.temp.cleanup()

    def write(self, name, text):
        (self.pack / name).write_text(text, encoding="utf-8")

    def replace(self, name, old, new):
        path = self.pack / name
        text = path.read_text(encoding="utf-8")
        self.assertIn(old, text)
        path.write_text(text.replace(old, new, 1), encoding="utf-8")

    def assert_no_production_delivery(self):
        data, _ = self.render()
        self.assertEqual(2, data["delivery"]["denominator"])
        self.assertEqual(0, data["delivery"]["numerator"])
        self.assertEqual(0.0, data["delivery"]["rate"])
        self.assertEqual([], data["delivery"]["delivered_wp_ids"])

    def assert_single_production_delivery(self):
        data, _ = self.render()
        self.assertEqual(2, data["delivery"]["denominator"])
        self.assertEqual(1, data["delivery"]["numerator"])
        self.assertEqual(50.0, data["delivery"]["rate"])
        self.assertEqual(["WP-PUR-BE-001"], data["delivery"]["delivered_wp_ids"])

    def render(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(self.pack), str(self.out)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        rendered = self.out.read_text(encoding="utf-8")
        match = re.search(
            r'<script id="D" type="application/json">(.*?)</script>',
            rendered,
            flags=re.S,
        )
        self.assertIsNotNone(match)
        return json.loads(match.group(1)), rendered

    def make_v2_pack(self):
        self.write(
            "00-brief.md",
            """# Brief

## Project Control

| field | value |
|---|---|
| wbs_schema | 2 |
| current_baseline | BL-001 |
""",
        )
        self.write("01-requirements.md", "# Requirements\n")
        self.write(
            "02-wbs.md",
            """# WBS

| wp_id | title_cn | title_en | type | owner | status | depends_on | requirement_refs | scope | non_goals | baseline_ref | run_ref | release_ref | planned_start | planned_finish | forecast_finish | actual_start | actual_finish | change_ref | acceptance_ref | outputs | delivery_target | delivery_counted |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| WP-PUR-BE-001 | 生产证据优先 | Evidence first | backend | owner-a | done | none | REQ-PUR-001@v1 | API | none | BL-001 | RUN-001 | REL-001 | 2026-09-01 | 2026-09-02 | 2026-09-02 | 2026-09-01 | 2026-09-02 | none | AC-PUR-BE-001 | API | production | yes |
| WP-BE-002 | 状态不冒充发布 | Status is not release | backend | owner-b | done | none | REQ-002@v1 | API | none | BL-001 | RUN-002 | REL-002 | 2026-09-01 | 2026-09-03 | 2026-09-03 | 2026-09-01 | 2026-09-03 | none | AC-BE-002 | API | production | yes |

## Artifact Readiness Register

| wp_id | artifact | applicability | readiness | owner | refs | reason | change_ref |
|---|---|---|---|---|---|---|---|
| WP-PUR-BE-001 | requirement | required | verified | product-owner | REQ-PUR-001@v1 | Baselined | none |
| WP-PUR-BE-001 | page | not_applicable | not_applicable | owner-a | none | Backend only | none |
| WP-PUR-BE-001 | api | required | ready | owner-a | API-PUR-BE-001 | Ready | none |
| WP-PUR-BE-001 | data | required | draft | owner-a | DATA-PUR-BE-001 | Draft | none |
| WP-PUR-BE-001 | acceptance | required | ready | acceptance-owner | AC-PUR-BE-001 | Ready | none |
| WP-PUR-BE-001 | risk | required | verified | owner-a | RISK-PUR-001 | Verified | none |
| WP-PUR-BE-001 | handoff | required | verified | owner-a | REL-001 | Verified | none |
| WP-BE-002 | requirement | required | ready | product-owner | REQ-002@v1 | Baselined | none |
| WP-BE-002 | page | not_applicable | not_applicable | owner-b | none | Backend only | none |
| WP-BE-002 | api | required | ready | owner-b | API-BE-002 | Ready | none |
| WP-BE-002 | data | not_applicable | not_applicable | owner-b | none | No data | none |
| WP-BE-002 | acceptance | required | ready | acceptance-owner | AC-BE-002 | Ready | none |
| WP-BE-002 | risk | required | ready | owner-b | none | Assessed | none |
| WP-BE-002 | handoff | required | draft | owner-b | REL-002 | Deployed only | none |
""",
        )
        self.write(
            "09-baselines.md",
            """# Baselines

| baseline_id | version | status | current | approved_by | approved_at | planned_start | planned_finish | forecast_finish | requirement_refs | wp_refs | change_ref | supersedes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BL-001 | v1 | approved | yes | product-owner | 2026-09-01 | 2026-09-01 | 2026-09-30 | 2026-09-30 | REQ-PUR-001@v1, REQ-002@v1 | WP-PUR-BE-001, WP-BE-002 | none | none |
""",
        )
        self.write(
            "10-handoff.md",
            """# Handoff

| run_id | wp_id | baseline_ref | status | actual_start | actual_finish | outcome | change_ref | next_action |
|---|---|---|---|---|---|---|---|---|
| RUN-001 | WP-PUR-BE-001 | BL-001 | closed | 2026-09-01 | 2026-09-02 | completed | none | none |
| RUN-002 | WP-BE-002 | BL-001 | closed | 2026-09-01 | 2026-09-03 | completed | none | none |

| release_id | wp_id | run_ref | baseline_ref | status | verified_at | environment | evidence | verified_by |
|---|---|---|---|---|---|---|---|---|
| REL-001 | WP-PUR-BE-001 | RUN-001 | BL-001 | verified | 2026-09-02 | production | deploy://rel-001 | acceptance-owner |
| REL-002 | WP-BE-002 | RUN-002 | BL-001 | deployed | none | production | deploy://rel-002 | none |
""",
        )
        self.write(
            "OWNERS.md",
            """# Owners

| role | name | responsibility |
|---|---|---|
| acceptance_owner | acceptance-owner | Production acceptance |
""",
        )

    def test_v2_artifact_table_does_not_overwrite_header_driven_work_packages(self):
        self.make_v2_pack()

        data, rendered = self.render()

        self.assertEqual(2, data["schema_version"])
        self.assertEqual("v2_register", data["artifact_mode"])
        self.assertEqual(2, len(data["wbs"]))
        first = next(wp for wp in data["wbs"] if wp["id"] == "WP-PUR-BE-001")
        self.assertEqual("生产证据优先", first["title"])
        self.assertEqual("done", first["status"])
        self.assertEqual(["REQ-PUR-001@v1"], first["requirement_refs"])
        self.assertEqual("draft", first["artifacts"]["data"]["readiness"])
        self.assertNotIn("无需求依据", rendered)

    def test_production_rate_uses_current_baseline_and_verified_production_rel(self):
        self.make_v2_pack()

        data, _ = self.render()

        # Verified production REL counts; status=done with deployed-only REL does not.
        self.assertEqual("BL-001", data["delivery"]["current_baseline"])
        self.assertEqual(2, data["delivery"]["denominator"])
        self.assertEqual(1, data["delivery"]["numerator"])
        self.assertEqual(50.0, data["delivery"]["rate"])
        self.assertEqual(["WP-PUR-BE-001"], data["delivery"]["delivered_wp_ids"])

    def test_production_rate_rejects_wp_that_is_not_done(self):
        self.make_v2_pack()
        self.replace(
            "02-wbs.md",
            "| owner-a | done | none | REQ-PUR-001@v1 |",
            "| owner-a | review | none | REQ-PUR-001@v1 |",
        )

        self.assert_no_production_delivery()

    def test_production_rate_rejects_wbs_run_release_and_baseline_mismatches(self):
        mutations = {
            "wbs_run_ref": (
                "02-wbs.md",
                "| BL-001 | RUN-001 | REL-001 |",
                "| BL-001 | RUN-009 | REL-001 |",
            ),
            "wbs_release_ref": (
                "02-wbs.md",
                "| BL-001 | RUN-001 | REL-001 |",
                "| BL-001 | RUN-001 | REL-009 |",
            ),
            "wbs_baseline_ref": (
                "02-wbs.md",
                "| API | none | BL-001 | RUN-001 |",
                "| API | none | BL-009 | RUN-001 |",
            ),
            "rel_run_ref": (
                "10-handoff.md",
                "| REL-001 | WP-PUR-BE-001 | RUN-001 | BL-001 |",
                "| REL-001 | WP-PUR-BE-001 | RUN-009 | BL-001 |",
            ),
            "rel_baseline_ref": (
                "10-handoff.md",
                "| REL-001 | WP-PUR-BE-001 | RUN-001 | BL-001 |",
                "| REL-001 | WP-PUR-BE-001 | RUN-001 | BL-009 |",
            ),
        }
        for label, (name, old, new) in mutations.items():
            with self.subTest(label=label):
                self.tearDown()
                self.setUp()
                self.make_v2_pack()
                self.replace(name, old, new)
                self.assert_no_production_delivery()

    def test_production_rate_rejects_run_that_is_not_closed_completed_and_finished(self):
        mutations = {
            "not_closed": (
                "| RUN-001 | WP-PUR-BE-001 | BL-001 | closed |",
                "| RUN-001 | WP-PUR-BE-001 | BL-001 | active |",
            ),
            "not_completed": (
                "| 2026-09-02 | completed | none | none |",
                "| 2026-09-02 | blocked | none | Fix blocker |",
            ),
            "missing_finish": (
                "| 2026-09-02 | completed | none | none |",
                "| none | completed | none | none |",
            ),
            "start_after_finish": (
                "| closed | 2026-09-01 | 2026-09-02 | completed |",
                "| closed | 2026-09-03 | 2026-09-02 | completed |",
            ),
            "wbs_finish_mismatch": (
                "| 2026-09-01 | 2026-09-02 | none | AC-PUR-BE-001 |",
                "| 2026-09-01 | 2026-09-03 | none | AC-PUR-BE-001 |",
            ),
        }
        for label, (old, new) in mutations.items():
            with self.subTest(label=label):
                self.tearDown()
                self.setUp()
                self.make_v2_pack()
                target = "02-wbs.md" if label == "wbs_finish_mismatch" else "10-handoff.md"
                self.replace(target, old, new)
                self.assert_no_production_delivery()

    def test_production_rate_rejects_verification_before_run_finish(self):
        self.make_v2_pack()
        self.replace(
            "10-handoff.md",
            "| verified | 2026-09-02 | production |",
            "| verified | 2026-08-31 | production |",
        )

        self.assert_no_production_delivery()

    def test_production_rate_rejects_non_locatable_release_evidence(self):
        invalid_values = [
            "ok",
            "12345678",
            "Production release verification passed successfully",
            "Evidence was checked and/or approved",
        ]
        for evidence in invalid_values:
            with self.subTest(evidence=evidence):
                self.tearDown()
                self.setUp()
                self.make_v2_pack()
                self.replace("10-handoff.md", "| deploy://rel-001 |", f"| {evidence} |")
                self.assert_no_production_delivery()

    def test_production_rate_accepts_each_stable_evidence_locator_type(self):
        valid_values = {
            "uri": "https://ci.example/jobs/123",
            "absolute_path": "/var/log/xsos/release-001.json",
            "dot_relative_path": "./evidence/release-001.json",
            "repo_relative_path": "docs/evidence/release-001.md",
            "relative_filename": "release-evidence.json",
            "windows_absolute_path": r"C:\evidence\release-001.json",
            "commit": "a1b2c3d4",
            "seven_char_commit_with_context": "commit a1b2c3d",
            "command": "cmd: make production-smoke-test",
        }
        valid_values.update({
            f"controlled_id_{prefix.lower()}": f"{prefix}-release001"
            for prefix in (
                "EVIDENCE", "EVD", "BUILD", "DEPLOY", "RELEASE",
                "CI", "JOB", "ARTIFACT",
            )
        })
        for label, evidence in valid_values.items():
            with self.subTest(label=label, evidence=evidence):
                self.tearDown()
                self.setUp()
                self.make_v2_pack()
                self.replace("10-handoff.md", "| deploy://rel-001 |", f"| {evidence} |")
                self.assert_single_production_delivery()

    def test_production_rate_rejects_unresolved_acceptance_verifier(self):
        self.make_v2_pack()
        self.replace("10-handoff.md", "| acceptance-owner |", "| random-reviewer |")

        self.assert_no_production_delivery()

    def test_v1_keeps_heading_based_coverage_fallback(self):
        self.write("00-brief.md", "# Legacy brief\n")
        self.write(
            "02-wbs.md",
            """# WBS

| wp_id | title_cn | title_en | type | owner | status | depends_on | acceptance_ref | outputs |
|---|---|---|---|---|---|---|---|---|
| WP-PUR-BE-001 | 旧工作包 | Legacy WP | backend | owner | todo | none | AC-PUR-BE-001 | code |
""",
        )
        self.write("01-requirements.md", "# Requirements\n\n## WP-PUR-BE-001 Requirement\n")
        self.write("06-acceptance.md", "# Acceptance\n\n## AC-PUR-BE-001 Acceptance\n")

        data, rendered = self.render()

        self.assertEqual(1, data["schema_version"])
        self.assertEqual("v1_fallback", data["artifact_mode"])
        self.assertTrue(data["wbs"][0]["cov"]["requirements"])
        self.assertTrue(data["wbs"][0]["cov"]["acceptance"])
        self.assertEqual("present", data["wbs"][0]["artifacts"]["requirement"]["readiness"])
        self.assertIn("v1 兼容模式", rendered)
        self.assertIsNone(data["delivery"]["rate"])


if __name__ == "__main__":
    unittest.main()
