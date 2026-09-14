#!/usr/bin/env python3
"""report_data.json + ticker_info.json을 읽어 final_report.html을 만든다.

analysis/2026-08-16_tenbagger_stock_picking/build_report.py 와 동일한 CSS 디자인 시스템(다크네이비
/올리브 톤, 세리프 헤드라인, TOC, 섹션 번호)을 그대로 재사용한다 — 트랙 C 두 번째 리포트이므로
시각적 일관성을 맞춘다.
"""
import json
import math
import os

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

with open(f"{OUT_DIR}/report_data.json", encoding="utf-8") as f:
    R = json.load(f)
with open(f"{OUT_DIR}/ticker_info.json", encoding="utf-8") as f:
    INFO = json.load(f)

GEN_DATE = "2026-08-19"


def fnum(v, digits=1, signed=False):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    s = f"{v:,.{digits}f}"
    if signed and v > 0:
        s = "+" + s
    return s


def fmoney_b(v):
    if v is None:
        return "—"
    return f"${v/1e9:,.1f}B"


def fpct(v, digits=1):
    if v is None:
        return "—"
    return f"{v*100:,.{digits}f}%"


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def mrow(label, m, cls=""):
    """metrics dict -> 표 한 행 (지표: cumulative_return/cagr/mdd/sharpe/calmar)."""
    return (
        f'<tr class="{cls}"><td class="tk-cell"><span class="tk-name">{esc(label)}</span></td>'
        f'<td class="num">{fnum(m.get("cumulative_return"),1,True)}%</td>'
        f'<td class="num">{fnum(m.get("cagr"),1,True)}%</td>'
        f'<td class="num">{fnum(m.get("mdd"),1)}%</td>'
        f'<td class="num strong">{fnum(m.get("sharpe"),2)}</td>'
        f'<td class="num">{fnum(m.get("calmar"),2)}</td>'
        "</tr>"
    )


# ---------------------------------------------------------------------------
# CSS — tenbagger 리포트와 동일한 디자인 시스템
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
  font-size: clamp(28px, 4.2vw, 44px); line-height:1.15; margin: 14px 0 10px; text-wrap: balance; max-width: 20ch; }
.masthead-sub{ font-size:16.5px; max-width:66ch; opacity:0.92; margin:0 0 22px; }
.masthead-meta{ display:flex; flex-wrap:wrap; gap: 10px 26px; font-size:13.5px; opacity:0.85;
  border-top:1px solid rgba(255,255,255,0.22); padding-top:16px; }
.masthead-meta b{ font-weight:600; }
.section{ padding: 52px 0 8px; border-top:1px solid var(--hairline); }
.section:first-of-type{ border-top:none; }
.section h2{ font-family:"Iowan Old Style","Palatino Linotype", Georgia, serif; font-size: 25px;
  font-weight:600; margin: 0 0 16px; display:flex; align-items:baseline; gap:12px; }
.sec-no{ font-family: ui-monospace, "SF Mono", Consolas, monospace; font-size:13px; color: var(--accent);
  border:1px solid var(--accent); border-radius:3px; padding:2px 6px; font-weight:600; letter-spacing:0.02em; }
.section h3{ font-size:17.5px; margin: 30px 0 10px; font-weight:650; }
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
.formula-box{ background:var(--code-bg); border:1px solid var(--hairline); border-radius:8px;
  padding:18px 22px; margin: 16px 0; overflow-x:auto; }
.formula-box .f-line{ font-family: ui-monospace,"SF Mono",Consolas,monospace; font-size:15px;
  color:var(--ink); white-space:nowrap; margin: 4px 0; }
.formula-box .f-note{ font-size:12.5px; color:var(--ink-muted); margin-top:8px; font-family: system-ui,-apple-system,sans-serif; white-space:normal; }
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
table.data-table .th-sub{ text-transform:none; font-weight:400; letter-spacing:0; font-size:10.5px; display:block; }
table.data-table th:first-child, table.data-table td:first-child{ text-align:left; }
table.data-table td{ padding:8px 12px; border-bottom:1px solid var(--hairline); text-align:right; white-space:nowrap; }
table.data-table tbody tr:hover{ background:var(--surface-2); }
table.data-table tbody tr:last-child td{ border-bottom:none; }
td.tk-cell{ text-align:left !important; }
td.tk-cell .tk-name{ font-weight:650; margin-right:8px; }
td.tk-cell .tk-sector{ font-size:11.5px; color:var(--ink-muted); font-family: system-ui,-apple-system,sans-serif; }
td.ctr{ text-align:center !important; }
td.num.delta.pos, .delta.pos{ color:var(--delta-pos); font-weight:650; }
td.num.delta.neg, .delta.neg{ color:var(--delta-neg); font-weight:650; }
.strong{ font-weight:700; }
tr.best-row{ background: var(--accent-soft); }
tr.trend-down td.trend-cell{ color:var(--delta-neg); }
tr.trend-up td.trend-cell{ color:var(--delta-pos); }
footer{ max-width:920px; margin:40px auto 0; padding: 26px 24px 10px; border-top:1px solid var(--hairline);
  font-size:12.5px; color:var(--ink-muted); }
footer p{ max-width:none; }
.toc{ display:flex; flex-wrap:wrap; gap:8px 18px; margin: 24px 0 4px; padding:16px 20px; background:var(--surface);
  border:1px solid var(--hairline); border-radius:8px; }
.toc a{ font-size:13.5px; color:var(--ink-2); text-decoration:none; }
.toc a:hover{ color:var(--accent); text-decoration:underline; }
.tier-grid{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:14px; margin:18px 0; }
.tier-card{ background:var(--surface); border:1px solid var(--hairline); border-radius:8px; padding:16px 18px; }
.tier-card h4{ margin:0 0 8px; font-size:14px; color:var(--ink); }
.tier-card .tier-range{ font-family: ui-monospace,"SF Mono",Consolas,monospace; font-size:20px; font-weight:700; color:var(--accent); }
.tier-card .tier-sub{ font-size:12px; color:var(--ink-muted); margin-top:4px; }
.src-list{ font-size:13px; color:var(--ink-2); padding-left:18px; }
.src-list li{ margin: 6px 0; }
.checklist{ list-style:none; padding-left:0; margin:18px 0; }
.checklist li{ padding: 10px 0 10px 30px; position:relative; border-bottom:1px solid var(--hairline); max-width:none; }
.checklist li:last-child{ border-bottom:none; }
.checklist li::before{ content:"✓"; position:absolute; left:0; top:10px; color:var(--accent); font-weight:700; }
"""

# ---------------------------------------------------------------------------
# 01 — 바스켓 개요 표 (ticker_info.json 실측)
# ---------------------------------------------------------------------------
TICKER_NAMES = {
    "IREN": "IREN Limited (구 Iris Energy)", "CIFR": "Cipher Mining (Cipher Digital)",
    "CLSK": "CleanSpark", "WULF": "TeraWulf", "HUT": "Hut 8", "BTDR": "Bitdeer Technologies",
    "CORZ": "Core Scientific", "MARA": "MARA Holdings", "RIOT": "Riot Platforms",
}
PIVOT_BASKET = R["main_basket"]
CONTRAST_BASKET = list(R["contrast_basket_buy_hold"].keys())
LISTING = R["listing_dates"]

basket_rows = []
for t in PIVOT_BASKET + ["CORZ"] + CONTRAST_BASKET:
    info = INFO.get(t) or {}
    role = "피벗(채굴→AI)" if t in PIVOT_BASKET + ["CORZ"] else "대조군(채굴 비중 우세)"
    basket_rows.append(
        f'<tr><td class="tk-cell"><span class="tk-name">{esc(t)}</span>'
        f'<span class="tk-sector">{esc(TICKER_NAMES.get(t, ""))}</span></td>'
        f'<td class="num">{esc(role)}</td>'
        f'<td class="num">{esc(LISTING.get(t, "—"))}</td>'
        f'<td class="num">{fmoney_b(info.get("marketCap"))}</td>'
        f'<td class="num strong">{fnum(info.get("beta"),2)}</td>'
        f'<td class="num">{fpct(info.get("shortPercentOfFloat"))}</td>'
        f'<td class="num">{fpct(info.get("heldPercentInstitutions"))}</td>'
        f'<td class="num">{fnum((info.get("averageVolume") or 0)/1e6,1)}M</td>'
        "</tr>"
    )
basket_table_html = "\n".join(basket_rows)

avg_beta = sum(INFO[t]["beta"] for t in PIVOT_BASKET + ["CORZ"] if INFO.get(t) and INFO[t].get("beta")) / len([t for t in PIVOT_BASKET + ["CORZ"] if INFO.get(t) and INFO[t].get("beta")])
avg_short = sum(INFO[t]["shortPercentOfFloat"] for t in PIVOT_BASKET + ["CORZ"] if INFO.get(t) and INFO[t].get("shortPercentOfFloat")) / len([t for t in PIVOT_BASKET + ["CORZ"] if INFO.get(t) and INFO[t].get("shortPercentOfFloat")])

# ---------------------------------------------------------------------------
# 06 — 베이스라인 비교 표
# ---------------------------------------------------------------------------
baseline_rows = "\n".join([
    mrow(f'IREN 매수후보유 (상장일 {LISTING["IREN"]}~)', R["iren_buy_hold"]["metrics"]),
    mrow(f'IREN 매수후보유 (공통구간 {R["main_basket_start"]}~)', R["iren_buy_hold_common_window"]["metrics"], "best-row"),
    mrow(f'바스켓({len(PIVOT_BASKET)}종) 균등보유 (정적)', R["basket_static_buy_hold"]["metrics"], "best-row"),
    mrow("바스켓 균등보유 (일별 리밸런싱, 참고)", R["basket_daily_rebalanced_hold"]["metrics"]),
    mrow("SPY 매수후보유", R["spy_buy_hold"]["metrics"]),
    mrow("BTC-USD 매수후보유", R["btc_buy_hold"]["metrics"]),
])

# ---------------------------------------------------------------------------
# 07 — 모멘텀 로테이션 스윕 표
# ---------------------------------------------------------------------------
rot_sweep_rows = []
for row in R["rotation_sweep"]:
    is_main = row["momentum_window"] == R["momentum_window_days"] and row["top_n"] == R["top_n"]
    rot_sweep_rows.append(
        f'<tr class="{"best-row" if is_main else ""}">'
        f'<td class="tk-cell"><span class="tk-name">{row["momentum_window"]}일 / top{row["top_n"]}</span>'
        f'<span class="tk-sector">시작 {row["start"]}</span></td>'
        f'<td class="num">{fnum(row["cumulative_return"],1,True)}%</td>'
        f'<td class="num">{fnum(row["cagr"],1,True)}%</td>'
        f'<td class="num">{fnum(row["mdd"],1)}%</td>'
        f'<td class="num strong">{fnum(row["sharpe"],2)}</td>'
        f'<td class="num">{fnum(row["calmar"],2)}</td>'
        "</tr>"
    )
rot_sweep_html = "\n".join(rot_sweep_rows)

# ---------------------------------------------------------------------------
# 08 — 추세추종 스윕 표
# ---------------------------------------------------------------------------
tf_rows = []
for row in R["trend_following_sweep"]:
    scope_label = "IREN 단일" if row["scope"] == "IREN_single" else "바스켓"
    is_best = row["stop_pct"] == R["trend_following_best"]["stop_pct"]
    tf_rows.append(
        f'<tr class="{"best-row" if is_best else ""}">'
        f'<td class="tk-cell"><span class="tk-name">스탑 {row["stop_pct"]*100:.0f}%</span>'
        f'<span class="tk-sector">{scope_label}</span></td>'
        f'<td class="num">{fnum(row["cumulative_return"],1,True)}%</td>'
        f'<td class="num">{fnum(row["cagr"],1,True)}%</td>'
        f'<td class="num">{fnum(row["mdd"],1)}%</td>'
        f'<td class="num strong">{fnum(row["sharpe"],2)}</td>'
        f'<td class="num">{fnum(row["calmar"],2)}</td>'
        f'<td class="num">{row.get("trade_count",0) if row["scope"]=="IREN_single" else "—"}</td>'
        "</tr>"
    )
tf_sweep_html = "\n".join(tf_rows)

# ---------------------------------------------------------------------------
# 09 — 변동성타게팅 오버레이 표
# ---------------------------------------------------------------------------
vt_rows = []
for row in R["vol_target_sweep"]:
    vt_rows.append(
        f'<tr><td class="tk-cell"><span class="tk-name">목표vol {row["target_vol"]:.0f}%</span>'
        f'<span class="tk-sector">상한 {row["cap"]:.1f}x</span></td>'
        f'<td class="num">{fnum(row["cumulative_return"],1,True)}%</td>'
        f'<td class="num">{fnum(row["cagr"],1,True)}%</td>'
        f'<td class="num">{fnum(row["mdd"],1)}%</td>'
        f'<td class="num strong">{fnum(row["sharpe"],2)}</td>'
        f'<td class="num">{fnum(row["calmar"],2)}</td>'
        "</tr>"
    )
vt_sweep_html = "\n".join(vt_rows)
champion_label = "추세추종(돈치안+트레일링스탑) 바스켓" if R["champion"] == "trend_following_basket" else "모멘텀 로테이션"
champion_no_overlay = R["champion_no_overlay"]

# ---------------------------------------------------------------------------
# 10 — 강건성 체크 표
# ---------------------------------------------------------------------------
robust_rows = "\n".join([
    mrow(f'CORZ 포함 7종 모멘텀로테이션 ({R["robustness_with_corz"]["start"]}~)', R["robustness_with_corz"]["momentum_rotation"]),
    mrow(f'CORZ 포함 7종 정적균등보유 ({R["robustness_with_corz"]["start"]}~)', R["robustness_with_corz"]["static_buy_hold"], "best-row"),
    mrow(f'피벗+대조군 8종 정적균등보유 ({R["all8_incl_contrast"]["start"]}~)', R["all8_incl_contrast"]["static_buy_hold"]),
    mrow(f'피벗+대조군 8종 모멘텀로테이션 ({R["all8_incl_contrast"]["start"]}~)', R["all8_incl_contrast"]["momentum_rotation"]),
])
contrast_rows = []
for t, d in R["contrast_basket_buy_hold"].items():
    contrast_rows.append(mrow(f'{t} 매수후보유 (전체이력 {d["listing_date"]}~)', d["full_history"]))
    contrast_rows.append(mrow(f'{t} 매수후보유 (공통구간 {R["main_basket_start"]}~)', d["common_window"]))
contrast_rows_html = "\n".join(contrast_rows)

FF = R["fixed_fractional_example"]

HTML = f"""<title>변동성 테마주 실전 매매법 연구</title>
<style>
{CSS}
</style>

<div class="masthead">
  <div class="masthead-inner">
    <div class="masthead-eyebrow">
      <span>QUANT RESEARCH NOTE</span><span class="dot">·</span><span>Track C · No.2 · 2026-08</span><span class="dot">·</span><span>Empirical Backtest</span>
    </div>
    <h1 class="masthead-title">IREN류 변동성 테마주 — 특징과 실전 매매법 실증 연구</h1>
    <p class="masthead-sub">지난 트랙 C 리포트(텐베거 발굴)가 스스로 밝힌 한계 — "S&amp;P500 유니버스가
      진짜 소형·테마 종목을 구조적으로 배제한다" — 를 정면으로 다룬다. 비트코인 채굴에서 AI/HPC
      데이터센터로 피벗한 종목 바스켓을 실제로 구성하고, 이 저장소의 백테스트 엔진으로 매수후보유·
      모멘텀 로테이션·추세추종·변동성타게팅 네 가지를 실측 비교한다.</p>
    <div class="masthead-meta">
      <span><b>피벗 바스켓</b> {esc(", ".join(PIVOT_BASKET))} (+ CORZ 별도 표기)</span>
      <span><b>대조군</b> {esc(", ".join(CONTRAST_BASKET))}</span>
      <span><b>백테스트 공통구간</b> {esc(R["main_basket_start"])} ~ {esc(R["main_basket_end"])}</span>
      <span><b>거래비용</b> 편도 {R["meta"]["fee_bps_oneway"]:.0f}bp (왕복 {R["meta"]["round_trip_cost_pct"]:.2f}%)</span>
    </div>
  </div>
</div>

<div class="wrap">

  <nav class="toc">
    <a href="#scope">00 개요</a>
    <a href="#basket">01 피벗 바스켓 실측</a>
    <a href="#why-volatile">02 왜 이렇게 변동성이 큰가</a>
    <a href="#control-group">03 "순수" 채굴주가 남아있는가</a>
    <a href="#academic">04 학계의 경고 — 복권주 효과</a>
    <a href="#methodology">05 백테스트 설계</a>
    <a href="#baseline">06 베이스라인 결과</a>
    <a href="#rotation">07 모멘텀 로테이션 결과</a>
    <a href="#trend">08 추세추종 결과</a>
    <a href="#voltarget">09 변동성타게팅 오버레이</a>
    <a href="#robustness">10 강건성 체크</a>
    <a href="#framework">11 종합 프레임워크</a>
    <a href="#conclusion">12 한계와 솔직한 결론</a>
    <a href="#sources">부록: 출처</a>
  </nav>

  <section class="section" id="scope">
    <h2><span class="sec-no">00</span> 개요 — 왜 이 리서치인가</h2>
    <p class="lede">지난 리포트(<code>tenbagger_stock_picking_research.html</code>)는 S&amp;P500
      유니버스에 그레이엄·린치·품질팩터 기준의 스크리닝을 실제로 돌려봤더니, 가장 뜨거운 섹터
      (정보기술)에서 시가총액 상한을 통과한 종목이 <b>하나도 없었다</b>는 결과로 끝났다 — S&amp;P500
      스코프 자체가 진짜 소형·테마 종목(IREN 같은)을 구조적으로 배제한다는 뜻이다. 이번 리포트는 그
      배제된 영역을 정면으로 다룬다. 사용자가 "이런 유형의 종목을 사는 것을 좋아한다"고 밝힌 그대로,
      두 가지를 다룬다:</p>
    <ol>
      <li><b>IREN 같은 종목의 특징</b> — 왜 이렇게 변동성이 큰지를 실제 재무·시장 데이터와 학술
        문헌으로 뒷받침한다.</li>
      <li><b>이런 변동성 큰 종목으로 최대한 벌 수 있는 방법</b> — 문헌 정리에 그치지 않고 이 저장소의
        실제 백테스트 엔진(<code>core.backtest_engine</code>, <code>core.position_sizing</code>)으로
        매수후보유·모멘텀 로테이션·추세추종·변동성타게팅을 직접 실행해 비교한다.</li>
    </ol>
    <p class="caveat">⚠️ 이 리포트는 투자 조언이 아니다. 09~10장에서 다루는 학술 문헌은 사용자가
      선호하는 이런 유형의 종목이 장기·위험조정 기준으로는 오히려 저조할 수 있다는, 이 리포트의
      결론과 정면으로 긴장 관계에 있는 내용을 포함한다 — 편하게 걸러내지 않고 그대로 싣는다.</p>
  </section>

  <section class="section" id="basket">
    <h2><span class="sec-no">01</span> 피벗 바스켓 — 실제로 확인한 종목들</h2>
    <p class="lede">"비트코인 채굴 → AI/HPC 데이터센터 피벗" 테마의 대표 종목을 웹 리서치로 확인했다.
      2026년 기준 이 섹터는 채굴사가 AI 컴퓨트 임대로 전환하는 것이 사실상 업계 표준 서사가 됐다 —
      전력 인프라(변전소·냉각·부지)를 GPU 워크로드로 재활용하면 같은 메가와트당 매출이 채굴보다
      훨씬 크다는 것이 공통 논리다(1MW당 매출 비교는 02장 참고).</p>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>종목</th><th>구분</th><th>상장(재상장)일</th><th>시가총액</th><th>베타</th>
          <th>공매도/유통주식</th><th>기관보유율</th><th>일평균거래량</th></tr></thead>
        <tbody>{basket_table_html}</tbody>
      </table>
    </div>
    <p class="fig-caption">2026-08-19 기준 yfinance 실측치(<code>.info</code>). CORZ(Core Scientific)는
      2022년 파산보호(Chapter 11) 이후 2024-01-24 재상장이라 다른 종목과 상장 배경이 달라 메인
      백테스트 바스켓에서는 별도로 분리했다(10장에서 포함 시 강건성만 별도 확인).</p>
    <p>피벗 바스켓 7종(CORZ 포함) 평균 베타는 <b>{avg_beta:.2f}</b>, 평균 공매도 비중은
      <b>{avg_short*100:.1f}%</b>다 — S&amp;P500 평균 베타(정의상 1.0)의 4배 이상이고, 공매도 비중은
      일반적으로 "숏스퀴즈 후보"로 분류되는 기준(유통주식 대비 20%대)을 넘나든다. HUT(베타 6.11)·
      MARA(5.36)·CORZ(5.59)는 시장이 1% 움직일 때 이론상 5~6% 움직인다는 뜻이다.</p>
  </section>

  <section class="section" id="why-volatile">
    <h2><span class="sec-no">02</span> 왜 이렇게 변동성이 큰가 — 자본구조와 서사</h2>
    <h3>부채로 짓는 GPU 팜 — IREN의 실제 자본구조</h3>
    <p>IREN은 2026년 6월 마이크로소프트와 5년간 약 <b>97억 달러</b> 규모의 GPU 클라우드 계약(엔비디아
      GB300 GPU, 텍사스 차일드리스 750MW 캠퍼스에 단계적 배치)을 체결했다. 이를 뒷받침하기 위해
      델(Dell)과 <b>58억 달러</b> 규모 GPU 구매계약을 맺었고, 이 구매대금의 96%를 <b>36.5억 달러</b>
      투자등급 GPU 파이낸싱(SOFR+2.13%의 21.0억 달러 사모사채 + SOFR+2.25%의 15.5억 달러 지연인출
      텀론)으로 조달했다. 즉 이 섹터의 성장은 <b>고객 선수금 + 신규 부채 + 전환사채</b>로 짓는 구조이지,
      기존 잉여현금흐름으로 짓는 구조가 아니다 — 우리가 실측한 표(01장)에서 총부채가 총현금을 크게
      웃도는 종목이 많은 이유(예: HUT 부채 76.7억 달러 vs 현금 2.3억 달러)이기도 하다.</p>
    <h3>업계 전체의 공통 서사 — "1MW당 매출이 다르다"</h3>
    <p>업계 추정으로 이 피벗은 2026년까지 최대 <b>400억 달러</b> 규모 매출 기회로, 이미 <b>700억
      달러</b> 넘는 AI/HPC 계약이 체결됐고 일부 채굴사는 2026년 말까지 매출의 최대 70%를 AI에서
      낼 것으로 전망된다. HIVE의 추정치가 이 서사를 압축한다 — 엔비디아 H100 GPU 10MW가 비트코인
      채굴 100MW와 비슷한 매출을 낸다는 것이다. 반대로 채굴 자체의 경제성은 나빠지고 있다 — 상장
      채굴사들이 코인 1개를 캐는 데 평균 약 1.9만 달러의 손실을 보고 있다는 업계 분석도 있다. 이
      "채굴은 밑지고 AI는 남는다"는 단순하지만 강력한 서사가 주가를 이끄는 핵심 동력이다.</p>
    <h3>변동성의 구조적 원인 3가지</h3>
    <ul>
      <li><b>이중 베타 노출</b> — 이 종목들은 비트코인 가격(채굴 매출)과 AI/반도체 테마(밸류에이션
        멀티플) 두 축에 동시에 노출된다. 두 자산군 다 자체로 변동성이 큰데, 이 종목은 그 둘의
        곱집합에 가깝다.</li>
      <li><b>서사·촉매 중심 가격형성</b> — 대형 AI 계약 발표(예: IREN-MSFT, Hut8-Anthropic $178억
        규모, Cipher-AWS 15년 리스) 하나가 주가를 하루에 수십% 움직인다 — 실적 발표보다 계약
        발표가 더 큰 촉매인 경우가 많다(binary event risk).</li>
      <li><b>희석 리스크</b> — GPU 팜 구축비가 워낙 커서 전환사채·신주 발행으로 자금을 조달하는
        경우가 잦고, 이는 기존 주주 지분을 희석시킨다 — 좋은 소식(대형 계약)이 동시에 나쁜 소식
        (대규모 자금조달)을 동반하는 경우가 흔하다.</li>
    </ul>
  </section>

  <section class="section" id="control-group">
    <h2><span class="sec-no">03</span> "순수" 채굴주가 남아있는가 — 조사 결과부터 정직하게</h2>
    <p class="lede">원래 계획은 "피벗 안 한 순수 채굴주"를 대조군으로 쓰는 것이었다(예: MARA, RIOT).
      실제로 조사해보니 <b>2026년 기준 이 구분 자체가 거의 무너졌다</b> — 정직하게 보고한다.</p>
    <ul>
      <li><b>MARA Holdings</b> — 순수 채굴에서 AI/HPC 인프라로 피벗 중이라고 보도된다.</li>
      <li><b>Riot Platforms</b> — AMD와의 10년 데이터센터 리스가 2026년 1월부터 실제 매출을 내기
        시작했다.</li>
      <li><b>Bitfarms</b> — 아예 2027년까지 채굴을 단계적으로 접고 AI/HPC로 완전히 전환한다고
        발표했다(1.28억 달러 데이터센터 계약, 2026-12 완공 목표).</li>
    </ul>
    <p>즉 "채굴사가 AI로 피벗한다"는 서사가 예외가 아니라 <b>업계 표준</b>이 됐다 — 미너 주가가
      2026년 들어 현물 비트코인보다 더 크게 오른 이유도 투자자들이 이들을 "코인 프록시"가 아니라
      "데이터센터 개발사"로 재평가했기 때문이라는 분석이 있다. 이 리포트에서는 MARA·RIOT을
      완전한 무피벗 대조군이 아니라 <b>"상대적으로 채굴 매출 비중이 여전히 큰" 대조군</b>으로
      재정의해서 쓴다 — 순수한 반사실적(counterfactual) 대조군은 이 섹터에 사실상 존재하지 않는다는
      것 자체가 하나의 발견이다. 10장에서 이 둘의 매수후보유 성과를 별도로 싣는다.</p>
    <p class="caveat">⚠️ 이는 "피벗 여부가 알파를 설명한다"는 가설을 이 데이터로는 깨끗하게
      검증할 수 없다는 뜻이다 — 처치군과 대조군이 이미 상당히 겹친다.</p>
  </section>

  <section class="section" id="academic">
    <h2><span class="sec-no">04</span> 학계의 경고 — 복권주(lottery stock) 효과</h2>
    <p class="lede">02~03장이 "왜 이런 종목이 매력적으로 보이는가"를 다뤘다면, 이 장은 정반대
      방향의 실증 연구를 정직하게 소개한다. 이 저장소의 다른 리포트들과 같은 정직성 기준을
      적용한다 — 사용자가 좋아하는 유형의 종목에 학계가 제기하는 진짜 경고다.</p>
    <h3>MAX 효과 — Bali, Cakici, Whitelaw (2011)</h3>
    <p>Turan Bali, Nusret Cakici, Robert Whitelaw의 &lt;Maxing Out: Stocks as Lotteries and the
      Cross-Section of Expected Returns&gt;(<i>Journal of Financial Economics</i>, 2011)는 최근
      1개월간 일일 최고수익률(MAX)이 높았던 종목일수록 다음 달 평균수익률이 <b>낮다</b>는 것을
      보였다 — MAX 최하위 10분위와 최상위 10분위의 위험조정 후 수익률 차이가 월 1%를 넘는다.
      해석은 직관에 반한다 — 투자자들이 복권 같은(작은 확률로 크게 터지는) payoff를 가진 종목을
      과도하게 선호해서 가격을 미리 밀어올리고, 그 결과 <b>기대수익률이 오히려 깎인다</b>는 것이다.
      비트코인 채굴-AI 피벗주처럼 "다음 대형 계약 발표 하나로 주가가 며칠 만에 배가 될 수 있다"는
      구조는 이 MAX 효과가 정의하는 복권형 payoff와 정확히 일치한다.</p>
    <h3>이디오싱크래틱 변동성 퍼즐 — Ang, Hodrick, Xing, Zhang (2006, 2009)</h3>
    <p>Andrew Ang, Robert Hodrick, Yuhang Xing, Xiaoyan Zhang의 &lt;The Cross-Section of Volatility
      and Expected Returns&gt;(<i>Journal of Finance</i>, 2006)는 파마-프렌치 3팩터 기준 이디오싱크래틱
      (개별종목 고유) 변동성이 높은 종목일수록 평균수익률이 "비정상적으로 낮다"는 것을 발견했다 —
      표준 자산가격결정 이론(고유위험을 더 지면 더 보상받아야 한다)과 정반대라 "퍼즐"로 불린다.
      후속 연구(2009, 23개 선진국 대상)는 이 효과가 G7 국가 전부에서 개별적으로 유의미하다는 것을
      보여 미국만의 우연이 아님을 뒷받침했다. 다만 Bali·Cakici·Whitelaw(2011)는 MAX를 통제하면 이
      이디오싱크래틱 변동성 효과가 사라진다는 것도 함께 보였다 — 즉 두 연구를 종합하면 "고유위험
      자체"가 아니라 "복권형 극단수익 프로파일(MAX)"이 근본 원인일 가능성이 높다는 것이 현재의
      정설에 가깝다.</p>
    <div class="callout">
      <div class="callout-title">이 리포트의 결론과의 긴장 관계</div>
      <p>이 학술 문헌은 IREN류 종목을 <b>넓은 횡단면(수천 개 종목)에서 매수후보유로 장기 보유</b>할
        때 위험조정 수익률이 저조한 경향이 있다고 말한다. 반면 05~09장의 백테스트는 <b>이 특정
        바스켓 하나를, 이 특정 4년 구간에서, 적절한 전략(추세추종+트레일링스탑)으로 운용</b>했을 때의
        결과다 — 표본이 하나의 테마·하나의 역사적 경로뿐이라 학술 연구의 대규모 횡단면 증거와 직접
        모순되지 않는다(오히려 표본 크기 자체가 학술 기준에서는 결론을 내리기에 턱없이 작다). 12장에서
        이 긴장을 다시 짚는다.</p>
    </div>
  </section>

  <section class="section" id="methodology">
    <h2><span class="sec-no">05</span> 백테스트 설계</h2>
    <p class="lede">이 저장소의 실제 엔진(<code>core.backtest_engine</code>,
      <code>core.position_sizing</code>, <code>core.market_data</code>)만 사용했다 — 사이징·지표
      계산 로직을 새로 구현하지 않았다.</p>
    <ul>
      <li><b>피벗 바스켓(메인)</b>: {esc(", ".join(PIVOT_BASKET))} (6종, CORZ 제외) — 전 종목이
        모멘텀 웜업(126거래일) 이력을 확보하는 공통 시작일은 <b>{esc(R["main_basket_start"])}</b>다.
        IREN이 2021-11-17 상장이라 이보다 이른 시작은 불가능하다.</li>
      <li><b>백테스트 종료일</b>: {esc(R["main_basket_end"])} — 즉 공통 구간은 약 4.25년이다.</li>
      <li><b>거래비용</b>: 편도 {R["meta"]["fee_bps_oneway"]:.0f}bp(=왕복 {R["meta"]["round_trip_cost_pct"]:.2f}%,
        저장소 모멘텀 로테이션 시리즈 No.06~08과 동일 관례), <code>core.backtest_engine</code>의
        turnover 기반 비용모델을 그대로 적용했다.</li>
      <li><b>모멘텀 로테이션</b>: <code>analysis/kostolany_market_report_2026-08-12/momentum_rotation.py</code>의
        듀얼모멘텀(절대+상대) 로직을 그대로 이식 — 월 첫 거래일 리밸런싱, 상대모멘텀 상위 top_n
        종목을 동일비중 보유, 절대모멘텀(직전 N거래일 수익률&gt;0)을 통과 못하면 현금.</li>
      <li><b>추세추종</b>: 20거래일 돈치안(Donchian) 신고가 브레이크아웃 진입 + 진입 후 고점 대비
        %트레일링스탑 청산(진입 이후 도달한 최고종가에서 stop_pct만큼 하락하면 익일 청산). 단일종목
        (IREN)과 바스켓(각 종목 독립 신호, 그날 신호가 켜진 종목에 동일비중 배분, 나머지는 현금)
        양쪽에 적용.</li>
      <li><b>변동성타게팅</b>: <code>core.position_sizing.realized_annual_volatility_pct</code>(21일
        롤링)와 <code>volatility_target_weight</code>를 그대로 호출 — 목표 연변동성 대비 실현
        변동성으로 노출 비중을 매일 조절(1일 랙 적용, lookahead 방지).</li>
    </ul>
    <p class="caveat">⚠️ 공통 구간이 약 4.25년뿐이라는 것 자체가 이 백테스트의 가장 큰 한계다 —
      상세는 12장에서 다룬다. 지금 이 순간 바로 짚어둔다: 이 구간은 비트코인·AI 인프라 두 테마가
      동시에 구조적 강세장이었던 시기와 거의 정확히 겹친다.</p>
  </section>

  <section class="section" id="baseline">
    <h2><span class="sec-no">06</span> 베이스라인 — 매수후보유</h2>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>전략</th><th>누적수익률</th><th>CAGR</th><th>MDD</th><th>샤프</th><th>칼마</th></tr></thead>
        <tbody>{baseline_rows}</tbody>
      </table>
    </div>
    <p>가장 눈에 띄는 숫자는 CAGR이 아니라 <b>MDD</b>다 — IREN을 상장일부터 그대로 들고 있었다면
      최대낙폭이 <b>{fnum(R["iren_buy_hold"]["metrics"]["mdd"],1)}%</b>다. 최종적으로는
      {fnum(R["iren_buy_hold"]["metrics"]["cumulative_return"],1,True)}%로 플러스 수익을 냈지만,
      그 과정에서 계좌가 거의 전멸에 가까운 낙폭을 견뎌야 했다는 뜻이다 — "결국 벌었으니 결과적으로
      괜찮았다"는 사후적 정당화가 얼마나 위험한지 보여주는 실측 사례다. 바스켓으로 분산하면(6종
      정적 균등보유) MDD가 {fnum(R["basket_static_buy_hold"]["metrics"]["mdd"],1)}%로(같은 구간 IREN
      단일종목의 {fnum(R["iren_buy_hold_common_window"]["metrics"]["mdd"],1)}%보다 훨씬 완만하게)
      줄어든다 — 다만 샤프는 {fnum(R["basket_static_buy_hold"]["metrics"]["sharpe"],2)}로 IREN
      단일종목({fnum(R["iren_buy_hold_common_window"]["metrics"]["sharpe"],2)}, 같은 구간)보다 오히려
      살짝 낮다. 정직하게 말하면 이 구간에서는 "분산이 위험조정수익률까지 개선했다"고 과장할 수
      없다 — 분산의 실제 효과는 샤프가 아니라 <b>MDD·개별기업 리스크(파산·소송·규제 등 이 바스켓
      중 CORZ가 실제로 한 번 겪은 리스크) 완화</b> 쪽에서 뚜렷하다.</p>
  </section>

  <section class="section" id="rotation">
    <h2><span class="sec-no">07</span> 모멘텀 로테이션 결과 — 기대에 못 미쳤다</h2>
    <p class="lede">저장소의 검증된 섹터 로테이션 방법론(No.05~08)을 그대로 이식했지만, 이 좁고
      상관관계 높은 바스켓에서는 오히려 정적 균등보유보다 못했다.</p>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>파라미터</th><th>누적수익률</th><th>CAGR</th><th>MDD</th><th>샤프</th><th>칼마</th></tr></thead>
        <tbody>{rot_sweep_html}</tbody>
      </table>
    </div>
    <p class="fig-caption">강조행 = 채택 파라미터(모멘텀 {R["momentum_window_days"]}거래일, top {R["top_n"]}).
      window/top_n 전 조합에서 샤프 0.37~0.82 범위 — 06장 정적 균등보유(샤프
      {fnum(R["basket_static_buy_hold"]["metrics"]["sharpe"],2)})를 넘는 조합이 드물다.</p>
    <p><b>왜 로테이션이 안 먹혔는가</b> — 섹터 ETF 로테이션(No.05~08)이 통했던 이유는 11개 섹터가
      서로 다른 경기 사이클에 반응해 "언제나 어딘가는 오르고 있다"는 폭(breadth)이 있었기 때문이다.
      이 바스켓은 정반대다 — 6~9개 종목이 전부 같은 두 개의 거시 동인(비트코인 가격, AI 인프라
      서사)에 동시에 노출돼 있어 상호 상관관계가 매우 높다. "상위 3개만 골라 타는" 전략이 통하려면
      종목 간 모멘텀 순위가 자주 뒤바뀌고 그 차이가 유의미해야 하는데, 이 바스켓은 오르내림이
      거의 항상 같이 움직여 로테이션이 분산효과도, 선택효과도 충분히 내지 못한다 — 이 저장소
      No.09~10(개별주 확장 기각)이 발견한 것과 결이 비슷한 구조적 한계다.</p>
  </section>

  <section class="section" id="trend">
    <h2><span class="sec-no">08</span> 추세추종(돈치안 브레이크아웃 + 트레일링스탑) — 최선의 결과</h2>
    <p class="lede">"변동성 큰 종목의 상승분을 다 뱉어내지 않고 타는 법"이라는 사용자의 실제 질문에
      가장 직접적으로 답하는 접근이다. 20거래일 신고가 돌파로 진입하고, 고점 대비 %만큼 물러나면
      기계적으로 청산한다.</p>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>설정</th><th>누적수익률</th><th>CAGR</th><th>MDD</th><th>샤프</th><th>칼마</th><th>매매횟수</th></tr></thead>
        <tbody>{tf_sweep_html}</tbody>
      </table>
    </div>
    <p class="fig-caption">강조행 = 바스켓 기준 샤프 최고 스탑폭({R["trend_following_best"]["stop_pct"]*100:.0f}%).
      IREN 단일종목은 스탑폭 15~35% 전 구간에서 샤프 1.2 안팎으로 안정적이었다 — 파라미터에
      과최적화된 느낌은 상대적으로 적다(단, 통계적 유의성 검정은 12장 한계에서 별도로 짚는다).</p>
    <p><b>{R["trend_following_best"]["stop_pct"]*100:.0f}% 트레일링스탑을 쓴 바스켓 버전</b>이
      전체 비교에서 최고 성과를 냈다 — 샤프 {fnum(champion_no_overlay["sharpe"],2)},
      CAGR {fnum(champion_no_overlay["cagr"],1,True)}%, MDD {fnum(champion_no_overlay["mdd"],1)}%
      (06장의 정적 균등보유 대비 MDD {fnum(R["basket_static_buy_hold"]["metrics"]["mdd"],1)}%보다는
      아직 크지만, IREN 단일종목 매수후보유의 {fnum(R["iren_buy_hold_common_window"]["metrics"]["mdd"],1)}%보다는
      훨씬 완화됐다). 다만 <b>MDD가 여전히 {fnum(champion_no_overlay["mdd"],1)}%라는 것</b>을 그대로
      받아들여야 한다 — 아무리 잘 설계된 트레일링스탑도 이 변동성 수준의 종목에서 50%대 낙폭
      자체를 없애지는 못한다. 갭다운(하루 만에 스탑 레벨을 훌쩍 넘어 하락)이 잦은 종목 특성상
      "종가 기준 스탑"은 실제 체결가가 이론값보다 나쁠 수 있다는 점도 감안해야 한다.</p>
  </section>

  <section class="section" id="voltarget">
    <h2><span class="sec-no">09</span> 변동성타게팅 오버레이 — 샤프는 못 올려도 절대낙폭은 크게 줄인다</h2>
    <p class="lede">08장 챔피언({esc(champion_label)})에 <code>core.position_sizing</code>의
      변동성타게팅을 얹었다. 결과는 단순하지 않다 — 위험조정수익률(샤프)은 오히려 살짝 낮아지지만,
      절대적인 낙폭은 극적으로 줄어든다.</p>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>목표변동성/상한</th><th>누적수익률</th><th>CAGR</th><th>MDD</th><th>샤프</th><th>칼마</th></tr></thead>
        <tbody>{vt_sweep_html}</tbody>
      </table>
    </div>
    <p class="fig-caption">비교 기준(오버레이 없음): 샤프 {fnum(champion_no_overlay["sharpe"],2)},
      MDD {fnum(champion_no_overlay["mdd"],1)}%, 칼마 {fnum(champion_no_overlay["calmar"],2)}.</p>
    <p><b>오버레이는 이 챔피언 전략의 샤프({fnum(champion_no_overlay["sharpe"],2)})를 넘지
      못했다</b> — 무레버리지(상한 1.0x) 최선 조합도 샤프 {fnum(R["vol_target_best_no_leverage"]["sharpe"],2)}에
      그친다. 저장소 No.06(멀티에셋 확장 리포트)에서도 변동성타게팅·회전율버퍼가 예상과 반대로
      샤프를 깎았던 것과 같은 패턴이 여기서도 재현됐다. 그런데 <b>목표변동성을 낮게 잡을수록(15%)
      MDD가 {fnum(champion_no_overlay["mdd"],1)}%에서 <span class="strong">{fnum(R["vol_target_sweep"][0]["mdd"],1)}%</span>까지
      줄어든다</b> — 절대 손실 규모를 SPY 매수후보유 MDD({fnum(R["spy_buy_hold"]["metrics"]["mdd"],1)}%)에
      근접한 수준까지 눌러준다는 뜻이다. 다만 그 대가로 CAGR도
      {fnum(champion_no_overlay["cagr"],1,True)}%에서 {fnum(R["vol_target_sweep"][0]["cagr"],1,True)}%로
      크게 줄어든다 — 공짜 점심은 없다. <b>결론: 변동성타게팅은 "수익을 더 벌어주는 도구"가 아니라
      "감당 가능한 낙폭 수준으로 위험예산을 재단하는 도구"</b>로 써야 한다 — 11장 프레임워크에서
      이 구분을 그대로 반영한다.</p>
  </section>

  <section class="section" id="robustness">
    <h2><span class="sec-no">10</span> 강건성 체크 — CORZ 포함, 대조군 별도</h2>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>전략</th><th>누적수익률</th><th>CAGR</th><th>MDD</th><th>샤프</th><th>칼마</th></tr></thead>
        <tbody>{robust_rows}</tbody>
      </table>
    </div>
    <p>CORZ(2024-01 파산 재상장)를 포함한 7종 바스켓으로 다시 돌려도(구간이
      {esc(R["robustness_with_corz"]["start"])}부터로 더 짧아짐) 같은 패턴이 재현된다 — 정적
      균등보유(샤프 {fnum(R["robustness_with_corz"]["static_buy_hold"]["sharpe"],2)})가 모멘텀
      로테이션(샤프 {fnum(R["robustness_with_corz"]["momentum_rotation"]["sharpe"],2)})을 이긴다.
      대조군을 포함한 8종(피벗+MARA+RIOT)에서도 동일하다 — 07장 결론이 특정 종목 리스트 선택에
      좌우된 우연이 아니라는 신호다.</p>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>대조군 종목</th><th>누적수익률</th><th>CAGR</th><th>MDD</th><th>샤프</th><th>칼마</th></tr></thead>
        <tbody>{contrast_rows_html}</tbody>
      </table>
    </div>
    <p class="caveat">⚠️ <b>MARA를 2014년 상장일부터 그대로 들고 있었다면 12년 넘게 지난 지금도
      원금 대비 {fnum(R["contrast_basket_buy_hold"]["MARA"]["full_history"]["cumulative_return"],1,True)}%
      (CAGR {fnum(R["contrast_basket_buy_hold"]["MARA"]["full_history"]["cagr"],1,True)}%) 상태다</b> —
      MDD는 {fnum(R["contrast_basket_buy_hold"]["MARA"]["full_history"]["mdd"],1)}%. 이것이 바로
      04장 학술 문헌이 경고하는 "복권주를 장기 매수후보유하면 위험조정수익률이 저조할 수 있다"는
      명제의 실제 사례다 — 이 리포트의 4.25년 백테스트 구간(2022-05~2026-08)이 얼마나 특수하게
      좋은 시기였는지를 보여주는 대조 사례이기도 하다.</p>
  </section>

  <section class="section" id="framework">
    <h2><span class="sec-no">11</span> 종합 프레임워크 — 실전에서 어떻게 다룰 것인가</h2>
    <p class="lede">01~10장의 실측 결과를 사용자가 실제로 쓸 수 있는 체크리스트로 종합한다.</p>
    <ul class="checklist">
      <li><b>사이징: 계좌 대비 리스크 %로 정하고, 절대 "감당할 수 있는 최대손실 금액" 역산으로
        수량을 정하라.</b> <code>core.position_sizing.fixed_fractional_size()</code> 실측 예시 —
        IREN 진입가 ${FF["entry_price"]:,.2f}에 스탑을 {FF["stop_pct_used"]*100:.0f}% 아래
        (${FF["stop_price"]:,.2f})에 두고 계좌 10만 달러의 2%(${FF["risk_amount"]:,.0f})만 리스크에
        건다면, 매수수량은 {FF["shares"]:.1f}주(계좌의 {FF["position_pct_of_account"]:.1f}%)로
        <b>계좌 전체를 거는 것보다 훨씬 작아진다</b> — 06장 IREN 단일종목 풀사이즈 매수후보유의
        MDD가 -84~-96%였던 것과 대비된다.</li>
      <li><b>단일종목 확신매매보다 바스켓 분산이 개별기업 리스크를 낮춘다 — 단, 샤프까지
        개선한다고 과장하진 않는다.</b> 06장에서 6종 정적 균등보유는 IREN 단일종목보다 MDD가
        뚜렷하게 낮았지만(같은 구간 기준), 샤프는 오히려 근소하게 낮았다. 이 테마를 좋아한다면
        "가장 확신하는 종목 하나"보다 "테마 전체를 얕고 넓게" 갖는 편이 CORZ류 개별기업 리스크
        (파산 이력)는 확실히 줄여주지만, 위험조정수익률까지 자동으로 좋아진다고 기대해서는 안
        된다.</li>
      <li><b>바스켓 내부 로테이션은 기대만큼 안 통한다 — 굳이 안 해도 된다.</b> 07장·10장에서
        일관되게 확인됨. 이 바스켓은 종목 간 상관관계가 너무 높아 "돌아가며 강한 것만 골라 타는"
        전략의 전제(분산된 강도 순위 변화)가 성립하지 않는다.</li>
      <li><b>트레일링스탑 규율은 실측으로 뒷받침된다 — 단, 낙폭을 없애주진 않는다.</b> 08장
        돈치안+{R["trend_following_best"]["stop_pct"]*100:.0f}% 트레일링스탑이 전체 비교에서
        최고 샤프({fnum(champion_no_overlay["sharpe"],2)})를 냈다. 그러나 MDD
        {fnum(champion_no_overlay["mdd"],1)}%는 여전히 크다 — "손절 규율을 지키면 안전해진다"가
        아니라 "손절 규율을 지키면 무규율 매수후보유보다 덜 나쁘다"는 것이 정확한 해석이다.</li>
      <li><b>변동성타게팅은 알파가 아니라 위험예산 도구로 써라.</b> 09장 — 목표변동성을 낮출수록
        수익도 위험도 같이 줄어드는 정직한 트레이드오프다. "계좌가 -70% 빠지는 것은 못 견디지만
        -30%는 견딜 수 있다"는 개인의 리스크 허용도에 맞춰 포지션 크기를 미리 정하는 용도로 쓰는
        것이 옳은 사용법이다.</li>
      <li><b>04장의 학술 경고를 실제 의사결정에 반영하라.</b> 이 종목군을 매매하고 싶다면, "장기
        보유하면 결국 오른다"는 가정에 기대지 말고 08장처럼 <b>명시적인 청산 규율이 있는 전술적
        운용</b>으로 접근하는 편이 문헌·실측 양쪽과 더 일치한다.</li>
    </ul>
  </section>

  <section class="section" id="conclusion">
    <h2><span class="sec-no">12</span> 한계와 솔직한 결론</h2>
    <h3>이 백테스트가 보여준 것</h3>
    <ul>
      <li>08장 추세추종(돈치안+트레일링스탑) 바스켓 버전이 4개 접근 중 가장 나은 위험조정수익률
        (샤프 {fnum(champion_no_overlay["sharpe"],2)})을 냈고, 07장 모멘텀 로테이션은 이 특정
        바스켓에서는 기대에 못 미쳤다 — 둘 다 파라미터 스윕과 CORZ 포함/대조군 포함 강건성 체크로
        재현을 확인했다.</li>
      <li>09장 변동성타게팅은 샤프를 올리진 못했지만 절대 낙폭을 큰 폭으로(최대 -71%→-30%대)
        줄이는 실용적 가치가 실측으로 확인됐다.</li>
    </ul>
    <h3>이 백테스트가 못 보여준 것 — 정직한 한계</h3>
    <ul>
      <li><b>표본 기간이 짧다.</b> 공통 백테스트 구간이 약 4.25년(2022-05~2026-08)뿐이다 — IREN이
        2021년 11월 상장이라 그 이전 데이터 자체가 존재하지 않는다. 이 저장소 다른 리포트(No.07)가
        2008년 금융위기까지 진짜 아웃오브샘플 검증을 했던 것과 같은 수준의 위기 구간 검증이 이
        바스켓으로는 원천적으로 불가능하다 — 2022년 크립토 겨울 정도가 이 표본에 포함된 유일한
        스트레스 구간이다.</li>
      <li><b>이 4.25년은 이례적으로 우호적인 시기였다.</b> 비트코인 강세장과 생성형 AI 인프라
        투자붐이 동시에 겹친 구간이다 — 다음 4년이 같은 조합일 것이라는 보장이 전혀 없다(10장
        MARA 12년 전체이력 CAGR {fnum(R["contrast_basket_buy_hold"]["MARA"]["full_history"]["cagr"],1,True)}%가
        같은 종목군도 시기에 따라 전혀 다른 결과를 낼 수 있음을 보여준다).</li>
      <li><b>표본이 하나의 테마·소수 종목에 집중돼 있다.</b> 04장 학술 문헌은 수천 개 종목의
        수십 년 횡단면 데이터로 도출된 결론이다 — 이 리포트의 6~9종목·4년 백테스트는 통계적으로
        그 결론을 반박할 수 있는 규모가 아니다. "이번엔 통했다"가 "이 전략이 장기적으로 우월하다"는
        증거는 아니다.</li>
      <li><b>파라미터 스윕 자체가 사후적으로 보였을 위험이 있다.</b> 08장 스탑폭·07장 모멘텀
        윈도우 모두 여러 값을 시도해서 최선을 골랐다 — 08장의 경우 스탑폭 전 구간(15~35%)에서
        결과가 비교적 안정적이라 과최적화 위험이 상대적으로 낮아 보이지만, 워크포워드나 순열검정
        (이 저장소 <code>core.backtest_engine.run_permutation_test</code>)으로 통계적 유의성을
        확인하는 절차는 이번 범위에 포함하지 않았다.</li>
      <li><b>"순수 대조군 부재"(03장)</b> — 피벗 여부가 초과수익의 진짜 원인인지, 아니면 그냥
        "비트코인+AI 테마 전체가 오른 시기"의 공통효과인지 이 데이터로는 깨끗하게 분리할 수 없다.</li>
      <li><b>실제 체결 가정의 단순화</b> — 종가 기준 신호·익일 체결을 가정했다. 이 정도 변동성의
        종목은 실제로는 장중 갭·유동성 부족으로 이론상 체결가와 실제 체결가의 괴리가 클 수 있다.</li>
    </ul>
    <div class="callout">
      <div class="callout-title">결론</div>
      <p>IREN류 종목은 실제로 구조적 이유(부채로 짓는 성장, 이중 베타 노출, 서사·촉매 중심 가격형성)
        때문에 변동성이 크고, 이 리포트의 실측 백테스트에서는 "무규율 매수후보유"보다 "추세추종+
        트레일링스탑"이 위험조정 기준으로 뚜렷하게 나았다. 그러나 이 결과를 낳은 4.25년은 이례적으로
        우호적인 구간이었고, 04장 학술 문헌은 이런 복권형 종목을 장기·무규율로 갖고 있는 투자자가
        평균적으로 손해를 볼 수 있다고 경고한다. 두 결론은 모순이 아니라 <b>같은 얘기의 다른
        측면</b>이다 — "이런 종목을 사는 것 자체"가 문제가 아니라 "어떻게 사이징하고 언제
        판다는 규율 없이 사는 것"이 문제라는 뜻이다. 11장 프레임워크가 그 규율의 구체적 형태다.</p>
    </div>
  </section>

  <section class="section" id="sources">
    <h2><span class="sec-no">부록</span> 참고 문헌 · 출처</h2>
    <ul class="src-list">
      <li>Turan G. Bali, Nusret Cakici, Robert F. Whitelaw, <i>Maxing Out: Stocks as Lotteries and
        the Cross-Section of Expected Returns</i>, <i>Journal of Financial Economics</i> (2011) —
        <a href="https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1262416">SSRN</a>,
        <a href="https://www.nber.org/papers/w14804">NBER Working Paper No. 14804</a></li>
      <li>Andrew Ang, Robert J. Hodrick, Yuhang Xing, Xiaoyan Zhang, <i>The Cross-Section of
        Volatility and Expected Returns</i>, <i>Journal of Finance</i> (2006) —
        <a href="https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.2006.00836.x">Wiley Online Library</a>,
        <a href="https://www.nber.org/papers/w10852">NBER Working Paper No. 10852</a>; 후속(2009) 국제
        증거 —
        <a href="https://www.sciencedirect.com/science/article/abs/pii/S0304405X08001542">High
        idiosyncratic volatility and low returns: International and further U.S. evidence</a></li>
      <li>비트코인 채굴사 AI/HPC 피벗 동향 — <a href="https://www.coindesk.com/markets/2026/03/27/bitcoin-miners-are-becoming-ai-companies-and-selling-their-btc-to-fund-the-transition">CoinDesk:
        Bitcoin Miners Are Becoming AI Companies</a>, <a href="https://insights4.vc/blog/bitcoin-miners-pivot-to-ai-data-centers/">Insights4VC:
        Bitcoin Miners Pivot to AI Data Centers — 2026 Company Analysis</a>, <a href="https://www.kucoin.com/blog/Why-BTC-Miners-are-Pivoting-to-AI-Data-Centers-in-2026">KuCoin:
        Why BTC Miners are Pivoting to AI Data Centers in 2026</a></li>
      <li>IREN-마이크로소프트 97억달러 계약, GPU 파이낸싱 — <a href="https://iren.gcs-web.com/news-releases/news-release-details/iren-secures-97bn-ai-cloud-contract-microsoft">IREN
        IR: IREN Secures $9.7bn AI Cloud Contract with Microsoft</a>, <a href="https://www.globenewswire.com/news-release/2026/06/01/3304211/0/en/IREN-Closes-3-65bn-Investment-Grade-GPU-Financing.html">GlobeNewswire:
        IREN Closes $3.65bn Investment-Grade GPU Financing</a></li>
      <li>Hut 8-Anthropic/Fluidstack 데이터센터 계약 — <a href="https://bitcoinmagazine.com/news/bitcoin-miner-hut-8-shares-jump-on-ai-deal">Bitcoin
        Magazine: Bitcoin Miner Hut 8 Shares Jump On $9.8 Billion AI Data Center Deal</a></li>
      <li>Bitfarms 채굴 단계적 종료·AI 전환 — <a href="https://bitcoinmagazine.com/news/bitfarms-to-exit-bitcoin-mining">Bitcoin
        Magazine: Bitfarms To Exit Bitcoin Mining, Pivot To AI</a></li>
      <li>MARA/RIOT 피벗 및 고베타 특성 — <a href="https://247wallst.com/investing/2026/04/16/mara-rises-6-bitcoin-miner-turned-ai-infrastructure-play-has-the-market-divided-and-buzzing/">24/7
        Wall St.: MARA Rises 6% — Bitcoin Miner Turned AI Infrastructure Play</a></li>
      <li>데이터 출처: Yahoo Finance(yfinance) — 이 저장소 <code>core.market_data</code>(로컬 캐시)
        경유로 실측. 베타·공매도비중·기관보유율 등은 2026-08-19 <code>yfinance Ticker.info</code>
        실측 스냅샷.</li>
      <li>이 저장소 내부 근거 — <code>analysis/kostolany_market_report_2026-08-12/momentum_rotation.py</code>
        (듀얼모멘텀 로테이션 원 구현), <code>core.backtest_engine</code>·<code>core.position_sizing</code>
        (백테스트·사이징 엔진, 이번 리포트를 위해 새로 구현하지 않고 그대로 재사용)</li>
    </ul>
  </section>

</div>

<footer>
  <p>데이터 출처: Yahoo Finance(yfinance), 이 저장소의 <code>core.market_data</code>·
    <code>core.backtest_engine</code>·<code>core.position_sizing</code>(기존 검증된 모듈 재사용).
    05~10장 백테스트는 리포트 생성일({esc(GEN_DATE)}) 기준 실행 결과이며, 종가 기준 신호·익일
    체결·왕복 {R["meta"]["round_trip_cost_pct"]:.2f}% 거래비용을 가정한 시뮬레이션이다. 이 리포트는
    과거·현재 데이터 기반 분석이며 투자 조언이 아니다.</p>
</footer>
"""

out_path = os.path.join(OUT_DIR, "final_report.html")
with open(out_path, "w", encoding="utf-8") as f:
    f.write(HTML)
print(f"저장 완료: {out_path} ({len(HTML):,} bytes)")
