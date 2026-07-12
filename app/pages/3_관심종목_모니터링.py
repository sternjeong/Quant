"""모듈 C: 관심 티커 리스트(최대 50개) + 매일 타점 모니터링 페이지.

- 관심 티커를 최대 50개까지 등록하고, 백테스팅(모듈 A)에서 검증된 전략을 연결한다.
- "지금 스캔 실행" 버튼으로 core.watchlist.scan_watchlist() 를 즉시 실행해 오늘 기준
  타점 발생 여부를 바로 확인할 수 있다 (scheduler/run_scheduler.py 가 매일 미국 장마감 후
  자동으로 실행하는 것과 완전히 동일한 로직).
- 스캔 중 신규 진입 신호가 발생한 종목은 alerts_log 에 기록되고, 데스크톱 알림도 함께 보낼 수 있다.
- 최근 타점 알림 로그를 확인하고 읽음 처리할 수 있다.
"""

import sys
from datetime import datetime
from pathlib import Path

# --- sys.path 부트스트랩: 프로젝트 루트를 추가해 core.* 임포트 가능하게 함 (app/pages/*.py 공통 규칙) ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import streamlit as st

from core.db import get_session, init_db
from core import job_manager
from core.models import Strategy
from core.notify import send_desktop_notification
from core.watchlist import (
    MAX_WATCHLIST_SIZE,
    add_to_watchlist,
    get_recent_alerts,
    get_unread_alert_count,
    list_watchlist,
    mark_alert_read,
    mark_all_alerts_read,
    remove_from_watchlist,
    scan_watchlist,
    update_watchlist_item,
)
from core.theme import apply_theme

init_db()

st.set_page_config(page_title="관심종목 모니터링", page_icon="🔔", layout="wide")
apply_theme()
job_manager.render_active_jobs_sidebar()
st.title("🔔 관심 티커 리스트 + 매일 타점 모니터링")
st.caption(
    "백테스팅에서 검증된 전략을 종목별로 연결해두면, 매일 미국 장마감 후 스케줄러가 "
    "자동으로 스캔해 타점 발생 시 알림을 보냅니다. 여기서는 등록/수정과 수동 스캔, 알림 이력을 관리합니다."
)

NO_STRATEGY_LABEL = "(전략 미지정)"


def _load_strategy_options() -> tuple[dict[int, str], list[str], dict[str, int | None]]:
    with get_session() as session:
        strategies = session.query(Strategy).order_by(Strategy.name).all()
        strategy_label_by_id = {s.id: f"{s.name} (#{s.id})" for s in strategies}
    options = [NO_STRATEGY_LABEL] + list(strategy_label_by_id.values())
    label_to_id: dict[str, int | None] = {NO_STRATEGY_LABEL: None}
    label_to_id.update({v: k for k, v in strategy_label_by_id.items()})
    return strategy_label_by_id, options, label_to_id


strategy_label_by_id, strategy_options, label_to_id = _load_strategy_options()

# ------------------------------------------------------------------
# 상단 요약
# ------------------------------------------------------------------
items = list_watchlist()
count = len(items)
unread_count = get_unread_alert_count()

col_m1, col_m2 = st.columns(2)
col_m1.metric("관심 티커", f"{count} / {MAX_WATCHLIST_SIZE}")
col_m2.metric("미확인 알림", unread_count)
st.progress(min(count / MAX_WATCHLIST_SIZE, 1.0))

st.divider()

# ------------------------------------------------------------------
# 관심 티커 추가
# ------------------------------------------------------------------
st.markdown("### 관심 티커 추가")

if strategies_missing := (len(strategy_options) == 1):
    st.caption("아직 저장된 전략이 없습니다. '백테스팅 엔진' 페이지에서 전략을 먼저 만들면 여기서 연결할 수 있습니다.")

with st.form("add_watchlist_form", clear_on_submit=True):
    col1, col2, col3, col4 = st.columns([2, 3, 3, 1])
    with col1:
        new_ticker = st.text_input("티커", placeholder="예: AAPL")
    with col2:
        new_strategy_label = st.selectbox("적용 전략", strategy_options)
    with col3:
        new_memo = st.text_input("메모", placeholder="선택 입력")
    with col4:
        st.write("")
        st.write("")
        submitted = st.form_submit_button("➕ 추가", use_container_width=True)

if submitted:
    if not new_ticker.strip():
        st.warning("티커를 입력해주세요.")
    else:
        try:
            new_id = add_to_watchlist(
                new_ticker, strategy_id=label_to_id[new_strategy_label], memo=new_memo or None
            )
            st.toast(f"{new_ticker.strip().upper()} 등록 완료 (id={new_id}).", icon="✅")
            st.rerun()
        except ValueError as e:
            st.error(str(e))

st.divider()

# ------------------------------------------------------------------
# 관심 티커 목록 (수정/삭제)
# ------------------------------------------------------------------
st.markdown("### 관심 티커 목록")

if not items:
    st.info("아직 등록된 관심 티커가 없습니다. 위에서 추가해보세요.")
else:
    header = st.columns([1.3, 3, 3, 1.6, 0.8, 0.8])
    header[0].markdown("**티커**")
    header[1].markdown("**적용 전략**")
    header[2].markdown("**메모**")
    header[3].markdown("**등록일**")
    header[4].markdown("**저장**")
    header[5].markdown("**삭제**")

    for item in items:
        cols = st.columns([1.3, 3, 3, 1.6, 0.8, 0.8])
        cols[0].markdown(f"`{item['ticker']}`")

        current_label = strategy_label_by_id.get(item["strategy_id"], NO_STRATEGY_LABEL)
        options_for_row = strategy_options if current_label in strategy_options else strategy_options + [current_label]
        selected_label = cols[1].selectbox(
            "전략",
            options_for_row,
            index=options_for_row.index(current_label),
            key=f"wl_strategy_{item['id']}",
            label_visibility="collapsed",
        )
        memo_val = cols[2].text_input(
            "메모", value=item["memo"], key=f"wl_memo_{item['id']}", label_visibility="collapsed"
        )
        added_at = item["added_at"]
        cols[3].markdown(added_at.strftime("%Y-%m-%d") if added_at else "-")

        if cols[4].button("💾", key=f"wl_save_{item['id']}", help="저장"):
            update_watchlist_item(item["id"], strategy_id=label_to_id.get(selected_label), memo=memo_val or None)
            st.toast(f"{item['ticker']} 업데이트 완료.", icon="✅")
            st.rerun()
        if cols[5].button("🗑️", key=f"wl_del_{item['id']}", help="삭제"):
            remove_from_watchlist(item["id"])
            st.toast(f"{item['ticker']} 삭제 완료.", icon="🗑️")
            st.rerun()

st.divider()

# ------------------------------------------------------------------
# 수동 스캔
# ------------------------------------------------------------------
st.markdown("### 오늘의 타점 스캔")
st.caption(
    "스케줄러(scheduler/run_scheduler.py)를 백그라운드에서 실행해두면 매일 미국 장마감 후 자동으로 스캔합니다. "
    "지금 바로 확인하고 싶다면 아래 버튼으로 수동 스캔할 수 있습니다 (스케줄러와 완전히 동일한 로직)."
)

notify_checked = st.checkbox("스캔 결과를 데스크톱 알림으로도 보내기", value=True)

if st.button("🔍 지금 스캔 실행", type="primary", disabled=not items):
    job_manager.start(
        "watchlist_scan", scan_watchlist,
        notify_fn=send_desktop_notification if notify_checked else None,
        label="관심 종목 스캔",
    )

scan_job = job_manager.render(
    "watchlist_scan", running_label="관심 종목을 스캔하는 중 (종목 수에 따라 다소 시간이 걸릴 수 있습니다)"
)
if scan_job is not None:
    if scan_job.status == "error":
        st.error(f"스캔 중 오류가 발생했습니다: {scan_job.error}")
    else:
        st.session_state["last_scan_results"] = scan_job.result
        st.session_state["last_scan_time"] = datetime.now()

scan_results = st.session_state.get("last_scan_results")
if scan_results:
    st.caption(f"마지막 스캔: {st.session_state['last_scan_time'].strftime('%Y-%m-%d %H:%M:%S')}")

    rows = []
    for r in scan_results:
        if r.strategy_id is None:
            status = "⚪ 전략 미연결"
        elif r.as_of is None:
            status = "❌ 데이터 없음/오류"
        elif r.triggered:
            status = "🟢 신규 타점 발생"
        elif r.in_position:
            status = "🟡 조건 유지 중"
        else:
            status = "⚫ 조건 미충족"
        rows.append(
            {
                "티커": r.ticker,
                "전략": r.strategy_name or "-",
                "상태": status,
                "기준일": r.as_of or "-",
                "메시지": r.message,
            }
        )
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    triggered_count = sum(1 for r in scan_results if r.triggered)
    if triggered_count:
        st.success(f"{triggered_count}개 종목에서 신규 타점이 발생했습니다!")
    else:
        st.info("신규 타점이 발생한 종목이 없습니다.")

st.divider()

# ------------------------------------------------------------------
# 최근 타점 알림 로그
# ------------------------------------------------------------------
st.markdown("### 최근 타점 알림 로그")

col_a, col_b = st.columns([4, 1])
with col_a:
    st.caption(f"미확인 알림 {unread_count}건 (최근 50건 표시)")
with col_b:
    if st.button("전체 읽음 처리", disabled=unread_count == 0):
        mark_all_alerts_read()
        st.rerun()

alerts = get_recent_alerts(limit=50)
if not alerts:
    st.caption("아직 발생한 알림이 없습니다.")
else:
    header = st.columns([1.3, 3, 2, 4, 1])
    header[0].markdown("**티커**")
    header[1].markdown("**전략**")
    header[2].markdown("**발생시각**")
    header[3].markdown("**메시지**")
    header[4].markdown("**읽음**")

    for a in alerts:
        cols = st.columns([1.3, 3, 2, 4, 1])
        cols[0].markdown(f"`{a['ticker']}`")
        cols[1].markdown(a["strategy_name"] or "-")
        cols[2].markdown(a["detected_at"].strftime("%Y-%m-%d %H:%M") if a["detected_at"] else "-")
        cols[3].markdown(a["message"] or "-")
        if a["is_read"]:
            cols[4].markdown("✅")
        else:
            if cols[4].button("읽음", key=f"alert_read_{a['id']}"):
                mark_alert_read(a["id"])
                st.rerun()
