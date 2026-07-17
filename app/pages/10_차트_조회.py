"""차트 조회 페이지 (TradingView 스타일).

전략/백테스트와 무관하게, 티커를 입력하면 봉 주기(분/시간/일/주/월)를 골라가며
캔들차트 + 거래량 + 이동평균/볼린저밴드/일목균형표/RSI/MACD 오버레이를 바로 볼 수 있다.
레이아웃은 TradingView처럼 차트를 상단에 크게 두고, 지표 설정은 접이식으로, 빠른 기간
선택은 차트 바로 아래에 둔다.
"""

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
from plotly.subplots import make_subplots

from core.db import init_db
from core.indicators import compute_bollinger, compute_ichimoku, compute_ma_cross, compute_macd, compute_rsi
from core import job_manager
from core.market_data import INTERVAL_MAX_LOOKBACK_DAYS, clamp_start_for_interval, get_price_history, resample_ohlcv
from core.theme import TRADINGVIEW_CHART_CONFIG, apply_theme, inject_chart_interactions, style_chart_like_tradingview
from core.watchlist import add_to_watchlist, list_watchlist, remove_from_watchlist

init_db()

st.set_page_config(page_title="차트 조회", page_icon="🕯️", layout="wide")
apply_theme()
job_manager.render_active_jobs_sidebar()
st.title("🕯️ 차트 조회")
st.caption("티커를 입력하고 봉 주기를 선택하면 TradingView 스타일 캔들차트를 바로 볼 수 있습니다 (백테스트 불필요).")

INTERVAL_LABELS = {
    "1m": "1분봉",
    "2m": "2분봉",
    "5m": "5분봉",
    "15m": "15분봉",
    "30m": "30분봉",
    "60m": "1시간봉",
    "90m": "90분봉",
    "1d": "일봉",
    "5d": "5일봉",
    "1wk": "주봉",
    "1mo": "월봉",
    "3mo": "분기봉",
}
DAILY_PLUS_INTERVALS = {"1d", "5d", "1wk", "1mo", "3mo"}

# TradingView 툴바처럼 짧은 코드로 표기(1m/1H/D/W ...)하고, 전체 이름은 버튼 hover 툴팁(help)으로만
# 보여준다. 분/시간/일 이상을 그룹으로 나눠 사이에 구분선을 넣어 한눈에 위계가 보이게 한다.
INTERVAL_SHORT_LABELS = {
    "1m": "1m", "2m": "2m", "5m": "5m", "15m": "15m", "30m": "30m",
    "60m": "1H", "90m": "90m",
    "1d": "D", "5d": "5D", "1wk": "W", "1mo": "M", "3mo": "3M",
}
INTERVAL_GROUPS = [
    ["1m", "2m", "5m", "15m", "30m"],
    ["60m", "90m"],
    ["1d", "5d", "1wk", "1mo", "3mo"],
]

# 주봉/월봉/분기봉은 yfinance가 별도 피드로 제공하는데, 그 피드가 일봉보다 최신 데이터 반영이 늦어
# "일봉엔 있는 오늘 데이터가 주봉/월봉엔 없는" 동기화 문제가 생긴다. 그래서 이 셋은 yfinance에 직접
# 요청하지 않고, 항상 받아오는 일봉을 여기서 리샘플링해서 만든다(같은 일봉이 원천이라 항상 동기화됨).
RESAMPLE_RULE_FOR_INTERVAL = {"1wk": "W-FRI", "1mo": "ME", "3mo": "QE"}

# TradingView 하단 빠른 기간 버튼 그대로(1일/5일/1개월/3개월/6개월/YTD/1년/전체).
# 분봉/시간봉으로 못 채울 만큼 긴 기간을 고르면 clamp_start_for_interval()이 알아서 당겨준다.
RANGE_PRESETS = {
    "1일": 1, "5일": 5, "1개월": 30, "3개월": 90, "6개월": 180,
    "YTD": "ytd", "1년": 365, "전체": None,
}


@st.cache_data(ttl=3600)
def _cached_price_history(ticker: str, start: str | None, end: str | None, interval: str) -> pd.DataFrame:
    resample_rule = RESAMPLE_RULE_FOR_INTERVAL.get(interval)
    if resample_rule:
        daily = get_price_history(ticker, start=start, end=end, interval="1d")
        return resample_ohlcv(daily, resample_rule) if not daily.empty else daily
    return get_price_history(ticker, start=start, end=end, interval=interval)


def _default_days_for(interval: str) -> int:
    """interval 변경 시 프리셋을 못 고른 경우 쓸 기본 조회 일수."""
    max_days = INTERVAL_MAX_LOOKBACK_DAYS.get(interval)
    if max_days is None:
        return 365
    return max_days


st.session_state.setdefault("chart_ticker", "AAPL")

watchlist_items = list_watchlist()
watchlist_by_ticker = {item["ticker"]: item for item in watchlist_items}

st.markdown("#### ⭐ 관심종목")
if watchlist_items:
    st.caption("클릭하면 바로 그 티커로 조회합니다.")
    tickers_only = [item["ticker"] for item in watchlist_items]
    cols_per_row = 8
    for row_start in range(0, len(tickers_only), cols_per_row):
        row_tickers = tickers_only[row_start : row_start + cols_per_row]
        row_cols = st.columns(cols_per_row)
        for t, col in zip(row_tickers, row_cols):
            if col.button(t, key=f"wl_pick_{t}", use_container_width=True):
                st.session_state["chart_ticker"] = t
                st.rerun()
else:
    st.caption("등록된 관심종목이 없습니다. 아래에서 티커를 조회한 뒤 '관심종목 추가'로 등록해보세요.")

col_ticker, col_wl_toggle = st.columns([3, 1])
with col_ticker:
    ticker = st.text_input("종목 티커", key="chart_ticker").strip().upper()
with col_wl_toggle:
    st.write("")
    st.write("")
    if ticker and ticker in watchlist_by_ticker:
        if st.button("★ 관심종목 해제", key="wl_remove", use_container_width=True):
            remove_from_watchlist(watchlist_by_ticker[ticker]["id"])
            st.rerun()
    elif ticker:
        if st.button("☆ 관심종목 추가", key="wl_add", use_container_width=True):
            try:
                add_to_watchlist(ticker)
                st.rerun()
            except ValueError as e:
                st.warning(str(e))

st.session_state.setdefault("chart_interval", "1d")

st.markdown(
    """
    <style>
    /* TradingView 툴바 스타일 봉 주기 세그먼트 버튼: 촘촘하고 작은 pill 형태 */
    div[class*="st-key-interval_toolbar"] div[data-testid="stHorizontalBlock"] {
        gap: 0.15rem;
    }
    div[class*="st-key-interval_toolbar"] button {
        min-height: 1.9rem;
        height: 1.9rem;
        padding: 0 0.1rem;
        font-size: 0.8rem;
        border-radius: 6px;
    }
    div[class*="st-key-interval_toolbar"] button[kind="secondary"] {
        background-color: transparent;
        border-color: transparent;
        color: #b2b5be;
    }
    div[class*="st-key-interval_toolbar"] button[kind="secondary"]:hover {
        background-color: rgba(255,255,255,0.06);
        color: #d1d4dc;
    }
    div[class*="st-key-interval_toolbar"] button[kind="primary"] {
        background-color: #2962ff;
        border-color: #2962ff;
        color: #ffffff;
        font-weight: 600;
    }
    div[class*="st-key-interval_group_sep"] {
        border-left: 1px solid #363a45;
        height: 1.9rem;
        margin-top: 0.15rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

with st.container(key="interval_toolbar"):
    # 그룹(분/시간/일 이상) 사이에 얇은 구분선 컬럼을 끼워 넣어 세그먼트 위계를 시각적으로 표현.
    n_seps = len(INTERVAL_GROUPS) - 1
    widths = []
    for gi, group in enumerate(INTERVAL_GROUPS):
        widths.extend([3] * len(group))
        if gi < n_seps:
            widths.append(1)
    toolbar_cols = st.columns(widths)

    col_idx = 0
    for gi, group in enumerate(INTERVAL_GROUPS):
        for code in group:
            col = toolbar_cols[col_idx]
            col_idx += 1
            is_active = st.session_state["chart_interval"] == code
            if col.button(
                INTERVAL_SHORT_LABELS[code], key=f"interval_btn_{code}",
                use_container_width=True, help=INTERVAL_LABELS[code],
                type="primary" if is_active else "secondary",
            ):
                st.session_state["chart_interval"] = code
                st.rerun()
        if gi < n_seps:
            with toolbar_cols[col_idx]:
                st.markdown(
                    '<div class="st-key-interval_group_sep-marker"></div>',
                    unsafe_allow_html=True,
                )
            col_idx += 1

interval = st.session_state["chart_interval"]

is_intraday = interval not in DAILY_PLUS_INTERVALS
max_lookback = INTERVAL_MAX_LOOKBACK_DAYS.get(interval)

st.session_state.setdefault("chart_start_date", date.today() - timedelta(days=_default_days_for(interval)))
st.session_state.setdefault("chart_end_date", date.today())
start_date = st.session_state["chart_start_date"]
end_date = st.session_state["chart_end_date"]

with st.expander("⚙️ 지표 설정 (TradingView 스타일 on/off)"):
    col_ma, col_bb, col_ichi, col_rsi, col_macd = st.columns(5)

    with col_ma:
        ma_enabled = st.checkbox("이동평균(MA)", value=True, key="chart_ma_enabled")
        if ma_enabled:
            ma_short = st.number_input("단기", min_value=2, max_value=200, value=20, key="chart_ma_short")
            ma_long = st.number_input("장기", min_value=3, max_value=400, value=60, key="chart_ma_long")
            ma_type = st.radio("종류", ["sma", "ema"], key="chart_ma_type", horizontal=True)

    with col_bb:
        bb_enabled = st.checkbox("볼린저밴드", value=False, key="chart_bb_enabled")
        if bb_enabled:
            bb_period = st.number_input("기간", min_value=2, max_value=200, value=20, key="chart_bb_period")
            bb_std = st.number_input("표준편차", min_value=0.5, max_value=5.0, value=2.0, step=0.5, key="chart_bb_std")

    with col_ichi:
        ichi_enabled = st.checkbox("일목균형표", value=False, key="chart_ichi_enabled")
        if ichi_enabled:
            ichi_tenkan = st.number_input("전환선", min_value=2, max_value=100, value=9, key="chart_ichi_tenkan")
            ichi_kijun = st.number_input("기준선", min_value=2, max_value=200, value=26, key="chart_ichi_kijun")
            ichi_span_b = st.number_input("선행스팬B", min_value=2, max_value=300, value=52, key="chart_ichi_span_b")

    with col_rsi:
        rsi_enabled = st.checkbox("RSI", value=False, key="chart_rsi_enabled")
        if rsi_enabled:
            rsi_period = st.number_input("기간", min_value=2, max_value=100, value=14, key="chart_rsi_period")

    with col_macd:
        macd_enabled = st.checkbox("MACD", value=False, key="chart_macd_enabled")
        if macd_enabled:
            macd_fast = st.number_input("단기", min_value=2, max_value=100, value=12, key="chart_macd_fast")
            macd_slow = st.number_input("장기", min_value=3, max_value=200, value=26, key="chart_macd_slow")
            macd_signal = st.number_input("시그널", min_value=2, max_value=100, value=9, key="chart_macd_signal")

clamped_start, was_clamped = clamp_start_for_interval(interval, start_date, end_date)
if was_clamped:
    st.warning(
        f"'{INTERVAL_LABELS[interval]}'는 최근 {max_lookback}일까지만 조회할 수 있어 "
        f"시작일을 {clamped_start.isoformat()}로 자동 조정했습니다."
    )


def render_chart(df: pd.DataFrame, ticker: str) -> go.Figure:
    rows = ["price", "volume"]
    if rsi_enabled:
        rows.append("rsi")
    if macd_enabled:
        rows.append("macd")

    row_heights_map = {
        2: [0.75, 0.25],
        3: [0.6, 0.2, 0.2],
        4: [0.5, 0.15, 0.175, 0.175],
    }
    row_heights = row_heights_map[len(rows)]
    price_row = rows.index("price") + 1
    volume_row = rows.index("volume") + 1

    fig = make_subplots(
        rows=len(rows), cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=row_heights
    )

    date_fmt = "%Y-%m-%d %H:%M" if is_intraday else "%Y-%m-%d"
    # 실제 봉이 있는 시점만 순서대로 늘어놓는 카테고리 축용 라벨 (날짜형 축 대신 사용) — 주말/공휴일/
    # (분봉·시간봉의) 장 마감~다음 개장 사이처럼 거래가 없어 데이터 자체가 없는 구간은 애초에 라벨이
    # 존재하지 않으므로 축에 빈 공백이 생기지 않는다. x가 이미 이 포맷 그대로의 문자열이라
    # hovertemplate도 별도 날짜 포맷 지시자 없이 그대로("%{x}") 쓴다.
    x_labels = df.index.strftime(date_fmt)
    fig.add_trace(
        go.Candlestick(
            x=x_labels, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
            name="가격", increasing_line_color="#26a69a", decreasing_line_color="#ef5350",
            hovertemplate=(
                "%{x}<br>"
                "시가: %{open:,.2f}<br>고가: %{high:,.2f}<br>저가: %{low:,.2f}<br>종가: %{close:,.2f}"
                "<extra></extra>"
            ),
        ),
        row=price_row, col=1,
    )

    if ma_enabled:
        cross = compute_ma_cross(df, int(ma_short), int(ma_long), ma_type)
        fig.add_trace(
            go.Scatter(x=x_labels, y=cross["short_ma"], name=f"MA{int(ma_short)}",
                        line=dict(width=1.4, color="#5B8DEF")),
            row=price_row, col=1,
        )
        fig.add_trace(
            go.Scatter(x=x_labels, y=cross["long_ma"], name=f"MA{int(ma_long)}",
                        line=dict(width=1.4, color="#F2994A")),
            row=price_row, col=1,
        )

    if bb_enabled:
        bb = compute_bollinger(df, int(bb_period), float(bb_std))
        fig.add_trace(
            go.Scatter(x=x_labels, y=bb["upper"], name="볼린저 상단",
                        line=dict(width=1, color="#9B51E0", dash="dot")),
            row=price_row, col=1,
        )
        fig.add_trace(
            go.Scatter(x=x_labels, y=bb["lower"], name="볼린저 하단",
                        line=dict(width=1, color="#9B51E0", dash="dot")),
            row=price_row, col=1,
        )

    if ichi_enabled:
        ichi = compute_ichimoku(
            df, tenkan_len=int(ichi_tenkan), kijun_len=int(ichi_kijun),
            span_b_len=int(ichi_span_b), displacement=int(ichi_kijun),
        )
        fig.add_trace(
            go.Scatter(x=x_labels, y=ichi["cloud_bottom"], line=dict(width=0), showlegend=False, hoverinfo="skip"),
            row=price_row, col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=x_labels, y=ichi["cloud_top"], name="구름대", line=dict(width=0),
                fill="tonexty", fillcolor="rgba(91,141,239,0.18)", hoverinfo="skip",
            ),
            row=price_row, col=1,
        )
        fig.add_trace(
            go.Scatter(x=x_labels, y=ichi["tenkan"], name="전환선", line=dict(width=1.2, color="#F2994A")),
            row=price_row, col=1,
        )
        fig.add_trace(
            go.Scatter(x=x_labels, y=ichi["kijun"], name="기준선", line=dict(width=1.2, color="#9B51E0")),
            row=price_row, col=1,
        )

    volume_colors = ["#26a69a" if c >= o else "#ef5350" for o, c in zip(df["Open"], df["Close"])]
    fig.add_trace(
        go.Bar(x=x_labels, y=df["Volume"], name="거래량", marker_color=volume_colors, showlegend=False),
        row=volume_row, col=1,
    )

    if rsi_enabled:
        rsi_row = rows.index("rsi") + 1
        rsi = compute_rsi(df, int(rsi_period))
        fig.add_trace(
            go.Scatter(x=x_labels, y=rsi, name=f"RSI{int(rsi_period)}", line=dict(width=1.5, color="#5B8DEF")),
            row=rsi_row, col=1,
        )
        fig.add_hline(y=70, line=dict(color="#ef5350", dash="dash", width=1), row=rsi_row, col=1)
        fig.add_hline(y=30, line=dict(color="#26a69a", dash="dash", width=1), row=rsi_row, col=1)

    if macd_enabled:
        macd_row = rows.index("macd") + 1
        macd_df = compute_macd(df, int(macd_fast), int(macd_slow), int(macd_signal))
        fig.add_trace(
            go.Bar(x=x_labels, y=macd_df["hist"], name="MACD 히스토그램", marker_color="#B0BEC5"),
            row=macd_row, col=1,
        )
        fig.add_trace(
            go.Scatter(x=x_labels, y=macd_df["macd"], name="MACD", line=dict(width=1.3, color="#5B8DEF")),
            row=macd_row, col=1,
        )
        fig.add_trace(
            go.Scatter(x=x_labels, y=macd_df["signal"], name="시그널", line=dict(width=1.3, color="#F2994A")),
            row=macd_row, col=1,
        )

    # TradingView처럼 캔들 위에 심볼/OHLC 정보를 겹쳐서 표시 (범례와 겹치지 않도록 플롯 안쪽 상단에 배치)
    last = df.iloc[-1]
    prev_close = float(df["Close"].iloc[-2]) if len(df) > 1 else float(last["Open"])
    change = float(last["Close"]) - prev_close
    change_pct = (change / prev_close * 100) if prev_close else 0.0
    move_color = "#26a69a" if change >= 0 else "#ef5350"
    sign = "+" if change >= 0 else ""
    fig.add_annotation(
        xref="x domain", yref="y domain", x=0.01, y=0.97, row=price_row, col=1,
        xanchor="left", yanchor="top", showarrow=False, align="left",
        font=dict(size=12, color="#d1d4dc"),
        text=(
            f"<b>{ticker}</b> · {INTERVAL_LABELS[interval]}　"
            f"시 {last['Open']:.2f}  고 {last['High']:.2f}  저 {last['Low']:.2f}  "
            f"종 <span style='color:{move_color}'><b>{last['Close']:.2f} "
            f"({sign}{change:.2f}, {sign}{change_pct:.2f}%)</b></span>"
        ),
    )
    # TradingView처럼 우측 가격축에 마지막 종가를 색상 배지로 표시
    fig.add_annotation(
        xref="x domain", yref="y", x=1.0, y=float(last["Close"]), row=price_row, col=1,
        xanchor="left", yanchor="middle", showarrow=False,
        text=f" {last['Close']:.2f} ", font=dict(size=11, color="#ffffff"),
        bgcolor=move_color, borderpad=3,
    )

    fig.update_layout(
        height=300 + 220 * len(rows),
        xaxis_rangeslider_visible=False,
        dragmode="pan",
        hovermode="x",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(l=10, r=45, t=30, b=10),
    )
    fig.update_xaxes(
        # 카테고리 축: 실제 데이터가 있는 봉만 순서대로 나열해 주말/공휴일/장외시간 공백을 없앤다.
        type="category", nticks=12,
        showspikes=True, spikemode="across", spikesnap="cursor", spikedash="dot",
        spikethickness=1, spikecolor="#758696",
    )
    style_chart_like_tradingview(fig)
    return fig


df = None
if not ticker:
    st.info("종목 티커를 입력해주세요. (예: AAPL, MSFT, 005930.KS)")
elif start_date >= end_date:
    st.warning("시작일은 종료일보다 빨라야 합니다.")
else:
    chart_params_key = (ticker, clamped_start.isoformat(), end_date.isoformat(), interval)
    job_manager.ensure(
        "chart_price_history", chart_params_key,
        _cached_price_history, ticker, clamped_start.isoformat(), end_date.isoformat(), interval,
        label=f"{ticker} 데이터 조회",
    )
    chart_job = job_manager.render("chart_price_history", running_label=f"{ticker} 데이터 조회 중")
    df = chart_job.result

    if df is None or df.empty:
        st.error(
            f"{ticker} 데이터를 가져오지 못했습니다. 티커를 확인하거나(예: 미국 주식은 접미사 없이, "
            "한국 주식은 '005930.KS'처럼), 조회 기간/봉 주기를 조정해보세요."
        )
        df = None
    else:
        st.plotly_chart(render_chart(df, ticker), use_container_width=True, config=TRADINGVIEW_CHART_CONFIG)
        inject_chart_interactions(ticker)

# TradingView처럼 빠른 기간 버튼을 차트 바로 아래에 배치 (조회 실패/미입력 상태에서도 항상 노출해
# 사용자가 기간을 바로 조정할 수 있게 한다).
range_cols = st.columns(len(RANGE_PRESETS))
today = date.today()
for (label, days), col in zip(RANGE_PRESETS.items(), range_cols):
    if col.button(label, use_container_width=True, key=f"preset_{label}"):
        if days == "ytd":
            new_start = date(today.year, 1, 1)
        elif days is None:
            new_start = date(1990, 1, 1)
        else:
            new_start = today - timedelta(days=days)
        st.session_state["chart_start_date"] = new_start
        st.session_state["chart_end_date"] = today
        st.rerun()

with st.expander("📅 직접 기간 지정"):
    col_start, col_end = st.columns(2)
    with col_start:
        st.date_input("시작일", key="chart_start_date")
    with col_end:
        st.date_input("종료일", key="chart_end_date")

if df is not None:
    st.caption(
        f"조회 기간: {df.index[0].date()} ~ {df.index[-1].date()} · {len(df)}개 봉 · {INTERVAL_LABELS[interval]} "
        "· 주말·공휴일·장외시간 등 거래 없는 구간은 표시하지 않습니다. 휠 확대/축소, 드래그 화면 이동, "
        "오른쪽 툴바에서 추세선/도형을 그릴 수 있습니다(그리고 나면 자동으로 화면 이동 모드로 돌아옵니다). "
        "그린 도형을 클릭하면 꼭짓점이 표시되어 드래그로 다른 캔들 위로 옮길 수 있고, 왼쪽 아래 색상 "
        "동그라미로 그 도형의 선 색을 바꿀 수 있으며, 지우개 도구로 삭제할 수 있습니다. 그린 도형은 "
        "같은 티커라면 봉 주기·지표를 바꿔도 유지됩니다 (티커를 바꾸면 초기화됩니다)."
    )
