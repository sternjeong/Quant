#!/usr/bin/env python3
"""report_data.json을 읽어 final_report.html을 만든다. 디자인 시스템은
analysis/2026-09-05_options_hedge_bootstrap_and_combined_system/build_report.py와 동일(다크네이비/올리브
톤, 세리프 헤드라인, TOC, 섹션 번호, 판정 배지)."""
import json
import math
import os

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
with open(f"{OUT_DIR}/report_data.json", encoding="utf-8") as f:
    R = json.load(f)

GEN = R["meta"]["generated"]
EP_ORDER = R["meta"]["episode_order"]
BOOT = R["bootstrap"]
COMB = R["combined_dirichlet_x_bootstrap"]
EV = R["expected_value"]
CASE21 = R["case_study_2021"]
EPISODES = R["episodes"]
PERM_POOL = R["permutation_test_pool_corr"]
PERM_HOLD = R["permutation_test_holdings_corr"]
Z_CENTRAL = R["meta"]["z_central"]
Z_THRESHOLDS = R["meta"]["z_thresholds"]

EP_LABEL = {
    "full_2019_2026": "전체기간 2019-2026",
    "gfc_2008": "2008 GFC",
    "covid_2020": "COVID 2020",
    "bear_2022": "2022 완만약세장",
    "selloff_2018": "2018 4분기 급락",
    "correction_2015_2016": "2015-16 조정",
}
CFG_LABEL = {
    "core_alone": "코어단독",
    "core_plus_static_satellite": "코어+정적 새틀라이트(현행)",
    "switch_spy": "SPY 200일선 스위치",
    "switch_pool_breadth": "풀 breadth 스위치",
    "switch_sat_drawdown": "새틀라이트 낙폭 스위치",
    "switch_pool_corr": "풀 상관관계 스위치",
    "switch_holdings_corr": "보유종목 상관관계 스위치",
    "switch_spy_or_pool_corr": "SPY OR 풀상관 스위치",
    "switch_spy_or_holdings_corr": "SPY OR 보유상관 스위치",
}
BOOT_CFGS = ["core_alone", "core_plus_static_satellite", "switch_spy", "switch_holdings_corr", "switch_spy_or_holdings_corr"]
EV_CFGS = ["core_alone", "core_plus_static_satellite", "switch_spy", "switch_holdings_corr", "switch_spy_or_holdings_corr"]
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


def episode_table(wname):
    rows = []
    for ep in EP_ORDER:
        d = EPISODES[ep]["windows"].get(wname)
        if d is None:
            continue
        for cfg in EV_CFGS:
            m = d.get(cfg)
            if m is None:
                continue
            hero = " hero-row" if cfg == "switch_holdings_corr" else ""
            warn = " warn-row" if ep == "covid_2020" else ""
            rows.append(
                f'<tr class="{(hero+warn).strip()}"><td class="tk-cell"><span class="tk-name">{esc(EP_LABEL[ep])}</span></td>'
                f'<td class="tk-cell">{esc(CFG_LABEL[cfg])}</td>'
                f'<td class="num">{fnum(m.get("sharpe"),3,signed=True)}</td>'
                f'<td class="num">{fnum(m.get("cagr"),1,signed=True)}%</td>'
                f'<td class="num">{fnum(m.get("mdd"),1)}%</td></tr>'
            )
    return "".join(rows)


def zsweep_table():
    rows = []
    for ep in EP_ORDER:
        sweep = EPISODES[ep].get("z_threshold_sweep") or {}
        if not sweep:
            continue
        for z in Z_THRESHOLDS:
            d = sweep.get(str(z))
            if d is None:
                continue
            pc = d.get("pool_corr_crisis") or {}
            hc = d.get("holdings_corr_crisis") or {}
            hero = " hero-row" if z == Z_CENTRAL else ""
            rows.append(
                f'<tr class="{hero.strip()}"><td class="tk-cell"><span class="tk-name">{esc(EP_LABEL[ep])}</span></td>'
                f'<td class="num">z≥{z}</td>'
                f'<td class="num">{fnum(pc.get("sharpe"),3,signed=True)}</td>'
                f'<td class="num">{fnum(hc.get("sharpe"),3,signed=True)}</td></tr>'
            )
    return "".join(rows)


def bootstrap_table():
    rows = []
    for ep in EP_ORDER:
        d = BOOT[ep]
        for cfg in BOOT_CFGS:
            c = d["by_config"][cfg]
            l20 = c["bootstrap_by_block_len"]["20"]
            ci = l20["ci90"] if l20 else [None, None]
            warn = " warn-row" if ep == "covid_2020" else ""
            hero = " hero-row" if cfg == "switch_holdings_corr" else ""
            rows.append(
                f'<tr class="{(warn+hero).strip()}"><td class="tk-cell"><span class="tk-name">{esc(EP_LABEL[ep])}</span></td>'
                f'<td class="tk-cell">{esc(CFG_LABEL[cfg])}</td>'
                f'<td class="num">{d["n_obs"]}</td>'
                f'<td class="num">{fnum(c["point_estimate_sharpe"],2,signed=True)}</td>'
                f'<td class="num">[{fnum(ci[0],2,signed=True)}, {fnum(ci[1],2,signed=True)}]</td></tr>'
            )
    return "".join(rows)


def combined_table():
    rows = []
    pairs = [
        ("holdings_corr_vs_static", "보유상관 스위치 vs 정적새틀라이트"),
        ("holdings_corr_vs_spy_switch", "보유상관 스위치 vs SPY스위치"),
        ("spy_or_holdingscorr_vs_spy_switch", "SPY-OR-보유상관 vs SPY스위치"),
        ("spy_or_holdingscorr_vs_static", "SPY-OR-보유상관 vs 정적새틀라이트"),
    ]
    for scen in ["base", "calm_heavy", "crisis_heavy"]:
        d = COMB[scen]
        for pair_key, pair_label in pairs:
            g = d[pair_key]
            rows.append(
                f'<tr><td class="tk-cell"><span class="tk-name">{esc(SCEN_LABEL[scen])}</span></td>'
                f'<td class="tk-cell">{esc(pair_label)}</td>'
                f'<td class="num">{fnum(g["pct_draws_a_ahead"]*100,1)}%</td>'
                f'<td class="num">{fnum(g["mean_gap"],3,signed=True)}</td>'
                f'<td class="num">[{fnum(g["ci90_gap"][0],3,signed=True)}, {fnum(g["ci90_gap"][1],3,signed=True)}]</td></tr>'
            )
    return "".join(rows)


def ev_table():
    rows = []
    for scen in ["base", "calm_heavy", "crisis_heavy"]:
        ev = EV[scen]
        order = sorted(EV_CFGS, key=lambda c: -ev[c]["sharpe"])
        for rank_i, cfg in enumerate(order, start=1):
            v = ev[cfg]
            hero = " hero-row" if rank_i == 1 else ""
            rows.append(
                f'<tr class="{hero.strip()}"><td class="tk-cell"><span class="tk-name">{esc(SCEN_LABEL[scen])}</span></td>'
                f'<td class="tk-cell">#{rank_i} {esc(CFG_LABEL[cfg])}</td>'
                f'<td class="num">{fnum(v["sharpe"],3,signed=True)}</td>'
                f'<td class="num">{fnum(v["cagr"],1,signed=True)}%</td></tr>'
            )
    return "".join(rows)


# ---- 파생 통계(내러티브용) ----
holdings_perm_pctile = PERM_HOLD.get("percentile_of_actual")
pool_perm_pctile = PERM_POOL.get("percentile_of_actual")

spy_days = CASE21["spy_days_from_peak"]
poolcorr_days = CASE21["pool_corr_days_from_peak"]
holdcorr_days = CASE21["holdings_corr_days_from_peak"]

corr_faster_than_spy = (holdcorr_days is not None and spy_days is not None and holdcorr_days < spy_days) or \
    (poolcorr_days is not None and spy_days is not None and poolcorr_days < spy_days)

base_holdcorr_vs_static = COMB["base"]["holdings_corr_vs_static"]["pct_draws_a_ahead"]
base_holdcorr_vs_spy = COMB["base"]["holdings_corr_vs_spy_switch"]["pct_draws_a_ahead"]
base_spyor_vs_spy = COMB["base"]["spy_or_holdingscorr_vs_spy_switch"]["pct_draws_a_ahead"]
crisis_spyor_vs_spy = COMB["crisis_heavy"]["spy_or_holdingscorr_vs_spy_switch"]["pct_draws_a_ahead"]

wins_majority_scenarios = sum(
    1 for s in ["base", "calm_heavy", "crisis_heavy"]
    if COMB[s]["spy_or_holdingscorr_vs_spy_switch"]["pct_draws_a_ahead"] > 0.5
)

full_full = EPISODES["full_2019_2026"]["windows"]["full_period"]
spy_full_sharpe = full_full["switch_spy"]["sharpe"]
spyor_full_sharpe = full_full["switch_spy_or_holdings_corr"]["sharpe"]
holdcorr_full_sharpe = full_full["switch_holdings_corr"]["sharpe"]

verdict_badge = "weak" if wins_majority_scenarios < 3 or (holdings_perm_pctile is not None and holdings_perm_pctile < 90) else "accept"
verdict_word = "약함(WEAK)" if verdict_badge == "weak" else "채택(ACCEPT)"

HTML = f"""<title>새틀라이트 상관관계 급등 신호 — 2021년 사각지대 재검증</title>
<style>
{CSS}
</style>

<div class="masthead">
  <div class="masthead-inner">
    <div class="masthead-eyebrow">
      <span>QUANT RESEARCH NOTE</span><span class="dot">·</span><span>트랙D 7라운드 후속</span><span class="dot">·</span><span>Correlation Spike Crisis Signal</span>
    </div>
    <h1 class="masthead-title">새틀라이트 보유종목 상관관계 급등 — 2021년 성장주 언와인드 사각지대를 잡는 세 번째 시도</h1>
    <p class="masthead-sub">작업35(H14/H15)는 새틀라이트 자체 breadth와 실현낙폭 두 신호가 모두 SPY
      200일선 스위치보다 늦게 반응해 2021년 말 성장주 언와인드(SPY는 사상최고치, 새틀라이트만
      -13.2% 선행 하락) 사각지대를 못 막았다고 결론냈다. 이번 라운드는 시도되지 않았던 세 번째
      신호군 — 보유종목/후보풀 간 페어와이즈 상관관계의 자기상대적(z-score) 급등 — 을 6개 역사적
      구간·순열검정·블록부트스트랩으로 감사한다. 2021년 사례 재측정 결과: SPY는 정점 대비
      {esc(str(spy_days))}거래일 뒤에 반응했고, 보유종목 상관관계 신호는 {esc(str(holdcorr_days))}거래일 뒤에
      반응했다 — {'더 빠르게' if corr_faster_than_spy else '오히려 더 느리게 혹은 비슷하게'} 반응해
      {'사각지대를 부분적으로 좁혔다' if corr_faster_than_spy else '사각지대를 좁히지 못했다'}. 다만
      순열검정·블록부트스트랩을 거치면 이 우위는 <span class="badge {verdict_badge}">{verdict_word}</span>
      수준으로 남는다.</p>
    <div class="masthead-meta">
      <span><b>기준일</b> {esc(GEN)}</span>
      <span><b>상관관계 창</b> 20거래일 롤링, z-lookback 252일, z_thresh∈{{1.0, 1.5, 2.0}}(중심 {Z_CENTRAL})</span>
      <span><b>부트스트랩</b> 순환 이동블록, L=10/20/40(중심 20), 창×구성당 2,000회</span>
      <span><b>기저확률</b> base/calm_heavy/crisis_heavy 3개 시나리오(H22 동일)</span>
    </div>
  </div>
</div>

<div class="wrap">

<div class="toc">
  <a href="#s0">0. 문제 제기</a>
  <a href="#s1">1. 2021년 사례 재측정</a>
  <a href="#s2">2. 6개 구간 백테스트</a>
  <a href="#s3">3. z-threshold 견고성</a>
  <a href="#s4">4. 순열검정</a>
  <a href="#s5">5. 블록부트스트랩 표본오차</a>
  <a href="#s6">6. 기댓값 재구성</a>
  <a href="#s7">7. 종합 판정</a>
  <a href="#s8">8. 한계</a>
</div>

<div class="section" id="s0">
  <h2><span class="sec-no">0</span>문제 제기 — 왜 상관관계인가</h2>
  <p class="lede">작업35가 시도한 breadth(풀의 200일선 상회 비율)와 실현 트레일링낙폭은 둘 다 이미
    "가격이 떨어진 뒤"에야 반응하는 후행지표라는 공통점이 있다. 상관관계 급등은 다른 메커니즘을
    가정한다 — 국지적(섹터/테마) 위기는 흔히 "가격이 떨어지기 시작하는 시점"보다 먼저 "종목들이
    같은 방향으로 더 강하게 움직이기 시작하는" 공행성(co-movement) 증가로 나타날 수 있다는 가설이다.
    절대 임계값이 아니라 상관관계 자신의 trailing 252일 평균/표준편차 대비 z-score로 신호를
    정의해(H14의 고정 임계값이 사후적으로 그 임계값에 맞춰 고른 것처럼 보일 위험을 피함), 실제
    보유종목 3개 간 상관관계(holdings_corr, 노이즈 큼)와 point-in-time 40종목 후보풀 전체의
    상관관계(pool_corr, 더 안정적이지만 계산비용이 커 일부 구간만 확보) 두 변형을 함께 검증한다.</p>
</div>

<div class="section" id="s1">
  <h2><span class="sec-no">1</span>2021년 성장주 언와인드 사례 재측정</h2>
  <p class="lede">H15와 동일한 방식 — 새틀라이트 고점(2021-11-19) 이후 각 신호가 처음 "약세(bear)"로
    전환한 날짜까지의 거래일 수를 측정한다.</p>
  <div class="kpi-row">
    <div class="kpi-tile"><div class="kpi-label">SPY 200일선 스위치 반응 지연</div>
      <div class="kpi-value">{esc(str(spy_days))}거래일</div>
      <div class="kpi-sub">{esc(str(CASE21["spy_switch_off_date"]))}</div></div>
    <div class="kpi-tile"><div class="kpi-label">풀 상관관계(pool_corr) 반응 지연</div>
      <div class="kpi-value">{esc(str(poolcorr_days))}거래일</div>
      <div class="kpi-sub">{esc(str(CASE21["pool_corr_off_date"]))}</div></div>
    <div class="kpi-tile"><div class="kpi-label">보유종목 상관관계(holdings_corr) 반응 지연</div>
      <div class="kpi-value">{esc(str(holdcorr_days))}거래일</div>
      <div class="kpi-sub">{esc(str(CASE21["holdings_corr_off_date"]))}</div></div>
  </div>
  <div class="callout {'good' if corr_faster_than_spy else 'warn'}">
    <div class="callout-title">{'상관관계 신호가 더 빨랐다' if corr_faster_than_spy else '상관관계 신호도 사각지대를 못 좁혔다'}</div>
    <p>작업35에서 breadth(61거래일 지연)가 SPY(43거래일 지연)보다도 늦었던 것과 비교하면, 이번
      상관관계 신호는 {'적어도 한쪽 변형이 SPY보다 빠르게 반응해 순수 후행지표는 아니라는 것을 시사한다' if corr_faster_than_spy else 'SPY 대비 뚜렷한 선행성을 보이지 못했다 — 국지적 성장주 언와인드는 상관관계 급등이라는 형태로도 충분히 빨리 드러나지 않았을 가능성이 있다'}.
      다만 단일 사례(n=1)이므로 이 지연 수치 자체를 통계적 증거로 취급하지 않는다 — 4~6절의 순열검정·
      부트스트랩이 진짜 감사다.</p>
  </div>
</div>

<div class="section" id="s2">
  <h2><span class="sec-no">2</span>6개 역사적 구간 백테스트</h2>
  <p class="lede">전체기간/2008 GFC/COVID/2022/2018/2015-16 6개 구간에서 코어단독·정적 새틀라이트·
    각 스위치 구성의 성과를 비교한다. covid_2020/selloff_2018/correction_2015_2016 3개 구간은
    point-in-time 40종목 풀 상관관계(pool_corr) 계산이 야후 파이낸스 레이트리밋으로 비용이 과도해
    생략했고(본문 7절에서 disclose), holdings_corr는 6개 구간 전부 계산했다.</p>
  <h3>전체기간</h3>
  <div class="table-wrap"><table class="data-table">
    <thead><tr><th>구간</th><th>구성</th><th>Sharpe</th><th>CAGR</th><th>MDD</th></tr></thead>
    <tbody>{episode_table("full_period")}</tbody>
  </table></div>
  <h3>위기창(crisis_window)</h3>
  <div class="table-wrap"><table class="data-table">
    <thead><tr><th>구간</th><th>구성</th><th>Sharpe</th><th>CAGR</th><th>MDD</th></tr></thead>
    <tbody>{episode_table("crisis_window")}</tbody>
  </table></div>
</div>

<div class="section" id="s3">
  <h2><span class="sec-no">3</span>z-threshold 견고성 스윕</h2>
  <p class="lede">중심값 z≥1.5 외에 z≥1.0(더 민감, 오탐 위험)·z≥2.0(더 둔감, 놓칠 위험)로 위기창
    Sharpe가 얼마나 안정적인지 확인한다(pool_corr는 계산된 구간에서만).</p>
  <div class="table-wrap"><table class="data-table">
    <thead><tr><th>구간</th><th>z-threshold</th><th>풀상관 위기창 Sharpe</th><th>보유상관 위기창 Sharpe</th></tr></thead>
    <tbody>{zsweep_table()}</tbody>
  </table></div>
</div>

<div class="section" id="s4">
  <h2><span class="sec-no">4</span>순열검정(순환이동 플라시보)</h2>
  <p class="lede">신호의 온/오프 시계열을 무작위 오프셋만큼 순환이동시켜(온/오프 비율·블록구조는
    보존, 실제 시장과의 시점 관계만 제거) 500개의 플라시보 신호를 만들고, 실제 신호의 Sharpe가 이
    분포에서 몇 백분위인지로 "타이밍 자체가 우연이 아닌가"를 확인한다(전체기간 창).</p>
  <div class="kpi-row">
    <div class="kpi-tile"><div class="kpi-label">풀상관(pool_corr) 실제 백분위</div>
      <div class="kpi-value">{fnum(pool_perm_pctile,1)}%ile</div>
      <div class="kpi-sub">실제 Sharpe {fnum(PERM_POOL.get("actual_sharpe"),3,signed=True)} / 플라시보 평균 {fnum(PERM_POOL.get("perm_mean"),3,signed=True)}</div></div>
    <div class="kpi-tile"><div class="kpi-label">보유상관(holdings_corr) 실제 백분위</div>
      <div class="kpi-value">{fnum(holdings_perm_pctile,1)}%ile</div>
      <div class="kpi-sub">실제 Sharpe {fnum(PERM_HOLD.get("actual_sharpe"),3,signed=True)} / 플라시보 평균 {fnum(PERM_HOLD.get("perm_mean"),3,signed=True)}</div></div>
  </div>
  <div class="callout">
    <div class="callout-title">95th 백분위 기준</div>
    <p>이 프로그램은 95번째 백분위를 통상적 유의성 기준선으로 써왔다(H9/H10 등). 풀상관은
      {fnum(pool_perm_pctile,1)}%ile, 보유상관은 {fnum(holdings_perm_pctile,1)}%ile로
      {'적어도 하나는' if (pool_perm_pctile or 0) >= 95 or (holdings_perm_pctile or 0) >= 95 else '둘 다'}
      {'이 기준을 넘는다' if (pool_perm_pctile or 0) >= 95 or (holdings_perm_pctile or 0) >= 95 else '이 기준에 못 미친다'} —
      실제 타이밍이 무작위 순환이동 대비 뚜렷하게 우월하다고 통계적으로 확정하기는 이르다.</p>
  </div>
</div>

<div class="section" id="s5">
  <h2><span class="sec-no">5</span>블록부트스트랩 표본오차</h2>
  <p class="lede">작업44(H33)와 동일한 순환 이동블록부트스트랩(L=10/20/40, 창×구성당 2,000회)을
    5개 구성 × 6개 구간에 적용했다. 아래는 L=20(중심 블록길이) 기준 90% 신뢰구간이다.</p>
  <div class="table-wrap"><table class="data-table">
    <thead><tr><th>구간</th><th>구성</th><th>N(거래일)</th><th>점추정 Sharpe</th><th>L=20 CI90</th></tr></thead>
    <tbody>{bootstrap_table()}</tbody>
  </table></div>
</div>

<div class="section" id="s6">
  <h2><span class="sec-no">6</span>기댓값 재구성 — 디리클레 × 부트스트랩 결합전파</h2>
  <p class="lede">H33b와 동일한 방식으로 매 draw마다 기저확률 가중치(디리클레, K=30)와 각 구간의
    부트스트랩 Sharpe 표본(L=20)을 함께 뽑아 10,000회 반복, "보유상관 스위치(또는 SPY-OR-보유상관)가
    비교 대상보다 기댓값 Sharpe가 높은 draw의 비율"을 승률로 정의했다.</p>
  <div class="table-wrap"><table class="data-table">
    <thead><tr><th>기저확률 시나리오</th><th>비교</th><th>승률(a 우위)</th><th>평균 갭</th><th>갭 CI90</th></tr></thead>
    <tbody>{combined_table()}</tbody>
  </table></div>
  <h3>가중치만 반영한 기댓값 순위 (참고, 표본오차 미반영)</h3>
  <div class="table-wrap"><table class="data-table">
    <thead><tr><th>시나리오</th><th>순위</th><th>기댓값 Sharpe</th><th>기댓값 CAGR</th></tr></thead>
    <tbody>{ev_table()}</tbody>
  </table></div>
</div>

<div class="section" id="s7">
  <h2><span class="sec-no">7</span>종합 판정 — 사각지대가 닫혔는가</h2>
  <p>기본(base) 시나리오에서 보유상관 스위치는 정적 새틀라이트 대비 {fnum(base_holdcorr_vs_static*100,0)}%,
    SPY 스위치 대비 {fnum(base_holdcorr_vs_spy*100,0)}% 승률을 보인다. SPY와 보유상관을 OR로 결합한
    구성은 SPY 단독 스위치를 기본 시나리오 {fnum(base_spyor_vs_spy*100,0)}%, 위기가중 시나리오
    {fnum(crisis_spyor_vs_spy*100,0)}% 승률로 앞선다 — 3개 시나리오 중 {wins_majority_scenarios}개에서
    SPY-OR-보유상관 결합이 SPY 단독보다 낫다.</p>
  <div class="callout {'good' if wins_majority_scenarios >= 2 else 'warn'}">
    <div class="callout-title">최종 판정: <span class="badge {verdict_badge}">{verdict_word}</span></div>
    <p>{'상관관계 급등 신호(특히 SPY와의 OR 결합)는 작업35의 breadth·낙폭 신호가 기각됐던 것과 달리, 적어도 방향성 면에서는 SPY 단독 스위치를 개선하는 쪽으로 나타난다' if wins_majority_scenarios >= 2 else '상관관계 급등 신호는 작업35의 breadth·낙폭 신호와 마찬가지로 SPY 단독 스위치를 안정적으로 이기지 못한다'} —
      순열검정 백분위({fnum(holdings_perm_pctile,1)}%ile)가 이 프로그램의 95% 기준선에 못 미치고,
      z-threshold 견고성도 완전하지 않다는 점에서 <b>"약한 우위" 이상으로 격상하기는 이르다</b>.
      2021년 사각지대는 이 라운드로도 완전히 닫히지 않았다 — {'SPY와의 OR 결합이 최소한의 완화책은 될 수 있다는 정도가 이 라운드가 줄 수 있는 최선의 결론이다' if wins_majority_scenarios >= 2 else '단일 신호로는 여전히 미해결 과제로 남긴다'}.</p>
  </div>
</div>

<div class="section" id="s8">
  <h2><span class="sec-no">8</span>한계</h2>
  <ul>
    <li>pool_corr(40종목 풀 상관관계)는 야후 파이낸스 레이트리밋 때문에 6개 구간 중 3개
      (covid_2020/selloff_2018/correction_2015_2016, 기저확률 합 37%)에서 계산을 생략했다 — 6절
      기댓값 계산에는 pool_corr 계열 구성을 아예 포함하지 않고 holdings_corr만 사용해 이 비대칭이
      결과를 왜곡하지 않도록 했다.</li>
    <li>holdings_corr는 보유종목 3개(페어 3개)뿐이라 표본이 매우 작고 노이즈가 크다 — z-score
      정의 자체의 통계적 안정성이 pool_corr보다 낮다.</li>
    <li>2021년 사례 재측정(1절)은 n=1 사건이다 — 지연 거래일수 차이를 통계적 증거로 취급하지
      않았고, 어디까지나 4~6절 감사의 참고 사례로만 썼다.</li>
    <li>순열검정은 신호의 시점 관계만 끊고 온/오프 비율·블록구조는 보존하는 순환이동 방식이다 —
      다른 플라시보 생성 방식(예: 완전 무작위 재추출)을 썼다면 백분위가 달라질 수 있다.</li>
    <li>디리클레 K=30 결합전파는 6개 구간의 상관관계(같은 시장 국면이 여러 구간에 걸쳐 있을 수
      있음)를 독립으로 가정한다 — 이 프로그램의 이전 라운드(H30/H33b)와 동일한 단순화다.</li>
  </ul>
</div>

</div>
<footer>
  <p>산출물: analysis/2026-09-14_satellite_correlation_crisis_signal/ (h_signals_and_backtest.py,
    h_bootstrap_and_permutation.py, build_report_data.py, report_data.json, build_report.py).
    작업35(satellite_specific_crisis_signal_research)의 직접 후속. core/, app/는 수정하지 않음.</p>
</footer>
"""

with open(f"{OUT_DIR}/final_report.html", "w", encoding="utf-8") as f:
    f.write(HTML)
print("wrote final_report.html", len(HTML))
