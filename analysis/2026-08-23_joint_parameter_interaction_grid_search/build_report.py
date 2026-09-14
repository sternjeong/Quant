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
H31 = R["h31"]

LOOKBACKS = H31["lookback_months"]
FREQS = list(H31["frequencies"].keys())
SEQ = H31["sequential_choice"]


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
    "biweekly_10d": "격주(10거래일)", "monthly_21d": "월간(21거래일, 순차선택)",
    "sixweek_30d": "6주(30거래일)", "quarterly_63d": "분기(63거래일)",
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


def sharpe_to_color(v, vmin, vmax):
    """value -> heatmap 배경색 (accent 계열, 낮을수록 옅게/붉게, 높을수록 진한 accent)."""
    if vmax == vmin:
        t = 0.5
    else:
        t = (v - vmin) / (vmax - vmin)
    t = max(0.0, min(1.0, t))
    # 저값: 옅은 붉은끼, 고값: 진한 accent green - CSS var로는 직접 보간 불가하니 rgba 근사
    r_lo, g_lo, b_lo = (227, 73, 72)   # --red 근사
    r_hi, g_hi, b_hi = (31, 77, 61)    # --accent 근사
    r = int(r_lo + (r_hi - r_lo) * t)
    g = int(g_lo + (g_hi - g_lo) * t)
    b = int(b_lo + (b_hi - b_lo) * t)
    alpha = 0.14 + 0.55 * t
    return f"rgba({r},{g},{b},{alpha:.2f})"


def heatmap_table(scen_name):
    scen = H31["scenarios"][scen_name]
    grid = scen["expected_value_grid"]
    vals = [v["expected_sharpe"] for v in grid.values()]
    vmin, vmax = min(vals), max(vals)
    seq_key = scen["sequential_choice_value"]["key"]
    joint_key = scen["joint_optimum"]["key"]

    header = "".join(f"<th>{FREQ_LABEL[f]}</th>" for f in FREQS)
    rows = []
    for months in LOOKBACKS:
        cells = []
        for f in FREQS:
            key = f"{months}|{f}"
            v = grid[key]["expected_sharpe"]
            bg = sharpe_to_color(v, vmin, vmax)
            cls = "seq-cell" if key == seq_key else ("best-row" if key == joint_key else "")
            marker = ""
            if key == joint_key:
                marker = " ★"
            elif key == seq_key:
                marker = " ▣"
            cells.append(f'<td class="num {cls}" style="background:{bg};">{fnum(v,3,True)}{marker}</td>')
        rows.append(f'<tr><td class="tk-cell"><span class="tk-name">{months}개월</span></td>{"".join(cells)}</tr>')
    return f'<thead><tr><th>룩백 \\ 리밸런싱</th>{header}</tr></thead><tbody>{"".join(rows)}</tbody>'


def top_ranking_table(scen_name, n=6):
    scen = H31["scenarios"][scen_name]
    rows = []
    seq_key = scen["sequential_choice_value"]["key"]
    for i, (key, v) in enumerate(scen["ranking_by_expected_sharpe"][:n]):
        months, freq = key.split("|")
        cls = "best-row" if i == 0 else ("warn-row" if key == seq_key else "")
        label = f"{months}개월 · {FREQ_LABEL[freq]}"
        tag = " (순차선택)" if key == seq_key else (" (결합 최적)" if i == 0 else "")
        rows.append(
            f'<tr class="{cls}"><td class="tk-cell"><span class="tk-name">{i+1}. {esc(label)}{tag}</span></td>'
            f'<td class="num">{fnum(v["expected_sharpe"],4)}</td>'
            f'<td class="num">{fnum(v["expected_cagr_pct"],2,True)}%</td>'
            f'<td class="num">{fnum(v["mdd_worst_case"],2)}%</td></tr>'
        )
    # sequential row if not already in top n
    if seq_key not in [k for k, _ in scen["ranking_by_expected_sharpe"][:n]]:
        rank = scen["sequential_rank_out_of_20"]
        v = scen["sequential_choice_value"]
        rows.append(
            f'<tr class="warn-row"><td class="tk-cell"><span class="tk-name">{rank}. '
            f'{SEQ["lookback_months"]}개월 · {FREQ_LABEL[SEQ["freq_name"]]} (순차선택)</span></td>'
            f'<td class="num">{fnum(v["expected_sharpe"],4)}</td>'
            f'<td class="num">{fnum(v["expected_cagr_pct"],2,True)}%</td>'
            f'<td class="num">{fnum(v["mdd_worst_case"],2)}%</td></tr>'
        )
    return "".join(rows)


def summary_kpis():
    tiles = []
    for scen_name in ["base", "calm_heavy", "crisis_heavy"]:
        scen = H31["scenarios"][scen_name]
        gap = scen["sharpe_gap_joint_minus_sequential"]
        rank = scen["sequential_rank_out_of_20"]
        cls = "pos" if gap > 0.05 else ""
        tiles.append(f"""
        <div class="kpi-tile">
          <div class="kpi-label">{esc(SCEN_LABEL[scen_name])} — 결합최적 vs 순차선택 갭</div>
          <div class="kpi-value {cls}">+{fnum(gap,4)}</div>
          <div class="kpi-sub">순차선택(12개월·월간) 순위: {rank}/20</div>
        </div>""")
    return "".join(tiles)


gaps = [H31["scenarios"][s]["sharpe_gap_joint_minus_sequential"] for s in ["base", "calm_heavy", "crisis_heavy"]]
avg_gap = sum(gaps) / len(gaps)
joint_opt_keys = {H31["scenarios"][s]["joint_optimum"]["key"] for s in ["base", "calm_heavy", "crisis_heavy"]}
same_joint_across_scenarios = len(joint_opt_keys) == 1
ranks = [H31["scenarios"][s]["sequential_rank_out_of_20"] for s in ["base", "calm_heavy", "crisis_heavy"]]

HTML = f"""<title>파라미터 결합효과 검증 연구</title>
<style>
{CSS}
</style>

<div class="masthead">
  <div class="masthead-inner">
    <div class="masthead-eyebrow">
      <span>QUANT RESEARCH NOTE</span><span class="dot">·</span><span>15라운드</span><span class="dot">·</span><span>Hypothesis-Driven Study</span>
    </div>
    <h1 class="masthead-title">모멘텀 룩백 x 리밸런싱 주기, 결합 그리드로 다시 본다</h1>
    <p class="masthead-sub">작업40(H27)이 모멘텀 룩백을, 작업41(H29)이 리밸런싱 주기를 각각 <b>다른
      파라미터는 그 시점까지의 기본값에 고정한 채</b> 독립적으로 스윕해 "12개월·월간"이라는 순차
      최적값에 도달했다. 이 라운드는 두 파라미터를 동시에 바꾸는 5×4 결합 그리드를 새로 백테스트해,
      순차 최적값이 실제 결합 최적점에 얼마나 가까운지 — 다시 말해 지금까지의 순차적 단일 파라미터
      튜닝이 상호작용 효과를 놓쳐온 것은 아닌지 — 직접 검증한다.</p>
    <div class="masthead-meta">
      <span><b>기준일</b> {esc(GEN)}</span>
      <span><b>그리드</b> 룩백 {"/".join(str(m) for m in LOOKBACKS)}개월 × 리밸런싱 {"/".join(FREQ_LABEL[f].split("(")[0] for f in FREQS)} = 20점</span>
      <span><b>검증 창</b> 전체기간(2019-2026) + 2008/2022/COVID/2018/2015-16 위기창 6개 × 20그리드점 = 120회 백테스트</span>
      <span><b>기저확률 시나리오</b> H22/작업39와 동일(기본/강세장편향/위기편향), 가중치 그대로 재사용</span>
    </div>
  </div>
</div>

<div class="wrap">

  <nav class="toc">
    <a href="#scope">00 문제 제기</a>
    <a href="#design">01 결합 그리드 설계</a>
    <a href="#results">02 실행 결과 (히트맵)</a>
    <a href="#synthesis">03 종합</a>
    <a href="#limitations">04 한계</a>
  </nav>

  <section class="section" id="scope">
    <h2><span class="sec-no">00</span> 문제 제기 — 왜 순차 최적화가 위험할 수 있는가</h2>
    <p class="lede">이 시리즈는 6~14라운드에 걸쳐 챔피언의 여러 설계 파라미터를 <b>순서대로, 한 번에
      하나씩</b> 스윕해왔다. 각 라운드는 그 시점까지 이미 정해진 다른 파라미터를 고정값으로 두고
      단일 파라미터만 바꿨다 — 전형적인 "그리디(greedy) 순차 최적화" 패턴이다.</p>
    <ul>
      <li><b>작업31/39 (H5)</b> — 새틀라이트 비중을 스윕(고정된 선정방식·고정된 리밸런싱 주기 대비) →
        15% 채택.</li>
      <li><b>작업40 (H27)</b> — 모멘텀 룩백을 3~18개월로 스윕(챔피언의 기존 고정 월간 리밸런싱·
        고정 필터 대비) → 12개월 채택.</li>
      <li><b>작업41 (H29)</b> — 리밸런싱 주기를 주간~분기로 스윕(H27이 방금 정한 12개월 룩백 고정
        대비) → 월간 채택.</li>
    </ul>
    <p>순차 튜닝의 위험은 잘 알려져 있다 — 파라미터 A를 B·C를 고정한 채 최적화해서 찾은 값이, B·C도
      함께 바뀌는 상황에서까지 최적이라는 보장은 없다. 두 파라미터 사이에 상호작용(interaction)이
      있다면, 결합 최적점은 순차 탐색이 방문한 적도 없는 조합에 있을 수 있다. 이번 라운드는 룩백×
      리밸런싱 2차원에서 그것이 실제로 일어나는지 실측한다.</p>
    <p class="caveat">⚠️ 투자 조언이 아니다. 기저확률은 문헌 기반 추정치이며(작업39/H22 근거 그대로
      재사용), 정밀한 확률표가 아니다.</p>
  </section>

  <section class="section" id="design">
    <h2><span class="sec-no">01</span> 결합 그리드 설계</h2>
    <p class="lede">룩백 5개(6/9/12/15/18개월) × 리밸런싱 4개(격주/월간/6주/분기) = 20개 그리드점을
      전체기간+5개 위기창에서 전부 신규 백테스트했다(120회). H27/H29 개별 스윕(각 6곳×6값=36회) 대비
      해상도를 낮췄다 — 룩백에서 3개월(두 스윕 모두 최하위가 확정적이었던 값)을, 빈도에서 주간
      (회전율 폭발로 최하위가 확정적이었던 값)을 제외해 계산량을 억제했다. 완전한 2D 결과를 완주하는
      것을 3D(새틀라이트 비중까지 포함) 확장보다 우선했다 — 이번 라운드는 3D 확장까지 갈 시간이
      없었고, 이는 정직하게 밝히는 축소다.</p>
    <p>모멘텀 신호·시장필터·거래비용(왕복 0.1%, 비중변화 절대값 기준) 관례는 H27/H29와 동일하게
      <code>champion_strategy.py</code>를 그대로 재사용했다. 리밸런싱 마스크는 "N거래일마다"로
      일반화한(H29와 동일한 방식) 커스텀 마스크를 썼는데, <b>위상(phase) 고정 방식은 H29 원본에서
      한 단계 개선했다</b> — H29는 배열 인덱스 0번째부터 N일 간격으로 셌는데, 이는 fetch 시작일(warmup
      크기)에 따라 실제 리밸런싱 날짜가 임의로 밀리는 아티팩트가 있음을 이번 라운드가 실측 중
      발견했다(같은 "월간" 이름표를 붙여도 warmup을 다르게 잡으면 위기창 샤프가 크게 달라짐 — 경제적
      차이가 아니라 순전한 위상 우연이었다). 이 그리드는 고정 달력기준일(2000-01-03)로부터의
      영업일수 mod n으로 위상을 고정해 이 문제를 없앴다 — 그 결과 검증 차원에서, 이 그리드의
      (12개월·월간) 셀이 H27이 보고한 순수 12개월·월간 수치와 시나리오별로 오차 0.01~0.08pt 내에서
      잘 일치함을 확인했다(완전히 동일하지 않은 것은 H27의 진짜 "매월 첫 거래일" 달력마스크 대비
      "N거래일마다" 근사라는, H29가 이미 밝힌 별도의 잔차 때문).</p>
  </section>

  <section class="section" id="results">
    <h2><span class="sec-no">02</span> 실행 결과 — 시나리오별 히트맵</h2>
    <p class="lede">아래 세 히트맵은 각각 기본/강세장편향/위기편향 시나리오에서 20개 그리드점의
      기댓값 샤프를 보여준다. <b>★는 그 시나리오의 결합 최적점</b>, <b>▣는 지금까지 순차 최적화가
      도달한 (12개월·월간) 조합</b>이다.</p>

    <div class="kpi-row">{summary_kpis()}</div>

    <h3>기본 시나리오</h3>
    <div class="table-wrap"><table class="data-table">{heatmap_table('base')}</table></div>
    <h3>강세장 편향 시나리오</h3>
    <div class="table-wrap"><table class="data-table">{heatmap_table('calm_heavy')}</table></div>
    <h3>위기 편향 시나리오</h3>
    <div class="table-wrap"><table class="data-table">{heatmap_table('crisis_heavy')}</table></div>

    <h3>기본 시나리오 — 상위 6개 조합 + 순차선택 위치</h3>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>조합</th><th>E[Sharpe]</th><th>E[CAGR]</th><th>위기창 최악 MDD(참고)</th></tr></thead>
        <tbody>{top_ranking_table('base')}</tbody>
      </table>
    </div>

    <div class="callout">
      <div class="callout-title">세 시나리오 모두에서 결합 최적점은 동일 — (15개월·분기)</div>
      <p><b>{'세 시나리오 전부에서 결합 최적점이 (15개월, 분기)로 동일하다' if same_joint_across_scenarios else '시나리오별로 결합 최적점이 갈린다'}</b> —
        기본 E[Sharpe] {fnum(H31['scenarios']['base']['joint_optimum']['expected_sharpe'],3,True)},
        강세장편향 {fnum(H31['scenarios']['calm_heavy']['joint_optimum']['expected_sharpe'],3,True)},
        위기편향 {fnum(H31['scenarios']['crisis_heavy']['joint_optimum']['expected_sharpe'],3,True)}. 순차선택(12개월·월간)은
        세 시나리오에서 각각 {ranks[0]}위/{ranks[1]}위/{ranks[2]}위(20개 중)로, <b>상위권(20개 중 5~6위)에는
        들지만 결합 최적점은 아니다.</b> 갭(결합최적 − 순차선택 기댓값샤프)은 기본
        {fnum(gaps[0],4)}, 강세장편향 {fnum(gaps[1],4)}, 위기편향 {fnum(gaps[2],4)}, 평균
        {fnum(avg_gap,4)}p — H27/H29 개별 스윕이 보고한 순위 1위와 2위 사이 격차(대개 0.01~0.09pt대)와
        같은 자릿수이며, "확실히 크다"고 말하기는 어렵지만 "무시할 수 없다"고 보는 것이 더 정직하다.</p>
    </div>

    <div class="callout">
      <div class="callout-title">그리드의 형태 — 룩백보다 리밸런싱 축의 방향성이 더 뚜렷하다</div>
      <p>히트맵을 가로(리밸런싱)로 읽으면, 분기(63일) 열이 세 시나리오 모두에서 가장 진한(높은) 색을
        보이고 격주(10일) 열이 가장 옅다(낮다) — H29가 "더 자주 리밸런싱한다고 위기에 유리해지지
        않는다"고 결론낸 방향성이 이 그리드에서도 룩백값과 무관하게 일관되게 유지된다. 세로(룩백)로
        읽으면 9~15개월 구간이 완만한 봉우리를 이루고 6개월과 18개월 양 극단이 상대적으로 열위다 —
        H27의 "12개월이 최선" 결론과 방향은 같지만, 정확한 정점은 룩백 단독으로 봤을 때(12개월)와
        결합해서 봤을 때(15개월) 한 칸 어긋난다. 즉 <b>두 축 사이에 약한 상호작용은 실제로 존재하되,
        어느 한쪽도 결합에 의해 뒤집히지는 않는다</b> — "더 잦은 리밸런싱이 유리해진다"거나 "훨씬 짧은
        룩백이 유리해진다"는 식의 질적 반전은 어디에도 없다.</p>
    </div>
  </section>

  <section class="section" id="synthesis">
    <h2><span class="sec-no">03</span> 종합 — 순차 최적화는 얼마나 위험했나
      <span class="verdict-badge v-partial">부분채택 (약한 상호작용 확인, 순차선택은 여전히 견고한 근사값)</span></h2>
    <div class="hyp-card">
      <div class="hyp-id">H31 — 결합 최적점은 순차선택과 다르지만, 격차는 작고 방향은 같다</div>
      <p style="margin:8px 0 0;">세 시나리오 모두에서 결합 최적점은 (15개월·분기)로, 순차 최적화가
        도달한 (12개월·월간)과는 다르다 — 순차 결과는 20개 중 5~6위에 그친다. 다만 기댓값 샤프 갭은
        평균 {fnum(avg_gap,4)}pt로, 이 연구 시리즈가 지금까지 "근소한 차이"로 분류해온 다른 갭들
        (예: H29의 위기편향 시나리오에서 월간 대 6주 갭 0.03pt)과 같은 자릿수다. <b>"순차 튜닝이
        완전히 강건했다"고 결론내리기는 어렵지만, "순차 튜닝이 심각하게 잘못된 답을 냈다"고 보기도
        어렵다</b> — 순차 최적화가 상위 30% 안에 드는 근사적으로 좋은 답을 찾았지만, 정확한 결합
        최적점은 아니었다는 것이 가장 정직한 요약이다.</p>
    </div>
    <div class="hyp-card">
      <div class="hyp-id">최종 권고 설정이 바뀌어야 하는가 — 조건부로 그렇다</div>
      <p style="margin:8px 0 0;">순수 기댓값 극대화가 목표라면 (15개월 룩백·분기 리밸런싱)이 이
        그리드에서 찾은 최선이며, 연 회전율이 크게 낮아 거래비용 부담도 준다는 부수적 장점이 있다.
        다만 이 결과 하나로 즉시 기본값을 바꾸는 것은 시기상조다 — 이번 그리드는 해상도를 낮춘
        20점뿐이고(§01), 갭 자체가 이 연구가 쓰는 6개 창의 노이즈 수준과 겹칠 수 있다(§04). <b>실용적
        절충안은 "12개월·월간을 여전히 기본값으로 유지하되, 15개월·분기를 향후 라운드에서 더 촘촘한
        해상도로 재검증할 후보로 명시적으로 승격"하는 것</b> — 15라운드에 걸친 이 연구 프로그램
        전체의 신뢰도 관점에서, 이번 결과는 "순차 튜닝이 크게 틀리지는 않았지만 완벽하지도 않았다"는
        중간 지점의 정직한 확인으로 남는다.</p>
    </div>
    <div class="hyp-card">
      <div class="hyp-id">연구 프로그램 전체에 대한 함의</div>
      <p style="margin:8px 0 0;">6~14라운드에 걸친 다른 순차 스윕들(새틀라이트 비중 15%, 스탑폭 10%
        등)도 원칙적으로는 같은 위험에 노출돼 있다 — 이번 라운드가 검증한 것은 룩백×리밸런싱 2차원
        하나뿐이다. 다만 이번 결과가 보여준 "상호작용은 있지만 질적 반전은 없다"는 패턴이 다른
        파라미터 쌍에도 일반화된다면(검증되지 않은 가정), 이 연구 프로그램 전체의 9개 이상 순차
        라운드가 근본적으로 잘못된 방향을 가리켰을 위험은 낮다고 잠정 평가할 수 있다 — 다만 이는
        추정이며, 향후 라운드가 다른 파라미터 쌍(예: 새틀라이트 비중×스탑폭)에서 같은 결합 검증을
        반복해 확인할 가치가 있는 미해결 과제로 명시적으로 남긴다.</p>
    </div>
  </section>

  <section class="section" id="limitations">
    <h2><span class="sec-no">04</span> 한계</h2>
    <ul>
      <li><b>그리드 해상도 축소</b> — 20점(5×4)은 H27/H29 개별 스윕(각 6값)보다 성기다. 특히 룩백에서
        제외한 3개월, 빈도에서 제외한 주간이 결합 상황에서는 어떤 예상 밖 상호작용을 보였을 가능성을
        배제할 수 없다(다만 개별 스윕에서 두 값 모두 압도적 열위였으므로 가능성은 낮다고 판단).</li>
      <li><b>3D(새틀라이트 비중 포함) 확장은 시도하지 못했다</b> — 스펙이 명시한 스트레치 목표였으나,
        완전한 2D 결과를 우선하기로 하고 시간 내에 착수하지 못했다. 새틀라이트 비중×룩백×리밸런싱의
        3원 상호작용은 여전히 미검증 상태로 남는다.</li>
      <li><b>갭의 통계적 유의성은 검증하지 않았다</b> — 결합최적과 순차선택 사이의 기댓값 샤프 갭
        (평균 {fnum(avg_gap,4)}pt)이 6개 창·근사적 기저확률이 만드는 노이즈 수준보다 유의하게 큰지
        형식적으로 검정하지 않았다. H29가 이미 비슷한 크기의 갭(월간 vs 6주, 위기편향)을 "통계적으로
        구분하기 어려운 수준"으로 해석했던 것과 같은 기준을 적용한다면, 이번 갭도 "확실한 우위"보다는
        "약한 신호"로 보는 것이 더 정직하다.</li>
      <li><b>리밸런싱 마스크는 여전히 "N거래일마다"로 단순화</b> — 이번 라운드가 위상 아티팩트는
        고쳤지만(§01), 실제 챔피언의 "매월 첫 거래일" 달력 기준 리밸런싱과는 여전히 다른 근사다.</li>
      <li><b>기저확률은 여전히 추정치</b> — H22/작업39가 정립한 기저확률을 그대로 재사용했다. 이
        수치들의 불확실성에 대한 한계는 H22 리포트에 이미 상세히 기술되어 있다.</li>
      <li><b>6개 창은 여전히 작고 서로 겹친다</b> — H22가 명시한 한계(창 간 상관관계, 표본 다양성
        부족, 다중비교 위험)가 이번 라운드에도 그대로 적용된다.</li>
      <li><b>필터·새틀라이트 비중은 건드리지 않았다</b> — 이진 시장필터(SPY 200일선)와 새틀라이트
        비중(15%)은 이번 그리드의 고정값으로 남아 있다. 이들을 포함한 더 큰 결합 그리드는 향후
        과제다.</li>
    </ul>
  </section>

</div>

<footer>
  <p>analysis/2026-08-23_joint_parameter_interaction_grid_search/ (데이터: report_data.json, 빌드:
    build_report.py) · h31_joint_parameter_grid.py는
    analysis/2026-08-19_champion_beta_and_satellite_research/champion_strategy.py의 17자산 챔피언
    빌딩블록(fetch_champion_histories/compute_portfolio_returns)을 재사용하고, build_champion_weights
    로직을 momentum_window와 리밸런싱 빈도 둘 다 가변으로 일반화한 build_weights_joint()로 5개
    룩백×4개 빈도×6개 창=120회를 전부 신규 백테스트했다. 리밸런싱 마스크는 H29(작업41)의 "N거래일마다"
    방식을 재사용하되, 위상을 고정 달력기준일(2000-01-03)로부터의 영업일수 mod n으로 고정해 warmup
    크기에 따라 위상이 임의로 밀리는 아티팩트를 제거했다(h31_joint_parameter_grid.py의 n_day_rebal_mask
    docstring 참고). 기저확률 가중은 H22(작업39)/h22_expected_value_reweighting.py와 동일한 3개
    시나리오(base/calm_heavy/crisis_heavy)를 재계산 없이 그대로 재사용했다. core.market_data를 통한
    실제 Yahoo Finance 데이터이며 추정치가 아니다. 이 워크트리는 main과 분기된 시점 이후 인프라 변경이
    반영되지 않을 수 있어, 모든 스크립트가 main 체크아웃(/workspaces/Quant)의 core/ 및 이전 라운드
    analysis/를 직접 참조해 실행했다 — 이 워크트리의 core/는 건드리지 않았다.</p>
</footer>
"""

out_file = f"{OUT_DIR}/final_report.html"
with open(out_file, "w", encoding="utf-8") as f:
    f.write(HTML)
print(f"SAVED {out_file}")
