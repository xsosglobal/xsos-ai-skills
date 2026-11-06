"""XSOS 插件清单（Codex 与 Claude Code 共用一套 skill 与 MCP 地址）。对应插件验收 B1–B4。"""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MCP_URL = "https://platform.szsyforging.com/api/v1/discussion/mcp"
SKILLS = sorted(p.parent.name for p in ROOT.glob("*/SKILL.md"))


def load(rel):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


class PluginManifestTest(unittest.TestCase):
    def test_plugin_manifest_codex(self):
        """B1 Codex：仓库即插件源，装「XSOS」带上全部 skill 与 MCP 地址，安装时登录。"""
        market = load(".agents/plugins/marketplace.json")
        entry = next(p for p in market["plugins"] if p["name"] == "xsos")
        self.assertEqual(entry["source"], {"source": "local", "path": "./"})
        self.assertEqual(entry["policy"]["authentication"], "ON_INSTALL")
        plugin = load(".codex-plugin/plugin.json")
        self.assertEqual(plugin["name"], "xsos")
        self.assertRegex(plugin["version"], r"^\d+\.\d+\.\d+$")
        self.assertEqual(plugin["interface"]["displayName"], "XSOS")
        skills_root = (ROOT / plugin["skills"]).resolve()
        self.assertEqual(sorted(p.parent.name for p in skills_root.glob("*/SKILL.md")), SKILLS)
        self.assertIn("xsos-package-plan", SKILLS)
        mcp = load(plugin["mcpServers"])
        self.assertEqual(mcp["mcpServers"]["xsos"], {"type": "http", "url": MCP_URL})

    def test_plugin_manifest_claude(self):
        """B2 Claude Code：同名插件、同一套 skill、同一个 MCP 地址；版本与 Codex 清单一致。"""
        market = load(".claude-plugin/marketplace.json")
        self.assertEqual(market["name"], "xsos")
        self.assertTrue(market["owner"]["name"])
        self.assertEqual([p["source"] for p in market["plugins"] if p["name"] == "xsos"], ["./"])
        plugin = load(".claude-plugin/plugin.json")
        self.assertEqual(plugin["name"], "xsos")
        self.assertEqual(plugin["version"], load(".codex-plugin/plugin.json")["version"])
        self.assertEqual(sorted(Path(p).name for p in plugin["skills"]), SKILLS, "新增 skill 要同时登记进 .claude-plugin/plugin.json")
        for p in plugin["skills"]:
            self.assertTrue((ROOT / p / "SKILL.md").is_file(), p)
        self.assertEqual(load(plugin["mcpServers"])["mcpServers"]["xsos"]["url"], MCP_URL)

    def test_skill_doc_mcp_steps(self):
        """B3 立包 skill：提交方案、我的任务、更新进度走 MCP 工具；开工落包仍是本机脚本；没登录时告诉用户怎么登录、不绕过。"""
        doc = (ROOT / "xsos-package-plan" / "SKILL.md").read_text(encoding="utf-8")
        for tool in ("whoami", "submit_plan", "my_tasks", "update_progress", "get_progress"):
            self.assertIn(f"`{tool}`", doc)
        self.assertIn("start_package.py", doc)
        self.assertIn("codex mcp login xsos", doc)
        self.assertIn("/mcp", doc)
        self.assertRegex(doc, r"用户说提交再调 `submit_plan`")
        self.assertRegex(doc, r"不要编")
        for status in ("todo", "in_progress", "review", "done", "blocked"):
            self.assertIn(status, doc)
        front = re.match(r"---\n(.*?)\n---", doc, re.S).group(1)
        self.assertIn("update_progress", front, "description 要能触发「更新进度」")

    def test_readme_install_steps(self):
        """B4 README：Codex 桌面版、Codex 命令行、Claude Code 三种安装与登录步骤。"""
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        section = readme.split("## 作为插件安装", 1)[1].split("\n## ", 1)[0]
        for line in ("codex plugin marketplace add xsosglobal/xsos-ai-skills", "codex plugin add xsos@xsos", "codex mcp login xsos",
                     "/plugin marketplace add xsosglobal/xsos-ai-skills", "/plugin install xsos@xsos", "浏览所有插件", "/mcp"):
            self.assertIn(line, section)
        self.assertIn(MCP_URL, section)


if __name__ == "__main__":
    unittest.main()
