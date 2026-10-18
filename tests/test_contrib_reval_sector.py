"""contrib-reval-sector-v1 사전 등록 규칙 테스트 — 합성 데이터만, 네트워크 없음."""

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
JOB = "contrib-reval-sector-v1"


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


mod = _load("contrib_reval_sector_v1_t", f"research/jobs/{JOB}/run.py")
ft3 = mod.ft3
ssb = mod.ssb


def test_job_contract_via_loader():
    from core.research_jobs import Config, load_job_definitions

    valid, invalid = load_job_definitions(Config.for_root(ROOT))
    assert JOB in valid, invalid.get(JOB)
    job = json.loads((ROOT / f"research/jobs/{JOB}/job.json").read_text(encoding="utf-8"))
    assert job["priority"] == 23 and job["resumable"] is True and job["max_memory_mb"] <= 2000
    assert job["outputs"] == ["results.json", "REPORT.md"] and job["summary_from"] == "verdicts"
    assert (ROOT / f"research/jobs/{JOB}/SPEC.md").exists()


def test_pre_registered_constants():
    assert mod.STRATEGIES == ("SC2", "SC2VT20", "BL30", "BL50") and mod.N_TRIALS == 4
    assert mod.BLEND_W == {"BL30": 0.30, "BL50": 0.50}
    assert mod.SCENARIOS == {"B": (10_000_000, 150_000), "A": (10_000_000, 0), "C": (3_000_000, 150_000),
                             "B10": (100_000_000, 1_500_000)}
    assert mod.PRIMARY_SCENARIO == "B" and mod.POLICY == "underweight_first"
    assert mod.HORIZONS == (10, 5) and mod.PRIMARY_HORIZON == 10 and mod.STEP == "M"
    assert (mod.FIRST_START, mod.JUDGED_END) == ("2000-01-01", "2024-09-30")
    assert (mod.WIN_SHARE_MIN, mod.MEDIAN_IRR_MARGIN, mod.P10_IRR_FLOOR, mod.MDD_TW_TOL) == (0.70, 0.005, -0.015, 0.05)
    assert mod.POWER_YEARS == 24.7
    assert (ft3.VT_TARGET, ft3.VT_WINDOW, ft3.SC2_TOP, ft3.SC2_LOOKBACK) == (0.20, 126, 2, 252)
    cfg = mod.account("B")
    assert cfg.initial_krw == 10_000_000 and cfg.monthly_contribution_krw == 150_000
    assert cfg.contribution_policy == "underweight_first" and cfg.fee_rate == mod.tx.KAKAO_FEE and cfg.apply_tax


# ---------------------------------------------------------------- 합성 가격
def _etf_prices(n=1100, seed=3):
    idx = pd.bdate_range("2015-01-02", periods=n)
    rng = np.random.default_rng(seed)
    cols = list(ssb.ETF_MENU) + [ssb.SPY]
    mk = rng.normal(0.0004, 0.014, n)
    trend = rng.normal(0, 0.0007, (n // 120 + 1, len(cols)))[np.arange(n) // 120]
    ret = mk[:, None] * np.linspace(0.7, 1.3, len(cols)) + trend + rng.normal(0, 0.009, (n, len(cols)))
    adj = pd.DataFrame(50 * (1 + ret).cumprod(axis=0), index=idx, columns=cols)
    adj.loc[idx < idx[400], "XLC"] = np.nan
    adj.loc[idx < idx[300], "XLRE"] = np.nan
    adj["BIL"] = (90 * (1 + 0.00008) ** np.arange(n))
    adj.loc[idx < idx[500], "BIL"] = np.nan
    close = adj * 0.995
    return {"adj": adj, "close": close, "fx": pd.Series(1200.0, index=idx), "source": "t", "missing": []}


@pytest.fixture(scope="module")
def prepared():
    prep = ssb.etf_prepare(_etf_prices())
    return prep, ssb.sleeve_decisions(prep)


def test_sc2_and_sc2vt20_frames_equal_forward_tournament(prepared):
    prep, dec = prepared
    total = prep["total"]
    start = dec[0]["date"]
    sc2 = mod.sc2_frame(prep, dec, start)
    vt = mod.sc2vt_frame(prep, dec, start)
    by_i = {d["i"]: d for d in dec}
    seen_scaled = seen_bil = False
    for i, d in by_i.items():
        day = total.index[i]
        tgt = ft3.sc2_target(total.iloc[: i + 1])
        expo, _ = ft3.vol_exposure(ft3.sc2_backfill_window(total.iloc[: i + 1]))
        r_sc2, r_vt = sc2.loc[day], vt.loc[day]
        exp_sc2 = pd.Series(tgt["weights"]).reindex(sc2.columns).fillna(0.0)
        assert np.allclose(r_sc2.to_numpy(), exp_sc2.to_numpy(), atol=2e-8), d["date"]          # SC2 = sc2_target, 100% 투자
        assert r_sc2.sum() == pytest.approx(1.0, abs=2e-8)
        if d["bil"]:
            exp_vt = pd.Series(ft3.vt_inner(tgt["weights"], expo)).reindex(vt.columns).fillna(0.0)
            assert np.allclose(r_vt.to_numpy(), exp_vt.to_numpy(), atol=2e-8), d["date"]        # SC2VT20 = vt_inner(…)
            seen_bil |= expo < 0.999
        else:                                                                                    # BIL 전: 남는 몫 현금(0%)
            assert r_vt["BIL"] == 0 and r_vt.sum() == pytest.approx(expo, abs=2e-8)
        seen_scaled |= expo < 0.999
    assert seen_scaled and seen_bil
    # 결정일 사이에는 목표가 그대로(같은 행)
    nxt = [d["i"] for d in dec]
    a, b = nxt[5], nxt[6]
    blk = vt.iloc[a - nxt[0]: b - nxt[0]]
    assert (blk.diff().abs().sum(axis=1).iloc[1:] == 0).all()
    # 한 번 만든 표를 잘라 쓴 것 = 그 시작일로 새로 만든 것(소매 100% 는 시작일과 무관)
    s2 = dec[10]["date"]
    fresh = mod.sc2vt_frame(prep, dec, s2)
    sliced = vt.loc[pd.Timestamp(s2):]
    assert np.allclose(fresh.to_numpy(), sliced.to_numpy(), atol=2e-8)


def test_blend_january_reset_and_start_dependence(prepared):
    prep, dec = prepared
    w = 0.30
    idx = prep["adj"].index
    later = [d for d in dec if d["bil"] and pd.Timestamp(d["date"]).month in (3, 7)]
    s_a = next(d["date"] for d in later if pd.Timestamp(d["date"]).month == 3)
    s_b = next(d["date"] for d in later if pd.Timestamp(d["date"]).month == 7 and d["date"] > s_a)
    A = mod.blend_frame(prep, dec, w, s_a)
    B = mod.blend_frame(prep, dec, w, s_b)
    ref, _ = ssb.build_etf_weights(prep, dec, w, s_a, None)
    assert np.array_equal(A.to_numpy(), ref.to_numpy())                                         # spy-sector-blend-v1 PART E 그대로
    jan = [d for d in dec if pd.Timestamp(d["date"]).month == 1 and d["date"] > s_b]
    assert jan
    for d in jan:
        if "SPY" not in d["weights"]:
            assert A.loc[pd.Timestamp(d["date"]), "SPY"] == pytest.approx(1 - w, abs=1e-7)  # 1월에 SPY 70% 로 되돌림
    nonjan = [d for d in dec if pd.Timestamp(d["date"]).month != 1 and d["date"] > s_a and "SPY" not in d["weights"]]
    assert any(abs(A.loc[pd.Timestamp(d["date"]), "SPY"] - (1 - w)) > 1e-4 for d in nonjan)    # 그 사이에는 표류
    # 첫 1월 뒤에는 시작일과 무관(같은 비중), 그 전에는 다르다
    j0 = pd.Timestamp(jan[0]["date"])
    a_after, b_after = A.loc[j0:], B.loc[j0:]
    assert np.allclose(a_after.to_numpy(), b_after.to_numpy(), atol=2e-8)
    a_before = A[(A.index >= pd.Timestamp(s_b)) & (A.index < j0)]
    b_before = B[B.index < j0]
    assert len(a_before) == len(b_before) > 0
    assert not np.allclose(a_before.to_numpy(), b_before.to_numpy(), atol=1e-6)
    assert idx[0] < pd.Timestamp(s_a)


def test_turnover_counts_monthly_changes(prepared):
    prep, dec = prepared
    vt = mod.sc2vt_frame(prep, dec, dec[0]["date"])
    t = mod.turnover_per_year(vt, prep["rets"])
    assert 0 < t < 12
    spy = mod.tx.buy_and_hold_weights(vt.index, "SPY")
    assert mod.turnover_per_year(spy, prep["rets"]) == 0.0


# ---------------------------------------------------------------- 구간
def test_judged_windows_end_by_2024_09_30():
    days = pd.bdate_range("1998-12-01", "2026-10-16")
    p = mod.real_params()
    days = days[days >= pd.Timestamp("2000-01-03")]
    for hz, n_judged, last_start in ((10, 177, "2014-09-01"), (5, 237, "2019-09-02")):
        wins = mod.make_windows(days, hz, p)
        rows = [{"start": str(s.date()), "end": str(e.date())} for s, e in wins]
        judged, reported = mod.split_rows(rows, p["judged_end"])
        assert judged[0]["start"] == "2000-01-03"
        assert len(judged) == n_judged and judged[-1]["start"] == last_start
        assert all(pd.Timestamp(r["end"]) <= pd.Timestamp("2024-09-30") for r in judged)
        assert reported and all(pd.Timestamp(r["end"]) > pd.Timestamp("2024-09-30") for r in reported)
        assert len(judged) + len(reported) == len(wins)


# ---------------------------------------------------------------- 판정
def _s(win=0.70, med=0.005, p10=-0.015, mdd_s=-0.40, mdd_b=-0.35, n=177):
    return {"n_windows": n, "share_terminal_win": win, "median_diff_irr": med, "p10_diff_irr": p10,
            "median_strategy_mdd_tw": mdd_s, "median_benchmark_mdd_tw": mdd_b}


POWER = mod.rp.power_report(24.7, 4)


def test_verdict_edges():
    ch = mod.contrib_checks(_s())                                         # 모두 정확히 경계값 → 통과
    assert ch == {"win_share": True, "median_irr": True, "p10_irr": True, "mdd_tw": True}
    assert mod.contrib_verdict(ch, None, 0.1, POWER) == mod.PASS
    for kw, key in ((dict(win=0.6999), "win_share"), (dict(med=0.0049), "median_irr"), (dict(p10=-0.0151), "p10_irr"),
                    (dict(mdd_s=-0.4001), "mdd_tw")):
        c = mod.contrib_checks(_s(**kw))
        assert c[key] is False and sum(v is False for v in c.values()) == 1, key
        assert mod.contrib_verdict(c, None, 0.1, POWER) == "FAIL_UNDERPOWERED"   # 0 < IR < MDE
        assert mod.contrib_verdict(c, None, POWER["mde_ir"] + 0.01, POWER) == "FAIL"
        assert mod.contrib_verdict(c, None, -0.2, POWER) == "FAIL"
        assert mod.contrib_verdict(c, None, None, POWER) == "FAIL"
    assert mod.contrib_verdict(ch, "same", 0.1, POWER) == mod.NOT_EVALUABLE
    assert mod.contrib_checks({"n_windows": 0, "share_terminal_win": None}) is None
    assert mod.contrib_verdict(None, None, 0.1, POWER) == mod.NOT_EVALUABLE
    c = mod.contrib_checks(_s(med=float("nan")))
    assert c["median_irr"] is None and mod.contrib_verdict(c, None, 0.1, POWER) != mod.PASS


def test_information_ratio():
    a = np.array([0.01, 0.0, 0.02, -0.01])
    assert np.isnan(mod.information_ratio(a, a))
    d = a - np.zeros(4)
    assert mod.information_ratio(a, np.zeros(4)) == pytest.approx(d.mean() / d.std(ddof=1) * np.sqrt(252))


# ---------------------------------------------------------------- 스모크·재개
def test_smoke_resume(tmp_path):
    out, ck = tmp_path / "out", tmp_path / "ck"
    assert mod.main(["--smoke", "--out", str(out), "--checkpoint", str(ck), "--max-new-per-run", "40"]) == 3
    assert mod.main(["--smoke", "--out", str(out), "--checkpoint", str(ck)]) == 0
    raw = (out / "results.json").read_bytes()
    assert len(raw) < 200_000
    res = json.loads(raw)
    assert all(res["smoke_coverage"].values())
    assert all(res["verdicts"][n].startswith("SMOKE_ONLY") for n in mod.STRATEGIES)
    assert res["power"]["n_trials"] == 4 and res["power"]["years"] == 24.7
    assert len(res["contributions_change"]) == 4
    assert (out / "REPORT.md").read_text(encoding="utf-8").startswith("# 적립식 세후 재평가")
