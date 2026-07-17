"""신규: 종목 발굴(스크리닝) 페이지.

core.strategy_tuning 이 이미 고정된 S&P500 종목 집합에 대해 진입/청산 타이밍을 최적화하는 도구라면,
이 페이지는 그보다 한 단계 앞선 질문 — "애초에 어떤 종목을 보유할지" — 에 답하기 위한 독립적인
스크리닝 도구다(core/stock_discovery.py). 튜닝 엔진과는 얽혀있지 않으며, 여기서 뽑은 종목을
튜닝/백테스트에 넣고 싶으면 사용자가 직접 다른 페이지(관심종목/전략 관리 등)로 옮겨야 한다.

주의: 과거 이력 저장(스냅샷 DB 적재 등)은 아직 만들지 않았다 — 지금은 "현재 시점" 1회성 스캔
결과만 보여준다. 시계열로 추적하고 싶다면(예: 매주 발굴 결과 변화 비교) 향후 확장 과제.
"""

import sys
from pathlib import Path

# --- sys.path 부트스트랩: 프로젝트 루트를 추가해 core.* 임포트 가능하게 함 (app/pages/*.py 공통 규칙) ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

from core import screener
from core.stock_discovery import DEFAULT_WEIGHTS, discover_candidates
from core.theme import apply_theme

st.set_page_config(page_title="종목 발굴", page_icon="🧭", layout="wide")
apply_theme()
st.title("🧭 종목 발굴")
st.caption(
    "모멘텀·성장·가치·퀄리티 4개 팩터의 percentile 점수를 합성해 S&P500 유니버스에서 상위 후보를 뽑습니다. "
    "타이밍 최적화(전략 튜닝)와 달리 '어떤 종목을 볼지' 자체를 고르는 용도의 독립 스크리닝 도구입니다."
)

try:
    universe_df = screener.get_universe(use_cache=True)
    all_sectors = sorted(universe_df["Sector"].dropna().unique().tolist()) if not universe_df.empty else []
except Exception:
    all_sectors = []

with st.sidebar:
    st.markdown("### 발굴 조건")
    sector_filter = st.multiselect("섹터 필터 (비워두면 전체)", options=all_sectors, default=[])
    universe_n = st.number_input(
        "스캔할 종목 수 (앞에서부터 N개, 응답 속도용)",
        min_value=10,
        max_value=500,
        value=100,
        step=10,
    )
    top_n = st.number_input("결과 상위 N개", min_value=5, max_value=100, value=30, step=5)

    st.markdown("### 팩터 가중치")
    w_momentum = st.slider("모멘텀", 0.0, 1.0, DEFAULT_WEIGHTS["momentum"], 0.05)
    w_growth = st.slider("성장", 0.0, 1.0, DEFAULT_WEIGHTS["growth"], 0.05)
    w_value = st.slider("가치", 0.0, 1.0, DEFAULT_WEIGHTS["value"], 0.05)
    w_quality = st.slider("퀄리티", 0.0, 1.0, DEFAULT_WEIGHTS["quality"], 0.05)

    weight_sum = w_momentum + w_growth + w_value + w_quality
    if abs(weight_sum - 1.0) > 1e-6:
        if weight_sum > 0:
            st.warning(f"가중치 합이 {weight_sum:.2f} 입니다 — 1.0이 되도록 자동 정규화해 계산합니다.")
        else:
            st.warning("모든 가중치가 0입니다 — 기본 가중치를 사용합니다.")

    run_clicked = st.button("🔍 종목 발굴 실행", type="primary", use_container_width=True)

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

        **주의**: 이 페이지는 현재 시점 스냅샷 스캔만 제공하며, 과거 이력 저장/추적 기능은 아직
        없습니다(향후 확장 가능).
        """
    )
