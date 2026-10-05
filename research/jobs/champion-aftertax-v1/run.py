"""측정 champion-aftertax-v1 (2026-10-06): 실제로 쓰는 배분(코어 85% + 새틀라이트 15%)을 2010년부터 세후·환전 후 원화로.

판정 없음 — 숫자를 재는 작업이다(엔진 변경 제안 없음). 화면 '세후 수익 계산'은 새벽 계산의 최근 3년만 쓸 수 있어서
(새틀라이트 백테스트가 반기마다 S&P500 을 다시 훑어 1년 ≈ 2분 이상), 긴 기간은 VM 연구 실행기에서 한 번 잰다.
계좌 가정: core/tax_fx.py 기본값(카카오페이증권 — 수수료 0.1%, 달러 보유·스프레드 0.05%, 양도세 250만 원 공제 후 22%,
이동평균, 배당 원천징수 15% 즉시 재투자), 초기 3,000만 원. 참고로 매번 원화 환전(우대 0%)·1억 원도 잰다.
새틀라이트 선정은 run_champion_backtest(균등가중)와 같은 반기 point-in-time 기록을 쓴다.
한계: 새틀라이트 후보가 현재 S&P500 명단이라 생존편향이 남는다(실제보다 좋게 나올 수 있음). 두 슬리브 사이를 매일 맞추지 않는다.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from core import tax_fx as tx  # noqa: E402

START = "2010-01-01"


def _real():
    from core import champion_strategy as cs
    from core.market_data import get_multiple_price_history

    bt = cs.run_champion_backtest(START, date.today().isoformat())
    log = bt["satellite"]["rebal_log"]
    core_w = cs.run_core_backtest(START)["weights"]
    champ = tx.champion_weights(core_w, log, cs.SATELLITE_WEIGHT)
    tick = list(dict.fromkeys(list(champ.columns) + ["SPY"]))
    hist = get_multiple_price_history(tick, start="2009-06-01", end=None, interval="1d")
    close = pd.DataFrame({t: hist[t]["Close"] for t in tick if t in hist and not hist[t].empty}).ffill()
    adj = pd.DataFrame({t: hist[t]["Adj Close"] for t in tick if t in hist and not hist[t].empty}).ffill()
    return champ, core_w.reindex(champ.index).fillna(0.0), close, adj, tx.usdkrw_series(), log, bt.get("metrics")


def _smoke():
    idx = pd.bdate_range("2010-01-04", "2013-12-31")
    rng = np.random.default_rng(5)
    names = ["C1", "C2", "S1", "S2", "S3", "SPY"]
    close = pd.DataFrame({t: 50 * np.exp(np.cumsum(rng.normal(0.0004, 0.012, len(idx)))) for t in names}, index=idx)
    core_w = pd.DataFrame(0.0, index=idx, columns=["C1", "C2"])
    core_w.loc[core_w.index.month % 2 == 0, "C1"] = 1.0
    core_w.loc[core_w.index.month % 2 == 1, "C2"] = 1.0
    log = [{"date": "2010-01-04", "weights": {"S1": 0.5, "S2": 0.5}}, {"date": "2011-07-01", "weights": {"S2": 0.5, "S3": 0.5}}]
    champ = tx.champion_weights(core_w, log, 0.15)
    return champ, core_w.reindex(champ.index).fillna(0.0), close, close, pd.Series(1100.0, index=idx), log, None


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--smoke", action="store_true")
    a = p.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    champ, core_w, close, adj, fx, log, bt_metrics = _smoke() if a.smoke else _real()
    spy_w = tx.buy_and_hold_weights(champ.index)
    setups = {"base_30m": {}, "krw_each_trade": {"fx_mode": "krw_each_trade", "fx_spread": 0.01},
              "base_100m": {"initial_krw": 100_000_000}}
    years = (champ.index[-1] - champ.index[0]).days / 365.25
    metrics = {}
    for sname, over in setups.items():
        cfg = tx.AccountConfig(**over)
        for name, w in (("champion", champ), ("core_only", core_w), ("spy", spy_w)):
            r = tx.simulate(w, close, adj, fx, cfg)
            liq = (r["final_after_liquidation_krw"] / cfg.initial_krw) ** (1 / years) - 1
            metrics.setdefault(sname, {})[name] = {
                "cagr_pre": r["cagr_pre"], "cagr_after": r["cagr_after"], "cagr_after_liquidation": liq,
                "mdd_after": r["mdd_after"], "final_krw": r["final_krw"],
                "final_after_liquidation_krw": r["final_after_liquidation_krw"],
                "totals": r["totals"], "years": r["years"]}
    b = metrics["base_30m"]
    summary = {k: f"세전 {v['cagr_pre']:.2%} → 세후 {v['cagr_after']:.2%} (청산 후 {v['cagr_after_liquidation']:.2%}), 원화 MDD {v['mdd_after']:.1%}"
               for k, v in b.items()}
    result = {"kind": "measurement (판정 없음)", "smoke": a.smoke, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "start": str(champ.index[0].date()), "end": str(champ.index[-1].date()), "summary": summary,
              "metrics": metrics, "satellite_rebalances": len(log), "backtest_metrics_usd": bt_metrics}
    (out / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    names = {"champion": "코어 85% + 새틀라이트 15%", "core_only": "코어만", "spy": "SPY 그냥 보유"}
    lines = [f"# 챔피언 세후·환전 후 원화 수익 (측정, 판정 없음){' — 스모크' if a.smoke else ''}", "",
             f"기간 {result['start']} ~ {result['end']}, 새틀라이트 반기 선정 {len(log)}회. 초기 3,000만 원, 카카오페이증권 가정.", "",
             "| | 세전 | 세후·비용후 | 지금 다 팔면 | 원화 MDD | 양도세(백만) | 수수료(백만) | 배당세(백만) |", "|---|---|---|---|---|---|---|---|"]
    for k, v in b.items():
        t = v["totals"]
        lines.append(f"| {names[k]} | {v['cagr_pre']:.2%} | {v['cagr_after']:.2%} | {v['cagr_after_liquidation']:.2%} | {v['mdd_after']:.1%} | "
                     f"{t['capital_gains_tax_krw'] / 1e6:.1f} | {t['fees_krw'] / 1e6:.1f} | {t['dividend_tax_krw'] / 1e6:.1f} |")
    for sname, title in (("krw_each_trade", "매번 원화 환전(우대 0%)"), ("base_100m", "초기 1억 원")):
        lines += ["", f"참고 — {title}: " + ", ".join(f"{names[k]} 세후 {v['cagr_after']:.2%}" for k, v in metrics[sname].items())]
    lines += ["", "한계: 새틀라이트 후보가 현재 S&P500 명단(생존편향 — 실제보다 좋게 나올 수 있음), 일봉 종가 체결, 슬리브 사이 매일 재조정 없음, 금융소득 종합과세 미반영. 과거 결과이며 앞으로의 수익을 뜻하지 않는다."]
    (out / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
