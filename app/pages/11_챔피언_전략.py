"""챔피언 전략 페이지 (신규, 2026-09-12).

`analysis/2026-09-05_research_program_synthesis/`가 49개 작업·26개 이상의 리포트(순열검정/블록
부트스트랩/국면분해/워크포워드 등으로 감사됨)를 종합해 도출한 코어+새틀라이트 자산배분 결론을,
그동안 정적 HTML 리포트 안에만 머물러 있던 것에서 꺼내 "오늘 기준" 라이브 추천으로 보여준다.

핵심 로직(랭킹/시장필터/브레이크아웃 스캔)은 core/champion_strategy.py, 이 파일은 화면 구성만 담당.
새 전략을 여기서 만들지 않는다 — 확신도가 낮은(weak/reversed) 구성요소도 숨기지 않고 그대로 노출한다.
"""

import sys
from datetime import date
from pathlib import Path
from typing import Optional

# --- sys.path 부트스트랩: 프로젝트 루트를 추가해 core.* 임포트 가능하게 함 (app/pages/*.py 공통 규칙) ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import job_manager
from core.backtest_engine import compute_drawdown_series, compute_monthly_returns
from core.champion_strategy import (
    CORE_UNIVERSE,
    SATELLITE_WEIGHT,
    compute_core_recommendation,
    compute_live_collar_state,
    compute_rebalance_diff,
    compute_satellite_recommendation,
    compute_satellite_recommendation_point_in_time,
    load_confidence_table,
    load_final_config,
    load_market_regime_context,
    load_rejected_ideas,
    load_research_meta,
    run_champion_backtest,
    run_champion_backtest_with_collar,
)
from core.db import init_db
from core.guru_tracker import find_gurus_holding_ticker, get_synced_guru_names
from core.market_data import get_price_history
from core.portfolio import get_portfolio_pnl
from core.theme import (
    apply_theme,
    render_drawdown_chart,
    render_metric_card,
    render_monthly_returns_heatmap,
    render_status_bar,
)

init_db()

st.set_page_config(page_title="챔피언 전략", page_icon="🏆", layout="wide")
apply_theme()
job_manager.render_active_jobs_sidebar()

st.title("🏆 챔피언 전략")

meta = load_research_meta()
st.caption(
    f"이 저장소가 지금까지 진행한 리서치 프로그램({meta.get('n_work_items', '?')}개 작업, "
    f"{meta.get('n_reports', '?')}개 이상 리포트)을 종합해 도출한 코어+새틀라이트 배분을 '오늘' "
    "시장 데이터에 그대로 적용한 라이브 추천입니다. 새 전략을 여기서 만들지 않습니다 — 확신도가 "
    "낮은(weak/reversed) 구성요소도 숨기지 않고 그대로 보여줍니다."
)
render_status_bar(
    [
        ("ENGINE", "LOCAL"),
        ("AS OF", date.today().isoformat()),
        ("CORE UNIVERSE", f"{len(CORE_UNIVERSE)} ASSETS"),
        ("SATELLITE UNIVERSE", "S&P500"),
    ]
)

# ----------------------------------------------------------------------------
# 거장 포트폴리오 교차참조 배지 (2026-09-14 추가) — 순수 참고 정보, 새 신호가 아니다.
#
# [4_거장_포트폴리오]에서 추적 중인 투자자/펀드가 코어 top4/새틀라이트 추천 종목과 같은 종목을
# 들고 있으면 캡션 하나로만 알려준다. 이 종목이 좋다는 뜻도, 이 엔진의 배분 근거도 아니다 —
# core/guru_tracker.find_gurus_holding_ticker()가 순수 조회만 하고 배분 로직은 건드리지 않는다.
# 동기화된 거장이 하나도 없으면(get_synced_guru_names() 비어있음) 아무것도 표시하지 않는다.
# ----------------------------------------------------------------------------
_SYNCED_GURU_COUNT = len(get_synced_guru_names())


def _guru_cross_ref_caption(ticker: str) -> Optional[str]:
    if _SYNCED_GURU_COUNT == 0:
        return None
    gurus = find_gurus_holding_ticker(ticker)
    if not gurus:
        return None
    if len(gurus) == 1:
        return f"🏛️ {gurus[0]}도 보유 중"
    return f"🏛️ {gurus[0]} 등 {len(gurus)}명의 추적 대상도 보유 중"


if _SYNCED_GURU_COUNT > 0:
    st.caption(
        "🏛️ 배지: [4_거장_포트폴리오]에서 추적 중인 투자자/펀드도 같은 종목을 보유 중이라는 "
        "참고 정보입니다 — 이 종목이 좋다는 뜻이 아니며 배분에도 반영되지 않습니다."
    )

_GRADE_BADGE = {"robust": "🟢 robust", "moderate": "🔵 moderate", "weak": "🟡 weak", "reversed": "🔴 reversed"}

# ----------------------------------------------------------------------------
# 코어: 17자산 모멘텀 랭킹 + 시장필터 (17종목만 조회하므로 빠름 — 페이지 진입 시 자동 계산)
# ----------------------------------------------------------------------------
today_str = date.today().isoformat()
# job_manager.render()는 완료된 작업을 반환하며 세션 추적을 지운다("바로 꺼내 써야 한다") — 그래서
# ensure()를 매 rerun마다 조건 없이 부르면, 결과를 이미 저장해둔 뒤에도(예: 아래 새틀라이트 버튼
# 클릭 등 다른 위젯 조작으로 rerun될 때마다) 추적이 사라진 상태라 매번 새로 계산을 시작해버리고,
# 그 재계산의 "실행 중" 상태가 자체적으로 거는 st.rerun()이 정작 이번 rerun에서 눌린 다른 위젯의
# 클릭 상태를 다음 rerun으로 못 넘어가게 삼켜버린다(직접 겪어서 확인함 — 새틀라이트 스캔 버튼이
# 반응하지 않던 원인). 이미 오늘자 결과를 세션에 들고 있으면 아예 다시 부르지 않도록 방어한다.
if st.session_state.get("champion_core_asof") != today_str:
    job_manager.ensure("champion_core", today_str, compute_core_recommendation, label="코어 모멘텀 랭킹 계산")
    core_job = job_manager.render("champion_core", running_label="코어 17자산 모멘텀 계산 중...")
    if core_job is not None:
        if core_job.status == "error":
            st.error(f"코어 계산 중 오류가 발생했습니다: {core_job.error}")
        else:
            st.session_state["champion_core_result"] = core_job.result
            st.session_state["champion_core_asof"] = today_str

core_result = st.session_state.get("champion_core_result")

st.markdown("## 1. 코어 — 섹터 로테이션 모멘텀 (85%)")
st.caption("17자산(11개 GICS 섹터 ETF + 채권2 + 금 + 국제주식 + 하이일드 + 원자재) 중 12개월 모멘텀 상위 4개, 동일비중 · 월간 리밸런싱.")

if core_result is None:
    st.info("코어 계산 결과를 불러오는 중입니다...")
else:
    filter_cols = st.columns(4)
    above = core_result["above_200dma"]
    with filter_cols[0]:
        spy_price = core_result["spy_price"]
        render_metric_card("SPY 현재가", f"${spy_price:,.2f}" if spy_price is not None else "N/A")
    with filter_cols[1]:
        spy_sma = core_result["spy_sma200"]
        render_metric_card("SPY 200일선", f"${spy_sma:,.2f}" if spy_sma is not None else "N/A")
    with filter_cols[2]:
        if above is None:
            render_metric_card("시장필터", "판정불가")
        else:
            render_metric_card("시장필터", "200일선 위" if above else "200일선 아래", tone="good" if above else "bad")
    with filter_cols[3]:
        render_metric_card(
            "코어 실투입 비중", f"{core_result['exposure_multiplier'] * 0.85 * 100:.1f}%",
            sublabel=f"현금 {core_result['cash_weight_from_filter'] * 100:.1f}%" if core_result["cash_weight_from_filter"] > 0 else None,
        )
    st.caption(
        "⚠️ 이 시장필터(SPY 200일선 하회 시 코어 비중 50% 축소) 자체의 확신도는 **weak**입니다 — "
        "방향(무필터가 더 낫다)은 살아있지만 블록부트스트랩 감사에서 통계적으로 약해졌습니다 "
        "(아래 '확신도' 표 참고)."
    )

    st.markdown("#### 오늘의 코어 top4")
    top4 = core_result["top4"]
    if not top4:
        st.warning("절대모멘텀(>0) 조건을 통과한 자산이 없습니다 — 코어 비중 전체가 사실상 현금입니다.")
    else:
        card_cols = st.columns(len(top4))
        ranked = core_result["ranked"]
        for col, ticker in zip(card_cols, top4):
            row = ranked[ranked["ticker"] == ticker].iloc[0]
            with col:
                render_metric_card(
                    ticker, f"{row['momentum_pct']:+.1f}%", tone="good",
                    sublabel=f"비중 {core_result['per_ticker_weight'] * 100:.1f}%",
                )
                guru_caption = _guru_cross_ref_caption(ticker)
                if guru_caption:
                    st.caption(guru_caption)

    with st.expander("전체 17자산 랭킹 보기"):
        st.dataframe(
            core_result["ranked"][["ticker", "momentum_pct", "passes_absolute_momentum", "in_top4", "last_close"]],
            use_container_width=True, hide_index=True,
        )
    st.caption(f"기준일: {core_result['as_of']}")

# ----------------------------------------------------------------------------
# 새틀라이트: point-in-time(백테스트와 동일한 방법) + 참고용 전체 S&P500 스캔
# (2026-09-14 작업 60: 라이브 추천이 백테스트와 다른 방법론을 쓰던 것을 정정 — 두 값을 함께
#  보여주되 어느 쪽이 실제로 검증된 방법인지 명확히 구분한다.)
# ----------------------------------------------------------------------------
st.markdown("## 2. 새틀라이트 — 돈치안 20일 브레이크아웃 (15%)")
st.caption(
    "코어의 15%를 돈치안 20일 브레이크아웃(직전 20일 고가를 종가가 돌파) 추세추종 종목으로 구성합니다. "
    "아래 두 탭은 서로 다른 방법론입니다 — 실제로 매매 판단을 내릴 때는 반드시 '① point-in-time' "
    "탭을 기준으로 하세요(아래 '3. 백테스트'가 측정하는 것이 바로 이 방법입니다)."
)

satellite_sizing_method = st.radio(
    "종목 간 비중 배분 방식", options=["equal", "inverse_vol"],
    format_func=lambda v: "균등가중 (기본, 검증됨)" if v == "equal" else "🧪 변동성 역가중 (실험적, 미검증)",
    horizontal=True, key="champion_satellite_sizing_method",
)
if satellite_sizing_method == "inverse_vol":
    st.caption(
        "⚠️ 이 옵션은 '어떤 종목을 고를지'가 아니라 '고른 종목 안에서 비중을 어떻게 나눌지'만 "
        "바꿉니다 — 이 리서치 프로그램이 아직 감사하지 않은 새 시도라 확신도 등급이 없습니다. "
        "아래 백테스트에서 균등가중과 비교해본 뒤 채택 여부를 직접 판단하세요."
    )

sat_tab_pit, sat_tab_scan = st.tabs([
    "✅ 백테스트와 동일한 방법 — 반기 point-in-time",
    "🔍 빠른 근사 스캔 (참고용 — 백테스트와 다른 방법론)",
])

with sat_tab_pit:
    st.caption(
        "직전 반기 리밸런싱일(1월/7월 첫 거래일)에 point-in-time 유니버스 표본(40종목)을 뽑아 돈치안 "
        "브레이크아웃+트레일링스탑이 활성인 종목 중 12개월 모멘텀 상위 3개를 골랐다면, 그 이후 계속 "
        "보유했을 때 '지금' 들고 있을 종목입니다 — 새 랭킹 로직이 아니라 백테스트가 실제로 검증한 "
        "로직(_pick_satellite_at_date)을 그대로 재사용합니다. point-in-time 유니버스 표본추출 + 가격 "
        "조회가 필요해 아래 '빠른 근사 스캔'만큼 시간이 걸릴 수 있습니다."
    )
    if st.button("📌 point-in-time 새틀라이트 계산"):
        job_manager.start(
            "champion_satellite_pit", compute_satellite_recommendation_point_in_time,
            sizing_method=satellite_sizing_method, label="새틀라이트 point-in-time 계산",
        )

    satellite_pit_job = job_manager.render(
        "champion_satellite_pit", running_label="point-in-time 유니버스 표본 + 브레이크아웃 스캔 중 (수 분 걸릴 수 있습니다)"
    )
    if satellite_pit_job is not None:
        if satellite_pit_job.status == "error":
            st.error(f"point-in-time 계산 중 오류가 발생했습니다: {satellite_pit_job.error}")
        else:
            st.session_state["champion_satellite_pit_result"] = satellite_pit_job.result

    satellite_pit_result = st.session_state.get("champion_satellite_pit_result")
    if satellite_pit_result is None:
        st.caption("아직 계산하지 않았습니다.")
    else:
        pit_selected = satellite_pit_result["selected"]
        pit_weights = satellite_pit_result.get("per_ticker_weights", {})
        st.caption(
            f"직전 리밸런싱일: {satellite_pit_result['rebal_date']} · 다음 리밸런싱까지 약 "
            f"{satellite_pit_result['trading_days_to_next_rebal']}거래일(공휴일 미반영 근사치) · "
            f"후보 풀 {satellite_pit_result['pool_size']}종목 중 활성 추세 {satellite_pit_result['n_active_trend']}개 · "
            f"사이징 방식: {satellite_pit_result.get('sizing_method', 'equal')}"
        )
        if not pit_selected:
            st.info("직전 리밸런싱 시점에 활성 브레이크아웃 종목이 없었습니다 — 새틀라이트 비중(15%)이 사실상 현금입니다.")
        else:
            pit_cols = st.columns(len(pit_selected))
            picks_df = satellite_pit_result["picks"]
            for col, ticker in zip(pit_cols, pit_selected):
                row = picks_df[picks_df["ticker"] == ticker].iloc[0]
                with col:
                    render_metric_card(
                        ticker, f"{row['return_since_rebal_pct']:+.1f}%", tone="good",
                        sublabel=f"비중 {pit_weights.get(ticker, 0.0) * 100:.1f}% · 리밸런싱 이후 수익률",
                    )
                    guru_caption = _guru_cross_ref_caption(ticker)
                    if guru_caption:
                        st.caption(guru_caption)
            with st.expander("point-in-time 종목 상세 보기"):
                st.dataframe(picks_df, use_container_width=True, hide_index=True)

with sat_tab_scan:
    st.caption(
        "현재 S&P500 유니버스 전체를 매번 스캔해 돈치안 브레이크아웃 중인 종목을 3개월 모멘텀 상위 "
        "5개로 고르는 단순화된 근사치입니다 — 반기 point-in-time 방법론과 다르므로 위 백테스트 성과와 "
        "직접 비교하지 마세요. 전체 스캔은 종목 수만큼 순차 조회가 필요해 수 분 걸릴 수 있습니다."
    )
    if st.button("🔍 새틀라이트 후보 스캔 실행"):
        job_manager.start(
            "champion_satellite", compute_satellite_recommendation,
            sizing_method=satellite_sizing_method, label="새틀라이트 후보 스캔",
        )

    satellite_job = job_manager.render(
        "champion_satellite", running_label="S&P500 스캔 중 (수 분 걸릴 수 있습니다)"
    )
    if satellite_job is not None:
        if satellite_job.status == "error":
            st.error(f"새틀라이트 스캔 중 오류가 발생했습니다: {satellite_job.error}")
        else:
            st.session_state["champion_satellite_result"] = satellite_job.result

    satellite_result = st.session_state.get("champion_satellite_result")
    if satellite_result is None:
        st.caption("아직 스캔하지 않았습니다.")
    else:
        selected = satellite_result["selected"]
        per_ticker_weights = satellite_result.get("per_ticker_weights", {})
        st.caption(
            f"스캔 {satellite_result['scanned_count']}종목 중 브레이크아웃 후보 {len(satellite_result['candidates'])}개, "
            f"기준일 {satellite_result['as_of']}, 사이징 방식: {satellite_result.get('sizing_method', 'equal')}"
        )
        if not selected:
            st.info("현재 브레이크아웃 중인 종목이 없습니다 — 새틀라이트 비중(15%)이 사실상 현금입니다.")
        else:
            sat_cols = st.columns(len(selected))
            for col, ticker in zip(sat_cols, selected):
                row = satellite_result["candidates"][satellite_result["candidates"]["ticker"] == ticker].iloc[0]
                with col:
                    render_metric_card(
                        ticker, f"{row['momentum_3m_pct']:+.1f}%", tone="good",
                        sublabel=f"비중 {per_ticker_weights.get(ticker, 0.0) * 100:.1f}%",
                    )
                    guru_caption = _guru_cross_ref_caption(ticker)
                    if guru_caption:
                        st.caption(guru_caption)
            with st.expander("브레이크아웃 후보 전체 보기"):
                st.dataframe(satellite_result["candidates"], use_container_width=True, hide_index=True)

# satellite_result는 아래 "오늘의 종합 판단"/"내 포트폴리오와 비교" 섹션에서 계속 쓰인다 —
# point-in-time 결과(검증된 방법론)가 있으면 그쪽을 우선하고, 없으면 참고용 스캔 결과로 대체한다.
satellite_result = st.session_state.get("champion_satellite_pit_result") or st.session_state.get("champion_satellite_result")

# ----------------------------------------------------------------------------
# 오늘의 종합 판단 — 코어/새틀라이트 상태를 한 곳에 모아 보여주는 요약 (2026-09-14 추가)
#
# 이 카드는 새 신호를 만들지 않는다 — 위에서 이미 계산한 코어/새틀라이트 결과를 요약할 뿐이다.
# 시장 국면(맥락)은 참고 정보로만 덧붙인다 — 국면에 따라 배분을 바꾸는 동적 스위치는 이 리서치
# 프로그램에서 기댓값 기준으로 반복 기각됐으므로(아래 확신도 표 참고), 이 카드가 그 판단을
# 대신하거나 덮어쓰지 않는다.
# ----------------------------------------------------------------------------
st.markdown("## 오늘의 종합 판단")
verdict_cols = st.columns(3)
with verdict_cols[0]:
    if core_result is None:
        render_metric_card("코어 실투입 비중", "계산 중...")
    else:
        core_invested = core_result["exposure_multiplier"] * 0.85 * 100
        render_metric_card(
            "코어 실투입 비중", f"{core_invested:.1f}%",
            sublabel=f"{'⚠️ 200일선 아래 — 축소' if core_result['above_200dma'] is False else '200일선 위'}",
            tone="good" if core_result["above_200dma"] is not False else "neutral",
        )
with verdict_cols[1]:
    if satellite_result is None:
        render_metric_card("새틀라이트 상태", "미실행", sublabel="위 '스캔 실행' 버튼 필요")
    elif not satellite_result["selected"]:
        render_metric_card("새틀라이트 상태", "현금 (후보 없음)", tone="neutral")
    else:
        render_metric_card(
            "새틀라이트 상태", f"{len(satellite_result['selected'])}종목 보유",
            sublabel=", ".join(satellite_result["selected"]),
        )
with verdict_cols[2]:
    regime_ctx = load_market_regime_context()
    if regime_ctx is None:
        render_metric_card("시장 국면 (참고)", "스냅샷 없음")
    else:
        render_metric_card(
            "시장 국면 (참고)", regime_ctx["trading_regime"],
            sublabel="⚠️ 애매한 판정" if regime_ctx["is_ambiguous"] else "배분에는 반영 안 함",
            tone="good" if regime_ctx["trading_regime"] == "강세장" else "bad",
        )
st.caption(
    "⚠️ '시장 국면'은 참고용 맥락일 뿐입니다 — 이 엔진은 국면에 따라 코어/새틀라이트 비중을 "
    "바꾸지 않습니다(국면조건부 동적 스위치는 확신도 감사에서 반복적으로 기각됨, 아래 확신도 표 참고)."
)

# ----------------------------------------------------------------------------
# 백테스트 — "오늘 신호"가 아니라 "과거에 이 전략을 실제로 썼다면 어땠을지"
# ----------------------------------------------------------------------------
st.markdown("## 3. 백테스트")
st.caption(
    "위 코어/새틀라이트 로직을 과거 구간에 그대로 실행합니다. 코어는 매달, 새틀라이트는 반기(1월/7월)마다 "
    "리밸런싱하며, 새틀라이트는 매 반기 point-in-time 유니버스 표본(40종목)을 다시 뽑고 그중 돈치안 "
    "브레이크아웃이 활성인 종목을 스캔하므로 기간이 길수록(반기 수만큼) 오래 걸립니다 "
    "(실측 기준 1년≈2분 안팎 — 기간을 늘리면 비례해서 늘어납니다)."
)

bt_col1, bt_col2, bt_col3 = st.columns(3)
with bt_col1:
    bt_start = st.date_input("시작일", value=date.today().replace(year=date.today().year - 3))
with bt_col2:
    bt_end = st.date_input("종료일", value=date.today())
with bt_col3:
    bt_satellite_weight = st.slider("새틀라이트 비중", min_value=0.0, max_value=0.3, value=SATELLITE_WEIGHT, step=0.05)

bt_apply_collar = st.checkbox(
    "🛡️ 옵션 칼라 헤지 비교선 추가 (확신도 weak — 아래 '4. 옵션 칼라 헤지' 참고)",
    value=False,
)
bt_sizing_method = st.session_state.get("champion_satellite_sizing_method", "equal")
if bt_sizing_method == "inverse_vol":
    st.caption("🧪 위에서 고른 '변동성 역가중' 사이징으로 새틀라이트를 재계산합니다 (미검증 opt-in).")

if st.button("📊 백테스트 실행"):
    if bt_apply_collar:
        job_manager.start(
            "champion_backtest", run_champion_backtest_with_collar,
            bt_start.isoformat(), bt_end.isoformat(), satellite_weight=bt_satellite_weight,
            satellite_sizing_method=bt_sizing_method,
            label="챔피언 전략 백테스트 (칼라 헤지 포함)",
        )
    else:
        job_manager.start(
            "champion_backtest", run_champion_backtest,
            bt_start.isoformat(), bt_end.isoformat(), satellite_weight=bt_satellite_weight,
            satellite_sizing_method=bt_sizing_method,
            label="챔피언 전략 백테스트",
        )

backtest_job = job_manager.render(
    "champion_backtest", running_label="백테스트 실행 중 (코어는 빠르지만 새틀라이트는 반기마다 point-in-time 스캔이 필요해 오래 걸릴 수 있습니다)"
)
if backtest_job is not None:
    if backtest_job.status == "error":
        st.error(f"백테스트 중 오류가 발생했습니다: {backtest_job.error}")
    else:
        st.session_state["champion_backtest_result"] = backtest_job.result

backtest_result = st.session_state.get("champion_backtest_result")
if backtest_result is None:
    st.caption("아직 백테스트를 실행하지 않았습니다.")
else:
    equity = backtest_result["equity_net"]
    spy_bench = get_price_history("SPY", start=backtest_result["start"], end=backtest_result["end"])
    spy_equity = (spy_bench["Close"] / spy_bench["Close"].iloc[0] * 100.0) if not spy_bench.empty else None

    eq_fig = go.Figure()
    eq_fig.add_trace(go.Scatter(x=equity.index, y=equity.values, name="챔피언(코어+새틀라이트)", line=dict(width=2, color="#5B8DEF")))
    if backtest_result["satellite_weight_applied"] > 0:
        core_equity = (1 + backtest_result["core"]["ret_net"]).cumprod() * 100.0
        eq_fig.add_trace(go.Scatter(x=core_equity.index, y=core_equity.values, name="코어만(새틀라이트 제외)", line=dict(width=1.5, color="#8a8a8a", dash="dot")))
    if spy_equity is not None:
        eq_fig.add_trace(go.Scatter(x=spy_equity.index, y=spy_equity.values, name="S&P500 매수보유", line=dict(width=1.5, color="#F2994A")))
    if "collar_equity_net" in backtest_result:
        collar_equity = backtest_result["collar_equity_net"]
        eq_fig.add_trace(go.Scatter(x=collar_equity.index, y=collar_equity.values, name="챔피언+칼라헤지", line=dict(width=2, color="#2ecc71", dash="dash")))
    eq_fig.update_layout(
        height=380, yaxis_title="자산가치 (시작=100)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(l=10, r=10, t=30, b=10),
    )
    st.plotly_chart(eq_fig, use_container_width=True)

    bm = backtest_result["metrics"]
    metric_cols = st.columns(5)
    with metric_cols[0]:
        render_metric_card("누적수익률", f"{bm.get('cumulative_return', 0):+.1f}%", tone="good" if bm.get("cumulative_return", 0) >= 0 else "bad")
    with metric_cols[1]:
        render_metric_card("CAGR", f"{bm.get('cagr', 0):+.1f}%", tone="good" if bm.get("cagr", 0) >= 0 else "bad")
    with metric_cols[2]:
        render_metric_card("MDD", f"{bm.get('mdd', 0):.1f}%", tone="bad" if bm.get("mdd", 0) < -20 else "neutral")
    with metric_cols[3]:
        render_metric_card("샤프지수", f"{bm.get('sharpe', 0):.2f}", tone="good" if bm.get("sharpe", 0) >= 1 else "neutral")
    with metric_cols[4]:
        render_metric_card("칼마지수", f"{bm.get('calmar', 0):.2f}")

    if "collar_metrics" in backtest_result:
        cm = backtest_result["collar_metrics"]
        st.caption("🛡️ 칼라 헤지 적용 시 (SPY 합성 ATM풋+5%OTM콜, 새틀라이트 노셔널만 방어):")
        collar_cols = st.columns(4)
        with collar_cols[0]:
            render_metric_card("CAGR (칼라)", f"{cm.get('cagr', 0):+.1f}%")
        with collar_cols[1]:
            render_metric_card("MDD (칼라)", f"{cm.get('mdd', 0):.1f}%")
        with collar_cols[2]:
            render_metric_card("샤프 (칼라)", f"{cm.get('sharpe', 0):.2f}")
        with collar_cols[3]:
            render_metric_card("칼마 (칼라)", f"{cm.get('calmar', 0):.2f}")
        with st.expander("칼라 헤지 월별 롤 로그"):
            st.dataframe(pd.DataFrame(backtest_result["collar_roll_log"]), use_container_width=True, hide_index=True)

    st.plotly_chart(render_drawdown_chart(compute_drawdown_series(equity)), use_container_width=True)

    monthly = compute_monthly_returns(equity)
    if not monthly.empty:
        st.plotly_chart(render_monthly_returns_heatmap(monthly), use_container_width=True)

    if backtest_result["satellite_weight_applied"] == 0.0:
        st.warning("이 구간에는 새틀라이트가 한 번도 종목을 고르지 못해 코어 100%로 대체되었습니다 (기간을 늘려보세요).")
    else:
        with st.expander("새틀라이트 반기 리밸런싱 로그"):
            st.dataframe(pd.DataFrame(backtest_result["satellite"]["rebal_log"]), use_container_width=True, hide_index=True)

    st.caption(
        "⚠️ 이 백테스트는 왕복 0.1% 거래비용만 반영하며(세금/슬리피지 등은 미포함), 리서치가 실제로 검증한 "
        "방법론(코어: 17자산 월간 로테이션, 새틀라이트: 반기 point-in-time 40종목 풀+돈치안 브레이크아웃 "
        "상위3)을 그대로 재현합니다 — 위 '오늘의 코어 top4'/'새틀라이트 후보 스캔'(라이브 추천)과는 "
        "새틀라이트 스캔 방식이 다릅니다(라이브는 매번 S&P500 전체를 스캔하는 단순화된 근사치)."
    )

# ----------------------------------------------------------------------------
# 옵션 칼라 헤지 — 라이브 계산 (2026-09-14부터: SPY 종가+VIX 대리변동성+FRED 금리로 합성
# Black-Scholes 가격을 매기므로 실제 옵션 시세 없이도 계산 가능. 확신도는 여전히 weak.)
# ----------------------------------------------------------------------------
st.markdown("## 4. 옵션 칼라 헤지 (새틀라이트 15% 노셔널 방어 — 확신도 weak)")
st.caption(
    "새틀라이트 노셔널(15%)만큼을 SPY 합성 칼라(ATM 풋 매수 + 5%OTM 콜 매도, 매월 첫 거래일 롤)로 "
    "방어한다고 가정했을 때 '지금 이 순간'의 헤지 상태입니다. 실제 옵션 시세가 아니라 Black-Scholes "
    "합성가격(내재변동성 대리치=VIX/100, 무위험금리=FRED FEDFUNDS)이며, 위 백테스트의 '칼라 헤지 "
    "비교선'과 동일한 방식입니다. 확신도는 **weak**(부트스트랩 90% 신뢰구간이 부호조차 확정 못함, "
    "슬리브 단독 승률 55~59%) — 기본 배분에는 반영되지 않는 참고용 오버레이입니다."
)
collar_state = compute_live_collar_state()
if collar_state is None:
    st.info("SPY/VIX 데이터를 불러오지 못해 계산할 수 없습니다.")
else:
    collar_live_cols = st.columns(4)
    with collar_live_cols[0]:
        render_metric_card("이번 롤 시작일", collar_state["roll_date"])
    with collar_live_cols[1]:
        render_metric_card("만기까지 거래일", f"{collar_state['days_remaining']}일")
    with collar_live_cols[2]:
        render_metric_card("풋 행사가 / 콜 행사가", f"${collar_state['put_strike']:,.0f} / ${collar_state['call_strike']:,.0f}")
    with collar_live_cols[3]:
        pnl = collar_state["mark_to_model_pnl_pct_of_satellite_notional"]
        render_metric_card(
            "이번 사이클 마크투모델 손익", f"{pnl:+.3f}%p",
            sublabel="포트폴리오 전체 비중 기준", tone="good" if pnl >= 0 else "bad",
        )
    st.caption(
        f"SPY {collar_state['spy_at_roll']:,.2f} (롤 시점) → {collar_state['spy_now']:,.2f} (현재), "
        f"내재변동성(VIX/100) {collar_state['implied_vol_at_roll']:.1%} → {collar_state['implied_vol_now']:.1%}."
    )

final_config = load_final_config()
options_overlay = final_config.get("options_overlay", {})
if options_overlay:
    with st.expander("리서치 원문 결론 (report_data.json::options_overlay)"):
        st.markdown(f"- **적용 범위**: {options_overlay.get('inclusion', 'N/A')}")
        st.markdown(f"- **수단**: {options_overlay.get('instrument', 'N/A')}")
        st.markdown(f"- **결론**: {options_overlay.get('verdict', 'N/A')}")

# ----------------------------------------------------------------------------
# 내 포트폴리오와 비교 — 리밸런싱 diff (2026-09-14 추가)
#
# 이 섹션은 새 신호를 만들지 않는다 — 위에서 이미 계산한 코어/새틀라이트 추천과
# app/pages/8_포트폴리오_관리.py 에 직접 입력해둔 실제 보유 종목을 비교만 한다. 이 앱은 증권사
# 자동연동이 없으므로, 아직 보유 종목을 등록하지 않았다면 8번 페이지에서 먼저 입력해야 한다.
# ----------------------------------------------------------------------------
st.markdown("## 5. 내 포트폴리오와 비교")
holdings_pnl = get_portfolio_pnl()
if holdings_pnl.empty:
    st.info(
        "아직 등록된 보유 종목이 없습니다 — [8_포트폴리오_관리] 페이지에서 실제 보유 종목(티커/수량/매입가)을 "
        "먼저 입력하면 이 엔진의 추천과 실제 보유를 비교해 무엇을 사고팔아야 할지 보여줍니다."
    )
else:
    if satellite_result is None:
        st.caption(
            "⚠️ 새틀라이트를 아직 스캔하지 않아 코어(85%) 부분만 비교합니다 — 위 '2. 새틀라이트' "
            "섹션에서 스캔을 실행하면 전체(코어+새틀라이트) 비교로 확장됩니다."
        )
    st.caption(
        "ℹ️ 총 계좌가치는 '보유 종목 시가총액 합계 + 현금 잔고'로 계산합니다 — 현금 잔고는 "
        "[8_포트폴리오_관리] 페이지에서 최신 상태로 입력해두어야 정확합니다."
    )
    diff_df = compute_rebalance_diff(core_result, satellite_result=satellite_result, holdings_pnl=holdings_pnl)
    if diff_df.empty:
        st.info("비교할 데이터가 없습니다.")
    else:
        action_order = {"매수": 0, "매도": 1, "현금 보유": 2, "유지": 3}
        diff_df = diff_df.iloc[diff_df["action"].map(action_order).argsort(kind="stable")]
        st.dataframe(
            diff_df.rename(
                columns={
                    "ticker": "티커", "source": "출처", "target_weight_pct": "목표비중(%)",
                    "current_weight_pct": "현재비중(%)", "diff_pct": "차이(%p)",
                    "current_value": "현재금액($)", "target_value": "목표금액($)",
                    "delta_value": "매매금액($)", "action": "액션",
                }
            ),
            use_container_width=True, hide_index=True,
        )

# ----------------------------------------------------------------------------
# 확신도 등급 + 기각된 아이디어
# ----------------------------------------------------------------------------
st.markdown("## 확신도 — 이 시스템의 각 결정이 얼마나 검증됐는가")
st.caption("이 엔진이 스스로 매긴 등급이 아니라, 리서치 프로그램이 순열검정·블록부트스트랩·국면 분해 감사를 거쳐 부여한 등급입니다.")

confidence_table = load_confidence_table()
if confidence_table:
    grade_order = {"robust": 0, "moderate": 1, "weak": 2, "reversed": 3}
    for row in sorted(confidence_table, key=lambda r: grade_order.get(r["grade"], 9)):
        with st.container(border=True):
            st.markdown(f"**{_GRADE_BADGE.get(row['grade'], row['grade'])} — {row['component']}**")
            st.caption(row["note"])
            st.caption(f"근거: {row['source']}")

rejected_ideas = load_rejected_ideas()
if rejected_ideas:
    with st.expander(f"이미 검토했지만 채택하지 않은 아이디어 ({len(rejected_ideas)}개)"):
        st.caption("베타헤지/개별주 전면확장 등 — 이 엔진이 왜 그런 기능을 추천하지 않는지의 근거입니다.")
        for row in rejected_ideas:
            st.markdown(f"**{_GRADE_BADGE.get(row['grade'], row['grade'])} — {row['component']}**")
            st.caption(row["note"])

st.caption(
    "더 자세한 근거는 `docs/reports/research_program_synthesis.html`(리서치 프로그램 전체 종합 리포트)을 참고하세요."
)
