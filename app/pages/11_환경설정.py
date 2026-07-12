"""환경설정 페이지: 사이드바 페이지 노출 순서를 직접 편집한다.

Streamlit 멀티페이지 앱은 app/pages/*.py 파일명 맨 앞 숫자로 사이드바 순서를 정하므로,
이 페이지는 core.page_order 를 이용해 그 파일명을 실제로 바꿔서 순서를 재배치한다.
"""

import sys
from pathlib import Path

# --- sys.path 부트스트랩: 프로젝트 루트를 추가해 core.* 임포트 가능하게 함 (app/pages/*.py 공통 규칙) ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

from core.page_order import list_pages, move_page
from core.theme import apply_theme

st.set_page_config(page_title="환경설정", page_icon="⚙️", layout="wide")
apply_theme()
st.title("⚙️ 환경설정")
st.caption(
    "왼쪽 사이드바에 페이지가 노출되는 순서를 여기서 직접 바꿀 수 있습니다. "
    "버튼을 누르면 즉시 파일명이 바뀌고, 사이드바에는 다음 새로고침(F5) 때 반영됩니다."
)

PAGES_DIR = Path(__file__).resolve().parent
THIS_FILE = Path(__file__).name

entries = list_pages(PAGES_DIR)

st.markdown("#### 페이지 순서")
for i, entry in enumerate(entries):
    is_first = i == 0
    is_last = i == len(entries) - 1
    is_self = entry.filename == THIS_FILE

    col_order, col_label, col_top, col_up, col_down, col_bottom = st.columns([1, 4, 1, 1, 1, 1])
    col_order.markdown(f"**{i + 1}**")
    col_label.markdown(f"{'🔧 ' if is_self else ''}{entry.label}" + ("  ·  *(이 페이지)*" if is_self else ""))

    if col_top.button("⏫", key=f"top_{entry.filename}", disabled=is_first, use_container_width=True, help="맨 위로"):
        move_page(PAGES_DIR, entry.filename, "top")
        st.rerun()
    if col_up.button("▲", key=f"up_{entry.filename}", disabled=is_first, use_container_width=True, help="위로"):
        move_page(PAGES_DIR, entry.filename, "up")
        st.rerun()
    if col_down.button("▼", key=f"down_{entry.filename}", disabled=is_last, use_container_width=True, help="아래로"):
        move_page(PAGES_DIR, entry.filename, "down")
        st.rerun()
    if col_bottom.button(
        "⏬", key=f"bottom_{entry.filename}", disabled=is_last, use_container_width=True, help="맨 아래로"
    ):
        move_page(PAGES_DIR, entry.filename, "bottom")
        st.rerun()

st.divider()
st.caption(
    "새 페이지 파일을 추가하면(README.md \"개발 컨벤션\" 참고) 이 목록에도 자동으로 나타납니다. "
    "이 페이지(환경설정) 자체도 원하는 위치로 옮길 수 있습니다."
)
