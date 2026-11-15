"""sat-horizon-v1 — 점수는 r−1 까지 가격만 쓴다, 상위 5개 고르기·전진 수익·고르기/확인 판정 경로."""

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("sat_horizon_v1", ROOT / "research/jobs/sat-horizon-v1/run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_scores_ignore_prices_on_formation_day():
    m = _load()
    n_days, n = 300, 12
    px = np.tile(np.linspace(10, 20, n_days)[:, None], (1, n))
    px[:, 3] *= np.linspace(1, 3, n_days)  # 3번이 꾸준히 강함
    r = 280
    cols = np.arange(n)
    a = m.scores(px, r, cols)
    px2 = px.copy()
    px2[r:, :] = 1.0  # 형성일 이후 가격을 망가뜨려도 점수는 같아야 한다
    b = m.scores(px2, r, cols)
    for k in m.RULES:
        assert np.allclose(np.nan_to_num(a[k], nan=-9), np.nan_to_num(b[k], nan=-9)), k
    assert m.top_n(a["MOM12_1"])[0] == 3 and m.top_n(a["HIGH52"]).size == 5


def test_top_n_needs_enough_finite_scores_and_breaks_ties_by_column():
    m = _load()
    assert m.top_n(np.array([np.nan, 1, 2, np.nan, 3, 4])).size == 0
    assert list(m.top_n(np.array([1.0, 1, 1, 1, 1, 1]))) == [0, 1, 2, 3, 4]


def test_forward_return_uses_last_price_when_series_stops():
    m = _load()
    px = np.array([[10.0], [11.0], [12.0], [np.nan], [np.nan]])
    assert abs(m.fwd_returns(px, 0, 4, np.array([0]))[0] - 0.2) < 1e-12


def test_judge_picks_best_non_gambling_rule_in_selection_and_checks_confirm():
    m = _load()
    dates = pd.date_range("2002-01-01", "2024-01-01", freq="MS")
    rng = np.random.default_rng(0)
    t = pd.DataFrame(index=dates)
    t["end"] = dates + pd.Timedelta(days=200)
    t["rand_hit7"] = 0.1
    t["rand_mean"] = 0.0
    for k in m.RULES:
        t[k] = rng.normal(0.0, 0.05, len(dates))
        t[f"hit_stock_{k}"] = 0.2
        t[f"picks_{k}"] = "A,B,C,D,E"
    t["univ_hit7_stock"] = 0.15
    t["MOM6"] = rng.normal(0.12, 0.05, len(dates))           # 꾸준히 큰 초과 → 골라지고 통과
    t["LOTTERY"] = rng.normal(0.5, 0.05, len(dates))         # 보고만이라 골라지면 안 된다
    t["REV1M"] = np.where(np.arange(len(dates)) % 10 == 0, 3.0, -0.02)  # 평균 크지만 중앙값 < 0 → 자격 없음
    power = m.rp.power_report(11.75, 4)
    out = m.judge_horizon("6m", t, power)
    assert out["chosen"] == "MOM6"
    assert "REV1M" not in out["eligible_in_selection"]
    assert out["verdict"] == "TARGET_MET", out.get("checks")


def test_job_json_is_valid():
    from core import research_jobs as rj

    job, why = rj.validate_job(json.loads((ROOT / "research/jobs/sat-horizon-v1/job.json").read_text()), "sat-horizon-v1")
    assert job is not None, why
