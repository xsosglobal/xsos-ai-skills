"""方案缺项检查（plan_check.py）与仓库中文名（repo_names.py）——对应基线 S1、S8。"""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


plan_check, repo_names = load("plan_check"), load("repo_names")

FULL = {"title": "回写", "project": "xsos-admin", "layer": "backend", "ownerId": "lu",
        "baseline": {"scenario": "s", "nonGoals": "n", "items": [{"text": "a", "test": "T"}]}}


class PlanCheckTest(unittest.TestCase):
    def test_wording_matches_discussion(self):
        """说法与需求讨论后端 planMissing 逐字一致（完整任务不报，缺的逐项说清）。"""
        bad = {"title": "x", "layer": "middle", "baseline": {"items": [{"text": "a"}]}}
        self.assertEqual(plan_check.missing([FULL, bad]), [
            "任务 2的项目", "任务 2的前端/后端", "任务 2的责任人", "任务 2的场景",
            "任务 2的第 1 条验收的测试", "任务 2的不做什么"])
        self.assertEqual(plan_check.missing([FULL]), [])
        no_items = {**FULL, "baseline": {**FULL["baseline"], "items": []}}
        self.assertEqual(plan_check.missing([no_items]), ["任务 1的验收条目"])
        self.assertEqual(plan_check.missing([]), ["至少一个任务"])

    def test_cli(self):
        p = subprocess.run([sys.executable, str(SCRIPTS / "plan_check.py")], input=json.dumps({"tasks": [FULL]}),
                           capture_output=True, text=True)
        self.assertEqual(json.loads(p.stdout), {"ok": True, "missing": []})
        p = subprocess.run([sys.executable, str(SCRIPTS / "plan_check.py")], input="not json", capture_output=True, text=True)
        self.assertEqual(p.returncode, 2)


# 本机 ~/work/gitee 下有远端的仓库（GitHub 仓库名，2026-10-23 盘点）；新增仓库时把它加进名称表和这里。
KNOWN = ["xsos-admin", "web", "xsos-platform-portal", "xsos-platform-core", "xsos-auth-center", "xsos-platform-registry",
         "xsos-iot-agent", "iot-gateway", "xsos-masterdata", "xsos-customer-master", "xsos-gallery", "xsos-todo-center",
         "xsos-notification-center", "xsos-mtr", "xsos-discussion", "dsh-delivery", "xsos-ai-skills",
         "xsos-delivery-control", "xsos-wbs", "xsos-business-context", "xsos-ai-workbench", "xsos-ai-eval-suite",
         "xsos-xiaoyuan-runtime", "xsos-admin-doc", "xsos-openapi", "xsos-platform-sdk", "xsos-web-frontend-kit",
         "req-bot", "laowuniupi"]


class RepoNamesTest(unittest.TestCase):
    def test_covers_all_repos(self):
        """S8：每个有远端的仓库都有中文名和一句话用途；别名不冲突。"""
        table = repo_names.load()
        for repo in KNOWN:
            self.assertIn(repo, table, repo)
            self.assertTrue(table[repo]["name"] and table[repo]["about"], repo)
        data = json.loads(repo_names.TABLE.read_text(encoding="utf-8"))
        keys = [k for repo, info in data["repos"].items() for k in [repo, *info.get("aliases", [])]]
        self.assertEqual(len(keys), len(set(keys)))

    def test_display_and_fallback(self):
        self.assertEqual(repo_names.lookup("xsos_admin")["display"], "业务后端 · xsos_admin")
        self.assertEqual(repo_names.lookup("dsh-delivery")["display"], "玄枢 · dsh-delivery")
        self.assertEqual(repo_names.lookup("nope")["display"], "nope")


if __name__ == "__main__":
    unittest.main()
