"""업무공간 내비게이션의 기본 화면: Today 명령 센터."""

from datetime import datetime

import streamlit as st

from core.theme import apply_theme
from core.today_dashboard import build_today_dashboard

st.set_page_config(page_title="오늘", page_icon="🏠", layout="wide")
apply_theme()


def _chip(label: str, value: str) -> None:
    st.markdown(
        f'<span class="quant-status-chip"><strong>{label}</strong> {value}</span>',
        unsafe_allow_html=True,
    )


def _link(path: str, label: str) -> None:
    st.page_link(path, label=label, width="stretch")


dashboard = build_today_dashboard()
generated = dashboard["generated_at"].strftime("%Y-%m-%d %H:%M UTC")
holdings = dashboard["holdings"] or {}
market = dashboard["market"] or {}
jobs = dashboard["jobs"] or {}

st.title("오늘")
st.caption("판단 → 근거 확인 → 안전한 실행. 저장된 상태만 읽으며, 이 화면은 새 시장 스캔이나 주문을 실행하지 않습니다.")

_chip("기준", generated)
_chip("주문", "PAPER 전용")
_chip("백업", {"fresh": "정상", "stale": "확인 필요", "blocked": "차단", "unknown": "상태 없음"}[dashboard["backup_status"]])
if holdings.get("as_of"):
    _chip("챔피언 신호", str(holdings["as_of"]))
if market.get("computed_at"):
    computed = market["computed_at"]
    computed_text = computed.strftime("%Y-%m-%d %H:%M UTC") if isinstance(computed, datetime) else str(computed)
    _chip("시장 스냅샷", computed_text)

st.divider()
state_col, allocation_col, risk_col, alert_col = st.columns(4)
with state_col:
    regime = market.get("regime", "UNKNOWN")
    st.metric("시장 국면", regime)
    if regime == "unknown":
        st.caption("데이터 부족에 따른 보류 상태")
with allocation_col:
    core = ", ".join(holdings.get("core_top4", [])) or "신호 없음"
    st.metric("코어 후보", str(len(holdings.get("core_top4", []))))
    st.caption(core)
with risk_col:
    st.metric("운영 경고", str(jobs.get("counts", {}).get("problem", 0)))
    st.caption("잡·백업·데이터 상태")
with alert_col:
    st.metric("읽지 않은 알림", str(dashboard["unread_alerts"]))
    st.caption(f"관심종목 {dashboard['watchlist_count']}개")

left, right = st.columns([1.2, 1])
with left:
    st.subheader("오늘 처리할 일")
    for action in dashboard["actions"]:
        st.markdown(
            f'<div class="quant-action-card {action["level"]}"><h4>{action["title"]}</h4>'
            f'<p>{action["detail"]}</p></div>',
            unsafe_allow_html=True,
        )
        _link(action["destination"], "자세히 보기")

with right:
    st.subheader("현재 전략 상태")
    st.markdown("**코어**")
    if holdings.get("core_top4"):
        st.code(" · ".join(holdings["core_top4"]), language=None)
    else:
        st.caption("저장된 코어 추천이 없습니다.")
    st.markdown("**새틀라이트**")
    if holdings.get("satellite_selected"):
        st.code(" · ".join(holdings["satellite_selected"]), language=None)
    else:
        st.caption("저장된 새틀라이트 추천이 없습니다.")
    st.caption("추천은 전략 신호이며, 주문 가능 여부와 별도입니다.")
    _link("pages/11_챔피언_전략.py", "챔피언 전략 열기")

st.divider()
st.subheader("작업공간")
workspace_links = (
    ("운용 알림", "pages/3_관심종목_모니터링.py"),
    ("운용", "pages/8_포트폴리오_관리.py"),
    ("탐색", "pages/5_종목_스크리닝.py"),
    ("리서치 랩", "pages/1_전략_스튜디오.py"),
    ("시장 정보", "pages/7_시장_진단.py"),
    ("시스템", "pages/10_환경설정.py"),
)
for column, (label, path) in zip(st.columns(len(workspace_links)), workspace_links):
    with column:
        _link(path, label)

with st.expander("이 서비스의 작업 방식", expanded=False):
    st.markdown(
        """
        - **오늘**에서는 저장된 신호·데이터 상태·운영 경고를 확인합니다.
        - **탐색**에서는 후보와 근거를 조사합니다.
        - **리서치**에서는 아이디어를 백테스트와 검증 게이트를 거쳐 paper 후보로 올립니다.

        화면의 `Unknown`, `PIT 미검증`, `Legacy` 표시는 투자 방향이 아니라 데이터·검증 상태를 뜻합니다.
        """
    )
