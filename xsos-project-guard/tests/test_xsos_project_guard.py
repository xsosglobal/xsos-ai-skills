import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "xsos_project_guard.py"


def load_guard_module():
    spec = importlib.util.spec_from_file_location("xsos_project_guard", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class XSOSProjectGuardTest(unittest.TestCase):
    def write_delivery_control_fixture(self, root: Path) -> None:
        template_root = root / "templates" / "project-scaffold"
        template_root.mkdir(parents=True)
        (template_root / "required-files.json").write_text(
            """[
  {"path": "AGENTS.md", "template": "templates/project-scaffold/AGENTS.md"},
  {"path": "custom.md", "template": "templates/project-scaffold/custom.md"}
]
""",
            encoding="utf-8",
        )
        (template_root / "AGENTS.md").write_text("# From Delivery Control\n", encoding="utf-8")
        (template_root / "custom.md").write_text("# Custom Template\n", encoding="utf-8")

    def test_audit_reads_required_files_from_delivery_control(self):
        guard = load_guard_module()
        with tempfile.TemporaryDirectory() as project_raw, tempfile.TemporaryDirectory() as delivery_raw:
            project_root = Path(project_raw)
            delivery_root = Path(delivery_raw)
            self.write_delivery_control_fixture(delivery_root)
            (project_root / "AGENTS.md").write_text("# Exists\n", encoding="utf-8")

            report = guard.audit_project(project_root, delivery_control_root=delivery_root)

            self.assertIn("custom.md", report.missing_required)
            self.assertNotIn("docs/wbs/00-brief.md", report.missing_required)

    def test_delivery_control_root_prefers_environment_override(self):
        guard = load_guard_module()
        with tempfile.TemporaryDirectory() as raw:
            with mock.patch.dict(os.environ, {"XSOS_DELIVERY_CONTROL_ROOT": raw}):
                self.assertEqual(Path(raw).resolve(), guard.resolve_delivery_control_root())

    def test_wbs_validator_resolves_from_current_skills_repository(self):
        guard = load_guard_module()
        expected = SCRIPT_PATH.resolve().parents[2] / "xsos-wbs-pack" / "scripts" / "validate_wbs_pack.py"
        self.assertEqual(expected, guard.WBS_VALIDATOR)
        self.assertTrue(guard.WBS_VALIDATOR.exists())

    def test_repair_uses_templates_from_delivery_control(self):
        guard = load_guard_module()
        with tempfile.TemporaryDirectory() as project_raw, tempfile.TemporaryDirectory() as delivery_raw:
            project_root = Path(project_raw)
            delivery_root = Path(delivery_raw)
            self.write_delivery_control_fixture(delivery_root)

            report = guard.repair_project(project_root, delivery_control_root=delivery_root)

            self.assertEqual("repaired", report.status)
            self.assertEqual("# From Delivery Control\n", (project_root / "AGENTS.md").read_text(encoding="utf-8"))
            self.assertEqual("# Custom Template\n", (project_root / "custom.md").read_text(encoding="utf-8"))

    def test_audit_reports_missing_standard_files(self):
        guard = load_guard_module()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "docs" / "wbs").mkdir(parents=True)
            (root / "docs" / "wbs" / "00-brief.md").write_text("# Brief\n", encoding="utf-8")

            report = guard.audit_project(root)

            self.assertEqual("fail", report.status)
            self.assertIn("AGENTS.md", report.missing_required)
            self.assertIn("docs/standards/README.md", report.missing_required)
            self.assertIn("docs/change-control.md", report.missing_required)

    def test_repair_creates_required_standard_scaffold(self):
        guard = load_guard_module()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)

            report = guard.repair_project(root)

            self.assertEqual("repaired", report.status)
            self.assertTrue((root / "AGENTS.md").exists())
            self.assertTrue((root / "docs" / "standards" / "README.md").exists())
            self.assertTrue((root / "docs" / "change-control.md").exists())
            self.assertTrue((root / "docs" / "sops" / "core-development-sop.md").exists())
            self.assertTrue((root / "docs" / "wbs" / "CHANGELOG.md").exists())

    def test_module_yaml_warning_when_absent_but_not_failure(self):
        guard = load_guard_module()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)

            report = guard.audit_project(root)

            self.assertEqual("fail", report.status)
            self.assertIn("module.yaml is absent; required only for runtime modules.", report.warnings)
            self.assertNotIn("module.yaml", report.missing_required)


if __name__ == "__main__":
    unittest.main()
