import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_status_drift.py"


def load():
    spec = importlib.util.spec_from_file_location("check_status_drift", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


HEADER = "| wp_id | title_cn | type | owner | status |"
SEP = "|---|---|---|---|---|"


def make_repo(root: Path, rows) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "master", str(root)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t"), ("commit.gpgsign", "false")):
        subprocess.run(["git", "-C", str(root), "config", k, v], check=True)
    pack = root / "docs" / "wbs"
    pack.mkdir(parents=True)
    body = "\n".join(f"| {r[0]} | {r[1]} | {r[2]} | 顾昊 | {r[3]} |" for r in rows)
    (pack / "02-wbs.md").write_text("# WBS\n\n" + "\n".join([HEADER, SEP, body]) + "\n",
                                    encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "init"], check=True)
    return pack


def commit(root: Path, message: str, name: str, content: str = "x") -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", message], check=True)


def run(pack: Path, *extra):
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(pack), "--prod-ref", "master", *extra],
        capture_output=True, text=True)


class StatusDriftTest(unittest.TestCase):
    def test_flags_shipped_backend_still_marked_unfinished(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "repo"
            pack = make_repo(root, [("WP-BE-001", "已上线的包", "backend", "in_progress")])
            commit(root, "feat(WP-BE-001): 实现", "internal/a.go", "package a")
            out = run(pack)
            self.assertIn("WP-BE-001", out.stdout)
            self.assertIn("代码已上生产", out.stdout)
            self.assertEqual(0, out.returncode, "默认只警告不阻断")
            self.assertEqual(1, run(pack, "--fail").returncode)

    def test_doc_only_commit_is_not_treated_as_shipped(self):
        """立包那次提交也带 wp_id,但只改文档——按提交数判断会把立包当完成。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "repo"
            pack = make_repo(root, [("WP-BE-002", "只立了包", "backend", "todo")])
            commit(root, "docs(WP-BE-002): 立包并写交接", "docs/wbs/10-handoff.md", "# handoff")
            out = run(pack)
            self.assertNotIn("WP-BE-002 标", out.stdout)
            self.assertIn("无失真", out.stdout)

    def test_cross_reference_in_body_is_not_evidence(self):
        """正文里提到别人的包,不算那个包被实现了。

        db9490b3 `feat(WP-BE-064): ...` 正文写着前端部分归 WP-FS-065,
        --grep 连正文一起搜,会把 WP-FS-065 误判成已上生产。
        """
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "repo"
            pack = make_repo(root, [("WP-FS-007", "前端包", "frontend", "todo")])
            path = root / "internal" / "e.go"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("package e", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-q",
                            "-m", "feat(WP-BE-006): 后端实现",
                            "-m", "前端部分归 WP-FS-007，本次不做。"], check=True)
            out = run(pack)
            self.assertNotIn("WP-FS-007 标", out.stdout)

    def test_docs_commit_touching_code_is_not_implementation(self):
        """立包提交顺手改两行 DTO,不算实现。

        c0c10046 `docs(WP-FS-059,...): 立三个前端包并写交接说明` 改了
        internal/quality/dto.go —— 只看文件后缀会把它当成"已上生产"。
        """
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "repo"
            pack = make_repo(root, [("WP-BE-010", "只立了包", "backend", "todo")])
            commit(root, "docs(WP-BE-010): 立包并顺手补 DTO 字段",
                   "internal/dto.go", "package internal")
            out = run(pack)
            self.assertNotIn("WP-BE-010 标", out.stdout)
            self.assertIn("无失真", out.stdout)

    def test_frontend_without_its_repo_is_unverifiable_not_undone(self):
        """只传后端仓库时,前端包"查不到"什么都说明不了,不能当成没做。

        2026-08-27 我一度以为 web 仓库不写 wp_id,于是直接跳过前端包。
        那个前提是错的——查的是 gitee 的陈旧引用,活的 github/master 上
        有 28 条。所以这里改成"无法验证",并提示把 web 仓库传进来。
        """
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "repo"
            pack = make_repo(root, [("WP-FS-003", "前端页面", "frontend", "todo")])
            commit(root, "feat(WP-BE-999): 无关改动", "internal/b.go", "package b")
            out = run(pack)
            self.assertIn("无法验证 1 个前端/全栈包", out.stdout)
            self.assertNotIn("WP-FS-003 标", out.stdout)

    def test_frontend_with_code_in_searched_repo_is_flagged(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "web"
            pack = make_repo(root, [("WP-FS-004", "前端页面", "frontend", "todo")])
            commit(root, "feat(WP-FS-004): 页面完成", "src/pages/a.tsx", "export default 1")
            out = run(pack, "--code-ext", ".tsx,.ts,.vue")
            self.assertIn("WP-FS-004", out.stdout)
            self.assertIn("代码已上生产", out.stdout)

    def test_fullstack_is_reported_separately_not_as_definite_drift(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "repo"
            pack = make_repo(root, [("WP-FS-004", "全栈包", "fullstack", "in_progress")])
            commit(root, "feat(WP-FS-004): 后端部分", "internal/c.go", "package c")
            out = run(pack)
            self.assertIn("前端未必完成", out.stdout)
            self.assertEqual(0, run(pack, "--fail").returncode, "待判断的不该阻断")

    def test_finished_status_is_not_flagged(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "repo"
            pack = make_repo(root, [("WP-BE-005", "早就完成", "backend", "done")])
            commit(root, "feat(WP-BE-005): 实现", "internal/d.go", "package d")
            self.assertIn("无失真", run(pack).stdout)

    def test_missing_prod_ref_skips_loudly(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "repo"
            pack = make_repo(root, [("WP-BE-006", "包", "backend", "todo")])
            out = subprocess.run(
                [sys.executable, str(SCRIPT), str(pack), "--prod-ref", "origin/nope"],
                capture_output=True, text=True)
            self.assertIn("解析不到", out.stderr)
            self.assertEqual(0, out.returncode)

    def test_parse_rows_reads_header_driven_columns(self):
        module = load()
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "02-wbs.md"
            path.write_text("# WBS\n\n" + "\n".join(
                [HEADER, SEP, "| WP-BE-009 | 标题 | backend | 顾昊 | review |"]) + "\n",
                encoding="utf-8")
            rows = module.parse_rows(path)
            self.assertEqual(1, len(rows))
            self.assertEqual("review", rows[0]["status"])
            self.assertEqual("backend", rows[0]["type"])


if __name__ == "__main__":
    unittest.main()
