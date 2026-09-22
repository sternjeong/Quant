"""Streamlit 앱 진입점과 업무공간 내비게이션 라우터."""

import sys
from pathlib import Path

# --- sys.path 부트스트랩: 프로젝트 루트를 추가해 core.* 임포트 가능하게 함 ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

from core.app_navigation import NAVIGATION
from core.db import init_db

init_db()

pages = {
    section: [
        st.Page(spec.path, title=spec.title, icon=spec.icon, default=spec.default)
        for spec in specs
    ]
    for section, specs in NAVIGATION.items()
}
st.navigation(pages, position="sidebar", expanded=True).run()
