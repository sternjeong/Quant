#!/usr/bin/env python3
"""report_data.json을 읽어 final_report.html을 만든다.

analysis/2026-09-14_nonai_control_basket_volatility_momentum/build_report.py 와 동일한 디자인
시스템(다크네이비/올리브 톤, 세리프 헤드라인, TOC, 섹션 번호, 판정 배지)을 그대로 재사용한다 —
같은 트랙C 계열 리포트라 시각적 연속성을 유지한다.
"""
import json
import math
import os

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

with open(f"{OUT_DIR}/report_data.json", encoding="utf-8") as f:
    R = json.load(f)

META = R["meta"]
GEN = META["generated"]
V20 = R["variants_top20"]
HOT15 = R["hot_sector_top15"]
H1 = R["h1_robustness"]
H2 = R["h2_cross_validation"]
H3 = R["h3_valuation"]
H4 = R["h4_market_cap"]


def fnum(v, digits=1, signed=False):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    s = f"{v:,.{digits}f}"
    if signed and v > 0:
        s = "+" + s
    return s


def pct(v, digits=1):
    if v is None:
        return "—"
    return f"{v * 100:.{digits}f}%"


def fmoney_b(v):
    if v is None:
        return "—"
    return f"${v / 1e9:,.1f}B"


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def grade_badge(text, tone="moderate"):
    cls = {"robust": "grade-A", "moderate": "grade-B", "weak": "grade-C"}.get(tone, "grade-B")
    return f'<span class="confidence-grade {cls}">{esc(text)}</span>'


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
.wrap{ max-width: 1060px; margin:0 auto; padding: 0 24px 96px; }
.masthead{ background: var(--accent); color: var(--accent-ink); padding: 56px 24px 40px; }
.masthead-inner{ max-width:1060px; margin:0 auto; }
.masthead-eyebrow{ font-size:12.5px; letter-spacing:0.12em; text-transform:uppercase; opacity:0.82;
  font-family: ui-monospace, "SF Mono", Consolas, monospace; display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
.masthead-eyebrow .dot{ opacity:0.5; }
h1.masthead-title{ font-family:"Iowan Old Style","Palatino Linotype", Georgia, serif; font-weight:600;
  font-size: clamp(28px, 4.2vw, 44px); line-height:1.15; margin: 14px 0 10px; text-wrap: balance; max-width: 34ch; }
.masthead-sub{ font-size:16.5px; max-width:76ch; opacity:0.92; margin:0 0 22px; }
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
.lede{ font-size:16.5px; color:var(--ink-2); max-width:78ch; }
.section p{ max-width:82ch; }
.section > p, .section > .lede { margin-top: 0; }
.section li{ max-width:78ch; }
.callout{ background: var(--surface-2); border:1px solid var(--hairline); border-left: 3px solid var(--accent);
  border-radius: 6px; padding: 18px 22px; margin: 20px 0 26px; }
.callout-title{ font-size:11.5px; text-transform:uppercase; letter-spacing:0.08em; color:var(--accent);
  font-weight:700; margin-bottom:8px; }
.callout p{ margin:0; max-width:none; }
.callout p + p{ margin-top:10px; }
.callout.warn{ border-left-color: var(--delta-neg); }
.callout.warn .callout-title{ color: var(--delta-neg); }
.caveat{ font-size:14.5px; color:var(--ink-2); background:var(--surface-2); border-radius:6px;
  padding:14px 18px; border:1px dashed var(--hairline); margin: 14px 0; }
.kpi-row{ display:grid; grid-template-columns:repeat(auto-fit, minmax(190px,1fr)); gap:14px; margin: 20px 0 8px; }
.kpi-tile{ background:var(--surface); border:1px solid var(--hairline); border-radius:8px; padding:16px 18px; box-shadow: var(--shadow); }
.kpi-label{ font-size:12.5px; color:var(--ink-muted); margin-bottom:6px; }
.kpi-value{ font-size:24px; font-weight:600; line-height:1.1; }
.kpi-value.pos{ color:var(--delta-pos); }
.kpi-value.neg{ color:var(--delta-neg); }
.kpi-sub{ font-size:12.5px; color:var(--ink-muted); margin-top:4px; }
.table-wrap{ overflow-x:auto; border:1px solid var(--hairline); border-radius:8px; background:var(--surface); }
table.data-table{ width:100%; border-collapse:collapse; font-size:13.5px; min-width:720px; }
table.data-table th{ text-align:right; font-weight:600; font-size:11.5px; color:var(--ink-muted); text-transform:uppercase;
  letter-spacing:0.03em; padding:10px 12px; border-bottom:1px solid var(--hairline); white-space:nowrap; }
table.data-table th:first-child, table.data-table td:first-child{ text-align:left; }
table.data-table td{ padding:8px 12px; border-bottom:1px solid var(--hairline); text-align:right; white-space:nowrap; }
table.data-table tbody tr:hover{ background:var(--surface-2); }
table.data-table tbody tr:last-child td{ border-bottom:none; }
td.tk-cell{ text-align:left !important; }
td.tk-cell .tk-name{ font-weight:650; margin-right:8px; }
.strong{ font-weight:700; }
tr.warn-row{ background: rgba(179,38,30,0.08); }
tr.hero-row{ background: rgba(31,77,61,0.08); }
footer{ max-width:1060px; margin:40px auto 0; padding: 26px 24px 10px; border-top:1px solid var(--hairline);
  font-size:12.5px; color:var(--ink-muted); }
footer p{ max-width:none; }
.toc{ display:flex; flex-wrap:wrap; gap:8px 18px; margin: 24px 0 4px; padding:16px 20px; background:var(--surface);
  border:1px solid var(--hairline); border-radius:8px; }
.toc a{ font-size:13.5px; color:var(--ink-2); text-decoration:none; }
.toc a:hover{ color:var(--accent); text-decoration:underline; }
.verdict-badge{ display:inline-block; font-size:12px; font-weight:700; letter-spacing:0.03em;
  padding:3px 10px; border-radius:20px; text-transform:uppercase; }
.v-accept{ background: var(--accent-soft); color: var(--accent); border:1px solid var(--accent); }
.v-reject{ background: rgba(179,38,30,0.10); color: var(--delta-neg); border:1px solid var(--delta-neg); }
.v-partial{ background: var(--accent-2-soft); color: var(--accent-2); border:1px solid var(--accent-2); }
.confidence-grade{ display:inline-block; font-size:12px; font-weight:700; padding:2px 9px; border-radius:4px; }
.grade-A{ background: var(--accent-soft); color:var(--accent); }
.grade-B{ background: var(--accent-2-soft); color:var(--accent-2); }
.grade-C{ background: rgba(179,38,30,0.10); color:var(--delta-neg); }
"""


def top20_rows(variant, highlight=None):
    rows = V20[variant] if isinstance(variant, str) else variant
    html = []
    for r in rows:
        cls = " hero-row" if highlight and r["ticker"] in highlight else ""
        html.append(
            f'<tr class="{cls.strip()}"><td class="tk-cell"><span class="tk-name">{esc(r["ticker"])}</span>'
            f'<span style="color:var(--ink-muted);font-size:12px;">{esc(r.get("sector") or "—")}</span></td>'
            f'<td class="num strong">{fnum(r["composite_score"],1)}</td>'
            f'<td class="num">{fnum(r.get("momentum_score"),1)}</td>'
            f'<td class="num">{fnum(r.get("growth_score"),1)}</td>'
            f'<td class="num">{fnum(r.get("value_score"),1)}</td>'
            f'<td class="num">{fnum(r.get("quality_score"),1)}</td>'
            f'<td class="num">{fmoney_b(r.get("market_cap"))}</td>'
            "</tr>"
        )
    return "".join(html)


def overlap_rows():
    html = []
    for o in H1["overlaps"]:
        a, b = o["pair"]
        html.append(
            f'<tr><td class="tk-cell"><span class="tk-name">{esc(a)} ∩ {esc(b)}</span></td>'
            f'<td class="num">{o["overlap_n"]}/20</td>'
            f'<td class="num strong">{pct(o["jaccard"],1)}</td>'
            f'<td class="tk-cell" style="text-align:left;">{esc(", ".join(o["overlap_tickers"]))}</td></tr>'
        )
    return "".join(html)


def theme_rows_html():
    html = []
    for t in H2["top5_themes"]:
        html.append(
            f'<tr><td class="tk-cell"><span class="tk-name">{esc(t["theme"])}</span>'
            f'<span style="color:var(--ink-muted);font-size:12px;">{esc(t["proxies"])}</span></td>'
            f'<td class="num strong">{fnum(t["rs_score"],0)}</td>'
            f'<td class="num">{fnum(t["return_3m"],1,True)}%</td>'
            f'<td class="num">{fnum(t["return_12m"],1,True)}%</td>'
            f'<td>{esc(t["trend"])}</td></tr>'
        )
    return "".join(html)


def sector_count_rows():
    html = []
    for sec, n in H2["bottom_up_sector_counts"]:
        html.append(
            f'<tr><td class="tk-cell"><span class="tk-name">{esc(sec)}</span></td>'
            f'<td class="num strong">{n}/20</td><td class="num">{pct(n/20,0)}</td></tr>'
        )
    return "".join(html)


def valuation_rows():
    html = []
    for r in H3["rows"]:
        if r["model_collapsed"]:
            tag = '<span class="verdict-badge v-reject">모형 붕괴</span>'
            jpe = jpb = "—"
        elif r.get("numerically_unstable"):
            tag = '<span class="verdict-badge v-partial">불안정(g≈r)</span>'
            jpe = fnum(r["justified_pe"], 1)
            jpb = fnum(r["justified_pb"], 2)
        else:
            rich = r["actual_trailing_pe"] and r["justified_pe"] and r["actual_trailing_pe"] > r["justified_pe"]
            tag = f'<span class="verdict-badge {"v-reject" if rich else "v-accept"}">{"고평가" if rich else "저평가"}</span>'
            jpe = fnum(r["justified_pe"], 1)
            jpb = fnum(r["justified_pb"], 2)
        html.append(
            f'<tr><td class="tk-cell"><span class="tk-name">{esc(r["ticker"])}</span></td>'
            f'<td class="num">{pct(r["roe_proxy"],1) if r["roe_proxy"] else "—"}</td>'
            f'<td class="num">{pct(r["sustainable_growth_g"],1) if r["sustainable_growth_g"] is not None else "—"}</td>'
            f'<td class="num">{jpe}</td>'
            f'<td class="num">{fnum(r["actual_trailing_pe"],1)}</td>'
            f'<td class="num">{jpb}</td>'
            f'<td class="num">{fnum(r["actual_price_to_book"],2)}</td>'
            f'<td>{tag}</td></tr>'
        )
    return "".join(html)


def mktcap_rows():
    html = []
    for ticker, mc in H4["rows"]:
        html.append(
            f'<tr><td class="tk-cell"><span class="tk-name">{esc(ticker)}</span></td>'
            f'<td class="num strong">{fmoney_b(mc)}</td></tr>'
        )
    return "".join(html)


N_COLLAPSED = H3["n_collapsed"]
N_TOTAL = H3["n_total"]
N_UNSTABLE = H3["n_unstable"]
N_RELIABLE = H3["n_reliable"]
N_RICH = H3["n_rich"]
N_CHEAP = H3["n_cheap"]

CORE_ALL3 = H1["core_all3"]
OV_DEFAULT_MOM = H1["overlaps"][0]
OV_DEFAULT_QUAL = H1["overlaps"][1]
OV_MOM_QUAL = H1["overlaps"][2]

TOP5_THEMES_STR = " > ".join(t["theme"] for t in H2["top5_themes"])
ENERGY_COUNT = next((n for sec, n in H2["bottom_up_sector_counts"] if sec == "Energy"), 0)
TECH_COUNT = sum(n for sec, n in H2["bottom_up_sector_counts"] if sec == "Technology")

HTML = f"""<title>오늘 이 순간의 스크리닝 — 2026-09-18 라이브 텐베거/모멘텀 후보 스냅샷</title>
<style>
{CSS}
</style>

<div class="masthead">
  <div class="masthead-inner">
    <div class="masthead-eyebrow">
      <span>QUANT RESEARCH NOTE</span><span class="dot">·</span><span>트랙 C, No.8</span><span class="dot">·</span><span>Live Cross-Sectional Snapshot — NOT a Backtest</span>
    </div>
    <h1 class="masthead-title">오늘 이 순간의 종목 발굴 — S&amp;P500 전체를 4팩터로 스캔하고 3가지 방법으로 감사한다</h1>
    <p class="masthead-sub">지금까지 트랙C 라운드는 전부 과거 검증(백테스트)이었다. 이 리포트는 역사적 검증이 아니라
      <b>core.stock_discovery.discover_candidates()</b>로 오늘 이 순간의 S&amp;P500 유니버스를 스캔한 라이브
      횡단면 스냅샷이다 — 시계열 수익률이 없어 순열검정/블록부트스트랩을 적용할 수 없는 대신, (1) 가중치를
      바꿔도 상위 종목이 안정적인지, (2) 이 저장소의 독립적인 하향식 섹터강도 엔진과 교차검증되는지,
      (3) 고든성장모형 밸류에이션이 오늘의 상위 후보에 실제로 적용 가능한지, (4) 상위 후보가 진짜 소형
      텐베거 후보군인지 대형주 로테이션에 불과한지, 4가지 다른 감사를 적용한다.</p>
    <div class="masthead-meta">
      <span><b>스캔 시각</b> {esc(META['as_of_scan'])}(재실행 {esc(GEN)})</span>
      <span><b>유니버스</b> {esc(META['universe'])}</span>
      <span><b>시장국면</b> {esc(META['market_regime']['regime'])}(총점 {fnum(META['market_regime']['total_score'],1)}, 200일선 상회 {fnum(META['market_regime']['pct_above_200sma'],1)}%)</span>
      <span><b>스캔 소요</b> {fnum(META['scan_runtime_sec'],0)}초</span>
    </div>
  </div>
</div>

<div class="wrap">

  <nav class="toc">
    <a href="#scope">00 문제 제기 — 이게 뭐고 뭐가 아닌지</a>
    <a href="#top20">01 오늘의 상위 20 (기본가중치)</a>
    <a href="#h1">02 H1 강건성 — 가중치 변형 교차비교</a>
    <a href="#h2">03 H2 교차검증 — 하향식 섹터강도 엔진과 대조</a>
    <a href="#h3">04 H3 밸류에이션 갭 — 고든모형 적용가능성</a>
    <a href="#h4">05 H4 시가총액 — 텐베거 후보인가, 대형주 로테이션인가</a>
    <a href="#synthesis">06 종합</a>
    <a href="#limitations">07 한계</a>
  </nav>

  <section class="section" id="scope">
    <h2><span class="sec-no">00</span> 문제 제기 — 이게 뭐고 뭐가 아닌지</h2>
    <p class="lede">에이전트 페르소나가 명시한 "아직 안 풀린 문제" 중 "오늘 기준 신규 후보 스캔"을 다룬다.
      전임 세션(2026-09-17, 작업88)이 이 폴더에 스캔·밸류에이션 스크립트만 작성해두고 미실행 상태로
      남겨뒀던 것을 이번 세션이 실행·완성했다. <b>이건 역사적 검증이 아니다</b> — 특정 종목·가중치가
      "장기적으로 통한다"는 어떤 통계적 주장도 하지 않는다. 딱 하나만 말한다: 2026-09-18 현재 시점에
      이 저장소의 기존 4팩터 스크리닝 엔진을 그대로 돌리면 무엇이 나오는지, 그리고 그 결과가 몇 가지
      독립적인 감사를 견디는지.</p>
    <p>새 스크리닝 로직은 만들지 않았다 — <code>core.stock_discovery.discover_candidates()</code>
      (모멘텀0.30/성장0.30/가치0.25/퀄리티0.15 기본 가중치의 percentile 합성 스코어)만 그대로
      호출했다. S&amp;P500 503개 종목 전체를 대상으로, 시총 상한 없이(<code>tenbagger_stock_picking_
      research</code>가 시총상한을 걸어 정보기술 섹터에서 0개를 얻었던 것과 의도적으로 다른 조건).</p>
  </section>

  <section class="section" id="top20">
    <h2><span class="sec-no">01</span> 오늘의 상위 20 — 기본가중치(모멘텀0.30/성장0.30/가치0.25/퀄리티0.15)</h2>
    <p class="lede">굵게 표시한 종목(하이라이트)은 아래 02절에서 3개 가중치 변형 전부에 공통으로 등장하는
      "가중치 불문 핵심 신호" 10종목이다.</p>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>종목/섹터</th><th>종합점수</th><th>모멘텀</th><th>성장</th><th>가치</th><th>퀄리티</th><th>시가총액</th></tr></thead>
        <tbody>{top20_rows("default", highlight=CORE_ALL3)}</tbody>
      </table>
    </div>
  </section>

  <section class="section" id="h1">
    <h2><span class="sec-no">02</span> H1 강건성 — 가중치를 바꿔도 상위 종목이 안정적인가</h2>
    <p class="lede">시계열이 없어 순열검정을 못 쓰는 대신, "합리적인 다른 가중치를 줬을 때도 같은 종목이
      뽑히는가"를 강건성의 대리지표로 쓴다. 모멘텀중심(0.60/0.20/0.10/0.10)과 퀄리티중심(0.10/0.20/0.20/0.50)
      두 극단 변형을 기본가중치와 상위20 자카드 유사도로 비교했다.</p>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>비교쌍</th><th>중첩(상위20)</th><th>자카드</th><th>공통 종목</th></tr></thead>
        <tbody>{overlap_rows()}</tbody>
      </table>
    </div>
    <p class="caveat"><b>가중치 불문 핵심 신호(3개 변형 전부 상위20 공통, {len(CORE_ALL3)}종목):</b>
      {esc(", ".join(CORE_ALL3))} — 상위20의 정확히 절반이 가중치 선택과 무관하게 살아남는다는 뜻으로,
      완전히 임의적인 결과는 아니다. 다만 모멘텀중심 vs 퀄리티중심 자카드는 {pct(OV_MOM_QUAL['jaccard'],0)}로
      가장 낮아, "무엇을 강조하느냐"가 여전히 결과의 절반 이상을 바꾼다.</p>
  </section>

  <section class="section" id="h2">
    <h2><span class="sec-no">03</span> H2 교차검증 — 상향식 스코어가 하향식 섹터강도 엔진과 일치하는가</h2>
    <p class="lede"><code>core.sector_strength.get_latest_theme_strength_snapshot()</code>(오늘
      {esc(H2['theme_snapshot_computed_at'][:16] if H2['theme_snapshot_computed_at'] else '—')} 계산,
      새로 계산하지 않고 최신 저장 스냅샷 그대로 사용)이 독립적으로 뽑은 오늘의 최강 테마 5개는
      <b>{esc(TOP5_THEMES_STR)}</b> 순이다.</p>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>테마</th><th>RS점수</th><th>3개월수익</th><th>12개월수익</th><th>추세</th></tr></thead>
        <tbody>{theme_rows_html()}</tbody>
      </table>
    </div>
    <p>반도체·사이버보안·클라우드·기술 4개(정보기술 계열)가 상위5 중 4자리를 차지하고 에너지가 3위에
      끼어 있다. 이걸 상위 20(기본가중치)의 실제 GICS 섹터 분포와 대조하면:</p>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>섹터</th><th>상위20 중</th><th>비중</th></tr></thead>
        <tbody>{sector_count_rows()}</tbody>
      </table>
    </div>
    <div class="callout warn">
      <div class="callout-title">불일치 발견</div>
      <p>하향식 엔진은 정보기술 계열 테마 4개를 상위5 중 4자리에 올렸지만, 상향식 합성스코어의 상위20은
        정보기술이 {TECH_COUNT}종목({pct(TECH_COUNT/20,0)})뿐이고 오히려 에너지가 {ENERGY_COUNT}종목
        ({pct(ENERGY_COUNT/20,0)})으로 압도적 1위다. 원인은 구조적이다 — 하향식 RS점수는 순수 가격추세
        (ROC 가중합)만 보는 반면, 상향식 종합점수는 가치·퀄리티 팩터가 각각 25%/15% 비중을 차지해 이미
        많이 오른(그래서 밸류에이션이 비싸진) 반도체/클라우드 개별종목의 가치 점수를 깎아먹는다. 실제로
        핫섹터 필터(정보기술+에너지)를 강제로 걸어도(05절 인접, 하단 표) 그 안에서조차 에너지 종목이
        기술 종목보다 위에 온다 — "가장 뜨거운 테마"와 "가장 매력적인 개별종목 점수"는 이 엔진 설계상
        다른 질문이라는 뜻이다.</p>
    </div>
    <h3>핫섹터(정보기술+에너지) 필터 적용 시 상위15</h3>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>종목/섹터</th><th>종합점수</th><th>모멘텀</th><th>성장</th><th>가치</th><th>퀄리티</th><th>시가총액</th></tr></thead>
        <tbody>{top20_rows(HOT15)}</tbody>
      </table>
    </div>
  </section>

  <section class="section" id="h3">
    <h2><span class="sec-no">04</span> H3 밸류에이션 갭 — 고든성장모형 정당PER/PBR이 오늘의 상위 후보에 실제로 적용되는가</h2>
    <p class="lede"><code>tenbagger_stock_picking_research</code>가 유도한 공식을 새로 만들지 않고 그대로
      재사용: 정당 P/E=(1-b)(1+g)/(r-g), g=b·ROE, b=이익유보율, r=9%(요구수익률). ROE는 trailingEps/bookValue
      프록시. r≤g면 모형이 수학적으로 붕괴(분모 발산)해 정당PER/PBR을 계산하지 않는다.</p>
    <div class="kpi-row">
      <div class="kpi-tile"><div class="kpi-label">모형 붕괴 (g≥r)</div>
        <div class="kpi-value neg">{N_COLLAPSED}/{N_TOTAL}</div>
        <div class="kpi-sub">{pct(N_COLLAPSED/N_TOTAL,0)} — 정당PER/PBR 계산 자체가 불가능</div></div>
      <div class="kpi-tile"><div class="kpi-label">수치적으로 불안정 (g≈r, 0.9r 이상)</div>
        <div class="kpi-value">{N_UNSTABLE}/{N_TOTAL}</div>
        <div class="kpi-sub">모형은 살아있지만 분모가 0에 가까워 값이 폭주</div></div>
      <div class="kpi-tile"><div class="kpi-label">신뢰 가능한 비교 가능</div>
        <div class="kpi-value">{N_RELIABLE}/{N_TOTAL}</div>
        <div class="kpi-sub">고평가 {N_RICH} · 저평가 {N_CHEAP}</div></div>
    </div>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>종목</th><th>ROE(프록시)</th><th>지속가능성장g</th><th>정당PER</th><th>실제PER</th><th>정당PBR</th><th>실제PBR</th><th>판정</th></tr></thead>
        <tbody>{valuation_rows()}</tbody>
      </table>
    </div>
    <div class="callout warn">
      <div class="callout-title">정직한 한계</div>
      <p>상위20 중 {pct(N_COLLAPSED/N_TOTAL,0)}가 g≥r로 모형 자체가 붕괴한다 — trailingEps/bookValue
        ROE프록시가 레버리지 높은 업종(에너지·보험·금융)에서 자기자본 대비 이익을 과대평가하고, 배당성향이
        낮은 종목은 유보율 b가 1에 가까워 g=b·ROE가 쉽게 9%를 넘는다. 이건 "오늘의 상위 후보가 전부
        고성장주라 모형이 못 따라간다"는 낙관적 해석보다는, <b>이 저장소가 확립한 고든모형 밸류에이션
        체크가 오늘처럼 에너지·금융 중심의 스크리닝 결과에는 구조적으로 적용하기 어렵다</b>는 방법론적
        한계로 읽는 게 더 정직하다 — 결측/실패를 그대로 보고한다는 이 트랙의 원칙에 따라 완화하지
        않는다. 살아남은 {N_RELIABLE}종목도 절반 가까이(고평가 {N_RICH}, 저평가 {N_CHEAP})로 갈려
        일관된 방향이 없다.</p>
    </div>
  </section>

  <section class="section" id="h4">
    <h2><span class="sec-no">05</span> H4(보너스) 시가총액 분포 — 텐베거 후보인가, 대형주 로테이션인가</h2>
    <p class="lede">이번엔 시총 상한을 아예 걸지 않고(작업26의 텐베거 스크리닝은 시총상한을 걸어 정보기술
      섹터 0개를 얻었다) 순수 종합점수로만 상위20을 뽑았다 — 그런데도 결과가 어떻게 나오는지 확인한다.</p>
    <div class="kpi-row">
      <div class="kpi-tile"><div class="kpi-label">시총 &lt; $10B (소형/중형)</div>
        <div class="kpi-value">{H4['n_below_10b']}/20</div></div>
      <div class="kpi-tile"><div class="kpi-label">시총 &lt; $2B (진짜 소형)</div>
        <div class="kpi-value">{H4['n_below_2b']}/20</div></div>
      <div class="kpi-tile"><div class="kpi-label">시총 범위</div>
        <div class="kpi-value" style="font-size:16px;">{fmoney_b(H4['min'][1])} ~ {fmoney_b(H4['max'][1])}</div>
        <div class="kpi-sub">{esc(H4['min'][0])} ~ {esc(H4['max'][0])}</div></div>
    </div>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>종목</th><th>시가총액</th></tr></thead>
        <tbody>{mktcap_rows()}</tbody>
      </table>
    </div>
    <div class="callout warn">
      <div class="callout-title">핵심 발견 — 텐베거 리포트의 구조적 한계가 다시 확인됨</div>
      <p>시총상한을 아예 걸지 않았는데도 상위20 전부가 $13.4B(SWK) ~ $414.4B(CVX) 범위의 대형주/메가캡이다
        — $10B 미만은 0종목, $2B 미만은 0종목. <code>tenbagger_stock_picking_research</code>(작업26)가
        "핫섹터+시총상한을 걸었더니 정보기술에서 0종목"이라고 보고했던 구조적 한계를, 이번엔 시총상한 없이
        순수 팩터 스코어만으로도 그대로 재확인한 셈이다 — S&amp;P500 유니버스 자체가 이미 "크게 자란"
        종목들의 집합이라, 어떤 팩터 가중치를 쓰든 이 엔진은 IREN·CIFR류(트랙C No.2~7이 다룬, 상장 초기
        고변동성·저시총 테마주)와 같은 성격의 진짜 텐베거 후보를 원천적으로 걸러낼 수 없다. 오늘 상위권은
        "10배가 될 종목"이 아니라 "지금 실적·모멘텀·밸류에이션이 맞아떨어지는 이미 큰 종목의 로테이션
        후보"에 가깝다.</p>
    </div>
  </section>

  <section class="section" id="synthesis">
    <h2><span class="sec-no">06</span> 종합 — 오늘 시점에서 실제로 뭘 시사하는가</h2>
    <div class="callout">
      <div class="callout-title">4가지 감사 요약</div>
      <p><b>H1(강건성):</b> 상위20의 절반({len(CORE_ALL3)}종목)이 3개 가중치 변형 전부에서 살아남아
        완전한 노이즈는 아니지만, 극단 변형 간 자카드가 {pct(OV_MOM_QUAL['jaccard'],0)}까지 떨어져
        가중치 선택이 여전히 결과의 절반 이상을 좌우한다. <b>H2(교차검증):</b> 하향식 엔진이 꼽은 최강
        테마(반도체·사이버보안·클라우드·기술)와 상향식 종합점수 상위 종목(에너지·금융 중심)이 정면으로
        어긋난다 — "가장 뜨거운 테마"와 "가장 매력적인 개별종목"은 이 두 엔진 설계상 다른 질문에 답하고
        있다는 걸 오늘 처음 실측으로 확인했다. <b>H3(밸류에이션):</b> 이 저장소의 고든모형 체크가 상위20의
        {pct(N_COLLAPSED/N_TOTAL,0)}에서 아예 적용 불가능(모형 붕괴)이고, 나머지도 방향이 갈린다 —
        "싸다/비싸다"는 깔끔한 결론을 오늘의 후보군엔 낼 수 없다. <b>H4(시가총액):</b> 시총상한 없이도
        전부 대형주/메가캡 — 텐베거 리포트가 진단한 구조적 한계가 다른 방법으로도 재확인됐다.</p>
    </div>
    <p><b>정직한 결론:</b> 오늘(2026-09-18) 이 엔진이 뽑은 상위 종목들은 "10배가 될 후보"라기보다
      실적·모멘텀·밸류에이션이 동시에 괜찮은 대형 에너지/금융주 로테이션 후보에 가깝다. 4개 감사 중
      뚜렷하게 통과한 건 없다 — 강건성은 절반만, 교차검증은 불일치, 밸류에이션은 대부분 적용 불가,
      시가총액은 텐베거 후보군을 원천 배제. 이건 실패가 아니라 이 엔진의 설계 범위를 오늘 데이터로
      정직하게 그은 것이다: <code>discover_candidates()</code>는 "지금 좋아 보이는 대형주 로테이션
      후보"를 찾는 도구지, "다음 IREN"을 찾는 도구가 아니다.</p>
  </section>

  <section class="section" id="limitations">
    <h2><span class="sec-no">07</span> 한계</h2>
    <ul>
      <li>이건 단일 시점 스냅샷이다 — 다음 날 재실행하면 순위가 달라질 수 있고, 이 리포트는 그 안정성을
        시계열로 검증하지 않는다(가중치 변형 간 비교만 했을 뿐, 날짜 간 비교는 하지 않았다).</li>
      <li>H1의 "강건성"은 순열검정이 아니라 가중치 3종 교차비교라는 약한 대리지표다 — 통계적 유의성
        주장이 아니다.</li>
      <li>H2의 테마→GICS 매핑은 <code>tenbagger_stock_picking_research</code>의 근사 관례를 그대로
        재사용한 수작업 매핑이라 완벽하지 않다(예: "냉각"·"우주" 같은 틈새 테마는 표준 GICS와 깔끔하게
        대응되지 않음).</li>
      <li>H3의 ROE 프록시(trailingEps/bookValue)는 자사주매입·일회성 손익·레버리지 차이를 구분하지
        못해 모형 붕괴 비율이 과대평가됐을 가능성이 있다 — 더 정교한 ROE(예: 5년 평균, 정상화 이익)를
        쓰면 붕괴 비율이 낮아질 수 있지만 이번 라운드는 기존 공식을 그대로 재사용하는 원칙을 지켰다.</li>
      <li>discover_candidates()는 fundamentals/valuation 데이터가 전부 없는 종목을 조용히 제외한다 —
        이번 스캔에서 제외된 종목 수는 기록하지 않았다(향후 라운드 보완 과제).</li>
      <li>market_cap 상한 없이도 대형주만 나온 것은 S&amp;P500 유니버스 자체의 구조적 한계이지 이
        스크리닝 로직의 버그가 아니다 — 진짜 소형 텐베거 후보를 찾으려면 애초에 Russell 2000류의
        더 넓은 유니버스가 필요하다는 게 이 라운드가 재확인한 결론이다.</li>
    </ul>
  </section>

</div>

<footer>
  <p>QUANT RESEARCH · 트랙C 라이브 스크리닝 스냅샷 · 기준 {esc(META['as_of_scan'])}(재실행 {esc(GEN)}) ·
    이 문서는 투자 조언이 아니며 저자 개인의 연구 기록입니다. 특정 종목명은 매수/매도 추천이 아니라
    스크리닝 엔진 산출물의 예시입니다.</p>
</footer>
"""

with open(f"{OUT_DIR}/final_report.html", "w", encoding="utf-8") as f:
    f.write(HTML)
print("[build_report] saved final_report.html")
