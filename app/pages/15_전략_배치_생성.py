"""전략 배치 생성 (신규 페이지, 2026-07-17): 유튜브 스크립트 여러 개 → 백본 전략 다량 생성.

STRATEGY_BATCH_GENERATION_SPEC.md 참고. 야간 미세튜닝(core.strategy_tuning, 이미 저장된 백본 하나를
숫자 파라미터만 다듬는 것)과 완전히 다른 목적 — "미세튜닝할 원본 백본 자체"를 다량으로 만든다.
core.nl_strategy.interpret_strategy_text()(단건 해석, 1_백테스팅.py "🤖 자연어 전략 등록" 탭이 이미
씀)를 스크립트 여러 개에 반복 적용하고, 표본 종목 5개로 즉시 sanity 백테스트해 죽은 전략인지
참고 신호를 붙인 뒤, 사용자가 직접 골라 전략 라이브러리에 저장하게 한다(자동 저장/자동 튜닝 큐
편입 없음 — 사용자 확정).
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import json

import pandas as pd
import streamlit as st

from core import job_manager
from core.db import get_session, init_db
from core.models import Strategy
from core.nl_strategy import generate_strategies_from_scripts, split_batch_scripts
from core.strategy_engine import is_staged_config
from core.strategy_explainer import explain_strategy
from core.theme import apply_theme

init_db()

st.set_page_config(page_title="전략 배치 생성", page_icon="🏭", layout="wide")
apply_theme()
st.title("🏭 전략 배치 생성")

st.markdown(
    "유튜브 등에서 본 매매 전략 스크립트를 **여러 개** 한 번에 붙여넣으면, 각각을 독립적으로 AI가 "
    "해석해서 백본 전략 후보를 만듭니다. 야간 미세튜닝은 '이미 있는 백본 하나'의 숫자만 다듬는 "
    "것이고, 이 페이지는 그 미세튜닝의 **재료가 될 백본 자체를 다량으로 늘리는** 용도입니다.\n\n"
    "각 스크립트는 줄 하나에 `---`만 있는 구분선으로 나눠서 붙여넣으세요(5-15개 기준 설계, 그 이상도 "
    "가능하지만 스크립트당 AI 호출 1-2회 + 표본 종목 5개 백테스트가 들어가 시간이 비례해서 늘어납니다)."
)

with st.expander("📖 이 페이지가 인식하는 지표(주요 예시) — RSI/거래량/볼린저 등"):
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
    st.stop()

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
                strategy = Strategy(
                    name=save_name,
                    indicator_config=json.dumps(r["indicator_config"], ensure_ascii=False),
                    source="배치생성",
                    description=f"{explanation}\n\n{sanity_summary}\n\n[원문 스크립트]\n{r['script']}",
                )
                session.add(strategy)
                session.flush()
                saved_id = strategy.id
            st.success(f"전략 '{save_name}' 저장 완료 (id={saved_id}). '전략 관리'/'다종목 미세튜닝'에서 이어서 쓰세요.")
