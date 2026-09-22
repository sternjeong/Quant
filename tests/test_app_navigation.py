from pathlib import Path

from core.app_navigation import NAVIGATION, all_pages


def test_navigation_groups_match_workflow():
    assert list(NAVIGATION) == ["홈", "운용", "탐색", "리서치", "시장", "시스템"]


def test_navigation_has_one_default_and_unique_paths():
    pages = all_pages()
    assert sum(page.default for page in pages) == 1
    assert len({page.path for page in pages}) == len(pages)


def test_navigation_paths_exist():
    app_dir = Path(__file__).resolve().parents[1] / "app"
    missing = [page.path for page in all_pages() if not (app_dir / page.path).exists()]
    assert missing == []
