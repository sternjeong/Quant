"""시점 기준 재무(core/fundamentals_pit.py) — 공시일 전 숫자를 보지 않음, 정정 공시, 낡은 값 무시, 실적 발표일, 저장소(네트워크 없음)."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pandas as pd
import pytest

from core import fundamentals_pit as fp
from core import satellite_lab as sl


def _fact(start, end, val, filed, form="10-Q"):
    return {"start": start, "end": end, "val": val, "filed": filed, "form": form}


RAW = {"facts": {"us-gaap": {
    "Revenues": {"units": {"USD": [
        _fact("2022-01-01", "2022-03-31", 100, "2022-04-28"),
        _fact("2022-04-01", "2022-06-30", 110, "2022-07-28"),
        _fact("2023-01-01", "2023-03-31", 120, "2023-04-27"),
        _fact("2023-04-01", "2023-06-30", 140, "2023-07-27"),
        _fact("2023-04-01", "2023-06-30", 150, "2023-10-30"),  # 나중에 정정
        _fact("2022-01-01", "2022-12-31", 450, "2023-02-15", "10-K"),
    ]}},
    "GrossProfit": {"units": {"USD": [_fact("2022-01-01", "2022-12-31", 200, "2023-02-15", "10-K")]}},
    "Assets": {"units": {"USD": [{"end": "2022-12-31", "val": 1000, "filed": "2023-02-15", "form": "10-K"}]}},
    "EarningsPerShareDiluted": {"units": {"USD/shares": [_fact("2023-01-01", "2023-03-31", 1.0, "2023-04-27")]}},
}}}


def _rec():
    rec = {"facts": fp.compact_companyfacts(RAW), "sic": 3571, "earnings_dates": ["2023-04-25", "2023-07-25"]}
    return rec


def test_point_in_time_hides_facts_filed_after_asof():
    rec = _rec()
    before = fp.view_from_record(rec, date(2023, 2, 1))
    assert before["gp_assets"] is None  # 10-K 는 2023-02-15 공시
    after = fp.view_from_record(rec, date(2023, 2, 20))
    assert after["gp_assets"] == pytest.approx(0.2)
    v = fp.view_from_record(rec, date(2023, 8, 1))
    assert v["rev_yoy"] == pytest.approx(140 / 110 - 1) and v["rev_yoy_prev"] == pytest.approx(120 / 100 - 1)
    assert v["last_earnings"] == "2023-07-25"


def test_restatement_only_visible_after_its_filing():
    rec = _rec()
    assert fp.view_from_record(rec, date(2023, 11, 1))["rev_yoy"] == pytest.approx(150 / 110 - 1)


def test_stale_quarters_are_unknown():
    assert fp.view_from_record(_rec(), date(2024, 6, 1))["rev_yoy"] is None  # 마지막 분기가 200일 넘게 지남


def test_compact_skips_non_usd_and_keeps_concept_priority():
    c = fp.compact_companyfacts(RAW)
    assert "eps" not in c and len(c["revenue"]) == 6 and len(c["gross_profit"]) == 1


def test_submissions_earnings_dates_from_8k_item_202():
    meta = {"sic": "3674", "filings": {"recent": {"form": ["8-K", "8-K", "10-Q"], "filingDate": ["2024-02-21", "2024-03-01", "2024-03-05"],
                                                 "items": ["2.02,9.01", "5.02", ""]}}}
    older = [{"form": ["8-K"], "filingDate": ["2019-02-14"], "items": ["2.02"]}]
    out = fp.compact_submissions(meta, older)
    assert out == {"sic": 3674, "earnings_dates": ["2019-02-14", "2024-02-21"]}


class _FakeClient:
    def __init__(self):
        self.calls = 0

    def resolve_cik(self, t):
        if t == "GONE":
            raise RuntimeError("ticker not found")
        return "0000000001"

    def _get(self, url):
        self.calls += 1
        if "companyfacts" in url:
            return json.dumps(RAW).encode()
        return json.dumps({"sic": "3571", "filings": {"recent": {"form": ["8-K"], "filingDate": ["2023-04-25"], "items": ["2.02"]}}}).encode()


def test_store_downloads_once_caches_and_marks_missing(tmp_path):
    c = _FakeClient()
    now = datetime(2026, 10, 8, tzinfo=timezone.utc)
    s = fp.Store(tmp_path, client=c, now=lambda: now)
    assert s.view("AAA", date(2023, 8, 1))["sic"] == 3571
    assert s.view("GONE", date(2023, 8, 1)) is None
    calls = c.calls
    s2 = fp.Store(tmp_path, client=c, now=lambda: now)  # 디스크에서 읽고 다시 받지 않는다
    assert s2.view("AAA", date(2023, 8, 1))["sic"] == 3571 and c.calls == calls
    res = fp.Store(tmp_path, client=c, now=lambda: now).prefetch(["AAA", "BBB"], deadline=0)
    assert res["complete"] is False and res["left"] == 2  # 시간 예산이 없으면 멈춘다


def test_lab_rejects_unknown_data_source_and_requires_store():
    spec, code = sl.read_variant_dir(sl.SEEDS_DIR / "S-SEED-010")
    with pytest.raises(sl.LabSpecError, match="data"):
        sl.validate_spec({**spec, "data": ["tweets"]})
    pp, poolp = sl.synthetic_providers(n_tickers=20, start="2019-01-01", end="2022-12-30")
    data = sl.build_data({"champion40"}, start="2021-01-01", end="2022-12-30", pool_provider=poolp, price_provider=pp)
    with pytest.raises(sl.LabSpecError, match="재무"):
        sl.run_variant(spec, spec["signal"]["params_grid"][0], sl.load_signal(code), data)
    data.fundamentals = fp.SyntheticStore()
    out = sl.run_variant(spec, spec["signal"]["params_grid"][0], sl.load_signal(code), data)
    assert out["schedule"]


def test_price_only_ideas_still_get_three_arguments():
    spec, code = sl.read_variant_dir(sl.SEEDS_DIR / "S-SEED-000")
    calls = []

    def sig(prices, as_of, params, *rest):
        calls.append(len(rest))
        return sl.load_signal(code)(prices, as_of, params)

    pp, poolp = sl.synthetic_providers(n_tickers=20, start="2019-01-01", end="2022-12-30")
    data = sl.build_data({"champion40"}, start="2021-01-01", end="2022-12-30", pool_provider=poolp, price_provider=pp)
    sl.run_variant(spec, spec["signal"]["params_grid"][0], sig, data)
    assert calls and set(calls) == {0}
