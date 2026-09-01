#!/usr/bin/env python3
"""WBS 进度看板生成器 —— 只读 docs/wbs，输出自包含 HTML。

用法: python3 render_wbs_board.py <pack-dir> [输出.html]
数据源就是 WBS Pack 本身，不引入任何新数据。
"""
import re, sys, json
from pathlib import Path
from collections import Counter, defaultdict
from datetime import date, datetime

PACK = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/wbs").resolve()
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else PACK / "board.html")

FACT_FILES = {
    "requirements": "01-requirements.md",
    "page_spec":    "03-page-spec.md",
    "api":          "04-api-contract.md",
    "data":         "05-data-contract.md",
    "acceptance":   "06-acceptance.md",
    "risks":        "07-risks.md",
    "handoff":      "10-handoff.md",
}
STATUS_ORDER = ["proposed", "todo", "in_progress", "blocked", "review", "done", "cancelled"]
WP_ID_RE = re.compile(r"^WP-(?:[A-Z0-9]+-)+\d{3}$")
ARTIFACT_KEYS = ["requirement", "page", "api", "data", "acceptance", "risk", "handoff"]
ARTIFACT_TO_FACT = {
    "requirement": "requirements",
    "page": "page_spec",
    "api": "api",
    "data": "data",
    "acceptance": "acceptance",
    "risk": "risks",
    "handoff": "handoff",
}


def split_row(line):
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def parse_tables(path):
    """Return every contiguous Markdown table as (headers, rows)."""
    if not path.is_file():
        return []
    tables, current = [], []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("|"):
            current.append(line)
        elif current:
            tables.append(current)
            current = []
    if current:
        tables.append(current)

    parsed = []
    for table in tables:
        if len(table) < 2:
            continue
        headers = [cell.lower() for cell in split_row(table[0])]
        rows = []
        for line in table[2:]:
            cells = split_row(line)
            rows.append({
                header: cells[index] if index < len(cells) else ""
                for index, header in enumerate(headers)
            })
        parsed.append((headers, rows))
    return parsed


def find_table(path, id_header, *, without=()):
    for headers, rows in parse_tables(path):
        if id_header in headers and not any(header in headers for header in without):
            return headers, rows
    return [], []


def split_refs(value):
    value = (value or "").strip().strip("`")
    if value.lower() in {"", "none", "n/a", "-", "tbd"}:
        return []
    return [
        token.strip().strip("`")
        for token in re.split(r"\s*(?:,|;|<br\s*/?>)\s*", value, flags=re.I)
        if token.strip().strip("`")
    ]


def clean_cell(value):
    return (value or "").strip().strip("`").strip()


def is_none(value):
    return clean_cell(value).lower() in {"", "none", "tbd", "n/a", "-"}


def parse_iso_temporal(value):
    value = clean_cell(value)
    if is_none(value):
        return None
    try:
        if "T" in value:
            return datetime.fromisoformat(value)
        parsed = date.fromisoformat(value)
        return parsed if parsed.isoformat() == value else None
    except ValueError:
        return None


def same_temporal_value(left, right):
    """Match validator semantics: date and datetime may match by local date."""
    left_value = parse_iso_temporal(left)
    right_value = parse_iso_temporal(right)
    if left_value is None or right_value is None:
        return False
    if isinstance(left_value, datetime) and isinstance(right_value, datetime):
        return left_value == right_value
    left_date = left_value.date() if isinstance(left_value, datetime) else left_value
    right_date = right_value.date() if isinstance(right_value, datetime) else right_value
    return left_date == right_date


def temporal_is_after(left, right):
    """Match validator ordering across ISO dates and offset-aware datetimes."""
    left_value = parse_iso_temporal(left)
    right_value = parse_iso_temporal(right)
    if left_value is None or right_value is None:
        return False
    if isinstance(left_value, datetime) and isinstance(right_value, datetime):
        try:
            return left_value > right_value
        except TypeError:
            return False
    left_date = left_value.date() if isinstance(left_value, datetime) else left_value
    right_date = right_value.date() if isinstance(right_value, datetime) else right_value
    return left_date > right_date


def inherited_file(name):
    """Use pack-local control file, then the nearest parent (initiative inheritance)."""
    local = PACK / name
    if local.is_file():
        return local
    for parent in PACK.parents:
        candidate = parent / name
        if candidate.is_file():
            return candidate
    return local


def has_stable_evidence_locator(value):
    """Require evidence that can be located or replayed, not descriptive prose."""
    evidence = clean_cell(value)
    if is_none(evidence) or len(evidence) < 8:
        return False
    if re.search(r"\b[A-Za-z][A-Za-z0-9+.-]*://\S+", evidence):
        return True
    if re.search(
        r"(?<![A-Za-z0-9])(?:"
        r"/[^\s,;]+|\.\.?/[^\s,;]+|[A-Za-z]:[\\/][^\s,;]+|"
        r"(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+\.[A-Za-z][A-Za-z0-9]{0,15}|"
        r"[A-Za-z0-9_.-]+\.[A-Za-z][A-Za-z0-9]{0,15}"
        r")(?![A-Za-z0-9])",
        evidence,
    ):
        return True
    for commit in re.findall(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{7,40}(?![0-9A-Fa-f])", evidence):
        # A decimal sequence is an issue/build number, not a commit locator.
        if any(char.lower() in "abcdef" for char in commit):
            return True
    if re.search(
        r"\b(?:EVIDENCE|EVD|BUILD|DEPLOY|RELEASE|CI|JOB|ARTIFACT)[_:#-][A-Za-z0-9][A-Za-z0-9._:-]*\b",
        evidence,
        flags=re.IGNORECASE,
    ):
        return True
    if re.search(r"\b(?:command|cmd):\s*\S.{1,}", evidence, flags=re.IGNORECASE):
        return True
    return False


def schema_version():
    for headers, rows in parse_tables(PACK / "00-brief.md"):
        if {"field", "value"}.issubset(headers):
            control = {row.get("field", "").strip().lower(): row.get("value", "").strip() for row in rows}
            if control.get("wbs_schema") == "2":
                return 2
        if "wbs_schema" in headers and rows and rows[0].get("wbs_schema", "").strip() == "2":
            return 2
    return 1

def sections(fname, prefix="WP"):
    p = PACK / fname
    if not p.is_file():
        return set()
    pat = rf"^##\s+({prefix}-(?:[A-Z0-9]+-)+\d{{3}})"
    return {m.group(1) for m in re.finditer(pat, p.read_text(encoding="utf-8"), re.M)}

# ── 解析 02-wbs.md 表格 ────────────────────────────────────────────────
schema = schema_version()
wbs, headers = {}, []
headers, rows = find_table(PACK / "02-wbs.md", "wp_id", without=("artifact",))
for row in rows:
    wp_id = row.get("wp_id", "").strip().strip("`")
    if not WP_ID_RE.fullmatch(wp_id):
        continue
    wbs[wp_id] = dict(
        id=wp_id, title=row.get("title_cn", ""), title_en=row.get("title_en", ""),
        type=row.get("type", ""), owner=row.get("owner", ""),
        status=row.get("status", ""), depends=split_refs(row.get("depends_on", "")),
        requirement_refs=split_refs(row.get("requirement_refs", "")),
        scope=row.get("scope", ""), non_goals=row.get("non_goals", ""),
        acceptance_ref=row.get("acceptance_ref", ""), outputs=row.get("outputs", ""),
        delivery_target=row.get("delivery_target", ""),
        delivery_counted=row.get("delivery_counted", "").lower(),
        baseline_refs=split_refs(row.get("baseline_ref", "")),
        run_refs=split_refs(row.get("run_ref", "")),
        release_refs=split_refs(row.get("release_ref", "")),
        actual_finish=row.get("actual_finish", ""),
    )

ids = set(wbs)
cov_sets = {}
if schema == 2:
    _, artifact_rows = find_table(PACK / "02-wbs.md", "artifact")
    artifact_register = defaultdict(dict)
    for row in artifact_rows:
        wp_id = row.get("wp_id", "").strip().strip("`")
        artifact = row.get("artifact", "").strip().lower()
        if wp_id in ids and artifact in ARTIFACT_KEYS and artifact not in artifact_register[wp_id]:
            artifact_register[wp_id][artifact] = {
                "applicability": row.get("applicability", "").strip().lower(),
                "readiness": row.get("readiness", "").strip().lower(),
                "owner": row.get("owner", ""),
                "refs": row.get("refs", ""),
                "reason": row.get("reason", ""),
                "change_ref": row.get("change_ref", ""),
            }
    for wid, w in wbs.items():
        w["artifacts"] = {
            artifact: artifact_register[wid].get(artifact, {
                "applicability": "missing", "readiness": "missing", "owner": "",
                "refs": "", "reason": "Missing Artifact Readiness row", "change_ref": "",
            })
            for artifact in ARTIFACT_KEYS
        }
        w["cov"] = {
            # V2 requirement traceability comes from stable REQ-*@vN refs, not headings.
            ARTIFACT_TO_FACT[artifact]: (
                artifact == "requirement" and bool(w["requirement_refs"])
            ) or w["artifacts"][artifact]["readiness"] not in {"", "missing", "not_started", "draft", "change_pending"}
            for artifact in ARTIFACT_KEYS
        }
        w["cov_n"] = sum(w["cov"].values())
    cov_sets = {
        fact: {wid for wid, w in wbs.items() if w["cov"].get(fact)}
        for fact in FACT_FILES
    }
    artifact_mode = "v2_register"
else:
    cov_sets = {k: sections(f) for k, f in FACT_FILES.items() if k != "acceptance"}
    cov_sets["acceptance"] = {a.replace("AC-", "WP-") for a in sections("06-acceptance.md", "AC")}
    for wid, w in wbs.items():
        w["cov"] = {k: (wid in s) for k, s in cov_sets.items()}
        w["cov_n"] = sum(w["cov"].values())
        w["artifacts"] = {
            artifact: {
                "applicability": "legacy",
                "readiness": "present" if w["cov"].get(ARTIFACT_TO_FACT[artifact]) else "missing",
                "owner": "", "refs": "", "reason": "V1 heading-based fallback", "change_ref": "",
            }
            for artifact in ARTIFACT_KEYS
        }
    artifact_mode = "v1_fallback"

# ── 当前批准基线 + 经验证生产 REL ──────────────────────────────────────
_, baseline_rows = find_table(PACK / "09-baselines.md", "baseline_id")
current_rows = [
    row for row in baseline_rows
    if clean_cell(row.get("status", "")).lower() == "approved"
    and clean_cell(row.get("current", "")).lower() == "yes"
]
current_baseline = clean_cell(current_rows[0].get("baseline_id", "")) if len(current_rows) == 1 else ""
baseline_wp_ids = set(split_refs(current_rows[0].get("wp_refs", ""))) if current_baseline else set()
baseline_statuses = {
    clean_cell(row.get("baseline_id", "")): clean_cell(row.get("status", "")).lower()
    for row in baseline_rows if clean_cell(row.get("baseline_id", ""))
}
denominator_ids = {
    wp_id for wp_id in baseline_wp_ids
    if wp_id in wbs and clean_cell(wbs[wp_id]["status"]).lower() != "cancelled"
    and clean_cell(wbs[wp_id]["delivery_counted"]).lower() == "yes"
}
_, release_rows = find_table(PACK / "10-handoff.md", "release_id")
_, run_rows = find_table(PACK / "10-handoff.md", "run_id")
run_by_id = {
    clean_cell(row.get("run_id", "")): row
    for row in run_rows if clean_cell(row.get("run_id", ""))
}
release_by_id = {
    clean_cell(row.get("release_id", "")): row
    for row in release_rows if clean_cell(row.get("release_id", ""))
}

_, owner_rows = find_table(inherited_file("OWNERS.md"), "role")
configured_roles = {}
for row in owner_rows:
    role = clean_cell(row.get("role", ""))
    name = clean_cell(row.get("name", ""))
    if role and not is_none(name) and name.lower() != "owner":
        configured_roles[role] = name


def resolves_acceptance_owner(value):
    actor = clean_cell(value)
    configured_name = configured_roles.get("acceptance_owner", "")
    return bool(configured_name) and actor in {"acceptance_owner", configured_name}


def has_verified_production_delivery(wp_id):
    """Mirror the validator's production RUN/REL evidence gate for the KPI."""
    wp = wbs[wp_id]
    if clean_cell(wp["status"]).lower() != "done":
        return False
    if clean_cell(wp["delivery_target"]).lower() != "production":
        return False
    if not (
        len(wp["baseline_refs"]) == 1
        and len(wp["run_refs"]) == 1
        and len(wp["release_refs"]) == 1
    ):
        return False

    baseline_ref = wp["baseline_refs"][0]
    run_ref = wp["run_refs"][0]
    release_ref = wp["release_refs"][0]
    if baseline_statuses.get(baseline_ref) not in {"approved", "superseded"}:
        return False

    release = release_by_id.get(release_ref)
    run = run_by_id.get(run_ref)
    if release is None or run is None:
        return False
    if clean_cell(release.get("wp_id", "")) != wp_id:
        return False
    if split_refs(release.get("run_ref", "")) != [run_ref]:
        return False
    if split_refs(release.get("baseline_ref", "")) != [baseline_ref]:
        return False
    if clean_cell(release.get("status", "")).lower() != "verified":
        return False
    if clean_cell(release.get("environment", "")).lower() != "production":
        return False
    evidence = clean_cell(release.get("evidence", ""))
    if not has_stable_evidence_locator(evidence):
        return False
    if not resolves_acceptance_owner(release.get("verified_by", "")):
        return False

    if clean_cell(run.get("wp_id", "")) != wp_id:
        return False
    if clean_cell(run.get("baseline_ref", "")) != baseline_ref:
        return False
    if clean_cell(run.get("status", "")).lower() != "closed":
        return False
    if clean_cell(run.get("outcome", "")).lower() != "completed":
        return False
    run_start = run.get("actual_start", "")
    run_finish = run.get("actual_finish", "")
    if parse_iso_temporal(run_start) is None or parse_iso_temporal(run_finish) is None:
        return False
    if temporal_is_after(run_start, run_finish):
        return False
    if not same_temporal_value(wp["actual_finish"], run_finish):
        return False

    verified_at = release.get("verified_at", "")
    if parse_iso_temporal(verified_at) is None:
        return False
    if temporal_is_after(run_finish, verified_at):
        return False
    return True


delivered_ids = set()
for wp_id in denominator_ids:
    if has_verified_production_delivery(wp_id):
        delivered_ids.add(wp_id)

# ── 反向依赖 + 阻塞分析 ────────────────────────────────────────────────
blocks = defaultdict(list)
for w in wbs.values():
    for d in w["depends"]:
        if d in ids:
            blocks[d].append(w["id"])
for wid, w in wbs.items():
    w["blocks"] = blocks.get(wid, [])
    w["blocked_by"] = [d for d in w["depends"]
                       if d in ids and wbs[d]["status"] not in ("done", "cancelled")]

data = dict(
    generated=datetime.now().strftime("%Y-%m-%d %H:%M"),
    pack=str(PACK),
    schema_version=schema,
    artifact_mode=artifact_mode,
    wbs=[wbs[i] for i in sorted(ids)],
    fact_files=FACT_FILES,
    status_order=STATUS_ORDER,
    delivery=dict(
        current_baseline=current_baseline or "none",
        numerator=len(delivered_ids),
        denominator=len(denominator_ids),
        rate=(round(len(delivered_ids) * 100 / len(denominator_ids), 1)
              if denominator_ids else None),
        delivered_wp_ids=sorted(delivered_ids),
        denominator_wp_ids=sorted(denominator_ids),
    ),
    stats=dict(
        total=len(ids),
        by_status=dict(Counter(w["status"] for w in wbs.values())),
        by_owner=dict(Counter(w["owner"] for w in wbs.values())),
        by_type=dict(Counter(w["type"] for w in wbs.values())),
        coverage={k: len(ids & s) for k, s in cov_sets.items()},
        blocked=sum(1 for w in wbs.values() if w["blocked_by"]),
    ),
)
print(f"解析: {len(ids)} 个工作包")
for k, n in data["stats"]["coverage"].items():
    print(f"  {k:14} {n:3}/{len(ids)}  {n*100//max(len(ids),1):3}%")


TPL = r"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>WBS 需求管理看板</title><style>
:root{--bg:#fbfbfc;--fg:#15171c;--mut:#6b7280;--line:#e3e6ea;--card:#fff;--acc:#2563eb;
--ok:#059669;--warn:#d97706;--bad:#dc2626;--prog:#7c3aed;--todo:#0891b2;--gray:#9ca3af}
@media(prefers-color-scheme:dark){:root{--bg:#0e1014;--fg:#e6e8ec;--mut:#8b929c;--line:#242830;--card:#15181e;
--acc:#5b93f7;--ok:#34d399;--warn:#fbbf24;--bad:#f87171;--prog:#a78bfa;--todo:#22d3ee;--gray:#6b7280}}
:root[data-theme=dark]{--bg:#0e1014;--fg:#e6e8ec;--mut:#8b929c;--line:#242830;--card:#15181e;
--acc:#5b93f7;--ok:#34d399;--warn:#fbbf24;--bad:#f87171;--prog:#a78bfa;--todo:#22d3ee;--gray:#6b7280}
:root[data-theme=light]{--bg:#fbfbfc;--fg:#15171c;--mut:#6b7280;--line:#e3e6ea;--card:#fff;--acc:#2563eb;
--ok:#059669;--warn:#d97706;--bad:#dc2626;--prog:#7c3aed;--todo:#0891b2;--gray:#9ca3af}
*{box-sizing:border-box}body{margin:0;padding:0 16px 60px;background:var(--bg);color:var(--fg);
font:14px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
.w{max-width:1400px;margin:0 auto;padding-top:20px}h1{font-size:1.5rem;margin:0 0 4px}
h2{font-size:1.05rem;margin:34px 0 12px;padding-top:16px;border-top:1px solid var(--line);scroll-margin-top:58px}
.sub{color:var(--mut);font-size:.85rem;margin:0 0 18px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:8px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:9px;padding:12px 14px}
.kpi b{display:block;font-size:1.6rem;line-height:1.15}.kpi span{color:var(--mut);font-size:.78rem}
.kpi.bad b{color:var(--bad)}.kpi.warn b{color:var(--warn)}.kpi.ok b{color:var(--ok)}
.note{background:var(--card);border-left:3px solid var(--bad);padding:11px 15px;border-radius:0 8px 8px 0;margin:14px 0;font-size:.88rem}
.layers{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px;margin:14px 0}
.layer{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 12px}
.layer b{display:block}.layer span{color:var(--mut);font-size:.78rem}
table{width:100%;border-collapse:collapse;font-size:.82rem}
th,td{text-align:left;padding:5px 8px;border-bottom:1px solid var(--line);white-space:nowrap}
th{color:var(--mut);font-weight:600;font-size:.76rem;position:sticky;top:0;background:var(--bg);z-index:2}
.scroll{overflow:auto;max-height:560px;border:1px solid var(--line);border-radius:8px}
code{font-family:ui-monospace,Menlo,monospace;font-size:.9em}
.y{color:var(--ok);font-weight:700}.n{color:var(--bad);opacity:.55}
.bar{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0}
.bar button{background:var(--card);color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:4px 11px;font-size:.8rem;cursor:pointer}
.bar button.on{background:var(--acc);color:#fff;border-color:var(--acc)}
.cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(215px,1fr));gap:12px;align-items:start}
.col{background:var(--card);border:1px solid var(--line);border-radius:9px;padding:10px}
.col>h3{margin:0 0 9px;font-size:.85rem;display:flex;justify-content:space-between;align-items:center}
.col>h3 em{font-style:normal;color:var(--mut);font-weight:400}
.c{background:var(--bg);border:1px solid var(--line);border-left:3px solid var(--s);border-radius:6px;
padding:8px 10px;margin-bottom:7px;font-size:.79rem}
.c b{display:block;font-size:.83rem;margin-bottom:2px}
.c .id{color:var(--mut);font-family:ui-monospace,Menlo,monospace;font-size:.74rem}
.c .m{color:var(--mut);font-size:.72rem;margin-top:4px;display:flex;gap:7px;flex-wrap:wrap}
.dot{display:inline-block;width:7px;height:7px;border-radius:2px;margin-right:1px}
.rd{font-size:.72rem;padding:2px 5px;border-radius:5px;background:var(--line);color:var(--mut)}
.rd.verified,.rd.ready,.rd.present{color:var(--ok)}.rd.draft,.rd.not_started,.rd.change_pending{color:var(--warn)}
.rd.missing{color:var(--bad)}.rd.not_applicable,.rd.superseded{color:var(--mut)}
.blk{color:var(--bad);font-weight:600}
footer{margin-top:36px;padding-top:14px;border-top:1px solid var(--line);color:var(--mut);font-size:.78rem}
#nav{position:sticky;top:0;z-index:20;background:var(--bg);border-bottom:1px solid var(--line);margin:0 -16px}
.nw{max-width:1400px;margin:0 auto;padding:8px 16px;display:flex;gap:4px;align-items:center;flex-wrap:wrap}
#nav a{color:var(--mut);text-decoration:none;font-size:.83rem;padding:5px 12px;border-radius:6px;white-space:nowrap}
#nav a:hover{background:var(--card);color:var(--fg)}
#nav a.on{background:var(--acc);color:#fff}
#nav a .n{color:inherit;opacity:.6;font-size:.76rem;margin-left:4px;font-weight:400}
.sp{flex:1 1 auto}
#tg{background:var(--card);border:1px solid var(--line);color:var(--fg);
border-radius:7px;padding:5px 11px;font-size:.8rem;cursor:pointer}
</style></head><body>
<nav id="nav"><div class="nw">
<a href="#s-top" data-s="s-top">概览</a>
<a href="#s-cov" data-s="s-cov">Artifact 就绪度</a>
<a href="#s-board" data-s="s-board">WP 执行状态<span class="n" id="nBoard"></span></a>
<a href="#s-blk" data-s="s-blk">阻塞<span class="n" id="nBlk"></span></a>
<span class="sp"></span><button id="tg">TH</button>
</div></nav>
<div class="w">
<h1 id="s-top">WBS 需求管理看板</h1><p class="sub" id="sub"></p>
<div class="kpis" id="kpis"></div>
<div class="layers"><div class="layer"><b>1. Artifact 就绪度</b><span>需求、页面、接口、数据、验收、风险、交接是否适用及准备到哪一步。</span></div><div class="layer"><b>2. WP status</b><span>工作包处于提议、待办、执行、阻塞、待审或完成；它不等于生产发布。</span></div><div class="layer"><b>3. 生产 REL</b><span>只有当前批准基线内、计入交付且有 verified production REL 的 WP 才计入生产交付。</span></div></div>
<div class="note" id="gapNote"></div>
<h2 id="s-cov">Artifact 就绪度矩阵</h2>
<div class="bar" id="covBar"></div>
<div class="scroll"><table id="tCov"></table></div>
<h2 id="s-board">WP 执行状态看板</h2>
<div class="bar" id="ownerBar"></div>
<div class="cols" id="board"></div>
<h2 id="s-blk">被阻塞的工作包</h2><div class="scroll"><table id="tBlk"></table></div>
<footer id="ft"></footer></div>
<script id="D" type="application/json">__DATA__</script>
<script>
const D=JSON.parse(document.getElementById("D").textContent), E=i=>document.getElementById(i),
esc=s=>String(s==null?"":s).replace(/[&<>]/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[m])), S=D.stats, T=S.total;
const FL=D.fact_files, FK=Object.keys(FL);
const CN={requirements:"需求",page_spec:"页面",api:"接口",data:"数据",acceptance:"验收",risks:"风险",handoff:"交接"};
const F2A={requirements:"requirement",page_spec:"page",api:"api",data:"data",acceptance:"acceptance",risks:"risk",handoff:"handoff"};
const RN={not_applicable:"不适用",not_started:"未开始",draft:"草稿",ready:"就绪",verified:"已验证",change_pending:"变更中",superseded:"已替代",present:"有",missing:"缺失"};
const SC={proposed:"--gray",todo:"--todo",in_progress:"--prog",blocked:"--bad",review:"--warn",done:"--ok",cancelled:"--gray"};
const SN={proposed:"已提出",todo:"待办",in_progress:"进行中",blocked:"阻塞",review:"待审",done:"已完成",cancelled:"已取消"};
function art(w,k){return w.artifacts[F2A[k]]||{applicability:"missing",readiness:"missing"};}
function artGood(a){return a.readiness==="ready"||a.readiness==="verified"||a.readiness==="not_applicable"||a.readiness==="present";}
E("sub").textContent=D.pack+" 生成于 "+D.generated+" · schema v"+D.schema_version+" · 数据源仅为 WBS Pack";
const req=S.coverage.requirements, gap=T-req;
const deliveryValue=D.delivery.rate==null?"N/A":D.delivery.rate+"%";
const reqGapLabel=D.schema_version===2?"缺需求版本引用":"缺需求条目";
E("kpis").innerHTML=[["",T,"工作包总数"],["bad",gap,reqGapLabel],["warn",S.by_status.review||0,"WP 状态：待审"],
["",S.by_status.in_progress||0,"WP 状态：进行中"],["",S.by_status.done||0,"WP 状态：done（非生产口径）"],
[D.delivery.rate===100?"ok":"warn",deliveryValue,"生产交付率 "+D.delivery.numerator+"/"+D.delivery.denominator],
["warn",S.blocked,"被依赖阻塞"]]
.map(function(a){return "<div class=\"kpi "+a[0]+"\"><b>"+a[1]+"</b><span>"+a[2]+"</span></div>";}).join("");
E("gapNote").innerHTML=D.schema_version===2
?"本看板按三套独立事实展示：<b>Artifact Readiness Register</b> 说明七类交付物是否适用及就绪状态；<b>WP status</b> 说明执行阶段；<b>生产交付率</b> 只认当前批准基线 <code>"+esc(D.delivery.current_baseline)+"</code> 内 <code>delivery_counted=yes</code> 且有 verified production REL 的工作包。三者不能互相冒充。"
:"当前是 <b>v1 兼容模式</b>：七类覆盖仍按各事实文件的 WP/AC 标题推断；v1 没有受控基线与 REL，因此生产交付率显示 N/A。";
var covFilter=null;
function covRows(){return D.wbs.filter(function(w){return !covFilter||!artGood(art(w,covFilter));}).map(function(w){
return "<tr><td><code>"+esc(w.id)+"</code></td><td style=\"white-space:normal\">"+esc(w.title)+"</td><td><span style=\"color:var("
+(SC[w.status]||"--gray")+")\">"+(SN[w.status]||esc(w.status))+"</span></td>"
+FK.map(function(k){var a=art(w,k),tip=[a.applicability,a.owner,a.refs,a.reason].filter(Boolean).join(" · ");return "<td style=\"text-align:center\" title=\""+esc(tip)+"\"><span class=\"rd "+esc(a.readiness)+"\">"+(RN[a.readiness]||esc(a.readiness))+"</span></td>";}).join("")
+"<td class=\"n\" style=\"text-align:right\">"+FK.filter(function(k){return artGood(art(w,k));}).length+"/"+FK.length+"</td></tr>";}).join("");}
function drawCov(){E("tCov").innerHTML="<thead><tr><th>wp_id</th><th>标题</th><th>状态</th>"
+FK.map(function(k){return "<th style=\"text-align:center\">"+CN[k]+"</th>";}).join("")
+"<th style=\"text-align:right\">就绪/不适用</th></tr></thead><tbody>"+covRows()+"</tbody>";}
E("covBar").innerHTML="<button class=\"on\" data-f=\"\">全部 "+T+"</button>"
+FK.map(function(k){var n=D.wbs.filter(function(w){return !artGood(art(w,k));}).length;return "<button data-f=\""+k+"\">未就绪"+CN[k]+" "+n+"</button>";}).join("");
E("covBar").onclick=function(e){if(e.target.tagName!=="BUTTON")return;
Array.prototype.forEach.call(E("covBar").children,function(b){b.classList.remove("on");});
e.target.classList.add("on");covFilter=e.target.dataset.f||null;drawCov();};
drawCov();
var ownerFilter=null;
function drawBoard(){E("board").innerHTML=D.status_order.filter(function(s){return S.by_status[s];}).map(function(s){
var list=D.wbs.filter(function(w){return w.status===s&&(!ownerFilter||w.owner===ownerFilter);});
var cards=list.map(function(w){return "<div class=\"c\" style=\"--s:var("+SC[s]+")\" title=\""+esc(w.scope).slice(0,300)+"\"><b>"
+esc(w.title)+"</b><span class=\"id\">"+esc(w.id)+" "+esc(w.type)+"</span><div class=\"m\"><span>"
+FK.map(function(k){var a=art(w,k);return "<i class=\"dot\" style=\"background:var("+(artGood(a)?"--ok":"--line")+")\" title=\""+CN[k]+"："+(RN[a.readiness]||a.readiness)+"\"></i>";}).join("")
+"</span>"+(w.blocked_by.length?"<span class=\"blk\">被 "+w.blocked_by.length+" 个阻塞</span>":"")
+(w.blocks.length?"<span>阻塞 "+w.blocks.length+" 个</span>":"")+"</div></div>";}).join("")
||"<div style=\"color:var(--mut);font-size:.78rem\">--</div>";
return "<div class=\"col\"><h3><span style=\"color:var("+SC[s]+")\">"+(SN[s]||s)+"</span><em>"+list.length+"</em></h3>"+cards+"</div>";}).join("");}
E("ownerBar").innerHTML="<button class=\"on\" data-o=\"\">全部负责人</button>"
+Object.keys(S.by_owner).sort(function(a,b){return S.by_owner[b]-S.by_owner[a];})
.map(function(o){return "<button data-o=\""+esc(o)+"\">"+esc(o)+" "+S.by_owner[o]+"</button>";}).join("");
E("ownerBar").onclick=function(e){if(e.target.tagName!=="BUTTON")return;
Array.prototype.forEach.call(E("ownerBar").children,function(b){b.classList.remove("on");});
e.target.classList.add("on");ownerFilter=e.target.dataset.o||null;drawBoard();};
drawBoard();
var blk=D.wbs.filter(function(w){return w.blocked_by.length;}).sort(function(a,b){return b.blocked_by.length-a.blocked_by.length;});
E("tBlk").innerHTML="<thead><tr><th>wp_id</th><th>标题</th><th>状态</th><th>被这些未完成包阻塞</th></tr></thead><tbody>"
+(blk.map(function(w){return "<tr><td><code>"+esc(w.id)+"</code></td><td style=\"white-space:normal\">"+esc(w.title)
+"</td><td style=\"color:var("+SC[w.status]+")\">"+(SN[w.status]||esc(w.status))+"</td><td><code>"
+w.blocked_by.map(esc).join("</code> <code>")+"</code></td></tr>";}).join("")
||"<tr><td colspan=\"4\" style=\"color:var(--mut)\">无</td></tr>")+"</tbody>";
E("ft").textContent="本页由 xsos-wbs-pack/scripts/render_wbs_board.py 从 "+D.pack+" 直接生成，自包含无外部依赖。修改 Artifact、WP status、基线或 REL 后均需重跑刷新。";
var r=document.documentElement;
E("tg").onclick=function(){var c=r.getAttribute("data-theme")||(matchMedia("(prefers-color-scheme:dark)").matches?"dark":"light");
r.setAttribute("data-theme",c==="dark"?"light":"dark");};

/* 导航:计数 + 滚动高亮当前板块。
   不用 IntersectionObserver —— 板块高度差得多(进度看板很长、阻塞表很短),
   observer 的 threshold 在这种情况下会来回抖。直接按"最后一个越过吸顶线的
   标题"判定,行为可预测。 */
E("nBoard").textContent=D.wbs.length;
if(blk.length)E("nBlk").textContent=blk.length;
var links=Array.prototype.slice.call(document.querySelectorAll("#nav a"));
var anchors=links.map(function(a){return E(a.dataset.s);});
function spy(){
  var line=E("nav").offsetHeight+12,cur=0;
  for(var i=0;i<anchors.length;i++){if(anchors[i]&&anchors[i].getBoundingClientRect().top<=line)cur=i;}
  /* 滚到底时始终点亮最后一项:最后一个板块可能矮到永远越不过判定线 */
  if(window.innerHeight+window.scrollY>=document.body.scrollHeight-4)cur=links.length-1;
  links.forEach(function(a,i){a.classList.toggle("on",i===cur);});
}
addEventListener("scroll",spy,{passive:true});addEventListener("resize",spy);spy();
</script></body></html>"""

OUT.write_text(TPL.replace("__DATA__", json.dumps(data, ensure_ascii=False)), encoding="utf-8")
print("\n看板已生成: %s  (%d KB)" % (OUT, OUT.stat().st_size // 1024))
