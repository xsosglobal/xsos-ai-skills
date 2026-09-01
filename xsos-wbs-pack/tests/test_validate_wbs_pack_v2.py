import tempfile
import shutil
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts/validate_wbs_pack.py"
SPEC = spec_from_file_location("validate_wbs_pack_v2", SCRIPT)
MODULE = module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class ValidateWBSPackV2Test(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.pack = Path(self.temp.name) / "docs/wbs"
        self.pack.mkdir(parents=True)
        content = {
            "00-brief.md": """# V2 Brief

## Goal

Control delivery from an approved baseline.

## Non-goals

None.

## Project Control

| field | value |
|---|---|
| wbs_schema | 2 |
| project_id | TEST-PROJECT |
| project_status | active |
| product_owner | product-owner |
| current_baseline | BL-001 |
| planned_start | 2026-08-20 |
| planned_finish | 2026-09-30 |
| forecast_finish | 2026-09-30 |
| actual_start | 2026-08-20 |
| actual_finish | none |
""",
            "01-requirements.md": """# Requirements

## Source Register

| source_id | source_type | source_ref | captured_at | note |
|---|---|---|---|---|
| SRC-001 | user_request | conversation | 2026-08-19 | Approved project scope |

## Requirement Register

| req_id | version | requirement_cn | requirement_en | priority | owner | status | baseline_ref | change_ref | acceptance_refs | source_refs | approved_at | supersedes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| REQ-001 | v1 | 受控生产交付 | Controlled production delivery | P0 | product-owner | baselined | BL-001 | none | AC-BE-001, AC-BE-002 | SRC-001 | 2026-08-19 | none |
""",
            "02-wbs.md": """# WBS

| wp_id | title_cn | title_en | type | owner | status | depends_on | requirement_refs | scope | non_goals | acceptance_ref | outputs | delivery_target | delivery_counted | baseline_ref | planned_start | planned_finish | forecast_finish | actual_start | actual_finish | change_ref | run_ref | release_ref |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| WP-BE-001 | 执行中工作 | Active work | backend | developer | in_progress | none | REQ-001@v1 | API implementation | UI redesign | AC-BE-001 | code | production | yes | BL-001 | 2026-09-01 | 2026-09-15 | 2026-09-15 | 2026-09-01 | none | none | RUN-001 | none |
| WP-BE-002 | 已生产交付 | Production delivery | backend | developer | done | none | REQ-001@v1 | Production API | New reports | AC-BE-002 | code, tests | production | yes | BL-001 | 2026-08-20 | 2026-08-30 | 2026-08-30 | 2026-08-20 | 2026-08-30 | none | RUN-002 | REL-001 |

## Artifact Readiness Register

| wp_id | artifact | applicability | readiness | owner | refs | reason | change_ref |
|---|---|---|---|---|---|---|---|
| WP-BE-001 | requirement | required | ready | product_owner | REQ-001@v1 | Baselined requirement | none |
| WP-BE-001 | page | not_applicable | not_applicable | developer | none | No UI work | none |
| WP-BE-001 | api | required | draft | developer | API-BE-001 | API implementation active | none |
| WP-BE-001 | data | not_applicable | not_applicable | developer | none | No data change | none |
| WP-BE-001 | acceptance | required | ready | acceptance_owner | AC-BE-001 | Acceptance approved | none |
| WP-BE-001 | risk | required | ready | developer | RISK-001 | Risk assessed | none |
| WP-BE-001 | handoff | required | draft | developer | RUN-001 | Active run | none |
| WP-BE-002 | requirement | required | ready | product_owner | REQ-001@v1 | Baselined requirement | none |
| WP-BE-002 | page | not_applicable | not_applicable | developer | none | No UI work | none |
| WP-BE-002 | api | required | verified | developer | API-BE-002 | Production API verified | none |
| WP-BE-002 | data | not_applicable | not_applicable | developer | none | No data change | none |
| WP-BE-002 | acceptance | required | verified | acceptance_owner | AC-BE-002 | Acceptance verified | none |
| WP-BE-002 | risk | required | ready | developer | RISK-001 | Risk assessed | none |
| WP-BE-002 | handoff | required | verified | developer | RUN-002, REL-001 | Production handoff verified | none |
""",
            "03-page-spec.md": """# Page Spec

| page_id | status | route | owner | requirement_refs | acceptance_refs | purpose_cn | purpose_en | states | change_ref |
|---|---|---|---|---|---|---|---|---|---|
""",
            "04-api-contract.md": """# API Contract

| api_id | status | method | path | provider | consumer | auth | requirement_refs | acceptance_refs | request | response | errors | change_ref |
|---|---|---|---|---|---|---|---|---|---|---|---|
| API-BE-001 | draft | GET | /active | backend | web | bearer | REQ-001@v1 | AC-BE-001 | none | active result | standard | none |
| API-BE-002 | verified | GET | /done | backend | web | bearer | REQ-001@v1 | AC-BE-002 | none | production result | standard | none |

| mock_id | status | api_id | scenario | fixture |
|---|---|---|---|---|
""",
            "05-data-contract.md": """# Data Contract

| model_id | status | source_of_truth | owner | requirement_refs | acceptance_refs | fields | change_ref |
|---|---|---|---|---|---|---|---|

| machine_id | status | entity | states | transitions | change_ref |
|---|---|---|---|---|---|
""",
            "06-acceptance.md": """# Acceptance

## AC-BE-001: Active work

Requirement refs:
- `REQ-001@v1`
Baseline:
- `BL-001`
Acceptance owner:
- `acceptance_owner`
Delivery target:
- `production`
中文：
- 执行中工作可验证。
English:
- Active work is verifiable.
Verification:
- Run tests.
Required evidence:
- Test output.
Decision:
- `pending`

## AC-BE-002: Production delivery

Requirement refs:
- `REQ-001@v1`
Baseline:
- `BL-001`
Acceptance owner:
- `acceptance_owner`
Delivery target:
- `production`
中文：
- 生产交付有证据。
English:
- Production delivery has evidence.
Verification:
- Verify production release evidence.
Required evidence:
- Verified production REL.
Decision:
- `accepted`
""",
            "07-risks.md": """# Risks

| risk_id | risk_cn | risk_en | probability | impact | owner | trigger | response | due_date | related_wp | residual_risk | status | accepted_by |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| RISK-001 | 交付证据丢失 | Delivery evidence is lost | medium | high | developer | Evidence is not retained | Preserve verification and release evidence | 2026-09-30 | WP-BE-001, WP-BE-002 | low | open | none |
""",
            "08-implementation-rules.md": "# Rules\n\nStay in baseline.\n",
            "09-baselines.md": """# Baselines

| baseline_id | version | status | current | approved_by | approved_at | planned_start | planned_finish | forecast_finish | requirement_refs | wp_refs | change_ref | supersedes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BL-001 | v1 | approved | yes | baseline-owner | 2026-08-19 | 2026-08-20 | 2026-09-30 | 2026-09-30 | REQ-001@v1 | WP-BE-001, WP-BE-002 | none | none |
""",
            "10-handoff.md": """# AI Runs and Release Evidence

| run_id | wp_id | baseline_ref | status | actual_start | actual_finish | outcome | change_ref | next_action |
|---|---|---|---|---|---|---|---|---|
| RUN-001 | WP-BE-001 | BL-001 | active | 2026-09-01T00:28:34-07:00 | none | none | none | Continue acceptance work |
| RUN-002 | WP-BE-002 | BL-001 | closed | 2026-08-20T09:00:00-07:00 | 2026-08-30T18:00:00-07:00 | completed | none | none |

| release_id | wp_id | run_ref | baseline_ref | status | verified_at | environment | evidence | verified_by |
|---|---|---|---|---|---|---|---|---|
| REL-001 | WP-BE-002 | RUN-002 | BL-001 | verified | 2026-08-31 | production | deploy://release-001 | acceptance-owner |
""",
            "11-change-requests.md": """# Change Requests

| cr_id | status | requested_at | decided_at | affected_refs | baseline_from | baseline_to | decision | approver |
|---|---|---|---|---|---|---|---|---|
""",
            "CHANGELOG.md": "# Changelog\n\n- Created v2 baseline.\n",
            "OWNERS.md": """# Owners

| role | name | responsibility |
|---|---|---|
| product_owner | product-owner | requirements |
| baseline_approver | baseline-owner | baseline approval |
| change_approver | change-owner | change approval |
| acceptance_owner | acceptance-owner | acceptance |
| developer | delivery-owner | delivery |
""",
        }
        for name, text in content.items():
            (self.pack / name).write_text(text, encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def validate(self):
        return MODULE.validate(self.pack)

    def test_valid_v2_pack_passes_and_reports_schema(self):
        result = self.validate()

        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(2, result["packs"][0]["schema_version"])

    def test_v1_compatibility_is_selected_without_project_control_marker(self):
        brief = (self.pack / "00-brief.md").read_text(encoding="utf-8")
        brief = brief.split("## Project Control", 1)[0]
        (self.pack / "00-brief.md").write_text(brief, encoding="utf-8")
        (self.pack / "01-requirements.md").write_text(
            "# Requirements\n\n## WP-BE-001 legacy\n\n- Requirement.\n\n"
            "## WP-BE-002 legacy\n\n- Requirement.\n",
            encoding="utf-8",
        )

        result = self.validate()

        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(1, result["packs"][0]["schema_version"])

    def test_v2_requires_control_files_and_wbs_columns(self):
        (self.pack / "09-baselines.md").unlink()
        wbs = (self.pack / "02-wbs.md").read_text(encoding="utf-8")
        (self.pack / "02-wbs.md").write_text(
            wbs.replace("| scope |", "| scope_missing |"), encoding="utf-8"
        )

        result = self.validate()

        self.assertFalse(result["valid"])
        self.assertIn("missing required file: 09-baselines.md", result["errors"])
        self.assertIn("02-wbs.md missing required column: scope", result["errors"])

    def test_active_wp_and_requirement_must_be_in_current_baseline(self):
        baseline = (self.pack / "09-baselines.md").read_text(encoding="utf-8")
        baseline = baseline.replace(
            "REQ-001@v1 | WP-BE-001, WP-BE-002",
            "REQ-999@v1 | WP-BE-002",
        )
        (self.pack / "09-baselines.md").write_text(baseline, encoding="utf-8")

        result = self.validate()

        self.assertFalse(result["valid"])
        self.assertTrue(any("active work package is outside current baseline: WP-BE-001" in e for e in result["errors"]))
        self.assertTrue(any("requirement reference not found: BL-001 -> REQ-999@v1" in e for e in result["errors"]))

    def test_requirement_register_tracks_source_and_current_status(self):
        requirements = (self.pack / "01-requirements.md").read_text(encoding="utf-8")
        requirements = requirements.replace(
            "| baselined | BL-001 | none | AC-BE-001, AC-BE-002 | SRC-001 |",
            "| draft | BL-001 | none | AC-BE-001, AC-BE-002 | SRC-999 |",
        )
        (self.pack / "01-requirements.md").write_text(requirements, encoding="utf-8")

        result = self.validate()

        self.assertFalse(result["valid"])
        self.assertTrue(any("source reference not found: REQ-001@v1 -> SRC-999" in e for e in result["errors"]))
        self.assertTrue(any("current baseline cannot use requirement REQ-001@v1 with status=draft" in e for e in result["errors"]))

    def test_early_v2_requirement_heading_remains_compatible(self):
        (self.pack / "01-requirements.md").write_text(
            "# Requirements\n\n## REQ-001@v1: Legacy v2 requirement\n\n- Requirement.\n",
            encoding="utf-8",
        )

        result = self.validate()

        self.assertTrue(result["valid"], result["errors"])

    def test_in_progress_requires_resolved_run_with_actual_start(self):
        wbs = (self.pack / "02-wbs.md").read_text(encoding="utf-8")
        (self.pack / "02-wbs.md").write_text(
            wbs.replace("| RUN-001 | none |", "| none | none |", 1), encoding="utf-8"
        )
        handoff = (self.pack / "10-handoff.md").read_text(encoding="utf-8")
        (self.pack / "10-handoff.md").write_text(
            handoff.replace("| active | 2026-09-01T00:28:34-07:00 |", "| active | none |", 1),
            encoding="utf-8",
        )

        result = self.validate()

        self.assertFalse(result["valid"])
        self.assertTrue(any("WP-BE-001 run_ref" in e and "is required" in e for e in result["errors"]))
        self.assertTrue(any("RUN-001 actual_start is required" in e for e in result["errors"]))

    def test_production_done_requires_completed_run_and_verified_release(self):
        handoff = (self.pack / "10-handoff.md").read_text(encoding="utf-8")
        handoff = handoff.replace(
            "| RUN-002 | WP-BE-002 | BL-001 | closed | 2026-08-20T09:00:00-07:00 | 2026-08-30T18:00:00-07:00 | completed |",
            "| RUN-002 | WP-BE-002 | BL-001 | closed | 2026-08-20T09:00:00-07:00 | none | blocked |",
        ).replace(
            "| REL-001 | WP-BE-002 | RUN-002 | BL-001 | verified | 2026-08-31 |",
            "| REL-001 | WP-BE-002 | RUN-002 | BL-001 | deployed | none |",
        )
        (self.pack / "10-handoff.md").write_text(handoff, encoding="utf-8")

        result = self.validate()

        self.assertFalse(result["valid"])
        self.assertTrue(any("production done WP-BE-002 RUN has no actual_finish" in e for e in result["errors"]))
        self.assertTrue(any("production done WP-BE-002 requires a verified REL" in e for e in result["errors"]))

    def test_baseline_change_requires_approved_cr_and_iso_dates(self):
        baseline = (self.pack / "09-baselines.md").read_text(encoding="utf-8")
        (self.pack / "09-baselines.md").write_text(
            baseline.replace("2026-08-20 | 2026-09-30", "2026-09-31 | 2026-09-30")
            .replace(
                "| WP-BE-001, WP-BE-002 | none | none |",
                "| WP-BE-001, WP-BE-002 | CR-001 | none |",
            ),
            encoding="utf-8",
        )
        (self.pack / "11-change-requests.md").write_text(
            """# Change Requests

| cr_id | status | requested_at | decided_at | affected_refs | baseline_from | baseline_to | decision | approver |
|---|---|---|---|---|---|---|---|---|
| CR-001 | proposed | 2026-08-31 | none | WP-BE-001 | none | BL-001 | none | none |
""",
            encoding="utf-8",
        )

        result = self.validate()

        self.assertFalse(result["valid"])
        self.assertTrue(any("planned_start has invalid ISO date: 2026-09-31" in e for e in result["errors"]))
        self.assertTrue(any("requires approved change_ref" in e and "CR-001 is proposed" in e for e in result["errors"]))

    def test_change_request_can_reference_acceptance_and_risk(self):
        (self.pack / "11-change-requests.md").write_text(
            """# Change Requests

| cr_id | status | requested_at | decided_at | affected_refs | baseline_from | baseline_to | decision | approver |
|---|---|---|---|---|---|---|---|---|
| CR-001 | proposed | 2026-08-31 | none | AC-BE-001, RISK-001 | BL-001 | none | none | none |
""",
            encoding="utf-8",
        )

        result = self.validate()

        self.assertTrue(result["valid"], result["errors"])

    def test_delivery_counted_uses_yes_no(self):
        wbs = (self.pack / "02-wbs.md").read_text(encoding="utf-8")
        (self.pack / "02-wbs.md").write_text(
            wbs.replace("| production | yes |", "| production | true |", 1), encoding="utf-8"
        )

        result = self.validate()

        self.assertFalse(result["valid"])
        self.assertTrue(any("invalid delivery_counted: true" in e for e in result["errors"]))

    def test_production_rate_excludes_review_target(self):
        wbs = (self.pack / "02-wbs.md").read_text(encoding="utf-8")
        (self.pack / "02-wbs.md").write_text(
            wbs.replace("| production | yes |", "| review | yes |", 1), encoding="utf-8"
        )

        result = self.validate()

        self.assertFalse(result["valid"])
        self.assertTrue(any(
            "delivery_counted=yes requires delivery_target=production" in error
            for error in result["errors"]
        ))

    def test_production_done_requires_production_environment(self):
        handoff = (self.pack / "10-handoff.md").read_text(encoding="utf-8")
        (self.pack / "10-handoff.md").write_text(
            handoff.replace("| production | deploy://release-001 |", "| test | deploy://release-001 |"),
            encoding="utf-8",
        )

        result = self.validate()

        self.assertFalse(result["valid"])
        self.assertTrue(any(
            "requires REL environment=production" in error for error in result["errors"]
        ))

    def test_verified_production_release_requires_done_status(self):
        wbs_path = self.pack / "02-wbs.md"
        wbs_path.write_text(
            wbs_path.read_text(encoding="utf-8").replace(
                "| WP-BE-002 | 已生产交付 | Production delivery | backend | developer | done |",
                "| WP-BE-002 | 已生产交付 | Production delivery | backend | developer | review |",
            ),
            encoding="utf-8",
        )

        result = self.validate()

        self.assertTrue(any(
            "verified production REL-001 requires WP-BE-002 status=done" in error
            for error in result["errors"]
        ))

    def test_executable_wp_requires_resolved_owner_and_managed_ac(self):
        wbs = (self.pack / "02-wbs.md").read_text(encoding="utf-8")
        (self.pack / "02-wbs.md").write_text(
            wbs.replace("| backend | developer |", "| backend | unknown-owner |", 1),
            encoding="utf-8",
        )
        acceptance = (self.pack / "06-acceptance.md").read_text(encoding="utf-8")
        (self.pack / "06-acceptance.md").write_text(
            acceptance.replace("Required evidence:", "Evidence:", 1),
            encoding="utf-8",
        )

        result = self.validate()

        self.assertFalse(result["valid"])
        self.assertTrue(any("owner must resolve" in error for error in result["errors"]))
        self.assertTrue(any(
            "AC-BE-001 missing managed field: required evidence" in error
            for error in result["errors"]
        ))

    def test_later_baseline_cannot_bypass_cr_or_immediate_supersedes(self):
        baseline_path = self.pack / "09-baselines.md"
        baseline = baseline_path.read_text(encoding="utf-8")
        baseline = baseline.replace("| approved | yes |", "| superseded | no |", 1)
        baseline += (
            "| BL-002 | v2 | approved | yes | baseline-owner | 2026-09-01 | "
            "2026-08-20 | 2026-09-30 | 2026-09-30 | REQ-001@v1 | "
            "WP-BE-001, WP-BE-002 | none | none |\n"
        )
        baseline_path.write_text(baseline, encoding="utf-8")
        brief_path = self.pack / "00-brief.md"
        brief_path.write_text(
            brief_path.read_text(encoding="utf-8").replace(
                "| current_baseline | BL-001 |", "| current_baseline | BL-002 |"
            ), encoding="utf-8")

        result = self.validate()

        self.assertTrue(any("BL-002 v2 requires exactly one CR" in e for e in result["errors"]))
        self.assertTrue(any("must supersede immediate prior baseline BL-001" in e for e in result["errors"]))

    def test_baseline_and_change_approvers_must_resolve_to_roles(self):
        baseline_path = self.pack / "09-baselines.md"
        baseline_path.write_text(
            baseline_path.read_text(encoding="utf-8").replace(
                "| baseline-owner |", "| intruder |", 1
            ), encoding="utf-8")
        (self.pack / "11-change-requests.md").write_text(
            """# Change Requests

| cr_id | status | requested_at | decided_at | affected_refs | baseline_from | baseline_to | decision | approver |
|---|---|---|---|---|---|---|---|---|
| CR-001 | approved | 2026-08-31 | 2026-09-01 | WP-BE-001 | BL-001 | none | Approve test change | intruder |
""", encoding="utf-8")

        result = self.validate()

        self.assertTrue(any("approved_by must resolve to baseline_approver" in e for e in result["errors"]))
        self.assertTrue(any("approver must resolve to change_approver" in e for e in result["errors"]))

    def test_current_baseline_cannot_include_proposed_or_drop_counted_done_work(self):
        wbs_path = self.pack / "02-wbs.md"
        wbs_path.write_text(
            wbs_path.read_text(encoding="utf-8").replace(
                "| in_progress |", "| proposed |", 1
            ), encoding="utf-8")
        baseline_path = self.pack / "09-baselines.md"
        baseline_path.write_text(
            baseline_path.read_text(encoding="utf-8").replace(
                "WP-BE-001, WP-BE-002", "WP-BE-001"
            ), encoding="utf-8")

        result = self.validate()

        self.assertTrue(any("cannot include proposed work package: WP-BE-001" in e for e in result["errors"]))
        self.assertTrue(any(
            "production-counted work package is outside current baseline" in e
            and "WP-BE-002" in e for e in result["errors"]
        ))

    def test_production_done_and_run_cannot_bind_draft_baseline(self):
        baseline_path = self.pack / "09-baselines.md"
        baseline_path.write_text(
            baseline_path.read_text(encoding="utf-8").replace(
                "| approved | yes |", "| draft | yes |", 1
            ), encoding="utf-8")

        result = self.validate()

        self.assertTrue(any("baseline_ref must be approved or superseded" in e for e in result["errors"]))
        self.assertTrue(any(
            "production done WP-BE-002 must retain an approved or superseded baseline_ref" in e
            for e in result["errors"]
        ))

    def test_one_work_package_cannot_have_multiple_active_runs(self):
        handoff_path = self.pack / "10-handoff.md"
        handoff = handoff_path.read_text(encoding="utf-8")
        handoff = handoff.replace(
            "\n\n| release_id |",
            "\n| RUN-003 | WP-BE-001 | BL-001 | active | 2026-09-02T09:00:00-07:00 | none | none | none | Continue |\n\n| release_id |",
            1)
        handoff_path.write_text(handoff, encoding="utf-8")

        result = self.validate()

        self.assertTrue(any("WP-BE-001 has multiple active RUNs" in e for e in result["errors"]))

    def test_historical_completed_run_allows_later_active_run(self):
        handoff_path = self.pack / "10-handoff.md"
        handoff = handoff_path.read_text(encoding="utf-8")
        handoff = handoff.replace(
            "| RUN-001 | WP-BE-001 |",
            "| RUN-000 | WP-BE-001 | BL-001 | closed | 2026-08-25T09:00:00-07:00 | 2026-08-25T18:00:00-07:00 | completed | none | Follow-up run required |\n"
            "| RUN-001 | WP-BE-001 |",
            1,
        )
        handoff_path.write_text(handoff, encoding="utf-8")

        result = self.validate()

        self.assertTrue(result["valid"], result["errors"])

    def test_closed_project_rejects_active_run_and_unfinished_work(self):
        brief_path = self.pack / "00-brief.md"
        brief_path.write_text(
            brief_path.read_text(encoding="utf-8").replace(
                "| project_status | active |", "| project_status | closed |"
            ), encoding="utf-8")

        result = self.validate()

        self.assertTrue(any("closed project actual_finish" in e for e in result["errors"]))
        self.assertTrue(any("closed project must not have active RUNs" in e for e in result["errors"]))
        self.assertTrue(any("closed project requires done/cancelled" in e for e in result["errors"]))

    def test_release_cannot_precede_run_or_use_vague_evidence(self):
        handoff_path = self.pack / "10-handoff.md"
        handoff_path.write_text(
            handoff_path.read_text(encoding="utf-8").replace(
                "2026-08-31 | production | deploy://release-001",
                "2026-08-19 | production | 12345678"
            ), encoding="utf-8")

        result = self.validate()

        self.assertTrue(any("verified_at is before RUN-002 actual_finish" in e for e in result["errors"]))
        self.assertTrue(any("evidence is too vague" in e for e in result["errors"]))

    def test_release_evidence_requires_a_stable_locator(self):
        valid = [
            "deploy://release-001",
            "/var/evidence/release-001.txt",
            "C:\\evidence\\release-001.txt",
            "docs/evidence/release-001.txt",
            "release-001.txt",
            "commit 1a2b3c4d",
            "BUILD-20260901-001",
            "command: curl https://example.invalid/health",
        ]
        for evidence in valid:
            with self.subTest(evidence=evidence):
                self.assertTrue(MODULE.has_stable_evidence_locator(evidence))
        self.assertFalse(MODULE.has_stable_evidence_locator("12345678"))
        self.assertFalse(MODULE.has_stable_evidence_locator("all checks passed"))

    def test_verified_artifact_refs_must_resolve(self):
        wbs_path = self.pack / "02-wbs.md"
        wbs = wbs_path.read_text(encoding="utf-8")
        wbs = wbs.replace("| API-BE-002 | Production API verified |", "| BOGUS-API | Production API verified |")
        wbs = wbs.replace("| RUN-002, REL-001 | Production handoff verified |", "| BOGUS-HANDOFF | Production handoff verified |")
        wbs_path.write_text(wbs, encoding="utf-8")

        result = self.validate()

        self.assertTrue(any("WP-BE-002/api reference not found: BOGUS-API" in e for e in result["errors"]))
        self.assertTrue(any("WP-BE-002/handoff reference not found: BOGUS-HANDOFF" in e for e in result["errors"]))

    def test_cancelled_work_retains_seven_artifact_rows(self):
        wbs_path = self.pack / "02-wbs.md"
        lines = wbs_path.read_text(encoding="utf-8").replace(
            "| in_progress |", "| cancelled |", 1
        ).splitlines()
        artifact_names = {"requirement", "page", "api", "data", "acceptance", "risk", "handoff"}
        kept = []
        for line in lines:
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) > 1 and cells[0] == "WP-BE-001" and cells[1] in artifact_names:
                continue
            kept.append(line)
        wbs_path.write_text("\n".join(kept) + "\n", encoding="utf-8")

        result = self.validate()

        self.assertTrue(any("WP-BE-001 missing artifact readiness rows" in e for e in result["errors"]))

    def test_changed_historical_done_work_loses_migration_exemption(self):
        wbs_path = self.pack / "02-wbs.md"
        lines = wbs_path.read_text(encoding="utf-8").replace(
            "| code, tests | production | yes | BL-001 |",
            "| code, tests | none | no | BL-001 |",
            1,
        ).replace(
            "| 2026-08-20 | 2026-08-30 | none | RUN-002 | REL-001 |",
            "| 2026-08-20 | 2026-08-30 | CR-001 | RUN-002 | REL-001 |",
            1,
        ).splitlines()
        kept = []
        for line in lines:
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if (
                cells
                and cells[0] == "WP-BE-002"
                and len(cells) > 1
                and cells[1] in MODULE.ARTIFACT_TYPES
            ):
                continue
            kept.append(line)
        wbs_path.write_text(
            "\n".join(kept) + "\n",
            encoding="utf-8",
        )
        (self.pack / "11-change-requests.md").write_text(
            """# Change Requests

| cr_id | status | requested_at | decided_at | affected_refs | baseline_from | baseline_to | decision | approver |
|---|---|---|---|---|---|---|---|---|
| CR-001 | approved | 2026-09-01 | 2026-09-01 | WP-BE-002 | BL-001 | none | Change historical package | change-owner |
""",
            encoding="utf-8",
        )

        result = self.validate()

        self.assertTrue(any("WP-BE-002 missing artifact readiness rows" in e for e in result["errors"]))

    def test_v2_cr_cannot_resolve_legacy_risk_heading(self):
        risk_path = self.pack / "07-risks.md"
        risk_path.write_text(
            risk_path.read_text(encoding="utf-8") + "\n## RISK-999 Legacy heading only\n",
            encoding="utf-8")
        (self.pack / "11-change-requests.md").write_text(
            """# Change Requests

| cr_id | status | requested_at | decided_at | affected_refs | baseline_from | baseline_to | decision | approver |
|---|---|---|---|---|---|---|---|---|
| CR-001 | proposed | 2026-08-31 | none | RISK-999 | BL-001 | none | none | none |
""", encoding="utf-8")

        result = self.validate()

        self.assertTrue(any("affected reference not found: RISK-999" in e for e in result["errors"]))

    def test_v2_initiative_inherits_root_owners(self):
        initiative = self.pack / "initiatives" / "pilot"
        initiative.mkdir(parents=True)
        for path in self.pack.iterdir():
            if path.is_file() and path.name not in {"OWNERS.md", "CHANGELOG.md"}:
                shutil.copy2(path, initiative / path.name)

        errors = MODULE.check_v2(initiative)

        self.assertFalse(any("OWNERS.md missing" in error for error in errors), errors)
        self.assertFalse(any("owner must resolve" in error for error in errors), errors)

    def test_planning_project_allows_no_current_baseline_and_only_proposed_work(self):
        brief = (self.pack / "00-brief.md").read_text(encoding="utf-8")
        brief = brief.replace("| project_status | active |", "| project_status | planning |")
        brief = brief.replace("| current_baseline | BL-001 |", "| current_baseline | none |")
        (self.pack / "00-brief.md").write_text(brief, encoding="utf-8")

        requirements = (self.pack / "01-requirements.md").read_text(encoding="utf-8")
        requirements = requirements.replace(
            "| baselined | BL-001 | none | AC-BE-001, AC-BE-002 | SRC-001 | 2026-08-19 |",
            "| proposed | none | none | AC-BE-001, AC-BE-002 | SRC-001 | none |",
        )
        (self.pack / "01-requirements.md").write_text(requirements, encoding="utf-8")

        wbs = (self.pack / "02-wbs.md").read_text(encoding="utf-8")
        rows = [
            line for line in wbs.splitlines()
            if not line.startswith("| WP-BE-002 ")
        ]
        wbs = "\n".join(rows) + "\n"
        wbs = wbs.replace("| in_progress |", "| proposed |")
        wbs = wbs.replace(
            "| BL-001 | 2026-09-01 | 2026-09-15 | 2026-09-15 | 2026-09-01 | none | none | RUN-001 | none |",
            "| none | TBD | TBD | TBD | none | none | none | none | none |",
        )
        wbs = wbs.replace(
            "| WP-BE-001 | handoff | required | draft | developer | RUN-001 | Active run | none |",
            "| WP-BE-001 | handoff | required | not_started | developer | none | Not started | none |",
        )
        (self.pack / "02-wbs.md").write_text(wbs, encoding="utf-8")

        baseline = (self.pack / "09-baselines.md").read_text(encoding="utf-8")
        baseline = "\n".join(
            line for line in baseline.splitlines()
            if not line.startswith("| BL-001 ")
        ) + "\n"
        (self.pack / "09-baselines.md").write_text(baseline, encoding="utf-8")

        handoff = (self.pack / "10-handoff.md").read_text(encoding="utf-8")
        handoff = "\n".join(
            line for line in handoff.splitlines()
            if not line.startswith("| RUN-") and not line.startswith("| REL-")
        ) + "\n"
        (self.pack / "10-handoff.md").write_text(handoff, encoding="utf-8")

        risks = (self.pack / "07-risks.md").read_text(encoding="utf-8")
        (self.pack / "07-risks.md").write_text(
            risks.replace("WP-BE-001, WP-BE-002", "WP-BE-001"),
            encoding="utf-8",
        )

        result = self.validate()

        self.assertTrue(result["valid"], result["errors"])

        wbs = (self.pack / "02-wbs.md").read_text(encoding="utf-8")
        (self.pack / "02-wbs.md").write_text(
            wbs.replace("| proposed |", "| todo |", 1), encoding="utf-8"
        )
        invalid = self.validate()
        self.assertFalse(invalid["valid"])
        self.assertTrue(any(
            "project_status=planning allows only proposed or cancelled" in error
            for error in invalid["errors"]
        ))

    def test_draft_project_allows_empty_canonical_tables_without_example_facts(self):
        brief = (self.pack / "00-brief.md").read_text(encoding="utf-8")
        brief = brief.replace("| project_status | active |", "| project_status | draft |")
        brief = brief.replace("| current_baseline | BL-001 |", "| current_baseline | none |")
        (self.pack / "00-brief.md").write_text(brief, encoding="utf-8")

        for filename, prefixes in {
            "01-requirements.md": ("| SRC-", "| REQ-"),
            "02-wbs.md": ("| WP-",),
            "07-risks.md": ("| RISK-",),
            "09-baselines.md": ("| BL-",),
            "10-handoff.md": ("| RUN-", "| REL-"),
        }.items():
            path = self.pack / filename
            text = "\n".join(
                line for line in path.read_text(encoding="utf-8").splitlines()
                if not line.startswith(prefixes)
            ) + "\n"
            path.write_text(text, encoding="utf-8")
        (self.pack / "06-acceptance.md").write_text(
            "# Acceptance\n\n## Authoring Guidance\n\nVerification is added with each real AC.\n",
            encoding="utf-8",
        )

        result = self.validate()

        self.assertTrue(result["valid"], result["errors"])


if __name__ == "__main__":
    unittest.main()
