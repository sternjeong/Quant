#!/usr/bin/env python3
"""report_data.json을 읽어 final_report.html을 만든다.

analysis/2026-08-19_champion_beta_and_satellite_research/build_report.py 와 동일한 CSS 디자인
시스템(다크네이비/올리브 톤, 세리프 헤드라인, TOC, 섹션 번호, 판정 배지)을 재사용한다.
"""
import json
import math
import os

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

with open(f"{OUT_DIR}/report_data.json", encoding="utf-8") as f:
    R = json.load(f)

GEN = R["meta"]["generated"]
H5 = R["h5"]
H6 = R["h6"]


def fnum(v, digits=1, signed=False):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    s = f"{v:,.{digits}f}"
    if signed and v > 0:
        s = "+" + s
    return s


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def verdict_badge(v):
    cls = "v-accept" if v.startswith("채택") else ("v-reject" if v.startswith("기각") else "v-partial")
    return f'<span class="verdict-badge {cls}">{esc(v)}</span>'


CSS = """
:root{
  color-scheme: light;
  --bg-page:#eef1ee; --surface:#ffffff; --surface-2:#f4f6f3;
  --ink:#12181a; --ink-2:#495550; --ink-muted:#828d87;
  --hairline:#d7ddd6; --border:rgba(11,11,11,0.10);
  --accent:#1f4d3d; --accent-ink:#ffffff; --accent-2:#8a6a1f;
  --accent-2-soft:#f2e6c8; --accent-soft:#e2ebe6; --chart-surface:#fcfcfb;
  --blue:#2a78d6; --orange:#eb6834; --aqua:#1baf7a; --red:#e34948;
  --gridline:#e1e0d9; --axis:#c3c2b7; --delta-pos:#184f95; --delta-neg:#b3261e;
  --code-bg:#f4f6f3; --shadow: 0 1px 2px rgba(20,30,25,0.04), 0 8px 24px -16px rgba(20,30,25,0.18);
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    color-scheme: dark;
    --bg-page:#0f1210; --surface:#171b16; --surface-2:#1c211b;
    --ink:#f2f4f0; --ink-2:#c4cbc2; --ink-muted:#8b958a;
    --hairline:#2c332a; --border:rgba(255,255,255,0.10);
    --accent:#5aab89; --accent-ink:#0b1310; --accent-2:#d9b45c;
    --accent-2-soft:#332a13; --accent-soft:#1b2921; --chart-surface:#1a1a19;
    --blue:#3987e5; --orange:#d95926; --aqua:#199e70; --red:#e66767;
    --gridline:#2c2c2a; --axis:#3a3f38; --delta-pos:#86b6ef; --delta-neg:#ff8a80;
    --code-bg:#1c211b; --shadow: 0 1px 2px rgba(0,0,0,0.3), 0 8px 24px -16px rgba(0,0,0,0.5);
  }
}
:root[data-theme="dark"]{
  color-scheme: dark;
  --bg-page:#0f1210; --surface:#171b16; --surface-2:#1c211b;
  --ink:#f2f4f0; --ink-2:#c4cbc2; --ink-muted:#8b958a;
  --hairline:#2c332a; --border:rgba(255,255,255,0.10);
  --accent:#5aab89; --accent-ink:#0b1310; --accent-2:#d9b45c;
  --accent-2-soft:#332a13; --accent-soft:#1b2921; --chart-surface:#1a1a19;
  --blue:#3987e5; --orange:#d95926; --aqua:#199e70; --red:#e66767;
  --gridline:#2c2c2a; --axis:#3a3f38; --delta-pos:#86b6ef; --delta-neg:#ff8a80;
  --code-bg:#1c211b; --shadow: 0 1px 2px rgba(0,0,0,0.3), 0 8px 24px -16px rgba(0,0,0,0.5);
}
*{box-sizing:border-box;}
html{-webkit-text-size-adjust:100%;}
body{ margin:0; background:var(--bg-page); color:var(--ink);
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif; line-height:1.6; font-size:16px; }
.serif{ font-family: "Iowan Old Style","Palatino Linotype", Georgia, serif; }
.mono, .num, td.num, .tk-name, .kpi-value, code {
  font-family: ui-monospace, "SF Mono", "Cascadia Mono", Consolas, monospace;
  font-variant-numeric: tabular-nums; }
a{ color:var(--accent); }
.wrap{ max-width: 920px; margin:0 auto; padding: 0 24px 96px; }
.masthead{ background: var(--accent); color: var(--accent-ink); padding: 56px 24px 40px; }
.masthead-inner{ max-width:920px; margin:0 auto; }
.masthead-eyebrow{ font-size:12.5px; letter-spacing:0.12em; text-transform:uppercase; opacity:0.82;
  font-family: ui-monospace, "SF Mono", Consolas, monospace; display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
.masthead-eyebrow .dot{ opacity:0.5; }
h1.masthead-title{ font-family:"Iowan Old Style","Palatino Linotype", Georgia, serif; font-weight:600;
  font-size: clamp(28px, 4.2vw, 44px); line-height:1.15; margin: 14px 0 10px; text-wrap: balance; max-width: 26ch; }
.masthead-sub{ font-size:16.5px; max-width:66ch; opacity:0.92; margin:0 0 22px; }
.masthead-meta{ display:flex; flex-wrap:wrap; gap: 10px 26px; font-size:13.5px; opacity:0.85;
  border-top:1px solid rgba(255,255,255,0.22); padding-top:16px; }
.masthead-meta b{ font-weight:600; }
.section{ padding: 52px 0 8px; border-top:1px solid var(--hairline); }
.section:first-of-type{ border-top:none; }
.section h2{ font-family:"Iowan Old Style","Palatino Linotype", Georgia, serif; font-size: 25px;
  font-weight:600; margin: 0 0 16px; display:flex; align-items:baseline; gap:12px; flex-wrap:wrap; }
.sec-no{ font-family: ui-monospace, "SF Mono", Consolas, monospace; font-size:13px; color: var(--accent);
  border:1px solid var(--accent); border-radius:3px; padding:2px 6px; font-weight:600; letter-spacing:0.02em; }
.section h3{ font-size:17.5px; margin: 30px 0 10px; font-weight:650; display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
.section h4{ font-size:15px; margin: 20px 0 8px; font-weight:650; color:var(--ink-2); }
.lede{ font-size:16.5px; color:var(--ink-2); max-width:72ch; }
.section p{ max-width:74ch; }
.section > p, .section > .lede { margin-top: 0; }
.section li{ max-width:70ch; }
.callout{ background: var(--surface-2); border:1px solid var(--hairline); border-left: 3px solid var(--accent);
  border-radius: 6px; padding: 18px 22px; margin: 20px 0 26px; }
.callout-title{ font-size:11.5px; text-transform:uppercase; letter-spacing:0.08em; color:var(--accent);
  font-weight:700; margin-bottom:8px; }
.callout p{ margin:0; max-width:none; }
.callout p + p{ margin-top:10px; }
.caveat{ font-size:14.5px; color:var(--ink-2); background:var(--surface-2); border-radius:6px;
  padding:14px 18px; border:1px dashed var(--hairline); margin: 14px 0; }
.kpi-row{ display:grid; grid-template-columns:repeat(auto-fit, minmax(190px,1fr)); gap:14px; margin: 20px 0 8px; }
.kpi-tile{ background:var(--surface); border:1px solid var(--hairline); border-radius:8px; padding:16px 18px; box-shadow: var(--shadow); }
.kpi-label{ font-size:12.5px; color:var(--ink-muted); margin-bottom:6px; }
.kpi-value{ font-size:26px; font-weight:600; line-height:1.1; }
.kpi-value.pos{ color:var(--delta-pos); }
.kpi-value.neg{ color:var(--delta-neg); }
.kpi-sub{ font-size:12.5px; color:var(--ink-muted); margin-top:4px; }
.chart-card{ background:var(--chart-surface); border:1px solid var(--hairline); border-radius:10px;
  padding:22px 22px 16px; margin: 22px 0; box-shadow: var(--shadow); }
.chart-card h3{ margin: 0 0 4px; font-size:16px; }
.chart-desc{ font-size:13.5px; color:var(--ink-muted); margin: 0 0 14px; max-width:none; }
svg.chart-svg{ width:100%; height:auto; display:block; overflow:visible; }
svg.chart-svg text{ fill:var(--ink-2); font-family: system-ui,-apple-system,"Segoe UI",sans-serif; }
svg.chart-svg .tick-label{ fill:var(--ink-muted); font-size:10.5px; }
svg.chart-svg .axis-line{ stroke:var(--axis); stroke-width:1; }
svg.chart-svg .grid-line{ stroke:var(--gridline); stroke-width:1; }
svg.chart-svg .bar-label{ font-size:11px; fill:var(--ink-2); font-family: ui-monospace,"SF Mono",Consolas,monospace; }
svg.chart-svg .cat-label{ font-size:12px; fill:var(--ink); }
.legend{ display:flex; gap:16px; flex-wrap:wrap; font-size:12.5px; color:var(--ink-2); margin: 4px 0 12px; }
.legend .dot{ display:inline-block; width:9px; height:9px; border-radius:50%; margin-right:6px; }
.table-wrap{ overflow-x:auto; border:1px solid var(--hairline); border-radius:8px; background:var(--surface); }
table.data-table{ width:100%; border-collapse:collapse; font-size:13.5px; min-width:600px; }
table.data-table th{ text-align:right; font-weight:600; font-size:11.5px; color:var(--ink-muted); text-transform:uppercase;
  letter-spacing:0.03em; padding:10px 12px; border-bottom:1px solid var(--hairline); white-space:nowrap; }
table.data-table th:first-child, table.data-table td:first-child{ text-align:left; }
table.data-table td{ padding:8px 12px; border-bottom:1px solid var(--hairline); text-align:right; white-space:nowrap; }
table.data-table tbody tr:hover{ background:var(--surface-2); }
table.data-table tbody tr:last-child td{ border-bottom:none; }
td.tk-cell{ text-align:left !important; }
td.tk-cell .tk-name{ font-weight:650; margin-right:8px; }
td.num.delta.pos, .delta.pos{ color:var(--delta-pos); font-weight:650; }
td.num.delta.neg, .delta.neg{ color:var(--delta-neg); font-weight:650; }
.strong{ font-weight:700; }
tr.best-row{ background: var(--accent-soft); }
footer{ max-width:920px; margin:40px auto 0; padding: 26px 24px 10px; border-top:1px solid var(--hairline);
  font-size:12.5px; color:var(--ink-muted); }
footer p{ max-width:none; }
.toc{ display:flex; flex-wrap:wrap; gap:8px 18px; margin: 24px 0 4px; padding:16px 20px; background:var(--surface);
  border:1px solid var(--hairline); border-radius:8px; }
.toc a{ font-size:13.5px; color:var(--ink-2); text-decoration:none; }
.toc a:hover{ color:var(--accent); text-decoration:underline; }
.src-list{ font-size:13px; color:var(--ink-2); padding-left:18px; }
.src-list li{ margin: 6px 0; }
.verdict-badge{ display:inline-block; font-size:12px; font-weight:700; letter-spacing:0.03em;
  padding:3px 10px; border-radius:20px; text-transform:uppercase; }
.v-accept{ background: var(--accent-soft); color: var(--accent); border:1px solid var(--accent); }
.v-reject{ background: rgba(179,38,30,0.10); color: var(--delta-neg); border:1px solid var(--delta-neg); }
.v-partial{ background: var(--accent-2-soft); color: var(--accent-2); border:1px solid var(--accent-2); }
.hyp-card{ background:var(--surface); border:1px solid var(--hairline); border-radius:8px; padding:16px 20px; margin:14px 0; }
.hyp-card .hyp-id{ font-family: ui-monospace,"SF Mono",Consolas,monospace; font-weight:700; color:var(--accent); font-size:13px; }
"""


def bar_chart(rows, max_val=None, unit="", w=860):
    H = 34 * len(rows) + 30
    left_pad, right_pad, top_pad = 210, 70, 10
    bar_area_w = w - left_pad - right_pad
    if max_val is None:
        max_val = max(v for _, v, _ in rows) * 1.15
    def x_for(v):
        return left_pad + (v / max_val) * bar_area_w if max_val else left_pad
    parts = [f'<svg class="chart-svg" viewBox="0 0 {w} {H}" role="img" aria-label="비교 막대차트">']
    steps = 4
    for si in range(steps + 1):
        gv = max_val * si / steps
        gx = x_for(gv)
        parts.append(f'<line class="grid-line" x1="{gx:.1f}" y1="{top_pad}" x2="{gx:.1f}" y2="{H-10}"/>')
        parts.append(f'<text class="tick-label" x="{gx:.1f}" y="{H-2}" text-anchor="middle">{gv:.2f}{unit}</text>')
    for i, (label, val, color) in enumerate(rows):
        y = top_pad + i * 34 + 17
        bx = x_for(max(val, 0))
        parts.append(f'<text class="cat-label" x="{left_pad-10}" y="{y+4}" text-anchor="end">{esc(label)}</text>')
        parts.append(f'<rect x="{left_pad}" y="{y-9}" width="{max(bx-left_pad,2):.1f}" height="18" rx="3" fill="{color}" opacity="0.88"/>')
        parts.append(f'<text class="bar-label" x="{bx+8:.1f}" y="{y+4}">{val:.3f}{unit}</text>')
    parts.append("</svg>")
    return "".join(parts)


def line_chart(xs, series, w=860, h=320, y_fmt="{:.2f}", x_fmt="{:.0f}%"):
    """series: list of (label, color, values) — 같은 xs를 공유하는 여러 선을 하나의 차트에 그린다.
    각 선은 자기 min/max에 맞춰 독립 y축(좌/우 2개까지)을 쓰지 않고, 공통 정규화 없이 원값 그대로
    그리되 y축 범위는 series 전체의 min/max로 통일한다(단위가 다르면 별도 차트로 분리해서 호출)."""
    left_pad, right_pad, top_pad, bot_pad = 56, 24, 20, 34
    plot_w = w - left_pad - right_pad
    plot_h = h - top_pad - bot_pad
    all_vals = [v for _, _, vals in series for v in vals]
    y_min, y_max = min(all_vals), max(all_vals)
    pad = (y_max - y_min) * 0.12 or 0.1
    y_min -= pad
    y_max += pad
    x_min, x_max = min(xs), max(xs)
    def X(x):
        return left_pad + (x - x_min) / (x_max - x_min) * plot_w if x_max > x_min else left_pad
    def Y(y):
        return top_pad + (1 - (y - y_min) / (y_max - y_min)) * plot_h
    parts = [f'<svg class="chart-svg" viewBox="0 0 {w} {h}" role="img" aria-label="라인차트">']
    steps = 4
    for si in range(steps + 1):
        gy = y_min + (y_max - y_min) * si / steps
        yy = Y(gy)
        parts.append(f'<line class="grid-line" x1="{left_pad}" y1="{yy:.1f}" x2="{w-right_pad}" y2="{yy:.1f}"/>')
        parts.append(f'<text class="tick-label" x="{left_pad-6}" y="{yy+3:.1f}" text-anchor="end">{y_fmt.format(gy)}</text>')
    for x in xs:
        xx = X(x)
        parts.append(f'<text class="tick-label" x="{xx:.1f}" y="{h-bot_pad+16}" text-anchor="middle">{x_fmt.format(x*100)}</text>')
    parts.append(f'<line class="axis-line" x1="{left_pad}" y1="{top_pad}" x2="{left_pad}" y2="{h-bot_pad}"/>')
    parts.append(f'<line class="axis-line" x1="{left_pad}" y1="{h-bot_pad}" x2="{w-right_pad}" y2="{h-bot_pad}"/>')
    for label, color, vals in series:
        pts = " ".join(f"{X(x):.1f},{Y(v):.1f}" for x, v in zip(xs, vals))
        parts.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2.4"/>')
        for x, v in zip(xs, vals):
            parts.append(f'<circle cx="{X(x):.1f}" cy="{Y(v):.1f}" r="3.6" fill="{color}"/>')
    parts.append("</svg>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# H5 데이터 가공
# ---------------------------------------------------------------------------
h5_frontier = H5["frontier"]
h5_core = H5["core_metrics"]
h5_sat = H5["satellite_standalone_metrics"]
h5_xs = [f["satellite_weight"] for f in h5_frontier]
h5_sharpes = [f["metrics"]["sharpe"] for f in h5_frontier]
h5_cagrs = [f["metrics"]["cagr"] for f in h5_frontier]
h5_mdds = [f["metrics"]["mdd"] for f in h5_frontier]
h5_calmars = [f["metrics"]["calmar"] for f in h5_frontier]
h5_peak_w = H5["peak_sharpe_weight"]
h5_peak_m = H5["peak_sharpe_metrics"]

h5_sharpe_chart = line_chart(h5_xs, [("샤프비율", "var(--blue)", h5_sharpes)], y_fmt="{:.3f}")
h5_mdd_chart = line_chart(h5_xs, [("MDD(%)", "var(--red)", h5_mdds)], y_fmt="{:.1f}%")
h5_calmar_chart = line_chart(h5_xs, [("칼마지수", "var(--aqua)", h5_calmars)], y_fmt="{:.2f}")


def h5_row(f):
    m = f["metrics"]
    sw = f["satellite_weight"]
    is_peak = abs(sw - h5_peak_w) < 1e-9
    cls = ' class="best-row"' if is_peak else ""
    return (
        f"<tr{cls}>"
        f'<td class="tk-cell"><span class="tk-name">{sw*100:.0f}%</span></td>'
        f'<td class="num">{fnum(m["cagr"],2,True)}%</td>'
        f'<td class="num">{fnum(m["mdd"],2)}%</td>'
        f'<td class="num strong">{fnum(m["sharpe"],3)}</td>'
        f'<td class="num">{fnum(m["calmar"],3)}</td>'
        f'<td class="num delta {"pos" if f["sharpe_delta_vs_core"]>=0 else "neg"}">{fnum(f["sharpe_delta_vs_core"],3,True)}</td>'
        f'<td class="num delta {"pos" if f["mdd_delta_vs_core_pct_points"]>=0 else "neg"}">{fnum(f["mdd_delta_vs_core_pct_points"],2,True)}%p</td>'
        "</tr>"
    )


h5_table_html = "\n".join(h5_row(f) for f in h5_frontier)

rebal_rows = []
for entry in H5["satellite_rebal_log"]:
    picks_str = ", ".join(entry["picks"]) if entry["picks"] else "(현금)"
    rebal_rows.append(
        "<tr>"
        f'<td class="tk-cell">{esc(entry["date"])}</td>'
        f'<td class="num">{entry["pool_size"]}</td>'
        f'<td class="num">{entry["n_positive_momentum"]}</td>'
        f'<td class="tk-cell">{esc(picks_str)}</td>'
        "</tr>"
    )
rebal_log_html = "\n".join(rebal_rows)

h5_verdict = "채택" if h5_peak_m["sharpe"] > h5_core["sharpe"] else "기각"

# MDD 악화 가속 지점 찾기: 연속 구간 사이 MDD 변화폭이 직전 구간 대비 몇 배로 뛰는 지점
mdd_deltas = [h5_mdds[i+1] - h5_mdds[i] for i in range(len(h5_mdds)-1)]
accel_idx = None
for i in range(1, len(mdd_deltas)):
    if abs(mdd_deltas[i]) > abs(mdd_deltas[i-1]) * 2.5 and abs(mdd_deltas[i]) > 0.5:
        accel_idx = i
        break
accel_weight = h5_xs[accel_idx + 1] if accel_idx is not None else None

# ---------------------------------------------------------------------------
# H6 데이터 가공
# ---------------------------------------------------------------------------
h6_pure = H6["pure_momentum"]
h6_blends = H6["soft_blends"]
h6_equal = h6_blends["equal_50_50"]
h6_tilted = h6_blends["momentum_tilted_30_70"]
h6_hard_ref = H6["h4_hard_filter_reference"]
h6_hard_q = h6_hard_ref["quality_momentum_hard_filter"]
h6_hard_qc = h6_hard_ref["quality_cap_momentum_hard_filter_robustness"]
h6_spy = H6["spy_buy_hold"]
h6_hard_pass_n = H6["hard_filter_pass_count_reference"]

h6_sharpe_bar = bar_chart(
    [("순수 모멘텀(퀄리티 무시)", h6_pure["metrics"]["sharpe"], "var(--blue)"),
     ("경성 필터+모멘텀(H4, 24종목)", h6_hard_q["metrics"]["sharpe"], "var(--aqua)"),
     ("연성 블렌드 50/50 퀄리티", h6_equal["metrics"]["sharpe"], "var(--orange)"),
     ("연성 블렌드 30/70(모멘텀틸트)", h6_tilted["metrics"]["sharpe"], "var(--orange)"),
     ("경성 필터+시총상한(H4, 8종목)", h6_hard_qc["metrics"]["sharpe"], "var(--red)")],
    unit="", w=860,
)


def h6_row(label, m, cash, highlight=False):
    cls = ' class="best-row"' if highlight else ""
    zero_elig = cash.get("pct_months_zero_eligible", cash.get("pct_months_zero_candidates"))
    mean_pool = cash.get("mean_eligible_pool", cash.get("mean_candidates"))
    filled = cash.get("pct_months_filled_topn", cash.get("pct_months_full_topn"))
    return (
        f"<tr{cls}>"
        f'<td class="tk-cell"><span class="tk-name">{esc(label)}</span></td>'
        f'<td class="num">{fnum(m["cagr"],2,True)}%</td>'
        f'<td class="num">{fnum(m["mdd"],2)}%</td>'
        f'<td class="num strong">{fnum(m["sharpe"],3)}</td>'
        f'<td class="num">{fnum(mean_pool,1)}</td>'
        f'<td class="num">{fnum(filled,1)}%</td>'
        f'<td class="num">{fnum(zero_elig,1)}%</td>'
        "</tr>"
    )


h6_table_html = "\n".join([
    h6_row("순수 모멘텀(퀄리티 무시, 100종목 전체)", h6_pure["metrics"], h6_pure["cash_stats"]),
    h6_row(f"경성 필터+모멘텀(H4 인용, {h6_hard_ref.get('quality_momentum_hard_filter',{}).get('universe_size','24')}종목)", h6_hard_q["metrics"], h6_hard_q.get("cash_stats", {})),
    h6_row("경성 필터+시총상한(H4 인용, 8종목, 강건성)", h6_hard_qc["metrics"], h6_hard_qc.get("cash_stats", {})),
    h6_row("연성 블렌드 — 퀄리티 50% / 모멘텀 50%", h6_equal["metrics"], h6_equal["cash_stats"]),
    h6_row("연성 블렌드 — 퀄리티 30% / 모멘텀 70%(모멘텀틸트)", h6_tilted["metrics"], h6_tilted["cash_stats"]),
])

h6_verdict = "기각"  # 두 블렌드 모두 순수 모멘텀·경성필터를 못 이김 (아래에서 실측치로 재확인)
if h6_equal["metrics"]["sharpe"] > h6_pure["metrics"]["sharpe"] or h6_tilted["metrics"]["sharpe"] > h6_pure["metrics"]["sharpe"]:
    h6_verdict = "부분채택"

# ---------------------------------------------------------------------------
# H7 — 스택 여부 판단
# ---------------------------------------------------------------------------
h5_positive = h5_peak_m["sharpe"] > h5_core["sharpe"]
h6_positive = h6_verdict != "기각"
h7_skipped = not (h5_positive and h6_positive)

# ---------------------------------------------------------------------------
# HTML 조립
# ---------------------------------------------------------------------------
HTML = f"""<title>새틀라이트 비중 프런티어와 퀄리티 연성 블렌드</title>
<style>
{CSS}
</style>

<div class="masthead">
  <div class="masthead-inner">
    <div class="masthead-eyebrow">
      <span>QUANT RESEARCH NOTE</span><span class="dot">·</span><span>Track D 연장 · 가설검증</span><span class="dot">·</span><span>Hypothesis-Driven Study</span>
    </div>
    <h1 class="masthead-title">새틀라이트 비중 프런티어와 퀄리티 연성 블렌드 — 트랙D "작게, 검증 가능하게 더하기" 메타 결론의 두 갈래 후속 검증</h1>
    <p class="masthead-sub">작업30(트랙D 완성)의 메타 결론 — "정적 헤지·기계적 사이징 규칙은 거의 항상
      손해였고, 규율을 지킨 소규모 확장(H1 코어-새틀라이트)과 기존 신호에 보조 필터를 얹는 것(H4 퀄리티
      필터)은 조건부로 통했다" — 을 두 방향에서 더 파본다. (1) H1이 10%/20%만 테스트한 새틀라이트
      비중을 0~50%로 촘촘히 스윕해 진짜 최적점과 위험조정 한계를 찾는다(H5). (2) H4의 경성 퀄리티
      필터가 후보 폭을 붕괴시킨 문제를, 하드 탈락 대신 연성 Z-점수 블렌드로 고치면 폭 붕괴 없이
      퀄리티의 이득을 얻을 수 있는지 검증한다(H6). 두 결과를 스태킹할 가치가 있는지도 판단한다(H7).</p>
    <div class="masthead-meta">
      <span><b>기준일</b> {esc(GEN)}</span>
      <span><b>H5 기간</b> {esc(H5['period']['start'])} ~ {esc(H5['period']['end'])}</span>
      <span><b>H6 기간</b> {esc(H6['meta']['start'])} ~ {esc(H6['meta']['end'])}</span>
      <span><b>데이터</b> Yahoo Finance(yfinance) via core.market_data/core.point_in_time_market_cap/core.valuation 로컬 캐시</span>
    </div>
  </div>
</div>

<div class="wrap">

  <nav class="toc">
    <a href="#scope">00 문제 제기</a>
    <a href="#h5">01 H5 — 새틀라이트 비중 프런티어</a>
    <a href="#h6">02 H6 — 경성 필터를 연성 블렌드로</a>
    <a href="#h7">03 H7 — 통합 챔피언</a>
    <a href="#synthesis">04 종합</a>
    <a href="#limitations">05 한계</a>
  </nav>

  <section class="section" id="scope">
    <h2><span class="sec-no">00</span> 문제 제기 — 트랙D의 어떤 결론을 이어가는가</h2>
    <p class="lede">작업29~30(트랙D)은 4개 가설로 "시장을 이긴다"는 것의 의미를 정면 검증했다.
      H1(코어-새틀라이트)은 채택, H2(챔피언 베타 헤지)는 뉘앙스 있는 기각, H3(순열검정)은 부분채택,
      H4(퀄리티 사전필터)는 부분채택이었다. 메타 결론은 명확했다 — <b>"구조를 뜯어고치기보다 기존
      챔피언에 작게, 검증 가능하게 더하기가 가장 일관되게 이겼다"</b>. 하지만 두 가지는 트랙D가
      끝내지 못하고 남겼다.</p>
    <p>첫째, H1은 새틀라이트 비중을 10%와 20%, 딱 두 점만 찍었다(샤프 1.03→1.06→1.05) — 정점이
      어디인지, 더 키우면 언제부터 악화되는지는 몰랐다. 둘째, H4는 경성 필터(PEG≤1.5·성장률≥15%·
      ROE프록시≥15%)가 후보 폭을 100종목→26종목(순수)/8종목(+시총상한)으로 붕괴시켜, 8종목 버전은
      31%의 달에 top4를 못 채워 현금화됐다는 구조적 긴장을 남겼다. 이 리포트는 H5로 새틀라이트
      비중의 전체 프런티어를 그리고, H6으로 경성 필터를 이 저장소가 이미 문서화한 앙상블 Z-점수
      결합 방법론으로 대체해본다.</p>
    <p class="caveat">⚠️ 투자 조언이 아니다. H6은 트랙D의 기대와 반대로 나온다 — 이 저장소의 원칙대로
      결과를 있는 그대로 보고한다.</p>
  </section>

  <section class="section" id="h5">
    <h2><span class="sec-no">01</span> H5 — 새틀라이트 비중 프런티어 {verdict_badge(h5_verdict)}</h2>
    <p class="lede">H1과 정확히 같은 새틀라이트 구축 로직(반기 리밸런싱, <code>sample_universe(as_of_date=t,
      use_point_in_time_market_cap=True)</code>로 그 시점 실제 존재감 있던 40종목 후보 풀, 12개월
      모멘텀 상위 3종목 동일가중)을 재사용하되, 비중만 0%·5%·10%·15%·20%·30%·40%·50%로 스윕했다.
      기간은 2019-08-12~2026-08-19(H1과 동일).</p>

    <div class="kpi-row">
      <div class="kpi-tile"><div class="kpi-label">코어(0%) 샤프</div><div class="kpi-value">{fnum(h5_core["sharpe"],3)}</div><div class="kpi-sub">CAGR {fnum(h5_core["cagr"],2,True)}% · MDD {fnum(h5_core["mdd"],2)}%</div></div>
      <div class="kpi-tile"><div class="kpi-label">새틀라이트 단독(100%, 참고) 샤프</div><div class="kpi-value">{fnum(h5_sat["sharpe"],3)}</div><div class="kpi-sub">CAGR {fnum(h5_sat["cagr"],2,True)}% · MDD {fnum(h5_sat["mdd"],2)}%</div></div>
      <div class="kpi-tile"><div class="kpi-label">샤프 정점 비중</div><div class="kpi-value pos">{h5_peak_w*100:.0f}%</div><div class="kpi-sub">샤프 {fnum(h5_peak_m["sharpe"],3)} (코어 대비 +{fnum(h5_peak_m["sharpe"]-h5_core["sharpe"],3)})</div></div>
      <div class="kpi-tile"><div class="kpi-label">MDD 악화 가속 지점</div><div class="kpi-value">{f"{accel_weight*100:.0f}%" if accel_weight else "—"}</div><div class="kpi-sub">이 비중부터 MDD 악화 속도가 이전 구간 대비 뚜렷이 빨라짐</div></div>
    </div>

    <div class="chart-card">
      <h3>샤프비율 — 새틀라이트 비중별 프런티어</h3>
      <p class="chart-desc">x축은 새틀라이트 비중(0~50%). {h5_peak_w*100:.0f}% 부근에서 정점을 찍고 그 이후 완만히 내려온다.</p>
      {h5_sharpe_chart}
    </div>
    <div class="chart-card">
      <h3>MDD — 새틀라이트 비중별 변화</h3>
      <p class="chart-desc">40%까지는 완만하지만 50%에서 뚜렷이 꺾여 악화된다(-18.6%→-20.8%, 한 구간 만에 코어 대비 총 -3.1%p).</p>
      {h5_mdd_chart}
    </div>
    <div class="chart-card">
      <h3>칼마지수(MDD 대비 CAGR) — 새틀라이트 비중별 변화</h3>
      <p class="chart-desc">칼마는 40%까지 계속 오르지만(CAGR 증가가 MDD 악화보다 빠름), 샤프는 이미 20%부터 꺾인다 — "수익 대비 낙폭"과 "변동성 대비 수익"이 다른 지점에서 최적점을 준다는 뜻.</p>
      {h5_calmar_chart}
    </div>

    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>새틀라이트 비중</th><th>CAGR</th><th>MDD</th><th>샤프</th><th>칼마</th><th>Δ샤프(vs 코어)</th><th>ΔMDD(vs 코어)</th></tr></thead>
        <tbody>{h5_table_html}</tbody>
      </table>
    </div>

    <div class="callout">
      <div class="callout-title">해석 — 샤프 극대화와 "가져갈 가치가 있는가"는 다른 질문</div>
      <p>샤프비율은 {h5_peak_w*100:.0f}~20% 구간에서 정점(1.09)을 찍고 그 이후 완만히 내려와 50%에서는
        코어 단독(1.03)과 거의 같아진다 — H1이 봤던 10%(1.06)·20%(1.05) 두 점은 정점 근처였지만
        정점 그 자체는 아니었다. MDD는 30%까지는 거의 그대로(-17.7%→-18.0%)지만, 40%를 지나며 악화
        속도가 빨라지고(-18.6%), 50%에서는 코어 대비 -3.1%p라는 뚜렷한 낙폭 확대가 나타난다 — 새틀라이트
        단독의 높은 변동성(MDD -33.5%)이 절반 가까이 섞이면서 코어의 낮은 낙폭 방어력을 실제로 갉아먹기
        시작하는 지점이다. 칼마지수만 보면 40%까지 계속 오르는 것처럼 보이지만(CAGR 증가폭이 아직
        MDD 악화폭을 앞서므로), 위험조정수익(샤프) 기준으로는 이미 20%를 넘는 순간부터 "더 태우는
        만큼 덜 돌려받는" 국면에 들어간다. 결론: <b>10~20%가 이 저장소가 이미 알고 있던 것보다 정확히
        옳은 범위였다</b> — 더 키우면 당장 무너지진 않지만(50%도 샤프 1.03으로 코어와 동률) 리스크가
        수익 개선보다 빠르게 불어나는 방향으로 기운다.</p>
    </div>

    <h3>새틀라이트 반기 리밸런싱 로그 (H1과 동일 point-in-time 실행 기록)</h3>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>리밸런싱일</th><th>후보 풀 크기</th><th>양(+)모멘텀 후보 수</th><th>실제 선정 종목</th></tr></thead>
        <tbody>{rebal_log_html}</tbody>
      </table>
    </div>
  </section>

  <section class="section" id="h6">
    <h2><span class="sec-no">02</span> H6 — 경성 필터를 연성 블렌드로 {verdict_badge(h6_verdict)}</h2>
    <p class="lede">H4와 동일한 표본(S&amp;P500 섹터균등 100종목, seed=42)·동일 기간(2019-08-12~2026-08-12)·
      동일 품질 지표(PEG/성장률/ROE프록시)를 쓰되, "통과/탈락"이 아니라 이 저장소가 이미 문서화한
      앙상블 공식(<code>core/strategy_engine.py</code>의 Σ(wᵢ×스코어ᵢ)/Σwᵢ, <code>docs/reports/study_notes_fin_engineering.html</code>
      "F. 앙상블과 신호결합")을 그대로 차용해 퀄리티 Z-점수와 모멘텀 Z-점수를 가중결합한다. 절대모멘텀>0
      게이트는 그대로 유지(퀄리티와 무관한 로테이션 자체의 리스크 규칙)하되, 그 안에서는 아무도 하드
      탈락하지 않는다 — 결측 퀄리티 데이터는 중립(0)으로 처리한다.</p>

    <div class="kpi-row">
      <div class="kpi-tile"><div class="kpi-label">순수 모멘텀 샤프(퀄리티 무시)</div><div class="kpi-value">{fnum(h6_pure["metrics"]["sharpe"],3)}</div><div class="kpi-sub">CAGR {fnum(h6_pure["metrics"]["cagr"],2,True)}% · MDD {fnum(h6_pure["metrics"]["mdd"],2)}%</div></div>
      <div class="kpi-tile"><div class="kpi-label">경성 필터+모멘텀 샤프(H4, {h6_hard_pass_n}종목)</div><div class="kpi-value pos">{fnum(h6_hard_q["metrics"]["sharpe"],3)}</div><div class="kpi-sub">CAGR {fnum(h6_hard_q["metrics"]["cagr"],2,True)}% · MDD {fnum(h6_hard_q["metrics"]["mdd"],2)}%</div></div>
      <div class="kpi-tile"><div class="kpi-label">연성 블렌드 50/50 샤프</div><div class="kpi-value neg">{fnum(h6_equal["metrics"]["sharpe"],3)}</div><div class="kpi-sub">CAGR {fnum(h6_equal["metrics"]["cagr"],2,True)}% · MDD {fnum(h6_equal["metrics"]["mdd"],2)}%</div></div>
      <div class="kpi-tile"><div class="kpi-label">연성 블렌드 30/70(모멘텀틸트) 샤프</div><div class="kpi-value neg">{fnum(h6_tilted["metrics"]["sharpe"],3)}</div><div class="kpi-sub">CAGR {fnum(h6_tilted["metrics"]["cagr"],2,True)}% · MDD {fnum(h6_tilted["metrics"]["mdd"],2)}%</div></div>
    </div>

    <div class="chart-card">
      <h3>샤프비율 — 퀄리티 처리방식별 비교</h3>
      <p class="chart-desc">경성 필터(청록)가 순수 모멘텀(파랑)을 이겼던 H4의 결과가 재확인된다. 그런데 연성 블렌드(주황) 두 버전 모두 순수 모멘텀보다도 낮다 — H6이 검증하려던 방향과 반대다.</p>
      {h6_sharpe_bar}
    </div>

    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>구성</th><th>CAGR</th><th>MDD</th><th>샤프</th><th>평균 후보폭</th><th>top4 완전충족 월(%)</th><th>후보 0 월(%)</th></tr></thead>
        <tbody>{h6_table_html}</tbody>
      </table>
    </div>

    <div class="callout">
      <div class="callout-title">해석 — 폭 붕괴는 고쳤지만, 성과는 오히려 나빠졌다</div>
      <p>후보 폭 붕괴 문제는 확실히 해결됐다 — 경성 필터+시총상한 버전은 31%의 달에 top4를 못 채웠지만
        (평균 후보 4.4개, 8종목 유니버스), 연성 블렌드는 매달 평균 {fnum(h6_equal['cash_stats'].get('mean_eligible_pool'),1)}개의
        후보가 살아있고 {fnum(h6_equal['cash_stats'].get('pct_months_filled_topn'),1)}%의 달에 top4를
        완전히 채운다 — "아무도 하드 탈락시키지 않는다"는 설계가 의도대로 작동했다.</p>
      <p>하지만 위험조정수익은 정반대 방향으로 움직였다. 순수 모멘텀(샤프 {fnum(h6_pure['metrics']['sharpe'],2)})보다도
        50/50 블렌드(샤프 {fnum(h6_equal['metrics']['sharpe'],2)})와 30/70 블렌드(샤프 {fnum(h6_tilted['metrics']['sharpe'],2)})
        모두 낮다 — 퀄리티 비중이 클수록(50%) 더 나빠진다는 점도 일관된 신호다. 이유를 뜯어보면
        직관적이다: H4의 경성 필터가 통과시킨 {h6_hard_pass_n}종목은 "퀄리티도 있고 모멘텀도 있는" 종목들의
        교집합이라 그 안에서 순수 모멘텀 랭킹만 해도 이미 유리한 부분집합에서 고르는 셈이었다. 반면
        연성 블렌드는 100종목 전체를 살려두고 순위만 흔드는데, 이 과정에서 <b>이번 구간(2019~2026)의
        진짜 승자(예: NVDA·META류 고모멘텀·고밸류에이션 종목)가 PEG/ROE 기준으로는 "퀄리티 열위"로
        찍혀 순위에서 밀려나고, 대신 밸류에이션은 매력적이지만 이 구간에서 덜 오른 종목이 그 자리를
        차지했다</b>. 즉 이 표본·구간에서는 퀄리티와 모멘텀이 상호보완적이지 않고 정확히 반대 방향으로
        움직이는 종목들을 자주 골라냈다 — "필터로 후보군 자체를 좁혀 그 안에서 모멘텀에 맡기는 것"과
        "전체 유니버스에서 모멘텀 순위를 퀄리티로 흔드는 것"은 수학적으로 비슷해 보여도 실제로는 다른
        전략이며, 이번 구간에서는 전자가 후자보다 뚜렷이 우월했다.</p>
    </div>
  </section>

  <section class="section" id="h7">
    <h2><span class="sec-no">03</span> H7 — 통합 챔피언 {verdict_badge("스킵")}</h2>
    <p class="lede">작업 지시사항의 결정 규칙을 그대로 따른다: "H5 또는 H6가 자기 베이스라인을 못 이기면
      H7을 강행하지 않는다." H5는 검증됐다(정점 {h5_peak_w*100:.0f}% 비중에서 샤프 {fnum(h5_peak_m['sharpe'],3)},
      코어 대비 +{fnum(h5_peak_m['sharpe']-h5_core['sharpe'],3)}). 하지만 H6은 두 블렌드 가중치
      모두에서 자기 베이스라인(순수 모멘텀, 그리고 H4의 경성 필터)을 이기지 못했다 — 검증되지 않은
      구성요소다.</p>
    <div class="callout">
      <div class="callout-title">스택하지 않는 이유</div>
      <p>H6의 연성 블렌드를 새틀라이트 슬리브의 선정 로직으로 바꿔 넣는 H7을 강행한다면, "검증된 개선(H5)"과
        "검증되지 않은 변경(H6)"을 억지로 합치는 셈이다 — 결과가 나빠져도 그게 H5의 문제인지 H6을
        끼워 넣은 부작용인지 분리해서 해석할 수 없고, 결과가 우연히 괜찮아도 그건 새틀라이트 표본이
        작아서(반기 14회 리밸런싱) 나온 잡음일 가능성이 H6의 실측 결과(100종목·97개월 표본에서도 진
        방향)보다 신뢰도가 낮다. 지시사항이 명시한 대로, 이런 상황에서 의미 있는 결론을 내는 방법은
        "검증된 구성요소만 채택"이다 — 즉 H7의 결론은 <b>새로운 백테스트가 아니라 H5의 결과를 그대로
        가져오는 것</b>이다: 17자산 코어 챔피언에 <b>순수 모멘텀 기반</b> point-in-time 새틀라이트를
        {h5_peak_w*100:.0f}~20% 비중으로 얹는다(H6의 퀄리티 블렌드는 새틀라이트 선정 로직에 넣지 않는다).</p>
    </div>
  </section>

  <section class="section" id="synthesis">
    <h2><span class="sec-no">04</span> 종합 — 이번 라운드가 트랙D 메타 결론에 더한 것</h2>
    <p>작업30의 메타 결론("구조를 뜯어고치기보다 기존 챔피언에 작게, 검증 가능하게 더하기가 가장
      일관되게 이겼다")은 이번 라운드에서도 정확히 같은 형태로 재확인됐지만, 한 가지 중요한 정정이
      붙는다.</p>
    <p><b>H5는 메타 결론을 강화한다.</b> "작게 더하기"가 통했던 이유가 우연히 찍은 두 점(10%/20%)의
      운이 아니라 실제 프런티어의 완만한 정점 근처였음을 확인했다 — 10~20% 범위는 위험조정수익
      기준으로 정말 최적점에 가깝고, 그 이상으로 "더 크게 더하기"는 당장 손해는 아니어도 개선을
      멈추고 리스크만 불리는 방향으로 기운다. <b>"작게"라는 말이 막연한 보수적 직관이 아니라 실측
      가능한 구체적 범위(10~20%)였다는 뜻이다.</b></p>
    <p><b>H6은 메타 결론에 중요한 반례를 더한다.</b> "경성 필터를 연성 블렌드로 완화하면 폭 붕괴
      문제 없이 필터의 이득을 유지할 수 있을 것"이라는, 이 저장소의 문서화된 앙상블 방법론에 기반한
      합리적 기대는 이번 표본·구간에서 틀렸다. 폭 붕괴는 확실히 고쳤지만, 그 대가로 성과 자체가
      순수 모멘텀보다도 나빠졌다 — <b>"경성 필터가 실은 좁은 후보군 안에서 모멘텀에 전권을 맡기는
      방식으로 작동했고, 그 좁힘 자체가 가치의 원천이었다"</b>는, H4가 남긴 긴장을 다른 각도에서
      재확인하는 결론이다. "구조를 유연하게 만드는 것"과 "구조를 유지한 채 신호만 정교화하는 것"은
      다른 선택지이며, 이번 라운드는 후자가 항상 우월하지 않다는 걸 보여준다 — 트랙D 전체가 반복해서
      확인해온 패턴("정적 규칙 변경은 자주 손해, 검증 없이 일반화하지 말 것")이 필터→블렌드 전환에도
      그대로 적용된다는 뜻이다.</p>
    <p>H7을 강행하지 않고 "검증된 것만 채택"으로 마무리한 것 자체도 트랙D의 정신에 부합한다 —
      가설이 두 개 다 이겼을 때만 스태킹을 시도하는 것이 "구조를 뜯어고치기보다 작게, 검증 가능하게"의
      실천이다.</p>
  </section>

  <section class="section" id="limitations">
    <h2><span class="sec-no">05</span> 한계</h2>
    <ul>
      <li><b>H5 새틀라이트 표본 크기</b> — H1과 동일한 한계: 2019~2026 구간에 14회 반기 리밸런싱뿐이라,
        특정 회차의 픽이 프런티어 전체 모양을 좌우할 수 있다. 프런티어가 매끄럽게 나온 것은 좋은
        신호지만 통계적 유의성 검정(순열검정 등)은 이번 범위에 포함하지 않았다.</li>
      <li><b>H5를 2008년 금융위기·2000년 닷컴버블까지 확장하지 못함</b> — H1과 동일한 계산비용 제약
        (point-in-time 유니버스 표본추출이 회당 약 1분)으로 2019~2026 주 구간에 집중했다.</li>
      <li><b>H6 품질 지표는 point-in-time이 아님</b> — H4와 동일한 한계: PEG/성장률/ROE프록시는
        "오늘 시점" 스냅샷 하나로 전체 백테스트 기간에 고정 적용된다(생존자 성격의 전향편향).
        연성 블렌드가 하드 필터를 못 이겼다는 결론 자체는 이 한계와 별개로(둘 다 같은 스냅샷을 쓰므로
        공정 비교) 유효하지만, 두 방식 모두의 절대 수치는 이 한계의 영향을 받는다.</li>
      <li><b>H6 결측 퀄리티 데이터의 중립(0) 처리</b> — 밸류에이션 조회 실패/누락 종목은 z-점수 0으로
        중립화했다. 이는 "정보 없음을 페널티로 취급하지 않는다"는 설계 선택이며, 대신 페널티로
        취급했다면(예: 최저점 부여) 결과가 달라질 수 있다.</li>
      <li><b>H7 미실행</b> — 결정 규칙에 따라 새 백테스트를 실행하지 않았다 — 이는 계산 절약이지
        회피가 아니다: H6이 부정적으로 나온 상태에서 H7을 강행해도 그 결과의 해석 가치가 낮다는
        판단(위 03절 참고)에 따른 의도적 스킵이다.</li>
      <li><b>다중비교 위험</b> — 이 저장소가 지금까지 수십 개의 파라미터/구조 변형을 같은 챔피언
        후보에 반복 검증해왔다는 근본적 한계(작업21이 이미 명시)는 이번 연구에도 그대로 적용된다.</li>
    </ul>
  </section>

</div>

<footer>
  <p>analysis/2026-08-20_satellite_frontier_and_quality_blend_research/ (데이터: report_data.json,
    빌드: build_report.py) · h5_satellite_weight_sweep.py는
    analysis/2026-08-19_champion_beta_and_satellite_research/의 champion_strategy.py·h1_core_satellite.py를
    그대로 재사용(비중 파라미터만 스윕)했고, h6_soft_quality_blend.py는 H4와 동일 표본·기간·품질
    지표를 재사용하되 선정 로직만 경성 필터→연성 Z-점수 블렌드로 바꿨다. 두 스크립트 모두
    core.market_data/core.point_in_time_market_cap/core.strategy_tuning/core.valuation의 로컬
    캐시로 실제 가격·point-in-time 시가총액·밸류에이션 데이터를 받아 실행한 결과를 그대로 사용했다
    (추정치 아님). 이 워크트리는 point-in-time 시가총액 인프라(작업25)가 main에 오르기 전 시점에서
    분기되어 그 인프라가 없어, 두 스크립트 모두 main 체크아웃(/workspaces/Quant)의 core/를 직접
    참조해 실행했다 — 이 워크트리의 core/는 건드리지 않았다.</p>
</footer>
"""

out_file = f"{OUT_DIR}/final_report.html"
with open(out_file, "w", encoding="utf-8") as f:
    f.write(HTML)
print(f"작성 완료: {out_file} ({len(HTML):,} bytes)")
