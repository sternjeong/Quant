"""news-drift-v1 — 기사 수는 창 안의 created_at 만 세고 쪽을 넘긴다, 극단 종목은 r−1 까지의 가격만 쓴다, 중앙값으로 나눈다."""

import importlib.util
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("news_drift_v1", ROOT / "research/jobs/news-drift-v1/run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_count_news_pages_and_window_bounds():
    m = _load()
    fake = m.FakeNews()
    n = m.count_news(fake, "T01", "2016-03-01T21:00:00Z", "2016-03-31T21:00:00Z")
    assert 0 <= n <= 120 and fake.calls == max(1, -(-n // m.PAGE_LIMIT))
    pages = [{"news": [{"id": 1, "created_at": "2016-02-29T23:00:00Z"}, {"id": 2, "created_at": "2016-03-05T00:00:00Z"},
                       {"id": 2, "created_at": "2016-03-05T00:00:00Z"}, {"id": 3, "created_at": "2016-03-31T21:00:00Z"}],
              "next_page_token": None}]
    assert m.count_news(lambda p: pages[0], "X", "2016-03-01T21:00:00Z", "2016-03-31T21:00:00Z") == 1


def test_extremes_use_prices_through_previous_day_and_split_by_median():
    m = _load()
    days = pd.bdate_range("2015-01-01", periods=80)
    cols = ["SPY"] + [f"T{i:02d}" for i in range(100)]
    px = np.tile(np.linspace(1, 2, len(cols)), (len(days), 1))
    r = 60
    px[r, 1:] = np.arange(100)[::-1] + 1.0                     # r 일 가격은 순위에 쓰이면 안 된다
    px[r - 1, 1:] = px[r - 22, 1:] * (1 + np.arange(100) / 100)  # T99 가 가장 많이 오름
    win, lose = m.extremes(px, days, cols, lambda d: frozenset(cols[1:]), r)
    assert win[-1] == "T99" and lose[0] == "T00" and len(win) == len(lose) == 10
    sets = m.split({"win": ["A", "B"], "lose": ["C", "D"], "counts": {"A": 9, "B": 1, "C": 0, "D": 7}})
    assert sets["W_NEWS"] == ["A"] and sets["L_QUIET"] == ["C"] and sets["median"] == 4.0
    assert m.extremes(px, days, cols, lambda d: frozenset(cols[1:]), 10) == ([], [])
