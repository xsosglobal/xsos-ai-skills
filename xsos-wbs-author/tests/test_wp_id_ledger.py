"""本机号段账:取号当刻排他,跨 worktree 可见。

背景是 2026-10-07 的真实事故:同一个仓库的两个 worktree 各自取到 WP-BE-163。
两边扫本地 pack、扫 origin/develop、扫远端分支都"看起来没占用"——因为对方那条
占号行还没提交,而 pack 是每个 worktree 一份的工作树副本,未提交的内容对彼此
完全不可见。远端扫描只能看见已推送的行,挡住的是"挂着的 PR 占号"。

所以这里用**真的 git worktree**来测:两个 worktree、同一个仓库、同一次取号,
不共享任何已提交内容,这正是出事时的形态。
"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

TESTS_DIR = Path(__file__).resolve().parent
SCRIPT = TESTS_DIR.parent / "scripts" / "add_work_package.py"

SPEC = {
    "title_cn": "试块申请行删除",
    "title_en": "Test block request line deletion",
    "type": "backend",
    "owner": "顾昊",
    "scope": "只允许删未投产的申请行",
    "non_goals": "不删申请单抬头",
    "requirements": ["未投产的申请行允许删除。"],
    "acceptance": ["未投产行能删，已投产行被拒绝。"],
}


def load_module():
    spec = importlib.util.spec_from_file_location("add_work_package_ledger", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_module()


def make_pack(root: Path, rows=("WP-BE-001",)):
    """最小可写 pack:validator 要求完整结构,缺一个文件就整包 INVALID。"""
    root.mkdir(parents=True, exist_ok=True)
    header = "| wp_id | title_cn | title_en | type | owner | status | depends_on | scope | non_goals | acceptance_ref | outputs |"
    sep = "|---|---|---|---|---|---|---|---|---|---|---|"
    body = [f"| {wp} | 旧包 | Old | backend | 顾昊 | done | none | s | n | AC-{wp[3:]} | o |" for wp in rows]
    (root / "02-wbs.md").write_text("# WBS\n\n" + "\n".join([header, sep] + body) + "\n", encoding="utf-8")
    (root / "01-requirements.md").write_text(
        "# 需求 / Requirements\n\n" + "".join(f"## {wp} 旧包\n\n- 旧需求。\n\n" for wp in rows), encoding="utf-8")
    (root / "06-acceptance.md").write_text(
        "# 验收 / Acceptance\n\n" + "".join(f"## AC-{wp[3:]} 旧包\n\n- 旧验收。\n\n" for wp in rows),
        encoding="utf-8")
    (root / "07-risks.md").write_text("# 风险 / Risks\n\n", encoding="utf-8")
    (root / "CHANGELOG.md").write_text("# CHANGELOG\n\n", encoding="utf-8")
    for name, heading in [
        ("00-brief.md", "# 概述 / Brief\n\n## Goal / 项目目标\n\n- 让测试跑起来。\n\n## Non-goals / 非目标\n\n- 别的都不管。"),
        ("03-page-spec.md", "# 页面 / Page Spec"),
        ("04-api-contract.md", "# 接口 / API Contract"),
        ("05-data-contract.md", "# 数据 / Data Contract"),
        ("08-implementation-rules.md", "# 实现约定 / Implementation Rules"),
        ("10-handoff.md", "# 交接 / Handoff"),
        ("OWNERS.md", "# OWNERS"),
    ]:
        (root / name).write_text(heading + "\n\n", encoding="utf-8")
    return root


class LedgerFixture(unittest.TestCase):
    """一个真 git 仓库 + 若干 worktree,所有 worktree 共用一份号段账。"""

    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix="wp-id-ledger-"))
        self.addCleanup(shutil.rmtree, self.temp, ignore_errors=True)
        self.repo = self.temp / "repo"
        make_pack(self.repo / "docs" / "wbs")
        self.git("init", "-q", "-b", "main", cwd=self.repo)
        self.git("config", "user.email", "test@example.com", cwd=self.repo)
        self.git("config", "user.name", "test", cwd=self.repo)
        self.git("add", "-A", cwd=self.repo)
        self.git("commit", "-q", "-m", "init", cwd=self.repo)
        self.ledger = self.temp / "wp-id-ledger.jsonl"

    def git(self, *args, cwd=None):
        return subprocess.run(["git", "-C", str(cwd or self.repo), *args],
                              capture_output=True, text=True, check=True)

    def worktree(self, name: str) -> Path:
        path = self.temp / name
        self.git("worktree", "add", "-q", "-b", f"wt-{name}", str(path))
        return path

    def run_tool(self, pack: Path, *extra, spec=None, env_extra=None):
        env = {**os.environ, "XSOS_WP_ID_LEDGER": str(self.ledger)}
        env.update(env_extra or {})
        return subprocess.run(
            [sys.executable, str(SCRIPT), str(pack), "--spec", "-", *extra],
            input=json.dumps(spec or SPEC, ensure_ascii=False),
            capture_output=True, text=True, env=env)

    def allocated(self, pack: Path, *extra, **kwargs) -> str:
        result = self.run_tool(pack, *extra, **kwargs)
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        prefix = "[dry-run] WP-" if "--dry-run" in extra else "已写入 WP-"
        for line in result.stdout.splitlines():
            if line.startswith(prefix):
                return line.split()[1].rstrip(":")
        self.fail(f"输出里没找到编号:\n{result.stdout}\n{result.stderr}")


class LedgerBehaviourTest(LedgerFixture):
    def test_second_worktree_skips_id_held_by_an_uncommitted_draft(self):
        """对方只改了工作树、没提交——旧机制看不见,账本必须看见。"""
        first = self.worktree("wt1")
        self.assertEqual(self.allocated(first / "docs" / "wbs"), "WP-BE-002")
        second = self.worktree("wt2")
        # wt2 的 pack 里只有 WP-BE-001(看不到 wt1 那份未提交的 WP-BE-002)
        self.assertNotIn("WP-BE-002", (second / "docs" / "wbs" / "02-wbs.md").read_text(encoding="utf-8"))
        self.assertEqual(self.allocated(second / "docs" / "wbs", "--dry-run"), "WP-BE-003")

    def test_draft_and_commit_in_the_same_worktree_keep_the_same_id(self):
        """草稿→落盘是两次调用,各取一次号;自己占的号不能被自己顶掉。"""
        tree = self.worktree("solo")
        pack = tree / "docs" / "wbs"
        self.assertEqual(self.allocated(pack, "--dry-run"), "WP-BE-002")
        self.assertEqual(self.allocated(pack), "WP-BE-002")

    def test_explicit_id_held_by_another_worktree_is_rejected(self):
        first = self.worktree("holder")
        self.allocated(first / "docs" / "wbs")
        second = self.worktree("taker")
        result = self.run_tool(second / "docs" / "wbs", "--dry-run", spec={**SPEC, "wp_id": "WP-BE-002"})
        self.assertEqual(result.returncode, 2, msg=result.stdout + result.stderr)
        self.assertIn("占着", result.stderr)
        self.assertIn("holder", result.stderr)

    def test_row_gone_frees_the_id(self):
        """改号、废弃、回滚之后,旧号得自己空出来,不能永久锁死。"""
        first = self.worktree("wt1")
        pack = first / "docs" / "wbs"
        self.assertEqual(self.allocated(pack), "WP-BE-002")
        text = (pack / "02-wbs.md").read_text(encoding="utf-8")
        kept = [line for line in text.splitlines() if "| WP-BE-002 |" not in line]
        (pack / "02-wbs.md").write_text("\n".join(kept) + "\n", encoding="utf-8")
        self.assertNotIn("WP-BE-002", (pack / "02-wbs.md").read_text(encoding="utf-8"))
        second = self.worktree("wt2")
        self.assertEqual(self.allocated(second / "docs" / "wbs", "--dry-run"), "WP-BE-002")

    def test_reservation_expires_so_an_abandoned_draft_cannot_lock_a_number(self):
        stale = {
            "at": "2020-01-01T00:00:00+08:00", "repo": MODULE.repo_key(self.repo / "docs" / "wbs"),
            "series": "WP-BE", "wp_id": "WP-BE-002", "state": "reserved",
            "pack": str(self.temp / "gone" / "02-wbs.md"), "worktree": str(self.temp / "gone"),
            "branch": "gone", "owner": "顾昊",
        }
        self.ledger.write_text(json.dumps(stale, ensure_ascii=False) + "\n", encoding="utf-8")
        tree = self.worktree("fresh")
        self.assertEqual(self.allocated(tree / "docs" / "wbs", "--dry-run"), "WP-BE-002")

    def test_release_id_frees_a_number_for_a_human(self):
        first = self.worktree("wt1")
        self.allocated(first / "docs" / "wbs")
        second = self.worktree("wt2")
        pack = second / "docs" / "wbs"
        released = self.run_tool(pack, "--release-id", "WP-BE-002", spec=None)
        self.assertEqual(released.returncode, 0, msg=released.stdout + released.stderr)
        self.assertEqual(self.allocated(pack, "--dry-run"), "WP-BE-002")

    def test_list_ids_shows_who_holds_what(self):
        first = self.worktree("wt1")
        self.allocated(first / "docs" / "wbs")
        listed = self.run_tool(self.repo / "docs" / "wbs", "--list-ids", spec=None)
        self.assertEqual(listed.returncode, 0, msg=listed.stdout + listed.stderr)
        self.assertIn("WP-BE-002", listed.stdout)
        self.assertIn("wt1", listed.stdout)

    def test_concurrent_worktrees_never_share_a_number(self):
        """真并发:4 个 worktree 同时取号,谁都不许拿到同一个号。"""
        trees = [self.worktree(f"par{i}") for i in range(4)]
        env = {**os.environ, "XSOS_WP_ID_LEDGER": str(self.ledger)}
        processes = [
            subprocess.Popen(
                [sys.executable, str(SCRIPT), str(tree / "docs" / "wbs"), "--spec", "-", "--dry-run"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
            for tree in trees
        ]
        ids = []
        for process in processes:
            out, err = process.communicate(json.dumps(SPEC, ensure_ascii=False))
            self.assertEqual(process.returncode, 0, msg=out + err)
            ids.append(next(line.split()[1] for line in out.splitlines() if line.startswith("[dry-run] WP-")))
        self.assertEqual(len(set(ids)), len(ids), msg=f"并发取号撞号: {ids}")

    def test_no_ledger_outside_a_git_repo_keeps_the_old_behaviour(self):
        """pack 不在 git 仓库里时退化成原来的文件快照取号,并明确告警。"""
        pack = make_pack(self.temp / "plain" / "wbs")
        result = self.run_tool(pack, "--dry-run")
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("取不到仓库键", result.stderr)
        self.assertFalse(self.ledger.exists())

    def test_no_id_ledger_flag_skips_the_ledger_entirely(self):
        tree = self.worktree("wt1")
        result = self.run_tool(tree / "docs" / "wbs", "--dry-run", "--no-id-ledger")
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertFalse(self.ledger.exists())

    def test_default_ledger_lives_in_the_shared_git_common_dir(self):
        """默认位置是 common dir:同一个 clone 的所有 worktree 共用一份,写不进去就等于没排他。"""
        tree = self.worktree("wt1")
        result = self.run_tool(tree / "docs" / "wbs", "--dry-run",
                               env_extra={"XSOS_WP_ID_LEDGER": ""})
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertTrue((self.repo / ".git" / "xsos-wp-id-ledger.jsonl").exists())
        self.assertIn("WP-BE-002", (self.repo / ".git" / "xsos-wp-id-ledger.jsonl").read_text(encoding="utf-8"))

    def test_unusable_ledger_path_degrades_instead_of_blocking(self):
        """账本写不进去时只告警:排他是增强,不能变成取号的门禁。"""
        blocker = self.temp / "blocker"
        blocker.write_text("not a directory\n", encoding="utf-8")
        tree = self.worktree("wt1")
        result = self.run_tool(tree / "docs" / "wbs", "--dry-run",
                               env_extra={"XSOS_WP_ID_LEDGER": str(blocker / "led.jsonl")})
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("没有跨 worktree 排他", result.stderr)
        self.assertIn("WP-BE-002", result.stdout)


class LedgerUnitTest(unittest.TestCase):
    def test_next_wp_id_skips_numbers_held_elsewhere(self):
        text = "| WP-BE-001 | x |\n"
        self.assertEqual(MODULE.next_wp_id(text, "BE"), "WP-BE-002")
        self.assertEqual(MODULE.next_wp_id(text, "BE", "", [2, 3]), "WP-BE-004")

    def test_corrupt_ledger_lines_never_block_allocation(self):
        with tempfile.TemporaryDirectory() as raw:
            pack = make_pack(Path(raw) / "wbs")
            ledger_path = Path(raw) / "ledger.jsonl"
            ledger_path.write_text("不是 json\n{\"wp_id\": \"WP-BE-002\", \"repo\": \"other\"}\n\n", encoding="utf-8")
            ledger = MODULE.IdLedger(pack, SPEC, ledger_path)
            self.assertEqual(ledger.held(), {})
            self.assertEqual(ledger.held_numbers("BE"), [])

    def test_records_are_append_only_and_last_state_wins(self):
        with tempfile.TemporaryDirectory() as raw:
            pack = make_pack(Path(raw) / "wbs")
            ledger_path = Path(raw) / "ledger.jsonl"
            ledger = MODULE.IdLedger(pack, SPEC, ledger_path)
            ledger.repo = "/tmp/some-repo/.git"
            ledger.worktree = str(pack)
            ledger.reserve("WP-BE-002", "BE")
            self.assertIn("WP-BE-002", ledger.held())
            ledger.release("WP-BE-002")
            self.assertNotIn("WP-BE-002", ledger.held())
            self.assertEqual(len(ledger_path.read_text(encoding="utf-8").strip().splitlines()), 2)


if __name__ == "__main__":
    unittest.main()
