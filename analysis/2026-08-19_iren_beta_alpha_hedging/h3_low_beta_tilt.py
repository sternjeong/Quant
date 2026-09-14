"""H3 — 베팅어게인스트베타(BAB) 저베타 이상현상 가설 검증.

가설(H3): 비트코인채굴→AI/HPC 피벗 후보군 내에서도 상대적으로 베타가 낮은 종목/구간에 더 많은
비중을 주는 것이(단순 동일가중이나 모멘텀 랭킹보다) 위험조정 수익을 개선한다. Frazzini & Pedersen
(2014, JFE) "Betting Against Beta"의 저베타 이상현상(레버리지 제약 투자자들이 고베타 자산을
과도하게 담아 고베타=저알파, 저베타=고알파가 되는 현상)이 이 소형 테마주 후보군 내부에서도
성립하는지를 직접 검증한다.

방법론:
  1. 월 1회(21거래일) 리밸런싱. 각 리밸런싱 시점에서 트레일링 90거래일 롤링 베타(SPY 대비, t-1일
     까지 데이터만 사용 — 룩어헤드 방지)로 종목을 정렬한다.
  2. 4개 포트폴리오를 동시에 시뮬레이션:
       - EW(동일가중): 전 종목 1/N
       - LB(저베타 틸트): 비중 ∝ 1/베타 (베타 하한 0.3로 클리핑, division 폭주 방지)
       - HB(고베타 틸트, 대조군): 비중 ∝ 베타 — BAB가 예측하는 비대칭을 반대 방향으로 보여주는 대조군
       - MOM(모멘텀 랭킹): 트레일링 63거래일 수익률 상위 절반(반올림) 종목만 동일가중, 나머지는 0
  3. 주 유니버스는 이력이 가장 짧은 CORZ를 제외한 6종목(공통구간이 훨씬 길어져 검증력이 높음),
     보조/강건성 검증으로 CORZ를 포함한 7종목 전체(공통구간이 짧아짐)도 함께 돌린다.
  4. 4개 포트폴리오의 CAGR·변동성·샤프·MDD를 비교 — LB가 EW와 MOM을 모두 능가하면 채택.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from common import MARKET_TICKER, PEER_TICKERS, daily_returns, fetch_close, perf_metrics, rolling_beta

BETA_WINDOW = 90
MOM_WINDOW = 63
REBALANCE_EVERY = 21
START = "2015-01-01"
END = "2026-08-19"
BETA_FLOOR = 0.3  # 저베타 비중(1/beta) 계산 시 division 폭주 방지용 하한


def _build_universe_data(tickers: list[str]) -> tuple[pd.DataFrame, pd.Series]:
    closes = {t: fetch_close(t, START, END) for t in tickers}
    closes = {t: c for t, c in closes.items() if not c.empty}
    rets = {t: daily_returns(c) for t, c in closes.items()}
    common_idx = None
    for r in rets.values():
        common_idx = r.index if common_idx is None else common_idx.intersection(r.index)
    mkt_close = fetch_close(MARKET_TICKER, START, END)
    r_mkt = daily_returns(mkt_close)
    common_idx = common_idx.intersection(r_mkt.index).sort_values()
    returns_df = pd.DataFrame({t: r.reindex(common_idx) for t, r in rets.items()})
    r_mkt_a = r_mkt.reindex(common_idx)
    return returns_df, r_mkt_a


def _beta_matrix(returns_df: pd.DataFrame, r_mkt: pd.Series, window: int) -> pd.DataFrame:
    betas = {}
    for t in returns_df.columns:
        betas[t] = rolling_beta(returns_df[t], r_mkt, window).shift(1)
    return pd.DataFrame(betas)


def _momentum_matrix(returns_df: pd.DataFrame, window: int) -> pd.DataFrame:
    cum = (1.0 + returns_df).rolling(window).apply(lambda x: x.prod() - 1.0, raw=True)
    return cum.shift(1)


def _simulate(returns_df: pd.DataFrame, beta_df: pd.DataFrame, mom_df: pd.DataFrame) -> dict[str, pd.Series]:
    idx = returns_df.index
    n = len(idx)
    first_valid = beta_df.dropna(how="any").index.min()
    if first_valid is None or pd.isna(first_valid):
        raise ValueError("베타 매트릭스에 유효한 행이 없음 — 유니버스 공통구간이 window보다 짧음")
    start_pos = idx.get_loc(first_valid)

    rebal_positions = list(range(start_pos, n, REBALANCE_EVERY))
    weights = {"EW": None, "LB": None, "HB": None, "MOM": None}
    port_rets = {k: [] for k in weights}
    port_dates = []

    tickers = list(returns_df.columns)
    n_assets = len(tickers)

    for i in range(start_pos, n):
        if i in rebal_positions:
            beta_row = beta_df.iloc[i]
            mom_row = mom_df.iloc[i]
            valid_mask = beta_row.notna()
            active = [t for t in tickers if valid_mask.get(t, False)]
            if not active:
                continue
            # EW
            ew = pd.Series(1.0 / len(active), index=active)
            # LB: inverse beta, floor 클리핑
            beta_clipped = beta_row[active].clip(lower=BETA_FLOOR)
            inv = 1.0 / beta_clipped
            lb = inv / inv.sum()
            # HB: proportional to beta (floor 살짝만, 음수 방지)
            beta_pos = beta_row[active].clip(lower=0.05)
            hb = beta_pos / beta_pos.sum()
            # MOM: 상위 절반 동일가중
            mom_active = mom_row[active].dropna()
            n_top = max(1, round(len(mom_active) / 2))
            top = mom_active.sort_values(ascending=False).index[:n_top]
            mom = pd.Series(0.0, index=active)
            mom.loc[top] = 1.0 / len(top)

            weights["EW"] = ew.reindex(tickers).fillna(0.0)
            weights["LB"] = lb.reindex(tickers).fillna(0.0)
            weights["HB"] = hb.reindex(tickers).fillna(0.0)
            weights["MOM"] = mom.reindex(tickers).fillna(0.0)

        row = returns_df.iloc[i]
        port_dates.append(idx[i])
        for k in weights:
            w = weights[k]
            if w is None:
                port_rets[k].append(np.nan)
            else:
                port_rets[k].append(float((row.fillna(0.0) * w).sum()))

    result = {}
    for k, vals in port_rets.items():
        s = pd.Series(vals, index=port_dates).dropna()
        result[k] = s
    return result


def run_universe(tickers: list[str], label: str) -> dict:
    returns_df, r_mkt = _build_universe_data(tickers)
    beta_df = _beta_matrix(returns_df, r_mkt, BETA_WINDOW)
    mom_df = _momentum_matrix(returns_df, MOM_WINDOW)
    port_rets = _simulate(returns_df, beta_df, mom_df)

    metrics = {k: perf_metrics(v) for k, v in port_rets.items()}
    avg_beta_by_port = {}
    for k in ("EW", "LB", "HB"):
        # 실현(사후) 베타: 포트폴리오 수익률 vs 시장 단순회귀
        from common import align, one_factor_ols
        pr, mr = align(port_rets[k], r_mkt)
        _, b, _ = one_factor_ols(pr.values, mr.values)
        avg_beta_by_port[k] = round(b, 3)

    lb_beats_ew = metrics["LB"]["sharpe"] > metrics["EW"]["sharpe"]
    lb_beats_mom = metrics["LB"]["sharpe"] > metrics["MOM"]["sharpe"]
    lb_beats_hb = metrics["LB"]["sharpe"] > metrics["HB"]["sharpe"]

    return {
        "label": label,
        "tickers": list(returns_df.columns),
        "n_days": int(len(returns_df)),
        "start": str(returns_df.index.min().date()),
        "end": str(returns_df.index.max().date()),
        "realized_beta": avg_beta_by_port,
        "metrics": metrics,
        "lb_beats_ew_sharpe": bool(lb_beats_ew),
        "lb_beats_mom_sharpe": bool(lb_beats_mom),
        "lb_beats_hb_sharpe": bool(lb_beats_hb),
        "verdict_hint": "채택" if (lb_beats_ew and lb_beats_mom) else "기각",
    }


def run() -> dict:
    primary_tickers = [t for t in PEER_TICKERS if t != "CORZ"]
    primary = run_universe(primary_tickers, "6종목(CORZ 제외, 긴 공통구간)")
    robustness = run_universe(PEER_TICKERS, "7종목 전체(CORZ 포함, 짧은 공통구간)")

    return {
        "hypothesis": "H3",
        "beta_window_days": BETA_WINDOW,
        "momentum_window_days": MOM_WINDOW,
        "rebalance_every_days": REBALANCE_EVERY,
        "primary": primary,
        "robustness_all7": robustness,
        "verdict_hint": primary["verdict_hint"],
    }


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2, ensure_ascii=False, default=str))
