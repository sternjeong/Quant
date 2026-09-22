"""앱 구조와 운영 상태를 설명하는 시스템 화면."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

from core.app_navigation import NAVIGATION
from core.theme import apply_theme
from core.ui_status import render_status_header

st.set_page_config(page_title="환경설정", page_icon="⚙️", layout="wide")
apply_theme()

st.title("⚙️ 환경설정")
render_status_header("settings")
st.caption("앱의 업무공간 구성과 화면 상태 표기 원칙을 확인합니다.")

st.subheader("업무공간 내비게이션")
st.caption("사이드바는 파일명 숫자가 아니라 아래 업무 흐름으로 고정됩니다. 구성 변경은 `core/app_navigation.py`에서 관리합니다.")
for section, pages in NAVIGATION.items():
    with st.expander(section, expanded=section in {"홈", "운용"}):
        for page in pages:
            if page.default:
                st.markdown(f"**{page.icon} {page.title}** · 기본 화면")
            else:
                st.page_link(page.path, label=f"{page.icon} {page.title}", width="stretch")

st.divider()
st.subheader("상태 표기 원칙")
st.markdown(
    """
    - **Fresh**: 저장된 기준 시각이 허용 범위 안에 있습니다.
    - **Stale**: 저장된 데이터가 오래되어 재확인이 필요합니다.
    - **Unknown**: 기준 시각을 신뢰할 수 있는 저장 상태가 없습니다.
    - **PIT 미검증/혼합/부분 검증**: 과거 시점에 실제로 알 수 있었던 데이터만 사용했는지 아직 완전히 보증하지 않습니다.

    `Unknown`은 약세나 매도 신호가 아니며, `PIT 미검증`은 성과가 나쁘다는 뜻이 아니라 검증 범위를 나타냅니다.
    """
)
