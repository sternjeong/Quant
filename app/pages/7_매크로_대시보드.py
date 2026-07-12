"""모듈 G: 매크로 대시보드 페이지.

FRED API 기반 경제지표 히스토리를 보여주고, 실질 GDP 증가율/실업률 추세로 경기 사이클 국면을
간이 추정해 국면별 아웃퍼폼 섹터(로테이션 참고표)를 함께 보여준다.
"""

import sys
from pathlib import Path

# --- sys.path 부트스트랩: 프로젝트 루트를 추가해 core.* 임포트 가능하게 함 (app/pages/*.py 공통 규칙) ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import plotly.graph_objects as go
import streamlit as st

from core.db import init_db
from core.fred_data import DEFAULT_INDICATORS, get_indicator_snapshot, get_series, is_configured
from core import job_manager
from core.macro_cycle import determine_cycle_phase, get_sector_rotation_table, yoy_growth
from core.theme import apply_theme

init_db()

st.set_page_config(page_title="매크로 대시보드", page_icon="🌐", layout="wide")
apply_theme()
job_manager.render_active_jobs_sidebar()
st.title("🌐 매크로 대시보드")
st.caption("FRED(연준) 경제지표 히스토리와 경기 사이클 국면 추정 + 섹터 로테이션 참고표를 보여줍니다.")

if not is_configured():
    st.warning(
        "FRED_API_KEY가 설정되지 않았습니다. `.env` 파일에 키를 채워넣으면 실제 지표를 볼 수 있습니다 "
        "([fred.stlouisfed.org/docs/api/api_key.html](https://fred.stlouisfed.org/docs/api/api_key.html)에서 무료 발급). "
        "지금은 섹터 로테이션 참고표만 표시합니다."
    )

tab_indicators, tab_cycle = st.tabs(["📊 경제지표", "🔄 경기 사이클 / 섹터 로테이션"])

# ============================================================================
# 탭 1: 경제지표 카드 + 히스토리 차트
# ============================================================================
with tab_indicators:
    if is_configured():
        job_manager.ensure("fred_snapshot", "snapshot", get_indicator_snapshot, label="FRED 지표 조회")
        fred_job = job_manager.render("fred_snapshot", running_label="FRED 데이터를 가져오는 중")
        snapshot = fred_job.result

        cols = st.columns(3)
        for i, row in enumerate(snapshot):
            with cols[i % 3]:
                if row["latest_value"] is not None:
                    st.metric(row["label"], f"{row['latest_value']:,.2f}{row['unit']}", help=f"기준일: {row['latest_date']}")
                else:
                    st.metric(row["label"], "데이터 없음")

        st.divider()
        indicator_id = st.selectbox(
            "히스토리 차트로 볼 지표", list(DEFAULT_INDICATORS.keys()), format_func=lambda k: DEFAULT_INDICATORS[k]["label"]
        )
        series = next((r["series"] for r in snapshot if r["series_id"] == indicator_id), None)
        if series is not None and not series.empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=series.index, y=series.values, name=indicator_id))
            fig.update_layout(title=DEFAULT_INDICATORS[indicator_id]["label"], height=400)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("이 지표의 히스토리 데이터를 가져오지 못했습니다.")
    else:
        st.info("FRED_API_KEY 설정 후 이 탭에서 기준금리/CPI/실업률/GDP 등 히스토리를 확인할 수 있습니다.")

# ============================================================================
# 탭 2: 경기 사이클 국면 + 섹터 로테이션
# ============================================================================
with tab_cycle:
    st.markdown("### 경기 사이클 국면 추정")
    st.caption(
        "실질 GDP 증가율(YoY)과 실업률 추세로 4국면(회복/확장/둔화/수축)을 간이 추정합니다. "
        "공식 경기판단이 아닌 참고용 경험칙입니다."
    )

    if is_configured():
        gdp_series = get_series("GDPC1")
        unemployment_series = get_series("UNRATE")

        if gdp_series.empty or unemployment_series.empty:
            st.warning("GDP 또는 실업률 데이터를 가져오지 못해 국면을 판단할 수 없습니다.")
        else:
            gdp_growth = yoy_growth(gdp_series, periods=4)
            result = determine_cycle_phase(gdp_growth, unemployment_series)

            if result["phase"] is None:
                st.warning(result["description"])
            else:
                st.success(f"현재 추정 국면: **{result['phase']}**")
                st.write(result["description"])
                st.markdown(f"**참고 아웃퍼폼 섹터**: {', '.join(result['sectors'])}")
    else:
        st.info("FRED_API_KEY 설정 후 이 섹션에서 실시간 국면 추정 결과를 볼 수 있습니다.")

    st.divider()
    st.markdown("### 국면별 섹터 로테이션 참고표")
    rotation_table = get_sector_rotation_table()
    rows = [
        {"국면": phase, "설명": info["description"], "아웃퍼폼 섹터": ", ".join(info["sectors"])}
        for phase, info in rotation_table.items()
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)
