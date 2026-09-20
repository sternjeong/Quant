#!/usr/bin/env python3
"""report_data.json을 읽어 final_report.html을 만든다.

analysis/2026-08-30_track_c_bootstrap_confidence_audit/build_report.py 와 동일한 디자인
시스템(다크네이비/올리브 톤, 세리프 헤드라인, TOC, 섹션 번호, 판정 배지)을 그대로 재사용한다 —
같은 트랙C 감사 계열 리포트라 시각적 연속성을 유지한다.
"""
import json
import math
import os

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

with open(f"{OUT_DIR}/report_data.json", encoding="utf-8") as f:
    R = json.load(f)

GEN = R["meta"]["generated"]
IREN = R["iren_reference"]
BASKETS = R["baskets"]
BASKET_ORDER = ["shipping", "cannabis", "solar"]


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
    return f"{v * 100:.{digits}f}%"


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def grade_badge(text, tone="moderate"):
    cls = {"robust": "grade-A", "moderate": "grade-B", "weak": "grade-C"}.get(tone, "grade-B")
    return f'<span class="confidence-grade {cls}">{esc(text)}</span>'


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
.wrap{ max-width: 1060px; margin:0 auto; padding: 0 24px 96px; }
.masthead{ background: var(--accent); color: var(--accent-ink); padding: 56px 24px 40px; }
.masthead-inner{ max-width:1060px; margin:0 auto; }
.masthead-eyebrow{ font-size:12.5px; letter-spacing:0.12em; text-transform:uppercase; opacity:0.82;
  font-family: ui-monospace, "SF Mono", Consolas, monospace; display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
.masthead-eyebrow .dot{ opacity:0.5; }
h1.masthead-title{ font-family:"Iowan Old Style","Palatino Linotype", Georgia, serif; font-weight:600;
  font-size: clamp(28px, 4.2vw, 44px); line-height:1.15; margin: 14px 0 10px; text-wrap: balance; max-width: 34ch; }
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
footer{ max-width:1060px; margin:40px auto 0; padding: 26px 24px 10px; border-top:1px solid var(--hairline);
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

BASKET_LABEL = {"shipping": "해운 슈퍼사이클", "cannabis": "대마초 구조적 하락", "solar": "태양광/클린에너지"}


def perf_table_rows(name):
    d = BASKETS[name]
    rep = d["representative"]
    rows = []
    rows.append(("SPY (동일 공통구간)", d["spy_buy_hold_common_window"]))
    rows.append((f"{rep} 단일 매수후보유", d["representative_buy_hold_common_window"]))
    rows.append(("바스켓 정적 매수후보유", d["basket_static_buy_hold"]))
    rows.append(("바스켓 내 모멘텀 로테이션", d["momentum_rotation"]))
    rows.append((f"추세추종 단일({rep})", d["trend_following_single"]))
    rows.append(("추세추종 바스켓 (챔피언 규칙)", d["trend_following_basket"]))
    html = []
    best_sharpe = max(r[1]["sharpe"] for r in rows)
    for label, m in rows:
        cls = " hero-row" if m["sharpe"] == best_sharpe else ""
        html.append(
            f'<tr class="{cls.strip()}"><td class="tk-cell"><span class="tk-name">{esc(label)}</span></td>'
            f'<td class="num">{fnum(m["cumulative_return"],1,True)}%</td>'
            f'<td class="num">{fnum(m["cagr"],1,True)}%</td>'
            f'<td class="num">{fnum(m["mdd"],1)}%</td>'
            f'<td class="num strong">{fnum(m["sharpe"],2)}</td>'
            "</tr>"
        )
    return "".join(html)


def _unwrap_metrics(d):
    return d["metrics"] if "metrics" in d else d


def iren_perf_rows():
    rows = [
        ("SPY (동일 공통구간)", _unwrap_metrics(IREN["spy_buy_hold"])),
        ("바스켓 정적 매수후보유", _unwrap_metrics(IREN["basket_static_buy_hold"])),
        ("바스켓 내 모멘텀 로테이션", _unwrap_metrics(IREN["momentum_rotation"])),
        ("추세추종 단일(IREN)", _unwrap_metrics(IREN["trend_following_single"])),
        ("추세추종 바스켓 (챔피언)", _unwrap_metrics(IREN["trend_following_basket"])),
    ]
    html = []
    best_sharpe = max(r[1]["sharpe"] for r in rows)
    for label, m in rows:
        cls = " hero-row" if m["sharpe"] == best_sharpe else ""
        html.append(
            f'<tr class="{cls.strip()}"><td class="tk-cell"><span class="tk-name">{esc(label)}</span></td>'
            f'<td class="num">{fnum(m["cumulative_return"],1,True)}%</td>'
            f'<td class="num">{fnum(m["cagr"],1,True)}%</td>'
            f'<td class="num">{fnum(m["mdd"],1)}%</td>'
            f'<td class="num strong">{fnum(m["sharpe"],2)}</td>'
            "</tr>"
        )
    return "".join(html)


def permutation_summary_rows():
    rows = []
    rows.append(("IREN (AI 피벗, 기준선)", IREN["permutation_basket"]["percentile"], IREN["permutation_basket"]["p_value"],
                  IREN["permutation_single"]["percentile"], IREN["permutation_single"]["p_value"]))
    for name in BASKET_ORDER:
        a = BASKETS[name]["audit"]
        rows.append((BASKET_LABEL[name], a["permutation_basket"]["percentile"], a["permutation_basket"]["p_value"],
                     a["permutation_single"]["percentile"], a["permutation_single"]["p_value"]))
    html = []
    for label, bp, bpv, sp, spv in rows:
        sig_b = bpv <= 0.05
        sig_s = spv <= 0.05
        cls = " hero-row" if label.startswith("IREN") else ""
        html.append(
            f'<tr class="{cls.strip()}"><td class="tk-cell"><span class="tk-name">{esc(label)}</span></td>'
            f'<td class="num">{fnum(bp,1)}pct</td><td class="num{" strong" if sig_b else ""}">{fnum(bpv,4)}{" ✓" if sig_b else ""}</td>'
            f'<td class="num">{fnum(sp,1)}pct</td><td class="num{" strong" if sig_s else ""}">{fnum(spv,4)}{" ✓" if sig_s else ""}</td></tr>'
        )
    return "".join(html)


def bootstrap_summary_rows():
    rows = []
    ib = IREN["bootstrap_L20"]["basket"]
    is_ = IREN["bootstrap_L20"]["single"]
    rows.append(("IREN 바스켓 (기준선)", ib["mean"], ib["ci90"], ib["pct_le_zero"]))
    rows.append(("IREN 단일 (기준선)", is_["mean"], is_["ci90"], is_["pct_le_zero"]))
    for name in BASKET_ORDER:
        a = BASKETS[name]["audit"]["bootstrap"]
        b20 = a["basket"]["by_block_len"]["20"]
        s20 = a["single"]["by_block_len"]["20"]
        rows.append((f"{BASKET_LABEL[name]} 바스켓", a["basket"]["point_estimate_sharpe"], b20["ci90"], b20["pct_le_zero"]))
        rows.append((f"{BASKET_LABEL[name]} 단일", a["single"]["point_estimate_sharpe"], s20["ci90"], s20["pct_le_zero"]))
    html = []
    for label, point, ci, plez in rows:
        cls = " hero-row" if label.startswith("IREN") else ""
        width = ci[1] - ci[0] if ci and ci[0] is not None else None
        html.append(
            f'<tr class="{cls.strip()}"><td class="tk-cell"><span class="tk-name">{esc(label)}</span></td>'
            f'<td class="num">{fnum(point,3,True)}</td>'
            f'<td class="num">{("[" + fnum(ci[0],2,True) + ", " + fnum(ci[1],2,True) + "]") if ci and ci[0] is not None else "—"}</td>'
            f'<td class="num">{fnum(width,2)}</td>'
            f'<td class="num">{pct(plez,2)}</td></tr>'
        )
    return "".join(html)


def basket_section(name, sec_no):
    d = BASKETS[name]
    rep = d["representative"]
    a = d["audit"]
    tf_b = d["trend_following_basket"]["sharpe"]
    bh_b = d["basket_static_buy_hold"]["sharpe"]
    rot = d["momentum_rotation"]["sharpe"]
    winner = max([("추세추종 바스켓", tf_b), ("정적 매수후보유", bh_b), ("모멘텀 로테이션", rot)], key=lambda x: x[1])
    replicates = tf_b > bh_b and tf_b > rot
    verdict_cls = "v-accept" if replicates else "v-reject"
    verdict_text = "IREN 패턴 재현" if replicates else "IREN 패턴 재현 안 됨"
    return f"""
  <section class="section" id="{name}">
    <h2><span class="sec-no">{sec_no}</span> {BASKET_LABEL[name]} — {esc(d['label'])}</h2>
    <p class="lede">{esc(d['narrative'])}</p>
    <p><b>종목:</b> {', '.join(d['tickers'])} (대표종목 {rep}) · <b>공통시작일</b> {d['common_start']} ~ {d['end']}
      (n≈{a['bootstrap']['basket']['n_obs']}거래일) · <span class="verdict-badge {verdict_cls}">{verdict_text}</span></p>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>구성</th><th>누적수익</th><th>CAGR</th><th>MDD</th><th>샤프</th></tr></thead>
        <tbody>{perf_table_rows(name)}</tbody>
      </table>
    </div>
    <p class="caveat">이 바스켓에서 가장 높은 샤프를 낸 구성은 <b>{winner[0]}</b>(샤프 {fnum(winner[1],2)})다 —
      IREN 연구(작업27)에서는 추세추종 바스켓이 항상 1위였지만, 여기서는 {"그 패턴이 그대로 재현된다" if replicates else "그렇지 않다"}.</p>
  </section>
"""


H_SHIP = BASKETS["shipping"]
H_CAN = BASKETS["cannabis"]
H_SOL = BASKETS["solar"]

HTML = f"""<title>진짜 비-AI 고변동성 대조군 — 변동성모멘텀 효과와 AI테마 효과의 분리</title>
<style>
{CSS}
</style>

<div class="masthead">
  <div class="masthead-inner">
    <div class="masthead-eyebrow">
      <span>QUANT RESEARCH NOTE</span><span class="dot">·</span><span>트랙 C, No.5</span><span class="dot">·</span><span>Hypothesis-Driven Study</span>
    </div>
    <h1 class="masthead-title">변동성 모멘텀 효과인가, AI 테마 효과인가 — 진짜 비-AI 대조군 바스켓 3개로 분리한다</h1>
    <p class="masthead-sub">IREN류 연구(작업27~28, 48)가 스스로 밝힌 빈틈: 지금까지 검토한 모든 고변동성
      후보(MARA·RIOT·Bitfarms 포함)가 사실 전부 AI/HPC로 피벗한 종목이라, "돈치안20+15%트레일링스탑
      추세추종이 통한다"는 결론이 이 규칙 자체의 일반적 효과인지 AI 랠리라는 특정 시대적 순풍의 효과인지
      가릴 대조군이 없었다. 이 리포트는 AI 서사가 전혀 없는 3개의 독립 고변동성 테마
      바스켓(해운 슈퍼사이클·대마초 구조적 하락·태양광 붐-버스트)에 동일한 규칙을 그대로 이식해
      직접 검증한다.</p>
    <div class="masthead-meta">
      <span><b>기준일</b> {esc(GEN)}</span>
      <span><b>순열검정</b> 바스켓당 {R['meta']['n_permutations']}회 셔플</span>
      <span><b>블록부트스트랩</b> 조합당 {R['meta']['n_boot']:,}회, 블록길이 {', '.join(str(x)+'일' for x in R['meta']['block_lengths'])}</span>
      <span><b>대조군</b> 해운·대마초·태양광 (전부 비-AI)</span>
    </div>
  </div>
</div>

<div class="wrap">

  <nav class="toc">
    <a href="#scope">00 문제 제기</a>
    <a href="#shipping">01 해운 슈퍼사이클</a>
    <a href="#cannabis">02 대마초 구조적 하락</a>
    <a href="#solar">03 태양광/클린에너지</a>
    <a href="#permutation">04 순열검정 종합비교</a>
    <a href="#bootstrap">05 블록부트스트랩 종합비교</a>
    <a href="#synthesis">06 종합 — 효과는 일반적인가, AI 특유인가</a>
    <a href="#tension">07 복권주 긴장 관계</a>
    <a href="#limitations">08 한계</a>
  </nav>

  <section class="section" id="scope">
    <h2><span class="sec-no">00</span> 문제 제기 — 왜 지금까지 진짜 대조군이 없었나</h2>
    <p class="lede">iren_volatile_momentum_stocks_research(작업27)는 비트코인 채굴 → AI/HPC 피벗
      바스켓(IREN·CIFR·CLSK·WULF·HUT·BTDR)에서 20일 돈치안 브레이크아웃+15% 트레일링스탑 추세추종이
      정적 매수후보유(샤프 0.88)·바스켓내 모멘텀 로테이션(샤프 0.69)을 모두 제치고 샤프 1.31을
      기록했다고 결론지었다. 순수 무피벗 대조군을 찾으려 했지만 MARA·RIOT·Bitfarms까지 전부 AI로
      피벗 중이라는 사실만 확인하고 대조군 없이 남겨뒀다(작업29). 즉 "이 규칙이 통한 건 규칙 자체가
      좋아서인가, 아니면 그냥 2022~2026년이 AI 인프라 슈퍼사이클이라 무슨 짓을 해도 벌었을 시기라서
      인가"라는 근본 질문에 아직 답한 적이 없다.</p>
    <p>이 리포트는 AI 서사가 전혀 없는(그러나 IREN류처럼 레버리지·변동성·서사 촉매 구조를 공유하는)
      3개 바스켓을 골라 <b>동일한 코드(analysis/2026-08-16_iren_volatile_momentum_stocks/backtest.py의
      donchian_trailing_stop_positions/run_trend_following_single/basket, 새로 발명하지 않음)</b>를
      그대로 실행한다. 방향도 의도적으로 다양화했다 — 해운(붐→버스트, IREN과 같은 방향)·태양광(붐→
      버스트, 더 긴 표본)·대마초(구조적 장기 하락, IREN과 정반대 방향)로, "규율 있는 청산이 상승장
      전용 트릭인지 방향과 무관한 일반 효과인지"까지 함께 가른다.</p>
    <h3>IREN류 바스켓 원본 성과(작업27, 비교 기준선)</h3>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>구성</th><th>누적수익</th><th>CAGR</th><th>MDD</th><th>샤프</th></tr></thead>
        <tbody>{iren_perf_rows()}</tbody>
      </table>
    </div>
    <p class="caveat">공통구간 {IREN['common_start']} ~ {IREN['end']} (≈4.25년). 아래 01~03절에서
      3개 대조군 바스켓에 정확히 같은 구성을 적용한 결과를 이 표와 나란히 비교한다.</p>
  </section>

  {basket_section("shipping", "01")}
  {basket_section("cannabis", "02")}
  {basket_section("solar", "03")}

  <section class="section" id="permutation">
    <h2><span class="sec-no">04</span> 순열검정 종합비교 — IREN 대비 세 대조군의 통계적 유의성</h2>
    <p class="lede">core.backtest_engine._shuffle_daily_bars(작업13/14, 이미 pytest 검증된 공식
      순열검정 인프라)를 코드 그대로 재사용해, 각 바스켓의 추세추종 챔피언 규칙을 200회 셔플 대비
      백분위·p-value로 검정했다. IREN 원본(작업32/H3)의 수치를 기준선으로 나란히 놓는다.</p>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>바스켓</th><th>바스켓 백분위</th><th>바스켓 p-value</th><th>단일종목 백분위</th><th>단일종목 p-value</th></tr></thead>
        <tbody>{permutation_summary_rows()}</tbody>
      </table>
    </div>
    <p class="caveat">✓ 표시는 p≤0.05(95% 유의 문턱 통과)를 뜻한다. IREN 원본도 바스켓 자체는 이 문턱을
      넘지 못했다(p≈0.075) — 단일종목만 넘었다(p≈0.005).</p>
  </section>

  <section class="section" id="bootstrap">
    <h2><span class="sec-no">05</span> 블록부트스트랩 종합비교 — 표본오차(sampling uncertainty)</h2>
    <p class="lede">h33_block_bootstrap_sample_error.moving_block_bootstrap_sharpe(작업44/48과 동일 함수,
      원형 이동블록, 블록길이 10/20/40일, 2000회)를 그대로 재사용해 각 바스켓 추세추종 챔피언의 일별
      전략수익률에 적용했다. 아래는 블록길이 20일(≈1개월) 기준 90% 신뢰구간이다.</p>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>구성</th><th>점추정 샤프</th><th>90% CI (L=20)</th><th>CI 폭</th><th>P(샤프≤0)</th></tr></thead>
        <tbody>{bootstrap_summary_rows()}</tbody>
      </table>
    </div>
  </section>

  <section class="section" id="synthesis">
    <h2><span class="sec-no">06</span> 종합 — 변동성 모멘텀 효과는 일반적인가, AI 테마 특유인가</h2>
    <div class="callout">
      <div class="callout-title">핵심 발견</div>
      <p>3개 비-AI 대조군 중 어느 것도 IREN의 "추세추종 바스켓이 매수후보유와 로테이션을 모두 이긴다"는
        패턴을 온전히 재현하지 못했다. 해운에서는 오히려 <b>바스켓 내 모멘텀 로테이션</b>(샤프
        {fnum(H_SHIP['momentum_rotation']['sharpe'],2)})이 추세추종(샤프
        {fnum(H_SHIP['trend_following_basket']['sharpe'],2)})과 정적 매수후보유(샤프
        {fnum(H_SHIP['basket_static_buy_hold']['sharpe'],2)})를 모두 앞섰다 — IREN 연구가 스스로
        "이 좁고 상관관계 높은 바스켓에서는 로테이션이 안 먹힌다"고 적었던 것과 정반대로, 해운
        5종목은 상관관계가 충분히 낮아 로테이션의 폭(breadth) 이점이 살아났다. 대마초에서는 모든
        구성이 손실을 냈지만(구조적 장기 하락), 추세추종·로테이션은 정적 매수후보유보다 손실을 크게
        줄였다(로테이션 CAGR {fnum(H_CAN['momentum_rotation']['cagr'],1,True)}% vs 정적매수후보유
        {fnum(H_CAN['basket_static_buy_hold']['cagr'],1,True)}%) — "규율 있는 청산이 하락장에서도
        손실제한 효과가 있다"는 방향 무관 일반 효과는 확인됐지만, 이기는 전략으로 바꾸지는 못했다.
        태양광에서는 단일종목 추세추종(ENPH, 샤프 {fnum(H_SOL['trend_following_single']['sharpe'],2)})이
        가장 좋았지만 바스켓 추세추종은 정적 매수후보유를 근소하게만 앞섰다(
        {fnum(H_SOL['trend_following_basket']['sharpe'],2)} vs {fnum(H_SOL['basket_static_buy_hold']['sharpe'],2)}).</p>
      <p>통계적 유의성 관점에서도 IREN의 비대칭(단일종목만 p&lt;0.05, 바스켓은 미달)이 세 대조군
        중 어디에서도 재현되지 않는다 — 위 04/05절 표를 보면 알 수 있듯, 순열검정·블록부트스트랩 둘 다
        바스켓별로 저마다 다른 패턴을 보인다.</p>
    </div>
    <p><b>정직한 결론:</b> IREN류 바스켓에서 관측된 "추세추종 규율이 매수후보유·로테이션을 모두
      이긴다"는 결과는 이 규칙 자체의 보편적 우위라기보다, <b>이 바스켓·이 표본기간(2022-05~2026-08,
      AI 인프라 슈퍼사이클과 정확히 겹침) 고유의 조합 효과일 가능성이 상당하다</b>는 것이 세 독립
      대조군으로 강화됐다. 다만 완전한 반증도 아니다 — 대마초 사례가 보여주듯 "방향과 무관하게
      규율 있는 청산이 손실을 줄인다"는 더 약하지만 더 일반적인 효과는 세 바스켓 모두에서 어느 정도
      확인된다. 즉 트랙C 에이전트 지침이 명시한 긴장("변동성 모멘텀 효과"를 찾고 싶다는 목적과
      "고변동성 종목의 위험조정수익률이 학술적으로 낮다"는 경고 사이의 긴장)이 이번 라운드로
      해소되기는커녕 더 뚜렷해졌다: IREN의 극적인 성과는 재현 가능한 일반 원리라기보다, 특정 시대의
      특정 바스켓에서 관측된 사례일 가능성이 더 커졌다.</p>
  </section>

  <section class="section" id="tension">
    <h2><span class="sec-no">07</span> 복권주(lottery-stock) 긴장 관계 — 이번 라운드가 더한 것</h2>
    <p>학계의 MAX 효과(Bali·Cakici·Whitelaw 2011)·이디오싱크래틱 변동성 퍼즐(Ang 외 2006/2009)은
      "복권 같은(극단적 상방 꼬리를 가진) 개별주는 평균적으로 위험조정수익률이 낮다"고 경고한다.
      대마초 바스켓(TLRY 등)은 정확히 이 경고가 실현된 사례다 — 초기 급등 이후 다년간 거의 모든
      구성이 자본을 파괴했다(정적 매수후보유 CAGR {fnum(H_CAN['basket_static_buy_hold']['cagr'],1,True)}%).
      반면 해운·태양광은 초기 복권 같은 상승 이후에도 규율 있는 로테이션/추세추종이 SPY(샤프
      {fnum(H_SHIP['spy_buy_hold_common_window']['sharpe'],2)}/{fnum(H_SOL['spy_buy_hold_common_window']['sharpe'],2)})와
      경쟁할 만한 결과를 냈다. 세 사례를 나란히 보면, "고변동성 테마가 텐베거가 될지 대마초가 될지는
      사후적으로만 구분 가능하고, 사전에 어느 쪽인지 가려낼 방법을 이 리서치 라인은 아직 갖고 있지
      않다"는 게 정직한 요약이다 — 이 긴장은 억지로 봉합하지 않는다.</p>
  </section>

  <section class="section" id="limitations">
    <h2><span class="sec-no">08</span> 한계</h2>
    <ul>
      <li>3개 대조군 바스켓도 결국 "사후에 뚜렷한 테마/사이클이 있었던 걸 알고 고른" 종목군이다 —
        IREN 선정 자체가 받았던 사후편향 의심(작업24/25, 개별주 확장 전면 기각의 근거였던 것)에서
        이 대조군도 완전히 자유롭지 않다.</li>
      <li>바스켓마다 표본기간·종목수·상관구조가 다르다(해운 5종목·5.1년, 대마초 4종목·7.6년, 태양광
        5종목·10.6년) — 세 바스켓을 "같은 실험의 반복"으로 보기엔 조건이 이질적이라, 엄밀한 메타분석
        (효과크기 통합)은 이 라운드에서 시도하지 않았다.</li>
      <li>여전히 왕복 0.1% 단순 비용모형, 생존편향(현재 시점에 거래되는 종목만 사용 — 해운/태양광 업종
        내 상장폐지·파산한 종목은 애초에 후보에서 빠짐)을 그대로 물려받는다.</li>
      <li>순열검정(_shuffle_daily_bars)은 날짜 순서만 섞어 추세/자기상관을 지우지만 각 날짜의 캔들
        모양(변동성)은 보존한다 — 즉 "이 정도 변동성을 가진 자산이라면 우연히도 이런 샤프가 나올 수
        있는가"를 묻는 것이지, "이 자산 자체가 애초에 존재할 법한 자산인가"는 묻지 않는다.</li>
      <li>블록부트스트랩은 실현된 하나의 역사적 경로가 대표성 있다는 전제 위에 있다 — 해운 운임이
        2021년에 실제로 그만큼 폭등하지 않았거나, 대마초가 실제로 합법화됐다면 등의 반사실은 반영하지
        못한다.</li>
      <li>세 바스켓 다 "추세추종이 로테이션·매수후보유를 항상 이긴다"는 단일 결론으로 수렴하지
        않았다는 것 자체가 이 리포트의 핵심 발견이지만, 표본이 3개뿐이라 "IREN이 예외다"와 "일반화된
        패턴이 없다"를 통계적으로 구분할 만큼 충분히 크지는 않다.</li>
    </ul>
  </section>

</div>

<footer>
  <p>QUANT RESEARCH · 트랙C 비-AI 대조군 바스켓 연구 · 해운/대마초/태양광 3개 독립 바스켓 ·
    기준일 {esc(GEN)} · 이 문서는 투자 조언이 아니며 저자 개인의 연구 기록입니다.</p>
</footer>
"""

with open(f"{OUT_DIR}/final_report.html", "w", encoding="utf-8") as f:
    f.write(HTML)
print("[build_report] saved final_report.html")
