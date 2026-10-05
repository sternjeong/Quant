"""세후·환전 후 수익 계산 페이지 (2026-10-05 추가, 사용자 요청 — 카카오페이증권 이용).

백테스트 수익률과 '실제로 통장에 남는 돈'의 차이(매매 수수료·환전 스프레드·양도소득세·배당 원천징수)를 원화로 보여 준다.
계산은 core/tax_fx.py 에 있고 이 파일은 화면만 담당한다. 주문 경로와 연결되어 있지 않다.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from datetime import date, timedelta

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

@st.cache_data(ttl=6 * 3600, show_spinner="코어 백테스트와 계좌 시뮬레이션 중… (1분 안팎)")
def _run(start_iso: str, cfg_items: tuple) -> dict:
    return tx.run_core_vs_spy(start_iso, tx.AccountConfig(**dict(cfg_items)))


def _simulation_tab() -> None:
    with st.expander("계산 가정 (카카오페이증권 기준, 2026-10 조사)", expanded=False):
        st.markdown(
            "- 매매 수수료 0.1%(해외주식 기본). 환전 스프레드는 기본 1% × (1 − 우대율). 실시간 환전 시간 95% 우대 → 0.05%.\n"
            "- **확인 필요**: 원화 주문(자동환전)의 우대율(우대 없음이라는 후기가 있음), 카카오페이증권의 취득가액 계산 방식(선입선출/이동평균).\n"
            "- 양도소득세: 해외주식 연간 순이익(원화)에서 250만 원 공제 후 22%, 다음 해 5월 말 납부. 손실 이월 없음.\n"
            "- 배당: 미국 원천징수 15% 를 뗀 나머지를 받는 날 같은 종목으로 다시 삽니다. 금융소득 2,000만 원 초과 종합과세는 넣지 않았습니다.\n"
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
    c7, c8, c9 = st.columns(3)
    integer_shares = c7.checkbox("정수 주로만 매수(소수점 매매 안 함)", value=False)
    harvest_gains = c8.checkbox("연말 공제 채우기(250만 원)", value=False,
                                help="12월 마지막 거래일 3일 전, 그해 실현 이익이 250만 원보다 적으면 이익 난 종목을 일부 팔았다 바로 다시 삽니다.")
    harvest_losses = c9.checkbox("연말 손실 확정", value=False,
                                 help="같은 날, 그해 실현 이익이 250만 원을 넘으면 손실 난 종목을 팔았다 바로 다시 사서 상계합니다.")

    cfg = tx.AccountConfig(
        initial_krw=float(initial), fee_rate=fee_pct / 100, fx_spread=tx.BASE_FX_SPREAD * (1 - discount / 100),
        fx_mode="usd_hold" if fx_mode_label.startswith("달러") else "krw_each_trade",
        cost_basis="average" if basis_label == "이동평균" else "fifo", integer_shares=integer_shares,
        harvest_gains=harvest_gains, harvest_losses=harvest_losses,
    )





    if st.button("▶ 계산", type="primary"):
        st.session_state["taxfx_key"] = (start.isoformat(), tuple(sorted(cfg.__dict__.items())))

    key = st.session_state.get("taxfx_key")
    if not key:
        st.info("설정을 고르고 '▶ 계산'을 누르세요.")
        return

    try:
        res = _run(*key)
    except Exception as exc:  # noqa: BLE001
        st.error(f"계산 실패: {type(exc).__name__}: {exc}")
        return


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


def _my_account_tab() -> None:
    from core import portfolio as pf
    from core import tax_planner as tp
    from core.market_data import get_multiple_price_history

    today = date.today()
    year = today.year
    st.caption("포트폴리오 화면에 입력한 보유(매입일·단가·수량)를 매입일 환율로 원화 취득가로 바꿔, 올해 낼 양도세와 "
               "연말 공제 채우기·손실 확정을 계산합니다. 매매 규칙은 바꾸지 않습니다(팔았다 같은 날 다시 사는 제안).")
    saved = tp.load_realized(year)
    c1, c2 = st.columns([2, 1])
    ytd = c1.number_input(f"{year}년에 이미 실현한 해외주식 이익(원) — 카카오페이증권 앱의 양도세 예상 금액 화면 값",
                          value=float(saved or 0.0), step=100_000.0, format="%.0f")
    if c2.button("저장", key="tax_ytd_save"):
        tp.save_realized(year, ytd)
        st.success("저장했습니다. 챔피언 전략 화면의 세금 미리보기도 이 값을 씁니다.")
    holdings = pf.list_holdings()
    if not holdings:
        st.info("포트폴리오 화면에 보유가 없습니다. 보유를 입력하면 종목별 원화 손익과 제안이 나옵니다.")
        return
    if not st.button("📒 내 보유로 올해 세금 계산", type="primary"):
        return
    with st.spinner("가격과 환율을 읽는 중…"):
        tickers = sorted({h["ticker"] for h in holdings})
        hist = get_multiple_price_history(tickers, start=(today - timedelta(days=10)).isoformat(), end=None, interval="1d")
        prices = {t: float(hist[t]["Close"].dropna().iloc[-1]) for t in tickers if t in hist and not hist[t].empty}
        pos = tp.positions(holdings, prices, tp.load_fx())
    st.dataframe(pd.DataFrame([
        {"종목": p["ticker"], "수량": p["shares"], "원화 취득가": f"{p['cost_krw']:,.0f}",
         "지금 팔면(원)": "—" if p["value_krw"] is None else f"{p['value_krw']:,.0f}",
         "미실현 손익(원)": "—" if p["gain_krw"] is None else f"{p['gain_krw']:,.0f}"} for p in pos]),
        width="stretch", hide_index=True)
    unreal = sum(p["gain_krw"] or 0.0 for p in pos)
    summ = tp.year_summary(ytd, 0.0, year)
    m1, m2, m3 = st.columns(3)
    m1.metric("올해 실현 이익", f"{ytd:,.0f}원")
    m2.metric("공제 남음", f"{summ['deduction_left_krw']:,.0f}원")
    m3.metric(f"{year + 1}년 5월 예상 양도세", f"{summ['tax_krw']:,.0f}원")
    st.caption(f"지금 보유를 다 팔면 미실현 손익 {unreal:,.0f}원이 더해집니다(예상 세금 "
               f"{tp.year_summary(ytd, unreal, year)['tax_krw']:,.0f}원).")
    sug = tp.harvest_suggestions(pos, float(ytd), today)
    st.subheader("연말 제안")
    if not sug["rows"]:
        st.write("지금 할 만한 공제 채우기·손실 확정이 없습니다"
                 + (" (공제 250만 원을 이미 정확히 썼거나 대상 종목이 없음)." if sug["kind"] else "."))
    else:
        what = "공제 채우기 — 이익 난 종목을 아래 수량만큼 팔고 같은 날 같은 수량을 다시 삽니다" if sug["kind"] == "gain" \
            else "손실 확정 — 손실 난 종목을 아래 수량만큼 팔고 같은 날 같은 수량을 다시 삽니다"
        (st.success if sug["actionable"] else st.info)(
            what + ("" if sug["actionable"] else f" (지금은 참고 — 11월 15일 이후에 하는 게 맞습니다. 그 전에 하면 남은 기간에 이익·손실이 또 생깁니다)"))
        st.dataframe(pd.DataFrame([
            {"종목": r["ticker"], "팔았다 다시 살 수량": r["shares"], "실현되는 손익(원)": f"{r['realize_krw']:,.0f}",
             "수수료(원, 왕복)": f"{r['fees_krw']:,.0f}",
             "줄어드는 세금(원)": f"{r.get('tax_saved_later_krw', r.get('tax_saved_now_krw', 0)):,.0f}"
                              + (" (나중)" if "tax_saved_later_krw" in r else " (올해)")} for r in sug["rows"]]),
            width="stretch", hide_index=True)
        st.caption(f"합계: 세금 {sug['tax_saved_krw']:,.0f}원 감소 vs 수수료 {sug['fees_krw']:,.0f}원"
                   + ("" if sug["worth_it"] else " — 수수료에 비해 이득이 작습니다."))
    for n in sug["notes"]:
        st.caption("· " + n)


tab_sim, tab_me = st.tabs(["📈 전략을 세후로 (과거 계산)", "📒 내 계좌 올해 세금"])
with tab_sim:
    _simulation_tab()
with tab_me:
    _my_account_tab()
