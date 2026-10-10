"""guru-mechanism-v1 (거장 보유 우선 메커니즘 시험) — 위약 크기, 13F 시점 규칙, 체크포인트 이어하기, 판정 규칙."""

import importlib.util
import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "research/jobs/guru-mechanism-v1/run.py"
_spec = importlib.util.spec_from_file_location("guru_mechanism_v1", PATH)
gm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gm)


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    """스모크를 끊어서(3) 이어 하기(0), 그리고 한 번에 돌린 것과 비교용."""
    base = tmp_path_factory.mktemp("gm")
    mp = pytest.MonkeyPatch()
    mp.setitem(gm.SMOKE, "n_placebo", 40)
    mp.setitem(gm.SMOKE, "batch", 10)
    mp.delenv("RESEARCH_JOB_DEADLINE_EPOCH", raising=False)
    a = ["--smoke", "--out", str(base / "a/out"), "--checkpoint", str(base / "a/ck")]
    codes = [gm.main(a + ["--max-batches-per-run", "2"]), gm.main(a)]
    b = ["--smoke", "--out", str(base / "b/out"), "--checkpoint", str(base / "b/ck")]
    codes.append(gm.main(b))
    mp.undo()
    return base, codes


def test_checkpoint_resume_3_then_0_and_matches_uninterrupted(runs):
    base, codes = runs
    assert codes == [3, 0, 0]
    ra = json.loads((base / "a/out/results.json").read_text())
    rb = json.loads((base / "b/out/results.json").read_text())
    assert ra["p2"] == rb["p2"] and ra["p2"]["n"] == 40
    assert ra["variants"] == rb["variants"]
    assert ra["verdicts"]["guru_mechanism"].startswith("SMOKE_ONLY")
    assert ra["replication"]["decomposition_matches_run_variant"] is True
    assert (base / "a/out/REPORT.md").exists()
    st = json.loads((base / "a/ck/state.json").read_text())
    assert st["p2"]["next"] == 40 and len(st["p2"]["is"]) == 40


def test_placebo_sets_have_g1_boosted_size(runs):
    base, _ = runs
    st = json.loads((base / "a/ck/state.json").read_text())
    checked = 0
    for k, row in st["panel"].items():
        if not row or not row["guru_known"]:
            continue
        n = len(gm.g1_boost_set(row))
        caps = st["mcaps"][k]
        assert len(gm.mcap_boost_set(row, caps, n)) == min(n, sum(v is not None for v in caps.values()))
        rng = np.random.default_rng([gm.P2_SEED, 0])
        s = gm.random_boost_set(row, n, rng)
        assert len(s) == n and s <= set(row["base"])
        checked += 1
    assert checked >= 10


def test_placebo_set_size_toy():
    row = {"base": {"A": 0.5, "B": 0.4, "C": 0.3, "D": 0.2}, "holders": {"C": ["g1"], "D": ["g2", "g1"]}}
    n = len(gm.g1_boost_set(row))
    assert n == 2
    assert gm.mcap_boost_set(row, {"A": 10.0, "B": 30.0, "C": 20.0, "D": None}, n) == {"B", "C"}
    assert len(gm.random_boost_set(row, n, np.random.default_rng(1))) == 2
    assert gm.g1_boost_set(row, drop="g1") == {"D"}
    assert gm.g1_boost_set(row, only="g2") == {"D"}
    # 우선 집합이 모멘텀보다 앞선다 — S-SEED-019 의 +1000
    assert gm.boosted_picks(row["base"], list(row["base"]), {"C", "D"}, 3) == ["C", "D", "A"]


def _filing(filed, period, tickers):
    return {"filed": filed, "period": period, "holdings": [{"ticker": t, "weight": 1 / len(tickers)} for t in tickers]}


def test_guru_data_uses_only_filings_before_rebalance():
    d = pd.Timestamp("2015-01-02")  # 리밸런싱일
    cutoff = date(2014, 12, 31)      # 전날
    per = {"g1": [_filing("2014-11-14", "2014-09-30", ["AAA"]), _filing("2015-01-02", "2014-12-31", ["BBB"])],
           "g2": [_filing("2014-12-31", "2014-09-30", ["CCC"])]}
    assert gm.holders_at(per, "AAA", cutoff) == ["g1"]
    assert gm.holders_at(per, "BBB", cutoff) == []          # 리밸런싱 당일 공시는 아직 모름
    assert gm.holders_at(per, "CCC", cutoff) == ["g2"]       # 전날까지 공시된 것은 앎
    assert not gm.any_filing_known({"g1": [_filing("2015-01-02", "2014-12-31", ["AAA"])]}, cutoff)


def test_panel_ignores_filings_on_or_after_rebalance_day():
    import core.satellite_lab as sl

    pp, pool = sl.synthetic_providers(n_tickers=20, start="2012-01-01", end="2016-12-30")
    data = sl.build_data({gm.POOL}, start="2014-01-01", end="2016-12-30", pool_provider=pool, price_provider=pp)
    seed0, code0 = sl.read_variant_dir(sl.SEEDS_DIR / gm.INCUMBENT_ID)
    spec0 = sl.validate_spec({**seed0, "pool": {"type": gm.POOL}})
    sig = sl.load_signal(code0)
    d = sl.rebalance_dates(data.trading_days, 6)[2]
    names = sorted(t for t in data.ohlcv if t != "SPY")
    per = {"g1": [_filing("2014-08-14", "2014-06-30", names[:3])]}
    row = gm.build_panel_row(data, d, spec0, sig, {"mom_window": 252}, per)
    late = {"g1": per["g1"] + [_filing(d.date().isoformat(), "2015-03-31", names)],
            "g2": [_filing((d.date() + timedelta(days=30)).isoformat(), "2015-03-31", names)]}
    row2 = gm.build_panel_row(data, d, spec0, sig, {"mom_window": 252}, late)
    assert row["base"], "추세 후보가 있어야 시험이 의미 있음"
    assert row["holders"] == row2["holders"]
    assert row["cutoff"] < d.date().isoformat()


def test_decide_rules():
    p2 = list(np.linspace(-1, 1, 101))
    ok = {g: 0.2 for g in gm.GURUS}
    assert gm.decide(0.99, p2, 0.1, ok)["verdict"] == "GURU_MECHANISM_SUPPORTED"
    r = gm.decide(0.99, p2, 1.5, ok)
    assert r["verdict"] == "PARTIAL" and r["failed"] == ["b"]
    five = dict(ok, **{gm.GURUS[0]: -0.1, gm.GURUS[1]: -0.1})
    assert gm.decide(0.99, p2, 0.1, five)["failed"] == ["c"]
    six = dict(ok, **{gm.GURUS[0]: -0.1})
    assert gm.decide(0.99, p2, 0.1, six)["verdict"] == "GURU_MECHANISM_SUPPORTED"
    assert gm.decide(0.5, p2, 1.5, ok)["verdict"] == "NOT_SUPPORTED"
    assert gm.decide(0.99, p2, 0.1, ok, g1_noop="같음")["verdict"] == "NOT_EVALUABLE"
    assert gm.decide(0.99, p2, 0.1, ok, mcap_coverage=0.5)["verdict"] == "NOT_EVALUABLE"
    assert gm.decide(0.99, p2, 0.1, ok, decomposition_ok=False)["verdict"] == "NOT_EVALUABLE"


def test_job_json_meets_contract():
    from core.research_jobs import validate_job

    data = json.loads((ROOT / "research/jobs/guru-mechanism-v1/job.json").read_text(encoding="utf-8"))
    job, err = validate_job(data, "guru-mechanism-v1", ROOT)
    assert job is not None, err
    assert job.resumable and job.priority == 9
