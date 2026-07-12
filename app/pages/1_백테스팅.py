"""모듈 A: 백테스팅 엔진 페이지.

- 이동평균 교차 / RSI / 볼린저밴드 지표를 토글로 켜고 끄면서 조합(AND/OR)한 전략을 구성
- 지표 토글로 표현하기 어려운 조건은 "✍️ 직접 수식 입력" 슬롯에 파이썬과 비슷한 문법의 수식을
  직접 입력해 구성 가능 (core/expression_engine.py, 예: "close > sma(close, 20) and rsi(close, 14) < 30")
- 특정 전략 적용 vs 종목 매수 후 보유 vs S&P500 매수 후 보유를 비교
- 누적수익률/CAGR/MDD/샤프지수/승률/매매횟수 계산, 표시할 지표는 사용자가 선택
- 자연어로 붙여넣은 전략 설명을 AI가 해석해 지표 조합으로 변환 후 전략 라이브러리에 저장
"""

import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

# --- sys.path 부트스트랩: 프로젝트 루트를 추가해 core.* 임포트 가능하게 함 (app/pages/*.py 공통 규칙) ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from core.backtest_engine import (
    DEFAULT_BENCHMARK_TICKER,
    BacktestRun,
    compare_with_benchmarks,
    save_backtest_result,
)
from core.db import get_session, init_db
from core.expression_engine import ExpressionError, validate_syntax
from core.indicators import compute_bollinger, compute_ichimoku, compute_ma_cross, compute_macd, compute_rsi
from core import job_manager
from core.models import Strategy
from core.nl_strategy import interpret_strategy_text
from core.strategy_engine import is_expression_config, is_staged_config
from core.strategy_library import detect_strategy_type
from core.theme import TRADINGVIEW_CHART_CONFIG, apply_theme, style_chart_like_tradingview

init_db()

st.set_page_config(page_title="백테스팅 엔진", page_icon="📈", layout="wide")
apply_theme()
job_manager.render_active_jobs_sidebar()
st.title("📈 백테스팅 엔진")
st.caption("전략 적용 vs 종목 매수 후 보유 vs S&P500 매수 후 보유를 비교하고, 전략을 라이브러리에 저장합니다.")

METRIC_LABELS = {
    "cumulative_return": "누적수익률(%)",
    "cagr": "CAGR(%)",
    "mdd": "MDD(%)",
    "sharpe": "샤프지수",
    "win_rate": "승률(%)",
    "trade_count": "매매횟수",
}

STRATEGY_TYPE_LABELS = {"staged": "1:2:6 단계별", "expression": "직접 수식", "regime": "레짐(AND/OR)"}

MODE_TOGGLE = "🎛️ 지표 토글"
MODE_EXPRESSION = "✍️ 직접 수식 입력"

EXPRESSION_CHEAT_SHEET = """\
**사용 가능한 변수**: `open`, `high`, `low`, `close`, `volume`

**사용 가능한 함수**:
- `sma(series, period)` / `ema(series, period)` — 단순/지수 이동평균
- `rsi(series, period=14)` — RSI
- `macd_line(series, fast=12, slow=26, signal=9)` / `macd_signal(...)` / `macd_hist(...)` — MACD
- `bb_upper(series, period=20, std=2)` / `bb_mid(...)` / `bb_lower(...)` — 볼린저밴드
- `stdev(series, period)` — 표준편차
- `highest(series, period)` / `lowest(series, period)` — 구간 내 최고/최저
- `crossover(a, b)` / `crossunder(a, b)` — a가 b를 상향/하향 돌파하는 순간(이벤트)
- `abs(x)`, `min(a, b)`, `max(a, b)`

**연산자**: `>`, `<`, `>=`, `<=`, `==`, `!=`, `and`, `or`, `not`, `+`, `-`, `*`, `/`

**예시**:
- `close > sma(close, 20) and rsi(close, 14) < 30`
- `crossover(macd_line(close), macd_signal(close))`
- `close < bb_lower(close, 20, 2) and volume > sma(volume, 20)`
"""

DEFAULT_UI_STATE = {
    "ticker": "AAPL",
    "ma_enabled": True,
    "ma_short": 20,
    "ma_long": 60,
    "ma_type": "sma",
    "ma_cross_type": "golden",
    "rsi_enabled": False,
    "rsi_period": 14,
    "rsi_op": "<",
    "rsi_value": 30.0,
    "bb_enabled": False,
    "bb_period": 20,
    "bb_std": 2.0,
    "bb_band": "lower",
    "bb_op": "break_below",
    "logic": "AND",
    "loaded_staged_config": None,
    "strategy_input_mode": MODE_TOGGLE,
    "expression_text": "",
}


def _init_ui_state() -> None:
    for k, v in DEFAULT_UI_STATE.items():
        st.session_state.setdefault(k, v)


def _load_config_into_state(indicator_config: dict) -> None:
    """저장된 전략의 indicator_config 를 UI 위젯 상태로 복원한다.

    1:2:6 단계별(staged) 전략은 지표 토글 UI로 표현할 수 없으므로, 대신
    st.session_state["loaded_staged_config"] 에 원본 그대로 저장해두고 토글은 전부 꺼둔다
    (백테스트 실행 시 이 값이 있으면 토글 UI 대신 그대로 사용한다). 직접 수식 전략도 마찬가지로
    토글 UI 대신 "expression_text" 로 복원하고 입력 방식을 자동으로 "직접 수식 입력"으로 전환한다.
    """
    if is_staged_config(indicator_config):
        st.session_state["loaded_staged_config"] = indicator_config
        st.session_state["ma_enabled"] = False
        st.session_state["rsi_enabled"] = False
        st.session_state["bb_enabled"] = False
        return

    st.session_state["loaded_staged_config"] = None

    if is_expression_config(indicator_config):
        st.session_state["expression_text"] = indicator_config.get("expression", "")
        st.session_state["strategy_input_mode"] = MODE_EXPRESSION
        st.session_state["ma_enabled"] = False
        st.session_state["rsi_enabled"] = False
        st.session_state["bb_enabled"] = False
        return

    st.session_state["strategy_input_mode"] = MODE_TOGGLE
    st.session_state["logic"] = indicator_config.get("logic", "AND")
    st.session_state["ma_enabled"] = False
    st.session_state["rsi_enabled"] = False
    st.session_state["bb_enabled"] = False
    for cond in indicator_config.get("conditions", []):
        ind = cond.get("indicator")
        if ind == "ma_cross":
            st.session_state["ma_enabled"] = True
            st.session_state["ma_short"] = cond.get("short", 20)
            st.session_state["ma_long"] = cond.get("long", 60)
            st.session_state["ma_type"] = cond.get("ma_type", "sma")
            st.session_state["ma_cross_type"] = cond.get("type", "golden")
        elif ind == "rsi":
            st.session_state["rsi_enabled"] = True
            st.session_state["rsi_period"] = cond.get("period", 14)
            st.session_state["rsi_op"] = cond.get("op", "<")
            st.session_state["rsi_value"] = float(cond.get("value", 30))
        elif ind == "bollinger":
            st.session_state["bb_enabled"] = True
            st.session_state["bb_period"] = cond.get("period", 20)
            st.session_state["bb_std"] = float(cond.get("std_dev", 2.0))
            st.session_state["bb_band"] = cond.get("band", "lower")
            st.session_state["bb_op"] = cond.get("op", "break_below")


def _build_indicator_config_from_ui() -> dict:
    conditions = []
    if st.session_state["ma_enabled"]:
        conditions.append(
            {
                "indicator": "ma_cross",
                "short": int(st.session_state["ma_short"]),
                "long": int(st.session_state["ma_long"]),
                "ma_type": st.session_state["ma_type"],
                "type": st.session_state["ma_cross_type"],
            }
        )
    if st.session_state["rsi_enabled"]:
        conditions.append(
            {
                "indicator": "rsi",
                "period": int(st.session_state["rsi_period"]),
                "op": st.session_state["rsi_op"],
                "value": float(st.session_state["rsi_value"]),
            }
        )
    if st.session_state["bb_enabled"]:
        conditions.append(
            {
                "indicator": "bollinger",
                "period": int(st.session_state["bb_period"]),
                "std_dev": float(st.session_state["bb_std"]),
                "band": st.session_state["bb_band"],
                "op": st.session_state["bb_op"],
            }
        )
    return {"logic": st.session_state["logic"], "conditions": conditions}


def render_price_chart(df: pd.DataFrame, conditions: list[dict]) -> go.Figure:
    """캔들차트 위에 지표를 오버레이한 TradingView 스타일 차트."""
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
        entry_text = [f"{e.stage}단계 진입 (+{e.weight:.0%})" for e in stage_events if e.kind == "entry"]
        exit_x = [e.date for e in stage_events if e.kind != "entry"]
        exit_y = [e.price for e in stage_events if e.kind != "entry"]
        exit_text = [
            f"{e.stage}단계 청산 (-{e.weight:.0%})" + (" [긴급청산]" if e.kind == "emergency_exit" else "")
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


def render_equity_comparison(results: dict[str, BacktestRun]) -> go.Figure:
    fig = go.Figure()
    colors = {
        "strategy": "#5B8DEF",
        "buy_and_hold_ticker": "#F2994A",
        "buy_and_hold_benchmark": "#9B51E0",
    }
    for key, run in results.items():
        if run.equity_curve is None or run.equity_curve.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=run.equity_curve.index, y=run.equity_curve.values, name=run.label,
                line=dict(width=2, color=colors.get(key)),
            )
        )
    fig.update_layout(
        height=380,
        yaxis_title="자산가치 (시작=100)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(l=10, r=10, t=30, b=10),
        template="plotly_white",
    )
    return fig


def metrics_dataframe(results: dict[str, BacktestRun], selected: list[str]) -> pd.DataFrame:
    """선택된 지표만 모아 표로 만든다.

    주의: 값을 모두 float 로 명시 변환해서 동질적인(homogeneous) float64 컬럼을 만든다.
    (정수/실수/None 이 섞인 object dtype DataFrame 을 st.dataframe 에 그대로 넘기면
    일부 환경의 pandas/pyarrow 조합에서 Arrow 직렬화 중 크래시가 발생할 수 있음)
    """
    data = {
        run.label: [float(run.metrics.get(m) or 0.0) for m in selected] for run in results.values()
    }
    index = [METRIC_LABELS[m] for m in selected]
    return pd.DataFrame(data, index=index).T


tab_backtest, tab_nl = st.tabs(["📊 지표 조합 백테스트", "🤖 자연어 전략 등록"])

with tab_backtest:
    _init_ui_state()

    with get_session() as session:
        strategies = session.query(Strategy).order_by(Strategy.created_at.desc()).all()
        strategy_options = {"직접 설정": None}
        for s in strategies:
            type_label = STRATEGY_TYPE_LABELS[detect_strategy_type(s.indicator_config)]
            strategy_options[f"{s.name} (#{s.id}, {type_label}, {s.source or '수동'})"] = s.id

    col_load, col_load_btn = st.columns([4, 1])
    with col_load:
        picked_label = st.selectbox("전략 라이브러리에서 불러오기", list(strategy_options.keys()))
    with col_load_btn:
        st.write("")
        st.write("")
        if st.button("불러오기", use_container_width=True):
            picked_id = strategy_options[picked_label]
            if picked_id is not None:
                with get_session() as session:
                    strategy = session.get(Strategy, picked_id)
                    if strategy is not None:
                        _load_config_into_state(json.loads(strategy.indicator_config))
                        st.session_state["loaded_strategy_id"] = picked_id
                        st.session_state["loaded_strategy_name"] = strategy.name
                        st.rerun()

    st.divider()

    col_ticker, col_start, col_end, col_logic = st.columns([2, 2, 2, 1])
    with col_ticker:
        ticker = st.text_input("종목 티커", key="ticker").strip().upper()
    with col_start:
        start_date = st.date_input("시작일", value=date.today() - timedelta(days=365 * 3))
    with col_end:
        end_date = st.date_input("종료일", value=date.today())
    with col_logic:
        st.selectbox("조건 결합", ["AND", "OR"], key="logic")

    loaded_staged_config = st.session_state.get("loaded_staged_config")

    if loaded_staged_config:
        st.info(
            "🧬 1:2:6 단계별(고급) 전략이 로드되어 있습니다. 아래 지표 토글 대신 이 전략 그대로 백테스트를 실행합니다. "
            "세부 조건 수정은 '전략 관리' 페이지에서 할 수 있습니다."
        )
        with st.expander("로드된 전략 JSON 보기"):
            st.json(loaded_staged_config)
        if st.button("↩️ 커스텀 지표 조합으로 전환 (단계별 전략 로드 해제)"):
            st.session_state["loaded_staged_config"] = None
            st.rerun()
    else:
        st.radio(
            "전략 입력 방식", [MODE_TOGGLE, MODE_EXPRESSION], key="strategy_input_mode", horizontal=True
        )

        if st.session_state["strategy_input_mode"] == MODE_EXPRESSION:
            st.markdown("#### 직접 수식 입력")
            st.caption("지표 토글로 표현하기 어려운 조건을 파이썬과 비슷한 문법의 수식으로 직접 입력합니다.")
            with st.expander("사용 가능한 변수/함수 보기", expanded=False):
                st.markdown(EXPRESSION_CHEAT_SHEET)
            st.text_area(
                "수식",
                key="expression_text",
                height=100,
                placeholder="예: close > sma(close, 20) and rsi(close, 14) < 30",
            )
            if st.button("🔍 문법 검증"):
                expr_to_check = st.session_state["expression_text"].strip()
                if not expr_to_check:
                    st.warning("수식을 입력해주세요.")
                else:
                    try:
                        validate_syntax(expr_to_check)
                    except ExpressionError as e:
                        st.error(f"수식 오류: {e}")
                    else:
                        st.success("문법 검증을 통과했습니다. 아래 '백테스트 실행'으로 실제 데이터에 돌려보세요.")
        else:
            st.markdown("#### 지표 토글 (TradingView 스타일 on/off)")
            col_ma, col_rsi, col_bb = st.columns(3)

            # 위젯은 모두 DEFAULT_UI_STATE 와 동일한 key 를 사용한다.
            # "불러오기" 버튼이 위젯 생성 이전(같은 스크립트 실행의 앞부분)에 session_state[key] 를
            # 먼저 갱신해두면, 아래 위젯들은 그 값을 그대로 초기값으로 사용하게 된다.
            with col_ma:
                st.checkbox("이동평균 교차", key="ma_enabled")
                if st.session_state["ma_enabled"]:
                    st.number_input("단기 기간", min_value=2, max_value=200, key="ma_short")
                    st.number_input("장기 기간", min_value=3, max_value=400, key="ma_long")
                    st.radio("이동평균 종류", ["sma", "ema"], key="ma_type", horizontal=True)
                    st.radio(
                        "국면", ["golden", "dead"], key="ma_cross_type", horizontal=True,
                        format_func=lambda x: "골든크로스(상승)" if x == "golden" else "데드크로스(하락)",
                    )

            with col_rsi:
                st.checkbox("RSI 과매수/과매도", key="rsi_enabled")
                if st.session_state["rsi_enabled"]:
                    st.number_input("RSI 기간", min_value=2, max_value=100, key="rsi_period")
                    st.selectbox("조건", ["<", "<=", ">", ">="], key="rsi_op")
                    st.number_input("기준값", min_value=0.0, max_value=100.0, key="rsi_value")

            with col_bb:
                st.checkbox("볼린저밴드 이탈", key="bb_enabled")
                if st.session_state["bb_enabled"]:
                    st.number_input("밴드 기간", min_value=2, max_value=200, key="bb_period")
                    st.number_input("표준편차 배수", min_value=0.5, max_value=5.0, step=0.5, key="bb_std")
                    st.radio(
                        "이탈 방향", ["lower", "upper"], key="bb_band", horizontal=True,
                        format_func=lambda x: "하단 이탈(눌림목)" if x == "lower" else "상단 이탈(과열)",
                    )
                    st.session_state["bb_op"] = (
                        "break_below" if st.session_state["bb_band"] == "lower" else "break_above"
                    )

    run_clicked = st.button("🚀 백테스트 실행", type="primary")

    if run_clicked:
        expression_mode = (
            not loaded_staged_config and st.session_state["strategy_input_mode"] == MODE_EXPRESSION
        )
        if loaded_staged_config:
            indicator_config = loaded_staged_config
            has_conditions = bool(indicator_config.get("entry_stages"))
        elif expression_mode:
            expr = st.session_state["expression_text"].strip()
            indicator_config = {"expression": expr}
            has_conditions = bool(expr)
        else:
            indicator_config = _build_indicator_config_from_ui()
            has_conditions = bool(indicator_config["conditions"])

        if not has_conditions:
            st.warning("최소 1개 이상의 지표를 켜거나 수식을 입력해주세요.")
        elif not ticker:
            st.warning("종목 티커를 입력해주세요.")
        elif start_date >= end_date:
            st.warning("시작일은 종료일보다 빨라야 합니다.")
        else:
            # 백그라운드 작업이 끝나는 시점은 다른 rerun이라 지역변수(indicator_config 등)가 더
            # 이상 살아있지 않으므로, 작업 시작 시점에 session_state 에 함께 저장해둔다.
            st.session_state["pending_config"] = indicator_config
            st.session_state["pending_ticker"] = ticker
            st.session_state["pending_start"] = start_date.isoformat()
            st.session_state["pending_end"] = end_date.isoformat()
            job_manager.start(
                "backtest_run", compare_with_benchmarks,
                ticker, indicator_config, start_date.isoformat(), end_date.isoformat(),
                benchmark_ticker=DEFAULT_BENCHMARK_TICKER,
                label=f"{ticker} 백테스트",
            )

    backtest_job = job_manager.render("backtest_run", running_label="백테스트 실행 중")
    if backtest_job is not None:
        if backtest_job.status == "error":
            st.error(f"백테스트 실행 중 오류가 발생했습니다 (수식 오류일 수 있음): {backtest_job.error}")
        else:
            st.session_state["last_results"] = backtest_job.result
            st.session_state["last_config"] = st.session_state["pending_config"]
            st.session_state["last_ticker"] = st.session_state["pending_ticker"]
            st.session_state["last_start"] = st.session_state["pending_start"]
            st.session_state["last_end"] = st.session_state["pending_end"]

    results = st.session_state.get("last_results")
    if results is not None:
        strategy_run: BacktestRun = results["strategy"]
        indicator_config = st.session_state["last_config"]

        if strategy_run.df.empty:
            st.error(f"{st.session_state['last_ticker']} 데이터를 가져오지 못했습니다. 티커를 확인해주세요.")
        else:
            st.markdown("#### 캔들차트 + 지표 오버레이")
            st.caption("마우스 휠로 확대/축소, 드래그로 화면 이동이 가능합니다.")
            if is_staged_config(indicator_config):
                st.plotly_chart(
                    render_staged_price_chart(strategy_run.df, indicator_config, strategy_run.stage_events),
                    use_container_width=True,
                    config=TRADINGVIEW_CHART_CONFIG,
                )
                if strategy_run.stage_events:
                    st.caption(f"진입/청산 이벤트 {len(strategy_run.stage_events)}건 발생 (차트 위 삼각형 마커 참고)")
            else:
                if is_expression_config(indicator_config):
                    st.caption("직접 수식 전략은 지표 오버레이 없이 캔들차트만 표시합니다.")
                st.plotly_chart(
                    render_price_chart(strategy_run.df, indicator_config.get("conditions", [])),
                    use_container_width=True,
                    config=TRADINGVIEW_CHART_CONFIG,
                )

            st.markdown("#### 전략 vs 매수보유 비교 (자산가치, 시작=100)")
            st.plotly_chart(render_equity_comparison(results), use_container_width=True)

            st.markdown("#### 성과 지표")
            selected_metrics = st.multiselect(
                "표시할 지표 선택",
                options=list(METRIC_LABELS.keys()),
                default=list(METRIC_LABELS.keys()),
                format_func=lambda m: METRIC_LABELS[m],
            )
            if selected_metrics:
                st.dataframe(metrics_dataframe(results, selected_metrics), use_container_width=True)
            else:
                st.info("표시할 지표를 1개 이상 선택하세요.")

            st.markdown("#### 이 전략을 라이브러리에 저장")
            col_name, col_save = st.columns([3, 1])
            with col_name:
                strategy_name = st.text_input(
                    "전략 이름", value=st.session_state.get("loaded_strategy_name", "") or "새 전략"
                )
            with col_save:
                st.write("")
                st.write("")
                if st.button("💾 저장", use_container_width=True):
                    with get_session() as session:
                        strategy = Strategy(
                            name=strategy_name,
                            indicator_config=json.dumps(indicator_config, ensure_ascii=False),
                            source="manual",
                            description=(
                                "백테스팅 화면에서 직접 입력한 수식으로 구성한 전략"
                                if is_expression_config(indicator_config)
                                else "백테스팅 화면에서 지표 토글로 직접 구성한 전략"
                            ),
                        )
                        session.add(strategy)
                        session.flush()
                        strategy_id = strategy.id

                    save_backtest_result(
                        strategy_id=strategy_id,
                        ticker=st.session_state["last_ticker"],
                        start=st.session_state["last_start"],
                        end=st.session_state["last_end"],
                        metrics=strategy_run.metrics,
                        extra_metrics={
                            "buy_and_hold_ticker": results["buy_and_hold_ticker"].metrics,
                            "buy_and_hold_benchmark": results["buy_and_hold_benchmark"].metrics,
                        },
                    )
                    st.success(f"전략 '{strategy_name}' 저장 완료 (id={strategy_id}). 관심 종목에 연결해 매일 모니터링할 수 있습니다.")

    with st.expander("저장된 전략 목록"):
        st.caption("전략 이름 수정/삭제는 좌측 메뉴의 '전략 관리' 페이지에서 할 수 있습니다.")
        with get_session() as session:
            rows = session.query(Strategy).order_by(Strategy.created_at.desc()).all()
            if rows:
                df_strategies = pd.DataFrame(
                    {
                        "id": pd.array([s.id for s in rows], dtype="int64"),
                        "이름": pd.array([str(s.name) for s in rows], dtype="string"),
                        "유형": pd.array(
                            [STRATEGY_TYPE_LABELS[detect_strategy_type(s.indicator_config)] for s in rows],
                            dtype="string",
                        ),
                        "출처": pd.array([str(s.source or "") for s in rows], dtype="string"),
                        "생성일": pd.to_datetime([s.created_at for s in rows]),
                    }
                )
                st.dataframe(df_strategies, use_container_width=True, hide_index=True)
            else:
                st.caption("아직 저장된 전략이 없습니다.")

with tab_nl:
    st.markdown(
        "유튜버 등의 전략 설명 스크립트(텍스트)를 붙여넣으면 AI가 조건을 해석해서 보여줍니다. "
        "`GEMINI_API_KEY`가 설정되어 있지 않으면 간단한 키워드 매칭으로 대체 해석합니다."
    )
    raw_text = st.text_area(
        "전략 설명 붙여넣기", height=200,
        placeholder="예: 20일 이동평균선이 60일 이동평균선을 상향 돌파하는 골든크로스가 뜨고, RSI가 30 이하로 떨어졌을 때 매수합니다.",
    )

    if st.button("🤖 AI로 해석하기"):
        if not raw_text.strip():
            st.warning("전략 설명을 입력해주세요.")
        else:
            job_manager.start("nl_interpret", interpret_strategy_text, raw_text, label="전략 해석")

    nl_interpret_job = job_manager.render(
        "nl_interpret", running_label="전략을 해석하는 중 (진입/청산 자기모순 자가진단 및 자기교정 포함)"
    )
    if nl_interpret_job is not None:
        if nl_interpret_job.status == "error":
            st.error(f"전략 해석 중 오류가 발생했습니다: {nl_interpret_job.error}")
        else:
            st.session_state["nl_result"] = nl_interpret_job.result
            st.session_state["nl_raw_text"] = raw_text
            st.session_state["nl_health_warnings"] = nl_interpret_job.result.get("health_warnings", [])
            st.session_state["nl_preview_results"] = None

    nl_result = st.session_state.get("nl_result")
    if nl_result is not None:
        nl_staged = is_staged_config(nl_result["indicator_config"])
        st.markdown("#### 해석 결과")
        if nl_staged:
            st.caption("🧬 1:2:6 단계별(고급) 전략으로 해석되었습니다 (신호가 겹칠수록 비중을 늘려가며 분할 진입/청산).")
        health_warnings = st.session_state.get("nl_health_warnings") or []
        for warning_msg in health_warnings:
            st.error(warning_msg)
        if health_warnings:
            st.caption("AI가 자기교정 재시도까지 거쳤지만 문제가 해결되지 않았습니다. 아래에서 조건을 직접 확인 후 저장하세요.")
        st.info(nl_result["description"])
        st.json(nl_result["indicator_config"])

        st.markdown("#### ▶ 바로 백테스트 미리보기")
        col_p_ticker, col_p_start, col_p_end, col_p_btn = st.columns([2, 2, 2, 1])
        with col_p_ticker:
            preview_ticker = st.text_input("종목 티커", value="AAPL", key="nl_preview_ticker").strip().upper()
        with col_p_start:
            preview_start = st.date_input(
                "시작일", value=date.today() - timedelta(days=365 * 3), key="nl_preview_start"
            )
        with col_p_end:
            preview_end = st.date_input("종료일", value=date.today(), key="nl_preview_end")
        with col_p_btn:
            st.write("")
            st.write("")
            preview_clicked = st.button("🚀 실행", key="nl_preview_run", use_container_width=True)

        if preview_clicked:
            if not preview_ticker:
                st.warning("종목 티커를 입력해주세요.")
            elif preview_start >= preview_end:
                st.warning("시작일은 종료일보다 빨라야 합니다.")
            else:
                job_manager.start(
                    "nl_preview_run", compare_with_benchmarks,
                    preview_ticker, nl_result["indicator_config"],
                    preview_start.isoformat(), preview_end.isoformat(),
                    benchmark_ticker=DEFAULT_BENCHMARK_TICKER,
                    label=f"{preview_ticker} 백테스트 미리보기",
                )

        nl_preview_job = job_manager.render("nl_preview_run", running_label=f"{preview_ticker} 백테스트 실행 중")
        if nl_preview_job is not None:
            if nl_preview_job.status == "error":
                st.error(f"백테스트 실행 중 오류가 발생했습니다: {nl_preview_job.error}")
            else:
                st.session_state["nl_preview_results"] = nl_preview_job.result

        preview_results = st.session_state.get("nl_preview_results")
        if preview_results is not None:
            preview_run: BacktestRun = preview_results["strategy"]
            if preview_run.df.empty:
                st.error("가격 데이터를 가져오지 못했습니다. 티커를 확인해주세요.")
            else:
                if nl_staged:
                    st.plotly_chart(
                        render_staged_price_chart(
                            preview_run.df, nl_result["indicator_config"], preview_run.stage_events
                        ),
                        use_container_width=True,
                        config=TRADINGVIEW_CHART_CONFIG,
                    )
                else:
                    st.plotly_chart(
                        render_price_chart(preview_run.df, nl_result["indicator_config"]["conditions"]),
                        use_container_width=True,
                        config=TRADINGVIEW_CHART_CONFIG,
                    )
                st.plotly_chart(render_equity_comparison(preview_results), use_container_width=True)
                st.dataframe(
                    metrics_dataframe(preview_results, list(METRIC_LABELS.keys())), use_container_width=True
                )

        st.divider()
        candidate_name = st.text_input("전략명 (수정 가능)", value=nl_result["name"])

        save_disabled = False
        if health_warnings:
            save_disabled = not st.checkbox(
                "위 경고를 확인했습니다. 조건이 겹쳐도 그대로 저장합니다.", key="nl_ack_health_warnings"
            )

        if st.button("📚 전략 라이브러리에 저장", type="primary", disabled=save_disabled):
            with get_session() as session:
                strategy = Strategy(
                    name=candidate_name,
                    indicator_config=json.dumps(nl_result["indicator_config"], ensure_ascii=False),
                    source="youtube_script",
                    description=nl_result["description"] + "\n\n[원문]\n" + st.session_state.get("nl_raw_text", ""),
                )
                session.add(strategy)
                session.flush()
                saved_id = strategy.id
            st.success(f"전략 '{candidate_name}' 저장 완료 (id={saved_id}). '지표 조합 백테스트' 탭에서 불러와 실행하세요.")
            del st.session_state["nl_result"]
