"""sat-earnings-v1 (실적 발표 직전 매수 피하기) 사전 등록 규칙 테스트 — 합성 데이터만, 네트워크 없음."""

import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("sat_earnings_v1", ROOT / "research/jobs/sat-earnings-v1/run.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["sat_earnings_v1"] = mod
    spec.loader.exec_module(mod)
    return mod


mod = _load()
T = pd.Timestamp
DAYS = pd.bdate_range("2010-01-01", "2011-12-31")


def _fl(exp):
    """예상일이 exp 가 되도록 하는 제출 이력(exp − 91일)."""
    return [str((T(exp) - pd.Timedelta(days=91)).date())]


def test_expected_date_uses_only_filings_before_d():
    d = T("2010-07-01")
    assert mod.expected_date(["2010-04-20", "2010-07-01", "2010-07-05"], d) == T("2010-04-20") + pd.Timedelta(days=91)
    assert mod.expected_date(["2010-07-01"], d) is None          # d 당일 제출은 '이전'이 아님
    assert mod.expected_date([], d) is None
    e = mod.expected_date(["2009-01-10"], d)                     # 91일씩 더해 d 이상
    assert e >= d and (e - T("2009-01-10")).days % 91 == 0 and e - pd.Timedelta(days=91) < d
    assert mod.expected_date(_fl("2010-07-01"), d) == d


def test_imminent_window_edges():
    d = T("2010-07-01")
    w_end = mod.window_end(DAYS, d)
    assert w_end == DAYS[DAYS.searchsorted(d, side="right") + 6]
    assert mod.is_imminent(_fl("2010-07-02"), d, DAYS)[0]                       # d+1 포함
    assert mod.is_imminent(_fl(str(w_end.date())), d, DAYS)[0]                  # 7번째 거래일 포함
    assert not mod.is_imminent(_fl(str((w_end + pd.Timedelta(days=1)).date())), d, DAYS)[0]
    assert not mod.is_imminent(_fl("2010-07-01"), d, DAYS)[0]                   # d 당일은 창 밖
    assert mod.is_imminent([], d, DAYS) == (False, None)                        # 이력 없음 = 임박 아님


def test_e1_delay_buy_day():
    assert mod.delay_buy_day(DAYS, T("2010-07-07")) == T("2010-07-09")   # 수 → 목, 금
    assert mod.delay_buy_day(DAYS, T("2010-07-10")) == T("2010-07-13")   # 토 → 월, 화
    assert mod.delay_buy_day(DAYS, T("2010-07-08")) == T("2010-07-12")


def test_e2_replacement_next_non_imminent():
    order = ["A", "B", "C", "D", "E", "F"]
    picks, swaps = mod.select_e2(order, lambda t: t in {"B", "D"})
    assert picks == ["A", "E", "C"] and swaps == [("B", "E")]
    picks, _ = mod.select_e2(order, lambda t: t in {"A", "B"})
    assert picks == ["D", "E", "C"]
    picks, swaps = mod.select_e2(["A", "B", "C", "D"], lambda t: t in {"A", "D"})
    assert picks == ["A", "B", "C"] and swaps == [("A", None)]


def test_build_schedules_variants():
    d = T("2010-07-01")
    scores = {d: {"A": 3.0, "B": 2.0, "C": 1.0, "D": 0.5}}
    filings = {"B": _fl("2010-07-06"), "C": ["2010-07-01"]}   # C 는 d 당일 제출뿐 → 이력 없음
    b = mod.build_schedules([d], scores, filings, DAYS)
    s = b["schedules"]
    assert s["E0"][0]["picks"] == ["A", "B", "C"]
    assert s["E1"][0]["delayed"] == {"B": T("2010-07-08")}
    assert s["E2"][0]["picks"] == ["A", "D", "C"]
    assert b["imminent_log"][0]["imminent"] == ["B"] and set(b["imminent_log"][0]["no_history"]) == {"A", "C"}


def test_e1_weights_swap_only_cash_on_buy_day():
    idx = pd.bdate_range("2010-01-04", "2010-12-31")
    core = pd.DataFrame({"X": 1.0}, index=idx)
    rng = np.random.default_rng(2)
    adj = pd.DataFrame({t: 50 * np.exp(np.cumsum(rng.normal(0, 0.01, len(idx)))) for t in ("X", "A", "B", "C", "BIL")},
                       index=idx)
    adj[mod.SAT_CASH] = adj["BIL"]
    b = T("2010-01-15")
    rows = [{"date": T("2010-01-04"), "picks": ["A", "B", "C"], "delayed": {"B": b}, "swaps": []},
            {"date": T("2010-07-01"), "picks": ["A", "B", "C"], "delayed": {}, "swaps": []}]
    w = mod.variant_weights(core, rows, adj)
    assert abs(w.loc[T("2010-01-04"), mod.SAT_CASH] - 0.05) < 1e-12 and w.loc[T("2010-01-04"), "B"] == 0.0
    cols = ["X", "A", "C", mod.SAT_CASH]
    start = w.loc[T("2010-01-04"), cols]
    assert (w.loc[:T("2010-01-14"), cols].diff().abs().sum(axis=1).iloc[1:] < 1e-12).all()   # 매수 전에는 목표 그대로
    cur = w.loc[b]
    assert cur[mod.SAT_CASH] == 0.0 and cur["B"] > 0
    # 매수일 목표 = 첫날부터 표류한 비중에서 현금 몫만 B 로(X·A·C 는 표류값 그대로라 매매 없음)
    g = start * (adj.loc[b, cols] / adj.loc[T("2010-01-04"), cols])
    drift = g / g.sum()
    assert np.allclose(cur[["X", "A", "C"]].to_numpy(), drift[["X", "A", "C"]].to_numpy())
    assert abs(cur["B"] - drift[mod.SAT_CASH]) < 1e-12
    assert (w.loc[b:T("2010-06-30")].diff().abs().sum(axis=1).iloc[1:] < 1e-12).all()
    assert abs(w.loc[T("2010-07-01"), "B"] - 0.05) < 1e-12          # 다음 재선정일은 기본 목표


def _synthetic_data():
    from core import satellite_lab as sl

    pp, poolp = sl.synthetic_providers(n_tickers=30, start="2008-01-01", end="2013-12-31", seed=3)
    pool = mod.SV._pool_wrapper(poolp, date.fromisoformat(mod.START))
    return sl, sl.build_data({"champion40"}, start="2009-12-01", end="2013-12-31", pool_provider=pool, price_provider=pp)


def test_e0_equals_satellite_value_champion():
    sl, data = _synthetic_data()
    sc = mod.score_inputs(data)
    built = mod.build_schedules(sc["dates"], sc["pool_scores"], {}, data.trading_days)
    e0 = built["schedules"]["E0"]
    spec, code = sl.read_variant_dir(sl.SEEDS_DIR / sl.INCUMBENT_ID)
    ref = sl.run_variant(spec, dict(spec["signal"]["params_grid"][0]), sl.load_signal(code), data)["schedule"]
    assert [(str(r["date"].date()), r["picks"]) for r in e0] == [(d, p) for d, p in ref]
    idx = data.trading_days[data.trading_days >= T(mod.START)]
    core = pd.DataFrame({"X": 1.0}, index=idx)
    w = mod.variant_weights(core, e0, pd.DataFrame(index=idx))
    pd.testing.assert_frame_equal(w, mod.tx.champion_weights(core, mod.SV.schedule_to_log(ref), mod.SAT_WEIGHT))
    assert [r["picks"] for r in built["schedules"]["E2"]] == [r["picks"] for r in e0]   # 이력 없으면 E2 = E0
    assert not any(r["delayed"] for r in built["schedules"]["E1"])


def test_pass_rule_edges():
    ok = dict(diff=0.001, h1=0.001, h2=0.001, sharpe_v=0.81, sharpe_0=0.80, mdd_v=-0.20, mdd_0=-0.19, ci_low=-0.004)
    assert mod.decide(**ok) == mod.PASS
    assert mod.decide(**{**ok, "diff": 0.0}) == mod.FAIL
    assert mod.decide(**{**ok, "h1": 0.0}) == mod.FAIL
    assert mod.decide(**{**ok, "h2": -0.001}) == mod.FAIL
    assert mod.decide(**{**ok, "sharpe_v": 0.80}) == mod.FAIL
    assert mod.decide(**{**ok, "mdd_v": -0.2101}) == mod.FAIL
    assert mod.decide(**{**ok, "mdd_v": -0.2099}) == mod.PASS
    assert mod.decide(**{**ok, "ci_low": -0.005}) == mod.FAIL
    assert mod.decide(**{**ok, "ci_low": float("nan")}) == mod.NOT_EVALUABLE
    assert mod.decide(**ok, noop="임박 사례 없음") == mod.NOT_EVALUABLE
    pw = mod.rp.power_report(14.7, 2)
    assert mod.decide(**{**ok, "diff": -0.01}, observed_ir=0.1, power=pw) in ("FAIL", "FAIL_UNDERPOWERED")


def test_bootstrap_deterministic():
    rng = np.random.default_rng(0)
    a, b = rng.normal(0.0004, 0.01, 800), rng.normal(0.0003, 0.01, 800)
    x, y = mod.block_bootstrap_diff(a, b, 252.0), mod.block_bootstrap_diff(a, b, 252.0)
    assert len(x) == 1000 and np.array_equal(x, y) and mod.BOOT_SEED == 20261021


def test_job_contract():
    job = json.loads((ROOT / "research/jobs/sat-earnings-v1/job.json").read_text(encoding="utf-8"))
    assert job["id"] == "sat-earnings-v1" and job["priority"] == 11 and job["resumable"] is True
    assert job["summary_from"] == "verdicts" and job["max_memory_mb"] <= 2500
    assert job["entrypoint"] == "research/jobs/sat-earnings-v1/run.py"
    assert (ROOT / "research/jobs/sat-earnings-v1/SPEC.md").exists()
    assert mod.N_TRIALS == 2 and mod.JUDGED == ("E1", "E2")


def test_smoke_resume(tmp_path):
    out, ck = tmp_path / "o", tmp_path / "c"
    assert mod.main(["--smoke", "--out", str(out), "--checkpoint", str(ck), "--max-steps-per-run", "2"]) == 3
    assert mod.main(["--smoke", "--out", str(out), "--checkpoint", str(ck)]) == 0
    r = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert set(r["verdicts"]) == set(mod.JUDGED) and all(v.startswith("SMOKE_ONLY(") for v in r["verdicts"].values())
    assert all(r["smoke_coverage"].values())
    assert (out / "results.json").stat().st_size < 200_000
    assert "스모크" in (out / "REPORT.md").read_text(encoding="utf-8")
