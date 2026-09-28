"""위성 후보 풀 전체 기록(2026-09-25) 테스트.

검증 대상:
1. core.champion_strategy: 후보 풀을 '추가 필드로만' 노출하고, 원전략 결정(picks·비중·기존 필드)은 변경 전 코드와
   비트 단위로 같다 — 변경 전(커밋 031e9cc) _pick_satellite_at_date 본문을 아래 _legacy_pick 에 그대로 옮겨 두고
   같은 입력으로 새 코드와 대조한다.
2. core.candidate_recorder: 풀 전체가 selected/held/rejected/missing_data 로 원장에 기록된다.
3. core.filing_veto_shadow / core.guidance_shadow: 후보 집합 C(채택+돌파 held) 전체를 기록하고, 원전략 결정은
   복사만 한다. 외부 조회 상한·우선순위(채택 > 모멘텀 순위)를 지키며, 풀이 비어도 죽지 않는다.

원칙: 네트워크 없음(모든 가격·유니버스·공시 조회는 mock). 예상값은 구현이 아니라 요구사항과 손으로 만든 입력에서
정했다(예: 매끄럽게 오르는 종목은 돌파 활성, 매끄럽게 내리는 종목은 비활성, 성장률 순서 = 모멘텀 순서).
성과·승률 개선을 주장하지 않는다.
"""

import copy
import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from core import candidate_ledger as cl
from core import candidate_recorder as rec
from core import champion_strategy as cs
from core import filing_veto_shadow as fvs
from core import guidance_shadow as gs
from core.models import CandidateDecision

AS_OF = date(2026, 9, 22)
REBAL = pd.Timestamp("2022-01-03")
LEGACY_KEYS = {
    "as_of", "rebal_date", "trading_days_to_next_rebal", "pool_size", "n_active_trend", "new_orders_allowed",
    "allocation_reason", "data_coverage", "selected", "sizing_method", "per_ticker_weight", "per_ticker_weights",
    "picks", "unallocated_weight",
}
NEW_KEYS = {"candidates", "rejected_tickers", "missing_tickers"}


# ---------------------------------------------------------------------------
# 변경 전 코드(031e9cc core/champion_strategy.py 의 _pick_satellite_at_date 본문 그대로). 이름 해석만 cs. 로 한다.
# ---------------------------------------------------------------------------
def _legacy_pick(rebal_date, top_k=cs.SATELLITE_BACKTEST_TOP_K, pool_n=cs.SATELLITE_BACKTEST_POOL_N,
                 sizing_method="equal"):
    as_of_str = rebal_date.date().isoformat()
    pool = cs.sample_universe(n=pool_n, as_of_date=as_of_str, use_point_in_time_market_cap=True, use_cache=True)
    candidates = [t for t in pool["ticker"].tolist() if t not in cs.CORE_UNIVERSE and t != cs.MARKET_FILTER_TICKER]

    fetch_start = (rebal_date - pd.DateOffset(days=cs.SATELLITE_BACKTEST_WARMUP_DAYS)).date().isoformat()
    fetch_end = rebal_date.date().isoformat()
    histories = cs.get_multiple_price_history(candidates, start=fetch_start, end=fetch_end, interval="1d")

    active_scores = {}
    n_with_history = 0
    for t in candidates:
        df = histories.get(t)
        if df is None or df.empty:
            continue
        n_with_history += 1
        close = df["Close"]
        close = close[close.index < rebal_date]
        if len(close) < cs.SATELLITE_DONCHIAN_WINDOW + 60:
            continue
        pos = cs.donchian_trailing_stop_positions(close)
        if pos.iloc[-1] != 1:
            continue
        if len(close) >= cs.SATELLITE_BACKTEST_MOMENTUM_WINDOW + 5:
            mom = close.iloc[-1] / close.iloc[-1 - cs.SATELLITE_BACKTEST_MOMENTUM_WINDOW] - 1.0
        else:
            mom = close.iloc[-1] / close.iloc[0] - 1.0
        if pd.notna(mom):
            active_scores[t] = float(mom)

    ranked = sorted(active_scores.items(), key=lambda kv: kv[1], reverse=True)
    picks = [t for t, _ in ranked[:top_k]]

    pick_weights = {t: 1.0 / len(picks) for t in picks} if picks else {}
    if sizing_method == "inverse_vol" and len(picks) >= 2:
        pick_histories = {t: histories[t][histories[t].index < rebal_date] for t in picks if t in histories}
        vol_weights = cs._inverse_vol_weights(pick_histories, picks, cs.SATELLITE_SIZING_VOL_LOOKBACK_DAYS)
        if vol_weights:
            pick_weights = vol_weights

    return {
        "date": as_of_str, "pool_size": len(candidates), "n_active_trend": len(active_scores),
        "n_with_history": n_with_history,
        "picks": picks, "weights": pick_weights,
    }


# ---------------------------------------------------------------------------
# 합성 입력
# ---------------------------------------------------------------------------
_IDX = pd.bdate_range("2019-06-03", "2023-12-29")


def _smooth(annual_pct: float, n: int = None) -> pd.DataFrame:
    idx = _IDX if n is None else _IDX[:n]
    g = (1 + annual_pct / 100) ** (1 / 252) - 1
    close = 100 * np.cumprod(np.full(len(idx), 1 + g))
    return pd.DataFrame({"Close": close}, index=idx)


def _install(monkeypatch, pool, histories):
    """sample_universe / 가격 조회 / 거래일력을 mock 으로 바꾼다(네트워크 없음)."""
    monkeypatch.setattr(cs, "sample_universe", lambda n, as_of_date=None, use_point_in_time_market_cap=False,
                        use_cache=True: pd.DataFrame({"ticker": list(pool)}))

    def _prices(tickers, start=None, end=None, interval="1d", use_cache=True):
        out = {}
        for t in tickers:
            if t in histories:
                df = histories[t]
                out[t] = df[(df.index >= pd.Timestamp(start)) & (df.index <= pd.Timestamp(end))]
        return out

    monkeypatch.setattr(cs, "get_multiple_price_history", _prices)
    monkeypatch.setattr(cs, "get_price_history", lambda ticker, start=None, end=None, use_cache=True, **k:
                        pd.DataFrame({"Close": 1.0}, index=_IDX[(_IDX >= pd.Timestamp(start)) & (_IDX <= pd.Timestamp(end))]))


def _designed_pool(monkeypatch):
    """손으로 설계한 풀: 성장률이 다른 상승 종목 5개(돌파 활성, 모멘텀 순서 = 성장률 순서), 하락 2개(돌파 비활성),
    이력 부족 1개, 이력 없음 1개, 코어 유니버스 ETF 1개(후보에서 원래 빠짐)."""
    rising = {"R10": 10.0, "R20": 20.0, "R30": 30.0, "R40": 40.0, "R50": 50.0}
    hist = {t: _smooth(g) for t, g in rising.items()}
    hist.update({"D1": _smooth(-20.0), "D2": _smooth(-35.0), "SHORT": _smooth(30.0, n=50)})
    pool = ["R10", "D1", "R30", "SHORT", "R50", "NOHIST", "R20", "D2", "R40", cs.CORE_UNIVERSE[0]]
    _install(monkeypatch, pool, hist)
    return pool


def _random_pool(monkeypatch, seed: int):
    rng = np.random.default_rng(seed)
    pool = [f"T{i:02d}" for i in range(24)]
    hist = {}
    for t in pool:
        kind = int(rng.integers(0, 8))
        if kind == 0:
            continue  # 이력 없음
        n = 60 if kind == 1 else len(_IDX)
        r = rng.normal(rng.normal(0.0004, 0.001), 0.02, n)
        hist[t] = pd.DataFrame({"Close": 100 * np.exp(np.cumsum(r))}, index=_IDX[:n])
    _install(monkeypatch, pool, hist)


# ---------------------------------------------------------------------------
# 1. 원전략 불변(회귀) + 추가 필드
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("seed", [0, 1, 2, 3])
@pytest.mark.parametrize("sizing", ["equal", "inverse_vol"])
def test_pick_matches_pre_change_code_bit_for_bit(monkeypatch, seed, sizing):
    _random_pool(monkeypatch, seed)
    for top_k in (1, 3, 5):
        new = cs._pick_satellite_at_date(REBAL, top_k=top_k, sizing_method=sizing)
        old = _legacy_pick(REBAL, top_k=top_k, sizing_method=sizing)
        for k, v in old.items():
            assert new[k] == v, k  # float 도 == (비트 단위 동일)
        assert set(new) - set(old) == {"ranked_active", "rejected_tickers", "missing_tickers"}
        # 추가 필드는 이미 계산한 값의 재배열일 뿐이다: ranked_active 앞 top_k = picks, 개수 = n_active_trend
        assert [t for t, _ in new["ranked_active"][:top_k]] == old["picks"]
        assert len(new["ranked_active"]) == old["n_active_trend"]
        assert (len(new["ranked_active"]) + len(new["rejected_tickers"]) + len(new["missing_tickers"])
                == old["pool_size"])


@pytest.mark.parametrize("sizing", ["equal", "inverse_vol"])
def test_point_in_time_legacy_fields_unchanged(monkeypatch, sizing):
    """기존 필드는 변경 전 로직(_legacy_pick)으로 만든 선정과 같고, 새 키는 정확히 3개만 늘었다."""
    _random_pool(monkeypatch, 7)
    out = cs.compute_satellite_recommendation_point_in_time(as_of_date="2022-03-15", top_k=3, sizing_method=sizing)
    legacy = _legacy_pick(REBAL, top_k=3, sizing_method=sizing)
    assert set(out) == LEGACY_KEYS | NEW_KEYS
    assert out["rebal_date"] == "2022-01-03"
    assert out["selected"] == legacy["picks"]
    assert out["pool_size"] == legacy["pool_size"] and out["n_active_trend"] == legacy["n_active_trend"]
    assert out["per_ticker_weights"] == {t: cs.SATELLITE_WEIGHT * w for t, w in legacy["weights"].items()}


def test_point_in_time_pool_fields_from_designed_input(monkeypatch):
    _designed_pool(monkeypatch)
    out = cs.compute_satellite_recommendation_point_in_time(as_of_date="2022-03-15", top_k=3)
    # 요구사항: 모멘텀 상위 3개 = 성장률 상위 3개
    assert out["selected"] == ["R50", "R40", "R30"]
    cand = out["candidates"]
    assert list(cand.columns) == ["ticker", "momentum_12m", "rank", "donchian_breakout", "selected"]
    assert cand["ticker"].tolist() == ["R50", "R40", "R30", "R20", "R10"]
    assert cand["rank"].tolist() == [1, 2, 3, 4, 5]
    assert cand["selected"].tolist() == [True, True, True, False, False]
    assert cand["donchian_breakout"].all()
    assert cand["momentum_12m"].is_monotonic_decreasing
    assert cand.loc[cand.ticker == "R20", "momentum_12m"].iloc[0] == pytest.approx(0.20, abs=0.01)
    assert sorted(out["rejected_tickers"]) == ["D1", "D2"]
    assert sorted(out["missing_tickers"]) == ["NOHIST", "SHORT"]
    assert out["n_active_trend"] == 5 and out["pool_size"] == 9  # 코어 ETF 는 원래 제외


def test_point_in_time_empty_pool(monkeypatch):
    _install(monkeypatch, [], {})
    out = cs.compute_satellite_recommendation_point_in_time(as_of_date="2022-03-15", top_k=3)
    assert out["selected"] == [] and out["new_orders_allowed"] is False
    assert out["candidates"].empty and list(out["candidates"].columns) == cs.SATELLITE_POOL_CANDIDATE_COLUMNS
    assert out["rejected_tickers"] == [] and out["missing_tickers"] == []


def test_order_path_ignores_new_fields():
    """주문 계획(scripts/champion_paper_trade.build_plan)은 새 필드가 있어도 없어도 같은 계획을 만든다."""
    from scripts.champion_paper_trade import build_plan

    core = {"per_ticker_weights": {"SPY": 0.2, "QQQ": 0.2}, "new_orders_allowed": True, "top4": ["SPY", "QQQ"]}
    sat = {"per_ticker_weights": {"AAA": 0.05}, "new_orders_allowed": True, "selected": ["AAA"],
           "allocation_reason": "ok"}
    sat_new = {**sat, "candidates": pd.DataFrame({"ticker": ["AAA", "BBB"]}), "rejected_tickers": ["CCC"],
               "missing_tickers": ["DDD"]}
    assert build_plan(core, sat, {}, 100_000.0) == build_plan(core, sat_new, {}, 100_000.0)


# ---------------------------------------------------------------------------
# 2. 원장: 풀 전체가 올바른 decision 으로
# ---------------------------------------------------------------------------
def _pool_result(new_orders_allowed=True, selected=("AAA", "BBB"), cand=("AAA", "BBB", "CCC", "DDD")):
    rows = [{"ticker": t, "momentum_12m": 0.5 - 0.1 * i, "rank": i + 1, "donchian_breakout": True,
             "selected": t in selected} for i, t in enumerate(cand)]
    return {
        "as_of": AS_OF.isoformat(), "rebal_date": "2026-07-01", "selected": list(selected), "sizing_method": "equal",
        "per_ticker_weights": {t: 0.05 for t in selected} if new_orders_allowed else {},
        "new_orders_allowed": new_orders_allowed, "allocation_reason": "ok" if new_orders_allowed else "보류",
        "pool_size": 8, "n_active_trend": len(cand),
        "candidates": pd.DataFrame(rows, columns=cs.SATELLITE_POOL_CANDIDATE_COLUMNS),
        "rejected_tickers": ["EEE", "FFF"], "missing_tickers": ["GGG", "HHH"],
    }


def _decisions(db_session, **flt):
    return {d.ticker: d for d in db_session.query(CandidateDecision).filter_by(**flt).all()}


def test_recorder_records_whole_pool(db_session, monkeypatch):
    monkeypatch.setattr("core.champion_strategy.compute_satellite_recommendation_point_in_time",
                        lambda **kw: _pool_result())
    out = rec._record_champion_satellite(AS_OF, session=db_session)
    got = {t: d.decision for t, d in _decisions(db_session, source="champion_satellite").items()}
    assert got == {"AAA": "selected", "BBB": "selected", "CCC": "held", "DDD": "held",
                   "EEE": "rejected", "FFF": "rejected", "GGG": "missing_data", "HHH": "missing_data"}
    assert out["n_pool"] == 8
    assert out["n_by_decision"] == {"selected": 2, "held": 2, "rejected": 2, "missing_data": 2}
    d = _decisions(db_session, source="champion_satellite")
    assert d["AAA"].order_proposal is not None and d["CCC"].order_proposal is None


def test_recorder_blocked_pool_has_no_selected(db_session, monkeypatch):
    monkeypatch.setattr("core.champion_strategy.compute_satellite_recommendation_point_in_time",
                        lambda **kw: _pool_result(new_orders_allowed=False))
    rec._record_champion_satellite(AS_OF, session=db_session)
    got = {t: d.decision for t, d in _decisions(db_session, source="champion_satellite").items()}
    assert got["AAA"] == "held" and got["BBB"] == "held"
    assert "selected" not in got.values()


def test_recorder_end_to_end_with_real_strategy(db_session, monkeypatch):
    _designed_pool(monkeypatch)
    real = cs.compute_satellite_recommendation_point_in_time
    monkeypatch.setattr("core.champion_strategy.compute_satellite_recommendation_point_in_time",
                        lambda **kw: real(as_of_date="2022-03-15", top_k=3))
    rec._record_champion_satellite(AS_OF, session=db_session)
    got = {t: d.decision for t, d in _decisions(db_session, source="champion_satellite").items()}
    assert got == {"R50": "selected", "R40": "selected", "R30": "selected", "R20": "held", "R10": "held",
                   "D1": "rejected", "D2": "rejected", "SHORT": "missing_data", "NOHIST": "missing_data"}


# ---------------------------------------------------------------------------
# 3a. 공시 veto shadow
# ---------------------------------------------------------------------------
class _Provider:
    """호출 순서를 기록하고, 호출마다 SEC 요청 수를 per_call 만큼 늘리는 가짜 공급자(네트워크 없음)."""

    def __init__(self, per_call=5):
        self.calls, self.per_call, self.request_count = [], per_call, 0

    def __call__(self, ticker, cutoff):
        self.calls.append(ticker)
        self.request_count += self.per_call
        return []


def test_filing_veto_records_whole_breakout_pool_and_copies_original(db_session):
    sat = _pool_result()
    before = copy.deepcopy({k: v for k, v in sat.items() if k != "candidates"})
    cand_before = sat["candidates"].copy()
    prov = _Provider()
    out = fvs.record_filing_veto_shadow(AS_OF, session=db_session, satellite_result=sat, event_provider=prov)
    rows = _decisions(db_session, strategy_version=fvs.SHADOW_STRATEGY_VERSION)
    assert set(rows) == {"AAA", "BBB", "CCC", "DDD"}  # C = 채택 + 돌파 held. rejected/missing 은 C 가 아니다
    orig = {t: json.loads(r.scores)["original_decision"] for t, r in rows.items()}
    assert orig == {"AAA": "selected", "BBB": "selected", "CCC": "held", "DDD": "held"}
    adopted = {t: json.loads(r.scores)["in_adopted_set"] for t, r in rows.items()}
    assert adopted == {"AAA": True, "BBB": True, "CCC": False, "DDD": False}
    assert prov.calls == ["AAA", "BBB", "CCC", "DDD"]
    assert out["n_candidates"] == 4 and out["n_adopted"] == 2 and out["n_skipped"] == 0
    # 원전략 결과는 읽기만 했다
    assert {k: v for k, v in sat.items() if k != "candidates"} == before
    pd.testing.assert_frame_equal(sat["candidates"], cand_before)
    # 원전략 원장(champion_satellite)에는 아무것도 쓰지 않았다
    assert db_session.query(CandidateDecision).filter_by(source="champion_satellite").count() == 0


def test_filing_veto_blocked_copies_held(db_session):
    fvs.record_filing_veto_shadow(AS_OF, session=db_session, satellite_result=_pool_result(new_orders_allowed=False),
                                  event_provider=_Provider())
    rows = _decisions(db_session, strategy_version=fvs.SHADOW_STRATEGY_VERSION)
    assert json.loads(rows["AAA"].scores)["original_decision"] == "held"
    assert json.loads(rows["AAA"].scores)["in_adopted_set"] is True


def test_filing_veto_ticker_cap_uses_priority_adopted_first(db_session):
    # 채택 종목(DDD)이 모멘텀 순위 4위여도 먼저 조회된다. 그다음은 모멘텀 순위 순.
    sat = _pool_result(selected=("DDD",), cand=("AAA", "BBB", "CCC", "DDD"))
    prov = _Provider()
    out = fvs.record_filing_veto_shadow(AS_OF, session=db_session, satellite_result=sat, event_provider=prov,
                                        max_tickers=2)
    assert prov.calls == ["DDD", "AAA"]
    assert out["skipped_tickers"] == {"BBB": "skipped_max_tickers", "CCC": "skipped_max_tickers"}
    rows = _decisions(db_session, strategy_version=fvs.SHADOW_STRATEGY_VERSION)
    assert rows["BBB"].decision == "missing_data" and rows["CCC"].decision == "missing_data"
    assert json.loads(rows["BBB"].scores)["exposed"] is False
    assert json.loads(rows["BBB"].scores)["original_decision"] == "held"  # 원전략 결정은 그대로 남는다


def test_filing_veto_request_and_time_budget(db_session):
    prov = _Provider(per_call=5)
    out = fvs.record_filing_veto_shadow(AS_OF, session=db_session, satellite_result=_pool_result(),
                                        event_provider=prov, max_sec_requests=10)
    assert prov.calls == ["AAA", "BBB"] and out["budget_stop"] == "request_budget_exceeded"
    assert out["skipped_tickers"] == {"CCC": "skipped_budget", "DDD": "skipped_budget"}

    ticks = iter([0.0, 0.0, 400.0])
    prov2 = _Provider()
    out2 = fvs.record_filing_veto_shadow(date(2026, 9, 23), session=db_session, satellite_result=_pool_result(),
                                         event_provider=prov2, time_budget_seconds=300.0,
                                         clock=lambda: next(ticks, 400.0))
    assert prov2.calls == ["AAA"] and out2["budget_stop"] == "time_budget_exceeded"


def test_filing_veto_default_caps_match_guidance_nightly():
    assert fvs.FILING_VETO_MAX_TICKERS == gs.NIGHTLY_MAX_TICKERS == 20
    assert fvs.FILING_VETO_TIME_BUDGET_SECONDS == 300.0
    assert 0 < fvs.FILING_VETO_MAX_SEC_REQUESTS <= gs.NIGHTLY_MAX_SEC_REQUESTS


def test_filing_veto_empty_pool(db_session):
    sat = _pool_result(selected=(), cand=())
    prov = _Provider()
    out = fvs.record_filing_veto_shadow(AS_OF, session=db_session, satellite_result=sat, event_provider=prov)
    assert out["n_candidates"] == 0 and prov.calls == []


# ---------------------------------------------------------------------------
# 3b. 가이던스 shadow
# ---------------------------------------------------------------------------
def _fake_fetcher(log):
    from core import guidance_event_provider as gep

    def fetcher(tickers, as_of=None, max_tickers=20, **kw):
        log.append(list(tickers))
        outcomes = [gep.TickerFetchOutcome(t, gep.STATUS_OK) for t in tickers[:max_tickers]]
        outcomes += [gep.TickerFetchOutcome(t, gep.STATUS_SKIPPED, reason="max_tickers_limit")
                     for t in tickers[max_tickers:]]
        meta = {"n_tickers_requested": len(tickers), "n_tickers_queried": min(len(tickers), max_tickers),
                "n_tickers_skipped": max(0, len(tickers) - max_tickers), "max_tickers": max_tickers,
                "n_network_requests": 0}
        return gep.GuidanceEventFetchResult({}, tuple(outcomes), meta)

    return fetcher


def test_guidance_records_pool_with_copied_decisions_and_priority(db_session):
    sat = _pool_result(selected=("DDD",), cand=("AAA", "BBB", "CCC", "DDD"))
    base = cl.champion_satellite_to_candidate_set(sat, strategy_version="champion_satellite/equal",
                                                  decision_cutoff=gs._cutoff_for(AS_OF))
    log = []
    out = gs.record_guidance_shadow(AS_OF, session=db_session, satellite_result=sat, fetch_events=True,
                                    max_tickers=2, event_fetcher=_fake_fetcher(log))
    assert log == [["DDD", "AAA", "BBB", "CCC"]]  # 채택 먼저, 그다음 모멘텀 순위
    rows = _decisions(db_session, strategy_version=gs.GUIDANCE_SHADOW_STRATEGY_VERSION)
    assert {t: r.decision for t, r in rows.items()} == {r.ticker: r.decision for r in base.records}
    assert {t: r.decision for t, r in rows.items()} == {"AAA": "held", "BBB": "held", "CCC": "held",
                                                          "DDD": "selected"}
    status = {t: json.loads(r.scores)["guidance_fetch_status"] for t, r in rows.items()}
    assert status == {"DDD": "ok", "AAA": "ok", "BBB": "skipped_max_tickers", "CCC": "skipped_max_tickers"}
    assert out["n_pool"] == 4 and out["n_adopted"] == 1
    assert out["candidate_population"] == "breakout_pool_selected_and_held"
    assert out["event_fetch_summary"]["n_tickers_queried"] == 2


def test_guidance_does_not_include_rejected_or_missing(db_session):
    gs.record_guidance_shadow(AS_OF, session=db_session, satellite_result=_pool_result(), events_by_ticker={})
    rows = _decisions(db_session, strategy_version=gs.GUIDANCE_SHADOW_STRATEGY_VERSION)
    assert set(rows) == {"AAA", "BBB", "CCC", "DDD"}
    assert all(json.loads(r.scores)["guidance_fetch_status"] == "not_requested" for r in rows.values())


def test_guidance_empty_pool(db_session):
    log = []
    out = gs.record_guidance_shadow(AS_OF, session=db_session, satellite_result=_pool_result(selected=(), cand=()),
                                    fetch_events=True, event_fetcher=_fake_fetcher(log))
    assert out["ok"] is True and out["n_pool"] == 0
