#!/usr/bin/env python3
"""report_data.json을 읽어 final_report.html을 만든다.

analysis/2026-08-22_satellite_realtime_stop_and_reentry_research/build_report.py 와 동일한
디자인 시스템(다크네이비 계열 아님 - 실제로는 짙은 올리브/네이비 톤, 세리프 헤드라인, TOC,
섹션 번호, 판정 배지)을 그대로 재사용한다.
"""
import json
import math
import os

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

with open(f"{OUT_DIR}/report_data.json", encoding="utf-8") as f:
    R = json.load(f)

GEN = R["meta"]["generated"]
H18 = R["h18"]
H19 = R["h19"]


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
.wrap{ max-width: 980px; margin:0 auto; padding: 0 24px 96px; }
.masthead{ background: var(--accent); color: var(--accent-ink); padding: 56px 24px 40px; }
.masthead-inner{ max-width:980px; margin:0 auto; }
.masthead-eyebrow{ font-size:12.5px; letter-spacing:0.12em; text-transform:uppercase; opacity:0.82;
  font-family: ui-monospace, "SF Mono", Consolas, monospace; display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
.masthead-eyebrow .dot{ opacity:0.5; }
h1.masthead-title{ font-family:"Iowan Old Style","Palatino Linotype", Georgia, serif; font-weight:600;
  font-size: clamp(28px, 4.2vw, 44px); line-height:1.15; margin: 14px 0 10px; text-wrap: balance; max-width: 30ch; }
.masthead-sub{ font-size:16.5px; max-width:70ch; opacity:0.92; margin:0 0 22px; }
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
.lede{ font-size:16.5px; color:var(--ink-2); max-width:74ch; }
.section p{ max-width:78ch; }
.section > p, .section > .lede { margin-top: 0; }
.section li{ max-width:74ch; }
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
.chart-card{ background:var(--chart-surface); border:1px solid var(--hairline); border-radius:10px;
  padding:22px 22px 16px; margin: 22px 0; box-shadow: var(--shadow); }
.chart-card h3{ margin: 0 0 4px; font-size:16px; }
.chart-desc{ font-size:13.5px; color:var(--ink-muted); margin: 0 0 14px; max-width:none; }
.table-wrap{ overflow-x:auto; border:1px solid var(--hairline); border-radius:8px; background:var(--surface); }
table.data-table{ width:100%; border-collapse:collapse; font-size:13.5px; min-width:620px; }
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
footer{ max-width:980px; margin:40px auto 0; padding: 26px 24px 10px; border-top:1px solid var(--hairline);
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
.pareto-yes{ color:var(--delta-pos); font-weight:700; }
.pareto-no{ color:var(--ink-muted); }
"""

# ---------------------------------------------------------------------------
# H18 데이터 가공
# ---------------------------------------------------------------------------
EP_LABELS = {
    "gfc_2008": "2008 금융위기(GFC)", "correction_2015_2016": "2015-16 조정(중국/유가)",
    "selloff_2018": "2018년말 셀오프", "bear_2022": "2022 약세장", "covid_2020": "COVID 급락",
}
EP_ORDER = H18["meta"]["episode_order"]
summary_rows = {r["episode"]: r for r in H18["summary_table_crisis_window"]}

n_b_beats_a_sharpe = sum(1 for r in H18["summary_table_crisis_window"] if r["case_b_beats_case_a_sharpe"])
n_b_beats_a_mdd = sum(1 for r in H18["summary_table_crisis_window"] if r["case_b_beats_case_a_mdd"])
n_episodes = len(H18["summary_table_crisis_window"])

covid = summary_rows["covid_2020"]
gfc = summary_rows["gfc_2008"]

h18_verdict = "부분채택"  # 5개 중 MDD는 5/5 개선, Sharpe는 1/5만 개선 - 명백히 조건부

# ---------------------------------------------------------------------------
# H19 데이터 가공
# ---------------------------------------------------------------------------
FP = H19["frontier_points"]
STOP_LEVELS = H19["meta"]["stop_levels"]
pareto_sm = [p for p in FP if p["pareto_efficient_sharpe_vs_mdd"]]
pareto_bc = [p for p in FP if p["pareto_efficient_bull_cagr_vs_crisis_sharpe"]]

h19_verdict = "채택"  # 실제 파레토 프론티어가 만들어졌고 유의미한 스프레드가 있음


def episode_table_row(label):
    r = summary_rows[label]
    a = r["case_a_static_satellite"]
    b = r["case_b_realtime_exit_plus_switch"]
    c = r["core_alone"]
    cls = "best-row" if r["case_b_beats_case_a_sharpe"] else ""
    return (f'<tr class="{cls}"><td class="tk-cell"><span class="tk-name">{esc(EP_LABELS[label])}</span>'
            f'<div class="kpi-sub">{esc(r["crisis_window"][0])} ~ {esc(r["crisis_window"][1])}</div></td>'
            f'<td class="num">{fnum(c["cagr"],2,True)}% / {fnum(c["mdd"],2)}% / {fnum(c["sharpe"],2)}</td>'
            f'<td class="num">{fnum(a["cagr"],2,True)}% / {fnum(a["mdd"],2)}% / {fnum(a["sharpe"],2)}</td>'
            f'<td class="num">{fnum(b["cagr"],2,True)}% / {fnum(b["mdd"],2)}% / {fnum(b["sharpe"],2)}</td>'
            f'<td class="num">{"✔" if r["case_b_beats_case_a_sharpe"] else "✘"}</td>'
            f'<td class="num">{"✔" if r["case_b_beats_case_a_mdd"] else "✘"}</td></tr>')


def frontier_row(p):
    return (f'<tr><td class="tk-cell"><span class="tk-name">{fnum(p["stop_pct"]*100,0)}%</span></td>'
            f'<td class="num">{fnum(p["full_period_cagr"],2,True)}%</td>'
            f'<td class="num">{fnum(p["full_period_sharpe"],3)}</td>'
            f'<td class="num">{fnum(p["full_period_mdd"],2)}%</td>'
            f'<td class="num">{fnum(p["avg_crisis_cagr_5ep"],2,True)}%</td>'
            f'<td class="num">{fnum(p["avg_crisis_sharpe_5ep"],3)}</td>'
            f'<td class="num"><span class="{"pareto-yes" if p["pareto_efficient_sharpe_vs_mdd"] else "pareto-no"}">{"파레토" if p["pareto_efficient_sharpe_vs_mdd"] else "지배됨"}</span></td>'
            f'<td class="num"><span class="{"pareto-yes" if p["pareto_efficient_bull_cagr_vs_crisis_sharpe"] else "pareto-no"}">{"파레토" if p["pareto_efficient_bull_cagr_vs_crisis_sharpe"] else "지배됨"}</span></td></tr>')


# ---------------------------------------------------------------------------
# HTML 조립
# ---------------------------------------------------------------------------
HTML = f"""<title>위기 표본 확장과 실시간청산 리스크 프론티어 연구</title>
<style>
{CSS}
</style>

<div class="masthead">
  <div class="masthead-inner">
    <div class="masthead-eyebrow">
      <span>QUANT RESEARCH NOTE</span><span class="dot">·</span><span>Track D 9라운드</span><span class="dot">·</span><span>Hypothesis-Driven Study</span>
    </div>
    <h1 class="masthead-title">위기 표본 확장과 실시간청산 리스크 프론티어 연구</h1>
    <p class="masthead-sub">8라운드(작업36)는 "Case A(정적보유, 순수익 최대화) vs Case B(실시간청산+SPY스위치,
      위기방어)"라는 이분법을 확정했지만, 근거는 2008/2022 딱 두 개의 위기 표본과 두 개의 이산적
      구성뿐이었다. 이번 라운드는 (H18) COVID급락·2018년말 셀오프·2015-16 조정 세 개를 더해 표본을
      5개로 늘리고, (H19) 트레일링스탑 폭을 10~30%로 실제 스윕해 이분법을 연속 스펙트럼으로 바꾼다.</p>
    <div class="masthead-meta">
      <span><b>기준일</b> {esc(GEN)}</span>
      <span><b>H18 위기표본</b> 2008 GFC · 2015-16 조정 · 2018년말 · 2022 약세장 · COVID 2020(5개)</span>
      <span><b>H19 스윕</b> 트레일링스탑 10/15/20/25/30%</span>
      <span><b>데이터</b> Yahoo Finance(yfinance) via core.market_data/core.point_in_time_market_cap/core.strategy_tuning 로컬 캐시</span>
    </div>
  </div>
</div>

<div class="wrap">

  <nav class="toc">
    <a href="#scope">00 문제 제기</a>
    <a href="#h18">01 H18 — 위기 표본 확장(5개 에피소드)</a>
    <a href="#h19">02 H19 — 연속 스펙트럼 프론티어</a>
    <a href="#synthesis">03 종합 — 투자자 프로필별 구체적 권고</a>
    <a href="#limitations">04 한계</a>
  </nav>

  <section class="section" id="scope">
    <h2><span class="sec-no">00</span> 문제 제기 — 8라운드의 "다중 정답"을 더 정밀하게 보강한다</h2>
    <p class="lede">작업36(H16/H17)은 "순수 수익 극대화라면 정적보유(Case A), 위기·꼬리위험 방어가
      목적이라면 실시간청산+SPY스위치(Case B)"라는 명시적 트레이드오프로 트랙D를 마무리했다. 이
      결론 자체는 정직했지만 두 가지 근본적 한계를 스스로 안고 있었다: (1) 위기 국면 검증이 2008
      금융위기와 2022 약세장, 딱 <b>2개 표본</b>뿐이었고, (2) Case A/B는 트레일링스탑 15%를 켜고
      끄는 <b>2개의 이산적 극단</b>일 뿐, 그 사이 어딘가가 더 나을 수 있다는 가능성은 전혀 탐색되지
      않았다. 이번 라운드는 이 두 한계를 정면으로 다룬다.</p>
    <ul>
      <li><b>H18</b> — COVID 급락(2020-02-19~04-30, 역사상 가장 빠른 낙폭)·2018년말 셀오프
        (2018-09~2019-01, 더 얕고 짧은 조정)·2015-16 조정(중국 위안화 절하/유가 붕괴, 다른 원인의
        충격)을 추가해 위기 표본을 5개로 늘리고, 같은 3구성(코어단독/Case A/Case B) 비교를
        재실행한다. Case B가 5개 에피소드 전체에서 일관되게 이기는지, 아니면 특정 유형의 위기에서만
        통하는지를 있는 그대로 보고한다.</li>
      <li><b>H19</b> — "선정"은 H10 기준을 고정한 채 "청산" 트레일링스탑 폭만 10/15/20/25/30%로
        스윕해, Case A와 Case B 사이의 연속적인 위험-수익 프론티어를 실제로 그린다. 파레토 효율점을
        가려 "짧은 투자기간·낙폭 민감형" vs "장기보유·변동성 감내형" 투자자에게 각각 어떤 스탑
        수준이 맞는지 구체적으로 제시한다.</li>
    </ul>
    <p class="caveat">⚠️ 투자 조언이 아니다. 결과가 기대와 다르게 나오면(예: 위기방어 구성이 특정
      위기 유형에서 오히려 손해를 키우는 경우) 있는 그대로 반영한다.</p>
  </section>

  <section class="section" id="h18">
    <h2><span class="sec-no">01</span> H18 — 위기 표본 확장 검증(n=2 → n=5) {verdict_badge(h18_verdict)}</h2>
    <p class="lede">2008 GFC·2022 약세장은 작업36(H16)이 이미 계산한 결과를 재계산 없이 그대로
      재사용했고(동일 정책·동일 데이터), COVID 2020·2018년말·2015-16 세 에피소드는 이번 라운드가
      새로 실행했다 — 각 에피소드마다 17자산 챔피언 코어(2008은 확립된 관례대로 SPY/TLT/GLD 3자산
      근사)와 point-in-time 40종목 풀에서 뽑은 돈치안+트레일링스탑 새틀라이트를 반기 리밸런싱으로
      쌓고, 정적보유(Case A)와 실시간청산+SPY스위치(Case B)를 각각 계산했다.</p>

    <h3>5개 위기 에피소드 종합 비교표 (위기 서브윈도우 · CAGR / MDD / 샤프)</h3>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>에피소드</th><th>코어단독</th><th>Case A(정적보유)</th><th>Case B(실시간청산+스위치)</th>
          <th>B가 샤프에서 A를 이김?</th><th>B가 MDD에서 A를 이김?</th></tr></thead>
        <tbody>
          {''.join(episode_table_row(l) for l in EP_ORDER)}
        </tbody>
      </table>
    </div>
    <p class="kpi-sub" style="margin-top:8px;">셀 안 세 숫자는 CAGR / MDD / 샤프 순.</p>

    <div class="kpi-row">
      <div class="kpi-tile"><div class="kpi-label">5개 중 Case B가 샤프에서 승리</div><div class="kpi-value">{n_b_beats_a_sharpe} / {n_episodes}</div><div class="kpi-sub">2008 GFC 단 1개만 승리</div></div>
      <div class="kpi-tile"><div class="kpi-label">5개 중 Case B가 MDD에서 승리</div><div class="kpi-value pos">{n_b_beats_a_mdd} / {n_episodes}</div><div class="kpi-sub">낙폭 축소는 예외 없이 전부 성공</div></div>
      <div class="kpi-tile"><div class="kpi-label">COVID 2020 Case B 샤프</div><div class="kpi-value neg">{fnum(covid['case_b_realtime_exit_plus_switch']['sharpe'],2)}</div><div class="kpi-sub">코어단독 {fnum(covid['core_alone']['sharpe'],2)}보다 크게 나쁨</div></div>
    </div>

    <div class="callout warn">
      <div class="callout-title">해석 — "위기방어"는 만능이 아니다: 낙폭은 항상 줄이지만, 위험조정수익은 8라운드형 위기에서만 개선</div>
      <p>표본을 5개로 늘려 나온 가장 중요한 발견은 <b>MDD와 샤프의 결과가 서로 다른 방향을 가리킨다</b>는
        것이다. Case B는 <b>5개 에피소드 전부</b>에서 코어단독·Case A보다 낙폭(MDD)을 줄이거나
        같게 만들었다(예외 없음) — 실시간청산과 SPY스위치가 하방을 깎아내는 기계적 효과는 확실하다.
        그러나 <b>샤프비율 기준으로 Case A를 실제로 이긴 건 2008 금융위기, 딱 1개뿐</b>이다. 2015-16
        조정·2018년말 셀오프·2022 약세장에서는 Case B가 코어단독보다도 나쁜 샤프를 기록했고
        (조정폭 자체가 크지 않은 국면에서 방어 메커니즘의 마찰비용이 이득보다 컸다는 뜻), 특히
        <b>COVID 급락에서는 Case B의 샤프({fnum(covid['case_b_realtime_exit_plus_switch']['sharpe'],2)})가
        코어단독({fnum(covid['core_alone']['sharpe'],2)})보다 훨씬 나쁘고 Case A({fnum(covid['case_a_static_satellite']['sharpe'],2)})보다도
        나쁘다</b> — 낙폭이 며칠 만에 20%대까지 꽂히는 초고속 크래시에서는 트레일링스탑(20일
        돈치안 기준)도, 일별 갱신되는 SPY 200일선 신호도 반응이 물리적으로 너무 늦어서, 이미
        무너진 시점에 청산을 확정지어 반등을 놓치는 "가장 나쁜 타이밍"에 걸렸기 때문으로 보인다.</p>
      <p><b>더 정밀한 특성 규명</b>: 2008 GFC(코어단독 샤프{fnum(gfc['core_alone']['sharpe'],2)}가 Case A에서
        {fnum(gfc['case_a_static_satellite']['sharpe'],2)}로 무너졌다가 Case B가 {fnum(gfc['case_b_realtime_exit_plus_switch']['sharpe'],2)}로
        거의 복구)처럼 <b>수개월에 걸쳐 서서히, 광범위하게 무너지는 위기</b>에서는 매일 갱신되는
        신호가 충분히 따라잡을 시간이 있어 Case B가 확실히 우월하다. 반면 (a) COVID처럼 <b>몇 주
        만에 수직 낙하하는 위기</b>에서는 신호 반응이 구조적으로 늦어 오히려 해가 되고, (b) 2015-16·
        2018년말처럼 <b>낙폭 자체가 얕고 짧은 통상적 조정</b>에서는 코어단독이 이미 준수해서
        방어장치를 얹을수록 마찰비용만 쌓인다. 즉 "위기방어"라는 라벨은 부정확하다 — 정확히는
        <b>"수개월 규모의 광범위·완만한 하락에 특화된 방어"</b>이며, 초고속 크래시나 얕은 조정에는
        적용하면 안 된다는 것이 5개 표본으로 처음 확인된 구체적 결론이다.</p>
    </div>
  </section>

  <section class="section" id="h19">
    <h2><span class="sec-no">02</span> H19 — 연속 스펙트럼 프론티어: 트레일링스탑 폭 스윕 {verdict_badge(h19_verdict)}</h2>
    <p class="lede">"선정"(돈치안20일 브레이크아웃 + 모멘텀 상위3, 반기 리밸런싱)은 H10 기준으로
      고정하고, "청산" 트리거로 쓰는 트레일링스탑 폭만 10/15/20/25/30%로 바꿔가며 전체기간
      (2019-2026, core+15%새틀라이트+SPY스위치)과 H18의 5개 위기 에피소드 위기서브윈도우 각각에서
      재계산했다(선정 로직이 그대로라 각 레벨마다 재선정 없이 rebal_log를 재사용 — 순수하게 "청산
      타이트니스"만의 효과를 분리).</p>

    <h3>프론티어 표 — 스탑 폭별 전체기간 vs 5개 위기 평균 성과</h3>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>스탑 폭</th><th>전체기간 CAGR</th><th>전체기간 샤프</th><th>전체기간 MDD</th>
          <th>위기 평균 CAGR</th><th>위기 평균 샤프</th><th>파레토(샤프-MDD)</th><th>파레토(강세CAGR-위기샤프)</th></tr></thead>
        <tbody>
          {''.join(frontier_row(p) for p in FP)}
        </tbody>
      </table>
    </div>
    <p class="kpi-sub" style="margin-top:8px;">"위기 평균"은 H18의 5개 에피소드(2008/2015-16/2018/2022/COVID)
      위기서브윈도우 CAGR·샤프의 단순평균(SPY스위치 결합 기준).</p>

    <div class="callout">
      <div class="callout-title">해석 — Case A/B는 진짜 연속선의 두 끝이 아니라, 10%가 실제로는 더 나은 극단이었다</div>
      <p>스윕 결과 예상과 다른 흥미로운 패턴이 나왔다: 스탑을 <b>느슨하게 할수록(30%)</b> 전체기간
        CAGR은 커지지만({fnum(FP[0]['full_period_cagr'],2)}% → {fnum(FP[-1]['full_period_cagr'],2)}%),
        <b>위기 평균 샤프는 단조롭게 나빠진다</b>({fnum(FP[0]['avg_crisis_sharpe_5ep'],3)} →
        {fnum(FP[-1]['avg_crisis_sharpe_5ep'],3)}) — 이건 예상대로다(느슨한 스탑은 덜 자주 청산돼
        상승분을 더 오래 태우지만 위기 때 손절이 늦어짐). 그런데 <b>전체기간 샤프는 가장 타이트한
        10%에서 오히려 최고치({fnum(FP[0]['full_period_sharpe'],3)})</b>를 찍고 15%에서 살짝
        떨어졌다가 다시 완만히 회복한다 — 즉 <b>10% 스탑은 강세장 위주 전체기간 샤프에서도, 위기
        평균 방어력에서도 동시에 가장 우수한 지점</b>이라, "타이트한 스탑 = 무조건 수익 희생"이라는
        직관적 가정이 이 데이터에서는 깨진다(파레토 표의 10%行이 두 평면 모두에서 "파레토"로 표시된
        이유). 반면 15%(8라운드의 Case B가 실제로 썼던 값)는 두 평면 모두에서 지배당하는 유일한
        지점 — 8라운드가 고정값으로 골랐던 15%가, 이번 스윕에서 보면 사실 파레토 효율선 위에 있지
        않은 준최적 선택이었다는 것도 이번 라운드가 새로 드러낸 사실이다. 20~30%는 강세장CAGR을
        더 밀어붙이려는 투자자에게는 파레토 효율적이지만(샤프-MDD 평면에서는 10%에 지배됨), 위기
        평균 샤프가 계속 나빠지는 대가를 진다.</p>
    </div>
  </section>

  <section class="section" id="synthesis">
    <h2><span class="sec-no">03</span> 종합 — 이분법을 넘어선 투자자 프로필별 구체적 권고</h2>
    <p class="lede">8라운드의 "Case A vs Case B" 이분법은 여전히 유효한 출발점이지만, 이번 라운드가
      보강한 두 가지 사실 — (1) Case B의 우위는 2008형 광범위·완만한 위기에서만 확실하고 초고속
      크래시(COVID)·얕은 조정(2015-16, 2018년말)에서는 오히려 해가 될 수 있다, (2) 스탑 폭은
      15% 하나로 고정할 이유가 없고 10%가 사실상 15%를 파레토 지배한다 — 는 실제로 다이얼을 돌릴
      수 있는 구체적 가이드로 이어진다.</p>

    <div class="hyp-card">
      <div class="hyp-id">프로필 1 — 장기 보유(5년+), 변동성을 감내할 수 있고 강세장 상단 포착이 우선</div>
      <p style="margin:8px 0 0;"><b>느슨한 스탑(25~30%) 또는 8라운드의 정적보유(Case A)</b>를 유지한다.
        위기 평균 샤프는 가장 나쁘지만({fnum(FP[-1]['avg_crisis_sharpe_5ep'],3)}), 전체기간 CAGR이
        가장 높고({fnum(FP[-1]['full_period_cagr'],2)}%) 잦은 청산으로 인한 반등 기회비용이 최소화된다.
        2015-16·2018년말 같은 얕은 조정에서는 어차피 Case B도 별 도움이 안 됐으므로, 방어장치의
        마찰비용을 굳이 감수할 이유가 없다.</p>
    </div>
    <div class="hyp-card">
      <div class="hyp-id">프로필 2 — 중기 보유(1~3년), 큰 낙폭에 민감하지만 극단적 방어까지는 필요없음</div>
      <p style="margin:8px 0 0;"><b>타이트한 스탑(10%) + SPY 200일선 스위치</b>를 권고한다. 이 라운드의
        핵심 발견대로 10% 스탑은 전체기간 샤프({fnum(FP[0]['full_period_sharpe'],3)})와 위기 평균
        샤프({fnum(FP[0]['avg_crisis_sharpe_5ep'],3)}) 양쪽에서 동시에 파레토 효율적이라, "강세장
        수익을 크게 희생하지 않으면서 위기 방어를 더 얻는" 실질적으로 공짜에 가까운 개선이다.
        8라운드가 고정했던 15%보다 명백히 나은 선택.</p>
    </div>
    <div class="hyp-card">
      <div class="hyp-id">프로필 3 — 단기/낙폭에 극도로 민감(은퇴 임박, 목표시점 확정 등), 광범위 위기 방어가 최우선</div>
      <p style="margin:8px 0 0;"><b>10% 스탑 + 실시간청산 + SPY스위치(Case B의 강화판)</b>를 유지하되,
        <b>"이 조합이 2008형 완만한 위기에서만 확실히 통한다"는 점을 명시적으로 인지</b>해야 한다.
        COVID형 초고속 크래시가 오면 이 조합도 코어단독보다 나쁠 수 있다는 걸 5개 표본이 실측으로
        보여줬으므로, 극단적 방어가 목적이라면 트레일링스탑/SPY스위치 단독이 아니라 별도의
        빠른 반응 메커니즘(예: 일중 손절, VIX 급등 트리거 등, 이번 라운드 범위 밖)을 추가로
        검토할 필요가 있다는 것을 다음 과제로 남긴다.</p>
    </div>
    <div class="hyp-card">
      <div class="hyp-id">공통 결론</div>
      <p style="margin:8px 0 0;">단일 최선 구성은 여전히 없지만, 이제는 "Case A 아니면 Case B"라는
        이분법이 아니라 <b>{fnum(min(STOP_LEVELS)*100,0)}%~{fnum(max(STOP_LEVELS)*100,0)}% 사이의
        실제 다이얼</b>로 골라 쓸 수 있다. 특히 10% 스탑이 8라운드 기본값(15%)을 두 축 모두에서
        지배한다는 것과, "위기방어"가 만능이 아니라 위기의 <b>속도와 폭</b>에 따라 갈린다는 것이
        이번 라운드가 8라운드 결론에 더한 두 가지 정밀화다.</p>
    </div>
  </section>

  <section class="section" id="limitations">
    <h2><span class="sec-no">04</span> 한계</h2>
    <ul>
      <li><b>여전히 표본 5개</b> — 2를 5로 늘렸지만 역사상 주요 위기는 훨씬 많다(1987 블랙먼데이,
        1997-98 아시아/LTCM, 2011 유럽 재정위기, 2013 테이퍼탠트럼 등). 데이터 가용성(캐시된
        ETF·point-in-time 유니버스 이력) 제약으로 이번 라운드가 다룬 5개가 현실적 상한이었다.</li>
      <li><b>2018년말·2015-16 코어는 17자산 챔피언이지만 일부 구성요소가 최근 상장</b> — XLC(2018-06),
        XLRE(2015-10)는 이 두 에피소드의 풀기간 시작 시점에 모멘텀 계산에 필요한 이력이 부족해
        자동으로 후보에서 제외됐다(NaN 모멘텀은 자연히 걸러짐) — "그 시점에 실제 존재했던 자산만"
        쓰인다는 점에서 point-in-time 원칙과 일치하지만, 완전한 17자산 유니버스로 검증된 결과는
        아니다.</li>
      <li><b>H19 스윕은 선정 로직을 고정</b> — 스탑 폭을 바꾸면 원래는 "선정 시점 자격 기준"도
        같이 바뀌어야 논리적으로 일관되지만(더 타이트한 스탑을 쓰면 애초에 그 폭 기준으로 활성
        신호였던 종목만 후보가 되어야 함), 계산 비용 절감을 위해 H10의 15% 기준 rebal_log를 그대로
        재사용하고 "청산" 트리거만 바꿨다 — "선정"까지 완전히 일관되게 재구축하면 프론티어 형태가
        달라질 수 있다.</li>
      <li><b>H18 위기서브윈도우가 짧을수록 샤프·CAGR의 통계적 잡음이 크다</b> — 특히 COVID(약 2개월),
        2018년말(약 4.5개월) 구간은 연율화 지표가 소수 거래일에 민감하게 흔들릴 수 있다.</li>
      <li><b>2008년 코어는 3자산(SPY/TLT/GLD) 근사, 새틀라이트 풀 생존편향</b> — 작업33/34/35/36과
        동일한 제약이 그대로 적용된다.</li>
      <li><b>다중비교 위험</b> — 이 저장소가 지금까지 수십 개의 파라미터/구조 변형을 반복 검증해온
        근본적 한계(작업21이 이미 명시)는 이번 연구에도 그대로 적용된다. 10% 스탑이 5개 스탑
        레벨·5개 위기표본 조합 중 사후적으로 가장 좋아 보인다는 것이, 사전에 무작위로 골랐어도
        그만큼 좋았을 것이라는 보장은 아니다.</li>
    </ul>
  </section>

</div>

<footer>
  <p>analysis/2026-08-23_crisis_sample_expansion_and_risk_frontier/ (데이터: report_data.json,
    빌드: build_report.py) · h18_expanded_crisis_samples.py는 2008/2022를
    analysis/2026-08-22_satellite_realtime_stop_and_reentry_research/h16_results.json에서
    재계산 없이 재사용하고, COVID 2020/2018년말/2015-16 세 에피소드는
    champion_strategy.run_champion(17자산 챔피언)·h11_crisis_robustness_test.build_satellite_returns_period
    (point-in-time 새틀라이트 선정)·h16_realtime_trailing_stop_exit.build_realtime_exit_weights(실시간청산)·
    h12_regime_switch(SPY 200일선 스위치) 로직을 그대로 재사용해 새로 실행했다. h19_risk_return_frontier.py는
    H10/H18의 rebal_log를 재사용하고 트레일링스탑 폭만 파라미터화해 재계산 비용을 최소화했다. 모든
    수치는 core.market_data/core.point_in_time_market_cap의 로컬 캐시를 통한 실제 Yahoo Finance
    데이터로 계산한 결과다(추정치 아님). 이 워크트리는 main과 분기된 시점 이후 인프라 변경이
    반영되지 않을 수 있어, 모든 스크립트가 main 체크아웃(/workspaces/Quant)의 core/를 직접
    참조해 실행했다 — 이 워크트리의 core/는 건드리지 않았다.</p>
</footer>
"""

out_file = f"{OUT_DIR}/final_report.html"
with open(out_file, "w", encoding="utf-8") as f:
    f.write(HTML)
print(f"SAVED {out_file}")
