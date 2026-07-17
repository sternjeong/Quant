"""모듈 A 확장: 전략 관리 페이지.

백테스팅 엔진(1_백테스팅.py)에서 저장한 전략(레짐형 AND/OR + 1:2:6 단계별)을 한눈에 모아보고
이름/설명/조건(JSON)을 수정하거나 삭제한다. 백테스트 실행 자체는 '백테스팅 엔진' 페이지에서 한다.
"""

import json
import sys
from pathlib import Path

# --- sys.path 부트스트랩: 프로젝트 루트를 추가해 core.* 임포트 가능하게 함 (app/pages/*.py 공통 규칙) ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import streamlit as st

from core.db import init_db
from core.strategy_explainer import explain_strategy
from core.strategy_library import delete_strategy, get_strategy, list_strategies, update_strategy
from core.theme import apply_theme

init_db()

st.set_page_config(page_title="전략 관리", page_icon="🗂️", layout="wide")
apply_theme()
st.title("🗂️ 전략 관리")
st.caption("저장된 전략의 이름/설명/조건(JSON)을 수정하거나 삭제합니다. 백테스트 실행/신규 등록은 '백테스팅 엔진' 페이지에서 합니다.")

TYPE_LABELS = {
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


strategies = list_strategies()

if not strategies:
    st.info("아직 저장된 전략이 없습니다. '백테스팅 엔진' 페이지에서 전략을 만들고 저장해보세요.")
    st.stop()

st.markdown("### 전략 목록")
overview_df = pd.DataFrame(
    {
        "id": pd.array([s["id"] for s in strategies], dtype="int64"),
        "이름": pd.array([s["name"] for s in strategies], dtype="string"),
        "유형": pd.array([TYPE_LABELS[s["strategy_type"]] for s in strategies], dtype="string"),
        "출처": pd.array([s["source"] or "-" for s in strategies], dtype="string"),
        "관심종목 연결": pd.array([s["watchlist_count"] for s in strategies], dtype="int64"),
        "백테스트 결과": pd.array([s["backtest_result_count"] for s in strategies], dtype="int64"),
        "생성일": pd.to_datetime([s["created_at"] for s in strategies]),
    }
)
st.dataframe(overview_df, use_container_width=True, hide_index=True)

st.divider()
st.markdown("### 전략 수정 / 삭제")

label_by_id = {s["id"]: f"{s['name']} (#{s['id']}, {TYPE_LABELS[s['strategy_type']]})" for s in strategies}
picked_id = st.selectbox("전략 선택", options=[s["id"] for s in strategies], format_func=lambda i: label_by_id[i])

strategy = get_strategy(picked_id)
if strategy is None:
    st.warning("선택한 전략을 찾을 수 없습니다 (이미 삭제되었을 수 있음).")
    st.stop()

st.caption(
    f"관련 관심종목 {strategy['watchlist_count']}개, 저장된 백테스트 결과 {strategy['backtest_result_count']}건이 이 전략에 연결되어 있습니다."
)

regen_key = f"regen_description_{strategy['id']}"
if st.button("🤖 AI로 설명 재생성", key=f"regen_btn_{strategy['id']}"):
    with st.spinner("전략 설명 생성 중..."):
        st.session_state[regen_key] = explain_strategy(json.loads(strategy["indicator_config"]))
    st.rerun()
st.caption("전략을 처음 저장할 때 자동으로 만들어진 설명입니다. 예전에 저장한 전략이라 설명이 부실하면 위 버튼으로 다시 생성할 수 있습니다.")

with st.form(f"edit_strategy_{strategy['id']}"):
    name_val = st.text_input("이름", value=strategy["name"])
    description_val = st.text_area(
        "설명", value=st.session_state.pop(regen_key, None) or strategy["description"], height=120
    )
    config_val = st.text_area(
        "조건 (indicator_config, JSON) — 직접 수정 가능",
        value=_pretty_json(strategy["indicator_config"]),
        height=340,
    )
    save_clicked = st.form_submit_button("💾 저장", type="primary")

if save_clicked:
    try:
        update_strategy(strategy["id"], name=name_val, description=description_val, indicator_config=config_val)
        st.toast(f"'{name_val}' 저장 완료.", icon="✅")
        st.rerun()
    except ValueError as e:
        st.error(f"저장 실패: {e}")

st.divider()
st.markdown("#### ⚠️ 위험 구역")

pending_key = "confirm_delete_strategy_id"
if st.session_state.get(pending_key) == strategy["id"]:
    st.warning(
        f"'{strategy['name']}' 전략을 정말 삭제할까요? 저장된 백테스트 결과 {strategy['backtest_result_count']}건은 "
        f"함께 삭제되고, 연결된 관심종목 {strategy['watchlist_count']}개는 전략 연결만 해제됩니다(관심종목 자체는 남음). "
        "되돌릴 수 없습니다."
    )
    c1, c2 = st.columns(2)
    if c1.button("🗑️ 삭제 확정", type="primary", use_container_width=True):
        delete_strategy(strategy["id"])
        st.session_state[pending_key] = None
        st.toast(f"'{strategy['name']}' 삭제 완료.", icon="🗑️")
        st.rerun()
    if c2.button("취소", use_container_width=True):
        st.session_state[pending_key] = None
        st.rerun()
else:
    if st.button("🗑️ 이 전략 삭제"):
        st.session_state[pending_key] = strategy["id"]
        st.rerun()
