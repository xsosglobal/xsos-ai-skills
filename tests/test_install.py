"""install.sh：首次安装、再次更新、本地改动时停止、目标已占用时不覆盖。"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "install.sh"
SKILLS = ["xsos-context-pack", "xsos-feedback-fix", "xsos-package-plan", "xsos-project-guard", "xsos-wbs-author", "xsos-wbs-pack"]


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


def commit(cwd, name, body="x"):
    path = Path(cwd) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    git(cwd, "add", name)
    git(cwd, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", name)


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.home = root / "home"
        self.home.mkdir()
        # 本地假源：六个 skill 目录各带一个 SKILL.md。
        self.source = root / "source"
        self.source.mkdir()
        git(self.source, "init", "-q", "-b", "main")
        for skill in SKILLS:
            commit(self.source, f"{skill}/SKILL.md", skill)

    def tearDown(self):
        self.tmp.cleanup()

    def run_install(self, **extra):
        env = {
            "PATH": os.environ["PATH"],
            "HOME": str(self.home),
            "XSOS_SKILLS_REPO_URL": str(self.source),
        }
        env.update(extra)
        return subprocess.run(["bash", str(INSTALL)], env=env, capture_output=True, text=True)

    @property
    def clone(self):
        return self.home / ".xsos-ai-skills"

    def test_first_install_links_both_tools(self):
        result = self.run_install()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        for tool in (".claude", ".codex"):
            for skill in SKILLS:
                link = self.home / tool / "skills" / skill
                self.assertTrue(link.is_symlink(), link)
                self.assertEqual((self.clone / skill).resolve(), link.resolve())
        self.assertIn(git(self.clone, "rev-parse", "--short", "HEAD"), result.stdout)

    def test_second_run_fast_forwards(self):
        self.assertEqual(0, self.run_install().returncode)
        commit(self.source, "xsos-wbs-pack/NEW.md")
        result = self.run_install()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertTrue((self.clone / "xsos-wbs-pack" / "NEW.md").exists())
        self.assertIn("✓", result.stdout)

    def test_local_changes_stop_without_touching_them(self):
        self.assertEqual(0, self.run_install().returncode)
        (self.clone / "xsos-wbs-pack" / "SKILL.md").write_text("mine", encoding="utf-8")
        commit(self.source, "xsos-wbs-pack/NEW.md")
        result = self.run_install()
        self.assertNotEqual(0, result.returncode)
        self.assertIn("未提交的改动", result.stderr)
        self.assertEqual("mine", (self.clone / "xsos-wbs-pack" / "SKILL.md").read_text(encoding="utf-8"))
        self.assertFalse((self.clone / "xsos-wbs-pack" / "NEW.md").exists())

    def test_other_branch_stops_without_switching(self):
        self.assertEqual(0, self.run_install().returncode)
        git(self.clone, "checkout", "-q", "-b", "feature/x")
        result = self.run_install()
        self.assertNotEqual(0, result.returncode)
        self.assertIn("不会切分支", result.stderr)
        self.assertEqual("feature/x", git(self.clone, "symbolic-ref", "--short", "HEAD"))

    def test_occupied_targets_are_not_overwritten(self):
        claude = self.home / ".claude" / "skills"
        claude.mkdir(parents=True)
        (claude / "xsos-wbs-pack").mkdir()  # 真实目录
        elsewhere = Path(self.tmp.name) / "elsewhere"
        elsewhere.mkdir()
        os.symlink(elsewhere, claude / "xsos-wbs-author")  # 指向别处的软链
        result = self.run_install()
        self.assertNotEqual(0, result.returncode)
        self.assertFalse((claude / "xsos-wbs-pack").is_symlink())
        self.assertEqual(elsewhere.resolve(), (claude / "xsos-wbs-author").resolve())
        self.assertTrue((claude / "xsos-feedback-fix").is_symlink())
        self.assertIn("没有覆盖", result.stdout)

    def test_reuses_clone_already_linked(self):
        # 按旧 README 装在别处的同事：沿用那份克隆，不再多克隆一份。
        old = Path(self.tmp.name) / "work" / "xsos-ai-skills"
        old.parent.mkdir()
        git(old.parent, "clone", "-q", str(self.source), str(old))
        claude = self.home / ".claude" / "skills"
        claude.mkdir(parents=True)
        os.symlink(old / "xsos-wbs-pack", claude / "xsos-wbs-pack")
        result = self.run_install()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertFalse(self.clone.exists())
        self.assertEqual((old / "xsos-wbs-author").resolve(), (self.home / ".codex" / "skills" / "xsos-wbs-author").resolve())


if __name__ == "__main__":
    unittest.main()
