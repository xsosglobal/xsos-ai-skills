from __future__ import annotations

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
        self, root: Path, paths: tuple[str, ...] | None = None
    ) -> None:
        """写一个 delivery-control 模板树。

        用例一律走 fixture,不读真实的 xsos-delivery-control:那个仓库是私有的,
        CI 上不存在。依赖它会让这些用例只在开发机上绿——CI 里直接
        FileNotFoundError。

        2026-09-06 起清单本身搬进了本仓（见 references/required-files.md），
        audit 不再读 delivery-control；这里的 fixture 只为 repair 提供模板。
        默认按真实清单铺齐，否则 repair 会在第一个没铺到的条目上停下。
        """
        if paths is None:
            guard = load_guard_module()
            manifest = json.loads(guard.REQUIRED_FILES_MANIFEST.read_text(encoding="utf-8"))
        else:
            manifest = [
                {"path": path, "template": f"templates/project-scaffold/{path}"}
                for path in paths
            ]
        template_root = root / "templates" / "project-scaffold"
        template_root.mkdir(parents=True, exist_ok=True)
        (template_root / "required-files.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        # 按条目自己声明的 template 落盘:清单里 wbs-pack 那批不在
        # templates/project-scaffold/ 下,按 path 推导会漏掉。
        for entry in manifest:
            template_path = root / entry["template"]
            template_path.parent.mkdir(parents=True, exist_ok=True)
            template_path.write_text(
                TEMPLATE_BODIES.get(entry["path"], f"# {entry['path']}\n"), encoding="utf-8"
            )

    def test_audit_reads_manifest_from_this_repo_not_delivery_control(self):
        """清单来自本仓，delivery-control 里的同名文件不再被读。

        2026-09-06 之前它读 delivery-control。那个仓库是 PRIVATE，于是 audit 在 CI 上
        直接 FileNotFoundError——首次真跑两个仓库同时崩。清单是「哪些文件必需」这条
        规则，规则住在规则源；模板留在治理仓，只有 repair 需要。
        """
        guard = load_guard_module()
        with tempfile.TemporaryDirectory() as project_raw, tempfile.TemporaryDirectory() as delivery_raw:
            project_root = Path(project_raw)
            delivery_root = Path(delivery_raw)
            # 故意在 delivery-control 里放一份**不同**的清单，它应当被忽略
            self.write_delivery_control_fixture(delivery_root, paths=("AGENTS.md", "custom.md"))
            (project_root / "AGENTS.md").write_text("# Exists\n", encoding="utf-8")

            report = guard.audit_project(project_root, delivery_control_root=delivery_root)

            self.assertNotIn("custom.md", report.missing_required)
            self.assertIn("docs/wbs/00-brief.md", report.missing_required)

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
            # 模板正文仍来自 delivery-control——搬走的是「哪些文件必需」这条清单,
            # 不是模板本身。custom.md 那条断言已删:清单不再由 fixture 提供,
            # 编不出真实清单里没有的条目。
            self.assertEqual("# From Delivery Control\n", (project_root / "AGENTS.md").read_text(encoding="utf-8"))
            self.assertNotIn("custom.md", report.created)

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
            self.write_delivery_control_fixture(delivery_root)

            report = guard.repair_project(root, delivery_control_root=delivery_root)

            self.assertEqual("repaired", report.status)
            # 清单来自本仓,repair 会把 19 条全建出来;这里只断言脚手架这几条在内,
            # 不再断言相等——否则每加一条必需文件都要改这个用例。
            self.assertLessEqual(set(STANDARD_SCAFFOLD), set(report.created))
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
        """开发机上顺带校验真实宪法仓库:清单里每条的模板在那边都存在。

        xsos-delivery-control 是私有仓库,CI 上检出不到——那里会显式 skip 并
        打印原因,不会伪装成通过。

        skip 的判据是**模板目录**在不在,不能再看 manifest 在不在:清单已经搬进
        本仓(references/required-files.json),`delivery_root / 绝对路径` 在
        pathlib 里直接返回那个绝对路径,于是它永远 exists,skip 永远不触发,
        CI 上接着去查一个根本没检出的仓库里的模板。main 因此红过一次。
        """
        guard = load_guard_module()
        delivery_root = guard.resolve_delivery_control_root()
        templates_root = delivery_root / "templates" / "project-scaffold"
        if not templates_root.is_dir():
            self.skipTest(f"xsos-delivery-control 未检出({templates_root}),仅开发机上运行")

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
