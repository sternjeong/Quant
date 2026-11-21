"""news-core-combo-v1 규칙 기계 장치(사전 등록 규칙이 의도대로 계산되는지 — 미래 정보 차단, 지연, 필터·기울기 발동)."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def _mod():
    name = "news_core_combo_run"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / "research/jobs/news-core-combo-v1/run.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


nc = _mod()
lab = nc.lab


def _toy(n=700, k=6, seed=3):
    idx = pd.bdate_range("2001-01-01", periods=n)
    rng = np.random.default_rng(seed)
    rets = pd.DataFrame(rng.normal(0.0005, 0.01, (n, k)) + np.linspace(-0.001, 0.001, k), index=idx,
                        columns=[f"I{j}" for j in range(k)])
    mkt = pd.Series(rng.normal(0.0003, 0.01, n), index=idx)
    return rets, mkt, pd.Series(0.0001, index=idx)


def _state(idx, nr_value, lag=1):
    months = pd.period_range(idx[0].to_period("M") - 200, idx[-1].to_period("M"), freq="M")
    u = pd.Series(np.random.default_rng(0).normal(size=len(months)), index=months)
    return {"nr": pd.Series(nr_value, index=months), "u": u, "lag": lag}


def test_b0_reproduces_core_longrun_rule():
    rets, mkt, _ = _toy()
    w, act = nc.news_weights(rets, mkt, nc.B0, None)
    pd.testing.assert_frame_equal(w, lab.target_weights(rets, mkt, lab.Rule()))
    assert act["filter_changed"] == 0 and act["picks_changed"] == 0


def test_pct_trailing_and_news_state_lag():
    x = pd.Series([1.0, 3, 2, 5, 4], index=pd.period_range("2000-01", periods=5, freq="M"))
    p = nc.pct_trailing(x, window=3)
    assert np.isnan(p.iloc[1]) and p.iloc[2] == 2 / 3 and p.iloc[3] == 1.0 and p.iloc[4] == 2 / 3
    news = nc.load_news()
    s1, s2 = nc.news_state(news, 1), nc.news_state(news, 2)
    m = pd.Period("1990-06", "M")
    assert s1["nr"][m] == s2["nr"][m + 1]
    # 지수 달 m 이후 값을 바꿔도 리밸런싱 달 m 의 NR(지연 1)은 그대로 — 미래 정보 없음
    n2 = news.copy()
    n2.loc[n2.index >= m, :] *= 10
    assert nc.news_state(n2, 1)["nr"][m] == s1["nr"][m]
    # 마지막 지수 달 다음 달까지 상태가 있다(라이브 리밸런싱용)
    assert np.isfinite(s1["nr"][news.index[-1] + 1])


def test_sensitivities_use_only_months_up_to_m_minus_lag():
    months = pd.period_range("2000-01", periods=200, freq="M")
    rng = np.random.default_rng(1)
    u = pd.Series(rng.normal(size=200), index=months)
    ex = pd.DataFrame({"a": 2 * u + rng.normal(0, 0.1, 200), "b": -u + rng.normal(0, 0.1, 200)}, index=months)
    m = months[150]
    b = nc.sensitivities(ex, u, m, 1, [0, 1])
    assert abs(b[0] - 2) < 0.1 and abs(b[1] + 1) < 0.1
    ex2 = ex.copy()
    ex2.loc[ex2.index >= m] = 99.0
    assert nc.sensitivities(ex2, u, m, 1, [0, 1]) == b
    assert nc.sensitivities(ex, u, months[40], 1, [0, 1]) == {}  # 60개월 미만


def test_filters_fire_as_registered():
    idx = pd.bdate_range("2001-01-01", periods=400)
    rets = pd.DataFrame({"A": 0.002, "B": 0.0015, "C": 0.001, "D": 0.0005, "E": 0.0003}, index=idx)
    down = pd.Series(-0.001, index=idx)   # 시장이 계속 내려 200일선 아래
    up = pd.Series(0.001, index=idx)
    base = nc.news_weights(rets, down, nc.B0, None)[0].iloc[-1].sum()
    assert abs(base - 0.5) < 1e-12
    calm = nc.news_weights(rets, down, nc.CANDIDATES[0], _state(idx, 0.3))[0].iloc[-1].sum()
    loud = nc.news_weights(rets, down, nc.CANDIDATES[0], _state(idx, 0.8))[0].iloc[-1].sum()
    assert abs(calm - 1.0) < 1e-12 and abs(loud - 0.5) < 1e-12        # N1: 조용한 하락은 줄이지 않음
    up_shock = nc.news_weights(rets, up, nc.CANDIDATES[1], _state(idx, 0.95))[0].iloc[-1].sum()
    assert abs(up_shock - 1.0) < 1e-12                                 # N2: 시장 상승 중이면 극단이어도 그대로
    wobble = up.copy()
    wobble.iloc[-25:] = -0.002                                         # 200일선 위지만 직전 21일 하락
    early = nc.news_weights(rets, wobble, nc.CANDIDATES[1], _state(idx, 0.95))[0].iloc[-1].sum()
    same = nc.news_weights(rets, wobble, nc.CANDIDATES[1], _state(idx, 0.5))[0].iloc[-1].sum()
    assert abs(early - 0.5) < 1e-12 and abs(same - 1.0) < 1e-12
    # 뉴스 상태 결측 → B0 대로
    nan_state = nc.news_weights(rets, down, nc.CANDIDATES[0], _state(idx, np.nan))[0].iloc[-1].sum()
    assert abs(nan_state - 0.5) < 1e-12


def test_tilt_changes_picks_only_in_high_news_months():
    rets, mkt, _ = _toy(n=3200, k=8)
    idx = rets.index
    low = nc.news_weights(rets, mkt, nc.CANDIDATES[2], _state(idx, 0.5))
    high = nc.news_weights(rets, mkt, nc.CANDIDATES[2], _state(idx, 0.9))
    pd.testing.assert_frame_equal(low[0], nc.news_weights(rets, mkt, nc.B0, None)[0])
    assert low[1]["tilt_months"] == 0 and high[1]["tilt_months"] > 0 and high[1]["picks_changed"] > 0
    assert ((high[0] > 0).sum(axis=1) <= 4).all()


def test_job_definition_valid():
    from core import research_jobs as rj

    data = json.loads((ROOT / "research/jobs/news-core-combo-v1/job.json").read_text(encoding="utf-8"))
    job, err = rj.validate_job(data, "news-core-combo-v1", ROOT)
    assert job is not None, err


def test_smoke_runs_offline(tmp_path):
    p = subprocess.run([sys.executable, str(ROOT / "research/jobs/news-core-combo-v1/run.py"), "--smoke",
                        "--out", str(tmp_path / "o"), "--checkpoint", str(tmp_path / "c")],
                       cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert p.returncode == 0, p.stderr[-1500:]
    res = json.loads((tmp_path / "o" / "results.json").read_text(encoding="utf-8"))
    assert res["smoke"] and res["power"]["n_trials"] == 4 and res["b0_reproduction_max_abs_diff"] == 0
    assert {"N1_confirm", "N2_early", "N3_tilt", "N4_full", "overall"} <= set(res["verdicts"])
    assert "검정력(사전 계산)" in (tmp_path / "o" / "REPORT.md").read_text(encoding="utf-8")
