"""모듈 G 통합: 시장 진단 페이지 (2026-07-21 통합 — 이전 7_매크로_대시보드.py + 16_코스톨라니_달걀_
이론.py + 12_섹터_리더_성장주.py).

"지금 시장이 어떤 상태인가"를 서로 다른 방법론(FRED 거시지표/경기사이클, 가격·거래량 기반 기술적
국면, 코스톨라니 심리 근사, 섹터/종목 관계 분석)으로 보여주는 페이지들을 하나로 묶었다. 위쪽
선택 버튼(세그먼트)으로 섹션을 고른다 — 매 rerun마다 선택된 섹션의 코드만 실행되므로(다른 섹션의
무거운 FRED/전종목 스캔 호출이 불필요하게 함께 실행되지 않는다), st.tabs 대신 세그먼트 컨트롤 +
session_state 분기 패턴을 쓴다. 이 패턴 덕분에 "섹터/테마 강도" 표에서 특정 테마를 클릭하면
(이전에는 st.switch_page로 별도 페이지 12로 이동) 같은 페이지 안에서 "섹터 리더·성장주" 섹션으로
session_state만 바꾸고 rerun하는 것으로 자연스럽게 대체된다.
"""

import html
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

from core import job_manager
from core.backtest_engine import DEFAULT_BENCHMARK_TICKER
from core.db import init_db
from core.fred_data import DEFAULT_INDICATORS, compute_fx_volatility, get_indicator_snapshot, get_series, is_configured
from core.kostolany_cycle import (
    PHASE_INFO,
    PHASE_ORDER,
    STATUS_LABELS,
    STATUS_ORDER,
    STYLE_LABELS,
    STYLE_ORDER,
    STYLE_PHASE_GUIDANCE,
    STYLE_PHASE_STATUS,
    compute_theme_cycle_phases,
    explain_phase_reasoning,
    get_latest_kostolany_cycle_snapshot,
    get_market_cycle_phase,
    save_kostolany_cycle_snapshot,
)
from core.kostolany_scenario_engine import (
    compute_broad_universe_scenario_runs,
    compute_theme_scenario_runs,
    run_ticker_contribution_policy_comparison,
    run_ticker_scenario,
    scenario_runs_to_summary_df,
)
from core.macro_cycle import (
    ASSET_CLASS_NOTES,
    classify_cfnai,
    compute_historical_quadrants,
    determine_cycle_phase,
    get_sector_rotation_table,
    interpret_yield_curve,
    yoy_growth,
)
from core.market_data import get_price_history
from core.market_regime import (
    get_advisory_risk_signals,
    get_latest_market_regime_snapshot,
    get_market_regime_snapshot,
    historical_regime_segments,
    is_snapshot_stale_for_today_kst,
    save_market_regime_snapshot,
    to_kst,
)
from core.sector_leaders import analyze_theme_relationships, build_price_chart_candidates, get_theme_macro_context
from core.sector_strength import THEME_UNIVERSE, compute_theme_strength, get_latest_theme_strength_snapshot, save_theme_strength_snapshot
from core.screener import get_universe
from core.strategy_tuning import sample_universe
from core.theme import (
    TRADINGVIEW_CHART_BG,
    TRADINGVIEW_CHART_GRID,
    TRADINGVIEW_CHART_TEXT,
    add_regime_shading,
    apply_theme,
)
from core.ui_status import render_status_header

# 앱 전역에서 이미 쓰는 상태색 3톤(core/theme.py의 Gemini/리더보드 배지와 동일) — 코스톨라니 섹션
# 카드 배지에 재사용.
_STATUS_COLORS = {"buy": "#4caf82", "hold": "#8a8a8a", "sell": "#e5533d"}

# 카테고리 팔레트(dataviz 스킬, 다크모드 검증본) — 섹터 리더·성장주 섹션 차트에서 재사용.
_CHART_COLORS = {
    "ETF": "#3987e5",
    "leader": "#d95926",
    "growth": ["#008300", "#c98500", "#9085e9"],
}

init_db()

st.set_page_config(page_title="시장 진단", page_icon="🌐", layout="wide")
apply_theme()
job_manager.render_active_jobs_sidebar()
st.title("🌐 시장 진단")
render_status_header("market")
st.caption("거시지표/경기사이클, 기술적 시장국면·섹터강도, 코스톨라니 심리국면, 섹터 리더·성장주 관계까지 — 여러 방법론으로 지금 시장을 진단합니다.")

if not is_configured():
    st.warning(
        "FRED_API_KEY가 설정되지 않았습니다. `.env` 파일에 키를 채워넣으면 실제 지표를 볼 수 있습니다 "
        "([fred.stlouisfed.org/docs/api/api_key.html](https://fred.stlouisfed.org/docs/api/api_key.html)에서 무료 발급). "
        "이 키가 필요 없는 섹션(시장 국면/섹터 강도, 코스톨라니, 섹터 리더·성장주)은 그대로 사용할 수 있습니다."
    )

_LABEL_INDICATORS = "📊 경제지표"
_LABEL_CYCLE = "🔄 경기 사이클 / 섹터 로테이션"
_LABEL_REGIME_STRENGTH = "📈 시장 국면 / 섹터 강도"
_LABEL_KOSTOLANY = "🥚 코스톨라니 달걀 이론"
_LABEL_SECTOR_LEADER = "🧭 섹터 리더·성장주"
_SECTIONS = [_LABEL_INDICATORS, _LABEL_CYCLE, _LABEL_REGIME_STRENGTH, _LABEL_KOSTOLANY, _LABEL_SECTOR_LEADER]

st.session_state.setdefault("market_diag_section", _LABEL_INDICATORS)
active_section = st.segmented_control(
    "진단 섹션", _SECTIONS, key="market_diag_section", label_visibility="collapsed"
)
if active_section is None:  # segmented_control은 재선택 시 해제(None)도 허용 — 이전 선택 유지
    active_section = st.session_state.get("market_diag_section") or _LABEL_INDICATORS
    st.session_state["market_diag_section"] = active_section

st.divider()


# ============================================================================
# 섹션 1: 경제지표 카드 + 히스토리 차트 (구 7_매크로_대시보드.py 탭1)
# ============================================================================
def _render_indicators() -> None:
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

        st.divider()
        st.markdown("#### 원/달러 환율 변동성")
        st.caption(
            "일별 변동률(전일 대비 %)의 20거래일(약 1개월) rolling 표준편차를 연율화(×√252)한 값입니다. "
            "수치가 높을수록 환율이 최근 크게 출렁였다는 뜻입니다."
        )
        fx_series = next((r["series"] for r in snapshot if r["series_id"] == "DEXKOUS"), None)
        if fx_series is not None and not fx_series.empty:
            fx_vol = compute_fx_volatility(fx_series)
            fx_vol_valid = fx_vol.dropna()
            fx_cols = st.columns(2)
            with fx_cols[0]:
                if not fx_vol_valid.empty:
                    st.metric(
                        "현재 연율화 변동성",
                        f"{fx_vol_valid.iloc[-1]:.1f}%",
                        help=f"기준일: {fx_vol_valid.index[-1]:%Y-%m-%d}",
                    )
                else:
                    st.metric("현재 연율화 변동성", "데이터 부족")
            with fx_cols[1]:
                st.metric("현재 환율", f"{fx_series.dropna().iloc[-1]:,.1f}원", help=f"기준일: {fx_series.dropna().index[-1]:%Y-%m-%d}")

            fx_chart_cols = st.columns(2)
            with fx_chart_cols[0]:
                fig_fx = go.Figure()
                fig_fx.add_trace(go.Scatter(x=fx_series.index, y=fx_series.values, name="원/달러"))
                fig_fx.update_layout(title="원/달러 환율 추이", height=320, margin=dict(l=10, r=10, t=40, b=10))
                st.plotly_chart(fig_fx, use_container_width=True)
            with fx_chart_cols[1]:
                fig_fx_vol = go.Figure()
                fig_fx_vol.add_trace(go.Scatter(x=fx_vol.index, y=fx_vol.values, name="연율화 변동성(%)"))
                fig_fx_vol.update_layout(title="원/달러 환율 변동성 (20일 rolling, 연율화)", height=320, margin=dict(l=10, r=10, t=40, b=10))
                st.plotly_chart(fig_fx_vol, use_container_width=True)
        else:
            st.info("원/달러 환율 데이터를 가져오지 못했습니다.")
    else:
        st.info("FRED_API_KEY 설정 후 이 섹션에서 기준금리/CPI/실업률/GDP 등 히스토리를 확인할 수 있습니다.")


# ============================================================================
# 섹션 2: 경기 사이클 국면 + 섹터 로테이션 (구 7_매크로_대시보드.py 탭2)
# ============================================================================
def _render_cycle() -> None:
    st.subheader(
        "경기 사이클 국면 추정",
        help=(
            "**주 판정**: GDP YoY 증가율을 자체 추세(2년 이동평균)와 비교한 '레벨'(위/아래) × "
            "최근 방향인 '모멘텀'(가속/감속) 두 축으로 4사분면(확장/둔화/회복/수축)을 정합니다. "
            "**침체 확인 오버레이 1**: Sahm Rule(실업률 3개월 평균이 12개월 저점 대비 +0.5%p 이상 "
            "상승)이 트리거되면 사분면 결과와 무관하게 '수축'으로 덮어씁니다. **참고 신호 2가지**: "
            "장단기 금리차(10Y-2Y) 역전 여부(선행지표, 국면 판정에는 안 섞고 경고로만 표시)와 "
            "시카고 연은 전국활동지수(CFNAI-MA3, 85개 지표를 가중평균한 종합 활동지수)를 별도로 "
            "함께 보여줘 하나의 지표에만 의존하지 않게 합니다."
        ),
    )
    st.caption(
        "실질 GDP 증가율(YoY)의 추세 대비 레벨×모멘텀(가속/감속)으로 4국면(회복/확장/둔화/수축)을 "
        "추정하고, Sahm Rule이 트리거되면 '수축'으로 덮어씁니다. 장단기 금리차·CFNAI는 판정에 섞지 "
        "않는 별도 참고 신호입니다. 공식 경기판단이 아닌 참고용 경험칙입니다."
    )

    if is_configured():
        gdp_series = get_series("GDPC1")
        unemployment_series = get_series("UNRATE")
        yield_curve_series = get_series("T10Y2Y")
        cfnai_series = get_series("CFNAI")

        if gdp_series.empty or unemployment_series.empty:
            st.warning("GDP 또는 실업률 데이터를 가져오지 못해 국면을 판단할 수 없습니다.")
        else:
            gdp_growth = yoy_growth(gdp_series, periods=4)
            result = determine_cycle_phase(gdp_growth, unemployment_series)
            cfnai_ma3 = cfnai_series.dropna().rolling(3).mean() if not cfnai_series.empty else pd.Series(dtype=float)
            yield_curve_latest = float(yield_curve_series.dropna().iloc[-1]) if not yield_curve_series.dropna().empty else None
            cfnai_latest = float(cfnai_ma3.iloc[-1]) if not cfnai_ma3.empty else None
            yield_curve_info = interpret_yield_curve(yield_curve_latest)
            cfnai_info = classify_cfnai(cfnai_latest)

            if result["phase"] is None:
                st.warning(result["description"])
            else:
                st.success(f"현재 추정 국면: **{result['phase']}**")
                st.write(result["description"])
                st.markdown(f"**참고 아웃퍼폼 섹터**: {', '.join(result['sectors'])}")
                st.caption(f"📌 자산군 성향(일반적 경향, 확정 규칙 아님): {ASSET_CLASS_NOTES[result['phase']]}")
                if result["sahm_override"]:
                    st.warning("⚠️ Sahm Rule 트리거로 '수축' 국면이 확정됐습니다(GDP 사분면만으로는 다른 국면이었을 수 있음).")
                if yield_curve_info and yield_curve_info["inverted"]:
                    st.warning("⚠️ 장단기 금리차(10Y-2Y)가 역전 상태입니다 — 아래 '선행/보조 신호'에서 자세히 확인하세요.")

                st.markdown("#### 판정 근거 신호 4가지")
                sig_cols = st.columns(4)
                quadrant, sahm = result["quadrant"], result["sahm_rule"]
                with sig_cols[0]:
                    if quadrant:
                        st.metric(
                            "GDP 사분면 (주 판정)",
                            f"{'추세 위' if quadrant['above_trend'] else '추세 아래'} · {quadrant['momentum']}",
                            help=(
                                f"최근 증가율 {quadrant['level']:.2f}% vs 추세(2년 평균) {quadrant['trend']:.2f}%.\n"
                                "위/아래 + 가속/감속 조합으로 4국면(확장/둔화/회복/수축)을 정합니다.\n"
                                "GDP는 분기 발표라 다른 신호보다 최신성이 떨어집니다."
                            ),
                        )
                    else:
                        st.metric("GDP 사분면 (주 판정)", "데이터 부족")
                with sig_cols[1]:
                    if sahm:
                        st.metric(
                            "Sahm Rule (침체 확인)",
                            "트리거됨" if sahm["triggered"] else "미트리거",
                            f"{sahm['delta_pp']:+.2f}%p",
                            help=(
                                f"실업률 3개월 평균 {sahm['current_3mo_avg']:.2f}% vs 12개월 저점 {sahm['recent_low']:.2f}%.\n"
                                "차이가 +0.5%p 이상이면 트리거 — 과거 모든 미국 침체를 실시간에 가깝게\n"
                                "정확히 잡아낸 것으로 검증된 지표입니다. 트리거 시 '수축'으로 강제 확정됩니다."
                            ),
                        )
                    else:
                        st.metric("Sahm Rule (침체 확인)", "데이터 부족")
                with sig_cols[2]:
                    if yield_curve_info:
                        st.metric(
                            "장단기 금리차 10Y-2Y (선행)",
                            f"{yield_curve_info['spread']:+.2f}%p",
                            "역전" if yield_curve_info["inverted"] else "정상",
                            delta_color="inverse",
                            help=(
                                "10년물-2년물 국채금리차입니다. 역전(음수)은 1955년 이후 모든 미국 침체에\n"
                                "앞서 나타난 선행 신호로, 평균 약 15개월(6~24개월 범위) 뒤 침체로 이어진\n"
                                "경우가 많았습니다. 국면 판정에는 안 섞고 경고 신호로만 사용합니다."
                            ),
                        )
                    else:
                        st.metric("장단기 금리차 10Y-2Y (선행)", "데이터 부족")
                with sig_cols[3]:
                    if cfnai_info:
                        st.metric(
                            "CFNAI-MA3 (종합 활동지수)",
                            f"{cfnai_info['value']:+.2f}",
                            cfnai_info["signal"],
                            help=(
                                "시카고 연은이 85개 월간 지표를 가중평균한 종합 경기활동지수의 3개월 "
                                "이동평균입니다.\n0=추세 성장률, +면 추세 이상, -면 추세 이하 성장을 뜻합니다.\n"
                                "-0.70 미만: 침체 위험 고조 / +0.20 초과: 확장 가능성 높음 / +0.70 초과: "
                                "과열·인플레 압력 우려\n(시카고 연은이 제시하는 공식 임계값)."
                            ),
                        )
                    else:
                        st.metric("CFNAI-MA3 (종합 활동지수)", "데이터 부족")

                st.markdown("#### 지표 추이")
                chart_cols = st.columns(2)
                with chart_cols[0]:
                    gdp_trend_series = gdp_growth.dropna().rolling(8).mean()
                    fig_gdp = go.Figure()
                    fig_gdp.add_trace(go.Scatter(x=gdp_growth.index, y=gdp_growth.values, name="GDP YoY 증가율(%)"))
                    fig_gdp.add_trace(
                        go.Scatter(x=gdp_trend_series.index, y=gdp_trend_series.values, name="추세(2년 평균)", line=dict(dash="dot"))
                    )
                    fig_gdp.update_layout(title="실질 GDP 증가율(YoY) vs 추세", height=320, margin=dict(l=10, r=10, t=40, b=10))
                    st.plotly_chart(fig_gdp, use_container_width=True)
                with chart_cols[1]:
                    unemployment_3mo = unemployment_series.dropna().rolling(3).mean()
                    fig_unemp = go.Figure()
                    fig_unemp.add_trace(go.Scatter(x=unemployment_3mo.index, y=unemployment_3mo.values, name="실업률 3개월 평균(%)"))
                    if sahm:
                        fig_unemp.add_hline(
                            y=sahm["recent_low"], line_dash="dot", annotation_text="12개월 저점", line_color="gray"
                        )
                        fig_unemp.add_hline(
                            y=sahm["recent_low"] + 0.5, line_dash="dash", annotation_text="Sahm 트리거선(+0.5%p)",
                            line_color="red",
                        )
                    fig_unemp.update_layout(title="실업률 3개월 평균 vs Sahm Rule 임계선", height=320, margin=dict(l=10, r=10, t=40, b=10))
                    st.plotly_chart(fig_unemp, use_container_width=True)

                chart_cols2 = st.columns(2)
                with chart_cols2[0]:
                    if not yield_curve_series.dropna().empty:
                        fig_yc = go.Figure()
                        fig_yc.add_trace(go.Scatter(x=yield_curve_series.index, y=yield_curve_series.values, name="10Y-2Y(%p)"))
                        fig_yc.add_hline(y=0, line_color="red", annotation_text="역전 기준선(0)")
                        fig_yc.update_layout(title="장단기 금리차(10Y-2Y)", height=320, margin=dict(l=10, r=10, t=40, b=10))
                        st.plotly_chart(fig_yc, use_container_width=True)
                    else:
                        st.info("장단기 금리차 데이터를 가져오지 못했습니다.")
                with chart_cols2[1]:
                    if not cfnai_ma3.empty:
                        fig_cfnai = go.Figure()
                        fig_cfnai.add_trace(go.Scatter(x=cfnai_ma3.index, y=cfnai_ma3.values, name="CFNAI-MA3"))
                        fig_cfnai.add_hline(y=-0.70, line_color="red", line_dash="dash", annotation_text="침체 위험(-0.70)")
                        fig_cfnai.add_hline(y=0.20, line_color="green", line_dash="dash", annotation_text="확장 가능성(+0.20)")
                        fig_cfnai.add_hline(y=0.70, line_color="orange", line_dash="dash", annotation_text="과열(+0.70)")
                        fig_cfnai.update_layout(title="CFNAI 3개월 이동평균", height=320, margin=dict(l=10, r=10, t=40, b=10))
                        st.plotly_chart(fig_cfnai, use_container_width=True)
                    else:
                        st.info("CFNAI 데이터를 가져오지 못했습니다.")

                st.markdown("#### 최근 분기별 판정 이력")
                st.caption("과거 각 분기 시점까지의 데이터만으로 같은 로직을 재계산한 결과입니다(미래 데이터 미사용).")
                history_df = compute_historical_quadrants(gdp_growth, lookback_quarters=12)
                if not history_df.empty:
                    display_history = history_df.copy()
                    display_history["quarter"] = display_history["quarter"].dt.strftime("%Y-%m")
                    display_history = display_history.rename(
                        columns={
                            "quarter": "분기",
                            "level": "GDP YoY(%)",
                            "trend": "추세(2년평균, %)",
                            "momentum": "모멘텀",
                            "phase": "판정 국면",
                        }
                    )
                    st.dataframe(display_history, use_container_width=True, hide_index=True)
                else:
                    st.info("역사적 판정 이력을 계산할 만큼 데이터가 충분하지 않습니다.")
    else:
        st.info("FRED_API_KEY 설정 후 이 섹션에서 실시간 국면 추정 결과를 볼 수 있습니다.")

    st.divider()
    st.markdown("### 국면별 섹터 로테이션 참고표")
    rotation_table = get_sector_rotation_table()
    rows = [
        {
            "국면": phase,
            "설명": info["description"],
            "아웃퍼폼 섹터": ", ".join(info["sectors"]),
            "자산군 성향(참고)": ASSET_CLASS_NOTES[phase],
        }
        for phase, info in rotation_table.items()
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)


# ============================================================================
# 섹션 3: 시장 국면(강세/약세) + 섹터/테마 강도 (구 7_매크로_대시보드.py 탭3, 기술적·룰 기반)
# ============================================================================
def _render_regime_strength() -> None:
    st.subheader(
        "시장 국면 (S&P500 기준)",
        help=(
            "**방법론**: 4개 신호를 각각 점수화(±25점, 시장폭만 ±25 스케일)해 합산합니다 — "
            "① 종가의 200일선 대비 위치, ② 50일선/200일선 골든·데드크로스, "
            "③ 시장폭(S&P500 종목 중 200일선 위 비율, 50%=0점·30%/70%에서 클립), "
            "④ 52주 고점 대비 낙폭(패널티 전용, -20% 이하는 만점 패널티). "
            "합산 점수가 +35 이상=강세장, -35 이하=약세장, 그 사이는 중립/혼조로 분류합니다."
        ),
    )
    st.caption(
        "200일선 대비 위치·50/200일 골든/데드크로스·시장폭(200일선 위 종목 비율)·52주 고점 대비 낙폭, "
        "4개 신호를 조합한 룰 기반 참고 지표입니다(공식 판단이 아닌 경험칙). 데드크로스는 이미 하락이 "
        "상당 부분 진행된 뒤 나오는 후행 신호라 매도 근거로는 신뢰도가 낮다는 점에 유의하세요."
    )

    saved_regime = get_latest_market_regime_snapshot()
    regime_is_stale = saved_regime is None or is_snapshot_stale_for_today_kst(saved_regime["computed_at"])
    if saved_regime is not None:
        st.session_state["market_regime_snapshot"] = saved_regime  # 재계산 실패해도 최소한 이전 값은 보여줌

    regime_header_cols = st.columns([5, 1])
    with regime_header_cols[0]:
        if saved_regime is not None:
            staleness_note = " · 자정이 지나 갱신 대기 중" if regime_is_stale else ""
            st.caption(
                f"🕛 마지막 갱신: {to_kst(saved_regime['computed_at']):%Y-%m-%d %H:%M} (한국시간){staleness_note} "
                "— 매일 자정 이후 첫 방문 시 자동 갱신(별도 스케줄러 프로세스가 없어도 동작)"
            )
    with regime_header_cols[1]:
        force_recompute_regime = st.button("🔄 지금 다시 계산", key="force_recompute_regime")

    universe_df = get_universe()
    if universe_df.empty:
        st.warning("S&P500 종목 유니버스를 가져오지 못해 시장 국면을 계산할 수 없습니다.")
    else:
        tickers = universe_df["Symbol"].tolist()
        if force_recompute_regime:
            job_manager.start(
                "market_regime_snapshot", get_market_regime_snapshot, tickers, label="시장 국면 계산"
            )
        elif regime_is_stale:
            # 스케줄러가 못 돌았거나(클라우드 등 상시 프로세스를 못 띄우는 환경) 아직 오늘 것이
            # 없을 때 — 한국시간 자정이 지난 뒤 첫 방문이 자동으로 재계산을 트리거한다.
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
                save_market_regime_snapshot(regime_job.result)

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

            st.markdown("#### 단기 국면 (참고용)")
            st.caption(
                "위 종합 국면은 200일선 등 중장기(1년 안팎) 추세 기준입니다. 아래는 그와 별개로 "
                "최근 1개월/3개월 수익률(%) 부호만 보는 단순 단기 지표 — 노이즈에 민감해 자주 "
                "바뀔 수 있으니 참고용으로만 보세요."
            )
            short_term = snapshot.get("short_term", {})
            st_cols = st.columns(2)
            for st_col, label in zip(st_cols, ("1개월", "3개월")):
                with st_col:
                    info = short_term.get(label)
                    if info:
                        st.metric(f"{label} 국면", info["regime"], f"{info['period_return_pct']:+.1f}%")
                    else:
                        st.metric(f"{label} 국면", "데이터 부족")

            st.markdown("#### S&P500 역사적 국면 타임라인")
            st.caption(
                "S&P500 종가에 배경 음영(초록=강세장/빨강=약세장)을 겹쳐 표시합니다 "
                "(core.market_regime.historical_regime_segments 재사용, 200일선 대비 위치 + 52주 "
                "고점 대비 낙폭으로 일별 라벨링)."
            )
            st.session_state.setdefault("market_regime_timeline_period", "3년")
            timeline_period = st.radio(
                "조회 기간", ["1년", "3년", "5년", "사용자 정의"],
                horizontal=True, key="market_regime_timeline_period",
            )
            today_date = pd.Timestamp.today().date()
            if timeline_period == "사용자 정의":
                st.session_state.setdefault(
                    "market_regime_timeline_custom_start", (pd.Timestamp(today_date) - pd.DateOffset(years=3)).date()
                )
                st.session_state.setdefault("market_regime_timeline_custom_end", today_date)
                custom_cols = st.columns(2)
                with custom_cols[0]:
                    timeline_start_date = st.date_input("시작일", key="market_regime_timeline_custom_start")
                with custom_cols[1]:
                    timeline_end_date = st.date_input("종료일", key="market_regime_timeline_custom_end")
            else:
                timeline_end_date = today_date
                timeline_years = {"1년": 1, "3년": 3, "5년": 5}[timeline_period]
                timeline_start_date = (pd.Timestamp(timeline_end_date) - pd.DateOffset(years=timeline_years)).date()
            timeline_start = pd.Timestamp(timeline_start_date).date().isoformat()
            timeline_end = pd.Timestamp(timeline_end_date).date().isoformat()
            if timeline_start_date >= timeline_end_date:
                st.warning("시작일이 종료일보다 앞서야 합니다.")
                timeline_price = pd.DataFrame()
                timeline_segments = {"강세장": [], "약세장": []}
            else:
                try:
                    timeline_price = get_price_history(DEFAULT_BENCHMARK_TICKER, start=timeline_start, end=timeline_end)
                    timeline_segments = historical_regime_segments(timeline_start, timeline_end)
                except Exception:  # noqa: BLE001 - 타임라인은 부가 기능, 실패해도 위 국면 판정 화면은 그대로 유지
                    timeline_price = pd.DataFrame()
                    timeline_segments = {"강세장": [], "약세장": []}
            if not timeline_price.empty:
                timeline_fig = go.Figure()
                timeline_fig.add_trace(
                    go.Scatter(
                        x=timeline_price.index, y=timeline_price["Close"], mode="lines",
                        name="S&P500", line=dict(color=TRADINGVIEW_CHART_TEXT, width=1.5),
                    )
                )
                timeline_fig.update_layout(
                    paper_bgcolor=TRADINGVIEW_CHART_BG, plot_bgcolor=TRADINGVIEW_CHART_BG,
                    font=dict(color=TRADINGVIEW_CHART_TEXT),
                    margin=dict(l=10, r=10, t=10, b=10), showlegend=False,
                )
                timeline_fig.update_xaxes(gridcolor=TRADINGVIEW_CHART_GRID, zerolinecolor=TRADINGVIEW_CHART_GRID)
                timeline_fig.update_yaxes(
                    gridcolor=TRADINGVIEW_CHART_GRID, zerolinecolor=TRADINGVIEW_CHART_GRID, title="S&P500 지수"
                )
                add_regime_shading(timeline_fig, timeline_segments)
                st.plotly_chart(timeline_fig, use_container_width=True, config={"displayModeBar": False})
            else:
                st.info("S&P500 이력 데이터를 가져오지 못해 타임라인을 표시할 수 없습니다.")

            st.markdown("#### 🔬 심층 리스크 신호 (참고용, 종합 점수에는 미반영)")
            st.caption(
                "위 4신호 종합 점수와 국면별 트레이닝 라벨링 로직은 그대로 두고, 시장 국면을 더 "
                "엄밀하게 판단하는 데 참고할 수 있는 3가지 신호를 신뢰도 높은 출처를 근거로 별도 "
                "표시합니다: **VIX**([CBOE](https://www.cboe.com/us/indices/dashboard/vix/) 공식 "
                "정의 — S&P500 옵션 내재변동성으로 산출하는 '공포 지수'), **하이일드 신용 스프레드**"
                "([FRED BAMLH0A0HYM2](https://fred.stlouisfed.org/series/BAMLH0A0HYM2), ICE BofA "
                "US High Yield OAS — 투기등급 회사채 스트레스로 주식시장보다 먼저 반응하는 경우가 "
                "많다고 알려짐), **10Y-3M 금리차**([뉴욕 연은 공식 침체확률 모형](https://www.newyorkfed.org/research/capital_markets/ycfaq)이 "
                "사용하는 스프레드 — 10Y-2Y보다 신뢰도 높은 선행지표로 보는 연구가 많음, 역전 시 "
                "통상 6~18개월 뒤 침체로 이어진 전례가 많으나 단기 매매 신호는 아님)."
            )
            try:
                advisory = get_advisory_risk_signals()
            except Exception:  # noqa: BLE001 - 심층 리스크 신호는 부가 기능, 실패해도 위 국면 판정은 유지
                advisory = None
            if advisory is not None:
                adv_cols = st.columns(3)
                vix_info = advisory.get("vix")
                with adv_cols[0]:
                    if vix_info:
                        st.metric(
                            "VIX (공포 지수)", f"{vix_info['level']:.1f}", vix_info["band"],
                            delta_color="inverse",
                            help="CBOE 공식 정의: S&P500 옵션 가격으로 산출한 향후 30일 내재변동성 기대치(연율화 %). "
                                 "관행상 15 미만=안정, 25~30 이상=공포 고조, 40 이상=패닉으로 해석됩니다.",
                        )
                    else:
                        st.metric("VIX (공포 지수)", "데이터 없음")
                credit_info = advisory.get("credit_spread")
                with adv_cols[1]:
                    if credit_info:
                        trend_note = (
                            f" (20거래일 전 대비 {credit_info['change_20d_bp']:+.0f}bp)"
                            if "change_20d_bp" in credit_info else ""
                        )
                        st.metric(
                            "하이일드 신용 스프레드", f"{credit_info['level_bp']:.0f}bp",
                            credit_info["band"], delta_color="inverse",
                            help=f"ICE BofA US High Yield OAS(FRED: BAMLH0A0HYM2){trend_note}. "
                                 "장기평균 약 500bp, 300bp 미만은 과열(복부감) 구간, 800bp 이상은 스트레스 고조 "
                                 "구간으로 보는 것이 다수 신용시장 해설의 공통 견해입니다.",
                        )
                    elif not is_configured():
                        st.metric("하이일드 신용 스프레드", "FRED 키 필요")
                    else:
                        st.metric("하이일드 신용 스프레드", "데이터 없음")
                yc3m_info = advisory.get("yield_curve_3m")
                with adv_cols[2]:
                    if yc3m_info:
                        st.metric(
                            "10Y-3M 금리차", f"{yc3m_info['spread_pct']:+.2f}%p",
                            yc3m_info["band"], delta_color="inverse",
                            help="뉴욕 연은 공식 침체확률 모형이 사용하는 스프레드. 1968년 이후 모든 미국 침체에 "
                                 "역전(음수)이 선행했다고 알려져 있으며(선행 시차 통상 6~18개월), 국면 종합 점수에는 "
                                 "섞지 않고 별도 경고 신호로만 사용합니다.",
                        )
                    elif not is_configured():
                        st.metric("10Y-3M 금리차", "FRED 키 필요")
                    else:
                        st.metric("10Y-3M 금리차", "데이터 없음")
            else:
                st.info("심층 리스크 신호를 아직 계산하지 못했습니다.")

    st.divider()
    st.subheader(
        "섹터/테마 강도 (RS 점수)",
        help=(
            "**RS 점수**: IBD 스타일 가중 ROC — 3개월(40%)·6개월(20%)·9개월(20%)·12개월(20%) "
            "수익률을 가중합해 '모멘텀 팩터'를 구하고, 이를 테마 집합 내 percentile(0~100, "
            "50=평균)로 환산합니다. **추세**: 같은 모멘텀 팩터를 20거래일 전 시점 기준으로도 계산해 "
            "지금 값과 비교 — 팩터가 올랐으면 '상승', 내렸으면 '하락', 같으면 '횡보'로 표시합니다."
        ),
    )
    st.caption(
        "IBD 스타일 상대강도(RS) 점수 — 최근 3개월에 가중치를 더 준 12개월 수익률을 테마 집합 내 "
        "percentile(0~100)로 환산했습니다. DRAM/반도체/우주처럼 GICS 표준 11개 섹터에 없는 세부 테마는 "
        "대표 ETF를 프록시로 사용합니다(복수 ETF는 평균)."
    )

    saved_strength = get_latest_theme_strength_snapshot()
    strength_is_stale = saved_strength is None or is_snapshot_stale_for_today_kst(saved_strength["computed_at"])
    if saved_strength is not None:
        st.session_state["theme_strength_result"] = saved_strength["theme_scores"]  # 재계산 실패해도 이전 값은 보여줌

    strength_header_cols = st.columns([5, 1])
    with strength_header_cols[0]:
        if saved_strength is not None:
            staleness_note = " · 자정이 지나 갱신 대기 중" if strength_is_stale else ""
            st.caption(
                f"🕛 마지막 갱신: {to_kst(saved_strength['computed_at']):%Y-%m-%d %H:%M} (한국시간){staleness_note} "
                "— 매일 자정 이후 첫 방문 시 자동 갱신(별도 스케줄러 프로세스가 없어도 동작)"
            )
    with strength_header_cols[1]:
        force_recompute_strength = st.button("🔄 지금 다시 계산", key="force_recompute_strength")

    if force_recompute_strength:
        job_manager.start("theme_strength", compute_theme_strength, label="섹터/테마 강도 계산")
    elif strength_is_stale:
        job_manager.ensure("theme_strength", "default", compute_theme_strength, label="섹터/테마 강도 계산")

    strength_job = job_manager.render("theme_strength", running_label="섹터/테마 강도를 계산하는 중")
    if strength_job is not None:
        if strength_job.status == "error":
            st.error(f"섹터/테마 강도 계산 중 오류가 발생했습니다: {strength_job.error}")
        else:
            st.session_state["theme_strength_result"] = strength_job.result
            save_theme_strength_snapshot(strength_job.result)

    strength_df = st.session_state.get("theme_strength_result")
    if strength_df is not None and not strength_df.empty:
        fmt_df = strength_df.copy()
        for col in ("return_3m", "return_6m", "return_12m"):
            fmt_df[col] = fmt_df[col].map(lambda v: f"{v:+.1f}%" if pd.notna(v) else "-")
        if "trend_change" in fmt_df.columns:
            fmt_df["trend"] = fmt_df.apply(
                lambda row: f"{row['trend']} ({row['trend_change']:+.1f}%p)" if pd.notna(row["trend_change"]) else row["trend"],
                axis=1,
            )

        chart_df = fmt_df.sort_values("rs_score", ascending=True)
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
        display_df = table_df.rename(
            columns={
                "theme": "테마", "proxies": "프록시 ETF", "rs_score": "RS 점수",
                "return_3m": "3개월", "return_6m": "6개월", "return_12m": "12개월", "trend": "추세",
            }
        )[["테마", "프록시 ETF", "RS 점수", "3개월", "6개월", "12개월", "추세"]].reset_index(drop=True)
        st.caption("💡 행을 클릭하면 그 테마의 대장주·성장주 관계 섹션으로 바로 이동합니다.")
        table_event = st.dataframe(
            display_df,
            use_container_width=True, hide_index=True,
            on_select="rerun", selection_mode="single-row", key="theme_strength_table",
            column_config={
                "RS 점수": st.column_config.Column(
                    help=(
                        "3개월(40%)·6개월(20%)·9개월(20%)·12개월(20%) 수익률을 가중합한 모멘텀 팩터를 "
                        "테마 집합 내 percentile(0~100, 50=평균)로 환산한 값입니다."
                    ),
                ),
                "추세": st.column_config.Column(
                    help=(
                        "지금 모멘텀 팩터(왼쪽 RS 점수의 원천값)를 20거래일 전 시점 기준으로도 다시 계산해 "
                        "비교합니다. 지금 값이 20거래일 전보다 높으면 '상승', 낮으면 '하락', 같으면 "
                        "'횡보'로 표시합니다. 괄호 안 수치는 그 변화량(현재 모멘텀 팩터 − 20거래일 전 "
                        "모멘텀 팩터, %p 단위)입니다."
                    ),
                ),
            },
        )
        selected_rows = table_event.selection.rows if table_event is not None else []
        if selected_rows:
            clicked_theme = display_df.iloc[selected_rows[0]]["테마"]
            st.session_state["macro_dashboard_selected_theme"] = clicked_theme
            st.session_state["market_diag_section"] = _LABEL_SECTOR_LEADER
            st.rerun()
    elif strength_df is not None:
        st.warning("섹터/테마 강도를 계산하지 못했습니다(데이터 없음).")


# ============================================================================
# 섹션 4: 코스톨라니 달걀 이론 (구 16_코스톨라니_달걀_이론.py)
# ============================================================================
def _render_kostolany() -> None:
    st.caption(
        "앙드레 코스톨라니의 달걀 이론(A1 저점조정 → A2 상승 → A3 버블/과열 → B1 고점조정시작 → B2 하락 → "
        "B3 패닉/급락)을 참고해, 전체 시장과 섹터/테마별로 지금 어느 국면인지 근사합니다. 이 이론의 핵심 "
        "축인 '투자자 수/심리'는 이 앱에서 구할 수 없어, **52주 고점·저점 대비 가격 위치 + 추세(ROC) + "
        "거래량 증감(20일/60일 평균 비율)** 3가지 조합으로 대신합니다. 공식 이론적 판정이 아닌 참고용 "
        "경험칙임을 감안해 주세요."
    )

    st.session_state.setdefault("kostolany_style", "장기")
    selected_style = st.segmented_control(
        "투자 스타일", STYLE_ORDER, format_func=lambda s: STYLE_LABELS[s], key="kostolany_style",
    )
    if selected_style is None:  # segmented_control은 재선택 시 해제(None) 허용 — 이전 선택 유지
        selected_style = st.session_state.get("kostolany_style") or "장기"
        st.session_state["kostolany_style"] = selected_style
    st.caption(
        "🐢 장기 투자는 코스톨라니 원전의 조언(저거래량 조정·패닉에서 매집, 고거래량 과열·고점이탈에서 "
        "비중축소)을 그대로 따릅니다. ⚡ 스윙 트레이딩은 '확인된 모멘텀을 단기로 타는' 관점이라 "
        "A1(아직 반등 미확인)은 관망으로, A2(거래량 동반 상승 확인)는 매수로 재분류됩니다 — 과열/고점"
        "이탈(A3/B1)은 두 스타일 모두 매도로 일치합니다."
    )
    style_status = STYLE_PHASE_STATUS[selected_style]
    style_guidance = STYLE_PHASE_GUIDANCE[selected_style]

    with st.expander("6국면 요약표", expanded=False):
        for status in STATUS_ORDER:
            st.markdown(f"**{STATUS_LABELS[status]}**")
            for phase in PHASE_ORDER:
                if style_status[phase] != status:
                    continue
                info = PHASE_INFO[phase]
                st.caption(f"**{info['label']}** — {info['description']} _(→ {style_guidance[phase]})_")

    saved = get_latest_kostolany_cycle_snapshot()
    is_stale = saved is None or is_snapshot_stale_for_today_kst(saved["computed_at"])
    if saved is not None:
        st.session_state["kostolany_cycle_result"] = (saved["market_phase"], saved["theme_phases"])

    header_cols = st.columns([5, 1])
    with header_cols[0]:
        if saved is not None:
            staleness_note = " · 자정이 지나 갱신 대기 중" if is_stale else ""
            st.caption(
                f"🕛 마지막 갱신: {to_kst(saved['computed_at']):%Y-%m-%d %H:%M} (한국시간){staleness_note} "
                "— 매일 자정 이후 첫 방문 시 자동 갱신(별도 스케줄러 프로세스가 없어도 동작)"
            )
    with header_cols[1]:
        force_recompute = st.button("🔄 지금 다시 계산", key="force_recompute_kostolany")

    def _compute_both():
        return get_market_cycle_phase(), compute_theme_cycle_phases()

    if force_recompute:
        job_manager.start("kostolany_cycle", _compute_both, label="코스톨라니 달걀 국면 계산")
    elif is_stale:
        job_manager.ensure("kostolany_cycle", "default", _compute_both, label="코스톨라니 달걀 국면 계산")

    cycle_job = job_manager.render("kostolany_cycle", running_label="코스톨라니 달걀 국면을 계산하는 중")
    if cycle_job is not None:
        if cycle_job.status == "error":
            st.error(f"코스톨라니 달걀 국면 계산 중 오류가 발생했습니다: {cycle_job.error}")
        else:
            market_phase, theme_phases = cycle_job.result
            st.session_state["kostolany_cycle_result"] = (market_phase, theme_phases)
            save_kostolany_cycle_snapshot(market_phase, theme_phases)

    result = st.session_state.get("kostolany_cycle_result")
    if result is None:
        st.info("아직 계산된 국면이 없습니다. 위 '지금 다시 계산' 버튼을 눌러주세요.")
    else:
        market_phase, theme_phases = result

        st.subheader("🌍 전체 시장 (S&P500)")
        if market_phase is None:
            st.warning("시장 국면을 계산할 데이터가 부족합니다.")
        else:
            market_status = style_status[market_phase["phase"]]
            st.markdown(
                f'<span style="display:inline-block;padding:2px 10px;border-radius:10px;'
                f'background:{_STATUS_COLORS[market_status]}22;color:{_STATUS_COLORS[market_status]};'
                f'font-size:0.85em;font-weight:600;">{html.escape(STATUS_LABELS[market_status])}</span>',
                unsafe_allow_html=True,
            )
            info_cols = st.columns([2, 1, 1, 1])
            with info_cols[0]:
                st.metric(market_phase["label"], f"{market_phase['zone']}")
                st.caption(f"{market_phase['description']} _(→ {style_guidance[market_phase['phase']]})_")
            with info_cols[1]:
                st.metric(
                    "52주 위치", f"{market_phase['position_pct']:.0f}%",
                    help="0=52주 최저가, 100=52주 최고가.",
                )
            with info_cols[2]:
                st.metric("20일 추세(ROC)", f"{market_phase['roc_pct']:+.1f}%")
            with info_cols[3]:
                vr = market_phase["volume_ratio"]
                st.metric(
                    "거래량 추세", "증가" if market_phase["volume_high"] else "보통/감소",
                    f"{vr:.2f}x" if vr is not None else "N/A",
                    help="20일 평균 거래량 / 60일 평균 거래량 (1.2배 이상이면 '증가'로 판정).",
                )

        st.divider()
        st.subheader(f"🏭 섹터/테마별 국면 ({STYLE_LABELS[selected_style]} 기준)")
        st.caption(
            "core.sector_strength.THEME_UNIVERSE의 GICS 11개 표준 섹터 + 반도체/우주/방산 등 세부 테마 "
            "전체를 같은 방식으로 판정한 뒤, 위에서 고른 투자 스타일 기준으로 **매수 관심 / 보유·관망 / "
            "매도 검토** 3그룹으로 묶어 보여줍니다. 각 카드를 펼치면 정확히 어느 국면(A1~B3)인지와 근거 "
            "수치를 볼 수 있습니다."
        )

        if theme_phases is None or theme_phases.empty:
            st.info("섹터/테마 국면 데이터가 없습니다.")
        else:
            board_cols = st.columns(3)
            for status, col in zip(STATUS_ORDER, board_cols):
                with col:
                    phases_in_status = [p for p in PHASE_ORDER if style_status[p] == status]
                    group_df = theme_phases[theme_phases["phase"].isin(phases_in_status)].copy()

                    st.markdown(f"##### {STATUS_LABELS[status]}")
                    phase_labels = " / ".join(PHASE_INFO[p]["label"] for p in phases_in_status)
                    st.caption(f"{phase_labels} · {len(group_df)}개 테마")

                    if group_df.empty:
                        st.caption("해당 테마가 없습니다.")
                        continue

                    if status == "sell":
                        group_df = group_df.sort_values("position_pct", ascending=False)
                    elif status == "buy":
                        group_df = group_df.sort_values("position_pct", ascending=True)
                    else:
                        group_df = group_df.sort_values("theme")

                    color = _STATUS_COLORS[status]
                    for _, row in group_df.iterrows():
                        vol_ratio = row["volume_ratio"]
                        vol_text = f"{vol_ratio:.2f}x" if pd.notna(vol_ratio) else "N/A"
                        theme_name = html.escape(str(row["theme"]))
                        phase_label = html.escape(str(row["label"]))
                        card_html = (
                            f'<div style="border-left:3px solid {color};padding:6px 10px;margin-bottom:0;'
                            f'border-radius:4px;background:rgba(255,255,255,0.04);">'
                            f'<div style="display:flex;justify-content:space-between;align-items:baseline;">'
                            f'<b style="font-size:0.92em;">{theme_name}</b>'
                            f'<span style="font-size:0.72em;opacity:0.65;white-space:nowrap;">{phase_label}</span>'
                            f"</div>"
                            f'<div style="font-size:0.76em;opacity:0.75;margin-top:2px;">'
                            f"52주 위치 {row['position_pct']:.0f}% · 추세 {row['roc_pct']:+.1f}% · 거래량 {vol_text}"
                            f"</div></div>"
                        )
                        st.markdown(card_html, unsafe_allow_html=True)
                        if st.button(
                            "📄 왜 이 국면인가요?",
                            key=f"kostolany_report_btn_{selected_style}_{row['theme']}",
                            use_container_width=True,
                        ):
                            st.session_state["kostolany_report_theme"] = row["theme"]

            report_theme = st.session_state.get("kostolany_report_theme")
            if report_theme is not None:
                report_rows = theme_phases[theme_phases["theme"] == report_theme]
                if report_rows.empty:
                    st.session_state.pop("kostolany_report_theme", None)
                else:
                    st.divider()
                    st.markdown(f"##### 📄 {report_theme} — 왜 이 국면({report_rows.iloc[0]['label']})인가요?")
                    report_text = explain_phase_reasoning(report_rows.iloc[0].to_dict(), style=selected_style)
                    st.markdown(report_text)
                    if st.button("닫기", key="kostolany_report_close"):
                        st.session_state.pop("kostolany_report_theme", None)
                        st.rerun()

            with st.expander("📋 표로 전체 보기 (정렬/검색용)", expanded=False):
                display_df = theme_phases[
                    ["theme", "label", "position_pct", "roc_pct", "volume_ratio", "phase"]
                ].copy()
                display_df["guidance"] = display_df["phase"].map(style_guidance)
                display_df = display_df.drop(columns="phase")
                display_df["position_pct"] = display_df["position_pct"].map(lambda v: f"{v:.0f}%")
                display_df["roc_pct"] = display_df["roc_pct"].map(lambda v: f"{v:+.1f}%")
                display_df["volume_ratio"] = display_df["volume_ratio"].map(lambda v: f"{v:.2f}x" if pd.notna(v) else "N/A")
                display_df.columns = ["테마", "국면", "52주 위치", "20일 추세", "거래량비", "가이드"]
                st.dataframe(display_df, use_container_width=True, hide_index=True)

        st.divider()
        st.subheader(f"📈 실제로 이 국면 신호대로 매매했다면? ({STYLE_LABELS[selected_style]} 기준)")
        st.caption(
            "위 국면 판정 로직을 아래에서 고른 기간에 그대로 적용해(룩어헤드 없이 매 시점까지의 데이터만 "
            "사용) '매수 관심·보유 국면에서 시장에 있고, 매도 검토 국면에서 현금화'하는 규칙으로 "
            "시뮬레이션한 결과입니다. 섹터/테마별로 매수 후 보유(buy & hold) 대비 초과수익률을 "
            "비교할 수 있고, 표에서 행을 클릭하면 그 섹터에서 실제로 언제·얼마에 사고 팔았는지까지 "
            "볼 수 있습니다 — 계산에 시간이 걸릴 수 있습니다. 아래 '양방향 트레이딩' 토글을 켜면 매도 "
            "검토 국면에서 현금화 대신 인버스를 매수하는 것으로 바꿔, 하락장에서도 계속 수익을 노리는 "
            "양방향 매매 결과를 같은 기준으로 비교할 수 있습니다."
        )
        st.session_state.setdefault("kostolany_scenario_start_date", date.today() - timedelta(days=365 * 5))
        st.session_state.setdefault("kostolany_scenario_end_date", date.today())
        scenario_date_cols = st.columns(2)
        with scenario_date_cols[0]:
            st.date_input("시작일", key="kostolany_scenario_start_date")
        with scenario_date_cols[1]:
            st.date_input("종료일", key="kostolany_scenario_end_date")
        kostolany_scenario_start = st.session_state["kostolany_scenario_start_date"]
        kostolany_scenario_end = st.session_state["kostolany_scenario_end_date"]
        if kostolany_scenario_start >= kostolany_scenario_end:
            st.warning("시작일은 종료일보다 빨라야 합니다.")
            st.stop()

        st.session_state.setdefault("kostolany_bidirectional", False)
        kostolany_bidirectional = st.toggle(
            "🔁 양방향 트레이딩 (매도 검토 국면에서 인버스 매수)",
            key="kostolany_bidirectional",
            help="끄면 기존과 동일하게 매도 검토 국면에서 현금 보유. 켜면 매수 관심·보유 국면은 정방향 "
            "매수, 매도 검토 국면은 현금 대신 인버스를 매수한 것으로 계산해 항상 시장에 몸을 담그는 "
            "양방향 전략 결과를 보여줍니다.",
        )
        if kostolany_bidirectional:
            st.caption(
                "⚠️ 실제 인버스 ETF/ETN 가격이 아니라 기초자산의 일별 수익률에 -1을 곱해 매일 복리로 "
                "재조정한 합성 수익률입니다(운용보수·괴리율은 반영 안 됨 — 방향성 참고용). 월 적립 "
                "옵션은 이 모드와 결합할 수 없어(포지션 -1은 '현금 대비 비중' 개념이 성립하지 않음) "
                "아래 옵션과 무관하게 항상 초기자본 일시투입으로 계산합니다."
            )

        with st.expander("💰 월 적립 옵션 (기본: 초기자본 100만 넣고 끝까지 보유)"):
            st.caption(
                "매달 얼마씩 투자에 넣을 수 있는지 입력하면, 매수보유 두 벤치마크(섹터/S&P500)는 매달 "
                "그 금액을 즉시 시장가로 사는 정액적립식(DCA)으로, 코스톨라니 신호 전략은 매도 검토 "
                "국면(현금 보유) 중에는 현금으로 누적만 하다가 매수 관심·보유 국면으로 바뀌는 순간 "
                "쌓인 현금을 한꺼번에 투입하는 방식으로 자동 전환해서 비교합니다(전략 스튜디오와 동일한 "
                "로직, core.backtest_engine.simulate_contribution_equity 재사용)."
            )
            kostolany_monthly_contribution = st.number_input(
                "월 적립금 (0이면 적립 없이 초기자본 한 번만 투자)",
                min_value=0.0, value=0.0, step=10.0, key="kostolany_monthly_contribution",
                disabled=kostolany_bidirectional,
            )

        run_scenario = st.button("📊 섹터별 시나리오 계산하기", key="run_kostolany_scenario")

        def _compute_scenario_runs():
            primary = compute_theme_scenario_runs(
                style=selected_style,
                start=kostolany_scenario_start.isoformat(),
                end=kostolany_scenario_end.isoformat(),
                monthly_contribution=kostolany_monthly_contribution,
                bidirectional=kostolany_bidirectional,
            )
            # 양방향 모드일 때는 "단방향(현금 보유)이었다면 어땠을지" 기준선도 같이 계산해둔다 —
            # 아래 결과 표에서 양방향이 단방향을 이긴 섹터를 색으로 바로 구분해 보여주기 위해서다
            # (2026-08-12 사용자 요청). 양방향은 항상 목돈 일시투입(monthly_contribution=0)으로 계산되므로
            # (run_kostolany_scenario 참고) 기준선도 동일하게 0으로 맞춰야 공정하게 비교된다.
            baseline = (
                compute_theme_scenario_runs(
                    style=selected_style,
                    start=kostolany_scenario_start.isoformat(),
                    end=kostolany_scenario_end.isoformat(),
                    monthly_contribution=0.0,
                    bidirectional=False,
                )
                if kostolany_bidirectional
                else None
            )
            # S&P500 지수 자체에도 같은 신호(같은 스타일·양방향 여부)로 매매했다면 어땠을지 — 단순
            # 매수보유가 아니라 "전략을 썼을 때" 기준으로도 섹터들을 비교할 수 있도록(2026-08-12 사용자
            # 요청). ticker가 benchmark_ticker와 같아 buy_and_hold_metrics가 곧 S&P500 매수보유와
            # 동일하다 — 별도로 벤치마크를 다시 계산할 필요가 없다.
            benchmark_strategy_run = run_ticker_scenario(
                DEFAULT_BENCHMARK_TICKER,
                style=selected_style,
                start=kostolany_scenario_start.isoformat(),
                end=kostolany_scenario_end.isoformat(),
                monthly_contribution=kostolany_monthly_contribution,
                bidirectional=kostolany_bidirectional,
            )
            return primary, baseline, benchmark_strategy_run

        scenario_job_key = (
            f"kostolany_scenario_{selected_style}_{kostolany_scenario_start.isoformat()}_"
            f"{kostolany_scenario_end.isoformat()}_{kostolany_monthly_contribution:g}_"
            f"{'bidir' if kostolany_bidirectional else 'long'}"
        )
        if run_scenario:
            job_manager.start(scenario_job_key, _compute_scenario_runs, label="코스톨라니 매매 시나리오 계산")

        scenario_job = job_manager.render(scenario_job_key, running_label="섹터별 매매 시나리오를 계산하는 중")
        if scenario_job is not None:
            if scenario_job.status == "error":
                st.error(f"시나리오 계산 중 오류가 발생했습니다: {scenario_job.error}")
            else:
                scenario_runs, baseline_runs, benchmark_strategy_run = scenario_job.result
                st.session_state["kostolany_scenario_runs"] = scenario_runs
                st.session_state["kostolany_scenario_baseline_runs"] = baseline_runs
                st.session_state["kostolany_scenario_benchmark_strategy_run"] = benchmark_strategy_run

        scenario_runs = st.session_state.get("kostolany_scenario_runs")
        baseline_runs = st.session_state.get("kostolany_scenario_baseline_runs")
        benchmark_strategy_run = st.session_state.get("kostolany_scenario_benchmark_strategy_run")
        if scenario_runs is not None:
            scenario_df = scenario_runs_to_summary_df(scenario_runs, style=selected_style)
            if scenario_df.empty:
                st.info("계산된 시나리오가 없습니다.")
            else:
                # 선택한 시작일보다 프록시 ETF의 실제 상장(데이터 시작)일이 30일 넘게 늦으면 그 섹터는
                # 요청한 기간 전체가 아니라 상장일 이후의 훨씬 짧은 구간만으로 계산된 것 — 표에 그냥
                # 섞어 넣으면 "선택한 기간 전체 성과"로 오해하기 쉬워 별도로 표시한다(2026-08-12
                # 사용자 요청: ETF가 그 기간에 없었던 섹터를 어떻게 처리할지).
                requested_start_ts = pd.Timestamp(kostolany_scenario_start)
                data_start_ts = pd.to_datetime(scenario_df["data_start"])
                insufficient_mask = (data_start_ts - requested_start_ts).dt.days > 30

                valid_df = scenario_df[~insufficient_mask]
                win_count = int((valid_df["excess_return"] > 0).sum())
                st.caption(
                    f"{len(valid_df)}개 섹터/테마(선택 기간 데이터 충분) 중 {win_count}개에서 매수 후 "
                    "보유보다 나은 결과 (excess_return > 0). 행을 클릭하면 아래에 매매 내역이 표시됩니다."
                )

                # S&P500 지수 자체에도 같은 신호로 매매했다면 어땠을지 — 단순 매수보유가 아니라 "전략을
                # 썼을 때" 기준으로도 비교할 수 있게(2026-08-12 사용자 요청).
                sp500_strategy_edge = None
                if benchmark_strategy_run is not None and not benchmark_strategy_run.df.empty:
                    bs_metrics = benchmark_strategy_run.metrics
                    bs_bh_metrics = benchmark_strategy_run.buy_and_hold_metrics
                    with st.container(border=True):
                        st.markdown(
                            f"##### 📌 S&P500 지수에도 같은 신호로 매매했다면? ({STYLE_LABELS[selected_style]}"
                            + (" · 양방향" if kostolany_bidirectional else "") + ")"
                        )
                        sp_cols = st.columns(4)
                        with sp_cols[0]:
                            st.metric(
                                "누적수익률", f"{bs_metrics['cumulative_return']:+.2f}%",
                                f"매수보유 대비 {bs_metrics['cumulative_return'] - bs_bh_metrics['cumulative_return']:+.2f}%p",
                            )
                        with sp_cols[1]:
                            st.metric("CAGR", f"{bs_metrics['cagr']:+.2f}%")
                        with sp_cols[2]:
                            st.metric("MDD", f"{bs_metrics['mdd']:.2f}%")
                        with sp_cols[3]:
                            st.metric("샤프", f"{bs_metrics['sharpe']:.2f}")
                        st.caption(
                            f"참고로 같은 기간 S&P500 매수보유는 누적수익률 {bs_bh_metrics['cumulative_return']:+.2f}%, "
                            f"CAGR {bs_bh_metrics['cagr']:+.2f}%, MDD {bs_bh_metrics['mdd']:.2f}%입니다. 아래 표의 "
                            "'초과수익률(S&P500 전략 대비)' 열에서 각 섹터의 전략 성과가 이 숫자보다 나은지 비교하세요."
                        )
                    sp500_strategy_edge = scenario_df["cumulative_return"] - bs_metrics["cumulative_return"]

                # 양방향 모드면 같은 기간·같은 섹터의 단방향(현금 보유) 기준선과 누적수익률을 비교해
                # 어느 쪽이 더 나았는지 표에 색으로 바로 보이게 한다(2026-08-12 사용자 요청).
                bidir_edge = None
                if baseline_runs:
                    baseline_df = scenario_runs_to_summary_df(baseline_runs, style=selected_style)
                    baseline_lookup = dict(zip(baseline_df["theme"], baseline_df["cumulative_return"]))
                    bidir_edge = scenario_df["cumulative_return"] - scenario_df["theme"].map(baseline_lookup)
                    bidir_compared = bidir_edge.notna()
                    bidir_win_count = int((bidir_edge[bidir_compared] > 0).sum())
                    st.caption(
                        f"🔁 양방향 vs 단방향: {int(bidir_compared.sum())}개 섹터 중 {bidir_win_count}개에서 "
                        "양방향(인버스 활용)이 단방향(현금 보유)보다 누적수익률이 더 높았습니다."
                    )
                st.caption(
                    "🟢초록 배경 = 해당 비교 기준(섹터 매수보유/S&P500 매수보유/S&P500 전략/단방향)을 이긴 셀, "
                    "🔴빨강 배경 = 진 셀입니다."
                )
                if insufficient_mask.any():
                    insufficient_df = scenario_df[insufficient_mask]
                    with st.expander(
                        f"⚠️ 데이터 부족으로 선택 기간 전체를 반영하지 못한 섹터 {len(insufficient_df)}개",
                        expanded=False,
                    ):
                        st.caption(
                            f"선택한 시작일({kostolany_scenario_start.isoformat()})보다 프록시 ETF 상장일이 "
                            "늦어서, 아래 섹터들은 표시된 '데이터 시작일'부터 종료일까지의 (더 짧은) 기간만 "
                            "반영된 결과입니다 — 위 승률 집계에서도 제외했습니다."
                        )
                        for _, r in insufficient_df.iterrows():
                            proxies = ", ".join(THEME_UNIVERSE.get(r["theme"], []))
                            st.markdown(f"- **{r['theme']}** ({proxies}) — {r['data_start']}부터 데이터 존재")
                display_scenario = scenario_df.copy()
                display_scenario["theme"] = display_scenario.apply(
                    lambda r: f"⚠️ {r['theme']}" if insufficient_mask.loc[r.name] else r["theme"], axis=1
                )
                pct_cols = [
                    "cumulative_return", "cagr", "mdd", "bh_cumulative_return", "bh_cagr", "bh_mdd",
                    "excess_return", "bench_cumulative_return", "bench_cagr", "bench_mdd",
                    "excess_return_vs_benchmark",
                ]
                for col in pct_cols:
                    display_scenario[col] = display_scenario[col].map(lambda v: f"{v:+.2f}%")
                display_scenario["win_rate"] = display_scenario["win_rate"].map(lambda v: f"{v:.1f}%")
                display_scenario = display_scenario.drop(columns=["style"])
                display_scenario.columns = [
                    "테마", "데이터 시작일", "누적수익률", "CAGR", "MDD", "샤프", "승률", "매매횟수",
                    "매수보유 누적수익률", "매수보유 CAGR", "매수보유 MDD", "초과수익률(섹터 매수보유 대비)",
                    "S&P500 매수보유 누적수익률", "S&P500 매수보유 CAGR", "S&P500 매수보유 MDD",
                    "초과수익률(S&P500 대비)",
                ]
                if sp500_strategy_edge is not None:
                    display_scenario["초과수익률(S&P500 전략 대비)"] = sp500_strategy_edge.map(
                        lambda v: f"{v:+.2f}%p" if pd.notna(v) else "-"
                    )
                if bidir_edge is not None:
                    display_scenario["양방향 우위(단방향 대비)"] = bidir_edge.map(
                        lambda v: f"{v:+.2f}%p" if pd.notna(v) else "-"
                    )

                # 승패가 갈리는 비교 열들을 전부 셀 단위로 색칠한다 — 섹터 매수보유/S&P500 매수보유는
                # 항상 존재하고, S&P500 전략/양방향 우위는 각각 계산됐을 때만 추가된다(2026-08-12
                # 사용자 요청: "이길 경우 위와 같이 표시").
                edge_columns_by_display_name = {
                    "초과수익률(섹터 매수보유 대비)": scenario_df["excess_return"],
                    "초과수익률(S&P500 대비)": scenario_df["excess_return_vs_benchmark"],
                }
                if sp500_strategy_edge is not None:
                    edge_columns_by_display_name["초과수익률(S&P500 전략 대비)"] = sp500_strategy_edge
                if bidir_edge is not None:
                    edge_columns_by_display_name["양방향 우위(단방향 대비)"] = bidir_edge

                def _highlight_edge_cells(row: pd.Series) -> list[str]:
                    styles = []
                    for col_name in row.index:
                        edge_series = edge_columns_by_display_name.get(col_name)
                        if edge_series is None:
                            styles.append("")
                            continue
                        val = edge_series.loc[row.name]
                        if pd.isna(val) or val == 0:
                            styles.append("")
                        else:
                            color = _STATUS_COLORS["buy"] if val > 0 else _STATUS_COLORS["sell"]
                            styles.append(f"background-color: {color}22")
                    return styles

                table_data = display_scenario.style.apply(_highlight_edge_cells, axis=1)
                selection = st.dataframe(
                    table_data,
                    use_container_width=True,
                    hide_index=True,
                    on_select="rerun",
                    selection_mode="single-row",
                    key="kostolany_scenario_table",
                    column_config={
                        "데이터 시작일": st.column_config.TextColumn(
                            help="이 섹터의 계산이 실제로 시작된 날짜. 선택한 시작일보다 늦다면 프록시 ETF가 "
                            "그때 아직 상장 전이었다는 뜻(테마 이름 앞 ⚠️ 표시)."
                        ),
                        "누적수익률": st.column_config.TextColumn(
                            help="시뮬레이션 시작일부터 지금까지의 총 수익률(%). 이 전략으로 굴렸을 때 원금이 몇 % 불었는지."
                        ),
                        "CAGR": st.column_config.TextColumn(
                            help="연평균 복리 성장률(Compound Annual Growth Rate). 기간이 서로 다른 전략끼리도 "
                            "비교할 수 있도록 수익률을 '연 몇 %씩 복리로 불어난 셈인지'로 환산한 값."
                        ),
                        "MDD": st.column_config.TextColumn(
                            help="최대 낙폭(Max Drawdown). 기간 중 자산가치가 고점 대비 최대 몇 %까지 떨어졌는지 — "
                            "0에 가까울수록 손실 구간이 얕았다는 뜻(음수, 클수록/0에 가까울수록 안전)."
                        ),
                        "샤프": st.column_config.TextColumn(
                            help="샤프 지수(Sharpe Ratio). 감수한 변동성(위험) 대비 수익이 얼마나 좋았는지 나타내는 "
                            "지표 — 같은 수익률이라도 변동성이 작을수록 높게 나오며, 보통 1 이상이면 양호한 편으로 본다."
                        ),
                        "승률": st.column_config.TextColumn(
                            help="완료된 매매(진입~청산) 중 수익으로 끝난 비율(%)."
                        ),
                        "매매횟수": st.column_config.NumberColumn(
                            help="시뮬레이션 기간 동안 발생한 총 매매(진입~청산 1쌍) 횟수."
                        ),
                        "매수보유 누적수익률": st.column_config.TextColumn(
                            help="같은 기간 동안 그냥 첫날 사서 계속 들고만 있었을 때(buy & hold)의 누적수익률 — 비교 기준선."
                        ),
                        "매수보유 CAGR": st.column_config.TextColumn(help="매수 후 보유(buy & hold) 기준의 CAGR."),
                        "매수보유 MDD": st.column_config.TextColumn(help="매수 후 보유(buy & hold) 기준의 최대 낙폭(MDD)."),
                        "초과수익률(섹터 매수보유 대비)": st.column_config.TextColumn(
                            help="이 전략의 누적수익률 - 그 섹터 매수 후 보유 누적수익률(%p). 양수면 국면 신호대로 "
                            "매매한 것이 그 섹터를 그냥 들고만 있는 것보다 나았다는 뜻."
                        ),
                        "S&P500 매수보유 누적수익률": st.column_config.TextColumn(
                            help="같은 기간 동안 S&P500 지수를 그냥 첫날 사서 계속 들고만 있었을 때의 누적수익률 — "
                            "'그냥 전체 시장에 투자했다면'과 비교하는 기준선."
                        ),
                        "S&P500 매수보유 CAGR": st.column_config.TextColumn(help="S&P500 매수 후 보유 기준의 CAGR."),
                        "S&P500 매수보유 MDD": st.column_config.TextColumn(help="S&P500 매수 후 보유 기준의 최대 낙폭(MDD)."),
                        "초과수익률(S&P500 대비)": st.column_config.TextColumn(
                            help="이 전략의 누적수익률 - S&P500 매수 후 보유 누적수익률(%p). 양수면 이 섹터에서 국면 "
                            "신호대로 매매한 것이 그냥 S&P500 지수를 사서 들고 있는 것보다 나았다는 뜻."
                        ),
                        "초과수익률(S&P500 전략 대비)": st.column_config.TextColumn(
                            help="이 섹터의 누적수익률 - S&P500 지수에 똑같은 신호(같은 스타일·양방향 여부)로 "
                            "매매했을 때의 누적수익률(%p). 양수면 이 섹터가 'S&P500에 같은 전략을 썼을 때'보다도 "
                            "나았다는 뜻 — 단순 매수보유가 아니라 전략 대 전략 비교."
                        ),
                        "양방향 우위(단방향 대비)": st.column_config.TextColumn(
                            help="양방향(인버스 활용) 전략의 누적수익률 - 같은 기간 단방향(매도 검토 국면에서 "
                            "현금 보유) 전략의 누적수익률(%p). 양수(초록 배경)면 인버스를 활용한 게 더 나았다는 "
                            "뜻, 음수(빨강 배경)면 오히려 손해였다는 뜻."
                        ),
                    },
                )
                selected_rows = selection["selection"]["rows"] if selection else []
                if selected_rows:
                    selected_theme = scenario_df.iloc[selected_rows[0]]["theme"]
                    selected_run = scenario_runs.get(selected_theme)
                    st.markdown(f"##### 🔍 {selected_theme} — 매매 내역")
                    if selected_run is None or not selected_run.trades:
                        st.caption("이 기간 동안 발생한 매매가 없습니다(신호가 계속 같은 상태를 유지).")
                    else:
                        trade_rows = []
                        for t in selected_run.trades:
                            row = {
                                "매수일": t.entry_date.date().isoformat() if t.entry_date is not None else "-",
                                "매수가": f"{t.entry_price:,.2f}",
                                "매도일": t.exit_date.date().isoformat() if t.exit_date is not None else "보유 중",
                                "매도가": f"{t.exit_price:,.2f}" if t.exit_price is not None else "-",
                                "수익률": f"{t.return_pct:+.2f}%" if t.return_pct is not None else "-",
                            }
                            if selected_run.bidirectional:
                                row["방향"] = "인버스" if t.direction == "inverse" else "정방향"
                            trade_rows.append(row)
                        st.dataframe(pd.DataFrame(trade_rows), use_container_width=True, hide_index=True)

                        st.caption(
                            "아래 그래프는 원가가 아니라 '기준 100에서 시작했을 때 자산가치가 어떻게 변했는지'로 "
                            "정규화했습니다 — 섹터 가격과 S&P500 지수는 절대 수준이 전혀 달라 그냥 겹쳐 그리면 "
                            "비교가 안 되기 때문입니다. "
                            + (
                                "▲/▼ 표시는 코스톨라니 전략 곡선 위에서 정방향↔인버스로 갈아탄 시점입니다."
                                if selected_run.bidirectional
                                else "▲/▼ 표시는 코스톨라니 전략 곡선 위 실제 매수/매도 시점입니다."
                            )
                        )
                        fig = go.Figure()
                        fig.add_trace(
                            go.Scatter(
                                x=selected_run.equity_curve.index, y=selected_run.equity_curve,
                                mode="lines", name="코스톨라니 신호 전략",
                                line=dict(color="#4c8bf5", width=2),
                            )
                        )
                        fig.add_trace(
                            go.Scatter(
                                x=selected_run.buy_and_hold_equity_curve.index,
                                y=selected_run.buy_and_hold_equity_curve,
                                mode="lines", name=f"{selected_theme} 매수 후 보유",
                                line=dict(color="#8a8a8a", width=1.5, dash="dot"),
                            )
                        )
                        fig.add_trace(
                            go.Scatter(
                                x=selected_run.benchmark_equity_curve.index,
                                y=selected_run.benchmark_equity_curve,
                                mode="lines", name="S&P500 매수 후 보유",
                                line=dict(color="#e5533d", width=1.5, dash="dash"),
                            )
                        )
                        eq = selected_run.equity_curve
                        if selected_run.bidirectional:
                            # 양방향 모드는 hold 없이 정방향<->인버스가 하루 만에 뒤집히는 경우가 흔해
                            # (extract_bidirectional_trades 참고) 청산 시점이 대부분 바로 다음 진입
                            # 시점과 겹친다 — 매수/매도 두 세트 대신 "어느 방향으로 진입했는지"만
                            # 방향별 색으로 표시하는 편이 덜 헷갈린다.
                            long_x = [t.entry_date for t in selected_run.trades if t.direction != "inverse"]
                            long_y = [eq.loc[d] for d in long_x]
                            inverse_x = [t.entry_date for t in selected_run.trades if t.direction == "inverse"]
                            inverse_y = [eq.loc[d] for d in inverse_x]
                            fig.add_trace(
                                go.Scatter(
                                    x=long_x, y=long_y, mode="markers", name="매수(정방향)",
                                    marker=dict(color=_STATUS_COLORS["buy"], size=11, symbol="triangle-up"),
                                )
                            )
                            fig.add_trace(
                                go.Scatter(
                                    x=inverse_x, y=inverse_y, mode="markers", name="매수(인버스)",
                                    marker=dict(color=_STATUS_COLORS["sell"], size=11, symbol="triangle-down"),
                                )
                            )
                        else:
                            buy_x = [t.entry_date for t in selected_run.trades if t.entry_date is not None]
                            buy_y = [eq.loc[d] for d in buy_x]
                            sell_x = [t.exit_date for t in selected_run.trades if t.exit_date is not None]
                            sell_y = [eq.loc[d] for d in sell_x]
                            fig.add_trace(
                                go.Scatter(
                                    x=buy_x, y=buy_y, mode="markers", name="매수",
                                    marker=dict(color="#4caf82", size=11, symbol="triangle-up"),
                                )
                            )
                            fig.add_trace(
                                go.Scatter(
                                    x=sell_x, y=sell_y, mode="markers", name="매도",
                                    marker=dict(color="#e5533d", size=11, symbol="triangle-down"),
                                )
                            )
                        fig.update_layout(
                            height=360, margin=dict(l=10, r=10, t=20, b=10),
                            legend=dict(orientation="h", yanchor="bottom", y=1.02),
                            yaxis_title="자산가치 (시작=100)",
                        )
                        st.plotly_chart(fig, use_container_width=True)

        st.divider()
        st.subheader("🔬 개별 종목 광범위 검증 — 섹터 ETF 대신 S&P500 표본으로")
        st.caption(
            "위 섹터별 시나리오는 섹터 ETF 약 20개뿐이고, 그중 상당수가 2015년 이후 상장된 신생 테마라 "
            "서로 상관관계도 높습니다(대부분 반도체/AI 계열) — '이 기법이 시장을 상대로 정말 유효한가'를 "
            "넓게 보기엔 표본이 작고 편향돼 있습니다. 여기서는 같은 국면 신호를 S&P500 섹터 균등 표본 "
            "(개별 종목, 대부분 수십 년치 이력 보유)에 그대로 적용해 승률·초과수익률을 더 큰 표본으로 "
            "다시 확인합니다(같은 위의 시작일/종료일/투자 스타일을 그대로 씁니다)."
        )
        universe_cols = st.columns([1, 2])
        with universe_cols[0]:
            universe_n = st.selectbox(
                "표본 크기", [20, 50, 100, 150], index=1, key="kostolany_universe_n",
                help="S&P500 안에서 섹터별로 균등 배분한 표본 종목 수(시가총액 순 결정론적 선택 — 같은 "
                "크기를 다시 눌러도 항상 같은 종목이 나옵니다).",
            )
        with universe_cols[1]:
            universe_pit = st.checkbox(
                "선택한 시작일 기준 실제 편입종목만 사용 (생존편향 방지)", value=True, key="kostolany_universe_pit",
                help="끄면 '지금의' S&P500 종목으로 과거를 돌립니다 — 지금 지수에 남아있는(즉 잘 버틴) "
                "종목만 보는 생존편향 위험이 있습니다. 켜면 선택한 시작일 당시 실제 편입종목 목록을 씁니다.",
            )

        run_universe = st.button("🔬 광범위 검증 실행", key="run_kostolany_universe_validation")

        def _compute_universe_runs():
            as_of = kostolany_scenario_start.isoformat() if universe_pit else None
            sample_df = sample_universe(n=universe_n, as_of_date=as_of)
            tickers = sample_df["ticker"].tolist()
            return compute_broad_universe_scenario_runs(
                tickers,
                style=selected_style,
                start=kostolany_scenario_start.isoformat(),
                end=kostolany_scenario_end.isoformat(),
            )

        universe_job_key = (
            f"kostolany_universe_{universe_n}_{universe_pit}_{selected_style}_"
            f"{kostolany_scenario_start.isoformat()}_{kostolany_scenario_end.isoformat()}"
        )
        if run_universe:
            job_manager.start(universe_job_key, _compute_universe_runs, label="개별 종목 광범위 검증 계산")

        universe_job = job_manager.render(
            universe_job_key, running_label=f"{universe_n}개 종목을 검증하는 중 (처음 조회하는 종목이 많으면 몇 분 걸릴 수 있습니다)"
        )
        if universe_job is not None:
            if universe_job.status == "error":
                st.error(f"광범위 검증 계산 중 오류가 발생했습니다: {universe_job.error}")
            else:
                st.session_state["kostolany_universe_runs"] = universe_job.result

        universe_runs = st.session_state.get("kostolany_universe_runs")
        if universe_runs is not None:
            universe_df = scenario_runs_to_summary_df(universe_runs, style=selected_style)
            if universe_df.empty:
                st.info("계산된 결과가 없습니다.")
            else:
                # 국면 신호(상승/하락 사이클 판정)는 최소 한 사이클을 겪어야 의미가 있다 — 개별 종목
                # 표본에도 최근 상장/스핀오프 종목이 섞일 수 있어 섹터별 시나리오와 동일한 기준(선택한
                # 시작일보다 30일 넘게 늦게 데이터가 시작하면 제외)으로 걸러낸다.
                u_requested_start_ts = pd.Timestamp(kostolany_scenario_start)
                u_data_start_ts = pd.to_datetime(universe_df["data_start"])
                u_insufficient_mask = (u_data_start_ts - u_requested_start_ts).dt.days > 30
                u_valid_df = universe_df[~u_insufficient_mask]

                if u_valid_df.empty:
                    st.info("유효한 데이터 기간을 가진 종목이 없습니다.")
                else:
                    n_tested = len(u_valid_df)
                    win_rate = float((u_valid_df["excess_return_vs_benchmark"] > 0).mean() * 100)
                    mean_excess = float(u_valid_df["excess_return_vs_benchmark"].mean())
                    median_excess = float(u_valid_df["excess_return_vs_benchmark"].median())

                    stat_cols = st.columns(4)
                    stat_cols[0].metric(
                        "검증 종목 수", f"{n_tested}개",
                        help=f"표본 {len(universe_df)}개 중 데이터 기간이 충분한 종목만 집계(제외 "
                        f"{len(universe_df) - n_tested}개).",
                    )
                    stat_cols[1].metric("S&P500 매수보유 대비 승률", f"{win_rate:.1f}%")
                    stat_cols[2].metric("평균 초과수익률", f"{mean_excess:+.2f}%p")
                    stat_cols[3].metric("중앙값 초과수익률", f"{median_excess:+.2f}%p")
                    st.caption(
                        "초과수익률(%p) = 코스톨라니 신호 전략 누적수익률 - 같은 기간 S&P500 매수 후 "
                        "보유 누적수익률. 평균이 중앙값보다 훨씬 크면 소수 종목의 극단치가 평균을 끌어올린 "
                        "것일 수 있으니 함께 참고하세요."
                    )
                    if len(universe_df) > n_tested:
                        st.caption(
                            f"⚠️ {len(universe_df) - n_tested}개 종목은 선택한 기간만큼 데이터가 없어 "
                            "위 집계에서 제외했습니다(아래 표에는 포함)."
                        )

                    with st.expander(f"📋 종목별 결과 전체 보기 ({len(universe_df)}개)", expanded=False):
                        u_display = universe_df.copy()
                        u_display["theme"] = u_display.apply(
                            lambda r: f"⚠️ {r['theme']}" if u_insufficient_mask.loc[r.name] else r["theme"], axis=1
                        )
                        pct_cols = [
                            "cumulative_return", "cagr", "mdd", "bh_cumulative_return", "bh_cagr", "bh_mdd",
                            "excess_return", "bench_cumulative_return", "bench_cagr", "bench_mdd",
                            "excess_return_vs_benchmark",
                        ]
                        for col in pct_cols:
                            u_display[col] = u_display[col].map(lambda v: f"{v:+.2f}%")
                        u_display["win_rate"] = u_display["win_rate"].map(lambda v: f"{v:.1f}%")
                        u_display = u_display.drop(columns=["style"])
                        u_display.columns = [
                            "티커", "데이터 시작일", "누적수익률", "CAGR", "MDD", "샤프", "승률", "매매횟수",
                            "매수보유 누적수익률", "매수보유 CAGR", "매수보유 MDD", "초과수익률(자체 매수보유 대비)",
                            "S&P500 매수보유 누적수익률", "S&P500 매수보유 CAGR", "S&P500 매수보유 MDD",
                            "초과수익률(S&P500 대비)",
                        ]
                        st.dataframe(u_display, use_container_width=True, hide_index=True)

        st.divider()
        st.subheader("💰 매달 버는 돈, 언제 넣을까? — DCA vs 신호 대기 vs 하이브리드")
        st.caption(
            "위 시나리오는 '이미 넣은 돈을 신호대로 사고팔았다면'을 다루고, 이 섹션은 '매달 새로 생기는 "
            "적립금을 어디에 둘지'만 다룹니다 — 매수 타점이 뜰 때까지 현금으로 쌓아둘지, 신호와 무관하게 "
            "바로 투자할지, 아니면 절반씩 섞을지 세 정책을 같은 종목/기간으로 비교합니다. 세 곡선 모두 "
            "일단 투입된 돈은 나중에 매도 신호가 떠도 되팔지 않습니다(그건 위 시나리오의 몫)."
        )
        st.markdown(
            "- 🔵 **순수 DCA**: 매달 신호와 무관하게 즉시 전액 투자\n"
            "- 🟠 **신호 대기**: 매수 관심·보유 국면이 될 때까지 현금으로 쌓아뒀다가 신호가 뜨면 몰아서 투자\n"
            "- 🟢 **하이브리드**: 매달 일부(비율 조절 가능)는 즉시 투자, 나머지는 신호를 기다렸다가 투자"
        )

        policy_cols = st.columns([2, 1, 1])
        with policy_cols[0]:
            policy_ticker = st.text_input(
                "종목/ETF 티커", value="SPY", key="kostolany_policy_ticker",
                help="섹터 전체가 아니라 실제로 매달 사려는 개별 티커를 넣어보세요(예: XLK, QQQ, AAPL).",
            ).strip().upper()
        with policy_cols[1]:
            policy_monthly = st.number_input(
                "월 적립금", min_value=1.0, value=100.0, step=10.0, key="kostolany_policy_monthly",
            )
        with policy_cols[2]:
            policy_hybrid_pct = st.slider(
                "하이브리드 즉시투자 비율", min_value=0, max_value=100, value=50, step=10,
                key="kostolany_policy_hybrid_pct", format="%d%%",
            )

        run_policy = st.button("📈 정책 비교 계산하기", key="run_kostolany_policy_comparison")

        def _compute_policy_comparison():
            return run_ticker_contribution_policy_comparison(
                policy_ticker,
                style=selected_style,
                start=kostolany_scenario_start.isoformat(),
                end=kostolany_scenario_end.isoformat(),
                monthly_contribution=policy_monthly,
                hybrid_baseline_ratio=policy_hybrid_pct / 100.0,
            )

        policy_job_key = (
            f"kostolany_policy_{policy_ticker}_{selected_style}_{kostolany_scenario_start.isoformat()}_"
            f"{kostolany_scenario_end.isoformat()}_{policy_monthly:g}_{policy_hybrid_pct}"
        )
        if run_policy:
            if not policy_ticker:
                st.warning("티커를 입력해주세요.")
            else:
                job_manager.start(policy_job_key, _compute_policy_comparison, label="월 적립 정책 비교 계산")

        policy_job = job_manager.render(policy_job_key, running_label="세 정책을 계산하는 중")
        if policy_job is not None:
            if policy_job.status == "error":
                st.error(f"정책 비교 계산 중 오류가 발생했습니다: {policy_job.error}")
            else:
                st.session_state["kostolany_policy_run"] = policy_job.result

        policy_run = st.session_state.get("kostolany_policy_run")
        if policy_run is not None:
            if policy_run.dca_equity_curve.empty:
                st.info(f"{policy_ticker}의 가격 데이터를 찾지 못했습니다.")
            else:
                metric_cols = st.columns(3)
                policy_defs = [
                    ("🔵 순수 DCA", policy_run.dca_metrics, metric_cols[0]),
                    ("🟠 신호 대기", policy_run.wait_metrics, metric_cols[1]),
                    (f"🟢 하이브리드 ({policy_hybrid_pct}%)", policy_run.hybrid_metrics, metric_cols[2]),
                ]
                for name, m, col in policy_defs:
                    with col:
                        st.metric(
                            name, f"{m['cumulative_return']:+.2f}%",
                            help=f"원금(총 납입액) 대비 손익률. XIRR(자금가중 연환산수익률): {m['cagr']:+.2f}%",
                        )
                        st.caption(f"MDD {m['mdd']:.2f}% · 샤프 {m['sharpe']:.2f}")

                policy_fig = go.Figure()
                policy_fig.add_trace(go.Scatter(
                    x=policy_run.dca_equity_curve.index, y=policy_run.dca_equity_curve,
                    mode="lines", name="순수 DCA", line=dict(color="#4c8bf5", width=2),
                ))
                policy_fig.add_trace(go.Scatter(
                    x=policy_run.wait_equity_curve.index, y=policy_run.wait_equity_curve,
                    mode="lines", name="신호 대기", line=dict(color="#e5533d", width=2),
                ))
                policy_fig.add_trace(go.Scatter(
                    x=policy_run.hybrid_equity_curve.index, y=policy_run.hybrid_equity_curve,
                    mode="lines", name=f"하이브리드 ({policy_hybrid_pct}%)", line=dict(color="#4caf82", width=2),
                ))
                policy_fig.add_trace(go.Scatter(
                    x=policy_run.contributed_capital.index, y=policy_run.contributed_capital,
                    mode="lines", name="누적 납입 원금", line=dict(color="#8a8a8a", width=1.5, dash="dot"),
                ))
                policy_fig.update_layout(
                    height=360, margin=dict(l=10, r=10, t=20, b=10),
                    legend=dict(orientation="h", yanchor="bottom", y=1.02),
                    yaxis_title="자산가치",
                )
                st.plotly_chart(policy_fig, use_container_width=True)


# ============================================================================
# 섹션 5: 섹터 리더·성장주 관계 분석 (구 12_섹터_리더_성장주.py)
# ============================================================================
def _render_sector_leader() -> None:
    st.caption(
        "테마별 대표 ETF 대비 대장주(시가총액 1위)와 성장주(이익성장률 상위 3개, 시가총액 상위 25% "
        "초대형주는 후보에서 제외)의 베타(민감도)/상관계수(동조화)/상대강도(RS) 비율 추세를 계산합니다. "
        "애플/마이크로소프트 같은 초대형주가 '성장주'로 잡히지 않도록, 대장주 한 종목만 빼는 대신 "
        "시가총액 상위 25% 전체를 성장주 후보에서 제외합니다(최근 러셀 지수 재조정에서도 초대형주는 "
        "성장/가치 경계가 흐려진다는 리서치 근거). 대장주/성장주는 매번 자동으로 다시 산출되며(수동 "
        "큐레이션 없음), 반도체/메모리·DRAM/방산/우주/냉각/사이버보안/클라우드/로보틱스/광통신/원자력처럼 "
        "GICS 표준 섹터에 없는 세부 테마는 코드에 미리 정의된 후보 종목군 안에서 동일한 방식으로 선정합니다."
    )

    theme_options = list(THEME_UNIVERSE.keys())
    # "시장 국면/섹터 강도" 섹션의 강도 표에서 특정 행(테마)을 눌러 넘어온 경우, 그 테마를 기본
    # 선택값으로 사용한다(딱 한 번만 소비 — pop). 없으면 기존처럼 "기술"을 기본값으로 둔다.
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
                st.caption("시장 국면 스냅샷이 아직 없습니다('시장 국면/섹터 강도' 섹션에서 한 번 계산하면 여기서도 보입니다).")
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
            "공식 경기판단이 아닌 참고용 경험칙입니다 — 자세한 방법론은 '경기 사이클/섹터 로테이션' 섹션 참고."
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
            if selected_key is None:
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


if active_section == _LABEL_INDICATORS:
    _render_indicators()
elif active_section == _LABEL_CYCLE:
    _render_cycle()
elif active_section == _LABEL_REGIME_STRENGTH:
    _render_regime_strength()
elif active_section == _LABEL_KOSTOLANY:
    _render_kostolany()
elif active_section == _LABEL_SECTOR_LEADER:
    _render_sector_leader()
