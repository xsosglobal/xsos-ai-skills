"""清单搬进规则源之后的约束。

2026-09-06：audit 曾在 CI 上直接崩，因为清单住在 PRIVATE 的 xsos-delivery-control，
runner 上检不出来。清单搬进本仓后，audit 与那个私有仓再无关系——这几条把它钉住。
"""
import json
import tempfile
import unittest
import importlib.util
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "xsos_project_guard.py"


def load_guard_module():
    spec = importlib.util.spec_from_file_location("xsos_project_guard", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


GUARD = load_guard_module()


class RequiredFilesManifestTest(unittest.TestCase):
    def test_manifest_lives_in_this_repo(self):
        """清单必须在本仓，不能再指向 delivery-control。"""
        self.assertTrue(GUARD.REQUIRED_FILES_MANIFEST.is_file(), GUARD.REQUIRED_FILES_MANIFEST)
        self.assertIn("xsos-project-guard", str(GUARD.REQUIRED_FILES_MANIFEST))

    def test_audit_works_without_delivery_control(self):
        """delivery-control 完全不可达时 audit 仍要能跑完，不能抛异常。"""
        with tempfile.TemporaryDirectory() as tmp:
            report = GUARD.audit_project(tmp, delivery_control_root=Path(tmp) / "nope")
            self.assertIn(report.status, {"pass", "fail"})
            self.assertTrue(report.missing_required)

    def test_manifest_has_no_unimplemented_fields(self):
        """清单不得出现代码没实现的字段。

        delivery-control 的 develop 分支上多一条带 "appliesTo": "module" 的 module.yaml，
        而 RequiredFile 只有 path 与 template，从不读 appliesTo。那一条一旦生效，
        module.yaml 会变成所有仓库无条件必需——实测 25 个仓库全部多缺 1 个，
        8 个原本 pass 的直接转 fail，而 audit_project 里那行硬编码 warning 还会同时说
        它「只有运行时模块才需要」。

        要支持 appliesTo，先实现它，再往清单里加。
        """
        known = {"path", "template"}
        raw = json.loads(GUARD.REQUIRED_FILES_MANIFEST.read_text(encoding="utf-8"))
        for entry in raw:
            extra = set(entry) - known
            self.assertFalse(
                extra,
                f"{entry.get('path')} 带了代码未实现的字段 {sorted(extra)}；"
                f"先在 RequiredFile 与 audit_project 里实现，再加进清单",
            )

    def test_repair_reports_missing_template_clearly(self):
        """repair 仍需要治理仓的模板；找不到时要明确报错，不静默降级。"""
        spec = GUARD.RequiredFile(path="AGENTS.md", template="templates/project-scaffold/AGENTS.md")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError) as ctx:
                GUARD.load_template(tmp, spec)
            self.assertIn("xsos-delivery-control", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
