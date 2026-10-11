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
    data["XLB"] = 50 * np.exp(np.cumsum(base + rng.normal(0, 0.001, len(idx))))  # XLE 와 거의 같은 움직임(2026-10-08 DBC 제외 후 XLB 로)
    closes = pd.DataFrame(data, index=idx)
    extra = pd.DataFrame({"SPY": np.linspace(100, 200, len(idx)), "BIL": 90.0}, index=idx)
    plain = cl.build_weights(closes, extra, cl.CoreConfig()).iloc[-1]
    capped = cl.build_weights(closes, extra, cl.CoreConfig(corr_cap=0.8)).iloc[-1]
    assert plain["XLE"] > 0 and plain["XLB"] > 0
    assert (capped["XLE"] > 0) != (capped["XLB"] > 0)


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
    # 2026-10-11: 현 코어 자신은 개선이 아니다 — 예전엔 FAIL, 이제는 기준선과 매일 같아 NOT_EVALUABLE(통과·탈락 기준은 그대로).
    assert same["verdict"] == "NOT_EVALUABLE" and same["verdict"] != "PASS"


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


# ---------------------------------------------------------------- rebound-rnd-v1 옵션 (2026-10-08)
def _rebound_market():
    """1년 하락 뒤 반등: SPY 가 200일선 아래로 갔다가 올라선다. 작년 승자 XLE 는 식고, XLK 는 반등 주도."""
    idx = pd.bdate_range("2020-01-01", "2023-12-29")
    n = len(idx)
    t = np.arange(n)
    crash = (idx >= "2022-01-01") & (idx < "2023-01-01")
    spy = 100 * np.exp(np.cumsum(np.where(crash, -0.0012, np.where(idx >= "2023-01-01", 0.003, 0.0008))))
    data = {a: 50 * np.exp(np.cumsum(np.full(n, -0.0006))) for a in cs.CORE_UNIVERSE}
    data["XLE"] = 50 * np.exp(np.cumsum(np.where(idx < "2023-01-01", 0.0015, -0.0015)))
    data["XLK"] = 50 * np.exp(np.cumsum(np.where(crash, -0.002, np.where(idx >= "2023-01-01", 0.004, 0.0005))))
    closes = pd.DataFrame(data, index=idx)
    extra = pd.DataFrame({"SPY": spy, "BIL": 90 + t * 0.001}, index=idx)
    return closes, extra


def test_bil_spy_fills_empty_slots_with_spy_only_in_bull_market():
    closes, extra = _rebound_market()
    w = cl.build_weights(closes, extra, cl.CoreConfig(cash="bil_spy"))
    feb23 = w.loc["2023-06-01":].iloc[0]
    assert feb23.get("SPY", 0) > 0 and feb23.sum() == pytest.approx(1.0)  # 빈 슬롯 → SPY
    bear = w.loc["2022-09-01":].iloc[0]
    assert bear.get("SPY", 0) == 0  # 200일선 아래면 SPY 로 채우지 않는다
    base = cl.build_weights(closes, extra, cl.CoreConfig(cash="bil"))
    assert "SPY" not in base.columns  # 기본은 그대로


def test_turnaround_switches_to_short_lookback_after_spy_reclaims_200dma():
    closes, extra = _rebound_market()
    slow = cl.build_weights(closes, extra, cl.CoreConfig(cash="bil"))
    fast = cl.build_weights(closes, extra, cl.CoreConfig(cash="bil", turnaround_lookback=63, turnaround_months=6))
    first_xlk = lambda w: w.index[(w["XLK"] > 0) & (w.index >= "2023-01-01")][0]  # noqa: E731
    assert first_xlk(fast) < first_xlk(slow)  # 전환점에서 반등 주도주를 더 빨리 잡는다


def test_cool_exclude_drops_last_years_fading_winner():
    closes, extra = _rebound_market()
    base = cl.build_weights(closes, extra, cl.CoreConfig(cash="bil"))
    cool = cl.build_weights(closes, extra, cl.CoreConfig(cash="bil", cool_exclude=0.10))
    d = "2023-05-01"
    assert base.loc[d:].iloc[0]["XLE"] > 0 and cool.loc[d:].iloc[0]["XLE"] == 0


# ---------------------------------------------------------------- core-weight-v1 비중 방식 (2026-10-08)
def test_rank_score_erc_weights_sum_and_order(prices):
    closes, extra = prices
    for wt in ("rank", "score", "erc"):
        w = cl.build_weights(closes, extra, cl.CoreConfig(cash="bil", weighting=wt))
        row = w.iloc[-1]
        assert row.sum() == pytest.approx(1.0) and (row >= -1e-12).all()
    r = cl.build_weights(closes, extra, cl.CoreConfig(cash="bil", weighting="rank", market_filter="none")).iloc[-1]
    held = sorted((x for x in r.drop("BIL").values if x > 0), reverse=True)
    if len(held) == 4:
        assert held == pytest.approx([0.4, 0.3, 0.2, 0.1])


def test_vol_target_only_scales_down(prices):
    closes, extra = prices
    base = cl.build_weights(closes, extra, cl.CoreConfig(cash="bil"))
    low = cl.build_weights(closes, extra, cl.CoreConfig(cash="bil", vol_target=0.01))
    high = cl.build_weights(closes, extra, cl.CoreConfig(cash="bil", vol_target=5.0))
    assert (low.drop(columns="BIL").sum(axis=1) <= base.drop(columns="BIL").sum(axis=1) + 1e-9).all()
    pd.testing.assert_frame_equal(high, base)  # 목표가 충분히 크면 그대로


def test_judge_adds_power_and_fail_kind_and_noop_guard(prices):
    from core import research_power as rp

    closes, extra = prices
    inc = cl.run(closes, extra, cl.CoreConfig(), "2011-06-01")
    var = cl.run(closes, extra, cl.CoreConfig(cash="bil"), "2011-06-01")
    res = cl.judge({"returns": var}, inc, [], n_trials=240, all_active_daily_srs=[])
    assert cl.JUDGE_VERSION == "core-judge/v1" and res["judge_version"] == "core-judge/v1"
    rep = res["power"]
    both = pd.concat([var.rename("v"), inc.rename("b")], axis=1).fillna(0.0)
    n_is = int((both.index < cl.holdout_split(both.index)).sum())
    assert rep["n_trials"] == 240 and rep["years"] == pytest.approx(n_is / 252, abs=0.01)
    assert rep["mde_ir"] == pytest.approx(rp.mde_ir(n_is / 252, 240), abs=0.002)
    if res["verdict"] == "FAIL":
        assert res["fail_kind"] == rp.classify_fail(res["gates"]["G1_improves_corrected"]["active_sharpe_annual"], rep)
    else:
        assert "fail_kind" not in res
    same = cl.judge({"returns": inc}, inc, [], n_trials=240, all_active_daily_srs=[])
    assert same["trial_consumed"] is False and "fail_kind" not in same and same["reasons"][0].startswith("NOT_EVALUABLE")
    json.dumps(same)


def test_not_evaluable_flows_through_core_registry_and_hub(tmp_path):
    from core import core_rnd as cr
    from hub import satellite_lab_page as page

    idea = {"id": "Q-2026q4-01", "title": "무효", "thesis": "t", "source": "s", "topic": "exit", "config": {"top_n": 5}}
    cr.freeze(idea, "agent", tmp_path)
    cr.freeze({**idea, "id": "Q-2026q4-02", "title": "옛 결과"}, "agent", tmp_path)
    with cr.edit_registry(tmp_path) as reg:
        reg["ideas"]["Q-2026q4-01"].update(status=cr.STATUS_NOT_EVALUABLE, attempts=1, result={
            "verdict": "NOT_EVALUABLE", "reasons": ["NOT_EVALUABLE: x"], "gates": {}, "trial_consumed": False})
        reg["ideas"]["Q-2026q4-02"].update(status=cr.STATUS_FAIL, attempts=1, result={  # power 키 없는 옛 저장 결과
            "verdict": "FAIL", "reasons": ["G1 x"], "gates": {}})
    reg = cr.load_registry(tmp_path)
    assert cr.queue(reg) == [] and not cr.has_work(tmp_path)
    assert "평가 불가" in cr.notification_text(reg["ideas"]["Q-2026q4-01"])
    assert "통과" not in cr.notification_text(reg["ideas"]["Q-2026q4-01"])
    assert cr.notification_text(reg["ideas"]["Q-2026q4-02"]).startswith("[코어 분기 연구]")
    ctx = cr.context_markdown(tmp_path)
    assert "not_evaluable" in ctx and "## 판정 해석" in ctx and "20개 넘는 연구" in ctx
    html_out = page.render_core({"core_registry": reg, "core_agent": {}, "core_quarter": "2026q4"})
    assert "평가 불가" in html_out and "독립 시험이 아니" in html_out


def test_core_fail_notification_suffix_and_pass_wording():
    from core import core_rnd as cr

    entry = {"id": "Q-1", "idea": {"title": "t"}, "status": "fail",
             "result": {"reasons": ["G1 x"], "fail_kind": "FAIL_UNDERPOWERED", "power": {"mde_ir": 0.88}}}
    assert "검정력 부족" in cr.notification_text(entry)
    ok = cr.notification_text({"id": "Q-1", "idea": {"title": "t"}, "status": "pass", "result": {"reasons": []}})
    assert "전진 원장" in ok and "채택 아님" in ok and "독립 시험이 아니" in ok


def test_agent_prompts_state_pass_meaning_and_holdout_reuse():
    for name in ("_contract.md", "_sat_contract.md", "core_designer.md"):
        text = (ROOT / "research" / "agent_prompts" / name).read_text(encoding="utf-8")
        assert "전진 원장" in text and "20개 넘는 연구" in text and "FAIL_UNDERPOWERED" in text, name
