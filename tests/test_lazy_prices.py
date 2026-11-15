"""lazy-prices-v1 — 숫자를 뺀 단어 빈도 코사인, 정정본·간격 밖 10-K 제외, 유사도 상위 5분위가 top."""

import importlib.util
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("lazy_prices_v1", ROOT / "research/jobs/lazy-prices-v1/run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_word_counts_drop_numbers_and_cosine_bounds():
    m = _load()
    a = m.word_counts("<html><p>Revenue rose 12% to $1,234 in 2019. Revenue risk</p></html>")
    assert a == Counter({"revenue": 2, "rose": 1, "to": 1, "in": 1, "risk": 1})
    assert abs(m.cosine(a, a) - 1.0) < 1e-12 and m.jaccard(a, a) == 1.0
    assert m.cosine(a, Counter({"other": 3})) == 0.0
    assert np.isnan(m.cosine(a, Counter()))


def test_ticker_events_skip_amendments_and_out_of_gap_filings():
    m = _load()
    client = m.FakeClient(["T00", "T01"])
    ev = m.ticker_events(client, "T00")                       # T00 은 해마다 많이 고친다(i % 3 == 0)
    assert len(ev) == 14 and all(e["filed"][5:7] == "02" for e in ev)
    ev1 = m.ticker_events(client, "T01")
    assert np.median([e["sim"] for e in ev1]) > np.median([e["sim"] for e in ev])


def test_panel_top_is_most_similar_quintile():
    m = _load()
    days = pd.bdate_range("2009-01-01", periods=300)
    tick = [f"S{i:02d}" for i in range(60)]
    closes = pd.DataFrame({t: np.linspace(10, 20, len(days)) for t in ["SPY", *tick]}, index=days)
    ev = pd.DataFrame({"ticker": tick, "filed": [days[100]] * 60, "sim": np.linspace(0.5, 0.99, 60), "jac": 0.5, "n_words": 1})
    f = m.LazyPanel(ev, closes, lambda d: frozenset(tick), "sim").form(200)
    assert f["ok"] and len(f["top"]) == 12
    cols = list(closes.columns)
    assert {cols[c] for c in f["top"]} == set(tick[-12:]) and {cols[c] for c in f["bottom"]} == set(tick[:12])
    assert not m.LazyPanel(ev, closes, lambda d: frozenset(tick), "sim").form(100)["ok"]   # 공시 당일에는 아직 못 쓴다
