"""insider-form4-v1 — SEC 분기 ZIP 파싱(임원·이사만, P/S만), 일상형/기회형 분류, 공시 다음 거래일부터만 신호."""

import importlib.util
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("insider_form4_v1", ROOT / "research/jobs/insider-form4-v1/run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rec(n, t, owner, rel, d, code, filed=None):
    d = pd.Timestamp(d)
    f = pd.Timestamp(filed) if filed else d + pd.Timedelta(days=2)
    return {"ACCESSION_NUMBER": f"A{n}", "FILING_DATE": f.strftime("%d-%b-%Y").upper(), "ISSUERTRADINGSYMBOL": t,
            "RPTOWNERCIK": owner, "RPTOWNER_RELATIONSHIP": rel, "TRANS_DATE": d.strftime("%d-%b-%Y").upper(), "TRANS_CODE": code,
            "TRANS_SHARES": 1000, "TRANS_PRICEPERSHARE": 50, "TRANS_ACQUIRED_DISP_CD": "A" if code == "P" else "D"}


def test_parse_keeps_insiders_and_classifies_routine_vs_opportunistic():
    m = _load()
    recs = []
    n = 0
    for y in (2006, 2007, 2008, 2009):
        n += 1; recs.append(_rec(n, "AAA", 1, "Officer", f"{y}-03-10", "P"))          # 일상형: 해마다 3월
        n += 1; recs.append(_rec(n, "BBB", 2, "Director", f"{y}-{3 + y - 2006:02d}-10", "P"))  # 기회형: 달이 바뀜
    n += 1; recs.append(_rec(n, "BBB", 3, "TenPercentOwner", "2009-05-01", "P"))     # 펀드 — 빠진다
    n += 1; recs.append(_rec(n, "ZZZ", 4, "Officer", "2009-05-01", "P"))             # 우리 종목 아님
    n += 1; recs.append(_rec(n, "aaa", 5, "Director", "2009-05-01", "M"))            # 옵션 행사 — 빠진다
    rows = m.parse_quarter_zip(m._fake_zip(recs), {"AAA", "BBB"}, lambda t: t)
    assert set(rows["owner"]) == {1, 2}
    ev = m.classify(rows)
    last = ev[ev["filed"].dt.year == 2009].set_index("owner")["kind"].to_dict()
    assert last == {1: "routine", 2: "opportunistic"}
    assert set(ev[ev["filed"].dt.year == 2006]["kind"]) == {"unclassified"}


def test_signal_starts_day_after_filing_and_cluster_needs_two_insiders():
    m = _load()
    days = pd.bdate_range("2009-01-01", "2009-12-31")
    tick = ["SPY", "A", "B", "C", "D"]
    closes = pd.DataFrame({t: np.linspace(10, 20, len(days)) for t in tick}, index=days)
    r = int(days.searchsorted(pd.Timestamp("2009-06-01")))
    f = days[r - 1]   # 형성일 전날 공시 → 다음 거래일 = r → 이번 달에는 못 쓴다
    ev = pd.DataFrame({"ticker": ["A", "A", "B", "C", "D", "D"], "filed": [days[r - 10], days[r - 9], days[r - 8], days[r - 7], days[r - 6], f],
                       "owner": [1, 2, 3, 4, 5, 6], "kind": ["opportunistic", "routine", "routine", "opportunistic", "routine", "opportunistic"],
                       "usd": 1e5})
    mem = lambda d: frozenset(tick[1:])  # noqa: E731
    any_ = m.InsiderPanel(ev, closes, mem, "A_ANY").form(r)
    assert any_["ok"] and len(any_["top"]) == 4
    cl = m.InsiderPanel(ev, closes, mem, "C_CLUSTER").form(r)
    assert not cl["ok"] and cl["n_eligible"] == 1          # A 만(2명), D 의 두 번째 매수는 아직 못 씀 → 3개 미만
    opp = m.InsiderPanel(ev, closes, mem, "O_OPP").form(r)
    assert opp["n_eligible"] == 2                           # A, C (D 의 기회형 매수는 다음 달부터)
    assert m.last_published_quarter(date(2026, 11, 15)) == (2026, 3)
