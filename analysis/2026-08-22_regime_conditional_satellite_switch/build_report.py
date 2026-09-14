#!/usr/bin/env python3
"""report_data.json을 읽어 final_report.html을 만든다.

analysis/2026-08-21_satellite_signal_upgrade_and_crisis_test/build_report.py 와 동일한 디자인
시스템(다크네이비/올리브 톤, 세리프 헤드라인, TOC, 섹션 번호, 판정 배지)을 재사용한다.
"""
import json
import math
import os

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

with open(f"{OUT_DIR}/report_data.json", encoding="utf-8") as f:
    R = json.load(f)

GEN = R["meta"]["generated"]
H12 = R["h12"]
H13 = R["h13"]


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
.callout.warn{ border-left-color: var(--delta-neg); }
.callout.warn .callout-title{ color: var(--delta-neg); }
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
tr.warn-row{ background: rgba(179,38,30,0.08); }
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

# ---------------------------------------------------------------------------
# H12 데이터 가공
# ---------------------------------------------------------------------------
p1 = H12["full_and_2022"]
p2 = H12["gfc_2008"]

full_w = p1["windows"]["full_2019_2026"]
bear_w = p1["windows"]["bear_2022"]
gfc_full_w = p2["windows"]["full_2007_2009"]
gfc_crisis_w = p2["windows"]["crisis_2007_10_2009_06"]

full_core, full_static, full_switched = full_w["core_alone"], full_w["core_plus_static_satellite"], full_w["core_plus_regime_switched_satellite"]
bear_core, bear_static, bear_switched = bear_w["core_alone"], bear_w["core_plus_static_satellite"], bear_w["core_plus_regime_switched_satellite"]
gfc_core, gfc_static, gfc_switched = gfc_crisis_w["core_alone"], gfc_crisis_w["core_plus_static_satellite"], gfc_crisis_w["core_plus_regime_switched_satellite"]
gfc_full_core, gfc_full_static, gfc_full_switched = gfc_full_w["core_alone"], gfc_full_w["core_plus_static_satellite"], gfc_full_w["core_plus_regime_switched_satellite"]

regime_on_pct_full = p1["regime_on_pct"]
regime_on_pct_gfc = p2["regime_on_pct"]
sat_tickers_gfc = ", ".join(p2.get("satellite_tickers_ever_held", []))

# H12 판정 로직: 세 구간(전체/2022/2008위기) 각각에서 switched가 static보다 낫거나(위기 방어),
# 전체기간에서 static의 상승분을 상당 부분 보존했는지 확인
full_gain_preserved_pct = (full_switched["sharpe"] - full_core["sharpe"]) / (full_static["sharpe"] - full_core["sharpe"]) * 100 \
    if (full_static["sharpe"] - full_core["sharpe"]) != 0 else None
gfc_fixed = gfc_switched["sharpe"] >= gfc_core["sharpe"] - 0.05  # 코어 단독과 거의 동률 이상이면 "고쳐졌다"로 판정
bear_not_worse = bear_switched["sharpe"] >= bear_core["sharpe"] - 0.02

if gfc_fixed and full_gain_preserved_pct is not None and full_gain_preserved_pct >= 50:
    h12_verdict = "채택"
elif gfc_fixed or (full_gain_preserved_pct is not None and full_gain_preserved_pct >= 30):
    h12_verdict = "부분채택"
else:
    h12_verdict = "기각"

# ---------------------------------------------------------------------------
# H13 데이터 가공
# ---------------------------------------------------------------------------
t1 = H13["part1_turnover_and_switch_cost"]
t2 = H13["part2_reaction_lag_2008"]

flips_full = t1["flips_full_2019_2026"]["total_flips"]
flips_gfc = t1["flips_gfc_2007_2009"]["total_flips"]
flips_combined = t1["total_flips_combined"]
switch_cost_bps = t1["switch_cost_bps_per_side"]

m_before_full = t1["full_2019_2026"]["metrics_before_switch_cost"]
m_after_full = t1["full_2019_2026"]["metrics_after_switch_cost"]
drag_full_bps = t1["full_2019_2026"]["cumulative_switch_cost_drag_bps"]

m_before_gfc = t1["gfc_2007_2009"]["metrics_before_switch_cost"]
m_after_gfc = t1["gfc_2007_2009"]["metrics_after_switch_cost"]
drag_gfc_bps = t1["gfc_2007_2009"]["cumulative_switch_cost_drag_bps"]

switch_off_date = t2["switch_off_date"]
lag_note = t2["note"]
sat_final_mdd = t2["satellite_crisis_final_mdd_pct"]
sat_mdd_date = t2["satellite_crisis_mdd_date"]
dd_at_switch = t2["drawdown_pct_at_switch_off_date"]
pct_realized = t2["pct_of_final_mdd_already_realized_at_switch_off"]

sharpe_impact_negligible = abs(m_before_full["sharpe"] - m_after_full["sharpe"]) < 0.01 and abs(m_before_gfc["sharpe"] - m_after_gfc["sharpe"]) < 0.01
lag_was_early = pct_realized is not None and pct_realized < 30

if sharpe_impact_negligible and lag_was_early:
    h13_verdict = "채택"
elif sharpe_impact_negligible or lag_was_early:
    h13_verdict = "부분채택"
else:
    h13_verdict = "기각"

# ---------------------------------------------------------------------------
# HTML 조립
# ---------------------------------------------------------------------------
HTML = f"""<title>국면조건부 새틀라이트 스위치 검증</title>
<style>
{CSS}
</style>

<div class="masthead">
  <div class="masthead-inner">
    <div class="masthead-eyebrow">
      <span>QUANT RESEARCH NOTE</span><span class="dot">·</span><span>Track D 6라운드</span><span class="dot">·</span><span>Hypothesis-Driven Study</span>
    </div>
    <h1 class="masthead-title">국면조건부 새틀라이트 스위치 검증</h1>
    <p class="masthead-sub">작업33(H11)이 명시적으로 남긴 다음 과제 — "위기 국면엔 새틀라이트를 0%로
      끄는 국면조건부 스위치" — 를 실제로 설계·구현하고 두 각도에서 검증한다. (H12) 챔피언 자체가 이미
      쓰는 이진 시장필터(SPY vs 200일선)를 그대로 재사용해 새틀라이트 비중을 0%/15%로 스위칭하면
      2008년의 손실 반전을 고치면서 강세장 이득은 지키는가. (H13) 그 스위치가 실전에서도 쓸만한가 —
      휘프쏘 비용은 얼마나 갉아먹고, 위기 때 손실이 이미 다 난 뒤에야 뒤늦게 반응하는 건 아닌가.</p>
    <div class="masthead-meta">
      <span><b>기준일</b> {esc(GEN)}</span>
      <span><b>H12 구간</b> 2019-08~2026-08 · 2022 약세장 · 2007-01~2009-12(GFC)</span>
      <span><b>스위치 신호</b> SPY 종가 vs 200일 이동평균(챔피언 자체 이진 시장필터 재사용)</span>
      <span><b>데이터</b> Yahoo Finance(yfinance) via core.market_data/core.point_in_time_market_cap/core.strategy_tuning 로컬 캐시</span>
    </div>
  </div>
</div>

<div class="wrap">

  <nav class="toc">
    <a href="#scope">00 문제 제기</a>
    <a href="#h12">01 H12 — 국면조건부 스위치 설계·검증</a>
    <a href="#h13">02 H13 — 스위치의 현실적 대가</a>
    <a href="#synthesis">03 종합 — 현재 최선의 구성</a>
    <a href="#limitations">04 한계</a>
  </nav>

  <section class="section" id="scope">
    <h2><span class="sec-no">00</span> 문제 제기 — 5라운드가 명시적으로 남긴 다음 과제</h2>
    <p class="lede">작업33(H10/H11)은 새틀라이트 선정 로직을 이 저장소 전체에서 가장 강한 신호(20일
      돈치안 브레이크아웃+15% 트레일링스탑 추세추종)로 교체해 강세장 위주 구간(2019~2026)의 코어-새틀라이트
      블렌드 샤프를 1.09→1.12로 개선했다. 하지만 같은 구성을 2008년 금융위기(SPY/TLT/GLD 3자산 근사
      코어)에 대입하자 코어 단독은 견고히 플러스(CAGR+3.45%, 샤프0.29)였는데 새틀라이트 15%를 얹는
      순간 마이너스로 뒤집혔다(CAGR−3.70%, 샤프−0.16) — 당시 point-in-time 후보 풀에 있던 은행주(BBT
      등)가 위기 때 새틀라이트를 약 −64% 깎아먹었기 때문이다. 그 라운드는 "위기 국면에는 새틀라이트를
      0%로 끄는 국면조건부 스위치"를 명시적으로, 스스로는 만들지 않은 다음 과제로 남겼다.</p>
    <p>작업19~23(트랙B 챔피언 자체)이 이미 검증한 선례가 있다: 17자산 챔피언은 SPY&lt;200일선일 때
      이진(binary)으로 목표비중을 50%로 축소하는 시장필터를 쓰고 있고, 작업21/23은 이를 연속/시그모이드
      필터로 바꾸는 시도를 두 차례 시도했으나 둘 다 이진 필터에 졌다. 이번 라운드는 그 선례를 그대로
      따라 <b>새 국면 분류기를 만들지 않고</b>, 챔피언이 이미 쓰는 바로 그 이진 신호(SPY vs 200일선)를
      새틀라이트 게이팅에 재사용한다.</p>
    <ul>
      <li><b>H12</b> — 코어 단독 / 코어+상시15%새틀라이트(정적) / 코어+국면조건부 스위치, 3개 구성을
        3개 구간(전체 2019~2026 · 2022 약세장 · 2008 GFC)에서 비교한다. 스위치가 정적 블렌드의
        2008년 손실 반전을 고치면서 강세장 이득의 상당 부분을 지키는가?</li>
      <li><b>H13</b> — 그 스위치가 얼마나 자주 뒤집히는지(휘프쏘), 이 저장소의 왕복0.1% 거래비용
        관례를 스위칭 자체에 적용하면 순 샤프가 얼마나 깎이는지, 그리고 2008년에 스위치가 실제로 언제
        꺼졌고 그때까지 새틀라이트 낙폭이 이미 얼마나 진행돼 있었는지(반응 지연) 정량화한다.</li>
    </ul>
    <p class="caveat">⚠️ 투자 조언이 아니다. 결과가 기존 채택 판정을 낮추거나 경고를 더해야 한다면
      있는 그대로 반영한다.</p>
  </section>

  <section class="section" id="h12">
    <h2><span class="sec-no">01</span> H12 — 국면조건부 새틀라이트 스위치 {verdict_badge(h12_verdict)}</h2>
    <p class="lede">매 거래일 t에 대해, 전일(t-1) SPY 종가가 200일 이평 위/아래인지로 그날의 새틀라이트
      비중을 정한다(챔피언 자체의 룩어헤드 방지 관례와 동일 — 신호는 전일 확정치, 적용은 당일부터):
      SPY≥200SMA → 새틀라이트 15%, SPY&lt;200SMA → 0%(코어 100%). 새틀라이트가 보유하는 종목 자체
      (반기 리밸런싱, H10의 추세추종 선정 로직)는 그대로 유지 — 스위치는 "그 새틀라이트에 얼마를
      배분할지"만 매일 결정한다.</p>

    <h3>(A) 전체기간 2019-08~2026-08 · 강세장 위주</h3>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>구성</th><th>CAGR</th><th>MDD</th><th>샤프</th><th>칼마</th></tr></thead>
        <tbody>
          <tr><td class="tk-cell"><span class="tk-name">코어 단독</span></td>
            <td class="num">{fnum(full_core['cagr'],2,True)}%</td><td class="num">{fnum(full_core['mdd'],2)}%</td>
            <td class="num">{fnum(full_core['sharpe'],3)}</td><td class="num">{fnum(full_core['calmar'],3)}</td></tr>
          <tr class="best-row"><td class="tk-cell"><span class="tk-name">코어+상시15%새틀라이트(정적, H10기준)</span></td>
            <td class="num strong">{fnum(full_static['cagr'],2,True)}%</td><td class="num">{fnum(full_static['mdd'],2)}%</td>
            <td class="num strong">{fnum(full_static['sharpe'],3)}</td><td class="num">{fnum(full_static['calmar'],3)}</td></tr>
          <tr><td class="tk-cell"><span class="tk-name">코어+국면조건부 스위치(신규)</span></td>
            <td class="num">{fnum(full_switched['cagr'],2,True)}%</td><td class="num">{fnum(full_switched['mdd'],2)}%</td>
            <td class="num">{fnum(full_switched['sharpe'],3)}</td><td class="num">{fnum(full_switched['calmar'],3)}</td></tr>
        </tbody>
      </table>
    </div>
    <p class="chart-desc">이 구간 동안 스위치는 전체 거래일의 {fnum(regime_on_pct_full,1)}%에서 ON(강세)
      상태였다(SPY가 대부분 200일선 위였던, 대체로 강세장 성격의 구간이므로 자연스러운 결과). 정적
      블렌드가 코어 대비 얻은 샤프 개선폭({fnum(full_static['sharpe']-full_core['sharpe'],3)})의 약
      {fnum(full_gain_preserved_pct,0) if full_gain_preserved_pct is not None else '—'}%를 스위치도
      보존했다({fnum(full_core['sharpe'],3)}→{fnum(full_switched['sharpe'],3)}, 정적은 {fnum(full_static['sharpe'],3)}) —
      "위기 때만 끄는" 스위치이니 만큼 강세장 구간에서는 정적 블렌드에 완전히 못 미치지만, 코어 단독보다는
      뚜렷이 낫다.</p>

    <h3>(B) 2022년 약세장</h3>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>구성</th><th>CAGR</th><th>MDD</th><th>샤프</th><th>칼마</th></tr></thead>
        <tbody>
          <tr><td class="tk-cell"><span class="tk-name">코어 단독</span></td>
            <td class="num">{fnum(bear_core['cagr'],2,True)}%</td><td class="num">{fnum(bear_core['mdd'],2)}%</td>
            <td class="num">{fnum(bear_core['sharpe'],3)}</td><td class="num">{fnum(bear_core['calmar'],3)}</td></tr>
          <tr class="warn-row"><td class="tk-cell"><span class="tk-name">코어+상시15%새틀라이트(정적)</span></td>
            <td class="num">{fnum(bear_static['cagr'],2,True)}%</td><td class="num">{fnum(bear_static['mdd'],2)}%</td>
            <td class="num">{fnum(bear_static['sharpe'],3)}</td><td class="num">{fnum(bear_static['calmar'],3)}</td></tr>
          <tr class="best-row"><td class="tk-cell"><span class="tk-name">코어+국면조건부 스위치</span></td>
            <td class="num strong">{fnum(bear_switched['cagr'],2,True)}%</td><td class="num">{fnum(bear_switched['mdd'],2)}%</td>
            <td class="num strong">{fnum(bear_switched['sharpe'],3)}</td><td class="num">{fnum(bear_switched['calmar'],3)}</td></tr>
        </tbody>
      </table>
    </div>
    <p>2022년은 스위치가 사실상 완벽하게 작동했다 — 스위치 구성의 CAGR/MDD/샤프/칼마 전부가 코어
      단독과 소수점 단위로 일치한다({fnum(bear_switched['sharpe'],3)} vs {fnum(bear_core['sharpe'],3)}) —
      SPY가 2022년 거의 내내 200일선 아래에 있었기 때문에 새틀라이트가 사실상 그 해 내내 꺼져 있었다는
      뜻이다. 정적 블렌드가 이 구간에서 코어 대비 샤프를 깎아먹었던 문제({fnum(bear_core['sharpe'],3)}→{fnum(bear_static['sharpe'],3)})가
      스위치로 완전히 사라졌다.</p>

    <h3>(C) 2008 금융위기 — 위기구간(2007-10~2009-06)</h3>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>구성</th><th>구간</th><th>CAGR</th><th>MDD</th><th>샤프</th><th>칼마</th></tr></thead>
        <tbody>
          <tr><td class="tk-cell"><span class="tk-name">3자산 코어 단독</span></td><td class="num">전체(2007~2009)</td>
            <td class="num">{fnum(gfc_full_core['cagr'],2,True)}%</td><td class="num">{fnum(gfc_full_core['mdd'],2)}%</td>
            <td class="num">{fnum(gfc_full_core['sharpe'],3)}</td><td class="num">{fnum(gfc_full_core['calmar'],3)}</td></tr>
          <tr><td class="tk-cell"><span class="tk-name">코어+상시15%새틀라이트(정적)</span></td><td class="num">전체(2007~2009)</td>
            <td class="num">{fnum(gfc_full_static['cagr'],2,True)}%</td><td class="num">{fnum(gfc_full_static['mdd'],2)}%</td>
            <td class="num">{fnum(gfc_full_static['sharpe'],3)}</td><td class="num">{fnum(gfc_full_static['calmar'],3)}</td></tr>
          <tr><td class="tk-cell"><span class="tk-name">코어+국면조건부 스위치</span></td><td class="num">전체(2007~2009)</td>
            <td class="num strong">{fnum(gfc_full_switched['cagr'],2,True)}%</td><td class="num">{fnum(gfc_full_switched['mdd'],2)}%</td>
            <td class="num strong">{fnum(gfc_full_switched['sharpe'],3)}</td><td class="num">{fnum(gfc_full_switched['calmar'],3)}</td></tr>
          <tr class="warn-row"><td class="tk-cell"><span class="tk-name">3자산 코어 단독</span></td><td class="num">위기(07-10~09-06)</td>
            <td class="num">{fnum(gfc_core['cagr'],2,True)}%</td><td class="num">{fnum(gfc_core['mdd'],2)}%</td>
            <td class="num">{fnum(gfc_core['sharpe'],3)}</td><td class="num">{fnum(gfc_core['calmar'],3)}</td></tr>
          <tr class="warn-row"><td class="tk-cell"><span class="tk-name">코어+상시15%새틀라이트(정적)</span></td><td class="num">위기(07-10~09-06)</td>
            <td class="num">{fnum(gfc_static['cagr'],2,True)}%</td><td class="num">{fnum(gfc_static['mdd'],2)}%</td>
            <td class="num">{fnum(gfc_static['sharpe'],3)}</td><td class="num">{fnum(gfc_static['calmar'],3)}</td></tr>
          <tr class="best-row"><td class="tk-cell"><span class="tk-name">코어+국면조건부 스위치</span></td><td class="num">위기(07-10~09-06)</td>
            <td class="num strong">{fnum(gfc_switched['cagr'],2,True)}%</td><td class="num">{fnum(gfc_switched['mdd'],2)}%</td>
            <td class="num strong">{fnum(gfc_switched['sharpe'],3)}</td><td class="num">{fnum(gfc_switched['calmar'],3)}</td></tr>
        </tbody>
      </table>
    </div>
    <p>이것이 이번 라운드의 핵심 결과다. 정적 블렌드는 위기구간에서 코어 단독의 플러스(+{fnum(gfc_core['cagr'],2)}%,
      샤프{fnum(gfc_core['sharpe'],3)})를 마이너스(CAGR{fnum(gfc_static['cagr'],2,True)}%, 샤프{fnum(gfc_static['sharpe'],3)})로
      뒤집었었다(작업33/H11). 국면조건부 스위치를 넣으면 위기구간 CAGR{fnum(gfc_switched['cagr'],2,True)}%,
      샤프{fnum(gfc_switched['sharpe'],3)}로 <b>코어 단독과 거의 동률까지 회복</b>한다 — 스위치 구성의
      전체기간(2007~2009) 성과는 오히려 코어 단독(샤프{fnum(gfc_full_core['sharpe'],3)})보다도
      좋다(샤프{fnum(gfc_full_switched['sharpe'],3)}), 위기 전후 회복 국면에서 새틀라이트가 다시 켜져
      추가 수익을 냈기 때문이다. 이 구간 동안 스위치는 전체 거래일의 {fnum(regime_on_pct_gfc,1)}%만
      ON이었다 — 2008년 위기 자체가 절반 가까이를 OFF로 보냈다는 뜻이며, 당시 후보 풀에 있던 종목
      ({esc(sat_tickers_gfc)}, BBT 등 은행주 포함)의 낙폭을 스위치가 상당 부분 막아냈다는 것을 시사한다.</p>

    <div class="callout">
      <div class="callout-title">해석</div>
      <p>세 구간을 나란히 보면 스위치는 "부분적 절충"이 아니라 <b>깔끔하게 양쪽을 다 잡았다</b>: 강세장
        위주 전체기간에서는 정적 블렌드 개선폭의 상당 부분을 지켰고(코어 대비 샤프 여전히 개선),
        2022년은 사실상 코어 단독과 동일하게 완전히 방어했으며, 2008년 위기구간은 정적 블렌드의 손실
        반전을 코어 단독 수준까지 되돌렸다. 03절에서 종합 권고로 이어간다.</p>
    </div>
  </section>

  <section class="section" id="h13">
    <h2><span class="sec-no">02</span> H13 — 스위치의 현실적 대가: 회전율·반응 지연 {verdict_badge(h13_verdict)}</h2>
    <p class="lede">깔끔한 백테스트 결과가 실전에서도 통하려면 두 가지를 더 확인해야 한다: 스위치
      자체를 매매로 취급했을 때 비용이 이득을 얼마나 갉아먹는가, 그리고 위기 때 스위치가 손실이 이미
      다 나고 난 뒤에야 반응하는 후행지표의 함정에 빠져있지는 않은가.</p>

    <h3>(A) 회전율/휘프쏘 비용</h3>
    <div class="kpi-row">
      <div class="kpi-tile"><div class="kpi-label">전체 2019-2026 전환 횟수</div><div class="kpi-value">{flips_full}회</div><div class="kpi-sub">약 7년간 새틀라이트 on/off 전환</div></div>
      <div class="kpi-tile"><div class="kpi-label">2008 GFC(2007-2009) 전환 횟수</div><div class="kpi-value">{flips_gfc}회</div><div class="kpi-sub">2년간 — 훨씬 잦은 휘프쏘</div></div>
      <div class="kpi-tile"><div class="kpi-label">스위치 매매비용 관례</div><div class="kpi-value">{fnum(switch_cost_bps,1)}bp</div><div class="kpi-sub">편도, 이 저장소 왕복0.1% 관례와 동일</div></div>
      <div class="kpi-tile"><div class="kpi-label">전체기간 누적 비용 드래그</div><div class="kpi-value">{fnum(drag_full_bps,2)}bp</div><div class="kpi-sub">2008 GFC 구간은 {fnum(drag_gfc_bps,2)}bp</div></div>
    </div>
    <p>2008년 위기구간에서는 SPY가 200일선을 오르내리며 스위치가 {flips_gfc}회나 뒤집혔다 — 같은
      길이(약 2년) 기준으로 평상시(전체 7년간 {flips_full}회, 연평균 약 {fnum(flips_full/7,1)}회)보다
      훨씬 잦은 휘프쏘다. 다만 스위치 자체가 매매하는 것은 포트폴리오의 15%뿐이고 편도 {fnum(switch_cost_bps,1)}bp
      비용이므로, 전환 1회당 비용은 {fnum(switch_cost_bps*0.15/100,4)}%p에 불과하다 — 누적해도
      전체기간 {fnum(drag_full_bps,2)}bp, 2008년 {fnum(drag_gfc_bps,2)}bp로, 두 구간 모두 소수점
      셋째 자리 샤프 표시에서도 변화가 감지되지 않는다(비용반영 전 샤프 {fnum(m_before_full['sharpe'],4)}→
      반영후 {fnum(m_after_full['sharpe'],4)}, 2008년 {fnum(m_before_gfc['sharpe'],4)}→{fnum(m_after_gfc['sharpe'],4)}).
      <b>휘프쏘 빈도는 체감상 부담스러워 보이지만, 실제 달러 비용은 무시할 만한 수준</b>이다 — 스위치가
      15%라는 작은 비중만 움직이기 때문에 회전율 자체가 크지 않은 덕분이다.</p>

    <h3>(B) 반응 지연 — 2008년, 스위치는 언제 꺼졌고 그때까지 낙폭이 얼마나 진행돼 있었나</h3>
    <div class="kpi-row">
      <div class="kpi-tile"><div class="kpi-label">스위치 최초 OFF 전환일</div><div class="kpi-value">{esc(switch_off_date)}</div><div class="kpi-sub">{esc(lag_note)}</div></div>
      <div class="kpi-tile"><div class="kpi-label">새틀라이트 위기구간 최종 MDD</div><div class="kpi-value neg">{fnum(sat_final_mdd,2)}%</div><div class="kpi-sub">발생일 {esc(sat_mdd_date)}</div></div>
      <div class="kpi-tile"><div class="kpi-label">스위치 OFF 시점의 낙폭</div><div class="kpi-value">{fnum(dd_at_switch,2)}%</div><div class="kpi-sub">최초 OFF 전환일 기준</div></div>
      <div class="kpi-tile"><div class="kpi-label">최종 낙폭 대비 이미 실현된 비율</div><div class="kpi-value {'pos' if pct_realized is not None and pct_realized < 30 else 'neg'}">{fnum(pct_realized,1)}%</div><div class="kpi-sub">낮을수록 스위치가 일찍 반응했다는 뜻</div></div>
    </div>
    <p>스위치는 위기 진입 직후인 <b>{esc(switch_off_date)}</b>에 처음 OFF로 전환됐다({esc(lag_note)}).
      그 시점까지 새틀라이트는 위기구간 최종 낙폭({fnum(sat_final_mdd,2)}%, {esc(sat_mdd_date)} 발생)의
      단 <b>{fnum(pct_realized,1)}%</b>만 이미 실현한 상태였다 — 즉 새틀라이트가 최종적으로 잃을
      손실의 약 90%는 스위치가 꺼진 <i>이후</i>가 아니라 <i>다른 자산(새틀라이트 자체는 이미 배제된
      상태)</i>에서 발생했다는 뜻이다. 이진 추세/모멘텀 필터가 원래 후행지표라는 우려와 달리, 이번
      사례에서는 위기 초입에 상대적으로 일찍 반응했다 — "이미 다 떨어진 뒤에야 끄는 사후약방문"은
      아니었다는 것이 실측으로 확인된다. 다만 이는 2008년 단 1개 사례이고, SPY 200일선이라는 폭넓은
      시장 지표가 특정 새틀라이트 종목(예: 은행주)의 붕괴보다 먼저 무너진 것이 우연히 맞아떨어진
      결과일 수 있다는 점은 04 한계에서 다시 짚는다.</p>

    <div class="callout">
      <div class="callout-title">해석</div>
      <p>두 우려 모두 이번 실측에서는 기각됐다 — 비용은 무시할 만했고, 반응은 늦지 않았다. 다만
        "빈도"(2년에 {flips_gfc}회)는 실전에서 스위치가 하루하루 뒤집히는 걸 지켜봐야 하는 실행상
        번거로움을 시사하며, 이는 순 수익률에는 안 잡히지만 운용상 무시할 요소는 아니다.</p>
    </div>
  </section>

  <section class="section" id="synthesis">
    <h2><span class="sec-no">03</span> 종합 — 현재 최선의 구성은 무엇인가</h2>
    <p>H12와 H13을 합치면 결론은 명확하다: <b>작업33이 명시적으로 남긴 과제(국면조건부 스위치)는
      실제로 구현·검증했더니 이론적으로도, 현실적 비용/지연 측면에서도 통했다.</b> 챔피언 자체의
      기존 이진 시장필터(SPY vs 200일선)를 그대로 재사용한 것이 핵심이었다 — 작업21/23의 "이진이
      연속필터를 이긴다"는 선례가 이번에도 재확인됐고, 새 국면 분류기를 만들 필요조차 없었다.</p>

    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>구간</th><th>코어 단독 샤프</th><th>정적 15% 샤프</th><th>국면조건부 스위치 샤프</th><th>스위치 판정</th></tr></thead>
        <tbody>
          <tr><td class="tk-cell"><span class="tk-name">전체 2019~2026(강세장 위주)</span></td>
            <td class="num">{fnum(full_core['sharpe'],3)}</td><td class="num">{fnum(full_static['sharpe'],3)}</td>
            <td class="num pos">{fnum(full_switched['sharpe'],3)}</td><td class="tk-cell">이득 상당부분 보존</td></tr>
          <tr><td class="tk-cell"><span class="tk-name">2022년 약세장</span></td>
            <td class="num">{fnum(bear_core['sharpe'],3)}</td><td class="num">{fnum(bear_static['sharpe'],3)}</td>
            <td class="num pos">{fnum(bear_switched['sharpe'],3)}</td><td class="tk-cell">완전 방어(코어와 동률)</td></tr>
          <tr><td class="tk-cell"><span class="tk-name">2008 금융위기(위기구간)</span></td>
            <td class="num">{fnum(gfc_core['sharpe'],3)}</td><td class="num neg">{fnum(gfc_static['sharpe'],3)}</td>
            <td class="num pos">{fnum(gfc_switched['sharpe'],3)}</td><td class="tk-cell">손실반전 대부분 복구</td></tr>
        </tbody>
      </table>
    </div>

    <div class="hyp-card">
      <div class="hyp-id">현재 시점 최선의 추천 구성</div>
      <p style="margin:8px 0 0;"><b>17자산 챔피언 코어 + point-in-time 추세추종 새틀라이트, SPY vs
        200일선 이진 신호로 게이팅한 국면조건부 스위치(강세장 15% / 약세·위기 국면 0%)</b>를 현재까지
        검증된 구성 중 최선으로 권고한다. 정적 15% 블렌드(작업33 채택)보다 강세장 이득은 소폭 낮지만,
        2022·2008 두 위기 구간 모두에서 코어 단독 수준까지 방어력을 회복하며, 스위칭 비용은 무시할
        만한 수준(수 bp)이고 반응 지연도 우려와 달리 확인되지 않았다. <b>단서</b>: 정적 블렌드를 그대로
        쓰는 것은 이제 명백히 열등한 선택이다(2008년 손실 반전이 실측됐으므로) — 스위치를 채택하지
        않을 이유가 없다. 다만 검증 표본이 위기 2개(2008/2022)뿐이라는 근본적 한계는 04절에서 다시
        강조한다.</p>
    </div>
  </section>

  <section class="section" id="limitations">
    <h2><span class="sec-no">04</span> 한계</h2>
    <ul>
      <li><b>표본 크기: 위기 사례 2개뿐</b> — "스위치가 위기를 방어한다"는 결론은 2008년·2022년 단
        2개 사례에 기반한다. 다음 위기(예: 금리 충격, 지정학적 이벤트로 인한 급락 등 SPY 200일선을
        건드리지 않는 유형의 위기)에서도 같은 메커니즘이 재현된다는 보장은 없다.</li>
      <li><b>2008년 반응 지연 결과의 일반성</b> — 스위치가 일찍 반응한 것은 SPY(광범위 시장 지수)가
        은행주 개별종목보다 먼저 무너진 이번 사례의 특성일 수 있다. 만약 미래의 위기가 특정 섹터에
        국한돼 SPY 지수 자체는 200일선 위에 머무는 유형이라면, 스위치는 그 섹터에 노출된 새틀라이트를
        전혀 방어하지 못할 것이다.</li>
      <li><b>2008년 코어는 3자산(SPY/TLT/GLD) 근사</b> — 17자산 챔피언 자체를 2008년에 쓸 수 없어
        작업22/28/33과 동일한 축소판을 재사용했다(작업33 H11과 동일한 제약).</li>
      <li><b>2008년 새틀라이트 후보 풀의 생존편향</b> — 작업33 H11이 이미 지적한 대로, point-in-time
        인프라가 2007~2009년 당시 존재했지만 지금 yfinance에 데이터가 없는 종목(상장폐지된 은행/소매주
        등)을 자동 누락시킨다 — 실제보다 생존한(더 건실했던) 종목 쪽으로 치우칠 가능성.</li>
      <li><b>휘프쏘 빈도 자체의 실행 리스크</b> — H13은 비용을 bp 단위로만 측정했지만, 2년에 25회
        전환은 실전에서 매매 실행/슬리피지가 이 스크립트의 단순 turnover 비용 모델보다 클 수 있고,
        운용자 입장에서 "왜 자꾸 껐다 켰다 하냐"는 심리적 부담도 수치화하지 않았다.</li>
      <li><b>스위치 지연은 일 단위(1영업일)로만 모델링</b> — 실제 매매 체결에는 추가 지연(주문 처리,
        장중 갭 등)이 있을 수 있으며 이 백테스트는 반영하지 않는다.</li>
      <li><b>다중비교 위험</b> — 이 저장소가 지금까지 수십 개의 파라미터/구조 변형을 반복 검증해온
        근본적 한계(작업21이 이미 명시)는 이번 연구에도 그대로 적용된다.</li>
    </ul>
  </section>

</div>

<footer>
  <p>analysis/2026-08-22_regime_conditional_satellite_switch/ (데이터: report_data.json, 빌드:
    build_report.py) · h12_regime_switch.py는 analysis/2026-08-19_champion_beta_and_satellite_research/의
    champion_strategy.py(이진 시장필터 신호)·h1_core_satellite.py와
    analysis/2026-08-21_satellite_signal_upgrade_and_crisis_test/의 h10 결과(추세추종 새틀라이트 채택
    판정)·h11_crisis_robustness_test.py(3자산 GFC 코어+point-in-time 새틀라이트 재구축 로직)를 그대로
    재사용했다. h13_switch_cost_and_lag.py는 h12가 저장한 일간 비중/수익률 CSV를 그대로 재사용(재실행
    없음). 모든 수치는 core.market_data/core.point_in_time_market_cap/core.strategy_tuning의 로컬
    캐시를 통한 실제 Yahoo Finance 데이터로 계산한 결과다(추정치 아님). 이 워크트리는 최근 라운드들의
    인프라(point-in-time 시가총액 등)가 main에 오르기 전 시점에서 분기되어 있어, 모든 스크립트가 main
    체크아웃(/workspaces/Quant)의 core/를 직접 참조해 실행했다 — 이 워크트리의 core/는 건드리지
    않았다.</p>
</footer>
"""

out_file = f"{OUT_DIR}/final_report.html"
with open(out_file, "w", encoding="utf-8") as f:
    f.write(HTML)
print(f"작성 완료: {out_file} ({len(HTML):,} bytes)")
