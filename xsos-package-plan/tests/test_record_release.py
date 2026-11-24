"""发布登记脚本（record_release.py）的测试——对应基线 S9。用本地假的需求讨论接口。"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import importlib.util
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "record_release.py"
_spec = importlib.util.spec_from_file_location("record_release", SCRIPT)
record_release = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(record_release)


class Fake(BaseHTTPRequestHandler):
    posts, latest, status = [], {}, 200

    def log_message(self, *a):
        pass

    def reply(self, code, value):
        data = json.dumps(value).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if Fake.status != 200:
            return self.reply(Fake.status, {"error": "down"})
        v = Fake.latest.get("version")
        self.reply(200, {"items": [{"version": v}] if v else []})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Fake.posts.append({"auth": self.headers.get("Authorization"), **body})
        self.reply(Fake.status, {"ok": True})


def sh(cwd, *args):
    return subprocess.run(list(args), cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class RecordReleaseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}/api/v1/discussion"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        Fake.posts, Fake.latest, Fake.status = [], {}, 200
        self.repo = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.repo, True)
        sh(self.repo, "git", "init", "-q", "-b", "develop")
        sh(self.repo, "git", "config", "user.name", "t")
        sh(self.repo, "git", "config", "user.email", "t@t")
        sh(self.repo, "git", "remote", "add", "origin", "git@github.com:xsosglobal/xsos-admin.git")
        (self.repo / "docs" / "wbs").mkdir(parents=True)
        (self.repo / "docs" / "wbs" / "02-wbs.md").write_text("| wp_id | t |\n|---|---|\n| WP-BE-001 | a |\n| WP-BE-002 | b |\n")
        self.commit("init")
        self.base = sh(self.repo, "git", "rev-parse", "HEAD")

    def commit(self, msg):
        (self.repo / "f").write_text(msg)
        sh(self.repo, "git", "add", ".")
        sh(self.repo, "git", "commit", "-qm", msg)

    def run_(self, *args, key="k"):
        env = {**os.environ, "XSOS_RELEASE_KEY": key} if key else {k: v for k, v in os.environ.items() if k != "XSOS_RELEASE_KEY"}
        p = subprocess.run([sys.executable, str(SCRIPT), "--repo-dir", str(self.repo), "--url", self.url, *args],
                           capture_output=True, text=True, env=env)
        return p.returncode, p.stdout, p.stderr

    def test_packages_since_last_release(self):
        """按上次登记的版本算差：尾注和 feat(WP-…) 标题都认，别的提交里提到的包号不算。"""
        Fake.latest = {"version": self.base}
        self.commit("feat(WP-BE-211): 发布登记\n\nWork-Package: WP-BE-211")
        self.commit("fix: 修一下\n\n前端部分归 WP-FE-263\n\nWork-Package: WP-BE-209")
        code, out, err = self.run_("--env", "test")
        self.assertEqual(code, 0, err)
        post = Fake.posts[-1]
        self.assertEqual(post["packages"], ["WP-BE-209", "WP-BE-211"])
        self.assertEqual(post["environment"], "test")
        self.assertEqual(post["repo"], "xsos-admin")
        self.assertEqual(post["version"], sh(self.repo, "git", "rev-parse", "HEAD"))
        self.assertEqual(post["auth"], "Bearer k")

    def test_first_release_counts_all_packages(self):
        """第一次登记：按这个版本 02-wbs 里已有的包算。"""
        code, out, err = self.run_("--env", "production")
        self.assertEqual(code, 0, err)
        self.assertEqual(Fake.posts[-1]["packages"], ["WP-BE-001", "WP-BE-002"])

    def test_failure_only_warns(self):
        """登记失败只告警、退出码 0；--strict 才失败。没有密钥也只告警。"""
        Fake.status = 503
        code, out, err = self.run_("--env", "test")
        self.assertEqual(code, 0)
        self.assertIn("不影响发布", err)
        code, *_ = self.run_("--env", "test", "--strict")
        self.assertEqual(code, 1)
        Fake.status = 200
        code, out, err = self.run_("--env", "test", key="")
        self.assertEqual(code, 0)
        self.assertIn("没有发布登记密钥", err)
        self.assertEqual(Fake.posts, [])

    def test_dry_run_does_not_post(self):
        Fake.latest = {"version": self.base}
        self.commit("x\n\nWork-Package: WP-BE-300")
        code, out, err = self.run_("--env", "test", "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["packages"], ["WP-BE-300"])
        self.assertEqual(Fake.posts, [])

    def test_rollback_records_version_only(self):
        """上次登记的版本不在这次的历史里（回滚），不猜包，只登记版本。"""
        self.commit("later\n\nWork-Package: WP-BE-400")
        Fake.latest = {"version": sh(self.repo, "git", "rev-parse", "HEAD")}
        code, out, err = self.run_("--env", "production", "--version", self.base)
        self.assertEqual(code, 0, err)
        self.assertEqual(Fake.posts[-1]["packages"], [])
        self.assertIn("回滚", json.loads(out)["note"])

    def test_merge_pr_subjects_from_release_branch(self):
        """发布分支 cherry-pick -m 1 过来的合并提交：标题是 Merge pull request，包号只在分支名里。"""
        Fake.latest = {"version": self.base}
        sh(self.repo, "git", "checkout", "-qb", "feature/WP-BE-349-device-admin-enroller")
        self.commit("实现设备管理员录入")
        sh(self.repo, "git", "checkout", "-q", "develop")
        sh(self.repo, "git", "merge", "-q", "--no-ff", "feature/WP-BE-349-device-admin-enroller", "-m",
           "Merge pull request #683 from xsosglobal/feature/WP-BE-349-device-admin-enroller")
        merge = sh(self.repo, "git", "rev-parse", "HEAD")
        sh(self.repo, "git", "checkout", "-qb", "master", self.base)
        sh(self.repo, "git", "cherry-pick", "-m", "1", merge)
        self.assertEqual(sh(self.repo, "git", "log", "-1", "--format=%s"),
                         "Merge pull request #683 from xsosglobal/feature/WP-BE-349-device-admin-enroller")
        self.commit("Merge pull request #685 from xsosglobal/release/WP-BE-348-349-face-enroll")
        self.commit("Merge pull request #12 from xsosglobal/chore/sync-develop-main")
        self.commit("release(WP-BE-350,WP-FE-120): 模板说明")
        code, out, err = self.run_("--env", "production")
        self.assertEqual(code, 0, err)
        self.assertEqual(Fake.posts[-1]["packages"], ["WP-BE-348", "WP-BE-349", "WP-BE-350", "WP-FE-120"])


class PackagesInSubjectTest(unittest.TestCase):
    """标题解析：只认类型前缀括号和合并 PR 标题里的分支名，其余标题和正文提到的包号都不算。"""

    def check(self, subject, expected):
        self.assertEqual(sorted(record_release.packages_in_subject(subject)), expected, subject)

    def test_existing_type_prefix_unchanged(self):
        self.check("feat(WP-BE-211): 发布登记", ["WP-BE-211"])
        self.check("fix(WP-FE-263) 修一下", ["WP-FE-263"])
        self.check("fix: 修一下 WP-BE-209", [])
        self.check("feat(portal): 提到 WP-BE-209", [])
        self.check("feat(WP-BE-211-x): 不是整段包号", [])

    def test_type_prefix_with_several_ids(self):
        self.check("release(WP-BE-348,WP-BE-349): 人脸录入", ["WP-BE-348", "WP-BE-349"])
        self.check("docs(WP-BE-348,WP-BE-349,WP-BE-350): 更新说明", ["WP-BE-348", "WP-BE-349", "WP-BE-350"])
        self.check("docs(WP-BE-348, WP-FE-120): 带空格", ["WP-BE-348", "WP-FE-120"])

    def test_merge_pr_feature_branch(self):
        self.check("Merge pull request #683 from xsosglobal/feature/WP-BE-349-device-admin-enroller", ["WP-BE-349"])
        self.check("Merge pull request #692 from xsosglobal/release/WP-BE-350-template-help", ["WP-BE-350"])
        self.check("Merge pull request #671 from xsosglobal/release/1123-WP-BE-336-continuous-print", ["WP-BE-336"])

    def test_merge_pr_release_branch_compressed_numbers(self):
        self.check("Merge pull request #685 from xsosglobal/release/WP-BE-348-349-face-enroll", ["WP-BE-348", "WP-BE-349"])
        self.check("Merge pull request #1 from o/release/WP-BE-348-349-350", ["WP-BE-348", "WP-BE-349", "WP-BE-350"])
        self.check("Merge pull request #1 from o/release/WP-BE-348-WP-FE-120-x", ["WP-BE-348", "WP-FE-120"])

    def test_compressed_numbers_stop_at_words(self):
        """压缩写法只吃完整的 3～5 位数字段：-2fa、-349x、6 位数字、单词都不当包号。"""
        self.check("Merge pull request #1 from o/feature/WP-BE-348-2fa-login", ["WP-BE-348"])
        self.check("Merge pull request #1 from o/feature/WP-BE-348-349x", ["WP-BE-348"])
        self.check("Merge pull request #1 from o/feature/WP-BE-348-123456", ["WP-BE-348"])
        self.check("Merge pull request #1 from o/feature/WP-BE-348-v2-12", ["WP-BE-348"])

    def test_merge_pr_without_package_is_empty(self):
        self.check("Merge pull request #12 from xsosglobal/chore/sync-develop-main", [])
        self.check("Merge pull request #13 from xsosglobal/develop", [])
        self.check("Merge branch 'feature/WP-BE-349-x' into develop", [])


if __name__ == "__main__":
    unittest.main()
