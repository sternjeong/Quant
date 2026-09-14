#!/usr/bin/env python3
"""report_data.json을 읽어 final_report.html을 만든다. 디자인 시스템은
analysis/2026-09-05_options_hedge_bootstrap_and_combined_system/build_report.py와 동일
(다크네이비/올리브 톤, 세리프 헤드라인, TOC, 섹션 번호, 판정 배지). 이 리포트는 새 백테스트가
아니라 49개 작업 전체(트랙B/C/D, 25개 이상의 개별 리포트)를 종합하는 캡스톤 리포트다 — 모든
숫자는 report_data.json에 이미 하드코딩돼 있으며, 그 숫자들은 각 원본 리포트의 report_data.json/
PROGRESS.md 기록을 직접 대조해 옮긴 것이다."""
import json
import os

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
with open(f"{OUT_DIR}/report_data.json", encoding="utf-8") as f:
    R = json.load(f)

META = R["meta"]
CFG = R["final_config"]
CONF = R["confidence_table"]
TRACKC = R["track_c_table"]

GRADE_LABEL = {"robust": "강건", "moderate": "보통", "weak": "약함", "reversed": "반전/미지지", "unsupported": "미지지"}
GRADE_BADGE_CLASS = {"robust": "accept", "moderate": "accept", "weak": "weak", "reversed": "reject", "unsupported": "reject"}


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def badge(grade):
    return f'<span class="badge {GRADE_BADGE_CLASS[grade]}">{GRADE_LABEL[grade]}</span>'


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
  font-size: clamp(28px, 4.2vw, 44px); line-height:1.15; margin: 14px 0 10px; text-wrap: balance; max-width: 40ch; }
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
.lede{ font-size:16.5px; color:var(--ink-2); max-width:80ch; }
.section p{ max-width:82ch; }
.section > p, .section > .lede { margin-top: 0; }
.section li{ max-width:80ch; }
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
table.data-table th{ text-align:left; font-weight:600; font-size:11.5px; color:var(--ink-muted); text-transform:uppercase;
  letter-spacing:0.03em; padding:10px 12px; border-bottom:1px solid var(--hairline); }
table.data-table th.num, table.data-table td.num{ text-align:right; white-space:nowrap; }
table.data-table td{ padding:10px 12px; border-bottom:1px solid var(--hairline); text-align:left; vertical-align:top; }
table.data-table tbody tr:hover{ background:var(--surface-2); }
table.data-table tbody tr:last-child td{ border-bottom:none; }
td.tk-cell{ text-align:left !important; }
td.tk-cell .tk-name{ font-weight:650; margin-right:8px; }
.strong{ font-weight:700; }
tr.warn-row{ background: rgba(179,38,30,0.08); }
tr.hero-row{ background: rgba(31,77,61,0.08); }
.badge{ display:inline-block; font-size:11.5px; font-weight:700; letter-spacing:0.03em; text-transform:uppercase;
  border-radius:4px; padding:3px 9px; white-space:nowrap; }
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
.profile-grid{ display:grid; grid-template-columns: repeat(auto-fit, minmax(280px,1fr)); gap:16px; margin:20px 0; }
.profile-card{ background:var(--surface); border:1px solid var(--hairline); border-radius:8px; padding:18px 20px; box-shadow:var(--shadow); }
.profile-card h4{ margin:0 0 8px; color:var(--ink); font-size:15.5px; }
.profile-card p{ font-size:14px; color:var(--ink-2); max-width:none; margin:0; }
"""


def conf_rows(rows):
    out = []
    for r in rows:
        out.append(
            f'<tr><td class="tk-cell"><span class="tk-name">{esc(r["component"])}</span></td>'
            f'<td>{badge(r["grade"])}</td>'
            f'<td>{esc(r["note"])}</td>'
            f'<td class="tk-cell" style="color:var(--ink-muted);font-size:12.5px;">{esc(r["source"])}</td></tr>'
        )
    return "".join(out)


CONF_ROWS = conf_rows(CONF)
TRACKC_ROWS = conf_rows(TRACKC)

n_robust = sum(1 for r in CONF if r["grade"] == "robust")
n_weak_or_worse = sum(1 for r in CONF if r["grade"] in ("weak", "reversed", "unsupported"))

HTML = f"""<title>리서치 프로그램 종합 리포트</title>
<style>
{CSS}
</style>

<div class="masthead">
  <div class="masthead-inner">
    <div class="masthead-eyebrow">
      <span>QUANT RESEARCH PROGRAM</span><span class="dot">·</span><span>CAPSTONE SYNTHESIS</span><span class="dot">·</span><span>작업 1~49 종합</span>
    </div>
    <h1 class="masthead-title">이 저장소가 지금까지 찾아낸 것 — 49개 작업, 25개 이상 리포트를 하나의 최종 권고로</h1>
    <p class="masthead-sub">트랙 B(섹터·멀티에셋 로테이션, No.04~10)·트랙 C(개별주 발굴, 텐베거·IREN류·베타/알파)·
      트랙 D(시장을 이기는 방법, 20라운드 가설검증 + 후속 4라운드)에 걸쳐 쌓인 연구를 한 곳에 모았다.
      이 리포트 자체는 새 백테스트를 만들지 않는다 — 모든 숫자는 각 원본 리포트가 이미 계산해 발행한
      값을 다시 옮긴 것이며, 표는 <code>PROGRESS.md</code>의 작업 19~49 기록과 각 리포트의
      <code>report_data.json</code>을 대조해 작성했다.</p>
    <div class="masthead-meta">
      <span><b>기준일</b> {esc(META["generated"])}</span>
      <span><b>대상</b> 작업 1~49, 리포트 26편(트랙A 3 + 트랙B 7 + 트랙C 4 + 트랙D/후속 12)</span>
      <span><b>신뢰도 등급</b> 강건 / 보통 / 약함 / 반전·미지지 (H30/H33~35 통일 스케일)</span>
    </div>
  </div>
</div>

<div class="wrap">

<div class="toc">
  <a href="#s1">1. 최종 권고 시스템</a>
  <a href="#s2">2. 신뢰도 등급표</a>
  <a href="#s3">3. 반복해서 발견된 메타 패턴</a>
  <a href="#s4">4. 실전 사용 가이드</a>
  <a href="#s5">5. 이 프로그램 자체의 한계</a>
  <a href="#s6">6. 더 깊이 읽고 싶다면</a>
</div>

<div class="section" id="s1">
  <h2><span class="sec-no">1</span>최종 권고 시스템</h2>
  <p class="lede">20라운드(트랙D)에 걸친 기댓값 재구성과 5차례의 블록부트스트랩 표본오차 감사 끝에
    수렴한, 지금 시점 이 프로그램의 최선의 답이다. 코어는 <b>강건</b>하지만, 코어를 이루는 거의 모든
    세부 파라미터와 새틀라이트/옵션 오버레이는 방향은 유지하되 확신은 처음 주장했던 것보다 훨씬
    낮게 잡아야 한다 — 2절 신뢰도 등급표를 함께 읽을 것.</p>

  <h3>코어 — 17자산 듀얼 모멘텀 섹터 로테이션</h3>
  <div class="kpi-row">
    <div class="kpi-tile"><div class="kpi-label">유니버스</div><div class="kpi-value" style="font-size:15px;">17자산</div>
      <div class="kpi-sub">GICS 11섹터 + TLT/IEF/GLD + EFA/HYG/DBC</div></div>
    <div class="kpi-tile"><div class="kpi-label">랭킹</div><div class="kpi-value" style="font-size:15px;">12개월 모멘텀</div>
      <div class="kpi-sub">절대모멘텀&gt;0 필터 통과 top4 동일비중</div></div>
    <div class="kpi-tile"><div class="kpi-label">리밸런싱</div><div class="kpi-value" style="font-size:15px;">월간</div>
      <div class="kpi-sub">분기 대안은 정밀검증 결과 사실상 동률(약함)</div></div>
    <div class="kpi-tile"><div class="kpi-label">시장필터</div><div class="kpi-value" style="font-size:15px;">이진 50% 축소</div>
      <div class="kpi-sub">SPY&lt;200일선, 방향 유지·확신 약함</div></div>
  </div>
  <p>{esc(CFG["core"]["vol_targeting"])}. 비용 가정은 {esc(CFG["core"]["cost_model"])}.</p>

  <h3>선택 요소 1 — point-in-time 추세추종 새틀라이트 (15%)</h3>
  <p>{esc(CFG["satellite"]["weight"])}</p>
  <p><b>청산 방식: 정적 반기 보유.</b> {esc(CFG["satellite"]["no_switch_rationale"])} — 이 프로그램이
    시도한 모든 동적 방어(국면조건부 스위치, 실시간 트레일링스탑, VIX 신속신호, 이중속도 하이브리드)는
    "최악의 경우 방어"에는 통했지만 "기저확률 가중 기댓값"에서는 정적보유에 반복적으로 졌다.</p>

  <h3>선택 요소 2 — 새틀라이트 슬리브 대상 합성 칼라 옵션</h3>
  <p>{esc(CFG["options_overlay"]["verdict"])} — 코어 전체가 아니라 새틀라이트 15% 명목가치에만
    적용하는 것이 핵심 조건이다(코어 전체에 적용하면 평시 프리미엄 드래그가 통째로 남는다).</p>

  <div class="callout warn">
    <div class="callout-title">공식 기각된 확장 — 섹터ETF+개별주 전면 혼합</div>
    <p>{esc(CFG["individual_stock_extension_rejected"])}</p>
  </div>

  <div class="callout">
    <div class="callout-title">요약 한 줄</div>
    <p><b>17자산 코어(이진 필터·월간·12개월 모멘텀) + 선택적 15% point-in-time 추세추종 새틀라이트
      (정적 반기보유, 스위치 없음) + 선택적으로 새틀라이트 슬리브에만 칼라 옵션.</b> 개별주 전면 혼합·
      코어 레벨 변동성타겟팅·모든 동적 방어 스위치는 기각. 이 구성 자체가 SPY 매수보유를 이긴다는
      방향성은 20라운드 내내 한 번도 완전히 뒤집히지 않았지만, 그 방향을 이루는 세부 설계 대부분은
      "약함" 등급이다 — 2절 참고.</p>
  </div>
</div>

<div class="section" id="s2">
  <h2><span class="sec-no">2</span>신뢰도 등급표</h2>
  <p class="lede">H30(몬테카를로 기저확률 민감도)·H33~35(블록부트스트랩 표본오차 감사)가 확립한
    통일 스케일을 그대로 쓴다 — <b>강건</b>(결합 승률 90%+ 또는 반복 라운드에 걸쳐 뒤집힌 적 없음),
    <b>보통</b>(70~90%, 방향은 확실하나 여유는 크지 않음), <b>약함</b>(50~70%, 방향은 유지하나
    표본오차 안에서 흔들림), <b>반전/미지지</b>(50% 미만이거나 애초 주장을 뒷받침할 근거가 감사에서
    사라짐). 트랙D 본류 12개 항목 중 {n_weak_or_worse}개가 약함 이하로 재평가됐다는 것 자체가
    이 프로그램의 가장 중요한 메타 발견이다(3절 참고).</p>
  <div class="table-wrap">
    <table class="data-table">
      <thead><tr><th>구성요소</th><th>등급</th><th>근거</th><th>출처</th></tr></thead>
      <tbody>{CONF_ROWS}</tbody>
    </table>
  </div>

  <h3>트랙 C — 개별주 발굴 (별도, 트랙 B/D와 통합되지 않은 독립 트랙)</h3>
  <p>트랙 C는 하향식 섹터 로테이션이 아니라 상향식 개별종목/바스켓 매매를 다루는 완전히 별도
    갈래다. 트랙B/D의 코어-새틀라이트 시스템에 편입된 적이 없고, 신뢰도 감사 방법론(H33 계열)이
    나중에 트랙C 자체에도 적용됐을 뿐이다.</p>
  <div class="table-wrap">
    <table class="data-table">
      <thead><tr><th>구성요소</th><th>등급</th><th>근거</th><th>출처</th></tr></thead>
      <tbody>{TRACKC_ROWS}</tbody>
    </table>
  </div>
</div>

<div class="section" id="s3">
  <h2><span class="sec-no">3</span>이 프로그램이 반복해서 발견한 메타 패턴</h2>

  <h3>3.1 — 정적 방어 메커니즘은 최악의 경우엔 이기고 기댓값에선 진다</h3>
  <p>새틀라이트 스위치(H12/H13), 실시간 트레일링스탑(H16/H17), VIX 신속신호+하이브리드(H20/H21),
    코어 시장필터(H25), 코어 변동성타겟팅(H28) — 다섯 개의 서로 다른 메커니즘이 전부 같은 모양의
    결과를 냈다: MDD·위기구간 성과는 개선하지만, 6개 창(전체기간+2008/2022/COVID/2018/2015-16)을
    역사적 발생빈도로 가중한 기댓값 샤프에서는 정적보유·무필터·오버레이없음에 진다. 자주 오는
    평상시에 조금씩 잃는 비용이, 드물게 오는 위기에 크게 버는 이득보다 누적으로 더 크기 때문이다.</p>

  <h3>3.2 — 빠르고 격렬한 크래시는 추세추종 방어신호를 구조적으로 이긴다</h3>
  <p>SPY 200일선, VIX 급등, 돈치안 트레일링스탑 — 전부 "이미 벌어지고 있는 움직임을 감지"해야
    작동하는 신호다. COVID처럼 몇 주 만에 끝나는 수직급락에서는 감지 자체가 늦어 방어에 실패한다
    (SPY 스위치는 낙폭의 36.5% 시점에야 반응, 새틀라이트 자체 신호는 훨씬 느림). 2008 GFC처럼
    완만하고 장기적인 위기에서는 같은 신호들이 잘 작동한다 — "위기 방어"는 뭉뚱그릴 개념이 아니라
    위기의 속도에 따라 갈리는 조건부 명제다. 옵션(칼라)은 사전에 페이오프가 확정돼 감지가 필요 없어
    이 구조적 약점을 유일하게 피해가지만, 대신 상시 프리미엄 비용을 진다.</p>

  <h3>3.3 — 가중치만 반영한 신뢰도는 체계적으로 과신을 부른다</h3>
  <p>H30(디리클레 기저확률 몬테카를로)만으로는 대부분의 "채택" 판정이 90%를 훌쩍 넘었다. 그러나
    H33~35가 각 창의 실제 표본 길이를 반영한 블록부트스트랩 표본오차를 결합하자, 6개 주요 판정
    (H22/H25/H26/H26b/H28/H32) 중 방향이 살아남은 것도 전부 50~60%대 "약함"으로 재등급됐다 —
    특히 COVID처럼 51거래일뿐인 짧은 창은 신뢰구간이 사실상 무정보에 가까웠다. 방향이 뒤집힌
    경우는 드물었지만("역전"이 아니라 "확신의 과장" 문제), 단일 창의 극적인 숫자를 그대로 믿으면
    안 된다는 교훈은 트랙D 전체와 트랙C 감사, 그리고 옵션헤지 감사(작업49)까지 예외 없이 반복됐다.</p>

  <h3>3.4 — 순차(그리디) 튜닝은 진짜 최적과 격차가 있지만, 그 격차가 극적이진 않다</h3>
  <p>룩백기간과 리밸런싱주기를 각각 따로 최적화한 뒤(12개월/월간) 뒤늦게 결합 그리드서치를 돌려보니
    (H31/H32) 진짜 결합 최적점은 (14~16개월, 분기)이었다 — 순차 선택은 20~40칸 그리드에서 5~20위권에
    그쳤다. 다만 기대샤프 격차는 +0.10 안팎으로, 이 시리즈가 다른 곳에서 "근소하다"고 부른 크기와
    비슷했고, 그리드 자체도 완만한 고원 형태였다 — "순차 튜닝이 크게 틀리진 않았지만 정확한 최적도
    아니었다"는 균형 잡힌 결론이다.</p>

  <h3>3.5 — 정적 사전필터는 반복적으로 착시, 동적 랭킹/타이밍은 반복적으로 진짜 가치</h3>
  <p>퀄리티 하드필터(H4)는 무작위 26종목 구성 200개와 비교하니 58.5백분위로 무작위와 구별 안 됐다
    (H8, 착시 확정). 베타 헤지(H1/H2/H4, 트랙C와 트랙D 챔피언 양쪽 모두)도 전부 손해였다. 반대로
    챔피언의 모멘텀 로테이션 자체(순열검정 97.5백분위)와 새틀라이트의 동적 선정 로직(모멘텀→
    추세추종 업그레이드로 88→93백분위 개선)은 확신 등급은 낮아도(약함~보통) 방향은 꾸준히 살아남았다.
    "필터로 후보를 미리 좁히는 것"과 "랭킹으로 매번 다시 계산하는 것"은 비슷해 보여도 이 프로그램
    에서는 반복적으로 다른 운명을 맞았다.</p>

  <h3>3.6 — "전면 통합"과 "작게 얹기"는 같은 재료로도 다른 결론을 낸다</h3>
  <p>개별주를 섹터ETF와 통째로 섞은 35종목 유니버스(No.09/10)는 point-in-time 검증 후 명백히
    기각됐지만, 같은 point-in-time 규율을 지키며 코어의 15%만 새틀라이트로 소량 얹는 것(H1, 작업30)은
    조건부로 채택됐다. 트랙C의 개별종목 발굴 방법론 자체는 독립적으로 유효할 수 있어도, "그것을
    포트폴리오에 얼마나 어떻게 섞는가"가 성패를 갈랐다 — 이 패턴은 옵션헤지에서도 재현됐다
    (슬리브 단독 비교에서는 약한 우위, 15%로 희석한 통합 시스템에서는 3개 시나리오 전부 우위).</p>
</div>

<div class="section" id="s4">
  <h2><span class="sec-no">4</span>실전 사용 가이드 — 투자자 프로필별</h2>
  <div class="profile-grid">
    <div class="profile-card">
      <h4>순수 기댓값·장기성장 우선</h4>
      <p>17자산 코어(이진 필터·12개월·월간) 단독, 또는 여기에 15% 정적보유 추세추종 새틀라이트를
        더한다. 스위치·실시간 스탑·옵션 헤지는 전부 뺀다 — 20라운드 기댓값 재구성이 일관되게 이
        조합을 1위로 꼽았다. 다만 룩백·리밸런싱 주기를 정확히 12개월/월간으로 고집할 필요는 없다
        (9개월·6주도 통계적으로 구별 안 됨) — 소수점 하나에 집착하지 말 것.</p>
    </div>
    <div class="profile-card">
      <h4>꼬리위험(테일 리스크)을 명시적으로 우선</h4>
      <p>코어+15% 새틀라이트에 (a) 10% 폭 실시간 트레일링스탑 청산(H19 파레토 효율, 구 15% 기본값을
        두 축 모두에서 앞섬)과 SPY 200일선 스위치를 함께 걸거나, (b) 새틀라이트 슬리브에 합성 칼라
        옵션을 얹는다. 단, 두 경우 모두 "2008형 완만한 위기에는 검증됐지만 COVID형 수직급락은
        추세신호로 못 막는다"는 것을 받아들여야 한다 — 진짜 감지불필요 방어는 옵션뿐이고, 옵션은
        상시 프리미엄 비용(연 CAGR 약 2%p 안팎 하락)이 든다.</p>
    </div>
    <div class="profile-card">
      <h4>IREN류 개별 변동성 테마주에 관심</h4>
      <p>트랙C는 트랙B/D와 통합되지 않은 독립 갈래다 — 섹터 로테이션 코어에 이 바스켓을 섞지 말 것
        (구조적으로 폭(breadth)이 부족해 로테이션이 성립 안 함). 대신 별도 자본배분으로 6~9종목
        바스켓에 20일 돈치안 브레이크아웃+15% 트레일링스탑을 규율 있게 적용하는 편이 정적 매수보유
        보다 낫다(샤프 1.31 vs 0.88~0.94). 다만 부트스트랩 감사 결과 이 우위의 신뢰구간 폭이 IREN
        단일종목과 거의 같아 확신 등급은 낮다(약함) — 베타 헤지·저베타 틸트 같은 헤지 시도는 전부
        기각됐으므로 "헤지로 안전하게"가 아니라 "사이징·청산 규율로 안전하게"가 핵심이다.</p>
    </div>
  </div>
</div>

<div class="section" id="s5">
  <h2><span class="sec-no">5</span>이 연구 프로그램 자체의 한계</h2>
  <ul>
    <li><b>역사 표본 자체가 좁다.</b> 전체 백테스트 우주는 대략 2000~2026년(챔피언 17자산은 2019년,
      3자산 프록시 확장판만 2000/2007년까지) — 이 기간에 실제로 포함된 위기 유형(2008 GFC, 닷컴버블,
      2018/2022 조정, COVID)의 "다음에도 비슷하게 반복될 것"이라는 전제 위에 모든 기댓값 계산이
      서 있다. H30/H33이 이 전제의 불확실성 일부(빈도 추정·표본오차)는 정량화했지만, 역사에 없던
      완전히 새로운 유형의 위기(예: 구조적 인플레이션 충격, AI발 생산성 충격)는 어떤 시나리오
      가중치로도 포착할 수 없다.</li>
    <li><b>거래비용 가정이 단순하다.</b> 전 프로그램에 걸쳐 왕복 0.1% 고정 비용만 반영 — 슬리피지,
      시장충격, 스프레드 확대(위기 구간일수록 커짐), 옵션 매수-매도 호가 스프레드는 반영하지 않았다.
      특히 위기 구간 성과 비교는 이 단순화 때문에 실제보다 낙관적일 수 있다.</li>
    <li><b>트랙C 바스켓은 작고 짧다.</b> IREN류 6~9종목, 공통 백테스트 구간이 4.25년(2022-05~
      2026-08)뿐이며 전 구간이 BTC·AI 인프라 동시 초강세장이었다 — 이 구간 밖에서 같은 결론이
      유지될지는 검증되지 않았다.</li>
    <li><b>다중비교/데이터 스누핑 위험이 완전히 제거되지 않았다.</b> 49개 작업에 걸쳐 수백 개의
      파라미터 조합·가설을 같은 핵심 표본(대체로 2019~2026)에 반복 검증했다 — 순열검정과 부트스트랩은
      "무작위 대비 우위"와 "표본오차"는 각각 확인했지만, "이 정확한 설계를 반복 검증 과정에서 고른
      행위 자체"의 과최적화까지 완전히 제거하진 못한다.</li>
    <li><b>본 캡스톤 리포트는 새 계산을 하지 않았다.</b> 여기 실린 모든 숫자는 원본 리포트의 발행
      값을 옮긴 것이며, 재계산·재검증은 각주에 인용된 원본 리포트 쪽에서 이뤄졌다 — 종합 과정에서
      숫자 옮김 오류가 없도록 report_data.json 원문과 대조했지만, 최종 확인은 항상 원본 리포트를
      기준으로 할 것.</li>
    <li>이 리포트를 포함해 이 저장소의 모든 내용은 투자 자문이 아니다.</li>
  </ul>
</div>

<div class="section" id="s6">
  <h2><span class="sec-no">6</span>더 깊이 읽고 싶다면 — 읽는 순서</h2>
  <p>전부 <code>docs/reports/README.md</code>에 목록과 요약이 있다. 결론만 빠르게 확인하려면:</p>
  <ol>
    <li><b>코어 챔피언의 진화</b>: No.05 → No.06 → No.07(2008 GFC 검증) → No.08(닷컴/2022 스트레스)
      → No.09/10(개별주 확장, 기각).</li>
    <li><b>기댓값 재구성 전체 흐름(트랙D 핵심)</b>: <code>expected_value_reframing_and_continuous_exposure_research.html</code>
      (H22, 정적보유가 스위치를 이긴다는 최초 발견) → <code>system_vs_buyhold_and_lookback_robustness_research.html</code>
      (H26/H27) → <code>vol_targeting_and_rebalance_frequency_expected_value_research.html</code>(H28/H29)
      → <code>base_rate_monte_carlo_sensitivity_research.html</code>(H30, 신뢰도 등급 최초 도입)
      → <code>joint_parameter_interaction_grid_search_research.html</code>(H31) →
      <code>champion_parameter_fine_resolution_and_satellite_joint_research.html</code>(H32) →
      <code>block_bootstrap_sample_error_quantification_research.html</code>(H33, 표본오차 감사 방법론) →
      <code>bootstrap_confidence_audit_remaining_verdicts_research.html</code>(H34) →
      <code>satellite_weight_and_core_filter_expected_value_research.html</code>(H24/H25) →
      <code>core_filter_bootstrap_and_satellite_weight_extension_research.html</code>(H35/H36, 트랙D 최종).</li>
    <li><b>새틀라이트 방어 메커니즘의 전체 계보</b>: <code>regime_conditional_satellite_switch_research.html</code>
      (H12/H13) → <code>satellite_specific_crisis_signal_research.html</code>(H14/H15) →
      <code>satellite_realtime_stop_and_reentry_research.html</code>(H16/H17) →
      <code>crisis_sample_expansion_and_risk_frontier_research.html</code>(H18/H19) →
      <code>vix_fast_crash_signal_and_hybrid_switch_research.html</code>(H20/H21).</li>
    <li><b>가장 최근 독립 후속 3편</b>: <code>risk_adjusted_momentum_ranking_research.html</code>(기각),
      <code>synthetic_options_tail_hedge_research.html</code> → <code>options_hedge_bootstrap_and_combined_system_research.html</code>
      (옵션헤지, 약하게 채택).</li>
    <li><b>트랙C 전체</b>: <code>tenbagger_stock_picking_research.html</code> →
      <code>iren_volatile_momentum_stocks_research.html</code> →
      <code>iren_beta_alpha_hedging_research.html</code> →
      <code>track_c_bootstrap_confidence_audit_research.html</code>.</li>
  </ol>
</div>

</div>
<footer>
  <p>산출물: analysis/2026-09-05_research_program_synthesis/ (report_data.json, build_report.py,
    final_report.html). 이 리포트는 PROGRESS.md 작업 1~49와 docs/reports/의 26개 리포트를 종합한
    캡스톤 문서이며, 신규 백테스트를 수행하지 않았다 — 모든 수치는 원본 리포트에서 옮겨 온 것이다.
    core/, app/는 수정하지 않음.</p>
</footer>
"""

with open(f"{OUT_DIR}/final_report.html", "w", encoding="utf-8") as f:
    f.write(HTML)
print("wrote final_report.html", len(HTML))
