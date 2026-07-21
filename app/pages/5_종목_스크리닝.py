"""모듈 E 통합: 종목 스크리닝 페이지 (2026-07-21 통합 — 이전 5_퀀트_스크리너.py + 14_종목_발굴.py).

두 페이지 모두 "지금 어떤 종목을 볼지" 고르는 스크리닝 도구라는 같은 목적을 서로 다른 방법론으로
풀고 있어(하나는 절대 기준 필터, 하나는 상대 순위 팩터 스코어) 탭으로 묶었다. 종목 타이밍
최적화(진입/청산 파라미터 튜닝)는 "🧪 전략 스튜디오" 페이지의 별도 영역이며 여기서 다루지 않는다.

- 탭1 "🔎 필터 스크리닝" (구 퀀트 스크리너): PER/PBR/시가총액/섹터/기술적 지표 조건으로
  S&P500 종목을 필터링.
- 탭2 "🧭 팩터 발굴" (구 종목 발굴): 모멘텀/성장/가치/퀄리티 4팩터 percentile 점수를 합성해
  상위 후보를 뽑는 상대 순위 방식. 과거 이력 저장은 아직 없음(현재 시점 1회성 스캔).
"""

import sys
from pathlib import Path

# --- sys.path 부트스트랩: 프로젝트 루트를 추가해 core.* 임포트 가능하게 함 (app/pages/*.py 공통 규칙) ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

from core import job_manager, screener
from core.db import init_db
from core.screener import list_sectors, screen
from core.stock_discovery import DEFAULT_WEIGHTS, discover_candidates
from core.theme import apply_theme
from core.watchlist import MAX_WATCHLIST_SIZE, add_to_watchlist, get_watchlist_count

init_db()

st.set_page_config(page_title="종목 스크리닝", page_icon="🔎", layout="wide")
apply_theme()
job_manager.render_active_jobs_sidebar()
st.title("🔎 종목 스크리닝")
st.caption("절대 기준 필터(탭1)와 상대 순위 팩터 스코어(탭2), 두 가지 방식으로 종목을 스크리닝합니다.")

tab_filter, tab_discovery = st.tabs(["🔎 필터 스크리닝", "🧭 팩터 발굴"])


def _render_filter_screener() -> None:
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
            add_targets = st.multiselect("추가할 티커 선택", result["ticker"].tolist(), key="filter_screener_add_targets")
            if st.button("➕ 관심 티커에 추가", disabled=not add_targets, key="filter_screener_add_btn"):
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


def _render_factor_discovery() -> None:
    st.caption(
        "모멘텀·성장·가치·퀄리티 4개 팩터의 percentile 점수를 합성해 S&P500 유니버스에서 상위 후보를 뽑습니다. "
        "절대 기준 필터(탭1)와 달리 유니버스 내 상대 순위로 후보를 골라내는 용도입니다."
    )

    try:
        universe_df = screener.get_universe(use_cache=True)
        all_sectors = sorted(universe_df["Sector"].dropna().unique().tolist()) if not universe_df.empty else []
    except Exception:
        all_sectors = []

    with st.sidebar:
        st.markdown("### 발굴 조건")
        sector_filter = st.multiselect("섹터 필터 (비워두면 전체)", options=all_sectors, default=[], key="discovery_sector_filter")
        universe_n = st.number_input(
            "스캔할 종목 수 (앞에서부터 N개, 응답 속도용)",
            min_value=10,
            max_value=500,
            value=100,
            step=10,
            key="discovery_universe_n",
        )
        top_n = st.number_input("결과 상위 N개", min_value=5, max_value=100, value=30, step=5, key="discovery_top_n")

        st.markdown("### 팩터 가중치")
        w_momentum = st.slider("모멘텀", 0.0, 1.0, DEFAULT_WEIGHTS["momentum"], 0.05, key="discovery_w_momentum")
        w_growth = st.slider("성장", 0.0, 1.0, DEFAULT_WEIGHTS["growth"], 0.05, key="discovery_w_growth")
        w_value = st.slider("가치", 0.0, 1.0, DEFAULT_WEIGHTS["value"], 0.05, key="discovery_w_value")
        w_quality = st.slider("퀄리티", 0.0, 1.0, DEFAULT_WEIGHTS["quality"], 0.05, key="discovery_w_quality")

        weight_sum = w_momentum + w_growth + w_value + w_quality
        if abs(weight_sum - 1.0) > 1e-6:
            if weight_sum > 0:
                st.warning(f"가중치 합이 {weight_sum:.2f} 입니다 — 1.0이 되도록 자동 정규화해 계산합니다.")
            else:
                st.warning("모든 가중치가 0입니다 — 기본 가중치를 사용합니다.")

        run_clicked = st.button("🔍 종목 발굴 실행", type="primary", use_container_width=True, key="discovery_run_btn")

    st.caption(
        "S&P500 전체(약 500종목)를 스캔하려면 사이드바에서 스캔 종목 수를 최대로 올리세요 — "
        "네트워크 조회량이 많아 시간이 오래 걸릴 수 있습니다(캐시된 종목은 빠름)."
    )

    if run_clicked:
        weight_sum = w_momentum + w_growth + w_value + w_quality
        if weight_sum > 0:
            weights = {
                "momentum": w_momentum / weight_sum,
                "growth": w_growth / weight_sum,
                "value": w_value / weight_sum,
                "quality": w_quality / weight_sum,
            }
        else:
            weights = DEFAULT_WEIGHTS

        with st.spinner("종목 발굴 중... (가격/펀더멘털 데이터를 종목별로 조회합니다)"):
            result_df = discover_candidates(
                universe_n=int(universe_n),
                weights=weights,
                sector_filter=sector_filter or None,
                top_n=int(top_n),
                use_cache=True,
            )

        if result_df.empty:
            st.warning("발굴 결과가 없습니다 — 필터 조건을 완화하거나 스캔 종목 수를 늘려보세요.")
        else:
            st.markdown(f"### 발굴 결과 ({len(result_df)}개)")
            display_df = result_df.rename(
                columns={
                    "ticker": "티커",
                    "name": "종목명",
                    "sector": "섹터",
                    "composite_score": "종합점수",
                    "momentum_score": "모멘텀",
                    "growth_score": "성장",
                    "value_score": "가치",
                    "quality_score": "퀄리티",
                    "trailing_pe": "PER",
                    "price_to_book": "PBR",
                    "earnings_growth": "이익성장률",
                    "market_cap": "시가총액",
                }
            )
            st.dataframe(
                display_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "종합점수": st.column_config.NumberColumn(format="%.1f"),
                    "모멘텀": st.column_config.NumberColumn(format="%.1f"),
                    "성장": st.column_config.NumberColumn(format="%.1f"),
                    "가치": st.column_config.NumberColumn(format="%.1f"),
                    "퀄리티": st.column_config.NumberColumn(format="%.1f"),
                    "PER": st.column_config.NumberColumn(format="%.1f"),
                    "PBR": st.column_config.NumberColumn(format="%.2f"),
                    "이익성장률": st.column_config.NumberColumn(format="%.1%"),
                    "시가총액": st.column_config.NumberColumn(format="%d"),
                },
            )
    else:
        st.info("사이드바에서 조건을 설정하고 '🔍 종목 발굴 실행' 버튼을 눌러주세요.")

    with st.expander("📖 스코어링 방법론"):
        st.markdown(
            """
            각 종목에 대해 4개 팩터를 계산하고, 스캔된 유니버스 안에서 **percentile 순위(0~100, 높을수록
            좋음)** 로 변환한 뒤 가중합해 `종합점수` 를 만듭니다.

            - **모멘텀**: IBD 스타일 가중 ROC(최근 3/6/9/12개월 수익률을 각각 40%/20%/20%/20% 비중으로
              합산). 최근 추세가 강할수록 높은 점수.
            - **성장**: yfinance `earningsGrowth`(연간 이익성장률) 기준. 높을수록 높은 점수.
            - **가치**: PER/PBR/PEG가 낮을수록(저평가일수록) 높은 점수. 적자 기업(PER이 없거나 음수)은
              밸류에이션 지표 자체가 무의미하므로 최하위로 처리합니다.
            - **퀄리티**: FCF 수익률(잉여현금흐름/시가총액)과 재무 레버리지 프록시(현금/부채, 무차입이면
              최상급)를 결합. 재무 건전성이 좋을수록 높은 점수.

            결측 데이터가 있는 종목은 해당 팩터에서 최하위 점수를 받습니다(정보가 없다고 좋은 점수를
            주지 않기 위한 보수적 처리).

            기본 가중치는 모멘텀 30% / 성장 30% / 가치 25% / 퀄리티 15% 입니다 — 모멘텀·성장을 가장
            중시하되, 가치 팩터로 고평가 함정을 걸러내고, 퀄리티는 하방 리스크 관리 보조 지표로 낮은
            비중을 둡니다. 사이드바에서 자유롭게 조정할 수 있습니다.

            **주의**: 이 탭은 현재 시점 스냅샷 스캔만 제공하며, 과거 이력 저장/추적 기능은 아직
            없습니다(향후 확장 가능).
            """
        )


with tab_filter:
    _render_filter_screener()

with tab_discovery:
    _render_factor_discovery()
