"""Streamlit 업무공간 내비게이션 정의.

파일명의 숫자 순서가 아니라 사용자의 작업 흐름을 기준으로 사이드바를 구성한다.
Streamlit 객체를 만들지 않는 순수 데이터라 테스트와 환경설정 화면에서도 재사용할 수 있다.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PageSpec:
    path: str
    title: str
    icon: str
    default: bool = False


NAVIGATION: dict[str, tuple[PageSpec, ...]] = {
    "홈": (
        PageSpec("views/today.py", "오늘", "🏠", default=True),
    ),
    "운용": (
        PageSpec("views/11_챔피언_전략.py", "챔피언 전략", "🏆"),
        PageSpec("views/14_챔피언_성과.py", "챔피언 성과", "📒"),
        PageSpec("views/8_포트폴리오_관리.py", "포트폴리오", "💼"),
        PageSpec("views/15_포트폴리오_비교.py", "포트폴리오 비교", "⚖️"),
        PageSpec("views/16_세후_수익_계산.py", "세후 수익 계산", "🧾"),
        PageSpec("views/3_관심종목_모니터링.py", "운용 알림", "🔔"),
    ),
    "탐색": (
        PageSpec("views/5_종목_스크리닝.py", "종목 스크리닝", "🔎"),
        PageSpec("views/9_차트_조회.py", "차트 조회", "🕯️"),
        PageSpec("views/6_밸류에이션.py", "밸류에이션", "🧮"),
        PageSpec("views/4_거장_포트폴리오.py", "거장 포트폴리오", "🧠"),
    ),
    "리서치": (
        PageSpec("views/1_전략_스튜디오.py", "전략 스튜디오", "📈"),
        PageSpec("views/12_챔피언_전략_최적화.py", "챔피언 최적화", "🔬"),
        PageSpec("views/13_뉴스_리서치.py", "뉴스 리서치", "📰"),
        PageSpec("views/2_Threads_요약.py", "Threads 요약", "🧵"),
    ),
    "시장": (
        PageSpec("views/7_시장_진단.py", "시장 진단", "🌐"),
    ),
    "시스템": (
        PageSpec("views/10_환경설정.py", "환경설정", "⚙️"),
    ),
}


def all_pages() -> tuple[PageSpec, ...]:
    return tuple(page for pages in NAVIGATION.values() for page in pages)
