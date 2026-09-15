#!/usr/bin/env python3
"""report_data.json을 읽어 final_report.html을 만든다.

analysis/2026-08-30_risk_adjusted_momentum_ranking/build_report.py와 동일한 디자인 시스템
(다크네이비/올리브 톤, 세리프 헤드라인, TOC, 섹션 번호, 판정 배지)을 재사용한다.
"""
import json
import math
import os

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

with open(f"{OUT_DIR}/report_data.json", encoding="utf-8") as f:
    R = json.load(f)

TABLE = R["table"]
PERM = R["permutation_test"]
EP_ORDER = ["full_2019_2026", "gfc_2008", "covid_2020", "bear_2022", "selloff_2018", "correction_2015_2016"]
EP_LABEL = {
    "full_2019_2026": "전체기간 2019-2026", "gfc_2008": "2008 GFC (SPY/TLT/GLD 3자산 근사)",
    "covid_2020": "COVID 2020 (~5주)", "bear_2022": "2022 완만약세장",
    "selloff_2018": "2018 4분기 급락", "correction_2015_2016": "2015-16 조정",
}
VARIANT_LABEL = {
    "raw": "raw 12개월(스킵없음, 기존 챔피언)",
    "raw_skip1m": "raw 12-2(최근 1개월 제외, J&T/Novy-Marx 관행)",
    "vol_scaled_12m": "위험조정(12m수익/12m변동성)",
    "sortino_12m": "Sortino류(12m수익/12m하방변동성)",
    "vol_scaled_3m_vol": "위험조정(12m수익/3m변동성)",
}
VARIANT_ORDER = ["raw", "raw_skip1m", "vol_scaled_12m", "sortino_12m", "vol_scaled_3m_vol"]


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
.src-list{ font-size:14px; }
.src-list li{ margin-bottom:10px; }
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
            warn = " warn-row" if v == "raw_skip1m" and delta is not None and delta < -0.15 else ""
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

FULL_RAW = TABLE["full_2019_2026"]["raw"]
FULL_SKIP = TABLE["full_2019_2026"]["raw_skip1m"]
FULL_VS = TABLE["full_2019_2026"]["vol_scaled_12m"]
COVID_RAW = TABLE["covid_2020"]["raw"]
COVID_SKIP = TABLE["covid_2020"]["raw_skip1m"]
COVID_VS = TABLE["covid_2020"]["vol_scaled_12m"]
CORR_RAW = TABLE["correction_2015_2016"]["raw"]
CORR_SKIP = TABLE["correction_2015_2016"]["raw_skip1m"]

SOURCES = [
    ("Jegadeesh, N. &amp; Titman, S. (1993)",
     "\"Returns to Buying Winners and Selling Losers: Implications for Stock Market Efficiency\", "
     "<i>The Journal of Finance</i> 48(1), 65-91.",
     "https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.1993.tb04702.x",
     "3-12개월 형성기간 모멘텀의 원조 논문. 이후 문헌 관행이 된 \"12-2\"(형성기간 12개월, 가장 최근"
     " 1개월 제외)의 출발점."),
    ("Novy-Marx, R. (2012)",
     "\"Is Momentum Really Momentum?\", <i>Journal of Financial Economics</i> 103(3), 429-453"
     " (2012 Fama-DFA Prize 수상).",
     "https://www.sciencedirect.com/science/article/abs/pii/S0304405X11001152",
     "모멘텀의 예측력은 형성 시점 직전 1개월이 아니라 t-12~t-7개월의 \"중간 구간\" 성과에서 나온다는"
     " 것을 보이고, 가장 최근 1개월을 신호에서 제외하면(단기 반전 노이즈 제거) 모멘텀 수익이"
     " 개선된다고 명시적으로 재확인."),
    ("Rachev, S., Jasic, T., Stoyanov, S. &amp; Fabozzi, F.J. (2007)",
     "\"Momentum Strategies Based on Reward-Risk Stock Selection Criteria\", "
     "<i>Journal of Banking &amp; Finance</i> 31(8), 2325-2346.",
     "https://www.sciencedirect.com/science/article/abs/pii/S0378426607000696",
     "S&amp;P500 517종목·1996-2003 표본에서, 원시누적수익률 랭킹이 절대수익(월 1.3%)은 가장 크지만"
     " Sharpe/CVaR류 보상위험비율 랭킹이 독립적인 위험조정 성과지표에서는 더 우수하다고 보고 -"
     " 이 저장소의 결론과 부분적으로만 일치(아래 04절 참조)."),
    ("Barroso, P. &amp; Santa-Clara, P. (2015)",
     "\"Momentum Has Its Moments\", <i>Journal of Financial Economics</i> 116(1), 111-120.",
     "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2041429",
     "모멘텀 \"랭킹\"이 아니라 이미 선정된 모멘텀 포트폴리오의 \"노출 크기\"를 최근 실현변동성의"
     " 역수로 스케일링(레버리지 상향 허용)하면 모멘텀 크래시가 거의 사라지고 Sharpe가 거의 2배가"
     " 된다는 결과 - 이 저장소가 2026-08-30에 이미 인용했으나 \"랭킹 단계\"에 잘못 적용했음을"
     " 스스로 한계로 명시한 바 있음(아래 04절)."),
    ("Daniel, K. &amp; Moskowitz, T.J. (2016)",
     "\"Momentum Crashes\", <i>Journal of Financial Economics</i> 122(2), 221-247.",
     "https://www.sciencedirect.com/science/article/abs/pii/S0304405X16301490 (NBER WP 20439)",
     "모멘텀 크래시는 시장이 급락한 뒤 급반등하는 \"패닉\" 국면에서 발생하며, 이는 롱-숏 모멘텀"
     " 구조(과거 패자의 옵션적 페이오프)를 전제로 한다는 메커니즘 규명."),
    ("Moreira, A. &amp; Muir, T. (2017)",
     "\"Volatility-Managed Portfolios\", <i>The Journal of Finance</i> 72(4), 1611-1644.",
     "https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12513",
     "시장/가치/모멘텀 등 각 팩터를 직전월 실현분산의 역수로 매월 스케일링하면 Sharpe와 효용이"
     " 전반적으로 개선된다는 결과 - Barroso&amp;Santa-Clara류 변동성관리를 다자산 팩터로 일반화."),
    ("Cederburg, S., O'Doherty, M.S., Wang, F. &amp; Yan, S. (2020)",
     "\"On the Performance of Volatility-Managed Portfolios\", "
     "<i>Journal of Financial Economics</i> 138(1), 95-117.",
     "https://www.sciencedirect.com/science/article/abs/pii/S0304405X2030132X",
     "103개 주식 전략에 대한 확장 표본 재검증 - 스패닝 회귀에서는 Moreira&amp;Muir와 일치하는"
     " 알파가 나오지만, 실시간으로 구현 가능한(ex-post 최적 결합가중치를 쓰지 않는) 버전은 대체로"
     " 무관리 포트폴리오를 못 이긴다는 비판 - 이 저장소의 H28/H34 변동성타겟팅 오버레이가 부트스트랩"
     " 결합전파에서 동전던지기(49.7%)로 무너진 것과 방향이 일치."),
]


def src_list():
    items = []
    for name, cite, link, note in SOURCES:
        items.append(
            f'<li><b>{name}</b>, {cite} <a href="{link}" target="_blank" rel="noopener">[link]</a><br>'
            f'<span style="color:var(--ink-2); font-size:13px;">{note}</span></li>'
        )
    return "".join(items)


HTML = f"""<title>모멘텀 랭킹 문헌 대조</title>
<style>
{CSS}
</style>

<div class="masthead">
  <div class="masthead-inner">
    <div class="masthead-eyebrow">
      <span>QUANT RESEARCH NOTE</span><span class="dot">·</span><span>리서치 에이전트 H</span><span class="dot">·</span><span>외부 문헌 대조</span>
    </div>
    <h1 class="masthead-title">이 챔피언의 12개월 원시모멘텀 랭킹, 학술 문헌과 대조하면 어디서 갈리는가</h1>
    <p class="masthead-sub">confidence_table의 "모멘텀 랭킹 방식"(moderate)과 "위험조정 모멘텀 랭킹"
      (reversed) 두 항목을 실제 학술 문헌 7편과 대조했다. 원시수익 랭킹이 위험조정 랭킹을 이긴다는
      내부 결론은 문헌과 부분적으로만 일치하고, 문헌이 표준으로 쓰는 "12-2"(최근 1개월 제외) 관행을
      이 저장소 데이터로 처음 재현해보니 <b>전체기간·COVID 모두에서 오히려 원본(스킵없음)보다
      나빴다</b> - 문헌과 정반대 방향의 새로운 반례.</p>
    <div class="masthead-meta">
      <span><b>오늘의 주제</b> 12개월 트레일링 모멘텀 랭킹: raw vs 위험조정 vs 12-2 스킵</span>
      <span><b>검증 구간</b> 6개 창(전체 2019-2026 + 위기 5개)</span>
      <span><b>순열검정</b> {N_PERM}회, 자산별 독립 캔들 셔플</span>
    </div>
  </div>
</div>

<div class="wrap">

  <nav class="toc">
    <a href="#scope">00 오늘의 주제 선정</a>
    <a href="#lit">01 문헌 서베이 (실제 검색)</a>
    <a href="#repro">02 재현 실험 — 12-2 스킵월 모멘텀</a>
    <a href="#perm">03 통계적 유의성(순열검정)</a>
    <a href="#synthesis">04 내부-외부 대조 종합</a>
    <a href="#limitations">05 한계</a>
  </nav>

  <section class="section" id="scope">
    <h2><span class="sec-no">00</span> 오늘의 주제 선정</h2>
    <p class="lede"><code>analysis/LATEST_STRATEGY_CANDIDATE.md</code>가 아직 존재하지 않아(D의
      최신 후보 없음), 지시에 따라 대기하지 않고
      <code>analysis/2026-09-05_research_program_synthesis/report_data.json</code>의
      <code>confidence_table</code>에서 아직 외부 문헌과 대조된 적 없는 두 항목을 골랐다:</p>
    <ul>
      <li><b>모멘텀 랭킹 방식(12개월 트레일링, 원시가격모멘텀)</b> - grade: moderate</li>
      <li><b>위험조정(변동성조정) 모멘텀 랭킹</b> - grade: reversed (raw가 이김)</li>
    </ul>
    <p>두 항목은 실제로 같은 스크립트(<code>analysis/2026-08-30_risk_adjusted_momentum_ranking/</code>)
      한 곳에서 함께 나온 결론이라 하나의 주제로 묶어 다뤘다.</p>
  </section>

  <section class="section" id="lit">
    <h2><span class="sec-no">01</span> 문헌 서베이 (실제 웹검색 수행)</h2>
    <p class="lede">아래 7편은 이번 실행에서 실제로 웹검색으로 찾아 원문/초록을 확인했다(기억에
      의존한 인용 없음). 2026-08-30 리포트가 이미 Barroso&amp;Santa-Clara(2015)와
      Daniel&amp;Moskowitz(2016)를 인용했었는데, 이번에 다시 검색해 두 논문의 저널·권호·핵심
      결과가 정확히 일치함을 확인했다 - 다만 그 리포트는 실시간 검색 여부가 불명확했으므로, 이번
      대조에서 독립적으로 재확인한 것으로 취급한다.</p>
    <ul class="src-list">{src_list()}</ul>
  </section>

  <section class="section" id="repro">
    <h2><span class="sec-no">02</span> 재현 실험 — Jegadeesh-Titman/Novy-Marx "12-2" 스킵월 모멘텀</h2>
    <p class="lede">이 챔피언은 지금까지 <code>MOMENTUM_WINDOW=252</code>(스킵 없는 순수 12개월
      트레일링)로만 랭킹해 왔다 - 룩백 길이 자체는 H27(작업40, 3~18개월)이 스윕했지만 "가장 최근
      1개월을 신호에서 뺄지"는 이 프로그램에서 한 번도 시도되지 않았다. Jegadeesh&amp;Titman(1993)
      이 쓰기 시작해 Novy-Marx(2012)가 명시적으로 재확인한 "12-2" 관행(t-12~t-1개월 구간만 쓰고
      가장 최근 1개월 제외 - 단기 반전 노이즈 제거)을 <code>skip_month_momentum.py</code>로
      구현해(<code>core/champion_strategy.py</code> 계열 함수·챔피언 유니버스·비용·시장필터는
      그대로 재사용, 랭킹 신호만 21거래일 시프트) 동일 6개 구간에서 raw(스킵없음)와 비교했다.</p>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>창</th><th>랭킹 신호</th><th>Sharpe</th><th>CAGR</th><th>MDD</th><th>Calmar</th><th>Δ Sharpe(vs raw)</th></tr></thead>
        <tbody>{variant_table(EP_ORDER)}</tbody>
      </table>
    </div>
    <p class="caveat">빨간 배경 행 = 12-2 스킵월이 raw 대비 Sharpe 0.15 이상 악화된 경우. 초록 배경
      행 = raw 자체(비교 기준선). 위험조정(12m)/Sortino류/위험조정(3m변동성) 세 행은 새로 계산하지
      않고 2026-08-30 report_data.json을 그대로 인용했다(재탕 검증이 아니라 같은 표 안에서 문헌
      비교를 위해 나란히 두기 위함).</p>
    <div class="callout warn">
      <div class="callout-title">문헌과 정반대 방향: 12-2 스킵월이 특히 COVID에서 크게 진다</div>
      <p>전체기간 2019-2026에서 raw Sharpe {fnum(FULL_RAW['sharpe'],2)}(CAGR {fnum(FULL_RAW['cagr'],1)}%)
        대 12-2 스킵월 Sharpe {fnum(FULL_SKIP['sharpe'],2)}(CAGR {fnum(FULL_SKIP['cagr'],1)}%) -
        스킵월이 raw보다 못하다. 가장 극적인 반례는 COVID 2020: raw Sharpe
        {fnum(COVID_RAW['sharpe'],2)}(CAGR {fnum(COVID_RAW['cagr'],1)}%)인데 12-2 스킵월은 Sharpe
        {fnum(COVID_SKIP['sharpe'],2)}(CAGR {fnum(COVID_SKIP['cagr'],1)}%)로 이미 기각된
        위험조정(12m) 변형(Sharpe {fnum(COVID_VS['sharpe'],2)})보다도 훨씬 나쁘다 - 6개 창×5개
        변형을 통틀어 이번에 나온 가장 나쁜 숫자다. 유일한 예외는 2015-16 조정(raw Sharpe
        {fnum(CORR_RAW['sharpe'],2)} vs 스킵월 {fnum(CORR_SKIP['sharpe'],2)})으로, 여기서만
        스킵월이 근소하게 앞섰다.</p>
    </div>
  </section>

  <section class="section" id="perm">
    <h2><span class="sec-no">03</span> 통계적 유의성 — 순열검정</h2>
    <p class="lede"><code>core.backtest_engine._shuffle_daily_bars</code>를 코드 그대로 재사용해
      17개 자산+SPY를 각각 독립적으로 캔들 순서만 섞은 가짜 시계열 {N_PERM}회를 만들고, "raw 대비
      12-2 스킵월의 Sharpe 격차"의 귀무분포를 전체기간 2019-2026에서 구했다(2026-08-30 스크립트와
      동일 방법론).</p>
    <div class="kpi-row">
      <div class="kpi-tile"><div class="kpi-label">실측 격차(스킵월−raw, Sharpe)</div>
        <div class="kpi-value neg">{fnum(EDGE_ACTUAL,3,signed=True)}</div>
        <div class="kpi-sub">raw={fnum(PERM['actual_sharpe_raw'],2)}, 스킵월={fnum(PERM['actual_sharpe_skip1m'],2)}</div></div>
      <div class="kpi-tile"><div class="kpi-label">순열 {N_PERM}회 격차 평균±표준편차</div>
        <div class="kpi-value">{fnum(EDGE_MEAN,3,signed=True)} ± {fnum(EDGE_STD,3)}</div>
        <div class="kpi-sub">노이즈만으로도 이 정도 폭의 격차가 흔함</div></div>
      <div class="kpi-tile"><div class="kpi-label">p-value (격차 기준)</div>
        <div class="kpi-value">{fnum(P_EDGE,4)}</div>
        <div class="kpi-sub">백분위 {fnum(PCTL_EDGE,1)}% — 통계적으로 유의하지 않음</div></div>
    </div>
    <div class="callout">
      <div class="callout-title">해석: 전체기간 손실 자체는 노이즈 대역 안</div>
      <p>실측 격차 {fnum(EDGE_ACTUAL,3,signed=True)}는 순열분포 평균 {fnum(EDGE_MEAN,3,signed=True)}
        ±{fnum(EDGE_STD,3)}에 비춰보면 p={fnum(P_EDGE,4)}(백분위 {fnum(PCTL_EDGE,1)}%)로, 통상 기준
        (p&lt;0.10)에 못 미친다 - "전체기간에서 스킵월이 raw보다 나쁘다"는 관찰조차 이 정도 표본
        (약 7년)으로는 확신을 갖고 말하기 어렵다. 하지만 이 p-value는 <b>전체기간 하나의 숫자</b>에
        대한 것이고, COVID 5주 구간 자체의 극단적 격차(Sharpe {fnum(COVID_SKIP['sharpe']-COVID_RAW['sharpe'],2,signed=True)})는
        순열검정 대상이 아니었다 - 표본이 5주뿐이라 별도 순열검정을 걸기엔 너무 짧다(아래 05절
        한계).</p>
    </div>
  </section>

  <section class="section" id="synthesis">
    <h2><span class="sec-no">04</span> 내부-외부 대조 종합</h2>
    <p><span class="verdict-badge v-partial">부분 일치</span> 원시수익 랭킹이 절대성과(CAGR/누적수익)에서
      위험조정 변형들을 이긴다는 이 저장소의 결론은 Rachev et al.(2007)의 "원시누적수익 랭킹이
      절대수익은 가장 크다"는 결과와 방향이 같다. 하지만 Rachev et al.은 <i>독립적인 위험조정
      성과지표에서는 보상위험비율 랭킹이 더 우수하다</i>고 결론짓는 반면, 이 저장소는 raw가 Sharpe·
      Calmar에서도 위험조정 변형을 이겼다(전체기간 Sharpe raw {fnum(FULL_RAW['sharpe'],2)} vs
      위험조정 {fnum(FULL_VS['sharpe'],2)}) - 이 지점은 완전히 갈린다. 갈리는 이유로 가장 설득력
      있는 건 유니버스 차이다: Rachev et al.은 S&amp;P500 517개 개별종목의 십분위 포트폴리오(넓은
      횡단면, 종목별 변동성과 모멘텀이 상당히 독립적)를 다루는 반면, 이 챔피언은 17개 자산군
      ETF(상당수가 지수 자체이거나 지수와 고상관) 중 top4만 뽑는 좁고 이산적인 구조라, "변동성으로
      나눈다"는 조작이 오히려 "가장 강하게, 가장 오래 추세를 탄 자산(주로 기술주 섹터 등)"의 순위를
      기계적으로 깎아내리는 부작용이 표본 크기 대비 훨씬 크게 작용한다.</p>
    <p><span class="verdict-badge v-reject">불일치(메커니즘 설명 가능)</span> Barroso&amp;
      Santa-Clara(2015)/Moreira&amp;Muir(2017)의 "변동성 관리가 모멘텀 Sharpe를 크게 개선한다"는
      핵심 결과는 이 챔피언에서 재현되지 않는데, 이는 원 논문 기각이 아니라 <b>적용 층위가 다르기
      때문</b>이다 - 원 논문은 이미 선정된 모멘텀 <i>포트폴리오의 노출 크기</i>(레버리지 상향 허용)를
      스케일링하는 반면, 2026-08-30 스크립트와 이번 대조 모두 <i>랭킹(누구를 살지)</i>에 같은 비율을
      썼다. 이 저장소가 실제로 노출 크기 층위에서 시도한 것(H28/H34, "변동성 타겟팅 오버레이" -
      20일 실현변동성 목표 18%, cap=1.0 즉 레버리지 상향 없이 축소만 허용)도 부트스트랩 결합전파에서
      49.7%(동전던지기)로 무너졌다(confidence_table "reversed" 등급) - 이 결과는 오히려
      Cederburg et al.(2020)의 비판(실시간 구현 가능한 변동성관리 포트폴리오는 대체로 무관리
      포트폴리오를 못 이긴다)과 정확히 같은 방향이다. 즉 "변동성 관리가 이 챔피언에서 안 먹힌다"는
      두 번(랭킹 층위·노출 층위)의 독립적 관측이, 최초 논문(2015/2017)보다 더 최근의, 더 엄격한
      비판 논문(2020)과 일치한다는 뜻 - 이 저장소의 회의론이 학계 안에서도 소수 의견이 아니다.</p>
    <p><span class="verdict-badge v-reject">불일치(신규 반례)</span> Jegadeesh&amp;Titman(1993)/
      Novy-Marx(2012)의 "가장 최근 1개월을 제외하면 모멘텀이 개선된다"는 관행은 이번 재현에서
      뒤집혔다 - 특히 COVID 2020에서 스킵월이 이번 대조 전체를 통틀어 가장 나쁜 결과(CAGR
      {fnum(COVID_SKIP['cagr'],1)}%)를 냈다. 메커니즘: Novy-Marx의 결과는 수십 년 표본에 걸친
      <i>평균</i> 효과이고, 단기 반전 노이즈를 걸러내는 게 대체로 이득이라는 전제다. 하지만 COVID처럼
      수직급락이 한 달 안에 일어나는 구간에서는 "가장 최근 1개월"이 노이즈가 아니라 <i>가장 중요한
      새 정보(위기의 시작)</i> 그 자체다 - 이를 일부러 제외하면 신호가 위기 발생을 최소 한 달 늦게
      알아채는 셈이 된다. 이는 confidence_table의 다른 항목("이진 시장필터... COVID에선 크게 짐 -
      느린 신호가 수직급락을 못 잡음")과 정확히 같은 패턴이 세 번째로(시장필터, 새틀라이트 위기신호,
      이제 모멘텀 스킵월까지) 반복된 것 - "느리게 반응하도록 설계된 신호는 전부 COVID형 수직급락에
      취약하다"는 이 저장소의 반복 관측이 학술 관행(12-2)에도 예외 없이 적용됨을 보여준다.</p>
  </section>

  <section class="section" id="limitations">
    <h2><span class="sec-no">05</span> 한계</h2>
    <ul>
      <li>12-2 스킵월 vs raw 순열검정은 전체기간 2019-2026 하나에만 적용했다 - COVID 5주 구간
        자체는 표본이 너무 짧아(약 35거래일) 독립적인 순열검정을 걸 수 없었다. COVID에서 관측된
        극단적 격차가 이 특정 6년 표본의 우연(단 한 번의 리밸런싱 타이밍 차이)인지, 구조적으로
        재현 가능한지는 추가 위기 구간(예: 2020년과 유사한 급락-급반등 패턴을 가진 다른 시장/시대)
        없이는 확정할 수 없다.</li>
      <li>Barroso&amp;Santa-Clara/Moreira&amp;Muir의 "노출 크기 스케일링"을 이 챔피언의 롱온리·
        동일가중 top4 구조에 원문 그대로(레버리지 상향 허용) 재현하지는 않았다 - H28/H34가 이미
        cap=1.0(레버리지 상향 없음)로 근접한 버전을 시도해 실패했으므로 우선순위를 낮췄지만, cap을
        1.0 이상으로 푼 버전은 여전히 미시도 상태로 남아있다.</li>
      <li>Rachev et al.(2007)의 "보상위험비율이 독립적 위험조정 성과지표에서 낫다"는 결론을 검증한
        "독립적 성과지표"가 논문마다 다르게 정의되므로(STARR/R-ratio 등), 이 리포트의 Sharpe/Calmar
        비교와 완전히 같은 잣대로 비교한 것은 아니다 - 정성적 방향 비교로 한정해서 읽어야 한다.</li>
      <li>절대모멘텀 게이트(진입 여부)는 신호 종류와 무관하게 항상 raw(스킵없는) 12개월 부호로
        고정했다 - 스킵월 신호의 부호로 게이트까지 바꾸는 완전한 12-2 구현은 시도하지 않았다.</li>
    </ul>
  </section>

</div>

<footer>
  <p>QUANT RESEARCH · 리서치 에이전트 H(학술 문헌/외부 벤치마크) · 모멘텀 랭킹 문헌 대조 + 12-2
    스킵월 재현({N_PERM}회 순열검정 포함) · 이 문서는 투자 조언이 아니며 저자 개인의 연구 기록입니다.</p>
</footer>
"""

with open(f"{OUT_DIR}/final_report.html", "w", encoding="utf-8") as f:
    f.write(HTML)
print("[build_report] saved final_report.html")
