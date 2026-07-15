"""모듈 G: 매크로 대시보드 페이지.

FRED API 기반 경제지표 히스토리를 보여주고, 실질 GDP 증가율/실업률 추세로 경기 사이클 국면을
간이 추정해 국면별 아웃퍼폼 섹터(로테이션 참고표)를 함께 보여준다.
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
from core.fred_data import DEFAULT_INDICATORS, get_indicator_snapshot, get_series, is_configured
from core import job_manager
from core.macro_cycle import determine_cycle_phase, get_sector_rotation_table, yoy_growth
from core.market_regime import get_market_regime_snapshot
from core.screener import get_universe
from core.sector_strength import compute_theme_strength
from core.theme import TRADINGVIEW_CHART_BG, TRADINGVIEW_CHART_GRID, TRADINGVIEW_CHART_TEXT, apply_theme

init_db()

st.set_page_config(page_title="매크로 대시보드", page_icon="🌐", layout="wide")
apply_theme()
job_manager.render_active_jobs_sidebar()
st.title("🌐 매크로 대시보드")
st.caption("FRED(연준) 경제지표 히스토리와 경기 사이클 국면 추정 + 섹터 로테이션 참고표를 보여줍니다.")

if not is_configured():
    st.warning(
        "FRED_API_KEY가 설정되지 않았습니다. `.env` 파일에 키를 채워넣으면 실제 지표를 볼 수 있습니다 "
        "([fred.stlouisfed.org/docs/api/api_key.html](https://fred.stlouisfed.org/docs/api/api_key.html)에서 무료 발급). "
        "지금은 섹터 로테이션 참고표만 표시합니다."
    )

tab_indicators, tab_cycle, tab_strength = st.tabs(
    ["📊 경제지표", "🔄 경기 사이클 / 섹터 로테이션", "📈 시장 국면 / 섹터 강도"]
)

# ============================================================================
# 탭 1: 경제지표 카드 + 히스토리 차트
# ============================================================================
with tab_indicators:
    if is_configured():
        job_manager.ensure("fred_snapshot", "snapshot", get_indicator_snapshot, label="FRED 지표 조회")
        fred_job = job_manager.render("fred_snapshot", running_label="FRED 데이터를 가져오는 중")
        snapshot = fred_job.result

        cols = st.columns(3)
        for i, row in enumerate(snapshot):
            with cols[i % 3]:
                if row["latest_value"] is not None:
                    st.metric(row["label"], f"{row['latest_value']:,.2f}{row['unit']}", help=f"기준일: {row['latest_date']}")
                else:
                    st.metric(row["label"], "데이터 없음")

        st.divider()
        indicator_id = st.selectbox(
            "히스토리 차트로 볼 지표", list(DEFAULT_INDICATORS.keys()), format_func=lambda k: DEFAULT_INDICATORS[k]["label"]
        )
        series = next((r["series"] for r in snapshot if r["series_id"] == indicator_id), None)
        if series is not None and not series.empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=series.index, y=series.values, name=indicator_id))
            fig.update_layout(title=DEFAULT_INDICATORS[indicator_id]["label"], height=400)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("이 지표의 히스토리 데이터를 가져오지 못했습니다.")
    else:
        st.info("FRED_API_KEY 설정 후 이 탭에서 기준금리/CPI/실업률/GDP 등 히스토리를 확인할 수 있습니다.")

# ============================================================================
# 탭 2: 경기 사이클 국면 + 섹터 로테이션
# ============================================================================
with tab_cycle:
    st.markdown("### 경기 사이클 국면 추정")
    st.caption(
        "실질 GDP 증가율(YoY)과 실업률 추세로 4국면(회복/확장/둔화/수축)을 간이 추정합니다. "
        "공식 경기판단이 아닌 참고용 경험칙입니다."
    )

    if is_configured():
        gdp_series = get_series("GDPC1")
        unemployment_series = get_series("UNRATE")

        if gdp_series.empty or unemployment_series.empty:
            st.warning("GDP 또는 실업률 데이터를 가져오지 못해 국면을 판단할 수 없습니다.")
        else:
            gdp_growth = yoy_growth(gdp_series, periods=4)
            result = determine_cycle_phase(gdp_growth, unemployment_series)

            if result["phase"] is None:
                st.warning(result["description"])
            else:
                st.success(f"현재 추정 국면: **{result['phase']}**")
                st.write(result["description"])
                st.markdown(f"**참고 아웃퍼폼 섹터**: {', '.join(result['sectors'])}")
    else:
        st.info("FRED_API_KEY 설정 후 이 섹션에서 실시간 국면 추정 결과를 볼 수 있습니다.")

    st.divider()
    st.markdown("### 국면별 섹터 로테이션 참고표")
    rotation_table = get_sector_rotation_table()
    rows = [
        {"국면": phase, "설명": info["description"], "아웃퍼폼 섹터": ", ".join(info["sectors"])}
        for phase, info in rotation_table.items()
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)

# ============================================================================
# 탭 3: 시장 국면(강세/약세) + 섹터/테마 강도 (기술적, 룰 기반 — MARKET_REGIME_SECTOR_STRENGTH_SPEC.md)
# ============================================================================
with tab_strength:
    st.markdown("### 시장 국면 (S&P500 기준)")
    st.caption(
        "200일선 대비 위치·50/200일 골든/데드크로스·시장폭(200일선 위 종목 비율)·52주 고점 대비 낙폭, "
        "4개 신호를 조합한 룰 기반 참고 지표입니다(공식 판단이 아닌 경험칙). 데드크로스는 이미 하락이 "
        "상당 부분 진행된 뒤 나오는 후행 신호라 매도 근거로는 신뢰도가 낮다는 점에 유의하세요."
    )

    universe_df = get_universe()
    if universe_df.empty:
        st.warning("S&P500 종목 유니버스를 가져오지 못해 시장 국면을 계산할 수 없습니다.")
    else:
        tickers = universe_df["Symbol"].tolist()
        job_manager.ensure(
            "market_regime_snapshot", len(tickers), get_market_regime_snapshot, tickers,
            label="시장 국면 계산",
        )
        regime_job = job_manager.render(
            "market_regime_snapshot",
            running_label="시장 국면을 계산하는 중 (최초 1회는 S&P500 전종목 조회로 다소 걸릴 수 있습니다)",
        )
        if regime_job is not None:
            if regime_job.status == "error":
                st.error(f"시장 국면 계산 중 오류가 발생했습니다: {regime_job.error}")
            else:
                st.session_state["market_regime_snapshot"] = regime_job.result

        snapshot = st.session_state.get("market_regime_snapshot")
        if snapshot is not None:
            regime, score = snapshot["regime"], snapshot["total_score"]
            if regime == "강세장":
                st.success(f"🐂 **{regime}**  (종합 점수 {score:+.0f}점)")
            elif regime == "약세장":
                st.error(f"🐻 **{regime}**  (종합 점수 {score:+.0f}점)")
            else:
                st.info(f"😐 **{regime}**  (종합 점수 {score:+.0f}점)")

            tp, mc, dd, br = (
                snapshot["trend_position"], snapshot["ma_cross"], snapshot["drawdown"], snapshot["breadth"],
            )
            cols = st.columns(4)
            with cols[0]:
                if tp:
                    st.metric("200일선 대비", "위" if tp["above_200sma"] else "아래", f"{tp['pct_vs_sma200']:+.1f}%")
                else:
                    st.metric("200일선 대비", "데이터 부족")
            with cols[1]:
                if mc:
                    st.metric("추세 상태", "골든크로스" if mc["golden_cross"] else "데드크로스")
                else:
                    st.metric("추세 상태", "데이터 부족")
            with cols[2]:
                if dd:
                    st.metric(
                        "52주 고점 대비", f"{dd['drawdown_pct']:.1f}%",
                        help="통상적인 공식 약세장 정의 기준: 고점 대비 -20% 이하",
                    )
                else:
                    st.metric("52주 고점 대비", "데이터 부족")
            with cols[3]:
                st.metric(
                    "시장폭(200일선 위 비율)", f"{br['pct_above_200sma']:.0f}%",
                    help=(
                        f"{br['n_above']}/{br['n_data_ok']}종목 (전체 {br['n_total']}종목 중 데이터 확보분). "
                        "85~90% 이상은 과열 구간으로 조정이 임박했을 수 있습니다."
                    ),
                )

with tab_strength:
    st.divider()
    st.markdown("### 섹터/테마 강도 (RS 점수)")
    st.caption(
        "IBD 스타일 상대강도(RS) 점수 — 최근 3개월에 가중치를 더 준 12개월 수익률을 테마 집합 내 "
        "percentile(0~100)로 환산했습니다. DRAM/반도체/우주처럼 GICS 표준 11개 섹터에 없는 세부 테마는 "
        "대표 ETF를 프록시로 사용합니다(복수 ETF는 평균)."
    )

    job_manager.ensure("theme_strength", "default", compute_theme_strength, label="섹터/테마 강도 계산")
    strength_job = job_manager.render("theme_strength", running_label="섹터/테마 강도를 계산하는 중")
    if strength_job is not None:
        if strength_job.status == "error":
            st.error(f"섹터/테마 강도 계산 중 오류가 발생했습니다: {strength_job.error}")
        else:
            st.session_state["theme_strength_result"] = strength_job.result

    strength_df = st.session_state.get("theme_strength_result")
    if strength_df is not None and not strength_df.empty:
        fmt_df = strength_df.copy()
        for col in ("return_3m", "return_6m", "return_12m"):
            # DRAM처럼 최근 상장돼 6/12개월치 데이터가 아직 없는 테마는 "-"로 표시(결측 NaN이
            # 차트/표에 "None"·"nan%"으로 그대로 노출되는 것을 방지).
            fmt_df[col] = fmt_df[col].map(lambda v: f"{v:+.1f}%" if pd.notna(v) else "-")

        chart_df = fmt_df.sort_values("rs_score", ascending=True)  # 수평 바는 아래→위로 그려지므로 1등이 맨 위에 오도록 오름차순
        bar_colors = ["#26a69a" if v >= 50 else "#ef5350" for v in chart_df["rs_score"]]

        fig = go.Figure()
        fig.add_trace(
            go.Bar(
                x=chart_df["rs_score"], y=chart_df["theme"], orientation="h",
                marker_color=bar_colors,
                text=[f"{v:.0f}" for v in chart_df["rs_score"]], textposition="outside",
                customdata=chart_df[["proxies", "return_3m", "return_6m", "return_12m", "trend"]],
                hovertemplate=(
                    "<b>%{y}</b> (%{customdata[0]})<br>"
                    "RS 점수: %{x:.0f}<br>"
                    "3개월 수익률: %{customdata[1]}<br>"
                    "6개월 수익률: %{customdata[2]}<br>"
                    "12개월 수익률: %{customdata[3]}<br>"
                    "추세: %{customdata[4]}<extra></extra>"
                ),
            )
        )
        fig.add_vline(x=50, line_dash="dash", line_color=TRADINGVIEW_CHART_GRID)
        fig.update_layout(
            paper_bgcolor=TRADINGVIEW_CHART_BG, plot_bgcolor=TRADINGVIEW_CHART_BG,
            font=dict(color=TRADINGVIEW_CHART_TEXT),
            height=max(320, 34 * len(chart_df)),
            xaxis=dict(title="RS 점수 (0~100, 50=테마 집합 내 평균)", range=[0, 108]),
            yaxis=dict(title=None),
            showlegend=False,
            margin=dict(l=10, r=40, t=10, b=40),
        )
        fig.update_xaxes(gridcolor=TRADINGVIEW_CHART_GRID, zerolinecolor=TRADINGVIEW_CHART_GRID)
        fig.update_yaxes(gridcolor=TRADINGVIEW_CHART_GRID, zerolinecolor=TRADINGVIEW_CHART_GRID)
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

        table_df = fmt_df.sort_values("rs_score", ascending=False).copy()
        table_df["rs_score"] = table_df["rs_score"].round(0).astype(int)
        st.dataframe(
            table_df.rename(
                columns={
                    "theme": "테마", "proxies": "프록시 ETF", "rs_score": "RS 점수",
                    "return_3m": "3개월", "return_6m": "6개월", "return_12m": "12개월", "trend": "추세",
                }
            )[["테마", "프록시 ETF", "RS 점수", "3개월", "6개월", "12개월", "추세"]],
            use_container_width=True, hide_index=True,
        )
    elif strength_df is not None:
        st.warning("섹터/테마 강도를 계산하지 못했습니다(데이터 없음).")
