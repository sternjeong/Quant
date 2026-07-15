"""Streamlit 멀티페이지 앱 진입점.

실행: streamlit run app/Home.py

컨벤션 (중요, 이후 app/pages/ 에 페이지를 추가하는 모든 모듈이 지켜야 함):
- `streamlit run app/Home.py` 로 실행하면 streamlit은 이 파일이 있는 app/ 디렉터리만
  sys.path에 넣어준다. core/ 는 프로젝트 루트에 있으므로, core.* 를 임포트하려면
  아래와 동일한 sys.path 부트스트랩 코드를 각 페이지 파일 최상단에도 그대로 복사해서 넣는다.
- 각 페이지는 app/pages/ 아래에 "{순번}_{한글이름}.py" 형식으로 만든다.
  (자세한 규칙은 app/pages/ 디렉터리 설명 참고, Home.py 하단 안내 문구에도 명시)
"""

import sys
from pathlib import Path

# --- sys.path 부트스트랩: 프로젝트 루트를 추가해 core.* 임포트 가능하게 함 ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

from core.db import init_db
from core.theme import apply_theme

st.set_page_config(
    page_title="개인용 주식 도우미",
    page_icon="📈",
    layout="wide",
)
apply_theme()

# 앱 최초 실행 시 DB/테이블이 없으면 생성
init_db()

st.title("📈 개인용 주식 도우미")
st.caption("나 혼자 쓰는 미국 주식 전략 검증 · 모니터링 · 리서치 대시보드")

st.markdown(
    """
왼쪽 사이드바에서 각 기능 페이지로 이동하세요. (모듈이 추가될 때마다 사이드바 목록도 자동으로 늘어납니다)

### 이 프로젝트가 하는 일

1. **전략 검증** — 유튜브 등에서 본 매매 전략을 과거 데이터로 백테스팅해서 정말 통하는지 확인합니다.
2. **관심 종목 자동 감시** — 검증된 전략을 관심 종목(최대 50개)에 매일 적용해, 타점이 뜨면 알림을 보냅니다.
3. **리서치 보조** — Threads 글 요약, 거장 포트폴리오 추종, 퀀트 스크리너, 밸류에이션, 매크로 지표, 내 포트폴리오 분석까지
   한 곳에서 확인합니다.

### 모듈 구성

| 모듈 | 내용 |
|---|---|
| A. 백테스팅 엔진 | 이동평균/RSI/볼린저밴드 등 지표 조합 전략을 과거 데이터로 검증, 자연어 전략 등록 |
| B. Threads 요약 | 원문 붙여넣기 → AI가 티커 인식 + 요약, 티커별 히스토리 누적 |
| C. 관심 티커 + 타점 모니터링 | 관심 종목 최대 50개, 매일 장마감 후 스캔 → 대시보드 표시 + 데스크톱 알림 |
| D. 거장 포트폴리오 추종 | SEC EDGAR 13F 기반 유명 펀드매니저 보유 종목 추적, ETF/펀드 구성종목 조회 |
| E. 퀀트 스크리너 | PER/PBR/시가총액/섹터/기술적 지표 등으로 전체 종목 필터링 |
| F. 밸류에이션 도구 | PER/PBR 밴드, 피어 비교, DCF/DDM 등 여러 방법론 동시 비교 |
| G. 매크로 대시보드 | FRED 기반 경제지표, 경기 사이클/섹터 로테이션 |
| H. 포트폴리오 관리 | 내 실제 보유 종목 손익/리스크 분석, AI 코멘트 |
| (부가) 차트 조회 | 백테스트 없이 티커+봉 주기(분~월봉)만으로 TradingView 스타일 캔들차트 바로 보기 |
| (부가) 섹터 리더/성장주 관계 분석 | 섹터별 대표 ETF·대장주(시총 1위)·성장주(이익성장률 상위)를 자동 선정해 베타/상관계수/상대강도 비교 |

### 참고

- 이 앱과는 별도로 `scheduler/run_scheduler.py` 를 항상 백그라운드에서 실행해두어야
  브라우저를 열지 않아도 매일 장마감 후 타점 알림을 받을 수 있습니다.
- 실행/설치 방법은 프로젝트 루트의 `README.md` 를 참고하세요.
    """
)

with st.sidebar:
    st.header("페이지 추가 규칙")
    st.caption(
        "app/pages/ 아래에 `{순번}_{이름}.py` 형식으로 파일을 추가하면 "
        "이 사이드바에 자동으로 노출됩니다. 예: `1_백테스팅.py`, `2_Threads_요약.py`"
    )
