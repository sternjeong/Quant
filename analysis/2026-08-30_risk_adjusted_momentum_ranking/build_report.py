#!/usr/bin/env python3
"""report_data.json을 읽어 final_report.html을 만든다.

analysis/2026-08-30_core_filter_bootstrap_and_satellite_weight_extension/build_report.py와 동일한
디자인 시스템(다크네이비/올리브 톤, 세리프 헤드라인, TOC, 섹션 번호, 판정 배지)을 재사용한다.
"""
import json
import math
import os

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

with open(f"{OUT_DIR}/report_data.json", encoding="utf-8") as f:
    R = json.load(f)

TABLE = R["table"]
PERM = R["permutation_test"]
BEST_NONRAW = R["best_variant_by_combined_sharpe_delta"]
EP_ORDER = ["full_2019_2026", "gfc_2008", "covid_2020", "bear_2022", "selloff_2018", "correction_2015_2016"]
EP_LABEL = {
    "full_2019_2026": "전체기간 2019-2026", "gfc_2008": "2008 GFC (SPY/TLT/GLD 3자산 근사)",
    "covid_2020": "COVID 2020 (~5주)", "bear_2022": "2022 완만약세장",
    "selloff_2018": "2018 4분기 급락", "correction_2015_2016": "2015-16 조정",
}
VARIANT_LABEL = {
    "raw": "raw (기존 챔피언)", "vol_scaled_12m": "위험조정(12m수익/12m변동성)",
    "sortino_12m": "Sortino류(12m수익/12m하방변동성)", "vol_scaled_3m_vol": "위험조정(12m수익/3m변동성)",
}
VARIANT_ORDER = ["raw", "vol_scaled_12m", "sortino_12m", "vol_scaled_3m_vol"]


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
html{-webkit-text-size-adjust:100%;}
body{ margin:0; background:var(--bg-page); color:var(--ink);
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif; line-height:1.6; font-size:16px; }
.serif{ font-family: "Iowan Old Style","Palatino Linotype", Georgia, serif; }
.mono, .num, td.num, .tk-name, .kpi-value, code {
  font-family: ui-monospace, "SF Mono", "Cascadia Mono", Consolas, monospace;
  font-variant-numeric: tabular-nums; }
a{ color:var(--accent); }
.wrap{ max-width: 1020px; margin:0 auto; padding: 0 24px 96px; }
.masthead{ background: var(--accent); color: var(--accent-ink); padding: 56px 24px 40px; }
.masthead-inner{ max-width:1020px; margin:0 auto; }
.masthead-eyebrow{ font-size:12.5px; letter-spacing:0.12em; text-transform:uppercase; opacity:0.82;
  font-family: ui-monospace, "SF Mono", Consolas, monospace; display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
.masthead-eyebrow .dot{ opacity:0.5; }
h1.masthead-title{ font-family:"Iowan Old Style","Palatino Linotype", Georgia, serif; font-weight:600;
  font-size: clamp(28px, 4.2vw, 44px); line-height:1.15; margin: 14px 0 10px; text-wrap: balance; max-width: 32ch; }
.masthead-sub{ font-size:16.5px; max-width:74ch; opacity:0.92; margin:0 0 22px; }
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
.lede{ font-size:16.5px; color:var(--ink-2); max-width:76ch; }
.section p{ max-width:80ch; }
.section > p, .section > .lede { margin-top: 0; }
.section li{ max-width:76ch; }
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
footer{ max-width:1020px; margin:40px auto 0; padding: 26px 24px 10px; border-top:1px solid var(--hairline);
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
"""


def variant_table(episodes):
    rows = []
    for ep in episodes:
        d = TABLE[ep]
        raw_sharpe = d["raw"]["sharpe"]
        for vi, v in enumerate(VARIANT_ORDER):
            m = d[v]
            delta = m["sharpe"] - raw_sharpe if v != "raw" else None
            hero = " hero-row" if v == "raw" else ""
            warn = ""
            if delta is not None and delta < -0.15:
                warn = " warn-row"
            label_ep = f'<span class="tk-name">{esc(EP_LABEL[ep])}</span>' if vi == 0 else ""
            rows.append(
                f'<tr class="{(hero+warn).strip()}"><td class="tk-cell">{label_ep}</td>'
                f'<td class="tk-cell">{esc(VARIANT_LABEL[v])}</td>'
                f'<td class="num">{fnum(m["sharpe"],2,signed=True)}</td>'
                f'<td class="num">{fnum(m["cagr"],2,signed=True)}%</td>'
                f'<td class="num">{fnum(m["mdd"],2)}%</td>'
                f'<td class="num">{fnum(m["calmar"],2,signed=True)}</td>'
                f'<td class="num">{fnum(delta,2,signed=True) if delta is not None else "—"}</td></tr>'
            )
    return "".join(rows)


N_PERM = PERM["n_permutations"]
EDGE_ACTUAL = PERM["actual_edge"]
EDGE_MEAN = PERM["permuted_edge_mean"]
EDGE_STD = PERM["permuted_edge_std"]
P_EDGE = PERM["p_value_edge"]
PCTL_EDGE = PERM["percentile_edge"]

GFC_RAW = TABLE["gfc_2008"]["raw"]
GFC_VS = TABLE["gfc_2008"]["vol_scaled_12m"]
COVID_RAW = TABLE["covid_2020"]["raw"]
COVID_VS = TABLE["covid_2020"]["vol_scaled_12m"]
BEAR_RAW = TABLE["bear_2022"]["raw"]
BEAR_VS3M = TABLE["bear_2022"]["vol_scaled_3m_vol"]
FULL_RAW = TABLE["full_2019_2026"]["raw"]
FULL_VS = TABLE["full_2019_2026"]["vol_scaled_12m"]

HTML = f"""<title>위험조정 모멘텀 랭킹 검증</title>
<style>
{CSS}
</style>

<div class="masthead">
  <div class="masthead-inner">
    <div class="masthead-eyebrow">
      <span>QUANT RESEARCH NOTE</span><span class="dot">·</span><span>신규 독립 트랙</span><span class="dot">·</span><span>Hypothesis-Driven Study</span>
    </div>
    <h1 class="masthead-title">위험조정(샤프) 모멘텀 랭킹은 챔피언의 raw 12개월 모멘텀을 이기지 못한다</h1>
    <p class="masthead-sub">"크지만 들쭉날쭉한 추세"보다 "작지만 꾸준한 추세"를 우선하는 변동성조정
      모멘텀은 학술적으로 근거가 있는 아이디어지만, 이 챔피언의 17자산·top4·월간 리밸런싱 틀에
      그대로 적용했을 때는 전체기간과 대부분의 위기 구간에서 raw 모멘텀보다 <b>일관되게 나쁘거나
      통계적으로 구분 안 되는</b> 결과를 냈다. 유일한 예외(2008 GFC 근사, 2022년 3개월 변동성판)는
      효과가 작고 방향이 구간마다 뒤집힌다.</p>
    <div class="masthead-meta">
      <span><b>비교 변형</b> raw / 위험조정(12m) / Sortino류(12m) / 위험조정(3m변동성)</span>
      <span><b>검증 구간</b> 6개 창(전체 2019-2026 + 위기 5개)</span>
      <span><b>순열검정</b> {N_PERM}회, 자산별 독립 캔들 셔플</span>
    </div>
  </div>
</div>

<div class="wrap">

  <nav class="toc">
    <a href="#scope">00 문제 제기</a>
    <a href="#design">01 백테스트 설계 및 6개 창 비교</a>
    <a href="#perm">02 통계적 유의성 검증(순열검정)</a>
    <a href="#synthesis">03 종합 — 채택/기각 판정과 메커니즘</a>
    <a href="#limitations">04 한계</a>
  </nav>

  <section class="section" id="scope">
    <h2><span class="sec-no">00</span> 문제 제기 — 왜 위험조정 모멘텀인가</h2>
    <p class="lede">이 저장소의 챔피언(17자산 듀얼모멘텀 로테이션, 작업19-23)은 처음부터 지금까지
      "지난 12개월 raw 총수익률"로만 후보를 랭킹해 왔다 — 룩백기간 자체는 H27(작업 2026-08-23,
      system_vs_buyhold_and_lookback_robustness)이 3~18개월로 재스윕했지만, "수익률을 무엇으로
      나눠 랭킹할지"라는 신호의 형태 자체는 한 번도 바뀐 적이 없다.</p>
    <p>학술적으로는 변동성으로 모멘텀 신호를 조정하는 접근이 상당히 두텁게 뒷받침된다.
      Barroso &amp; Santa-Clara(2015, "Momentum has its Moments", <i>Journal of Financial
      Economics</i>)는 모멘텀 포트폴리오를 최근 실현변동성의 역수로 스케일링하면(risk-managed
      momentum) 유명한 "모멘텀 크래시"(2009년 반등장처럼 롱-숏 모멘텀이 급격히 역전되는 구간)의
      꼬리위험이 크게 줄고 샤프비율이 개선된다는 것을 보였다. Daniel &amp; Moskowitz(2016,
      "Momentum Crashes", <i>Journal of Financial Economics</i>)는 그 메커니즘을 더 파고들어,
      모멘텀 크래시가 시장이 급락했다가 급반등하는 국면에서 "패자(과거에 하락한 자산)가 시장베타가
      높아 반등장에서 승자보다 더 크게 튀어오르며" 발생한다고 설명한다. Blitz 등(로베코 계열
      연구, 예: Blitz, Huij &amp; Martens 2011 "Residual Momentum")은 종목 고유의 변동성(잔차
      변동성)이 낮은 모멘텀 종목이 더 안정적인 초과수익을 낸다고 보고한다. 이 저장소의 챔피언은
      이미 이진 시장필터(SPY&lt;200일선)로 "언제 노출을 줄일지"를 다루지만, "매달 상위 4개를
      무엇으로 뽑을지"라는 횡단면 랭킹 신호 자체에는 이 문헌의 아이디어가 반영된 적이 없다 — 이
      갭을 메우는 것이 이번 라운드의 목적이다.</p>
    <div class="callout">
      <div class="callout-title">가설</div>
      <p>trailing 12개월 수익률을 같은 기간 일간수익률의 연율화 변동성으로 나눈 "위험조정
        모멘텀"으로 top-4 랭킹을 바꾸면, "크지만 변동성이 큰(그래서 반전 위험이 큰)" 후보 대신
        "작지만 꾸준한" 후보를 우선하게 되어 특히 위기 후 반등장에서의 휩쏘(whipsaw)를 줄이고
        위기구간 Sharpe/Calmar를 개선할 것이다. 절대모멘텀 게이트(양의 raw 12개월 수익률)는 신호
        종류와 무관하게 그대로 유지해, 바뀌는 것은 오직 "몇 개를 살지 정하는 순위" 하나뿐이다.</p>
    </div>
  </section>

  <section class="section" id="design">
    <h2><span class="sec-no">01</span> 백테스트 설계 및 6개 창 비교</h2>
    <p class="lede"><code>analysis/2026-08-19_champion_beta_and_satellite_research/champion_strategy.py</code>
      의 유니버스(GICS 11섹터+TLT/IEF/GLD+EFA/HYG/DBC)·top4·월간 리밸런싱·SPY&lt;200일선 50%축소
      이진 시장필터·왕복 0.1% 비용을 그대로 재사용하고, 랭킹 신호만 4가지로 바꿔가며 돌렸다
      (<code>risk_adjusted_champion.py</code>): (1) <b>raw</b> — 기존 챔피언 그대로, (2)
      <b>위험조정(12m)</b> — 12개월 수익률 ÷ 12개월 일간수익률 연율화 변동성, (3) <b>Sortino류(12m)</b>
      — 분모를 하방(음수)일간수익률만의 변동성으로 대체, (4) <b>위험조정(3m변동성)</b> — 모멘텀
      룩백은 12개월 그대로 두고 변동성만 3개월로 줄여 "12개월 변동성이 너무 느리게 반응해 신호를
      희석시키는 것 아닌가"를 별도 점검. 2008 GFC는 섹터ETF 미상장으로 이 프로그램의 기존 관례대로
      SPY+TLT+GLD 3자산·top2 근사를 썼다.</p>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>창</th><th>랭킹 신호</th><th>Sharpe</th><th>CAGR</th><th>MDD</th><th>Calmar</th><th>Δ Sharpe(vs raw)</th></tr></thead>
        <tbody>{variant_table(EP_ORDER)}</tbody>
      </table>
    </div>
    <p class="caveat">빨간 배경 행 = raw 대비 Sharpe가 0.15 이상 악화된 경우. 초록 배경 행 = raw
      자체(비교 기준선).</p>
    <div class="callout warn">
      <div class="callout-title">가설과 반대 방향: 전체기간에서 raw가 확실히 앞선다</div>
      <p>챔피언의 주력 검증 구간인 전체기간 2019-2026에서 raw Sharpe {fnum(FULL_RAW['sharpe'],2)}
        (CAGR {fnum(FULL_RAW['cagr'],1)}%) 대 위험조정(12m) Sharpe {fnum(FULL_VS['sharpe'],2)}
        (CAGR {fnum(FULL_VS['cagr'],1)}%) — 세 위험조정 변형 모두 raw보다 낮았다. 더 뚜렷한 반례는
        COVID 2020: raw Sharpe {fnum(COVID_RAW['sharpe'],2)}(CAGR {fnum(COVID_RAW['cagr'],1)}%)인 데
        비해 위험조정(12m)은 Sharpe {fnum(COVID_VS['sharpe'],2)}(CAGR {fnum(COVID_VS['cagr'],1)}%)로
        완전히 반대 부호다 — 급락 후 급반등장에서 위험조정 신호가 "최근까지 변동성이 낮았던(그래서
        아직 덜 반등한) 후보"를 우선하다가 실제로 가장 크게 반등한 고변동성 섹터를 놓친 결과로
        해석된다. 예외는 두 곳뿐이다: 2008 GFC 근사(raw Sharpe {fnum(GFC_RAW['sharpe'],2)} vs
        위험조정 Sharpe {fnum(GFC_VS['sharpe'],2)}, 3자산·top2라 후보군이 좁아 효과 크기 자체가
        작음)와 2022년 약세장에서 변동성 룩백을 3개월로 줄인 변형(raw Sharpe {fnum(BEAR_RAW['sharpe'],2)}
        vs Sharpe {fnum(BEAR_VS3M['sharpe'],2)}). 두 예외 모두 부호는 가설과 맞지만 근거 표본이
        작거나(3자산) 특정 변동성 룩백 선택에만 의존해 일반화하기엔 약하다.</p>
    </div>
  </section>

  <section class="section" id="perm">
    <h2><span class="sec-no">02</span> 통계적 유의성 검증 — 순열검정</h2>
    <p class="lede"><code>core.backtest_engine._shuffle_daily_bars</code>(Masters류 "4대 검증
      테스트"의 순열검정 핵심 유틸, 작업13/14가 이미 pytest로 검증)를 코드 그대로 재사용해 17개
      자산+SPY 각각을 독립적으로 캔들 순서만 무작위로 섞은 가짜 시계열 {N_PERM}회를 만들고, 그
      위에서 raw와 위험조정(12m) 챔피언을 동일하게 재실행해 "raw 대비 위험조정의 Sharpe 격차"의
      귀무분포를 만들었다(대상 구간: 주력 검증 구간인 전체기간 2019-2026, 위험조정(12m)은 4개
      변형 중 논문 근거가 가장 직접적인 형태라 대표로 선택 — 위 표에서 이미 이겼다면 이 변형이
      1순위 후보였겠지만, 실제로는 어떤 변형도 raw를 이기지 못했으므로 여기서는 "raw 대비 손실이
      노이즈로 설명될 만큼 작은가"를 검정하는 방향으로 쓰였다).</p>
    <div class="kpi-row">
      <div class="kpi-tile"><div class="kpi-label">실측 격차(위험조정−raw, Sharpe)</div>
        <div class="kpi-value neg">{fnum(EDGE_ACTUAL,3,signed=True)}</div>
        <div class="kpi-sub">raw={fnum(PERM['actual_sharpe_raw'],2)}, 위험조정={fnum(PERM['actual_sharpe_best'],2)}</div></div>
      <div class="kpi-tile"><div class="kpi-label">순열 {N_PERM}회 격차 평균±표준편차</div>
        <div class="kpi-value">{fnum(EDGE_MEAN,3,signed=True)} ± {fnum(EDGE_STD,3)}</div>
        <div class="kpi-sub">노이즈만으로도 이 정도 폭의 격차가 흔함</div></div>
      <div class="kpi-tile"><div class="kpi-label">p-value (격차 기준)</div>
        <div class="kpi-value">{fnum(P_EDGE,4)}</div>
        <div class="kpi-sub">백분위 {fnum(PCTL_EDGE,1)}% — 통계적으로 유의하지 않음</div></div>
    </div>
    <div class="callout">
      <div class="callout-title">해석: raw와 위험조정의 차이는 통계적으로 구분되지 않는다</div>
      <p>실측 격차 {fnum(EDGE_ACTUAL,3,signed=True)}는 순열 {N_PERM}회 분포의 평균
        {fnum(EDGE_MEAN,3,signed=True)}·표준편차 {fnum(EDGE_STD,3)}에 비춰보면 백분위
        {fnum(PCTL_EDGE,1)}%(p={fnum(P_EDGE,4)})로, 순수 노이즈만으로도 이 정도 격차가 나올 확률이
        {fnum(P_EDGE*100,1)}%에 달한다 — 통상 기준(p&lt;0.10)에 한참 못 미친다. 즉 "전체기간에서
        위험조정이 raw보다 나쁘다"는 관찰조차 확신을 갖고 말하기엔 근거가 약하다는 뜻이다(방향은
        일관되게 나쁜 쪽이지만 크기가 노이즈 대역 안에 있다). 위험조정 단독 Sharpe의 순열검정 p-value도
        {fnum(PERM['p_value_best_alone'],4)}로
        비슷한 수준이다 — 두 신호 모두 순수 셔플 데이터에서 흔히 나올 법한 범위 안에 있다는 뜻이며,
        이는 "이 정도 표본(약 7년)으로는 두 랭킹 신호를 통계적으로 구분하기 어렵다"는 걸 시사한다.</p>
    </div>
  </section>

  <section class="section" id="synthesis">
    <h2><span class="sec-no">03</span> 종합 — 판정과 메커니즘</h2>
    <p><span class="verdict-badge v-reject">기각</span> 위험조정(샤프) 모멘텀 랭킹은 이 챔피언
      구조에서 raw 12개월 모멘텀을 대체할 근거가 없다. 4개 변형(위험조정 12m, Sortino류 12m,
      위험조정 3m변동성) 중 어느 것도 전체기간 2019-2026에서 raw를 이기지 못했고, 5개 위기구간
      중 3곳(COVID 2020, 2022 약세장의 12개월 변동성판, 2018/2015-16 급락·조정)에서도 동등하거나
      뚜렷이 나빴다. 유일하게 방향이 맞은 두 사례(2008 GFC 근사, 2022년 3개월 변동성판)는 효과가
      작고 표본이 좁아 우연일 가능성을 배제할 수 없다 — 실제로 순열검정은 전체기간의 (작은) 손실조차
      노이즈 대역 안에 있다는 걸 보여준다.</p>
    <h3>메커니즘: 왜 COVID에서 정확히 반대로 작동했나</h3>
    <p>Daniel &amp; Moskowitz(2016)가 설명하는 모멘텀 크래시는 "시장이 급락한 뒤 급반등할 때 과거의
      패자(하락한 고베타 자산)가 승자보다 더 크게 튀어오른다"는 것이었다 — 이 메커니즘은 롱-숏
      모멘텀 팩터를 전제로 한다. 이 챔피언은 롱온리·절대모멘텀 게이트가 있는 로테이션이라 애초에
      "하락한 자산을 공매도해서 반등에 당하는" 경로 자체가 없다. 대신 관찰된 실패 경로는 다르다:
      2020년 3월 코로나 급락 직후 리밸런싱 시점에서, raw 모멘텀은 "그나마 덜 빠졌거나 이미 반등
      조짐을 보이는" 고변동성 섹터(예: 기술주)를 상위로 뽑는 반면, 위험조정 신호는 같은 후보의
      분모(변동성)가 급증했기 때문에 순위가 낮아지고, 대신 변동성이 낮았던(하지만 그만큼 반등폭도
      작은) 방어적 자산이 상위로 올라온다 — "휩쏘를 피하려다 반등장 자체를 놓치는" 정확히 반대
      실패 모드다. 이건 Barroso&amp;Santa-Clara의 "포지션 크기를 변동성으로 줄인다"는 원 처방과
      이번 구현("포지션 크기는 동일가중 유지, 순위만 변동성으로 조정")이 다르기 때문일 수 있다 —
      즉 이 결과는 "위험조정 모멘텀 자체가 틀렸다"기보다 "랭킹 단계에 적용하는 특정 방식이 이
      챔피언의 롱온리·이산적 top4 구조와 맞지 않았다"는 더 좁은 결론으로 읽어야 한다.</p>
    <h3>2008 GFC에서는 왜 방향이 맞았나</h3>
    <p>GFC 3자산 근사(SPY/TLT/GLD, top2)에서는 위험조정이 근소하게 앞섰다(Sharpe
      {fnum(GFC_RAW['sharpe'],2)}→{fnum(GFC_VS['sharpe'],2)}). 이 구간은 TLT(국채)가 변동성은
      낮고 꾸준히 상승한 "안전자산 랠리"였던 반면 SPY는 변동성이 극단적으로 컸다 — 위험조정 신호가
      정확히 이 상황(변동성이 낮고 꾸준한 승자 vs 변동성이 크고 들쭉날쭉한 하락 후보)에 최적화된
      형태라 방향이 맞았다. 하지만 후보가 3개뿐이고 top2를 뽑으므로 순위가 한 자리만 바뀌어도
      결과가 크게 흔들리는 구조라, 이 결과를 17자산·top4 프로덕션 챔피언에 일반화하기는 어렵다.</p>
  </section>

  <section class="section" id="limitations">
    <h2><span class="sec-no">04</span> 한계</h2>
    <ul>
      <li>순열검정은 대표로 위험조정(12m) 대 raw, 전체기간 2019-2026 하나의 조합에만 적용했다 —
        Sortino류·3개월 변동성판이나 개별 위기구간까지 전부 순열검정하지는 않았다(계산량 문제).
        다른 조합에서 방향이 뒤집힐 여지는 낮아 보이지만(표 1의 모든 위기구간이 대체로 일관된
        방향을 보임) 확정적으로 배제하지는 못한다.</li>
      <li>2008 GFC는 3자산·top2 근사라 17자산·top4 프로덕션 챔피언과 구조가 다르다 — 여기서 관찰된
        위험조정의 근소한 우위가 17자산 버전에서도 재현된다는 보장은 없다(실제로 섹터ETF가
        상장됐다면 재현 여부를 직접 검증할 수 있었을 것).</li>
      <li>위험조정 신호를 "랭킹"에만 적용하고 "포지션 크기"에는 적용하지 않았다 — Barroso&amp;
        Santa-Clara의 원 처방(포지션 크기 조정)을 이 로테이션 구조(동일가중 top4)에 이식하는 건
        범위 밖이었다. 그 변형이 이번 결과와 다르게 나올 가능성은 남아있다.</li>
      <li>변동성 추정을 단순 표준편차(일간수익률 rolling std)로만 썼다 — EWMA나 GARCH류 변동성
        추정으로 바꾸면 반응속도가 달라져 결과가 바뀔 여지가 있다.</li>
      <li>거래비용/생존편향 등 모형오차(specification error) 자체는 다루지 않았다 — raw 챔피언과
        동일한 비용 관례를 그대로 적용해 두 변형 간 상대비교의 공정성만 확보했다.</li>
    </ul>
  </section>

</div>

<footer>
  <p>QUANT RESEARCH · 신규 독립 트랙 · 위험조정 모멘텀 랭킹 검증(6개 창 백테스트 + {N_PERM}회
    순열검정) · 이 문서는 투자 조언이 아니며 저자 개인의 연구 기록입니다.</p>
</footer>
"""

with open(f"{OUT_DIR}/final_report.html", "w", encoding="utf-8") as f:
    f.write(HTML)
print("[build_report] saved final_report.html")
