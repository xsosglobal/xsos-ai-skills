import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "add_work_package.py"


def load():
    spec = importlib.util.spec_from_file_location("add_work_package", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MINIMAL_SPEC = {
    "title_cn": "采购对账差异表",
    "title_en": "Purchase reconciliation diff",
    "type": "backend",
    "owner": "顾昊",
    "scope": "录入发票原值并与采购单逐行比对",
    "non_goals": "不改 Web",
    "requirements": ["发票金额必须录入原值，不得由系统反算。"],
    "acceptance": ["差异表能列出金额不一致的行项。"],
}

V2_SPEC = {
    **MINIMAL_SPEC,
    "requirement_en": "Invoice amounts must use the supplied source value.",
    "acceptance_en": ["The diff table lists every line whose amount differs."],
    "artifact_applicability": {
        "page": {"applicability": "not_applicable", "reason": "Backend-only change."},
        "api": {"applicability": "required", "reason": "The query API changes."},
        "data": {"applicability": "not_applicable", "reason": "No schema change."},
    },
    "source_refs": [{
        "source_type": "chat",
        "source_ref": "chat://2026-09-01/purchase-reconciliation",
        "captured_at": "2026-09-01",
        "note": "用户本轮原始需求",
    }],
    "delivery_target": "production",
    "delivery_counted": "yes",
    "changelog": "登记原始需求并生成待审批工作包。",
    "date": "2026-09-01",
}


def make_pack(root: Path, rows=("WP-BE-001",)):
    root.mkdir(parents=True, exist_ok=True)
    header = "| wp_id | title_cn | title_en | type | owner | status | depends_on | scope | non_goals | acceptance_ref | outputs |"
    sep = "|---|---|---|---|---|---|---|---|---|---|---|"
    body = [
        f"| {wp} | 旧包 | Old | backend | 顾昊 | done | none | s | n | AC-{wp[3:]} | o |"
        for wp in rows
    ]
    (root / "02-wbs.md").write_text("# WBS\n\n" + "\n".join([header, sep] + body) + "\n", encoding="utf-8")
    (root / "01-requirements.md").write_text(
        "# 需求 / Requirements\n\n" + "".join(f"## {wp} 旧包\n\n- 旧需求。\n\n" for wp in rows),
        encoding="utf-8")
    (root / "06-acceptance.md").write_text(
        "# 验收 / Acceptance\n\n" + "".join(f"## AC-{wp[3:]} 旧包\n\n- 旧验收。\n\n" for wp in rows),
        encoding="utf-8")
    (root / "07-risks.md").write_text("# 风险 / Risks\n\n", encoding="utf-8")
    (root / "CHANGELOG.md").write_text("# CHANGELOG\n\n", encoding="utf-8")
    # validator 要求完整结构，缺一个文件就整包 INVALID
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


def make_v2_pack(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    (root / "00-brief.md").write_text("""# V2 Brief

## Goal

Turn raw requirements into controlled delivery proposals.

## Non-goals

Do not approve baselines automatically.

## Project Control / 项目控制

| field | value |
|---|---|
| wbs_schema | 2 |
| project_id | TEST-AUTHOR |
| project_status | planning |
| product_owner | 顾昊 |
| current_baseline | none |
| planned_start | TBD |
| planned_finish | TBD |
| forecast_finish | TBD |
| actual_start | none |
| actual_finish | none |
""", encoding="utf-8")
    (root / "01-requirements.md").write_text("""# Requirements

## Source Register / 来源登记

| source_id | source_type | source_ref | captured_at | note |
|---|---|---|---|---|
| SRC-001 | file | docs/input.md | 2026-08-31 | initial |

## Requirement Register / 需求登记

| req_id | version | requirement_cn | requirement_en | priority | owner | status | baseline_ref | change_ref | acceptance_refs | source_refs | approved_at | supersedes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| REQ-001 | v1 | 保持旧需求可追溯 | Keep existing traceability | P1 | 顾昊 | draft | none | none | AC-BE-001 | SRC-001 | none | none |

## REQ-001@v1: Existing requirement

- Keep the existing proposal traceable.
""", encoding="utf-8")
    # Deliberately put wp_id away from column 1 to prove schema v2 is header-driven.
    (root / "02-wbs.md").write_text("""# WBS

| title_cn | status | wp_id | title_en | type | owner | depends_on | requirement_refs | scope | non_goals | acceptance_ref | outputs | delivery_target | delivery_counted | baseline_ref | planned_start | planned_finish | forecast_finish | actual_start | actual_finish | change_ref | run_ref | release_ref |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 旧包 | proposed | WP-BE-001 | Existing | backend | 顾昊 | none | REQ-001@v1 | Existing scope | none | AC-BE-001 | docs | review | no | none | TBD | TBD | TBD | none | none | none | none | none |

## Artifact Readiness Register / 交付物就绪度

| wp_id | artifact | applicability | readiness | owner | refs | reason | change_ref |
|---|---|---|---|---|---|---|---|
| WP-BE-001 | requirement | required | draft | 顾昊 | REQ-001@v1 | Existing draft | none |
| WP-BE-001 | page | not_applicable | not_applicable | 顾昊 | none | Backend only | none |
| WP-BE-001 | api | required | not_started | 顾昊 | none | API pending | none |
| WP-BE-001 | data | not_applicable | not_applicable | 顾昊 | none | No data change | none |
| WP-BE-001 | acceptance | required | draft | 顾昊 | AC-BE-001 | Acceptance drafted | none |
| WP-BE-001 | risk | required | ready | 顾昊 | none | Assessed | none |
| WP-BE-001 | handoff | required | not_started | 顾昊 | none | Not started | none |
""", encoding="utf-8")
    (root / "06-acceptance.md").write_text(
        """# Acceptance

## AC-BE-001 Existing

Requirement refs:
- `REQ-001@v1`
Baseline:
- `none`
Acceptance owner:
- `顾昊`
Delivery target:
- `review`
中文：
- 既有验收可观察。
English:
- Existing acceptance is observable.
Verification:
- Check the existing proposal.
Required evidence:
- Verification output.
Decision:
- `pending`
""",
        encoding="utf-8",
    )
    for name, body in {
        "03-page-spec.md": "# Page Spec\n\n| page_id | status | route | owner | requirement_refs | acceptance_refs | purpose_cn | purpose_en | states | change_ref |\n|---|---|---|---|---|---|---|---|---|---|\n",
        "04-api-contract.md": "# API Contract\n\n| api_id | status | method | path | provider | consumer | auth | requirement_refs | acceptance_refs | request | response | errors | change_ref |\n|---|---|---|---|---|---|---|---|---|---|---|---|\n\n| mock_id | status | api_id | scenario | fixture |\n|---|---|---|---|---|\n",
        "05-data-contract.md": "# Data Contract\n\n| model_id | status | source_of_truth | owner | requirement_refs | acceptance_refs | fields | change_ref |\n|---|---|---|---|---|---|---|---|\n\n| machine_id | status | entity | states | transitions | change_ref |\n|---|---|---|---|---|---|\n",
        "07-risks.md": "# Risks\n\n| risk_id | risk_cn | risk_en | probability | impact | owner | trigger | response | due_date | related_wp | residual_risk | status | accepted_by |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|\n",
        "08-implementation-rules.md": "# Rules\n\nUse the approved baseline.\n",
        "09-baselines.md": "# Baselines\n\n| baseline_id | version | status | current | approved_by | approved_at | planned_start | planned_finish | forecast_finish | requirement_refs | wp_refs | change_ref | supersedes |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|\n",
        "10-handoff.md": "# AI Runs and Release Evidence\n\n| run_id | wp_id | baseline_ref | status | actual_start | actual_finish | outcome | change_ref | next_action |\n|---|---|---|---|---|---|---|---|---|\n\n| release_id | wp_id | run_ref | baseline_ref | status | verified_at | environment | evidence | verified_by |\n|---|---|---|---|---|---|---|---|---|\n",
        "11-change-requests.md": "# Change Requests\n\n| cr_id | status | requested_at | decided_at | affected_refs | baseline_from | baseline_to | decision | approver |\n|---|---|---|---|---|---|---|---|---|\n",
        "CHANGELOG.md": "# Changelog\n\n",
        "OWNERS.md": "# Owners\n\n| role | name | responsibility |\n|---|---|---|\n| product_owner | 顾昊 | approve baseline |\n",
    }.items():
        (root / name).write_text(body, encoding="utf-8")
    return root


def run(pack: Path, spec: dict, *extra):
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(pack), "--spec", "-", *extra],
        input=json.dumps(spec, ensure_ascii=False), capture_output=True, text=True)


class AddWorkPackageTest(unittest.TestCase):
    def test_allocates_next_id_and_writes_three_files(self):
        with tempfile.TemporaryDirectory() as raw:
            pack = make_pack(Path(raw) / "wbs", rows=("WP-BE-001", "WP-BE-007"))
            result = run(pack, MINIMAL_SPEC)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

            wbs = (pack / "02-wbs.md").read_text(encoding="utf-8")
            self.assertIn("| WP-BE-008 |", wbs)
            self.assertIn("AC-BE-008", wbs)
            self.assertIn("## WP-BE-008 采购对账差异表", (pack / "01-requirements.md").read_text(encoding="utf-8"))
            self.assertIn("## AC-BE-008 采购对账差异表", (pack / "06-acceptance.md").read_text(encoding="utf-8"))

    def test_schema1_renders_the_english_half_when_given(self):
        """acceptance_en 曾经只有 schema 2 的渲染器读，而真实 pack 全是 schema 1。

        于是调用方传了它、拿到退出码 0、却悄悄收到一段只有中文的验收——
        跟它自己的兄弟条目形状都不一样。一个静默不起作用的参数比没有参数更糟。
        """
        with tempfile.TemporaryDirectory() as raw:
            pack = make_pack(Path(raw) / "wbs")
            spec = dict(MINIMAL_SPEC)
            spec["acceptance_en"] = ["First English line.", "Second English line."]
            spec["verification"] = ["Run `go test ./...`."]
            self.assertEqual(0, run(pack, spec).returncode)

            acceptance = (pack / "06-acceptance.md").read_text(encoding="utf-8")
            self.assertIn("中文：", acceptance)
            self.assertIn("English:", acceptance)
            self.assertIn("First English line.", acceptance)
            self.assertIn("Verification:", acceptance)
            self.assertIn("Run `go test ./...`.", acceptance)

    def test_schema1_stays_bare_without_the_english_half(self):
        """没传英文就保持原样：仓库里绝大多数存量条目就是只有中文的裸列表。"""
        with tempfile.TemporaryDirectory() as raw:
            pack = make_pack(Path(raw) / "wbs")
            self.assertEqual(0, run(pack, MINIMAL_SPEC).returncode)
            acceptance = (pack / "06-acceptance.md").read_text(encoding="utf-8")
            self.assertNotIn("中文：", acceptance)
            self.assertNotIn("English:", acceptance)

    def test_new_row_lands_inside_the_table(self):
        """插入不得在表格中间留空行——空行会让 validator 静默跳过后面所有行。"""
        with tempfile.TemporaryDirectory() as raw:
            pack = make_pack(Path(raw) / "wbs")
            self.assertEqual(0, run(pack, MINIMAL_SPEC).returncode)
            lines = (pack / "02-wbs.md").read_text(encoding="utf-8").splitlines()
            start = next(i for i, l in enumerate(lines) if l.startswith("| wp_id"))
            block = []
            for line in lines[start:]:
                if not line.strip():
                    break
                block.append(line)
            self.assertEqual(4, len(block), "表头 + 分隔 + 旧包 + 新包 应连成一片")
            self.assertTrue(block[2].startswith("| WP-BE-002 |"), block)

    def test_rejects_duplicate_wp_id(self):
        with tempfile.TemporaryDirectory() as raw:
            pack = make_pack(Path(raw) / "wbs")
            spec = dict(MINIMAL_SPEC, wp_id="WP-BE-001")
            result = run(pack, spec)
            self.assertEqual(2, result.returncode)
            self.assertIn("已存在", result.stderr)

    def test_rejects_pipe_in_field(self):
        with tempfile.TemporaryDirectory() as raw:
            pack = make_pack(Path(raw) / "wbs")
            spec = dict(MINIMAL_SPEC, scope="a | b")
            result = run(pack, spec)
            self.assertEqual(2, result.returncode)
            self.assertIn("表格切断", result.stderr)

    def test_rejects_dangling_dependency(self):
        with tempfile.TemporaryDirectory() as raw:
            pack = make_pack(Path(raw) / "wbs")
            spec = dict(MINIMAL_SPEC, depends_on=["WP-BE-999"])
            result = run(pack, spec)
            self.assertEqual(2, result.returncode)
            self.assertIn("悬空", result.stderr)

    def test_rejects_bad_status(self):
        with tempfile.TemporaryDirectory() as raw:
            pack = make_pack(Path(raw) / "wbs")
            result = run(pack, dict(MINIMAL_SPEC, status="doing"))
            self.assertEqual(2, result.returncode)

    def test_missing_requirements_is_refused(self):
        with tempfile.TemporaryDirectory() as raw:
            pack = make_pack(Path(raw) / "wbs")
            spec = {k: v for k, v in MINIMAL_SPEC.items() if k != "requirements"}
            result = run(pack, spec)
            self.assertEqual(2, result.returncode)
            self.assertIn("requirements", result.stderr)

    def test_risks_and_changelog_are_optional_but_wired(self):
        with tempfile.TemporaryDirectory() as raw:
            pack = make_pack(Path(raw) / "wbs")
            spec = dict(MINIMAL_SPEC,
                        risks=[{"title": "发票口径未确认", "body": "供应商开票方式未知。"}],
                        changelog="新增采购对账差异表。", date="2026-08-27")
            self.assertEqual(0, run(pack, spec).returncode)
            self.assertIn("RISK-BE-002-001", (pack / "07-risks.md").read_text(encoding="utf-8"))
            log = (pack / "CHANGELOG.md").read_text(encoding="utf-8")
            self.assertIn("## 2026-08-27", log)
            self.assertIn("`WP-BE-002`", log)

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as raw:
            pack = make_pack(Path(raw) / "wbs")
            before = (pack / "02-wbs.md").read_text(encoding="utf-8")
            result = run(pack, MINIMAL_SPEC, "--dry-run")
            self.assertEqual(0, result.returncode)
            self.assertEqual(before, (pack / "02-wbs.md").read_text(encoding="utf-8"))
            self.assertIn("(candidate)", result.stdout)
            self.assertIn("OK:", result.stdout)

    def test_next_wp_id_skips_gaps_and_never_reuses(self):
        module = load()
        text = "| WP-BE-001 |\n| WP-BE-004 |\n"
        self.assertEqual("WP-BE-005", module.next_wp_id(text, "BE"))
        self.assertEqual("WP-FS-001", module.next_wp_id(text, "FS"))

    def test_next_wp_id_takes_union_with_integration_branch(self):
        """当前工作树落后时,编号必须按集成分支/远端分支的并集取。

        2026-08-27 连撞两次:一次基于落后 12 个提交的 local 算出已被占用的
        076,一次是 PR 挂着期间 080 被并行会话抢走。只看本地文件必然复现。
        """
        module = load()
        local = "| WP-BE-001 |\n| WP-BE-075 |\n"
        remote = "| WP-BE-076 |\n| WP-BE-080 |\n"
        self.assertEqual("WP-BE-076", module.next_wp_id(local, "BE"))
        self.assertEqual("WP-BE-081", module.next_wp_id(local, "BE", remote))
        # 本地有未推的新包时,并集要把它也算上
        self.assertEqual("WP-BE-091", module.next_wp_id(local + "| WP-BE-090 |\n", "BE", remote))

    def test_v2_is_header_driven_and_stops_at_proposed(self):
        with tempfile.TemporaryDirectory() as raw:
            pack = make_v2_pack(Path(raw) / "wbs")
            result = run(pack, V2_SPEC)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

            wbs = (pack / "02-wbs.md").read_text(encoding="utf-8")
            row = next(line for line in wbs.splitlines() if "WP-BE-002" in line)
            cells = [cell.strip() for cell in row.strip("|").split("|")]
            headers = [
                cell.strip() for cell in
                next(line for line in wbs.splitlines() if "| wp_id |" in line).strip("|").split("|")
            ]
            values = dict(zip(headers, cells))
            self.assertEqual("proposed", values["status"])
            self.assertEqual("REQ-BE-002@v1", values["requirement_refs"])
            self.assertEqual("production", values["delivery_target"])
            self.assertEqual("yes", values["delivery_counted"])
            self.assertEqual("none", values["baseline_ref"])
            self.assertEqual("TBD", values["planned_start"])
            self.assertEqual("none", values["run_ref"])
            self.assertEqual("none", values["release_ref"])

            artifact_rows = [
                line for line in wbs.splitlines() if line.startswith("| WP-BE-002 |")
            ]
            self.assertEqual(7, len(artifact_rows))
            self.assertTrue(any("| api | required | not_started |" in row for row in artifact_rows))
            self.assertTrue(any(
                "| page | not_applicable | not_applicable |" in row
                for row in artifact_rows
            ))

            requirements = (pack / "01-requirements.md").read_text(encoding="utf-8")
            self.assertIn("| SRC-002 | chat | chat://2026-09-01/purchase-reconciliation |", requirements)
            self.assertIn("| REQ-BE-002 | v1 |", requirements)
            self.assertIn("## REQ-BE-002@v1: 采购对账差异表", requirements)
            self.assertIn("English:\n\n- Invoice amounts", requirements)
            self.assertIn("## WP-BE-002 采购对账差异表", requirements)
            self.assertEqual(1, requirements.count("## Source Register / 来源登记"))
            self.assertEqual(1, requirements.count("## Requirement Register / 需求登记"))

            acceptance = (pack / "06-acceptance.md").read_text(encoding="utf-8")
            self.assertIn("Requirement refs:", acceptance)
            self.assertIn("Acceptance owner:", acceptance)
            self.assertIn("Delivery target:\n\n- `production`", acceptance)
            self.assertIn("English:", acceptance)
            self.assertIn("Required evidence:", acceptance)
            self.assertIn("Decision:\n\n- `pending`", acceptance)

            changelog = (pack / "CHANGELOG.md").read_text(encoding="utf-8")
            self.assertIn("- Requirement: `REQ-BE-002@v1`.", changelog)
            self.assertIn("- Baseline / CR: `none` / `none`.", changelog)
            self.assertIn("- Delivery evidence: `pending` (`delivery_target=production`).", changelog)
            self.assertIn("owner baseline approval", changelog)

    def test_v2_writes_managed_risk_row_and_links_artifact(self):
        with tempfile.TemporaryDirectory() as raw:
            pack = make_v2_pack(Path(raw) / "wbs")
            spec = dict(V2_SPEC, risks=[{
                "risk_cn": "上游发票口径仍可能变化",
                "risk_en": "The upstream invoice convention may still change",
                "probability": "medium",
                "impact": "high",
                "trigger": "供应商更改发票金额定义",
                "response": "停止实现并提交 CR 重新基线",
                "due_date": "2026-09-15",
                "residual_risk": "low",
            }])
            result = run(pack, spec)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

            risks = (pack / "07-risks.md").read_text(encoding="utf-8")
            self.assertIn("| RISK-BE-002-001 | 上游发票口径仍可能变化 |", risks)
            self.assertIn("| WP-BE-002 | low | open | none |", risks)
            wbs = (pack / "02-wbs.md").read_text(encoding="utf-8")
            self.assertIn(
                "| WP-BE-002 | risk | required | draft | 顾昊 | RISK-BE-002-001 |",
                wbs,
            )

    def test_v2_reuses_registered_source_and_requirement_without_rewriting(self):
        with tempfile.TemporaryDirectory() as raw:
            pack = make_v2_pack(Path(raw) / "wbs")
            self.assertEqual(0, run(pack, V2_SPEC).returncode)
            spec = {
                key: value for key, value in V2_SPEC.items()
                if key not in {"requirements", "date"}
            }
            spec.update({
                "series": "FS",
                "title_cn": "采购差异导出",
                "title_en": "Purchase diff export",
                "requirement_refs": ["REQ-BE-002@v1"],
                "source_refs": ["SRC-002"],
                "delivery_target": "review",
                "delivery_counted": "no",
                "changelog": "复用既有需求版本新增导出工作包。",
            })
            result = run(pack, spec)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            requirements = (pack / "01-requirements.md").read_text(encoding="utf-8")
            self.assertEqual(1, requirements.count("## REQ-BE-002@v1:"))
            self.assertEqual(1, requirements.count("| REQ-BE-002 | v1 |"))
            self.assertIn("## WP-FS-001 采购差异导出", requirements)

    def test_v2_new_requirement_version_links_immediate_predecessor(self):
        with tempfile.TemporaryDirectory() as raw:
            pack = make_v2_pack(Path(raw) / "wbs")
            spec = dict(
                V2_SPEC,
                series="FS",
                title_cn="既有需求第二版",
                title_en="Existing requirement version two",
                requirement_refs=["REQ-001@v2"],
                source_refs=["SRC-001"],
                requirements=["第二版改变了业务验收语义。"],
            )
            result = run(pack, spec)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            requirements = (pack / "01-requirements.md").read_text(encoding="utf-8")
            row = next(line for line in requirements.splitlines() if "| REQ-001 | v2 |" in line)
            self.assertIn("| REQ-001@v1 |", row)

    def test_v2_requirement_version_cannot_skip_predecessor(self):
        with tempfile.TemporaryDirectory() as raw:
            pack = make_v2_pack(Path(raw) / "wbs")
            result = run(pack, dict(
                V2_SPEC,
                requirement_refs=["REQ-001@v3"],
                source_refs=["SRC-001"],
            ))
            self.assertEqual(2, result.returncode)
            self.assertIn("需求版本不能跳号", result.stderr)

    def test_v2_refuses_todo_and_approval_mutation(self):
        with tempfile.TemporaryDirectory() as raw:
            pack = make_v2_pack(Path(raw) / "wbs")
            todo = run(pack, dict(V2_SPEC, status="todo"))
            self.assertEqual(2, todo.returncode)
            self.assertIn("只能创建 proposed", todo.stderr)

            approval = run(pack, dict(V2_SPEC, baseline_status="approved"))
            self.assertEqual(2, approval.returncode)
            self.assertIn("不能批准 BL 或 CR", approval.stderr)

    def test_v2_review_target_cannot_enter_production_delivery_rate(self):
        with tempfile.TemporaryDirectory() as raw:
            pack = make_v2_pack(Path(raw) / "wbs")
            result = run(pack, dict(
                V2_SPEC,
                delivery_target="review",
                delivery_counted="yes",
            ))
            self.assertEqual(2, result.returncode)
            self.assertIn("只用于生产交付率", result.stderr)

    def test_v2_requires_configured_owner(self):
        with tempfile.TemporaryDirectory() as raw:
            pack = make_v2_pack(Path(raw) / "wbs")
            owners = pack / "OWNERS.md"
            owners.write_text(
                "# Owners\n\n| role | name | responsibility |\n"
                "|---|---|---|\n| product_owner |  | approve |\n",
                encoding="utf-8",
            )
            result = run(pack, V2_SPEC)
            self.assertEqual(2, result.returncode)
            self.assertIn("未在 OWNERS.md 解析到具体人员", result.stderr)

    def test_v2_does_not_touch_baseline_run_release_or_change_records(self):
        with tempfile.TemporaryDirectory() as raw:
            pack = make_v2_pack(Path(raw) / "wbs")
            protected = ["09-baselines.md", "10-handoff.md", "11-change-requests.md"]
            before = {name: (pack / name).read_text(encoding="utf-8") for name in protected}
            result = run(pack, V2_SPEC)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            after = {name: (pack / name).read_text(encoding="utf-8") for name in protected}
            self.assertEqual(before, after)

    def test_schema_marker_must_be_inside_project_control_table(self):
        module = load()
        with tempfile.TemporaryDirectory() as raw:
            pack = make_pack(Path(raw) / "wbs")
            brief = (pack / "00-brief.md").read_text(encoding="utf-8")
            (pack / "00-brief.md").write_text(
                brief + "\nProse only: wbs_schema: 2\n", encoding="utf-8"
            )
            self.assertEqual(1, module.project_schema(pack))


    def test_series_comes_from_type_not_a_fixed_default(self):
        """type=frontend 要拿到 WP-FE-，不是一律 WP-BE-。

        实测:在 xsos-platform-portal（160 个包全是 WP-FE-）建一个 type=frontend 的包，
        旧实现给出 WP-BE-001——编号看着合法、前缀全错，而且不会被任何门禁拦下来。
        """
        module = load()
        self.assertEqual("FE", module.SERIES_BY_TYPE["frontend"])
        self.assertEqual("INTEG", module.SERIES_BY_TYPE["integration"])
        self.assertEqual("BE", module.SERIES_BY_TYPE["backend"])

    def test_added_errors_ignores_pre_existing_ones(self):
        """只看新增的错误。

        「必须全绿」会让这个脚本在任何有存量债的仓库上完全不可用，而存量恰恰是
        最常见的状态——portal 的 develop 上有 82 条，全部早于任何一次使用。
        要求先修完再准建包，这种门禁现实里只会被绕过。
        """
        module = load()
        before = "INVALID\n- 02-wbs.md acceptance reference not found: WP-FE-063 -> AC-FE-063 (line 67)\n"
        after = "INVALID\n- 02-wbs.md acceptance reference not found: WP-FE-063 -> AC-FE-063 (line 68)\n"
        self.assertEqual([], module.added_errors(before, after))

    def test_added_errors_reports_genuinely_new_ones(self):
        module = load()
        before = "INVALID\n- 老错误 (line 1)\n"
        after = "INVALID\n- 老错误 (line 2)\n- 新错误 (line 9)\n"
        self.assertEqual(["新错误"], module.added_errors(before, after))

    def test_added_errors_counts_repeats(self):
        """同一条错误出现两次要算两次，否则重复引入会被吞掉。"""
        module = load()
        self.assertEqual(["X"], module.added_errors("- X (line 1)\n", "- X (line 1)\n- X (line 5)\n"))

if __name__ == "__main__":
    unittest.main()
