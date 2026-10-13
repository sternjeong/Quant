"""V1 티커 뉴스 리서치: 무료 API 메타데이터를 출처 링크와 함께 요약한다."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

from core import job_manager
from core.db import init_db
from core.news_digest import (
    ensure_default_subscriptions,
    list_latest_digests,
    list_news_articles,
    list_subscriptions,
    replace_subscriptions,
    run_news_pipeline,
)
from core.theme import apply_theme
from core.ui_status import render_status_header


init_db()
ensure_default_subscriptions()
st.set_page_config(page_title="뉴스 리서치", page_icon="📰", layout="wide")
apply_theme()
job_manager.render_active_jobs_sidebar()

st.title("📰 티커별 뉴스 리서치")
render_status_header("news")
st.caption(
    "Finnhub·FMP가 제공한 제목·짧은 설명·원문 링크만 수집해 티커별로 종합합니다. "
    "기사 전문을 스크래핑하지 않으며, 요약은 연구 보조 정보일 뿐 매매 권고가 아닙니다."
)

subscriptions = list_subscriptions()
tickers = [row["ticker"] for row in subscriptions]

with st.expander("수집 티커 설정", expanded=False):
    edited = st.text_area(
        "티커 (쉼표 또는 줄바꿈으로 구분)", value=", ".join(tickers),
        help="처음에는 챔피언 전략 코어 ETF 17개가 들어 있습니다. 이 목록은 관심종목 매매 감시와 별개입니다.",
    )
    if st.button("티커 목록 저장"):
        try:
            saved = replace_subscriptions(edited.replace("\n", ",").split(","))
            st.success(f"{len(saved)}개 티커를 저장했습니다.")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

left, right = st.columns([1, 2])
with left:
    st.metric("뉴스 대상", f"{len(tickers)}개")
with right:
    if st.button("지금 수집·요약", type="primary", disabled=not tickers):
        job_manager.start("news_refresh", run_news_pipeline, tickers, force=True, label="뉴스 수집·요약")

pipeline_job = job_manager.render("news_refresh", running_label="무료 뉴스 API를 수집하고 티커별로 요약하는 중")
if pipeline_job is not None:
    if pipeline_job.status == "error":
        st.error(f"뉴스 수집·요약 실패: {pipeline_job.error}")
    else:
        result = pipeline_job.result
        st.success(
            f"수집 완료: 후보 {result['refresh']['attempted']}건 중 새 기사 {result['refresh']['added']}건, "
            f"새 요약 {len(result['digests'])}개"
        )
        if result["refresh"]["errors"]:
            st.caption("일부 공급자 응답 오류: " + ", ".join(result["refresh"]["errors"][:5]))

st.divider()
selected = st.selectbox("표시할 티커", ["전체"] + tickers)
selected_ticker = None if selected == "전체" else selected
digests = list_latest_digests(selected_ticker, limit=50)

st.subheader("최근 종합 요약")
if not digests:
    st.info("아직 뉴스 요약이 없습니다. ‘지금 수집·요약’을 누르거나 매일 KST 07:30 자동 보고를 기다리세요.")
else:
    for digest in digests:
        when = digest["created_at"].strftime("%Y-%m-%d %H:%M UTC")
        with st.expander(f"{digest['ticker']} · 기사 {digest['article_count']}건 · {when}", expanded=selected_ticker is not None):
            st.markdown(digest["summary"])
            st.caption("Claude 요약" if digest["summary_status"] == "claude" else "제목 기반 대체 요약")
            if digest.get("sentiment"):
                badge = {"bullish": "🟢 긍정", "bearish": "🔴 부정", "neutral": "⚪ 중립"}.get(digest["sentiment"], "⚪ 중립")
                score = digest.get("sentiment_score")
                score_text = f" ({score:+.2f})" if score is not None else ""
                st.caption(f"감성: {badge}{score_text}")
            st.markdown("**원문 출처**")
            for link in digest["source_links"]:
                label = f"{link.get('source', '출처')} · {link.get('title', '원문')[:130]}"
                st.link_button(label, link["url"], use_container_width=True)

st.divider()
st.subheader("수집된 기사 인덱스")
articles = list_news_articles(selected_ticker, limit=40)
if not articles:
    st.caption("표시할 수집 기사가 없습니다.")
else:
    for article in articles:
        published = article["published_at"].strftime("%Y-%m-%d %H:%M UTC") if article["published_at"] else "발행 시각 미제공"
        with st.expander(f"[{article['event_type']}] {article['headline']} — {article['source']}"):
            st.caption(published + " · " + ", ".join(article["tickers"]))
            if article["excerpt"]:
                st.write(article["excerpt"])
            st.link_button("원문 열기", article["url"])
