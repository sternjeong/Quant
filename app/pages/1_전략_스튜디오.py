"""모듈 A 통합: 전략 스튜디오 페이지 (2026-07-21 통합 — 이전 1_백테스팅.py + 9_전략_관리.py +
13_야간_미세튜닝_리더보드.py + 15_전략_배치_생성.py).

전략의 일생(생성 → 튜닝 → 저장/이력 확인 → 관리)이 서로 다른 4개 페이지에 흩어져 있던 것을
"전략"이라는 하나의 대상을 중심으로 탭으로 묶었다.

- 🛠 생성/백테스트: 이동평균 교차/RSI/볼린저밴드 토글 조합, "✍️ 직접 수식 입력"(core/expression_engine.py),
  자연어 전략 등록(AI 해석), 전략 합성(AND/OR) — 전략 적용 vs 종목 매수보유 vs S&P500 매수보유 비교
- 🧬 다종목 미세튜닝: 백본 전략을 S&P500 섹터 균등 표본에 적용해 종목 스타일별 파라미터를 자동
  탐색(train/test 분리 검증)하고 종목별 3-way 비교로 결과 확인 (core/strategy_tuning.py)
- 🏭 배치 생성: 유튜브 스크립트 여러 개 → 백본 전략 다량 생성 (구 15_전략_배치_생성.py)
- 🌙 야간 미세튜닝 리더보드: 로컬 스케줄러/GitHub Actions가 반복 튜닝한 결과를 국면×섹터로 필터링해
  검토하고 라이브러리에 저장 (구 13_야간_미세튜닝_리더보드.py)
- 🗂️ 전략 관리: 저장된 전략의 이름/설명/조건 수정, 보관/삭제 (구 9_전략_관리.py)
"""

import json
import re
import sys
from datetime import date, datetime, timedelta
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
    run_backtest,
    save_backtest_result,
)
from core.chart_rendering import render_price_chart, render_staged_price_chart
from core.db import get_session, init_db
from core.expression_engine import ExpressionError, validate_syntax
from core import job_manager
from core.models import Strategy
from core.nl_strategy import generate_strategies_from_scripts, interpret_strategy_text, split_batch_scripts
from core import era_validation, screener, strategy_tuning
from core.strategy_engine import is_expression_config, is_staged_config
from core.strategy_explainer import describe_regime_config, describe_staged_config, explain_strategy
from core.strategy_library import (
    archive_strategy,
    delete_strategy,
    detect_strategy_type,
    get_strategy,
    list_strategies,
    unarchive_strategy,
    update_strategy,
)
from core.strategy_tuning import get_top_tuning_results, list_tuning_runs
from core.theme import TRADINGVIEW_CHART_CONFIG, apply_theme

init_db()

st.set_page_config(page_title="전략 스튜디오", page_icon="📈", layout="wide")
apply_theme()
job_manager.render_active_jobs_sidebar()
st.title("📈 전략 스튜디오")
st.caption("전략 생성/백테스트부터 다종목 미세튜닝·배치 생성·야간 튜닝 리더보드·관리까지, 전략의 일생을 한 페이지에서 다룹니다.")

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
                "평균 보유일수": (r.get("test_comparison") or {}).get("strategy", {}).get("avg_holding_days"),
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


tab_backtest, tab_nl, tab_tuning, tab_combine, tab_batch, tab_nightly, tab_manage = st.tabs(
    [
        "📊 지표 조합 백테스트", "🤖 자연어 전략 등록", "🧬 다종목 미세튜닝", "🧩 전략 합성",
        "🏭 배치 생성", "🌙 야간 미세튜닝 리더보드", "🗂️ 전략 관리",
    ]
)

with tab_backtest:
    _init_ui_state()

    with get_session() as session:
        strategies = session.query(Strategy).filter(Strategy.is_archived.is_(False)).order_by(Strategy.created_at.desc()).all()
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

            with st.expander("📊 국면별(강세장/약세장/횡보장) 수익률 분해"):
                st.caption(
                    "S&P500 기준으로 하루하루를 강세장/약세장/횡보장으로 라벨링한 뒤, 이 전략이 "
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
            rows = session.query(Strategy).filter(Strategy.is_archived.is_(False)).order_by(Strategy.created_at.desc()).all()
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
        combine_strategies = session.query(Strategy).filter(Strategy.is_archived.is_(False)).order_by(Strategy.created_at.desc()).all()
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
            tuning_strategies = session.query(Strategy).filter(Strategy.is_archived.is_(False)).order_by(Strategy.created_at.desc()).all()
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

        swing_mode = st.checkbox(
            "🏄 스윙 트레이딩 모드: 보유기간 최대 6개월(126거래일) 강제",
            value=False, key="tuning_swing_mode",
            help=(
                "체크하면 탐색 단계부터 진입 후 126거래일(약 6개월)이 지나면 원래 신호와 무관하게 "
                "강제 청산한 성과로 파라미터를 고릅니다 — 장기 보유(예: 추세 끝까지 들고 가는 퀄리티 "
                "컴파운더식 파라미터)가 최적으로 뽑히는 것을 막고, 스윙 트레이더가 실제로 감당할 수 있는 "
                "결과로 튜닝합니다(SPEC 15절). 체크 안 하면(기본값) 기존과 동일하게 보유기간 제약 없이 "
                "탐색합니다."
            ),
        )

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
                    max_holding_days=strategy_tuning._SWING_MAX_HOLDING_DAYS if swing_mode else None,
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
                            "종료일": h["end_date"], "탐색강도": h["intensity"],
                            "스윙모드": "🏄 예" if h.get("max_holding_days") else "-",
                            "생성일": h["created_at"],
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
                    "학습했다는 뜻) — 같은 스타일이어도 학습국면(약세장/강세장/횡보장)이 다르면 서로 다른 "
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
                # 종목당 국면(약세장/강세장/횡보장)별로 최대 3행이 나올 수 있어 티커만으로는 결과를 특정할 수 없다 —
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


# ============================================================================
# 탭: 배치 생성 (구 15_전략_배치_생성.py)
# ============================================================================
def _render_batch_generation_tab() -> None:
    st.markdown(
        "유튜브 등에서 본 매매 전략 스크립트를 **여러 개** 한 번에 붙여넣으면, 각각을 독립적으로 AI가 "
        "해석해서 백본 전략 후보를 만듭니다. 야간 미세튜닝은 '이미 있는 백본 하나'의 숫자만 다듬는 "
        "것이고, 이 탭은 그 미세튜닝의 **재료가 될 백본 자체를 다량으로 늘리는** 용도입니다.\n\n"
        "각 스크립트는 줄 하나에 `---`만 있는 구분선으로 나눠서 붙여넣으세요(5-15개 기준 설계, 그 이상도 "
        "가능하지만 스크립트당 AI 호출 1-2회 + 표본 종목 5개 백테스트가 들어가 시간이 비례해서 늘어납니다)."
    )

    with st.expander("📖 이 탭이 인식하는 지표(주요 예시) — RSI/거래량/볼린저 등"):
        st.markdown(
            "- **추세**: 이동평균 교차(`ma_cross`), 단일 이평선 터치(`ma_touch`), MACD 교차/레벨, "
            "일목균형표(전환-기준선, 구름대, 후행스팬)\n"
            "- **과매수/과매도**: RSI 레벨/교차, 볼린저 밴드(상단/하단/중심선), %B, 밴드폭 스퀴즈-해제\n"
            "- **거래량**: `volume_spike`(직전 평균 대비 급증 — \"거래량이 터진다/실린다\"), "
            "`volume_dryup`(최근 고점 대비 급감 — \"거래량이 마른다/매물 소화\"), MFI(거래량 반영 RSI)\n"
            "- **캔들패턴**: 장악형, 마루보즈, 핀바, 도지, 인사이드바(돌파), 쌍바닥/쌍봉, 다이버전스, "
            "관통형/흑운형, 모닝/이브닝스타, 적삼병/흑삼병, 삼법형\n\n"
            "스크립트에 이런 표현이 나오면 자동으로 해당 지표로 매핑을 시도합니다 — 해석 결과의 "
            "'해석 근거' expander에서 실제로 어떤 지표가 왜 선택됐는지 확인할 수 있습니다."
        )

    scripts_text = st.text_area(
        "전략 설명 스크립트 여러 개 붙여넣기",
        height=280,
        placeholder=(
            "20일 이동평균선이 60일 이동평균선을 상향 돌파하는 골든크로스가 뜨고, "
            "동시에 거래량이 평소 대비 2배 이상 터지면 매수합니다.\n"
            "---\n"
            "RSI가 30 이하로 떨어졌다가 다시 30을 상향 돌파하면 매수하고, "
            "볼린저 밴드 상단을 터치하면 매도합니다.\n"
            "---\n"
            "거래량이 최근 고점 대비 크게 줄어드는 눌림목 구간에서 상승 인걸형 캔들이 나오면 매수합니다."
        ),
    )

    if st.button("🤖 배치 해석 + sanity 백테스트 시작", type="primary"):
        scripts = split_batch_scripts(scripts_text)
        if not scripts:
            st.warning("스크립트를 최소 1개 이상 입력해주세요 (구분선 `---` 없이 1개만 넣어도 됩니다).")
        else:
            job_manager.start(
                "batch_generate", generate_strategies_from_scripts, scripts,
                label=f"전략 배치 생성 ({len(scripts)}개 스크립트)",
            )

    batch_job = job_manager.render(
        "batch_generate", running_label="스크립트를 하나씩 해석하고 표본 종목 5개로 sanity 백테스트하는 중"
    )
    if batch_job is not None:
        if batch_job.status == "error":
            st.error(f"배치 생성 중 오류가 발생했습니다: {batch_job.error}")
        else:
            st.session_state["batch_results"] = batch_job.result

    batch_results = st.session_state.get("batch_results")

    if not batch_results:
        st.info("아직 생성된 배치 결과가 없습니다. 위에 스크립트를 붙여넣고 실행해보세요.")
        return

    n_ok = sum(1 for r in batch_results if r["ok"])
    n_passed = sum(1 for r in batch_results if r["ok"] and (r.get("sanity") or {}).get("passed"))
    col1, col2, col3 = st.columns(3)
    col1.metric("스크립트 수", f"{len(batch_results)}개")
    col2.metric("해석 성공", f"{n_ok}개")
    col3.metric("sanity 통과", f"{n_passed}개")

    st.divider()
    st.subheader("결과")

    for i, r in enumerate(batch_results):
        if not r["ok"]:
            st.error(f"**스크립트 {i + 1}**: 해석 실패 — {r.get('error')}")
            with st.expander("원문 스크립트 보기"):
                st.text(r["script"])
            continue

        sanity = r.get("sanity") or {}
        passed = sanity.get("passed")
        badge = "✅ PASS" if passed else "⚠️ sanity 미통과"
        staged = is_staged_config(r["indicator_config"])
        type_label = "🧬 1:2:6 단계별" if staged else "레짐(AND/OR)"

        header = (
            f"{badge} · **스크립트 {i + 1}: {r['name']}** ({type_label}) — "
            f"표본 5종목 평균 초과수익 "
            f"{sanity.get('avg_excess_return'):+.2f}%p" if sanity.get("avg_excess_return") is not None
            else f"{badge} · **스크립트 {i + 1}: {r['name']}** ({type_label}) — 초과수익 계산 불가"
        )
        with st.expander(header, expanded=not passed and n_passed == 0):
            st.caption(f"표본 5종목 합산 거래횟수: {sanity.get('total_trades', 0)}회")
            for w in r.get("health_warnings") or []:
                st.warning(w)
            st.info(r["description"])
            with st.popover("🔍 해석 근거(원문 스크립트) 보기"):
                st.text(r["script"])
            st.json(r["indicator_config"])

            save_key = f"batch_save_name_{i}"
            save_name = st.text_input("전략명 (수정 가능)", value=r["name"], key=save_key)
            if st.button("📚 전략 라이브러리에 저장", key=f"batch_save_btn_{i}"):
                with st.spinner("전략 설명 생성 중..."):
                    explanation = explain_strategy(r["indicator_config"])
                sanity_summary = (
                    f"[배치 생성 sanity] 표본 5종목 합산 거래횟수 {sanity.get('total_trades', 0)}회, "
                    f"평균 초과수익 {sanity.get('avg_excess_return'):+.2f}%p ({'통과' if passed else '미통과'})"
                    if sanity.get("avg_excess_return") is not None
                    else "[배치 생성 sanity] 계산 불가"
                )
                with get_session() as session:
                    batch_strategy = Strategy(
                        name=save_name,
                        indicator_config=json.dumps(r["indicator_config"], ensure_ascii=False),
                        source="배치생성",
                        description=f"{explanation}\n\n{sanity_summary}\n\n[원문 스크립트]\n{r['script']}",
                    )
                    session.add(batch_strategy)
                    session.flush()
                    saved_id = batch_strategy.id
                st.success(f"전략 '{save_name}' 저장 완료 (id={saved_id}). '전략 관리'/'다종목 미세튜닝' 탭에서 이어서 쓰세요.")


with tab_batch:
    _render_batch_generation_tab()


# ============================================================================
# 탭: 야간 미세튜닝 리더보드 (구 13_야간_미세튜닝_리더보드.py)
#
# 두 경로로 결과가 쌓인다:
# 1. **로컬 스케줄러**: scheduler/run_scheduler.py의 strategy_nightly_tuning_job()이 로컬에서
#    상시 실행 중이면 매일 한국시간 00:05~04:00에 로컬 DB(StrategyTuningRun/Result)에 쌓인다.
# 2. **GitHub Actions**: `.github/workflows/nightly_tuning.yml`이 매일 15:05 UTC(≈00:05 KST)에
#    `scripts/nightly_tuning_ci.py`를 실행해 결과를 저장소에 커밋된
#    `data/nightly_tuning_leaderboard.json`으로 남긴다.
# ============================================================================
def _render_nightly_leaderboard_tab() -> None:
    _tuning_strategy_id = 3
    _ci_leaderboard_path = PROJECT_ROOT / "data" / "nightly_tuning_leaderboard.json"

    def _load_ci_leaderboard_json() -> list[dict]:
        """GitHub Actions(scripts/nightly_tuning_ci.py)가 커밋해둔 결과 파일을 읽는다.

        core.strategy_tuning.get_top_tuning_results()와 정확히 같은 dict 형태로 저장돼 있어(그
        함수의 반환값을 그대로 json.dumps한 것) 로컬 DB 결과와 같은 코드 경로로 렌더링할 수 있다.
        다만 JSON 직렬화 과정에서 datetime이 문자열로 바뀌므로, 이후 .strftime()을 쓰는 기존 코드가
        그대로 동작하도록 다시 datetime으로 파싱해 되돌린다.
        """
        if not _ci_leaderboard_path.exists():
            return []
        try:
            records = json.loads(_ci_leaderboard_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        for r in records:
            if r.get("run_created_at"):
                try:
                    r["run_created_at"] = datetime.fromisoformat(str(r["run_created_at"]))
                except ValueError:
                    r["run_created_at"] = None
            r["_source"] = "github_actions"
        return records

    with get_session() as session:
        nightly_strategy = session.get(Strategy, _tuning_strategy_id)
        strategy_name = nightly_strategy.name if nightly_strategy else f"#{_tuning_strategy_id}"

    ci_results = _load_ci_leaderboard_json()

    st.caption(
        f"'{strategy_name}'(#{_tuning_strategy_id}) 전략을 종목 표본(매 반복 다른 시드로 재추출)과 "
        "탐색 강도(빠름/보통/정밀 순환)를 바꿔가며 반복 미세튜닝합니다. S&P500 기준 실제 약세장/강세장/ "
        "횡보장 구간의 데이터로 각각 따로 학습한 세 설정을 매번 만들어(학습국면 컬럼 참고), 두 경로(①로컬 "
        "`scheduler/run_scheduler.py` 상시 실행, ②GitHub Actions가 매일 커밋하는 "
        "`data/nightly_tuning_leaderboard.json`)로 쌓인 모든 실행 결과를 합쳐 test 구간(out-of-sample) "
        "초과수익이 가장 높은 상위 10개를 보여줍니다.\n\n"
        "①은 로컬에서 스케줄러 프로세스를 상시로 띄워둬야 결과가 쌓이고, ②는 이 저장소에 GitHub Actions "
        "워크플로가 활성화돼 있어야 결과가 쌓입니다(Streamlit Community Cloud 배포본은 ①은 못 쓰지만 "
        "②로 커밋된 파일은 저장소에 딸려오므로 그대로 볼 수 있습니다)."
    )

    all_runs = [r for r in list_tuning_runs() if r["base_strategy_id"] == _tuning_strategy_id]
    if not all_runs and not ci_results:
        st.info(
            "아직 쌓인 야간 미세튜닝 결과가 없습니다. `python scheduler/run_scheduler.py`를 로컬에서 "
            "상시 실행해두거나, GitHub Actions 워크플로(`.github/workflows/nightly_tuning.yml`)가 "
            "한 번 이상 실행되면 결과가 쌓이기 시작합니다."
        )
        return

    ncol1, ncol2, ncol3 = st.columns(3)
    ncol1.metric("로컬 스케줄러 누적 실행 횟수", f"{len(all_runs)}회")
    if all_runs:
        latest_run = max(all_runs, key=lambda r: r["created_at"])
        ncol2.metric("로컬 최근 실행 시각", latest_run["created_at"].strftime("%Y-%m-%d %H:%M"))
    else:
        ncol2.metric("로컬 최근 실행 시각", "기록 없음")
    ncol3.metric("GitHub Actions 결과 파일 건수", f"{len(ci_results)}건" if ci_results else "없음")

    db_results = get_top_tuning_results(_tuning_strategy_id, limit=50)
    for r in db_results:
        r["_source"] = "local_scheduler"

    combined = [r for r in (db_results + ci_results) if r.get("excess_return") is not None]
    combined.sort(key=lambda r: r["excess_return"], reverse=True)
    seen: set[tuple] = set()
    deduped: list[dict] = []
    for r in combined:
        key = (r.get("ticker"), str(r.get("run_created_at")), r.get("run_id"), r.get("_source"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)

    if not deduped:
        st.info("실행은 쌓였지만 유효한(성공한) 결과가 아직 없습니다.")
        return

    _swing_holding_days_threshold = strategy_tuning._SWING_MAX_HOLDING_DAYS  # 126거래일 ≈ 6개월 (SPEC 15절)

    def _duration_type(r: dict) -> str:
        """test_comparison의 실측 avg_holding_days(SPEC 15절, 완료된 매매의 평균 진입~청산 일수)를
        기준으로 스윙형/장기형을 판정한다. style_type(경기민감주 등 SPEC 4절의 6종 분류)은 원래
        "탐색 방향"을 다르게 주기 위한 축이라 보유기간과 느슨하게만 상관될 뿐 그 자체가 스윙/장기
        구분이 아니다 — 실제 보유일수가 있으면 그걸로, 없으면(구버전 결과, avg_holding_days 지표
        추가 이전에 저장됨) 판정 불가로 표시한다."""
        avg_days = ((r.get("test_comparison") or {}).get("strategy") or {}).get("avg_holding_days")
        if avg_days is None:
            return "N/A (구버전 결과)"
        return "🏄 스윙형" if avg_days <= _swing_holding_days_threshold else "🐢 장기형"

    for r in deduped:
        r["_duration_type"] = _duration_type(r)

    def _load_saved_nightly_strategies() -> list[dict]:
        """전략 라이브러리에 저장해둔 야간튜닝 결과를 국면/섹터/스타일로 파싱해 돌려준다.

        저장 시 description에 "[야간 미세튜닝 메타데이터] 학습국면=..., 섹터=..., 스타일=..."
        형태로 남겨두므로(위 저장 버튼 로직), 별도 테이블 없이 정규식으로 역파싱해 현황판을 만든다.
        """
        pattern = re.compile(r"학습국면=([^,]+), 섹터=([^,]+), 스타일=([^,]+)")
        with get_session() as session:
            rows = session.query(Strategy).filter(Strategy.source == "nightly_tuning_leaderboard").all()
            saved = []
            for s in rows:
                m = pattern.search(s.description or "")
                if not m:
                    continue
                saved.append(
                    {
                        "id": s.id,
                        "name": s.name,
                        "regime": m.group(1).strip(),
                        "sector": m.group(2).strip(),
                        "style": m.group(3).strip(),
                    }
                )
            return saved

    st.divider()
    st.subheader("📋 저장 현황판 (국면 x 섹터)")
    st.caption(
        "지금까지 전략 라이브러리에 저장한 야간튜닝 전략을 학습국면 x 섹터 매트릭스로 보여줍니다. "
        "'—'는 아직 저장하지 않은 조합, ✅ 옆은 그 조합에서 저장한 스타일(경기민감주 등 6종 분류 — "
        "보유기간 구분이 아니라 파라미터 탐색 방향을 다르게 준 축입니다, SPEC 4절)입니다."
    )
    saved_nightly_strategies = _load_saved_nightly_strategies()
    matrix_regimes = sorted({r.get("trained_regime") for r in deduped if r.get("trained_regime")})
    matrix_sectors = sorted({r.get("sector") for r in deduped if r.get("sector")})
    if not matrix_regimes or not matrix_sectors:
        st.info("현황판을 그릴 만큼 국면/섹터 정보가 담긴 결과가 아직 없습니다.")
    else:
        matrix_rows = []
        for regime in matrix_regimes:
            row = {"국면": regime}
            for sector in matrix_sectors:
                cell_saved = [s for s in saved_nightly_strategies if s["regime"] == regime and s["sector"] == sector]
                if cell_saved:
                    styles = sorted({s["style"] for s in cell_saved})
                    row[sector] = f"✅ {'/'.join(styles)}"
                else:
                    row[sector] = "—"
            matrix_rows.append(row)
        st.dataframe(pd.DataFrame(matrix_rows).set_index("국면"), use_container_width=True)
        st.caption(
            f"저장된 야간튜닝 전략 총 {len(saved_nightly_strategies)}건 "
            f"(전체 {len(matrix_regimes) * len(matrix_sectors)}개 조합 중 "
            f"{len({(s['regime'], s['sector']) for s in saved_nightly_strategies})}개 조합에서 저장됨). "
            "'전략 관리' 탭에서도 확인할 수 있습니다."
        )

    st.divider()
    st.subheader("🔎 국면 x 섹터로 좁혀보기")
    st.caption(
        "약세장/강세장/횡보장(학습국면)과 섹터를 조합해 필터링한 뒤, 그 조합에서 가장 좋은 결과를 골라 "
        "아래 '상세 보기'에서 전략 라이브러리에 저장할 수 있습니다. **'스타일'**은 종목 특성에 따라 "
        "파라미터 탐색 방향을 다르게 준 6종 분류(경기민감주/성장주/가치주/주도주/경기방어주/퀄리티 "
        "컴파운더 — SPEC 4절)로, 스윙/장기와 느슨하게만 상관될 뿐 그 자체가 보유기간 구분은 아닙니다. "
        "실제로 몇 거래일 들고 갔는지로 스윙/장기를 나누려면 **'보유기간 유형'** 필터를 쓰세요(완료된 "
        "매매의 실측 평균 보유일수 기준, SPEC 15절)."
    )
    regime_options = ["전체"] + sorted({r.get("trained_regime") for r in deduped if r.get("trained_regime")})
    sector_options = ["전체"] + sorted({r.get("sector") for r in deduped if r.get("sector")})
    style_options = ["전체"] + sorted({r.get("style_type") for r in deduped if r.get("style_type")})
    duration_options = ["전체"] + sorted({r["_duration_type"] for r in deduped})
    fcol1, fcol2, fcol3, fcol4 = st.columns(4)
    sel_regime = fcol1.selectbox("학습국면(약세장/강세장/횡보장)", regime_options)
    sel_sector = fcol2.selectbox("섹터", sector_options)
    sel_style = fcol3.selectbox(
        "스타일(6종 분류 — SPEC 4절, 보유기간과 별개)", style_options,
        help=(
            "**이건 스윙/장기 구분이 아닙니다.** 종목이 어떤 성격인지(모멘텀 강한 주도주인지, "
            "안정적인 방어주인지 등)를 6가지로 판별한 태그일 뿐입니다 — 이익성장률/PER/PBR/섹터/"
            "가격추세 같은 종목 데이터로 계산됩니다(core.strategy_tuning.compute_style_scores).\n\n"
            "다만 튜닝 엔진이 이 태그에 따라 '이평 기간 등을 원본의 몇 배 범위에서 탐색할지'를 다르게 "
            "주기는 합니다 — 예: 주도주는 원본의 0.3~0.8배(짧게), 퀄리티 컴파운더는 1.0~2.5배(길게). "
            "이 배수가 회전율에 간접적으로 영향을 주기 때문에 '느슨하게만' 스윙/장기와 관련이 있는 "
            "겁니다. 하지만 실제로 몇 거래일 들고 갔는지는 탐색 결과에 따라 달라질 수 있어(예: '주도주'로 "
            "태깅돼도 우연히 긴 이평 조합이 채택되면 오래 보유), 이 태그만으로 보유기간을 확정할 수 "
            "없습니다. → 정확한 보유기간 구분은 오른쪽 '보유기간 유형' 필터를 쓰세요."
        ),
    )
    sel_duration = fcol4.selectbox(
        "보유기간 유형(실측 평균보유일수 기준)", duration_options,
        help=(
            "**이게 진짜 스윙/장기 구분입니다.** 왼쪽 '스타일'과 달리 탐색 편향이 아니라, 실제로 "
            "백테스트에서 체결된 매매들의 진입~청산 평균 보유일수(avg_holding_days)를 직접 잰 값입니다"
            "(SPEC 15절). 126거래일(≈6개월) 이하면 🏄 스윙형, 초과면 🐢 장기형으로 분류합니다. "
            "avg_holding_days 지표 추가 이전에 저장된 구버전 결과는 이 값이 없어 'N/A'로 표시됩니다."
        ),
    )

    filtered = [
        r
        for r in deduped
        if (sel_regime == "전체" or r.get("trained_regime") == sel_regime)
        and (sel_sector == "전체" or r.get("sector") == sel_sector)
        and (sel_style == "전체" or r.get("style_type") == sel_style)
        and (sel_duration == "전체" or r["_duration_type"] == sel_duration)
    ]
    if not filtered:
        st.warning("이 조합에 해당하는 결과가 아직 없습니다. 필터를 넓혀보세요.")
        return

    top_results = filtered[:10]

    st.subheader(
        "🏆 상위 10개 (test 구간 초과수익 기준)",
        help=(
            "**방법론**: 각 종목마다 가격 이력을 시계열 순서 그대로 75% train / 25% test로 나눠, "
            "train 구간에서만 파라미터를 그리드서치(샤프 비율 최대화 + 자기모순/거래횟수 필터)로 "
            "탐색합니다. 채택된 파라미터의 성과는 결과에 전혀 관여하지 않은 test(out-of-sample) 구간으로 "
            "정직하게 재검증하고, '초과수익'(전략 CAGR − S&P500 매수보유 CAGR, test 구간 기준)이 높은 "
            "순으로 순위를 매깁니다."
        ),
    )
    leaderboard_df = pd.DataFrame(
        [
            {
                "순위": i + 1,
                "티커": r["ticker"],
                "섹터": r.get("sector") or "N/A",
                "스타일": r.get("style_type") or "N/A",
                "보유기간 유형": r["_duration_type"],
                "학습국면": r.get("trained_regime") or "N/A",
                "초과수익(%p)": r["excess_return"],
                "탐색 강도": r["run_intensity"],
                "백본변경": "🧬 예" if r.get("backbone_changed") else "-",
                "실행일시": r["run_created_at"].strftime("%Y-%m-%d %H:%M") if r.get("run_created_at") else "N/A",
                "출처": "🖥️ 로컬" if r.get("_source") == "local_scheduler" else "☁️ GitHub Actions",
            }
            for i, r in enumerate(top_results)
        ]
    )
    st.dataframe(leaderboard_df, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("🔍 상세 보기")
    ticker_options = [
        f"{i + 1}위 {r['ticker']} ({r.get('trained_regime') or 'N/A'} 학습, 초과수익 {r['excess_return']:+.2f}%p)"
        for i, r in enumerate(top_results)
    ]
    selected_idx = st.selectbox("종목 선택", range(len(top_results)), format_func=lambda i: ticker_options[i])
    selected = top_results[selected_idx]

    save_key = f"nightly_saved_{selected.get('_source')}_{selected.get('run_id')}_{selected['ticker']}"
    if st.button("📚 이 결과를 전략 라이브러리에 저장", key=f"nightly_save_btn_{selected_idx}"):
        tuned_config_to_save = selected.get("tuned_config")
        if not tuned_config_to_save:
            st.error("이 결과에는 저장할 튜닝 전략 설정이 없습니다.")
        else:
            with st.spinner("전략 설명 생성 중..."):
                explanation = explain_strategy(tuned_config_to_save)
            with get_session() as session:
                nightly_saved_strategy = Strategy(
                    name=(
                        f"{selected['ticker']} 야간튜닝 ({selected.get('trained_regime') or 'N/A'}·"
                        f"{selected.get('sector') or 'N/A'}·{selected.get('style_type') or 'N/A'})"
                    ),
                    indicator_config=json.dumps(tuned_config_to_save, ensure_ascii=False),
                    source="nightly_tuning_leaderboard",
                    description=(
                        f"{explanation}\n\n[야간 미세튜닝 메타데이터] 학습국면={selected.get('trained_regime')}, "
                        f"섹터={selected.get('sector')}, 스타일={selected.get('style_type')}, "
                        f"초과수익={selected.get('excess_return')}%p, 탐색강도={selected.get('run_intensity')}, "
                        f"출처={'로컬' if selected.get('_source') == 'local_scheduler' else 'GitHub Actions'}."
                    ),
                )
                session.add(nightly_saved_strategy)
                session.flush()
                saved_id = nightly_saved_strategy.id
            st.session_state[save_key] = saved_id
            st.success(f"'{selected['ticker']}' ({selected.get('trained_regime')}·{selected.get('sector')}) 전략을 라이브러리에 저장했습니다 (id={saved_id}).")

    if st.session_state.get(save_key):
        st.caption(f"✅ 이미 저장됨 (전략 id={st.session_state[save_key]}). 다시 눌러도 새 항목으로 추가 저장됩니다.")

    test_comparison = selected.get("test_comparison") or {}
    if test_comparison:
        metrics_rows = []
        for label, key in [
            ("튜닝 전략", "strategy"),
            (f"{selected['ticker']} 매수보유", "buy_and_hold_ticker"),
            ("S&P500 매수보유", "buy_and_hold_benchmark"),
        ]:
            m = test_comparison.get(key) or {}
            metrics_rows.append(
                {
                    "구분": label,
                    "누적수익률(%)": m.get("cumulative_return"),
                    "CAGR(%)": m.get("cagr"),
                    "MDD(%)": m.get("mdd"),
                    "샤프지수": m.get("sharpe"),
                    "승률(%)": m.get("win_rate"),
                    "매매횟수": m.get("trade_count"),
                }
            )
        st.dataframe(pd.DataFrame(metrics_rows), use_container_width=True, hide_index=True)
    else:
        st.info("이 결과에는 test 구간 비교 지표가 저장되어 있지 않습니다.")

    st.subheader("📉 진입/청산 시점 차트")
    st.caption(
        "위 표의 test 구간(out-of-sample)과 같은 기간에 채택된 튜닝 전략을 다시 적용해, 캔들차트 위에 "
        "실제 진입/청산 지점을 삼각형 마커로 표시합니다 (전략 스튜디오의 차트 렌더링을 그대로 재사용)."
    )
    chart_state_key = f"nightly_chart_visible_{selected_idx}"
    if st.button("📈 이 종목 차트 보기", key=f"nightly_chart_btn_{selected_idx}"):
        st.session_state[chart_state_key] = True

    if st.session_state.get(chart_state_key):
        tuned_config_for_chart = selected.get("tuned_config")
        run_start, run_end, train_ratio = (
            selected.get("run_start_date"),
            selected.get("run_end_date"),
            selected.get("train_ratio"),
        )
        if not tuned_config_for_chart:
            st.info("이 결과에는 튜닝된 전략 설정이 저장되어 있지 않아 차트를 그릴 수 없습니다.")
        elif not (run_start and run_end and train_ratio):
            st.info("이 결과에는 실행 시점의 기간 정보가 저장되어 있지 않아 차트를 그릴 수 없습니다.")
        else:
            _, _, test_start, test_end = strategy_tuning.train_test_split_dates(run_start, run_end, train_ratio)
            with st.spinner(f"{selected['ticker']} test 구간({test_start} ~ {test_end}) 데이터 조회 중..."):
                chart_run = run_backtest(
                    selected["ticker"], tuned_config_for_chart, test_start, test_end, label="튜닝 전략"
                )
            if chart_run.df.empty:
                st.warning(f"{selected['ticker']} 가격 데이터를 가져오지 못했습니다.")
            else:
                if is_staged_config(tuned_config_for_chart):
                    fig = render_staged_price_chart(chart_run.df, tuned_config_for_chart, chart_run.stage_events)
                    event_count = len(chart_run.stage_events)
                else:
                    fig = render_price_chart(
                        chart_run.df, tuned_config_for_chart.get("conditions", []), chart_run.trades
                    )
                    event_count = len(chart_run.trades)
                st.plotly_chart(fig, use_container_width=True, config=TRADINGVIEW_CHART_CONFIG)
                st.caption(
                    f"test 구간 {test_start} ~ {test_end} 동안 진입/청산 이벤트 {event_count}건 "
                    "(마커에 마우스를 올리면 근거를 확인할 수 있습니다)."
                )

    st.subheader("🔧 실제로 바뀐 파라미터")
    nightly_base_config = selected.get("base_config") or {}
    nightly_tuned_config = selected.get("tuned_config") or {}
    if not nightly_base_config or not nightly_tuned_config:
        st.info("이 결과에는 원본/튜닝 전략 설정이 저장되어 있지 않아 비교할 수 없습니다.")
    else:
        diff = strategy_tuning.describe_tuning_diff(nightly_base_config, nightly_tuned_config)
        st.markdown(strategy_tuning.summarize_tuning_diff(diff, backbone_changed=selected.get("backbone_changed", False)))

        if diff["changes"] and diff["schema"] == "json":
            diff_df = pd.DataFrame(
                [
                    {
                        "위치": c["path"],
                        "지표": c["indicator"] or "-",
                        "이전": c["before"],
                        "이후": c["after"],
                    }
                    for c in diff["changes"]
                ]
            )
            st.dataframe(diff_df, use_container_width=True, hide_index=True)

    with st.expander("⚙️ 원본/튜닝 전략 JSON 직접 보기"):
        col_base, col_tuned = st.columns(2)
        with col_base:
            st.caption("원본(백본)")
            st.json(nightly_base_config)
        with col_tuned:
            st.caption("채택된 튜닝 결과")
            st.json(nightly_tuned_config)


with tab_nightly:
    _render_nightly_leaderboard_tab()


# ============================================================================
# 탭: 전략 관리 (구 9_전략_관리.py)
# ============================================================================
def _render_strategy_management_tab() -> None:
    type_labels = {
        "staged": "🧬 1:2:6 단계별",
        "regime": "📐 레짐(AND/OR)",
        "expression": "✍️ 직접 수식",
        "combined": "🧩 전략 합성",
    }

    def _pretty_json(raw: str) -> str:
        try:
            return json.dumps(json.loads(raw), indent=2, ensure_ascii=False)
        except json.JSONDecodeError:
            return raw

    strategies = list_strategies(include_archived=True)

    if not strategies:
        st.info("아직 저장된 전략이 없습니다. '📊 지표 조합 백테스트' 탭에서 전략을 만들고 저장해보세요.")
        return

    st.markdown("### 전략 목록")
    st.caption(
        "🗄️ 보관됨 표시가 붙은 전략은 백테스트/미세튜닝/전략 합성/관심종목 연결 등 '활성 선택' 목록에는 "
        "더 이상 나타나지 않지만, 삭제된 건 아니라 여기서 언제든 다시 복원할 수 있습니다."
    )
    overview_df = pd.DataFrame(
        {
            "id": pd.array([s["id"] for s in strategies], dtype="int64"),
            "이름": pd.array([s["name"] for s in strategies], dtype="string"),
            "유형": pd.array([type_labels[s["strategy_type"]] for s in strategies], dtype="string"),
            "상태": pd.array(["🗄️ 보관됨" if s["is_archived"] else "✅ 활성" for s in strategies], dtype="string"),
            "출처": pd.array([s["source"] or "-" for s in strategies], dtype="string"),
            "관심종목 연결": pd.array([s["watchlist_count"] for s in strategies], dtype="int64"),
            "백테스트 결과": pd.array([s["backtest_result_count"] for s in strategies], dtype="int64"),
            "생성일": pd.to_datetime([s["created_at"] for s in strategies]),
        }
    )
    st.dataframe(overview_df, use_container_width=True, hide_index=True)

    st.divider()
    st.markdown("### 전략 수정 / 삭제")

    label_by_id = {
        s["id"]: f"{'🗄️ ' if s['is_archived'] else ''}{s['name']} (#{s['id']}, {type_labels[s['strategy_type']]})"
        for s in strategies
    }
    picked_id = st.selectbox("전략 선택", options=[s["id"] for s in strategies], format_func=lambda i: label_by_id[i])

    manage_strategy = get_strategy(picked_id)
    if manage_strategy is None:
        st.warning("선택한 전략을 찾을 수 없습니다 (이미 삭제되었을 수 있음).")
        return

    st.caption(
        f"관련 관심종목 {manage_strategy['watchlist_count']}개, 저장된 백테스트 결과 "
        f"{manage_strategy['backtest_result_count']}건이 이 전략에 연결되어 있습니다."
    )

    regen_key = f"regen_description_{manage_strategy['id']}"
    if st.button("🤖 AI로 설명 재생성", key=f"regen_btn_{manage_strategy['id']}"):
        with st.spinner("전략 설명 생성 중..."):
            st.session_state[regen_key] = explain_strategy(json.loads(manage_strategy["indicator_config"]))
        st.rerun()
    st.caption("전략을 처음 저장할 때 자동으로 만들어진 설명입니다. 예전에 저장한 전략이라 설명이 부실하면 위 버튼으로 다시 생성할 수 있습니다.")

    with st.form(f"edit_strategy_{manage_strategy['id']}"):
        name_val = st.text_input("이름", value=manage_strategy["name"])
        description_val = st.text_area(
            "설명", value=st.session_state.pop(regen_key, None) or manage_strategy["description"], height=120
        )
        config_val = st.text_area(
            "조건 (indicator_config, JSON) — 직접 수정 가능",
            value=_pretty_json(manage_strategy["indicator_config"]),
            height=340,
        )
        save_clicked = st.form_submit_button("💾 저장", type="primary")

    if save_clicked:
        try:
            update_strategy(manage_strategy["id"], name=name_val, description=description_val, indicator_config=config_val)
            st.toast(f"'{name_val}' 저장 완료.", icon="✅")
            st.rerun()
        except ValueError as e:
            st.error(f"저장 실패: {e}")

    st.divider()
    st.markdown("#### 🗄️ 보관 (삭제 아님, 활성 선택 목록에서만 제외)")
    if manage_strategy["is_archived"]:
        st.caption("이 전략은 현재 보관됨 상태입니다. 복원하면 다시 백테스트/미세튜닝/전략 합성/관심종목 연결 목록에 나타납니다.")
        if st.button("♻️ 이 전략 복원", key=f"unarchive_{manage_strategy['id']}"):
            unarchive_strategy(manage_strategy["id"])
            st.toast(f"'{manage_strategy['name']}' 복원 완료.", icon="♻️")
            st.rerun()
    else:
        st.caption("보관하면 삭제되지 않고 그대로 남지만, 백테스트/미세튜닝/전략 합성/관심종목 연결 같은 '활성 선택' 목록에서만 숨겨집니다. 언제든 복원할 수 있습니다.")
        if st.button("🗄️ 이 전략 보관", key=f"archive_{manage_strategy['id']}"):
            archive_strategy(manage_strategy["id"])
            st.toast(f"'{manage_strategy['name']}' 보관 완료.", icon="🗄️")
            st.rerun()

    st.divider()
    st.markdown("#### ⚠️ 위험 구역")

    pending_key = "confirm_delete_strategy_id"
    if st.session_state.get(pending_key) == manage_strategy["id"]:
        st.warning(
            f"'{manage_strategy['name']}' 전략을 정말 삭제할까요? 저장된 백테스트 결과 "
            f"{manage_strategy['backtest_result_count']}건은 함께 삭제되고, 연결된 관심종목 "
            f"{manage_strategy['watchlist_count']}개는 전략 연결만 해제됩니다(관심종목 자체는 남음). "
            "되돌릴 수 없습니다."
        )
        dc1, dc2 = st.columns(2)
        if dc1.button("🗑️ 삭제 확정", type="primary", use_container_width=True):
            delete_strategy(manage_strategy["id"])
            st.session_state[pending_key] = None
            st.toast(f"'{manage_strategy['name']}' 삭제 완료.", icon="🗑️")
            st.rerun()
        if dc2.button("취소", use_container_width=True):
            st.session_state[pending_key] = None
            st.rerun()
    else:
        if st.button("🗑️ 이 전략 삭제"):
            st.session_state[pending_key] = manage_strategy["id"]
            st.rerun()


with tab_manage:
    _render_strategy_management_tab()
