import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "xsos_project_guard.py"

# 交付控制仓库标准脚手架里的一部分路径,够覆盖「manifest 驱动」这条链路。
STANDARD_SCAFFOLD = (
    "AGENTS.md",
    "docs/standards/README.md",
    "docs/change-control.md",
    "docs/sops/core-development-sop.md",
    "docs/wbs/CHANGELOG.md",
)

TEMPLATE_BODIES = {
    "AGENTS.md": "# From Delivery Control\n",
    "custom.md": "# Custom Template\n",
}


def load_guard_module():
    spec = importlib.util.spec_from_file_location("xsos_project_guard", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class XSOSProjectGuardTest(unittest.TestCase):
    def write_delivery_control_fixture(
        self, root: Path, paths: tuple[str, ...] = ("AGENTS.md", "custom.md")
    ) -> None:
        """写一个最小的 delivery-control 模板树。

        用例一律走 fixture,不读真实的 xsos-delivery-control:那个仓库是私有的,
        CI 上不存在。依赖它会让这些用例只在开发机上绿——CI 里直接
        FileNotFoundError。真实 manifest 的校验单独放在下面的集成用例里。
        """
        template_root = root / "templates" / "project-scaffold"
        template_root.mkdir(parents=True, exist_ok=True)
        manifest = [
            {"path": path, "template": f"templates/project-scaffold/{path}"} for path in paths
        ]
        (template_root / "required-files.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        for path in paths:
            template_path = template_root / path
            template_path.parent.mkdir(parents=True, exist_ok=True)
            template_path.write_text(
                TEMPLATE_BODIES.get(path, f"# {path}\n"), encoding="utf-8"
            )

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
        with tempfile.TemporaryDirectory() as project_raw, tempfile.TemporaryDirectory() as delivery_raw:
            root = Path(project_raw)
            delivery_root = Path(delivery_raw)
            self.write_delivery_control_fixture(delivery_root, STANDARD_SCAFFOLD)
            (root / "docs" / "wbs").mkdir(parents=True)
            (root / "docs" / "wbs" / "00-brief.md").write_text("# Brief\n", encoding="utf-8")

            report = guard.audit_project(root, delivery_control_root=delivery_root)

            self.assertEqual("fail", report.status)
            self.assertIn("AGENTS.md", report.missing_required)
            self.assertIn("docs/standards/README.md", report.missing_required)
            self.assertIn("docs/change-control.md", report.missing_required)

    def test_repair_creates_required_standard_scaffold(self):
        guard = load_guard_module()
        with tempfile.TemporaryDirectory() as project_raw, tempfile.TemporaryDirectory() as delivery_raw:
            root = Path(project_raw)
            delivery_root = Path(delivery_raw)
            self.write_delivery_control_fixture(delivery_root, STANDARD_SCAFFOLD)

            report = guard.repair_project(root, delivery_control_root=delivery_root)

            self.assertEqual("repaired", report.status)
            self.assertEqual(sorted(STANDARD_SCAFFOLD), sorted(report.created))
            for rel_path in STANDARD_SCAFFOLD:
                self.assertTrue((root / rel_path).exists(), rel_path)

    def test_module_yaml_warning_when_absent_but_not_failure(self):
        guard = load_guard_module()
        with tempfile.TemporaryDirectory() as project_raw, tempfile.TemporaryDirectory() as delivery_raw:
            root = Path(project_raw)
            delivery_root = Path(delivery_raw)
            self.write_delivery_control_fixture(delivery_root, STANDARD_SCAFFOLD)

            report = guard.audit_project(root, delivery_control_root=delivery_root)

            self.assertEqual("fail", report.status)
            self.assertIn("module.yaml is absent; required only for runtime modules.", report.warnings)
            self.assertNotIn("module.yaml", report.missing_required)

    def test_real_delivery_control_manifest_is_consistent(self):
        """开发机上顺带校验真实宪法仓库:manifest 能解析,且模板文件都在。

        xsos-delivery-control 是私有仓库,CI 上检出不到——那里会显式 skip 并
        打印原因,不会伪装成通过。
        """
        guard = load_guard_module()
        delivery_root = guard.resolve_delivery_control_root()
        manifest = delivery_root / guard.REQUIRED_FILES_MANIFEST
        if not manifest.exists():
            self.skipTest(f"xsos-delivery-control 未检出({manifest}),仅开发机上运行")

        specs = guard.load_required_files(delivery_root)
        self.assertTrue(specs, "required-files.json 不应为空")
        missing_templates = [
            spec.template
            for spec in specs
            if spec.template and not (delivery_root / spec.template).exists()
        ]
        self.assertEqual([], missing_templates)


if __name__ == "__main__":
    unittest.main()
