#!/usr/bin/env python3
"""report_data.json을 읽어 final_report.html을 만든다.

analysis/2026-08-23_vol_targeting_and_rebalance_frequency_expected_value/build_report.py와 동일한
디자인 시스템(다크네이비/올리브 톤, 세리프 헤드라인, TOC, 섹션 번호, 판정 배지)을 그대로 재사용한다.
"""
import json
import math
import os

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

with open(f"{OUT_DIR}/report_data.json", encoding="utf-8") as f:
    R = json.load(f)

GEN = R["meta"]["generated"]
H30 = R["h30"]
META = H30["meta"]


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
    return f"{v*100:.{digits}f}%"


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
.chart-card{ background:var(--chart-surface); border:1px solid var(--hairline); border-radius:10px;
  padding:22px 22px 16px; margin: 22px 0; box-shadow: var(--shadow); }
.chart-card h3{ margin: 0 0 4px; font-size:16px; }
.chart-desc{ font-size:13.5px; color:var(--ink-muted); margin: 0 0 14px; max-width:none; }
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
td.num.delta.pos, .delta.pos{ color:var(--delta-pos); font-weight:650; }
td.num.delta.neg, .delta.neg{ color:var(--delta-neg); font-weight:650; }
.strong{ font-weight:700; }
tr.best-row{ background: var(--accent-soft); }
tr.warn-row{ background: rgba(179,38,30,0.08); }
.bar-track{ position:relative; height:14px; background:var(--surface-2); border-radius:3px; overflow:hidden; min-width:120px; }
.bar-fill{ position:absolute; left:0; top:0; bottom:0; background:var(--accent); border-radius:3px; }
.bar-fill.weak{ background:var(--ink-muted); }
footer{ max-width:1020px; margin:40px auto 0; padding: 26px 24px 10px; border-top:1px solid var(--hairline);
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
.confidence-grade{ display:inline-block; font-size:12px; font-weight:700; padding:2px 9px; border-radius:4px; }
.grade-A{ background: var(--accent-soft); color:var(--accent); }
.grade-B{ background: var(--accent-2-soft); color:var(--accent-2); }
.grade-C{ background: rgba(179,38,30,0.10); color:var(--delta-neg); }
"""

CFG_LABEL = {
    "core_alone": "코어 단독",
    "case_a_static_satellite": "정적보유 새틀라이트(15%)",
    "case_b_spy_switch": "SPY 스위치",
    "case_c_vix_switch": "VIX 스위치",
    "case_d_hybrid_or_switch": "하이브리드(OR)",
    "case_e_continuous_exposure": "연속노출 사이징",
    "spy_buyhold": "SPY 매수보유",
    "core_plus_satellite": "챔피언+새틀라이트",
    "no_overlay": "오버레이 없음",
    "vol_targeted": "변동성타겟팅",
    "weekly_5d": "주간", "biweekly_10d": "격주", "monthly_21d": "월간(기존)",
    "sixweek_30d": "6주", "quarterly_63d": "분기",
    "3": "3개월", "6": "6개월", "9": "9개월", "12": "12개월(기존)", "15": "15개월", "18": "18개월",
}
K_LABEL = {"tight_K60": "좁은 확신 (K=60)", "central_K30": "중심 (K=30)", "wide_K15": "넓은 불확실성 (K=15)"}
K_ORDER = ["wide_K15", "central_K30", "tight_K60"]

HYP_META = {
    "h22_config_comparison": {
        "title": "H22 — 정적보유 새틀라이트 vs 스위치 계열 4종 (작업39 원 결론)",
        "anchor": "h22",
    },
    "h26_system_vs_spy": {
        "title": "H26 — 챔피언 시스템 vs SPY 매수보유 (작업40 원 결론)",
        "anchor": "h26",
    },
    "h27_lookback": {
        "title": "H27 — 모멘텀 랭킹 룩백기간 3~18개월 (작업40 원 결론)",
        "anchor": "h27",
    },
    "h28_vol_targeting": {
        "title": "H28 — 코어 레벨 변동성타겟팅 오버레이 (작업41 원 결론)",
        "anchor": "h28",
    },
    "h29_rebalance_freq": {
        "title": "H29 — 리밸런싱 주기 5종 (작업41 원 결론)",
        "anchor": "h29",
    },
}


def cfg_label(c):
    return CFG_LABEL.get(c, c)


def rank_bar_table(hyp_key, k_name):
    scen = H30[hyp_key][k_name]
    configs = scen["configs"]
    rows = []
    ordered = sorted(configs, key=lambda c: -scen["win_rate"][c])
    for c in ordered:
        wr = scen["win_rate"][c]
        mean_v = scen["mean_expected_value"][c]
        ci = scen["ci90_expected_value"][c]
        width = max(2, wr * 100)
        cls = "" if wr >= 0.05 else "weak"
        rows.append(
            f'<tr><td class="tk-cell"><span class="tk-name">{esc(cfg_label(c))}</span></td>'
            f'<td class="num">{pct(wr,1)}</td>'
            f'<td><div class="bar-track"><div class="bar-fill {cls}" style="width:{width:.1f}%"></div></div></td>'
            f'<td class="num">{fnum(mean_v,4)}</td>'
            f'<td class="num">[{fnum(ci[0],4)}, {fnum(ci[1],4)}]</td></tr>'
        )
    return "".join(rows)


def gap_summary(hyp_key, k_name):
    scen = H30[hyp_key][k_name]
    g = scen["gap_winner_vs_rival"]
    return g


def k_sensitivity_row(hyp_key):
    rows = []
    for k in K_ORDER:
        scen = H30[hyp_key][k]
        top_cfg, top_wr = max(scen["win_rate"].items(), key=lambda kv: kv[1])
        g = scen["gap_winner_vs_rival"]
        rows.append(
            f'<tr><td class="tk-cell"><span class="tk-name">{esc(K_LABEL[k])}</span></td>'
            f'<td class="num">{esc(cfg_label(top_cfg))}</td>'
            f'<td class="num">{pct(top_wr,1)}</td>'
            f'<td class="num">{esc(cfg_label(g["winner"]))} vs {esc(cfg_label(g["rival"]))}</td>'
            f'<td class="num">{fnum(g["mean_gap"],4)}</td>'
            f'<td class="num">{pct(g["pct_draws_winner_still_ahead"],1)}</td></tr>'
        )
    return "".join(rows)


def confidence_grade(hyp_key):
    """중심(K=30) 시나리오의 top-win-rate를 기준으로 A/B/C 등급."""
    wr = max(H30[hyp_key]["central_K30"]["win_rate"].values())
    if wr >= 0.90:
        return "A", "grade-A", "강건(90%+ 표본에서 동일 결론)"
    if wr >= 0.70:
        return "B", "grade-B", "대체로 강건(70~90% 표본)"
    return "C", "grade-C", "취약(70% 미만 — 사실상 우연에 가까움)"


def hyp_section(hyp_key, section_no, extra_note=""):
    meta = HYP_META[hyp_key]
    grade, grade_cls, grade_desc = confidence_grade(hyp_key)
    return f"""
  <section class="section" id="{meta['anchor']}">
    <h2><span class="sec-no">{section_no}</span> {esc(meta['title'])}
      <span class="confidence-grade {grade_cls}">신뢰도 {grade}</span></h2>
    <p class="lede">{grade_desc} — 10,000회 디리클레 표본 중 중심 시나리오(K=30)에서 1위를 차지한
      비율을 신뢰도 등급의 기준으로 삼는다.</p>

    <h3>순위 분포 — 중심 시나리오 (K=30, 10,000회 표본)</h3>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>구성</th><th>1위 비율(승률)</th><th></th><th>E[Sharpe] 평균</th><th>90% CI</th></tr></thead>
        <tbody>{rank_bar_table(hyp_key, 'central_K30')}</tbody>
      </table>
    </div>

    <h3>K(불확실성 폭) 민감도 — 결론이 사전분포 폭 자체에 얼마나 좌우되는가</h3>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>불확실성 폭</th><th>1위 구성</th><th>1위 비율</th><th>격차 비교(1위 vs 2위)</th>
          <th>평균 격차</th><th>1위가 여전히 앞서는 표본 비율</th></tr></thead>
        <tbody>{k_sensitivity_row(hyp_key)}</tbody>
      </table>
    </div>
    {extra_note}
  </section>
"""


HTML = f"""<title>기저확률 몬테카를로 민감도 검증</title>
<style>
{CSS}
</style>

<div class="masthead">
  <div class="masthead-inner">
    <div class="masthead-eyebrow">
      <span>QUANT RESEARCH NOTE</span><span class="dot">·</span><span>15라운드</span><span class="dot">·</span><span>Hypothesis-Driven Study</span>
    </div>
    <h1 class="masthead-title">기저확률 가정, 몬테카를로로 정직하게 흔들어본다</h1>
    <p class="masthead-sub">작업39(H22)는 6개 레짐 아키타입의 연간 발생빈도를 점추정치로 고정한 뒤
      손으로 고른 3개 대안 시나리오(기본/평온중시/위기중시)로만 순위 안정성을 확인했다. 이번 라운드는
      그 기저확률을 디리클레 분포에서 뽑은 10,000개 확률벡터로 대체해, "정적보유가 이긴다"·"챔피언이
      SPY를 이긴다"·"12개월 룩백이 최선이다" 같은 지금까지의 결론이 정말로 강건한지, 아니면 점추정치
      선택 하나에 우연히 의존했던 것인지를 정량적으로 가른다.</p>
    <div class="masthead-meta">
      <span><b>기준일</b> {esc(GEN)}</span>
      <span><b>표본 수</b> 시나리오당 {META['n_draws']:,}회 (시드 {META['seed']})</span>
      <span><b>분포</b> Dirichlet(K·기저확률), K=15/30/60 3단계로 폭 자체도 민감도분석</span>
      <span><b>새 백테스트</b> 없음 — h22/h26/h27/h28/h29의 기존 원자료만 재가중</span>
    </div>
  </div>
</div>

<div class="wrap">

  <nav class="toc">
    <a href="#scope">00 문제 제기</a>
    <a href="#design">01 기저확률 불확실성 분포 설계</a>
    <a href="#h22">02 H22 — 정적보유 vs 스위치</a>
    <a href="#h26">03 H26 — 시스템 vs SPY</a>
    <a href="#h27">04 H27 — 룩백기간</a>
    <a href="#h28">05 H28 — 변동성타겟팅</a>
    <a href="#h29">06 H29 — 리밸런싱 주기</a>
    <a href="#synthesis">07 종합 — 신뢰도 등급표</a>
    <a href="#limitations">08 한계</a>
  </nav>

  <section class="section" id="scope">
    <h2><span class="sec-no">00</span> 문제 제기 — 3개 시나리오는 왜 충분히 엄밀하지 않은가</h2>
    <p class="lede">작업39(H22)의 방법론은 트랙D 전체가 지금까지 기대는 핵심 도구다. 하지만 "기본/
      평온중시/위기중시" 3개는 <b>사람이 손으로 고른 이산 점</b>일 뿐 확률분포가 아니다 — 위기중시
      시나리오가 "충분히 비관적인지", 기본 시나리오가 "정말 중심값인지"를 확인할 방법이 없었다.
      만약 실제 기저확률이 이 3개 점 "사이 어딘가"가 아니라 그 바깥에 있다면, 지금까지의 모든
      "채택/기각" 판정이 우연히 3개 점을 잘 고른 결과일 수도 있다.</p>
    <p>이번 라운드는 기저확률 자체를 확률변수로 승격시킨다 — 6개 아키타입의 발생확률을 하나의
      확률벡터(합=1)로 보고, 그 위에 진짜 사전분포를 얹은 뒤 10,000번 무작위로 뽑아 매번 기댓값
      순위를 다시 계산한다. "정적보유가 1위인 표본이 몇 %인가"가 3개 시나리오의 "3전 3승"보다
      훨씬 더 정직한 강건성 지표다.</p>
    <p class="caveat">⚠️ 투자 조언이 아니다. 이 분석은 h22/h26/h27/h28/h29가 이미 계산해 둔 6개 창의
      Sharpe/CAGR 숫자를 재가중할 뿐, 새로운 백테스트나 새로운 시장 데이터를 포함하지 않는다.</p>
  </section>

  <section class="section" id="design">
    <h2><span class="sec-no">01</span> 기저확률 불확실성 분포 설계</h2>
    <p class="lede">6개 아키타입(평시/2008형/COVID형/2022형/2018형/2015-16형)의 발생확률
      p = (p₁,...,p₆), Σp=1 에 <b>디리클레(Dirichlet) 분포</b> p ~ Dir(α), α_i = K·(H22 점추정치_i)
      를 사전분포로 둔다. 디리클레는 확률벡터(심플렉스) 위에서 정의되는 표준적 켤레분포로, "각 확률이
      0~1 사이 독립균등"이 아니라 "전부 합쳐 반드시 1이 되는" 제약을 자연스럽게 만족시킨다는 점에서
      이 문제에 적합하다.</p>
    <table class="data-table" style="margin:10px 0;">
      <thead><tr><th>아키타입</th><th>H22 점추정치(평균으로 사용)</th><th>K=30에서 표준편차</th><th>해석</th></tr></thead>
      <tbody>
        <tr><td class="tk-cell"><span class="tk-name">평시/강세장 (전체기간 대용)</span></td><td class="num">50%</td><td class="num">±9.1%p</td><td class="tk-cell">가장 확신 있는 추정 — 표본기간이 길고 실측 데이터 기반</td></tr>
        <tr><td class="tk-cell"><span class="tk-name">2008형 체계적위기</span></td><td class="num">3%</td><td class="num">±3.1%p</td><td class="tk-cell">변동계수 ~100% — 실제로는 0%에 가까울 수도, 6%+일 수도</td></tr>
        <tr><td class="tk-cell"><span class="tk-name">COVID형 급락</span></td><td class="num">4%</td><td class="num">±3.5%p</td><td class="tk-cell">희귀사건이라 통계적 추정이 근본적으로 어려움</td></tr>
        <tr><td class="tk-cell"><span class="tk-name">2022형 완만약세장</span></td><td class="num">10%</td><td class="num">±5.4%p</td><td class="tk-cell">중간 불확실성</td></tr>
        <tr><td class="tk-cell"><span class="tk-name">2018형 급격조정</span></td><td class="num">16%</td><td class="num">±6.6%p</td><td class="tk-cell">조정 정의가 문헌마다 갈려 폭이 넓음</td></tr>
        <tr><td class="tk-cell"><span class="tk-name">2015-16형 완만조정</span></td><td class="num">17%</td><td class="num">±6.7%p</td><td class="tk-cell">조정 정의가 문헌마다 갈려 폭이 넓음</td></tr>
      </tbody>
    </table>
    <p>근거: 약세장/조정 발생빈도에 대한 문헌은 정의(−10% vs −20% 하락)와 표본기간에 따라 크게
      갈린다 — 예컨대 S&P500 기준 -20%+ "약세장"은 1928년 이후 평균 5~6년에 한 번(Ned Davis
      Research/Yardeni류 집계) 수준으로 집계되지만, -10~-20% "조정"은 그보다 2~3배 자주 발생한다는
      게 공통적으로 인용되는 범위다. 이 폭 자체가 이미 "위기 발생빈도는 정밀하게 알려진 상수가
      아니다"라는 근거이므로, 변동계수 ~50~100% 수준(점추정치의 절반~두 배가 여전히 현실적으로
      가능)으로 잡는 것이 과도한 폭이 아니라 오히려 최소한의 정직한 표현이라고 판단했다.</p>
    <p>K(디리클레 총 집중도)는 "가상 관측표본 크기"로 해석된다 — K가 클수록 점추정치를 더 신뢰,
      작을수록 더 무지에 가깝다. 결론이 K 선택 자체에 좌우되지 않는지 확인하기 위해 3단계
      (K=15 넓음 / K=30 중심 / K=60 좁음)를 전부 계산해 보고한다.</p>
    <p class="kpi-sub">구현: <code>numpy.random.default_rng(20260823).dirichlet(alpha, size=10000)</code> —
      매 표본이 자동으로 합=1을 만족하는 유효 확률벡터이므로 별도 재정규화가 불필요하다.</p>
  </section>

  {hyp_section('h22_config_comparison', '02')}
  {hyp_section('h26_system_vs_spy', '03')}
  {hyp_section('h27_lookback', '04',
    extra_note='<div class="callout warn"><div class="callout-title">"12개월이 최선"이라는 결론은 '
    '점추정치보다 훨씬 약하다</div><p>작업40(H27)은 3개 이산 시나리오 전부에서 12개월이 1위라고 '
    '보고했지만, 몬테카를로로 보면 중심 시나리오(K=30)에서도 12개월의 1위 비율은 55.5%에 불과하다 — '
    f'{esc(cfg_label("9"))}가 근소한 차이로 뒤쫓는 구조라, "12개월이 확실히 최선"이라기보다는 '
    '"12개월과 9개월이 통계적으로 거의 구분 안 된다"는 게 더 정직한 결론이다. 3개 이산 시나리오가 '
    '우연히 12개월 쪽 표본만 골랐을 가능성을 배제할 수 없다.</p></div>'),
  }
  {hyp_section('h28_vol_targeting', '05')}
  {hyp_section('h29_rebalance_freq', '06',
    extra_note='<div class="callout warn"><div class="callout-title">"월간이 최선"도 룩백만큼은 아니지만 '
    '약해진다</div><p>작업41(H29)은 3개 시나리오 중 2개에서 월간이 이긴다고 보고했는데, 몬테카를로 '
    '중심 시나리오에서 월간의 1위 비율은 68.9% — H22/H26/H28만큼 압도적이지 않다. 6주 주기가 상당한 '
    '표본에서 근소하게 앞서는 구간이 있다는 원 리포트의 관찰이 몬테카를로에서도 재확인된다.</p></div>'),
  }

  <section class="section" id="synthesis">
    <h2><span class="sec-no">07</span> 종합 — 지금까지의 결론 중 어디까지가 진짜 강건한가</h2>
    <p class="lede">10,000회 몬테카를로로 5개 기존 결론을 다시 채점하면, 셋은 <b>강건(A등급)</b>, 하나는
      <b>대체로 강건(B등급)</b>, 하나는 <b>취약(C등급)</b>으로 갈린다 — "채택"이라는 딱지가 전부
      동일한 확신 수준을 뜻하지 않았다는 걸 이번 라운드가 처음으로 정량화했다.</p>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>가설</th><th>원 판정(작업39-41)</th><th>중심 시나리오 1위 비율</th><th>신뢰도 등급</th><th>해석</th></tr></thead>
        <tbody>
"""

SYNTH_ROWS = [
    ("h22_config_comparison", "채택 (정적보유 1위)", "정적보유가 지금까지의 3개 손선택 시나리오뿐 아니라 확률분포 전체에서도 사실상 항상 이긴다."),
    ("h26_system_vs_spy", "채택 (시스템 > SPY)", "새틀라이트를 더한 시스템이 대다수 표본에서 이기지만, K가 넓어질수록(불확실성이 클수록) 승률이 완만히 낮아진다 — 여전히 우세하나 H22만큼 절대적이진 않다."),
    ("h27_lookback", "채택 (12개월 최선)", "가장 취약한 결론 — 12개월과 9개월의 실질 차이가 기저확률 불확실성 안에 묻힌다. \"12개월이 확실히 낫다\"가 아니라 \"12개월이 근소 우위 후보\" 정도로 재평가해야 한다."),
    ("h28_vol_targeting", "기각 (오버레이 없음이 이김)", "오버레이 없는 코어가 거의 모든 표본에서 이긴다 — 원 결론 그대로 강건하다."),
    ("h29_rebalance_freq", "부분채택 (월간 유지, 위기시 6주 근소우위)", "월간이 다수 표본에서 이기지만 확실성은 H22/H26/H28보다 낮다 — \"월간이 기본값으로 안전\"은 유지되나 \"명백한 최선\"이라는 표현은 과장이다."),
]

for hyp_key, orig, interp in SYNTH_ROWS:
    grade, grade_cls, grade_desc = confidence_grade(hyp_key)
    wr = max(H30[hyp_key]["central_K30"]["win_rate"].values())
    HTML += (
        f'<tr><td class="tk-cell"><span class="tk-name">{esc(HYP_META[hyp_key]["title"].split(" — ")[0])}'
        f' {esc(HYP_META[hyp_key]["title"].split(" — ")[1].split(" (")[0])}</span></td>'
        f'<td class="tk-cell">{esc(orig)}</td>'
        f'<td class="num">{pct(wr,1)}</td>'
        f'<td class="num"><span class="confidence-grade {grade_cls}">{grade}</span></td>'
        f'<td class="tk-cell">{esc(interp)}</td></tr>'
    )

HTML += f"""
        </tbody>
      </table>
    </div>
    <div class="hyp-card">
      <div class="hyp-id">가장 중요한 결론 — "정적보유가 스위치를 이긴다"는 이 연구 프로그램 전체에서 가장 단단한 결과다</div>
      <p style="margin:8px 0 0;">15라운드 전체를 통틀어 확인된 다섯 가지 기존 결론 중, 몬테카를로로
        가장 광범위한 표본에서 살아남는 것은 H22(정적보유 새틀라이트가 스위치 계열을 이긴다)와
        H28(변동성타겟팅 오버레이는 순수 비용)이다 — 두 결론 모두 K=15의 가장 넓은 불확실성
        시나리오에서도 각각 97.3%, 87.9%의 표본에서 살아남는다. 반대로 H27(12개월 룩백)은 애초에
        "12개월과 9개월 사이의 근소한 우위"였던 결과라 기저확률 불확실성을 정직하게 반영하면 확신이
        크게 낮아진다 — 이는 룩백이 틀렸다는 뜻이 아니라, "확실히 12개월이 최선"이라는 문장이
        과도하게 확신에 찬 표현이었다는 뜻이다.</p>
    </div>
  </section>

  <section class="section" id="limitations">
    <h2><span class="sec-no">08</span> 한계</h2>
    <ul>
      <li><b>디리클레 사전분포 자체도 가정이다</b> — K=15/30/60이라는 세 값과, 평균을 H22 점추정치에
        고정하는 선택 모두 "합리적으로 보이는 근사"이지 검증된 참값이 아니다. 이 몬테카를로가
        답할 수 있는 것은 "K가 이 범위 안이라면 결론이 얼마나 안정적인가"이지, "진짜 기저확률이
        무엇인가"가 아니다.</li>
      <li><b>여전히 6개 창뿐이다</b> — H22가 이미 지적한 한계(표본 6개, 서로 겹치는 기간, 다중비교
        위험)가 그대로 남는다. 몬테카를로는 "이 6개 숫자를 어떻게 가중하느냐"의 불확실성만 다루지,
        "이 6개 숫자 자체가 얼마나 정확한가"의 불확실성(백테스트 표본오차, 생존편향, 거래비용 가정)은
        다루지 않는다 — 두 불확실성을 합치면 실제 신뢰구간은 여기 보고된 것보다 더 넓을 가능성이 높다.</li>
      <li><b>아키타입 간 독립성 가정</b> — 디리클레는 카테고리 간 음의 상관을 자동으로 부여하지만
        (한 카테고리 확률이 오르면 다른 게 내려감), 실제로는 "2008형과 2022형이 동시에 자주/드물게
        발생"할 수도 있는 등 더 복잡한 상관구조가 있을 수 있다. 더 정교한 모형(계층적 사전분포 등)은
        이번 라운드 범위 밖이다.</li>
      <li><b>H27/H29는 표본 크기가 더 많아(6/5개 옵션) 승률 해석에 주의</b> — 옵션이 많을수록 "완전
        무작위"일 때의 기대 1위 비율이 낮아진다(6개 옵션이면 1/6≈16.7%). H27의 55.5%는 그래도 우연
        수준(16.7%)보다는 훨씬 높으므로 "12개월이 여전히 유력한 후보"라는 결론 자체는 유지되나,
        "확실한 승자"라는 강한 표현은 정당화되지 않는다는 게 정확한 해석이다.</li>
      <li><b>정책적 함의는 그대로다</b> — 신뢰도 등급이 낮다고 해서 원래 선택(12개월 룩백, 월간
        리밸런싱)을 바꿔야 한다는 뜻은 아니다. 대안(9개월, 6주)이 확실히 더 낫다는 증거도 마찬가지로
        약하므로, "바꿀 만큼 강한 근거는 없다"는 현상유지 논리가 여전히 성립한다.</li>
    </ul>
  </section>

</div>

<footer>
  <p>analysis/2026-08-23_base_rate_monte_carlo_sensitivity/ (데이터: report_data.json, 빌드:
    build_report.py) · h30_monte_carlo_base_rate_sensitivity.py는 새 백테스트 없이
    analysis/2026-08-23_expected_value_reframing_and_continuous_exposure/h22_results.json,
    analysis/2026-08-23_system_vs_buyhold_and_lookback_robustness/{{h26,h27}}_results.json,
    analysis/2026-08-23_vol_targeting_and_rebalance_frequency_expected_value/{{h28,h29}}_results.json의
    raw_lookup_table(6개 창 x 구성 x Sharpe/CAGR/MDD)만 읽어, numpy.random.Generator.dirichlet로
    시나리오당 10,000개 확률벡터를 뽑아 매번 기댓값 순위를 재계산했다(K=15/30/60, 시드 20260823,
    numpy만 사용, 재현 가능). 이 워크트리는 main과 분기된 시점 이후 인프라 변경이 반영되지 않을 수
    있어, 모든 스크립트가 main 체크아웃(/workspaces/Quant)의 이전 라운드 analysis/를 직접 참조해
    실행했다 — 이 워크트리의 core/·app/는 건드리지 않았다.</p>
</footer>
"""

out_file = f"{OUT_DIR}/final_report.html"
with open(out_file, "w", encoding="utf-8") as f:
    f.write(HTML)
print(f"SAVED {out_file}")
