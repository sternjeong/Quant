"""crash-rebound-signal-v1 — 과거 정보만 쓰는 신호, 사건 구분, 쌍 비교, 스모크, 포착기(네트워크 없음)."""

from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("crash_rebound_signal_v1", ROOT / "research" / "jobs" / "crash-rebound-signal-v1" / "run.py")
mod = importlib.util.module_from_spec(_spec)
import sys  # noqa: E402

sys.modules["crash_rebound_signal_v1"] = mod
_spec.loader.exec_module(mod)

_sspec = importlib.util.spec_from_file_location("crash_rebound_scan", ROOT / "scripts" / "crash_rebound_scan.py")
scan_mod = importlib.util.module_from_spec(_sspec)
_sspec.loader.exec_module(scan_mod)


def _crash_path(n_up=300, n_down=60, n_rebound=300, seed=0):
    r = np.random.default_rng(seed)
    ret = np.concatenate([np.full(n_up, 0.001), np.full(n_down, -0.006), np.full(n_rebound, 0.002)]) + r.normal(0, 0.008, n_up + n_down + n_rebound)
    idx = pd.bdate_range("2001-01-01", periods=len(ret))
    return pd.Series(100 * np.cumprod(1 + ret), index=idx)


def test_signals_use_only_past_data():
    close = _crash_path()
    epu = mod.load_news()
    base = mod.state_frame(close, mod.MKT_CRASH, mod.MKT_END, epu)
    cut = 400
    pert = close.copy()
    pert.iloc[cut + 1:] *= np.random.default_rng(5).uniform(0.5, 1.5, len(pert) - cut - 1)
    alt = mod.state_frame(pert, mod.MKT_CRASH, mod.MKT_END, epu)
    cols = ["dd", "rsi", "ma20", "vol21", "episode", "days_since_low", *mod.SIGNALS]
    pd.testing.assert_frame_equal(base[cols].iloc[:cut + 1], alt[cols].iloc[:cut + 1])
    assert base["episode"].max() >= 0  # 실제로 급락 사건이 있었다


def test_news_uses_publication_lag():
    epu = pd.Series([100.0, 200.0, 300.0], index=pd.PeriodIndex(["2020-01", "2020-02", "2020-03"], freq="M"))
    d = mod.news_daily(epu, pd.DatetimeIndex(["2020-02-03", "2020-03-31"]))
    assert list(d) == [100.0, 200.0]  # 2월에는 1월 값, 3월에는 2월 값


def test_episode_detection_start_and_end():
    idx = pd.bdate_range("2000-01-03", periods=400)
    c = np.full(400, 100.0)
    c[260:270] = np.linspace(100, 80, 10)   # 265 근처에서 −15% 돌파
    c[270:300] = 80.0
    c[300:310] = np.linspace(80, 99, 10)    # −5% 위로 회복 → 종료
    c[310:] = 99.0
    fr = mod.state_frame(pd.Series(c, index=idx), mod.MKT_CRASH, mod.MKT_END)
    eps = mod.episodes(fr)
    assert len(eps) == 1
    st, en, open_ = eps[0]
    assert fr["dd"].iloc[st] <= -0.15 < fr["dd"].iloc[st - 1]
    assert fr["dd"].iloc[en] <= -0.05 < fr["dd"].iloc[en + 1]
    assert not open_
    assert fr["DEEPER"].sum() == 0  # −25% 까지는 안 갔다


def test_paired_outcome_and_stats():
    idx = pd.bdate_range("2000-01-03", periods=40)
    c = pd.Series(100.0, index=idx)
    fr = pd.DataFrame({"close": c})
    for s in mod.SIGNALS:
        fr[s] = False
    c.iloc[5:] = 90.0     # 진입 다음 날 바로 하락
    c.iloc[20:] = 120.0
    fr["close"] = c
    fr.loc[idx[10], "FTD"] = True  # 10 일 신호 → 11 일 90 에 매수
    rf = np.zeros(40)
    o = mod.episode_outcome(fr, rf, (2, 30, False), h=25)  # 진입 3 (100), 끝 28 (120)
    assert o["signals"]["FTD"]["D"] == pytest.approx(math.log(120 / 90) - math.log(120 / 100))
    assert o["signals"]["FTD"]["delay"] == 8
    assert o["signals"]["RSI_LT30"]["D"] == pytest.approx(-math.log(1.2))  # 안 켜짐 → 끝까지 현금
    assert o["signals"]["RSI_LT30"]["pain_diff"] == pytest.approx(0 - (-0.10))
    assert mod.episode_outcome(fr, rf, (2, 30, False), h=40) is None  # 자료 밖
    st = mod.paired_stats([0.1, 0.2, 0.15, 0.12])
    assert st["n"] == 4 and st["p"] < 0.01 and st["needed_effect"] > 0
    cl = mod.clustered_stats({"A": [0.1, 0.3], "B": [0.1], "C": []})
    assert cl["n_stocks"] == 2 and cl["n_episodes"] == 3 and cl["mean"] == pytest.approx(0.15)
    assert mod.t_sf(mod.t_crit(0.01, 9), 9) == pytest.approx(0.01, abs=1e-6)


def _blk(mean, p, pain, n):
    return {"mean": mean, "p": p, "pain_diff_median": pain, "n": n, "sd": 0.1, "n_stocks": n}


def test_judge_rules():
    def mk(**kw):
        sig = {s: _blk(0.05, 0.001, 0.01, 10) for s in mod.SIGNALS}
        sig.update(kw)
        return {"by_era": {e: {"horizons": {"250": {"signals": sig}}} for e in mod.ERAS}}

    bt = {"horizons": {"250": {"signals": {s: _blk(0.05, 0.001, 0.0, 10) for s in mod.SIGNALS}}}}
    j = mod.judge(mk(FTD=_blk(0.05, 0.2, 0.0, 10), DEEPER=_blk(0.05, 0.001, 0.0, 3), VOL_FADE=_blk(-0.05, 0.9, 0.0, 10)), bt)
    assert j["verdicts"]["RSI_LT30"] == "SIGNAL_HELPS"
    assert j["verdicts"]["FTD"] == "FAIL" and j["detail"]["FTD"]["fail_kind"] == "FAIL_UNDERPOWERED"
    assert j["verdicts"]["DEEPER"] == "NOT_EVALUABLE"
    assert j["verdicts"]["VOL_FADE"] == "FAIL" and j["detail"]["VOL_FADE"]["fail_kind"] == "FAIL"


def test_smoke_end_to_end(tmp_path):
    rc = mod.main(["--smoke", "--out", str(tmp_path / "o"), "--checkpoint", str(tmp_path / "c")])
    assert rc == 0
    res = json.loads((tmp_path / "o" / "results.json").read_text(encoding="utf-8"))
    assert set(res["verdicts"]) == set(mod.SIGNALS)
    assert all(v in {"SIGNAL_HELPS", "FAIL", "NOT_EVALUABLE"} for v in res["verdicts"].values())
    assert "power" in res and res["market"]["by_era"]["A"]["n_episodes"] > 0
    rep = (tmp_path / "o" / "REPORT.md").read_text(encoding="utf-8")
    assert "현재 상태" in rep and "생존 편향" in rep


def test_scanner_offline():
    prices = mod.synthetic_prices(("SPY", "AAPL", "NVDA"), seed=3)
    states = scan_mod.scan(prices, mod.load_news())
    assert set(states) == {"SPY", "AAPL", "NVDA"}
    assert states["SPY"]["crash_th"] == mod.MKT_CRASH and states["AAPL"]["crash_th"] == mod.STK_CRASH
    txt = scan_mod.render(states, None)
    assert "읽기 전용" in txt and "SPY" in txt and "판정: 아직 없음" in txt
    txt2 = scan_mod.render(states, {s: "FAIL" for s in mod.SIGNALS})
    assert "통과한 신호 없음" in txt2


def test_job_json_valid():
    from core import research_jobs as rj

    job = json.loads((ROOT / "research" / "jobs" / "crash-rebound-signal-v1" / "job.json").read_text(encoding="utf-8"))
    rj.validate_job(job, "crash-rebound-signal-v1")
