#!/usr/bin/env python3
"""report_data.json을 읽어 final_report.html을 만든다. 디자인 시스템은
analysis/2026-09-05_options_hedge_bootstrap_and_combined_system/build_report.py와 동일(다크네이비/올리브
톤, 세리프 헤드라인, TOC, 섹션 번호, 판정 배지) — 새 디자인을 만들지 않는다."""
import json
import math
import os

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
with open(f"{OUT_DIR}/report_data.json", encoding="utf-8") as f:
    R = json.load(f)

GEN = R["meta"]["generated"]
EP_ORDER = R["meta"]["episode_order"]
BASE = R["baseline_table"]
PERM = R["permutation"]
ZP = R["zero_payoff_placebo"]
BOOT = R["bootstrap_ci"]
COMB = R["combined_dirichlet_x_bootstrap"]

EP_LABEL = {
    "full_2019_2026": "전체기간 2019-2026 (평시)",
    "gfc_2008": "2008 GFC",
    "covid_2020": "COVID 2020 (~51거래일)",
    "bear_2022": "2022 완만약세장",
    "selloff_2018": "2018 4분기 급락",
    "correction_2015_2016": "2015-16 조정",
}
EP_SHORT = {
    "full_2019_2026": "평시전체", "gfc_2008": "2008GFC", "covid_2020": "COVID",
    "bear_2022": "2022약세", "selloff_2018": "2018급락", "correction_2015_2016": "2015-16",
}
VARIANT_LABEL = {
    "collar_baseline": "베이스라인(1.00/1.05/21)",
    "collar_deep_otm_put": "딥아웃풋(0.90/1.05/21)",
    "collar_wide_otm_call": "와이드콜(1.00/1.10/21)",
    "collar_long_tenor": "롱테너(1.00/1.05/63)",
    "collar_zero_cost": "제로코스트(1.00/zc/21)",
}
SCEN_LABEL = {"base": "기본(base)", "calm_heavy": "평시가중(calm_heavy)", "crisis_heavy": "위기가중(crisis_heavy)"}


def fnum(v, digits=2, signed=False):
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
  font-size: clamp(28px, 4.2vw, 44px); line-height:1.15; margin: 14px 0 10px; text-wrap: balance; max-width: 36ch; }
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
table.data-table{ width:100%; border-collapse:collapse; font-size:13.5px; min-width:760px; }
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
.badge{ display:inline-block; font-size:11.5px; font-weight:700; letter-spacing:0.03em; text-transform:uppercase;
  border-radius:4px; padding:3px 9px; }
.badge.reject{ background:rgba(179,38,30,0.12); color:var(--delta-neg); }
.badge.weak{ background:var(--accent-2-soft); color:var(--accent-2); }
.badge.accept{ background:rgba(27,175,122,0.14); color:var(--aqua); }
footer{ max-width:1060px; margin:40px auto 0; padding: 26px 24px 10px; border-top:1px solid var(--hairline);
  font-size:12.5px; color:var(--ink-muted); }
footer p{ max-width:none; }
.toc{ display:flex; flex-wrap:wrap; gap:8px 18px; margin: 24px 0 4px; padding:16px 20px; background:var(--surface);
  border:1px solid var(--hairline); border-radius:8px; }
.toc a{ font-size:13.5px; color:var(--ink-2); text-decoration:none; }
.toc a:hover{ color:var(--accent); text-decoration:underline; }
"""

# ---------------------------------------------------------------------------
# Section 1: baseline table
# ---------------------------------------------------------------------------


def baseline_rows():
    rows = []
    for ep in EP_ORDER:
        d = BASE[ep]
        warn = " warn-row" if ep == "covid_2020" else ""
        rows.append(
            f'<tr class="{warn.strip()}"><td class="tk-cell"><span class="tk-name">{esc(EP_LABEL[ep])}</span>'
            f'<span style="color:var(--ink-muted);font-size:12px;"> ({d["window_used"]})</span></td>'
            f'<td class="num">{fnum(d["core_alone"]["sharpe"],2,True)}</td>'
            f'<td class="num">{fnum(d["unhedged_satellite"]["sharpe"],2,True)}</td>'
            f'<td class="num">{fnum(d["collar_hedged"]["sharpe"],2,True)}</td>'
            f'<td class="num">{fnum(d["unhedged_satellite"]["mdd"],1)}%</td>'
            f'<td class="num">{fnum(d["collar_hedged"]["mdd"],1)}%</td>'
            f'<td class="num">{d["n_rolls"]}</td></tr>'
        )
    return "".join(rows)


# ---------------------------------------------------------------------------
# Section 2: grid sweeps (put/call/tenor)
# ---------------------------------------------------------------------------


def grid_rows(grid: dict, param_fmt="{:.3f}"):
    rows = []
    for ep in EP_ORDER:
        cells = "".join(
            f'<td class="num">{fnum(pt["sharpe_collar"],2,True)}</td>' for pt in grid[ep]
        )
        rows.append(
            f'<tr><td class="tk-cell"><span class="tk-name">{esc(EP_SHORT[ep])}</span></td>{cells}'
            f'<td class="num" style="color:var(--ink-muted);">{fnum(grid[ep][0]["sharpe_unhedged"],2,True)}</td></tr>'
        )
    return "".join(rows)


PUT_PARAMS = [pt["param"] for pt in R["put_grid"]["full_2019_2026"]]
CALL_PARAMS = [pt["param"] for pt in R["call_grid"]["full_2019_2026"]]
TENOR_PARAMS = [pt["param"] for pt in R["tenor_grid"]["full_2019_2026"]]


def zero_cost_rows():
    rows = []
    for ep in EP_ORDER:
        d = R["zero_cost"][ep]
        rows.append(
            f'<tr><td class="tk-cell"><span class="tk-name">{esc(EP_LABEL[ep])}</span></td>'
            f'<td class="num">{fnum(d["sharpe_unhedged"],2,True)}</td>'
            f'<td class="num">{fnum(BASE[ep]["collar_hedged"]["sharpe"],2,True)}</td>'
            f'<td class="num">{fnum(d["sharpe_collar"],2,True)}</td></tr>'
        )
    return "".join(rows)


# ---------------------------------------------------------------------------
# Section 3: H3 permutation + zero-payoff placebo
# ---------------------------------------------------------------------------


def permutation_rows():
    rows = []
    for ep in EP_ORDER:
        d = PERM[ep]
        pct = d["actual_percentile_in_null"]
        cls = "hero-row" if pct >= 85 else ("warn-row" if pct <= 25 else "")
        rows.append(
            f'<tr class="{cls}"><td class="tk-cell"><span class="tk-name">{esc(EP_LABEL[ep])}</span></td>'
            f'<td class="num">{d["n_rolls"]}</td>'
            f'<td class="num">{fnum(d["actual_sharpe_delta"],3,True)}</td>'
            f'<td class="num">[{fnum(d["null_p5"],3,True)}, {fnum(d["null_p95"],3,True)}]</td>'
            f'<td class="num">{fnum(pct,1)}<span style="color:var(--ink-muted)">th</span></td></tr>'
        )
    return "".join(rows)


def zero_payoff_rows():
    rows = []
    for ep in EP_ORDER:
        d = ZP[ep]
        cls = "hero-row" if d["real_beats_placebo"] else "warn-row"
        rows.append(
            f'<tr class="{cls}"><td class="tk-cell"><span class="tk-name">{esc(EP_LABEL[ep])}</span></td>'
            f'<td class="num">{fnum(d["unhedged_sharpe"],2,True)}</td>'
            f'<td class="num">{fnum(d["zero_payoff_sharpe"],2,True)}</td>'
            f'<td class="num">{fnum(d["real_collar_sharpe"],2,True)}</td>'
            f'<td class="num">{"예" if d["real_beats_placebo"] else "아니오"}</td></tr>'
        )
    return "".join(rows)


# ---------------------------------------------------------------------------
# Section 4: H4 bootstrap CI + combined dirichlet
# ---------------------------------------------------------------------------

VARIANTS = list(R["meta"]["variants"].keys())


def bootstrap_rows():
    rows = []
    for ep in EP_ORDER:
        d = BOOT[ep]
        for cfg in ["unhedged_satellite"] + VARIANTS:
            c = d["by_config"][cfg]
            ci = c["ci90_L20"] or [None, None]
            hero = " hero-row" if cfg == "collar_baseline" else ""
            rows.append(
                f'<tr class="{hero.strip()}"><td class="tk-cell"><span class="tk-name">{esc(EP_SHORT[ep])}</span></td>'
                f'<td class="tk-cell">{esc(VARIANT_LABEL.get(cfg, "무헤지"))}</td>'
                f'<td class="num">{d["n_obs"]}</td>'
                f'<td class="num">{fnum(c["point_sharpe"],2,True)}</td>'
                f'<td class="num">[{fnum(ci[0],2,True)}, {fnum(ci[1],2,True)}]</td></tr>'
            )
    return "".join(rows)


def combined_rows():
    rows = []
    for scen in ["base", "calm_heavy", "crisis_heavy"]:
        for v in VARIANTS:
            g = COMB[scen][f"{v}_vs_unhedged_satellite"]
            wr = g["pct_draws_a_ahead"]
            cls = "hero-row" if wr >= 0.55 else ("warn-row" if wr <= 0.45 else "")
            rows.append(
                f'<tr class="{cls}"><td class="tk-cell"><span class="tk-name">{esc(SCEN_LABEL[scen])}</span></td>'
                f'<td class="tk-cell">{esc(VARIANT_LABEL[v])}</td>'
                f'<td class="num">{fnum(wr*100,1)}%</td>'
                f'<td class="num">{fnum(g["mean_gap"],3,True)}</td>'
                f'<td class="num">[{fnum(g["ci90_gap"][0],3,True)}, {fnum(g["ci90_gap"][1],3,True)}]</td></tr>'
            )
    return "".join(rows)


# ---------------------------------------------------------------------------
# derived headline numbers
# ---------------------------------------------------------------------------

FULL_BASELINE_SHARPE = BASE["full_2019_2026"]["collar_hedged"]["sharpe"]
FULL_DEEP_PUT_SHARPE = R["put_grid"]["full_2019_2026"][-1]["sharpe_collar"]
GFC_BASELINE_SHARPE = BASE["gfc_2008"]["collar_hedged"]["sharpe"]
GFC_LONG_TENOR_SHARPE = R["tenor_grid"]["gfc_2008"][-1]["sharpe_collar"]
FULL_LONG_TENOR_SHARPE = R["tenor_grid"]["full_2019_2026"][-1]["sharpe_collar"]
FULL_SHORT_TENOR_SHARPE = R["tenor_grid"]["full_2019_2026"][0]["sharpe_collar"]
REAL_BEATS_COUNT = R["real_beats_placebo_count"]
PERM_FULL_PCT = PERM["full_2019_2026"]["actual_percentile_in_null"]
PERM_COVID_PCT = PERM["covid_2020"]["actual_percentile_in_null"]
PERM_GFC_PCT = PERM["gfc_2008"]["actual_percentile_in_null"]

WIN_RATES_BASE = [COMB["base"][f"{v}_vs_unhedged_satellite"]["pct_draws_a_ahead"] for v in VARIANTS]
WIN_RATES_ALL = [COMB[s][f"{v}_vs_unhedged_satellite"]["pct_draws_a_ahead"] for s in ["base", "calm_heavy", "crisis_heavy"] for v in VARIANTS]
WIN_MIN, WIN_MAX = min(WIN_RATES_ALL) * 100, max(WIN_RATES_ALL) * 100

HTML = f"""<title>칼라 옵션 헤지 파라미터 민감도 — 모네니스×테너 그리드 감사</title>
<style>
{CSS}
</style>

<div class="masthead">
  <div class="masthead-inner">
    <div class="masthead-eyebrow">
      <span>QUANT RESEARCH NOTE</span><span class="dot">·</span><span>작업57 라이브화 후속</span><span class="dot">·</span><span>Parameter Sensitivity Audit</span>
    </div>
    <h1 class="masthead-title">칼라 옵션 헤지의 (풋 1.00 / 콜 1.05 / 테너 21일)은 왜 이 숫자인가 — 모네니스×테너 그리드와 부트스트랩으로 감사한다</h1>
    <p class="masthead-sub">2026-09-14 라이브화된 새틀라이트 합성 칼라(ATM 풋 매수 + 5%OTM 콜 매도, 월간 롤)는
      원 리서치(작업48)가 민감도 체크용으로 남겨둔 주석값이 그대로 기본값이 된 것일 뿐, 이 조합 자체가
      감사된 적은 없었다. 그리드 스윕(H2)은 풋/콜 모네니스와 테너 각각에서 <b>경제적으로 말이 되는
      단조로운 트레이드오프</b>(싼 보험은 평시에 유리, 넓은/긴 보호는 위기에 유리)를 드러내 베이스라인이
      우연한 뾰족한 봉우리가 아님을 확인했지만, 순열검정(H3a)은 실제 청산 타이밍이 진짜 위기창
      (2008/COVID/2022/2018)에서만 무작위 재배치를 이기고 평시 전체기간에서는 오히려 진다는 걸 보였고,
      제로페이오프 플라시보(H3b)는 6개 창 전부에서 실제 칼라가 순수 비용드래그보다 낫다는 걸 확인했다.
      그런데 블록부트스트랩+디리클레 결합전파(H4)를 걸면 베이스라인을 포함한 5개 파라미터 변형
      전부가 무헤지 새틀라이트 대비 승률 {fnum(WIN_MIN,0)}%~{fnum(WIN_MAX,0)}%로 <b>서로도, 무헤지와도
      통계적으로 구별이 안 된다</b> — 파라미터를 튜닝해도 신뢰구간 안의 노이즈일 뿐이라는, 이 프로그램의
      전형적 패턴이 여기서도 재현됐다.</p>
    <div class="masthead-meta">
      <span><b>기준일</b> {esc(GEN)}</span>
      <span><b>그리드</b> 풋 4×콜 4×테너 4 + 이웃결합 16 (창당 32포인트)</span>
      <span><b>순열검정</b> {R["meta"]["n_permutations"]}회, 페이오프-프리미엄 쌍 셔플</span>
      <span><b>부트스트랩</b> 순환 이동블록 L=10/20/40, 창×구성당 {R["meta"]["bootstrap_n_boot"]}회 + 디리클레(K=30) 결합전파</span>
    </div>
  </div>
</div>

<div class="wrap">

<div class="toc">
  <a href="#s0">0. 문제 제기</a>
  <a href="#s1">1. 베이스라인 — 6개 창 요약</a>
  <a href="#s2">2. H2 그리드 스윕 — 풋/콜/테너 민감도</a>
  <a href="#s3">3. H3 플라시보 — 타이밍이 진짜인가, 비용드래그인가</a>
  <a href="#s4">4. H4 블록부트스트랩 — 파라미터 선택이 신뢰구간을 벗어나는가</a>
  <a href="#s5">5. 종합 판정</a>
  <a href="#s6">6. 한계 및 다음 과제</a>
</div>

<div class="section" id="s0">
  <h2><span class="sec-no">0</span>문제 제기</h2>
  <p class="lede">작업57(챔피언 엔진 고도화)이 <code>core/champion_strategy.py::build_collar_overlay_returns</code>를
    라이브 배포하며 쓴 (put=1.00 ATM, call=1.05 5%OTM, tenor=21거래일≈월물) 조합은 작업48
    (synthetic_options_tail_hedge_research)이 "민감도는 다음 라운드 과제"로 명시적으로 남긴 채 그대로
    기본값이 됐다. 이 라운드는 그 숙제를 4단계로 닫는다 — (H1) 6개 역사적 창의 코어/새틀라이트 수익률을
    캐시하고, (H2) 그 위에 풋/콜/테너 그리드와 제로코스트 변형을 얹어 베이스라인이 고립된 봉우리인지
    완만한 고원인지 보고, (H3) 순열검정+제로페이오프 플라시보로 "타이밍이 진짜 위기와 맞물려서" 가치를
    내는지 확인하고, (H4) 이 프로그램의 표준 감사(블록부트스트랩×디리클레 결합전파)를 그리드의 이웃
    후보들에 직접 적용한다. 계산 로직은 새로 만들지 않고 <code>build_collar_overlay_returns</code>/
    <code>bs_put_price</code>/<code>bs_call_price</code>를 그대로 재사용했다(제로코스트 콜 행사가만
    이분탐색 어댑터를 얇게 추가).</p>
</div>

<div class="section" id="s1">
  <h2><span class="sec-no">1</span>베이스라인(풋1.00/콜1.05/테너21) — 6개 창 요약</h2>
  <p class="lede">결정창은 full_2019_2026은 전체기간, 나머지는 위기창(crisis_window)이다. COVID 행(강조)은
    n=51거래일로 표본이 가장 짧다.</p>
  <div class="table-wrap">
    <table class="data-table">
      <thead><tr><th>창(결정창)</th><th>코어단독 Sharpe</th><th>무헤지새틀라이트 Sharpe</th><th>칼라 Sharpe</th>
        <th>무헤지 MDD</th><th>칼라 MDD</th><th>롤 횟수</th></tr></thead>
      <tbody>{baseline_rows()}</tbody>
    </table>
  </div>
</div>

<div class="section" id="s2">
  <h2><span class="sec-no">2</span>H2 — 그리드 스윕: 풋/콜/테너 각각의 민감도</h2>
  <p class="lede">각 셀은 결정창(crisis_window/full_period) Sharpe. 오른쪽 끝 회색 열은 참고용 무헤지 새틀라이트
    Sharpe(해당 창, 그리드와 무관하게 고정).</p>

  <h3>H2a 풋 모네니스 — ATM(1.00, 베이스라인) → 딥아웃풋(0.90)</h3>
  <div class="table-wrap">
    <table class="data-table">
      <thead><tr><th>창</th>{"".join(f'<th>put={p:.3f}</th>' for p in PUT_PARAMS)}<th>무헤지(참고)</th></tr></thead>
      <tbody>{grid_rows(R["put_grid"])}</tbody>
    </table>
  </div>
  <p>딥아웃풋(0.90)은 평시 전체기간 Sharpe를 {fnum(FULL_BASELINE_SHARPE,2,True)}→{fnum(FULL_DEEP_PUT_SHARPE,2,True)}로
    끌어올리지만(싼 보험료), 실제 위기창에서는 예외 없이 베이스라인보다 나쁘다(GFC·COVID·2018 모두
    단조 악화) — "보험을 얇게 살수록 평시엔 이득, 위기엔 손해"라는 경제적으로 말이 되는 방향성이 6개
    창 중 5개에서 단조적으로 나타나 무작위 노이즈로 보기 어렵다(2015-16만 거의 평평 — 애초에 이
    구간은 새틀라이트 자체가 크게 부진해 칼라 유무가 거의 무관).</p>

  <h3>H2b 콜 모네니스 — 1.025(타이트) → 1.10(와이드) + 제로코스트</h3>
  <div class="table-wrap">
    <table class="data-table">
      <thead><tr><th>창</th>{"".join(f'<th>call={c:.3f}</th>' for c in CALL_PARAMS)}<th>무헤지(참고)</th></tr></thead>
      <tbody>{grid_rows(R["call_grid"])}</tbody>
    </table>
  </div>
  <p>콜은 반대 방향 — 타이트한 콜(1.025, 프리미엄을 더 많이 걷어 순비용을 낮춤)이 4/6 창(GFC·COVID·
    2018·2015-16)에서 베이스라인(1.05)보다 낫다. 다만 평시 전체기간과 2022년은 오히려 베이스라인
    (1.05)이 근소 1위 — 상단을 더 많이 내주는 타이트 콜의 기회비용이 강세장에서 드러난다. 제로코스트
    변형(프리미엄=페이오프가 되도록 매 롤 콜 행사가를 이분탐색)은 아래 표처럼 베이스라인과 무헤지의
    중간 어딘가에 수렴할 뿐, 어느 쪽도 일관되게 이기지 못한다.</p>
  <div class="table-wrap">
    <table class="data-table">
      <thead><tr><th>창</th><th>무헤지</th><th>베이스라인 칼라</th><th>제로코스트 칼라</th></tr></thead>
      <tbody>{zero_cost_rows()}</tbody>
    </table>
  </div>

  <h3>H2c 테너 — 10일(짧음) → 63일(김, 분기물 근사)</h3>
  <div class="table-wrap">
    <table class="data-table">
      <thead><tr><th>창</th>{"".join(f'<th>tenor={t}d</th>' for t in TENOR_PARAMS)}<th>무헤지(참고)</th></tr></thead>
      <tbody>{grid_rows(R["tenor_grid"])}</tbody>
    </table>
  </div>
  <div class="callout">
    <div class="callout-title">가장 뚜렷한 패턴 — 테너는 진짜 트레이드오프다</div>
    <p>평시 전체기간은 짧은 테너(10일)가 최고({fnum(FULL_SHORT_TENOR_SHARPE,2,True)})이고 길어질수록
      단조 악화({fnum(FULL_LONG_TENOR_SHARPE,2,True)}까지, 63일)하는 반면, GFC 위기창은 정반대로
      63일 테너가 베이스라인(21일, {fnum(GFC_BASELINE_SHARPE,2,True)})을 {fnum(GFC_LONG_TENOR_SHARPE,2,True)}로
      크게 앞선다 — "짧은 물은 평시 비용이 싸고, 긴 물은 광범위·장기 위기(2008형)를 한 계약 안에서
      더 온전히 포착한다"는, H19(트레일링스탑 폭 스윕)가 찾은 것과 같은 종류의 진짜 연속 프론티어다.
      2022년 약세장도 짧은 테너보다 긴 테너가 낫다(0.30→0.58). 단일 정답은 없다는 이 프로그램의
      반복 패턴이 옵션 테너에도 그대로 적용된다.</p>
  </div>

  <h3>H2d 이웃 결합그리드 — 견고성(고원 vs 봉우리) 확인</h3>
  <p>풋∈{{0.95,1.00}}×콜∈{{1.05,1.10}}×테너∈{{21,42}} 16개 조합을 6개 창에 돌려도 극단적 반전은 없다 —
    위 H2a/H2b/H2c에서 본 단조적 방향성이 결합해도 유지될 뿐, 어느 한 조합이 나머지를 압도하는 뾰족한
    봉우리는 어느 창에서도 나타나지 않았다(원자료는 report_data.json의 neighborhood_grid에 전부 보존).
    베이스라인은 이 고원 위의 합리적인 한 점이라는 것이 점추정 수준에서는 확인된다 — 다만 "합리적인
    한 점"이 "유의미하게 우월한 점"과 같은 말은 아니라는 게 4절의 핵심이다.</p>
</div>

<div class="section" id="s3">
  <h2><span class="sec-no">3</span>H3 — 플라시보: 타이밍이 진짜인가, 비용드래그의 착시인가</h2>
  <h3>H3a 순열검정 — 실제 롤 타이밍이 무작위 재배치를 이기는가</h3>
  <p class="lede">각 롤의 (프리미엄,페이오프) 쌍을 200회 무작위 재배치해 만든 널분포 대비, 실제(섞지 않은)
    타이밍의 위기창 Sharpe 개선폭이 몇 백분위인지. 85 이상(강조)이면 실제 타이밍이 우연보다 뚜렷이
    낫다는 뜻, 25 이하(경고)면 실제 타이밍이 오히려 우연보다 못하다는 뜻이다.</p>
  <div class="table-wrap">
    <table class="data-table">
      <thead><tr><th>창</th><th>N(롤)</th><th>실제 Δ샤프</th><th>널분포 90% CI</th><th>실제값 백분위</th></tr></thead>
      <tbody>{permutation_rows()}</tbody>
    </table>
  </div>
  <div class="callout">
    <div class="callout-title">위기창에서는 타이밍이 진짜다, 평시에서는 아니다</div>
    <p>GFC({fnum(PERM_GFC_PCT,1)}th)·COVID({fnum(PERM_COVID_PCT,1)}th)·2022(96.5th)·2018(97.5th)
      네 위기창 모두 실제 타이밍이 무작위 재배치의 상위 백분위에 있다 — 우연이 아니라 실제 크래시가
      만기 페이오프와 실제로 맞물려서 가치를 낸다는 직접 증거다. 하지만 평시 전체기간은 정반대로
      {fnum(PERM_FULL_PCT,1)}th — 실제 달력상의 롤 타이밍이 무작위 배치보다 오히려 나쁘다(평시엔
      어차피 페이오프가 거의 없으니, 우연히 비쌀 때 프리미엄을 낸 롤이 몇 번 끼면 그대로 손해로
      남는다). 2015-16은 75.5th로 애매한 중간. 종합: 이 헤지는 "평상시엔 비용, 위기엔 보험"이라는
      본연의 설계대로 작동하고 있다는 게 순열검정으로 뒷받침된다.</p>
  </div>

  <h3>H3b 제로페이오프 플라시보 — 페이오프(볼록성) 자체가 가치를 내는가</h3>
  <p class="lede">같은 프리미엄 지불 스케줄은 유지한 채 만기 페이오프를 전부 0으로 만든 가짜 오버레이와
    비교. 실제 칼라가 이 플라시보보다 뚜렷이 나아야 "페이오프 자체가 방어에 기여한다"는 주장이 선다.</p>
  <div class="table-wrap">
    <table class="data-table">
      <thead><tr><th>창</th><th>무헤지</th><th>제로페이오프 플라시보</th><th>실제 칼라</th><th>실제&gt;플라시보?</th></tr></thead>
      <tbody>{zero_payoff_rows()}</tbody>
    </table>
  </div>
  <div class="callout good">
    <div class="callout-title">6개 창 전부에서 실제 칼라가 순수 비용드래그 플라시보를 이긴다</div>
    <p>{REAL_BEATS_COUNT}/6개 창 전부 실제 칼라 Sharpe &gt; 제로페이오프 플라시보 Sharpe — "칼라가 무헤지를
      이긴다"는 관측이 단순히 프리미엄 지불로 변동성을 깎아 샤프 분모를 줄이는 계산상의 부작용이
      아니라, 실제 만기 페이오프(볼록성)가 진짜 가치를 더한다는 뜻이다. H3a·H3b를 합치면 이 칼라
      헤지는 "가짜 신호"는 아니다 — 다음 절의 질문은 "그 진짜 신호가 통계적으로 얼마나 강한가"이다.</p>
  </div>
</div>

<div class="section" id="s4">
  <h2><span class="sec-no">4</span>H4 — 블록부트스트랩×디리클레 결합전파: 파라미터 선택이 신뢰구간을 벗어나는가</h2>
  <p class="lede">3절까지는 점추정 기준으로 칼라가 "진짜"라는 근거를 쌓았다. 이 절은 이 프로그램의
    핵심 메타패턴("가중치만 반영한 승률 90%대가 블록부트스트랩을 거치면 50%대로 무너진다")이 베이스라인과
    그 이웃 4개 변형(딥아웃풋풋/와이드콜/롱테너/제로코스트) 각각에 대해서도 재현되는지 직접 감사한다.</p>
  <h3>창별 신뢰구간 (L=20, 90% CI)</h3>
  <div class="table-wrap">
    <table class="data-table">
      <thead><tr><th>창</th><th>구성</th><th>N(거래일)</th><th>점추정 Sharpe</th><th>L=20 CI90</th></tr></thead>
      <tbody>{bootstrap_rows()}</tbody>
    </table>
  </div>

  <h3>디리클레(K=30) × 부트스트랩 결합전파 — 각 변형 vs 무헤지 승률</h3>
  <div class="table-wrap">
    <table class="data-table">
      <thead><tr><th>기저확률 시나리오</th><th>파라미터 변형</th><th>승률(변형 우위)</th><th>평균 갭</th><th>갭 CI90</th></tr></thead>
      <tbody>{combined_rows()}</tbody>
    </table>
  </div>
  <div class="callout warn">
    <div class="callout-title">파라미터를 어떻게 바꿔도 동전던지기 근처</div>
    <p>5개 파라미터 변형(베이스라인 포함) × 3개 시나리오 = 15개 승률이 전부 {fnum(WIN_MIN,0)}%~{fnum(WIN_MAX,0)}%
      범위에 몰려있다 — 55% 이상(강조)이거나 45% 이하(경고)인 셀도 있지만 갭 CI90은 전부 0을 큰
      폭으로 포함한다. 2절(H2)에서 찾은 "테너가 길수록 위기에 강하다"는 점추정 수준의 방향성은
      crisis_heavy 시나리오에서 롱테너(58.8%)·제로코스트(59.0%)가 베이스라인(57.0%)보다 근소하게
      높은 승률로 살아있긴 하지만, 이 프로그램의 90% 신뢰 기준에는 전부 한참 못 미친다. <span class="badge weak">약함(WEAK)</span>
      결론: 어느 특정 (풋,콜,테너) 조합도 다른 조합보다 통계적으로 우월하다고 말할 수 없다 — 2~3절의
      "진짜 신호"와 4절의 "그 신호의 정확한 크기는 노이즈에 묻힌다"는 이 프로그램에서 반복돼온
      "방향은 있지만 확신은 약하다"는 패턴의 또 다른 사례다.</p>
  </div>
</div>

<div class="section" id="s5">
  <h2><span class="sec-no">5</span>종합 판정</h2>
  <p><b>기존 confidence_table의 "칼라 옵션 헤지: 약함(weak)" 등급은 유지되며, 이번 감사로 등급의
    근거가 더 정교해졌다.</b> 구체적으로:</p>
  <ul>
    <li><b>베이스라인(1.00/1.05/21)은 과최적화된 봉우리가 아니다</b> — H2d 이웃결합그리드에서 극적인
      반전 없이 완만한 고원 위에 있고, 그 고원 자체가 경제적으로 말이 되는 단조로운 트레이드오프
      (싼 보험=평시 유리·위기 불리, 긴 테너=위기 유리·평시 불리)로 설명된다. 사후적으로 데이터에
      맞춰 고른 숫자라는 의심은 낮아졌다(채택).</li>
    <li><b>"타이밍이 진짜"라는 주장은 H3a/H3b 둘 다에서 지지된다</b> — 실제 위기창에서는 실제 타이밍이
      무작위 재배치를 압도적으로 이기고, 6개 창 전부에서 실제 페이오프가 제로페이오프 플라시보를
      이긴다(채택).</li>
    <li><b>하지만 그 어떤 파라미터 조합도 다른 조합·무헤지 대비 통계적으로 유의하게 우월하지 않다</b> —
      H4 결합전파 승률이 전부 45~59% 구간(채택되지 않음, WEAK 유지). 즉 "칼라 헤지 자체는 방향이
      있는 진짜 메커니즘"과 "그 정확한 파라미터 선택은 임의적이어도 무방하다(통계적으로 구별 안 됨)"는
      두 명제가 동시에 성립한다.</li>
    <li>실용적 함의: 현재 라이브 기본값(1.00/1.05/21)을 굳이 바꿀 근거는 없다 — 바꾼다고 통계적으로
      유의하게 나아지지 않는다. 다만 crisis_heavy 시나리오에서 롱테너·제로코스트가 근소하게 앞서는
      점추정 방향성은 "위기 국면에서만 테너를 늘리는 조건부 전환" 같은 다음 단계 아이디어의 씨앗은
      될 수 있다(6절에서 다음 과제로 명시).</li>
  </ul>
</div>

<div class="section" id="s6">
  <h2><span class="sec-no">6</span>한계 및 다음 과제</h2>
  <ul>
    <li>COVID 창은 n_obs=51로 이 프로그램에서 가장 짧다 — 신뢰구간이 사실상 무정보에 가깝다(작업49의
      경고 그대로 재현).</li>
    <li>옵션가격은 여전히 Black-Scholes + VIX/100 대리변동성이라는 단순화다 — 스마일/스큐, 일일
      마크투마켓은 반영하지 않는다.</li>
    <li>제로코스트 변형의 콜 행사가는 매 롤 이분탐색으로 그때그때 구한 것이라, 다른 4개 변형과 달리
      "고정 모네니스"가 아니다 — 직접 비교 시 이 비대칭을 감안해야 한다.</li>
    <li>H2d 결합그리드는 16개 조합만 스윕했다(전체 4×4×4=64칸 중 일부) — 더 촘촘한 3차원 그리드는
      다루지 않았다.</li>
    <li><b>다음 과제로 명시</b>: H2c가 찾은 "짧은 테너=평시 유리, 긴 테너=위기 유리" 트레이드오프를
      SPY 200일선 같은 기존 국면필터로 테너 자체를 전환하는 조건부 설계로 발전시켜, H4와 동일한
      부트스트랩 감사를 거치면 이 프로그램의 다른 모든 "조건부 스위치"(국면조건부 새틀라이트 등)와
      같은 패턴(가중치 승률은 높지만 결합전파에서 무너짐)이 재현되는지 확인할 가치가 있다 — 이번
      라운드에서는 만들지 않았다.</li>
  </ul>
</div>

</div>
<footer>
  <p>산출물: analysis/2026-09-15_options_collar_parameter_sensitivity/ (h1_champion_returns_cache.py,
    h2_moneyness_tenor_grid.py, h3_placebo_and_permutation.py, h4_block_bootstrap_audit.py,
    build_report_data.py, report_data.json, build_report.py). 작업57(챔피언 엔진 고도화 — 옵션 칼라
    헤지 라이브화)의 파라미터 민감도 후속 감사. core/, app/는 수정하지 않음.</p>
</footer>
"""

with open(f"{OUT_DIR}/final_report.html", "w", encoding="utf-8") as f:
    f.write(HTML)
print("wrote final_report.html", len(HTML))
