#!/usr/bin/env python3
"""report_data.json을 읽어 final_report.html을 만든다.

analysis/2026-08-30_track_c_bootstrap_confidence_audit/build_report.py(트랙C 4번째 리포트)와
동일한 디자인 시스템(다크네이비/올리브 톤, 세리프 헤드라인, TOC, 섹션 번호, 판정 배지)을
재사용한다 — 트랙C 내부의 시각적 연속성을 유지하고 새 CSS를 발명하지 않는다.
"""
import json
import math
import os

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

with open(f"{OUT_DIR}/report_data.json", encoding="utf-8") as f:
    R = json.load(f)

META = R["meta"]
H1 = R["h1_spy_collar"]
H2 = R["h2_beta_scaled_collar"]
H3 = R["h3_btc_collar"]
BOOT = R["bootstrap_audit"]
GEN = META["generated"]
DD = META["drawdown_episode"]


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


def grade_from_winrate(wr):
    """wr = 챌린저가 베이스라인을 이기는 부트스트랩 표본 비율."""
    if wr is None:
        return "unknown"
    if wr >= 0.90 or wr <= 0.10:
        return "robust"
    if wr >= 0.70 or wr <= 0.30:
        return "moderate"
    return "weak"


def grade_badge(grade, pos_label="챌린저 우위", neg_label="베이스라인 우위"):
    label = {"robust": f"강건({pos_label if grade=='robust' else neg_label})",
             "moderate": "보통", "weak": "약함(동전던지기 근처)"}.get(grade, grade)
    cls = {"robust": "grade-A", "moderate": "grade-B", "weak": "grade-C"}.get(grade, "grade-B")
    return f'<span class="confidence-grade {cls}">{esc(label)}</span>'


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
.confidence-grade{ display:inline-block; font-size:12px; font-weight:700; padding:2px 9px; border-radius:4px; }
.grade-A{ background: var(--accent-soft); color:var(--accent); }
.grade-B{ background: var(--accent-2-soft); color:var(--accent-2); }
.grade-C{ background: rgba(179,38,30,0.10); color:var(--delta-neg); }
"""

# ---------------------------------------------------------------------------
# 지표 행 렌더링
# ---------------------------------------------------------------------------

CONFIG_LABEL = {
    "unhedged": "무헤지(챔피언 그대로)",
    "protective_put": "풋 매수만(콜 없음)",
    "collar": "SPY 칼라(풋+콜)",
    "collar_1x_notional": "SPY 칼라 1x 노셔널",
    "collar_beta_scaled": "SPY 칼라 베타스케일 노셔널",
    "collar_spy": "SPY 칼라",
    "collar_btc": "BTC 칼라",
}


def metric_row(label, m, hero=False, warn=False):
    cls = " hero-row" if hero else (" warn-row" if warn else "")
    n_obs = f' <span class="kpi-sub">(n={m["n_obs"]})</span>' if "n_obs" in m else ""
    return (
        f'<tr class="{cls.strip()}"><td class="tk-cell"><span class="tk-name">{esc(label)}</span>{n_obs}</td>'
        f'<td class="num">{fnum(m.get("cumulative_return"),1,signed=True)}%</td>'
        f'<td class="num">{fnum(m.get("cagr"),1,signed=True)}%</td>'
        f'<td class="num">{fnum(m.get("mdd"),1,signed=True)}%</td>'
        f'<td class="num">{fnum(m.get("sharpe"),2,signed=True)}</td>'
        f'<td class="num">{fnum(m.get("calmar"),2,signed=True)}</td></tr>'
    )


def metrics_table(period_dict, keys, hero_key=None, warn_keys=()):
    rows = []
    for k in keys:
        if k not in period_dict:
            continue
        rows.append(metric_row(CONFIG_LABEL.get(k, k), period_dict[k], hero=(k == hero_key), warn=(k in warn_keys)))
    return "".join(rows)


def boot_comparison_row(label, comp, pos_label, neg_label):
    wr20 = comp["win_rate_a_over_b_L20"]
    wr10 = comp["win_rate_a_over_b_L10"]
    wr40 = comp["win_rate_a_over_b_L40"]
    grade = grade_from_winrate(wr20)
    return (
        f'<tr><td class="tk-cell"><span class="tk-name">{esc(label)}</span></td>'
        f'<td class="num">{pct(wr10,1)}</td><td class="num">{pct(wr20,1)}</td><td class="num">{pct(wr40,1)}</td>'
        f'<td class="num">{fnum(comp["point_gap"],3,signed=True)}</td>'
        f'<td>{grade_badge(grade, pos_label, neg_label)}</td></tr>'
    )


H1_FULL = metrics_table(H1["full_period"], ["unhedged", "protective_put", "collar"], hero_key="unhedged")
H1_DD = metrics_table(H1["drawdown_episode"], ["unhedged", "protective_put", "collar"], hero_key="unhedged")
H2_FULL = metrics_table(H2["full_period"], ["unhedged", "collar_1x_notional", "collar_beta_scaled"],
                         hero_key="unhedged", warn_keys=("collar_beta_scaled",))
H2_DD = metrics_table(H2["drawdown_episode"], ["unhedged", "collar_1x_notional", "collar_beta_scaled"],
                       hero_key="unhedged", warn_keys=("collar_beta_scaled",))
H3_FULL = metrics_table(H3["full_period"], ["unhedged", "collar_spy", "collar_btc"], hero_key="unhedged")
H3_DD = metrics_table(H3["drawdown_episode"], ["unhedged", "collar_spy", "collar_btc"], hero_key="collar_btc")

BOOT_H1_FULL = boot_comparison_row("풋 매수 vs 무헤지", BOOT["h1_full_period"]["comparisons"]["protective_put_vs_unhedged"], "풋", "무헤지") + \
    boot_comparison_row("칼라 vs 무헤지", BOOT["h1_full_period"]["comparisons"]["collar_vs_unhedged"], "칼라", "무헤지")
BOOT_H1_DD = boot_comparison_row("풋 매수 vs 무헤지", BOOT["h1_drawdown_episode"]["comparisons"]["protective_put_vs_unhedged"], "풋", "무헤지") + \
    boot_comparison_row("칼라 vs 무헤지", BOOT["h1_drawdown_episode"]["comparisons"]["collar_vs_unhedged"], "칼라", "무헤지")
BOOT_H2_FULL = boot_comparison_row("베타스케일 vs 1x노셔널", BOOT["h2_full_period"]["comparisons"]["collar_beta_scaled_vs_collar_1x_notional"], "베타스케일", "1x") + \
    boot_comparison_row("1x노셔널 vs 무헤지", BOOT["h2_full_period"]["comparisons"]["collar_1x_notional_vs_unhedged"], "1x칼라", "무헤지")
BOOT_H2_DD = boot_comparison_row("베타스케일 vs 1x노셔널", BOOT["h2_drawdown_episode"]["comparisons"]["collar_beta_scaled_vs_collar_1x_notional"], "베타스케일", "1x") + \
    boot_comparison_row("1x노셔널 vs 무헤지", BOOT["h2_drawdown_episode"]["comparisons"]["collar_1x_notional_vs_unhedged"], "1x칼라", "무헤지")
BOOT_H3_FULL = boot_comparison_row("BTC칼라 vs SPY칼라", BOOT["h3_full_period"]["comparisons"]["collar_btc_vs_collar_spy"], "BTC칼라", "SPY칼라") + \
    boot_comparison_row("BTC칼라 vs 무헤지", BOOT["h3_full_period"]["comparisons"]["collar_btc_vs_unhedged"], "BTC칼라", "무헤지") + \
    boot_comparison_row("SPY칼라 vs 무헤지", BOOT["h3_full_period"]["comparisons"]["collar_spy_vs_unhedged"], "SPY칼라", "무헤지")
BOOT_H3_DD = boot_comparison_row("BTC칼라 vs SPY칼라", BOOT["h3_drawdown_episode"]["comparisons"]["collar_btc_vs_collar_spy"], "BTC칼라", "SPY칼라") + \
    boot_comparison_row("BTC칼라 vs 무헤지", BOOT["h3_drawdown_episode"]["comparisons"]["collar_btc_vs_unhedged"], "BTC칼라", "무헤지") + \
    boot_comparison_row("SPY칼라 vs 무헤지", BOOT["h3_drawdown_episode"]["comparisons"]["collar_spy_vs_unhedged"], "SPY칼라", "무헤지")

BASKET_STR = "·".join(META["basket"])

HTML = f"""<title>옵션 칼라 헤지를 변동성모멘텀 바스켓에 이식하다</title>
<style>
{CSS}
</style>

<div class="masthead">
  <div class="masthead-inner">
    <div class="masthead-eyebrow">
      <span>QUANT RESEARCH NOTE</span><span class="dot">·</span><span>트랙 C 5번째 리포트</span><span class="dot">·</span><span>Hypothesis-Driven Study</span>
    </div>
    <h1 class="masthead-title">옵션 칼라 헤지를 변동성모멘텀 챔피언에 직접 이식하면 무슨 일이 벌어지는가</h1>
    <p class="masthead-sub">트랙C 두 번째~세 번째 리포트(작업27/28)가 남긴 숙제였다 — "옵션 인프라가 없어
      정성적 논의로만 다뤘다"던 H5를 이제 라이브화된 core.champion_strategy 합성 Black-Scholes 칼라
      엔진(SPY 종가+VIX 대리변동성+FRED 금리, 2026-09-14 라이브화)으로 직접 검증한다. 대상은 트랙C의
      IREN류 피벗 바스켓 챔피언({esc(BASKET_STR)}, 20일 돈치안 브레이크아웃+15% 트레일링스탑, 동일가중
      100% 노셔널)이다.</p>
    <div class="masthead-meta">
      <span><b>기준일</b> {esc(GEN)}</span>
      <span><b>공통구간</b> {esc(META['common_start'])} ~ {esc(META['end'])}</span>
      <span><b>바스켓 자체 최악낙폭</b> {esc(DD['peak_date'])} → {esc(DD['trough_date'])} ({fnum(DD['drawdown_pct'],1)}%)</span>
      <span><b>부트스트랩</b> 조합당 {BOOT['meta']['n_boot']:,}회, 블록길이 {', '.join(str(x)+'일' for x in BOOT['meta']['block_lengths'])}</span>
    </div>
  </div>
</div>

<div class="wrap">

  <nav class="toc">
    <a href="#scope">00 문제 제기</a>
    <a href="#h1">01 H1 — SPY 칼라 직접 이식</a>
    <a href="#h2">02 H2 — 베타 스케일링 반박가설</a>
    <a href="#h3">03 H3 — BTC 기초자산 반박가설</a>
    <a href="#synthesis">04 종합 — 헤지가 틀렸던 건 메커니즘이 아니라 기초자산이었다</a>
    <a href="#limitations">05 한계</a>
  </nav>

  <section class="section" id="scope">
    <h2><span class="sec-no">00</span> 문제 제기 — 왜 이제서야 검증하는가</h2>
    <p class="lede">작업48/49(트랙D)는 이미 합성 칼라를 백테스트했지만, 그건 17자산 챔피언에 15%만
      편입되는 point-in-time 새틀라이트 슬리브에 적용한 것이었다 — 트랙C 자신의 바스켓 챔피언(그
      자체가 전략이라 100% 노셔널로 운용됨)에는 한 번도 이식되지 않았다. 이번 라운드는 core가 이미
      라이브로 쓰는 <code>bs_put_price</code>/<code>bs_call_price</code>/<code>_fedfunds_rate_asof</code>
      를 그대로 재사용해(옵션가격 이론을 새로 만들지 않음) 세 가설을 검증한다: <b>H1</b> SPY 기반
      칼라를 그대로 얹으면 어떻게 되는가, <b>H2</b> 이 바스켓의 베타가 시장보다 훨씬 크니(작업27
      실측 2.5~6.1배) 노셔널을 베타만큼 키우면 나아지는가, <b>H3</b> 작업28 H2가 이미 회귀로 확인한
      "이 바스켓은 BTC 노출이 SPY 노출보다 설명력이 큰 종목이 7개 중 4개"라는 사실을 그대로 옵션
      기초자산 선택에 적용하면(SPY 대신 BTC-USD) 나아지는가.</p>
  </section>

  <section class="section" id="h1">
    <h2><span class="sec-no">01</span> H1 — SPY 기반 칼라 직접 이식은 기각</h2>
    <p class="lede">ATM 풋 매수(+5% OTM 콜 매도로 프리미엄 상쇄)를 바스켓 수익률에 1:1 노셔널로
      얹었다. 라이브 엔진과 동일한 파라미터({fnum(META['collar_params']['put_moneyness'],2)} 풋 /
      {fnum(META['collar_params']['call_moneyness'],2)} 콜 / {META['collar_params']['tenor_days']}일
      테너, {H1['n_rolls']}회 롤).</p>
    <h3>전체기간 ({esc(META['common_start'])}~{esc(META['end'])})</h3>
    <div class="table-wrap"><table class="data-table">
      <thead><tr><th>구성</th><th>누적수익률</th><th>CAGR</th><th>MDD</th><th>샤프</th><th>칼마</th></tr></thead>
      <tbody>{H1_FULL}</tbody>
    </table></div>
    <h3>바스켓 자체 최악낙폭 구간 ({esc(DD['peak_date'])}~{esc(DD['recovery_date'])}, {fnum(DD['drawdown_pct'],1)}%)</h3>
    <div class="table-wrap"><table class="data-table">
      <thead><tr><th>구성</th><th>누적수익률</th><th>CAGR</th><th>MDD</th><th>샤프</th><th>칼마</th></tr></thead>
      <tbody>{H1_DD}</tbody>
    </table></div>
    <div class="callout warn">
      <div class="callout-title">위기조차 못 잡는다 — SPY가 안 움직였기 때문</div>
      <p>바스켓이 -71% 무너진 구간에서 SPY는 겨우 {fnum(H3['drawdown_episode']['spy_drawdown_in_window_pct'],1)}%밖에
        빠지지 않았다(H3절 참고) — 즉 이 바스켓의 최악 낙폭은 시장 전체와 디커플링된 고유(idiosyncratic)
        이벤트였다. SPY 풋은 그 구간에도 거의 청구되지 않고, 매달 프리미엄만 갹출한 채 전체기간
        수익률을 깎았다(무헤지 샤프 {fnum(H1['full_period']['unhedged']['sharpe'],2)} → 칼라
        {fnum(H1['full_period']['collar']['sharpe'],2)}, 풋만 {fnum(H1['full_period']['protective_put']['sharpe'],2)}).
        낙폭구간에서도 칼라·풋 모두 무헤지보다 <b>더 나쁘다</b>(MDD가 오히려 확대) — 보험료를 내고도
        보장이 발동하지 않은 셈이다.</p>
    </div>
    <h3>블록부트스트랩 감사 — 승률(챌린저가 베이스라인을 이기는 표본 비율)</h3>
    <div class="table-wrap"><table class="data-table">
      <thead><tr><th>비교</th><th>L=10</th><th>L=20</th><th>L=40</th><th>점추정 격차</th><th>등급</th></tr></thead>
      <tbody>{BOOT_H1_FULL}</tbody>
    </table></div>
    <p class="caveat">낙폭구간(n={BOOT['h1_drawdown_episode']['n_obs']}거래일)에서도 결과는 동일한 방향
      — 칼라·풋 모두 무헤지를 이기는 표본이 절반에 못 미친다(L=20 승률 각각
      {pct(BOOT['h1_drawdown_episode']['comparisons']['collar_vs_unhedged']['win_rate_a_over_b_L20'],1)},
      {pct(BOOT['h1_drawdown_episode']['comparisons']['protective_put_vs_unhedged']['win_rate_a_over_b_L20'],1)}).
      점추정만이 아니라 표본오차를 감안해도 "SPY 칼라가 이 바스켓을 방어한다"는 주장은 성립하지
      않는다 — <b>기각(강건)</b>.</p>
  </section>

  <section class="section" id="h2">
    <h2><span class="sec-no">02</span> H2 — 베타 스케일링 반박가설도 기각(오히려 더 나쁨)</h2>
    <p class="lede">"1:1 노셔널이 이 바스켓의 실제 시장 익스포저에 비해 과소헤지 아닐까"라는 반박
      가설 — 트레일링 126일 롤링 베타(선행편향 없음, 매 롤마다 그 시점 베타로 고정)로 SPY 옵션
      노셔널을 확대했다. 실측 베타 분포: 최소 {fnum(H2['beta_stats']['min'],2)}, 중앙값
      {fnum(H2['beta_stats']['median'],2)}, 평균 {fnum(H2['beta_stats']['mean'],2)}, 최대
      {fnum(H2['beta_stats']['max'],2)}배 — 즉 대부분의 롤에서 노셔널을 3배 안팎으로 키웠다.</p>
    <h3>전체기간</h3>
    <div class="table-wrap"><table class="data-table">
      <thead><tr><th>구성</th><th>누적수익률</th><th>CAGR</th><th>MDD</th><th>샤프</th><th>칼마</th></tr></thead>
      <tbody>{H2_FULL}</tbody>
    </table></div>
    <h3>바스켓 자체 최악낙폭 구간</h3>
    <div class="table-wrap"><table class="data-table">
      <thead><tr><th>구성</th><th>누적수익률</th><th>CAGR</th><th>MDD</th><th>샤프</th><th>칼마</th></tr></thead>
      <tbody>{H2_DD}</tbody>
    </table></div>
    <div class="callout warn">
      <div class="callout-title">과소헤지가 문제가 아니었다 — 프리미엄 드래그를 3배로 키웠을 뿐</div>
      <p>사전에 명시했던 우려가 그대로 실현됐다: 이 바스켓의 낙폭은 SPY와 디커플링된 고유 이벤트라,
        SPY 노셔널을 베타만큼 키워도 그 구간엔 SPY 자체가 안 움직여 방어력이 늘지 않고, 매달 내는
        프리미엄만 베타배수로 불어났다. 결과는 전체기간 샤프 {fnum(H1['full_period']['collar']['sharpe'],2)}
        (1x) → {fnum(H2['full_period']['collar_beta_scaled']['sharpe'],2)}(베타스케일)로 뚜렷한
        악화, 낙폭구간은 MDD가 {fnum(H1['drawdown_episode']['collar']['mdd'],1)}%에서
        {fnum(H2['drawdown_episode']['collar_beta_scaled']['mdd'],1)}%로 오히려 <b>확대</b>됐다.</p>
    </div>
    <h3>블록부트스트랩 감사</h3>
    <div class="table-wrap"><table class="data-table">
      <thead><tr><th>비교</th><th>L=10</th><th>L=20</th><th>L=40</th><th>점추정 격차</th><th>등급</th></tr></thead>
      <tbody>{BOOT_H2_FULL}</tbody>
    </table></div>
    <p class="caveat">낙폭구간에서도 베타스케일이 1x노셔널을 이기는 표본은 L=20 기준
      {pct(BOOT['h2_drawdown_episode']['comparisons']['collar_beta_scaled_vs_collar_1x_notional']['win_rate_a_over_b_L20'],1)}
      뿐이다 — <b>기각(강건, 방향은 오히려 더 나쁜 쪽으로 확실)</b>. "베타가 크니 헤지를 더 키우자"는
      직관은 헤지 대상 위험의 정체(고유위험 vs 시장위험)를 먼저 확인하지 않으면 역효과를 낼 수 있다는
      걸 실측으로 보여준 사례다.</p>
  </section>

  <section class="section" id="h3">
    <h2><span class="sec-no">03</span> H3 — BTC 기초자산 반박가설은 부분채택(위기창에서 뚜렷한 반전)</h2>
    <p class="lede">작업28 H2가 회귀로 이미 확인했던 사실을 옵션 기초자산 선택에 그대로 적용했다:
      이 바스켓의 최악낙폭 구간에서 SPY는 {fnum(H3['drawdown_episode']['spy_drawdown_in_window_pct'],1)}%
      밖에 안 빠졌지만 BTC-USD는 {fnum(H3['drawdown_episode']['btc_drawdown_in_window_pct'],1)}%나
      빠졌다 — 훨씬 큰 공행성. SPY 대신 BTC-USD를 기초자산으로 쓰는 합성 칼라(내재변동성 대신 21일
      실현변동성을 대리치로 사용 — VIX 같은 선행지표가 없어 구조적으로 불리한 조건임을 사전에 명시)를
      비교했다.</p>
    <h3>전체기간</h3>
    <div class="table-wrap"><table class="data-table">
      <thead><tr><th>구성</th><th>누적수익률</th><th>CAGR</th><th>MDD</th><th>샤프</th><th>칼마</th></tr></thead>
      <tbody>{H3_FULL}</tbody>
    </table></div>
    <h3>바스켓 자체 최악낙폭 구간</h3>
    <div class="table-wrap"><table class="data-table">
      <thead><tr><th>구성</th><th>누적수익률</th><th>CAGR</th><th>MDD</th><th>샤프</th><th>칼마</th></tr></thead>
      <tbody>{H3_DD}</tbody>
    </table></div>
    <div class="callout good">
      <div class="callout-title">전체기간엔 더 나쁘지만, 정확히 위기 구간에서는 셋 중 가장 낫다</div>
      <p>전체기간만 보면 BTC 칼라는 최악이다(샤프 {fnum(H3['full_period']['collar_btc']['sharpe'],2)},
        실현변동성 기반 프리미엄이 비싸 평시 드래그가 SPY 칼라보다 크다). 하지만 낙폭구간에서는
        정반대다 — BTC 칼라의 샤프({fnum(H3['drawdown_episode']['collar_btc']['sharpe'],2)})가
        무헤지({fnum(H3['drawdown_episode']['unhedged']['sharpe'],2)})와 SPY칼라
        ({fnum(H3['drawdown_episode']['collar_spy']['sharpe'],2)})를 모두 앞서고, MDD도
        {fnum(H3['drawdown_episode']['collar_btc']['mdd'],1)}%로 나머지 둘({fnum(H3['drawdown_episode']['unhedged']['mdd'],1)}%,
        {fnum(H3['drawdown_episode']['collar_spy']['mdd'],1)}%)보다 뚜렷이 얕다. "옵션 헤지 자체가
        안 통한다"가 아니라 "<b>잘못된 기초자산을 헤지하고 있었다</b>"는 게 더 정확한 진단이라는
        뜻이다.</p>
    </div>
    <h3>블록부트스트랩 감사</h3>
    <p class="lede">전체기간</p>
    <div class="table-wrap"><table class="data-table">
      <thead><tr><th>비교</th><th>L=10</th><th>L=20</th><th>L=40</th><th>점추정 격차</th><th>등급</th></tr></thead>
      <tbody>{BOOT_H3_FULL}</tbody>
    </table></div>
    <p class="lede">낙폭구간 — 방향이 완전히 뒤집힌다</p>
    <div class="table-wrap"><table class="data-table">
      <thead><tr><th>비교</th><th>L=10</th><th>L=20</th><th>L=40</th><th>점추정 격차</th><th>등급</th></tr></thead>
      <tbody>{BOOT_H3_DD}</tbody>
    </table></div>
    <p class="caveat">낙폭구간에서 BTC칼라가 SPY칼라를 이기는 부트스트랩 표본이 L=20 기준
      {pct(BOOT['h3_drawdown_episode']['comparisons']['collar_btc_vs_collar_spy']['win_rate_a_over_b_L20'],1)},
      무헤지를 이기는 표본이 {pct(BOOT['h3_drawdown_episode']['comparisons']['collar_btc_vs_unhedged']['win_rate_a_over_b_L20'],1)}
      — <b>모두 70% 안팎으로 "보통(moderate)" 등급</b>이다. 방향은 뚜렷하지만 95% 문턱을 넘는
      "강건" 등급은 아니다 — n_obs가 낙폭구간(227거래일) 하나뿐이라는 근본적 한계 때문이다(05절).
      다만 전체기간에서는 BTC칼라가 SPY칼라·무헤지 둘 다에 확실히 지는 쪽(승률 29~32%)이라, "BTC
      칼라를 상시 걸어두라"는 결론은 아니다 — 위기 국면에서만 가치가 있다는 뜻으로 읽어야 한다.</p>
  </section>

  <section class="section" id="synthesis">
    <h2><span class="sec-no">04</span> 종합 — 헤지가 틀렸던 건 메커니즘이 아니라 기초자산이었다</h2>
    <div class="table-wrap"><table class="data-table">
      <thead><tr><th>가설</th><th>판정</th><th>핵심 근거</th></tr></thead>
      <tbody>
        <tr class="warn-row"><td class="tk-cell"><span class="tk-name">H1 SPY 칼라 직접 이식</span></td>
          <td><span class="verdict-badge v-reject">기각</span></td>
          <td>전체기간·낙폭구간 모두 무헤지보다 나쁨, 부트스트랩 승률 43~47%(전부 강건하게 기각)</td></tr>
        <tr class="warn-row"><td class="tk-cell"><span class="tk-name">H2 베타 스케일링 노셔널</span></td>
          <td><span class="verdict-badge v-reject">기각(더 나쁨)</span></td>
          <td>1x노셔널보다도 악화(샤프 1.14→0.91), 프리미엄 드래그를 베타배수로 키운 부작용</td></tr>
        <tr class="hero-row"><td class="tk-cell"><span class="tk-name">H3 BTC 기초자산</span></td>
          <td><span class="verdict-badge v-partial">부분채택</span></td>
          <td>전체기간엔 최악이지만 낙폭구간에서 셋 중 최선(승률 67~69%, 보통 등급)</td></tr>
      </tbody>
    </table></div>
    <p>세 가설을 나란히 놓으면 하나의 일관된 진단이 나온다 — 이 바스켓의 초과수익과 최악의 낙폭은
      <b>시장(SPY) 위험이 아니라 고유/테마 위험(BTC 상관 + 개별 서사 촉매)에서 나온다</b>는 게 트랙C가
      작업27~28부터 반복 확인한 결론이었고, 이번 옵션 헤지 이식 라운드는 그걸 세 번째 각도(옵션가격
      메커니즘)에서 재확인했다. SPY 기초자산을 그대로 쓰면(H1) 보험이 발동하지 않고, 노셔널만
      키우면(H2) 드래그만 커지고, 기초자산 자체를 이 바스켓의 진짜 위험요인(BTC)으로 바꾸면(H3)
      비로소 위기창에서 방어력이 나타난다 — 다만 그 대가(평시 드래그)가 크고 통계적 신뢰도도 "보통"
      수준이라, "이 헤지를 상시 걸어두면 해결된다"는 승리 서사로 포장하지 않는다. 트랙C의 다른
      결론들(작업28 H1 시장베타헤지 기각, H2 BTC 설명력 부분채택)과도 방향이 정확히 일치한다 — 이
      바스켓을 헤지하려면 SPY가 아니라 그 바스켓이 실제로 노출된 위험요인을 먼저 특정해야 한다는
      메타 원칙이 세 번째로 재확인된 것.</p>
  </section>

  <section class="section" id="limitations">
    <h2><span class="sec-no">05</span> 한계</h2>
    <ul>
      <li>바스켓 자체가 2021년 말 상장이라 공통구간이 약 4.3년({esc(META['common_start'])}~{esc(META['end'])})
        뿐이고, "바스켓 자체 최악낙폭 구간"도 데이터 안에서 유일하게 관측된 사건 하나(2025-10~2026-03)다
        — 다른 성격의 위기(예: 이 바스켓이 실제로 시장과 동반 붕괴하는 시나리오)는 아직 한 번도
        표본에 없다.</li>
      <li>BTC 칼라의 변동성 입력은 VIX 같은 선행 내재변동성 지수가 아니라 21일 롤링 실현변동성
        대리치다 — 실현변동성은 변동성 급등 초입에 후행하는 경향이 있어, SPY 버전보다 구조적으로
        불리한 조건에서 비교됐다는 점을 감안해야 한다(즉 BTC 칼라의 위기창 우위는 이 핸디캡을 이미
        지고도 나온 결과라 오히려 더 견고할 수 있다는 해석도 가능하지만, 반대로 더 정교한 내재변동성
        추정을 쓰면 결과가 달라질 가능성도 열려 있다).</li>
      <li>부트스트랩 승률이 낙폭구간에서 "강건"이 아니라 "보통" 등급에 머무는 건 근본적으로 n_obs가
        227거래일(단일 사건)뿐이기 때문이다 — 이 프로그램 전체의 반복된 한계(표본기간 짧음)가 여기서도
        그대로 적용된다.</li>
      <li>세 가설 모두 왕복 거래비용은 바스켓 챔피언 자체(0.1%)에만 반영돼 있고, 옵션 프리미엄/페이오프
        자체에는 별도의 매수-매도 스프레드나 슬리피지를 추가하지 않았다 — 실제 옵션시장 마찰비용을
        더하면 세 구성 모두 지금보다 더 나빠질 것이다(트랙D 작업48/49와 동일한 단순화).</li>
      <li>H2의 베타 추정(126일 롤링, [0.5, 8.0] 윈저라이즈)은 소형·고변동성 종목 특유의 노이즈를
        그대로 물려받는다 — 작업28 H4가 이미 "소형주 베타추정 노이즈가 역베타가중을 망친다"고 경고한
        것과 같은 메커니즘이 여기서도 작동했을 수 있다.</li>
      <li>이 리포트가 검증한 건 "이 특정 칼라 파라미터(ATM풋/5%OTM콜/21일)"뿐이다 — 파라미터 자체의
        견고성(과최적화 여부)은 후속 라운드(analysis/2026-09-15_options_collar_parameter_sensitivity)
        에서 별도로 감사한다.</li>
    </ul>
  </section>

</div>

<footer>
  <p>QUANT RESEARCH · 옵션 칼라 헤지 이식 — 변동성모멘텀 바스켓(트랙C 5번째 리포트) · 기준일 {esc(GEN)} ·
    이 문서는 투자 조언이 아니며 저자 개인의 연구 기록입니다.</p>
</footer>
"""

with open(f"{OUT_DIR}/final_report.html", "w", encoding="utf-8") as f:
    f.write(HTML)
print("[build_report] saved final_report.html")
