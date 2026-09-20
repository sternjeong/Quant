"""H_corr - 새틀라이트 전용 위기신호: "상관관계 급등"을 아직 안 풀린 2021년 성장주 언와인드
사각지대에 새로 대입해본다.

배경(작업35/H14/H15, satellite_specific_crisis_signal_research): 새틀라이트 자체 breadth(풀의
200일선 상회 비율)·실현 트레일링낙폭 두 신호는 둘 다 SPY 200일선 스위치를 못 이겼고, 2021년 말
성장주 언와인드(TSLA/NVDA/UPS 보유, SPY는 사상최고치 근처인데 새틀라이트만 -13.2% 먼저 빠짐) 사례
에서 SPY(43거래일 지연)보다도 breadth(61거래일 지연)가 더 늦게 반응해 사각지대를 못 막았다.

이번 라운드는 그때 시도되지 않은 세 번째 신호군 - 상관관계 급등 - 을 테스트한다:
  (1) holdings_corr: 실제 보유 중인 새틀라이트 종목(top_k=3, 반기 정적보유) 간 20일 롤링 페어와이즈
      평균상관관계. 국지적(섹터/테마) 위기는 흔히 "동반 급락"으로 나타나므로, 보유종목 간 상관관계가
      역사적 분포 대비 급등하면 개별종목 특이위험이 아니라 공통 위험요인이 지배하기 시작했다는
      신호일 수 있다는 가설.
  (2) pool_corr: 보유종목(3개, 페어 3개뿐이라 노이즈가 클 수 있음)이 아니라 point-in-time 후보풀
      전체(40종목, breadth와 동일한 풀)의 평균 페어와이즈 상관관계 - 더 넓은 표본으로 안정성을 높인
      변형.
  두 신호 모두 절대 임계값이 아니라 "trailing 252일 자기 자신의 평균/표준편차 대비 z-score"로
  정의한다(H14의 breadth>=0.5, drawdown<=-10%식 고정 임계값이 사후적으로 그 임계값에 맞춰 고른
  것처럼 보일 위험을 피하기 위함 - 상관관계는 시장 국면에 따라 절대 레벨 자체가 표류하므로 자기
  상대적 정의가 더 원칙적이다). z_thresh=1.5를 중심값으로, 1.0/2.0으로 견고성을 확인한다.

SPY 스위치와의 AND/OR 결합(spy_or_poolcorr 등)도 함께 본다 - "더 빨리 반응"이 목적이므로 OR이
직관적으로 유리할 것으로 예상되지만, 平시 오탐(휘프소) 비용도 같이 본다.

6개 역사적 구간(전체기간/2008GFC/COVID/2022/2018/2015-16) 전부에서 백테스트하고, H22와 동일한
기저확률 시나리오로 기댓값을 재구성하며, 2021년 사례는 H15와 동일한 방식으로 반응 시차를 다시
측정한다. 순열검정(원신호를 순환이동시켜 무작위 타이밍과 비교)과 블록부트스트랩 표본오차 감사는
별도 스크립트(h_bootstrap_and_permutation.py)에서 이 스크립트가 저장한 일별수익률 CSV를 재사용해
수행한다.

재사용 모듈(재구현 없음): champion_strategy.run_champion/CHAMPION_UNIVERSE(2026-08-19),
h1_core_satellite.semiannual_rebal_dates/blend_returns(2026-08-19),
h11_crisis_robustness_test.build_satellite_returns_period/run_three_asset_champion/
THREE_ASSET_UNIVERSE(2026-08-21), h12_regime_switch.fetch_spy_regime_signal/
build_regime_switched_weight_series/blend_returns_time_varying/perf_metrics_slice/
SATELLITE_WEIGHT_ON(2026-08-22), h14_satellite_specific_signal.pool_candidates_at_date/
build_drawdown_signal/signal_to_bull/combined_signal(2026-08-22). core/는 그대로 import만.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

MAIN_CHECKOUT = "/opt/quant"
sys.path.insert(0, MAIN_CHECKOUT)
sys.path.insert(0, str(Path(MAIN_CHECKOUT) / "analysis" / "2026-08-19_champion_beta_and_satellite_research"))
sys.path.insert(0, str(Path(MAIN_CHECKOUT) / "analysis" / "2026-08-21_satellite_signal_upgrade_and_crisis_test"))
sys.path.insert(0, str(Path(MAIN_CHECKOUT) / "analysis" / "2026-08-22_regime_conditional_satellite_switch"))
sys.path.insert(0, str(Path(MAIN_CHECKOUT) / "analysis" / "2026-08-22_satellite_specific_crisis_signal_and_2021_case_study"))

import numpy as np
import pandas as pd

from champion_strategy import run_champion, CHAMPION_UNIVERSE, _closes_from_histories
from h1_core_satellite import semiannual_rebal_dates, blend_returns
from h11_crisis_robustness_test import (
    run_three_asset_champion, build_satellite_returns_period, THREE_ASSET_UNIVERSE,
)
from h12_regime_switch import (
    fetch_spy_regime_signal, build_regime_switched_weight_series, blend_returns_time_varying,
    perf_metrics_slice, SATELLITE_WEIGHT_ON,
)
from h14_satellite_specific_signal import (
    pool_candidates_at_date, build_drawdown_signal, signal_to_bull, combined_signal,
)
from core.market_data import get_multiple_price_history

OUT_DIR = Path(__file__).resolve().parent

CORR_WINDOW = 20
Z_LOOKBACK = 252
Z_THRESHOLDS = [1.0, 1.5, 2.0]
Z_CENTRAL = 1.5

EPISODES = {
    "full_2019_2026": ("2019-08-12", "2026-08-19", "2019-08-12", "2026-08-19"),
    "gfc_2008": ("2007-01-01", "2009-12-31", "2007-10-01", "2009-06-30"),
    "covid_2020": ("2019-01-01", "2020-12-31", "2020-02-19", "2020-04-30"),
    "bear_2022": ("2019-08-12", "2026-08-19", "2022-01-01", "2022-12-31"),
    "selloff_2018": ("2017-06-01", "2019-06-30", "2018-09-01", "2019-01-15"),
    "correction_2015_2016": ("2014-06-01", "2016-06-30", "2015-08-01", "2016-02-15"),
}
EPISODE_ORDER = ["full_2019_2026", "gfc_2008", "covid_2020", "bear_2022", "selloff_2018", "correction_2015_2016"]

# H22(작업39, expected_value_reframing_and_continuous_exposure)와 동일한 기저확률 시나리오 - 재계산 없이
# 그대로 재사용
BASE_RATE_SCENARIOS = {
    "base": {"full_2019_2026": 0.50, "gfc_2008": 0.03, "covid_2020": 0.04, "bear_2022": 0.10,
             "selloff_2018": 0.16, "correction_2015_2016": 0.17},
    "calm_heavy": {"full_2019_2026": 0.65, "gfc_2008": 0.015, "covid_2020": 0.02, "bear_2022": 0.065,
                   "selloff_2018": 0.12, "correction_2015_2016": 0.13},
    "crisis_heavy": {"full_2019_2026": 0.35, "gfc_2008": 0.06, "covid_2020": 0.07, "bear_2022": 0.14,
                     "selloff_2018": 0.19, "correction_2015_2016": 0.19},
}


def log(msg):
    print(f"[h_corr] {msg}", flush=True)


# ---------------------------------------------------------------------------
# 신호 구축
# ---------------------------------------------------------------------------

def build_pool_breadth_and_correlation(start: str, end: str, trading_index: pd.DatetimeIndex,
                                        corr_window: int = CORR_WINDOW) -> tuple[pd.Series, pd.Series, list[dict]]:
    """H14의 build_pool_breadth_signal과 동일한 point-in-time 40종목 풀(고정 멤버십, 반기 갱신)에서
    breadth(200일선 상회비율)와 평균 페어와이즈 상관관계를 한 번의 가격조회로 함께 계산한다."""
    rebal_dates = semiannual_rebal_dates(trading_index, start, end)
    per_period_pool, all_tickers, pool_log = [], set(), []
    for d in rebal_dates:
        cands = pool_candidates_at_date(d)
        per_period_pool.append((d, cands))
        pool_log.append({"date": str(d.date()), "pool_size": len(cands)})
        all_tickers.update(cands)
    all_tickers = sorted(all_tickers)
    fetch_start = (pd.Timestamp(start) - pd.DateOffset(days=450)).date().isoformat()
    histories = get_multiple_price_history(all_tickers, start=fetch_start, end=end, interval="1d")
    closes = pd.DataFrame({t: histories[t]["Close"] for t in all_tickers
                           if t in histories and not histories[t].empty}).sort_index().ffill()
    sma200 = closes.rolling(200, min_periods=200).mean()
    above = closes >= sma200
    rets = closes.pct_change()

    full_idx = trading_index[(trading_index >= pd.Timestamp(start)) & (trading_index <= pd.Timestamp(end))]
    rebal_set = {d: [t for t in c if t in closes.columns] for d, c in per_period_pool}
    current: list[str] = []
    breadth = pd.Series(index=full_idx, dtype=float)
    corr = pd.Series(index=full_idx, dtype=float)
    for dt in full_idx:
        if dt in rebal_set:
            current = rebal_set[dt]
        if not current:
            breadth[dt] = np.nan
            corr[dt] = np.nan
            continue
        valid = [t for t in current if t in above.columns]
        row = above.loc[dt, valid].dropna() if (dt in above.index and valid) else pd.Series(dtype=float)
        breadth[dt] = float(row.mean()) if len(row) > 0 else np.nan
        if len(valid) >= 5 and dt in rets.index:
            w = rets.loc[:dt, valid].tail(corr_window)
            if len(w) >= int(corr_window * 0.6):
                cm = w.corr().values
                n = len(valid)
                iu = np.triu_indices(n, k=1)
                vals = cm[iu]
                corr[dt] = float(np.nanmean(vals)) if len(vals) else np.nan
            else:
                corr[dt] = np.nan
        else:
            corr[dt] = np.nan
    breadth = breadth.ffill()
    corr = corr.ffill()
    breadth.name, corr.name = "pool_breadth", "pool_corr"
    return breadth, corr, pool_log


def build_holdings_correlation(rebal_log: list[dict], tickers_ever_held: list[str],
                                start: str, end: str, trading_index: pd.DatetimeIndex,
                                corr_window: int = CORR_WINDOW) -> pd.Series:
    """실제 보유중인 새틀라이트 종목(top_k=3) 간 20일 롤링 평균 페어와이즈 상관관계."""
    full_idx = trading_index[(trading_index >= pd.Timestamp(start)) & (trading_index <= pd.Timestamp(end))]
    if not tickers_ever_held:
        return pd.Series(np.nan, index=full_idx, name="holdings_corr")
    fetch_start = (pd.Timestamp(start) - pd.DateOffset(days=corr_window + 60)).date().isoformat()
    histories = get_multiple_price_history(tickers_ever_held, start=fetch_start, end=end, interval="1d")
    closes = _closes_from_histories(histories, tickers_ever_held)
    closes = closes.reindex(closes.index.union(full_idx)).sort_index().ffill()
    rets = closes.pct_change()

    rebal_set = {pd.Timestamp(r["date"]): r["picks"] for r in rebal_log}
    current: list[str] = []
    corr = pd.Series(index=full_idx, dtype=float)
    for dt in full_idx:
        if dt in rebal_set:
            current = [t for t in rebal_set[dt] if t in rets.columns]
        if len(current) < 2:
            corr[dt] = np.nan
            continue
        w = rets.loc[:dt, current].tail(corr_window)
        if len(w) < int(corr_window * 0.6):
            corr[dt] = np.nan
            continue
        cm = w.corr().values
        n = len(current)
        iu = np.triu_indices(n, k=1)
        vals = cm[iu]
        corr[dt] = float(np.nanmean(vals)) if len(vals) else np.nan
    corr = corr.ffill()
    corr.name = "holdings_corr"
    return corr


def corr_zscore_bull(corr_series: pd.Series, lookback: int = Z_LOOKBACK, z_thresh: float = Z_CENTRAL) -> tuple[pd.Series, pd.Series]:
    """상관관계 급등(z >= z_thresh)이면 bear. lookback 부족(워밍업)이면 bull(정보 없음 -> 평시 취급)."""
    roll_mean = corr_series.rolling(lookback, min_periods=int(lookback * 0.5)).mean()
    roll_std = corr_series.rolling(lookback, min_periods=int(lookback * 0.5)).std()
    z = (corr_series - roll_mean) / roll_std
    bull = ~(z >= z_thresh)
    bull = bull.fillna(True)
    bull.name = "bull"
    return bull, z


# ---------------------------------------------------------------------------
# 에피소드별 백테스트
# ---------------------------------------------------------------------------

def build_core(label: str, full_start: str, full_end: str) -> dict:
    if label == "gfc_2008":
        return run_three_asset_champion(full_start, full_end)
    return run_champion(full_start, full_end)


def run_episode(label: str, full_start: str, full_end: str, crisis_start: str, crisis_end: str,
                 extra_windows: dict[str, tuple[str, str]] | None = None,
                 include_pool_signal: bool = True) -> dict:
    """include_pool_signal=False면 풀(40종목) breadth/상관관계 신호 계산을 건너뛴다 - 이 신호는
    point-in-time 유니버스 샘플링을 반기마다 새로 하고 40종목 전체의 가격이력을 따로 받아와야 해서,
    h14가 한 번도 다루지 않은 기간(covid_2020/selloff_2018/correction_2015_2016)에서는 처음 겪는
    네트워크 비용(예전 상장폐지·리브랜딩 종목이 많아 야후 파이낸스 레이트리밋에 자주 걸림)이 크다.
    이미 h14가 이 풀을 계산해둔 full_2019_2026/gfc_2008에서는 캐시로 저렴하므로 그대로 계산하고,
    나머지 3개 창은 holdings_corr(보유종목 3~10개, 이미 h11/h18/h33이 캐시해둔 종목들)만 계산해
    비용을 감당 가능한 수준으로 낮춘다 - 본문에서 이 비대칭을 명시적으로 disclose한다."""
    t0 = time.time()
    log(f"=== {label}: 코어 구축 {full_start}~{full_end} (pool_signal={include_pool_signal}) ===")
    core = build_core(label, full_start, full_end)
    trading_index = core["ret_net"].index
    excl = set(THREE_ASSET_UNIVERSE) if label == "gfc_2008" else set(CHAMPION_UNIVERSE)

    log("  새틀라이트(정적보유, point-in-time, 추세추종) 구축...")
    sat = build_satellite_returns_period(full_start, full_end, trading_index, exclude=excl, method="trend_following")

    if include_pool_signal:
        log("  풀 breadth/상관관계 신호 구축...")
        pool_breadth, pool_corr, pool_log = build_pool_breadth_and_correlation(full_start, full_end, trading_index)
    else:
        log("  풀 신호 생략(비용 절감) - breadth/pool_corr는 NaN(스위치 항상 ON)으로 채움")
        pool_breadth = pd.Series(np.nan, index=trading_index[(trading_index >= pd.Timestamp(full_start)) & (trading_index <= pd.Timestamp(full_end))])
        pool_corr = pool_breadth.copy()
        pool_log = []

    log("  보유종목 상관관계 신호 구축...")
    holdings_corr = build_holdings_correlation(sat["rebal_log"], sat["tickers_ever_held"], full_start, full_end, trading_index)

    spy_bull_raw = fetch_spy_regime_signal(full_start, full_end)
    spy_bull = spy_bull_raw.reindex(trading_index).ffill()

    if include_pool_signal:
        breadth_bull = signal_to_bull(pool_breadth, "breadth")
    else:
        breadth_bull = pd.Series(True, index=pool_breadth.index, name="bull")  # NaN 채움 대신 명시적 "항상 ON"(no-op)
    dd = build_drawdown_signal(sat["ret_net"])
    dd_bull = signal_to_bull(dd, "drawdown")

    z_variants = {}
    for z in Z_THRESHOLDS:
        pc_bull, pc_z = corr_zscore_bull(pool_corr, z_thresh=z)
        hc_bull, hc_z = corr_zscore_bull(holdings_corr, z_thresh=z)
        z_variants[z] = {"pool_corr_bull": pc_bull, "holdings_corr_bull": hc_bull,
                          "pool_corr_z": pc_z, "holdings_corr_z": hc_z}

    pc_bull_central = z_variants[Z_CENTRAL]["pool_corr_bull"]
    hc_bull_central = z_variants[Z_CENTRAL]["holdings_corr_bull"]
    spy_or_poolcorr = combined_signal(spy_bull, pc_bull_central, "or")
    spy_or_holdcorr = combined_signal(spy_bull, hc_bull_central, "or")

    signals_central = {
        "spy": spy_bull, "pool_breadth": breadth_bull, "sat_drawdown": dd_bull,
        "pool_corr": pc_bull_central, "holdings_corr": hc_bull_central,
        "spy_or_pool_corr": spy_or_poolcorr, "spy_or_holdings_corr": spy_or_holdcorr,
    }

    static_blend = blend_returns(core["ret_net"], sat["ret_net"], SATELLITE_WEIGHT_ON)
    windows = {"full_period": (full_start, full_end), "crisis_window": (crisis_start, crisis_end)}
    if extra_windows:
        windows.update(extra_windows)
    table = {}
    switched_series = {}
    for wname, (ws, we) in windows.items():
        row = {"core_alone": perf_metrics_slice(core["ret_net"], ws, we),
               "core_plus_static_satellite": perf_metrics_slice(static_blend, ws, we)}
        for sname, bull in signals_central.items():
            wser = build_regime_switched_weight_series(trading_index, bull, SATELLITE_WEIGHT_ON)
            blended = blend_returns_time_varying(core["ret_net"], sat["ret_net"], wser)
            row[f"switch_{sname}"] = perf_metrics_slice(blended, ws, we)
            if wname == "full_period":
                switched_series[f"switch_{sname}"] = blended
        table[wname] = row
    switched_series["core_alone"] = core["ret_net"]
    switched_series["core_plus_static_satellite"] = static_blend

    # z-threshold 견고성(로버스트니스) 스윕: pool_corr/holdings_corr만, crisis_window 기준 Sharpe
    z_sweep = {}
    for z in Z_THRESHOLDS:
        pc_bull = z_variants[z]["pool_corr_bull"]
        hc_bull = z_variants[z]["holdings_corr_bull"]
        pc_w = build_regime_switched_weight_series(trading_index, pc_bull, SATELLITE_WEIGHT_ON)
        hc_w = build_regime_switched_weight_series(trading_index, hc_bull, SATELLITE_WEIGHT_ON)
        pc_blend = blend_returns_time_varying(core["ret_net"], sat["ret_net"], pc_w)
        hc_blend = blend_returns_time_varying(core["ret_net"], sat["ret_net"], hc_w)
        z_sweep[str(z)] = {
            "pool_corr_crisis": perf_metrics_slice(pc_blend, crisis_start, crisis_end),
            "holdings_corr_crisis": perf_metrics_slice(hc_blend, crisis_start, crisis_end),
        }

    result = {
        "label": label, "full_period": [full_start, full_end], "crisis_window": [crisis_start, crisis_end],
        "windows": table, "z_threshold_sweep": z_sweep, "pool_signal_computed": include_pool_signal,
        "n_satellite_rebals": len(sat["rebal_log"]), "satellite_tickers_ever_held": sat["tickers_ever_held"],
        "elapsed_s": round(time.time() - t0, 1),
    }
    log(f"  {label} 완료 ({result['elapsed_s']}s)")
    return result, switched_series, {
        "pool_breadth": pool_breadth, "pool_corr": pool_corr, "holdings_corr": holdings_corr,
        "spy_bull": spy_bull, "pool_corr_bull": pc_bull_central, "holdings_corr_bull": hc_bull_central,
        "rebal_log": sat["rebal_log"],
    }


# ---------------------------------------------------------------------------
# 2021년 성장주 언와인드 사례 재검증 (H15 후속)
# ---------------------------------------------------------------------------

def case_study_2021(series: dict) -> dict:
    spy_bull = series["spy_bull"]
    pool_corr_bull = series["pool_corr_bull"]
    holdings_corr_bull = series["holdings_corr_bull"]
    pool_corr = series["pool_corr"]
    holdings_corr = series["holdings_corr"]

    window_start, window_end = "2021-09-01", "2022-03-31"
    idx = spy_bull.index
    win_idx = idx[(idx >= window_start) & (idx <= window_end)]

    def first_bear_date(bull: pd.Series, after: str) -> str | None:
        s = bull.reindex(win_idx).ffill()
        s = s[s.index >= after]
        bear = s[~s]
        return str(bear.index[0].date()) if len(bear) else None

    peak_date = pd.Timestamp("2021-11-19")
    spy_off = first_bear_date(spy_bull, str(peak_date.date()))
    pool_corr_off = first_bear_date(pool_corr_bull, str(peak_date.date()))
    holdings_corr_off = first_bear_date(holdings_corr_bull, str(peak_date.date()))

    def days_from_peak(date_str):
        if date_str is None:
            return None
        return int(idx.get_indexer([pd.Timestamp(date_str)])[0] - idx.get_indexer([peak_date])[0])

    return {
        "window": [window_start, window_end],
        "peak_date": str(peak_date.date()),
        "spy_switch_off_date": spy_off, "spy_days_from_peak": days_from_peak(spy_off),
        "pool_corr_off_date": pool_corr_off, "pool_corr_days_from_peak": days_from_peak(pool_corr_off),
        "holdings_corr_off_date": holdings_corr_off, "holdings_corr_days_from_peak": days_from_peak(holdings_corr_off),
        "pool_corr_series_window": {str(d.date()): (None if pd.isna(v) else round(float(v), 4))
                                     for d, v in pool_corr.reindex(win_idx).items()},
        "holdings_corr_series_window": {str(d.date()): (None if pd.isna(v) else round(float(v), 4))
                                         for d, v in holdings_corr.reindex(win_idx).items()},
    }


# ---------------------------------------------------------------------------
# 기댓값 재구성 (H22 기저확률 재사용)
# ---------------------------------------------------------------------------

def expected_value_table(episodes: dict, configs: list[str]) -> dict:
    out = {}
    for scen_name, rates in BASE_RATE_SCENARIOS.items():
        total = sum(rates.values())
        w = {k: v / total for k, v in rates.items()}
        ev = {cfg: {"sharpe": 0.0, "cagr": 0.0} for cfg in configs}
        for ep, wt in w.items():
            wname = "full_period" if ep == "full_2019_2026" else "crisis_window"
            row = episodes[ep]["windows"][wname]
            for cfg in configs:
                m = row.get(cfg)
                if m is None or m.get("sharpe") is None:
                    continue
                ev[cfg]["sharpe"] += wt * m["sharpe"]
                ev[cfg]["cagr"] += wt * m["cagr"]
        out[scen_name] = ev
    return out


def main():
    t0 = time.time()
    episodes = {}
    all_series = {}
    signal_series = {}
    # bear_2022의 full_period(2019-08-12~2026-08-19)는 full_2019_2026과 정확히 동일한 구간이므로
    # 코어+새틀라이트+풀 신호를 두 번 만들 필요가 없다 - full_2019_2026을 만들 때 bear_2022의
    # 위기창을 extra_windows로 같이 슬라이스해 재사용한다(h11/h12/h14/h33 등 이 프로그램 전체가
    # "2019-08~2026-08 전체기간은 한 번만 계산하고 2022년은 그 슬라이스"라는 관례를 지켜온 것과 동일).
    bear2022_fs, bear2022_fe, bear2022_cs, bear2022_ce = EPISODES["bear_2022"]
    fresh_labels = [l for l in EPISODE_ORDER if l != "bear_2022"]
    # full_2019_2026/gfc_2008은 작업35(H14)가 이미 이 풀(40종목)의 breadth를 계산해봐서 point-in-time
    # 샘플링·가격이력 캐시가 이미 있어 저렴하다. covid_2020/selloff_2018/correction_2015_2016은 H14가
    # 한 번도 다루지 않은 기간이라 처음부터 캐시가 없고, 옛 상장폐지·리브랜딩 종목이 많아 야후
    # 파이낸스 레이트리밋에 자주 걸려 비용이 훨씬 크다(실측: 스모크테스트에서 280초 안에 이 창 하나의
    # 풀 신호도 못 끝냄) - 이 3개 창은 풀 신호를 생략하고 holdings_corr(보유종목 3~10개, 이미
    # 캐시됨)만 계산한다. 본문에서 이 비대칭을 disclose한다.
    POOL_SIGNAL_LABELS = {"full_2019_2026", "gfc_2008"}
    for label in fresh_labels:
        fs, fe, cs, ce = EPISODES[label]
        extra = {"bear_2022_crisis": (bear2022_cs, bear2022_ce)} if label == "full_2019_2026" else None
        result, series, sig = run_episode(label, fs, fe, cs, ce, extra_windows=extra,
                                           include_pool_signal=(label in POOL_SIGNAL_LABELS))
        episodes[label] = result
        all_series[label] = series
        signal_series[label] = sig

    full_res = episodes["full_2019_2026"]
    episodes["bear_2022"] = {
        "label": "bear_2022", "full_period": [bear2022_fs, bear2022_fe], "crisis_window": [bear2022_cs, bear2022_ce],
        "windows": {"full_period": full_res["windows"]["full_period"],
                    "crisis_window": full_res["windows"]["bear_2022_crisis"]},
        "z_threshold_sweep": {}, "pool_signal_computed": full_res["pool_signal_computed"],
        "note": "full_2019_2026과 동일한 코어+새틀라이트+신호 구축을 재사용, 위기창만 슬라이스(재계산 없음)",
        "n_satellite_rebals": full_res["n_satellite_rebals"],
        "satellite_tickers_ever_held": full_res["satellite_tickers_ever_held"],
    }
    all_series["bear_2022"] = all_series["full_2019_2026"]  # 부트스트랩 CSV는 full_2019_2026 것을 그대로 슬라이스해서 씀

    configs = ["core_alone", "core_plus_static_satellite", "switch_spy", "switch_pool_breadth",
               "switch_sat_drawdown", "switch_pool_corr", "switch_holdings_corr",
               "switch_spy_or_pool_corr", "switch_spy_or_holdings_corr"]

    # 기댓값(4절)에는 pool_corr 계열을 넣지 않는다 - 6개 창 중 3개(covid_2020/selloff_2018/
    # correction_2015_2016, 기저확률 합 37%)에서 계산 자체를 생략했기 때문에(비용/레이트리밋), 그
    # 창들에서는 "스위치 없음"과 트리비얼하게 같은 값이 들어가 기댓값이 왜곡된다. holdings_corr는
    # 6개 창 전부에서 실제로 계산됐으므로 기댓값 대상에 포함한다.
    ev_configs = ["core_alone", "core_plus_static_satellite", "switch_spy",
                  "switch_holdings_corr", "switch_spy_or_holdings_corr"]
    ev = expected_value_table(episodes, ev_configs)

    case2021 = case_study_2021(signal_series["full_2019_2026"])

    # 부트스트랩용 원자료(일별수익률) 저장 - full_2019_2026/gfc_2008/covid_2020/selloff_2018/
    # correction_2015_2016 5개(bear_2022는 full_2019_2026 CSV를 그대로 재사용하므로 별도 저장 불필요)
    boot_configs = ["core_alone", "core_plus_static_satellite", "switch_spy", "switch_holdings_corr", "switch_spy_or_holdings_corr"]
    for label in fresh_labels:
        series = all_series[label]
        for cfg in boot_configs:
            s = series[cfg]
            s.to_frame(cfg).to_csv(OUT_DIR / f"{label}_{cfg}.csv")
        sig = signal_series[label]
        bulls = pd.DataFrame({"pool_corr_bull": sig["pool_corr_bull"], "holdings_corr_bull": sig["holdings_corr_bull"],
                               "spy_bull": sig["spy_bull"]})
        bulls.to_csv(OUT_DIR / f"{label}_bull_signals.csv")

    result = {
        "meta": {
            "generated": pd.Timestamp.today().strftime("%Y-%m-%d"),
            "corr_window": CORR_WINDOW, "z_lookback": Z_LOOKBACK, "z_thresholds": Z_THRESHOLDS,
            "z_central": Z_CENTRAL, "episode_order": EPISODE_ORDER, "configs": configs,
            "satellite_weight_on": SATELLITE_WEIGHT_ON, "boot_configs": boot_configs,
        },
        "episodes": episodes,
        "expected_value": ev,
        "case_study_2021": case2021,
        "base_rate_scenarios": BASE_RATE_SCENARIOS,
    }
    with open(OUT_DIR / "h_corr_results.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    log(f"저장 완료: h_corr_results.json (총 {time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
