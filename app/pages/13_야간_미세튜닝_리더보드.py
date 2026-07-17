"""야간 반복 미세튜닝 리더보드 (신규 페이지, 2026-07-15).

두 경로로 결과가 쌓인다:
1. **로컬 스케줄러**: scheduler/run_scheduler.py의 strategy_nightly_tuning_job()이 로컬에서
   상시 실행 중이면 매일 한국시간 00:05~04:00에 로컬 DB(StrategyTuningRun/Result)에 쌓인다.
2. **GitHub Actions** (2026-07-16 추가): `.github/workflows/nightly_tuning.yml`이 매일
   15:05 UTC(≈00:05 KST)에 `scripts/nightly_tuning_ci.py`를 실행해 결과를 저장소에 커밋된
   `data/nightly_tuning_leaderboard.json`으로 남긴다 — 로컬 스케줄러를 상시로 안 띄워도, 그리고
   Streamlit Community Cloud 배포본(별도 프로세스를 못 띄우고 DB도 매번 초기화됨)에서도 이
   JSON 파일은 저장소와 함께 그대로 딸려오므로 결과를 볼 수 있다. 이 페이지는 두 경로의 결과를
   합쳐서(중복 제거) test 구간(out-of-sample) 초과수익(excess_return) 상위 10개를 보여준다.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

# --- sys.path 부트스트랩: 프로젝트 루트를 추가해 core.* 임포트 가능하게 함 (app/pages/*.py 공통 규칙) ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import streamlit as st

from core import strategy_tuning
from core.backtest_engine import run_backtest
from core.chart_rendering import render_price_chart, render_staged_price_chart
from core.db import get_session, init_db
from core.models import Strategy
from core.strategy_engine import is_staged_config
from core.strategy_tuning import get_top_tuning_results, list_tuning_runs
from core.theme import TRADINGVIEW_CHART_CONFIG, apply_theme

init_db()

st.set_page_config(page_title="야간 미세튜닝 리더보드", page_icon="🌙", layout="wide")
apply_theme()
st.title("🌙 야간 미세튜닝 리더보드")

_TUNING_STRATEGY_ID = 3
_CI_LEADERBOARD_PATH = PROJECT_ROOT / "data" / "nightly_tuning_leaderboard.json"


def _load_ci_leaderboard_json() -> list[dict]:
    """GitHub Actions(scripts/nightly_tuning_ci.py)가 커밋해둔 결과 파일을 읽는다.

    core.strategy_tuning.get_top_tuning_results()와 정확히 같은 dict 형태로 저장돼 있어(그
    함수의 반환값을 그대로 json.dumps한 것) 로컬 DB 결과와 같은 코드 경로로 렌더링할 수 있다.
    다만 JSON 직렬화 과정에서 datetime이 문자열로 바뀌므로, 이후 .strftime()을 쓰는 기존 코드가
    그대로 동작하도록 다시 datetime으로 파싱해 되돌린다.
    """
    if not _CI_LEADERBOARD_PATH.exists():
        return []
    try:
        records = json.loads(_CI_LEADERBOARD_PATH.read_text(encoding="utf-8"))
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
    strategy = session.get(Strategy, _TUNING_STRATEGY_ID)
    strategy_name = strategy.name if strategy else f"#{_TUNING_STRATEGY_ID}"

ci_results = _load_ci_leaderboard_json()

st.caption(
    f"'{strategy_name}'(#{_TUNING_STRATEGY_ID}) 전략을 종목 표본(매 반복 다른 시드로 재추출)과 "
    "탐색 강도(빠름/보통/정밀 순환)를 바꿔가며 반복 미세튜닝합니다. S&P500 기준 실제 약세장/강세장 "
    "구간의 데이터로 각각 따로 학습한 두 설정을 매번 만들어(학습국면 컬럼 참고), 두 경로(①로컬 "
    "`scheduler/run_scheduler.py` 상시 실행, ②GitHub Actions가 매일 커밋하는 "
    "`data/nightly_tuning_leaderboard.json`)로 쌓인 모든 실행 결과를 합쳐 test 구간(out-of-sample) "
    "초과수익이 가장 높은 상위 10개를 보여줍니다.\n\n"
    "①은 로컬에서 스케줄러 프로세스를 상시로 띄워둬야 결과가 쌓이고, ②는 이 저장소에 GitHub Actions "
    "워크플로가 활성화돼 있어야 결과가 쌓입니다(Streamlit Community Cloud 배포본은 ①은 못 쓰지만 "
    "②로 커밋된 파일은 저장소에 딸려오므로 그대로 볼 수 있습니다)."
)

all_runs = [r for r in list_tuning_runs() if r["base_strategy_id"] == _TUNING_STRATEGY_ID]
if not all_runs and not ci_results:
    st.info(
        "아직 쌓인 야간 미세튜닝 결과가 없습니다. `python scheduler/run_scheduler.py`를 로컬에서 "
        "상시 실행해두거나, GitHub Actions 워크플로(`.github/workflows/nightly_tuning.yml`)가 "
        "한 번 이상 실행되면 결과가 쌓이기 시작합니다."
    )
    st.stop()

col1, col2, col3 = st.columns(3)
col1.metric("로컬 스케줄러 누적 실행 횟수", f"{len(all_runs)}회")
if all_runs:
    latest_run = max(all_runs, key=lambda r: r["created_at"])
    col2.metric("로컬 최근 실행 시각", latest_run["created_at"].strftime("%Y-%m-%d %H:%M"))
else:
    col2.metric("로컬 최근 실행 시각", "기록 없음")
col3.metric("GitHub Actions 결과 파일 건수", f"{len(ci_results)}건" if ci_results else "없음")

db_results = get_top_tuning_results(_TUNING_STRATEGY_ID, limit=50)
for r in db_results:
    r["_source"] = "local_scheduler"

combined = [r for r in (db_results + ci_results) if r.get("excess_return") is not None]
combined.sort(key=lambda r: r["excess_return"], reverse=True)
seen: set[tuple] = set()
top_results: list[dict] = []
for r in combined:
    key = (r.get("ticker"), str(r.get("run_created_at")), r.get("run_id"), r.get("_source"))
    if key in seen:
        continue
    seen.add(key)
    top_results.append(r)
    if len(top_results) >= 10:
        break

if not top_results:
    st.info("실행은 쌓였지만 유효한(성공한) 결과가 아직 없습니다.")
    st.stop()

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
    "실제 진입/청산 지점을 삼각형 마커로 표시합니다 (백테스팅 엔진의 차트 렌더링을 그대로 재사용)."
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
base_config = selected.get("base_config") or {}
tuned_config = selected.get("tuned_config") or {}
if not base_config or not tuned_config:
    st.info("이 결과에는 원본/튜닝 전략 설정이 저장되어 있지 않아 비교할 수 없습니다.")
else:
    diff = strategy_tuning.describe_tuning_diff(base_config, tuned_config)
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
        st.json(base_config)
    with col_tuned:
        st.caption("채택된 튜닝 결과")
        st.json(tuned_config)
