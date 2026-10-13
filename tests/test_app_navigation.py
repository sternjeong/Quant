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


def test_no_legacy_pages_directory():
    # 빈 폴더도 구형 라우터를 켠다. 시작 직후 상세 URL이 Home.py를 건너뛸 수 있다.
    app_dir = Path(__file__).resolve().parents[1] / "app"
    assert not (app_dir / "pages").exists()


def test_cold_deep_link_and_rerun_keep_workspace_menu(tmp_path, monkeypatch):
    import streamlit as st
    from streamlit.runtime.pages_manager import PagesManager
    from streamlit.testing.v1 import AppTest

    from core import app_navigation, db
    from core.app_navigation import PageSpec

    # 실제 진입점을 사용하되 화면/DB는 작은 로컬 fixture로 대체한다.
    entrypoint = tmp_path / "Home.py"
    entrypoint.write_text((Path(__file__).resolve().parents[1] / "app/Home.py").read_text())
    views = tmp_path / "views"
    views.mkdir()
    (views / "today.py").write_text("import streamlit as st\nst.write('home')\n")
    (views / "detail.py").write_text(
        "import streamlit as st\n"
        "st.write('detail')\n"
        "if st.button('poll'):\n"
        "    st.rerun()\n"
    )
    monkeypatch.setattr(app_navigation, "NAVIGATION", {
        "홈": (PageSpec("views/today.py", "오늘", "🏠", default=True),),
        "운용": (PageSpec("views/detail.py", "상세", "📒"),),
    })
    monkeypatch.setattr(db, "init_db", lambda: None)
    monkeypatch.setattr(PagesManager, "uses_pages_directory", None)
    menus = []
    navigation = st.navigation

    def record_navigation(pages, **kwargs):
        menus.append((list(pages), kwargs))
        return navigation(pages, **kwargs)

    monkeypatch.setattr(st, "navigation", record_navigation)
    at = AppTest.from_file(entrypoint).switch_page("views/detail.py").run()
    assert not at.exception
    assert at.markdown[0].value == "detail"
    assert menus[-1] == (["홈", "운용"], {"position": "sidebar", "expanded": True})
    menus.clear()
    at.button[0].click().run()
    assert not at.exception
    assert at.markdown[0].value == "detail"
    assert menus[-1][0] == ["홈", "운용"]

    # DB 오류로 실행이 중단돼도 메뉴는 이미 등록돼 있어야 한다.
    monkeypatch.setattr(db, "init_db", st.stop)
    menus.clear()
    at.run()
    assert not at.exception
    assert menus[-1][0] == ["홈", "운용"]
