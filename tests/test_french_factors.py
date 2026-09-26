"""Ken French 데이터 파서·캐시·Newey-West 회귀·팩터 노출·감쇠표 — 네트워크 없이 합성 데이터로."""

import io
import os
import time
import zipfile

import numpy as np
import pandas as pd
import pytest

from core import french_factors as ff

MONTHLY = """This file was created using the 202608 CRSP database.
Missing data are indicated by -99.99 or -999.

,Mkt-RF,SMB
192607,   2.89,  -2.42
192608,   2.64, -99.99

 Annual Factors: January-December
,Mkt-RF,SMB
1927,  29.47,  -2.04
"""
DAILY = "header text\n\n,Mom\n19261103,   0.55\n19261104,  -0.51\n\nCopyright 2026\n"


def _zip(text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("X.csv", text)
    return buf.getvalue()


def test_parse_monthly_reads_first_table_only_and_masks_missing():
    df = ff.parse_french_csv(MONTHLY)
    assert list(df.columns) == ["Mkt-RF", "SMB"] and len(df) == 2
    assert df.index[0] == pd.Timestamp("1926-07-31")
    assert df.iloc[0, 0] == pytest.approx(0.0289) and np.isnan(df.iloc[1, 1])


def test_parse_daily_and_crlf():
    df = ff.parse_french_csv(DAILY.replace("\n", "\r\n"))
    assert df.index.tolist() == [pd.Timestamp("1926-11-03"), pd.Timestamp("1926-11-04")]
    assert df["Mom"].tolist() == pytest.approx([0.0055, -0.0051])


def test_load_caches_then_falls_back_to_stale_cache():
    calls = []
    df = ff.load("mom_daily", fetch=lambda n: calls.append(n) or _zip(DAILY))
    assert calls == [ff.DATASETS["mom_daily"]] and len(df) == 2
    assert len(ff.load("mom_daily", fetch=lambda n: calls.append(n))) == 2 and len(calls) == 1  # 신선한 캐시
    path = ff.CACHE_DIR / "french_mom_daily.csv"
    old = time.time() - 30 * 86400
    os.utime(path, (old, old))
    def boom(_):
        raise OSError("down")
    assert len(ff.load("mom_daily", fetch=boom)) == 2  # 받기 실패 → 낡은 캐시
    assert ff.load("strev_monthly", fetch=boom) is None  # 캐시도 없으면 None


def test_ols_nw_recovers_coefficients():
    rng = np.random.default_rng(0)
    x = rng.normal(size=(3000, 2))
    y = 0.5 + 1.2 * x[:, 0] - 0.7 * x[:, 1] + rng.normal(0, 0.1, 3000)
    fit = ff.ols_nw(y, x, 5)
    assert fit["coef"] == pytest.approx([0.5, 1.2, -0.7], abs=0.01)
    assert fit["t"][0] > 50 and fit["r2"] > 0.99


def _factors(n=800, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2020-01-01", periods=n)
    f = pd.DataFrame(rng.normal(0, 0.01, (n, len(ff.DAILY_FACTORS))), index=idx, columns=ff.DAILY_FACTORS)
    f["RF"] = 0.0001
    return f


def test_factor_exposure_separates_clone_from_alpha():
    f = _factors()
    rng = np.random.default_rng(2)
    clone = f["RF"] + 1.0 * f["Mkt-RF"] + 0.8 * f["Mom"] + rng.normal(0, 0.001, len(f))
    out = ff.factor_exposure(clone, f)
    assert out["loadings"]["Mom"]["beta"] == pytest.approx(0.8, abs=0.02) and abs(out["alpha_t"]) < 2
    alpha = clone + 0.002
    assert ff.factor_exposure(alpha, f)["alpha_t"] > 2
    assert ff.factor_exposure(clone.iloc[:100], f) is None and ff.factor_exposure(clone, None) is None


def test_decay_table_splits_at_publication_year():
    idx = pd.date_range("1960-01-31", "2020-12-31", freq="ME")
    rng = np.random.default_rng(3)
    r = pd.Series(np.where(idx.year <= 1990, 0.01, 0.002), index=idx) + rng.normal(0, 0.02, len(idx))
    row = next(x for x in ff.decay_table(pd.DataFrame({"ST_Rev": r})) if x["factor"] == "ST_Rev")
    assert row["pre"]["end"] == "1990-12" and row["post"]["start"] == "1991-01"
    assert row["pre"]["mean_pct"] > row["post"]["mean_pct"] and 0 < row["post_to_pre"] < 0.5
    assert "| ST_Rev |" in ff.render_decay_markdown(ff.decay_table(pd.DataFrame({"ST_Rev": r})), "2026-09-26", "2020-12")


def test_judge_reports_factor_exposure_without_changing_verdict():
    from core import hypothesis_judge as hj
    from core import hypothesis_spec as hs
    from tests.test_hypothesis_core import _cliff_setup, spec

    provider, data = _cliff_setup()
    idx = data["SPY"].index
    f = pd.DataFrame(0.0, index=idx, columns=ff.DAILY_FACTORS + ["RF"])
    f["Mkt-RF"] = data["SPY"]["Close"].pct_change().fillna(0)
    f["Mom"] = np.random.default_rng(5).normal(0, 0.01, len(idx))
    code = "def score(p, a, k):\n    return {'GOOD': 1.0}\n"
    s = hs.validate(spec(universe={"type": "list", "tickers": ["GOOD", "BAD"]}, period={"start": "2019-06-01"},
                         signal={"params_grid": [{"lookback": 60}]}))
    kw = dict(cumulative_trials=1, prior_srs=[], price_provider=provider, champion_corr_fn=None, cost=(25.0, "t"))
    base = hj.judge({"spec": s, "signal_code": code}, **kw)
    with_f = hj.judge({"spec": s, "signal_code": code}, factors_fn=lambda: f, **kw)
    assert base["factor_exposure"] is None and with_f["factor_exposure"]["n_days"] > 252
    assert with_f["verdict"] == base["verdict"] and with_f["reasons"] == base["reasons"]
