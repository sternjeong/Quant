"""챔피언 성과 페이지 (2026-09-26 추가) — "이 전략을 썼다면 언제 사고 언제 팔아 얼마를 벌었나".

계산은 core/champion_performance.py, 이 파일은 화면만 담당한다. 두 절을 절대 섞지 않는다.
  A. 백테스트(가상·과거): run_champion_backtest 의 비중 시계열을 그대로 풀어 거래 목록·자산곡선을 보여 준다.
  B. 실제 시장 기록(2026-09-19~): ChampionLedgerEntry 원장('추천을 따랐다면')과 paper 계좌(모의투자).

페이지 진입만으로 긴 계산을 시작하지 않는다 — 캐시가 있으면 즉시 표시, 없으면 버튼 + job_manager.
job_manager.ensure()는 쓰지 않는다(매 rerun 호출 시 다른 위젯 클릭을 삼키는 문제, 11_챔피언_전략.py 주석 참고).
"""

import sys
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import html

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import job_manager
from core.champion_performance import (
    DEFAULT_INITIAL_CAPITAL,
    LIVE_MIN_DAYS,
    SLEEVE_CORE,
    SLEEVE_SATELLITE,
    build_live_record,
    cache_params,
    compute_backtest_performance,
    default_start,
    format_pct,
    format_usd,
    load_cached,
    load_latest_cached,
    series_from_json,
    to_dollars,
)
from core.champion_strategy import SATELLITE_WEIGHT
from core.db import init_db
from core.theme import apply_theme
from core.ui_status import render_status_header

init_db()

st.set_page_config(page_title="챔피언 성과", page_icon="📒", layout="wide")
apply_theme()
job_manager.render_active_jobs_sidebar()

# ----------------------------------------------------------------------------
# 차트 공통 — dataviz 규칙: 다크 표면용 범주 팔레트(검증 통과), 얇은 선, 실선 헤어라인 격자,
# 범례 항상 표시(2개 이상), 텍스트는 계열 색이 아닌 잉크색, 손익은 파랑↔빨강 발산 + 부호/범례.
# ----------------------------------------------------------------------------
C_STRATEGY = "#3987e5"  # 슬롯1 파랑
C_SPY = "#d95926"  # 슬롯2 주황
C_6040 = "#199e70"  # 슬롯3 청록
C_CORE = "#c98500"  # 슬롯4 노랑
C_SAT = "#d55181"  # 슬롯5 자홍
C_GAIN = "#3987e5"
C_LOSS = "#e66767"
INK = "#d7d8db"
INK_MUTED = "#898781"
GRID = "#2c2c2a"
AXIS = "#383835"
SURFACE = "#0d0e12"

st.markdown(
    """
    <style>
    .perf-kpis {display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:8px; margin:6px 0 10px;}
    .perf-kpi {background:#15161b; border:1px solid #262830; border-radius:8px; padding:9px 12px;}
    .perf-kpi small {display:block; color:#888b93 !important; font-size:.72rem;}
    .perf-kpi b {display:block; font-size:1.25rem; font-weight:600; line-height:1.35;}
    .perf-kpi span {display:block; color:#888b93 !important; font-size:.72rem;}
    .perf-band {border-radius:8px; padding:8px 12px; margin:4px 0 10px; font-size:.86rem; line-height:1.45;}
    .perf-band.virtual {background:rgba(57,135,229,.10); border:1px solid rgba(57,135,229,.45);}
    .perf-band.live {background:rgba(25,158,112,.10); border:1px solid rgba(25,158,112,.5);}
    .perf-band.warn {background:rgba(245,166,35,.10); border:1px solid rgba(245,166,35,.55);}
    .perf-tag {display:inline-block; font-size:.72rem; font-weight:600; border-radius:4px; padding:1px 6px; margin-right:6px;}
    .perf-tag.virtual {background:#3987e5; color:#0d0e12 !important;}
    .perf-tag.live {background:#199e70; color:#0d0e12 !important;}
    </style>
    """,
    unsafe_allow_html=True,
)


def _kpis(items: list[tuple[str, str, str]]) -> None:
    """(라벨, 값, 보조설명) 카드 격자 — 폰에서는 2열, 넓으면 한 줄."""
    cells = "".join(
        f'<div class="perf-kpi"><small>{html.escape(a)}</small><b>{html.escape(b)}</b>'
        + (f"<span>{html.escape(c)}</span>" if c else "") + "</div>"
        for a, b, c in items
    )
    st.markdown(f'<div class="perf-kpis">{cells}</div>', unsafe_allow_html=True)


def _band(text: str, kind: str) -> None:
    st.markdown(f'<div class="perf-band {kind}">{text}</div>', unsafe_allow_html=True)


def _style(fig: go.Figure, height: int, *, legend: bool = True, y_title: str = "", money: bool = False) -> go.Figure:
    fig.update_layout(
        height=height,
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        font=dict(color=INK, size=12),
        margin=dict(l=8, r=8, t=36 if legend else 12, b=8),
        showlegend=legend,
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0, font=dict(size=11),
                    bgcolor="rgba(0,0,0,0)"),
        hoverlabel=dict(bgcolor="#15161b", bordercolor="#262830", font=dict(color=INK)),
    )
    fig.update_xaxes(gridcolor=GRID, linecolor=AXIS, tickfont=dict(color=INK_MUTED), zeroline=False)
    fig.update_yaxes(gridcolor=GRID, linecolor=AXIS, tickfont=dict(color=INK_MUTED), zeroline=False,
                     title=dict(text=y_title, font=dict(color=INK_MUTED, size=11)),
                     tickprefix="$" if money else None, tickformat=",.0f" if money else None)
    return fig


_PLOT_CONFIG = {"displayModeBar": False, "scrollZoom": False}


def _plot(fig: go.Figure) -> None:
    st.plotly_chart(fig, use_container_width=True, config=_PLOT_CONFIG)


# ----------------------------------------------------------------------------
st.title("📒 챔피언 성과")
render_status_header("champion_performance")
st.caption(
    "챔피언 전략(코어 85% 월간 모멘텀 top4 + 새틀라이트 15% 반기 돌파 top3)을 썼다면 언제 무엇을 사고 팔아 "
    "얼마를 벌었거나 잃었는지를 S&P500(SPY)과 나란히 보여 줍니다."
)
_band(
    "⚠️ <b>A. 백테스트</b>는 과거 데이터에 규칙을 적용한 <b>가상 결과</b>입니다 — 비용은 편도 코어 3bp·새틀라이트 "
    "8bp만 가정(세금·슬리피지 추가 없음), 새틀라이트 후보는 현재 S&P500 명단 기반이라 생존편향이 남아 있고, "
    "미래 수익을 보장하지 않습니다. <b>B. 실제 시장 기록</b>은 실제 주문이 아니라 '추천을 따랐다면'의 계산이며, "
    "paper 계좌 수치는 모의투자입니다.",
    "warn",
)

capital = st.number_input(
    "초기 금액($) — 모든 금액이 이 금액 기준으로 바뀝니다(재계산 없음)",
    min_value=100.0, max_value=100_000_000.0, value=DEFAULT_INITIAL_CAPITAL, step=1_000.0, format="%.0f",
)

# ============================================================================
# A. 백테스트 (가상 · 과거)
# ============================================================================
st.markdown("## A. 백테스트 — 가상 · 과거")
_band('<span class="perf-tag virtual">가상</span>과거 가격에 오늘과 같은 규칙을 적용해 계산한 결과입니다. '
      "실제로 이 기간에 주문한 기록이 아닙니다.", "virtual")

today = date.today()
period_options = {"최근 5년(기본)": default_start(today), "최근 3년": date(today.year - 3, 1, 1).isoformat(),
                  "직접 지정": None}
pc1, pc2 = st.columns([1, 1])
with pc1:
    period_label = st.selectbox("기간", list(period_options), index=0)
with pc2:
    if period_options[period_label] is None:
        custom_start = st.date_input("시작일", value=date(today.year - 5, 1, 1),
                                     min_value=date(2019, 1, 1), max_value=today - timedelta(days=200))
        bt_start = custom_start.isoformat()
    else:
        bt_start = period_options[period_label]
        st.caption(f"시작일 {bt_start} → 종료일 오늘({today.isoformat()})")

cached = load_latest_cached(start=bt_start, satellite_weight=SATELLITE_WEIGHT)
fresh_today = load_cached(cache_params(bt_start, today.isoformat(), SATELLITE_WEIGHT)) is not None

n_half_years = max(1, (today.year - int(bt_start[:4])) * 2)
btn_label = "📊 오늘 데이터로 다시 계산" if cached else "📊 계산 시작"
if st.button(btn_label, disabled=fresh_today, help="이미 오늘 날짜로 계산된 결과가 있으면 비활성화됩니다."):
    job_manager.start(
        "champion_performance", compute_backtest_performance, bt_start, today.isoformat(),
        satellite_weight=SATELLITE_WEIGHT, label="챔피언 성과 백테스트",
    )
if not cached:
    st.caption(
        f"아직 이 기간의 계산 결과가 없습니다. 새틀라이트는 반기마다 point-in-time 스캔이 필요해 약 {n_half_years}회 × "
        "2분 안팎이 걸립니다 — 다른 화면으로 이동해도 계속 진행됩니다."
    )

perf_job = job_manager.render(
    "champion_performance",
    running_label=f"백테스트 계산 중 — 새틀라이트 반기 스캔 {n_half_years}회 안팎이라 수십 분 걸릴 수 있습니다",
)
if perf_job is not None:
    if perf_job.status == "error":
        st.error(f"계산 중 오류가 발생했습니다: {perf_job.error}")
    else:
        cached = perf_job.result
        st.success("계산을 마쳤습니다.")

if cached:
    p = cached["params"]
    s = cached["summary"]
    d = to_dollars(cached, capital)
    dd = s["drawdown"]
    st.caption(
        f"기간 {s['start']} ~ {s['end']} · 계산 시각 {cached.get('computed_at', '?')[:16].replace('T', ' ')} UTC · "
        f"새틀라이트 비중 {p['satellite_weight']:.0%}"
    )

    # --- 한눈 요약 ---
    gap_pp = s["total_return_pct"] - s["spy_total_return_pct"]
    _kpis([
        ("최종 금액(가상)", format_usd(d["final_usd"]), f"{format_usd(capital)}로 시작"),
        ("총 손익", format_usd(d["pnl_usd"], signed=True), format_pct(s["total_return_pct"])),
        ("연율(CAGR)", format_pct(s["cagr_pct"]), f"SPY {format_pct(s['spy_cagr_pct'])}"),
        ("최대낙폭", format_pct(dd["mdd_pct"]), f"{dd['peak_date']} → {dd['trough_date']}"),
        ("SPY 대비", f"{gap_pp:+.1f}%p",
         f"SPY만 샀다면 {format_usd(d['spy_final_usd'])}"),
    ])
    if s.get("sixty_forty_total_return_pct") is not None:
        st.caption(
            f"참고: 같은 기간 60/40(SPY 60%·TLT 40%, 매일 비중 유지, 비용 없음) {format_pct(s['sixty_forty_total_return_pct'])} · "
            f"SPY 최대낙폭 {format_pct(s['spy_drawdown']['mdd_pct'])} · 거래 {s['n_trades']}건"
            f"(마감 {s['n_closed_trades']}건 중 이익 {s['n_winning_closed_trades']}건, 보유 중 {s['n_open_trades']}건)"
        )

    trades = d["trades"]
    curves = d["curves"]

    # --- 자산곡선 ---
    st.markdown("#### 자산 변화: 전략 vs S&P500")
    st.caption("초기 금액을 넣고 규칙대로만 움직였다면 매일 계좌 금액이 어땠을지(가상). 회색 띠 = 전략의 최대낙폭 구간.")
    ec1, ec2 = st.columns([1, 1])
    with ec1:
        show_sleeves = st.toggle("코어·새틀라이트 단독 곡선도 보기", value=False)
    with ec2:
        mark_options = ["(표시 안 함)"] + sorted(trades["ticker"].unique().tolist()) if not trades.empty else ["(표시 안 함)"]
        mark_ticker = st.selectbox("매수·매도 지점 표시할 종목", mark_options, index=0)

    fig = go.Figure()
    series_spec = [("strategy", "챔피언 전략", C_STRATEGY, 2.4)]
    if show_sleeves:
        series_spec += [("core", "코어 단독", C_CORE, 1.4), ("satellite", "새틀라이트 단독", C_SAT, 1.4)]
    series_spec += [("spy", "S&P500(SPY) 매수보유", C_SPY, 1.8), ("sixty_forty", "60/40", C_6040, 1.4)]
    for key, name, color, width in series_spec:
        c = curves.get(key)
        if c is None or c.empty:
            continue
        fig.add_trace(go.Scatter(
            x=c.index, y=c.values, name=name, mode="lines", line=dict(color=color, width=width),
            hovertemplate=f"{name}: $%{{y:,.0f}}<extra></extra>",
        ))
    if dd.get("peak_date") and dd.get("trough_date"):
        fig.add_vrect(x0=dd["peak_date"], x1=dd["trough_date"], fillcolor="rgba(137,135,129,0.16)", line_width=0,
                      layer="below")
    if mark_ticker != "(표시 안 함)" and not trades.empty:
        strat = curves["strategy"]
        tt = trades[trades["ticker"] == mark_ticker]
        buys = pd.to_datetime(tt["buy_date"])
        sells = pd.to_datetime(tt.loc[~tt["is_open"], "sell_date"])
        fig.add_trace(go.Scatter(
            x=buys, y=strat.reindex(buys).values, mode="markers", name=f"{mark_ticker} 매수",
            marker=dict(symbol="triangle-up", size=12, color=INK, line=dict(color=SURFACE, width=2)),
            customdata=tt[["buy_price"]].values,
            hovertemplate=f"{mark_ticker} 매수 @ $%{{customdata[0]:,.2f}}<extra></extra>",
        ))
        if not sells.empty:
            ts = tt[~tt["is_open"]]
            fig.add_trace(go.Scatter(
                x=sells, y=strat.reindex(sells).values, mode="markers", name=f"{mark_ticker} 매도",
                marker=dict(symbol="triangle-down", size=12, color=INK_MUTED, line=dict(color=SURFACE, width=2)),
                customdata=ts[["sell_price", "net_return_pct"]].values,
                hovertemplate=f"{mark_ticker} 매도 @ $%{{customdata[0]:,.2f}} (%{{customdata[1]:+.1f}}%)<extra></extra>",
            ))
    _style(fig, 380, money=True)
    fig.update_layout(hovermode="x unified")
    _plot(fig)

    # --- 거래 타임라인 ---
    st.markdown("#### 언제 사고 언제 팔았나")
    st.caption(
        "막대 하나 = 한 번의 보유(매수일 종가 → 매도일 종가). 파랑 = 비용 반영 수익, 빨강 = 손실. "
        "막대를 누르면 가격·수익률·SPY 대비가 나옵니다."
    )
    tl_sleeve = st.radio("슬리브", ["전체", SLEEVE_CORE, SLEEVE_SATELLITE], horizontal=True, key="tl_sleeve")
    tl = trades if tl_sleeve == "전체" else trades[trades["sleeve"] == tl_sleeve]
    if tl.empty:
        st.caption("이 슬리브에는 거래가 없습니다.")
    else:
        order = (tl.groupby("ticker")["buy_date"].min().sort_values(ascending=False).index.tolist())
        tfig = go.Figure()
        for label, mask, color in (("수익(+)", tl["net_return_pct"] >= 0, C_GAIN),
                                   ("손실(−)", tl["net_return_pct"] < 0, C_LOSS)):
            part = tl[mask]
            if part.empty:
                continue
            start_ts = pd.to_datetime(part["buy_date"])
            end_ts = pd.to_datetime(part["sell_date"])
            dur_ms = ((end_ts - start_ts).dt.total_seconds() * 1000).clip(lower=86_400_000 * 3)
            tfig.add_trace(go.Bar(
                y=part["ticker"], x=dur_ms, base=start_ts, orientation="h", name=label,
                marker=dict(color=color, line=dict(color=SURFACE, width=1)),
                customdata=part[["sleeve", "buy_date", "buy_price", "sell_date", "sell_price", "net_return_pct",
                                 "spy_return_pct", "pnl_usd", "is_open"]].values,
                hovertemplate=(
                    "<b>%{y}</b> (%{customdata[0]})<br>매수 %{customdata[1]} @ $%{customdata[2]:,.2f}<br>"
                    "매도 %{customdata[3]} @ $%{customdata[4]:,.2f}<br>수익률 %{customdata[5]:+.1f}% · "
                    "SPY %{customdata[6]:+.1f}%<br>손익 $%{customdata[7]:,.0f}<extra></extra>"
                ),
            ))
        n_rows = len(order)
        _style(tfig, max(220, 26 * n_rows + 80))
        tfig.update_layout(barmode="overlay", bargap=0.35)
        tfig.update_yaxes(categoryorder="array", categoryarray=order, tickfont=dict(size=11, color=INK))
        tfig.update_xaxes(type="date")
        _plot(tfig)

    # --- 거래 목록 ---
    st.markdown("#### 거래 목록")
    st.caption("보유 구간 단위로 묶은 표입니다. 수익률은 매수·매도 편도 비용을 뺀 값, 손익($)은 전략 계좌 기준 이 거래의 몫입니다.")
    if trades.empty:
        st.caption("거래가 없습니다.")
    else:
        trades = trades.copy()
        trades["year"] = trades["buy_date"].str[:4]
        f1, f2 = st.columns(2)
        with f1:
            sel_sleeve = st.multiselect("슬리브", [SLEEVE_CORE, SLEEVE_SATELLITE], default=[], placeholder="전체")
            sel_year = st.multiselect("매수 연도", sorted(trades["year"].unique()), default=[], placeholder="전체")
        with f2:
            sel_ticker = st.multiselect("티커", sorted(trades["ticker"].unique()), default=[], placeholder="전체")
            sort_by = st.selectbox("정렬", ["최근 매수순", "수익률 높은순", "수익률 낮은순", "손익($) 큰순", "손익($) 작은순"])
        view = trades
        if sel_sleeve:
            view = view[view["sleeve"].isin(sel_sleeve)]
        if sel_year:
            view = view[view["year"].isin(sel_year)]
        if sel_ticker:
            view = view[view["ticker"].isin(sel_ticker)]
        sort_map = {"최근 매수순": ("buy_date", False), "수익률 높은순": ("net_return_pct", False),
                    "수익률 낮은순": ("net_return_pct", True), "손익($) 큰순": ("pnl_usd", False),
                    "손익($) 작은순": ("pnl_usd", True)}
        col, asc = sort_map[sort_by]
        view = view.sort_values(col, ascending=asc)
        shown = pd.DataFrame({
            "티커": view["ticker"], "슬리브": view["sleeve"],
            "매수일": view["buy_date"], "매도일": view["sell_date"].where(~view["is_open"], "보유 중"),
            "보유일": view["holding_days"], "매수가": view["buy_price"], "매도가": view["sell_price"],
            "수익률%": view["net_return_pct"], "SPY%": view["spy_return_pct"],
            "SPY 대비%p": view["excess_vs_spy_pct"], "손익$": view["pnl_usd"],
            "비중%": view["avg_portfolio_weight_pct"], "조정": view["n_adjustments"],
        })
        st.caption(f"{len(shown)}건 · 손익 합 {format_usd(float(view['pnl_usd'].sum()), signed=True)}")
        st.dataframe(
            shown, hide_index=True, use_container_width=True, height=min(420, 38 + 35 * len(shown)),
            column_config={
                "티커": st.column_config.TextColumn(pinned=True, width="small"),
                "매수가": st.column_config.NumberColumn(format="$%.2f"),
                "매도가": st.column_config.NumberColumn(format="$%.2f"),
                "수익률%": st.column_config.NumberColumn(format="%+.1f"),
                "SPY%": st.column_config.NumberColumn(format="%+.1f"),
                "SPY 대비%p": st.column_config.NumberColumn(format="%+.1f"),
                "손익$": st.column_config.NumberColumn(format="$%,.0f"),
                "비중%": st.column_config.NumberColumn(format="%.1f", help="전체 계좌 대비 평균 비중"),
                "조정": st.column_config.NumberColumn(help="보유 중 비중을 늘리거나 줄인 횟수(시장필터 등)"),
            },
        )
        with st.expander("매수·매도 수량 기록(비중 조정 포함)"):
            ev = d["events"]
            if sel_ticker:
                ev = ev[ev["ticker"].isin(sel_ticker)]
            if sel_sleeve:
                ev = ev[ev["sleeve"].isin(sel_sleeve)]
            st.caption("신호일 종가에 체결했다고 가정한 주문 단위 기록입니다. 금액·수량은 그 시점 가상 계좌 기준입니다.")
            st.dataframe(
                pd.DataFrame({
                    "날짜": ev["date"], "티커": ev["ticker"], "슬리브": ev["sleeve"], "구분": ev["action"],
                    "가격": ev["price"], "비중 전%": ev["weight_before_pct"], "비중 후%": ev["weight_after_pct"],
                    "금액$": ev["notional_usd"], "수량": ev["shares"],
                }).sort_values("날짜", ascending=False),
                hide_index=True, use_container_width=True, height=320,
                column_config={
                    "가격": st.column_config.NumberColumn(format="$%.2f"),
                    "금액$": st.column_config.NumberColumn(format="$%,.0f"),
                    "수량": st.column_config.NumberColumn(format="%.2f"),
                    "비중 전%": st.column_config.NumberColumn(format="%.1f"),
                    "비중 후%": st.column_config.NumberColumn(format="%.1f"),
                },
            )

    # --- 티커별 기여 ---
    st.markdown("#### 종목별로 얼마를 벌고 잃었나")
    st.caption("기간 전체에서 각 종목이 계좌에 더하거나 뺀 금액(비용 반영, 가상). 막대 합 = 총 손익.")
    contrib = d["contrib"]
    if not contrib.empty:
        by_t = contrib.groupby("ticker", as_index=False).agg(pnl_usd=("pnl_usd", "sum"), n_trades=("n_trades", "sum"),
                                                             sleeve=("sleeve", "first"))
        by_t = by_t.sort_values("pnl_usd")
        top_n = st.radio("표시", ["상위 8·하위 5", "전체"], horizontal=True, key="contrib_n")
        if top_n != "전체" and len(by_t) > 13:
            by_t = pd.concat([by_t.head(5), by_t.tail(8)])
        cfig = go.Figure(go.Bar(
            y=by_t["ticker"], x=by_t["pnl_usd"], orientation="h",
            marker=dict(color=[C_GAIN if v >= 0 else C_LOSS for v in by_t["pnl_usd"]],
                        line=dict(color=SURFACE, width=1)),
            text=[format_usd(v, signed=True) for v in by_t["pnl_usd"]], textposition="outside",
            textfont=dict(color=INK, size=11), cliponaxis=False,
            customdata=by_t[["sleeve", "n_trades"]].values,
            hovertemplate="<b>%{y}</b> (%{customdata[0]}) · 거래 %{customdata[1]}건<br>손익 $%{x:,.0f}<extra></extra>",
        ))
        _style(cfig, max(220, 26 * len(by_t) + 40), legend=False, money=True)
        cfig.update_layout(margin=dict(l=8, r=56, t=12, b=8))
        cfig.update_yaxes(tickfont=dict(size=11, color=INK))
        _plot(cfig)

    # --- 연도별 ---
    st.markdown("#### 연도별 수익: 전략 vs SPY")
    st.caption("각 해의 수익률(가상). * 는 기간이 한 해 전체가 아닌 부분 연도입니다.")
    yearly = d["yearly"]
    if not yearly.empty:
        ylab = [f"{y}{'*' if pt else ''}" for y, pt in zip(yearly["year"], yearly["partial"])]
        yfig = go.Figure()
        yfig.add_trace(go.Bar(x=ylab, y=yearly["strategy_pct"], name="챔피언 전략", marker_color=C_STRATEGY,
                              marker_line=dict(color=SURFACE, width=2),
                              hovertemplate="%{x} 전략 %{y:+.1f}%<extra></extra>"))
        yfig.add_trace(go.Bar(x=ylab, y=yearly["spy_pct"], name="S&P500(SPY)", marker_color=C_SPY,
                              marker_line=dict(color=SURFACE, width=2),
                              hovertemplate="%{x} SPY %{y:+.1f}%<extra></extra>"))
        _style(yfig, 300, y_title="수익률 %")
        yfig.update_layout(barmode="group", bargap=0.3, bargroupgap=0.08)
        yfig.update_yaxes(ticksuffix="%", zeroline=True, zerolinecolor=AXIS)
        _plot(yfig)
        st.dataframe(
            pd.DataFrame({
                "연도": ylab, "전략%": yearly["strategy_pct"], "SPY%": yearly["spy_pct"],
                "차이%p": yearly.get("diff_vs_spy_pct"), "60/40%": yearly.get("sixty_forty_pct"),
                "전략 손익$": yearly["strategy_pnl_usd"],
            }),
            hide_index=True, use_container_width=True,
            column_config={
                "전략%": st.column_config.NumberColumn(format="%+.1f"),
                "SPY%": st.column_config.NumberColumn(format="%+.1f"),
                "차이%p": st.column_config.NumberColumn(format="%+.1f"),
                "60/40%": st.column_config.NumberColumn(format="%+.1f"),
                "전략 손익$": st.column_config.NumberColumn(format="$%,.0f"),
            },
        )

    rec = cached.get("reconciliation") or {}
    st.caption(
        ("✅ 검산: 이 화면의 일별 수익률 분해가 기존 챔피언 백테스트와 일치하고, 거래 손익 합이 자산곡선 총손익과 같습니다."
         if rec.get("ok") else "⚠️ 검산 불일치: 거래 손익 합과 백테스트 자산곡선이 어긋납니다 — 결과를 믿기 전에 확인이 필요합니다.")
        + " 새틀라이트 반기 선정 기록은 아래에 있습니다."
    )
    if cached.get("satellite_rebal_log"):
        with st.expander("새틀라이트 반기 선정 기록"):
            st.dataframe(pd.DataFrame([
                {"리밸런싱일": r["date"], "고른 종목": ", ".join(r["picks"]) or "(없음)",
                 "후보 수": r.get("pool_size"), "돌파 활성": r.get("n_active_trend")}
                for r in cached["satellite_rebal_log"]
            ]), hide_index=True, use_container_width=True)

st.page_link("pages/11_챔피언_전략.py", label="🏆 챔피언 전략(오늘의 추천·백테스트 설정)으로", width="stretch")

# ============================================================================
# B. 실제 시장 기록 (2026-09-19~) — 백테스트와 섞지 않는다
# ============================================================================
st.divider()
st.markdown("## B. 실제 시장 기록(2026-09-19~)")
_band('<span class="perf-tag live">실제 시장</span>매일 밤 그날의 추천 비중을 기록하고, 다음 날 실제 종가로 '
      "'따랐다면' 수익을 계산한 원장입니다. 주문 기록이 아니며, 위 백테스트와 다른 기간·다른 계산입니다.", "live")


@st.cache_data(ttl=1800, show_spinner=False)
def _live_record() -> dict:
    return build_live_record()


try:
    live = _live_record()
except Exception as exc:  # noqa: BLE001
    live = {"available": False, "enough": False, "reason": f"원장을 읽지 못했습니다({type(exc).__name__}).",
            "paper": {"available": False}}

if not live.get("available"):
    st.info(f"기록 없음 — {live.get('reason', '')} 판단할 수 있는 실제 기록이 아직 없습니다.")
else:
    n = live["n_entries"]
    if not live.get("enough"):
        st.warning(f"아직 기간이 짧아 판단 불가 — 기록 {n}일(비교에 최소 {LIVE_MIN_DAYS}일 필요). 아래 숫자는 참고용입니다.")
    lg = live["ledger_total_return_pct"]
    _kpis([
        ("따랐다면(원장)", format_pct(lg, 2), f"{live['start_date']} ~ {live['end_date']} · {n}일"),
        ("같은 기간 SPY", format_pct(live.get("spy_total_return_pct"), 2), ""),
        ("같은 기간 60/40", format_pct(live.get("sixty_forty_total_return_pct"), 2), "SPY/TLT 매수보유"),
        (f"{format_usd(capital)}였다면", format_usd(capital * (1 + lg / 100)), "원장 수익률 적용(가상)"),
    ])
    lfig = go.Figure()
    for key, name, color, width in (("ledger_curve", "따랐다면(원장)", C_STRATEGY, 2.4),
                                    ("spy_curve", "S&P500(SPY)", C_SPY, 1.8),
                                    ("sixty_forty_curve", "60/40", C_6040, 1.4)):
        sr = series_from_json(live.get(key))
        if sr.empty:
            continue
        lfig.add_trace(go.Scatter(x=sr.index, y=(sr - 1) * 100, name=name, mode="lines+markers",
                                  line=dict(color=color, width=width), marker=dict(size=6),
                                  hovertemplate=f"{name}: %{{y:+.2f}}%<extra></extra>"))
    st.caption("원장 시작일 대비 누적 수익률(%). 실제 가격으로 계산했지만 실제 주문은 아닙니다.")
    _style(lfig, 300, y_title="누적 %")
    lfig.update_layout(hovermode="x unified")
    lfig.update_yaxes(ticksuffix="%", zeroline=True, zerolinecolor=AXIS)
    _plot(lfig)

    cw = live.get("current_weights") or {}
    rows = [{"슬리브": SLEEVE_CORE, "티커": t, "비중%": round(w * 100, 2)} for t, w in (cw.get("core") or {}).items() if w]
    rows += [{"슬리브": SLEEVE_SATELLITE, "티커": t, "비중%": round(w * 100, 2)} for t, w in (cw.get("satellite") or {}).items() if w]
    if rows:
        st.caption(f"{live['end_date']} 기록 기준, 다음 거래일부터 따를 비중")
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    if live.get("weight_changes"):
        with st.expander("원장 비중 변화(편입·비중 변경·제외)"):
            st.dataframe(pd.DataFrame(live["weight_changes"]).rename(columns={
                "date": "날짜", "ticker": "티커", "sleeve": "슬리브", "action": "구분",
                "weight_before_pct": "비중 전%", "weight_after_pct": "비중 후%"}),
                hide_index=True, use_container_width=True)

paper = live.get("paper") or {}
st.markdown("#### paper 계좌(모의투자)")
if not paper.get("available"):
    st.caption("paper 계좌 스냅샷이 없습니다(Alpaca paper 키가 없거나 동기화 잡이 아직 기록하지 않음). 원장 수치만 있습니다.")
else:
    pc = series_from_json(paper.get("curve"))
    _kpis([
        ("paper 계좌 자산(모의)", format_usd(paper.get("last_equity")), f"{paper['last_date']} 스냅샷"),
        ("첫 스냅샷 대비", format_pct((float(pc.iloc[-1]) - 1) * 100 if not pc.empty else None, 2),
         f"{paper['first_date']}부터 · {paper['n_snapshots']}건"),
    ])
    st.caption("모의투자 계좌가 브로커에 보고한 실제 자산입니다. 입출금은 반영하지 않으며, 원장과의 차이는 체결·시차·추종 여부 때문일 수 있습니다.")
