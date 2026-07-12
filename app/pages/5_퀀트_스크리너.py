"""모듈 E: 퀀트 스크리너 페이지.

PER/PBR/시가총액/섹터/기술적 지표(RSI, 200일선) 조건으로 종목(기본: S&P500)을 필터링하고,
결과를 관심 티커 리스트(모듈 C)에 바로 추가할 수 있다.
"""

import sys
from pathlib import Path

# --- sys.path 부트스트랩: 프로젝트 루트를 추가해 core.* 임포트 가능하게 함 (app/pages/*.py 공통 규칙) ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

from core.db import init_db
from core import job_manager
from core.screener import list_sectors, screen
from core.theme import apply_theme
from core.watchlist import MAX_WATCHLIST_SIZE, add_to_watchlist, get_watchlist_count

init_db()

st.set_page_config(page_title="퀀트 스크리너", page_icon="🔎", layout="wide")
apply_theme()
job_manager.render_active_jobs_sidebar()
st.title("🔎 퀀트 스크리너")
st.caption(
    "PER/PBR/시가총액/섹터/기술적 지표 조건으로 S&P500 종목을 필터링합니다. "
    "종목 유니버스는 위키피디아에서 받아와 24시간 캐시하며, 네트워크 오류 시 소규모 대체 목록을 사용합니다."
)

with st.form("screener_form"):
    st.markdown("### 필터 조건 (비워두면 해당 조건 미적용)")

    c1, c2, c3 = st.columns(3)
    with c1:
        per_min = st.number_input("PER 최소", value=None, placeholder="예: 0", step=1.0)
        per_max = st.number_input("PER 최대", value=None, placeholder="예: 20", step=1.0)
    with c2:
        pbr_min = st.number_input("PBR 최소", value=None, placeholder="예: 0", step=0.5)
        pbr_max = st.number_input("PBR 최대", value=None, placeholder="예: 3", step=0.5)
    with c3:
        mcap_min_b = st.number_input("시가총액 최소 (억 달러)", value=None, placeholder="예: 10", step=10.0)
        mcap_max_b = st.number_input("시가총액 최대 (억 달러)", value=None, placeholder="예: 5000", step=10.0)

    c4, c5, c6 = st.columns(3)
    with c4:
        sectors = st.multiselect("섹터", list_sectors())
    with c5:
        rsi_min = st.number_input("RSI 최소", value=None, placeholder="예: 0", step=5.0, min_value=0.0, max_value=100.0)
        rsi_max = st.number_input("RSI 최대", value=None, placeholder="예: 30 (과매도)", step=5.0, min_value=0.0, max_value=100.0)
    with c6:
        sma200_choice = st.radio("200일 이동평균선 대비", ["조건 없음", "위 (상승 추세)", "아래 (하락 추세)"], horizontal=False)

    custom_tickers_str = st.text_input(
        "티커 직접 지정 (쉼표로 구분, 비워두면 S&P500 전체 스캔 — 시간이 걸릴 수 있습니다)",
        placeholder="예: AAPL, MSFT, NVDA",
    )

    submitted = st.form_submit_button("🔍 스크리닝 실행", type="primary")

if submitted:
    filters = {
        "per_min": per_min,
        "per_max": per_max,
        "pbr_min": pbr_min,
        "pbr_max": pbr_max,
        "market_cap_min": mcap_min_b * 1e8 if mcap_min_b else None,
        "market_cap_max": mcap_max_b * 1e8 if mcap_max_b else None,
        "sectors": sectors or None,
        "rsi_min": rsi_min,
        "rsi_max": rsi_max,
        "above_sma200": {"조건 없음": None, "위 (상승 추세)": True, "아래 (하락 추세)": False}[sma200_choice],
    }

    tickers = None
    if custom_tickers_str.strip():
        tickers = [t.strip().upper() for t in custom_tickers_str.split(",") if t.strip()]

    needs_technicals = filters["rsi_min"] is not None or filters["rsi_max"] is not None or filters["above_sma200"] is not None

    job_manager.start(
        "screener_run", screen, tickers=tickers, filters=filters, include_technicals=needs_technicals,
        label="퀀트 스크리닝",
    )

screener_job = job_manager.render(
    "screener_run", running_label="스크리닝 중 (전체 S&P500 스캔 시 수 분 걸릴 수 있습니다)"
)
if screener_job is not None:
    if screener_job.status == "error":
        st.error(f"스크리닝 중 오류가 발생했습니다: {screener_job.error}")
    else:
        st.session_state["screener_result"] = screener_job.result

result = st.session_state.get("screener_result")
if result is not None:
    st.divider()
    st.markdown(f"### 스크리닝 결과 ({len(result)}개)")
    if result.empty:
        st.warning("조건에 맞는 종목이 없습니다.")
    else:
        display_df = result.rename(
            columns={
                "ticker": "티커",
                "name": "종목명",
                "sector": "섹터",
                "per": "PER",
                "pbr": "PBR",
                "market_cap": "시가총액",
                "price": "현재가",
                "rsi": "RSI",
                "above_sma200": "200일선 위",
            }
        )
        st.dataframe(display_df, use_container_width=True, hide_index=True)

        st.markdown("### 관심 티커에 추가")
        current_count = get_watchlist_count()
        st.caption(f"현재 관심 티커 {current_count}/{MAX_WATCHLIST_SIZE}개")
        add_targets = st.multiselect("추가할 티커 선택", result["ticker"].tolist())
        if st.button("➕ 관심 티커에 추가", disabled=not add_targets):
            errors = []
            added = 0
            for t in add_targets:
                try:
                    add_to_watchlist(t, memo="퀀트 스크리너에서 추가")
                    added += 1
                except ValueError as e:
                    errors.append(str(e))
            if added:
                st.toast(f"{added}개 티커를 관심 티커에 추가했습니다.", icon="✅")
            for e in errors:
                st.error(e)
