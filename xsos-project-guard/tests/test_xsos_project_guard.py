import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "xsos_project_guard.py"


def load_guard_module():
    spec = importlib.util.spec_from_file_location("xsos_project_guard", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class XSOSProjectGuardTest(unittest.TestCase):
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
