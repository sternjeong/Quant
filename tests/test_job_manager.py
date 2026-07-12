"""core/job_manager.py 테스트.

job_manager는 실제 작업을 별도 스레드 풀에서 실행해 Streamlit 스크립트 rerun(페이지 이동 등)에
영향받지 않게 하는 것이 핵심이므로, Streamlit 스크립트 컨텍스트가 필요한 함수(start/ensure/render/
render_active_jobs_sidebar)는 AppTest로 실제 스크립트를 돌려 검증한다.
"""

import pytest
from streamlit.testing.v1 import AppTest

from core import job_manager


@pytest.fixture(autouse=True)
def _clean_registry():
    job_manager._jobs.clear()
    yield
    job_manager._jobs.clear()


def _basic_job_script():
    import time

    import streamlit as st

    from core import job_manager

    def _work():
        time.sleep(0.05)
        return "hello"

    if "started" not in st.session_state:
        job_manager.start("basic", _work, label="테스트 작업")
        st.session_state["started"] = True

    job = job_manager.render("basic", poll_seconds=0.02)
    if job is not None:
        st.session_state["final_status"] = job.status
        st.session_state["final_result"] = job.result


def test_render_waits_until_done_and_returns_result():
    at = AppTest.from_function(_basic_job_script)
    at.run()
    assert at.session_state["final_status"] == "done"
    assert at.session_state["final_result"] == "hello"
    # 완료된 작업은 render()가 소비하면서 레지스트리에서 제거되어야 한다.
    assert job_manager._jobs == {}


def _error_job_script():
    import streamlit as st

    from core import job_manager

    def _boom():
        raise ValueError("의도된 실패")

    if "started" not in st.session_state:
        job_manager.start("boom", _boom, label="실패하는 작업")
        st.session_state["started"] = True

    job = job_manager.render("boom", poll_seconds=0.02)
    if job is not None:
        st.session_state["final_status"] = job.status
        st.session_state["final_error"] = job.error


def test_render_surfaces_exception_as_error_status():
    at = AppTest.from_function(_error_job_script)
    at.run()
    assert at.session_state["final_status"] == "error"
    assert "의도된 실패" in at.session_state["final_error"]


def test_render_returns_none_when_no_job_tracked():
    def _script():
        import streamlit as st

        from core import job_manager

        result = job_manager.render("never_started")
        st.session_state["result_is_none"] = result is None

    at = AppTest.from_function(_script)
    at.run()
    assert at.session_state["result_is_none"] is True


def _ensure_dedup_script():
    import time

    import streamlit as st

    from core import job_manager

    def _slow_work():
        time.sleep(0.2)
        return "done"

    job_manager.ensure("slot_a", "AAPL", _slow_work, label="자동 조회")
    first_job_id = st.session_state["_job_slot::slot_a"]["job_id"]

    job_manager.ensure("slot_a", "AAPL", _slow_work, label="자동 조회")
    second_job_id = st.session_state["_job_slot::slot_a"]["job_id"]

    st.session_state["job_ids_match"] = first_job_id == second_job_id


def test_ensure_does_not_restart_job_for_same_params_key():
    at = AppTest.from_function(_ensure_dedup_script)
    at.run()
    # 같은 params_key로 두 번 ensure()를 불러도 기존에 추적 중인 job을 그대로 재사용해야 한다
    # (새 job_id로 덮어쓰면 새 백그라운드 작업이 중복으로 시작된 것).
    assert at.session_state["job_ids_match"] is True


def _ensure_param_change_script():
    import streamlit as st

    from core import job_manager

    def _work(ticker):
        return ticker

    if "phase" not in st.session_state:
        st.session_state["phase"] = "AAPL"

    job_manager.ensure("slot_b", st.session_state["phase"], _work, st.session_state["phase"], label="조회")
    job = job_manager.render("slot_b", poll_seconds=0.01)
    if job is not None:
        st.session_state.setdefault("results", []).append(job.result)
        if st.session_state["phase"] == "AAPL":
            st.session_state["phase"] = "MSFT"
            st.rerun()


def test_ensure_starts_new_job_when_params_key_changes():
    at = AppTest.from_function(_ensure_param_change_script)
    at.run()
    assert at.session_state["results"] == ["AAPL", "MSFT"]


def test_render_active_jobs_sidebar_lists_running_jobs():
    def _script():
        import threading

        import streamlit as st

        from core import job_manager

        started = threading.Event()
        finished = threading.Event()

        def _hang():
            started.set()
            finished.wait(timeout=2)
            return "ok"

        if "started" not in st.session_state:
            job_manager.start("hanging", _hang, label="오래 걸리는 작업")
            st.session_state["started"] = True
            started.wait(timeout=2)

        job_manager.render_active_jobs_sidebar()
        finished.set()  # 백그라운드 스레드가 바로 끝나도록 풀어준다

    at = AppTest.from_function(_script)
    at.run()
    sidebar_captions = [c.value for c in at.sidebar.caption]
    assert any("오래 걸리는 작업" in c for c in sidebar_captions)


def test_render_active_jobs_sidebar_empty_when_no_jobs():
    def _script():
        from core import job_manager

        job_manager.render_active_jobs_sidebar()

    at = AppTest.from_function(_script)
    at.run()
    assert at.sidebar.caption.len == 0
