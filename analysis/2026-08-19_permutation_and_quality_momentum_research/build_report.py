#!/usr/bin/env python3
"""report_data.json을 읽어 최종 HTML 리포트(final_report.html)를 만든다.

analysis/2026-08-19_iren_beta_alpha_hedging/build_report.py 와 동일한 디자인 시스템(다크네이비/올리브
톤, 세리프 헤드라인, TOC, 섹션 번호, 판정 배지)을 그대로 재사용한다.
"""
import json
import math
import os

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

with open(f"{OUT_DIR}/report_data.json", encoding="utf-8") as f:
    R = json.load(f)

GEN = R["meta"]["generated"][:10]
H3 = R["h3"]
H4 = R["h4"]


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
    cls = "v-accept" if v == "채택" else ("v-reject" if v == "기각" else "v-partial")
    return f'<span class="verdict-badge {cls}">{esc(v)}</span>'


H3_BASKET_VERDICT = "부분채택"  # 백분위 93.0/p=0.0746 — 5% 관행 기준은 못 넘지만 무작위 대비 강한 우위
H3_SINGLE_VERDICT = "채택"       # 백분위 100.0/p=0.005
H4_VERDICT = "부분채택"          # 품질+모멘텀이 순수모멘텀은 이기지만 트랙B 챔피언엔 못 미침, 시총상한 버전은 붕괴

# ---------------------------------------------------------------------------
# CSS — 트랙 C 기존 리포트와 동일한 디자인 시스템
# ---------------------------------------------------------------------------
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
  font-size: clamp(28px, 4.2vw, 44px); line-height:1.15; margin: 14px 0 10px; text-wrap: balance; max-width: 24ch; }
.masthead-sub{ font-size:16.5px; max-width:68ch; opacity:0.92; margin:0 0 22px; }
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
.legend{ display:flex; gap:18px; flex-wrap:wrap; margin: 2px 0 14px; font-size:12.5px; color:var(--ink-2); }
.legend .lg-item{ display:flex; align-items:center; gap:6px; }
.legend .lg-swatch{ width:14px; height:3px; border-radius:2px; display:inline-block; }
.fig-caption{ font-size:12.5px; color:var(--ink-muted); margin: 10px 0 0; max-width:none; }
svg.chart-svg{ width:100%; height:auto; display:block; overflow:visible; }
svg.chart-svg text{ fill:var(--ink-2); font-family: system-ui,-apple-system,"Segoe UI",sans-serif; }
svg.chart-svg .tick-label{ fill:var(--ink-muted); font-size:10.5px; }
svg.chart-svg .axis-line{ stroke:var(--axis); stroke-width:1; }
svg.chart-svg .grid-line{ stroke:var(--gridline); stroke-width:1; }
svg.chart-svg .bar-label{ font-size:11px; fill:var(--ink-2); font-family: ui-monospace,"SF Mono",Consolas,monospace; }
svg.chart-svg .cat-label{ font-size:12px; fill:var(--ink); }
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
td.tk-cell .tk-sector{ font-size:11.5px; color:var(--ink-muted); font-family: system-ui,-apple-system,sans-serif; }
td.num.delta.pos, .delta.pos{ color:var(--delta-pos); font-weight:650; }
td.num.delta.neg, .delta.neg{ color:var(--delta-neg); font-weight:650; }
.strong{ font-weight:700; }
tr.best-row{ background: var(--accent-soft); }
tr.worst-row{ background: rgba(179,38,30,0.07); }
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
.tag-list{ display:flex; flex-wrap:wrap; gap:6px; margin: 8px 0; }
.tag{ font-size:11.5px; font-family: ui-monospace,"SF Mono",Consolas,monospace; background:var(--surface-2);
  border:1px solid var(--hairline); border-radius:4px; padding:2px 7px; color:var(--ink-2); }
"""


# ---------------------------------------------------------------------------
# SVG 헬퍼
# ---------------------------------------------------------------------------
def bar_chart(rows, max_val=None, unit="", w=860):
    H = 34 * len(rows) + 30
    left_pad, right_pad, top_pad = 220, 70, 10
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


def histogram(values, actual, n_bins=20, w=860, h=280, color="var(--blue)", actual_color="var(--red)"):
    """순열검정 분포 히스토그램 + 실제값 세로선."""
    lo, hi = min(values + [actual]), max(values + [actual])
    span = hi - lo
    lo -= span * 0.05
    hi += span * 0.05
    bin_w = (hi - lo) / n_bins
    counts = [0] * n_bins
    for v in values:
        idx = min(int((v - lo) / bin_w), n_bins - 1)
        counts[idx] += 1
    max_count = max(counts) if counts else 1

    left_pad, right_pad, top_pad, bottom_pad = 46, 20, 16, 34
    plot_w = w - left_pad - right_pad
    plot_h = h - top_pad - bottom_pad
    bw = plot_w / n_bins

    def x_for(v):
        return left_pad + (v - lo) / (hi - lo) * plot_w

    def y_for_count(c):
        return top_pad + plot_h - (c / max_count) * plot_h if max_count else top_pad + plot_h

    parts = [f'<svg class="chart-svg" viewBox="0 0 {w} {h}" role="img" aria-label="순열검정 분포 히스토그램">']
    # y축 그리드(4단)
    for si in range(5):
        gy = top_pad + plot_h * si / 4
        gc = round(max_count * (1 - si / 4))
        parts.append(f'<line class="grid-line" x1="{left_pad}" y1="{gy:.1f}" x2="{w-right_pad}" y2="{gy:.1f}"/>')
        parts.append(f'<text class="tick-label" x="{left_pad-6}" y="{gy+3:.1f}" text-anchor="end">{gc}</text>')
    for i, c in enumerate(counts):
        bx = left_pad + i * bw
        by = y_for_count(c)
        bh = (top_pad + plot_h) - by
        parts.append(f'<rect x="{bx+0.5:.1f}" y="{by:.1f}" width="{max(bw-1,0.5):.1f}" height="{max(bh,0):.1f}" fill="{color}" opacity="0.75"/>')
    # x축 눈금 (5개)
    for si in range(5):
        gx = left_pad + plot_w * si / 4
        gv = lo + (hi - lo) * si / 4
        parts.append(f'<text class="tick-label" x="{gx:.1f}" y="{h-8}" text-anchor="middle">{gv:.2f}</text>')
    # 실제값 세로선
    ax = x_for(actual)
    parts.append(f'<line x1="{ax:.1f}" y1="{top_pad-4}" x2="{ax:.1f}" y2="{top_pad+plot_h+4}" stroke="{actual_color}" stroke-width="2.5" stroke-dasharray="5,3"/>')
    label_x = min(max(ax + 6, left_pad + 40), w - right_pad - 10)
    parts.append(f'<text x="{label_x:.1f}" y="{top_pad+14}" fill="{actual_color}" font-weight="700" font-size="12" text-anchor="middle">실제 {actual:.2f}</text>')
    parts.append("</svg>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# H3 데이터 준비
# ---------------------------------------------------------------------------
basket_perm = H3["permutation_basket"]
single_perm = H3["permutation_single_iren"]
basket_hist = histogram(basket_perm["permuted_sharpes"], basket_perm["actual_sharpe"])
single_hist = histogram(single_perm["permuted_sharpes"], single_perm["actual_sharpe"], color="var(--aqua)")

perm_summary_bar = bar_chart(
    [("무작위 200회 평균(바스켓)", basket_perm["permuted_mean"], "var(--blue)"),
     ("실제 챔피언(바스켓, 20일/15%)", basket_perm["actual_sharpe"], "var(--red)"),
     ("무작위 200회 평균(IREN단일)", single_perm["permuted_mean"], "var(--aqua)"),
     ("실제 챔피언(IREN단일)", single_perm["actual_sharpe"], "var(--orange)")],
    unit="", w=860,
)

stop_sweep_rows = []
for row in H3["stop_pct_fine_sweep"]:
    is_champion = abs(row["stop_pct"] - 0.15) < 1e-9
    is_best = row["sharpe"] == max(r["sharpe"] for r in H3["stop_pct_fine_sweep"])
    cls = "best-row" if is_best else ("worst-row" if row["sharpe"] < 1.0 else "")
    stop_sweep_rows.append(
        f'<tr class="{cls}">'
        f'<td class="tk-cell"><span class="tk-name">{row["stop_pct"]*100:.1f}%</span>{" <span class=\"tag\">챔피언</span>" if is_champion else ""}</td>'
        f'<td class="num">{fnum(row["cagr"],1,True)}%</td>'
        f'<td class="num">{fnum(row["mdd"],1)}%</td>'
        f'<td class="num strong">{fnum(row["sharpe"],2)}</td>'
        f'<td class="num">{fnum(row["calmar"],2)}</td>'
        "</tr>"
    )
stop_sweep_html = "\n".join(stop_sweep_rows)

window_sweep_rows = []
for row in H3["entry_window_sweep"]:
    is_champion = row["entry_window"] == 20
    is_best = row["sharpe"] == max(r["sharpe"] for r in H3["entry_window_sweep"])
    cls = "best-row" if is_best else ""
    window_sweep_rows.append(
        f'<tr class="{cls}">'
        f'<td class="tk-cell"><span class="tk-name">{row["entry_window"]}일</span>{" <span class=\"tag\">챔피언</span>" if is_champion else ""}</td>'
        f'<td class="num">{fnum(row["cagr"],1,True)}%</td>'
        f'<td class="num">{fnum(row["mdd"],1)}%</td>'
        f'<td class="num strong">{fnum(row["sharpe"],2)}</td>'
        "</tr>"
    )
window_sweep_html = "\n".join(window_sweep_rows)

# 2D 그리드 -> entry_window x stop_pct 히트맵 테이블
grid = H3["grid_2d_sweep"]
windows = sorted(set(r["entry_window"] for r in grid))
stops = sorted(set(r["stop_pct"] for r in grid))
grid_map = {(r["entry_window"], r["stop_pct"]): r["sharpe"] for r in grid}
grid_max = max(grid_map.values())
grid_min = min(grid_map.values())


def heat_color(v):
    t = (v - grid_min) / (grid_max - grid_min) if grid_max > grid_min else 0.5
    # 연한 회색 -> accent 초록 그라디언트
    return f"color-mix(in srgb, var(--accent) {t*80:.0f}%, var(--surface))"


grid_header = "".join(f'<th>{s*100:.1f}%</th>' for s in stops)
grid_rows_html = []
for wnd in windows:
    cells = []
    for s in stops:
        v = grid_map.get((wnd, s))
        champion_mark = " ★" if (wnd == 20 and abs(s - 0.15) < 1e-9) else ""
        style = f'style="background:{heat_color(v)}; font-weight:{700 if champion_mark else 500};"' if v is not None else ""
        cells.append(f'<td class="num" {style}>{fnum(v,2) if v is not None else "—"}{champion_mark}</td>')
    grid_rows_html.append(f'<tr><td class="tk-cell"><span class="tk-name">{wnd}일</span></td>{"".join(cells)}</tr>')
grid_table_html = "\n".join(grid_rows_html)

# ---------------------------------------------------------------------------
# H4 데이터 준비
# ---------------------------------------------------------------------------
pure = H4["pure_momentum"]
qual = H4["quality_momentum"]
qcap = H4["quality_cap_momentum"]
spy = H4["spy_buy_hold"]
sample_ew = H4["sample_equal_weight_buy_hold"]
trackb = H4["track_b_17asset_champion_reference"]

h4_compare_rows = [
    ("SPY 매수보유", spy, None),
    ("표본 100종목 균등가중 매수보유", sample_ew, None),
    ("순수 모멘텀 로테이션 (100종목)", pure["metrics"], pure["universe_size"]),
    ("품질필터+모멘텀 로테이션 (26종목)", qual["metrics"], qual["universe_size"]),
    ("품질+시총상한 로테이션 (8종목)", qcap["metrics"], qcap["universe_size"]),
    ("트랙B 17자산 ETF 챔피언(참고, 인용)", trackb["metrics"], 17),
]
best_sharpe = max(r[1]["sharpe"] for r in h4_compare_rows)


def h4_row(label, m, n, is_ref=False):
    cls = "best-row" if m["sharpe"] == best_sharpe else ""
    ref_tag = ' <span class="tag">인용</span>' if is_ref else ""
    n_tag = f'<span class="tk-sector">{n}종목</span>' if n else ""
    return (
        f'<tr class="{cls}">'
        f'<td class="tk-cell"><span class="tk-name">{esc(label)}</span>{ref_tag}<br>{n_tag}</td>'
        f'<td class="num">{fnum(m.get("cumulative_return"),1,True)}%</td>'
        f'<td class="num">{fnum(m.get("cagr"),2,True)}%</td>'
        f'<td class="num">{fnum(m.get("mdd"),2)}%</td>'
        f'<td class="num strong">{fnum(m.get("sharpe"),3)}</td>'
        f'<td class="num">{fnum(m.get("calmar"),2)}</td>'
        "</tr>"
    )


h4_table_html = "\n".join(
    h4_row(label, m, n, is_ref=(label.startswith("트랙B")))
    for label, m, n in h4_compare_rows
)

h4_bar = bar_chart(
    [("SPY 매수보유", spy["sharpe"], "var(--ink-muted)"),
     ("순수 모멘텀(100종목)", pure["metrics"]["sharpe"], "var(--blue)"),
     ("품질+모멘텀(26종목)", qual["metrics"]["sharpe"], "var(--aqua)"),
     ("품질+시총상한(8종목)", qcap["metrics"]["sharpe"], "var(--red)"),
     ("트랙B 17자산 챔피언(인용)", trackb["metrics"]["sharpe"], "var(--orange)")],
    unit="", w=860,
)

quality_pass_tags = "".join(f'<span class="tag">{esc(t)}</span>' for t in H4["quality_pass_tickers"])
cap_tags = "".join(f'<span class="tag">{esc(t)}</span>' for t in H4["quality_and_cap_ceiling_tickers"])

# 품질필터 통과종목 상세 표 (PEG 오름차순)
qdetail_sorted = sorted(
    [r for r in H4["quality_screen_detail"] if r["quality_pass"]],
    key=lambda r: r["peg"] if r["peg"] is not None else 999,
)
qdetail_rows = []
for r in qdetail_sorted:
    flag = ' <span class="tag">ROE프록시 이상치</span>' if (r["roe_proxy_pct"] or 0) > 200 else ""
    qdetail_rows.append(
        "<tr>"
        f'<td class="tk-cell"><span class="tk-name">{esc(r["ticker"])}</span><span class="tk-sector">{esc(r["sector"])}</span></td>'
        f'<td class="num">{fnum(r["per"],1)}</td>'
        f'<td class="num strong">{fnum(r["peg"],2)}</td>'
        f'<td class="num">{fnum(r["earnings_growth_pct"],1)}%</td>'
        f'<td class="num">{fnum(r["roe_proxy_pct"],1)}%{flag}</td>'
        f'<td class="num">${r["market_cap"]/1e9:,.1f}B</td>'
        "</tr>"
    )
qdetail_html = "\n".join(qdetail_rows)


# ---------------------------------------------------------------------------
# 최종 HTML 조립
# ---------------------------------------------------------------------------
HTML = f"""<title>순열검정과 퀄리티 모멘텀</title>
<style>
{CSS}
</style>

<div class="masthead">
  <div class="masthead-inner">
    <div class="masthead-eyebrow">
      <span>QUANT RESEARCH NOTE</span><span class="dot">·</span><span>Track C · 가설검증 후속</span><span class="dot">·</span><span>Hypothesis-Driven Study</span>
    </div>
    <h1 class="masthead-title">순열검정으로 챔피언을 다시 심문하고, 퀄리티로 모멘텀을 걸러본다</h1>
    <p class="masthead-sub">이 저장소의 두 연구 트랙이 각자 남긴 숙제 두 개를 마저 푼다 — (1) 작업27의
      IREN류 추세추종 챔피언(샤프 1.31)은 작업21의 섹터로테이션 챔피언과 달리 순열검정을 받은 적이
      없었다. (2) 작업19~23의 모멘텀 로테이션은 퀄리티 팩터를 전혀 쓰지 않았고, 작업26의 퀄리티
      스크리닝은 모멘텀과 결합된 적이 없었다. 둘 다 실제 코드를 돌려 검증하고, 예상과 어긋난 부분도
      그대로 보고한다.</p>
    <div class="masthead-meta">
      <span><b>기준일</b> {esc(GEN)}</span>
      <span><b>H3 대상</b> IREN 바스켓 6종목(비트코인채굴→AI 피벗)</span>
      <span><b>H4 대상</b> S&amp;P500 섹터균등표본 100종목</span>
      <span><b>데이터</b> Yahoo Finance(yfinance) via core.market_data/core.valuation 로컬 캐시</span>
    </div>
  </div>
</div>

<div class="wrap">

  <nav class="toc">
    <a href="#scope">00 문제 제기</a>
    <a href="#h3">01 H3 — 추세추종 챔피언 순열검정</a>
    <a href="#h4">02 H4 — 퀄리티-모멘텀 하이브리드</a>
    <a href="#synthesis">03 종합</a>
    <a href="#limitations">04 한계</a>
    <a href="#sources">부록: 출처</a>
  </nav>

  <section class="section" id="scope">
    <h2><span class="sec-no">00</span> 문제 제기 — 이 연구가 메우는 빈틈</h2>
    <p class="lede">이 저장소는 트랙 B(하향식 섹터/자산 로테이션)와 트랙 C(상향식 개별종목 발굴) 두
      갈래로 리서치를 쌓아왔다. 두 갈래 모두 이번 리포트가 정면으로 다루는 구멍을 하나씩 남겼다.</p>
    <ul>
      <li><b>통계적 엄밀성의 비대칭</b> — 트랙 B의 17자산 멀티에셋 챔피언(No.06/07)은 200회 순열검정을
        거쳐 97.5th 백분위(p&asymp;0.025)로 통계적 유의성까지 확인됐다. 반면 트랙 C의 IREN류 추세추종
        챔피언(작업27, 샤프 1.31)은 실제 백테스트만 거쳤을 뿐 순열검정은 받은 적이 없다 — 4.25년이라는
        짧은 표본과 비트코인·AI 인프라 동시 초강세장이라는 특수한 레짐이 겹쳐, 샤프 1.31이 진짜 실력인지
        운인지 구분할 근거가 없었다.</li>
      <li><b>퀄리티와 모멘텀이 한 번도 만난 적이 없다</b> — 트랙 B의 로테이션은 순수 트레일링 모멘텀
        랭킹만 쓴다. 트랙 C 1번째 리포트(작업26)가 만든 PEG/성장률/ROE 퀄리티 스크리닝은 1회성 정적
        필터로만 쓰였다. Asness/Frazzini/Pedersen의 "Quality Minus Junk"를 비롯한 문헌은 퀄리티와
        모멘텀이 상대적으로 낮은 상관관계를 갖고 결합 시 개선되는 경우가 많다고 보고한다 — 이 저장소
        안에서 실제로 그런지 아직 검증한 적이 없었다.</li>
    </ul>
    <p class="caveat">⚠️ 이 리포트는 투자 조언이 아니다. 두 가설 모두 "예상대로 되지 않을 수 있다"는
      전제로 설계했고, 실제로 H3의 결과는 예상보다 애매하게(부분적으로만) 나왔다 — 그대로 보고한다.</p>
  </section>

  <section class="section" id="h3">
    <h2><span class="sec-no">01</span> H3 — IREN류 추세추종 챔피언, 순열검정을 통과하는가 {verdict_badge(H3_BASKET_VERDICT)}</h2>
    <p class="lede">작업27의 챔피언(돈치안 20일 브레이크아웃 + 15% 트레일링스탑, 6종목 바스켓,
      2022-05-19~2026-08-18, 왕복 0.1% 비용)에 순열검정을 적용한다.</p>

    <h3>방법론 — 작업21과 "같은 통계 논리", 다른 구현이 필요했던 이유</h3>
    <p>작업21의 순열검정은 "매달 상위4개 랭킹 대신 양(+)모멘텀 후보 중 무작위 4개를 뽑아도 비슷한가"를
      봤다 — 월별 횡단면 랭킹/선택 스텝이 있는 전략 전용 방법이라, 랭킹·선택 스텝이 아예 없는(바스켓
      전종목에 독립적으로 규칙을 적용하는) 이 추세추종 전략에는 그대로 이식할 수 없다(원본 스크립트
      <code>scripts/_sharpe_research_round4.py</code>도 이미 삭제됨). 대신 이 저장소의 백테스트
      엔진(작업13/14가 만든 Masters의 "4대 검증 테스트" 중 하나, <code>core.backtest_engine.
      _shuffle_daily_bars</code>)을 코드 그대로 재사용했다 — 각 날짜의 시/고/저/종가 "캔들 모양"(전일
      종가 대비 비율)은 보존한 채 날짜 등장 순서만 무작위로 섞어, 변동성·드리프트 분포는 실제와
      동일하지만 추세·자기상관은 사라진 가짜 시계열을 만든다. 이 가짜 시계열 200개에 작업27의 챔피언
      로직(<code>donchian_trailing_stop_positions</code>, 코드 그대로 재사용)을 그대로 돌려 샤프
      분포를 만들고, 실제 챔피언이 그 분포 어디에 위치하는지 봤다.</p>

    <div class="kpi-row">
      <div class="kpi-tile">
        <div class="kpi-label">바스켓 챔피언 백분위</div>
        <div class="kpi-value">{fnum(basket_perm["percentile"],1)}<span style="font-size:16px;">th</span></div>
        <div class="kpi-sub">p&asymp;{fnum(basket_perm["p_value"],4)} (5% 관행 기준 미달)</div>
      </div>
      <div class="kpi-tile">
        <div class="kpi-label">IREN 단일종목 백분위</div>
        <div class="kpi-value pos">{fnum(single_perm["percentile"],1)}<span style="font-size:16px;">th</span></div>
        <div class="kpi-sub">p&asymp;{fnum(single_perm["p_value"],4)} (5% 통과)</div>
      </div>
      <div class="kpi-tile">
        <div class="kpi-label">무작위 200회 평균 샤프(바스켓)</div>
        <div class="kpi-value">{fnum(basket_perm["permuted_mean"],3)}</div>
        <div class="kpi-sub">표준편차 {fnum(basket_perm["permuted_std"],3)} · 실제 {fnum(basket_perm["actual_sharpe"],2)}</div>
      </div>
      <div class="kpi-tile">
        <div class="kpi-label">트랙B 참고(작업21)</div>
        <div class="kpi-value">97.5<span style="font-size:16px;">th</span></div>
        <div class="kpi-sub">p&asymp;0.025 (통과)</div>
      </div>
    </div>

    <div class="chart-card">
      <h3>순열검정 요약 — 무작위 평균 vs 실제 챔피언</h3>
      {perm_summary_bar}
    </div>

    <div class="chart-card">
      <h3>Fig. 1 · 바스켓 챔피언 순열검정 분포 (n=200)</h3>
      <p class="chart-desc">파란 막대 = 날짜순서를 섞은 200개 가짜 시계열의 샤프 분포. 빨간 점선 = 실제
        챔피언(20일/15%) 샤프 {fnum(basket_perm["actual_sharpe"],2)}. 백분위 {fnum(basket_perm["percentile"],1)}th —
        무작위보다는 뚜렷이 우수하지만, 상위 5% 안에는 들지 못한다(상위 7.46% 수준).</p>
      {basket_hist}
    </div>

    <div class="chart-card">
      <h3>Fig. 2 · IREN 단일종목 순열검정 분포 (n=200)</h3>
      <p class="chart-desc">단일종목은 200회 중 단 1회도 실제 샤프({fnum(single_perm["actual_sharpe"],2)})를
        넘지 못했다 — 무작위 분포의 오른쪽 끝 바깥에 위치, 5% 유의수준을 명확히 통과(p&asymp;{fnum(single_perm["p_value"],4)}).</p>
      {single_hist}
    </div>

    <p class="caveat">⚠️ <b>바스켓과 단일종목의 결과가 갈린 이유(해석)</b> — 바스켓(6종목 평균)은
      진입/청산 타이밍이 종목별로 흩어져 있어 "순서를 섞어도" 바스켓 합성 효과 자체가 어느 정도
      살아남는 반면, 단일종목(IREN)은 돈치안 규칙이 그 종목 고유의 추세 구조에 더 직접적으로 물려있어
      순서를 섞으면 효과가 확실히 사라진다 — 즉 <b>"추세추종이 통계적으로 유의미한 엣지를 갖는다"는
      증거는 단일종목 차원에서 훨씬 강하고, 바스켓 차원에서는 아직 5% 관행 기준을 넘지 못했다</b>는
      비대칭적 결론이 나왔다. 작업27은 바스켓을 챔피언으로 채택했었는데, 이 결과는 그 선택에 대한
      직접적인 통계적 보강까지는 아니라는 뜻 — 정직하게 "부분채택"으로 기록한다.</p>

    <h3>스탑폭 세밀 스윕 — 15%가 고립된 스파이크인가, 완만한 고원인가</h3>
    <p>진입창(entry_window)을 20일로 고정하고 스탑폭을 10~35% 사이 11개 지점으로 세밀화했다(기존
      <code>trend_following_sweep.csv</code>는 5개 지점뿐이었다).</p>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>스탑폭</th><th>CAGR</th><th>MDD</th><th>샤프</th><th>Calmar</th></tr></thead>
        <tbody>{stop_sweep_html}</tbody>
      </table>
    </div>
    <p>세밀화하니 15%는 실은 스윕의 전역 최적점이 아니었다 — <b>10%(샤프 {fnum(H3["stop_pct_fine_sweep"][0]["sharpe"],2)})가
      15%(샤프 {fnum(basket_perm["actual_sharpe"],2)})보다 오히려 높다.</b> 다만 12.5~17.5% 구간
      전체가 1.2대 초반~1.37로 뭉쳐 있어("완만한 고원") 15%가 순수 고립 스파이크는 아니다. 정확히
      20%에서만 전 구간에 걸쳐 뚜렷한 트로프(0.92)가 나타나는 게 특이한 구조 — 아래 2D 그리드에서
      진입창을 바꿔도 이 20% 트로프가 재현되는지 확인했다.</p>

    <h3>진입창(돈치안 룩백) 스윕 — 20일 고정 여부</h3>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>진입창</th><th>CAGR</th><th>MDD</th><th>샤프</th></tr></thead>
        <tbody>{window_sweep_html}</tbody>
      </table>
    </div>
    <p>진입창도 마찬가지로 20일이 전역 최적은 아니다 — 25~30일 구간이 오히려 더 좋다(30일 샤프
      {fnum(H3["entry_window_sweep"][4]["sharpe"],2)}, MDD도 {fnum(H3["entry_window_sweep"][4]["mdd"],1)}%로
      챔피언보다 얕다). 15일 이하로 짧아지면 뚜렷이 나빠진다.</p>

    <h3>2D 그리드 — 진입창 × 스탑폭 동시 스윕</h3>
    <p class="chart-desc">★ = 작업27의 원 챔피언 조합(20일/15%). 색이 짙을수록 샤프가 높다. 20% 스탑
      컬럼이 진입창에 무관하게 항상 어둡다(트로프가 재현) — 우연한 노이즈가 아니라 이 특정 스탑폭
      근방에서 구조적으로 손절이 자주 걸리는 패턴으로 추정된다.</p>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>진입창 \\ 스탑폭</th>{grid_header}</tr></thead>
        <tbody>{grid_table_html}</tbody>
      </table>
    </div>

    <p class="caveat">⚠️ <b>종합 판정 — 부분채택인 이유</b> — (1) 단일종목 차원에서는 순열검정을
      명확히 통과(p&asymp;0.005)해 "추세추종이 순수 노이즈가 아니다"는 근거가 강하다. (2) 바스켓
      챔피언은 93rd 백분위로 무작위보다 뚜렷이 우수하지만 관행적 5% 유의수준(p&lt;0.05)에는 못 미친다
      (p&asymp;0.075) — 트랙 B 챔피언(p&asymp;0.025)보다는 약한 근거다. (3) 다만 파라미터 스윕은
      15%/20일이 고립된 과최적화 스파이크가 아니라 넓은 인근 영역(스탑 12.5~17.5%, 진입창 15~30일)이
      대체로 함께 좋다는 것을 보여준다 — 오히려 세밀 스윕에서 발견된 10%스탑/25~30일 진입창이
      원 챔피언보다 나은 지점이라, "작업27이 챔피언을 고른 방식 자체는 과최적화라기보다 스윕 해상도가
      성겼던 것"이라는 새로운 해석이 더 정확하다. 종합하면: <b>이 전략군에는 진짜 엣지가 있다는
      근거가 있지만(특히 단일종목), 바스켓 합성 버전의 정확한 우수성은 트랙 B 수준으로 통계적으로
      확정되지 않았다</b> — 작업27의 결론에 이 caveat을 추가하는 것이 정직한 처리다.</p>
  </section>

  <section class="section" id="h4">
    <h2><span class="sec-no">02</span> H4 — 퀄리티 사전필터 + 모멘텀 로테이션 {verdict_badge(H4_VERDICT)}</h2>
    <p class="lede">S&amp;P500 섹터균등표본 100종목({esc(GEN)} 기준, seed=42)에 작업26의 2단계 퀄리티
      필터(PEG&le;1.5, 이익성장률&ge;15%, ROE프록시&ge;15%, <code>core.valuation</code> 재사용)를 먼저
      적용한 뒤, 통과한 종목만으로 트랙 B와 동일한 로테이션 규칙(12개월 모멘텀, top4 동일비중, 절대모멘텀
      필터, SPY&lt;200일선 시 50%축소, 월간 리밸런싱, 왕복 0.1%비용)을 돌려 순수 모멘텀 로테이션과
      비교했다({esc(H4["meta"]["start"])}~{esc(H4["meta"]["end"])}, 트랙B No.06/07과 동일 기간).</p>

    <h3>필터 정의 — 작업26과 다른 점을 명시</h3>
    <p>작업26의 1단계(핫섹터 제한 + 시총 $300억 상한)는 "텐베거"(소형·특정 테마) 발굴에 특화된
      제약이라 일반 로테이션 비교에는 가져오지 않았다 — 메인 비교는 시총 상한 없이 순수
      퀄리티/밸류에이션 필터만 적용한다. 다만 작업26이 예고한 "품질 필터가 후보 폭을 구조적으로
      줄인다"는 긴장을 그대로 확인하기 위해, 별도 로버스트니스 런에서 $300억 시총 상한을 다시
      걸어 그 효과를 명시적으로 재현했다.</p>

    <h3>퀄리티 필터 통과 종목 — {H4["quality_pass_count"]}/{len(H4["sample_tickers"])}종목 ({fnum(H4["quality_pass_pct_of_sample"],1)}%)</h3>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>종목</th><th>PER</th><th>PEG</th><th>이익성장률</th><th>ROE프록시</th><th>시가총액</th></tr></thead>
        <tbody>{qdetail_html}</tbody>
      </table>
    </div>
    <p class="caveat">⚠️ <b>데이터 품질 캐벗</b> — GDDY(GoDaddy)의 ROE프록시가 12,698%로 표시된다 —
      자사주매입으로 장부가(BVPS)가 극단적으로 작아져 EPS/BVPS 프록시 공식이 폭주한 경우다(진짜
      ROE가 아니라 계산 아티팩트). 작업26이 만든 "EPS/BVPS를 ROE 프록시로 쓴다"는 근사 자체의 알려진
      약점을 여기서도 그대로 물려받았다 — 필터를 통과시키긴 했지만 이 종목의 퀄리티 판정은 곧이곧대로
      믿으면 안 된다는 걸 명시해둔다.</p>
    <p>+시총 $300억 상한까지 적용하면 {len(H4["quality_and_cap_ceiling_tickers"])}종목만 남는다:
      <span class="tag-list">{cap_tags}</span></p>

    <div class="chart-card">
      <h3>샤프비율 비교</h3>
      <p class="chart-desc">품질필터를 더한 모멘텀(26종목)이 순수 모멘텀(100종목)과 SPY를 모두
        앞서지만, 트랙B의 17자산 멀티에셋 챔피언(인용치)에는 못 미친다. 시총상한까지 겹치면(8종목)
        오히려 SPY보다도 크게 나빠진다.</p>
      {h4_bar}
    </div>

    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>구성</th><th>누적수익률</th><th>CAGR</th><th>MDD</th><th>샤프</th><th>Calmar</th></tr></thead>
        <tbody>{h4_table_html}</tbody>
      </table>
    </div>

    <h3>후보 폭(breadth) — 품질필터가 로테이션에 미친 실제 영향</h3>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>구성</th><th>월평균 후보수</th><th>top4 이상 채워진 달</th><th>후보부족(현금화 발생)</th><th>후보 0개인 달</th></tr></thead>
        <tbody>
          <tr><td class="tk-cell"><span class="tk-name">순수 모멘텀(100종목)</span></td>
            <td class="num">{fnum(pure["cash_stats"]["mean_candidates"],1)}</td>
            <td class="num">{fnum(pure["cash_stats"]["pct_months_full_topn"],1)}%</td>
            <td class="num">{fnum(pure["cash_stats"]["pct_months_below_topn"],1)}%</td>
            <td class="num">{fnum(pure["cash_stats"]["pct_months_zero_candidates"],1)}%</td></tr>
          <tr><td class="tk-cell"><span class="tk-name">품질+모멘텀(26종목)</span></td>
            <td class="num">{fnum(qual["cash_stats"]["mean_candidates"],1)}</td>
            <td class="num">{fnum(qual["cash_stats"]["pct_months_full_topn"],1)}%</td>
            <td class="num">{fnum(qual["cash_stats"]["pct_months_below_topn"],1)}%</td>
            <td class="num">{fnum(qual["cash_stats"]["pct_months_zero_candidates"],1)}%</td></tr>
          <tr class="worst-row"><td class="tk-cell"><span class="tk-name">품질+시총상한(8종목)</span></td>
            <td class="num">{fnum(qcap["cash_stats"]["mean_candidates"],1)}</td>
            <td class="num">{fnum(qcap["cash_stats"]["pct_months_full_topn"],1)}%</td>
            <td class="num strong">{fnum(qcap["cash_stats"]["pct_months_below_topn"],1)}%</td>
            <td class="num">{fnum(qcap["cash_stats"]["pct_months_zero_candidates"],1)}%</td></tr>
        </tbody>
      </table>
    </div>
    <p>작업26이 예고했던 긴장이 정확히 재현됐다 — 순수 필터(26종목)는 월평균 후보
      {fnum(qual["cash_stats"]["mean_candidates"],1)}개로 여전히 top4를 채우기에 충분했지만(현금화
      0%), 시총 $300억 상한까지 겹친 8종목 유니버스는 월평균 후보가 {fnum(qcap["cash_stats"]["mean_candidates"],1)}개로
      줄어 <b>84개월 중 {fnum(qcap["cash_stats"]["pct_months_below_topn"]*84/100,0)}개월({fnum(qcap["cash_stats"]["pct_months_below_topn"],0)}%)은
      top4를 못 채워 일부 현금으로 남았다</b> — "퀄리티 스크리닝을 강하게 걸수록 로테이션에 필요한
      폭(breadth)이 구조적으로 줄어든다"는 것을 실측으로 확인한 것이다. 성과도 이를 그대로 반영한다
      (샤프 {fnum(qcap["metrics"]["sharpe"],2)}로 SPY {fnum(spy["sharpe"],2)}보다도 낮고, MDD도
      {fnum(qcap["metrics"]["mdd"],1)}%로 오히려 더 나쁘다 — 소수 종목 집중 위험이 퀄리티의 이점을
      상쇄).</p>

    <p class="caveat">⚠️ <b>부분채택인 이유</b> — 메인 비교(퀄리티 필터만, 시총상한 없음)는 가설을
      지지한다: 품질+모멘텀 샤프 {fnum(qual["metrics"]["sharpe"],2)}가 순수 모멘텀
      {fnum(pure["metrics"]["sharpe"],2)}, SPY {fnum(spy["sharpe"],2)}, 표본균등가중
      {fnum(sample_ew["sharpe"],2)}을 전부 앞선다 — Asness/Frazzini/Pedersen류 퀄리티-모멘텀 결합
      문헌과 방향이 일치한다. 다만 (1) 이 저장소의 다른 챔피언(트랙B 17자산 멀티에셋, 샤프 1.10)에는
      여전히 못 미치고, (2) 필터를 조금만 더 세게 걸면(시총상한 추가) 정확히 정반대 결과가 나온다는
      것도 같은 실험에서 확인됐다 — "퀄리티가 모멘텀을 개선한다"는 방향은 맞지만 "얼마나 세게
      거를 것인가"에 결과가 매우 민감하다는 조건부 결론이라 완전 채택으로 올리지 않는다.</p>
  </section>

  <section class="section" id="synthesis">
    <h2><span class="sec-no">03</span> 종합</h2>
    <p class="lede">두 가설 모두 "완전 채택"에는 못 미쳤지만, 방향은 둘 다 긍정적이었고 그 과정에서
      이 저장소의 기존 챔피언들에 대한 구체적인 보정 사항을 남겼다.</p>
    <p><b>H3(추세추종 챔피언 순열검정)</b> — 단일종목 차원의 엣지는 통계적으로 확실하다(p&asymp;0.005).
      바스켓 합성 챔피언은 무작위보다 뚜렷이 우수하지만(93rd 백분위) 트랙B 수준(97.5th)에는 못
      미친다. 세밀 스윕은 원 챔피언 파라미터(20일/15%)가 고립된 스파이크가 아니라 넓은 고원 지대
      안에 있다는 것도 함께 확인했다 — 오히려 더 나은 인근 조합(10%스탑, 25~30일 진입창)이
      발견됐다. 작업27의 리포트에는 "바스켓 챔피언의 정확한 우수성은 아직 5% 관행 기준으로
      통계적으로 확정되지 않았다"는 caveat을 추가하는 것이 정직한 후속 조치다.</p>
    <p><b>H4(퀄리티-모멘텀 하이브리드)</b> — 방향은 명확히 지지된다: 같은 유니버스·같은 로테이션
      규칙에서 퀄리티 사전필터를 더하면 순수 모멘텀보다 샤프가 개선된다({fnum(pure["metrics"]["sharpe"],2)}→{fnum(qual["metrics"]["sharpe"],2)}).
      다만 이 결과는 (a) 트랙B의 자산배분형 멀티에셋 챔피언보다 낮고, (b) 필터 강도에 매우 민감하다
      (시총상한을 더하면 샤프가 {fnum(qcap["metrics"]["sharpe"],2)}로 붕괴) — "퀄리티는 모멘텀을
      개선하는 방향의 팩터이지만, 개별주 유니버스에서 트랙B의 자산배분형 분산 효과를 대체할 만큼
      강력하지는 않다"는 것이 가장 정확한 요약이다.</p>
    <div class="callout">
      <div class="callout-title">실전 시사점</div>
      <p>이 저장소에서 지금까지 나온 "가장 강건한" 전략은 여전히 트랙B의 17자산 멀티에셋 로테이션이다
        (순열검정 통과 + 2008/2000/2022 세 번의 실제 위기 아웃오브샘플 검증 + 이번 H4 비교에서도
        개별주 퀄리티-모멘텀 하이브리드보다 우위). 개별주 차원의 전략들(트랙C 전체)은 하나같이
        "방향은 맞지만 자산배분형 분산만큼 강하지는 않다"는 패턴을 반복하고 있다 — 이번 두 가설도
        예외가 아니다.</p>
    </div>
  </section>

  <section class="section" id="limitations">
    <h2><span class="sec-no">04</span> 한계</h2>
    <ul>
      <li><b>H3 순열검정의 방법론적 선택</b> — 날짜 순서를 통째로 섞는 방식(각 날짜의 캔들 모양은
        보존)은 추세·자기상관을 강하게 제거하는 귀무가설이다. 더 약한 귀무가설(예: 블록 부트스트랩으로
        단기 변동성 군집만 보존)을 썼다면 채택 방향으로 결과가 달라졌을 수 있다 — 이번 리포트는
        이 저장소가 이미 검증된 core 인프라(작업13/14)를 그대로 재사용하는 것을 우선했다.</li>
      <li><b>H3 표본 크기</b> — 바스켓 6종목, 단일 파라미터 조합, 4.25년 구간이라는 원래 작업27의
        한계는 순열검정으로도 해소되지 않는다 — 순열검정은 "이 정도 샤프가 순수 노이즈로 나올
        확률"을 계량화할 뿐, 표본 자체가 넓어지는 건 아니다.</li>
      <li><b>H4 펀더멘털의 시점 문제(가장 중요한 한계)</b> — PEG/이익성장률/ROE프록시는 현재
        ({esc(GEN)}) 시점 스냅샷만 사용했다. 작업25가 만든 point-in-time 인프라는 시가총액에만
        적용되고, 이 저장소에 PEG/성장률/ROE의 과거 시점 값을 재구성할 데이터소스가 없다. 즉 이
        백테스트는 "오늘 기준 퀄리티 통과 종목 집합을 과거 전체 구간에 그대로 적용"한 것으로,
        작업24/25가 개별주 확장 갈래에서 발견했던 것과 같은 유형의 전향편향(hindsight bias)을
        내포한다 — 오늘 시점에 이미 좋은 펀더멘털을 보이는 종목은 과거에도 꾸준히 좋았을 가능성이
        높아(생존 편향과 유사한 메커니즘), 결과가 실제보다 낙관적일 수 있다.</li>
      <li><b>H4 표본 크기와 시드 의존성</b> — S&amp;P500 100종목 표본은 섹터균등추출이지만 seed=42
        하나만 썼다 — 다른 시드로는 통과 종목 구성이 달라져 결과가 흔들릴 수 있다(트랙B가 이미
        여러 라운드에 걸쳐 겪은 다중비교/과최적화 위험과 같은 종류).</li>
      <li><b>ROE 프록시의 알려진 약점</b> — EPS/BVPS는 자사주매입으로 장부가가 왜곡된 종목(GDDY
        사례, 위 표 참고)에서 무의미한 극단치를 낸다 — 작업26에서 물려받은 근사식의 한계이며 이번
        리포트에서 고치지 않고 그대로 노출만 시켰다.</li>
      <li><b>거래비용 모델의 단순함</b> — 두 가설 모두 왕복 0.1% 고정비용만 반영했다 — 슬리피지,
        특히 H4의 소형주(시총 $150억 미만 다수)에서는 실제 체결비용이 이보다 클 가능성이 높다.</li>
    </ul>
  </section>

  <section class="section" id="sources">
    <h2><span class="sec-no">부록</span> 출처</h2>
    <h4>H3 — 순열검정 방법론</h4>
    <ul class="src-list">
      <li>Timothy Masters, <i>Permutation and Randomization Tests for Trading System Development</i> —
        이 저장소 <code>core/backtest_engine.py</code>(작업13/14)가 이미 구현·pytest 검증한 방법론.</li>
    </ul>
    <h4>H4 — 퀄리티-모멘텀 결합 문헌</h4>
    <ul class="src-list">
      <li><a href="https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2312432" target="_blank" rel="noopener">Asness, Frazzini &amp; Pedersen, "Quality Minus Junk" (SSRN 2312432, Review of Accounting Studies 2019)</a> — 퀄리티(안전·수익성·성장성·배당성향)가 높은 종목이 유의미한 위험조정 초과수익을 낸다는 원 논문.</li>
      <li><a href="https://sghiscock.com.au/wp-content/uploads/2024/09/Momentum-and-Quality_SGH2024_web.pdf" target="_blank" rel="noopener">SGH, "Momentum and Quality" (2024)</a> — 1964~2023년 데이터에서 모멘텀-퀄리티 팩터 상관계수 약 0.29(낮은 상관, 상호보완적)로 추정.</li>
      <li><a href="https://alphaarchitect.com/using-momentum-to-find-value/" target="_blank" rel="noopener">Alpha Architect, "Using Momentum to Find Value"</a> — 가치/퀄리티와 모멘텀을 함께 쓸 때의 실증적 이점 논의.</li>
      <li>James O'Shaughnessy, <i>What Works on Wall Street</i> — 가치·모멘텀 결합("Trending Value") 전략이 1964~2009년 백테스트에서 단일 팩터보다 우수했다는 실증(퀄리티 결합 확장판도 논의).</li>
    </ul>
  </section>

</div>

<footer>
  <p>analysis/2026-08-19_permutation_and_quality_momentum_research/ (데이터: report_data.json =
    h3_results.json + h4_results.json 병합, 빌드: build_report.py) · h3_permutation_test.py는
    core.backtest_engine._shuffle_daily_bars와 analysis/2026-08-16_iren_volatile_momentum_stocks/
    backtest.py의 donchian_trailing_stop_positions를 코드 그대로 재사용했다. h4_quality_momentum_hybrid.py는
    core.screener/core.valuation/core.strategy_tuning.sample_universe와 analysis/
    kostolany_market_report_2026-08-12/momentum_rotation.py의 로테이션 로직 패턴을 재사용했다.
    모든 수치는 실제 코드 실행 결과이며 추정치가 아니다.</p>
</footer>
"""

out_file = f"{OUT_DIR}/final_report.html"
with open(out_file, "w", encoding="utf-8") as f:
    f.write(HTML)
print(f"작성 완료: {out_file} ({len(HTML):,} bytes)")
