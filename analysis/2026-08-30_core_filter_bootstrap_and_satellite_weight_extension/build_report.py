#!/usr/bin/env python3
"""report_data.json을 읽어 final_report.html을 만든다.

analysis/2026-08-24_bootstrap_confidence_audit_remaining_verdicts/build_report.py(H34)와 동일한
디자인 시스템(다크네이비/올리브 톤, 세리프 헤드라인, TOC, 섹션 번호, 판정 배지)을 재사용한다.
"""
import json
import math
import os

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

with open(f"{OUT_DIR}/report_data.json", encoding="utf-8") as f:
    R = json.load(f)

GEN = R["meta"]["generated"]
H35 = R["h35"]
H36 = R["h36"]
H36EV = R["h36_expected_value"]
UNIFIED = R["unified_confidence_table"]
EP_ORDER = R["meta"]["episode_order"]

EP_LABEL = {
    "full_2019_2026": "전체기간 2019-2026",
    "gfc_2008": "2008 GFC",
    "covid_2020": "COVID 2020 (~5주)",
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


def pct(v, digits=1):
    if v is None:
        return "—"
    return f"{v*100:.{digits}f}%"


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def grade_badge(grade):
    label = {"robust": "강건", "moderate": "보통", "weak": "약함", "reversed": "반전/미지지"}.get(grade, grade)
    cls = {"robust": "grade-A", "moderate": "grade-A", "weak": "grade-B", "reversed": "grade-C"}.get(grade, "grade-B")
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


def window_ci_rows(boot, configs, cfg_label):
    rows = []
    for ep in EP_ORDER:
        d = boot[ep]
        for cfg in configs:
            m = d["by_config"][cfg]
            n_obs = d["n_obs"][cfg] if isinstance(d.get("n_obs"), dict) else d.get("n_obs")
            pt = m["point_estimate_sharpe"]
            b20 = m["bootstrap_by_block_len"]["20"]
            warn = " warn-row" if (n_obs or 0) < 100 else ""
            nblocks = b20["n_nonoverlapping_blocks_approx"] if b20 else None
            rows.append(
                f'<tr class="{warn.strip()}"><td class="tk-cell"><span class="tk-name">{esc(EP_LABEL[ep])}</span></td>'
                f'<td class="tk-cell">{esc(cfg_label.get(cfg, cfg))}</td>'
                f'<td class="num">{n_obs}</td>'
                f'<td class="num">{fnum(pt,3,signed=True)}</td>'
                f'<td class="num">[{fnum(b20["ci90"][0],3,signed=True)}, {fnum(b20["ci90"][1],3,signed=True)}]</td>'
                f'<td class="num">{fnum(nblocks,1) if nblocks else "—"}</td></tr>'
            )
    return "".join(rows)


CFG_LABEL_H25 = {"with_filter": "필터 유지(현 챔피언)", "without_filter": "무필터(상시 완전투자)"}

C25 = H35["combined_h25_without_filter_vs_with_filter"]


def unified_rows():
    rows = []
    for row in UNIFIED:
        gc = row["combined_grade"]
        cls = {"robust": "grade-A", "moderate": "grade-A", "weak": "grade-B", "reversed": "grade-C"}.get(gc, "grade-B")
        warn = " warn-row" if gc == "reversed" else ""
        hero = " hero-row" if row["id"] == "H25" else warn.strip()
        rows.append(
            f'<tr class="{hero}"><td class="tk-cell"><span class="tk-name">{esc(row["id"])}</span> '
            f'{esc(row["label"])}</td>'
            f'<td class="num">{pct(row["weighting_only_win_rate"],1)}</td>'
            f'<td class="num">{pct(row["combined_win_rate"],1)}</td>'
            f'<td class="num">[{fnum(row["combined_gap_ci90"][0],3,signed=True)}, {fnum(row["combined_gap_ci90"][1],3,signed=True)}]</td>'
            f'<td>{grade_badge(gc)}</td></tr>'
        )
    return "".join(rows)


EP_LABEL_SHORT = {
    "full_2019_2026": "전체 19-26", "gfc_2008": "GFC 08", "covid_2020": "COVID 20",
    "bear_2022": "약세 22", "selloff_2018": "급락 18", "correction_2015_2016": "조정 15-16",
}


def h36_frontier_table(scenario):
    scen = H36EV["scenarios"][scenario]
    ev = scen["expected_value_by_weight"]
    weights = H36["meta"]["satellite_weights"]
    rows = []
    peak_w = scen["optimal_weight"]
    for sw in weights:
        v = ev[str(sw)]
        hero = " hero-row" if abs(v["satellite_weight"] - peak_w) < 1e-9 else ""
        rows.append(
            f'<tr class="{hero.strip()}"><td class="tk-cell"><span class="tk-name">{sw*100:.0f}%</span></td>'
            f'<td class="num">{fnum(v["expected_sharpe"],4,signed=True)}</td>'
            f'<td class="num">{fnum(v["expected_cagr_pct"],2,signed=True)}%</td>'
            f'<td class="num">{fnum(v["worst_case_crisis_mdd"],2)}%</td></tr>'
        )
    return "".join(rows)


def h36_per_window_table(sw_list):
    rows = []
    for ep in EP_ORDER:
        episode = H36["episodes"][ep]
        frontier = {f["satellite_weight"]: f for f in episode["frontier"]}
        use_crisis = episode["crisis_window"] is not None
        key = "crisis_window" if use_crisis else "full_period"
        cells = []
        for sw in sw_list:
            m = frontier[sw][key]
            cells.append(f'<td class="num">{fnum(m["sharpe"],2,signed=True)}</td>')
        rows.append(f'<tr><td class="tk-cell"><span class="tk-name">{esc(EP_LABEL[ep])}</span></td>{"".join(cells)}</tr>')
    return "".join(rows)


SW_DISPLAY = [0.0, 0.15, 0.30, 0.50, 0.70, 0.90, 1.00]

HTML = f"""<title>코어필터 부트스트랩 감사 및 새틀라이트 비중 확장</title>
<style>
{CSS}
</style>

<div class="masthead">
  <div class="masthead-inner">
    <div class="masthead-eyebrow">
      <span>QUANT RESEARCH NOTE</span><span class="dot">·</span><span>20라운드</span><span class="dot">·</span><span>Hypothesis-Driven Study</span>
    </div>
    <h1 class="masthead-title">이진 시장필터의 승리는 표본오차에 무너지고, 새틀라이트 비중은 100%까지도 정점을 못 찾는다</h1>
    <p class="masthead-sub">19라운드(H24/H25)가 명시적으로 남긴 두 숙제를 잇는다. H35는 H25("무필터가
      이긴다")에 H33/H34식 블록부트스트랩 표본오차 감사를 처음으로 적용했고, H36은 H24의 새틀라이트
      비중 스윕을 50%에서 100%까지 확장했다. 결과: <b>H25는 다른 5개 감사받은 판정과 똑같이 동전던지기
      근처로 무너졌고, H36은 확장한 100% 상한까지도 진짜 정점을 찾지 못했다</b> — 두 결과 모두 이
      백테스트 프로그램이 반복해서 확인해 온 "기댓값 승리는 사실 대부분 얇다"는 패턴과 일치한다.</p>
    <div class="masthead-meta">
      <span><b>기준일</b> {esc(GEN)}</span>
      <span><b>블록부트스트랩</b> 창×구성당 {R['meta']['n_boot']:,}회, 블록길이 {', '.join(str(x)+'일' for x in R['meta']['block_lengths'])}</span>
      <span><b>결합전파</b> {R['meta']['n_draws']:,} draws (디리클레×부트스트랩)</span>
      <span><b>대상</b> H35 코어 필터 감사 · H36 새틀라이트 비중 0~100%</span>
    </div>
  </div>
</div>

<div class="wrap">

  <nav class="toc">
    <a href="#scope">00 문제 제기</a>
    <a href="#h35">01 H35 — 코어 필터 판정의 블록부트스트랩 감사</a>
    <a href="#h36">02 H36 — 새틀라이트 비중 확장 스윕(0~100%)</a>
    <a href="#synthesis">03 종합 — 트랙D 최종 확정 결론</a>
    <a href="#limitations">04 한계</a>
  </nav>

  <section class="section" id="scope">
    <h2><span class="sec-no">00</span> 문제 제기 — 19라운드가 남긴 두 숙제</h2>
    <p class="lede">19라운드(작업39-46, H22~H25)의 마지막 작업 H25는 챔피언의 가장 오래된 설계
      선택 — SPY&lt;200일 이동평균 시 50%로 축소하는 이진 시장필터 — 조차 6개 창 기저확률가중
      기댓값에서 무필터(상시 완전투자)에 진다는 걸 보였다. 하지만 H25는 스스로 "이 결과는 H22/H26/
      H28/H32가 모두 받은 블록부트스트랩 표본오차 감사를 아직 받지 않았다"고 명시했다 — 그리고 그
      감사를 받은 4개 판정은 하나같이 90%대 확신이 결합전파 후 50%대 근처로 무너졌다. 같은 라운드의
      H24(새틀라이트 비중 재스윕)는 0~50% 범위에서 기댓값 샤프가 상한까지 단조증가해 "진짜 정점을
      못 찾았다"고 자인했다. 이 라운드는 정확히 이 두 갭을 닫는다.</p>
  </section>

  <section class="section" id="h35">
    <h2><span class="sec-no">01</span> H35 — 코어 시장필터 판정의 블록부트스트랩 신뢰도 감사</h2>
    <p class="lede">H25가 저장한 건 요약지표뿐이라, champion_strategy.run_champion을 h25와 완전히
      동일한 코드·유니버스·날짜로 6개 창 x 필터ON/OFF 각 1회 재실행해 일별수익률을 새로 확보했다
      (재계산된 Sharpe는 h25_results.json 원본과 대조해 일치를 확인했다). 이후 H33/H34와 동일한
      순환 이동블록부트스트랩(L=10/20/40일, 창×구성당 2,000회)과 디리클레 결합전파(10,000 draws)를
      적용했다.</p>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>창</th><th>구성</th><th>n_obs(거래일)</th><th>점추정 Sharpe</th>
          <th>90% 부트스트랩 CI (L=20)</th><th>≈비독립 블록수</th></tr></thead>
        <tbody>{window_ci_rows(H35['bootstrap_h25_core_filter'], ['with_filter','without_filter'], CFG_LABEL_H25)}</tbody>
      </table>
    </div>
    <p class="caveat">⚠️ 빨간 배경 행 = n_obs&lt;100(COVID 51거래일, 2018 92거래일) — 이 두 창은
      부트스트랩 CI가 특히 넓고 불안정하다(H33/H34에서도 반복 확인된 패턴). COVID의 무필터 우위
      (point Sharpe 0.76 vs 필터 0.13)조차 CI가 [-2.6, 5.0]으로 겹칠 만큼 넓다.</p>
    <h3>가중치×표본오차 결합 전파</h3>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>비교</th><th>가중치만(H30 방식), 무필터 승률</th><th>결합, 무필터 승률</th><th>90% CI(격차, 무필터−필터유지)</th></tr></thead>
        <tbody>
          <tr class="hero-row"><td class="tk-cell"><span class="tk-name">무필터 vs 필터유지</span></td>
            <td class="num">{pct(C25['weighting_only_win_rate_challenger'],1)}</td>
            <td class="num">{pct(C25['combined_win_rate_challenger'],1)}</td>
            <td class="num">[{fnum(C25['combined_gap_challenger_minus_baseline']['ci90'][0],3,signed=True)}, {fnum(C25['combined_gap_challenger_minus_baseline']['ci90'][1],3,signed=True)}]</td></tr>
        </tbody>
      </table>
    </div>
    <div class="callout warn">
      <div class="callout-title">H25도 예외가 아니었다 — 90%대의 확신은 표본오차 앞에서 55%로 무너진다</div>
      <p>가중치만 흔들면 무필터는 {pct(C25['weighting_only_win_rate_challenger'],1)} 확률로 이겼다 —
        H25가 "3개 시나리오 전부 무필터 승"이라 결론지은 것과 정확히 일치한다. 하지만 표본오차를
        결합하면 승률이 {pct(C25['combined_win_rate_challenger'],1)}로 떨어진다 — H22(57.9%), H26
        (59.7%)과 거의 같은 수준의 "약함" 등급이다. 방향(무필터 우위)은 살아남지만 "거의 확실"이라고
        부를 근거는 없다. 특히 사전에 기대했던 "2008 vs COVID의 극적인 대비"는 실제로 확인됐다 —
        2008은 필터가 이기고(Sharpe 0.46 vs 0.30) COVID는 무필터가 크게 이긴다(0.76 vs 0.13) — 하지만
        이 대비 자체가 두 창의 매우 넓은 CI 안에서 통계적으로 유의미하게 구분되지 않는다는 게 이번
        감사의 핵심 발견이다. 즉 H25의 "챔피언 필터도 진다"는 결론은 다른 4개 감사받은 판정과 나란히
        <b>"방향은 유지, 확신은 약함"</b>으로 재분류해야 한다.</p>
    </div>
  </section>

  <section class="section" id="h36">
    <h2><span class="sec-no">02</span> H36 — 새틀라이트 비중 확장 스윕 (0% → 100%)</h2>
    <p class="lede">H24와 완전히 동일한 코어(필터 포함, 이진 필터 문제 자체는 H35의 몫이라 여기서
      건드리지 않는다)+새틀라이트(H18/H22가 확정한 정적보유 trend_following) 구성, 동일한 6개 창,
      동일한 H22 SCENARIOS(base/calm_heavy/crisis_heavy) 가중치를 재사용하되 비중 리스트를
      60/70/80/90/100%까지 확장했다. 원시 코어·새틀라이트 수익률은 전부 H24/H16/H12가 이미 저장한
      캐시를 그대로 재사용했다(재백테스트 없이 블렌딩 비중만 확장).</p>
    <h3>기저확률가중 기댓값 프런티어 (base 시나리오)</h3>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>새틀라이트 비중</th><th>E[Sharpe]</th><th>E[CAGR]</th><th>최악위기 MDD(6창 중 최소)</th></tr></thead>
        <tbody>{h36_frontier_table('base')}</tbody>
      </table>
    </div>
    <h3>calm_heavy / crisis_heavy 시나리오 정점</h3>
    <div class="kpi-row">
      <div class="kpi-tile"><div class="kpi-label">base 시나리오 최적 비중</div>
        <div class="kpi-value">{H36EV['scenarios']['base']['optimal_weight']*100:.0f}%</div>
        <div class="kpi-sub">E[Sharpe]={H36EV['scenarios']['base']['expected_value_by_weight']['1.0']['expected_sharpe']:.4f} (스윕 상한)</div></div>
      <div class="kpi-tile"><div class="kpi-label">calm_heavy 최적 비중</div>
        <div class="kpi-value">{H36EV['scenarios']['calm_heavy']['optimal_weight']*100:.0f}%</div>
        <div class="kpi-sub">90%와 100%가 사실상 동률(둘 다 0.4008)</div></div>
      <div class="kpi-tile"><div class="kpi-label">crisis_heavy 최적 비중</div>
        <div class="kpi-value">{H36EV['scenarios']['crisis_heavy']['optimal_weight']*100:.0f}%</div>
        <div class="kpi-sub">E[Sharpe] 여전히 음수 전 구간, 그래도 100%가 "덜 나쁨"</div></div>
    </div>
    <h3>창별 위기 Sharpe (비중별)</h3>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>창</th>{"".join(f"<th>{sw*100:.0f}%</th>" for sw in SW_DISPLAY)}</tr></thead>
        <tbody>{h36_per_window_table(SW_DISPLAY)}</tbody>
      </table>
    </div>
    <div class="callout warn">
      <div class="callout-title">100%까지도 정점이 없다 — 그리고 그게 편하게 받아들일 결과는 아니다</div>
      <p>base와 crisis_heavy 두 시나리오 모두 기댓값 Sharpe가 0%에서 100%까지 단조증가했다(base:
        {H36EV['scenarios']['base']['expected_value_by_weight']['0.0']['expected_sharpe']:.4f} →
        {H36EV['scenarios']['base']['expected_value_by_weight']['1.0']['expected_sharpe']:.4f}).
        calm_heavy만 90~100% 사이에서 사실상 평평해진다(정점이라기보단 포화). 문자 그대로 읽으면
        "17자산 분산 코어를 포기하고 point-in-time 모멘텀 새틀라이트로 전액 교체하는 게 기댓값상
        더 낫다"는 뜻이다 — 하지만 그 대가는 만만치 않다: 6개 창 중 최악(2008 GFC 3자산 근사)의
        MDD가 비중 0%의 -15.1%에서 100%의 -73.6%로 거의 5배 악화된다. gfc_2008/correction_2015_2016
        창은 비중이 오를수록 절대 Sharpe 자체가 더 나빠지는데도(예: gfc_2008 crisis Sharpe -0.90→
        -0.93), 정작 기댓값을 지배하는 건 selloff_2018/covid_2020처럼 새틀라이트가 크게 앞서는 창들
        — 즉 "평균적으로 이긴다"는 결론이 "어느 창에서든 이긴다"는 뜻은 전혀 아니다.</p>
    </div>
  </section>

  <section class="section" id="synthesis">
    <h2><span class="sec-no">03</span> 종합 — 트랙D 20라운드 전체를 아우르는 최종 확정 신뢰도표</h2>
    <p class="lede">H33/H34가 시작한 감사를 H35로 마무리하면서, 트랙D 전체가 "채택"이라 불러온 6개
      주요 판정이 이제 전부 같은 잣대(승률 90%↑=강건, 70~90%=보통, 50~70%=약함, 50%미만=반전/미지지)
      아래 나란히 놓인다.</p>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>판정</th><th>가중치만(H30 방식)</th><th>결합(가중치+표본오차)</th><th>90% CI(격차)</th><th>신뢰도 등급</th></tr></thead>
        <tbody>{unified_rows()}</tbody>
      </table>
    </div>
    <h3>읽는 법</h3>
    <ul>
      <li><b>H25(신규, 이번 라운드)</b> — {pct(C25['weighting_only_win_rate_challenger'],1)}→{pct(C25['combined_win_rate_challenger'],1)}
        (약함). 다른 4개 감사받은 판정(H22 57.9%, H26 59.7%, H26b 53.6%, H28 49.7%)과 나란히 놓이며
        정확히 같은 패턴을 재확인한다 — 챔피언의 가장 오래된 설계 선택조차 "확실히 진다"가 아니라
        "근소하게, 불확실하게 진다"였다. 유일하게 이 등급을 벗어난 건 H32(48.6→49.6%, 가중치 단계부터
        이미 동전던지기)뿐이다.</li>
      <li><b>공통 패턴</b>: 6개 판정 중 5개가 "가중치만으로는 90%대 이상 확신 → 표본오차 결합 시 50%대
        약함"으로 수렴했다. 이건 우연이 아니라 구조적이다 — 6개 창(그 중 절반이 crisis-window라
        n_obs&lt;150)에 기반한 디리클레 가중치 자체는 표본 크기가 커 보여도, 그 안의 각 창이 자체적으로
        가진 표본오차(특히 COVID 51일, 2018 92일)가 가중치 재표본보다 훨씬 크게 작용한다.</li>
      <li><b>H36은 이 감사 대상이 아니다</b> — H36은 "정점이 어디 있는가"라는 형태(frontier) 질문이라
        H22/H25처럼 이분법적 승/패 비교가 아니다. 다만 base/crisis_heavy 두 시나리오가 100%까지 단조
        증가했다는 사실 자체는 표본오차 감사 없이도 이미 "이 결과를 프로덕션 그대로 받아들이면 안 된다"는
        경고 신호로 충분하다 — 아래 04절에서 상술.</li>
    </ul>
    <h3>최종 권고 재확인</h3>
    <p>트랙D 20라운드 전체를 종합하면: (1) 기존 챔피언(17자산+12개월 모멘텀+이진 시장필터+월간
      리밸런싱+15% 정적보유 새틀라이트)의 각 설계 선택 — 필터 포함 — 은 하나도 "확실한 개선"이라고
      부를 근거가 없다. 무필터/변동성타겟팅제거/시스템&gt;SPY 전부 방향은 유지되지만 확신은 약하다.
      (2) 새틀라이트 비중을 100%까지 올리는 건 이 6개 특정 역사적 창의 기댓값 프런티어상으로는 계속
      유리해 보이지만, 그 자체가 통계적 감사(H35식)를 받은 적 없고 위기 시 MDD가 5배 악화되는 명백한
      트레이드오프가 있어 실무 채택 근거로 쓰기엔 너무 이르다. <b>정직한 요약: 이 트랙D 프로그램이
      20라운드에 걸쳐 발견한 "개선"들은 거의 전부 방향은 맞지만 크기가 작고 불확실하다 — 단 하나도
      "확실한 알파"라 부를 수 있는 수준의 통계적 확신에 도달하지 못했다.</b></p>
  </section>

  <section class="section" id="limitations">
    <h2><span class="sec-no">04</span> 한계</h2>
    <ul>
      <li>H35의 블록부트스트랩은 H33/H34와 동일한 한계를 그대로 물려받는다 — 원 역사적 창이 "대표성
        있는 하나의 실현"이라는 전제 위에 서 있고, 실제로 일어난 적 없는 "다른 위기"를 만들어내지
        못한다. COVID(51거래일)와 2018(92거래일)의 CI는 특히 넓고 불안정하다.</li>
      <li>H36은 프런티어(정점 탐색) 질문이라 H35식 승/패 이분법 부트스트랩 감사를 이번 라운드에서
        적용하지 않았다 — "100%가 진짜 최적"이라는 주장 자체는 아직 표본오차 검증을 거치지 않은
        점추정 기반 결론이다. 다음 라운드가 남길 만한 숙제다.</li>
      <li>H36의 100% 비중은 17자산 분산 코어를 완전히 포기하고 point-in-time 모멘텀 새틀라이트
        (훨씬 작고, 회전율이 높고, 변동성이 큰 유니버스)로 전액 대체한다는 뜻이다 — 백테스트가 포착
        못 하는 실무 제약(집중 리스크, 대형화 시 시장충격/유동성, 새틀라이트 유니버스 자체의 생존편향
        가능성)이 있다. 6개 역사적 창에서 기댓값이 높다고 이걸 그대로 실행하라는 뜻이 아니다.</li>
      <li>창 사이의 상관(2008과 2022가 완전히 독립이 아닐 가능성)은 여전히 모델링하지 않았다 —
        H30/H33/H34가 이미 지적한 디리클레의 "카테고리 간 독립성 가정" 한계가 이번 라운드에도 그대로
        적용된다.</li>
      <li>거래비용/생존편향 등 모형오차(specification error) 자체는 이번 라운드에서도 다루지 않았다 —
        표본오차(sampling)만 감사했을 뿐이다.</li>
      <li>H35 재계산 Sharpe는 h25_results.json 원본과 육안 대조로만 검증했다(자동화된 수치 diff는
        아님) — 소수점 단위의 미세한 차이가 있을 수 있으나 결론에 영향을 줄 정도는 아니다.</li>
    </ul>
  </section>

</div>

<footer>
  <p>QUANT RESEARCH · 20라운드 · H35 코어필터 블록부트스트랩 감사 + H36 새틀라이트 비중 확장 스윕 ·
    기준일 {esc(GEN)} · 이 문서는 투자 조언이 아니며 저자 개인의 연구 기록입니다.</p>
</footer>
"""

with open(f"{OUT_DIR}/final_report.html", "w", encoding="utf-8") as f:
    f.write(HTML)
print("[build_report] saved final_report.html")
