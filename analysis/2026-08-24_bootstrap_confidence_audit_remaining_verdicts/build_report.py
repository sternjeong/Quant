#!/usr/bin/env python3
"""report_data.json을 읽어 final_report.html을 만든다.

analysis/2026-08-23_block_bootstrap_sample_error_quantification/build_report.py(H33)와 동일한
디자인 시스템(다크네이비/올리브 톤, 세리프 헤드라인, TOC, 섹션 번호, 판정 배지)을 재사용한다.
"""
import json
import math
import os

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

with open(f"{OUT_DIR}/report_data.json", encoding="utf-8") as f:
    R = json.load(f)

GEN = R["meta"]["generated"]
H34 = R["h34"]
H33 = R["h33"]
H33B = R["h33b"]
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


def combined_row(label, weighting_wr, combined_wr, gap):
    return (
        f'<tr><td class="tk-cell"><span class="tk-name">{esc(label)}</span></td>'
        f'<td class="num">{pct(weighting_wr,1)}</td>'
        f'<td class="num">{pct(combined_wr,1)}</td>'
        f'<td class="num">[{fnum(gap[0],3,signed=True)}, {fnum(gap[1],3,signed=True)}]</td></tr>'
    )


CFG_LABEL_H26 = {"spy_buyhold": "SPY 매수보유", "core_alone": "코어 단독", "case_a_static_satellite": "시스템(코어+새틀라이트)"}
CFG_LABEL_H28 = {"no_overlay": "오버레이 없음", "vol_targeted": "변동성타겟팅(18%)"}
CFG_LABEL_H32 = {"monthly_21d": "월간(21일)", "quarterly_63d": "분기(63일)"}

C26 = H34["combined_h26_system_vs_spy"]
C26b = H34["combined_h26_core_alone_vs_spy"]
C28 = H34["combined_h28_vol_targeted_vs_no_overlay"]
C32 = H34["combined_h32_quarterly_vs_monthly"]


def unified_rows():
    rows = []
    for row in UNIFIED:
        gc = row["combined_grade"]
        cls = {"robust": "grade-A", "moderate": "grade-A", "weak": "grade-B", "reversed": "grade-C"}.get(gc, "grade-B")
        warn = " warn-row" if gc == "reversed" else ""
        rows.append(
            f'<tr class="{warn.strip()}"><td class="tk-cell"><span class="tk-name">{esc(row["id"])}</span> '
            f'{esc(row["label"])}</td>'
            f'<td class="num">{pct(row["weighting_only_win_rate"],1)}</td>'
            f'<td class="num">{pct(row["combined_win_rate"],1)}</td>'
            f'<td class="num">[{fnum(row["combined_gap_ci90"][0],3,signed=True)}, {fnum(row["combined_gap_ci90"][1],3,signed=True)}]</td>'
            f'<td>{grade_badge(gc)}</td></tr>'
        )
    return "".join(rows)


HTML = f"""<title>블록부트스트랩 신뢰도 감사 확장</title>
<style>
{CSS}
</style>

<div class="masthead">
  <div class="masthead-inner">
    <div class="masthead-eyebrow">
      <span>QUANT RESEARCH NOTE</span><span class="dot">·</span><span>19라운드</span><span class="dot">·</span><span>Hypothesis-Driven Study</span>
    </div>
    <h1 class="masthead-title">나머지 세 판정도 표본오차 앞에서 흔들린다</h1>
    <p class="masthead-sub">작업44(H33)는 H22 한 비교(코어단독 vs 정적보유 새틀라이트)에만 블록부트스트랩
      표본오차를 적용해 "가중치 불확실성보다 표본오차가 압도적으로 더 크다"는 걸 발견했지만, 같은 시리즈의
      다른 세 "채택" 판정 — H26(시스템 vs SPY), H28(변동성타겟팅 기각), H32(분기 리밸런싱 채택) —에는 아직
      같은 감사를 적용한 적이 없었다. 이번 라운드는 정확히 같은 방법론을 셋 다에 확장한다. 결과는
      한결같았다 — <b>가중치만 흔들 때는 90%대 이상으로 확정적이던 판정들이, 표본오차를 더하면 대부분
      50%대 근처(동전던지기)로 무너진다.</b></p>
    <div class="masthead-meta">
      <span><b>기준일</b> {esc(GEN)}</span>
      <span><b>블록부트스트랩</b> 창×구성당 {R['meta']['n_boot']:,}회, 블록길이 {', '.join(str(x)+'일' for x in R['meta']['block_lengths'])}</span>
      <span><b>결합전파</b> {R['meta']['n_draws']:,} draws (디리클레×부트스트랩)</span>
      <span><b>대상</b> H26 시스템vsSPY · H28 변동성타겟팅 · H32 리밸런싱주기</span>
    </div>
  </div>
</div>

<div class="wrap">

  <nav class="toc">
    <a href="#scope">00 문제 제기</a>
    <a href="#h26">01 H26 — 시스템 vs SPY 매수보유</a>
    <a href="#h28">02 H28 — 변동성타겟팅 오버레이</a>
    <a href="#h32">03 H32 — 분기 vs 월간 리밸런싱</a>
    <a href="#unified">04 종합 — 5개 판정 통합 신뢰도표</a>
    <a href="#limitations">05 한계</a>
  </nav>

  <section class="section" id="scope">
    <h2><span class="sec-no">00</span> 문제 제기 — H33이 하나에만 적용했던 감사를 셋으로 확장</h2>
    <p class="lede">작업44(H33)는 트랙D 전체가 의존해 온 6개 창의 Sharpe 점추정치 자체에 표본오차가
      있다는 걸 처음으로 정량화했다 — H30의 디리클레 가중치 불확실성만으로는 "정적보유가 99.7% 확률로
      이긴다"고 나왔지만, 창별 일별수익률 시계열 자체의 블록부트스트랩 표본오차를 더하면 그 확률이
      58%까지 떨어졌다. 이건 H22 딱 하나의 비교에서만 확인된 사실이었다 — H26(시스템 vs SPY 매수보유),
      H28(변동성타겟팅 기각), H32(분기 리밸런싱 채택)는 전부 H30식 가중치-단독 몬테카를로만 거쳤을 뿐,
      단 한 번도 이 표본오차 감사를 받은 적이 없다. 이 라운드는 정확히 그 갭을 닫는다 — H33의 코드를
      그대로 재사용해 세 판정 모두에 동일한 방법론(순환 이동블록부트스트랩, L=10/20/40일 중 20일
      중심, 창당 2,000회, 디리클레 결합전파 10,000 draws)을 적용한다.</p>
    <p class="caveat">⚠️ 투자 조언이 아니다. H32 비교는 사용자 지시대로 룩백을 12개월로 고정한 채
      리밸런싱 주기(월간 vs 분기)만 격리해 감사한다 — H32의 원래 headline 권고("분기가 모든 해상도·
      시나리오에서 방향이 안 뒤집힌다")는 룩백을 9~18개월로 함께 스윕한 40칸 그리드에서 나온 것이라,
      이 라운드의 좁은 12개월-고정 비교는 그 headline과 범위가 다르다는 점을 04절에서 다시 명시한다.</p>
  </section>

  <section class="section" id="h26">
    <h2><span class="sec-no">01</span> H26 — 시스템(코어+새틀라이트) vs SPY 매수보유</h2>
    <p class="lede">작업40(H26)의 원래 판정은 "챔피언+새틀라이트 &gt; 챔피언단독 &gt; SPY매수보유"
      순위가 세 시나리오 전부에서 일관됐다는 것이었다. 이번 라운드는 SPY 매수보유 일별수익률을 새로
      받아오고(신규, 저비용), core_alone/case_a_static_satellite는 H33이 이미 저장해 둔 일별수익률을
      그대로 재사용해 세 구성 모두를 블록부트스트랩했다.</p>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>창</th><th>구성</th><th>n_obs(거래일)</th><th>점추정 Sharpe</th>
          <th>90% 부트스트랩 CI (L=20)</th><th>≈비독립 블록수</th></tr></thead>
        <tbody>{window_ci_rows(H34['bootstrap_h26_system_vs_spy'], ['spy_buyhold','core_alone','case_a_static_satellite'], CFG_LABEL_H26)}</tbody>
      </table>
    </div>
    <h3>가중치×표본오차 결합 전파</h3>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>비교</th><th>가중치만(H30 방식)</th><th>결합(가중치+표본오차)</th><th>90% CI(격차)</th></tr></thead>
        <tbody>
          {combined_row('시스템(코어+새틀라이트) vs SPY', C26['weighting_only_win_rate_challenger'], C26['combined_win_rate_challenger'], C26['combined_gap_challenger_minus_baseline']['ci90'])}
          {combined_row('코어단독 vs SPY (부가)', C26b['weighting_only_win_rate_challenger'], C26b['combined_win_rate_challenger'], C26b['combined_gap_challenger_minus_baseline']['ci90'])}
        </tbody>
      </table>
    </div>
    <div class="callout warn">
      <div class="callout-title">"시스템이 SPY를 이긴다"는 방향은 살아남지만 확신은 크게 준다</div>
      <p>가중치만 흔들면 시스템(코어+새틀라이트)의 승률은 {pct(C26['weighting_only_win_rate_challenger'],1)}로 매우 강건해 보였다.
        하지만 표본오차까지 결합하면 승률이 {pct(C26['combined_win_rate_challenger'],1)}로 떨어진다 —
        여전히 절반을 넘어 방향은 유지되지만(약함 등급), "거의 확실"이라고 부를 수준은 아니다. 코어단독
        vs SPY는 더 약하다({pct(C26b['weighting_only_win_rate_challenger'],1)} → {pct(C26b['combined_win_rate_challenger'],1)}) —
        시스템 전체의 우위 대부분이 새틀라이트가 아니라 로테이션+필터(코어) 자체에서 나온다는 H26의
        원래 주장과 일관되지만, 그 코어 자체의 SPY 대비 우위도 표본오차를 감안하면 동전던지기에
        근접한다.</p>
    </div>
  </section>

  <section class="section" id="h28">
    <h2><span class="sec-no">02</span> H28 — 변동성타겟팅 오버레이 없음 vs 있음</h2>
    <p class="lede">작업41(H28)의 원래 판정은 "세 시나리오 전부에서 변동성타겟팅이 기각된다"였다
      (17자산 분산+이진 시장필터가 이미 변동성타겟팅의 몫 대부분을 흡수해서, 오버레이는 순수 비용에
      가깝다는 설명). 이번 라운드는 champion_strategy.run_champion을 6개 창에 새로 실행해 오버레이
      有/無 두 일별수익률 시계열을 얻고 블록부트스트랩했다.</p>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>창</th><th>구성</th><th>n_obs(거래일)</th><th>점추정 Sharpe</th>
          <th>90% 부트스트랩 CI (L=20)</th><th>≈비독립 블록수</th></tr></thead>
        <tbody>{window_ci_rows(H34['bootstrap_h28_vol_targeting'], ['no_overlay','vol_targeted'], CFG_LABEL_H28)}</tbody>
      </table>
    </div>
    <h3>가중치×표본오차 결합 전파</h3>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>비교</th><th>가중치만(H30 방식), 오버레이 승률</th><th>결합, 오버레이 승률</th><th>90% CI(격차, 오버레이−없음)</th></tr></thead>
        <tbody>
          {combined_row('변동성타겟팅 vs 오버레이없음', C28['weighting_only_win_rate_challenger'], C28['combined_win_rate_challenger'], C28['combined_gap_challenger_minus_baseline']['ci90'])}
        </tbody>
      </table>
    </div>
    <div class="callout warn">
      <div class="callout-title">"강하게 기각됐다"는 판정이 표본오차 앞에서는 동전던지기로 무너진다</div>
      <p>가중치만 흔들면 오버레이 없음이 {pct(1-C28['weighting_only_win_rate_challenger'],1)} 확률로 이겨
        H28의 "세 시나리오 전부 기각" 서술이 정당했다. 하지만 표본오차를 더하면 오버레이 없음의 승률이
        {pct(1-C28['combined_win_rate_challenger'],1)}까지 떨어진다 — 사실상 정확히 절반이다. 방향 자체가
        "변동성타겟팅이 낫다"로 뒤집혔다는 뜻은 아니다(격차의 평균은 여전히 거의 0에 가깝게 오버레이없음
        쪽으로 살짝 치우쳐 있다) — 정확한 해석은 "둘 사이의 차이가 애초에 표본오차 내에서 구분이 안 될
        만큼 작았다"는 것이다. H28 원문이 스스로 인정했던 "MDD 개선폭도 0.3%p뿐"이라는 관찰과 일관된다
        — 애초에 실질적 차이가 거의 없는 두 구성을 비교했던 것이고, 표본오차 렌즈가 그 사실을 더
        선명하게 드러낼 뿐이다.</p>
    </div>
  </section>

  <section class="section" id="h32">
    <h2><span class="sec-no">03</span> H32 — 분기 리밸런싱 vs 월간 리밸런싱 (룩백 12개월 고정)</h2>
    <p class="lede">작업44(H32)의 원래 headline은 "룩백 9~18개월 x 리밸런싱 4값의 40칸 정밀그리드에서
      분기 리밸런싱이 모든 해상도·시나리오에서 일관되게 강건했다"였다 — 다만 룩백은 그 그리드 안에서
      함께 최적화됐다(정밀 정점은 14~16개월). 이 라운드는 사용자 지시대로 룩백을 정확히 12개월로
      고정한 채 리밸런싱 주기만 격리해서 champion_strategy와 h32의 run_champion_joint()를 재사용해
      6개 창 x 2개 주기를 새로 백테스트했다 — H32의 원래 40칸 그리드 headline과는 범위가 다른 더
      좁은 질문이라는 점에 유의.</p>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>창</th><th>구성</th><th>n_obs(거래일)</th><th>점추정 Sharpe</th>
          <th>90% 부트스트랩 CI (L=20)</th><th>≈비독립 블록수</th></tr></thead>
        <tbody>{window_ci_rows(H34['bootstrap_h32_rebalance_freq'], ['monthly_21d','quarterly_63d'], CFG_LABEL_H32)}</tbody>
      </table>
    </div>
    <h3>가중치×표본오차 결합 전파</h3>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>비교</th><th>가중치만(H30 방식), 분기 승률</th><th>결합, 분기 승률</th><th>90% CI(격차, 분기−월간)</th></tr></thead>
        <tbody>
          {combined_row('분기(63일) vs 월간(21일), 12개월 고정', C32['weighting_only_win_rate_challenger'], C32['combined_win_rate_challenger'], C32['combined_gap_challenger_minus_baseline']['ci90'])}
        </tbody>
      </table>
    </div>
    <div class="callout warn">
      <div class="callout-title">12개월 고정 비교에서는 애초부터 승자가 없었다 — 표본오차와 무관하게</div>
      <p>가중치만 흔든 시점에서 이미 분기의 승률은 {pct(C32['weighting_only_win_rate_challenger'],1)}로
        동전던지기 근처였다(월간이 근소하게 앞섬) — 표본오차를 더해도 {pct(C32['combined_win_rate_challenger'],1)}로
        거의 그대로다. 이건 H33/H26/H28처럼 "확신이 무너지는" 패턴이 아니라, "12개월 룩백에 고정한 채
        리밸런싱 주기만 격리하면 애초에 유의미한 승자가 없었다"는 다른 이야기다 — H32 자신이 이미
        기록한 관찰(순차 기본값 12개월/월간이 40칸 그리드에서 11~20위에 그침, 리밸런싱 주기 축이
        방향을 주도하는 건 오직 룩백을 함께 늘렸을 때)과 정확히 일치한다. 즉 <b>"분기가 낫다"는 H32의
        headline은 룩백을 14~16개월로 함께 옮겼을 때만 성립하는 결합효과였지, 12개월을 그대로 두고
        리밸런싱만 바꾸는 단독 개입에서는 애초에 근거가 약했다.</b></p>
    </div>
  </section>

  <section class="section" id="unified">
    <h2><span class="sec-no">04</span> 종합 — 5개 판정을 아우르는 통합 신뢰도표</h2>
    <p class="lede">H33(H22)과 이번 라운드(H26/H26부가/H28/H32)를 모두 같은 잣대(승률 90%↑=강건,
      70~90%=보통, 50~70%=약함, 50%미만=반전/미지지)로 나란히 놓으면, 트랙D 전체가 지금까지 "채택"이라고
      불러온 판정들의 실제 신뢰도 스펙트럼이 드러난다.</p>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>판정</th><th>가중치만(H30 방식)</th><th>결합(가중치+표본오차)</th><th>90% CI(격차)</th><th>신뢰도 등급</th></tr></thead>
        <tbody>{unified_rows()}</tbody>
      </table>
    </div>
    <h3>읽는 법</h3>
    <ul>
      <li><b>H22 정적보유 새틀라이트</b> — 가중치만으로는 99.7%로 최강건해 보였지만 결합하면 57.9%(약함)로
        가장 크게 무너진 판정. 그래도 방향은 살아남는다.</li>
      <li><b>H26 시스템 vs SPY</b> — 92.4%→59.7%(약함). 시스템이 SPY를 이긴다는 방향은 유지되나,
        "거의 확실"은 과장이었다.</li>
      <li><b>H26부가 코어단독 vs SPY</b> — 63.3%→53.6%(약함). 로테이션+필터 자체의 SPY 대비 우위는
        원래도 강하지 않았고, 결합하면 사실상 동전던지기에 근접한다.</li>
      <li><b>H28 변동성타겟팅 기각</b> — 96.5%→49.7%(반전/미지지 경계). "강하게 기각"이라는 원래 서술은
        과장이었다 — 실제로는 둘 사이에 표본오차 내에서 구분 안 되는 차이만 있었다. "미지지"로 분류하되,
        이는 "변동성타겟팅이 더 낫다"는 확정적 반전이 아니라 애초에 유의미한 차이가 없었다는 뜻으로
        읽어야 정확하다.</li>
      <li><b>H32 분기 리밸런싱(12개월 고정)</b> — 48.6%→49.6%(반전/미지지). 가중치 단계부터 이미
        동전던지기였다 — 표본오차가 확신을 깎은 게 아니라, 애초에 이 좁은 비교에는 확신이 없었다.
        H32의 진짜 headline(룩백을 14~16개월로 함께 옮긴 결합 최적점)은 이 라운드에서 재검증하지
        않았다(범위 밖, 05절 한계 참고) — "분기로 전환" 권고 자체를 이 결과 하나로 기각하는 건
        범위를 벗어난 과잉해석이다.</li>
    </ul>
    <h3>최종 권고 재확인</h3>
    <p>트랙D 19라운드에 걸쳐 누적된 기댓값-최적 챔피언 설정(17자산+12개월 모멘텀+이진 시장필터+
      월간 리밸런싱+변동성타겟팅 없음, 선택적 15% 정적보유 새틀라이트)의 <b>방향은 이번 감사로 하나도
      뒤집히지 않았다</b>. 다만 "채택"이라는 딱지가 가리키는 확신 수준은 판정마다 크게 다르다 — 시장필터
      자체의 존재(H26이 보여준 시스템&gt;SPY 방향)는 약하게라도 유지되는 결론인 반면, 변동성타겟팅
      기각과 12개월-고정 분기전환 두 가지는 표본오차 관점에서 "확신을 갖고 권고할 근거가 약하다"는 게
      정직한 결론이다. 실무적으로는: (1) 로테이션+필터+새틀라이트라는 큰 그림은 유지, (2) 변동성타겟팅
      오버레이는 "명백히 나쁘다"가 아니라 "실질적으로 차이가 없다"로 서술을 낮추고, (3) 분기 리밸런싱
      전환은 룩백을 함께 조정하지 않는 한(H32의 실제 headline 조건) 프로덕션에 강하게 밀어붙일 근거가
      부족하다.</p>
  </section>

  <section class="section" id="limitations">
    <h2><span class="sec-no">05</span> 한계</h2>
    <ul>
      <li>H32 비교는 사용자 지시대로 룩백을 12개월로 고정한 채 리밸런싱 주기만 격리했다 — H32의 원래
        headline(룩백 14~16개월 x 분기의 결합 최적점)은 이 라운드에서 재검증하지 않았다. "분기가
        미지지"라는 이번 결과는 좁은 질문("12개월을 그대로 두고 리밸런싱만 바꾸면?")에 대한 정직한
        답일 뿐, H32의 결합 최적점 자체를 반증하지 않는다.</li>
      <li>블록부트스트랩 자체의 한계는 H33과 동일하다 — 원 역사적 창이 "대표성 있는 하나의 실현"이라는
        전제 위에 서 있고, 실제로 일어난 적 없는 "다른 위기"를 만들어내지 못한다. COVID(51거래일)와
        2018(92거래일)의 신뢰구간은 특히 넓고 불안정하다는 게 이번 라운드에서도 재확인됐다.</li>
      <li>H28의 변동성타겟팅 비교는 champion_strategy.run_champion을 새로 실행한 신규 백테스트라
        H28 원본과 완전히 같은 코드 경로를 탔는지 별도로 대조하지 않았다 — 점추정 Sharpe 값은 H28
        원본 report_data.json과 근사하게 일치하는지만 육안으로 확인했고, 소수점 단위의 미세한 차이가
        있을 수 있다.</li>
      <li>창 사이의 상관(2008과 2022가 완전히 독립이 아닐 가능성)은 여전히 모델링하지 않았다 —
        H30/H33이 이미 지적한 디리클레의 "카테고리 간 독립성 가정" 한계가 이번 라운드에도 그대로
        적용된다.</li>
      <li>거래비용/생존편향 등 모형오차(specification error) 자체는 이번 라운드에서도 다루지 않았다 —
        표본오차(sampling)만 감사했을 뿐이다.</li>
      <li>H26 부가 비교(코어단독 vs SPY)는 이 라운드가 자체적으로 추가한 것으로, H26 원본이 명시적으로
        요구한 3-way 비교의 일부만 재현한다(SPY vs 시스템, SPY vs 코어단독은 각각 감사했지만 코어단독
        vs 시스템 자체의 표본오차 감사는 H33이 이미 커버했다).</li>
    </ul>
  </section>

</div>

<footer>
  <p>QUANT RESEARCH · 19라운드 · H34 블록부트스트랩 신뢰도 감사 확장(H26/H28/H32) · 기준일 {esc(GEN)} ·
    이 문서는 투자 조언이 아니며 저자 개인의 연구 기록입니다.</p>
</footer>
"""

with open(f"{OUT_DIR}/final_report.html", "w", encoding="utf-8") as f:
    f.write(HTML)
print("[build_report] saved final_report.html")
