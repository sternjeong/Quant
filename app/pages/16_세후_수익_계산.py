"""세후·환전 후 수익 계산 페이지 (2026-10-05 추가, 사용자 요청 — 카카오페이증권 이용).

백테스트 수익률과 '실제로 통장에 남는 돈'의 차이(매매 수수료·환전 스프레드·양도소득세·배당 원천징수)를 원화로 보여 준다.
계산은 core/tax_fx.py 에 있고 이 파일은 화면만 담당한다. 주문 경로와 연결되어 있지 않다.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import tax_fx as tx
from core.theme import apply_theme

st.set_page_config(page_title="세후 수익 계산", page_icon="🧾", layout="wide")
apply_theme()
st.title("🧾 세후 수익 계산")
st.caption("챔피언 코어를 실제 계좌처럼 굴려 수수료·환전·양도소득세·배당 원천징수를 뺀 원화 금액을 봅니다. "
           "같은 설정으로 'SPY 그냥 보유'도 나란히 계산합니다. 추정치이며 세금 신고용이 아닙니다.")

with st.expander("계산 가정 (카카오페이증권 기준, 2026-10 조사)", expanded=False):
    st.markdown(
        "- 매매 수수료 0.1%(해외주식 기본). 환전 스프레드는 기본 1% × (1 − 우대율). 실시간 환전 시간 95% 우대 → 0.05%.\n"
        "- **확인 필요**: 원화 주문(자동환전)의 우대율(우대 없음이라는 후기가 있음), 카카오페이증권의 취득가액 계산 방식(선입선출/이동평균).\n"
        "- 양도소득세: 해외주식 연간 순이익(원화)에서 250만 원 공제 후 22%, 다음 해 5월 말 납부. 손실 이월 없음.\n"
        "- 배당: 미국 원천징수 15%. 금융소득 2,000만 원 초과 종합과세는 넣지 않았습니다.\n"
        "- 코어 100% 기준입니다(새틀라이트 15% 미포함). 매매는 목표 비중이 바뀌는 날에만 합니다."
    )

c1, c2, c3 = st.columns(3)
initial = c1.number_input("투자금(원)", min_value=1_000_000, value=30_000_000, step=1_000_000)
start = c2.date_input("시작일", value=pd.Timestamp("2010-01-04").date())
fx_mode_label = c3.radio("환전 방식", ["달러로 바꿔 두고 달러로 매매", "매매할 때마다 원화↔달러"], index=0)
c4, c5, c6 = st.columns(3)
fee_pct = c4.number_input("매매 수수료(%)", min_value=0.0, max_value=1.0, value=tx.KAKAO_FEE * 100, step=0.01, format="%.3f")
discount = c5.slider("환전 우대율(%)", 0, 100, 95 if fx_mode_label.startswith("달러") else 0)
basis_label = c6.radio("취득가액 계산", ["이동평균", "선입선출"], index=0)
integer_shares = st.checkbox("정수 주로만 매수(소수점 매매 안 함)", value=False)

cfg = tx.AccountConfig(
    initial_krw=float(initial), fee_rate=fee_pct / 100, fx_spread=tx.BASE_FX_SPREAD * (1 - discount / 100),
    fx_mode="usd_hold" if fx_mode_label.startswith("달러") else "krw_each_trade",
    cost_basis="average" if basis_label == "이동평균" else "fifo", integer_shares=integer_shares,
)


@st.cache_data(ttl=6 * 3600, show_spinner="코어 백테스트와 계좌 시뮬레이션 중… (1분 안팎)")
def _run(start_iso: str, cfg_items: tuple) -> dict:
    return tx.run_core_vs_spy(start_iso, tx.AccountConfig(**dict(cfg_items)))


if st.button("▶ 계산", type="primary"):
    st.session_state["taxfx_key"] = (start.isoformat(), tuple(sorted(cfg.__dict__.items())))

key = st.session_state.get("taxfx_key")
if not key:
    st.info("설정을 고르고 '▶ 계산'을 누르세요.")
    st.stop()

try:
    res = _run(*key)
except Exception as exc:  # noqa: BLE001
    st.error(f"계산 실패: {type(exc).__name__}: {exc}")
    st.stop()


def _won(v: float) -> str:
    return f"{v / 1e6:,.1f}백만 원"


rows = []
for name, r in (("챔피언 코어", res["core"]), ("SPY 그냥 보유", res["spy"])):
    t = r["totals"]
    rows.append({
        "": name, "세전 연수익": f"{r['cagr_pre']:.2%}", "세후·비용후 연수익": f"{r['cagr_after']:.2%}",
        "최종 평가액": _won(r["final_krw"]), "지금 다 팔면": _won(r["final_after_liquidation_krw"]),
        "최대 낙폭": f"{r['mdd_after']:.1%}", "양도세": _won(t["capital_gains_tax_krw"]),
        "배당세": _won(t["dividend_tax_krw"]), "수수료": _won(t["fees_krw"]), "환전 비용": _won(t["fx_cost_krw"]),
    })
st.dataframe(pd.DataFrame(rows).set_index(""), width="stretch")
st.caption("'지금 다 팔면'은 아직 안 낸 양도세(미실현 이익)까지 뺀 금액입니다. 그냥 보유는 팔기 전까지 세금이 미뤄지므로 "
           "평가액과 이 값을 함께 봐야 공정합니다. 과거 결과이며 앞으로의 수익을 뜻하지 않습니다.")

fig = go.Figure()
for name, r, color in (("코어 세후", res["core"]["values_krw"], "#2e7d32"), ("코어 세전", res["core"]["pre_cost_krw"], "#a5d6a7"),
                       ("SPY 세후", res["spy"]["values_krw"], "#1565c0")):
    fig.add_trace(go.Scatter(x=r.index, y=r.values / 1e6, name=name, line=dict(color=color)))
fig.update_layout(height=380, yaxis_title="백만 원", margin=dict(l=10, r=10, t=10, b=10))
st.plotly_chart(fig, width="stretch")

st.subheader("연도별 양도차익과 세금 (챔피언 코어)")
years = pd.DataFrame(res["core"]["years"])
if not years.empty:
    show = years.set_index("year")
    st.dataframe((show.select_dtypes("number") / 1e6).round(2).rename(columns=lambda c: c.replace("_krw", "(백만 원)")),
                 width="stretch")
pays = pd.DataFrame(res["core"]["tax_payments"])
if not pays.empty:
    st.caption("양도세 납부(다음 해 5월 말, 현금이 모자라면 비중대로 팔아서 냄)")
    st.dataframe(pays, width="stretch", hide_index=True)
