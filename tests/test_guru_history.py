"""거장 13F 이력(core/guru_history.py) — 공시일 전에는 안 보임, 신규 매수·상위 5, infoTable 파싱, 이름 맞추기, 시험실 연결."""

from __future__ import annotations

from datetime import date

import pytest

from core import guru_history as gh
from core import satellite_lab as sl

XML = b"""<?xml version="1.0"?>
<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
  <infoTable><nameOfIssuer>APPLE INC</nameOfIssuer><cusip>037833100</cusip><value>900</value></infoTable>
  <infoTable><nameOfIssuer>APPLE INC</nameOfIssuer><cusip>037833100</cusip><value>100</value></infoTable>
  <infoTable><nameOfIssuer>BANK AMER CORP</nameOfIssuer><cusip>060505104</cusip><value>500</value></infoTable>
  <infoTable><nameOfIssuer>SPDR S&amp;P 500</nameOfIssuer><cusip>78462F103</cusip><value>50</value><putCall>Put</putCall></infoTable>
</informationTable>"""


def test_parse_infotable_sums_by_cusip_and_skips_options():
    rows = {r["cusip"]: r["value"] for r in gh.parse_infotable(XML)}
    assert rows == {"037833100": 1000.0, "060505104": 500.0}


def test_norm_name_matches_sec_titles():
    assert gh.norm_name("BANK AMER CORP") == gh.norm_name("Bank of America Corp")
    assert gh.norm_name("OCCIDENTAL PETE CORP") == gh.norm_name("OCCIDENTAL PETROLEUM CORP /DE/".replace("/DE/", ""))
    assert gh.norm_name("APPLE INC") == "APPLE"


def _f(filed, period, holds):
    return {"filed": filed, "period": period, "holdings": [{"ticker": t, "weight": w} for t, w in holds.items()]}


def test_view_point_in_time_new_buys_and_top5():
    per = {"A": [_f("2020-02-14", "2019-12-31", {"AAPL": 0.5, "KO": 0.5}),
                 _f("2020-05-15", "2020-03-31", {"AAPL": 0.4, "KO": 0.3, "NVDA": 0.3})],
           "B": [_f("2020-05-10", "2020-03-31", {"NVDA": 0.02, "X1": 0.2, "X2": 0.2, "X3": 0.2, "X4": 0.2, "X5": 0.18})]}
    early = gh.view_from_filings(per, "NVDA", date(2020, 5, 1))
    assert early == {"n_holders": 0, "n_new": 0, "n_top5": 0, "max_weight": 0.0}  # 5월 공시 전
    late = gh.view_from_filings(per, "NVDA", date(2020, 5, 20))
    assert late["n_holders"] == 2 and late["n_new"] == 1 and late["n_top5"] == 1 and late["max_weight"] == pytest.approx(0.3)
    assert gh.view_from_filings(per, "NVDA", date(2019, 1, 1)) == {}  # 데이터 없음


def test_guru_seeds_require_store_and_run_with_synthetic():
    spec, code = sl.read_variant_dir(sl.SEEDS_DIR / "S-SEED-024")
    assert spec["data"] == ["guru13f"] and spec["topic"] == "guru"
    pp, poolp = sl.synthetic_providers(n_tickers=20, start="2019-01-01", end="2022-12-30")
    data = sl.build_data({"champion40"}, start="2021-01-01", end="2022-12-30", pool_provider=poolp, price_provider=pp)
    with pytest.raises(sl.LabSpecError, match="13F"):
        sl.run_variant(spec, spec["signal"]["params_grid"][0], sl.load_signal(code), data)
    data.guru = gh.SyntheticStore()
    assert sl.run_variant(spec, spec["signal"]["params_grid"][0], sl.load_signal(code), data)["schedule"]


def test_guru_topic_switch_exists():
    from core import rnd_topics as rt

    assert rt.SAT_TOPIC_KEYS["guru"] == "sat_guru" and "sat_guru" in rt.TOPICS
