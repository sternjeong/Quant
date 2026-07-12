"""core/page_order.py 페이지 재정렬 유틸 검증 (실제 파일 rename을 tmp_path에서 수행)."""

from core import page_order


def _make_pages(tmp_path, names: list[str]) -> None:
    for name in names:
        (tmp_path / name).write_text("# dummy page\n")


def test_list_pages_sorts_numerically_not_lexicographically(tmp_path):
    _make_pages(tmp_path, ["2_b.py", "10_j.py", "1_a.py"])
    entries = page_order.list_pages(tmp_path)
    assert [e.filename for e in entries] == ["1_a.py", "2_b.py", "10_j.py"]
    assert [e.label for e in entries] == ["a", "b", "j"]


def test_list_pages_ignores_non_matching_files(tmp_path):
    _make_pages(tmp_path, ["1_a.py", "b.py", "__init__.py"])
    entries = page_order.list_pages(tmp_path)
    assert [e.filename for e in entries] == ["1_a.py"]


def test_reorder_pages_renumbers_without_collision(tmp_path):
    _make_pages(tmp_path, ["1_a.py", "2_b.py", "3_c.py"])
    page_order.reorder_pages(tmp_path, ["3_c.py", "1_a.py", "2_b.py"])
    entries = page_order.list_pages(tmp_path)
    assert [e.filename for e in entries] == ["1_c.py", "2_a.py", "3_b.py"]


def test_move_page_up(tmp_path):
    _make_pages(tmp_path, ["1_a.py", "2_b.py", "3_c.py"])
    page_order.move_page(tmp_path, "3_c.py", "up")
    entries = page_order.list_pages(tmp_path)
    assert [e.label for e in entries] == ["a", "c", "b"]


def test_move_page_down(tmp_path):
    _make_pages(tmp_path, ["1_a.py", "2_b.py", "3_c.py"])
    page_order.move_page(tmp_path, "1_a.py", "down")
    entries = page_order.list_pages(tmp_path)
    assert [e.label for e in entries] == ["b", "a", "c"]


def test_move_page_top(tmp_path):
    _make_pages(tmp_path, ["1_a.py", "2_b.py", "3_c.py"])
    page_order.move_page(tmp_path, "3_c.py", "top")
    entries = page_order.list_pages(tmp_path)
    assert [e.label for e in entries] == ["c", "a", "b"]


def test_move_page_bottom(tmp_path):
    _make_pages(tmp_path, ["1_a.py", "2_b.py", "3_c.py"])
    page_order.move_page(tmp_path, "1_a.py", "bottom")
    entries = page_order.list_pages(tmp_path)
    assert [e.label for e in entries] == ["b", "c", "a"]


def test_move_page_noop_at_boundary(tmp_path):
    _make_pages(tmp_path, ["1_a.py", "2_b.py"])
    page_order.move_page(tmp_path, "1_a.py", "up")  # 이미 맨 위
    page_order.move_page(tmp_path, "2_b.py", "down")  # 이미 맨 아래
    entries = page_order.list_pages(tmp_path)
    assert [e.filename for e in entries] == ["1_a.py", "2_b.py"]
