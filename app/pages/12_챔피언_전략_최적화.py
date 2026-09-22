"""챔피언 전략 파라미터 최적화 슬롯 (신규, 2026-09-13).

`app/pages/11_챔피언_전략.py`가 "오늘 기준" 라이브 신호 + 과거 백테스트를 보여주는 페이지라면, 이
페이지는 그 백테스트가 쓰는 튜닝 가능한 파라미터(새틀라이트 비중/코어 상위 N종목/시장필터 축소
배수/새틀라이트 top_k/새틀라이트 후보 풀 크기)를 train/test로 나눠 스윕하고, 그 결과가 "견고한지
(완만한 고원)" 아니면 "우연인지(뾰족한 피크, train에서만 좋고 test에서 갈라짐)"를 보여준다.

**이 페이지는 단일 최고 설정을 추천하지 않는다.** `core/strategy_tuning.py`가 이미 확립한 관례
(train/test 75/25 시계열 분리, `run_sensitivity_sweep`의 "이웃 값 간 완만한 변화=견고 vs 뾰족한
피크=과최적화 의심" 판정, `compute_overfitting_curve`의 "train은 계속 좋아지는데 test는 갈라지면
과최적화 시작 지점" 진단 철학)을 그대로 챔피언 전략 파라미터에 적용한 것뿐이다 — 새 방법론을
발명하지 않는다. 채택 여부는 항상 사람이 이 그래프를 보고 판단한다("데이터마이닝이 아니라 가설
하나를 검증하는 용도"라는 원칙).

핵심 로직은 core/champion_strategy.py::run_champion_param_sweep() 등 — 이 파일은 화면 구성만 담당.
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

from core import job_manager
from core.champion_strategy import CHAMPION_TUNABLE_PARAMS, run_champion_param_sweep
from core.db import init_db
from core.theme import apply_theme
from core.ui_status import render_status_header

init_db()

st.set_page_config(page_title="챔피언 전략 최적화", page_icon="🔬", layout="wide")
apply_theme()
job_manager.render_active_jobs_sidebar()

st.title("🔬 챔피언 전략 최적화 — 파라미터 민감도/견고성 분석")
render_status_header("champion_optimization")
st.caption(
    "챔피언 전략(코어+새틀라이트)의 튜닝 가능한 파라미터를 값마다 바꿔가며 train/test 구간에서 "
    "각각 성과를 계산합니다. **단일 최고 설정을 추천하지 않습니다** — train 곡선이 완만한 고원인지 "
    "뾰족한 피크인지, 그리고 train에서 최적이었던 값이 test에서도 최적이었는지를 보여줄 뿐입니다. "
    "(이 프로젝트의 기존 원칙: 이건 전략을 검증하는 용도이지, 데이터마이닝 용도가 아닙니다.)"
)

METRIC_LABELS = {
    "sharpe": "샤프지수",
    "cumulative_return": "누적수익률(%)",
    "cagr": "CAGR(%)",
    "mdd": "MDD(%)",
}

_JOB_SLOT = "champion_param_sweep"

# ----------------------------------------------------------------------------
# 입력
# ----------------------------------------------------------------------------
param_options = list(CHAMPION_TUNABLE_PARAMS.keys())
col_param, col_metric, col_ratio = st.columns([2, 1, 1])
with col_param:
    param_name = st.selectbox(
        "탐색할 파라미터",
        options=param_options,
        format_func=lambda p: CHAMPION_TUNABLE_PARAMS[p]["label"],
        key="sweep_param_name",
    )
with col_metric:
    metric = st.selectbox(
        "평가 지표", options=list(METRIC_LABELS.keys()), format_func=lambda m: METRIC_LABELS[m], key="sweep_metric"
    )
with col_ratio:
    train_ratio = st.slider("train 비율", min_value=0.5, max_value=0.9, value=0.75, step=0.05, key="sweep_train_ratio")

param_meta = CHAMPION_TUNABLE_PARAMS[param_name]
st.caption(f"현재 라이브 값: **{param_meta['current']}** · {param_meta['note']}")
if param_name in ("satellite_top_k", "satellite_pool_n"):
    st.warning(
        "⚠️ 이 파라미터는 값마다 새틀라이트 반기 point-in-time 스캔을 다시 돌립니다 — 기간이 길거나 "
        "탐색값이 많으면 수 분~수십 분 걸릴 수 있습니다. 먼저 짧은 기간(1~2년)과 좁은 값 범위로 "
        "시험해보는 것을 권장합니다."
    )

default_values_str = ", ".join(str(v) for v in param_meta["default_values"])
values_str = st.text_input(
    "탐색할 값 목록 (쉼표로 구분)", value=default_values_str, key=f"sweep_values_{param_name}"
)

col_start, col_end = st.columns(2)
with col_start:
    start_date = st.date_input("시작일", value=date.today() - timedelta(days=365 * 3), key="sweep_start")
with col_end:
    end_date = st.date_input("종료일", value=date.today(), key="sweep_end")

try:
    values = sorted({float(v.strip()) for v in values_str.split(",") if v.strip()})
except ValueError:
    values = []
    st.error("값 목록을 숫자로 해석할 수 없습니다 — 쉼표로 구분된 숫자를 입력하세요 (예: 2, 3, 4, 5).")

run_disabled = len(values) < 2 or start_date >= end_date
if run_disabled and values:
    st.error("시작일은 종료일보다 빨라야 합니다.")
elif len(values) < 2:
    st.info("탐색값을 2개 이상 입력해야 곡선을 그릴 수 있습니다.")

if st.button("🔬 파라미터 스윕 실행", disabled=run_disabled, key="run_champion_sweep"):
    job_manager.start(
        _JOB_SLOT,
        run_champion_param_sweep,
        param_name, values, str(start_date), str(end_date),
        train_ratio=train_ratio, metric=metric,
        label=f"{param_meta['label']} 스윕 ({len(values)}개 값)",
    )

sweep_job = job_manager.render(_JOB_SLOT, running_label=f"{param_meta['label']} 스윕 실행 중")
if sweep_job is not None:
    if sweep_job.status == "error":
        st.error(f"스윕 중 오류가 발생했습니다: {sweep_job.error}")
    else:
        st.session_state["champion_sweep_result"] = sweep_job.result

# ----------------------------------------------------------------------------
# 결과
# ----------------------------------------------------------------------------
result = st.session_state.get("champion_sweep_result")
if result is None:
    st.caption("아직 스윕을 실행하지 않았습니다.")
else:
    result_label = CHAMPION_TUNABLE_PARAMS.get(result["param_name"], {}).get("label", result["param_name"])
    st.markdown(f"## {result_label} — train vs test")
    st.caption(
        f"train 구간 {result['train_period'][0]} ~ {result['train_period'][1]} · "
        f"test 구간 {result['test_period'][0]} ~ {result['test_period'][1]} · "
        f"평가 지표: {METRIC_LABELS.get(result['metric'], result['metric'])}"
    )

    points = result["points"]
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=[p["value"] for p in points], y=[p["train_metric"] for p in points],
            mode="lines+markers", name="train", line=dict(width=2, color="#5B8DEF"), marker=dict(size=8),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[p["value"] for p in points], y=[p["test_metric"] for p in points],
            mode="lines+markers", name="test (out-of-sample)", line=dict(width=2, color="#F0A63C", dash="dot"),
            marker=dict(size=8),
        )
    )
    fig.update_layout(
        height=360, xaxis_title=result_label, yaxis_title=METRIC_LABELS.get(result["metric"], result["metric"]),
        template="plotly_white", margin=dict(l=10, r=10, t=30, b=10), legend=dict(orientation="h", y=1.1),
    )
    st.plotly_chart(fig, use_container_width=True)

    col_robust, col_peak = st.columns(2)
    with col_robust:
        if result["is_train_robust"] is None:
            st.info("train 유효 포인트가 2개 미만이라 견고성을 판정할 수 없습니다.")
        elif result["is_train_robust"]:
            st.success(
                f"✅ train 곡선 견고함(robust) — 이웃 값 간 최대 변화폭({result['train_max_jump']})이 "
                f"전체 값 범위({result['train_metric_range']})의 절반 이하입니다."
            )
        else:
            st.warning(
                f"⚠️ train 곡선이 특정 값 하나에서만 튑니다 (최대 변화폭 {result['train_max_jump']} / "
                f"전체 범위 {result['train_metric_range']}) — 과최적화(curve-fitting) 의심."
            )
    with col_peak:
        if result["peaks_agree"] is None:
            st.info(
                "train/test 둘 다 유효한 값이 2개 이상이어야 비교할 수 있습니다 — 지금은 비교 근거가 "
                f"부족합니다 (n_valid_train={result['n_valid_train']}, n_valid_test={result['n_valid_test']})."
            )
        elif result["peaks_agree"]:
            st.success(
                f"✅ train 최적값({result['best_train_value']})이 test에서도 최적이었습니다 "
                f"({result['best_test_value']})."
            )
        else:
            st.warning(
                f"⚠️ train에서 최적이었던 값({result['best_train_value']})이 test에서는 최적이 "
                f"아니었습니다(test 최적값: {result['best_test_value']}) — train에만 맞춰진 과최적화 신호일 "
                "수 있습니다."
            )

    with st.expander("포인트별 상세 표"):
        st.dataframe(pd.DataFrame(points), use_container_width=True, hide_index=True)

st.caption(
    "방법론: `core/strategy_tuning.py::train_test_split_dates`(75/25 시계열 분리)와 "
    "`core/backtest_engine.py::run_sensitivity_sweep`(이웃값 변화 완만함=견고 판정)을 그대로 재사용합니다 — "
    "이 페이지가 새로 발명한 통계 기법은 없습니다."
)
