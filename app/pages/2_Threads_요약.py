"""모듈 B: Threads 글 -> 티커별 요약 페이지.

Threads 자동 크롤링은 막혀 있으므로, 원문을 직접 붙여넣으면 AI가 관련 티커를 자동 인식하고
요약을 생성한다. 자동 인식이 틀렸을 경우 저장 전/후 모두 티커를 직접 수정할 수 있다.
저장된 글은 티커별로 시간순 히스토리를 모아볼 수 있다.
"""

import sys
from datetime import datetime
from pathlib import Path

# --- sys.path 부트스트랩: 프로젝트 루트를 추가해 core.* 임포트 가능하게 함 (app/pages/*.py 공통 규칙) ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

from core.db import init_db
from core import job_manager
from core.threads_summary import (
    analyze_text,
    delete_summary,
    delete_weekly_report,
    generate_report_feedback,
    generate_weekly_report,
    get_ticker_history,
    list_summaries,
    list_tracked_tickers,
    list_weekly_reports,
    save_report_feedback,
    save_summary,
    save_weekly_report,
    update_tickers,
)
from core.theme import apply_theme

init_db()

st.set_page_config(page_title="Threads 요약", page_icon="🧵", layout="wide")
apply_theme()
job_manager.render_active_jobs_sidebar()
st.title("🧵 Threads 글 → 티커별 요약")
st.caption(
    "Threads 자동 크롤링은 막혀 있어, 원문을 직접 붙여넣으면 AI가 관련 티커를 자동 인식하고 요약합니다. "
    "GEMINI_API_KEY가 없으면 정규식 기반으로 티커 후보만 추출합니다 (요약은 원문 일부로 대체)."
)

tab_new, tab_history, tab_report = st.tabs(["✍️ 새 글 분석", "📚 티커별 히스토리", "📅 주간 인사이트 리포트"])

# ============================================================================
# 탭 1: 새 글 붙여넣기 -> AI 분석 -> 티커 수정 -> 저장
# ============================================================================
with tab_new:
    raw_text = st.text_area("Threads 원문 붙여넣기", height=200, placeholder="여기에 원문을 붙여넣으세요...")

    if st.button("🔍 분석하기", disabled=not raw_text.strip()):
        job_manager.start("threads_analyze", analyze_text, raw_text, label="Threads 글 분석")

    analyze_job = job_manager.render("threads_analyze", running_label="AI가 티커를 인식하고 요약을 생성하는 중")
    if analyze_job is not None:
        if analyze_job.status == "error":
            st.error(f"분석 중 오류가 발생했습니다: {analyze_job.error}")
        else:
            result = analyze_job.result
            st.session_state["analyzed_raw_text"] = raw_text
            st.session_state["analyzed_tickers"] = ", ".join(result["tickers"])
            st.session_state["analyzed_summary"] = result["summary"]

    if "analyzed_raw_text" in st.session_state:
        st.divider()
        st.markdown("### 분석 결과 (저장 전 직접 수정 가능)")

        edited_tickers = st.text_input(
            "인식된 티커 (쉼표로 구분, 자동 인식이 틀렸다면 직접 수정)",
            value=st.session_state["analyzed_tickers"],
        )
        edited_summary = st.text_area("AI 요약 (필요시 수정)", value=st.session_state["analyzed_summary"], height=120)

        if st.button("💾 저장", type="primary"):
            tickers = [t.strip() for t in edited_tickers.split(",") if t.strip()]
            try:
                save_summary(st.session_state["analyzed_raw_text"], tickers, edited_summary)
                st.toast("저장 완료.", icon="✅")
                for key in ("analyzed_raw_text", "analyzed_tickers", "analyzed_summary"):
                    st.session_state.pop(key, None)
                st.rerun()
            except ValueError as e:
                st.error(str(e))

    st.divider()
    st.markdown("### 최근 저장된 글")
    recent = list_summaries(limit=20)
    if not recent:
        st.info("아직 저장된 글이 없습니다.")
    else:
        for item in recent:
            with st.expander(
                f"{', '.join(item['tickers']) or '(티커 없음)'} — {item['created_at'].strftime('%Y-%m-%d %H:%M')}"
            ):
                st.write(item["ai_summary"])
                st.caption(item["raw_text"][:300] + ("..." if len(item["raw_text"]) > 300 else ""))

                retag_key = f"retag_{item['id']}"
                new_tickers_str = st.text_input(
                    "티커 재태깅", value=", ".join(item["tickers"]), key=retag_key
                )
                col1, col2 = st.columns([1, 1])
                if col1.button("✏️ 티커 수정 저장", key=f"save_retag_{item['id']}"):
                    new_tickers = [t.strip() for t in new_tickers_str.split(",") if t.strip()]
                    update_tickers(item["id"], new_tickers)
                    st.toast("티커를 수정했습니다.", icon="✅")
                    st.rerun()
                if col2.button("🗑️ 삭제", key=f"delete_{item['id']}"):
                    delete_summary(item["id"])
                    st.toast("삭제했습니다.", icon="🗑️")
                    st.rerun()

# ============================================================================
# 탭 2: 티커별 히스토리 모아보기
# ============================================================================
with tab_history:
    tracked = list_tracked_tickers()
    if not tracked:
        st.info("아직 태깅된 티커가 없습니다. '새 글 분석' 탭에서 먼저 글을 저장해주세요.")
    else:
        selected_ticker = st.selectbox("티커 선택", tracked)
        history = get_ticker_history(selected_ticker)
        st.caption(f"{selected_ticker} 관련 글 {len(history)}건 (시간순)")
        for item in history:
            st.markdown(f"**{item['created_at'].strftime('%Y-%m-%d %H:%M')}**")
            st.write(item["ai_summary"])
            with st.expander("원문 보기"):
                st.write(item["raw_text"])
            st.divider()

# ============================================================================
# 탭 3: 주간 AI 인사이트 리포트 — 개별 글 요약이 아니라, 최근 N일간 저장된 글
# 여러 개를 종합했을 때만 드러나는 테마/정서 변화/촉매·리스크를 뽑아낸다.
# 버튼으로 즉시 생성하거나, scheduler/run_scheduler.py의 주간 잡으로 자동 생성된
# 리포트를 히스토리에서 확인할 수 있다.
# ============================================================================
with tab_report:
    tracked_for_report = list_tracked_tickers()
    if not tracked_for_report:
        st.info("아직 태깅된 티커가 없습니다. '새 글 분석' 탭에서 먼저 글을 저장해주세요.")
    else:
        st.caption(
            "선택한 티커에 대해 최근 N일간 저장된 글을 AI가 종합 분석해 리포트를 만듭니다. "
            "단순 요약이 아니라 테마·정서 변화·촉매/리스크·합의-소수의견·관찰 포인트를 뽑아냅니다. "
            "매주 자동 생성을 원하면 `scheduler/run_scheduler.py`를 계속 실행해두세요 "
            "(매주 일요일 20:00 America/New_York에 추적 중인 모든 티커에 대해 자동 생성됩니다)."
        )
        col_ticker, col_days, col_btn = st.columns([2, 1, 1])
        with col_ticker:
            report_ticker = st.selectbox("티커 선택", tracked_for_report, key="report_ticker")
        with col_days:
            report_days = st.number_input("최근 며칠", min_value=1, max_value=30, value=7, key="report_days")
        with col_btn:
            st.write("")
            st.write("")
            generate_clicked = st.button("🧠 리포트 생성", type="primary", use_container_width=True)

        if generate_clicked:
            job_manager.start(
                "threads_weekly_report", generate_weekly_report, report_ticker, days=int(report_days),
                label=f"{report_ticker} 주간 인사이트 리포트",
            )

        report_job = job_manager.render(
            "threads_weekly_report", running_label=f"{report_ticker} 최근 {report_days}일 글을 종합 분석하는 중"
        )
        if report_job is not None:
            if report_job.status == "error":
                st.error(f"리포트 생성 중 오류가 발생했습니다: {report_job.error}")
            else:
                result = report_job.result
                if result["post_count"] > 0:
                    save_weekly_report(
                        result["ticker"], result["period_start"], result["period_end"],
                        result["post_count"], result["report"],
                    )
                    st.toast("리포트를 생성하고 저장했습니다.", icon="✅")
                st.session_state["latest_report"] = result

        latest_report = st.session_state.get("latest_report")
        if latest_report and latest_report["ticker"] == report_ticker:
            st.divider()
            period_label = (
                f"{latest_report['period_start'].strftime('%Y-%m-%d')} ~ "
                f"{latest_report['period_end'].strftime('%Y-%m-%d')}"
            )
            st.markdown(f"### {latest_report['ticker']} 인사이트 리포트 ({period_label}, 글 {latest_report['post_count']}건)")
            st.markdown(latest_report["report"])

        st.divider()
        st.markdown("### 리포트 히스토리")
        st.caption(
            "리포트를 생성하고 시간이 좀 지난 뒤(예: 한 달 정도, 또는 리포트가 다룬 기간만큼) "
            "\"🔍 피드백 확인\"을 누르면, 그때 가격 대비 지금 가격이 어떻게 됐고 리포트의 테마/촉매/"
            "리스크/관찰 포인트가 실제로 얼마나 들어맞았는지 AI가 회고해줍니다."
        )
        past_reports = list_weekly_reports(report_ticker)
        if not past_reports:
            st.info("아직 생성된 리포트가 없습니다. 위 버튼으로 첫 리포트를 만들어보세요.")
        else:
            for r in past_reports:
                elapsed_days = (datetime.utcnow() - r["created_at"]).days
                label = (
                    f"{r['period_start'].strftime('%Y-%m-%d')} ~ {r['period_end'].strftime('%Y-%m-%d')} "
                    f"(글 {r['post_count']}건, 생성일 {r['created_at'].strftime('%Y-%m-%d %H:%M')}, "
                    f"{elapsed_days}일 경과)"
                )
                with st.expander(label):
                    st.markdown(r["report_text"])
                    if r["price_at_generation"] is not None:
                        st.caption(f"리포트 생성 시점 종가: {r['price_at_generation']:,.2f}")

                    st.divider()
                    if r["feedback_text"]:
                        st.markdown("#### 🔍 사후 검증(회고)")
                        if r["feedback_price"] is not None and r["price_at_generation"] is not None:
                            change_pct = (r["feedback_price"] / r["price_at_generation"] - 1) * 100
                            st.caption(
                                f"회고 시점({r['feedback_generated_at'].strftime('%Y-%m-%d %H:%M')}) 종가: "
                                f"{r['feedback_price']:,.2f} ({change_pct:+.1f}%)"
                            )
                        st.markdown(r["feedback_text"])

                    col_fb, col_del = st.columns([1, 1])
                    feedback_slot = f"threads_feedback_{r['id']}"
                    if col_fb.button(
                        "🔍 피드백 확인" if not r["feedback_text"] else "🔍 피드백 다시 확인",
                        key=f"feedback_{r['id']}",
                        use_container_width=True,
                    ):
                        job_manager.start(
                            feedback_slot, generate_report_feedback, r["id"], label=f"{report_ticker} 리포트 회고"
                        )

                    feedback_job = job_manager.render(
                        feedback_slot, running_label="가격 변화를 확인하고 리포트를 회고하는 중"
                    )
                    if feedback_job is not None:
                        if feedback_job.status == "error":
                            st.error(f"피드백 생성 중 오류가 발생했습니다: {feedback_job.error}")
                        else:
                            fb = feedback_job.result
                            save_report_feedback(r["id"], fb["feedback"], fb["current_price"])
                            st.toast("피드백을 생성했습니다.", icon="✅")
                            st.rerun()
                    if col_del.button("🗑️ 리포트 삭제", key=f"delete_report_{r['id']}", use_container_width=True):
                        delete_weekly_report(r["id"])
                        st.toast("리포트를 삭제했습니다.", icon="🗑️")
                        st.rerun()
