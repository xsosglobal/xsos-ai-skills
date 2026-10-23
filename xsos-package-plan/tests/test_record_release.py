"""发布登记脚本（record_release.py）的测试——对应基线 S9。用本地假的需求讨论接口。"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "record_release.py"


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


if __name__ == "__main__":
    unittest.main()
