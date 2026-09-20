"""8개 바스켓(기존 6개 + 신규 2개) 전부의 "상관구조" 지표를 사후가 아니라 동일한 방법으로 재계산.

historical_era_trend_following_extension(작업88)이 가설로만 남긴 것: "IREN 패턴 재현 여부는
바스켓 내 종목 수·상관관계 구조와 관련 있어 보인다(재현된 IREN·크립토윈터·태양광은 상관관계가
높고, 미재현된 해운·닷컴버블은 이질적 — 단 대마초는 반례)". 이 스크립트는 그 인상을 숫자로
바꾼다 — 각 바스켓의 "그 백테스트가 실제로 쓴 공통구간"에서 일별 수익률의 평균 쌍별 상관계수를
동일한 방법으로 계산해, structural_hypothesis_test.py에서 재현여부·샤프격차와 대조한다.

기존 6개 바스켓은 각자 원 스크립트가 이미 확정한 티커/공통구간 정의를 그대로 재사용한다(재정의
없음) — IREN(작업27), 해운/대마초/태양광(작업77), 크립토윈터/닷컴버블(작업88).
"""
import json
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "/opt/quant")
sys.path.insert(0, "/opt/quant/analysis/2026-08-16_iren_volatile_momentum_stocks")
from backtest import find_common_start  # noqa: E402
from core.market_data import get_multiple_price_history  # noqa: E402

OUT_DIR = "/opt/quant/analysis/2026-09-19_basket_correlation_structure_predictor"

# (tickers, load_start, end, momentum_warmup_days) — 각 원 연구가 실제로 쓴 값 그대로.
EXISTING_BASKETS = {
    "iren": {
        "tickers": ["IREN", "CIFR", "CLSK", "WULF", "HUT", "BTDR"],
        "load_start": "2005-01-01", "end": "2026-08-18", "warmup": 126,
        "source": "작업27 analysis/2026-08-16_iren_volatile_momentum_stocks",
    },
    "shipping": {
        "tickers": ["ZIM", "SBLK", "DAC", "FRO", "STNG"],
        "load_start": "2005-01-01", "end": "2026-09-12", "warmup": 126,
        "source": "작업77 analysis/2026-09-14_nonai_control_basket_volatility_momentum",
    },
    "cannabis": {
        "tickers": ["TLRY", "CGC", "ACB", "CRON"],
        "load_start": "2005-01-01", "end": "2026-09-12", "warmup": 126,
        "source": "작업77 analysis/2026-09-14_nonai_control_basket_volatility_momentum",
    },
    "solar": {
        "tickers": ["ENPH", "SEDG", "RUN", "FSLR", "PLUG"],
        "load_start": "2005-01-01", "end": "2026-09-12", "warmup": 126,
        "source": "작업77 analysis/2026-09-14_nonai_control_basket_volatility_momentum",
    },
    "crypto_winter_2018": {
        "tickers": ["MARA", "RIOT"],
        "load_start": "2017-01-01", "end": "2021-10-29", "warmup": 126,
        "source": "작업88 analysis/2026-09-17_historical_era_trend_following_extension",
    },
    "dotcom_bubble_2000": {
        "tickers": ["CSCO", "QCOM", "EBAY", "GLW", "CIEN", "AMZN"],
        "load_start": "1997-06-01", "end": "2002-12-31", "warmup": 126,
        "source": "작업88 analysis/2026-09-17_historical_era_trend_following_extension",
    },
    # 신규(이 라운드 사전등록)
    "ev_spac_bust": {
        "tickers": ["WKHS", "HYLN", "LCID", "PSNY"],
        "load_start": "2005-01-01", "end": "2026-09-18", "warmup": 126,
        "source": "이번 라운드(사전등록, 예측: 상관관계 HIGH)",
    },
    "biotech_catalyst": {
        "tickers": ["SRPT", "IONS", "RARE", "ALNY", "BMRN"],
        "load_start": "2005-01-01", "end": "2026-09-18", "warmup": 126,
        "source": "이번 라운드(사전등록, 예측: 상관관계 LOW)",
    },
}


def log(msg):
    print(f"[corr] {msg}", flush=True)


def closes_frame(histories: dict) -> pd.DataFrame:
    closes = pd.DataFrame({t: df["Close"] for t, df in histories.items() if not df.empty})
    return closes.sort_index()


def avg_pairwise_corr(returns: pd.DataFrame) -> dict:
    corr = returns.corr(method="pearson")
    n = corr.shape[0]
    iu = np.triu_indices(n, k=1)
    vals = corr.values[iu]
    return {
        "mean": float(np.mean(vals)),
        "median": float(np.median(vals)),
        "min": float(np.min(vals)),
        "max": float(np.max(vals)),
        "n_pairs": int(len(vals)),
        "pairwise": {f"{corr.columns[i]}-{corr.columns[j]}": round(float(corr.values[i, j]), 4)
                     for i, j in zip(*iu)},
    }


def main():
    result = {}
    for name, cfg in EXISTING_BASKETS.items():
        log(f"===== {name} =====")
        tickers = cfg["tickers"]
        hist = get_multiple_price_history(tickers, start=cfg["load_start"], end=cfg["end"], interval="1d")
        closes = closes_frame(hist)
        closes = closes[tickers]  # 컬럼 순서 고정
        common_start = find_common_start(closes.dropna(how="all"), cfg["warmup"])
        sliced = closes[closes.index >= common_start]
        rets = sliced.pct_change().dropna(how="all")
        stats = avg_pairwise_corr(rets)
        log(f"  종목 {tickers}, 공통시작 {common_start.date()}~{cfg['end']} (n={len(rets)}거래일)")
        log(f"  평균 쌍별 상관계수: {stats['mean']:.4f} (범위 {stats['min']:.4f}~{stats['max']:.4f})")
        result[name] = {
            "tickers": tickers,
            "n_tickers": len(tickers),
            "common_start": common_start.date().isoformat(),
            "end": cfg["end"],
            "n_trading_days": int(len(rets)),
            "source": cfg["source"],
            "correlation": stats,
        }

    with open(f"{OUT_DIR}/correlation_results.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    log(f"저장 완료: {OUT_DIR}/correlation_results.json")


if __name__ == "__main__":
    main()
