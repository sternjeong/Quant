"""전략 차트 렌더링 (모듈 A에서 분리, 2026-07-16).

캔들차트 위에 지표를 오버레이하고 진입/청산 지점에 삼각형 마커를 찍는 로직. 원래
app/pages/1_전략_스튜디오.py 안에만 있던 함수들을 여기로 옮겨, 다른 페이지(예: 야간 미세튜닝
리더보드)도 백테스팅 엔진과 똑같은 차트/타점 마커 로직을 재사용할 수 있게 했다.

핵심 함수:
    render_price_chart(df, conditions, trades) -> go.Figure (레짐/직접수식 전략용)
    render_staged_price_chart(df, staged_config, stage_events) -> go.Figure (1:2:6 단계별 전략용)
"""

from __future__ import annotations

from typing import Optional

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from core.indicators import compute_bollinger, compute_ichimoku, compute_ma_cross, compute_macd, compute_rsi
from core.theme import style_chart_like_tradingview


def render_price_chart(df: pd.DataFrame, conditions: list[dict], trades: Optional[list] = None) -> go.Figure:
    """캔들차트 위에 지표를 오버레이한 TradingView 스타일 차트.

    trades를 넘기면(core.strategy_engine.extract_trades가 만든 Trade 목록, entry_reason/exit_reason
    포함) 진입/청산 지점에 삼각형 마커를 찍고 호버 시 어떤 조건이 만족되어 진입/청산했는지 보여준다.
    """
    show_rsi = any(c["indicator"] == "rsi" for c in conditions)
    rows = 2 if show_rsi else 1
    row_heights = [0.7, 0.3] if show_rsi else [1.0]
    fig = make_subplots(
        rows=rows, cols=1, shared_xaxes=True, vertical_spacing=0.06, row_heights=row_heights
    )

    fig.add_trace(
        go.Candlestick(
            x=df.index,
            open=df["Open"],
            high=df["High"],
            low=df["Low"],
            close=df["Close"],
            name="가격",
            increasing_line_color="#26a69a",
            decreasing_line_color="#ef5350",
            hovertemplate=(
                "%{x|%Y-%m-%d}<br>시가: %{open:,.2f}<br>고가: %{high:,.2f}<br>저가: %{low:,.2f}<br>"
                "종가: %{close:,.2f}<extra></extra>"
            ),
        ),
        row=1,
        col=1,
    )

    ma_colors = ["#5B8DEF", "#F2994A"]
    for cond in conditions:
        if cond["indicator"] == "ma_cross":
            cross = compute_ma_cross(df, cond.get("short", 20), cond.get("long", 60), cond.get("ma_type", "sma"))
            fig.add_trace(
                go.Scatter(
                    x=df.index, y=cross["short_ma"], name=f"MA{cond.get('short', 20)}",
                    line=dict(width=1.5, color=ma_colors[0]),
                ),
                row=1, col=1,
            )
            fig.add_trace(
                go.Scatter(
                    x=df.index, y=cross["long_ma"], name=f"MA{cond.get('long', 60)}",
                    line=dict(width=1.5, color=ma_colors[1]),
                ),
                row=1, col=1,
            )
        elif cond["indicator"] == "bollinger":
            bb = compute_bollinger(df, cond.get("period", 20), cond.get("std_dev", 2.0))
            fig.add_trace(
                go.Scatter(x=df.index, y=bb["upper"], name="볼린저 상단",
                            line=dict(width=1, color="#9B51E0", dash="dot")),
                row=1, col=1,
            )
            fig.add_trace(
                go.Scatter(x=df.index, y=bb["lower"], name="볼린저 하단",
                            line=dict(width=1, color="#9B51E0", dash="dot")),
                row=1, col=1,
            )
        elif cond["indicator"] == "rsi":
            rsi = compute_rsi(df, cond.get("period", 14))
            fig.add_trace(
                go.Scatter(x=df.index, y=rsi, name=f"RSI{cond.get('period', 14)}",
                            line=dict(width=1.5, color="#5B8DEF")),
                row=2, col=1,
            )
            fig.add_hline(y=70, line=dict(color="#ef5350", dash="dash", width=1), row=2, col=1)
            fig.add_hline(y=30, line=dict(color="#26a69a", dash="dash", width=1), row=2, col=1)

    if trades:
        entry_x = [t.entry_date for t in trades]
        entry_y = [t.entry_price for t in trades]
        entry_text = [f"진입<br>근거: {t.entry_reason or '조건 충족'}" for t in trades]
        closed_trades = [t for t in trades if t.exit_date is not None]
        exit_x = [t.exit_date for t in closed_trades]
        exit_y = [t.exit_price for t in closed_trades]
        exit_text = [f"청산<br>근거: {t.exit_reason or '조건 이탈'}" for t in closed_trades]
        if entry_x:
            fig.add_trace(
                go.Scatter(
                    x=entry_x, y=entry_y, mode="markers", name="진입",
                    marker=dict(symbol="triangle-up", size=11, color="#26a69a"),
                    text=entry_text, hoverinfo="text+x",
                ),
                row=1, col=1,
            )
        if exit_x:
            fig.add_trace(
                go.Scatter(
                    x=exit_x, y=exit_y, mode="markers", name="청산",
                    marker=dict(symbol="triangle-down", size=11, color="#ef5350"),
                    text=exit_text, hoverinfo="text+x",
                ),
                row=1, col=1,
            )

    fig.update_layout(
        height=620 if show_rsi else 480,
        xaxis_rangeslider_visible=False,
        dragmode="pan",
        hovermode="x",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(l=10, r=10, t=30, b=10),
    )
    fig.update_xaxes(
        showspikes=True, spikemode="across", spikesnap="cursor", spikedash="dot",
        spikethickness=1, spikecolor="#758696",
    )
    style_chart_like_tradingview(fig)
    return fig


def _find_stage_param(staged_config: dict, indicator: str) -> dict:
    """staged_config 전체에서 특정 indicator 조건을 처음 찾아 그 파라미터를 반환한다 (차트 오버레이용)."""
    stages = list(staged_config.get("entry_stages", [])) + list(staged_config.get("exit_stages", []))
    emergency = staged_config.get("emergency_exit")
    if emergency:
        stages = [*stages, emergency]
    for stage in stages:
        for cond in stage.get("conditions", []):
            if cond.get("indicator") == indicator:
                return cond
    return {}


def render_staged_price_chart(df: pd.DataFrame, staged_config: dict, stage_events: Optional[list] = None) -> go.Figure:
    """1:2:6 단계별 전략용 차트: 캔들+일목균형표 구름대(1행) / MACD(2행) / RSI(3행)."""
    ichi_cond = (
        _find_stage_param(staged_config, "ichimoku_cloud_break")
        or _find_stage_param(staged_config, "ichimoku_tk_state")
        or _find_stage_param(staged_config, "ichimoku_chikou_state")
    )
    macd_cond = _find_stage_param(staged_config, "macd_cross") or _find_stage_param(staged_config, "macd_level")
    rsi_cond = _find_stage_param(staged_config, "rsi_cross") or _find_stage_param(staged_config, "rsi")

    ichi = compute_ichimoku(
        df,
        tenkan_len=int(ichi_cond.get("tenkan_len", 9)),
        kijun_len=int(ichi_cond.get("kijun_len", 26)),
        span_b_len=int(ichi_cond.get("span_b_len", 52)),
        displacement=int(ichi_cond.get("displacement", 26)),
    )
    macd_df = compute_macd(
        df,
        fast=int(macd_cond.get("fast", 12)),
        slow=int(macd_cond.get("slow", 26)),
        signal=int(macd_cond.get("signal", 9)),
    )
    rsi_period = int(rsi_cond.get("period", 14))
    rsi = compute_rsi(df, period=rsi_period)

    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.04, row_heights=[0.5, 0.25, 0.25]
    )

    fig.add_trace(
        go.Candlestick(
            x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
            name="가격", increasing_line_color="#26a69a", decreasing_line_color="#ef5350",
            hovertemplate=(
                "%{x|%Y-%m-%d}<br>시가: %{open:,.2f}<br>고가: %{high:,.2f}<br>저가: %{low:,.2f}<br>"
                "종가: %{close:,.2f}<extra></extra>"
            ),
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(x=df.index, y=ichi["cloud_bottom"], line=dict(width=0), showlegend=False, hoverinfo="skip"),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=df.index, y=ichi["cloud_top"], name="구름대", line=dict(width=0),
            fill="tonexty", fillcolor="rgba(91,141,239,0.18)", hoverinfo="skip",
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(x=df.index, y=ichi["tenkan"], name="전환선", line=dict(width=1.2, color="#F2994A")),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(x=df.index, y=ichi["kijun"], name="기준선", line=dict(width=1.2, color="#9B51E0")),
        row=1, col=1,
    )

    if stage_events:
        entry_x = [e.date for e in stage_events if e.kind == "entry"]
        entry_y = [e.price for e in stage_events if e.kind == "entry"]
        entry_text = [
            f"{e.stage}단계 진입 (+{e.weight:.0%})<br>근거: {e.reason}"
            for e in stage_events if e.kind == "entry"
        ]
        exit_x = [e.date for e in stage_events if e.kind != "entry"]
        exit_y = [e.price for e in stage_events if e.kind != "entry"]
        exit_text = [
            f"{e.stage}단계 청산 (-{e.weight:.0%})" + (" [긴급청산]" if e.kind == "emergency_exit" else "")
            + f"<br>근거: {e.reason}"
            for e in stage_events if e.kind != "entry"
        ]
        if entry_x:
            fig.add_trace(
                go.Scatter(
                    x=entry_x, y=entry_y, mode="markers", name="진입",
                    marker=dict(symbol="triangle-up", size=11, color="#26a69a"),
                    text=entry_text, hoverinfo="text+x",
                ),
                row=1, col=1,
            )
        if exit_x:
            fig.add_trace(
                go.Scatter(
                    x=exit_x, y=exit_y, mode="markers", name="청산",
                    marker=dict(symbol="triangle-down", size=11, color="#ef5350"),
                    text=exit_text, hoverinfo="text+x",
                ),
                row=1, col=1,
            )

    fig.add_trace(
        go.Bar(x=df.index, y=macd_df["hist"], name="MACD 히스토그램", marker_color="#B0BEC5"),
        row=2, col=1,
    )
    fig.add_trace(
        go.Scatter(x=df.index, y=macd_df["macd"], name="MACD", line=dict(width=1.3, color="#5B8DEF")),
        row=2, col=1,
    )
    fig.add_trace(
        go.Scatter(x=df.index, y=macd_df["signal"], name="시그널", line=dict(width=1.3, color="#F2994A")),
        row=2, col=1,
    )

    fig.add_trace(
        go.Scatter(x=df.index, y=rsi, name=f"RSI{rsi_period}", line=dict(width=1.5, color="#5B8DEF")),
        row=3, col=1,
    )
    fig.add_hline(y=70, line=dict(color="#ef5350", dash="dash", width=1), row=3, col=1)
    fig.add_hline(y=30, line=dict(color="#26a69a", dash="dash", width=1), row=3, col=1)

    fig.update_layout(
        height=780,
        xaxis_rangeslider_visible=False,
        dragmode="pan",
        hovermode="x",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(l=10, r=10, t=30, b=10),
    )
    fig.update_xaxes(
        showspikes=True, spikemode="across", spikesnap="cursor", spikedash="dot",
        spikethickness=1, spikecolor="#758696",
    )
    style_chart_like_tradingview(fig)
    return fig
