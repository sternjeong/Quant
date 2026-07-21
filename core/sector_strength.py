"""모듈 G 확장: 섹터/테마 강도(상대강도) 지표.

MARKET_REGIME_SECTOR_STRENGTH_SPEC.md 참고. GICS 표준 11개 섹터는 SPDR Select Sector ETF를,
DRAM/반도체/우주처럼 GICS에 없는 세부 테마는 대표 ETF(복수면 평균)를 프록시로 사용해 IBD 스타일
RS(Relative Strength) 점수를 계산한다.

StrengthFactor = 0.4*ROC(63) + 0.2*ROC(126) + 0.2*ROC(189) + 0.2*ROC(252) (거래일 기준 12개월,
최근 3개월에 가중치를 더 준 IBD RS Rating 공식)을 테마 집합 내 percentile로 변환해 0~100 점수로
표시한다.
"""

from __future__ import annotations

import io
from datetime import date, timedelta
from typing import Optional

import pandas as pd

from core.db import get_session
from core.indicators import roc
from core.market_data import get_multiple_price_history
from core.market_regime import is_snapshot_stale_for_today_kst, to_kst  # noqa: F401 - re-export for callers
from core.models import SectorStrengthSnapshot

# core.market_data.get_price_history(start=None)는 문서와 달리, 로컬 캐시가 아예 없는 티커에
# 대해서는 yfinance의 기본 period("1mo")만 받아와 200/252일 계산에 필요한 이력이 부족해진다
# (S&P500 개별 종목/지수는 다른 기능들이 이미 여러 해 캐싱해둬서 우연히 안 걸리는 것뿐). 테마 ETF는
# 이 앱에서 처음 조회하는 티커들이라 명시적 시작일을 넘겨 이 함정을 피한다.
DEFAULT_LOOKBACK_DAYS = 800  # 252거래일(ROC) + 20거래일(추세 비교) 대비 넉넉한 여유


def _default_start() -> str:
    return (date.today() - timedelta(days=DEFAULT_LOOKBACK_DAYS)).isoformat()

# 테마명 -> 프록시 ETF 티커 리스트 (코드 프리셋, 확장 시 항목만 추가하면 됨)
#
# "기술" 세부 테마 5종(방산/냉각/사이버보안/클라우드/로보틱스, 2026-07-15 추가)은 실제로 거래되는
# 유동성 있는 테마 ETF를 리서치해 선정했다(범위 확대 방지 위해 AUM/거래대금이 충분히 확인되는
# 것만 채택 — 양자컴퓨팅/블록체인 등 신생·소형 테마 ETF는 이번엔 제외):
# - 방산: ITA(iShares US Aerospace & Defense) — 기존 "우주" 테마에 섞여 있던 대형 방산 프라임(LMT/
#   RTX/NOC 등)을 분리하려고 신설. 실무에서도 "현금흐름 안정적인 방산 프라임"과 "계약모멘텀 기반
#   고변동성 우주기업"을 별개 트레이드로 구분함(TS2 Space/Defense Outlook 2026).
# - 냉각: DTCR(Global X Data Center & Digital Infrastructure) — AI 데이터센터 액체냉각을 다루는
#   순수(pure-play) 냉각 전용 ETF는 아직 없어(2026-07 기준), 데이터센터 인프라 ETF 중 냉각/전력
#   비중이 큰 DTCR을 최선의 프록시로 채택.
# - 사이버보안: CIBR(First Trust NASDAQ Cybersecurity, AUM $10B+로 이 분야 최대 유동성).
# - 클라우드: SKYY(First Trust Cloud Computing, 대형/오래됨) + WCLD(WisdomTree Cloud Computing,
#   순수 SaaS 위주) 평균 — 반도체 테마가 SOXX+SMH 두 개를 평균하는 것과 같은 패턴.
# - 로보틱스: BOTZ(Global X Robotics & Artificial Intelligence).
THEME_UNIVERSE: dict[str, list[str]] = {
    "기술": ["XLK"],
    "금융": ["XLF"],
    "헬스케어": ["XLV"],
    "임의소비재": ["XLY"],
    "필수소비재": ["XLP"],
    "에너지": ["XLE"],
    "산업재": ["XLI"],
    "소재": ["XLB"],
    "유틸리티": ["XLU"],
    "부동산": ["XLRE"],
    "커뮤니케이션": ["XLC"],
    "반도체": ["SOXX", "SMH"],
    "메모리/DRAM": ["DRAM"],
    "우주": ["UFO", "ARKX", "ROKT"],
    "방산": ["ITA"],
    "냉각": ["DTCR"],
    "사이버보안": ["CIBR"],
    "클라우드": ["SKYY", "WCLD"],
    "로보틱스": ["BOTZ"],
    # 2026-07-17 딥서치 반영: AI 데이터센터 병목이 GPU 자체에서 "GPU 랙 간 통신"(광통신/실리콘
    # 포토닉스)과 "전력 공급"(원자력/SMR)으로 옮겨가는 추세가 뚜렷해져 신규 추가. 광통신은
    # NVIDIA가 Lumentum/Coherent에 각 $2B씩 전략 투자하고 Ciena 수주잔고가 $7B로 급증하는 등
    # 2026년 상반기 실적 모멘텀이 강한 테마라 KraneShares가 2026-07-14 전용 ETF(LUMA)를 막 상장
    # (아직 이력이 짧아 RS 점수는 데이터가 쌓일 때까지 DRAM과 같은 패턴으로 계산이 지연됨).
    # 원자력/SMR ETF(NLR)는 2007년 상장이라 이력 문제 없음.
    "광통신": ["LUMA"],
    "원자력": ["NLR"],
}

ROC_WEIGHTS: list[tuple[int, float]] = [(63, 0.4), (126, 0.2), (189, 0.2), (252, 0.2)]
TREND_LOOKBACK_DAYS = 20

# compute_theme_strength()가 반환하는 DataFrame의 컬럼 순서 — 빈 결과를 만들 때와 저장된 스냅샷을
# 복원할 때(둘 다 아래) 동일하게 재사용해 컬럼 목록이 어긋나지 않게 한다.
_THEME_STRENGTH_COLUMNS = [
    "theme", "proxies", "strength_factor", "rs_score", "return_3m", "return_6m", "return_12m",
    "trend", "trend_change",
]


def _strength_factor(close: pd.Series) -> Optional[float]:
    """IBD 스타일 가중 ROC(모멘텀 팩터)를 계산한다.

    최근 상장된 ETF(예: DRAM 메모리 ETF, 2025년 상장)는 아직 252거래일(12개월) 치 이력이 없을 수
    있다 — 이 경우 전체 4개 구간 대신, 확보된 이력이 지원하는 구간만 골라 그 가중치를 다시
    100%로 정규화해 계산한다(짧은 이력이라도 있는 만큼은 점수를 매기는 쪽을 택함). 63거래일(3개월)
    치도 없으면 점수를 매길 수 없어 None을 반환한다.
    """
    s = close.dropna()
    usable = [(w, weight) for w, weight in ROC_WEIGHTS if len(s) >= w + 1]
    if not usable:
        return None
    weight_sum = sum(weight for _, weight in usable)
    total = 0.0
    for window, weight in usable:
        r = roc(s, window)
        if r.dropna().empty:
            return None
        total += float(r.iloc[-1]) * (weight / weight_sum)
    return total


def theme_price_history(proxies: list[str], start: Optional[str] = None, end: Optional[str] = None) -> Optional[pd.Series]:
    """프록시가 여러 개면 정규화된(첫날=100) 종가를 평균해 테마 대표 시계열을 만든다.

    core.sector_leaders 등 다른 모듈에서도 재사용하는 공개 함수. start를 안 넘기면
    DEFAULT_LOOKBACK_DAYS(약 2.2년) 전부터 조회한다(신규 티커의 yfinance 기본기간 함정 회피).
    """
    histories = get_multiple_price_history(proxies, start=start or _default_start(), end=end, interval="1d")
    normalized = []
    for df in histories.values():
        if df is None or df.empty or "Close" not in df.columns:
            continue
        close = df["Close"].dropna()
        if close.empty:
            continue
        normalized.append(close / float(close.iloc[0]) * 100)
    if not normalized:
        return None
    combined = pd.concat(normalized, axis=1).mean(axis=1).dropna()
    return combined if not combined.empty else None


def compute_theme_strength(
    theme_universe: Optional[dict[str, list[str]]] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> pd.DataFrame:
    """모든 테마의 RS 점수(0~100 percentile)와 수익률/추세를 계산한다.

    Returns:
        columns: theme, proxies, strength_factor, rs_score, return_3m, return_6m, return_12m, trend,
        trend_change (지금 모멘텀 팩터 - 20거래일 전 모멘텀 팩터, %p 단위 — trend가 "횡보"이거나
        데이터가 부족하면 None) (rs_score 내림차순 정렬)
    """
    themes = THEME_UNIVERSE if theme_universe is None else theme_universe
    rows = []
    for theme, proxies in themes.items():
        series = theme_price_history(proxies, start, end)
        if series is None:
            continue
        factor = _strength_factor(series)
        if factor is None:
            continue

        trend = "횡보"
        trend_change: Optional[float] = None
        if len(series) > TREND_LOOKBACK_DAYS:
            past_series = series.iloc[:-TREND_LOOKBACK_DAYS]
            past_factor = _strength_factor(past_series)
            if past_factor is not None:
                trend_change = factor - past_factor
                if factor > past_factor + 1e-9:
                    trend = "상승"
                elif factor < past_factor - 1e-9:
                    trend = "하락"

        r3 = roc(series, 63).iloc[-1] if len(series) > 63 else None
        r6 = roc(series, 126).iloc[-1] if len(series) > 126 else None
        r12 = roc(series, 252).iloc[-1] if len(series) > 252 else None

        rows.append(
            {
                "theme": theme,
                "proxies": ", ".join(proxies),
                "strength_factor": factor,
                "return_3m": r3,
                "return_6m": r6,
                "return_12m": r12,
                "trend": trend,
                "trend_change": trend_change,
            }
        )

    if not rows:
        return pd.DataFrame(columns=_THEME_STRENGTH_COLUMNS)

    df = pd.DataFrame(rows)
    df["rs_score"] = df["strength_factor"].rank(pct=True) * 100
    df = df.sort_values("rs_score", ascending=False).reset_index(drop=True)
    return df


def save_theme_strength_snapshot(theme_scores: pd.DataFrame) -> int:
    """compute_theme_strength()의 결과를 DB에 저장한다.

    scheduler/run_scheduler.py::market_snapshot_job()이 매일 한국시간 00:00에 호출하는 게 기본
    경로이고, Streamlit 페이지에서 사용자가 "지금 다시 계산"을 눌렀을 때도 결과를 여기 저장해
    다음 조회부터 최신값을 즉시 보여준다.
    """
    with get_session() as session:
        row = SectorStrengthSnapshot(theme_scores=theme_scores.to_json(orient="records", force_ascii=False))
        session.add(row)
        session.flush()
        return row.id


def get_latest_theme_strength_snapshot() -> Optional[dict]:
    """가장 최근에 저장된 섹터/테마 강도 스냅샷을 반환한다. 아직 하나도 없으면 None.

    Returns: {"theme_scores": DataFrame, "computed_at": datetime} 또는 None.
    """
    with get_session() as session:
        row = (
            session.query(SectorStrengthSnapshot)
            .order_by(SectorStrengthSnapshot.id.desc())
            .first()
        )
        if row is None:
            return None
        computed_at = row.computed_at
        theme_scores_json = row.theme_scores

    df = pd.read_json(io.StringIO(theme_scores_json), orient="records")
    if df.empty:
        df = pd.DataFrame(columns=_THEME_STRENGTH_COLUMNS)
    return {"theme_scores": df, "computed_at": computed_at}
