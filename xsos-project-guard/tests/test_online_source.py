"""唯一权威源（顾昊 2026-10-16）：规则与模板只从线上 xsos-delivery-control main 读。

全部用假的 gh 执行器，不连网、不需要组织凭据。
"""
import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "xsos_project_guard.py"


def load_guard_module():
    spec = importlib.util.spec_from_file_location("xsos_project_guard", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


GUARD = load_guard_module()
MANIFEST = json.loads(GUARD.REQUIRED_FILES_MANIFEST.read_text(encoding="utf-8"))

RULE = """# WBS Rule

## 中文

<!-- xsos-rule:zh -->
一个包只做一件事。
<!-- /xsos-rule:zh -->

## English

<!-- xsos-rule:en -->
One package does one thing.
<!-- /xsos-rule:en -->
"""


class FakeGh:
    """模拟 `gh api repos/<repo>/contents/<path>?ref=<ref> -H Accept: raw`。"""

    def __init__(self, files=None, fail=None):
        self.files = files or {}
        self.fail = fail
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append(command)
        if self.fail == "missing-gh":
            raise FileNotFoundError("gh")
        if self.fail == "auth":
            return subprocess.CompletedProcess(command, 1, "", "To get started with GitHub CLI, please run:  gh auth login\n")
        endpoint = command[2]
        path = endpoint.split("/contents/", 1)[1].split("?ref=", 1)[0]
        if path in self.files:
            return subprocess.CompletedProcess(command, 0, self.files[path], "")
        return subprocess.CompletedProcess(command, 1, "", "gh: Not Found (HTTP 404)\n")


def all_templates():
    return {entry["template"]: f"# online {entry['path']}\n" for entry in MANIFEST if entry.get("template")}


class OnlineSourceTest(unittest.TestCase):
    def source(self, **kwargs):
        return GUARD.OnlineSource(runner=FakeGh(**kwargs))

    def test_reads_main_of_delivery_control_through_gh(self):
        gh = FakeGh(files={"rules/wbs-rule.md": RULE})
        body = GUARD.OnlineSource(runner=gh).read("rules/wbs-rule.md")
        self.assertEqual(RULE, body)
        self.assertEqual(
            ["gh", "api", "repos/xsosglobal/xsos-delivery-control/contents/rules/wbs-rule.md?ref=main",
             "-H", "Accept: application/vnd.github.raw"],
            gh.calls[0],
        )

    def test_not_logged_in_fails_without_falling_back_to_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(GUARD.SourceError) as ctx:
                GUARD.sync_project(tmp, source=self.source(fail="auth"), check=True)
            self.assertIn("gh auth", str(ctx.exception))
            self.assertEqual([], list(Path(tmp).iterdir()))

    def test_missing_gh_is_a_clear_error(self):
        with self.assertRaises(GUARD.SourceError) as ctx:
            self.source(fail="missing-gh").read("rules/wbs-rule.md")
        self.assertIn("gh", str(ctx.exception))

    def test_cli_exits_nonzero_when_source_unreachable(self):
        with tempfile.TemporaryDirectory() as tmp:
            err = io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                code = GUARD.main(["sync", tmp, "--check"], runner=FakeGh(fail="auth"))
            self.assertEqual(2, code)
            self.assertIn("错误", err.getvalue())


class SyncTest(unittest.TestCase):
    def test_sync_creates_missing_files_from_online_templates(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = GUARD.sync_project(tmp, source=GUARD.OnlineSource(runner=FakeGh(files=all_templates())))
            self.assertEqual("repaired", report.status)
            self.assertTrue(report.source_authoritative)
            self.assertEqual("# online AGENTS.md\n", (Path(tmp) / "AGENTS.md").read_text(encoding="utf-8"))

    def test_sync_never_touches_existing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "AGENTS.md").write_text("# 项目自己的规则\n", encoding="utf-8")
            report = GUARD.sync_project(tmp, source=GUARD.OnlineSource(runner=FakeGh(files=all_templates())))
            self.assertNotIn("AGENTS.md", report.created)
            self.assertEqual("# 项目自己的规则\n", (Path(tmp) / "AGENTS.md").read_text(encoding="utf-8"))

    def test_check_reports_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = GUARD.main(["sync", tmp, "--check"], runner=FakeGh(files=all_templates()))
            self.assertEqual(1, code)
            self.assertEqual([], list(Path(tmp).iterdir()))
            report = json.loads(out.getvalue())
            self.assertIn("AGENTS.md", report["missing_required"])
            self.assertEqual("github:xsosglobal/xsos-delivery-control@main", report["source"])

    def test_check_passes_when_nothing_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            for entry in MANIFEST:
                path = Path(tmp) / entry["path"]
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("x\n", encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                code = GUARD.main(["sync", tmp, "--check"], runner=FakeGh(files=all_templates()))
            self.assertEqual(0, code)

    def test_template_missing_online_is_reported_and_fails(self):
        files = all_templates()
        dropped = next(iter(files))
        del files[dropped]
        with tempfile.TemporaryDirectory() as tmp:
            report = GUARD.sync_project(tmp, source=GUARD.OnlineSource(runner=FakeGh(files=files)), check=True)
            self.assertEqual("fail", report.status)
            self.assertTrue(any(dropped in item for item in report.template_missing))

    def test_explicit_local_copy_is_marked_non_authoritative(self):
        with tempfile.TemporaryDirectory() as project, tempfile.TemporaryDirectory() as local:
            for template, body in all_templates().items():
                path = Path(local) / template
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(body, encoding="utf-8")
            report = GUARD.sync_project(project, delivery_control_root=local, check=True)
            self.assertFalse(report.source_authoritative)
            self.assertIn("非权威源", report.warnings[0])


class RuleTest(unittest.TestCase):
    def test_rule_reads_language_block_online(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = GUARD.main(["rule", "rules/wbs-rule.md", "--lang", "en"],
                              runner=FakeGh(files={"rules/wbs-rule.md": RULE}))
        self.assertEqual(0, code)
        self.assertEqual("One package does one thing.\n", out.getvalue())

    def test_rule_format_matches_xuanshu_protocol(self):
        broken = RULE + "\n## WBS 规则（2026-10-16）\n- 区外追加的内容\n"
        with self.assertRaises(ValueError) as ctx:
            GUARD.rule_versions(broken, "AGENTS.md")
        self.assertIn("区外仅允许文件标题、中文标题和English标题", str(ctx.exception))

    def test_markers_inside_code_fence_are_ignored(self):
        fenced = RULE.replace("一个包只做一件事。", "一个包只做一件事。\n```\n<!-- xsos-rule:en -->\n```")
        self.assertIn("<!-- xsos-rule:en -->", GUARD.rule_versions(fenced)["zh"])


if __name__ == "__main__":
    unittest.main()
