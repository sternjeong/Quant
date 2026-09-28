"""검증 연구: 챔피언 코어의 17자산 유니버스 선택이 특별한가? (사전 등록)

배경: `analysis/2026-09-14_methodology_meta_audit` 가 "코어 자산군 17자산은 한 번도 형식 검정을 받지
않았는데 robust 등급으로 남아 있다"는 이중 잣대를 지적했다. 기존 순열검정(`analysis/LATEST_STRATEGY_
CANDIDATE.md`)은 "17개 **안에서** 모멘텀 순위로 고르는 것이 무작위보다 나은가"를 물었을 뿐, "하필 그
17개를 고른 것이 특별한가"는 묻지 않았다. 이 작업이 그 질문에 답한다.

## 사전 등록 (결과를 보기 전에 고정했다 — docs/RESEARCH_JOBS.md 2절, 이후 바꾸지 않는다)

귀무가설 두 개. 각각 같은 로직·같은 기간으로 무작위 유니버스를 DRAWS 회 돌려 실제 17자산의 백분위를 본다.

  H_A (넓은 무작위)  : POOL_A 에서 아무 17개.            "아무렇게나 고른 17개보다 나은가"
  H_B (구성 보존)    : 섹터 11개 고정 + DIVERSIFIERS 6개.  "섹터 + 분산자산 6개라는 틀은 주되,
                                                          하필 그 6개를 고른 것이 특별한가"

판정 기준(둘 다 동일): 경험적 p = (실제 이상인 무작위 수 + 1) / (추출 수 + 1)
  PASS      p <= 0.05   (상위 5% 이내 — 그 선택이 특별하다)
  WEAK      p <= 0.20   (상위 20% 이내 — 다소 낫지만 우연을 배제 못 한다)
  FAIL      그 외        (우연과 구별되지 않는다)

H_B 가 진짜 시험대다 — 작업22 H19 의 실제 결정(EFA·HYG·DBC 추가)을 정조준한다.

**규율(어기면 이 연구의 의미가 사라진다):** 더 나은 무작위 유니버스를 발견해도 **채택하지 않는다.**
이것은 현직(incumbent) 평가이지 탐색이 아니다. 여기서 최고를 골라 쓰면 챔피언 계보의 가설 수
(메타 감사 기준 N=80)에 수백 개를 더하는 꼴이고, 메타 감사가 지적한 바로 그 실수를 반복하게 된다.
그래서 이 스크립트는 상위 유니버스의 **구성 자체를 출력하지 않고**, 상위·하위 10% 집단의 자산 등장
빈도만 집계한다.

백테스트는 라이브 엔진(`core/champion_strategy.py`)과 **별개 구현**이다. 절대 샤프를 라이브 수치와
직접 비교하면 안 된다 — 의미 있는 것은 백분위뿐이다(모든 유니버스가 똑같은 코드를 통과하므로).
실제 17자산의 샤프가 LATEST_STRATEGY_CANDIDATE.md 의 1.06 근처인지는 정합성 확인용으로 출력한다.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from core.champion_strategy import (  # noqa: E402
    CORE_MOMENTUM_LOOKBACK_DAYS,
    CORE_TOP_N,
    CORE_UNIVERSE,
    CORE_WEIGHT,
    MARKET_FILTER_EXPOSURE_CUT,
    MARKET_FILTER_SMA_WINDOW,
    MARKET_FILTER_TICKER,
)

EXIT_DONE, EXIT_IN_PROGRESS = 0, 3
TRADING_DAYS = 252
ONE_WAY_BPS = 5.0        # 왕복 0.1% — 챔피언 백테스트 관례
START = "2019-08-12"     # LATEST_STRATEGY_CANDIDATE.md 의 측정 구간 시작과 같게
WARMUP_START = "2018-06-01"  # 12개월 모멘텀 선행 이력(XLC 상장 2018-06-18 이 전체 기간을 묶는다)
DEFAULT_DRAWS = 500
SEED = 0
P_PASS, P_WEAK = 0.05, 0.20  # 사전 등록 문턱
SAVE_EVERY = 25              # 체크포인트 저장 간격(추출 수)

SECTORS = ["XLC", "XLY", "XLP", "XLE", "XLF", "XLV", "XLI", "XLB", "XLRE", "XLK", "XLU"]
# 분산자산 후보(H_B 의 6칸을 채울 풀) — 채권·원자재·해외·리츠. 미국 주식 스타일/사이즈는 일부러 뺐다:
# 넣으면 H_B 가 "분산이냐 집중이냐"를 묻게 되어, 원래 묻고 싶은 "어느 분산자산이냐"가 흐려진다.
DIVERSIFIERS = [
    "TLT", "IEF", "SHY", "LQD", "HYG", "TIP", "AGG", "EMB",   # 채권 8
    "GLD", "SLV", "DBC", "USO", "DBA",                         # 원자재 5
    "EFA", "EEM", "VGK", "EWJ", "VWO", "ACWX",                 # 해외 6
    "VNQ", "IYR",                                              # 리츠 2
]
# H_A 전용 추가분 — 미국 주식 스타일/사이즈. H_A 는 "아무 17개"가 기준이므로 이쪽까지 포함한다.
US_STYLE = ["IWM", "MDY", "QQQ", "VTV", "VUG", "MTUM", "USMV", "DIA"]

POOL_A = SECTORS + DIVERSIFIERS + US_STYLE
SATELLITE_ACTUAL = [t for t in CORE_UNIVERSE if t not in SECTORS]  # TLT IEF GLD EFA HYG DBC


# ---------------------------------------------------------------- 데이터
def load_panel(tickers: list[str]) -> pd.DataFrame:
    """종목별 조정 종가 패널(날짜 × 티커)."""
    from core.market_data import get_multiple_price_history

    histories = get_multiple_price_history(sorted(set(tickers)), WARMUP_START)
    cols = {}
    for ticker, df in (histories or {}).items():
        if df is None or df.empty or "Close" not in df:
            continue
        col = "Adj Close" if "Adj Close" in df and df["Adj Close"].notna().any() else "Close"
        s = df[col].dropna()
        s.index = pd.DatetimeIndex(s.index).tz_localize(None).normalize()
        cols[ticker] = s[~s.index.duplicated(keep="last")]
    return pd.DataFrame(cols).sort_index()


def usable_tickers(panel: pd.DataFrame) -> list[str]:
    """백테스트 시작일에 이미 12개월 모멘텀을 계산할 수 있는 종목만(신규 상장 편향 차단)."""
    head = panel.loc[: pd.Timestamp(START)]
    return [t for t in panel.columns if head[t].notna().sum() > CORE_MOMENTUM_LOOKBACK_DAYS]


# ---------------------------------------------------------------- 백테스트
def rebalance_dates(days: pd.DatetimeIndex) -> list[pd.Timestamp]:
    """매월 첫 거래일 — 라이브 챔피언의 리밸런싱 관례."""
    return list(pd.Series(days, index=days).groupby(days.to_period("M")).min())


def market_filter_series(panel: pd.DataFrame) -> pd.Series:
    """리밸런싱일에 곱할 노출 배율(SPY 200일선 위면 1.0, 아래면 0.5)."""
    spy = panel[MARKET_FILTER_TICKER]
    above = spy >= spy.rolling(MARKET_FILTER_SMA_WINDOW).mean()
    return above.map({True: 1.0, False: MARKET_FILTER_EXPOSURE_CUT})


def backtest(universe: list[str], rets: pd.DataFrame, mom: pd.DataFrame, expo: pd.Series,
             days: pd.DatetimeIndex, rebal: set) -> pd.Series:
    """코어 로테이션 일별 순수익. 오늘 정한 비중은 다음 거래일부터 적용(weights.shift(1) 관례),
    리밸런싱 사이에는 보유 비중이 가격에 따라 표류하고, 미배분 비중은 현금(수익 0)이다."""
    cols = [t for t in universe if t in mom.columns]
    holdings: dict[str, float] = {}
    pending: dict[str, float] | None = None
    out = []
    for d in days:
        r_day, cost = 0.0, 0.0
        if pending is not None:
            turnover = sum(abs(pending.get(k, 0.0) - holdings.get(k, 0.0)) for k in set(pending) | set(holdings))
            cost = turnover * ONE_WAY_BPS / 1e4
            holdings, pending = dict(pending), None
        if holdings:
            grown = {}
            for k, w in holdings.items():
                r = rets.at[d, k]
                r = 0.0 if pd.isna(r) else float(r)
                r_day += w * r
                grown[k] = w * (1 + r)
            total = 1 + r_day
            holdings = {k: v / total for k, v in grown.items()} if total > 0 else {}
        out.append(r_day - cost)
        if d in rebal:
            scores = mom.loc[d, cols].dropna()
            picks = scores[scores > 0].nlargest(CORE_TOP_N)
            if len(picks):
                w = CORE_WEIGHT * float(expo.at[d]) / len(picks)
                pending = {t: w for t in picks.index}
            else:
                pending = {}
    return pd.Series(out, index=days)


def stats(r: pd.Series) -> dict:
    r = r.dropna()
    n = len(r)
    if n < 2:
        return {"n_days": n, "sharpe": 0.0}
    sd = float(r.std(ddof=1))
    eq = (1 + r).cumprod()
    return {"n_days": n,
            "sharpe": (float(r.mean()) / sd * math.sqrt(TRADING_DAYS)) if sd > 0 else 0.0,
            "cagr": float(eq.iloc[-1] ** (TRADING_DAYS / n) - 1),
            "max_drawdown": float((eq / eq.cummax() - 1).min())}


# ---------------------------------------------------------------- 추출·판정
def draw_universes(kind: str, pool: list[str], n_draws: int, seed: int) -> list[list[str]]:
    """시드 고정이라 재개해도 같은 순서를 다시 만든다(체크포인트가 앞에서부터 채워진다).
    H_A: 풀에서 17개. H_B: 섹터 11개 고정 + 분산자산 풀에서 6개. 중복 조합은 한 번만 센다."""
    rng = np.random.default_rng(seed)
    seen, out, guard = set(), [], 0
    while len(out) < n_draws and guard < n_draws * 50:
        guard += 1
        if kind == "A":
            uni = sorted(rng.choice(pool, size=len(CORE_UNIVERSE), replace=False).tolist())
        else:
            uni = sorted(SECTORS + rng.choice(pool, size=len(SATELLITE_ACTUAL), replace=False).tolist())
        key = tuple(uni)
        if key in seen:
            continue
        seen.add(key)
        out.append(uni)
    return out


def empirical_p(sharpes: list[float], actual: float) -> tuple[int, float]:
    arr = np.asarray(sharpes, dtype=float)
    n_better = int((arr >= actual).sum())
    return n_better, round((n_better + 1) / (len(arr) + 1), 4)


def verdict_of(p: float) -> str:
    """사전 등록 판정 — 결과를 보기 전에 고정했다."""
    if p <= P_PASS:
        return "PASS"
    return "WEAK" if p <= P_WEAK else "FAIL"


def asset_frequency(universes: list[list[str]], sharpes: list[float], quantile: float = 0.1) -> dict:
    """상위/하위 10% 집단의 자산 등장 빈도. 개별 조합은 공개하지 않는다(위 규율)."""
    order = np.argsort(sharpes)
    k = max(1, int(len(sharpes) * quantile))

    def freq(idxs):
        c: dict[str, int] = {}
        for i in idxs:
            for t in universes[i]:
                c[t] = c.get(t, 0) + 1
        return {t: round(v / len(idxs), 3) for t, v in c.items()}

    top_f, bot_f = freq(order[-k:]), freq(order[:k])
    gap = {t: round(top_f.get(t, 0.0) - bot_f.get(t, 0.0), 3) for t in set(top_f) | set(bot_f)}
    return {"n_each_group": k, "top_decile": top_f, "bottom_decile": bot_f,
            "gap_sorted": dict(sorted(gap.items(), key=lambda kv: -kv[1]))}


def summarize(universes, sharpes, actual_sharpe) -> dict:
    arr = np.asarray(sharpes, dtype=float)
    n_better, p = empirical_p(sharpes, actual_sharpe)
    return {"n_draws": len(arr), "mean": float(arr.mean()),
            "sd": float(arr.std(ddof=1)) if len(arr) > 1 else 0.0,
            "min": float(arr.min()), "median": float(np.median(arr)), "max": float(arr.max()),
            "percentile_of_actual": round(100.0 * float((arr < actual_sharpe).mean()), 1),
            "n_random_at_least_as_good": n_better, "empirical_p": p, "verdict": verdict_of(p),
            "asset_frequency": asset_frequency(universes, sharpes)}


# ---------------------------------------------------------------- 리포트
def render(res: dict) -> str:
    a, b, act = res["H_A"], res["H_B"], res["actual"]
    L = [
        "# 챔피언 코어의 17자산 유니버스 선택이 특별한가?",
        "",
        f"생성 {res['generated_at']} · 시드 {SEED} · 기간 {START} ~ {res['end_date']} ({act['n_days']}거래일)",
        f" · 추출 H_A {a['n_draws']}회 / H_B {b['n_draws']}회",
        "",
        "## 판정 (사전 등록, 결과를 보기 전에 고정)",
        "",
        "| 가설 | 묻는 것 | 실제 백분위 | 경험적 p | 판정 |",
        "|---|---|---|---|---|",
        f"| **H_A** 넓은 무작위 | 아무렇게나 고른 17개보다 나은가 | {a['percentile_of_actual']} | "
        f"{a['empirical_p']:.4f} | **{a['verdict']}** |",
        f"| **H_B** 구성 보존 | 하필 그 분산자산 6개인 것이 특별한가 | {b['percentile_of_actual']} | "
        f"{b['empirical_p']:.4f} | **{b['verdict']}** |",
        "",
        f"기준: p ≤ {P_PASS} PASS · p ≤ {P_WEAK} WEAK · 그 외 FAIL.",
        "",
        "## 묻는 것",
        "",
        "메타 감사(`analysis/2026-09-14_methodology_meta_audit`)가 \"코어 17자산은 한 번도 형식 검정을 받지",
        "않았는데 robust 등급으로 남아 있다\"고 지적했다. 기존 순열검정은 *17개 안에서* 고르는 방식을 검증했을",
        "뿐, *하필 그 17개* 를 고른 것이 특별한지는 묻지 않았다.",
        "",
        "- **H_A(넓은 무작위)**: 풀 40종에서 아무 17개. 채권만 잔뜩 뽑힌 조합도 섞이므로 이기기 쉬운 시험이다.",
        "- **H_B(구성 보존)**: 섹터 11개는 고정하고 분산자산 6칸만 교체. 작업22 H19의 실제 결정",
        "  (EFA·HYG·DBC 추가)을 정조준하는 진짜 시험대다.",
        "",
        "**규율:** 더 나은 무작위 유니버스를 발견해도 채택하지 않는다. 이것은 현직 평가이지 탐색이 아니다.",
        "그래서 상위 조합의 구성은 공개하지 않고, 자산 등장 빈도만 본다.",
        "",
        "## 설정",
        "",
        f"- 로직(모든 유니버스에 동일): 매월 첫 거래일, 12개월({CORE_MOMENTUM_LOOKBACK_DAYS}거래일) 모멘텀이",
        f"  양(+)인 것 중 상위 {CORE_TOP_N}개 동일비중, 코어 비중 {CORE_WEIGHT:.0%}(나머지 현금),",
        f"  SPY가 {MARKET_FILTER_SMA_WINDOW}일선 아래면 노출 ×{MARKET_FILTER_EXPOSURE_CUT:g}, 편도 {ONE_WAY_BPS:g}bp",
        f"- 실제 17자산: {', '.join(CORE_UNIVERSE)}",
        f"- 풀: H_A {res['pool_sizes']['A']}종 / H_B 분산자산 {res['pool_sizes']['B']}종",
        "",
        "## 정합성 확인",
        "",
        f"이 스크립트의 실제 17자산 샤프 **{act['sharpe']:.3f}** (CAGR {act['cagr']:.2%}, MDD {act['max_drawdown']:.2%}).",
        "`analysis/LATEST_STRATEGY_CANDIDATE.md` 의 후보1(코어 단독) 샤프 1.06과 크게 다르지 않아야 한다.",
        "이 백테스트는 라이브 엔진과 별개 구현이므로 **절대 수치를 라이브와 비교하지 말 것** — 의미 있는 것은",
        "백분위뿐이다(모든 유니버스가 똑같은 코드를 통과한다).",
        "",
        "## 무작위 분포",
        "",
        "| 가설 | 평균 | 표준편차 | 최솟값 | 중앙값 | 최댓값 | 실제 이상 |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, arm in (("H_A", a), ("H_B", b)):
        L.append(f"| {name} | {arm['mean']:.3f} | {arm['sd']:.3f} | {arm['min']:.3f} | "
                 f"{arm['median']:.3f} | {arm['max']:.3f} | {arm['n_random_at_least_as_good']}개 |")
    L += [
        "",
        "## 어떤 자산이 성과를 갈랐나 (H_B 기준)",
        "",
        "상위 10% 유니버스에서의 등장 비율 − 하위 10%에서의 등장 비율. 양수면 그 자산이 있을 때 결과가 좋았다.",
        "**이 표를 보고 유니버스를 바꾸지 않는다** — 같은 데이터에서 나온 사후 관찰이다.",
        "",
        "| 자산 | 상위 10% | 하위 10% | 차이 | 현재 채택 |",
        "|---|---|---|---|---|",
    ]
    bf = b["asset_frequency"]
    for t, gap in list(bf["gap_sorted"].items())[:14]:
        if t in SECTORS:
            continue  # H_B 에서 섹터는 항상 들어가므로 정보가 없다
        L.append(f"| {t} | {bf['top_decile'].get(t, 0):.2f} | {bf['bottom_decile'].get(t, 0):.2f} | "
                 f"{gap:+.2f} | {'O' if t in SATELLITE_ACTUAL else '-'} |")
    L += [
        "",
        "## 한계",
        "",
        "1. **기간이 짧다.** XLC 상장(2018-06) 제약으로 7년뿐이고 진짜 약세장은 2022년 하나다. 백분위 자체의",
        "   표본오차가 크다. 2008·2000 위기는 이 라운드에 없다.",
        "2. **풀 구성이 결과를 좌우한다.** 분산자산 풀에 무엇을 넣을지는 판단이었다(미국 주식 스타일은 일부러",
        "   제외 — 넣으면 H_B가 \"분산이냐 집중이냐\"를 묻게 된다).",
        "3. **거래비용이 단순하다.** 편도 5bp 고정이며 유동성 차이를 반영하지 않는다. 분산자산 풀의 일부",
        "   (DBA·ACWX 등)는 실제로 더 비싸므로, 무작위 쪽에 유리하게 기운 셈이다.",
        "4. **살아남은 것만 본다.** 풀은 오늘 존재하는 ETF로 짰다. 그 사이 청산된 ETF는 들어 있지 않다.",
        "5. **코어만 본다.** 새틀라이트(15%)는 이 연구에 없다.",
        "",
        "## 다음 라운드 숙제",
        "",
        "- H_B가 FAIL이면 → 분산자산 6개를 특별 취급하지 않도록 confidence_table 등급을 낮춘다.",
        "- H_B가 PASS면 → 왜 그 6개인지 설명할 근거를 찾는다. 설명 없는 통과는 다음 기간에 깨진다.",
        "- 같은 방식으로 `CORE_TOP_N=4`와 `200일선 이진 필터`, `12개월 룩백`을 검증한다(파라미터 이웃).",
        "- 새틀라이트 청산 메커니즘(돈치안 20일 + 15% 트레일) — 메타 감사가 지목한 또 하나의 미검증 부품.",
        "- 한계 1을 공략: Ken French 팩터로 근사해 100년 구간에서 같은 질문을 던진다(`core/french_factors.py`).",
        "",
    ]
    return "\n".join(L)


# ---------------------------------------------------------------- 실행
def _save(ckpt: Path, payload: dict) -> None:
    tmp = ckpt / "progress.tmp"
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(ckpt / "progress.json")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--draws", type=int, default=DEFAULT_DRAWS, help="H_A·H_B 각각의 무작위 추출 수")
    ap.add_argument("--out", required=True)
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--smoke", action="store_true", help="작은 추출 수로 끝까지 한 번에(대화 세션 확인용)")
    args = ap.parse_args(argv)

    out, ckpt = Path(args.out), Path(args.checkpoint)
    out.mkdir(parents=True, exist_ok=True)
    ckpt.mkdir(parents=True, exist_ok=True)
    draws = 10 if args.smoke else args.draws
    deadline = float(os.environ.get("RESEARCH_JOB_DEADLINE_EPOCH") or time.time() + 86400)

    saved = {}
    if (ckpt / "progress.json").exists():
        saved = json.loads((ckpt / "progress.json").read_text(encoding="utf-8"))
        if saved.get("draws") != draws:  # 추출 수가 바뀌면 처음부터
            saved = {}
    done: dict[str, list[float]] = {"A": saved.get("A", []), "B": saved.get("B", [])}
    print(f"[1/4] 가격 ({len(set(POOL_A)) + 1}종) · 이어받기 A {len(done['A'])} / B {len(done['B'])}", flush=True)

    panel = load_panel(POOL_A + [MARKET_FILTER_TICKER])
    ok = usable_tickers(panel)
    missing = sorted(set(CORE_UNIVERSE + [MARKET_FILTER_TICKER]) - set(ok))
    if missing:
        print(f"중단: 챔피언 구성에 필요한 종목의 이력이 부족하다 — {missing}", file=sys.stderr)
        return 1
    pool_a = [t for t in POOL_A if t in ok]
    pool_b = [t for t in DIVERSIFIERS if t in ok]
    dropped = sorted(set(POOL_A) - set(pool_a))

    print("[2/4] 공통 계산(수익률·모멘텀·시장필터)", flush=True)
    panel = panel[sorted(set(pool_a) | {MARKET_FILTER_TICKER})]
    ctx = {"rets": panel.pct_change(fill_method=None),
           "mom": panel / panel.shift(CORE_MOMENTUM_LOOKBACK_DAYS) - 1,
           "expo": market_filter_series(panel)}
    ctx["days"] = panel.index[panel.index >= pd.Timestamp(START)]
    ctx["rebal"] = set(rebalance_dates(ctx["days"]))

    actual = stats(backtest(CORE_UNIVERSE, **ctx))
    print(f"      실제 17자산 샤프 {actual['sharpe']:.3f} (참고: LATEST_STRATEGY_CANDIDATE 1.06)", flush=True)

    universes = {"A": draw_universes("A", pool_a, draws, SEED),
                 "B": draw_universes("B", pool_b, draws, SEED + 1)}
    print(f"[3/4] 무작위 백테스트 (A·B 각 {draws}회)", flush=True)
    for arm in ("A", "B"):
        while len(done[arm]) < len(universes[arm]):
            if not args.smoke and time.time() > deadline - 45:
                _save(ckpt, {"draws": draws, **done})
                print(f"체크포인트: A {len(done['A'])} / B {len(done['B'])} — 시간 예산 소진", flush=True)
                return EXIT_IN_PROGRESS
            done[arm].append(stats(backtest(universes[arm][len(done[arm])], **ctx))["sharpe"])
            if len(done[arm]) % SAVE_EVERY == 0:
                _save(ckpt, {"draws": draws, **done})
                print(f"  [{arm}] {len(done[arm])}/{len(universes[arm])}", flush=True)

    res = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "seed": SEED, "start": START, "end_date": ctx["days"][-1].date().isoformat(),
           "draws": draws, "pool_sizes": {"A": len(pool_a), "B": len(pool_b)},
           "dropped_from_pool": dropped, "actual_universe": list(CORE_UNIVERSE), "actual": actual,
           "H_A": summarize(universes["A"], done["A"], actual["sharpe"]),
           "H_B": summarize(universes["B"], done["B"], actual["sharpe"])}
    res["verdicts"] = {"H_A_broad_random": res["H_A"]["verdict"], "H_B_composition_held": res["H_B"]["verdict"]}

    print("[4/4] 결과 쓰는 중", flush=True)
    (out / "results.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "REPORT.md").write_text(render(res), encoding="utf-8")
    print(f"완료: H_A {res['H_A']['verdict']} (p={res['H_A']['empirical_p']}) · "
          f"H_B {res['H_B']['verdict']} (p={res['H_B']['empirical_p']})", flush=True)
    return EXIT_DONE


if __name__ == "__main__":
    sys.exit(main())
