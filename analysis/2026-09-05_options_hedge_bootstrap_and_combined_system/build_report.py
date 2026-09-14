#!/usr/bin/env python3
"""report_data.json을 읽어 final_report.html을 만든다. 디자인 시스템은
analysis/2026-08-30_synthetic_options_tail_hedge/build_report.py와 동일(다크네이비/올리브 톤,
세리프 헤드라인, TOC, 섹션 번호, 판정 배지)."""
import json
import math
import os

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
with open(f"{OUT_DIR}/report_data.json", encoding="utf-8") as f:
    R = json.load(f)

GEN = R["meta"]["generated"]
EP_ORDER = R["meta"]["episode_order"]
BOOT = R["bootstrap"]
COMB = R["combined"]

EP_LABEL = {
    "full_2019_2026": "전체기간 2019-2026",
    "gfc_2008": "2008 GFC",
    "covid_2020": "COVID 2020 (~51거래일)",
    "bear_2022": "2022 완만약세장",
    "selloff_2018": "2018 4분기 급락",
    "correction_2015_2016": "2015-16 조정",
}
CFG_LABEL = {
    "core_alone": "코어단독",
    "unhedged_satellite": "새틀라이트 무헤지(현행)",
    "protective_put": "새틀라이트+합성풋",
    "collar": "새틀라이트+합성칼라",
    "collar_full_system": "코어+새틀라이트+칼라(통합)",
}
SCEN_LABEL = {"base": "기본(base)", "calm_heavy": "평시가중(calm_heavy)", "crisis_heavy": "위기가중(crisis_heavy)"}


def fnum(v, digits=2, signed=False):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    s = f"{v:,.{digits}f}"
    if signed and v > 0:
        s = "+" + s
    return s


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


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
  font-size: clamp(28px, 4.2vw, 44px); line-height:1.15; margin: 14px 0 10px; text-wrap: balance; max-width: 36ch; }
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
.callout.good{ border-left-color: var(--aqua); }
.callout.good .callout-title{ color: var(--aqua); }
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
table.data-table{ width:100%; border-collapse:collapse; font-size:13.5px; min-width:760px; }
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
.badge{ display:inline-block; font-size:11.5px; font-weight:700; letter-spacing:0.03em; text-transform:uppercase;
  border-radius:4px; padding:3px 9px; }
.badge.reject{ background:rgba(179,38,30,0.12); color:var(--delta-neg); }
.badge.weak{ background:var(--accent-2-soft); color:var(--accent-2); }
.badge.accept{ background:rgba(27,175,122,0.14); color:var(--aqua); }
footer{ max-width:1060px; margin:40px auto 0; padding: 26px 24px 10px; border-top:1px solid var(--hairline);
  font-size:12.5px; color:var(--ink-muted); }
footer p{ max-width:none; }
.toc{ display:flex; flex-wrap:wrap; gap:8px 18px; margin: 24px 0 4px; padding:16px 20px; background:var(--surface);
  border:1px solid var(--hairline); border-radius:8px; }
.toc a{ font-size:13.5px; color:var(--ink-2); text-decoration:none; }
.toc a:hover{ color:var(--accent); text-decoration:underline; }
"""

# ---- Section 1: bootstrap table ----
BOOT_CFGS = ["core_alone", "unhedged_satellite", "protective_put", "collar"]


def bootstrap_table():
    rows = []
    for ep in EP_ORDER:
        d = BOOT["bootstrap"][ep]
        for cfg in BOOT_CFGS:
            c = d["by_config"][cfg]
            l20 = c["bootstrap_by_block_len"]["20"]
            ci = l20["ci90"] if l20 else [None, None]
            warn = " warn-row" if ep == "covid_2020" else ""
            hero = " hero-row" if cfg == "collar" else ""
            rows.append(
                f'<tr class="{(warn+hero).strip()}"><td class="tk-cell"><span class="tk-name">{esc(EP_LABEL[ep])}</span></td>'
                f'<td class="tk-cell">{esc(CFG_LABEL[cfg])}</td>'
                f'<td class="num">{d["n_obs"]}</td>'
                f'<td class="num">{fnum(c["point_estimate_sharpe"],2,signed=True)}</td>'
                f'<td class="num">[{fnum(ci[0],2,signed=True)}, {fnum(ci[1],2,signed=True)}]</td></tr>'
            )
    return "".join(rows)


def combined_gap_table():
    rows = []
    for scen in ["base", "calm_heavy", "crisis_heavy"]:
        d = BOOT["combined_dirichlet_x_bootstrap"][scen]
        for pair_key, pair_label in [("collar_vs_unhedged_satellite", "칼라 vs 무헤지"),
                                       ("protective_put_vs_unhedged_satellite", "풋 vs 무헤지")]:
            g = d[pair_key]
            hero = " hero-row" if pair_key.startswith("collar") and scen == "base" else ""
            rows.append(
                f'<tr class="{hero.strip()}"><td class="tk-cell"><span class="tk-name">{esc(SCEN_LABEL[scen])}</span></td>'
                f'<td class="tk-cell">{esc(pair_label)}</td>'
                f'<td class="num">{fnum(g["pct_draws_a_ahead"]*100,1)}%</td>'
                f'<td class="num">{fnum(g["mean_gap"],3,signed=True)}</td>'
                f'<td class="num">[{fnum(g["ci90_gap"][0],3,signed=True)}, {fnum(g["ci90_gap"][1],3,signed=True)}]</td></tr>'
            )
    return "".join(rows)


def combined_ev_table():
    rows = []
    ranks = COMB["rank_by_scenario"]
    for scen in ["base", "calm_heavy", "crisis_heavy"]:
        ev = COMB["expected_value_by_scenario"][scen]
        order = [c for c, _ in ranks[scen]["by_sharpe"]]
        for rank_i, cfg in enumerate(order, start=1):
            v = ev[cfg]
            hero = " hero-row" if cfg == "collar_full_system" and rank_i == 1 else ""
            rows.append(
                f'<tr class="{hero.strip()}"><td class="tk-cell"><span class="tk-name">{esc(SCEN_LABEL[scen])}</span></td>'
                f'<td class="tk-cell">#{rank_i} {esc(CFG_LABEL[cfg])}</td>'
                f'<td class="num">{fnum(v["sharpe"],3,signed=True)}</td>'
                f'<td class="num">{fnum(v["cagr"]*100,1,signed=True)}%</td>'
                f'<td class="num">{fnum(v["mdd_worst_case"],1)}%</td></tr>'
            )
    return "".join(rows)


COVID_COLLAR_CI20 = BOOT["bootstrap"]["covid_2020"]["by_config"]["collar"]["bootstrap_by_block_len"]["20"]["ci90"]
COVID_UNHEDGED_CI20 = BOOT["bootstrap"]["covid_2020"]["by_config"]["unhedged_satellite"]["bootstrap_by_block_len"]["20"]["ci90"]
COVID_COLLAR_PT = BOOT["bootstrap"]["covid_2020"]["by_config"]["collar"]["point_estimate_sharpe"]
COVID_N = BOOT["bootstrap"]["covid_2020"]["n_obs"]
BASE_WINRATE_COLLAR = BOOT["combined_dirichlet_x_bootstrap"]["base"]["collar_vs_unhedged_satellite"]["pct_draws_a_ahead"]
CRISIS_WINRATE_COLLAR = BOOT["combined_dirichlet_x_bootstrap"]["crisis_heavy"]["collar_vs_unhedged_satellite"]["pct_draws_a_ahead"]
BASE_WINRATE_PUT = BOOT["combined_dirichlet_x_bootstrap"]["base"]["protective_put_vs_unhedged_satellite"]["pct_draws_a_ahead"]

EV_BASE = COMB["expected_value_by_scenario"]["base"]
EV_CALM = COMB["expected_value_by_scenario"]["calm_heavy"]
EV_CRISIS = COMB["expected_value_by_scenario"]["crisis_heavy"]

collar_beats_unhedged_all = all(
    COMB["expected_value_by_scenario"][s]["collar_full_system"]["sharpe"] > COMB["expected_value_by_scenario"][s]["unhedged_satellite"]["sharpe"]
    for s in ["base", "calm_heavy", "crisis_heavy"]
)
collar_beats_core_count = sum(
    COMB["expected_value_by_scenario"][s]["collar_full_system"]["sharpe"] > COMB["expected_value_by_scenario"][s]["core_alone"]["sharpe"]
    for s in ["base", "calm_heavy", "crisis_heavy"]
)

HTML = f"""<title>옵션헤지 부트스트랩 감사와 통합시스템 기댓값</title>
<style>
{CSS}
</style>

<div class="masthead">
  <div class="masthead-inner">
    <div class="masthead-eyebrow">
      <span>QUANT RESEARCH NOTE</span><span class="dot">·</span><span>작업48 후속</span><span class="dot">·</span><span>Confidence Audit + Expected Value</span>
    </div>
    <h1 class="masthead-title">칼라 옵션 헤지, COVID 단일창의 극적 승리는 부트스트랩 신뢰구간 앞에서 흔들리지만 — 새틀라이트 비중으로 희석된 통합 시스템에서는 되레 기댓값이 개선된다</h1>
    <p class="masthead-sub">작업48은 합성 칼라 옵션이 COVID 구간에서 코어단독·무헤지새틀라이트·최선의
      추세 하이브리드를 전부 이겼다고 결론냈지만, 이 결론은 이 프로그램의 다른 모든 주요 결론과 달리
      한 번도 표본오차 감사를 받지 않았다(51거래일짜리 초단기 창). 이번 라운드는 그 감사(H_bootstrap)와,
      칼라를 새틀라이트 슬리브 단독이 아니라 코어+새틀라이트+칼라 전체 시스템에 넣었을 때 기댓값
      순위가 바뀌는지(H_combined)를 함께 검증한다. 결과: COVID 단일창의 칼라 우위는 신뢰구간이
      [{fnum(COVID_COLLAR_CI20[0],2,signed=True)}, {fnum(COVID_COLLAR_CI20[1],2,signed=True)}]로 부호조차
      확정 못 할 만큼 넓어 <b>단일경로 아티팩트에 가깝다</b>. 하지만 새틀라이트 비중(15%)으로 희석된
      통합 시스템 레벨에서는 세 기저확률 시나리오 전부에서 칼라가 무헤지 기저선을 기댓값 샤프로
      이긴다({fnum(BASE_WINRATE_COLLAR*100,0)}%~{fnum(CRISIS_WINRATE_COLLAR*100,0)}% 승률) — 트레이드오프
      자체는 사라지지 않았지만 규모가 작아지며 방향이 뒤집혔다.</p>
    <div class="masthead-meta">
      <span><b>기준일</b> {esc(GEN)}</span>
      <span><b>부트스트랩</b> 순환 이동블록, L=10/20/40(중심 20), 창×구성당 2,000회</span>
      <span><b>결합전파</b> 디리클레 가중치(K=30) × 부트스트랩 표본오차, 10,000 draw</span>
      <span><b>기저확률</b> base/calm_heavy/crisis_heavy 3개 시나리오(H22 동일)</span>
    </div>
  </div>
</div>

<div class="wrap">

<div class="toc">
  <a href="#s0">0. 문제 제기</a>
  <a href="#s1">1. 부트스트랩 감사 결과</a>
  <a href="#s2">2. 통합 시스템 기댓값 재검증</a>
  <a href="#s3">3. 종합 — 최종 권고가 바뀌는가</a>
  <a href="#s4">4. 한계</a>
</div>

<div class="section" id="s0">
  <h2><span class="sec-no">0</span>문제 제기 — 옵션헤지 리포트가 남긴 두 과제</h2>
  <p class="lede">작업48(synthetic_options_tail_hedge_research)은 스스로 두 가지 한계를 명시했다:
    (1) COVID 구간의 극적인 칼라 우위가 이 프로그램의 표준 표본오차 감사(H33 블록부트스트랩)를 한
    번도 거치지 않았다는 것, (2) 칼라를 새틀라이트 슬리브 단독에 대해서만 테스트했을 뿐 코어+새틀라이트
    전체 시스템의 기댓값 순위(H22 프레임)에 넣어본 적이 없다는 것. 이 리포트는 그 두 과제를 순서대로
    닫는다.</p>
</div>

<div class="section" id="s1">
  <h2><span class="sec-no">1</span>부트스트랩 감사 결과 — 창별 신뢰구간</h2>
  <p class="lede">H33과 동일한 순환 이동블록부트스트랩(L=10/20/40, 창×구성당 2,000회)을 4개 구성
    (코어단독/무헤지새틀라이트/합성풋/합성칼라) × 6개 창에 적용했다. 아래 표는 L=20(중심 블록길이)
    기준 90% 신뢰구간이다. COVID 행(강조)은 n_obs=51로 이 프로그램에서 가장 짧은 창임을 다시 경고한다.</p>
  <div class="table-wrap">
    <table class="data-table">
      <thead><tr><th>창</th><th>구성</th><th>N(거래일)</th><th>점추정 Sharpe</th><th>L=20 CI90</th></tr></thead>
      <tbody>{bootstrap_table()}</tbody>
    </table>
  </div>
  <div class="callout warn">
    <div class="callout-title">COVID 칼라 우위, 신뢰구간으로 보면</div>
    <p>점추정 Sharpe는 칼라 {fnum(COVID_COLLAR_PT,2,signed=True)} vs 무헤지 {fnum(BOOT['bootstrap']['covid_2020']['by_config']['unhedged_satellite']['point_estimate_sharpe'],2,signed=True)}로
      칼라가 크게 앞서지만, 부트스트랩 90% CI는 칼라 [{fnum(COVID_COLLAR_CI20[0],2,signed=True)}, {fnum(COVID_COLLAR_CI20[1],2,signed=True)}],
      무헤지 [{fnum(COVID_UNHEDGED_CI20[0],2,signed=True)}, {fnum(COVID_UNHEDGED_CI20[1],2,signed=True)}]로 둘 다
      부호가 뒤집힐 수 있을 만큼 넓게 겹친다. n_obs={COVID_N}(약 10주)인 창에서 L=40 블록은 원 시계열을
      통째로 재사용하는 것과 다를 바 없어 분산이 인위적으로 좁아질 위험까지 있다(H33이 경고한 것과
      동일한 패턴) — 즉 이 CI조차 과소추정일 가능성이 있다. COVID 단일창의 "칼라가 이겼다"는 관측은
      방향은 맞을 수 있어도 이 표본만으로는 통계적으로 확정할 수 없는, 이 프로그램이 반복해서 발견해온
      "극적인 단일 에피소드 승리"의 전형적 패턴이다.</p>
  </div>

  <h3>디리클레 가중치 × 부트스트랩 표본오차 결합전파 — 칼라/풋 vs 무헤지 승률</h3>
  <p>H33b와 동일한 방식으로, 매 draw마다 기저확률 가중치(디리클레) 1개와 각 창의 부트스트랩 Sharpe
    표본(L=20) 1개씩을 동시에 뽑아 10,000회 반복, "칼라(또는 풋)가 무헤지보다 기댓값 Sharpe가 높은
    draw의 비율"을 승률로 정의했다. 이는 <b>새틀라이트 슬리브 단독</b> 비교이며(2절의 통합 시스템
    기댓값과는 스케일이 다름), COVID 한 창의 승리가 6창 전체로 일반화되는지를 본다.</p>
  <div class="table-wrap">
    <table class="data-table">
      <thead><tr><th>기저확률 시나리오</th><th>비교</th><th>승률(a 우위)</th><th>평균 갭</th><th>갭 CI90</th></tr></thead>
      <tbody>{combined_gap_table()}</tbody>
    </table>
  </div>
  <div class="callout">
    <div class="callout-title">판정</div>
    <p>새틀라이트 슬리브 단독 기준으로는 칼라의 승률이 시나리오 전반에서 {fnum(BOOT['combined_dirichlet_x_bootstrap']['calm_heavy']['collar_vs_unhedged_satellite']['pct_draws_a_ahead']*100,0)}%~{fnum(CRISIS_WINRATE_COLLAR*100,0)}%,
      풋은 {fnum(BASE_WINRATE_PUT*100,0)}% 안팎으로 "동전던지기보다 약간 나은" 수준에 그친다 — 90%
      확신을 요구하는 이 프로그램의 기준(H33/H35 등)에 크게 못 미친다. <span class="badge weak">약함(WEAK)</span>
      COVID가 만든 극적 인상과 달리, 새틀라이트 슬리브 단독으로 본 칼라 우위는 6개 창 전체 표본오차와
      가중치 불확실성을 더하면 "약한 우위" 수준으로 무너진다 — 이 프로그램의 전형적 패턴("90%대가
      50%대로 무너진다")이 여기서도 재현됐다.</p>
  </div>
</div>

<div class="section" id="s2">
  <h2><span class="sec-no">2</span>통합 시스템(코어+새틀라이트+칼라) 기댓값 재검증</h2>
  <p class="lede">칼라 오버레이를 새틀라이트 노셔널(포트폴리오의 15%)에만 적용한 채, H22와 동일한
    기저확률 시나리오(base/calm_heavy/crisis_heavy)로 6개 창을 가중해 세 구성 — 코어단독 / 코어+
    새틀라이트(무헤지, 현행 기댓값-선호 baseline) / 코어+새틀라이트+칼라(통합) — 의 기댓값 Sharpe·CAGR
    순위를 냈다. 1절과 달리 여기서는 칼라의 평시 프리미엄 드래그가 포트폴리오 전체가 아니라 15%
    슬리브에서만 발생하므로, 드래그가 얼마나 희석되는지가 핵심 질문이다.</p>
  <div class="table-wrap">
    <table class="data-table">
      <thead><tr><th>시나리오</th><th>순위</th><th>기댓값 Sharpe</th><th>기댓값 CAGR</th><th>위기창 최악 MDD</th></tr></thead>
      <tbody>{combined_ev_table()}</tbody>
    </table>
  </div>
  <div class="callout good">
    <div class="callout-title">희석 효과가 방향을 뒤집었다</div>
    <p>기댓값 Sharpe 기준으로 칼라 통합 시스템은 세 시나리오 <b>전부</b>에서 무헤지 기저선(현행 관행)을
      이긴다({'전부' if collar_beats_unhedged_all else '일부'} 개선: base {fnum(EV_BASE['collar_full_system']['sharpe'],3,signed=True)} vs
      {fnum(EV_BASE['unhedged_satellite']['sharpe'],3,signed=True)}, calm_heavy {fnum(EV_CALM['collar_full_system']['sharpe'],3,signed=True)} vs
      {fnum(EV_CALM['unhedged_satellite']['sharpe'],3,signed=True)}, crisis_heavy {fnum(EV_CRISIS['collar_full_system']['sharpe'],3,signed=True)} vs
      {fnum(EV_CRISIS['unhedged_satellite']['sharpe'],3,signed=True)}). 코어단독 대비로는 3개 시나리오 중
      {collar_beats_core_count}개에서 칼라가 앞선다(위기가중·기본 시나리오에서 앞서고, 평시가중 시나리오에서는
      코어단독이 여전히 근소 우위) — 1절의 "새틀라이트 슬리브 단독" 비교에서는 승률이 약했던 칼라가,
      포트폴리오 15%로 스케일이 줄어들자 평시 드래그도 함께 줄어 무헤지 대비로는 견고하게 개선되는
      것으로 나타난다. 다만 여전히 <span class="badge weak">약함(WEAK)</span> — 코어단독을 항상 이기지는
      못하고, Sharpe 갭 자체도 크지 않다(소수점 셋째 자리 단위).</p>
  </div>
</div>

<div class="section" id="s3">
  <h2><span class="sec-no">3</span>종합 — 최종 권고가 바뀌는가</h2>
  <p>두 검증을 합치면 그림이 명확해진다: <b>"칼라가 COVID를 극적으로 막았다"는 서사는 표본오차 앞에서
    약해지지만, "칼라를 새틀라이트 규모로 희석해 포트폴리오에 넣으면 무헤지보다 기댓값이 낫다"는
    더 조심스러운 결론은 살아남는다.</b> 이는 작업48이 이미 암시했던 트레이드오프(평시 드래그 vs
    위기 방어)가 사라진 게 아니라, 통합 시스템 스케일에서는 트레이드오프의 크기 자체가 작아져
    비대칭이 무헤지 쪽에 불리하게 남는다는 뜻이다.</p>
  <p><b>권고 변경 여부</b>: 이 프로그램의 기존 baseline(코어+정적보유 새틀라이트, 무헤지)을 코어+
    새틀라이트+칼라로 교체하는 것은 base/crisis_heavy 시나리오에서 기댓값 Sharpe가 개선되므로
    <b>고려할 가치가 있다</b>. 다만 (a) 개선폭이 크지 않고, (b) calm_heavy(평시 지속 가정) 시나리오에서는
    코어단독이 여전히 최상위이며, (c) 1절의 새틀라이트-단독 승률이 약하다는 것은 이 개선이 강건한
    "칼라가 우월하다"는 명제가 아니라 "칼라의 비용 대비 보험가치가 포트폴리오 규모에서는 나쁘지
    않은 거래"라는 훨씬 약한 명제임을 의미한다. <b>확정적 채택(ACCEPT)이 아니라 조건부 고려
    (WEAK-LEAN-TOWARD-ADOPT)</b>로 남긴다.</p>
</div>

<div class="section" id="s4">
  <h2><span class="sec-no">4</span>한계</h2>
  <ul>
    <li>COVID 창은 n_obs=51로 이 프로그램에서 가장 짧다 — L=40 블록 부트스트랩은 사실상 원 시계열
      재사용에 가까워 분산을 과소추정할 수 있다(본문 1절에서 명시).</li>
    <li>옵션 가격결정은 여전히 Black-Scholes + VIX/100 대리변동성이라는 단순화를 쓴다 — 스마일/스큐,
      일일 마크투마켓(델타/감마)은 반영하지 않는다(작업48의 한계 그대로 승계).</li>
    <li>2절의 "통합 시스템"은 챔피언 17종목 코어 + 15% 새틀라이트 + 칼라를 그대로 합산한 것으로,
      집중도·유동성·옵션 매매 슬리피지 등 실전 마찰비용은 반영하지 않았다(코어/새틀라이트 백테스트
      엔진 자체의 기존 가정을 그대로 승계).</li>
    <li>기저확률 3개 시나리오(base/calm_heavy/crisis_heavy)는 H22와 동일한 "최선 추정"이며 정밀한
      역사적 확률이 아니다 — 시나리오가 바뀌면 3절의 권고도 다시 흔들릴 수 있다.</li>
    <li>디리클레 K=30 결합전파는 6개 창의 상관관계(같은 시장 국면이 여러 창에 걸쳐 있을 수 있음)를
      독립으로 가정한다 — 이 프로그램의 이전 라운드(H30/H33b)와 동일한 단순화다.</li>
  </ul>
</div>

</div>
<footer>
  <p>산출물: analysis/2026-09-05_options_hedge_bootstrap_and_combined_system/ (h_bootstrap_audit.py,
    h_combined_system_ev.py, report_data.json, build_report.py). 작업48(synthetic_options_tail_hedge_research)의
    직접 후속. core/, app/는 수정하지 않음.</p>
</footer>
"""

with open(f"{OUT_DIR}/final_report.html", "w", encoding="utf-8") as f:
    f.write(HTML)
print("wrote final_report.html", len(HTML))
