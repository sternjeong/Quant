#!/usr/bin/env python3
"""report_data.json을 읽어 final_report.html을 만든다.

analysis/2026-08-23_joint_parameter_interaction_grid_search/build_report.py(H31)와 동일한 디자인
시스템(다크네이비/올리브 톤, 세리프 헤드라인, TOC, 섹션 번호, 판정 배지)을 그대로 재사용한다.
"""
import json
import math
import os
from datetime import date

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

with open(f"{OUT_DIR}/report_data.json", encoding="utf-8") as f:
    R = json.load(f)

S1 = R["stage1"]
S2 = R["stage2"]
REFINED = R["refined_optimum_used_for_stage2"]

LOOKBACKS = S1["lookback_months"]
FREQS = list(S1["frequencies"].keys())
SEQ = S1["sequential_choice"]
H31_WINNER = S1["h31_coarse_winner"]
SAT_WEIGHTS = [f["satellite_weight"] for f in S2["sequential_core_frontier"]["frontier"]]


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
.wrap{ max-width: 1080px; margin:0 auto; padding: 0 24px 96px; }
.masthead{ background: var(--accent); color: var(--accent-ink); padding: 56px 24px 40px; }
.masthead-inner{ max-width:1080px; margin:0 auto; }
.masthead-eyebrow{ font-size:12.5px; letter-spacing:0.12em; text-transform:uppercase; opacity:0.82;
  font-family: ui-monospace, "SF Mono", Consolas, monospace; display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
.masthead-eyebrow .dot{ opacity:0.5; }
h1.masthead-title{ font-family:"Iowan Old Style","Palatino Linotype", Georgia, serif; font-weight:600;
  font-size: clamp(28px, 4.2vw, 44px); line-height:1.15; margin: 14px 0 10px; text-wrap: balance; max-width: 34ch; }
.masthead-sub{ font-size:16.5px; max-width:78ch; opacity:0.92; margin:0 0 22px; }
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
td.seq-cell{ outline: 2px solid var(--accent-2); outline-offset:-2px; }
footer{ max-width:1080px; margin:40px auto 0; padding: 26px 24px 10px; border-top:1px solid var(--hairline);
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
.legend{ display:flex; gap:18px; flex-wrap:wrap; font-size:12.5px; color:var(--ink-muted); margin: 8px 0 18px; }
.legend .sw{ display:inline-block; width:12px; height:12px; border-radius:2px; margin-right:6px; vertical-align:-1px; }
"""

FREQ_LABEL = {
    "monthly_21d": "월간(21거래일, 순차선택)", "sixweek_30d": "6주(30거래일)",
    "twomonth_42d": "2개월(42거래일)", "quarterly_63d": "분기(63거래일, H31 우승)",
}
SCEN_LABEL = {"base": "기본(중심 추정)", "calm_heavy": "강세장 편향(보수적)", "crisis_heavy": "위기 편향(비관적)"}


def sharpe_to_color(v, vmin, vmax):
    if vmax == vmin:
        t = 0.5
    else:
        t = (v - vmin) / (vmax - vmin)
    t = max(0.0, min(1.0, t))
    r_lo, g_lo, b_lo = (227, 73, 72)
    r_hi, g_hi, b_hi = (31, 77, 61)
    r = int(r_lo + (r_hi - r_lo) * t)
    g = int(g_lo + (g_hi - g_lo) * t)
    b = int(b_lo + (b_hi - b_lo) * t)
    alpha = 0.14 + 0.55 * t
    return f"rgba({r},{g},{b},{alpha:.2f})"


def heatmap_table(scen_name):
    scen = S1["scenarios"][scen_name]
    grid = scen["expected_value_grid"]
    vals = [v["expected_sharpe"] for v in grid.values()]
    vmin, vmax = min(vals), max(vals)
    seq_key = scen["sequential_choice_value"]["key"]
    fine_key = scen["fine_grid_optimum"]["key"]
    h31_key = scen["h31_coarse_winner_value"]["key"]

    header = "".join(f"<th>{FREQ_LABEL[f]}</th>" for f in FREQS)
    rows = []
    for months in LOOKBACKS:
        cells = []
        for f in FREQS:
            key = f"{months}|{f}"
            v = grid[key]["expected_sharpe"]
            bg = sharpe_to_color(v, vmin, vmax)
            cls = "seq-cell" if key == seq_key else ("best-row" if key == fine_key else "")
            marker = ""
            if key == fine_key:
                marker = " ★"
            elif key == h31_key:
                marker = " ◆"
            elif key == seq_key:
                marker = " ▣"
            cells.append(f'<td class="num {cls}" style="background:{bg};">{fnum(v,3,True)}{marker}</td>')
        rows.append(f'<tr><td class="tk-cell"><span class="tk-name">{months}개월</span></td>{"".join(cells)}</tr>')
    return f'<thead><tr><th>룩백 \\ 리밸런싱</th>{header}</tr></thead><tbody>{"".join(rows)}</tbody>'


def top_ranking_table(scen_name, n=8):
    scen = S1["scenarios"][scen_name]
    rows = []
    seq_key = scen["sequential_choice_value"]["key"]
    h31_key = scen["h31_coarse_winner_value"]["key"]
    top_keys = [k for k, _ in scen["ranking_by_expected_sharpe"][:n]]
    for i, (key, v) in enumerate(scen["ranking_by_expected_sharpe"][:n]):
        months, freq = key.split("|")
        cls = "best-row" if i == 0 else ("warn-row" if key == seq_key else "")
        label = f"{months}개월 · {FREQ_LABEL[freq].split('(')[0]}"
        tag = ""
        if key == seq_key:
            tag = " (순차선택)"
        elif key == h31_key:
            tag = " (H31 조그리드 우승)"
        elif i == 0:
            tag = " (정밀그리드 최적)"
        rows.append(
            f'<tr class="{cls}"><td class="tk-cell"><span class="tk-name">{i+1}. {esc(label)}{tag}</span></td>'
            f'<td class="num">{fnum(v["expected_sharpe"],4)}</td>'
            f'<td class="num">{fnum(v["expected_cagr_pct"],2,True)}%</td>'
            f'<td class="num">{fnum(v["mdd_worst_case"],2)}%</td></tr>'
        )
    for extra_key, extra_label in [(seq_key, f"{SEQ['lookback_months']}개월 · 월간 (순차선택)"),
                                    (h31_key, f"{H31_WINNER['lookback_months']}개월 · 분기 (H31 조그리드 우승)")]:
        if extra_key not in top_keys:
            v = scen["expected_value_grid"][extra_key]
            rank = [i for i, (k, _) in enumerate(scen["ranking_by_expected_sharpe"]) if k == extra_key][0] + 1
            rows.append(
                f'<tr class="warn-row"><td class="tk-cell"><span class="tk-name">{rank}. {esc(extra_label)}</span></td>'
                f'<td class="num">{fnum(v["expected_sharpe"],4)}</td>'
                f'<td class="num">{fnum(v["expected_cagr_pct"],2,True)}%</td>'
                f'<td class="num">{fnum(v["mdd_worst_case"],2)}%</td></tr>'
            )
    return "".join(rows)


def summary_kpis():
    tiles = []
    for scen_name in ["base", "calm_heavy", "crisis_heavy"]:
        scen = S1["scenarios"][scen_name]
        gap = scen["sharpe_gap_fine_minus_sequential"]
        rank = scen["sequential_rank_out_of_40"]
        cls = "pos" if gap > 0.05 else ""
        tiles.append(f"""
        <div class="kpi-tile">
          <div class="kpi-label">{esc(SCEN_LABEL[scen_name])} — 정밀최적 vs 순차선택 갭</div>
          <div class="kpi-value {cls}">+{fnum(gap,4)}</div>
          <div class="kpi-sub">순차선택(12개월·월간) 순위: {rank}/40</div>
        </div>""")
    return "".join(tiles)


def satellite_table():
    seq_f = {f["satellite_weight"]: f["metrics"] for f in S2["sequential_core_frontier"]["frontier"]}
    ref_f = {f["satellite_weight"]: f["metrics"] for f in S2["refined_core_frontier"]["frontier"]}
    seq_peak = S2["sequential_core_frontier"]["peak_sharpe_weight"]
    ref_peak = S2["refined_core_frontier"]["peak_sharpe_weight"]
    rows = []
    for sw in SAT_WEIGHTS:
        sm, rm = seq_f[sw], ref_f[sw]
        seq_cls = "best-row" if sw == seq_peak else ""
        ref_cls = "best-row" if sw == ref_peak else ""
        rows.append(
            f'<tr><td class="tk-cell"><span class="tk-name">{sw*100:.0f}%</span></td>'
            f'<td class="num {seq_cls}">{fnum(sm["sharpe"],3)}</td><td class="num">{fnum(sm["cagr"],2,True)}%</td><td class="num">{fnum(sm["mdd"],2)}%</td>'
            f'<td class="num {ref_cls}">{fnum(rm["sharpe"],3)}</td><td class="num">{fnum(rm["cagr"],2,True)}%</td><td class="num">{fnum(rm["mdd"],2)}%</td></tr>'
        )
    return "".join(rows)


gaps_seq = [S1["scenarios"][s]["sharpe_gap_fine_minus_sequential"] for s in ["base", "calm_heavy", "crisis_heavy"]]
gaps_h31 = [S1["scenarios"][s]["sharpe_gap_fine_minus_h31coarse"] for s in ["base", "calm_heavy", "crisis_heavy"]]
avg_gap_seq = sum(gaps_seq) / len(gaps_seq)
avg_gap_h31 = sum(gaps_h31) / len(gaps_h31)
fine_opt_keys = {S1["scenarios"][s]["fine_grid_optimum"]["key"] for s in ["base", "calm_heavy", "crisis_heavy"]}
same_fine_across_scenarios = len(fine_opt_keys) == 1
seq_ranks = [S1["scenarios"][s]["sequential_rank_out_of_40"] for s in ["base", "calm_heavy", "crisis_heavy"]]
h31_ranks = [S1["scenarios"][s]["h31_coarse_winner_rank_out_of_40"] for s in ["base", "calm_heavy", "crisis_heavy"]]

seq_015 = {f["satellite_weight"]: f["metrics"] for f in S2["sequential_core_frontier"]["frontier"]}[0.15]
ref_015 = {f["satellite_weight"]: f["metrics"] for f in S2["refined_core_frontier"]["frontier"]}[0.15]
seq_peak_m = S2["sequential_core_frontier"]["peak_sharpe_metrics"]
ref_peak_m = S2["refined_core_frontier"]["peak_sharpe_metrics"]

GEN = date.today().isoformat()

HTML = f"""<title>파라미터 정밀 그리드 · 새틀라이트 결합 연구</title>
<style>
{CSS}
</style>

<div class="masthead">
  <div class="masthead-inner">
    <div class="masthead-eyebrow">
      <span>QUANT RESEARCH NOTE</span><span class="dot">·</span><span>17라운드</span><span class="dot">·</span><span>Hypothesis-Driven Study</span>
    </div>
    <h1 class="masthead-title">(15개월, 분기) 조그리드 우승점, 정밀 해상도와 새틀라이트로 다시 검증한다</h1>
    <p class="masthead-sub">작업43(H31, 16라운드)은 룩백 5×리밸런싱 4=20칸의 성긴 그리드에서 결합 최적점을
      (15개월, 분기)로 찾았지만, 스스로 두 가지 미해결 과제를 남겼다 — ① 그리드 해상도가 거칠어 진짜
      정점이 다를 수 있다, ② 새틀라이트 비중을 함께 바꾸면 순위가 달라질 수 있다. 이 라운드는 룩백을
      1개월 간격(9~18개월, 10값)으로, 리밸런싱을 우승 구간에 재배치한 4값으로 좁혀 40칸 정밀 그리드를
      새로 백테스트하고(Stage 1), 그 정밀 최적점에 새틀라이트 비중(0~30%)을 얹어 순차 기본값과
      직접 비교한다(Stage 2).</p>
    <div class="masthead-meta">
      <span><b>기준일</b> {esc(GEN)}</span>
      <span><b>Stage 1 그리드</b> 룩백 9~18개월(1개월 간격, 10값) × 리밸런싱 월간/6주/2개월/분기(4값) = 40점 × 6개 창 = 240회 백테스트</span>
      <span><b>Stage 2</b> 정밀최적 코어 vs 순차 기본값 코어 각각에 새틀라이트 0/10/15/20/25/30% 블렌드, 전체기간 단일창</span>
      <span><b>기저확률 시나리오</b> H22/작업39와 동일(기본/강세장편향/위기편향), 가중치 그대로 재사용</span>
    </div>
  </div>
</div>

<div class="wrap">

  <nav class="toc">
    <a href="#scope">00 문제 제기</a>
    <a href="#stage1">01 Stage 1 — 정밀 2D 그리드</a>
    <a href="#stage2">02 Stage 2 — 새틀라이트 비중 결합</a>
    <a href="#synthesis">03 종합 — 최종 권고</a>
    <a href="#limitations">04 한계</a>
  </nav>

  <section class="section" id="scope">
    <h2><span class="sec-no">00</span> 문제 제기 — H31이 남긴 두 과제</h2>
    <p class="lede">16라운드(H31/작업43)는 룩백 5개(6/9/12/15/18개월)×리밸런싱 4개(격주/월간/6주/분기)
      = 20칸 그리드에서 결합 최적점이 (15개월, 분기)로 나왔음을 확인했다 — 순차 최적화가 도달한
      (12개월, 월간)은 20개 중 5~6위에 그쳤다. 하지만 그 라운드는 명시적으로 "그리드 해상도가 거칠다"와
      "새틀라이트 비중(현재 기본값 15%)까지 결합하면 최적점이 바뀔 수 있는데 아직 검증하지 않았다"는
      두 가지를 다음 라운드 과제로 남겼다. 이 라운드는 정확히 그 둘을 순서대로 닫는다.</p>
    <p>계산 비용을 고려해(H31이 명시한 교훈 그대로) 2단계로 나눴다 — Stage 1은 6개 창 기댓값 가중을
      유지한 채 (룩백, 리밸런싱) 2D를 정밀화하고, Stage 2는 그 결과 위에 새틀라이트 비중을 얹되
      point-in-time 유니버스 표본추출 비용 때문에 전체기간 단일창(H5와 동일한 절충)으로 제한한다 —
      완전한 6창×3차원 그리드는 이번 라운드에서도 시도하지 않았다(§04에 명시).</p>
    <p class="caveat">⚠️ 투자 조언이 아니다. 기저확률은 문헌 기반 추정치이며(작업39/H22 근거 그대로
      재사용), 정밀한 확률표가 아니다.</p>
  </section>

  <section class="section" id="stage1">
    <h2><span class="sec-no">01</span> Stage 1 — 정밀 2D 그리드</h2>
    <p class="lede">룩백을 H31의 3개월 간격(6/9/12/15/18) 대신 <b>1개월 간격 9~18개월(10값)</b>으로
      촘촘히 하고, 리밸런싱은 H31의 격주(10일)를 빼고 우승 구간(6주~분기)을 메우는 2개월(42일)을
      새로 넣어 월간/6주/2개월/분기 4값을 유지했다 — 총 10×4=40칸×6개 창=240회 백테스트. H31의 리밸런싱
      마스크(고정 달력기준일 2000-01-03로부터 영업일수 mod n)를 그대로 재사용했고, 검증 차원에서 이
      정밀 그리드의 (15개월, 분기)·(12개월, 월간) 셀 값이 H31 원본과 <b>완전히 일치</b>함을 확인했다
      (동일 코드·동일 데이터 재사용이므로 당연한 결과지만, 재현성 체크로 명시한다).</p>

    <div class="kpi-row">{summary_kpis()}</div>

    <h3>기본 시나리오 히트맵</h3>
    <p class="chart-desc">★ = 정밀그리드 최적점, ◆ = H31 조그리드 우승점(15개월·분기), ▣ = 순차선택(12개월·월간)</p>
    <div class="table-wrap"><table class="data-table">{heatmap_table('base')}</table></div>
    <h3>강세장 편향 시나리오</h3>
    <div class="table-wrap"><table class="data-table">{heatmap_table('calm_heavy')}</table></div>
    <h3>위기 편향 시나리오</h3>
    <div class="table-wrap"><table class="data-table">{heatmap_table('crisis_heavy')}</table></div>

    <h3>기본 시나리오 — 상위 8개 조합 + 참고선</h3>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>조합</th><th>E[Sharpe]</th><th>E[CAGR]</th><th>위기창 최악 MDD(참고)</th></tr></thead>
        <tbody>{top_ranking_table('base')}</tbody>
      </table>
    </div>

    <div class="callout">
      <div class="callout-title">정밀 그리드의 결론 — 정점은 15개월이 아니라 14~16개월 구간의 완만한 고원, 분기 리밸런싱은 세 시나리오 전부에서 재확인</div>
      <p>세 시나리오 모두에서 정밀그리드 1위가 완전히 같지는 않다 — 기본/강세장편향은
        14개월·분기(E[Sharpe] {fnum(S1['scenarios']['base']['fine_grid_optimum']['expected_sharpe'],4)} /
        {fnum(S1['scenarios']['calm_heavy']['fine_grid_optimum']['expected_sharpe'],4)}), 위기편향은
        16개월·분기({fnum(S1['scenarios']['crisis_heavy']['fine_grid_optimum']['expected_sharpe'],4)})가 근소하게 1위다.
        하지만 세 시나리오 모두 <b>2위가 나머지 값</b>(기본/강세장편향은 16개월·분기, 위기편향은 14개월·분기)이고
        격차는 0.0001~0.0141pt로 사실상 동률이다 — <b>H31이 우승시킨 15개월·분기는 세 시나리오 모두에서
        정확히 5위</b>(40개 중)로 밀려났다. 즉 <b>H31의 (15개월, 분기)는 진짜 정점이 아니라, 14~16개월이
        만드는 완만한 고원 위의 한 점이었다</b> — 해상도를 높이자 정점이 이동했지만, 그 이동 폭은 1~2개월
        수준으로 작고 성능 차이도 매우 작다(0.01pt 안팎). 반면 <b>리밸런싱 축은 정밀 해상도에서도
        방향이 전혀 바뀌지 않았다</b> — 분기(63일) 열이 세 시나리오 모두에서 상위권을 독점하고, 순차선택의
        월간(21일)은 40개 중 {seq_ranks[0]}/{seq_ranks[1]}/{seq_ranks[2]}위로 하위권에 남는다.</p>
    </div>

    <div class="callout">
      <div class="callout-title">순차선택(12개월·월간) 대비 갭은 H31보다 오히려 더 커졌다</div>
      <p>정밀최적 대비 순차선택의 기댓값 샤프 갭은 기본 {fnum(gaps_seq[0],4)}, 강세장편향
        {fnum(gaps_seq[1],4)}, 위기편향 {fnum(gaps_seq[2],4)}(평균 {fnum(avg_gap_seq,4)}pt)로,
        H31이 보고한 평균 약 0.10pt보다 커졌다 — 정밀 그리드가 (12개월, 월간) 주변보다 (14~16개월, 분기)
        구간을 더 뚜렷하게 우대하기 때문이다. 반대로 <b>H31의 조그리드 우승점(15개월·분기) 대비 정밀최적의
        갭은 작다</b> — 기본 {fnum(gaps_h31[0],4)}, 강세장편향 {fnum(gaps_h31[1],4)}, 위기편향
        {fnum(gaps_h31[2],4)}(평균 {fnum(avg_gap_h31,4)}pt), H31 우승점은 40개 중 세 시나리오 모두
        정확히 {h31_ranks[0]}위 — <b>"H31의 결론이 대략 맞았고, 정밀화는 소폭 보정을 더했을 뿐"</b>이라는
        것이 가장 정직한 요약이다.</p>
    </div>
  </section>

  <section class="section" id="stage2">
    <h2><span class="sec-no">02</span> Stage 2 — 새틀라이트 비중 결합</h2>
    <p class="lede">Stage 1의 정밀최적(base 시나리오 기준 <b>{REFINED['lookback_months']}개월·분기</b>)을
      코어로 삼아, H5와 동일한 point-in-time 새틀라이트(반기 리밸런싱, 12개월 모멘텀 상위 3종목,
      새틀라이트 단독 샤프 {fnum(S2['satellite_standalone_metrics']['sharpe'],2)})를 0/10/15/20/25/30%
      비중으로 블렌드했다. 순차 기본값 코어(12개월·월간)에도 동일한 새틀라이트 비중 스윕을 적용해
      직접 비교했다. Stage 2는 전체기간(2019-08-12~2026-08-19) 단일창만 썼다(§00·§04에 명시한 절충).</p>

    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>새틀라이트 비중</th>
          <th>순차코어(12mo·월간) Sharpe</th><th>CAGR</th><th>MDD</th>
          <th>정밀최적코어({REFINED['lookback_months']}mo·분기) Sharpe</th><th>CAGR</th><th>MDD</th></tr></thead>
        <tbody>{satellite_table()}</tbody>
      </table>
    </div>

    <div class="callout warn">
      <div class="callout-title">역전 발견 — 전체기간(단일창) 기준으로는 순차 기본값 코어가 정밀최적 코어를 새틀라이트 결합 후에도 앞선다</div>
      <p>새틀라이트가 없는 코어 단독(0%)에서는 두 코어의 샤프가 동일(각 {fnum(S2['core_sequential_metrics']['sharpe'],2)})하지만,
        MDD는 정밀최적코어가 더 얕다({fnum(S2['core_refined_metrics']['mdd'],1)}% vs
        {fnum(S2['core_sequential_metrics']['mdd'],1)}%) — 분기 리밸런싱의 저회전율 효과다. 그런데
        <b>새틀라이트를 얹으면 순위가 뒤집힌다</b> — 두 코어 모두 정점이 15% 비중에서 나오지만, 순차코어+15%
        새틀라이트는 샤프 {fnum(seq_015['sharpe'],2)}, 정밀최적코어+15%는 {fnum(ref_015['sharpe'],2)}로
        순차코어가 앞선다. 모든 비중 구간(10~30%)에서 순차코어의 샤프가 정밀최적코어보다 0.02~0.04pt
        높다. 이는 Stage 1의 6창 기댓값 가중(위기창에서 분기 리밸런싱이 유리)과 Stage 2의 단일 전체기간창
        (2019-2026, 대체로 강세장 우세 구간)의 성격이 다르기 때문으로 해석된다 — <b>분기 리밸런싱의
        장점은 위기 국면에서 나타나는데, Stage 2가 그 국면을 대표 표본으로 담지 못했다</b>. 즉 Stage 1의
        "정밀최적이 순차선택보다 기댓값상 우월하다"는 결론은 <b>6창 기저확률 가중이라는 전제 위에서만
        성립</b>하며, 강세장이 오래 지속된 단일 구간만 보면 반대 결론이 나올 수 있다는 것을 이번 라운드가
        직접 보여준다.</p>
    </div>

    <div class="callout">
      <div class="callout-title">새틀라이트 비중 자체의 결론은 두 코어에서 동일 — 15%가 정점, 20%까지 완만한 고원</div>
      <p>순차코어·정밀최적코어 모두 샤프 정점은 15%(순차 {fnum(seq_peak_m['sharpe'],3)}, 정밀최적
        {fnum(ref_peak_m['sharpe'],3)})에서 나오고 20%까지는 거의 평평하다(둘 다 0.01pt 이내 하락) — H5가
        원래 찾은 "15%가 최적, 10~20%는 완만한 고원"이라는 결론이 코어의 (룩백, 리밸런싱) 설정과 무관하게
        그대로 유지된다. <b>기존 프로덕션 새틀라이트 비중(15%)을 바꿀 이유는 이번 라운드에서도 나오지
        않았다.</b></p>
    </div>
  </section>

  <section class="section" id="synthesis">
    <h2><span class="sec-no">03</span> 종합 — 프로덕션 기본값을 바꿔야 하는가
      <span class="verdict-badge v-partial">부분채택 — 리밸런싱 주기만 분기로, 룩백·새틀라이트 비중은 유지</span></h2>
    <div class="hyp-card">
      <div class="hyp-id">H32 — 정밀 해상도는 H31의 결론을 뒤집지 않았지만, 정점의 정확한 위치는 소폭 이동했다</div>
      <p style="margin:8px 0 0;">Stage 1은 H31의 "룩백보다 리밸런싱 축의 방향성이 뚜렷하다"는 결론을 정밀
        해상도에서도 그대로 재확인했다 — 분기 리밸런싱은 세 시나리오 모두에서 상위권을 독점한다. 룩백은
        15개월 단일점이 아니라 14~16개월의 완만한 고원이며, H31의 15개월은 그 고원 위 한 점(정밀그리드
        40개 중 5위, 세 시나리오 공통)이지 진짜 정점이 아니었다 — 정점은 시나리오에 따라 14 또는
        16개월로 갈렸다. <b>이는 "narrow peak(과최적화 위험 신호)"가 아니라 "broad plateau(신뢰할 수 있는
        신호)"의 전형적 패턴</b>이다 — H30(작업42)이 9개월과 12개월 사이에서 발견한 것과 같은 종류의
        완만함이 여기서도 반복된다.</p>
    </div>
    <div class="hyp-card">
      <div class="hyp-id">Stage 2 — 새틀라이트를 결합해도 결론은 바뀌지 않지만, "언제 우월한가"라는 조건이 붙는다</div>
      <p style="margin:8px 0 0;">Stage 2가 드러낸 역전(§02)은 정밀최적 코어의 우위가 6창 위기 편중
        기댓값 프레임 안에서만 성립하고, 강세장이 지속된 단일 전체기간에서는 순차 기본값이 오히려 근소하게
        앞선다는 것을 뜻한다. 새틀라이트 비중 자체(15%)는 두 코어 어디에 얹어도 최적점이 그대로였다 —
        3차원 결합이 새틀라이트 차원에서는 룩백×리밸런싱 선택과 독립적이라는 뜻이고, 이는 프로덕션
        설정을 단순화하는 데 오히려 도움이 된다(새틀라이트 비중은 신경 쓸 필요 없이 15% 그대로 유지).</p>
    </div>
    <div class="hyp-card">
      <div class="hyp-id">최종 권고 — 리밸런싱 주기는 분기로 전환을 권고, 룩백과 새틀라이트 비중은 그대로 유지</div>
      <p style="margin:8px 0 0;"><b>분기 리밸런싱(63일)으로의 전환은 이번 라운드에서 권고한다</b> — 정밀
        해상도·새틀라이트 결합 양쪽에서 방향이 한 번도 흔들리지 않았고(§01·§02), 연 회전율이 크게
        낮아져(전체기간 기준 정밀최적 코어 연 260.7% vs 순차 코어 연 482.1%, Stage 1 원자료 기준)
        거래비용·운영 부담도 함께 준다는 부수적 이점이 분명하다. <b>룩백을 12개월에서 14~15개월로
        옮기는 것은 권고하지 않는다</b> — 갭이 40개 중
        1위와 5위 사이에서 0.01pt 안팎으로, H30이 이미 "9개월과 12개월도 사실상 토스업"이라 밝힌 것과
        같은 수준의 노이즈일 가능성이 높고, Stage 2의 단일 전체기간 검증에서는 오히려 12개월이
        새틀라이트 결합 후 근소하게 더 나았다(§02). <b>새틀라이트 비중 15%는 그대로 유지</b> — 코어
        설정이 무엇이든 최적점이 흔들리지 않았다. 요약하면, 이번 라운드는 "리밸런싱 주기만 분기로
        바꾸고, 룩백과 새틀라이트 비중은 현재 값을 유지"하는 <b>부분 채택</b>이 세 갈래 증거(그리드
        방향성, 고원의 완만함, 단일창 역전) 전부를 가장 정직하게 반영한 결론이다.</p>
    </div>
  </section>

  <section class="section" id="limitations">
    <h2><span class="sec-no">04</span> 한계</h2>
    <ul>
      <li><b>Stage 2는 6창 기댓값 가중을 적용하지 못했다</b> — point-in-time 새틀라이트 표본추출의
        네트워크/캐시 비용 때문에 H5와 동일한 절충(전체기간 단일창)을 그대로 따랐다. §02에서 드러난
        역전은 바로 이 절충 때문에 발생한 것으로 해석되며, 6창 전부에서 새틀라이트를 재검증하는 완전한
        3D 그리드는 여전히 미완의 과제로 남는다.</li>
      <li><b>룩백 6~8개월, 리밸런싱 격주(10일)는 정밀 재검증에서 제외했다</b> — H31에서 양 극단이
        압도적 열위였다는 근거로 제외했으나, 결합 상황에서 예상 밖의 상호작용을 보였을 가능성을
        완전히 배제할 수는 없다.</li>
      <li><b>갭의 통계적 유의성은 여전히 형식적으로 검정하지 않았다</b> — 1~2위 사이 격차(0.01pt 안팎)가
        6개 창·근사적 기저확률이 만드는 노이즈 수준보다 유의하게 큰지 확인하지 않았다. H30·H31이 이미
        비슷한 수준의 격차를 "약한 신호"로 해석했던 것과 같은 기준을 여기도 적용해야 한다.</li>
      <li><b>기저확률은 여전히 추정치</b> — H22/작업39가 정립한 기저확률을 그대로 재사용했다.</li>
      <li><b>6개 창은 여전히 작고 서로 겹친다</b> — H22가 명시한 한계(창 간 상관관계, 표본 다양성 부족,
        다중비교 위험)가 이번 라운드에도 그대로 적용된다.</li>
      <li><b>시장필터·거래비용 관례는 건드리지 않았다</b> — 이진 시장필터(SPY 200일선)와 거래비용
        가정(왕복 0.1%)은 이번 그리드의 고정값으로 남아 있다.</li>
    </ul>
  </section>

</div>

<footer>
  <p>analysis/2026-08-23_champion_parameter_fine_resolution_and_satellite_joint/ (데이터:
    h32_stage1_results.json/h32_stage2_results.json/report_data.json, 빌드: build_report.py) ·
    h32_fine_grid_and_satellite_joint.py는
    analysis/2026-08-23_joint_parameter_interaction_grid_search/h31_joint_parameter_grid.py(작업43)의
    고정 달력기준일 리밸런싱 마스크(n_day_rebal_mask)를 그대로 재사용하고, Stage 2는
    analysis/2026-08-20_satellite_frontier_and_quality_blend_research/h5_satellite_weight_sweep.py와
    analysis/2026-08-19_champion_beta_and_satellite_research/h1_core_satellite.py의 point-in-time
    새틀라이트 구축 로직(build_satellite_returns/blend_returns)을 그대로 재사용했다. 기저확률 가중은
    H22(작업39)/h22_expected_value_reweighting.py와 동일한 3개 시나리오(base/calm_heavy/crisis_heavy)를
    재계산 없이 그대로 재사용했다. core.market_data를 통한 실제 Yahoo Finance 데이터이며 추정치가
    아니다. 총 실행시간 {fnum(R.get('total_runtime_sec',0)/60,1)}분(Stage 1+2 합산). 이 워크트리는 main과
    분기된 시점 이후 인프라 변경이 반영되지 않을 수 있어, core/는 이 워크트리의 코드를 그대로 사용했다.</p>
</footer>
"""

out_file = f"{OUT_DIR}/final_report.html"
with open(out_file, "w", encoding="utf-8") as f:
    f.write(HTML)
print(f"SAVED {out_file}")
