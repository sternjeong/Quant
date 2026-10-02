"""코어 R&D(core/core_lab.py) — 현 코어 재현, 각 변형 옵션의 동작, 심판 구조, 연구 스크립트 스모크."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import core.champion_strategy as cs
from core import core_lab as cl

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def prices():
    idx = pd.bdate_range("2010-01-01", "2015-12-31")
    rng = np.random.default_rng(5)
    tickers = list(cs.CORE_UNIVERSE) + ["SPY", "BIL"]
    data = {t: 50 * np.exp(np.cumsum(rng.normal(rng.uniform(-0.0002, 0.0006), 0.012, len(idx)))) for t in tickers}
    data["BIL"] = 90 * np.exp(np.cumsum(np.full(len(idx), 0.0001)))
    frame = pd.DataFrame(data, index=idx)
    return frame[list(cs.CORE_UNIVERSE)], frame[["SPY", "BIL", "HYG", "IEF"]]


def test_incumbent_reproduces_live_engine(prices):
    closes, extra = prices
    start = "2011-06-01"
    w = cs._build_core_weights(closes, extra["SPY"])
    keep = closes.index >= pd.Timestamp(start)
    live = cs._compute_portfolio_returns(closes[keep], w[keep], cost_bps_per_side=cs.CORE_COST_BPS_PER_SIDE)["ret_net"]
    lab = cl.run(closes, extra, cl.CoreConfig(), start)
    assert np.allclose(lab.values, live.values, atol=1e-12)


def test_cash_bil_fills_unallocated(prices):
    closes, extra = prices
    w = cl.build_weights(closes, extra, cl.CoreConfig(cash="bil"))
    late = w.iloc[-1]
    assert late.sum() == pytest.approx(1.0)
    assert "BIL" in w.columns


def test_tranche_offsets_change_rebalance_days():
    idx = pd.bdate_range("2021-03-01", "2021-04-30")
    m0 = cl._first_trading_day_mask(idx, 0)
    m7 = cl._first_trading_day_mask(idx, 7)
    assert list(idx[m0]) == [pd.Timestamp("2021-03-01"), pd.Timestamp("2021-04-01")]
    assert list(idx[m7]) == [pd.Timestamp("2021-03-08"), pd.Timestamp("2021-04-08")]


def test_corr_cap_skips_near_duplicate():
    idx = pd.bdate_range("2019-01-01", "2021-06-30")
    rng = np.random.default_rng(1)
    base = rng.normal(0.001, 0.01, len(idx))
    data = {t: 50 * np.exp(np.cumsum(rng.normal(-0.0005, 0.01, len(idx)))) for t in cs.CORE_UNIVERSE}
    data["XLE"] = 50 * np.exp(np.cumsum(base))
    data["DBC"] = 50 * np.exp(np.cumsum(base + rng.normal(0, 0.001, len(idx))))  # XLE 와 거의 같은 움직임
    closes = pd.DataFrame(data, index=idx)
    extra = pd.DataFrame({"SPY": np.linspace(100, 200, len(idx)), "BIL": 90.0}, index=idx)
    plain = cl.build_weights(closes, extra, cl.CoreConfig()).iloc[-1]
    capped = cl.build_weights(closes, extra, cl.CoreConfig(corr_cap=0.8)).iloc[-1]
    assert plain["XLE"] > 0 and plain["DBC"] > 0
    assert (capped["XLE"] > 0) != (capped["DBC"] > 0)


def test_rank_buffer_reduces_turnover(prices):
    closes, extra = prices
    plain = cl.build_weights(closes, extra, cl.CoreConfig())
    buf = cl.build_weights(closes, extra, cl.CoreConfig(buffer_n=7))
    t = lambda w: float(w.diff().abs().sum(axis=1).sum())  # noqa: E731
    assert t(buf) <= t(plain)


def test_asset_trend_filter_drops_downtrend_assets(prices):
    closes, extra = prices
    w = cl.build_weights(closes, extra, cl.CoreConfig(market_filter="asset_sma", filter_window=210))
    sma = closes.rolling(210).mean()
    sd = closes.index[-2]
    reb = w.index[w.diff().abs().sum(axis=1) > 0]
    for d in reb[-3:]:
        prev = closes.index[closes.index.get_loc(d) - 1]
        for t in w.columns:
            if w.at[d, t] > 0 and pd.notna(sma.at[prev, t]):
                assert closes.at[prev, t] >= sma.at[prev, t]
    assert sd is not None


def test_judge_structure(prices):
    closes, extra = prices
    inc = cl.run(closes, extra, cl.CoreConfig(), "2011-06-01")
    var = cl.run(closes, extra, cl.CoreConfig(cash="bil"), "2011-06-01")
    res = cl.judge({"returns": var}, inc, [], n_trials=12, all_active_daily_srs=[])
    assert set(res["gates"]) == {"G1_improves_corrected", "G2_holdout", "G3_subperiods", "G4_neighbors", "G5_drawdown"}
    assert res["verdict"] in ("PASS", "FAIL")
    json.dumps(res)
    same = cl.judge({"returns": inc}, inc, [], n_trials=12, all_active_daily_srs=[])
    assert same["verdict"] == "FAIL"  # 현 코어 자신은 개선이 아니다


def test_research_job_smoke(tmp_path):
    p = subprocess.run([sys.executable, str(ROOT / "research/jobs/core-rnd-v1/run.py"), "--smoke",
                        "--out", str(tmp_path / "out"), "--checkpoint", str(tmp_path / "ck")],
                       cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert p.returncode == 0, p.stdout[-1500:] + p.stderr[-1500:]
    res = json.loads((tmp_path / "out" / "results.json").read_text(encoding="utf-8"))
    assert res["n_trials"] == 12 and len(res["verdicts"]) == 12 and res["smoke"] is True
    assert "스모크" in (tmp_path / "out" / "REPORT.md").read_text(encoding="utf-8")


def test_job_definition_is_valid():
    from core import research_jobs as rj

    data = json.loads((ROOT / "research/jobs/core-rnd-v1/job.json").read_text(encoding="utf-8"))
    job, err = rj.validate_job(data, "core-rnd-v1", ROOT)
    assert job is not None, err
