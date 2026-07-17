"""모듈 F: 밸류에이션 도구 페이지.

한 종목에 대해 PER/PBR 히스토리 밴드, 동종업계 피어 비교, 여러 밸류에이션 방법론(DCF/DDM/
PER·PBR 상대가치/EV·EBITDA/PEG/그레이엄 넘버)을 한 화면에서 비교한다. 특정 방법론으로
결론을 내리지 않고, 여러 결과를 나란히 놓고 직접 판단하는 것이 목표(SPEC.md 모듈 F).
"""

import sys
from pathlib import Path

# --- sys.path 부트스트랩: 프로젝트 루트를 추가해 core.* 임포트 가능하게 함 (app/pages/*.py 공통 규칙) ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import plotly.graph_objects as go
import streamlit as st

from core.db import init_db
from core import job_manager
from core.theme import apply_theme
from core.valuation import (
    compute_all_valuations,
    fetch_valuation_inputs,
    get_peer_comparison,
    get_valuation_band,
    select_auto_peers,
)

# 방법론별 카드의 물음표 아이콘(st.metric의 help=)에 뜨는 3줄 안팎 설명. compute_all_valuations()의
# methods dict 키와 1:1로 맞춰뒀다(신규 방법론 추가 시 여기도 같이 추가할 것).
_METHOD_HELP = {
    "dcf": (
        "미래 잉여현금흐름(FCF)을 현재가치로 할인해 적정 주가를 추정합니다.\n"
        "성장률/할인율 가정치(위 '가정치 조절'에서 변경 가능)에 따라 결과가 크게 달라집니다.\n"
        "잉여현금흐름 데이터가 없거나 마이너스면 산출할 수 없습니다."
    ),
    "ddm": (
        "미래 배당금을 현재가치로 할인해 적정 주가를 추정합니다.\n"
        "배당을 지급하지 않는 종목은 산출할 수 없습니다.\n"
        "고배당·안정 성장 기업(유틸리티, 배당주 등)에 특히 적합한 방법입니다."
    ),
    "per_relative": (
        "주당순이익(EPS)에 동종업계 평균 PER을 곱해 적정 주가를 추정합니다.\n"
        "위에서 '피어 평균 PER'을 직접 입력하지 않으면 자기 자신의 현재 PER을 그대로 씁니다.\n"
        "동종업계와 성장성/리스크가 비슷할 때 더 신뢰할 수 있는 방법입니다."
    ),
    "pbr_relative": (
        "주당순자산(BVPS)에 동종업계 평균 PBR을 곱해 적정 주가를 추정합니다.\n"
        "자산 비중이 큰 업종(금융/제조업)에서 특히 많이 쓰입니다.\n"
        "무형자산 비중이 큰 기업(소프트웨어 등)에는 잘 안 맞을 수 있습니다."
    ),
    "ev_ebitda": (
        "EBITDA에 동종업계 평균 EV/EBITDA 배수를 곱해 기업가치(EV)를 구한 뒤,\n"
        "순부채(총부채-총현금)를 빼고 발행주식수로 나눠 적정 주가를 추정합니다.\n"
        "자본구조(부채비율)가 다른 기업 간 비교에서 PER보다 유리한 방법입니다."
    ),
    "graham_number": (
        "벤저민 그레이엄이 제시한 보수적 적정주가 공식 √(22.5 × EPS × BVPS)입니다.\n"
        "EPS와 BVPS가 모두 양수여야 계산되며, 성장주보다 가치주에 더 적합합니다.\n"
        "다른 방법론보다 훨씬 보수적인(낮은) 값이 나오는 경향이 있습니다."
    ),
}
_PEG_HELP = (
    "PER을 이익성장률(%)로 나눈 값입니다.\n"
    "1.0에 가까우면 이익 성장 대비 적정가로 흔히 해석됩니다(참고용 경험칙).\n"
    "이익성장률 데이터가 없으면 산출할 수 없습니다."
)

init_db()

st.set_page_config(page_title="밸류에이션 도구", page_icon="🧮", layout="wide")
apply_theme()
job_manager.render_active_jobs_sidebar()
st.title("🧮 밸류에이션 도구")
st.caption("여러 밸류에이션 방법론의 결과를 한 화면에서 비교합니다. 특정 기법이 정답은 아니니 참고용으로만 사용하세요.")

ticker = st.text_input("종목 티커", placeholder="예: AAPL").strip().upper()

if not ticker:
    st.info("티커를 입력해주세요.")
    st.stop()

job_manager.ensure("valuation_inputs", ticker, fetch_valuation_inputs, ticker, label=f"{ticker} 데이터 조회")
valuation_job = job_manager.render("valuation_inputs", running_label=f"{ticker} 데이터를 가져오는 중")
if valuation_job.status == "error":
    st.error(f"{ticker} 데이터를 가져오지 못했습니다: {valuation_job.error}")
    st.stop()
inputs = valuation_job.result

if inputs.get("currentPrice") is None:
    st.error(f"{ticker} 데이터를 가져오지 못했습니다. 티커를 확인해주세요.")
    st.stop()

st.markdown(f"### {inputs.get('longName') or ticker} ({ticker})")
c1, c2, c3 = st.columns(3)
c1.metric("현재가", f"${inputs['currentPrice']:,.2f}")
c2.metric("PER", f"{inputs['trailingPE']:.2f}" if inputs.get("trailingPE") else "-")
c3.metric("PBR", f"{inputs['priceToBook']:.2f}" if inputs.get("priceToBook") else "-")

tab_methods, tab_band, tab_peer = st.tabs(["📐 방법론별 비교", "📈 PER/PBR 밴드", "🏢 피어 비교"])

# ============================================================================
# 탭 1: 방법론별 비교 (가정치 조절 가능)
# ============================================================================
with tab_methods:
    with st.expander("⚙️ 가정치 조절 (DCF/DDM/상대가치 배수)"):
        a1, a2, a3 = st.columns(3)
        with a1:
            st.markdown("**DCF**")
            dcf_growth = st.slider("연 성장률", 0.0, 0.30, 0.08, 0.01, key="dcf_growth")
            dcf_discount = st.slider("할인율", 0.05, 0.20, 0.10, 0.01, key="dcf_discount")
            dcf_terminal = st.slider("영구성장률", 0.0, 0.05, 0.025, 0.005, key="dcf_terminal")
        with a2:
            st.markdown("**DDM**")
            ddm_required = st.slider("요구수익률", 0.03, 0.20, 0.09, 0.01, key="ddm_required")
            ddm_growth = st.slider("배당 성장률", 0.0, 0.10, 0.03, 0.005, key="ddm_growth")
        with a3:
            st.markdown("**상대가치 배수** (비워두면 자기 자신의 현재 배수 사용)")
            peer_per = st.number_input("피어 평균 PER", value=None, placeholder=f"기본값: {inputs.get('trailingPE') or '-'}")
            peer_pbr = st.number_input("피어 평균 PBR", value=None, placeholder=f"기본값: {inputs.get('priceToBook') or '-'}")

    assumptions = {
        "dcf_growth_rate": dcf_growth,
        "dcf_discount_rate": dcf_discount,
        "dcf_terminal_growth": dcf_terminal,
        "ddm_required_return": ddm_required,
        "ddm_growth_rate": ddm_growth,
    }
    if peer_per:
        assumptions["peer_per"] = peer_per
    if peer_pbr:
        assumptions["peer_pbr"] = peer_pbr

    result = compute_all_valuations(ticker, assumptions=assumptions, inputs=inputs)
    current_price = result["current_price"]

    st.markdown("### 방법론별 추정 주당가치 vs 현재가")
    method_cols = st.columns(3)
    for i, (key, m) in enumerate(result["methods"].items()):
        with method_cols[i % 3]:
            help_text = _METHOD_HELP.get(key)
            if m["value"] is None:
                st.metric(m["label"], "산출 불가", help=help_text)
            else:
                diff_pct = (m["value"] / current_price - 1) * 100
                st.metric(m["label"], f"${m['value']:,.2f}", f"{diff_pct:+.1f}% (현재가 대비)", help=help_text)

    chart_values = {m["label"]: m["value"] for m in result["methods"].values() if m["value"] is not None}
    if chart_values:
        fig = go.Figure()
        fig.add_trace(go.Bar(x=list(chart_values.keys()), y=list(chart_values.values()), name="추정 주당가치"))
        fig.add_hline(y=current_price, line_dash="dash", line_color="red", annotation_text="현재가")
        fig.update_layout(height=400, yaxis_title="주당가치 ($)")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("이 종목은 산출 가능한 방법론이 없습니다 (데이터 부족).")

    peg_value = result["peg"]["value"]
    st.metric(
        "PEG 비율",
        f"{peg_value:.2f}" if peg_value is not None else "산출 불가 (이익성장률 데이터 없음)",
        help=_PEG_HELP,
    )

# ============================================================================
# 탭 2: PER/PBR 히스토리 밴드
# ============================================================================
with tab_band:
    st.caption(
        "⚠️ 분기별 실제 과거 EPS/BVPS는 무료로 구하기 어려워, **현재 EPS/BVPS를 과거 주가에 그대로 적용한 근사치**입니다. "
        "추세 참고용으로만 사용하세요."
    )
    years = st.slider("조회 기간(년)", 1, 10, 5, key="band_years")
    band_df = get_valuation_band(ticker, years=years, inputs=inputs)

    if band_df.empty:
        st.warning("가격 데이터를 가져오지 못했습니다.")
    else:
        per_col, pbr_col = st.columns(2)
        with per_col:
            if band_df["PER"].notna().any():
                fig_per = go.Figure()
                fig_per.add_trace(go.Scatter(x=band_df.index, y=band_df["PER"], name="PER"))
                fig_per.add_hline(y=band_df["PER"].mean(), line_dash="dot", annotation_text="평균")
                fig_per.update_layout(title="PER 밴드", height=350)
                st.plotly_chart(fig_per, use_container_width=True)
            else:
                st.info("EPS 데이터가 없어 PER 밴드를 계산할 수 없습니다.")
        with pbr_col:
            if band_df["PBR"].notna().any():
                fig_pbr = go.Figure()
                fig_pbr.add_trace(go.Scatter(x=band_df.index, y=band_df["PBR"], name="PBR"))
                fig_pbr.add_hline(y=band_df["PBR"].mean(), line_dash="dot", annotation_text="평균")
                fig_pbr.update_layout(title="PBR 밴드", height=350)
                st.plotly_chart(fig_pbr, use_container_width=True)
            else:
                st.info("BVPS 데이터가 없어 PBR 밴드를 계산할 수 없습니다.")

# ============================================================================
# 탭 3: 동종업계 피어 비교
# ============================================================================
with tab_peer:
    st.caption(
        "같은 섹터에서 시가총액이 가장 비슷한 종목 2개를 자동으로 골라 비교합니다(AI 호출 없는 "
        "규칙 기반 — core.screener 캐시를 재사용해 빠릅니다). 필요하면 아래에서 직접 바꿀 수 있습니다."
    )
    job_manager.ensure("valuation_auto_peers", ticker, select_auto_peers, ticker, label="자동 피어 선정")
    auto_peers_job = job_manager.render("valuation_auto_peers", running_label="같은 섹터에서 비슷한 종목을 찾는 중")

    default_peer_input_key = f"peer_input_{ticker}"
    applied_flag_key = f"peer_auto_applied_{ticker}"
    st.session_state.setdefault(default_peer_input_key, "")
    # job_manager.render()는 작업이 막 끝난 그 rerun에서만 Job을 반환한다(그 다음부턴 추적이 지워져
    # None) — 그 타이밍에 딱 한 번만 자동 선정 결과를 입력창 기본값에 반영해, 이후 사용자가 직접
    # 수정한 값을 재실행마다 덮어쓰지 않게 한다.
    if auto_peers_job is not None and not st.session_state.get(applied_flag_key):
        st.session_state[default_peer_input_key] = ", ".join(auto_peers_job.result)
        st.session_state[applied_flag_key] = True

    peer_input = st.text_input(
        "피어 티커 (쉼표로 구분, 자동 선정 결과를 직접 수정 가능)",
        key=default_peer_input_key,
        placeholder="예: MSFT, GOOGL, META",
    )
    if st.session_state.get(applied_flag_key) and peer_input.strip() == "":
        st.caption("자동 선정된 피어가 없어 직접 입력이 필요합니다 (섹터/시가총액 정보 부족).")

    peer_tickers = [ticker] + [t.strip().upper() for t in peer_input.split(",") if t.strip()]
    peer_tickers = list(dict.fromkeys(peer_tickers))  # 순서 유지 dedupe

    if len(peer_tickers) > 1:
        job_manager.ensure("valuation_peers", peer_tickers, get_peer_comparison, peer_tickers, label="피어 데이터 조회")
        peer_job = job_manager.render("valuation_peers", running_label="피어 데이터를 가져오는 중")
        peer_df = peer_job.result
        display_df = peer_df.rename(
            columns={
                "ticker": "티커",
                "name": "종목명",
                "sector": "섹터",
                "per": "PER",
                "pbr": "PBR",
                "ev_ebitda": "EV/EBITDA",
                "current_price": "현재가",
            }
        )
        st.dataframe(display_df, use_container_width=True, hide_index=True)
    else:
        st.info("피어 티커를 1개 이상 입력하면 비교 테이블이 표시됩니다.")
