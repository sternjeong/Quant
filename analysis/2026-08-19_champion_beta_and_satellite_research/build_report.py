#!/usr/bin/env python3
"""report_data.json을 읽어 final_report.html을 만든다.

analysis/2026-08-19_iren_beta_alpha_hedging/build_report.py 와 동일한 CSS 디자인 시스템(다크네이비/
올리브 톤, 세리프 헤드라인, TOC, 섹션 번호, 판정 배지)을 재사용한다.
"""
import json
import math
import os

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

with open(f"{OUT_DIR}/report_data.json", encoding="utf-8") as f:
    R = json.load(f)

GEN = R["meta"]["generated"]
H1 = R["h1"]
H2 = R["h2"]


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


# ---------------------------------------------------------------------------
# CSS — iren_beta_alpha_hedging 리포트와 동일한 디자인 시스템
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


# ---------------------------------------------------------------------------
# H1 데이터 가공
# ---------------------------------------------------------------------------
core_m = H1["core_metrics"]
sat_m = H1["satellite_metrics"]
blends = H1["blends"]
blend10 = blends.get("0.1", blends.get("0.1"))
blend20 = blends.get("0.2", blends.get("0.2"))

# blends 딕셔너리 key는 파이썬 float->str 변환 결과라 "0.1"/"0.2" 형태일 수도, "0.10" 형태일 수도 있어
# 안전하게 첫 번째/두 번째 값을 순서대로 사용한다.
blend_items = list(blends.items())
blend_low = blend_items[0][1]["metrics"] if len(blend_items) > 0 else None
blend_high = blend_items[1][1]["metrics"] if len(blend_items) > 1 else None
blend_low_pct = blend_items[0][0] if len(blend_items) > 0 else "0.1"
blend_high_pct = blend_items[1][0] if len(blend_items) > 1 else "0.2"

h1_sharpe_bar = bar_chart(
    [("코어(17자산 챔피언)", core_m["sharpe"], "var(--blue)"),
     ("새틀라이트 단독", sat_m["sharpe"], "var(--orange)"),
     (f"블렌드 {float(blend_low_pct)*100:.0f}%", blend_low["sharpe"], "var(--aqua)"),
     (f"블렌드 {float(blend_high_pct)*100:.0f}%", blend_high["sharpe"], "var(--aqua)")],
    unit="", w=860,
)

h1_calmar_bar = bar_chart(
    [("코어(17자산 챔피언)", core_m["calmar"], "var(--blue)"),
     ("새틀라이트 단독", sat_m["calmar"], "var(--orange)"),
     (f"블렌드 {float(blend_low_pct)*100:.0f}%", blend_low["calmar"], "var(--aqua)"),
     (f"블렌드 {float(blend_high_pct)*100:.0f}%", blend_high["calmar"], "var(--aqua)")],
    unit="", w=860,
)


def metrics_row(label, m, highlight=False):
    cls = ' class="best-row"' if highlight else ""
    return (
        f"<tr{cls}>"
        f'<td class="tk-cell"><span class="tk-name">{esc(label)}</span></td>'
        f'<td class="num">{fnum(m["cagr"],2,True)}%</td>'
        f'<td class="num">{fnum(m["mdd"],2)}%</td>'
        f'<td class="num strong">{fnum(m["sharpe"],3)}</td>'
        f'<td class="num">{fnum(m["calmar"],3)}</td>'
        f'<td class="num">{fnum(m["cumulative_return"],1,True)}%</td>'
        "</tr>"
    )


h1_table_rows = [
    metrics_row("코어(17자산 챔피언) 100%", core_m),
    metrics_row("새틀라이트 단독 100%(참고)", sat_m),
    metrics_row(f"블렌드 — 새틀라이트 {float(blend_low_pct)*100:.0f}%", blend_low, highlight=(blend_low["sharpe"] > core_m["sharpe"])),
    metrics_row(f"블렌드 — 새틀라이트 {float(blend_high_pct)*100:.0f}%", blend_high, highlight=(blend_high["sharpe"] > core_m["sharpe"])),
]
h1_table_html = "\n".join(h1_table_rows)

# 반기 리밸런싱 로그 표
rebal_rows = []
for entry in H1["satellite_rebal_log"]:
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

h1_verdict = "부분채택" if (blend_low["sharpe"] >= core_m["sharpe"] or blend_high["sharpe"] >= core_m["sharpe"]) else "기각"
if blend_low["sharpe"] >= core_m["sharpe"] and blend_high["sharpe"] >= core_m["sharpe"]:
    h1_verdict = "채택"

# ---------------------------------------------------------------------------
# H2 데이터 가공
# ---------------------------------------------------------------------------
p19 = H2["primary_17asset_2019_2026"]
p15 = H2["robustness_17asset_2015_2026"]
p07 = H2["three_asset_proxy_2007_2026_incl_gfc"]

h2_sharpe_bar = bar_chart(
    [("2019~2026 무헤지", p19["unhedged"]["sharpe"], "var(--aqua)"),
     ("2019~2026 롤링헤지", p19["rolling_hedged"]["sharpe"], "var(--red)"),
     ("2015~2026 무헤지", p15["unhedged"]["sharpe"], "var(--aqua)"),
     ("2015~2026 롤링헤지", p15["rolling_hedged"]["sharpe"], "var(--red)"),
     ("2007~2026(3자산 근사) 무헤지", p07["unhedged"]["sharpe"], "var(--aqua)"),
     ("2007~2026(3자산 근사) 롤링헤지", p07["rolling_hedged"]["sharpe"], "var(--red)")],
    unit="", w=860,
)


def h2_row(label, d, has_alpha_share=True):
    alpha_share = d.get("alpha_share_of_total_cagr_pct")
    alpha_share_str = f"{fnum(alpha_share,1)}%" if alpha_share is not None else "—"
    alpha_ann = d.get("static_alpha_annualized_pct")
    alpha_ann_str = f"{fnum(alpha_ann,2,True)}%" if alpha_ann is not None else "—"
    return (
        "<tr>"
        f'<td class="tk-cell"><span class="tk-name">{esc(label)}</span></td>'
        f'<td class="num">{fnum(d["avg_rolling_beta"],2)}</td>'
        f'<td class="num">{fnum(d["unhedged"]["sharpe"],3)}</td>'
        f'<td class="num">{fnum(d["rolling_hedged"]["sharpe"],3)}</td>'
        f'<td class="num delta {"pos" if d["sharpe_delta_rolling"]>0 else "neg"}">{fnum(d["sharpe_delta_rolling"],3,True)}</td>'
        f'<td class="num">{fnum(d["unhedged"]["mdd_pct"],1)}%</td>'
        f'<td class="num">{alpha_ann_str}</td>'
        f'<td class="num">{alpha_share_str}</td>'
        "</tr>"
    )


h2_table_html = "\n".join([
    h2_row("17자산 챔피언 (2019-08~2026-08, 주표본)", p19),
    h2_row("17자산 챔피언 (2015-01~2026-08, 강건성)", p15),
    h2_row("3자산 근사 SPY+TLT+GLD (2007-07~2026-08, GFC 포함)", p07, has_alpha_share=False),
])

h2_verdict = "기각" if (not p19["sharpe_improved_rolling"] and not p15["sharpe_improved_rolling"]) else "부분채택"

# ---------------------------------------------------------------------------
# HTML 조립
# ---------------------------------------------------------------------------
HTML = f"""<title>챔피언의 정체와 새틀라이트</title>
<style>
{CSS}
</style>

<div class="masthead">
  <div class="masthead-inner">
    <div class="masthead-eyebrow">
      <span>QUANT RESEARCH NOTE</span><span class="dot">·</span><span>Track B 연장 · 가설검증</span><span class="dot">·</span><span>Hypothesis-Driven Study</span>
    </div>
    <h1 class="masthead-title">챔피언의 정체와 새틀라이트 — 17자산 로테이션의 베타 정체성 재심문 + point-in-time 개별주 새틀라이트 실험</h1>
    <p class="masthead-sub">이 저장소가 지금까지 검증한 최고 성과 전략(11개 GICS 섹터+채권+금+국제주식+원자재
      17자산 듀얼모멘텀 로테이션, No.07/08)을 두 방향에서 다시 심문한다. (1) point-in-time으로만 고른
      개별주 새틀라이트를 소액만 얹으면 이 챔피언을 더 낫게 만들 수 있는가 — No.09가 반복한 사후편향
      실수를 반복하지 않고. (2) 이 챔피언의 초과수익 자체가 진짜 실력(알파)인가, 아니면 IREN류 종목
      연구(작업28)가 발견한 것처럼 그냥 위장된 베타인가.</p>
    <div class="masthead-meta">
      <span><b>기준일</b> {esc(GEN)}</span>
      <span><b>챔피언 유니버스</b> 17자산(11 GICS 섹터 ETF+TLT/IEF/GLD+EFA/HYG/DBC)</span>
      <span><b>벤치마크</b> SPY</span>
      <span><b>데이터</b> Yahoo Finance(yfinance) via core.market_data/core.point_in_time_market_cap 로컬 캐시</span>
    </div>
  </div>
</div>

<div class="wrap">

  <nav class="toc">
    <a href="#scope">00 문제 제기</a>
    <a href="#h1">01 H1 — 코어-새틀라이트</a>
    <a href="#h2">02 H2 — 챔피언의 베타 정체성</a>
    <a href="#synthesis">03 종합</a>
    <a href="#limitations">04 한계</a>
  </nav>

  <section class="section" id="scope">
    <h2><span class="sec-no">00</span> 문제 제기 — 이 연구가 지금까지의 무엇을 잇는가</h2>
    <p class="lede">작업19~23이 검증한 17자산 듀얼모멘텀 로테이션(GICS 11섹터+TLT/IEF/GLD+EFA/HYG/DBC,
      top4·12개월 모멘텀·월간 리밸런싱·SPY 200일선 이진 시장필터)은 2008년 금융위기·2000년 닷컴버블·
      2022년 약세장까지 아웃오브샘플로 검증된, 이 저장소의 현재 "챔피언"이다. 작업24/25는 이 챔피언에
      개별주를 섞어 수익을 더 끌어올리려다 사후편향(2026년 기준 AI 랠리 승자를 무의식적으로 우대 선택)에
      걸렸고, point-in-time 시가총액 인프라(<code>core.point_in_time_market_cap</code>)로 재검증하자
      샤프비율이 1.23에서 0.68로 폭락해 개별주 전면 대체 갈래를 공식 기각했다(No.10). 같은 주에 진행된
      작업28(트랙 C)은 IREN류 변동성 테마주에 대해 "베타를 제거하는 헤지는 전부 손해 — 초과수익 자체가
      베타"라는 결론을 냈다.</p>
    <p>이 연구는 두 결론을 챔피언 전략 자체에 정면으로 적용한다. <b>H1</b>은 No.09의 실수(전면 대체·
      사후편향)를 반복하지 않는 다른 설계 — 코어는 그대로 두고 point-in-time으로만 고른 개별주를
      소액 새틀라이트로만 얹으면 여전히 개선 여지가 있는지 — 를 검증한다. <b>H2</b>는 작업28의 베타
      헤지 방법론을 개별 종목이 아니라 챔피언 "포트폴리오 자체"의 일간 수익률 시계열에 그대로 적용해,
      이 저장소가 지금까지 "이겼다"고 불러온 챔피언의 초과수익이 진짜 알파인지 재확인한다.</p>
    <p class="caveat">⚠️ 투자 조언이 아니다. 아래 결과 중 일부(특히 H2)는 챔피언 전략의 성격에 대해
      기존 서술보다 덜 낙관적인 재해석을 담고 있다 — 이 저장소의 원칙대로 그대로 보고한다.</p>
  </section>

  <section class="section" id="h1">
    <h2><span class="sec-no">01</span> H1 — 코어-새틀라이트: point-in-time 개별주가 챔피언을 개선하는가 {verdict_badge(h1_verdict)}</h2>
    <p class="lede">코어(17자산 챔피언, {100-float(blend_high_pct)*100:.0f}~{100-float(blend_low_pct)*100:.0f}%)에
      반기(6개월)마다 <code>sample_universe(as_of_date=t, use_point_in_time_market_cap=True)</code>로 뽑은
      point-in-time 후보 풀(40종목, 섹터균등) 안에서 12개월 모멘텀 상위 3종목을 동일가중으로 담는
      새틀라이트({float(blend_low_pct)*100:.0f}~{float(blend_high_pct)*100:.0f}%)를 얹었다. 검증 구간은
      챔피언의 기존 주 검증 구간(2019-08-12~2026-08-19)과 동일하다.</p>

    <div class="kpi-row">
      <div class="kpi-tile"><div class="kpi-label">코어 단독 샤프</div><div class="kpi-value">{fnum(core_m["sharpe"],3)}</div><div class="kpi-sub">CAGR {fnum(core_m["cagr"],2,True)}% · MDD {fnum(core_m["mdd"],2)}%</div></div>
      <div class="kpi-tile"><div class="kpi-label">새틀라이트 단독 샤프(참고)</div><div class="kpi-value">{fnum(sat_m["sharpe"],3)}</div><div class="kpi-sub">CAGR {fnum(sat_m["cagr"],2,True)}% · MDD {fnum(sat_m["mdd"],2)}%</div></div>
      <div class="kpi-tile"><div class="kpi-label">블렌드 {float(blend_low_pct)*100:.0f}% 샤프</div><div class="kpi-value {'pos' if blend_low['sharpe']>=core_m['sharpe'] else 'neg'}">{fnum(blend_low["sharpe"],3)}</div><div class="kpi-sub">CAGR {fnum(blend_low["cagr"],2,True)}% · MDD {fnum(blend_low["mdd"],2)}%</div></div>
      <div class="kpi-tile"><div class="kpi-label">블렌드 {float(blend_high_pct)*100:.0f}% 샤프</div><div class="kpi-value {'pos' if blend_high['sharpe']>=core_m['sharpe'] else 'neg'}">{fnum(blend_high["sharpe"],3)}</div><div class="kpi-sub">CAGR {fnum(blend_high["cagr"],2,True)}% · MDD {fnum(blend_high["mdd"],2)}%</div></div>
    </div>

    <div class="chart-card">
      <h3>샤프비율 비교 — 코어 vs 새틀라이트 vs 블렌드</h3>
      <p class="chart-desc">블렌드 막대가 코어 막대보다 오른쪽에 있으면 새틀라이트 추가가 실제로 위험조정수익을 개선했다는 뜻이다.</p>
      {h1_sharpe_bar}
    </div>
    <div class="chart-card">
      <h3>칼마지수(MDD 대비 CAGR) 비교</h3>
      {h1_calmar_bar}
    </div>

    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>구성</th><th>CAGR</th><th>MDD</th><th>샤프</th><th>칼마</th><th>누적수익률</th></tr></thead>
        <tbody>{h1_table_html}</tbody>
      </table>
    </div>

    <h3>새틀라이트 반기 리밸런싱 로그 (point-in-time 선정 실제 기록)</h3>
    <p>후보 풀은 매 리밸런싱일마다 <code>core.strategy_tuning.sample_universe(n=40,
      as_of_date=&lt;그 날짜&gt;, use_point_in_time_market_cap=True)</code>로 새로 뽑았다 — "지금 유명한
      종목"이 아니라 "그 시점에 실제로 그 규모였던 종목"만 후보가 된다. 아래 표는 그 point-in-time
      후보 풀 안에서 12개월 모멘텀이 양(+)인 종목 중 상위 3개를 그대로 실은 것이다(사후에 손으로 고른
      종목 없음).</p>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>리밸런싱일</th><th>후보 풀 크기</th><th>양(+)모멘텀 후보 수</th><th>실제 선정 종목</th></tr></thead>
        <tbody>{rebal_log_html}</tbody>
      </table>
    </div>

    <div class="callout">
      <div class="callout-title">해석</div>
      <p>새틀라이트를 10~20%만 얹으면 코어 단독(샤프 {fnum(core_m['sharpe'],2)})보다 두 비중 모두에서
        샤프비율이 개선된다({float(blend_low_pct)*100:.0f}%: {fnum(blend_low['sharpe'],2)},
        {float(blend_high_pct)*100:.0f}%: {fnum(blend_high['sharpe'],2)}) — MDD는 거의 그대로면서
        (코어 {fnum(core_m['mdd'],1)}% → {float(blend_low_pct)*100:.0f}%
        {fnum(blend_low['mdd'],1)}%/{float(blend_high_pct)*100:.0f}% {fnum(blend_high['mdd'],1)}%)
        CAGR은 뚜렷이 오른다({fnum(core_m['cagr'],1)}% → {fnum(blend_low['cagr'],1)}%/{fnum(blend_high['cagr'],1)}%).
        No.09가 걸렸던 함정(사후에 승자였던 종목 위주로 표본이 뽑히는 편향)을 이번엔 반복하지
        않았다는 게 핵심이다 — 위 리밸런싱 로그를 보면 NVDA·TSLA·AVGO처럼 실제로 이 구간 승자였던
        종목도 등장하지만, XOM/COP/CVX(2022-2023 에너지 강세장)·NEM(2026년 금 강세)·GE/CAT(2024-25
        산업재)처럼 그 시점 국면에 맞는 다양한 종목도 함께 뽑혔다 — "미래를 아는 사람이 고른 리스트"가
        아니라 "그 시점 모멘텀 규칙이 실제로 골랐을 리스트"라는 뜻이다. 다만 새틀라이트 단독 성과
        (샤프 {fnum(sat_m['sharpe'],2)}, MDD {fnum(sat_m['mdd'],1)}%)는 코어보다 뚜렷이 변동성이 크므로,
        이 개선은 "새틀라이트가 그 자체로 더 나은 전략"이어서가 아니라 "이미 낮은 변동성의 코어에
        비상관적인 소량의 고변동성 알파를 섞는 분산 효과"로 해석하는 것이 더 정확하다.</p>
    </div>
  </section>

  <section class="section" id="h2">
    <h2><span class="sec-no">02</span> H2 — 챔피언의 베타 정체성: 초과수익은 알파인가 베타인가 {verdict_badge(h2_verdict)}</h2>
    <p class="lede">작업28의 방법론(개별 종목의 롤링 SPY 베타만큼 숏 헤지 → 헤지 전후 샤프 비교)을
      챔피언 "포트폴리오"의 일간 수익률 시계열에 그대로 적용했다. 세 구간에서 독립적으로 검증했다 —
      챔피언의 주 검증 구간(2019-08~2026-08), 더 어려운 확장 구간(2015-01~2026-08, 2018~2019년
      느린 구간 포함), 그리고 2008년 금융위기를 포함하는 3자산(SPY+TLT+GLD) 근사판(2007-07~2026-08,
      작업22 H20 재사용 — 섹터 ETF가 2018년 이후 상장이라 17자산 원판은 2008년까지 못 감).</p>

    <div class="kpi-row">
      <div class="kpi-tile"><div class="kpi-label">평균 롤링 베타(2019~26)</div><div class="kpi-value">{fnum(p19["avg_rolling_beta"],2)}</div><div class="kpi-sub">정적(전체구간) 베타 {fnum(p19["static_full_sample_beta"],2)}, R² {fnum(p19["static_beta_r2"],3)}</div></div>
      <div class="kpi-tile"><div class="kpi-label">무헤지 샤프(2019~26)</div><div class="kpi-value">{fnum(p19["unhedged"]["sharpe"],3)}</div><div class="kpi-sub">SPY {fnum(p19["spy_benchmark"]["sharpe"],3)}</div></div>
      <div class="kpi-tile"><div class="kpi-label">롤링헤지 후 샤프(2019~26)</div><div class="kpi-value neg">{fnum(p19["rolling_hedged"]["sharpe"],3)}</div><div class="kpi-sub">Δ {fnum(p19["sharpe_delta_rolling"],3,True)}</div></div>
      <div class="kpi-tile"><div class="kpi-label">회귀 알파(연율화, 2019~26)</div><div class="kpi-value">{fnum(p19["static_alpha_annualized_pct"],2,True)}%</div><div class="kpi-sub">전체 CAGR의 {fnum(p19["alpha_share_of_total_cagr_pct"],1)}%</div></div>
    </div>

    <div class="chart-card">
      <h3>세 구간 모두: 무헤지 vs 롤링 베타헤지 샤프</h3>
      <p class="chart-desc">헤지 막대(붉은색)가 무헤지 막대(청록색)보다 항상 낮다 — 베타를 물리적으로 제거하면 세 구간 모두 위험조정수익이 나빠진다.</p>
      {h2_sharpe_bar}
    </div>

    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>구간</th><th>평균 롤링베타</th><th>무헤지 샤프</th><th>롤링헤지 샤프</th><th>Δ샤프</th><th>무헤지 MDD</th><th>회귀알파(연율)</th><th>알파/전체CAGR</th></tr></thead>
        <tbody>{h2_table_html}</tbody>
      </table>
    </div>

    <div class="callout">
      <div class="callout-title">초과수익 분해</div>
      <p>2019~2026 주표본에서 챔피언의 CAGR({fnum(p19['unhedged']['cagr_pct'],2)}%)은 SPY({fnum(p19['spy_benchmark']['cagr_pct'],2)}%)와
        원금 기준으로는 거의 같다(격차 {fnum(p19['excess_return_vs_spy_cagr_pct'],2,True)}%p) — 이 구간에서
        챔피언의 진짜 우위는 원금 수익률이 아니라 <b>위험조정 수익률과 낙폭</b>이다(샤프
        {fnum(p19['unhedged']['sharpe'],2)} vs {fnum(p19['spy_benchmark']['sharpe'],2)}, MDD
        {fnum(p19['unhedged']['mdd_pct'],1)}% vs {fnum(p19['spy_benchmark']['mdd_pct'],1)}%). 단일요인
        회귀(젠센 알파)로 베타를 통계적으로 통제하면 연율 {fnum(p19['static_alpha_annualized_pct'],2,True)}%의
        알파가 남는다 — 전체 CAGR의 {fnum(p19['alpha_share_of_total_cagr_pct'],1)}%에 해당하는, 결코 작지
        않은 몫이다. 그런데도 그 베타를 실제로 롤링 헤지로 걷어내면(H1 방법론 그대로) 샤프가
        {fnum(p19['unhedged']['sharpe'],3)}→{fnum(p19['rolling_hedged']['sharpe'],3)}로 오히려 나빠진다 —
        2015~2026 강건성 표본과 2007~2026(3자산 근사, GFC 포함) 구간 모두 같은 방향으로 재현됐다.</p>
      <p>이 두 사실은 겉보기엔 모순 같지만 같이 읽으면 하나의 결론으로 수렴한다: 통계적으로 정의된
        "알파"(회귀 절편)는 실재하지만, 그 알파는 베타 노출과 분리된 별도의 신호가 아니라 <b>"베타
        노출의 크기를 시점마다 동적으로 조절하는 것 자체"</b>에서 나온다(시장필터가 SPY 약세 국면에
        비중을 50%로 줄이고, 모멘텀 랭킹이 자산군 간 베타를 이동시킨다 — 2020년 4월엔 채권·금으로,
        2022년엔 원자재·에너지로). 고정 배율의 롤링 베타 숏 오버레이는 이 "동적 타이밍"을 정적인
        상시 헤지로 뭉개버려 정확히 그 가치를 없앤다. 즉 <b>베타와 알파를 물리적으로 분리할 수는
        없다 — 이 전략에서는 베타의 타이밍 자체가 알파다.</b></p>
    </div>
  </section>

  <section class="section" id="synthesis">
    <h2><span class="sec-no">03</span> 종합 — "시장을 이긴다"는 것에 대해 이번 라운드가 더한 것</h2>
    <p>이 저장소는 작업19부터 지금까지 "시장을 이긴다"는 말의 의미를 계속 좁혀왔다 — 처음엔 단순
      원금수익률(작업19), 그다음엔 위험조정수익률(작업20/21), 그다음엔 아웃오브샘플 강건성(작업22/23),
      그다음엔 그 우위가 사후편향이 아닌지(작업24/25/No.09/10)였다. 이번 라운드는 거기에 두 가지를
      더한다.</p>
    <p><b>첫째(H1), "코어를 지키고 새틀라이트로만 개별주를 더하면" 사후편향 없이도 개선 여지가 있다.</b>
      No.09/10이 확정한 결론("개별주로 챔피언을 통째로 대체하면 안 된다")은 여전히 유효하지만, 이번
      결과는 그 결론이 "개별주는 전혀 도움이 안 된다"는 뜻은 아니었음을 보여준다 — 비중을 작게 유지하고
      point-in-time 규율을 지키면, 개별주는 코어의 낮은 변동성을 거의 해치지 않으면서 수익을 끌어올리는
      분산 효과를 낼 수 있다. "전부 바꾸느냐 전혀 안 쓰느냐"가 아니라 "얼마나 섞느냐"가 진짜 질문이었다.</p>
    <p><b>둘째(H2), 챔피언의 초과수익 자체가 "시장을 이긴다"는 서술이 암시하는 만큼 깔끔한 알파가
      아니다.</b> 이 저장소는 지금까지 챔피언의 샤프비율·MDD 우위를 "전략의 실력"으로 서술해왔다(작업21의
      순열검정도 "무작위 자산 선택 대비 우위"를 확인했을 뿐, 베타 노출 자체의 기여는 따로 떼어보지
      않았다). 이번에 처음으로 베타를 물리적으로 제거해보니, 세 개의 독립된 구간(2019~2026·2015~2026·
      2007~2026 GFC 포함) 모두에서 헤지가 샤프비율을 깎았다 — 작업28이 IREN류 개별 테마주에서 낸
      결론과 정확히 같은 방향이다. 다만 개별주 사례와 다른 결이 하나 있다 — 회귀 알파(젠센 알파)
      자체는 통계적으로 작지 않게 남는다(2019~2026 구간 기준 전체 CAGR의 약
      {fnum(p19['alpha_share_of_total_cagr_pct'],0)}%). 이 저장소가 얻은 가장 정확한 문장은
      "챔피언의 초과수익은 베타가 전부다"가 아니라, <b>"챔피언의 알파는 베타 노출을 언제·얼마나
      가져갈지 국면에 따라 조절하는 능력 그 자체이며, 그래서 베타와 알파를 물리적으로 분리하려는
      시도(정적 숏 헤지)는 그 알파의 원천을 파괴한다"</b>는 것이다. "시장을 이긴다"는 건 이 전략에서는
      시장 익스포저를 없애는 게 아니라 그 익스포저의 크기를 국면에 맞게 조절하는 능력이었다.</p>
  </section>

  <section class="section" id="limitations">
    <h2><span class="sec-no">04</span> 한계</h2>
    <ul>
      <li><b>새틀라이트 반기 리밸런싱의 표본 크기</b> — 2019~2026 구간에 14회 리밸런싱뿐이라, 특정
        2~3회의 좋거나 나쁜 픽이 전체 결과를 좌우할 수 있다(예: 2020-2021년 반기에 반복 등장한
        NVDA/TSLA/AAPL). 순열검정 등 통계적 유의성 검정은 이번 범위에 포함하지 않았다.</li>
      <li><b>point-in-time 시가총액의 알려진 근사 오차</b> — <code>core/point_in_time_market_cap.py</code>
        자체 문서화된 한계(발행주식수는 분기 단위 계단식 데이터, 상장 초기 이력 부재 종목은 근사)가
        새틀라이트 후보 풀에도 그대로 적용된다.</li>
      <li><b>코어·새틀라이트 블렌드의 단순화</b> — 두 슬리브를 일별로 비용 없이 정확히 목표 비중대로
        재조정한다고 가정한 선형 블렌드다. 실제로는 슬리브 간 리밸런싱에도 거래비용이 든다.</li>
      <li><b>H1을 2008년 금융위기·2000년 닷컴버블까지 확장하지 못함</b> — point-in-time 유니버스
        표본추출이 회당 약 1분(500종목 스캔) 걸려, 반기 리밸런싱을 두 시기까지 확장하면 계산비용이
        커 이번 라운드 예산 안에서는 2019~2026 주 구간에 집중했다. 코어(H2)는 세 구간 모두 검증했지만
        새틀라이트(H1)는 아니라는 비대칭이 있다.</li>
      <li><b>H2 헤지 시뮬레이션의 표준 한계</b> — 공매도 차입비용·마진 이자·헤지 리밸런싱 자체의
        거래비용 미반영(작업28과 동일 한계). 베타 추정 롤링윈도우(126거래일) 선택에 따라 결과가
        달라질 수 있다(민감도 분석은 이번 범위 밖).</li>
      <li><b>다중비교 위험</b> — 이 저장소가 지금까지 수십 개의 파라미터/구조 변형을 같은 챔피언
        후보에 반복 검증해왔다는 근본적 한계(작업21이 이미 명시)는 이번 연구에도 그대로 적용된다.</li>
    </ul>
  </section>

</div>

<footer>
  <p>analysis/2026-08-19_champion_beta_and_satellite_research/ (데이터: report_data.json, 빌드:
    build_report.py) · champion_strategy.py/h1_core_satellite.py/h2_champion_beta_hedge.py가
    core.market_data/core.point_in_time_market_cap/core.strategy_tuning의 로컬 캐시로 실제 가격·
    point-in-time 시가총액 데이터를 받아 실행한 결과를 그대로 사용했다(추정치 아님). 원 챔피언 스크립트
    (작업19~23)는 연구용 스크래치라 삭제되어, 이 리포트의 champion_strategy.py는 PROGRESS.md에 기록된
    스펙을 독립적으로 재구현한 것이다 — 발표 수치가 원 리포트와 소수점 단위로 다를 수 있으나 2019-08-12~
    2026-08-19 구간에서 방향과 크기가 일치함을 SPY 대조군으로 교차검증했다.</p>
</footer>
"""

out_file = f"{OUT_DIR}/final_report.html"
with open(out_file, "w", encoding="utf-8") as f:
    f.write(HTML)
print(f"작성 완료: {out_file} ({len(HTML):,} bytes)")
