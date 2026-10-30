"""시장 자금 흐름 — 어느 시장이 강하고 약한지, 시장끼리 얼마나 같이 움직이는지, 주도주는 누구인지.

계산은 전부 core/market_flow.py 에 있다(순수 함수). 이 화면은 보여 주기만 한다.
'자금 이동'은 펀드 유출입 통계가 아니라 20일 초과수익과 거래대금 증가율로 만든 대리지표이며, 매매 신호가 아니다
(R&D 결과 로테이션 규칙은 세후로 SPY 를 이기지 못했다). 주문·추천·챔피언 규칙과 연결되어 있지 않다.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import market_flow as mf
from core.db import init_db
from core.theme import TRADINGVIEW_CHART_BG, TRADINGVIEW_CHART_GRID, TRADINGVIEW_CHART_TEXT, apply_theme

init_db()
st.set_page_config(page_title="시장 자금 흐름", page_icon="🌊", layout="wide")
apply_theme()
st.title("🌊 시장 자금 흐름")

_QUADRANT_COLORS = {
    mf.QUADRANT_LEADING: "#4caf82", mf.QUADRANT_WEAKENING: "#c98500",
    mf.QUADRANT_LAGGING: "#e5533d", mf.QUADRANT_IMPROVING: "#3987e5",
}
_PALETTE = ["#3987e5", "#d95926", "#008300", "#c98500", "#9085e9", "#e5533d", "#4caf82", "#8a8a8a"]


def _style(fig: go.Figure, height: int = 420) -> go.Figure:
    fig.update_layout(
        paper_bgcolor=TRADINGVIEW_CHART_BG, plot_bgcolor=TRADINGVIEW_CHART_BG,
        font=dict(color=TRADINGVIEW_CHART_TEXT), height=height, margin=dict(l=10, r=20, t=30, b=40),
    )
    fig.update_xaxes(gridcolor=TRADINGVIEW_CHART_GRID, zerolinecolor=TRADINGVIEW_CHART_GRID)
    fig.update_yaxes(gridcolor=TRADINGVIEW_CHART_GRID, zerolinecolor=TRADINGVIEW_CHART_GRID)
    return fig


@st.cache_data(ttl=1800, show_spinner="시장 가격을 불러오는 중…")
def _load_recent():
    return mf.load_universe()


@st.cache_data(ttl=6 * 3600, show_spinner="장기 가격(약 16년)을 불러오는 중…")
def _load_long():
    start = (date.today() - timedelta(days=mf.LONG_LOOKBACK_DAYS)).isoformat()
    return mf.load_universe(start=start)


@st.cache_data(ttl=1800, show_spinner="종목 가격을 불러오는 중…")
def _load_histories(tickers: tuple[str, ...]):
    from core.market_data import get_multiple_price_history

    start = (date.today() - timedelta(days=mf.LOOKBACK_DAYS)).isoformat()
    return get_multiple_price_history(list(tickers), start=start, interval="1d")


close, volume, missing = _load_recent()
if close.empty or mf.BENCHMARK not in close.columns:
    st.error("가격 데이터를 불러오지 못했습니다. 잠시 뒤 다시 열어 주세요.")
    st.stop()

table = mf.compute_market_table(close, volume)
names = mf.ticker_names()
label = lambda t: f"{names.get(t, t)} ({t})"  # noqa: E731
as_of = close.index.max().date()
st.caption(
    f"기준일 {as_of} (마감된 일봉만 사용) · 시장 {len(table)}개. '자금 이동'은 펀드 유출입이 아니라 가격·거래대금 대리지표이고, "
    "매매 신호가 아닙니다."
)
if missing:
    st.warning("가격을 받지 못한 시장: " + ", ".join(missing))

_SECTIONS = ["📍 한눈에", "🔄 로테이션 맵", "🔗 상관 지도", "🏆 주도주·수익률", "🧪 가설 검증"]
st.session_state.setdefault("market_flow_section", _SECTIONS[0])
section = st.segmented_control("섹션", _SECTIONS, key="market_flow_section", label_visibility="collapsed")
if section is None:
    section = st.session_state.get("market_flow_section") or _SECTIONS[0]
st.divider()

_COLS = {
    "name": "시장", "ticker": "티커", "quadrant": "4분면", "rs_score": "강도(0~100)", "return_1m": "1개월(%)",
    "return_3m": "3개월(%)", "return_12m": "12개월(%)", "rel_20d": "20일 초과수익(%p)",
    "dollar_vol_change": "거래대금 변화(%)", "flow_score": "자금 이동 점수",
}


def _show_table(df: pd.DataFrame) -> None:
    out = df[list(_COLS)].rename(columns=_COLS)
    st.dataframe(
        out.style.format({c: "{:.1f}" for c in out.columns if c not in ("시장", "티커", "4분면")}, na_rep="–"),
        use_container_width=True, hide_index=True,
    )


# ============================================================ 한눈에
if section == _SECTIONS[0]:
    tech = table[table["ticker"].isin(["XLK", "QQQ", "SMH"])]
    if not tech.empty:
        weak_tech = tech[tech["return_1m"] < -3]
        if len(weak_tech):
            st.warning("기술 관련 시장이 최근 1개월 크게 약합니다: " + ", ".join(
                f"{r['name']} {r['return_1m']:+.1f}%" for _, r in weak_tech.iterrows()))
        else:
            st.success("기술 관련 시장은 최근 1개월 큰 약세가 없습니다.")

    left, right = st.columns(2)
    with left:
        st.subheader("강세 상위 8 (강도 점수)")
        _show_table(table.head(8))
    with right:
        st.subheader("약세 하위 8")
        _show_table(table.tail(8).iloc[::-1])

    st.subheader("자금 이동 대리지표 — 들어오는 쪽 / 빠지는 쪽")
    flows = table.sort_values("flow_score", ascending=False)
    l2, r2 = st.columns(2)
    with l2:
        st.markdown("**들어오는 쪽 (초과수익↑·거래대금↑)**")
        _show_table(flows.head(6))
    with r2:
        st.markdown("**빠지는 쪽 (초과수익↓·거래대금↓)**")
        _show_table(flows.tail(6).iloc[::-1])
    st.caption("자금 이동 점수 = 20일 초과수익(vs SPY)의 z점수 + 20일 평균 거래대금이 120일 평균 대비 변한 정도의 z점수. "
               "지수·환율처럼 거래량이 없는 자산은 앞 항만 씁니다.")

    st.subheader("전체 시장 강도")
    chart = table.sort_values("rs_score")
    fig = go.Figure(go.Bar(
        x=chart["rs_score"], y=[label(t) for t in chart["ticker"]], orientation="h",
        marker_color=[_QUADRANT_COLORS.get(q, "#8a8a8a") for q in chart["quadrant"]],
        customdata=np.stack([chart["quadrant"].fillna("–"), chart["return_3m"].round(1)], axis=-1),
        hovertemplate="%{y}<br>강도 %{x:.0f}<br>4분면 %{customdata[0]}<br>3개월 %{customdata[1]}%<extra></extra>",
    ))
    fig.add_vline(x=50, line_dash="dash", line_color=TRADINGVIEW_CHART_GRID)
    st.plotly_chart(_style(fig, max(420, 22 * len(chart))), use_container_width=True, config={"displayModeBar": False})
    st.caption("색 = 로테이션 4분면(초록 주도 · 주황 약화 · 빨강 부진 · 파랑 개선). 강도는 sector_strength 와 같은 IBD 가중 수익률의 순위(0~100)입니다.")

# ============================================================ 로테이션 맵
elif section == _SECTIONS[1]:
    st.subheader("상대강도 로테이션 맵 (RRG 단순판)")
    st.caption(
        "가로 = 자산/SPY 비율이 자기 63일 평균 대비 얼마나 높은가(100 기준), 세로 = 그 비율이 10거래일 전보다 올랐는가(100 기준). "
        "오른쪽 위 주도 → 오른쪽 아래 약화 → 왼쪽 아래 부진 → 왼쪽 위 개선 순으로 시계방향으로 돈다는 것이 이 도표의 읽는 법입니다. "
        "꼬리는 5거래일 간격 8개 점입니다."
    )
    options = [t for t in table["ticker"] if t != mf.BENCHMARK]
    default = [t for t in ["XLK", "SMH", "XLE", "XLV", "XLP", "XLU", "TLT", "GLD", "EWY"] if t in options]
    picked = st.multiselect("표시할 시장", options, default=default, format_func=label)
    tails = mf.rrg_tails(close, picked)
    if not tails:
        st.info("표시할 시장을 골라 주세요.")
    else:
        fig = go.Figure()
        for i, (t, df) in enumerate(tails.items()):
            color = _PALETTE[i % len(_PALETTE)]
            fig.add_trace(go.Scatter(
                x=df["rs_ratio"], y=df["rs_momentum"], mode="lines+markers", name=label(t),
                line=dict(color=color, width=1.5), marker=dict(size=4, color=color), opacity=0.7,
                hoverinfo="skip", showlegend=False,
            ))
            fig.add_trace(go.Scatter(
                x=[df["rs_ratio"].iloc[-1]], y=[df["rs_momentum"].iloc[-1]], mode="markers+text", text=[t],
                textposition="top center", name=label(t), marker=dict(size=11, color=color),
                hovertemplate=f"{label(t)}<br>RS-Ratio %{{x:.1f}}<br>RS-Momentum %{{y:.1f}}<extra></extra>",
            ))
        fig.add_vline(x=100, line_color=TRADINGVIEW_CHART_GRID)
        fig.add_hline(y=100, line_color=TRADINGVIEW_CHART_GRID)
        fig.update_layout(xaxis_title="RS-Ratio (상대강도 수준)", yaxis_title="RS-Momentum (방향)", showlegend=False)
        st.plotly_chart(_style(fig, 560), use_container_width=True, config={"displayModeBar": False})
        st.markdown("**4분면 현황**")
        for q in (mf.QUADRANT_LEADING, mf.QUADRANT_WEAKENING, mf.QUADRANT_LAGGING, mf.QUADRANT_IMPROVING):
            members = table[table["quadrant"] == q]["ticker"].tolist()
            st.markdown(f"- **{q}** ({len(members)}): " + (", ".join(label(t) for t in members) or "없음"))

# ============================================================ 상관 지도
elif section == _SECTIONS[2]:
    st.subheader("시장 간 상관")
    c1, c2 = st.columns([1, 2])
    window = c1.selectbox("상관 계산 기간(거래일)", [20, 60, 120, 252], index=1)
    mode = c2.radio("보기", ["현재 상관", "장기(252일) 대비 변화"], horizontal=True)
    cols = [t for t in table["ticker"]]
    if mode == "현재 상관":
        mat = mf.correlation_matrix(close[cols], window)
        zmin, zmax, scale = -1, 1, "RdBu"
    else:
        mat = mf.correlation_shift(close[cols], short=window, long=252)
        zmin, zmax, scale = -0.6, 0.6, "RdBu"
    order = [t for t in cols if t in mat.columns]
    mat = mat.loc[order, order]
    fig = go.Figure(go.Heatmap(
        z=mat.values, x=order, y=order, zmin=zmin, zmax=zmax, colorscale=scale,
        hovertemplate="%{y} · %{x}<br>%{z:.2f}<extra></extra>",
    ))
    fig.update_yaxes(autorange="reversed")
    st.plotly_chart(_style(fig, 760), use_container_width=True, config={"displayModeBar": False})
    st.caption("파랑 = 같이 움직임(+), 빨강 = 반대로 움직임(−). 변화 보기에서 파랑은 요즘 더 같이 움직인다는 뜻입니다. "
               "일간 로그수익률 기준이고, 관측치가 기간의 70% 미만인 시장은 뺍니다.")

    st.subheader(f"최근 {window}일 vs 252일 — 상관이 가장 크게 바뀐 쌍")
    moves = mf.top_correlation_moves(close[cols], short=window, long=252, n=10)
    if not moves.empty:
        moves = moves.assign(a=moves["a"].map(label), b=moves["b"].map(label))
        st.dataframe(
            moves.rename(columns={"a": "시장 A", "b": "시장 B", "corr_short": f"최근 {window}일", "corr_long": "252일", "change": "변화"})
            .style.format({f"최근 {window}일": "{:.2f}", "252일": "{:.2f}", "변화": "{:+.2f}"}),
            use_container_width=True, hide_index=True,
        )

    st.subheader("두 시장의 상관 추이")
    p1, p2 = st.columns(2)
    a = p1.selectbox("시장 A", cols, index=cols.index("XLK") if "XLK" in cols else 0, format_func=label)
    b = p2.selectbox("시장 B", cols, index=cols.index("TLT") if "TLT" in cols else 1, format_func=label)
    if a != b:
        roll = mf.rolling_pair_correlation(close, a, b, window)
        fig = go.Figure(go.Scatter(x=roll.index, y=roll.values, line=dict(color=_PALETTE[0])))
        fig.add_hline(y=0, line_color=TRADINGVIEW_CHART_GRID)
        fig.update_yaxes(range=[-1, 1], title=f"{window}일 롤링 상관")
        st.plotly_chart(_style(fig, 320), use_container_width=True, config={"displayModeBar": False})

# ============================================================ 주도주·수익률
elif section == _SECTIONS[3]:
    st.subheader("시장별 주도주와 수익률")
    tickers = list(table["ticker"])
    default_idx = tickers.index("XLE") if "XLE" in tickers else 0
    market = st.selectbox("시장 선택 (강도 순)", tickers, index=default_idx, format_func=lambda t: f"{label(t)} · 강도 {table.set_index('ticker').loc[t, 'rs_score']:.0f}")
    candidates, source = mf.leader_candidates(market)
    st.caption(f"후보 출처: {source}")
    if candidates:
        histories = _load_histories(tuple(candidates))
        leaders = mf.price_leaders(candidates, histories, top_n=5)
        if leaders.empty:
            st.info("후보 종목의 가격을 받지 못했습니다.")
        else:
            st.markdown("**가격 기준 주도주 (IBD 강도 상위)**")
            show = leaders.rename(columns={
                "ticker": "티커", "rs_score": "후보 내 강도", "return_1m": "1개월(%)", "return_3m": "3개월(%)", "return_12m": "12개월(%)"})
            st.dataframe(show[["티커", "후보 내 강도", "1개월(%)", "3개월(%)", "12개월(%)"]].style.format(
                {c: "{:.1f}" for c in ["후보 내 강도", "1개월(%)", "3개월(%)", "12개월(%)"]}, na_rep="–"),
                use_container_width=True, hide_index=True)
            days = {"1개월": 21, "3개월": 63, "6개월": 126, "12개월": 252}
            span = st.radio("수익률 그래프 기간", list(days), index=1, horizontal=True)
            leader_close = pd.DataFrame({t: histories[t]["Close"] for t in leaders["ticker"] if t in histories and not histories[t].empty})
            combined = pd.concat([close[[market, mf.BENCHMARK]], leader_close], axis=1).sort_index()
            combined = combined.loc[:, ~combined.columns.duplicated()]
            ret = mf.normalized_returns(combined, list(dict.fromkeys([market, mf.BENCHMARK, *leaders["ticker"]])), days[span])
            if not ret.empty:
                fig = go.Figure()
                for i, t in enumerate(ret.columns):
                    is_ref = t in (market, mf.BENCHMARK)
                    fig.add_trace(go.Scatter(
                        x=ret.index, y=ret[t], name=label(t) if is_ref else t, mode="lines",
                        line=dict(width=3 if t == market else 2, dash="dash" if t == mf.BENCHMARK else "solid", color=_PALETTE[i % len(_PALETTE)]),
                    ))
                fig.update_yaxes(title="누적 수익률(%)")
                st.plotly_chart(_style(fig, 460), use_container_width=True, config={"displayModeBar": False})
                st.caption("시작일 0%. 굵은 선 = 선택한 시장, 점선 = SPY. 과거 수익률이며 앞으로를 뜻하지 않습니다.")
        theme = mf.theme_for_etf(market)
        if theme:
            st.markdown("**시가총액 기준 대표주**")
            if st.button("대표주·성장주 계산 (재무 조회, 처음엔 오래 걸림)", key=f"rep_{market}"):
                from core.sector_leaders import compute_leader_and_growth

                with st.spinner("재무 정보를 조회하는 중…"):
                    res = compute_leader_and_growth(theme)
                if res["leader"]:
                    st.write(f"대표주(시총 1위): **{res['leader']['ticker']}** {res['leader']['name']}")
                    if res["growth_stocks"]:
                        st.write("성장주 후보: " + ", ".join(g["ticker"] for g in res["growth_stocks"]))
    else:
        st.info("이 시장은 개별 종목 주도주가 없습니다. 위 '한눈에'·'로테이션 맵'에서 시장 자체의 움직임을 보세요.")

# ============================================================ 가설 검증
else:
    st.subheader("가설: 한 시장이 빠지면 다른 시장이 오르는가?")
    st.caption(
        "선택한 시장이 크게 빠진 날(그날까지의 분포로 본 하위 구간)을 과거에서 모두 찾고, 그 뒤 일정 기간 다른 시장이 SPY 보다 "
        "평소보다 얼마나 더 벌었는지 셉니다. 겹치는 날은 한 번만 세고, 자산 수만큼 검정하므로 보정 후에도 남는지 따로 표시합니다."
    )
    long_close, _, long_missing = _load_long()
    k1, k2, k3, k4 = st.columns(4)
    source_options = [t for t in mf.all_tickers() if t in long_close.columns]
    source = k1.selectbox("빠진 시장", source_options, index=source_options.index("XLK") if "XLK" in source_options else 0, format_func=label)
    trig = k2.selectbox("낙폭 측정(거래일)", [10, 20, 40, 60], index=1)
    hor = k3.selectbox("이후 기간(거래일)", [10, 20, 40, 60], index=1)
    q = k4.selectbox("하위 분위", [0.05, 0.10, 0.20], index=1, format_func=lambda v: f"{int(v*100)}%")
    res = mf.conditional_forward_excess(long_close, source, trigger_window=trig, horizon=hor, quantile=q)
    if res.empty:
        st.info("조건에 맞는 과거 사건이 없거나 이력이 부족합니다.")
    else:
        episodes = res.attrs.get("episode_dates", [])
        n_tests = res.attrs.get("n_tests", len(res))
        raw, adj = int(res["significant_raw"].sum()), int(res["significant_bonferroni"].sum())
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("독립 에피소드", len(episodes))
        m2.metric("검정한 시장 수", n_tests)
        m3.metric("보정 전 유의(p<0.05)", raw, help=f"우연만으로도 약 {0.05 * n_tests:.1f}개는 나올 수 있습니다.")
        m4.metric("보정 후 유의", adj)
        if adj == 0:
            st.warning(f"보정 후에도 유의한 시장이 없습니다. '{label(source)}'가 빠진 뒤 다른 시장이 체계적으로 더 벌었다는 증거는 이 표본에서 나오지 않았습니다.")
        else:
            st.success(f"보정 후에도 유의한 시장 {adj}개. 다만 같은 기간·같은 사건을 본 결과이므로 새 자료(전진 기록)로 다시 확인하기 전에는 근거로 쓰지 마세요.")
        plot = res.dropna(subset=["mean_excess"]).sort_values("mean_excess")
        colors = ["#4caf82" if s else ("#c98500" if r else "#8a8a8a") for s, r in zip(plot["significant_bonferroni"], plot["significant_raw"])]
        fig = go.Figure(go.Bar(
            x=plot["mean_excess"], y=[label(t) for t in plot["ticker"]], orientation="h", marker_color=colors,
            customdata=np.stack([plot["episodes"], plot["t_stat"].round(2), plot["p_value"].round(3), plot["hit_rate"].round(0)], axis=-1),
            hovertemplate="%{y}<br>평균 %{x:+.2f}%p<br>에피소드 %{customdata[0]}<br>t %{customdata[1]} · p %{customdata[2]}<br>이긴 비율 %{customdata[3]}%<extra></extra>",
        ))
        fig.add_vline(x=0, line_color=TRADINGVIEW_CHART_GRID)
        fig.update_xaxes(title=f"{hor}거래일 SPY 대비 초과수익 − 평소 평균 (%p)")
        st.plotly_chart(_style(fig, max(420, 22 * len(plot))), use_container_width=True, config={"displayModeBar": False})
        st.caption("회색 = 유의하지 않음, 주황 = 보정 전에만 유의, 초록 = 보정 후에도 유의. 표본이 작아 구간 추정 오차가 큽니다.")
        if long_missing:
            st.caption("장기 이력에서 빠진 시장: " + ", ".join(long_missing))

        st.markdown("**지금 이 조건에 해당하는가?**")
        src = long_close[source].dropna()
        now_ret = float(src.iloc[-1] / src.iloc[-1 - trig] - 1) * 100
        hist_ret = (src / src.shift(trig) - 1).dropna()
        now_pct = float((hist_ret <= hist_ret.iloc[-1]).mean() * 100)
        st.write(f"{label(source)} 최근 {trig}거래일 수익률 **{now_ret:+.1f}%** — 역사적 분포의 하위 {now_pct:.0f}% 지점.")
