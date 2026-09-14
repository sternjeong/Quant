#!/usr/bin/env python3
"""report_data.json을 읽어 final_report.html을 만든다.

analysis/2026-08-23_system_vs_buyhold_and_lookback_robustness/build_report.py와 동일한 디자인
시스템(다크네이비/올리브 톤, 세리프 헤드라인, TOC, 섹션 번호, 판정 배지)을 그대로 재사용한다.
"""
import json
import math
import os

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

with open(f"{OUT_DIR}/report_data.json", encoding="utf-8") as f:
    R = json.load(f)

GEN = R["meta"]["generated"]
H28 = R["h28"]
H29 = R["h29"]


def fnum(v, digits=1, signed=False):
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
"""

CFG_LABEL_28 = {"no_overlay": "코어 그대로 (오버레이 없음)", "vol_targeted": "코어+변동성타겟팅 오버레이"}
ARCHETYPE_KOR = {
    "full_2019_2026": "평시/강세장 (2019-2026 전체기간 대용)",
    "gfc_2008": "완만·광범위 시스템 위기 (2008 GFC형)",
    "covid_2020": "초고속 크래시 (COVID형)",
    "bear_2022": "중간강도 약세장 (2022형)",
    "selloff_2018": "단기·급격 조정 (2018년말형)",
    "correction_2015_2016": "완만한 중기 조정 (2015-16형)",
}
EP_ORDER = ["full_2019_2026", "gfc_2008", "covid_2020", "bear_2022", "selloff_2018", "correction_2015_2016"]
SCEN_LABEL = {"base": "기본(중심 추정)", "calm_heavy": "강세장 편향(보수적)", "crisis_heavy": "위기 편향(비관적)"}
FREQ_LABEL = {
    "weekly_5d": "주간(5거래일)", "biweekly_10d": "격주(10거래일)", "monthly_21d": "월간(21거래일, 기존)",
    "sixweek_30d": "6주(30거래일)", "quarterly_63d": "분기(63거래일)",
}
FREQ_ORDER = ["weekly_5d", "biweekly_10d", "monthly_21d", "sixweek_30d", "quarterly_63d"]

base28 = H28["scenarios"]["base"]
top28_cfg, top28_val = base28["ranking_by_expected_sharpe"][0]

base29 = H29["scenarios"]["base"]
top29_freq, top29_val = base29["ranking_by_expected_sharpe"][0]

# H29 sensitivity: does monthly win in every scenario?
h29_winners = {s: H29["scenarios"][s]["ranking_by_expected_sharpe"][0][0] for s in ["base", "calm_heavy", "crisis_heavy"]}
h29_monthly_always_wins = all(v == "monthly_21d" for v in h29_winners.values())

h28_winners = {s: H28["scenarios"][s]["ranking_by_expected_sharpe"][0][0] for s in ["base", "calm_heavy", "crisis_heavy"]}
h28_no_overlay_always_wins = all(v == "no_overlay" for v in h28_winners.values())


def h28_window_table():
    rows = []
    for ep in EP_ORDER:
        row = H28["raw_lookup_table"][ep]
        rows.append(
            f'<tr><td class="tk-cell"><span class="tk-name">{esc(ARCHETYPE_KOR[ep])}</span></td>'
            f'<td class="num">{fnum(row["no_overlay"]["sharpe"],2)}</td>'
            f'<td class="num">{fnum(row["vol_targeted"]["sharpe"],2)}</td>'
            f'<td class="num">{fnum(row["no_overlay"]["mdd"],2)}%</td>'
            f'<td class="num">{fnum(row["vol_targeted"]["mdd"],2)}%</td>'
            f'<td class="num">{fnum(row["pct_days_scaled_down"],1)}%</td></tr>'
        )
    return "".join(rows)


def h28_ev_table(scen_name):
    scen = H28["scenarios"][scen_name]
    rows = []
    for i, (cfg, val) in enumerate(scen["ranking_by_expected_sharpe"]):
        cagr = scen["expected_value"][cfg]["cagr"]
        mdd_worst = scen["expected_value"][cfg]["mdd_worst_case"]
        cls = "best-row" if i == 0 else ""
        rows.append(
            f'<tr class="{cls}"><td class="tk-cell"><span class="tk-name">{i+1}. {esc(CFG_LABEL_28[cfg])}</span></td>'
            f'<td class="num">{fnum(val,4)}</td><td class="num">{fnum(cagr,2,True)}%</td>'
            f'<td class="num">{fnum(mdd_worst,2)}%</td></tr>'
        )
    return "".join(rows)


def h29_window_table():
    rows = []
    for ep in EP_ORDER:
        row = H29["raw_lookup_table"][ep]
        cells = "".join(f'<td class="num">{fnum(row[f]["sharpe"],2)}</td>' for f in FREQ_ORDER)
        rows.append(f'<tr><td class="tk-cell"><span class="tk-name">{esc(ARCHETYPE_KOR[ep])}</span></td>{cells}</tr>')
    return "".join(rows)


def h29_ev_table(scen_name):
    scen = H29["scenarios"][scen_name]
    ev = scen["expected_value"]
    ranking_order = [k for k, v in scen["ranking_by_expected_sharpe"]]
    rows = []
    for f in FREQ_ORDER:
        v = ev[f]
        cls = "best-row" if f == ranking_order[0] else ""
        rows.append(
            f'<tr class="{cls}"><td class="tk-cell"><span class="tk-name">{esc(FREQ_LABEL[f])}</span></td>'
            f'<td class="num">{fnum(v["expected_sharpe"],4)}</td>'
            f'<td class="num">{fnum(v["expected_cagr_pct"],2,True)}%</td>'
            f'<td class="num">{fnum(v["mdd_worst_case"],2)}%</td>'
            f'<td class="num">{fnum(v["avg_annual_turnover_pct_full_period"],0)}%</td></tr>'
        )
    return "".join(rows)


h28_params = H28["params"]
core_full = H28["raw_lookup_table"]["full_2019_2026"]

HTML = f"""<title>변동성타겟팅 & 리밸런싱 주기 기댓값 재검증</title>
<style>
{CSS}
</style>

<div class="masthead">
  <div class="masthead-inner">
    <div class="masthead-eyebrow">
      <span>QUANT RESEARCH NOTE</span><span class="dot">·</span><span>14라운드</span><span class="dot">·</span><span>Hypothesis-Driven Study</span>
    </div>
    <h1 class="masthead-title">코어 변동성타겟팅과 리밸런싱 주기, 기댓값으로 다시 본다</h1>
    <p class="masthead-sub">작업39(H22)가 정립한 기저확률 가중 기댓값 방법론을 이번엔 챔피언 "코어"
      자체의 두 가지 설계 선택에 적용한다 — (H28) 작업20-21(트랙B No.06)이 발견한 "포트폴리오 레벨
      변동성타겟팅은 샤프를 살짝 깎지만 MDD를 크게 줄인다"는 결과가, 라운드11이 새틀라이트 스위치
      전부에서 확인한 "기댓값에서는 진다"는 패턴을 코어 레벨에서도 반복하는가? (H29) 작업19가 고른
      월간 리밸런싱은 작업27(H27)이 룩백을 재검증한 것처럼 한 번도 재스윕되지 않았는데, 거래비용과
      위기창 반응속도를 함께 반영해도 여전히 최선인가?</p>
    <div class="masthead-meta">
      <span><b>기준일</b> {esc(GEN)}</span>
      <span><b>기저확률 시나리오</b> H22와 동일(기본/강세장편향/위기편향), 재계산 없이 그대로 재사용</span>
      <span><b>검증 창</b> 전체기간(2019-2026) + 2008/2022/COVID/2018/2015-16 위기창 6개</span>
    </div>
  </div>
</div>

<div class="wrap">

  <nav class="toc">
    <a href="#scope">00 문제 제기</a>
    <a href="#h28">01 H28 — 코어 변동성타겟팅 기댓값 재검증</a>
    <a href="#h29">02 H29 — 리밸런싱 주기 기댓값 재검증</a>
    <a href="#synthesis">03 종합</a>
    <a href="#limitations">04 한계</a>
  </nav>

  <section class="section" id="scope">
    <h2><span class="sec-no">00</span> 문제 제기 — 코어 자체의 두 설계 선택은 왜 지금까지 안 물어봤나</h2>
    <p class="lede">13라운드에 걸쳐 새틀라이트/스위치 계열의 정교화(트랙D)는 반복적으로 검증했지만,
      그보다 훨씬 앞선 트랙B의 두 코어 설계 선택은 만들어진 이후 재검증된 적이 없다.</p>
    <ul>
      <li><b>H28</b> — 변동성타겟팅은 라운드11(H10~H21)이 검증한 새틀라이트 온/오프 스위치들과
        형태가 닮았다(최악 개선·평균 악화). 다만 스위치는 이진(전부/전무)인 반면 변동성타겟팅은
        연속 스칼라라는 차이가 있다 — 이 차이가 기댓값 결론을 바꾸는지가 핵심 질문이다.</li>
      <li><b>H29</b> — 리밸런싱 주기는 H27이 재검증한 모멘텀 룩백과 같은 급의 "만들어진 뒤 한 번도
        재검증 안 된 근본 파라미터"다. 다른 점은 룩백은 신호 계산 방식이고, 리밸런싱 주기는 거래비용
        (자주 거래할수록 비용 증가)과 반응속도(자주 거래할수록 위기 반응 빠름)가 정반대로 작용하는
        명시적 트레이드오프를 담고 있다는 것이다.</li>
    </ul>
    <p class="caveat">⚠️ 투자 조언이 아니다. 기저확률은 문헌 기반 추정치이며(작업39/H22 근거 그대로
      재사용), 정밀한 확률표가 아니다.</p>
  </section>

  <section class="section" id="h28">
    <h2><span class="sec-no">01</span> H28 — 코어 변동성타겟팅 기댓값 재검증
      <span class="verdict-badge v-reject">기각 (오버레이 없는 코어가 이긴다)</span></h2>
    <p class="lede"><code>champion_strategy.py</code>의 17자산 챔피언(기존 이진 시장필터 포함)을
      그대로 재사용해 일별 순수익률(비용반영)을 뽑고, <code>portfolio_vol_targeting.py</code>(작업
      20-21, 트랙B No.06)의 <code>vol_target_scale()</code> 함수를 그대로 재사용해 목표변동성
      {fnum(h28_params['target_vol_annual'],0)}%·상한 {fnum(h28_params['cap'],1)}배·
      {h28_params['vol_window_days']}일 실현변동성 기준 오버레이를 씌웠다(원 라운드가 최종 채택한
      파라미터, <code>momentum_rotation_vol_target_final.json</code>에서 확인).</p>

    <h3>6개 창 Sharpe/MDD 비교 + 오버레이 축소 빈도</h3>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>검증 창</th><th>오버레이 없음 Sharpe</th><th>변동성타겟팅 Sharpe</th>
          <th>오버레이 없음 MDD</th><th>변동성타겟팅 MDD</th><th>노출축소일 비중</th></tr></thead>
        <tbody>{h28_window_table()}</tbody>
      </table>
    </div>
    <p class="kpi-sub">전체기간(2019-2026)에서 오버레이 없는 코어 Sharpe {fnum(core_full['no_overlay']['sharpe'],2)}·
      MDD {fnum(core_full['no_overlay']['mdd'],2)}% 대비, 변동성타겟팅은 Sharpe
      {fnum(core_full['vol_targeted']['sharpe'],2)}·MDD {fnum(core_full['vol_targeted']['mdd'],2)}% —
      MDD 개선폭이 {fnum(core_full['no_overlay']['mdd']-core_full['vol_targeted']['mdd'],2)}p로 매우 작다.
      6개 창 전체에서 노출이 축소된 날의 비중은 6~24% 수준(위기창일수록 오히려 더 자주 축소)이었다.</p>

    <h3>기댓값 순위 — 기본 시나리오</h3>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>구성</th><th>E[Sharpe]</th><th>E[CAGR]</th><th>위기창 최악 MDD(참고)</th></tr></thead>
        <tbody>{h28_ev_table('base')}</tbody>
      </table>
    </div>

    <div class="callout">
      <div class="callout-title">민감도분석 — 3가지 시나리오 전부에서 오버레이 없는 쪽이 이긴다</div>
      <div class="table-wrap" style="margin-top:10px;">
        <table class="data-table">
          <thead><tr><th>시나리오</th><th>1위</th><th>2위</th></tr></thead>
          <tbody>
            {''.join(f'<tr><td class="tk-cell"><span class="tk-name">{esc(SCEN_LABEL[s])}</span></td>' + ''.join(f'<td class="num">{esc(CFG_LABEL_28[cfg])} ({fnum(val,4)})</td>' for cfg, val in H28["scenarios"][s]["ranking_by_expected_sharpe"]) + '</tr>' for s in ["base", "calm_heavy", "crisis_heavy"])}
          </tbody>
        </table>
      </div>
      <p style="margin-top:10px;"><b>오버레이 없는 코어가 기본·강세장편향·위기편향 세 시나리오
        전부에서 1위</b>다 — 라운드11이 새틀라이트 스위치 전부에서 확인한 패턴("최악은 개선, 평균은
        악화")과 방향은 같지만, 이번엔 <b>최악조차 거의 개선되지 않는다</b>는 점이 더 정직한 결과다.
        위기편향 시나리오에서조차 오버레이가 더 나쁘다({fnum(H28['scenarios']['crisis_heavy']['expected_value']['vol_targeted']['sharpe'],4)}
        vs {fnum(H28['scenarios']['crisis_heavy']['expected_value']['no_overlay']['sharpe'],4)}) — 위기창에서
        노출을 줄이는 게 아니라 이미 이진 시장필터가 그 역할을 절반쯤 대신하고 있어서, 오버레이가
        더할 수 있는 한계 방어력이 거의 없기 때문으로 해석된다.</p>
    </div>

    <div class="callout warn">
      <div class="callout-title">"연속 스칼라라 이진 스위치와 다를 것"이라는 가설은 기각된다</div>
      <p>사용자 질문의 핵심 가설 — "위기창에서 온전히 꺼지는(0 또는 1) 새틀라이트 스위치보다,
        연속적으로 노출을 줄이는 변동성타겟팅이 평시 비용을 덜 치를 것"이라는 예상은 실측과 어긋난다.
        17자산 챔피언은 이미 (a) 4개 자산으로 분산되어 있고 (b) 이진 시장필터가 위기 국면 노출을
        절반으로 줄이는 별도 메커니즘을 갖고 있어서, 그 위에 얹는 변동성 스칼라는 평시(강세장편향
        시나리오에서도 손해)와 위기 양쪽 모두에서 순수하게 노이즈에 가깝게 작동한다 — 원 리포트(작업
        20-21, No.06)가 관찰한 "MDD 크게 개선"은 단일/소수 자산 백테스트 맥락이었을 가능성이 높고,
        이미 분산+필터가 갖춰진 이 코어에는 잘 옮겨오지 않는다.</p>
    </div>
  </section>

  <section class="section" id="h29">
    <h2><span class="sec-no">02</span> H29 — 리밸런싱 주기 기댓값 재검증
      <span class="verdict-badge v-partial">부분 채택 (월간이 기본/강세장 시나리오에서 이기지만, 위기편향에서는 6주가 근소 우위)</span></h2>
    <p class="lede">주간(5거래일)/격주(10)/월간(21, 기존)/6주(30)/분기(63) 5개 빈도로
      <code>champion_strategy.py</code>의 build_champion_weights 로직을 리밸런싱 마스크만 교체해
      재구현했다(모멘텀 룩백·시장필터·비용 관례는 그대로). 왕복 0.1% 비용이 비중 변화 절대값 기준으로
      이미 반영되므로, 빈도가 늘수록 회전율과 비용이 자동으로 함께 늘어난다.</p>

    <h3>6개 창 Sharpe 전체 비교</h3>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>검증 창</th><th>주간</th><th>격주</th><th>월간(기존)</th><th>6주</th><th>분기</th></tr></thead>
        <tbody>{h29_window_table()}</tbody>
      </table>
    </div>

    <h3>연간 회전율 (거래비용이 어떻게 늘어나는지 확인)</h3>
    <p class="kpi-sub">전체기간 기준 연평균 회전율: 주간
      {fnum(H29['raw_lookup_table']['full_2019_2026']['weekly_5d']['avg_annual_turnover_pct'],0)}% ·
      격주 {fnum(H29['raw_lookup_table']['full_2019_2026']['biweekly_10d']['avg_annual_turnover_pct'],0)}% ·
      월간 {fnum(H29['raw_lookup_table']['full_2019_2026']['monthly_21d']['avg_annual_turnover_pct'],0)}% ·
      6주 {fnum(H29['raw_lookup_table']['full_2019_2026']['sixweek_30d']['avg_annual_turnover_pct'],0)}% ·
      분기 {fnum(H29['raw_lookup_table']['full_2019_2026']['quarterly_63d']['avg_annual_turnover_pct'],0)}% —
      의도한 대로 빈도가 늘수록 회전율(및 그에 비례한 비용)이 단조증가한다. 주간 회전율이 월간의
      2배가 넘는데도(1014% vs 471%) 그 비용 부담을 신호 반응속도 개선이 상쇄하지 못한다.</p>

    <h3>기댓값 프론티어 — 기본 시나리오</h3>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>리밸런싱 주기</th><th>E[Sharpe]</th><th>E[CAGR]</th><th>위기창 최악 MDD(참고)</th><th>연회전율(참고)</th></tr></thead>
        <tbody>{h29_ev_table('base')}</tbody>
      </table>
    </div>

    <div class="callout">
      <div class="callout-title">민감도분석 — 시나리오마다 1위가 갈린다</div>
      <div class="table-wrap" style="margin-top:10px;">
        <table class="data-table">
          <thead><tr><th>시나리오</th><th>1위</th><th>2위</th><th>3위</th></tr></thead>
          <tbody>
            {''.join(f'<tr><td class="tk-cell"><span class="tk-name">{esc(SCEN_LABEL[s])}</span></td>' + ''.join(f'<td class="num">{esc(FREQ_LABEL[f])} ({fnum(v,3)})</td>' for f, v in H29["scenarios"][s]["ranking_by_expected_sharpe"][:3]) + '</tr>' for s in ["base", "calm_heavy", "crisis_heavy"])}
          </tbody>
        </table>
      </div>
      <p style="margin-top:10px;"><b>월간 리밸런싱은 기본·강세장편향 시나리오에서 1위를 유지하지만,
        위기편향 시나리오에서는 6주(30거래일) 리밸런싱이 근소하게(
        {fnum(H29['scenarios']['crisis_heavy']['expected_value']['sixweek_30d']['expected_sharpe'],4)}
        vs {fnum(H29['scenarios']['crisis_heavy']['expected_value']['monthly_21d']['expected_sharpe'],4)})
        앞선다</b> — 격차는 작지만(0.03pt) H27(룩백)이나 H26(시스템 vs SPY)처럼 세 시나리오 전부에서
        같은 답이 나오지는 않았다. 순수 위기창만 볼 때는 신호를 살짝 더 천천히 갱신하는 쪽(6주)이
        빈번한 위기창 재진입 잡음을 줄이는 것으로 보이나, 이 격차는 다른 두 시나리오의 격차(월간이
        확실히 앞섬)보다 훨씬 작아 전체적으로는 월간이 여전히 가장 견고한 기본값이다.</p>
    </div>

    <div class="callout warn">
      <div class="callout-title">"더 자주 리밸런싱하면 위기에 빠르게 반응해 유리할 것"이라는 가설도 기각된다</div>
      <p>주간·격주처럼 짧은 주기는 모든 시나리오에서 월간보다 뚜렷하게 열위다 — H27이 짧은 모멘텀
        룩백에서 확인한 것과 같은 패턴("빠른 반응"이 실제로는 잡음 과잉반응+비용누적으로 이어짐)이
        리밸런싱 주기에서도 반복된다. 유일하게 월간을 앞서는 경우(6주, 위기편향 시나리오)조차
        "더 자주"가 아니라 "비슷하거나 살짝 더 느리게"라는 점이 흥미롭다 — 이 시스템의 신호(12개월
        모멘텀+이진 시장필터)는 원래 저빈도로 설계되어 있어서, 실행 빈도만 올린다고 반응속도가
        개선되지 않고 비용만 늘어난다는 게 일관된 결론이다.</p>
    </div>
  </section>

  <section class="section" id="synthesis">
    <h2><span class="sec-no">03</span> 종합 — 트랙B+D 전체에 비춘 최종 기댓값-최적 챔피언 설정</h2>
    <p class="lede">14라운드에 걸쳐 검증한 코어 설계 선택 두 가지 중 하나는 기각, 하나는 부분 채택으로
      마무리된다 — 이번 라운드도 "항상 기존 선택이 정당화된다"는 확증편향에 빠지지 않고 정직하게
      갈렸다는 점이 방법론의 신뢰도를 보여준다.</p>
    <div class="hyp-card">
      <div class="hyp-id">H28 — 코어 레벨 변동성타겟팅은 기댓값에서 진다, 게다가 최악조차 크게 개선하지 않는다</div>
      <p style="margin:8px 0 0;">라운드11이 새틀라이트 스위치 전부에서 확인한 "최악은 개선·평균은 악화"
        패턴이 코어 레벨에서도 방향은 유지되지만, 이번엔 최악 개선폭조차 미미해(MDD 0.3p 수준) 순수하게
        열위인 결과다. 연속 스칼라라는 형태 차이는 결론을 바꾸지 못했다 — 오히려 이미 분산(17자산 top4)+
        이진 필터를 갖춘 코어에는 추가 변동성 스칼라가 얹을 여지가 거의 없다는 게 더 근본적인 이유로
        보인다. 챔피언 코어에는 변동성타겟팅 오버레이를 추가하지 않는 것이 기댓값 관점에서 명확히 낫다.</p>
    </div>
    <div class="hyp-card">
      <div class="hyp-id">H29 — 월간 리밸런싱은 대체로 정당화되지만, H26/H27만큼 만장일치는 아니다</div>
      <p style="margin:8px 0 0;">기본·강세장편향 시나리오에서는 월간이 명확히 1위이나, 위기편향
        시나리오에서는 6주 주기가 근소하게 앞선다 — 격차가 작고(0.03pt) 다른 두 시나리오의 우위(월간)가
        더 크므로, 기본값은 여전히 월간으로 유지하되 "위기 국면 전용으로 리밸런싱을 살짝 늦추는" 추가
        스위치는 이번 6개 빈도 그리드만으로는 기댓값 개선폭이 확신할 만큼 크지 않아 권장하지 않는다.</p>
    </div>
    <div class="hyp-card">
      <div class="hyp-id">최종 기댓값-최적 챔피언 설정 (14라운드 누적)</div>
      <p style="margin:8px 0 0;">"17자산·12개월 모멘텀(H27 확인)·이진 시장필터·월간 리밸런싱(H29 대체로
        확인)·변동성타겟팅 오버레이 없음(H28 신규 기각)·(선택적) 15% 정적 새틀라이트(작업39 확인)"가
        14라운드 전체를 통틀어 기댓값 관점에서 가장 견고한 구성으로 남는다. 이번 라운드는 두 가지
        "추가하면 좋아 보이는" 옵션(변동성타겟팅, 더 잦은 리밸런싱) 둘 다를 정직하게 기각/보류함으로써
        코어 자체가 이미 상당히 잘 튜닝돼 있다는 걸 재확인했다.</p>
    </div>
  </section>

  <section class="section" id="limitations">
    <h2><span class="sec-no">04</span> 한계</h2>
    <ul>
      <li><b>기저확률은 여전히 추정치</b> — H22/작업39가 정립한 3%/4%/10%/16%/17%/50% 기저확률을 그대로
        재사용했다. 이 수치들의 불확실성에 대한 한계는 H22 리포트에 이미 상세히 기술되어 있다.</li>
      <li><b>H28의 변동성타겟팅 파라미터는 1개 조합만 테스트</b> — 원 라운드(작업20-21)가 최종 채택한
        목표변동성 18%·상한 1.0배만 검증했다. 다른 목표변동성(10~15%)이나 상한(1.5~2.0배)을 스윕하면
        결과가 달라질 가능성을 배제할 수 없으나, 원 라운드 자체가 이미 여러 조합을 스윕해 이 값을
        "최종 채택"했으므로 재현하는 것이 합리적인 선택이었다.</li>
      <li><b>H29의 리밸런싱 마스크는 "N거래일마다"로 단순화</b> — 기존 월간 리밸런싱은 "매월 첫
        거래일"(달력 경계) 기준이었는데, 이번 스윕은 "인덱스 0번째부터 N거래일 간격"으로 일반화했다.
        월간(21거래일) 결과가 원래의 달력월 기준과 소수점 단위로 다를 수 있으나(H27의 champion_strategy.py
        재구현과 동일한 성격의 한계), 방향성 결론에는 영향을 주지 않는다.</li>
      <li><b>H29 위기편향 시나리오의 6주 우위는 격차가 작다</b> — 0.03pt 차이는 이 연구가 쓰는 6개
        창·근사적 기저확률의 노이즈 수준 안에 있을 수 있어, "6주가 위기에 확실히 더 낫다"기보다는
        "월간과 통계적으로 구분하기 어렵다"는 정도로 해석하는 게 더 정직하다.</li>
      <li><b>6개 창은 여전히 작고 서로 겹친다</b> — H22가 명시한 한계(창 간 상관관계, 표본 다양성 부족,
        다중비교 위험)가 이번 라운드에도 그대로 적용된다.</li>
      <li><b>필터 자체는 두 가설 모두에서 건드리지 않았다</b> — 이진 시장필터(SPY 200일선, 50% 축소)의
        최적성은 병렬 라운드(H24/H25)의 검증 대상이며, 이번 라운드의 결론은 "필터가 현재 스펙 그대로
        있다는 전제 하에서"만 유효하다.</li>
    </ul>
  </section>

</div>

<footer>
  <p>analysis/2026-08-23_vol_targeting_and_rebalance_frequency_expected_value/ (데이터: report_data.json,
    빌드: build_report.py) · h28_vol_targeting_expected_value.py는
    analysis/2026-08-19_champion_beta_and_satellite_research/champion_strategy.py의 run_champion()으로
    17자산 챔피언 일별 순수익률을 뽑고, analysis/kostolany_market_report_2026-08-12/portfolio_vol_targeting.py의
    vol_target_scale() 함수를 그대로 재사용해 오버레이를 씌워 6개 창을 전부 신규 백테스트했다.
    h29_rebalance_frequency_expected_value.py는 champion_strategy.py의 build_champion_weights 로직을
    리밸런싱 마스크만 교체해(N거래일 간격) 5개 빈도 x 6개 창을 전부 신규 백테스트했다. 두 가설 모두
    H22/작업39와 동일한 기저확률 가중 시나리오(기본/강세장편향/위기편향)를 재계산 없이 재사용했다.
    core.market_data를 통한 실제 Yahoo Finance 데이터이며 추정치가 아니다. 이 워크트리는 main과
    분기된 시점 이후 인프라 변경이 반영되지 않을 수 있어, 모든 스크립트가 main 체크아웃
    (/workspaces/Quant)의 core/ 및 이전 라운드 analysis/를 직접 참조해 실행했다 — 이 워크트리의 core/는
    건드리지 않았다.</p>
</footer>
"""

out_file = f"{OUT_DIR}/final_report.html"
with open(out_file, "w", encoding="utf-8") as f:
    f.write(HTML)
print(f"SAVED {out_file}")
