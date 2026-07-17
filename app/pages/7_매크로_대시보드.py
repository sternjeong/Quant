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

from core.backtest_engine import DEFAULT_BENCHMARK_TICKER
from core.db import init_db
from core.fred_data import DEFAULT_INDICATORS, compute_fx_volatility, get_indicator_snapshot, get_series, is_configured
from core import job_manager
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
from core.screener import get_universe
from core.sector_strength import compute_theme_strength, get_latest_theme_strength_snapshot, save_theme_strength_snapshot
from core.theme import (
    TRADINGVIEW_CHART_BG,
    TRADINGVIEW_CHART_GRID,
    TRADINGVIEW_CHART_TEXT,
    add_regime_shading,
    apply_theme,
)

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
        st.info("FRED_API_KEY 설정 후 이 탭에서 기준금리/CPI/실업률/GDP 등 히스토리를 확인할 수 있습니다.")

# ============================================================================
# 탭 2: 경기 사이클 국면 + 섹터 로테이션
# ============================================================================
with tab_cycle:
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
# 탭 3: 시장 국면(강세/약세) + 섹터/테마 강도 (기술적, 룰 기반 — MARKET_REGIME_SECTOR_STRENGTH_SPEC.md)
# ============================================================================
with tab_strength:
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
            # VIX/FRED 조회는 이미 로컬 디스크 캐시(TTL)가 있어 job_manager 백그라운드 잡 없이
            # 매 rerun마다 직접 호출해도 빠르다 — job_manager.ensure()는 render()가 완료된 job의
            # 추적을 곧바로 지워버려서(job_manager.py의 render() 참고) 이 자리처럼 "매 rerun마다
            # 무조건 ensure() 호출"하는 패턴과 조합하면 매번 새 잡이 재시작되며 폴링용 st.rerun()이
            # 반복 발생해, 같은 rerun 안에서 사용자가 막 클릭한 다른 위젯(조회 기간 라디오 등)의
            # 값이 반영되기 전에 스크립트가 계속 중단·재시작되는 문제가 실측으로 확인됐다
            # (2026-07-17). 무거운 계산이 아니므로 동기 호출로 되돌려 이 문제를 피한다.
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

with tab_strength:
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
        # 스케줄러가 못 돌았거나(클라우드 등 상시 프로세스를 못 띄우는 환경) 아직 오늘 것이 없을 때 —
        # 한국시간 자정이 지난 뒤 첫 방문이 자동으로 재계산을 트리거한다.
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
            # DRAM처럼 최근 상장돼 6/12개월치 데이터가 아직 없는 테마는 "-"로 표시(결측 NaN이
            # 차트/표에 "None"·"nan%"으로 그대로 노출되는 것을 방지).
            fmt_df[col] = fmt_df[col].map(lambda v: f"{v:+.1f}%" if pd.notna(v) else "-")
        if "trend_change" in fmt_df.columns:
            # 상승/하락/횡보 라벨만으로는 얼마나 강하게 움직였는지 안 보여서, 모멘텀 팩터 변화량
            # (%p)을 라벨 옆에 괄호로 덧붙인다. trend_change가 없으면(데이터 부족) 라벨만 표시.
            fmt_df["trend"] = fmt_df.apply(
                lambda row: f"{row['trend']} ({row['trend_change']:+.1f}%p)" if pd.notna(row["trend_change"]) else row["trend"],
                axis=1,
            )

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
        display_df = table_df.rename(
            columns={
                "theme": "테마", "proxies": "프록시 ETF", "rs_score": "RS 점수",
                "return_3m": "3개월", "return_6m": "6개월", "return_12m": "12개월", "trend": "추세",
            }
        )[["테마", "프록시 ETF", "RS 점수", "3개월", "6개월", "12개월", "추세"]].reset_index(drop=True)
        st.caption("💡 행을 클릭하면 그 테마의 대장주·성장주·매크로 리포트 페이지로 이동합니다.")
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
            st.switch_page("pages/12_섹터_리더_성장주.py")
    elif strength_df is not None:
        st.warning("섹터/테마 강도를 계산하지 못했습니다(데이터 없음).")
