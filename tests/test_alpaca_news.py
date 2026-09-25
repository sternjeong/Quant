"""core/alpaca_news.py — mock 응답으로 정규화·PIT·페이지네이션을 검증한다(네트워크 없음)."""

from core import alpaca_news as n


def _art(i, created, updated=None, headline="h"):
    return {"id": i, "created_at": created, "updated_at": updated or created, "headline": headline,
            "symbols": ["aapl"], "source": "x"}


def test_pagination_dedup_and_drops_articles_without_created_at():
    pages = [
        {"news": [_art(1, "2026-01-02T10:00:00Z"), {"id": 2, "headline": "no time"}], "next_page_token": "t"},
        {"news": [_art(1, "2026-01-02T10:00:00Z"), _art(3, "2026-01-01T09:00:00Z")], "next_page_token": None},
    ]
    calls = []
    def get(path):
        calls.append(path)
        return pages[len(calls) - 1]
    res = n.fetch_news(["aapl"], "2026-01-01", "2026-01-03", get_json=get)
    assert [a["id"] for a in res] == [3, 1]          # 오름차순, 중복(1) 제거, 시각 없는 2 제외
    assert "page_token=t" in calls[1] and "symbols=AAPL" in calls[0]
    assert res[0]["symbols"] == ["AAPL"]


def test_as_of_uses_created_not_updated():
    # 어제 게시됐지만 오늘 수정된 기사는 어제 시점에 알 수 있었다. 오늘 게시된 기사는 알 수 없었다.
    payload = {"news": [_art(1, "2026-01-01T10:00:00Z", updated="2026-01-05T00:00:00Z"),
                        _art(2, "2026-01-03T10:00:00Z")]}
    res = n.fetch_news(["AAPL"], "2026-01-01", "2026-01-05", as_of="2026-01-02T00:00:00Z", get_json=lambda p: payload)
    assert [a["id"] for a in res] == [1]
    assert res[0]["updated_at"] == "2026-01-05T00:00:00Z"


def test_page_cap_stops_runaway_pagination():
    calls = []
    def get(path):
        calls.append(1)
        return {"news": [], "next_page_token": "again"}
    n.fetch_news(["AAPL"], "a", "b", get_json=get)
    assert len(calls) == n.MAX_PAGES
