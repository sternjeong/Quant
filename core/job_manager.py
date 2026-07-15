"""페이지를 이동해도 끊기지 않는 백그라운드 작업 실행기.

Streamlit은 사용자가 다른 페이지로 이동(또는 어떤 위젯이든 조작)하면 현재 실행 중인 스크립트를
그 자리에서 중단하고 새로 rerun한다. 즉 `with st.spinner(...): result = 무거운_함수()`처럼 페이지
스크립트 안에서 동기적으로 실행하는 작업은, 그 작업이 끝나기 전에 사용자가 다른 페이지로 넘어가면
같이 취소되어 버린다.

이를 피하려면 실제 작업은 Streamlit의 스크립트 실행 스레드가 아니라 별도 스레드 풀에서 돌리고,
페이지는 진행 상태를 세션에 저장된 job id로 추적하며 폴링만 해야 한다 — 그러면 스레드 풀의 작업은
사용자가 어느 페이지에 있든, 심지어 브라우저 탭을 옮겨도 백그라운드에서 계속 실행된다.

이 앱은 1인 로컬 사용 전제(SPEC.md 0장)라, 작업 레지스트리를 프로세스 전역(모듈 레벨)에 둔다 —
세션 재실행과 무관하게 살아있어야 페이지를 옮겨도 작업이 이어지기 때문이다.
"""

from __future__ import annotations

import ctypes
import threading
import time
import uuid
from dataclasses import dataclass, field
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable, Optional

import streamlit as st

_PRUNE_AFTER_SECONDS = 300.0  # 완료된 지 5분 지난 작업은 다음 start() 때 레지스트리에서 정리


class _JobCancelledError(BaseException):
    """강제 종료된 작업의 스레드에 비동기로 주입하는 예외.

    작업 함수가 `except Exception`으로 감싸여 있어도 그대로 통과해 스레드를 빠져나가도록
    Exception이 아닌 BaseException을 상속한다.
    """


@dataclass
class Job:
    id: str
    label: str
    status: str = "running"  # running | done | error
    result: Any = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    future: Optional[Future] = None
    thread_ident: Optional[int] = None

    @property
    def elapsed_seconds(self) -> float:
        end = self.finished_at if self.finished_at is not None else time.time()
        return end - self.created_at


_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="quant-job")
_lock = threading.Lock()
_jobs: dict[str, Job] = {}


def _run(job_id: str, func: Callable, args: tuple, kwargs: dict) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job is not None:
            job.thread_ident = threading.get_ident()
    try:
        result = func(*args, **kwargs)
    except _JobCancelledError:
        return  # cancel()이 이미 레지스트리에서 제거했으니 상태 갱신 없이 조용히 종료
    except Exception as e:  # noqa: BLE001 - 백그라운드 스레드 예외를 Job.error로 전달
        with _lock:
            job = _jobs.get(job_id)
            if job is not None:
                job.status = "error"
                job.error = str(e)
                job.finished_at = time.time()
        return
    with _lock:
        job = _jobs.get(job_id)
        if job is not None:
            job.status = "done"
            job.result = result
            job.finished_at = time.time()


def _force_stop_thread(ident: int) -> None:
    """CPython 비공식 API로 대상 스레드에 비동기 예외를 주입해 강제 종료를 시도한다.

    스레드가 소켓 등 블로킹 C 콜(네트워크 조회 등) 안에 있으면 그 콜이 파이썬 바이트코드로
    돌아올 때까지는 실제로 멈추지 않는다 — 100% 즉시 종료를 보장하지 않는 베스트 에포트다.
    그래도 cancel()이 레지스트리에서 즉시 제거하므로 UI(사이드바 목록)에서는 바로 사라진다.
    """
    res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
        ctypes.c_long(ident), ctypes.py_object(_JobCancelledError)
    )
    if res > 1:  # 예외가 둘 이상의 스레드에 걸렸다면(비정상) 롤백
        ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_long(ident), None)


def cancel(job_id: str) -> bool:
    """작업을 강제 종료한다. 아직 시작 전이었다면 실행 자체를 취소하고, 이미 실행 중이었다면
    스레드에 종료 예외 주입을 시도한다. 어느 쪽이든 레지스트리에서 즉시 제거되어 사이드바 목록과
    각 페이지의 render()에서는 곧바로 "작업 없음" 상태로 보인다.

    존재하지 않거나 이미 끝난 job_id면 False를 반환한다.
    """
    with _lock:
        job = _jobs.pop(job_id, None)
    if job is None:
        return False
    if job.future is not None:
        job.future.cancel()  # 아직 스레드 풀 큐에서 시작 전이었다면 이것만으로 충분
    if job.thread_ident is not None:
        _force_stop_thread(job.thread_ident)
    return True


def _prune_finished() -> None:
    now = time.time()
    stale = [
        jid
        for jid, j in _jobs.items()
        if j.status != "running" and j.finished_at is not None and now - j.finished_at > _PRUNE_AFTER_SECONDS
    ]
    for jid in stale:
        _jobs.pop(jid, None)


def start(slot: str, func: Callable, *args, label: str = "", **kwargs) -> str:
    """`slot`에 새 작업을 시작한다 (버튼 클릭 등으로 명시적으로 트리거될 때 호출).

    같은 슬롯에 이미 추적 중인 작업이 있었다면 그 추적을 새 작업으로 덮어쓴다(이전 작업은
    취소되지 않고 백그라운드에서 계속 실행되다가 스스로 끝나면 정리된다).
    """
    job_id = uuid.uuid4().hex
    with _lock:
        _prune_finished()
        _jobs[job_id] = Job(id=job_id, label=label or slot)
    future = _executor.submit(_run, job_id, func, args, kwargs)
    with _lock:
        job = _jobs.get(job_id)
        if job is not None:
            job.future = future
    st.session_state[f"_job_slot::{slot}"] = {"job_id": job_id, "params_key": None}
    return job_id


def ensure(slot: str, params_key: Any, func: Callable, *args, label: str = "", **kwargs) -> None:
    """페이지 로드 시 자동으로 실행되는 조회 작업용 — `params_key`(예: 티커)가 이전과 같으면
    이미 추적 중인 작업을 그대로 재사용하고, 다르면(또는 아직 없으면) 새로 시작한다.

    버튼 클릭 없이 매 rerun마다 호출해도, params_key가 그대로면 중복으로 새 작업을 만들지 않는다.
    """
    tracked = st.session_state.get(f"_job_slot::{slot}")
    if tracked is not None and tracked.get("params_key") == params_key:
        return
    job_id = start(slot, func, *args, label=label, **kwargs)
    st.session_state[f"_job_slot::{slot}"]["params_key"] = params_key
    _ = job_id


def render(slot: str, *, running_label: Optional[str] = None, poll_seconds: float = 0.4) -> Optional[Job]:
    """매 rerun마다 호출: 진행 중이면 상태를 표시하고 자동으로 새로고침하며, 끝났으면 Job을
    반환한다(반환 후 추적은 정리되므로 결과는 그 자리에서 바로 꺼내 써야 한다).

    추적 중인 작업이 없으면 None을 반환한다.
    """
    session_key = f"_job_slot::{slot}"
    tracked = st.session_state.get(session_key)
    if not tracked:
        return None
    with _lock:
        job = _jobs.get(tracked["job_id"])
    if job is None:
        st.session_state.pop(session_key, None)
        return None

    if job.status == "running":
        label = running_label or f"⏳ {job.label} 실행 중..."
        st.info(f"{label} ({job.elapsed_seconds:.0f}초 경과)")
        time.sleep(poll_seconds)
        st.rerun()
        return None  # pragma: no cover - st.rerun()이 예외를 던져 여기 도달하지 않음

    st.session_state.pop(session_key, None)
    with _lock:
        _jobs.pop(job.id, None)
    return job


def is_slot_running(slot: str) -> bool:
    tracked = st.session_state.get(f"_job_slot::{slot}")
    if not tracked:
        return False
    with _lock:
        job = _jobs.get(tracked["job_id"])
    return job is not None and job.status == "running"


def list_running_jobs() -> list[Job]:
    with _lock:
        return [j for j in _jobs.values() if j.status == "running"]


def render_active_jobs_sidebar() -> None:
    """모든 페이지 사이드바에 현재 백그라운드에서 실행 중인 작업 목록을 보여준다.

    다른 페이지로 이동해도 이전 페이지에서 시작한 작업이 계속 실행되고 있음을 알 수 있게 하기
    위함이다. 이 함수 자체는 rerun을 강제하지 않는다(다른 위젯 조작 등 자연스러운 rerun이 있을
    때마다 최신 상태로 갱신된다) — 작업을 소유한 페이지로 돌아가면 그 페이지의 `render()`가
    실시간으로 진행률을 갱신해준다.
    """
    jobs = list_running_jobs()
    with st.sidebar:
        if not jobs:
            return
        st.markdown("---")
        st.caption("🔄 백그라운드 작업 실행 중 (다른 페이지로 이동해도 계속 진행됩니다)")
        for j in jobs:
            st.caption(f"⏳ {j.label} — {j.elapsed_seconds:.0f}초 경과")
            if st.button("🛑 강제 종료", key=f"_job_kill::{j.id}"):
                cancel(j.id)
                st.rerun()
