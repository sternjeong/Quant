#!/usr/bin/env python3
"""report_data.json을 읽어 final_report.html을 만든다.

analysis/2026-08-24_bootstrap_confidence_audit_remaining_verdicts/build_report.py(H34)와 동일한
디자인 시스템(다크네이비/올리브 톤, 세리프 헤드라인, TOC, 섹션 번호, 판정 배지)을 그대로 재사용한다.
"""
import json
import math
import os

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

with open(f"{OUT_DIR}/report_data.json", encoding="utf-8") as f:
    R = json.load(f)

META = R["meta"]
GEN = META["generated"]
EP_ORDER = META["episode_order"]
BOOT = R["bootstrap_summary"]
COMBINED = R["combined_propagation"]
UNIFIED = R["unified_rows"]
AGG = R["candidate_aggregate"]
H4 = R["h4_grid_percentile"]
H1 = R["h1_reproducibility"]

EP_LABEL = {
    "full_2019_2026": "전체기간 2019-2026",
    "gfc_2008": "2008 GFC",
    "covid_2020": "COVID 2020 (~5주)",
    "bear_2022": "2022 완만약세장",
    "selloff_2018": "2018 4분기 급락",
    "correction_2015_2016": "2015-16 조정",
}
CFG_LABEL = {
    "m12_monthly": "12개월/월간(현재 기본값)",
    "m12_quarterly": "12개월/분기(H34 감사)",
    "m14_quarterly": "14개월/분기",
    "m15_quarterly": "15개월/분기",
    "m16_quarterly": "16개월/분기",
}
SCEN_LABEL = {"base": "기본(base)", "calm_heavy": "평온장 가중(calm_heavy)", "crisis_heavy": "위기 가중(crisis_heavy)"}


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
tr.good-row{ background: rgba(27,175,122,0.08); }
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


def h1_rows():
    rows = []
    for r in H1["rows"]:
        rows.append(
            f'<tr><td class="tk-cell"><span class="tk-name">{esc(EP_LABEL[r["episode"]])}</span></td>'
            f'<td class="tk-cell">{esc(CFG_LABEL[r["config"]])}</td>'
            f'<td class="num">{fnum(r["sharpe_h32_stored"],3,signed=True)}</td>'
            f'<td class="num">{fnum(r["sharpe_this_session"],3,signed=True)}</td>'
            f'<td class="num">{r["abs_diff"]:.6f}</td></tr>'
        )
    return "".join(rows)


def boot_rows(configs):
    rows = []
    for ep in EP_ORDER:
        d = BOOT[ep]
        for cfg in configs:
            m = d["by_config"][cfg]
            n_obs = d["n_obs"][cfg]
            pt = m["point_estimate_sharpe"]
            b20 = m["bootstrap_by_block_len"]["20"]
            warn = " warn-row" if n_obs < 100 else ""
            rows.append(
                f'<tr class="{warn.strip()}"><td class="tk-cell"><span class="tk-name">{esc(EP_LABEL[ep])}</span></td>'
                f'<td class="tk-cell">{esc(CFG_LABEL[cfg])}</td>'
                f'<td class="num">{n_obs}</td>'
                f'<td class="num">{fnum(pt,3,signed=True)}</td>'
                f'<td class="num">[{fnum(b20["ci90"][0],3,signed=True)}, {fnum(b20["ci90"][1],3,signed=True)}]</td></tr>'
            )
    return "".join(rows)


def combined_rows_for_scenario(scen):
    rows = []
    for base_cfg in ("m12_monthly", "m12_quarterly"):
        for cand in ("m14_quarterly", "m15_quarterly", "m16_quarterly"):
            c = COMBINED[scen][base_cfg][cand]
            gap = c["combined_gap_challenger_minus_baseline"]["ci90"]
            wr = c["combined_win_rate_challenger"]
            cls = " good-row" if wr >= 0.6 else ""
            rows.append(
                f'<tr class="{cls.strip()}"><td class="tk-cell"><span class="tk-name">{esc(CFG_LABEL[cand])}</span> vs {esc(CFG_LABEL[base_cfg])}</td>'
                f'<td class="num">{pct(c["weighting_only_win_rate_challenger"],1)}</td>'
                f'<td class="num">{pct(c["sampling_only_win_rate_challenger"],1)}</td>'
                f'<td class="num">{pct(wr,1)}</td>'
                f'<td class="num">[{fnum(gap[0],3,signed=True)}, {fnum(gap[1],3,signed=True)}]</td></tr>'
            )
    return "".join(rows)


def h4_rows(scen):
    d = H4[scen]
    rows = []
    seq = d["sequential_12m_monthly"]
    rows.append(
        f'<tr><td class="tk-cell"><span class="tk-name">12개월/월간(현재 기본값)</span></td>'
        f'<td class="num">{seq["rank_out_of_40"]}/40</td>'
        f'<td class="num">{fnum(100*(40-seq["rank_out_of_40"]+1)/40,1)}%</td>'
        f'<td class="num">{fnum(seq["expected_sharpe"],4,signed=True)}</td>'
        f'<td class="num">{fnum(seq["mdd_worst_case"],2,signed=True)}%</td></tr>'
    )
    for c in d["candidates_14_15_16_quarterly"]:
        rows.append(
            f'<tr class="good-row"><td class="tk-cell"><span class="tk-name">{c["lookback_months"]}개월/분기</span></td>'
            f'<td class="num">{c["rank_out_of_40"]}/40</td>'
            f'<td class="num">{c["percentile"]}%</td>'
            f'<td class="num">{fnum(c["expected_sharpe"],4,signed=True)}</td>'
            f'<td class="num">—</td></tr>'
        )
    return "".join(rows)


def agg_kpis():
    tiles = []
    for cand in ("m14_quarterly", "m15_quarterly", "m16_quarterly"):
        a = AGG[cand]
        cls = "pos" if a["mean"] > 0.5 else "neg"
        tiles.append(
            f'<div class="kpi-tile"><div class="kpi-label">{esc(CFG_LABEL[cand])} — 결합승률(18개 비교 중 6개 평균)</div>'
            f'<div class="kpi-value {cls}">{pct(a["mean"],1)}</div>'
            f'<div class="kpi-sub">범위 {pct(a["min"],1)} ~ {pct(a["max"],1)} (n={a["n_comparisons"]})</div></div>'
        )
    return "".join(tiles)


HTML = f"""<title>정밀그리드 결합후보(14~16개월+분기) 블록부트스트랩 감사</title>
<style>
{CSS}
</style>

<div class="masthead">
  <div class="masthead-inner">
    <div class="masthead-eyebrow">
      <span>QUANT RESEARCH NOTE</span><span class="dot">·</span><span>트랙D 21라운드(H37)</span><span class="dot">·</span><span>리서치 에이전트 B · 무인 야간 실행</span>
    </div>
    <h1 class="masthead-title">이번엔 동전던지기로 안 무너졌다 — 결합 파라미터 후보의 첫 표본오차 감사</h1>
    <p class="masthead-sub">H32(작업44)가 40칸 정밀그리드에서 찾은 결합 우승 구간(룩백 14~16개월+분기
      리밸런싱)은 지금까지 한 번도 블록부트스트랩 감사를 받은 적이 없었다 — H34(작업45)가 감사한
      "분기 vs 월간"은 룩백을 12개월로 고정한 좁은 질문이었고, 거기선 실제로 승률이 49.6%까지
      무너졌다. 이번 라운드는 H32의 진짜 headline(룩백도 같이 옮기는 결합 조합)을 처음으로 같은
      방법론(순환 이동블록부트스트랩+디리클레 결합전파)으로 감사한다. 결과: <b>18개 비교(3개 후보×3개
      기저확률 시나리오×2개 기준선) 전부에서 결합 승률이 54.8%~63.2% 범위에 머물렀다</b> — 이
      프로그램에서 흔했던 "50% 근처로 붕괴"가 이번엔 일어나지 않았다.</p>
    <div class="masthead-meta">
      <span><b>기준일</b> {esc(GEN)}</span>
      <span><b>블록부트스트랩</b> 창×구성당 {META['n_boot']:,}회, 블록길이 {', '.join(str(x)+'일' for x in META['block_lengths'])}</span>
      <span><b>결합전파</b> {META['n_draws']:,} draws (디리클레×부트스트랩, 3개 시나리오)</span>
      <span><b>신규 백테스트</b> 6개 창 × 3개 룩백(14/15/16개월) = 18회</span>
    </div>
  </div>
</div>

<div class="wrap">

  <nav class="toc">
    <a href="#scope">00 문제 제기</a>
    <a href="#h1">01 H1 — 재현성 확인</a>
    <a href="#h2">02 H2 — 블록부트스트랩 표본오차 (5개 구성 × 6개 창)</a>
    <a href="#h3">03 H3 — 가중치×표본오차 결합전파 (3개 시나리오)</a>
    <a href="#h4">04 H4 — 40칸 전수 그리드 백분위</a>
    <a href="#synthesis">05 종합 판정</a>
    <a href="#limitations">06 한계</a>
  </nav>

  <section class="section" id="scope">
    <h2><span class="sec-no">00</span> 문제 제기 — 결합 우승점은 아직 표본오차 감사를 받은 적이 없다</h2>
    <p class="lede">H32(작업44, 17라운드)는 룩백 9~18개월 × 리밸런싱 4주기 = 40칸 정밀그리드에서
      14~16개월+분기가 샤프 격차 0.01~0.014 안에 들어오는 "완만한 고원"이라고 보고하고, 현재
      <code>core/champion_strategy.py</code> 라이브 기본값(12개월/월간)은 그 그리드에서 11~20위에
      그친다고 밝혔다. 그런데 H34(작업45, 18라운드)가 뒤이어 수행한 블록부트스트랩 감사는 정확히
      이 결합 최적점을 감사하지 않았다 — 사용자 지시에 따라 <b>룩백을 12개월로 고정한 채 리밸런싱
      주기만</b> 격리했고(H34 04절 한계에 명시), 그 좁은 비교에서는 가중치 단계부터 이미 49.6%로
      동전던지기였다. 즉 "룩백을 같이 14~16개월로 옮기는 결합 효과 자체"는 이 프로그램의 어떤
      라운드도 아직 표본오차 렌즈로 들여다본 적이 없다 — 리서치 에이전트 B 페르소나가 명시한
      "아직 안 풀린 문제" 2번이 정확히 이것이다.</p>
    <p class="caveat">⚠️ 투자 조언이 아니다. 이 라운드는 코어(17자산 로테이션+이진 시장필터) 단독
      비교만 다룬다 — 새틀라이트 블렌딩은 H32 Stage 2가 이미 전체기간 단일창에서만 다뤘고 이번
      감사 범위 밖이다. core/app는 전혀 수정하지 않았다(순수 리서치).</p>
  </section>

  <section class="section" id="h1">
    <h2><span class="sec-no">01</span> H1 — 재현성 확인</h2>
    <p class="lede">14/15/16개월+분기 구성을 이번 세션이 <code>h32_fine_grid_and_satellite_joint.py</code>의
      <code>run_champion_joint()</code>를 코드 변경 없이 그대로 호출해 6개 창에서 재실행하고,
      H32가 저장해 둔 <code>h32_stage1_results.json</code>의 원본 점추정치와 대조했다.</p>
    <div class="kpi-row">
      <div class="kpi-tile"><div class="kpi-label">최대 절대오차(18개 비교)</div>
        <div class="kpi-value pos">{H1['max_abs_diff']:.6f}</div>
        <div class="kpi-sub">판정: {esc(H1['verdict'])}</div></div>
    </div>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>창</th><th>구성</th><th>H32 저장값(Sharpe)</th><th>이번 세션 재실행(Sharpe)</th><th>절대오차</th></tr></thead>
        <tbody>{h1_rows()}</tbody>
      </table>
    </div>
    <p>18개 셀 전부 소수점 6자리까지 완전히 일치 — 결정론적 재현성이 확인됐다(코드·유니버스·비용모형
      무변경, 캐시된 가격 데이터도 동일).</p>
  </section>

  <section class="section" id="h2">
    <h2><span class="sec-no">02</span> H2 — 블록부트스트랩 표본오차 (5개 구성 × 6개 창)</h2>
    <p class="lede">H33/H34와 완전히 동일한 순환 이동블록부트스트랩(블록길이 10/20/40일, 창당
      {META['n_boot']:,}회)을 12개월/월간(현재 기본값)·12개월/분기(H34 기준선)·14/15/16개월/분기
      다섯 구성 모두에 적용했다. 아래는 블록길이 20일 기준 90% 신뢰구간.</p>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>창</th><th>구성</th><th>n_obs(거래일)</th><th>점추정 Sharpe</th><th>90% 부트스트랩 CI (L=20)</th></tr></thead>
        <tbody>{boot_rows(["m12_monthly","m12_quarterly","m14_quarterly","m15_quarterly","m16_quarterly"])}</tbody>
      </table>
    </div>
    <p class="caveat">COVID(51거래일)·2018 급락(약 90거래일) 창은 관측치가 적어 신뢰구간이 넓다 —
      H33/H34가 이미 지적한 것과 같은 한계가 그대로 적용된다.</p>
  </section>

  <section class="section" id="h3">
    <h2><span class="sec-no">03</span> H3 — 가중치×표본오차 결합전파 (3개 시나리오)</h2>
    <p class="lede">H30/H33 방식 그대로, 3개 기저확률 시나리오(base/calm_heavy/crisis_heavy, H32와
      동일한 가중치)에서 디리클레(K=30) 가중치 불확실성과 블록부트스트랩(L=20) 표본오차를 결합
      전파했다. "가중치만"은 점추정치에만 디리클레를 적용한 H30식 근사, "표본오차만"은 고정 기저확률
      가중치로 부트스트랩만 반영, "결합"이 둘을 함께 반영한 최종 승률이다.</p>
    <div class="kpi-row">{agg_kpis()}</div>
    <h3>base 시나리오</h3>
    <div class="table-wrap"><table class="data-table">
      <thead><tr><th>비교</th><th>가중치만</th><th>표본오차만</th><th>결합</th><th>90% CI(격차)</th></tr></thead>
      <tbody>{combined_rows_for_scenario('base')}</tbody>
    </table></div>
    <h3>calm_heavy 시나리오</h3>
    <div class="table-wrap"><table class="data-table">
      <thead><tr><th>비교</th><th>가중치만</th><th>표본오차만</th><th>결합</th><th>90% CI(격차)</th></tr></thead>
      <tbody>{combined_rows_for_scenario('calm_heavy')}</tbody>
    </table></div>
    <h3>crisis_heavy 시나리오</h3>
    <div class="table-wrap"><table class="data-table">
      <thead><tr><th>비교</th><th>가중치만</th><th>표본오차만</th><th>결합</th><th>90% CI(격차)</th></tr></thead>
      <tbody>{combined_rows_for_scenario('crisis_heavy')}</tbody>
    </table></div>
    <div class="callout good">
      <div class="callout-title">이 프로그램에서 드문 패턴 — 결합 승률이 50% 아래로 한 번도 안 내려갔다</div>
      <p>가중치만 반영하면 거의 항상 99.5~100%로 확정적으로 보이던 승률이(이 프로그램의 반복 패턴대로)
        표본오차를 더하면 크게 떨어진다 — 다만 이번엔 49~50%대로 붕괴하지 않고 <b>18개 비교 전부
        54.8%~63.2% 범위에서 멈췄다</b>. 16개월/분기가 가장 일관되게 앞섰고(평균 {pct(AGG['m16_quarterly']['mean'],1)}),
        14개월/분기가 근소하게 뒤를 이었으며(평균 {pct(AGG['m14_quarterly']['mean'],1)}), 15개월/분기가
        상대적으로 가장 약했다(평균 {pct(AGG['m15_quarterly']['mean'],1)}, 그래도 최저치 54.8%로 절반은
        넘는다). 3개 시나리오·2개 기준선(12개월/월간, 12개월/분기) 전부에서 방향이 한 번도 안 뒤집힌
        것도 특기할 만하다.</p>
    </div>
  </section>

  <section class="section" id="h4">
    <h2><span class="sec-no">04</span> H4 — 40칸 전수 그리드 백분위 (플라시보 대용, 재계산 없음)</h2>
    <p class="lede">순열검정 대신, H32가 이미 완성해 둔 40칸(룩백 10값×리밸런싱 4값) 전수 그리드
      — 이건 표본이 아니라 그 자체가 전체 모집단이다 — 안에서 14/15/16개월+분기가 3개 시나리오
      각각 몇 위인지 다시 확인했다. "완만한 고원"이라는 H32의 서술이 숫자로 얼마나 완만한지
      정량화하는 목적.</p>
    <h3>base 시나리오</h3>
    <div class="table-wrap"><table class="data-table">
      <thead><tr><th>구성</th><th>순위(40칸 중)</th><th>백분위</th><th>기대 Sharpe</th><th>최악구간 MDD</th></tr></thead>
      <tbody>{h4_rows('base')}</tbody>
    </table></div>
    <h3>calm_heavy 시나리오</h3>
    <div class="table-wrap"><table class="data-table">
      <thead><tr><th>구성</th><th>순위(40칸 중)</th><th>백분위</th><th>기대 Sharpe</th><th>최악구간 MDD</th></tr></thead>
      <tbody>{h4_rows('calm_heavy')}</tbody>
    </table></div>
    <h3>crisis_heavy 시나리오</h3>
    <div class="table-wrap"><table class="data-table">
      <thead><tr><th>구성</th><th>순위(40칸 중)</th><th>백분위</th><th>기대 Sharpe</th><th>최악구간 MDD</th></tr></thead>
      <tbody>{h4_rows('crisis_heavy')}</tbody>
    </table></div>
    <div class="callout">
      <div class="callout-title">14개월/분기의 최악구간 MDD가 특히 눈에 띈다</div>
      <p>14개월/분기의 5개 위기창(GFC/COVID/2022/2018/2015-16) 중 최악 MDD는 -15.73%로, 현재
        기본값(12개월/월간)의 -29.77%보다 거의 절반이다. 15/16개월/분기는 같은 지표가 -28.01%로
        현재 기본값과 큰 차이가 없다 — 이 MDD 개선은 14개월이라는 특정 지점에서만 나타나는 것으로
        보이며, "14~16개월 어디든 동등하게 좋다"는 단순화는 MDD 관점에서는 성립하지 않는다. 다만
        03절의 결합승률에서는 16개월이 14개월을 근소하게 앞섰다는 점과 함께 읽으면, "샤프 기준으로는
        16개월이 근소 우위, 꼬리위험 기준으로는 14개월이 뚜렷한 우위"라는 트레이드오프로 해석하는
        게 정확하다.</p>
    </div>
  </section>

  <section class="section" id="synthesis">
    <h2><span class="sec-no">05</span> 종합 판정</h2>
    <p class="lede">이 프로그램의 등급 관례(승률 90%↑=강건, 70~90%=보통, 50~70%=약함, 50%미만=반전/미지지)를
      그대로 적용하면, 14/15/16개월+분기 결합 후보 셋 다 <b>약함(weak)</b> 등급이다 — "확신"이라고
      부르기엔 부족하지만(70% 문턱 미달), 이 프로그램에서 이례적으로 <b>모든 강건성 체크(3개
      시나리오×2개 기준선×1개 전수그리드)에서 방향이 단 한 번도 뒤집히지 않았다</b>는 점이 다른
      "약함" 판정들과 구별되는 지점이다.</p>
    <ul>
      <li><b>H32 원래 headline("분기가 강건하다")</b> — 룩백을 함께 옮긴 결합 조합에서만 성립한다는
        H34의 추측이 이번 감사로 확인됐다. 12개월 고정 상태에서는 H34가 이미 보여준 대로 근거가
        없었지만(49.6%), 룩백을 14~16개월로 함께 옮기면 18개 비교 전부에서 54.8%~63.2%로 안정된다.</li>
      <li><b>16개월/분기</b>가 결합승률 기준으로는 가장 일관되게 앞서지만(평균 {pct(AGG['m16_quarterly']['mean'],1)}),
        <b>14개월/분기</b>는 최악구간 MDD가 뚜렷이 더 낮다(-15.73% vs 현재 기본값 -29.77%) — 샤프
        최적과 꼬리위험 최적이 갈리는 지점으로, "하나의 정답"으로 단순화하지 않는다.</li>
      <li><b>15개월/분기</b>(H31의 조(粗)그리드 원래 우승점)는 세 후보 중 가장 약하다(평균
        {pct(AGG['m15_quarterly']['mean'],1)}) — H32가 이미 지적한 "정밀 정점은 14 또는 16으로
        흔들린다"는 관찰과 일관되며, 특정 숫자 "15개월"에 집착할 근거는 이 라운드로 더 약해졌다.</li>
      <li>이 결과는 <b>core/champion_strategy.py의 기본값을 바꾸라는 권고가 아니다</b> — 리서치
        결과를 라이브 엔진에 반영할지는 사용자가 별도로 판단한다(페르소나 지시). 다만 confidence_table의
        "리밸런싱 주기(월간)" 항목에 "결합 조합(14~16개월+분기)은 별도 감사에서 약함(54.8~63.2%)
        등급으로 확인됨 — 룩백 고정 상태의 분기전환 단독과는 다른 결론"이라는 각주를 추가할 근거가
        생겼다.</li>
    </ul>
  </section>

  <section class="section" id="limitations">
    <h2><span class="sec-no">06</span> 한계</h2>
    <ul>
      <li>코어 단독 비교만 다뤘다 — 새틀라이트 블렌딩과 결합했을 때도 같은 순위가 유지되는지는
        확인하지 않았다(H32 Stage 2가 14개월/분기+새틀라이트 조합의 단일창 결과만 남겼다).</li>
      <li>블록부트스트랩 자체의 한계는 H33/H34와 동일 — 실제 역사에 없었던 "다른 위기"를 만들어내지
        못하고, COVID·2018처럼 짧은 창은 신뢰구간이 넓다.</li>
      <li>H4의 40칸 그리드 백분위는 순열검정의 완전한 대체가 아니다 — 그리드 자체가 유한한 격자
        (룩백 1개월 간격, 리밸런싱 4값)라 격자 밖의 연속적 대안(예: 13.5개월)은 다루지 못한다.</li>
      <li>디리클레 결합전파의 "카테고리 간 독립성" 가정(H30/H33이 이미 지적)은 이번 라운드에도 그대로
        적용된다 — 2008과 2022가 완전히 독립적인 표본이 아닐 가능성은 모델링하지 않았다.</li>
      <li>거래비용/세금 등 모형오차(specification error)는 다루지 않았다 — 순수 표본오차(sampling
        error)만 감사했다. `cost_tax_audit_research`(작업72)가 지적한 순열검정 실패(p=0.2388)는
        이 라운드의 범위 밖이며, 이번 라운드의 "약함" 등급에도 별도로 반영하지 않았다 — 두 감사를
        모두 통과해야 진짜 confidence가 올라간다는 원칙은 유지된다.</li>
    </ul>
  </section>

</div>

<footer>
  <p>QUANT RESEARCH · 트랙D 21라운드(H37) · 정밀그리드 결합후보(14~16개월+분기) 블록부트스트랩 감사 ·
    기준일 {esc(GEN)} · 이 문서는 투자 조언이 아니며 저자 개인의 연구 기록입니다.</p>
</footer>
"""

with open(f"{OUT_DIR}/final_report.html", "w", encoding="utf-8") as f:
    f.write(HTML)

print("final_report.html written.")
