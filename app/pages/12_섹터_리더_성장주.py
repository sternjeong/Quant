"""(부가) 섹터별 대표 ETF · 대장주 · 성장주 관계 분석 페이지.

SECTOR_LEADER_GROWTH_RELATIONSHIP_SPEC.md 참고. 테마(GICS 11개 섹터 + 반도체/DRAM/우주)를 고르면
그 테마의 대표 ETF, 시가총액 1위 대장주, 이익성장률 백분위 상위 성장주 3개를 자동 선정하고,
셋의 베타(민감도)/상관계수(동조화)/상대강도(RS) 비율 추세를 계산해 보여준다.
"""

import sys
from pathlib import Path

# --- sys.path 부트스트랩: 프로젝트 루트를 추가해 core.* 임포트 가능하게 함 (app/pages/*.py 공통 규칙) ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.db import init_db
from core import job_manager
from core.sector_leaders import analyze_theme_relationships
from core.sector_strength import THEME_UNIVERSE
from core.theme import TRADINGVIEW_CHART_BG, TRADINGVIEW_CHART_GRID, TRADINGVIEW_CHART_TEXT, apply_theme

init_db()

st.set_page_config(page_title="섹터 리더/성장주 관계 분석", page_icon="🧭", layout="wide")
apply_theme()
job_manager.render_active_jobs_sidebar()
st.title("🧭 섹터 리더·성장주 관계 분석")
st.caption(
    "테마별 대표 ETF 대비 대장주(시가총액 1위)와 성장주(이익성장률 상위 3개, 시가총액 상위 25% "
    "초대형주는 후보에서 제외)의 베타(민감도)/상관계수(동조화)/상대강도(RS) 비율 추세를 계산합니다. "
    "애플/마이크로소프트 같은 초대형주가 '성장주'로 잡히지 않도록, 대장주 한 종목만 빼는 대신 "
    "시가총액 상위 25% 전체를 성장주 후보에서 제외합니다(최근 러셀 지수 재조정에서도 초대형주는 "
    "성장/가치 경계가 흐려진다는 리서치 근거). 대장주/성장주는 매번 자동으로 다시 산출되며(수동 "
    "큐레이션 없음), 반도체/메모리·DRAM/방산/우주/냉각/사이버보안/클라우드/로보틱스처럼 GICS 표준 "
    "섹터에 없는 세부 테마는 코드에 미리 정의된 후보 종목군 안에서 동일한 방식으로 선정합니다."
)

# 카테고리 팔레트(dataviz 스킬, 다크모드 검증본): 파랑/주황/초록/노랑/보라. 앱 기존 캔들 상승/하락
# 색(#26a69a/#ef5350)과 겹치지 않도록 초록조차 다른 톤(#008300)을 사용.
_CHART_COLORS = {
    "ETF": "#3987e5",  # 파랑 — 기준선(점선)
    "leader": "#d95926",  # 주황 — 대장주(굵게)
    "growth": ["#008300", "#c98500", "#9085e9"],  # 초록/노랑/보라 — 성장주 1~3
}

theme_options = list(THEME_UNIVERSE.keys())
selected_theme = st.selectbox("테마 선택", theme_options, index=theme_options.index("기술") if "기술" in theme_options else 0)

job_manager.ensure(
    "sector_leader_growth", selected_theme, analyze_theme_relationships, selected_theme,
    label=f"{selected_theme} 섹터 리더/성장주 분석",
)
job = job_manager.render("sector_leader_growth", running_label=f"{selected_theme} 대장주/성장주를 분석하는 중")
if job is not None:
    if job.status == "error":
        st.error(f"분석 중 오류가 발생했습니다: {job.error}")
        st.session_state.pop("sector_leader_growth_result", None)
    else:
        st.session_state["sector_leader_growth_result"] = job.result

result = st.session_state.get("sector_leader_growth_result")

if result is None or result.get("theme") != selected_theme:
    st.info("테마를 선택하면 분석이 시작됩니다. 잠시만 기다려 주세요.")
    st.stop()

st.caption(f"대표 ETF: {', '.join(result['proxies'])} · 후보 종목 {result['candidates_count']}개 중 자동 선정")

leader = result.get("leader")
growth_stocks = result.get("growth_stocks", [])

if leader is None:
    st.warning("이 테마의 후보 종목 데이터를 가져오지 못했습니다 (네트워크 오류 또는 데이터 없음).")
    st.stop()


def _fmt_pct(v):
    return "N/A" if v is None else f"{v:+.1f}%"


def _fmt_num(v, digits=2):
    return "N/A" if v is None else f"{v:.{digits}f}"


st.subheader(f"👑 대장주: {leader['ticker']} ({leader['name']})")
cols = st.columns(5)
cols[0].metric("시가총액", f"${leader['market_cap'] / 1e9:,.1f}B" if leader.get("market_cap") else "N/A")
cols[1].metric("베타 (ETF 대비 민감도)", _fmt_num(leader.get("beta")))
cols[2].metric("상관계수 (동조화)", _fmt_num(leader.get("correlation")))
cols[3].metric(f"RS 추세 ({leader.get('trend', 'N/A')})", _fmt_pct(leader.get("rs_change_3m")), help="최근 3개월 상대강도(종목가/ETF가) 비율 변화율")
cols[4].metric("추세추종 신호", leader.get("abs_trend", "N/A"), help="종목 자체의 절대 가격 추세(200일선 위/아래 + 50/200일 골든·데드크로스). ETF 대비 상대강도(RS)와는 다른 지표입니다.")

st.subheader("🌱 성장주 (이익성장률 상위 3개, 초대형주 제외)")
if growth_stocks:
    growth_df = pd.DataFrame(
        [
            {
                "티커": g["ticker"],
                "종목명": g["name"],
                "시가총액": f"${g['market_cap'] / 1e9:,.1f}B" if g.get("market_cap") else "N/A",
                "이익성장률": _fmt_pct(g.get("earnings_growth") * 100 if g.get("earnings_growth") is not None else None),
                "PER": _fmt_num(g.get("per")),
                "베타": _fmt_num(g.get("beta")),
                "상관계수": _fmt_num(g.get("correlation")),
                "RS 추세": g.get("trend", "N/A"),
                "RS 3개월 변화": _fmt_pct(g.get("rs_change_3m")),
                "🐢 추격 후보": "예" if g.get("lag_candidate") else "-",
            }
            for g in growth_stocks
        ]
    )
    st.dataframe(growth_df, use_container_width=True, hide_index=True)

    if any(g.get("lag_candidate") for g in growth_stocks):
        st.info(
            "🐢 **추격 후보**: 대장주가 상승추세이고 이 종목의 베타/상관계수도 충분히 높아(대장주와 "
            "연동돼 있어) 함께 움직일 여지가 있는데, 아직 ETF 대비 상대강도(RS)가 상승으로 확인되지는 "
            "않은 종목입니다. Lo-MacKinlay(1990)/Hou(2007)의 리드-래그(lead-lag) 연구에 따르면 같은 "
            "산업 내에서 대형주 수익률이 정보확산 지연으로 소형주 수익률을 선행하는 경향이 있습니다 — "
            "다만 이 예측력에 기반한 초과수익은 거래비용을 반영하면 빠르게 사라진다는 한계도 같은 "
            "연구에서 확인됐습니다. **투자 조언이 아니라 관찰 지표이며, 실제로 따라잡는다는 보장은 "
            "없습니다.**"
        )
else:
    st.info("이 테마에서 성장주 후보를 찾지 못했습니다.")

chart_series = result.get("chart_series", {})
if chart_series:
    st.subheader("📈 정규화 성과 비교 (시작일 = 100)")
    fig = go.Figure()
    for label, series in chart_series.items():
        if label == "ETF":
            fig.add_trace(
                go.Scatter(
                    x=series.index, y=series.values, name="대표 ETF", mode="lines",
                    line=dict(color=_CHART_COLORS["ETF"], width=2, dash="dash"),
                )
            )
        elif label == leader["ticker"]:
            fig.add_trace(
                go.Scatter(
                    x=series.index, y=series.values, name=f"대장주 {label}", mode="lines",
                    line=dict(color=_CHART_COLORS["leader"], width=3),
                )
            )
        else:
            idx = [g["ticker"] for g in growth_stocks].index(label) if label in [g["ticker"] for g in growth_stocks] else 0
            color = _CHART_COLORS["growth"][idx % len(_CHART_COLORS["growth"])]
            fig.add_trace(
                go.Scatter(x=series.index, y=series.values, name=f"성장주 {label}", mode="lines", line=dict(color=color, width=2))
            )
    fig.update_layout(
        paper_bgcolor=TRADINGVIEW_CHART_BG, plot_bgcolor=TRADINGVIEW_CHART_BG,
        font=dict(color=TRADINGVIEW_CHART_TEXT),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(l=10, r=10, t=10, b=10),
        hovermode="x unified",
    )
    fig.update_xaxes(gridcolor=TRADINGVIEW_CHART_GRID, zerolinecolor=TRADINGVIEW_CHART_GRID)
    fig.update_yaxes(gridcolor=TRADINGVIEW_CHART_GRID, zerolinecolor=TRADINGVIEW_CHART_GRID, title="정규화 지수 (시작일=100)")
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
else:
    st.info("비교 차트를 그리기에 데이터가 부족합니다.")

st.caption(
    "베타 1보다 크면 ETF보다 변동성이 크게 움직인다는 뜻이고, 상관계수가 낮으면 ETF와 별개로 "
    "움직이는 종목이라는 뜻입니다. RS 추세는 최근 20거래일 기준 상대강도(종목가/ETF가) 비율이 "
    "±1% 이상 움직였을 때만 상승/하락으로 표시하고, 그 이하는 횡보로 표시합니다."
)
