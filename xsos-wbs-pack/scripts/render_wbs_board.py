#!/usr/bin/env python3
"""WBS 进度看板生成器 —— 只读 docs/wbs，输出自包含 HTML。

用法: python3 render_wbs_board.py <pack-dir> [输出.html]
数据源就是 WBS Pack 本身，不引入任何新数据。
"""
import re, sys, json, html, os
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime

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
STATUS_ORDER = ["proposed", "todo", "in_progress", "review", "done", "cancelled"]

def sections(fname, prefix="WP"):
    p = PACK / fname
    if not p.is_file():
        return set()
    pat = rf"^##\s+({prefix}-[A-Z]+-\d+)"
    return {m.group(1) for m in re.finditer(pat, p.read_text(encoding="utf-8"), re.M)}

# ── 解析 02-wbs.md 表格 ────────────────────────────────────────────────
wbs, headers = {}, []
for line in (PACK / "02-wbs.md").read_text(encoding="utf-8").splitlines():
    if line.startswith("|") and "wp_id" in line:
        headers = [c.strip() for c in line.strip("|").split("|")]
    m = re.match(r"^\|\s*(WP-[A-Z]+-\d+)\s*\|", line)
    if m and headers:
        cells = [c.strip() for c in line.strip("|").split("|")]
        row = dict(zip(headers, cells + [""] * (len(headers) - len(cells))))
        deps = [d.strip() for d in row.get("depends_on", "").split(",")
                if d.strip() and d.strip().lower() != "none"]
        wbs[m.group(1)] = dict(
            id=m.group(1), title=row.get("title_cn", ""), title_en=row.get("title_en", ""),
            type=row.get("type", ""), owner=row.get("owner", ""),
            status=row.get("status", ""), depends=deps,
            scope=row.get("scope", ""), non_goals=row.get("non_goals", ""),
            acceptance_ref=row.get("acceptance_ref", ""), outputs=row.get("outputs", ""),
        )

ids = set(wbs)
cov_sets = {k: sections(f) for k, f in FACT_FILES.items() if k != "acceptance"}
cov_sets["acceptance"] = {a.replace("AC-", "WP-") for a in sections("06-acceptance.md", "AC")}
for wid, w in wbs.items():
    w["cov"] = {k: (wid in s) for k, s in cov_sets.items()}
    w["cov_n"] = sum(w["cov"].values())

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
    wbs=[wbs[i] for i in sorted(ids)],
    fact_files=FACT_FILES,
    status_order=STATUS_ORDER,
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
<a href="#s-cov" data-s="s-cov">覆盖矩阵</a>
<a href="#s-board" data-s="s-board">进度看板<span class="n" id="nBoard"></span></a>
<a href="#s-blk" data-s="s-blk">阻塞<span class="n" id="nBlk"></span></a>
<span class="sp"></span><button id="tg">TH</button>
</div></nav>
<div class="w">
<h1 id="s-top">WBS 需求管理看板</h1><p class="sub" id="sub"></p>
<div class="kpis" id="kpis"></div>
<div class="note" id="gapNote"></div>
<h2 id="s-cov">需求到工作包 覆盖矩阵</h2>
<div class="bar" id="covBar"></div>
<div class="scroll"><table id="tCov"></table></div>
<h2 id="s-board">进度看板</h2>
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
const SC={proposed:"--gray",todo:"--todo",in_progress:"--prog",review:"--warn",done:"--ok",cancelled:"--gray"};
const SN={proposed:"已提出",todo:"待办",in_progress:"进行中",review:"待审",done:"已完成",cancelled:"已取消"};
E("sub").textContent=D.pack+" 生成于 "+D.generated+" 数据源为 WBS Pack 本身，无新增数据";
const req=S.coverage.requirements, gap=T-req;
E("kpis").innerHTML=[["",T,"工作包总数"],["bad",gap,"无需求依据"],["warn",S.by_status.review||0,"卡在待审"],
["",S.by_status.in_progress||0,"进行中"],["ok",S.by_status.done||0,"已完成"],
["warn",S.blocked,"被依赖阻塞"],["warn",Object.keys(S.by_owner).length,"负责人数"]]
.map(function(a){return "<div class=\"kpi "+a[0]+"\"><b>"+a[1]+"</b><span>"+a[2]+"</span></div>";}).join("");
E("gapNote").innerHTML="<b>"+gap+" / "+T+"</b> 个工作包在 <code>01-requirements.md</code> 里没有对应需求条目（覆盖 "
+Math.round(req/T*100)+"%）——说明大多数包是<b>直接写的工作包，没有从需求分解</b>。<br><br>对照：<code>06-acceptance.md</code> 覆盖 <b>"
+Math.round(S.coverage.acceptance/T*100)+"%</b>，因为 validator 强制校验 <code>acceptance_ref</code>；其余不被强制的事实文件覆盖率是 "
+FK.filter(function(k){return k!=="acceptance";}).map(function(k){return Math.round(S.coverage[k]/T*100)+"%";}).join(" / ")
+"。<b>Gate 拦什么，什么就补齐——这是最直接的因果证据。</b>";
var covFilter=null;
function covRows(){return D.wbs.filter(function(w){return !covFilter||!w.cov[covFilter];}).map(function(w){
return "<tr><td><code>"+esc(w.id)+"</code></td><td style=\"white-space:normal\">"+esc(w.title)+"</td><td><span style=\"color:var("
+(SC[w.status]||"--gray")+")\">"+(SN[w.status]||esc(w.status))+"</span></td>"
+FK.map(function(k){return "<td style=\"text-align:center\" class=\""+(w.cov[k]?"y":"n")+"\">"+(w.cov[k]?"YES":"--")+"</td>";}).join("")
+"<td class=\"n\" style=\"text-align:right\">"+w.cov_n+"/"+FK.length+"</td></tr>";}).join("");}
function drawCov(){E("tCov").innerHTML="<thead><tr><th>wp_id</th><th>标题</th><th>状态</th>"
+FK.map(function(k){return "<th style=\"text-align:center\">"+CN[k]+"</th>";}).join("")
+"<th style=\"text-align:right\">齐全度</th></tr></thead><tbody>"+covRows()+"</tbody>";}
E("covBar").innerHTML="<button class=\"on\" data-f=\"\">全部 "+T+"</button>"
+FK.map(function(k){return "<button data-f=\""+k+"\">缺"+CN[k]+" "+(T-S.coverage[k])+"</button>";}).join("");
E("covBar").onclick=function(e){if(e.target.tagName!=="BUTTON")return;
Array.prototype.forEach.call(E("covBar").children,function(b){b.classList.remove("on");});
e.target.classList.add("on");covFilter=e.target.dataset.f||null;drawCov();};
drawCov();
var ownerFilter=null;
function drawBoard(){E("board").innerHTML=D.status_order.filter(function(s){return S.by_status[s];}).map(function(s){
var list=D.wbs.filter(function(w){return w.status===s&&(!ownerFilter||w.owner===ownerFilter);});
var cards=list.map(function(w){return "<div class=\"c\" style=\"--s:var("+SC[s]+")\" title=\""+esc(w.scope).slice(0,300)+"\"><b>"
+esc(w.title)+"</b><span class=\"id\">"+esc(w.id)+" "+esc(w.type)+"</span><div class=\"m\"><span>"
+FK.map(function(k){return "<i class=\"dot\" style=\"background:var("+(w.cov[k]?"--ok":"--line")+")\" title=\""+CN[k]+"\"></i>";}).join("")
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
E("ft").textContent="本页由 xsos-wbs-pack/scripts/render_wbs_board.py 从 "+D.pack+" 直接生成，自包含无外部依赖。改 02-wbs.md 的 status 后重跑即刷新。";
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
