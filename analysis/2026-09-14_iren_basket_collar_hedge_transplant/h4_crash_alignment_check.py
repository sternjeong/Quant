"""H4 (반박/정직성 점검) - 콜라가 실제로 이 바스켓 고유의 최악 낙폭을 방어하는가, 아니면 SPY만
방어하고 바스켓 특이적(idiosyncratic) 크래시는 그냥 못 잡는가.

H1~H3가 "왜" 콜라가 도움이 안 되는지에 대한 구조적 설명을 제공한다: 이 바스켓의 크래시가 SPY의
크래시와 같은 시점에 일어나지 않는다면, SPY 옵션은 애초에 방어할 기회조차 없다. 이 가설은 그
구조적 원인을 직접 확인한다 - `iren_beta_alpha_hedging_research`가 이미 정리한 "이 종목군 초과
수익 자체가 베타"라는 결론과 짝을 이루는 반대쪽 절반("그런데 이 바스켓의 최악 낙폭은 그 베타로
설명되는가?")이다.

방법론: 바스켓 정적매수후보유 자산곡선에서 가장 깊은 낙폭구간(peak-to-trough) top-5를 찾고, 그
구간 동안 (a) SPY도 같은 방향으로 낙폭 중이었는지(SPY 자체의 동시 낙폭 %), (b) 그 구간에 걸친
콜라 롤 사이클들의 실제 net_payoff(풋 수취 - 콜 지급)가 방어에 기여했는지를 대조한다. 새 지표를
발명하지 않고 h1_h2가 이미 저장한 롤 로그(roll_log)와 collar_overlay_ret.csv를 그대로 사용한다.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from hedge_common import OUT_DIR, END, get_price_history


def log(msg):
    print(f"[h4] {msg}", flush=True)


def top_drawdown_episodes(ret: pd.Series, top_n: int = 5) -> list[dict]:
    equity = (1.0 + ret.fillna(0.0)).cumprod()
    running_max = equity.cummax()
    drawdown = equity / running_max - 1.0

    episodes = []
    in_dd = False
    start_idx = None
    peak_val = None
    for i, (dt, dd) in enumerate(drawdown.items()):
        if dd < -1e-9 and not in_dd:
            in_dd = True
            start_idx = i
            peak_val = running_max.iloc[i]
        elif dd >= -1e-9 and in_dd:
            in_dd = False
            window = drawdown.iloc[start_idx:i]
            trough_pos = window.values.argmin()
            trough_idx = start_idx + trough_pos
            episodes.append({
                "peak_date": str(drawdown.index[start_idx].date()),
                "trough_date": str(drawdown.index[trough_idx].date()),
                "recovery_date": str(dt.date()),
                "depth_pct": round(float(window.min()) * 100, 2),
            })
    if in_dd:
        window = drawdown.iloc[start_idx:]
        trough_pos = window.values.argmin()
        trough_idx = start_idx + trough_pos
        episodes.append({
            "peak_date": str(drawdown.index[start_idx].date()),
            "trough_date": str(drawdown.index[trough_idx].date()),
            "recovery_date": "미회복(구간 끝까지)",
            "depth_pct": round(float(window.min()) * 100, 2),
        })
    episodes.sort(key=lambda e: e["depth_pct"])
    return episodes[:top_n]


def spy_return_over(spy_close: pd.Series, start: str, end: str) -> float | None:
    s = spy_close[(spy_close.index >= start) & (spy_close.index <= end)]
    if len(s) < 2:
        return None
    return round(float(s.iloc[-1] / s.iloc[0] - 1.0) * 100, 2)


def rolls_overlapping(roll_log: list[dict], start: str, end: str) -> list[dict]:
    out = []
    for r in roll_log:
        if r["roll_date"] <= end and r["expiry_date"] >= start:
            out.append(r)
    return out


def main():
    with open(OUT_DIR / "h1_h2_results.json", encoding="utf-8") as f:
        h1h2 = json.load(f)

    basket_bh_ret = pd.read_csv(OUT_DIR / "basket_bh_unhedged_ret.csv", index_col=0, parse_dates=True)["ret"]
    basket_trend_ret = pd.read_csv(OUT_DIR / "basket_trend_unhedged_ret.csv", index_col=0, parse_dates=True)["ret"]

    spy = get_price_history("SPY", start=basket_bh_ret.index[0].date().isoformat(), end=END, use_cache=True)["Close"]
    spy.index = pd.DatetimeIndex(spy.index).normalize()

    out = {"meta": {"generated": END}, "episodes": {}}
    for label, ret in [("basket_bh", basket_bh_ret), ("basket_trend", basket_trend_ret)]:
        episodes = top_drawdown_episodes(ret, top_n=5)
        roll_log = h1h2["roll_logs"][label]
        for ep in episodes:
            ep["spy_return_over_same_window_pct"] = spy_return_over(spy, ep["peak_date"], ep["trough_date"])
            overlapping_rolls = rolls_overlapping(roll_log, ep["peak_date"], ep["trough_date"])
            total_payoff = sum(r["net_payoff_pct"] for r in overlapping_rolls)
            total_premium = sum(r["net_premium_pct"] for r in overlapping_rolls)
            ep["n_overlapping_collar_rolls"] = len(overlapping_rolls)
            ep["collar_net_payoff_pct_sum"] = round(total_payoff * 100, 3)
            ep["collar_net_premium_pct_sum"] = round(total_premium * 100, 3)
            ep["collar_net_contribution_pct_sum"] = round((total_payoff + total_premium) * 100, 3)
        out["episodes"][label] = episodes
        log(f"{label}:")
        for ep in episodes:
            log(f"  {ep['peak_date']}~{ep['trough_date']} 바스켓{ep['depth_pct']}% "
                f"vs SPY동시구간{ep['spy_return_over_same_window_pct']}% | "
                f"콜라기여 {ep['collar_net_contribution_pct_sum']}%p ({ep['n_overlapping_collar_rolls']}개 롤)")

    with open(OUT_DIR / "h4_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    log("저장 완료: h4_results.json")


if __name__ == "__main__":
    main()
