#!/usr/bin/env python3
"""report_data.json을 읽어 final_report.html을 만든다. 디자인 시스템은 트랙D 리포트들과 동일
(다크네이비/올리브 톤, 세리프 헤드라인, TOC, 섹션 번호, 판정 배지) — 새로 만들지 않고
analysis/2026-08-24_bootstrap_confidence_audit_remaining_verdicts/build_report.py의 CSS를 그대로
재사용한다.

이 리포트는 리서치 에이전트 D(전략 구성가) 라운드 1의 결과다 — 새 전략을 발명하지 않고, 이미
라이브인 core/champion_strategy.py의 두 기본 구성(코어단독 / 코어+새틀라이트)을 "월 1~3회 매매"
제약 관점에서 실측 비교한다."""
import json
import math
import os

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
with open(f"{OUT_DIR}/report_data.json", encoding="utf-8") as f:
    R = json.load(f)

META = R["meta"]
C1 = R["candidate_1_core_only"]
C2 = R["candidate_2_core_satellite"]
SPY = R["spy_buyhold"]
PERM = R["permutation_test_candidate_1"]
BOOT = R["bootstrap_audit"]


def fnum(v, digits=2, signed=False):
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
.table-wrap{ overflow-x:auto; border:1px solid var(--hairline); border-radius:8px; background:var(--surface); }
table.data-table{ width:100%; border-collapse:collapse; font-size:13.5px; min-width:640px; }
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
.confidence-grade{ display:inline-block; font-size:12px; font-weight:700; padding:2px 9px; border-radius:4px; }
.grade-A{ background: var(--accent-soft); color:var(--accent); }
.grade-B{ background: var(--accent-2-soft); color:var(--accent-2); }
.grade-C{ background: rgba(179,38,30,0.10); color:var(--delta-neg); }
"""

FREQ_OK_C1 = 1.0 <= C1["trades_per_month"] <= 3.0
FREQ_OK_C2 = 1.0 <= C2["trades_per_month"] <= 3.0


def freq_badge(ok):
    return '<span class="verdict-badge v-accept">제약 충족</span>' if ok else '<span class="verdict-badge v-reject">제약 초과</span>'


def metrics_row(label, m, trades_per_month, freq_ok):
    return (
        f'<tr><td class="tk-cell"><span class="tk-name">{esc(label)}</span></td>'
        f'<td class="num">{fnum(trades_per_month,2)}</td>'
        f'<td class="num">{fnum(m["cagr"],2)}%</td>'
        f'<td class="num">{fnum(m["mdd"],2)}%</td>'
        f'<td class="num">{fnum(m["sharpe"],2)}</td>'
        f'<td class="num">{fnum(m["calmar"],2)}</td>'
        f'<td>{freq_badge(freq_ok)}</td></tr>'
    )


def boot_row(cfg, label):
    d = BOOT["by_config"][cfg]
    b20 = d["bootstrap_by_block_len"]["20"]
    return (
        f'<tr><td class="tk-cell"><span class="tk-name">{esc(label)}</span></td>'
        f'<td class="num">{d["n_obs"]}</td>'
        f'<td class="num">{fnum(d["point_estimate_sharpe"],3,signed=True)}</td>'
        f'<td class="num">[{fnum(b20["ci90"][0],3,signed=True)}, {fnum(b20["ci90"][1],3,signed=True)}]</td></tr>'
    )


PERM_PASS = PERM["p_value"] is not None and PERM["p_value"] < 0.05
WIN_RATE_C2_VS_C1 = BOOT["candidate2_vs_candidate1_win_rate_L20"]

HTML = f"""<title>전략 후보 라운드 1 — 매매빈도 실측</title>
<style>
{CSS}
</style>

<div class="masthead">
  <div class="masthead-inner">
    <div class="masthead-eyebrow">
      <span>QUANT R&amp;D · 에이전트 D</span><span class="dot">·</span><span>라운드 1</span><span class="dot">·</span><span>Strategy Candidate Construction</span>
    </div>
    <h1 class="masthead-title">기존 챔피언 구조 중 어느 쪽이 "월 1~3회" 제약에 맞는가</h1>
    <p class="masthead-sub">새 전략을 발명하지 않는다 — <code>core/champion_strategy.py</code>가 이미 라이브로
      쓰는 두 기본 구성(코어 단독 vs 코어+15% 반기 새틀라이트)을 실제 과거 데이터로 돌려 "월평균 매매 횟수"를
      처음으로 실측하고, 여기에 순열검정(무작위선택 대비)과 블록부트스트랩(표본오차) 감사를 더했다.</p>
    <div class="masthead-meta">
      <span><b>백테스트 구간</b> {esc(C1['start'])} ~ {esc(C1['end'])} ({fnum(R['n_months_in_period'],1)}개월)</span>
      <span><b>순열검정</b> {META['n_permutations']}회, seed={META['seed']}</span>
      <span><b>블록부트스트랩</b> {META['n_boot']:,}회 × L={', '.join(str(x) for x in META['block_lengths'])}일</span>
      <span><b>총 실행시간</b> {fnum(R.get('total_runtime_sec'),0)}초</span>
    </div>
  </div>
</div>

<div class="wrap">

  <nav class="toc">
    <a href="#scope">00 문제 제기</a>
    <a href="#candidates">01 후보 정의</a>
    <a href="#trades">02 매매빈도 + 성과 실측</a>
    <a href="#permutation">03 순열검정</a>
    <a href="#bootstrap">04 블록부트스트랩</a>
    <a href="#verdict">05 결론</a>
    <a href="#limitations">06 한계</a>
  </nav>

  <section class="section" id="scope">
    <h2><span class="sec-no">00</span> 문제 제기</h2>
    <p class="lede">사용자는 실제로 월 1회, 많아야 3회 정도만 매매하는 스윙 트레이딩을 원한다.
      <code>analysis/2026-09-05_research_program_synthesis/</code>가 49개 작업을 종합해 확정한
      "챔피언" 시스템(17자산 코어 로테이션 + 선택적 15% 새틀라이트)은 구조적으로 이미 이 빈도에
      가깝지만, 지금까지 이 저장소의 어떤 리포트도 "실제로 한 달에 몇 번 주문이 나가는지"를
      직접 세어본 적이 없다 — 전부 회전율(turnover, 비중 변화의 절대값 합)이나 샤프/CAGR만
      보고했다. 이 라운드는 정확히 그 공백을 메운다: 새 파라미터를 발명하지 않고, 라이브 기본값
      그대로인 두 구성을 백테스트해 종목별 진입/청산/재조정이 발생한 날짜를 세어 "월평균 매매
      횟수"를 처음으로 실측한다.</p>
    <p class="caveat">투자 조언이 아니다. confidence_table 기준 코어 17자산 유니버스는 강건, 12개월
      모멘텀 랭킹과 새틀라이트 정적보유는 보통 등급이지만, 리밸런싱 주기·이진 시장필터·새틀라이트
      포함 여부 자체는 약함 등급이다 — 두 후보 모두 이미 라이브 기본값이므로 이 등급들을 그대로
      상속한다(아래에서 숨기지 않는다).</p>
  </section>

  <section class="section" id="candidates">
    <h2><span class="sec-no">01</span> 후보 정의 — 새로 만들지 않고 이미 있는 두 기본값을 비교</h2>
    <h3>후보 1 — 코어 단독</h3>
    <p>17자산(11개 GICS 섹터 ETF + TLT/IEF + GLD + EFA + HYG + DBC) 유니버스에서 12개월 트레일링
      모멘텀 상위 4개(양(+)모멘텀 통과 종목 중) 동일비중, 월간(매월 첫 거래일) 리밸런싱, SPY 200일선
      하회 시 코어 비중 50% 축소. 새틀라이트 없음 — <code>run_core_backtest()</code> 기본값 그대로.</p>
    <h3>후보 2 — 코어 + 새틀라이트</h3>
    <p>후보 1과 완전히 동일한 코어에 더해, 코어의 15%를 point-in-time 40종목 풀에서 돈치안 20일
      브레이크아웃+15% 트레일링스탑이 활성인 종목 중 12개월 모멘텀 상위 3개로 구성한 새틀라이트를
      1월/7월 첫 거래일 반기 리밸런싱으로 얹는다 — <code>run_champion_backtest()</code> 기본값
      그대로.</p>
  </section>

  <section class="section" id="trades">
    <h2><span class="sec-no">02</span> 매매빈도 + 성과 실측</h2>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>후보</th><th>월평균 매매횟수</th><th>CAGR</th><th>MDD</th><th>샤프</th><th>칼마</th><th>매매빈도 제약(1~3회/월)</th></tr></thead>
        <tbody>
          {metrics_row('후보1 — 코어 단독', C1['metrics'], C1['trades_per_month'], FREQ_OK_C1)}
          {metrics_row('후보2 — 코어+새틀라이트', C2['metrics'], C2['trades_per_month'], FREQ_OK_C2)}
          {metrics_row('참고 — SPY 매수보유', SPY['metrics'], 0.0, True)}
        </tbody>
      </table>
    </div>
    <p class="caveat">매매횟수는 "회전율"이 아니라 실제 주문 발생 건수다 — 종목별 목표비중이 바뀌는
      날마다(신규 진입/청산/시장필터로 인한 기존 보유분 비중 조정 포함) 종목 1개당 1건으로 센다.
      후보1은 총 {C1['trades']['total_trades']}건/{fnum(R['n_months_in_period'],1)}개월, 후보2는
      코어 {C2['core_trades']['total_trades']}건 + 새틀라이트 {C2['satellite_trades']['total_trades']}건
      = 총 {C2['total_trades']}건/{fnum(R['n_months_in_period'],1)}개월.</p>
  </section>

  <section class="section" id="permutation">
    <h2><span class="sec-no">03</span> 순열검정 — 후보1 코어 로테이션이 무작위선택보다 나은가</h2>
    <p class="lede">작업21(No.06)이 이 멀티에셋 로테이션에 처음 적용했던 방법론을 이번 후보의 정확한
      백테스트 구간·설정으로 재구현했다: 매달 "양(+)모멘텀 후보 중 무작위 4개"를 뽑되 시장필터/비용
      모델/리밸런싱 스케줄은 실제 후보1과 완전히 동일하게 유지한 가짜 전략을 {PERM['n_permutations']}회
      돌려 샤프 분포를 만들고, 실제 모멘텀 랭킹 기반 샤프({fnum(PERM['actual_sharpe'],3)})가 그 분포
      어디에 위치하는지 본다.</p>
    <div class="kpi-row">
      <div class="kpi-tile"><div class="kpi-label">실제 샤프</div><div class="kpi-value">{fnum(PERM['actual_sharpe'],3)}</div></div>
      <div class="kpi-tile"><div class="kpi-label">무작위 {PERM['n_permutations']}회 평균±표준편차</div>
        <div class="kpi-value">{fnum(PERM['permuted_mean'],3)} ± {fnum(PERM['permuted_std'],3)}</div></div>
      <div class="kpi-tile"><div class="kpi-label">백분위</div><div class="kpi-value">{fnum(PERM['percentile'],1)}</div></div>
      <div class="kpi-tile"><div class="kpi-label">p-value</div>
        <div class="kpi-value {'pos' if PERM_PASS else 'neg'}">{fnum(PERM['p_value'],4)}</div></div>
    </div>
    <div class="callout {''  if PERM_PASS else 'warn'}">
      <div class="callout-title">{'무작위선택 대비 통계적으로 유의미' if PERM_PASS else '무작위선택과 통계적으로 구별 안 됨'}</div>
      <p>{'모멘텀 랭킹이 이 구간에서 무작위 선택보다 유의미하게(p<0.05) 낫다 — 이 결과는 confidence_table의 기존 moderate 등급 판정(작업21, p≈0.025)과 방향이 일치한다.' if PERM_PASS else '이 구간·설정에서는 모멘텀 랭킹과 무작위선택의 차이가 통계적으로 유의하지 않다 — confidence_table의 moderate 등급(근소한 우위)과 일관된 결과로, "강건"으로 올려 부를 근거는 아니다.'}</p>
    </div>
  </section>

  <section class="section" id="bootstrap">
    <h2><span class="sec-no">04</span> 블록부트스트랩 — 표본오차 감사</h2>
    <p class="lede">작업44/45(H33/H34)와 동일 방법론(순환 이동블록부트스트랩, 블록길이
      {', '.join(str(x)+'일' for x in META['block_lengths'])}, {META['n_boot']:,}회)을 두 후보와
      SPY 매수보유 각각의 일별 순수익률에 적용한다.</p>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>구성</th><th>n_obs(거래일)</th><th>점추정 샤프</th><th>90% 부트스트랩 CI (L=20)</th></tr></thead>
        <tbody>
          {boot_row('candidate_1_core_only', '후보1 — 코어 단독')}
          {boot_row('candidate_2_core_satellite', '후보2 — 코어+새틀라이트')}
          {boot_row('spy_buyhold', 'SPY 매수보유')}
        </tbody>
      </table>
    </div>
    <div class="callout">
      <div class="callout-title">후보2(코어+새틀라이트)가 후보1(코어단독)을 이기는 빈도</div>
      <p>같은 L=20 부트스트랩 표본을 페어로 비교하면 후보2의 샤프가 후보1보다 높게 나오는 비율은
        <b>{pct(WIN_RATE_C2_VS_C1,1) if WIN_RATE_C2_VS_C1 is not None else '계산불가'}</b>다 —
        confidence_table의 "새틀라이트 포함 여부" 약함 등급과 일관되게, 새틀라이트를 더하는 게
        확실한 우위라고 말하기는 어렵다.</p>
    </div>
  </section>

  <section class="section" id="verdict">
    <h2><span class="sec-no">05</span> 결론</h2>
    <div class="callout">
      <div class="callout-title">매매빈도 제약 관점 최종 판정</div>
      <p>후보1(코어 단독)의 월평균 매매횟수는 <b>{fnum(C1['trades_per_month'],2)}건</b>,
        후보2(코어+새틀라이트)는 <b>{fnum(C2['trades_per_month'],2)}건</b>이다. 사용자 제약(월 1~3회)
        기준으로 {"후보1과 후보2 둘 다 제약을 충족한다" if FREQ_OK_C1 and FREQ_OK_C2 else ("후보1만 제약을 충족한다" if FREQ_OK_C1 and not FREQ_OK_C2 else ("후보2만 제약을 충족한다" if FREQ_OK_C2 and not FREQ_OK_C1 else "두 후보 모두 제약을 벗어난다"))}.</p>
    </div>
  </section>

  <section class="section" id="limitations">
    <h2><span class="sec-no">06</span> 한계</h2>
    <ul>
      <li>매매횟수 산식은 "목표비중이 바뀐 종목 수"를 그대로 세므로, 시장필터가 켜지고 꺼질 때
        기존 보유 4종목 전부의 비중이 동시에 바뀌는 것도 4건으로 잡는다 — 실제로는 브로커에 따라
        "리밸런싱 1건"으로 취급될 수도 있어 이 수치는 다소 보수적(과대) 추정일 수 있다.</li>
      <li>새틀라이트 point-in-time 유니버스 스캔 중 데이터 제공자(yfinance) 레이트리밋으로 일부
        후보 종목의 가격 이력을 못 받아온 경우가 있었다 — 코드가 실패한 종목을 건너뛰는 방식으로
        설계돼 있어 계산 자체는 완료됐지만, 일부 반기 시점의 후보 풀이 이론상 40종목보다 적었을 수
        있다(라이브 추천에서도 동일하게 발생 가능한 알려진 제약).</li>
      <li>순열검정은 후보1의 코어 로테이션 선택 스텝에만 적용했다 — 새틀라이트의 돈치안+트레일링스탑
        선정 로직 자체의 순열검정은 이번 라운드에서 재수행하지 않았다(작업20의 h9 placebo 감사가
        이미 weak 등급으로 결론지은 바 있어 confidence_table을 그대로 인용).</li>
      <li>블록부트스트랩의 후보2 vs 후보1 승률은 같은 기간의 두 시계열을 정확히 페어링(같은 날짜의
        블록)하지 않고 각자의 L=20 부트스트랩 표본을 독립적으로 비교했다 — 두 전략이 코어를 공유해
        수익률이 상관돼 있다는 사실을 반영하지 않으므로, 실제 격차의 불확실성은 이 수치보다 더 좁을
        수도 넓을 수도 있다.</li>
      <li>이 라운드는 비용모델(왕복 0.1%)을 그대로 썼다 — 실제 세금/슬리피지 반영 감사는 에이전트 F의
        몫이다.</li>
    </ul>
  </section>

</div>

<footer>
  <p>QUANT R&amp;D · 에이전트 D(전략 구성가) · 라운드 1 · 기준일 {esc(META['generated'])} ·
    이 문서는 투자 조언이 아니며 저자 개인의 연구 기록입니다.</p>
</footer>
"""

with open(f"{OUT_DIR}/final_report.html", "w", encoding="utf-8") as f:
    f.write(HTML)
print("[build_report] saved final_report.html")
