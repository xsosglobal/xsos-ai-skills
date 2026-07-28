import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml


SCRIPT = Path(__file__).parents[1] / "scripts/context_pack.py"


class ContextPackTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.project = root / "project"
        self.context = root / "context"
        (self.project / "docs/wbs").mkdir(parents=True)
        for folder in ("capabilities", "scenarios", "baselines"):
            (self.context / folder).mkdir(parents=True)

        (self.project / "AGENTS.md").write_text("# Rules\n", encoding="utf-8")
        (self.project / "module.yaml").write_text("module_key: demo\n", encoding="utf-8")
        (self.project / "docs/wbs/00-brief.md").write_text("# Brief\n", encoding="utf-8")
        (self.project / "docs/wbs/01-requirements.md").write_text("# Requirements\n", encoding="utf-8")
        (self.project / "docs/wbs/02-wbs.md").write_text(
            "| ID | CN | EN | Type | Owner | Status | Depends | AC | Outputs |\n"
            "|---|---|---|---|---|---|---|---|---|\n"
            "| WP-DEMO-001 | 演示任务 | Demo | backend | owner | todo | - | AC-DEMO-001 | code, tests |\n",
            encoding="utf-8",
        )
        (self.project / "docs/wbs/04-api-contract.md").write_text("# API\n", encoding="utf-8")
        (self.project / "docs/wbs/06-acceptance.md").write_text(
            "# Acceptance\n\n## AC-DEMO-001: Demo accepted\n\n- Tests pass.\n", encoding="utf-8"
        )
        self.write_yaml("capabilities/demo.yaml", {
            "id": "demo.read", "version": "1.0.0", "status": "active", "domain": "demo",
            "owner": "demo-owner", "description": "Read demo data.",
            "contract_refs": ["docs/wbs/04-api-contract.md"], "source_refs": ["module.yaml"],
        })
        self.write_yaml("scenarios/demo.yaml", {
            "id": "demo-flow", "version": "1.0.0", "status": "accepted", "owner": "biz-owner",
            "goal": "Complete demo flow.", "trigger": "Task starts.", "outcome": "Demo completes.",
            "participants": [{"capability_id": "demo.read", "required_version": "1.0.0"}],
            "steps": ["Read demo data."], "source_refs": ["docs/wbs/01-requirements.md"],
        })
        requirement_hash = hashlib.sha256((self.project / "docs/wbs/01-requirements.md").read_bytes()).hexdigest()
        self.write_yaml("baselines/active.yaml", {
            "id": "active", "status": "active", "approved_by": "tech-owner", "approved_at": "2026-07-27",
            "scenario_versions": {"demo-flow": "1.0.0"},
            "capability_versions": {"demo.read": "1.0.0"},
            "source_hashes": {"docs/wbs/01-requirements.md": requirement_hash},
        })

    def tearDown(self):
        self.temp.cleanup()

    def write_yaml(self, relative, value):
        path = self.context / relative
        path.write_text(yaml.safe_dump(value, allow_unicode=True, sort_keys=False), encoding="utf-8")

    def invoke(self, command="validate", extra=None):
        args = [
            "python3", str(SCRIPT), command, "--project-root", str(self.project), "--wp", "WP-DEMO-001",
            "--context-root", str(self.context), "--scenario", "demo-flow", "--baseline", "active",
        ]
        if command == "build":
            args += ["--output", str(Path(self.temp.name) / "pack.md")]
        args += extra or []
        return subprocess.run(args, text=True, capture_output=True)

    def test_valid_context_builds_traceable_pack(self):
        result = self.invoke("build")
        self.assertEqual(result.returncode, 0, result.stderr)
        pack = (Path(self.temp.name) / "pack.md").read_text(encoding="utf-8")
        self.assertIn("demo-flow@1.0.0", pack)
        self.assertIn("demo.read@1.0.0", pack)
        self.assertIn("Source Evidence", pack)

    def test_same_inputs_produce_same_pack_hash(self):
        first = self.invoke("build")
        self.assertEqual(first.returncode, 0, first.stderr)
        first_hash = hashlib.sha256((Path(self.temp.name) / "pack.md").read_bytes()).hexdigest()
        second = self.invoke("build")
        self.assertEqual(second.returncode, 0, second.stderr)
        second_hash = hashlib.sha256((Path(self.temp.name) / "pack.md").read_bytes()).hexdigest()
        self.assertEqual(first_hash, second_hash)

    def test_missing_capability_blocks_resolution(self):
        (self.context / "capabilities/demo.yaml").unlink()
        result = self.invoke()
        self.assertEqual(result.returncode, 2)
        self.assertIn("capability not found", result.stderr)

    def test_capability_version_drift_is_blocking(self):
        value = yaml.safe_load((self.context / "capabilities/demo.yaml").read_text(encoding="utf-8"))
        value["version"] = "1.1.0"
        self.write_yaml("capabilities/demo.yaml", value)
        result = self.invoke()
        self.assertEqual(result.returncode, 2)
        self.assertIn("capability version mismatch", result.stderr)

    def test_inactive_baseline_is_blocking(self):
        value = yaml.safe_load((self.context / "baselines/active.yaml").read_text(encoding="utf-8"))
        value["status"] = "retired"
        self.write_yaml("baselines/active.yaml", value)
        result = self.invoke()
        self.assertEqual(result.returncode, 2)
        self.assertIn("baseline is not active", result.stderr)

    def test_source_hash_drift_is_blocking(self):
        (self.project / "docs/wbs/01-requirements.md").write_text("# Changed\n", encoding="utf-8")
        result = self.invoke()
        self.assertEqual(result.returncode, 2)
        self.assertIn("source hash drift", result.stderr)

    def test_missing_acceptance_is_blocking(self):
        (self.project / "docs/wbs/06-acceptance.md").write_text("# Acceptance\n", encoding="utf-8")
        result = self.invoke()
        self.assertEqual(result.returncode, 2)
        self.assertIn("acceptance criterion not found", result.stderr)

    def test_dynamic_wbs_headers_support_scope_and_non_goals(self):
        (self.project / "docs/wbs/02-wbs.md").write_text(
            "| wp_id | title_cn | title_en | type | owner | status | depends_on | scope | non_goals | acceptance_ref | outputs |\n"
            "|---|---|---|---|---|---|---|---|---|---|---|\n"
            "| WP-DEMO-001 | 演示任务 | Demo | backend | owner | todo | - | task scope | no UI | AC-DEMO-001 | code, tests |\n",
            encoding="utf-8",
        )
        result = self.invoke("build")
        self.assertEqual(result.returncode, 0, result.stderr)
        pack = (Path(self.temp.name) / "pack.md").read_text(encoding="utf-8")
        self.assertIn("Acceptance `AC-DEMO-001`", pack)
        self.assertIn("Outputs: code, tests", pack)

    def test_cross_repository_source_is_resolved_by_alias(self):
        pda = Path(self.temp.name) / "pda"
        pda.mkdir()
        (pda / "contract.md").write_text("# PDA contract\n", encoding="utf-8")
        capability = yaml.safe_load((self.context / "capabilities/demo.yaml").read_text(encoding="utf-8"))
        capability["repository"] = "pda"
        capability["contract_refs"] = ["contract.md"]
        capability["source_refs"] = []
        self.write_yaml("capabilities/demo.yaml", capability)

        result = self.invoke("build", ["--repo", f"pda={pda}"])

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("`pda` | `contract.md`", (Path(self.temp.name) / "pack.md").read_text(encoding="utf-8"))

    def test_path_escape_and_sensitive_source_are_blocking(self):
        capability = yaml.safe_load((self.context / "capabilities/demo.yaml").read_text(encoding="utf-8"))
        capability["source_refs"] = ["../outside.md"]
        self.write_yaml("capabilities/demo.yaml", capability)
        escaped = self.invoke()
        self.assertEqual(escaped.returncode, 2)
        self.assertIn("escapes repository", escaped.stderr)

        capability["source_refs"] = [".env.production"]
        self.write_yaml("capabilities/demo.yaml", capability)
        sensitive = self.invoke()
        self.assertEqual(sensitive.returncode, 2)
        self.assertIn("sensitive source is forbidden", sensitive.stderr)

    def test_formal_baseline_requires_approval_and_exact_git_revision(self):
        subprocess.run(["git", "init", "-q", str(self.project)], check=True)
        subprocess.run(["git", "-C", str(self.project), "add", "."], check=True)
        subprocess.run([
            "git", "-C", str(self.project), "-c", "user.name=Test", "-c", "user.email=test@example.com",
            "commit", "-qm", "fixture",
        ], check=True)
        revision = subprocess.run(
            ["git", "-C", str(self.project), "rev-parse", "HEAD"], text=True, capture_output=True, check=True
        ).stdout.strip()
        baseline = yaml.safe_load((self.context / "baselines/active.yaml").read_text(encoding="utf-8"))
        (self.context / "approvals").mkdir()
        (self.context / "approvals/2026-07-27.md").write_text("Approved by owner.\n", encoding="utf-8")
        baseline.update({"mode": "formal", "approval_ref": "docs/approvals/2026-07-27.md", "repository_revisions": {"project": revision}})
        baseline["approval_ref"] = "approvals/2026-07-27.md"
        self.write_yaml("baselines/active.yaml", baseline)
        passed = self.invoke()
        self.assertEqual(passed.returncode, 0, passed.stderr)

        (self.project / "module.yaml").write_text("module_key: changed\n", encoding="utf-8")
        dirty = self.invoke()
        self.assertEqual(dirty.returncode, 2)
        self.assertIn("repository is dirty: project", dirty.stderr)
        subprocess.run(["git", "-C", str(self.project), "restore", "module.yaml"], check=True)

        baseline["repository_revisions"]["project"] = "deadbeef"
        self.write_yaml("baselines/active.yaml", baseline)
        drift = self.invoke()
        self.assertEqual(drift.returncode, 2)
        self.assertIn("repository revision drift", drift.stderr)

    def test_formal_baseline_requires_existing_approval_evidence(self):
        baseline = yaml.safe_load((self.context / "baselines/active.yaml").read_text(encoding="utf-8"))
        baseline.update({
            "mode": "formal",
            "approval_ref": "approvals/missing.md",
            "repository_revisions": {"project": "unused"},
        })
        self.write_yaml("baselines/active.yaml", baseline)

        result = self.invoke()

        self.assertEqual(result.returncode, 2)
        self.assertIn("approval evidence not found", result.stderr)


if __name__ == "__main__":
    unittest.main()
