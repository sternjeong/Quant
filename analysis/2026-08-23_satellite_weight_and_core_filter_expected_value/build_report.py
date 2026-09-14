#!/usr/bin/env python3
"""report_data.json을 읽어 final_report.html을 만든다.

analysis/2026-08-24_bootstrap_confidence_audit_remaining_verdicts/build_report.py(H34)와 동일한
디자인 시스템(다크네이비/올리브 톤, 세리프 헤드라인, TOC, 섹션 번호, 판정 배지)을 재사용한다.

주: 이 스크립트는 오케스트레이터가 12라운드(H24/H25) 에이전트가 세션 한도로 완료 알림 없이
멈춘 뒤(작업 결과는 h24_results.json/h25_results.json/report_data.json에 전부 남아있었음)
직접 작성했다 - 원 에이전트가 만든 report_data.json을 그대로 읽어 리포트만 빌드한다.
"""
import json
import math
import os

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

with open(f"{OUT_DIR}/report_data.json", encoding="utf-8") as f:
    R = json.load(f)

EP_ORDER = R["meta"]["episode_order"]
SCENARIOS = R["meta"]["scenarios"]
H24 = R["h24_expected_value"]
H25 = R["h25_expected_value"]
H24_RAW = R["h24_raw"]["episodes"]
H25_RAW = R["h25_raw"]["episodes"]

EP_LABEL = {
    "full_2019_2026": "전체기간 2019-2026",
    "gfc_2008": "2008 GFC",
    "covid_2020": "COVID 2020",
    "bear_2022": "2022 완만약세장",
    "selloff_2018": "2018 4분기 급락",
    "correction_2015_2016": "2015-16 조정",
}


def fnum(v, digits=2, signed=False):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    s = f"{v:,.{digits}f}"
    if signed and v > 0:
        s = "+" + s
    return s


def pct(v, digits=0):
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


def h24_sweep_rows(scenario_key):
    rows = []
    ranking = H24["scenarios"][scenario_key]["expected_value_by_weight"]
    for w in ["0.0", "0.05", "0.1", "0.15", "0.2", "0.25", "0.3", "0.4", "0.5"]:
        row = ranking[w]
        cls = " warn-row" if w == "0.15" else ""
        rows.append(
            f'<tr class="{cls.strip()}"><td class="tk-cell"><span class="tk-name">{fnum(row["satellite_weight"]*100,0)}%</span></td>'
            f'<td class="num">{fnum(row["expected_sharpe"],4,signed=True)}</td>'
            f'<td class="num">{fnum(row["expected_cagr_pct"],2,signed=True)}%</td>'
            f'<td class="num">{fnum(row["worst_case_crisis_mdd"],2)}%</td></tr>'
        )
    return "".join(rows)


def h25_episode_rows():
    rows = []
    for ep in EP_ORDER:
        v = H25_RAW[ep]
        fp = v["metrics"]["full_period"]
        cw = v["metrics"].get("crisis_window")
        cw_with = cw["with_filter"]["sharpe"] if cw else None
        cw_without = cw["without_filter"]["sharpe"] if cw else None
        rows.append(
            f'<tr><td class="tk-cell"><span class="tk-name">{esc(EP_LABEL[ep])}</span></td>'
            f'<td class="num">{fnum(fp["with_filter"]["sharpe"],2,signed=True)}</td>'
            f'<td class="num">{fnum(fp["without_filter"]["sharpe"],2,signed=True)}</td>'
            f'<td class="num">{fnum(cw_with,2,signed=True) if cw_with is not None else "—"}</td>'
            f'<td class="num">{fnum(cw_without,2,signed=True) if cw_without is not None else "—"}</td>'
            f'<td class="num">{fnum(fp["with_filter"]["mdd"],1)}%</td>'
            f'<td class="num">{fnum(fp["without_filter"]["mdd"],1)}%</td></tr>'
        )
    return "".join(rows)


def h25_scenario_rows():
    rows = []
    label = {"base": "기본", "calm_heavy": "평온중시", "crisis_heavy": "위기중시"}
    for sk in ["base", "calm_heavy", "crisis_heavy"]:
        ev = H25["scenarios"][sk]["expected_value"]
        winner = H25["scenarios"][sk]["winner"]
        rows.append(
            f'<tr><td class="tk-cell"><span class="tk-name">{label[sk]}</span></td>'
            f'<td class="num">{fnum(ev["with_filter"]["sharpe"],4,signed=True)}</td>'
            f'<td class="num">{fnum(ev["without_filter"]["sharpe"],4,signed=True)}</td>'
            f'<td class="num">{fnum(ev["with_filter"]["worst_case_crisis_mdd"],2)}%</td>'
            f'<td class="num">{fnum(ev["without_filter"]["worst_case_crisis_mdd"],2)}%</td>'
            f'<td>{"필터없음" if winner=="without_filter" else "필터있음"}</td></tr>'
        )
    return "".join(rows)


H24_BASE_WINNER = H24["scenarios"]["base"]["ranking_by_expected_sharpe"][0]
H25_BASE = H25["scenarios"]["base"]["expected_value"]

HTML = f"""<title>새틀라이트 비중·코어 시장필터 기댓값 재검증</title>
<style>
{CSS}
</style>

<div class="masthead">
  <div class="masthead-inner">
    <div class="masthead-eyebrow">
      <span>QUANT RESEARCH NOTE</span><span class="dot">·</span><span>12라운드</span><span class="dot">·</span><span>Hypothesis-Driven Study</span>
    </div>
    <h1 class="masthead-title">챔피언의 시장필터 자체도 기댓값에서 진다</h1>
    <p class="masthead-sub">작업39(H22)가 새틀라이트 레벨 스위치(SPY스위치·VIX스위치·하이브리드)를
      전부 정적보유에 지게 만들었던 바로 그 기댓값 렌즈를, 트랙B의 가장 근본적인 설계 — 챔피언
      17자산 코어 자체의 이진 시장필터(SPY&lt;200일선 → 50% 축소) — 에 처음으로 적용했다. 결과는
      같은 패턴의 반복이다: <b>필터 없이 항상 완전투자하는 쪽이 세 시나리오 전부에서 기댓값
      샤프가 더 높다.</b> 새틀라이트 비중(H24)은 반대로 스윕 범위(0~50%) 안에서 기댓값이 계속
      단조증가해, 15%가 정점이 아니라 더 넓은 범위 재검증이 필요함을 보여줬다.</p>
    <div class="masthead-meta">
      <span><b>방법론</b> H22와 동일한 기저확률 가중 기댓값(base/calm_heavy/crisis_heavy)</span>
      <span><b>6개 창</b> 전체기간 2019-2026 + 2008/COVID/2022/2018/2015-16</span>
      <span><b>비고</b> 원 에이전트가 세션 한도로 리포트 빌드 직전 중단, 오케스트레이터가
        h24/h25_results.json + report_data.json을 그대로 읽어 리포트만 완성</span>
    </div>
  </div>
</div>

<div class="wrap">

  <nav class="toc">
    <a href="#scope">00 문제 제기</a>
    <a href="#h24">01 H24 — 새틀라이트 비중 기댓값 재검증</a>
    <a href="#h25">02 H25 — 코어 시장필터도 기댓값에서 지는가</a>
    <a href="#synthesis">03 종합</a>
    <a href="#limitations">04 한계</a>
  </nav>

  <section class="section" id="scope">
    <h2><span class="sec-no">00</span> 문제 제기 — 아직 손 안 댄 두 근본 설계</h2>
    <p class="lede">작업39(H22)는 새틀라이트 레벨의 스위치·청산 메커니즘(작업33~38에서 쌓아온
      전부)이 기댓값 기준으로는 정적보유에 진다는 걸 보였다. 하지만 그 시리즈는 새틀라이트
      "비중"(작업31/H5가 강세장 편향 단일창에서 15~20%로 골랐던 값)과, 애초에 트랙B 전체의
      출발점이었던 챔피언 코어 자체의 시장필터는 한 번도 이 렌즈로 재검증하지 않았다. 이 라운드는
      그 두 근본 질문을 오케스트레이터가 직접 위임한 가설(H24/H25)로 다룬다.</p>
  </section>

  <section class="section" id="h24">
    <h2><span class="sec-no">01</span> H24 — 새틀라이트 비중 자체의 기댓값 재검증</h2>
    <p class="lede">코어(필터 포함, 현재 챔피언 그대로)+새틀라이트(H10/H18이 확정한 트렌드추종
      정적보유 방식)를 비중 0~50%로 스윕해 6개 창 전부에 적용, H22의 기저확률 가중을 그대로
      적용했다.</p>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>새틀라이트 비중</th><th>기대 샤프(기본)</th><th>기대 CAGR</th><th>최악 위기창 MDD</th></tr></thead>
        <tbody>{h24_sweep_rows('base')}</tbody>
      </table>
    </div>
    <div class="callout warn">
      <div class="callout-title">15%는 정점이 아니다 — 스윕 범위 끝(50%)까지 단조증가</div>
      <p>기본 시나리오에서 기대 샤프는 비중을 늘릴수록 계속 증가해 스윕 상한인
        {fnum(float(H24_BASE_WINNER[0])*100,0)}%에서
        최댓값({fnum(H24_BASE_WINNER[1],4,signed=True)})을 찍는다 — 평온중시·위기중시 시나리오도
        동일한 패턴이다. 기존 15% 기본값(작업31/H5가 강세장 편향 단일 전체기간에서 "정점"으로 골랐던
        값)은 이 6개 창 가중 기댓값 관점에서는 스윕 구간 내 최적점이 아니라, 그저 위험(최악 위기창
        MDD가 15%에서 -16.15%, 50%에서 -45.16%로 3배 가까이 악화)을 억누른 보수적 선택이었다는 게
        드러난다. <b>즉 15%는 "기댓값 최적"이 아니라 "리스크 예산 제약 아래의 타협점"으로 재해석해야
        한다</b> — 순수 기댓값만 극대화하려면 50% 이상까지 계속 올리는 게 유리해 보이지만, 그만큼
        꼬리위험도 커지므로 스윕 범위를 더 넓혀 진짜 정점(있다면)을 찾는 게 다음 과제다.</p>
    </div>
  </section>

  <section class="section" id="h25">
    <h2><span class="sec-no">02</span> H25 — 코어 시장필터도 기댓값에서 지는가</h2>
    <p class="lede">챔피언 17자산 코어를 이진 시장필터 유/무 두 버전으로 나눠(그 외 유니버스·랭킹·
      리밸런싱은 완전히 동일) 6개 창 전부에서 실행했다. 위기창이 있는 창은 전체기간과 위기
      서브윈도우 둘 다 지표를 냈다.</p>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>창</th><th>전체기간 샤프(필터有)</th><th>전체기간 샤프(필터無)</th>
          <th>위기창 샤프(필터有)</th><th>위기창 샤프(필터無)</th><th>MDD(필터有)</th><th>MDD(필터無)</th></tr></thead>
        <tbody>{h25_episode_rows()}</tbody>
      </table>
    </div>
    <h3>기저확률 가중 기댓값</h3>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>시나리오</th><th>기대 샤프(필터有)</th><th>기대 샤프(필터無)</th>
          <th>최악 위기창 MDD(필터有)</th><th>최악 위기창 MDD(필터無)</th><th>승자</th></tr></thead>
        <tbody>{h25_scenario_rows()}</tbody>
      </table>
    </div>
    <div class="callout warn">
      <div class="callout-title">필터 없음이 세 시나리오 전부에서 이긴다</div>
      <p>기본 시나리오 기대 샤프는 필터 있음 {fnum(H25_BASE["with_filter"]["sharpe"],4,signed=True)}
        vs 필터 없음 {fnum(H25_BASE["without_filter"]["sharpe"],4,signed=True)}로, 새틀라이트
        스위치들과 정확히 같은 패턴(자주 오는 평상시엔 필터가 손해, 드문 위기에만 도움)이 트랙B의
        가장 근본적인 설계에서도 반복된다. 다만 창별로 뜯어보면 균일하지 않다 — <b>2008 GFC는
        필터가 전체기간·위기창 둘 다에서 확실히 이긴다</b>(1.00 vs 0.75, 위기창 0.46 vs 0.30,
        MDD도 훨씬 방어적). 반면 <b>COVID 위기창에서는 필터가 크게 진다</b>(0.13 vs 0.77) — SPY
        200일선이라는 느린 추세신호가 몇 주짜리 수직급락에 못 따라간다는, 작업38(VIX 연구)이 이미
        확인한 사각지대가 코어 필터 자체에서도 그대로 나타난다. 위기 유형에 따라 필터의 유불리가
        갈린다는 게 15라운드(H30)~19라운드(H34)가 반복해서 찾아낸 "평균적으로는 손해, 특정 유형의
        위기에서만 확실히 이득"이라는 패턴과 완전히 일관된다.</p>
    </div>
  </section>

  <section class="section" id="synthesis">
    <h2><span class="sec-no">03</span> 종합</h2>
    <p>이 라운드는 트랙D가 새틀라이트 레벨에서 반복해서 찾아낸 결론("평상시엔 잃고 위기엔 버는
      정적 필터는 기댓값에서 진다")이 <b>코어 자체의 필터에도 똑같이 적용된다</b>는 걸 처음으로
      확인했다 — 이건 이 연구 프로그램 전체의 출발점(트랙B, 작업19~21)이 세운 가장 오래된 설계
      선택에 대한 정직한 재검토다. 다만 H33/H34(블록부트스트랩)가 이미 보여줬듯, "가중치만
      흔든" 이 결과의 승률도 표본오차까지 결합하면 상당히 약해질 가능성이 높다 — H25는 아직 그
      감사를 받지 않았다(05절 한계 참고). H24는 반대로 "15%가 최적"이라는 기존 믿음이 사실은
      리스크 선호를 반영한 임의의 선택이었을 뿐, 순수 기댓값 관점에서는 더 큰 비중이 유리해
      보인다는 걸 드러냈다 — 이 역시 꼬리위험을 얼마나 감내할지에 대한 가치판단이 필요한
      문제이지, "정답"이 있는 문제가 아니다.</p>
    <p>실무적 결론: (1) 챔피언의 시장필터는 "위기 방어용 보험"으로는 여전히 의미가 있지만
      (특히 2008형 완만위기), "기댓값을 높이는 장치"라는 프레이밍은 새틀라이트 스위치들과
      마찬가지로 정확하지 않다 — 다만 지금까지의 감사 경험상(H30·H33·H34) 이 방향도 표본오차를
      더하면 확신이 크게 줄어들 가능성이 높으므로, 다음 라운드에서 H25에도 같은 블록부트스트랩
      감사를 적용해볼 필요가 있다. (2) 새틀라이트 비중 15%는 "기댓값 최적"이 아니라 리스크
      예산상의 보수적 선택으로 재규정해야 하고, 더 넓은 스윕(50%를 넘어)으로 진짜 정점을 찾는
      게 남은 과제다.</p>
  </section>

  <section class="section" id="limitations">
    <h2><span class="sec-no">04</span> 한계</h2>
    <ul>
      <li>H24의 스윕 범위(0~50%)가 기본 시나리오에서 단조증가로 끝나 진짜 정점을 못 찾았다 —
        더 넓은 범위(예: 60~100%)로 재검증이 필요하다.</li>
      <li>H25의 "필터 없음이 이긴다"는 결과는 H22/H26/H28/H32와 달리 아직 블록부트스트랩
        표본오차 감사(H33/H34 방법론)를 거치지 않았다 — 지금까지의 패턴(가중치만으로는 90%대
        확신이던 판정들이 표본오차 결합 시 50%대로 떨어짐)을 감안하면, 이 "필터 없음 승리"도
        비슷하게 약화될 가능성이 높다.</li>
      <li>이 라운드는 원래 위임됐던 에이전트가 세션 한도로 중단된 뒤 계산 결과(h24/h25_results.json,
        report_data.json)만 남기고 최종 리포트를 빌드하지 못한 채 4일 이상 방치돼 있던 것을
        오케스트레이터가 직접 리포트만 작성해 완성한 것이다 — 계산 자체(백테스트 실행)는 원
        에이전트가 수행했고, 오케스트레이터는 그 결과를 검증 후 서술·시각화만 담당했다.</li>
      <li>H25의 필터는 "SPY&lt;200일선 → 50% 축소"라는 특정 규칙 하나만 테스트했다 — 축소 비율
        자체(50%가 아니라 25%나 75%였다면)를 스윕하는 건 이번 범위 밖이다.</li>
    </ul>
  </section>

</div>

<footer>
  <p>QUANT RESEARCH · 12라운드 · H24 새틀라이트 비중 + H25 코어 시장필터 기댓값 재검증 ·
    이 문서는 투자 조언이 아니며 저자 개인의 연구 기록입니다.</p>
</footer>
"""

with open(f"{OUT_DIR}/final_report.html", "w", encoding="utf-8") as f:
    f.write(HTML)
print("wrote", f"{OUT_DIR}/final_report.html")
