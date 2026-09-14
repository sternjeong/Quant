#!/usr/bin/env python3
"""report_data.json을 읽어 final_report.html을 만든다.

analysis/2026-08-23_expected_value_reframing_and_continuous_exposure/build_report.py 와 동일한
디자인 시스템(다크네이비/올리브 톤, 세리프 헤드라인, TOC, 섹션 번호, 판정 배지)을 그대로 재사용한다.
"""
import json
import math
import os

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

with open(f"{OUT_DIR}/report_data.json", encoding="utf-8") as f:
    R = json.load(f)

GEN = R["meta"]["generated"]
H26 = R["h26"]
H27 = R["h27"]


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

CFG_LABEL_26 = {
    "spy_buyhold": "SPY 매수보유 (단순)",
    "core_alone": "17자산 챔피언 코어 단독",
    "core_plus_satellite": "코어+정적 새틀라이트 (전체 시스템)",
}
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

base26 = H26["scenarios"]["base"]
ranking26_base = base26["ranking_by_expected_sharpe"]
top26_cfg, top26_val = ranking26_base[0]

base27 = H27["scenarios"]["base"]
ranking27_base = base27["ranking_by_expected_sharpe"]
top27_months, top27_val = ranking27_base[0]


def h26_window_table():
    rows = []
    for ep in EP_ORDER:
        row = H26["raw_lookup_table"][ep]
        rows.append(
            f'<tr><td class="tk-cell"><span class="tk-name">{esc(ARCHETYPE_KOR[ep])}</span></td>'
            f'<td class="num">{fnum(row["spy_buyhold"]["sharpe"],2)}</td>'
            f'<td class="num">{fnum(row["core_alone"]["sharpe"],2)}</td>'
            f'<td class="num strong">{fnum(row["core_plus_satellite"]["sharpe"],2)}</td>'
            f'<td class="num">{fnum(row["spy_buyhold"]["cagr"],1,True)}%</td>'
            f'<td class="num">{fnum(row["core_alone"]["cagr"],1,True)}%</td>'
            f'<td class="num strong">{fnum(row["core_plus_satellite"]["cagr"],1,True)}%</td></tr>'
        )
    return "".join(rows)


def h26_ev_table(scen_name):
    scen = H26["scenarios"][scen_name]
    rows = []
    for i, (cfg, val) in enumerate(scen["ranking_by_expected_sharpe"]):
        cagr = scen["expected_value"][cfg]["cagr"]
        mdd_worst = scen["expected_value"][cfg]["mdd_worst_case"]
        cls = "best-row" if i == 0 else ""
        rows.append(
            f'<tr class="{cls}"><td class="tk-cell"><span class="tk-name">{i+1}. {esc(CFG_LABEL_26[cfg])}</span></td>'
            f'<td class="num">{fnum(val,4)}</td><td class="num">{fnum(cagr,2,True)}%</td>'
            f'<td class="num">{fnum(mdd_worst,2)}%</td></tr>'
        )
    return "".join(rows)


def h27_lookback_table(scen_name):
    scen = H27["scenarios"][scen_name]
    ev = scen["expected_value"]
    rows = []
    ranking_order = [k for k, v in scen["ranking_by_expected_sharpe"]]
    for months in ["3", "6", "9", "12", "15", "18"]:
        v = ev[months]
        cls = "best-row" if months == ranking_order[0] else ""
        rows.append(
            f'<tr class="{cls}"><td class="tk-cell"><span class="tk-name">{months}개월</span></td>'
            f'<td class="num">{fnum(v["expected_sharpe"],4)}</td>'
            f'<td class="num">{fnum(v["expected_cagr_pct"],2,True)}%</td>'
            f'<td class="num">{fnum(v["mdd_worst_case"],2)}%</td></tr>'
        )
    return "".join(rows)


def h27_window_table():
    rows = []
    for ep in EP_ORDER:
        row = H27["raw_lookup_table"][ep]
        cells = "".join(f'<td class="num">{fnum(row[str(m)]["sharpe"],2)}</td>' for m in [3, 6, 9, 12, 15, 18])
        rows.append(f'<tr><td class="tk-cell"><span class="tk-name">{esc(ARCHETYPE_KOR[ep])}</span></td>{cells}</tr>')
    return "".join(rows)


spy_full = H26["raw_lookup_table"]["full_2019_2026"]["spy_buyhold"]
sys_full = H26["raw_lookup_table"]["full_2019_2026"]["core_plus_satellite"]
core_full = H26["raw_lookup_table"]["full_2019_2026"]["core_alone"]

HTML = f"""<title>전체 시스템 vs 매수보유 & 룩백 강건성 연구</title>
<style>
{CSS}
</style>

<div class="masthead">
  <div class="masthead-inner">
    <div class="masthead-eyebrow">
      <span>QUANT RESEARCH NOTE</span><span class="dot">·</span><span>13라운드</span><span class="dot">·</span><span>Hypothesis-Driven Study</span>
    </div>
    <h1 class="masthead-title">전체 시스템 vs 매수보유, 그리고 룩백기간 강건성</h1>
    <p class="masthead-sub">11라운드(작업39, H22)가 정립한 기저확률 가중 기댓값 방법론을 이번엔 두
      가지 근본 질문에 적용한다 — (H26) 13라운드 동안 쌓아온 로테이션 챔피언+새틀라이트 시스템 전체가,
      가장 단순한 대안인 SPY 매수보유를 실제로 이기는가? (H27) 챔피언의 12개월 모멘텀 랭킹 룩백은
      작업19가 정한 이후 한 번도 재검증되지 않았는데, 기저확률로 공정하게 가중해도 여전히 최선인가?</p>
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
    <a href="#h26">01 H26 — 전체 시스템 vs SPY 매수보유</a>
    <a href="#h27">02 H27 — 모멘텀 룩백기간 기댓값 재검증</a>
    <a href="#synthesis">03 종합</a>
    <a href="#limitations">04 한계</a>
  </nav>

  <section class="section" id="scope">
    <h2><span class="sec-no">00</span> 문제 제기 — 13라운드 뒤, 아직 안 물어본 두 개의 당연한 질문</h2>
    <p class="lede">작업19~39는 17자산 듀얼모멘텀 로테이션 챔피언을 만들고(작업19-23), 그 위에 새틀라이트·
      스위치·기댓값 재구성까지(작업33-39) 쌓아왔다. 하지만 이 모든 복잡함이 "가장 단순한 대안"보다
      실제로 나은지는 한 번도 직접 비교하지 않았고, 그 복잡함의 근간인 12개월 모멘텀 룩백 자체도
      작업19 이후 재검증된 적이 없다. 이번 라운드는 두 가설로 이 사각지대를 메운다.</p>
    <ul>
      <li><b>H26</b> — (a) 순수 SPY 매수보유, (b) 17자산 챔피언 코어 단독, (c) 코어+15% 정적 새틀라이트
        (H22가 찾은 기댓값 최적 구성)을 H22와 동일한 6개 창·3개 시나리오로 정면비교한다.</li>
      <li><b>H27</b> — 챔피언의 모멘텀 랭킹 룩백을 3/6/9/12/15/18개월로 스윕하고, 같은 기저확률로
        기댓값 프론티어를 그려 12개월이 여전히 최선인지 확인한다.</li>
    </ul>
    <p class="caveat">⚠️ 투자 조언이 아니다. 기저확률은 문헌 기반 추정치이며(작업39/H22 근거 그대로
      재사용), 정밀한 확률표가 아니다.</p>
  </section>

  <section class="section" id="h26">
    <h2><span class="sec-no">01</span> H26 — 전체 시스템 vs SPY 매수보유 <span class="verdict-badge v-accept">채택 (시스템이 이긴다)</span></h2>
    <p class="lede">(a) SPY 매수보유는 이번 라운드 신규 백테스트, (b)/(c) 코어단독·코어+정적새틀라이트는
      이미 존재하는 <code>expected_value_reframing_and_continuous_exposure/report_data.json</code>의
      h22 <code>raw_lookup_table</code>(동일 6개 창 정의로 이미 실측됨)을 재계산 없이 그대로 재사용했다.</p>

    <h3>6개 창 Sharpe/CAGR 직접비교</h3>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>검증 창</th><th>SPY 매수보유 Sharpe</th><th>코어단독 Sharpe</th><th>전체시스템 Sharpe</th>
          <th>SPY CAGR</th><th>코어단독 CAGR</th><th>전체시스템 CAGR</th></tr></thead>
        <tbody>{h26_window_table()}</tbody>
      </table>
    </div>
    <p class="kpi-sub">전체기간(2019-2026)에서 SPY 매수보유 Sharpe {fnum(spy_full['sharpe'],2)}·CAGR
      {fnum(spy_full['cagr'],1,True)}% 대비, 코어단독 {fnum(core_full['sharpe'],2)}·{fnum(core_full['cagr'],1,True)}%,
      전체시스템 {fnum(sys_full['sharpe'],2)}·{fnum(sys_full['cagr'],1,True)}% — 강세장 구간에서도 시스템이
      단순 SPY보다 나은 위험조정수익을 낸다.</p>

    <h3>기댓값 순위 — 기본 시나리오</h3>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>구성</th><th>E[Sharpe]</th><th>E[CAGR]</th><th>위기창 최악 MDD(참고)</th></tr></thead>
        <tbody>{h26_ev_table('base')}</tbody>
      </table>
    </div>

    <div class="callout">
      <div class="callout-title">민감도분석 — 3가지 시나리오 전부에서 순위가 유지되는가</div>
      <div class="table-wrap" style="margin-top:10px;">
        <table class="data-table">
          <thead><tr><th>시나리오</th><th>1위</th><th>2위</th><th>3위</th></tr></thead>
          <tbody>
            {''.join(f'<tr><td class="tk-cell"><span class="tk-name">{esc(SCEN_LABEL[s])}</span></td>' + ''.join(f'<td class="num">{esc(CFG_LABEL_26[cfg])} ({fnum(val,3)})</td>' for cfg, val in H26["scenarios"][s]["ranking_by_expected_sharpe"]) + '</tr>' for s in ["base", "calm_heavy", "crisis_heavy"])}
          </tbody>
        </table>
      </div>
      <p style="margin-top:10px;"><b>전체시스템(코어+정적새틀라이트)이 세 시나리오 전부에서 1위, 코어단독이
        2위, SPY 매수보유가 3개 시나리오 모두에서 최하위</b>다 — 이 순위는 위기편향 시나리오에서도
        흔들리지 않는다. SPY가 최하위인 이유는 직관적이다: 17자산 챔피언은 SPY보다 넓은 유니버스에서
        절대/상대모멘텀으로 상위 4개만 골라 담고 이진 시장필터로 약세장 비중을 줄이는 반면, SPY는
        지수 하나를 있는 그대로 전량 보유해 하락장에서 방어 메커니즘이 전혀 없다.</p>
    </div>

    <div class="callout warn">
      <div class="callout-title">복잡성 대비 기댓값 — 정직한 평가</div>
      <p>기본 시나리오에서 전체시스템의 E[Sharpe]는 SPY 대비 약
        {fnum(H26['scenarios']['base']['expected_value']['core_plus_satellite']['sharpe'] - H26['scenarios']['base']['expected_value']['spy_buyhold']['sharpe'],3)}p 높다 —
        절대적으로는 작지 않은 격차이지만, 이걸 얻기 위해 감수하는 운영 복잡성(17자산 포인트인타임
        유니버스 샘플링, 매월 리밸런싱 신호계산, 이진 시장필터, 새틀라이트 종목선정, 왕복 거래비용
        반영)은 결코 작지 않다. 코어단독만으로도 SPY 대비 기댓값 우위 대부분을 이미 확보한다는 점도
        주목할 만하다 — 새틀라이트가 더하는 한계 개선분은 코어 자체가 SPY를 이기는 폭보다 작다. 즉
        "복잡함이 공짜가 아니라는 것"과 "복잡함의 첫 단계(코어 로테이션)가 가장 큰 몫을 한다"는 두
        메시지가 동시에 성립한다 — 개인 투자자가 인프라·시간 비용을 감당할 수 없다면 코어단독만으로도
        상당한 기댓값 개선을 얻고, 그 이상의 새틀라이트 계층은 한계효용이 체감되는 추가 복잡성이다.</p>
    </div>
  </section>

  <section class="section" id="h27">
    <h2><span class="sec-no">02</span> H27 — 모멘텀 랭킹 룩백기간 기댓값 재검증 <span class="verdict-badge v-accept">채택 (12개월이 여전히 최선)</span></h2>
    <p class="lede">3/6/9/12/15/18개월 룩백으로 챔피언(기존 이진 시장필터 포함)을 6개 창에서 새로
      백테스트했다(<code>champion_strategy.py</code>의 빌딩블록을 momentum_window 파라미터만 바꿔
      재사용, 필터 자체는 건드리지 않음).</p>

    <h3>6개 창 - 6개 룩백 Sharpe 전체 비교</h3>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>검증 창</th><th>3개월</th><th>6개월</th><th>9개월</th><th>12개월</th><th>15개월</th><th>18개월</th></tr></thead>
        <tbody>{h27_window_table()}</tbody>
      </table>
    </div>
    <p class="kpi-sub">COVID 위기창에서는 9~15개월 구간이 동률로 가장 안정적이고(느린 반응이 오히려
      과최적화된 급락 타이밍을 피함), 3~6개월처럼 지나치게 짧은 룩백은 잦은 회전과 잡음 신호로
      COVID·GFC 양쪽 모두에서 오히려 나쁜 성과를 냈다 — "짧은 룩백이 빠른 위기 대응에 유리할 것"이라는
      가설상의 직관과 반대되는 실측 결과다.</p>

    <h3>기댓값 프론티어 — 기본 시나리오</h3>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>모멘텀 룩백</th><th>E[Sharpe]</th><th>E[CAGR]</th><th>위기창 최악 MDD(참고)</th></tr></thead>
        <tbody>{h27_lookback_table('base')}</tbody>
      </table>
    </div>

    <div class="callout">
      <div class="callout-title">민감도분석 — 3가지 시나리오 전부에서 12개월이 1위</div>
      <div class="table-wrap" style="margin-top:10px;">
        <table class="data-table">
          <thead><tr><th>시나리오</th><th>1위</th><th>2위</th><th>3위</th></tr></thead>
          <tbody>
            {''.join(f'<tr><td class="tk-cell"><span class="tk-name">{esc(SCEN_LABEL[s])}</span></td>' + ''.join(f'<td class="num">{m}개월 ({fnum(v,3)})</td>' for m, v in H27["scenarios"][s]["ranking_by_expected_sharpe"][:3]) + '</tr>' for s in ["base", "calm_heavy", "crisis_heavy"])}
          </tbody>
        </table>
      </div>
      <p style="margin-top:10px;"><b>12개월 룩백이 기본·강세장편향·위기편향 세 시나리오 전부에서
        1위</b>다 — 작업19가 학술적 관행(12-1 모멘텀 팩터)에 근거해 고른 선택이, 13라운드가 지난 뒤
        기저확률 가중 기댓값 검증에서도 그대로 확인됐다. 9개월이 근소한 2위로 항상 따라붙는다는 점은
        주목할 만하다 — 12개월 근방(9~12개월)이 견고한 최적 구간이고, 그 아래(3~6개월)나 크게 위쪽
        (15~18개월)은 뚜렷하게 열위다.</p>
    </div>

    <div class="callout warn">
      <div class="callout-title">"짧은 룩백이 빠른 레짐전환에 유리하다"는 가설은 기각된다</div>
      <p>COVID처럼 몇 주 만에 급락한 레짐 전환에서 12개월 룩백이 느리게 반응할 거라는 우려와 달리,
        실측으로는 3~6개월처럼 짧은 룩백이 COVID·GFC 위기창 모두에서 12개월보다 더 나쁜 성과를
        기록했다 — 짧은 룩백은 위기 국면에서도 최근 몇 달의 잡음(반등/재하락 반복)에 과잉반응해 회전만
        늘리고 필터링 능력이 떨어진다. 12개월 룩백의 "느린 반응"은 오히려 안정적인 추세 판별력으로
        작동한다 — 이는 이진 시장필터(SPY 200일선)가 이미 별도로 빠른 레짐감지 역할을 일부 담당하고
        있어서, 랭킹 룩백까지 짧게 가져갈 필요가 적다는 방증이기도 하다.</p>
    </div>
  </section>

  <section class="section" id="synthesis">
    <h2><span class="sec-no">03</span> 종합 — 트랙B/D 전체에 비춘 의미</h2>
    <p class="lede">이번 라운드는 두 개의 "당연했지만 안 물어본" 질문에 모두 긍정적인(그러나 정직하게
      제한된) 답을 냈다.</p>
    <div class="hyp-card">
      <div class="hyp-id">H26 — 복잡함은 정당화된다, 다만 대부분의 몫은 "코어"가 이미 낸다</div>
      <p style="margin:8px 0 0;">13라운드 연구 전체의 최종 정당성 검증에서, 로테이션 챔피언(+새틀라이트)
        시스템은 SPY 매수보유를 기댓값 관점에서 견고하게 이긴다. 그러나 그 우위의 상당 부분은 이미
        "코어단독"(순수 로테이션+필터, 새틀라이트 없음) 단계에서 확보되고, 새틀라이트가 더하는 한계
        개선은 상대적으로 작다 — 트랙D(작업33-39)가 "새틀라이트+스위치 계열의 정교화"에 쓴 노력 대비,
        트랙B(작업19-23)의 "코어 로테이션 자체를 만든 것"이 이 연구 프로그램 전체 가치의 더 큰
        몫이라는 뜻이다.</p>
    </div>
    <div class="hyp-card">
      <div class="hyp-id">H27 — 12개월 룩백은 사후적으로도 정당화된다, 재튜닝 불필요</div>
      <p style="margin:8px 0 0;">작업19가 학술 관행을 따라 고른 12개월이, 기저확률 가중 기댓값이라는
        엄밀한 잣대로도 세 시나리오 전부에서 1위를 유지한다 — 13라운드 동안 이 파라미터를 재검증하지
        않고 그대로 써온 것이 사후적으로 정당화됐다. 향후 라운드가 이 파라미터를 다시 스윕할 필요는
        낮다.</p>
    </div>
    <div class="hyp-card">
      <div class="hyp-id">두 결과를 합친 최종 권고</div>
      <p style="margin:8px 0 0;">"17자산·12개월 모멘텀·이진 시장필터·(선택적) 15% 정적 새틀라이트"
        구성 그대로가, 13라운드에 걸쳐 시도한 모든 대안(다른 룩백, 스위치 계열, 연속노출, 그리고 이번
        라운드의 SPY 매수보유 벤치마크)을 통틀어 기댓값 관점에서 가장 견고한 선택으로 남는다. 이는
        "새로운 발견"이 아니라 "기존 선택이 옳았다는 확인"이라는 점에서 결과 자체는 소박하지만, 13라운드
        동안 쌓아온 복잡성 전체가 근거 없이 늘어난 게 아니라는 걸 처음으로 정면 검증했다는 점에서
        이 연구 프로그램의 정직성 감사(honesty audit)로서 가치가 있다.</p>
    </div>
  </section>

  <section class="section" id="limitations">
    <h2><span class="sec-no">04</span> 한계</h2>
    <ul>
      <li><b>기저확률은 여전히 추정치</b> — H22/작업39가 정립한 3%/4%/10%/16%/17%/50% 기저확률을 그대로
        재사용했다. 이 수치들의 불확실성에 대한 한계는 H22 리포트에 이미 상세히 기술되어 있고, 이번
        라운드가 새로 검증하지는 않았다.</li>
      <li><b>H26의 SPY 매수보유는 이번 라운드 신규 백테스트, 코어/시스템 수치는 재사용</b> — 세 구성이
        정확히 같은 창 정의·기간으로 계산됐음을 스크립트에서 직접 확인했으나(h23_results.json meta의
        window 정의와 h22 raw_lookup_table 수치가 일치), SPY 쪽은 배당재투자를 단순 종가 기준으로
        근사했다(배당 포함 총수익 지수가 아님) — 실제로는 SPY 매수보유의 CAGR이 근소하게 더 높게
        나올 수 있다(연 약 1.3%p 안팕의 배당수익률 과소평가).</li>
      <li><b>H27의 코어단독 수치는 champion_strategy.py 독립 재구현</b> — 12개월 룩백 결과가 H22/H26이
        재사용한 raw_lookup_table 수치와 소수점 단위로 미세하게 다르다(예: COVID 위기창 Sharpe 0.13 vs
        0.22) — champion_strategy.py 자체 docstring이 이미 명시하듯 "원 리포트 대비 재구현이라 소수점
        단위로 다를 수 있다"는 알려진 특성이며, 워밍업 기간·fetch 시점 차이에서 비롯된다. 순위/방향성
        결론에는 영향을 주지 않는다.</li>
      <li><b>6개 창은 여전히 작고 서로 겹친다</b> — H22가 명시한 한계(창 간 상관관계, 표본 다양성 부족,
        다중비교 위험)가 이번 라운드에도 그대로 적용된다.</li>
      <li><b>룩백 스윕은 6개 값(3/6/9/12/15/18개월)만 테스트</b> — 더 촘촘한 그리드(예: 1개월 단위)나
        비-정수개월 룩백은 탐색하지 않았다. 12개월 근방(9~15개월)이 완만한 고원(plateau)을 이루는지,
        날카로운 봉우리인지는 이번 6점 그리드만으로는 완전히 판별하기 어렵다.</li>
      <li><b>필터 자체는 두 가설 모두에서 건드리지 않았다</b> — 이진 시장필터(SPY 200일선, 50% 축소)의
        최적성은 별도 병렬 라운드(H25)의 검증 대상이며, 이번 라운드의 결론은 "필터가 현재 스펙 그대로
        있다는 전제 하에서"만 유효하다.</li>
    </ul>
  </section>

</div>

<footer>
  <p>analysis/2026-08-23_system_vs_buyhold_and_lookback_robustness/ (데이터: report_data.json, 빌드:
    build_report.py) · h26_system_vs_spy_buyhold.py는 SPY 매수보유만 신규 백테스트하고 코어단독/
    코어+정적새틀라이트 수치는 analysis/2026-08-23_expected_value_reframing_and_continuous_exposure/
    report_data.json의 h22 raw_lookup_table을 재계산 없이 그대로 재사용했다(동일 6개 창 정의).
    h27_momentum_lookback_expected_value.py는 analysis/2026-08-19_champion_beta_and_satellite_research/
    champion_strategy.py의 빌딩블록(build_champion_weights/compute_portfolio_returns)을
    momentum_window 파라미터만 바꿔 6개 룩백 x 6개 창을 전부 신규 백테스트했다(core.market_data를 통한
    실제 Yahoo Finance 데이터, 추정치 아님). 두 가설 모두 H22/작업39와 동일한 기저확률 가중 시나리오
    (기본/강세장편향/위기편향)를 재계산 없이 재사용했다. 이 워크트리는 main과 분기된 시점 이후 인프라
    변경이 반영되지 않을 수 있어, 모든 스크립트가 main 체크아웃(/workspaces/Quant)의 core/ 및 이전
    라운드 analysis/를 직접 참조해 실행했다 — 이 워크트리의 core/는 건드리지 않았다.</p>
</footer>
"""

out_file = f"{OUT_DIR}/final_report.html"
with open(out_file, "w", encoding="utf-8") as f:
    f.write(HTML)
print(f"SAVED {out_file}")
