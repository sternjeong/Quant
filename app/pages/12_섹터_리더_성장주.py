"""(부가) 섹터별 대표 ETF · 대장주 · 성장주 관계 분석 페이지.

SECTOR_LEADER_GROWTH_RELATIONSHIP_SPEC.md 참고. 테마(GICS 11개 섹터 + 반도체/DRAM/우주)를 고르면
그 테마의 대표 ETF, 시가총액 1위 대장주, 이익성장률 백분위 상위 성장주 3개를 자동 선정하고,
셋의 베타(민감도)/상관계수(동조화)/상대강도(RS) 비율 추세를 계산해 보여준다.
"""

import sys
from datetime import date, timedelta
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
from core.market_regime import historical_regime_segments
from core.sector_leaders import analyze_theme_relationships, build_price_chart_candidates, get_theme_macro_context
from core.sector_strength import THEME_UNIVERSE
from core.theme import (
    TRADINGVIEW_CHART_BG,
    TRADINGVIEW_CHART_GRID,
    TRADINGVIEW_CHART_TEXT,
    add_regime_shading,
    apply_theme,
)

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
# 매크로 대시보드의 섹터/테마 강도 표에서 특정 행(테마)을 눌러 넘어온 경우, 그 테마를 기본 선택값으로
# 사용한다(딱 한 번만 소비 — pop). 없으면 기존처럼 "기술"을 기본값으로 둔다.
_incoming_theme = st.session_state.pop("macro_dashboard_selected_theme", None)
_default_theme = _incoming_theme if _incoming_theme in theme_options else "기술"
selected_theme = st.selectbox(
    "테마 선택", theme_options, index=theme_options.index(_default_theme) if _default_theme in theme_options else 0
)

with st.container(border=True):
    st.markdown("##### 🌍 매크로 경제 리포트")
    macro_context = get_theme_macro_context(selected_theme)
    market_regime = macro_context["market_regime"]
    cycle_phase = macro_context["cycle_phase"]
    mapped_sector = macro_context["mapped_sector"]

    mrow1, mrow2 = st.columns(2)
    with mrow1:
        if market_regime is not None:
            st.metric(
                "시장 국면 (S&P500 기준)",
                market_regime["regime"],
                help="200일선 위치·골든/데드크로스·시장폭·52주 고점 대비 낙폭 4개 신호 합산 (core.market_regime, 매일 자정 자동 갱신).",
            )
        else:
            st.caption("시장 국면 스냅샷이 아직 없습니다(매크로 대시보드에서 한 번 계산하면 여기서도 보입니다).")
    with mrow2:
        if cycle_phase is not None and cycle_phase.get("phase"):
            st.metric(
                "경기 사이클 국면",
                cycle_phase["phase"],
                help="GDP 증가율의 추세 대비 레벨×모멘텀 + Sahm Rule 오버레이 (core.macro_cycle).",
            )
        else:
            st.caption("FRED_API_KEY 미설정 또는 데이터 부족으로 경기 사이클 국면을 계산할 수 없습니다.")

    if cycle_phase is not None and cycle_phase.get("phase"):
        st.write(cycle_phase["description"])
        if mapped_sector is not None:
            if macro_context["is_favored_sector"]:
                st.success(
                    f"✅ **{selected_theme}**(≈ {mapped_sector} 섹터)는 현재 '{cycle_phase['phase']}' 국면에서 "
                    "역사적으로 아웃퍼폼하는 섹터 로테이션 목록에 포함됩니다."
                )
            else:
                st.info(
                    f"ℹ️ **{selected_theme}**(≈ {mapped_sector} 섹터)는 현재 '{cycle_phase['phase']}' 국면의 "
                    f"아웃퍼폼 섹터 목록(참고: {', '.join(cycle_phase['sectors'])})에는 포함되지 않습니다."
                )
        else:
            st.caption(f"'{selected_theme}'는 경기 사이클 섹터 로테이션 참고표와 매핑되지 않은 니치 테마입니다.")
    st.caption(
        "공식 경기판단이 아닌 참고용 경험칙입니다 — 자세한 방법론은 매크로 대시보드 페이지 참고."
    )

PERIOD_PRESETS = {"1개월": 30, "6개월": 182, "1년": 365, "3년": 365 * 3}
period_mode = st.radio(
    "분석 기간", list(PERIOD_PRESETS.keys()) + ["직접 선택"],
    index=2, horizontal=True, key="sector_leader_period_mode",
)
if period_mode == "직접 선택":
    col_start, col_end = st.columns(2)
    with col_start:
        period_start = st.date_input("시작일", value=date.today() - timedelta(days=365), key="sector_leader_start_date")
    with col_end:
        period_end = st.date_input("종료일", value=date.today(), key="sector_leader_end_date")
    if period_start >= period_end:
        st.warning("시작일은 종료일보다 빨라야 합니다.")
        st.stop()
else:
    period_end = date.today()
    period_start = period_end - timedelta(days=PERIOD_PRESETS[period_mode])
st.caption("베타/상관계수/RS 비율·성과 비교 차트는 선택한 기간 전체를 기준으로 계산됩니다(대장주/성장주 자체 선정 기준은 기간과 무관).")

period_start_iso = period_start.isoformat()
period_end_iso = period_end.isoformat()

job_manager.ensure(
    "sector_leader_growth", (selected_theme, period_start_iso, period_end_iso), analyze_theme_relationships,
    selected_theme, start=period_start_iso, end=period_end_iso,
    label=f"{selected_theme} 섹터 리더/성장주 분석 ({period_mode})",
)
job = job_manager.render("sector_leader_growth", running_label=f"{selected_theme} 대장주/성장주를 분석하는 중")
if job is not None:
    if job.status == "error":
        st.error(f"분석 중 오류가 발생했습니다: {job.error}")
        st.session_state.pop("sector_leader_growth_result", None)
    else:
        st.session_state["sector_leader_growth_result"] = job.result

result = st.session_state.get("sector_leader_growth_result")

if (
    result is None
    or result.get("theme") != selected_theme
    or result.get("start") != period_start_iso
    or result.get("end") != period_end_iso
):
    st.info("테마/기간을 선택하면 분석이 시작됩니다. 잠시만 기다려 주세요.")
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


st.subheader(
    f"👑 대장주: {leader['ticker']} ({leader['name']})",
    help="**선정 방법론**: 테마 후보 종목 중 시가총액 1위를 '대장주'로 자동 선정합니다.",
)
cols = st.columns(5)
cols[0].metric("시가총액", f"${leader['market_cap'] / 1e9:,.1f}B" if leader.get("market_cap") else "N/A")
cols[1].metric(
    "베타 (ETF 대비 민감도)",
    _fmt_num(leader.get("beta")),
    help="ETF보다 얼마나 크게 흔들리는지 보는 지표입니다. 1보다 크면 ETF보다 더 민감하게 움직입니다.",
)
cols[2].metric(
    "상관계수 (동조화)",
    _fmt_num(leader.get("correlation")),
    help="ETF와 같은 방향으로 움직이는 정도입니다. 1에 가까울수록 거의 같이 움직입니다.",
)
cols[3].metric(f"RS 추세 ({leader.get('trend', 'N/A')})", _fmt_pct(leader.get("rs_change_3m")), help="최근 3개월 상대강도(종목가/ETF가) 비율 변화율")
cols[4].metric("추세추종 신호", leader.get("abs_trend", "N/A"), help="종목 자체의 절대 가격 추세(200일선 위/아래 + 50/200일 골든·데드크로스). ETF 대비 상대강도(RS)와는 다른 지표입니다.")

st.subheader(
    "🌱 성장주 (이익성장률 상위 3개, 초대형주 제외)",
    help=(
        "**선정 방법론**: 시가총액 상위 25%(대장주 포함)를 초대형주로 보고 후보에서 제외한 뒤, "
        "남은 종목 중 이익성장률 백분위가 높은 상위 3개를 뽑습니다(후보군이 작아 상위 25%를 "
        "제외하면 아무도 안 남으면 대장주 한 종목만 제외). 🐢 추격 후보는 대장주와의 베타·상관계수가 "
        "모두 임계값 이상인데(연동은 확인됨) 아직 RS가 대장주를 못 따라온 종목을 표시합니다."
    ),
)
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

try:
    _regime_segments = historical_regime_segments(period_start_iso, period_end_iso)
except Exception:  # noqa: BLE001 - 배경 음영은 부가 기능이라 실패해도 차트 자체는 그대로 보여줌
    _regime_segments = {"강세장": [], "약세장": []}

chart_series = result.get("chart_series", {})
if chart_series:
    st.subheader("📈 정규화 성과 비교 (시작일 = 100)")
    st.caption(
        "배경의 옅은 초록/빨강은 S&P500 기준 역사적 강세장/약세장 구간입니다 "
        "(core.market_regime — 200일선 대비 위치 + 52주 고점 대비 낙폭으로 라벨링)."
    )
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
    add_regime_shading(fig, _regime_segments)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    price_candidates = build_price_chart_candidates(
        result.get("proxies", []), leader, growth_stocks, start=period_start_iso, end=period_end_iso
    )
    if price_candidates:
        st.subheader("📉 실제 주가 조회")
        st.caption("티커를 고르면 해당 종목의 실제 가격 차트를 볼 수 있습니다.")

        candidate_by_key = {c["key"]: c for c in price_candidates}
        prev_key = st.session_state.get("selected_price_ticker", price_candidates[0]["key"])
        selected_key = st.segmented_control(
            "티커 선택",
            options=list(candidate_by_key.keys()),
            format_func=lambda k: candidate_by_key[k]["label"],
            default=prev_key if prev_key in candidate_by_key else price_candidates[0]["key"],
            label_visibility="collapsed",
            key="selected_price_ticker",
        )
        if selected_key is None:  # segmented_control은 재선택 시 해제(None)도 허용 — 이전 선택 유지
            selected_key = prev_key if prev_key in candidate_by_key else price_candidates[0]["key"]

        selected_candidate = candidate_by_key.get(selected_key, price_candidates[0])
        selected_series = selected_candidate["series"]
        if selected_series is not None and not selected_series.empty:
            price_fig = go.Figure()
            price_fig.add_trace(
                go.Scatter(
                    x=selected_series.index,
                    y=selected_series.values,
                    mode="lines",
                    name=selected_candidate["label"],
                    line=dict(width=2.5, color=_CHART_COLORS["leader"] if selected_candidate["key"] == leader["ticker"] else _CHART_COLORS["ETF"] if selected_candidate["key"] == "ETF" else _CHART_COLORS["growth"][0]),
                )
            )
            price_fig.update_layout(
                paper_bgcolor=TRADINGVIEW_CHART_BG,
                plot_bgcolor=TRADINGVIEW_CHART_BG,
                font=dict(color=TRADINGVIEW_CHART_TEXT),
                margin=dict(l=10, r=10, t=10, b=10),
                hovermode="x unified",
            )
            price_fig.update_xaxes(gridcolor=TRADINGVIEW_CHART_GRID, zerolinecolor=TRADINGVIEW_CHART_GRID)
            price_fig.update_yaxes(gridcolor=TRADINGVIEW_CHART_GRID, zerolinecolor=TRADINGVIEW_CHART_GRID, title="실제 가격")
            add_regime_shading(price_fig, _regime_segments)
            st.plotly_chart(price_fig, use_container_width=True, config={"displayModeBar": False})
        else:
            st.info("선택한 티커의 실제 가격 데이터를 찾지 못했습니다.")
else:
    st.info("비교 차트를 그리기에 데이터가 부족합니다.")

st.caption(
    "베타 1보다 크면 ETF보다 변동성이 크게 움직인다는 뜻이고, 상관계수가 낮으면 ETF와 별개로 "
    "움직이는 종목이라는 뜻입니다. RS 추세는 최근 20거래일 기준 상대강도(종목가/ETF가) 비율이 "
    "±1% 이상 움직였을 때만 상승/하락으로 표시하고, 그 이하는 횡보로 표시합니다."
)
