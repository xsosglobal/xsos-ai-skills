"""立包前的版本自检：落后提示、离线静默、环境变量关闭。"""
import importlib.util
import io
import os
from contextlib import redirect_stderr
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "add_work_package.py"


def load():
    spec = importlib.util.spec_from_file_location("add_work_package_update", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True)


def commit(cwd, name):
    (Path(cwd) / name).write_text(name, encoding="utf-8")
    git(cwd, "add", name)
    git(cwd, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", name)


class UpdateCheckTest(unittest.TestCase):
    def setUp(self):
        self.module = load()
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.origin, self.clone = root / "origin", root / "clone"
        self.origin.mkdir()
        git(self.origin, "init", "-q", "-b", "main")
        commit(self.origin, "a")
        git(root, "clone", "-q", str(self.origin), str(self.clone))
        self.env = mock.patch.dict(os.environ, {}, clear=False)
        self.env.start()
        os.environ.pop(self.module.UPDATE_CHECK_ENV, None)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def check(self):
        err = io.StringIO()
        with redirect_stderr(err):
            behind = self.module.check_skills_up_to_date(self.clone)
        return behind, err.getvalue()

    def test_up_to_date_is_silent(self):
        behind, err = self.check()
        self.assertEqual(0, behind)
        self.assertEqual("", err)

    def test_behind_prints_count_and_command(self):
        commit(self.origin, "b")
        commit(self.origin, "c")
        behind, err = self.check()
        self.assertEqual(2, behind)
        self.assertIn("落后 GitHub main 2 个提交", err)
        self.assertIn("install.sh", err)
        # 只提示不自动拉：本地 HEAD 不动。
        local = subprocess.run(["git", "-C", str(self.clone), "rev-list", "--count", "HEAD"], capture_output=True, text=True).stdout.strip()
        self.assertEqual("1", local)

    def test_recent_fetch_is_not_repeated(self):
        self.assertEqual(0, self.check()[0])  # 第一次 fetch，写下 FETCH_HEAD
        commit(self.origin, "b")
        behind, err = self.check()  # 十分钟内不再 fetch，按已有远端记录判断
        self.assertEqual(0, behind)
        head = self.clone / ".git" / "FETCH_HEAD"
        os.utime(head, (0, 0))  # 记录过期后重新 fetch
        behind, err = self.check()
        self.assertEqual(1, behind)

    def test_offline_is_silent(self):
        git(self.clone, "remote", "set-url", "origin", str(Path(self.tmp.name) / "missing"))
        behind, err = self.check()
        self.assertIsNone(behind)
        self.assertEqual("", err)

    def test_not_a_git_repo_is_silent(self):
        plain = Path(self.tmp.name) / "plain"
        plain.mkdir()
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertIsNone(self.module.check_skills_up_to_date(plain))
        self.assertEqual("", err.getvalue())

    def test_env_disables_check(self):
        commit(self.origin, "b")
        os.environ[self.module.UPDATE_CHECK_ENV] = "1"
        behind, err = self.check()
        self.assertIsNone(behind)
        self.assertEqual("", err)


if __name__ == "__main__":
    unittest.main()
