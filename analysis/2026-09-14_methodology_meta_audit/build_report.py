#!/usr/bin/env python3
"""report_data.json을 읽어 final_report.html을 만든다.

analysis/2026-08-30_track_c_bootstrap_confidence_audit/build_report.py와 동일한 디자인 시스템
(다크네이비/올리브 톤, 세리프 헤드라인, TOC, 섹션 번호, 판정 배지)을 재사용한다.
"""
import json
import os

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

with open(f"{OUT_DIR}/report_data.json", encoding="utf-8") as f:
    R = json.load(f)

TC = R["test_counts"]
BFDR = R["bonferroni_fdr"]
CONS = R["consistency_and_leakage_audit"]
MC = R["meta_conclusion"]


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def pct(v, digits=1):
    if v is None:
        return "—"
    return f"{v*100:.{digits}f}%"


def fnum(v, digits=4):
    if v is None:
        return "—"
    return f"{v:.{digits}f}"


GRADE_LABEL = {
    "robust": "강건(robust)", "moderate": "보통(moderate)", "weak": "약함(weak)",
    "reversed": "반전(reversed)", "unsupported": "근거부족(unsupported)",
}


def grade_badge(grade_raw):
    key = grade_raw.split("(")[0].strip()
    label = GRADE_LABEL.get(key, grade_raw)
    cls = {"robust": "grade-A", "moderate": "grade-B", "weak": "grade-C", "reversed": "grade-C",
           "unsupported": "grade-C"}.get(key, "grade-B")
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
body{ margin:0; background:var(--bg-page); color:var(--ink);
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif; line-height:1.6; font-size:16px; }
.serif{ font-family: "Iowan Old Style","Palatino Linotype", Georgia, serif; }
.mono, .num, td.num, code {
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
  font-size: clamp(28px, 4.2vw, 44px); line-height:1.15; margin: 14px 0 10px; text-wrap: balance; max-width: 34ch; }
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
table.data-table td{ padding:8px 12px; border-bottom:1px solid var(--hairline); text-align:right; }
table.data-table tbody tr:hover{ background:var(--surface-2); }
table.data-table tbody tr:last-child td{ border-bottom:none; }
td.tk-cell{ text-align:left !important; max-width: 360px; white-space:normal; }
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
.confidence-grade{ display:inline-block; font-size:12px; font-weight:700; padding:2px 9px; border-radius:4px; white-space:nowrap;}
.grade-A{ background: var(--accent-soft); color:var(--accent); }
.grade-B{ background: var(--accent-2-soft); color:var(--accent-2); }
.grade-C{ background: rgba(179,38,30,0.10); color:var(--delta-neg); }
"""

# ---------------------------------------------------------------------------
# Section 1 — 검정 총 횟수
# ---------------------------------------------------------------------------
track_rows = "".join(
    f'<tr><td class="tk-cell">{esc(track)}</td><td class="num">{d["subtotal"]}</td></tr>'
    for track, d in TC["headline_by_track"].items()
)

item_rows = ""
for track, d in TC["headline_by_track"].items():
    for item, n in d["items"].items():
        item_rows += f'<tr><td class="tk-cell">[{esc(track.split(" (")[0])}] {esc(item)}</td><td class="num">{n}</td></tr>'

excluded_rows = "".join(
    f'<tr><td class="tk-cell">{esc(k)}</td><td class="num">{v if v is not None else "미상(정량화 불가)"}</td></tr>'
    for k, v in TC["excluded_from_headline_total"].items()
)

granular = TC["granular_scan"]["totals"]

# ---------------------------------------------------------------------------
# Section 2 — 다중비교 보정
# ---------------------------------------------------------------------------
claim_rows = "".join(
    f'<tr><td class="tk-cell"><b>{esc(c["label"])}</b><br><span style="color:var(--ink-muted);font-size:12px">{esc(c["method"])}</span></td>'
    f'<td class="num">{fnum(c["p_or_implied"])}</td>'
    f'<td>{grade_badge(c["program_grade"])}</td></tr>'
    for c in sorted(BFDR["claims"], key=lambda c: c["p_or_implied"])
)

qual_rows = "".join(
    f'<tr><td class="tk-cell"><b>{esc(c["label"])}</b></td><td>{grade_badge(c["program_grade"])}</td>'
    f'<td class="tk-cell" style="text-align:left">{esc(c["why_excluded"])}</td></tr>'
    for c in BFDR["qualitative_only_claims_excluded_from_calc"]
)

bonferroni_rows = ""
for name, res in BFDR["bonferroni_by_family_size"].items():
    bonferroni_rows += (
        f'<tr><td class="tk-cell">{esc(name)}</td>'
        f'<td class="num">{fnum(res["per_test_threshold"], 6)}</td>'
        f'<td class="num">{res["survivor_count"]} / {len(BFDR["claims"])}</td></tr>'
    )

fdr = BFDR["bh_fdr_on_final_layer_pvalues"]
fdr_rows = ""
for i, p in enumerate(fdr["sorted_p"]):
    th = fdr["thresholds"][i]
    passed = p <= th
    cls = "hero-row" if passed else ""
    fdr_rows += (
        f'<tr class="{cls}"><td class="tk-cell">순위 {i+1}</td><td class="num">{fnum(p)}</td>'
        f'<td class="num">{fnum(th, 5)}</td><td class="num">{"PASS" if passed else "fail"}</td></tr>'
    )

# ---------------------------------------------------------------------------
# Section 3 — 일관성 감사
# ---------------------------------------------------------------------------
leakage_rows = "".join(
    f'<tr><td class="tk-cell"><code style="font-size:12px">{esc(f["file"])}</code></td>'
    f'<td class="tk-cell" style="text-align:left">{esc(f["finding"])}</td></tr>'
    for f in CONS["look_ahead_bias_spotcheck"]["files_checked"]
)

HTML = f"""<title>방법론 메타 감사 — 다중비교 보정</title>
<style>
{CSS}
</style>

<div class="masthead">
  <div class="masthead-inner">
    <div class="masthead-eyebrow">
      <span>QUANT RESEARCH NOTE</span><span class="dot">·</span><span>메타 감사</span><span class="dot">·</span><span>Methodology Audit</span>
    </div>
    <h1 class="masthead-title">이 연구 프로그램 전체를 다중비교로 보정하면 무엇이 남는가</h1>
    <p class="masthead-sub">67개 작업·30개 이상의 리서치 라운드에 걸쳐 검정된 가설 수를 처음으로
      실제 집계하고, Bonferroni/Benjamini-Hochberg FDR을 적용해 지금까지 "robust"/"moderate"로
      불려온 결론들이 여전히 유의미한지 재계산한다. 결과가 불리해도 완화하지 않는다 — 그게 이 감사의
      존재 이유다.</p>
    <div class="masthead-meta">
      <span><b>작성</b>: 리서치 에이전트 G (방법론 메타 감사관)</span>
      <span><b>일자</b>: {esc(R["meta"]["generated"])}</span>
      <span><b>범위</b>: PROGRESS.md 작업 1-67 + analysis/ 29개 report_data.json</span>
    </div>
  </div>
</div>

<div class="wrap">
  <div class="toc">
    <a href="#sec1">1. 검정 총 횟수 추정</a>
    <a href="#sec2">2. 다중비교 보정</a>
    <a href="#sec3">3. 등급 일관성 감사</a>
    <a href="#sec4">4. Look-ahead bias 재점검</a>
    <a href="#sec5">5. 메타 결론</a>
  </div>

  <div class="section" id="sec1">
    <h2><span class="sec-no">1</span>검정 총 횟수 추정</h2>
    <p class="lede">work item(작업) 단위가 아니라 실제 검정된 가설/변형 단위로 두 층위에서 집계했다.
      헤드라인 집계는 PROGRESS.md 원문을 직접 읽고 손으로 셌고(재현 가능하도록 <code>count_tests.py</code>에
      출처 주석과 함께 코드로 남겼다), granular 집계는 <code>report_data.json</code> 29개 파일을
      기계적으로 전수 스캔했다.</p>

    <div class="kpi-row">
      <div class="kpi-tile"><div class="kpi-label">헤드라인 가설/라운드 (챔피언 계보)</div>
        <div class="kpi-value">{TC['headline_total']}</div>
        <div class="kpi-sub">Track B+C+D+사후 독립라운드</div></div>
      <div class="kpi-tile"><div class="kpi-label">granular 비교 리프 (report_data.json 전수)</div>
        <div class="kpi-value">{granular['scalar_descriptive_winrate_leaves'] + granular['multiarm_winrate_arms']}</div>
        <div class="kpi-sub">서술적 win_rate + MC/부트스트랩 비교 arm 합계</div></div>
      <div class="kpi-tile"><div class="kpi-label">공식 순열검정 p-value (JSON 저장분)</div>
        <div class="kpi-value">{granular['formal_permutation_p_values']}</div>
        <div class="kpi-sub">텍스트에만 있는 것 별도(총 12개 취합, §2)</div></div>
      <div class="kpi-tile"><div class="kpi-label">별도 트랙(계보 밖, 미포함)</div>
        <div class="kpi-value neg">55+</div>
        <div class="kpi-sub">macro_event_study 단독</div></div>
    </div>

    <h3>트랙별 헤드라인 가설 수</h3>
    <div class="table-wrap"><table class="data-table">
      <thead><tr><th>트랙</th><th>소계</th></tr></thead>
      <tbody>{track_rows}<tr class="hero-row"><td class="tk-cell"><b>합계 (챔피언 전략 계보)</b></td><td class="num"><b>{TC['headline_total']}</b></td></tr></tbody>
    </table></div>

    <h4>세부 내역 (PROGRESS.md 작업 번호 인용)</h4>
    <div class="table-wrap"><table class="data-table">
      <thead><tr><th>가설/라운드</th><th>개수</th></tr></thead>
      <tbody>{item_rows}</tbody>
    </table></div>

    <h4>집계에서 의도적으로 제외한 것</h4>
    <div class="table-wrap"><table class="data-table">
      <thead><tr><th>대상</th><th>추정 규모</th></tr></thead>
      <tbody>{excluded_rows}</tbody>
    </table></div>
    <div class="callout warn">
      <div class="callout-title">숨은 빙산: 야간 종목별 튜닝</div>
      <p><code>core/strategy_tuning.py::_compute_tuning_significance</code>는 종목별로 독립적인
      순열검정을 돌려 개별 α=0.05 기준으로만 판단하고, 같은 그룹 안 다른 종목들·다른 스타일그룹·
      다른 실행일 사이에 어떤 교차 보정도 하지 않는다. 이 저장소의 analysis/ 리서치 라운드보다
      실행 횟수가 훨씬 많을 가능성이 높은(100종목 표본 × 여러 스타일그룹 × 반복 실행) 프로덕션
      경로이지만, 실행 로그가 남아있지 않아 이 감사에서 정량화할 수 없었다 — 다음 감사 라운드의
      숙제로 명시한다.</p>
    </div>
  </div>

  <div class="section" id="sec2">
    <h2><span class="sec-no">2</span>다중비교 보정 — 실제 계산</h2>
    <p class="lede">최종 종합 리포트(<code>research_program_synthesis</code>)의 confidence_table(12) +
      track_c_table(5) = 17개 결론 중, 정량적 유의성 지표(p-value 또는 부트스트랩/몬테카를로 승률을
      1-win_rate로 환산한 값)를 실제로 보유한 12개에 대해 계산했다. 나머지 5개(robust 1 · moderate 2 ·
      unsupported 1 · 이미 형식검정으로 자체기각된 1)는 형식적 검정 자체가 없어 아래에 별도로 다룬다.</p>

    <h3>12개 결론의 p-value(또는 환산 p) 순위</h3>
    <div class="table-wrap"><table class="data-table">
      <thead><tr><th>결론</th><th>p / 환산 p</th><th>프로그램 등급(보정 전)</th></tr></thead>
      <tbody>{claim_rows}</tbody>
    </table></div>

    <h3>Bonferroni 보정 (α=0.05)</h3>
    <p>가설-족(family) 크기를 어떻게 정의하든 결과는 거의 바뀌지 않는다:</p>
    <div class="table-wrap"><table class="data-table">
      <thead><tr><th>가설 족 정의</th><th>개별 검정 임계값 (α/N)</th><th>생존 개수</th></tr></thead>
      <tbody>{bonferroni_rows}</tbody>
    </table></div>
    <div class="callout warn">
      <div class="callout-title">가장 관대한 가정에서도</div>
      <p>가장 관대한 가정(N=9, 모멘텀 랭킹 주장 하나를 낳은 파라미터 탐색 라운드 수만 계산)에서도
      12개 중 <b>단 1개</b>(IREN 단일종목 추세추종, p=0.005)만 살아남는다. 이 프로그램의 실제
      헤드라인 가설 규모(N=80)를 쓰면 <b>생존자는 0개</b>다.</p>
    </div>

    <h3>Benjamini-Hochberg FDR (q=0.05), 12개 최종층위 p값만으로</h3>
    <p>가장 관대하게 "가설 족 = 이 12개뿐"이라고 가정해도(실제로는 최소 80개, macro_event_study까지
      넣으면 135개+) BH-FDR 결과는 다음과 같다:</p>
    <div class="table-wrap"><table class="data-table">
      <thead><tr><th>순위(오름차순 p)</th><th>p</th><th>BH 임계값 (i/n·q)</th><th>결과</th></tr></thead>
      <tbody>{fdr_rows}</tbody>
    </table></div>
    <div class="callout warn">
      <div class="callout-title">FDR 생존자: 0/{fdr['n']}</div>
      <p>가장 작은 p-value(0.0050, 순위1)조차 순위1의 임계값(0.00417)을 넘지 못해 기각(귀무 채택)
      되므로, BH 절차 정의상 그보다 큰 p를 가진 나머지는 자동으로 전부 탈락한다. <b>이 12개짜리
      "가장 너그러운" 부분집합만 놓고 봐도 살아남는 결론이 하나도 없다.</b></p>
    </div>

    <h3>형식적 p-value가 아예 없는 3개 결론</h3>
    <div class="table-wrap"><table class="data-table">
      <thead><tr><th>결론</th><th>등급</th><th>보정 대상에서 제외한 이유</th></tr></thead>
      <tbody>{qual_rows}</tbody>
    </table></div>
  </div>

  <div class="section" id="sec3">
    <h2><span class="sec-no">3</span>등급 일관성 감사</h2>

    <h3>발견된 수치 규칙 (트랙D 후반부에만 존재)</h3>
    <p><code>{esc(CONS['grading_rule_found']['source'])}</code>에서 발견한 유일한 코드화된 규칙:
      win_rate&ge;0.90→robust, &ge;0.70→moderate, &ge;0.50→weak, &lt;0.50→reversed.
      이 규칙은 작업44-47(H22/H25/H26/H26b/H28/H32)에만 적용됐고, 트랙B/트랙C의 '채택/부분채택/기각'
      판정에는 대응하는 수치 기준이 문서화된 적이 없다.</p>

    <h3>이중 잣대: 검정을 안 받은 결론이 검정받고 떨어진 결론보다 등급이 높다</h3>
    <p>{esc(CONS['grading_double_standard']['finding'])}</p>
    <div class="callout">
      <div class="callout-title">구체적 대조</div>
      <p><b>{esc(CONS['grading_double_standard']['concrete_contrast'][0]['claim'])}</b><br>
      vs. <b>{esc(CONS['grading_double_standard']['concrete_contrast'][0]['vs'])}</b></p>
      <p><b>{esc(CONS['grading_double_standard']['concrete_contrast'][1]['claim'])}</b><br>
      vs. <b>{esc(CONS['grading_double_standard']['concrete_contrast'][1]['vs'])}</b></p>
    </div>

    <h3>가설 번호(H-ID) 네임스페이스 충돌</h3>
    <p>{esc(CONS['hypothesis_id_namespace_collision']['finding'])}</p>

    <h3>같은 라운드 안에서 다른 강도의 증거를 하나의 등급으로 묶은 사례</h3>
    <p>{esc(CONS['same_evidence_different_grade_case']['finding'])}</p>
  </div>

  <div class="section" id="sec4">
    <h2><span class="sec-no">4</span>Look-ahead bias / data leakage 재점검</h2>
    <p class="lede">{esc(CONS['look_ahead_bias_spotcheck']['method'])}</p>
    <div class="table-wrap"><table class="data-table">
      <thead><tr><th>파일</th><th>점검 결과</th></tr></thead>
      <tbody>{leakage_rows}</tbody>
    </table></div>
    <div class="callout">
      <div class="callout-title">정직한 긍정 결과</div>
      <p>{esc(CONS['look_ahead_bias_spotcheck']['verdict'])}</p>
      <p><b>한계</b>: {esc(CONS['look_ahead_bias_spotcheck']['caveat'])}</p>
    </div>

    <h3>더 근본적인 문제: 유효 독립 위기표본은 6개뿐</h3>
    <p>{esc(CONS['deeper_finding_effective_independent_regime_count']['finding'])}</p>
    <div class="callout warn">
      <div class="callout-title">Bonferroni/FDR로도 못 고치는 문제</div>
      <p>{esc(CONS['deeper_finding_effective_independent_regime_count']['severity'])}</p>
    </div>
  </div>

  <div class="section" id="sec5">
    <h2><span class="sec-no">5</span>메타 결론</h2>
    <p class="lede">{esc(MC['headline'])}</p>

    <h3>robust 등급(1개)에 대해</h3>
    <p>{esc(MC['on_robust_grade'])}</p>

    <h3>moderate 등급(3개)에 대해</h3>
    <p>{esc(MC['on_moderate_grades'])}</p>

    <div class="callout warn">
      <div class="callout-title">라이브 챔피언 전략에 대한 최종 판단</div>
      <p>{esc(MC['verdict_on_champion_strategy'])}</p>
    </div>
  </div>
</div>

<footer>
  <p>이 리포트는 <code>analysis/2026-09-14_methodology_meta_audit/</code>의
  <code>count_tests.py</code>·<code>bonferroni_fdr_audit.py</code>·
  <code>consistency_and_leakage_audit.json</code>·<code>build_report_data.py</code>로 재현 가능하다.
  git commit/push는 수행하지 않았다 — 사용자 확인 후 반영 여부를 결정할 것.</p>
</footer>
"""

with open(f"{OUT_DIR}/final_report.html", "w", encoding="utf-8") as f:
    f.write(HTML)

print("saved -> final_report.html")
