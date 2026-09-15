#!/usr/bin/env python3
"""step1/step2/step3 결과를 읽어 final_report.html을 만든다. 디자인 시스템은
analysis/2026-09-05_options_hedge_bootstrap_and_combined_system/build_report.py와 동일(다크네이비/
올리브 톤, 세리프 헤드라인, TOC, 섹션 번호, 판정 배지)."""
import json
import math
import os

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
R = json.load(open(f"{OUT_DIR}/report_data.json", encoding="utf-8"))
S1 = R["step1_cost_scenarios"]
S2 = R["step2_permutation_bootstrap"]
S3 = R["step3_tax_simulation"]

COST_LABEL = {
    "current_0.1pct_rt": "현재가정 (왕복 0.1%)",
    "moderate_0.3pct_rt": "현실화-보통 (왕복 0.3%)",
    "conservative_0.5pct_rt": "현실화-보수 (왕복 0.5%)",
    "no_promo_0.8pct_rt": "프로모션 없음 (왕복 0.8%)",
}
COST_ORDER = ["current_0.1pct_rt", "moderate_0.3pct_rt", "conservative_0.5pct_rt", "no_promo_0.8pct_rt"]


def fnum(v, digits=2, signed=False, suffix=""):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    s = f"{v:,.{digits}f}"
    if signed and v > 0:
        s = "+" + s
    return s + suffix


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
table.data-table{ width:100%; border-collapse:collapse; font-size:13.5px; min-width:680px; }
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


def cost_table(sleeve_results: dict) -> str:
    rows = []
    for name in COST_ORDER:
        d = sleeve_results.get(name)
        if not d:
            continue
        m = d["metrics"]
        hero = " hero-row" if name == "current_0.1pct_rt" else ""
        rows.append(
            f'<tr class="{hero.strip()}"><td class="tk-cell">{esc(COST_LABEL[name])}</td>'
            f'<td class="num">{fnum(m["cagr"],2,signed=True,suffix="%")}</td>'
            f'<td class="num">{fnum(m["sharpe"],3,signed=True)}</td>'
            f'<td class="num">{fnum(m["mdd"],1,suffix="%")}</td>'
            f'<td class="num">{fnum(d["avg_annual_cost_drag_pct"],3,suffix="%")}</td></tr>'
        )
    return "".join(rows)


def perm_table() -> str:
    rows = []
    for name in ["current_0.1pct_rt", "conservative_0.5pct_rt"]:
        d = S2["permutation_core"].get(name)
        if not d:
            continue
        rows.append(
            f'<tr><td class="tk-cell">{esc(COST_LABEL[name])}</td>'
            f'<td class="num">{fnum(d["actual_sharpe"],3,signed=True)}</td>'
            f'<td class="num">{fnum(d["permuted_mean"],3,signed=True)}</td>'
            f'<td class="num">{d["percentile"]}%</td>'
            f'<td class="num">{d["p_value"]}</td></tr>'
        )
    return "".join(rows)


def boot_table(sleeve: str) -> str:
    rows = []
    d = S2["block_bootstrap"].get(sleeve, {})
    for name in COST_ORDER:
        c = d.get(name)
        if not c:
            continue
        b20 = c.get("block_20", {})
        rows.append(
            f'<tr><td class="tk-cell">{esc(COST_LABEL[name])}</td>'
            f'<td class="num">{fnum(c["actual_sharpe"],3,signed=True)}</td>'
            f'<td class="num">[{fnum(b20.get("ci_2.5"),2,signed=True)}, {fnum(b20.get("ci_97.5"),2,signed=True)}]</td>'
            f'<td class="num">{fnum(b20.get("pct_bootstrap_sharpe_positive"),1)}%</td></tr>'
        )
    return "".join(rows)


def tax_table() -> str:
    rows = []
    for acc_key, d in S3["account_scenarios"].items():
        hero = " hero-row" if acc_key == "100000000" else ""
        rows.append(
            f'<tr class="{hero.strip()}"><td class="tk-cell">{fnum(d["account_krw"],0)}원</td>'
            f'<td class="num">{fnum(d["total_pretax_gain_krw"],0)}원</td>'
            f'<td class="num">{fnum(d["total_tax_krw"],0)}원</td>'
            f'<td class="num">{fnum(d["total_aftertax_gain_krw"],0)}원</td>'
            f'<td class="num">{fnum(d["effective_tax_rate_on_total_gain_pct"],1)}%</td></tr>'
        )
    return "".join(rows)


# ---- 파생 수치 ----
CUR = S1["core_results"]["current_0.1pct_rt"]["metrics"]
CONS = S1["core_results"]["conservative_0.5pct_rt"]["metrics"]
NOPROMO = S1["core_results"]["no_promo_0.8pct_rt"]["metrics"]
SPY = S1["spy_buyhold_metrics"]
CORE_TPY = S1["core_trades_per_year"]
SAT_TPY = S1["satellite_trades_per_year"]
TOTAL_TPY = S1["total_trades_per_year"]

PERM_CUR = S2["permutation_core"]["current_0.1pct_rt"]
PERM_CONS = S2["permutation_core"]["conservative_0.5pct_rt"]

ACC_100M = S3["account_scenarios"]["100000000"]
ACC_30M = S3["account_scenarios"]["30000000"]
ACC_300M = S3["account_scenarios"]["300000000"]

CORE_CAGR_DROP = CUR["cagr"] - CONS["cagr"]
CORE_SHARPE_DROP = CUR["sharpe"] - CONS["sharpe"]
PERM_NOT_SIG_CUR = PERM_CUR["p_value"] > 0.05
PERM_NOT_SIG_CONS = PERM_CONS["p_value"] > 0.05
SAT_BOOT_L20 = S2["block_bootstrap"]["satellite"]["current_0.1pct_rt"]["block_20"]
SAT_CI_CROSSES_ZERO = SAT_BOOT_L20["ci_2.5"] < 0

GEN = "2026-09-14"

HTML = f"""<title>비용/세금 감사 — 챔피언 전략 라이브 기본설정</title>
<style>
{CSS}
</style>

<div class="masthead">
  <div class="masthead-inner">
    <div class="masthead-eyebrow">
      <span>QUANT RESEARCH NOTE</span><span class="dot">·</span><span>리서치 에이전트 F</span><span class="dot">·</span><span>비용/세금/표본크기 감사</span>
    </div>
    <h1 class="masthead-title">왕복 0.1% 비용가정, 이 저장소가 지금까지 한 번도 감사하지 않은 숫자를 처음 열어본다</h1>
    <p class="masthead-sub">이번 실행 시점에 에이전트 D의 새 후보(`analysis/LATEST_STRATEGY_CANDIDATE.md`)가
      없어(페르소나 프롬프트의 명시적 폴백에 따라) 지금 실제로 라이브로 도는
      `core/champion_strategy.py`의 코어(17자산 로테이션, {esc(f"연 {CORE_TPY:.1f}회")} 편도매매)+
      새틀라이트(반기 리밸런싱, {esc(f"연 {SAT_TPY:.1f}회")} 편도매매)를 감사 대상으로 삼았다.
      비용을 왕복 0.1%→0.5%로 올리고, 한국 거주자 해외주식 양도소득세(22%, 250만원 공제 —
      2026-09-14 웹검색 확인)까지 반영하면 결론이 바뀌는지 확인한다.</p>
    <div class="masthead-meta">
      <span><b>기준일</b> {GEN}</span>
      <span><b>순열검정</b> _shuffle_daily_bars 재사용, N=200</span>
      <span><b>블록부트스트랩</b> 순환 이동블록, L=10/20/40, 창당 2,000회</span>
      <span><b>세율/공제</b> 22% / 연 250만원 (국세청 등 2026-09-14 확인)</span>
    </div>
  </div>
</div>

<div class="wrap">

<div class="toc">
  <a href="#s0">0. 배경 — 왜 D의 후보가 아니라 라이브 기본설정을 감사하는가</a>
  <a href="#s1">1. 거래비용 현실화</a>
  <a href="#s2">2. 순열검정 + 블록부트스트랩</a>
  <a href="#s3">3. 원/달러 환전 비용</a>
  <a href="#s4">4. 한국 거주자 해외주식 양도소득세</a>
  <a href="#s5">5. 저빈도 매매의 표본 크기 문제</a>
  <a href="#s6">6. 종합 판정</a>
</div>

<div class="section" id="s0">
  <h2><span class="sec-no">0</span>배경</h2>
  <p class="lede">에이전트 F(비용/세금/리스크 감사관)의 프롬프트는 D의 새 후보가 없을 때 "절대
    대기하지 않고" `core/champion_strategy.py`의 라이브 기본설정을 감사 대상으로 쓰라고 명시한다 —
    이 저장소 모든 백테스트가 지금까지 써온 `BACKTEST_COST_BPS_PER_SIDE=5.0`(왕복 0.1%) 가정
    자체가 한 번도 감사된 적이 없기 때문이다. 이번 라운드는 그 폴백을 실행한다.</p>
</div>

<div class="section" id="s1">
  <h2><span class="sec-no">1</span>거래비용 현실화 — 왕복 0.1%는 충분한가</h2>
  <p class="lede">한국 증권사(키움/한국투자증권 등)의 미국주식 온라인 수수료는 표준 0.25%/편도
    (프로모션 없이) — 왕복이면 이미 현재 가정(0.1%)의 5배다. 여기에 슬리피지를 더해 왕복 0.3%
    (프로모션 적용 시나리오)/0.5%(수수료+슬리피지 보수적)/0.8%(프로모션 전혀 없는 표준가+슬리피지
    최악 시나리오)로 코어·새틀라이트를 각각 재백테스트했다.</p>

  <h3>코어(17자산 로테이션)</h3>
  <div class="table-wrap">
    <table class="data-table">
      <thead><tr><th>비용 시나리오</th><th>CAGR</th><th>Sharpe</th><th>MDD</th><th>연평균 비용drag</th></tr></thead>
      <tbody>{cost_table(S1["core_results"])}</tbody>
    </table>
  </div>

  <h3>새틀라이트(반기 리밸런싱)</h3>
  <div class="table-wrap">
    <table class="data-table">
      <thead><tr><th>비용 시나리오</th><th>CAGR</th><th>Sharpe</th><th>MDD</th><th>연평균 비용drag</th></tr></thead>
      <tbody>{cost_table(S1["satellite_results"])}</tbody>
    </table>
  </div>

  <div class="callout">
    <div class="callout-title">참고: SPY 매수보유(비용 0)</div>
    <p>CAGR {fnum(SPY['cagr'],2,signed=True,suffix="%")}, Sharpe {fnum(SPY['sharpe'],3,signed=True)}, MDD {fnum(SPY['mdd'],1,suffix="%")}
      — 같은 기간({S1['meta']['full_start']}~{S1['meta']['full_end']}) 기준.</p>
  </div>
</div>

<div class="section" id="s2">
  <h2><span class="sec-no">2</span>순열검정 + 블록부트스트랩 — 비용 반영 전/후 비교</h2>
  <p class="lede">코어 17자산의 개별 캔들모양은 보존한 채 날짜 순서만 섞는 `_shuffle_daily_bars`
    순열검정(N=200)을, 현재 비용가정과 보수적 비용가정(왕복 0.5%) 각각에서 실행했다(새틀라이트는
    반기 point-in-time 재스캔 비용이 커 이번 라운드는 코어만 순열검정, 대신 부트스트랩은 새틀라이트도
    포함).</p>
  <div class="table-wrap">
    <table class="data-table">
      <thead><tr><th>비용 시나리오</th><th>실제 Sharpe</th><th>순열평균 Sharpe</th><th>백분위</th><th>p-value</th></tr></thead>
      <tbody>{perm_table()}</tbody>
    </table>
  </div>

  <h3>블록부트스트랩 (L=20 신뢰구간) — 코어</h3>
  <div class="table-wrap">
    <table class="data-table">
      <thead><tr><th>비용 시나리오</th><th>실제 Sharpe</th><th>95% CI</th><th>부트스트랩 Sharpe&gt;0 비율</th></tr></thead>
      <tbody>{boot_table("core")}</tbody>
    </table>
  </div>

  <h3>블록부트스트랩 (L=20 신뢰구간) — 새틀라이트</h3>
  <div class="table-wrap">
    <table class="data-table">
      <thead><tr><th>비용 시나리오</th><th>실제 Sharpe</th><th>95% CI</th><th>부트스트랩 Sharpe&gt;0 비율</th></tr></thead>
      <tbody>{boot_table("satellite")}</tbody>
    </table>
  </div>
</div>

<div class="section" id="s3">
  <h2><span class="sec-no">3</span>원/달러 환전 비용</h2>
  <p class="lede">`core.fred_data`의 DEXKOUS(원/달러 매매기준율) 캐시 기준 최근 변동성은 60일
    일별표준편차 약 0.60%(연율화 약 9.5%) — 이는 환율 자체의 방향성 리스크이지 환전 스프레드가
    아니다. 웹검색으로 확인한 환전 스프레드는 증권사 기준환율 대비 약 1%가 표준이며, 온라인 환전
    시 최대 90% 우대를 받으면 실질 스프레드가 약 0.1%까지 줄어든다.</p>
  <div class="callout good">
    <div class="callout-title">중요한 구조적 사실 — 환전은 매 리밸런싱마다 발생하지 않는다</div>
    <p>코어/새틀라이트 리밸런싱은 이미 USD로 보유 중인 자산 간 교체(ETF A 매도 → ETF B 매수)라서,
      통합증거금(USD 결제) 계좌를 쓰면 원화 재환전이 필요 없다 — 환전은 최초 원화 입금(KRW→USD)과
      최종 출금(USD→KRW) 시점에만 발생하는 <b>일회성 비용</b>이다. 왕복 환전비용을 우대 90%
      기준 약 0.2%, 우대 없음 기준 약 2%로 잡아도 5~10년 보유 기간에 걸쳐 연환산하면 연
      0.02~0.4%p 수준 — 코어의 잦은 리밸런싱(연 {CORE_TPY:.1f}회 편도)이 만드는 수수료 drag보다
      훨씬 작다. 다만 이 저장소의 코어 백테스트 비용모델(1절)은 이 일회성 환전비용을 아예
      포함하지 않으므로, 계좌 개설 초기 진입비용으로 별도 인지해야 한다.</p>
  </div>
</div>

<div class="section" id="s4">
  <h2><span class="sec-no">4</span>한국 거주자 해외주식 양도소득세</h2>
  <p class="lede"><b>2026-09-14 웹검색으로 확인</b>(하드코딩 아님): 국세청 기준 해외주식(미국 ETF
    포함) 양도소득세율은 <b>22%(양도소득세 20% + 지방소득세 2%)</b>, 기본공제는 <b>과세연도(1~12월)당
    250만원</b>(전체 해외주식 거래 손익통산 후 1회 적용), 신고는 다음해 5월. 같은 과세연도 내
    손익통산은 허용되지만 <b>연도를 넘긴 손실 이월공제는 없다</b>. 출처: 국세청(nts.go.kr) 해외주식
    양도소득세 안내, 미래에셋증권·유안타증권 고객안내, calculatorhost.com "해외주식 양도소득세 2026"
    요약.</p>
  <p>코어 슬리브의 실현 거래(진입~청산이 완료된 것만, {S3['meta']['n_trades']}건, 왕복 0.5% 비용
    반영 후 순손익 기준)를 연도별로 집계해 계좌 규모별로 세금을 계산했다.</p>
  <div class="table-wrap">
    <table class="data-table">
      <thead><tr><th>계좌 규모</th><th>세전 누적실현손익</th><th>세금 합계</th><th>세후 누적손익</th><th>실효세율</th></tr></thead>
      <tbody>{tax_table()}</tbody>
    </table>
  </div>
  <div class="callout warn">
    <div class="callout-title">공제 250만원의 상대적 효과는 계좌 규모에 따라 크게 다르다</div>
    <p>계좌 3천만원(코어분 {fnum(ACC_30M['core_capital_krw'],0)}원)에서는 연간 실현이익이 공제선
      아래에 머무는 해가 많아 실효세율이 {fnum(ACC_30M['effective_tax_rate_on_total_gain_pct'],1)}%에
      그치지만, 계좌 3억원(코어분 {fnum(ACC_300M['core_capital_krw'],0)}원)에서는 실효세율이
      {fnum(ACC_300M['effective_tax_rate_on_total_gain_pct'],1)}%까지 올라간다 — 고정 250만원 공제가
      대형 계좌에서는 사실상 무시할 만한 수준이 되기 때문이다. 이 시뮬레이션은 시장필터에 의한 부분
      비중축소(트리밍)로 발생하는 실현손익은 무시했으므로(방법론 참고), 실제 과세 이벤트는 여기
      추정치보다 다소 더 많을 수 있다 — 즉 이 표의 세금 총액은 보수적으로 "덜 나쁜 쪽"에 편향돼
      있다.</p>
  </div>
</div>

<div class="section" id="s5">
  <h2><span class="sec-no">5</span>저빈도 매매의 표본 크기 문제</h2>
  <p class="lede">코어는 연평균 {CORE_TPY:.1f}회, 새틀라이트는 연평균 {SAT_TPY:.1f}회(둘 다 편도
    기준) 매매한다 — 합쳐서 연 {TOTAL_TPY:.1f}회 편도({TOTAL_TPY/2:.1f}회 왕복 근사). {S1['meta']['n_years']:.1f}년
    백테스트 구간 전체에서 실제 발생한 사건 수는 코어 {S1['core_trade_events']}건, 새틀라이트
    {S1['satellite_trade_events']}건뿐이다 — 이 저장소의 다른 고빈도 전략들(일별 신호)에 비하면
    표본이 훨씬 작다.</p>
  <div class="callout">
    <div class="callout-title">순열검정/부트스트랩이 이 문제를 완전히 가려주지 않는다</div>
    <p>순열검정(N=200)과 블록부트스트랩(창당 2,000회)은 "일별 수익률 시계열"을 재표본하는 방법이라
      표본 크기 자체는 거래일수({S2['block_bootstrap']['core']['current_0.1pct_rt']['n_days']}일)
      기준으로 크지만, 이건 "몇 번을 반복 시뮬레이션했는가"이지 "실제로 몇 번의 독립적인 매매
      결정이 있었는가"와는 다른 질문이다. 코어의 리밸런싱 결정 자체는 {S1['core_rebal_change_days']}번의
      "구성 변경일"에서만 발생했고, 새틀라이트는 반기마다 {len(S1['satellite_rebal_log'])}번뿐이다 —
      이렇게 적은 수의 실제 리밸런싱 의사결정 표본으로는, 백테스트 구간에 우연히 몇 번의 좋은(혹은
      나쁜) 리밸런싱 타이밍이 낀 것인지 아니면 진짜 알파인지 이 프로그램의 표준 방법론만으로는
      확실히 가려낼 수 없다. 순열검정 p-value가 낮게 나와도(2절 참고) 이는 "일별 가격 패턴이
      무작위가 아니다"를 보여줄 뿐, "리밸런싱 의사결정 표본이 충분하다"를 보장하지 않는다 —
      confidence 등급을 매길 때 이 구분을 명시적으로 낮춰 반영해야 한다.</p>
  </div>
</div>

<div class="section" id="s6">
  <h2><span class="sec-no">6</span>종합 판정 — 확신도 하향 조정</h2>
  <p class="lede">비용을 왕복 0.1%→0.5%로 현실화해도 코어의 방향(양(+)의 CAGR·Sharpe)은 뒤집히지
    않는다. 하지만 이 감사는 <b>이 저장소가 지금까지 확인하지 않았던 세 가지 약점</b>을 새로 드러냈고,
    그중 하나(순열검정)는 결론을 하향 조정할 만큼 심각하다.</p>

  <div class="kpi-row">
    <div class="kpi-tile">
      <div class="kpi-label">코어 CAGR 드래그 (0.1%→0.5% 왕복비용)</div>
      <div class="kpi-value neg">-{fnum(CORE_CAGR_DROP,2)}%p</div>
      <div class="kpi-sub">Sharpe {fnum(CUR['sharpe'],2)} → {fnum(CONS['sharpe'],2)} (-{fnum(CORE_SHARPE_DROP,2)})</div>
    </div>
    <div class="kpi-tile">
      <div class="kpi-label">순열검정 p-value (현재비용 / 보수적비용)</div>
      <div class="kpi-value neg">{PERM_CUR['p_value']} / {PERM_CONS['p_value']}</div>
      <div class="kpi-sub">둘 다 관례적 유의수준 0.05를 크게 초과 — 유의하지 않음</div>
    </div>
    <div class="kpi-tile">
      <div class="kpi-label">계좌 1억원 실효세율(세전이익 대비)</div>
      <div class="kpi-value neg">{fnum(ACC_100M['effective_tax_rate_on_total_gain_pct'],1)}%</div>
      <div class="kpi-sub">3천만원 {fnum(ACC_30M['effective_tax_rate_on_total_gain_pct'],1)}% ~ 3억원 {fnum(ACC_300M['effective_tax_rate_on_total_gain_pct'],1)}%</div>
    </div>
  </div>

  <div class="callout warn">
    <div class="callout-title">가장 중요한 새 발견 — 코어의 순열검정이 관례적 유의수준을 통과하지 못한다</div>
    <p>2019-08~2026-09(XLC 실제 상장 이후 17자산이 모두 갖춰지는 구간, {S1['meta']['n_years']:.1f}년) 창에서
      코어 로테이션 규칙(캔들모양 보존, 날짜순서만 무작위화한 200회 순열)을 검정한 결과, 실제 Sharpe가
      순열 분포에서 상위 {100-PERM_CUR['percentile']:.1f}%(현재비용)~{100-PERM_CONS['percentile']:.1f}%(보수적비용)에
      위치해 p-value {PERM_CUR['p_value']}(현재비용)~{PERM_CONS['p_value']}(보수적비용)를 기록했다 —
      이 프로그램이 다른 채택 판정에 요구해온 기준(p&lt;0.05, 통상 90% 이상 확신)에 명확히 못 미친다.
      즉 <b>"날짜 순서를 무작위로 섞은 가짜 시계열에도 이 정도(또는 더 나은) Sharpe가 우연히 나올 확률이
      17~24%"</b>라는 뜻이다 — 낮지 않다. 블록부트스트랩(2절)의 신뢰구간이 0 위쪽에 있다는 것과
      모순되지는 않는다(서로 다른 귀무가설을 검정하는 것이므로 — 부트스트랩은 "이 Sharpe 추정치
      자체의 표본오차가 작은가", 순열검정은 "이 정도 Sharpe가 순수 노이즈에서도 나올 수 있는가"),
      하지만 confidence 등급을 매길 때는 더 엄격한(더 회의적인) 검정 결과를 따라야 한다는 것이 이
      프로젝트의 기존 관례다. <b>이 순열검정은 XLC가 실제로 존재하는 기간(2018-06 이후)으로 제한된
      감사 창을 쓴다 — 이 저장소의 원래 코어 로테이션 발견 라운드가 검증한 기간·데이터와 완전히
      같지 않을 수 있음</b>을 감안해도, 지금 라이브로 도는 정확히 이 17자산·이 파라미터 조합에
      대해서는 이번이 첫 순열검정이며 결과가 약하다는 사실 자체는 남는다.</p>
  </div>

  <div class="callout warn">
    <div class="callout-title">새틀라이트는 부호조차 통계적으로 확정하기 어렵다</div>
    <p>새틀라이트의 블록부트스트랩 95% CI(L=20)는 [{fnum(SAT_BOOT_L20['ci_2.5'],2,signed=True)},
      {fnum(SAT_BOOT_L20['ci_97.5'],2,signed=True)}]로 0을 포함한다 — 다만 이건 이번 감사가 계산비용
      때문에 최근 반기 4회(약 {S1['meta']['satellite_n_years']:.1f}년, {S1['satellite_trade_events']}건의
      진입/청산)만 재구성한 축소 창이라는 근본적 한계 때문일 가능성이 크다(방법론 참고 — 라이브
      기본값의 전체기간·pool_n=40이 아님). 이 정도로 짧은 창에서 CI가 0을 포함하는 것은 이 프로그램의
      다른 사례(H33/H34가 COVID의 51거래일 창에서 겪은 것과 동일한 패턴)와 일관되며, "새틀라이트가
      효과 없다"는 결론이 아니라 "이 감사 창만으로는 확신할 수 없다"는 뜻으로 읽어야 한다.</p>
  </div>

  <div class="callout">
    <div class="callout-title">최종 판정</div>
    <p><b>거래비용 현실화(1절)</b>: 왕복 0.1%→0.5%로 올려도 코어·새틀라이트 모두 부호는 유지된다
      (코어 CAGR {fnum(CUR['cagr'],1)}%→{fnum(CONS['cagr'],1)}%, 새틀라이트(최근 {S1['meta']['satellite_n_years']:.1f}년)
      {fnum(S1['satellite_results']['current_0.1pct_rt']['metrics']['cagr'],1)}%→{fnum(S1['satellite_results']['conservative_0.5pct_rt']['metrics']['cagr'],1)}%)
      — 비용만으로 결론이 뒤집히지는 않는다. <b>세금(4절)</b>까지 반영하면 계좌 규모에 따라 세전
      실현이익의 13~22.5%가 추가로 사라진다. <b>하지만 순열검정(2절)</b>이 관례적 유의수준을
      통과하지 못한다는 것은 비용·세금 이전에도 이미 "이 특정 신호가 노이즈와 통계적으로 구분되는가"
      자체가 약하다는 뜻이므로, confidence 등급은 <span class="badge weak">약함(WEAK)</span>으로
      하향 조정한다 — 코어단독의 원래 confidence_table 등급(robust~moderate 계열로 알려짐)을
      그대로 유지할 근거가 이번 비용/세금 감사 관점에서는 부족하다. <b>"방향은 맞을 수 있지만 비용과
      세금을 다 반영한 후에도 통계적으로 확신하기엔 이르다"</b>가 이 감사의 정직한 결론이다.
      실전 매매 전에 (a) 더 긴 순열검정 창(다른 대리 데이터로 XLC 이전 기간 보완) 또는 (b) 더 단순한
      벤치마크(SPY 매수보유, 참고선) 대비 초과성과의 통계적 유의성 재검증이 필요하다는 것을
      다음 라운드(D/G)가 검토해야 할 항목으로 남긴다.</p>
  </div>
</div>

</div>
<footer>
  <p>산출물: analysis/2026-09-14_cost_tax_audit/ (step1_cost_scenarios.py, step2_permutation_bootstrap.py,
    step3_tax_simulation.py, step1_results.json, step2_results.json, step3_results.json, build_report.py).
    리서치 에이전트 F(research_agents/agent_f_cost_tax_auditor.md)의 첫 실행 — D의 새 후보가 없어
    core/champion_strategy.py 라이브 기본설정을 폴백 감사 대상으로 삼음. core/, app/는 수정하지 않음.</p>
</footer>
"""

with open(f"{OUT_DIR}/final_report.html", "w", encoding="utf-8") as f:
    f.write(HTML)
print("wrote final_report.html", len(HTML))
