"""No.05 리포트("강세장엔 평균회귀가 아니라 추세추종")의 듀얼 모멘텀 섹터 로테이션을 재구현하고
재현성을 검증한다(원 리포트는 이 저장소에 빌드 스크립트를 남기지 않고 Artifact로만 존재했음).

전략: GICS 11개 핵심 섹터 ETF, 매월 첫 거래일 리밸런싱, 절대모멘텀(직전 252거래일 수익률 >0)
필터를 통과한 섹터 중 상대모멘텀(12개월 수익률) 상위 3개를 동일비중(각 33.3%) 보유, 후보 부족분은
현금.
"""
import sys
sys.path.insert(0, "/workspaces/Quant")

import numpy as np
import pandas as pd

from core.backtest_engine import calculate_metrics, compute_equity_curve, run_buy_and_hold, _first_trading_day_of_month_mask
from core.market_data import get_multiple_price_history

OUT_DIR = "/workspaces/Quant/analysis/kostolany_market_report_2026-08-12"
SECTOR_ETFS = ["XLK", "XLF", "XLV", "XLY", "XLP", "XLE", "XLI", "XLB", "XLU", "XLRE", "XLC"]
MOMENTUM_WINDOW = 252  # 12개월(거래일 기준)
TOP_N = 3
WARMUP_DAYS = 400


def fetch_histories(start: str, end: str | None = None) -> dict[str, pd.DataFrame]:
    fetch_start = (pd.Timestamp(start) - pd.DateOffset(days=WARMUP_DAYS)).date().isoformat()
    return get_multiple_price_history(SECTOR_ETFS, start=fetch_start, end=end, interval="1d")


def build_momentum_weights(
    closes: pd.DataFrame, start: str, end: str | None = None,
    momentum_window: int = MOMENTUM_WINDOW, top_n: int = TOP_N,
    weighting: str = "equal",  # "equal" | "inverse_vol"
    vol_window: int = 63,
) -> pd.DataFrame:
    """월별 리밸런싱 날의 목표 비중(0~1, 섹터별 컬럼)을 담은 DataFrame(인덱스=전체 거래일,
    리밸런싱일 이후 다음 리밸런싱일까지 그대로 유지 = ffill)을 만든다.

    momentum_window거래일 수익률로 절대/상대 모멘텀을 계산 — 신호 계산에는 리밸런싱일 "전일 종가"까지만
    사용해 lookahead를 피한다(신호가 뜬 날의 다음 거래일 시가/종가로 체결한다고 가정하는 기존 엔진
    관례와 일치하도록, executed_position은 compute_equity_curve가 이미 한 거래일 shift 처리한다).
    """
    momentum = closes.pct_change(momentum_window)
    daily_ret = closes.pct_change()
    realized_vol = daily_ret.rolling(vol_window, min_periods=vol_window).std()

    is_rebal = _first_trading_day_of_month_mask(closes.index)
    weights = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)

    last_weights = pd.Series(0.0, index=closes.columns)
    for i, dt in enumerate(closes.index):
        if is_rebal.iloc[i] and i > 0:
            signal_date = closes.index[i - 1]  # 리밸런싱일 전일 종가 기준으로 신호 계산(lookahead 방지)
            mom = momentum.loc[signal_date]
            candidates = mom[mom > 0].sort_values(ascending=False)
            picks = candidates.index[:top_n]
            w = pd.Series(0.0, index=closes.columns)
            if len(picks) > 0:
                if weighting == "equal":
                    w[picks] = 1.0 / top_n
                elif weighting == "inverse_vol":
                    vol = realized_vol.loc[signal_date, picks]
                    inv = 1.0 / vol.replace(0, np.nan)
                    inv = inv.fillna(0.0)
                    total_slots = len(picks) / top_n  # 부족분은 현금 유지, 있는 슬롯만 위험균등 배분
                    if inv.sum() > 0:
                        w[picks] = (inv / inv.sum()) * (len(picks) / top_n)
            last_weights = w
        weights.iloc[i] = last_weights.values
    return weights


def compute_rotation_equity(
    histories: dict[str, pd.DataFrame], start: str, end: str | None = None, **kwargs,
) -> tuple[pd.Series, pd.DataFrame]:
    closes = pd.DataFrame({t: df["Close"] for t, df in histories.items()}).dropna(how="all")
    closes = closes.ffill()
    # 여기서 남은 결측(상장/재상장 전 구간)은 절대 dropna하지 않는다 — 종목 하나라도 늦게
    # 시작하면(예: 파산 후 재상장) 그 시작일까지 전체 유니버스의 백테스트 구간이 통째로 잘려나가는
    # 버그가 있었다(예: 노블코퍼레이션 NE가 2021-06 재상장이라 68종목 표본 전체가 2015년 대신
    # 2021-06부터로 잘림). NaN인 채로 두면 momentum(=pct_change)도 자연히 NaN이 되어
    # build_momentum_weights의 "mom > 0" 조건에서 자동으로 후보에서 빠진다(NaN 비교는 항상 False) —
    # 상장 전 종목은 그냥 후보 자격이 없는 것으로 처리되고, 나머지 종목들의 백테스트 구간은 그대로
    # 보존된다.
    weights_full = build_momentum_weights(closes, start, end, **kwargs)

    sliced_closes = closes[closes.index >= pd.Timestamp(start)]
    if end:
        sliced_closes = sliced_closes[sliced_closes.index <= pd.Timestamp(end)]
    weights = weights_full.loc[sliced_closes.index]

    daily_ret = sliced_closes.pct_change().fillna(0.0)
    executed_weights = weights.shift(1).fillna(0.0)  # 리밸런싱 신호 다음 거래일부터 체결
    port_ret = (daily_ret * executed_weights).sum(axis=1)
    equity = (1.0 + port_ret).cumprod() * 100.0
    equity.iloc[0] = 100.0
    return equity, weights


def main():
    # 1) 원 리포트 기간(2019-08-12~2026-08-12)으로 재현성 검증
    start1, end1 = "2019-08-12", "2026-08-12"
    histories = fetch_histories(start1, end1)
    eq1, w1 = compute_rotation_equity(histories, start1, end1)
    m1 = calculate_metrics(eq1, [], eq1.index[0], eq1.index[-1])
    print(f"[검증용 {start1}~{end1}] 모멘텀 로테이션(Top3 동일비중):", m1)

    bench1 = run_buy_and_hold("SPY", start1, end1)
    print(f"[검증용] SPY 매수보유:", bench1.metrics)

    equal_closes = pd.DataFrame({t: df["Close"] for t, df in histories.items()}).ffill().dropna()
    equal_closes = equal_closes[(equal_closes.index >= pd.Timestamp(start1)) & (equal_closes.index <= pd.Timestamp(end1))]
    equal_ret = equal_closes.pct_change().fillna(0.0).mean(axis=1)
    equal_eq = (1.0 + equal_ret).cumprod() * 100.0
    equal_eq.iloc[0] = 100.0
    m_equal = calculate_metrics(equal_eq, [], equal_eq.index[0], equal_eq.index[-1])
    print(f"[검증용] 11개 섹터 균등보유:", m_equal)

    print("\n(원 리포트 발표치: 모멘텀 로테이션 CAGR 15.74%/MDD -31.50%/샤프 0.82, "
          "SPY CAGR 15.10%/MDD -34.10%/샤프 0.81, 균등보유 CAGR 11.39%/MDD -36.83%/샤프 0.67)")

    import json as _json
    with open(f"{OUT_DIR}/momentum_rotation_verification.json", "w", encoding="utf-8") as f:
        _json.dump({
            "period": {"start": start1, "end": end1},
            "reproduced": m1, "spy_bh": bench1.metrics, "equal_weight_11": m_equal,
            "original_reported": {"cagr": 15.74, "mdd": -31.50, "sharpe": 0.82,
                                    "spy_cagr": 15.10, "spy_mdd": -34.10, "spy_sharpe": 0.81,
                                    "equal_cagr": 11.39, "equal_mdd": -36.83, "equal_sharpe": 0.67},
        }, f, ensure_ascii=False, indent=2)

    # 2) 내 리포트와 같은 전체 기간(2015-01-01~2026-08-12)으로 확장
    start2, end2 = "2015-01-01", "2026-08-12"
    histories2 = fetch_histories(start2, end2)
    eq2, w2 = compute_rotation_equity(histories2, start2, end2)
    m2 = calculate_metrics(eq2, [], eq2.index[0], eq2.index[-1])
    print(f"\n[확장 {start2}~{end2}] 모멘텀 로테이션(Top3 동일비중):", m2)

    bench2 = run_buy_and_hold("^GSPC", start2, end2)
    print(f"[확장] S&P500 매수보유:", bench2.metrics)

    import pickle
    with open("momentum_rotation_extended.pkl", "wb") as f:
        pickle.dump({"eq": eq2, "weights": w2, "bench_eq": bench2.equity_curve, "bench_metrics": bench2.metrics,
                     "rotation_metrics": m2, "histories": histories2}, f)
    print("DONE")


if __name__ == "__main__":
    main()
