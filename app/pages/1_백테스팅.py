"""모듈 A: 백테스팅 엔진 페이지.

- 이동평균 교차 / RSI / 볼린저밴드 지표를 토글로 켜고 끄면서 조합(AND/OR)한 전략을 구성
- 지표 토글로 표현하기 어려운 조건은 "✍️ 직접 수식 입력" 슬롯에 파이썬과 비슷한 문법의 수식을
  직접 입력해 구성 가능 (core/expression_engine.py, 예: "close > sma(close, 20) and rsi(close, 14) < 30")
- 특정 전략 적용 vs 종목 매수 후 보유 vs S&P500 매수 후 보유를 비교
- 누적수익률/CAGR/MDD/샤프지수/승률/매매횟수 계산, 표시할 지표는 사용자가 선택
- 자연어로 붙여넣은 전략 설명을 AI가 해석해 지표 조합으로 변환 후 전략 라이브러리에 저장
- 다종목 미세튜닝: 백본 전략을 S&P500 섹터 균등 표본(기본 100종목)에 적용해 종목 스타일별로
  파라미터를 자동 탐색하고(train/test 분리 검증), 종목별 3-way 비교로 결과를 확인 (core/strategy_tuning.py)
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

from core.backtest_engine import (
    DEFAULT_BENCHMARK_TICKER,
    BacktestRun,
    compare_with_benchmarks,
    compute_regime_breakdown,
    save_backtest_result,
)
from core.chart_rendering import render_price_chart, render_staged_price_chart
from core.db import get_session, init_db
from core.expression_engine import ExpressionError, validate_syntax
from core import job_manager
from core.models import Strategy
from core.nl_strategy import interpret_strategy_text
from core import era_validation, screener, strategy_tuning
from core.strategy_engine import is_expression_config, is_staged_config
from core.strategy_explainer import describe_regime_config, describe_staged_config, explain_strategy
from core.strategy_library import detect_strategy_type
from core.theme import TRADINGVIEW_CHART_CONFIG, apply_theme

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

STRATEGY_TYPE_LABELS = {
    "staged": "1:2:6 단계별",
    "expression": "직접 수식",
    "regime": "레짐(AND/OR)",
    "combined": "전략 합성",
}

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


def _describe_candidate_compact(config: dict) -> str:
    """튜닝 리포트 표에 한 줄로 넣기 위해 후보 config를 스키마에 맞게 간단히 요약한다 (결정론적,
    Gemini 호출 없음 — 트레일에 후보가 최대 수십 개라 explain_strategy()를 쓰면 호출량이 커짐)."""
    if is_expression_config(config):
        return config.get("expression", "")
    if is_staged_config(config):
        return describe_staged_config(config).replace("\n", " / ")
    return describe_regime_config(config)


def render_ticker_picker(key_suffix: str, caption: str) -> pd.DataFrame:
    """S&P500 전체 목록을 스크롤 가능한 표로 보여주고, 체크박스로 담은 종목을 반환한다.

    "다종목 미세튜닝"(직접 선택 모드)과 "알고리즘 자동 생성"(교차검증 대상 선택) 양쪽에서
    재사용한다. key_suffix가 다르면 같은 스크립트 실행 안에서 여러 번 호출해도 위젯 key가
    충돌하지 않는다(Streamlit 탭은 화면에 보이지 않아도 매 rerun마다 전부 실행되므로 필요).

    Returns:
        columns: ticker, sector. 아무것도 담지 않았으면 빈 DataFrame(같은 컬럼 유지).
    """
    st.caption(caption)
    picker_universe = screener.get_universe().sort_values(["Sector", "Symbol"]).reset_index(drop=True)
    picker_display = picker_universe.rename(columns={"Symbol": "티커", "Security": "종목명", "Sector": "섹터"})
    picker_event = st.dataframe(
        picker_display, use_container_width=True, hide_index=True, height=420,
        on_select="rerun", selection_mode="multi-row", key=f"ticker_picker_{key_suffix}",
    )
    picked_rows = picker_event.selection.rows if picker_event and getattr(picker_event, "selection", None) else []
    picked_df = (
        picker_universe.iloc[picked_rows][["Symbol", "Sector"]]
        .rename(columns={"Symbol": "ticker", "Sector": "sector"})
        .reset_index(drop=True)
        if picked_rows
        else pd.DataFrame(columns=["ticker", "sector"])
    )
    if not picked_df.empty:
        st.caption(f"🧺 담은 종목 {len(picked_df)}개: {', '.join(picked_df['ticker'])}")
    else:
        st.caption("🧺 담은 종목 없음 — 표에서 체크박스를 선택해주세요.")
    return picked_df


def render_tuning_run_results(run_id: int, key_prefix: str) -> None:
    """저장된 StrategyTuningRun 1건의 결과 표 + 3-way 비교 차트 + 라이브러리 저장 버튼을 렌더링한다.

    "다종목 미세튜닝"(백본을 여러 종목에 적용)과 "알고리즘 자동 생성"(백지에서 만든 전략 + 교차검증)
    양쪽 다 결과를 StrategyTuningRun/StrategyTuningResult에 같은 형태로 저장하므로(core.strategy_tuning
    참고) 이 렌더링 로직을 그대로 공유한다. key_prefix는 두 탭이 같은 rerun에서 동시에 이 함수를
    호출해도 위젯 key가 충돌하지 않게 한다.
    """
    run_data = strategy_tuning.get_tuning_run(run_id)
    if run_data is None:
        st.warning("해당 실행 결과를 찾을 수 없습니다.")
        return

    ok_rows = [r for r in run_data["results"] if not r.get("error") and r.get("tuned_config")]
    error_rows = [r for r in run_data["results"] if r.get("error")]
    if error_rows:
        st.caption(f"⚠️ {len(error_rows)}개 종목은 데이터 조회/실행 실패로 결과에서 제외되었습니다.")

    if not ok_rows:
        st.warning("표시할 결과가 없습니다.")
        return

    table_df = pd.DataFrame(
        [
            {
                "티커": r["ticker"],
                "섹터": r.get("sector") or "-",
                "유형": r.get("style_type") or "-",
                "초과수익(%)": r.get("excess_return"),
                "전략 CAGR(%)": (r.get("test_comparison") or {}).get("strategy", {}).get("cagr"),
                "종목홀딩 CAGR(%)": (r.get("test_comparison") or {}).get("buy_and_hold_ticker", {}).get("cagr"),
                "S&P500 CAGR(%)": (r.get("test_comparison") or {}).get("buy_and_hold_benchmark", {}).get("cagr"),
                "샤프": (r.get("test_comparison") or {}).get("strategy", {}).get("sharpe"),
                "MDD(%)": (r.get("test_comparison") or {}).get("strategy", {}).get("mdd"),
                "경고": len(r.get("health_warnings") or []),
                "백본변경": "🧬 예" if r.get("backbone_changed") else "-",
            }
            for r in ok_rows
        ]
    )

    col_sort, col_topn = st.columns(2)
    with col_sort:
        sort_option = st.selectbox(
            "정렬 기준 (기본: 초과수익 = 전략 CAGR - S&P500 매수보유 CAGR)",
            ["초과수익(%)", "전략 CAGR(%)", "샤프", "MDD(%)"], key=f"{key_prefix}_sort_option",
        )
    with col_topn:
        top_n = st.number_input(
            "표시할 상위 개수", min_value=1, max_value=len(table_df),
            value=min(20, len(table_df)), key=f"{key_prefix}_top_n",
        )

    sorted_df = table_df.sort_values(sort_option, ascending=False, na_position="last").reset_index(drop=True)
    display_df = sorted_df.head(int(top_n))

    st.markdown(f"#### 결과 ({len(display_df)}/{len(sorted_df)}종목 표시, {sort_option} 기준 정렬)")
    st.caption("표에서 행을 클릭해 직접 종목을 선택하면 아래에 3-way 비교 차트가 표시됩니다 (선택 없으면 상위 3종목).")
    selection_event = st.dataframe(
        display_df, use_container_width=True, hide_index=True,
        on_select="rerun", selection_mode="multi-row", key=f"{key_prefix}_result_table",
    )

    selected_rows = (
        selection_event.selection.rows if selection_event and getattr(selection_event, "selection", None) else []
    )
    selected_tickers = (
        display_df.iloc[selected_rows]["티커"].tolist() if selected_rows else display_df.head(3)["티커"].tolist()
    )

    results_by_ticker = {r["ticker"]: r for r in ok_rows}
    period_choice = st.radio(
        "비교 기간", ["test 구간(out-of-sample)", "전체 기간"], key=f"{key_prefix}_period_choice", horizontal=True
    )

    for sel_ticker in selected_tickers:
        r = results_by_ticker.get(sel_ticker)
        if r is None:
            continue
        st.markdown(f"##### {sel_ticker} ({r.get('style_type')}, {r.get('sector') or '-'})")

        if period_choice == "test 구간(out-of-sample)" and r.get("train_metrics") is not None:
            _, _, chart_start, chart_end = strategy_tuning.train_test_split_dates(
                run_data["start_date"].isoformat(), run_data["end_date"].isoformat(), run_data["train_ratio"]
            )
        else:
            chart_start = run_data["start_date"].isoformat()
            chart_end = run_data["end_date"].isoformat()

        try:
            chart_results = compare_with_benchmarks(sel_ticker, r["tuned_config"], chart_start, chart_end)
            st.plotly_chart(render_equity_comparison(chart_results), use_container_width=True)
            st.dataframe(metrics_dataframe(chart_results, list(METRIC_LABELS.keys())), use_container_width=True)
        except Exception as e:
            st.warning(f"{sel_ticker} 차트 생성 실패: {e}")

        for w in r.get("health_warnings") or []:
            st.warning(f"{sel_ticker}: {w}")

        with st.expander(f"{sel_ticker} 튜닝된 전략 JSON"):
            st.json(r["tuned_config"])

        if st.button(f"📚 {sel_ticker} 전략을 라이브러리에 저장", key=f"{key_prefix}_save_{sel_ticker}"):
            with st.spinner("전략 설명 생성 중..."):
                explanation = explain_strategy(r["tuned_config"])
            with get_session() as session:
                saved_strategy = Strategy(
                    name=f"{sel_ticker} 미세튜닝 ({r.get('style_type')}, run#{run_data['id']})",
                    indicator_config=json.dumps(r["tuned_config"], ensure_ascii=False),
                    source="tuning_engine",
                    description=(
                        f"{explanation}\n\n[튜닝 메타데이터] 실행 id={run_data['id']}, 종목 유형={r.get('style_type')}, "
                        f"초과수익={r.get('excess_return')}%, 백본 전략 id={run_data.get('base_strategy_id')}."
                    ),
                )
                session.add(saved_strategy)
                session.flush()
                saved_id = saved_strategy.id
            st.success(f"'{sel_ticker}' 전략 저장 완료 (id={saved_id}).")
            st.info(f"📖 전략 설명: {explanation}")


tab_backtest, tab_nl, tab_tuning, tab_combine = st.tabs(
    ["📊 지표 조합 백테스트", "🤖 자연어 전략 등록", "🧬 다종목 미세튜닝", "🧩 전략 합성"]
)

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
                        st.session_state["loaded_strategy_description"] = strategy.description
                        st.rerun()

    if st.session_state.get("loaded_strategy_id") is not None and st.session_state.get(
        "loaded_strategy_description"
    ):
        st.info(f"📖 전략 설명: {st.session_state['loaded_strategy_description']}")

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
                    st.caption(
                        f"진입/청산 이벤트 {len(strategy_run.stage_events)}건 발생 "
                        "(차트 위 삼각형 마커에 마우스를 올리면 진입/청산 근거를 확인할 수 있습니다)"
                    )
            else:
                if is_expression_config(indicator_config):
                    st.caption("직접 수식 전략은 지표 오버레이 없이 캔들차트만 표시합니다.")
                st.caption("차트 위 삼각형 마커에 마우스를 올리면 진입/청산 근거를 확인할 수 있습니다.")
                st.plotly_chart(
                    render_price_chart(
                        strategy_run.df, indicator_config.get("conditions", []), strategy_run.trades
                    ),
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

            with st.expander("📊 국면별(강세장/약세장/중립) 수익률 분해"):
                st.caption(
                    "S&P500 기준으로 하루하루를 강세장/약세장/중립으로 라벨링한 뒤, 이 전략이 "
                    "각 국면에 속한 날들에는 대체로 어떻게 움직였는지 모아서 계산한 참고 지표입니다 "
                    "(연속 구간이 아니어도 됨 — 국면별 스코어링은 core.market_regime 재사용)."
                )
                regime_breakdown = compute_regime_breakdown(strategy_run)
                if regime_breakdown:
                    breakdown_df = pd.DataFrame(
                        [
                            {
                                "국면": label,
                                "거래일수": info["trading_days"],
                                "누적수익률(%)": info["cumulative_return"],
                            }
                            for label, info in regime_breakdown.items()
                        ]
                    )
                    st.dataframe(breakdown_df, use_container_width=True, hide_index=True)
                else:
                    st.info("벤치마크 데이터를 가져올 수 없어 국면별 분해를 계산하지 못했습니다.")

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
                    with st.spinner("전략 설명 생성 중..."):
                        explanation = explain_strategy(indicator_config)
                    with get_session() as session:
                        strategy = Strategy(
                            name=strategy_name,
                            indicator_config=json.dumps(indicator_config, ensure_ascii=False),
                            source="manual",
                            description=explanation,
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
                    st.info(f"📖 전략 설명: {explanation}")

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

with tab_combine:
    st.markdown(
        "전략 라이브러리에 저장된 서로 다른 두 전략을 골라 신호를 **AND**(둘 다 보유 신호일 때만 진입) "
        "또는 **OR**(하나라도 보유 신호면 진입)로 합친 새 전략을 만듭니다. 하위 전략은 레짐(AND/OR)/"
        "직접 수식/1:2:6 단계별/전략 합성 중 어떤 유형이든 자유롭게 조합할 수 있습니다(1:2:6 단계별 "
        "전략은 비중>0인 구간을 보유 중으로 간주해 결합합니다)."
    )

    with get_session() as session:
        combine_strategies = session.query(Strategy).order_by(Strategy.created_at.desc()).all()
        combine_options = {
            f"{s.name} (#{s.id}, {STRATEGY_TYPE_LABELS[detect_strategy_type(s.indicator_config)]})": s.id
            for s in combine_strategies
        }

    if len(combine_options) < 2:
        st.info(
            "전략을 합치려면 전략 라이브러리에 최소 2개의 전략이 저장되어 있어야 합니다. "
            "다른 탭에서 전략을 먼저 저장해주세요."
        )
    else:
        col_pick_a, col_pick_b = st.columns(2)
        with col_pick_a:
            combine_label_a = st.selectbox("전략 A", list(combine_options.keys()), key="combine_pick_a")
        with col_pick_b:
            combine_label_b = st.selectbox(
                "전략 B", list(combine_options.keys()), index=1, key="combine_pick_b"
            )

        combine_logic = st.radio(
            "결합 방식",
            ["AND", "OR"],
            key="combine_logic",
            horizontal=True,
            format_func=lambda x: "AND (둘 다 보유 신호일 때만 진입)" if x == "AND" else "OR (하나라도 보유 신호면 진입)",
        )

        combine_id_a = combine_options[combine_label_a]
        combine_id_b = combine_options[combine_label_b]
        if combine_id_a == combine_id_b:
            st.warning("전략 A와 전략 B가 같습니다. 결과는 원본 전략과 동일해집니다.")

        with get_session() as session:
            combine_strategy_a = session.get(Strategy, combine_id_a)
            combine_strategy_b = session.get(Strategy, combine_id_b)
            combine_config_a = json.loads(combine_strategy_a.indicator_config) if combine_strategy_a else None
            combine_config_b = json.loads(combine_strategy_b.indicator_config) if combine_strategy_b else None
            combine_name_a = combine_strategy_a.name if combine_strategy_a else "?"
            combine_name_b = combine_strategy_b.name if combine_strategy_b else "?"

        if combine_config_a is None or combine_config_b is None:
            st.warning("선택한 전략을 찾을 수 없습니다 (이미 삭제되었을 수 있음).")
        else:
            combined_config = {"combine": combine_logic, "strategies": [combine_config_a, combine_config_b]}

            with st.expander("합성된 전략 JSON 미리보기"):
                st.json(combined_config)

            st.divider()

            col_combine_ticker, col_combine_start, col_combine_end = st.columns(3)
            with col_combine_ticker:
                combine_ticker = st.text_input("종목 티커", value="AAPL", key="combine_ticker").strip().upper()
            with col_combine_start:
                combine_start_date = st.date_input(
                    "시작일", value=date.today() - timedelta(days=365 * 3), key="combine_start_date"
                )
            with col_combine_end:
                combine_end_date = st.date_input("종료일", value=date.today(), key="combine_end_date")

            if st.button("🚀 합성 전략 백테스트 실행", type="primary", key="combine_run_btn"):
                if not combine_ticker:
                    st.warning("종목 티커를 입력해주세요.")
                elif combine_start_date >= combine_end_date:
                    st.warning("시작일은 종료일보다 빨라야 합니다.")
                else:
                    st.session_state["combine_pending_config"] = combined_config
                    st.session_state["combine_pending_ticker"] = combine_ticker
                    st.session_state["combine_pending_start"] = combine_start_date.isoformat()
                    st.session_state["combine_pending_end"] = combine_end_date.isoformat()
                    job_manager.start(
                        "combine_backtest_run", compare_with_benchmarks,
                        combine_ticker, combined_config,
                        combine_start_date.isoformat(), combine_end_date.isoformat(),
                        benchmark_ticker=DEFAULT_BENCHMARK_TICKER,
                        label=f"{combine_ticker} 합성 전략 백테스트",
                    )

            combine_job = job_manager.render("combine_backtest_run", running_label="합성 전략 백테스트 실행 중")
            if combine_job is not None:
                if combine_job.status == "error":
                    st.error(f"백테스트 실행 중 오류가 발생했습니다: {combine_job.error}")
                else:
                    st.session_state["combine_last_results"] = combine_job.result
                    st.session_state["combine_last_config"] = st.session_state["combine_pending_config"]
                    st.session_state["combine_last_ticker"] = st.session_state["combine_pending_ticker"]
                    st.session_state["combine_last_start"] = st.session_state["combine_pending_start"]
                    st.session_state["combine_last_end"] = st.session_state["combine_pending_end"]

            combine_results = st.session_state.get("combine_last_results")
            if combine_results is not None:
                combine_strategy_run: BacktestRun = combine_results["strategy"]
                if combine_strategy_run.df.empty:
                    st.error(
                        f"{st.session_state['combine_last_ticker']} 데이터를 가져오지 못했습니다. "
                        "티커를 확인해주세요."
                    )
                else:
                    st.markdown("#### 캔들차트")
                    st.caption(
                        "전략 합성은 지표 오버레이 없이 캔들차트만 표시합니다. "
                        "마우스 휠로 확대/축소, 드래그로 화면 이동이 가능합니다."
                    )
                    st.plotly_chart(
                        render_price_chart(combine_strategy_run.df, [], combine_strategy_run.trades),
                        use_container_width=True,
                        config=TRADINGVIEW_CHART_CONFIG,
                    )

                    st.markdown("#### 전략 vs 매수보유 비교 (자산가치, 시작=100)")
                    st.plotly_chart(render_equity_comparison(combine_results), use_container_width=True)

                    st.markdown("#### 성과 지표")
                    combine_selected_metrics = st.multiselect(
                        "표시할 지표 선택",
                        options=list(METRIC_LABELS.keys()),
                        default=list(METRIC_LABELS.keys()),
                        format_func=lambda m: METRIC_LABELS[m],
                        key="combine_metrics_select",
                    )
                    if combine_selected_metrics:
                        st.dataframe(
                            metrics_dataframe(combine_results, combine_selected_metrics),
                            use_container_width=True,
                        )
                    else:
                        st.info("표시할 지표를 1개 이상 선택하세요.")

                    st.markdown("#### 이 합성 전략을 라이브러리에 저장")
                    col_combine_name, col_combine_save = st.columns([3, 1])
                    with col_combine_name:
                        combine_name = st.text_input(
                            "전략 이름",
                            value=f"{combine_name_a} {combine_logic} {combine_name_b}",
                            key="combine_name_input",
                        )
                    with col_combine_save:
                        st.write("")
                        st.write("")
                        if st.button("💾 저장", use_container_width=True, key="combine_save_btn"):
                            with st.spinner("전략 설명 생성 중..."):
                                combine_explanation = explain_strategy(st.session_state["combine_last_config"])
                            with get_session() as session:
                                saved_combined = Strategy(
                                    name=combine_name,
                                    indicator_config=json.dumps(
                                        st.session_state["combine_last_config"], ensure_ascii=False
                                    ),
                                    source="strategy_combination",
                                    description=(
                                        f"{combine_explanation}\n\n[합성 메타데이터] "
                                        f"전략A id={combine_id_a}({combine_name_a}), "
                                        f"전략B id={combine_id_b}({combine_name_b}), 결합={combine_logic}."
                                    ),
                                )
                                session.add(saved_combined)
                                session.flush()
                                combine_saved_id = saved_combined.id

                            save_backtest_result(
                                strategy_id=combine_saved_id,
                                ticker=st.session_state["combine_last_ticker"],
                                start=st.session_state["combine_last_start"],
                                end=st.session_state["combine_last_end"],
                                metrics=combine_strategy_run.metrics,
                                extra_metrics={
                                    "buy_and_hold_ticker": combine_results["buy_and_hold_ticker"].metrics,
                                    "buy_and_hold_benchmark": combine_results["buy_and_hold_benchmark"].metrics,
                                },
                            )
                            st.success(f"합성 전략 '{combine_name}' 저장 완료 (id={combine_saved_id}).")
                            st.info(f"📖 전략 설명: {combine_explanation}")

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
                        render_price_chart(
                            preview_run.df,
                            nl_result["indicator_config"]["conditions"],
                            preview_run.trades,
                        ),
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
            with st.spinner("전략 설명 생성 중..."):
                explanation = explain_strategy(nl_result["indicator_config"])
            with get_session() as session:
                strategy = Strategy(
                    name=candidate_name,
                    indicator_config=json.dumps(nl_result["indicator_config"], ensure_ascii=False),
                    source="youtube_script",
                    description=f"{explanation}\n\n[원문 스크립트]\n{st.session_state.get('nl_raw_text', '')}",
                )
                session.add(strategy)
                session.flush()
                saved_id = strategy.id
            st.success(f"전략 '{candidate_name}' 저장 완료 (id={saved_id}). '지표 조합 백테스트' 탭에서 불러와 실행하세요.")
            st.info(f"📖 전략 설명: {explanation}")
            del st.session_state["nl_result"]

with tab_tuning:
    st.markdown(
        "유튜브 등에서 소개된 전략(백본)을 S&P500 섹터 균등 표본(기본 100종목)에 적용합니다. 종목을 "
        "먼저 **주도주/성장주/가치주/경기민감주/경기방어주/퀄리티 컴파운더** 6개 스타일로 나누고, "
        "**같은 스타일 종목들을 하나의 데이터셋으로 묶어** 그 그룹 전체에 공통으로 잘 맞는 파라미터 "
        "하나를 찾습니다(종목마다 따로 최적화하지 않음 — 한 종목에만 우연히 맞는 과최적화를 피하기 "
        "위함). 그렇게 찾은 그룹 공통 설정은 test(최근, out-of-sample) 구간에서 종목별로 개별 검증만 "
        "받고, 그 test 결과는 파라미터 선택에는 전혀 반영하지 않습니다 — 그래야 여기서 이겼다는 결과가 "
        "실제 미래 성과와도 관련이 있습니다.\n\n"
        "**그래도 그룹 평균이 test 구간에서 S&P500을 못 이기면** Gemini가 제안한 구조가 다른 대안을 "
        "1회성으로 시도합니다(레짐/1:2:6/직접수식 전략 모두 해당 — 결과 표의 '백본변경' 컬럼으로 확인 "
        "가능). 그래도 못 이기는 그룹/종목은 감추지 않고 그대로 보여줍니다 — 승률을 인위적으로 "
        "끌어올리기 위해 test 구간을 선택 기준에 섞지는 않습니다."
    )

    tuning_source = st.radio(
        "백본 전략 선택 방식", ["📚 전략 라이브러리에서 선택", "✍️ 새 텍스트 붙여넣기"],
        key="tuning_source", horizontal=True,
    )

    tuning_base_config: Optional[dict] = None
    tuning_base_strategy_id: Optional[int] = None

    if tuning_source == "📚 전략 라이브러리에서 선택":
        with get_session() as session:
            tuning_strategies = session.query(Strategy).order_by(Strategy.created_at.desc()).all()
            tuning_options = {f"{s.name} (#{s.id})": s.id for s in tuning_strategies}
        if not tuning_options:
            st.info("저장된 전략이 없습니다. 다른 탭에서 전략을 먼저 저장하거나 '새 텍스트 붙여넣기'를 사용하세요.")
        else:
            tuning_picked_label = st.selectbox("백본 전략", list(tuning_options.keys()), key="tuning_backbone_pick")
            tuning_base_strategy_id = tuning_options[tuning_picked_label]
            with get_session() as session:
                picked_strategy = session.get(Strategy, tuning_base_strategy_id)
                if picked_strategy is not None:
                    tuning_base_config = json.loads(picked_strategy.indicator_config)
    else:
        tuning_raw_text = st.text_area(
            "전략 설명 붙여넣기", height=160, key="tuning_raw_text",
            placeholder="예: 볼린저 밴드 하단을 이탈한 뒤 상승 인걸(장악형) 캔들이 나오면 10% 진입, "
                        "RSI가 30을 상향 돌파하면 나머지 비중을 크게 추가 진입합니다...",
        )
        if st.button("🤖 AI로 해석하기", key="tuning_interpret_btn"):
            if not tuning_raw_text.strip():
                st.warning("전략 설명을 입력해주세요.")
            else:
                job_manager.start("tuning_interpret", interpret_strategy_text, tuning_raw_text, label="튜닝용 전략 해석")

        tuning_interpret_job = job_manager.render("tuning_interpret", running_label="전략을 해석하는 중")
        if tuning_interpret_job is not None:
            if tuning_interpret_job.status == "error":
                st.error(f"전략 해석 중 오류가 발생했습니다: {tuning_interpret_job.error}")
            else:
                st.session_state["tuning_nl_result"] = tuning_interpret_job.result

        tuning_nl_result = st.session_state.get("tuning_nl_result")
        if tuning_nl_result is not None:
            st.info(tuning_nl_result["description"])
            st.json(tuning_nl_result["indicator_config"])
            tuning_base_config = tuning_nl_result["indicator_config"]

    if tuning_base_config is not None:
        st.divider()

        with st.expander("🔍 튜닝 대상 파라미터 미리보기", expanded=False):
            if "expression" in tuning_base_config:
                tuning_expr_for_preview = tuning_base_config["expression"]
                st.caption(
                    "직접 수식(expression) 전략은 AI가 수식 안 숫자의 튜닝 가능 여부/역할을 판별해야 "
                    "미리 볼 수 있습니다(버튼 클릭 시 1회 AI 호출)."
                )
                if st.button("🤖 AI로 튜닝 파라미터 식별", key="tuning_param_preview_btn"):
                    job_manager.start(
                        "tuning_param_identify", strategy_tuning.identify_tunable_numbers,
                        tuning_expr_for_preview, label="튜닝 파라미터 식별",
                    )
                preview_job = job_manager.render("tuning_param_identify", running_label="수식 분석 중")
                if preview_job is not None:
                    if preview_job.status == "error":
                        st.error(f"분석 중 오류가 발생했습니다: {preview_job.error}")
                    else:
                        st.session_state["tuning_param_preview_expr"] = tuning_expr_for_preview
                        st.session_state["tuning_param_preview_tunables"] = preview_job.result

                if st.session_state.get("tuning_param_preview_expr") == tuning_expr_for_preview:
                    tunables = st.session_state.get("tuning_param_preview_tunables") or []
                    if not tunables:
                        st.info("이 수식에서는 튜닝 가능한 숫자를 찾지 못했습니다 (원본 그대로 사용됩니다).")
                    else:
                        expr_rows = strategy_tuning.describe_tunable_params_expression(tunables)
                        expr_preview_df = pd.DataFrame(
                            [
                                {
                                    "수식 텍스트": r["text"],
                                    "역할": r["role"],
                                    "원본값": r["original"],
                                    **{style: f"{lo}~{hi}" for style, (lo, hi) in r["style_ranges"].items()},
                                }
                                for r in expr_rows
                            ]
                        )
                        st.dataframe(expr_preview_df, use_container_width=True, hide_index=True)
            else:
                param_rows = strategy_tuning.describe_tunable_params(tuning_base_config)
                if not param_rows:
                    st.info("이 전략에는 튜닝 가능한 숫자 파라미터가 없습니다 (원본 그대로 사용됩니다).")
                else:
                    st.caption(
                        "스타일별 값은 종목 스타일 분류 결과에 따라 그룹마다 실제로 사용될 탐색 범위입니다. "
                        "'비중배분'(weight) 항목은 entry_stages/exit_stages 각각의 합계가 항상 100%가 "
                        "되도록 재조정되므로, 실제 채택값은 다른 단계의 값에 따라 표시된 범위에서 소폭 "
                        "밀릴 수 있습니다."
                    )
                    param_preview_df = pd.DataFrame(
                        [
                            {
                                "위치": r["path"],
                                "지표": r["indicator"],
                                "파라미터": r["key"],
                                "원본값": r["original"],
                                "분류": r["category"],
                                **{style: f"{lo}~{hi}" for style, (lo, hi) in r["style_ranges"].items()},
                            }
                            for r in param_rows
                        ]
                    )
                    st.dataframe(param_preview_df, use_container_width=True, hide_index=True)

        tuning_universe_mode = st.radio(
            "종목 표본 방식", ["🎲 자동 섹터 균등 표본", "🧺 직접 선택"], key="tuning_universe_mode", horizontal=True
        )

        manual_tickers_df: Optional[pd.DataFrame] = None
        tuning_universe_n = 100

        if tuning_universe_mode == "🎲 자동 섹터 균등 표본":
            tuning_universe_n = st.number_input(
                "표본 종목 수", min_value=10, max_value=200, value=100, step=10, key="tuning_universe_n"
            )
        else:
            manual_tickers_df = render_ticker_picker(
                "tuning",
                "아래 목록을 마우스 휠로 스크롤하면서 원하는 종목의 체크박스를 클릭해 담으세요 "
                "(담은 종목만 미세튜닝 대상이 됩니다).",
            )

        col_intensity, col_ratio = st.columns(2)
        with col_intensity:
            tuning_intensity = st.select_slider(
                "탐색 강도 (파라미터 후보 개수: 빠름 20 / 보통 60 / 정밀 150)",
                options=["빠름", "보통", "정밀"], value="보통", key="tuning_intensity",
            )
        with col_ratio:
            tuning_train_ratio = st.slider(
                "Train 비율 (나머지는 test/out-of-sample 검증용)",
                min_value=0.5, max_value=0.9, value=0.75, step=0.05, key="tuning_train_ratio",
            )

        col_tstart, col_tend = st.columns(2)
        with col_tstart:
            tuning_start_date = st.date_input(
                "시작일", value=date.today() - timedelta(days=365 * 5), key="tuning_start_date"
            )
        with col_tend:
            tuning_end_date = st.date_input("종료일", value=date.today(), key="tuning_end_date")

        is_manual_mode = tuning_universe_mode == "🧺 직접 선택"

        use_point_in_time = False
        if not is_manual_mode:
            use_point_in_time = st.checkbox(
                "🕰️ 생존자 편향 방지: 시작일 기준 실제 S&P500 편입종목만 표본으로 사용",
                value=False, key="tuning_use_point_in_time",
                help=(
                    "체크 안 하면(기본값) '지금 시점' S&P500 전체가 표본 후보입니다 — 지금 지수에 "
                    "남아있는 종목은 이미 최근 몇 년간 크게 오른 생존자들이라 백테스트 성과가 낙관적으로 "
                    "나올 수 있습니다(survivorship bias). 체크하면 위 '시작일' 기준으로 그 시점에 실제 "
                    "S&P500에 속해 있던 종목만 후보로 삼습니다(fja05680/sp500 공개 데이터 기반, "
                    "core/point_in_time_universe.py). 이후 지수에서 편출됐지만 상장폐지는 안 된 종목도 "
                    "표본에 남을 수 있는 대신, 상장폐지까지 간 종목은 yfinance에 가격 데이터가 없어 "
                    "여전히 빠질 수 있습니다(알려진 한계)."
                ),
            )

        if st.button("🚀 다종목 미세튜닝 실행", type="primary", key="tuning_run_btn"):
            if tuning_start_date >= tuning_end_date:
                st.warning("시작일은 종료일보다 빨라야 합니다.")
            elif is_manual_mode and (manual_tickers_df is None or manual_tickers_df.empty):
                st.warning("직접 선택 모드에서는 종목을 1개 이상 담아야 합니다.")
            else:
                run_label = f"{len(manual_tickers_df)}종목 미세튜닝" if is_manual_mode else f"{tuning_universe_n}종목 미세튜닝"
                job_manager.start(
                    "tuning_batch", strategy_tuning.run_and_save_tuning,
                    tuning_base_config, int(tuning_universe_n),
                    tuning_start_date.isoformat(), tuning_end_date.isoformat(),
                    train_ratio=tuning_train_ratio, intensity=tuning_intensity,
                    base_strategy_id=tuning_base_strategy_id,
                    tickers_df=manual_tickers_df if is_manual_mode else None,
                    universe_as_of_date=tuning_start_date.isoformat() if use_point_in_time else None,
                    label=run_label,
                )

    tuning_job = job_manager.render(
        "tuning_batch", running_label="다종목 미세튜닝 실행 중 (종목 수/탐색 강도에 따라 수 분 소요될 수 있습니다)"
    )
    if tuning_job is not None:
        if tuning_job.status == "error":
            st.error(f"튜닝 실행 중 오류가 발생했습니다: {tuning_job.error}")
        else:
            st.session_state["tuning_last_run_id"] = tuning_job.result
            st.success(f"튜닝 완료 (실행 id={tuning_job.result}). 아래에서 결과를 확인하세요.")

    st.divider()
    with st.expander("📜 과거 튜닝 실행 이력"):
        tuning_history = strategy_tuning.list_tuning_runs()
        if tuning_history:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "id": h["id"], "종목수": h["universe_size"], "시작일": h["start_date"],
                            "종료일": h["end_date"], "탐색강도": h["intensity"], "생성일": h["created_at"],
                        }
                        for h in tuning_history
                    ]
                ),
                use_container_width=True, hide_index=True,
            )
            pick_run_id = st.number_input(
                "결과를 볼 실행 id", min_value=0, value=tuning_history[0]["id"], step=1, key="tuning_pick_run_id"
            )
            if st.button("이 실행 결과 보기", key="tuning_load_history_btn"):
                st.session_state["tuning_last_run_id"] = int(pick_run_id)
                st.rerun()
        else:
            st.caption("아직 실행 이력이 없습니다.")

    tuning_run_id = st.session_state.get("tuning_last_run_id")
    if tuning_run_id:
        run_data = strategy_tuning.get_tuning_run(int(tuning_run_id))
        if run_data is None:
            st.warning("해당 실행 결과를 찾을 수 없습니다.")
        else:
            ok_rows = [r for r in run_data["results"] if not r.get("error") and r.get("tuned_config")]
            error_rows = [r for r in run_data["results"] if r.get("error")]
            if error_rows:
                st.caption(f"⚠️ {len(error_rows)}개 종목은 데이터 조회/실행 실패로 결과에서 제외되었습니다.")

            if not ok_rows:
                st.warning("표시할 결과가 없습니다.")
            else:
                table_df = pd.DataFrame(
                    [
                        {
                            "티커": r["ticker"],
                            "섹터": r.get("sector") or "-",
                            "유형": r.get("style_type") or "-",
                            "학습국면": r.get("trained_regime") or "-",
                            "초과수익(%)": r.get("excess_return"),
                            "전략 CAGR(%)": (r.get("test_comparison") or {}).get("strategy", {}).get("cagr"),
                            "종목홀딩 CAGR(%)": (r.get("test_comparison") or {}).get("buy_and_hold_ticker", {}).get("cagr"),
                            "S&P500 CAGR(%)": (r.get("test_comparison") or {}).get("buy_and_hold_benchmark", {}).get("cagr"),
                            "샤프": (r.get("test_comparison") or {}).get("strategy", {}).get("sharpe"),
                            "MDD(%)": (r.get("test_comparison") or {}).get("strategy", {}).get("mdd"),
                            "경고": len(r.get("health_warnings") or []),
                            "백본변경": "🧬 예" if r.get("backbone_changed") else "-",
                            "데이터부족": "⚠️ 예" if r.get("insufficient_regime_data") else "-",
                        }
                        for r in ok_rows
                    ]
                )

                st.markdown("#### 스타일×국면 그룹별 요약")
                st.caption(
                    "같은 스타일·같은 학습국면의 종목들은 동일한 tuned_config를 공유합니다(그룹 단위로 "
                    "학습했다는 뜻) — 같은 스타일이어도 학습국면(약세장/강세장)이 다르면 서로 다른 "
                    "설정입니다(S&P500 기준 실제 국면 구간 데이터로 각각 따로 학습). 승률은 test 구간에서 "
                    "종목홀딩·S&P500을 둘 다 이긴 종목의 비율입니다. '데이터부족'은 조회 구간 안에 해당"
                    "국면 구간이 부족해 원본 전략을 그대로 사용했다는 뜻입니다."
                )
                group_summary_df = (
                    table_df.assign(
                        이김=lambda d: (d["전략 CAGR(%)"] > d["종목홀딩 CAGR(%)"])
                        & (d["전략 CAGR(%)"] > d["S&P500 CAGR(%)"])
                    )
                    .groupby(["유형", "학습국면"])
                    .agg(
                        종목수=("티커", "count"),
                        **{"평균초과수익(%)": ("초과수익(%)", "mean")},
                        승률=("이김", "mean"),
                        백본변경=("백본변경", lambda s: (s == "🧬 예").any()),
                        데이터부족=("데이터부족", lambda s: (s == "⚠️ 예").any()),
                    )
                    .reset_index()
                )
                group_summary_df["평균초과수익(%)"] = group_summary_df["평균초과수익(%)"].round(2)
                group_summary_df["승률(%)"] = (group_summary_df.pop("승률") * 100).round(0)
                group_summary_df["백본변경"] = group_summary_df["백본변경"].map({True: "🧬 예", False: "-"})
                group_summary_df["데이터부족"] = group_summary_df["데이터부족"].map({True: "⚠️ 예", False: "-"})
                st.dataframe(
                    group_summary_df.sort_values("평균초과수익(%)", ascending=False),
                    use_container_width=True, hide_index=True,
                )

                with st.expander("🧪 튜닝 리포트 (파라미터를 왜 이렇게 바꿨는지 — 다중 구간 워크포워드)"):
                    st.caption(
                        "각 스타일×국면 그룹의 train 구간 안에서(국면별 트레이닝은 실제로 그 국면이었던 "
                        "연속 구간들을) 폴드로 나눠 후보별로 독립 평가한 뒤, 폴드 간 평균 − 표준편차×0.5로 "
                        "점수를 매겨 채택했습니다(특정 시기에만 우연히 맞는 후보에 패널티). 점수가 높을수록 "
                        "여러 시기에 걸쳐 안정적이라는 뜻이지, test/실전에서 시장을 이긴다는 보장은 아닙니다."
                    )
                    for style, regime in sorted(
                        {(r.get("style_type") or "-", r.get("trained_regime") or "-") for r in ok_rows}
                    ):
                        rep_row = next(
                            r for r in ok_rows
                            if (r.get("style_type") or "-") == style and (r.get("trained_regime") or "-") == regime
                        )
                        trail = rep_row.get("tuning_trail") or []
                        if not trail:
                            continue
                        st.markdown(f"**{style} · {regime} 학습** ({len(trail)}개 후보 평가, 점수 내림차순 상위 10개 표시)")
                        trail_df = pd.DataFrame(
                            [
                                {
                                    "순위": i + 1,
                                    "채택": "✅" if i == 0 else "",
                                    "파라미터": _describe_candidate_compact(t["config"]),
                                    "폴드별 샤프": " / ".join(f"{s:+.2f}" for s in t["fold_sharpes"]),
                                    "평균": t["mean_sharpe"],
                                    "표준편차": t["std_sharpe"],
                                    "점수": t["score"],
                                }
                                for i, t in enumerate(trail[:10])
                            ]
                        )
                        st.dataframe(trail_df, use_container_width=True, hide_index=True)

                st.divider()
                col_sort, col_topn = st.columns(2)
                with col_sort:
                    tuning_sort_option = st.selectbox(
                        "정렬 기준 (기본: 초과수익 = 전략 CAGR - S&P500 매수보유 CAGR)",
                        ["초과수익(%)", "전략 CAGR(%)", "샤프", "MDD(%)"], key="tuning_sort_option",
                    )
                with col_topn:
                    tuning_top_n = st.number_input(
                        "표시할 상위 개수", min_value=1, max_value=len(table_df),
                        value=min(20, len(table_df)), key="tuning_top_n",
                    )

                sorted_df = table_df.sort_values(
                    tuning_sort_option, ascending=False, na_position="last"
                ).reset_index(drop=True)
                display_df = sorted_df.head(int(tuning_top_n))

                st.markdown(f"#### 결과 ({len(display_df)}/{len(sorted_df)}종목 표시, {tuning_sort_option} 기준 정렬)")
                st.caption("표에서 행을 클릭해 직접 종목을 선택하면 아래에 3-way 비교 차트가 표시됩니다 (선택 없으면 상위 3종목).")
                selection_event = st.dataframe(
                    display_df, use_container_width=True, hide_index=True,
                    on_select="rerun", selection_mode="multi-row", key="tuning_result_table",
                )

                selected_rows = (
                    selection_event.selection.rows
                    if selection_event and getattr(selection_event, "selection", None)
                    else []
                )
                # 종목당 국면(약세장/강세장)별로 2행이 나올 수 있어 티커만으로는 결과를 특정할 수 없다 —
                # (티커, 학습국면) 조합을 키로 써서 선택/조회한다.
                selected_keys = (
                    list(display_df.iloc[selected_rows][["티커", "학습국면"]].itertuples(index=False, name=None))
                    if selected_rows
                    else list(display_df.head(3)[["티커", "학습국면"]].itertuples(index=False, name=None))
                )

                results_by_key = {(r["ticker"], r.get("trained_regime") or "-"): r for r in ok_rows}
                tuning_period_choice = st.radio(
                    "비교 기간", ["test 구간(out-of-sample)", "전체 기간"], key="tuning_period_choice", horizontal=True
                )

                for sel_ticker, sel_regime in selected_keys:
                    r = results_by_key.get((sel_ticker, sel_regime))
                    if r is None:
                        continue
                    st.markdown(f"##### {sel_ticker} ({r.get('style_type')}, {sel_regime} 학습, {r.get('sector') or '-'})")

                    if tuning_period_choice == "test 구간(out-of-sample)":
                        _, _, chart_start, chart_end = strategy_tuning.train_test_split_dates(
                            run_data["start_date"].isoformat(), run_data["end_date"].isoformat(), run_data["train_ratio"]
                        )
                    else:
                        chart_start = run_data["start_date"].isoformat()
                        chart_end = run_data["end_date"].isoformat()

                    try:
                        chart_results = compare_with_benchmarks(sel_ticker, r["tuned_config"], chart_start, chart_end)
                        st.plotly_chart(render_equity_comparison(chart_results), use_container_width=True)
                        st.dataframe(
                            metrics_dataframe(chart_results, list(METRIC_LABELS.keys())), use_container_width=True
                        )
                    except Exception as e:
                        st.warning(f"{sel_ticker} 차트 생성 실패: {e}")

                    for w in r.get("health_warnings") or []:
                        st.warning(f"{sel_ticker}: {w}")

                    with st.expander(f"{sel_ticker} ({sel_regime} 학습) 튜닝된 전략 JSON"):
                        st.json(r["tuned_config"])

                    era_job_slot = f"era_validate_{sel_ticker}_{sel_regime}"
                    with st.expander(f"🌍 {sel_ticker} ({sel_regime} 학습) 시대별 강건성 재검증"):
                        st.caption(
                            "이 train/test 구간이 우연히 한 방향(상승/하락)으로만 치우친 시기여서 "
                            "튜닝된 파라미터가 그 시기에만 맞는 건 아닌지, 재튜닝 없이 같은 설정을 "
                            "닷컴버블 붕괴/2008 금융위기/코로나 충격+회복/2022 금리인상 약세장/2010년대 "
                            "중반 횡보 구간 등 성격이 뚜렷하게 다른 5개 과거 시대에 그대로 적용해 "
                            "재검증합니다(core/era_validation.py). 이 종목이 해당 시대의 실제 S&P500 "
                            "편입종목이 아니었으면(point-in-time 확인) 그 시대는 자동으로 건너뜁니다."
                        )
                        if st.button("🌍 시대별 재검증 실행", key=f"era_validate_btn_{sel_ticker}_{sel_regime}"):
                            job_manager.start(
                                era_job_slot, era_validation.validate_across_eras,
                                r["tuned_config"], [sel_ticker],
                                label=f"{sel_ticker} 시대별 재검증",
                            )
                        era_job = job_manager.render(era_job_slot, running_label="시대별 재검증 실행 중 (5개 시대 x 백테스트)")
                        if era_job is not None:
                            if era_job.status == "error":
                                st.error(f"재검증 중 오류가 발생했습니다: {era_job.error}")
                            else:
                                era_result = era_job.result
                                st.metric("시대 강건성 점수 (초과수익 양수였던 시대 비율)", f"{era_result['era_robustness_score']:.0%}")
                                era_df = pd.DataFrame(
                                    [
                                        {
                                            "시대": era_name,
                                            "평균 초과수익(%)": stats.get("mean_excess_return"),
                                            "승률": stats.get("win_ratio"),
                                            "검증 종목수": stats.get("n_tickers_tested"),
                                            "PIT 데이터 없어 제외": stats.get("n_tickers_skipped_no_pit_data"),
                                        }
                                        for era_name, stats in era_result["per_era"].items()
                                    ]
                                )
                                st.dataframe(era_df, use_container_width=True, hide_index=True)

                    if st.button(
                        f"📚 {sel_ticker} ({sel_regime} 학습) 튜닝 전략을 라이브러리에 저장",
                        key=f"tuning_save_{sel_ticker}_{sel_regime}",
                    ):
                        with st.spinner("전략 설명 생성 중..."):
                            explanation = explain_strategy(r["tuned_config"])
                        with get_session() as session:
                            saved_strategy = Strategy(
                                name=f"{sel_ticker} 미세튜닝 ({r.get('style_type')}, {sel_regime} 학습, run#{run_data['id']})",
                                indicator_config=json.dumps(r["tuned_config"], ensure_ascii=False),
                                source="tuning_engine",
                                description=(
                                    f"{explanation}\n\n[튜닝 메타데이터] 실행 id={run_data['id']}, "
                                    f"종목 유형={r.get('style_type')}, 학습국면={sel_regime}, "
                                    f"test 구간 초과수익={r.get('excess_return')}%, "
                                    f"백본 전략 id={run_data.get('base_strategy_id')}."
                                ),
                            )
                            session.add(saved_strategy)
                            session.flush()
                            saved_id = saved_strategy.id
                        st.success(f"'{sel_ticker}' 튜닝 전략 저장 완료 (id={saved_id}).")
                        st.info(f"📖 전략 설명: {explanation}")
