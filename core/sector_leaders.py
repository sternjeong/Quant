"""섹터별 대표 ETF · 대장주 · 성장주 관계 분석 (신규 모듈).

SECTOR_LEADER_GROWTH_RELATIONSHIP_SPEC.md 참고. 대표 ETF는 기존 `core.sector_strength.THEME_UNIVERSE`를
그대로 재사용하고, 이 모듈은 그 위에 (1) 섹터별 대장주(시가총액 1위)/성장주(이익성장률 백분위 상위)
자동 선정과 (2) 종목-ETF 간 베타/상관계수/상대강도(RS) 비율 추세 계산만 추가한다.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

import pandas as pd

from core import macro_cycle, screener, valuation
from core.fred_data import get_series as fred_get_series
from core.fred_data import is_configured as fred_is_configured
from core.market_data import get_price_history
from core.market_regime import get_latest_market_regime_snapshot, score_ma_cross, score_trend_position
from core.sector_strength import DEFAULT_LOOKBACK_DAYS, THEME_UNIVERSE, theme_price_history

# core.market_data.get_price_history(start=None)는 로컬 캐시가 없는 티커에 대해 yfinance 기본
# period("1mo")만 받아와 베타/상관계수 계산(252거래일 필요)에 이력이 부족해진다 — 대장주/성장주는
# 이 페이지에서 처음 조회되는 티커가 많아 이 함정에 그대로 걸린다(core.sector_strength.theme_price_history
# 가 이미 같은 문제를 겪어 명시적 시작일로 고쳤음). 상수는 그 모듈 것을 그대로 재사용해 "얼마나
# 과거까지"의 기준을 한 곳에 둔다.


def _default_start() -> str:
    return (date.today() - timedelta(days=DEFAULT_LOOKBACK_DAYS)).isoformat()

# 한국어 테마명(THEME_UNIVERSE 키) -> GICS 영문 섹터명(core.screener.get_universe()의 Sector 컬럼과 매칭).
# GICS 표준 11개 섹터만 대상 — 니치 테마(반도체/DRAM/우주)는 GICS 섹터가 없어 아래 별도 프리셋 사용.
THEME_TO_GICS_SECTOR: dict[str, str] = {
    "기술": "Information Technology",
    "금융": "Financials",
    "헬스케어": "Health Care",
    "임의소비재": "Consumer Discretionary",
    "필수소비재": "Consumer Staples",
    "에너지": "Energy",
    "산업재": "Industrials",
    "소재": "Materials",
    "유틸리티": "Utilities",
    "부동산": "Real Estate",
    "커뮤니케이션": "Communication Services",
}

# GICS에 없는 니치 테마의 후보 종목 프리셋(THEME_UNIVERSE의 ETF 프록시 프리셋과 동일한 성격 —
# 종목 구성이 바뀌면 딕셔너리만 수정하면 됨). 반도체는 SOXX/SMH 주요 보유 종목, 메모리/DRAM은
# MARKET_REGIME_SECTOR_STRENGTH_SPEC.md에서 확인한 Roundhill DRAM ETF의 3대 비중 종목.
#
# 2026-07-15: 기존 "우주" 테마에 대형 방산 프라임(LMT/RTX/NOC/GD/LHX)이 섞여 있어 대장주가 항상
# 방산 프라임(시총이 훨씬 큼)이 되고 진짜 우주기업은 성장주로도 잘 안 뽑히는 문제가 있었다 — 방산을
# 별도 테마로 완전히 분리(대형 프라임 + 중소형 방산기술주 KTOS/AVAV/MRCY)하고, 우주는 순수
# 우주기업(+ 소형주 LUNR/RDW 추가로 "대형주 추세추종→소형주" 비교가 의미 있도록)만 남겼다.
# 보잉(BA)은 매출 대부분이 상업 항공기라 방산 대장주 선정을 왜곡할 수 있어 방산 후보에서 제외.
# 냉각/사이버보안/클라우드/로보틱스는 기존 "기술"(GICS Information Technology) 테마가 초대형주
# 위주로만 대장주/성장주를 뽑던 것을 보완하기 위해 신규 세분화(THEME_UNIVERSE 주석의 리서치 근거 참고).
# 사이버보안 후보에 CyberArk(CYBR) 대신 Qualys(QLYS)를 넣은 이유: CyberArk는 2026-02-11 Palo Alto
# Networks에 인수합병 완료돼 나스닥 상장폐지됐다(yfinance 조회 시 404로 실증 확인) — 별도 상장
# 종목이 아니게 된 회사를 후보에서 빼고 같은 성격의 다른 독립 상장 종목으로 교체. 로보틱스 후보에
# iRobot(IRBT) 대신 Symbotic(SYM)을 넣은 이유도 동일 — iRobot은 2025-12 챕터11 파산 후 Picea에
# 인수되며 2025-12-22 나스닥 거래정지·상장폐지됐다(마찬가지로 yfinance 404로 실증 확인).
NICHE_THEME_CANDIDATES: dict[str, list[str]] = {
    "반도체": [
        "NVDA", "AVGO", "AMD", "TXN", "QCOM", "INTC", "MU", "ASML",
        "LRCX", "AMAT", "KLAC", "ADI", "MRVL", "ON", "MPWR",
    ],
    "메모리/DRAM": ["MU", "005930.KS", "000660.KS"],
    "방산": ["LMT", "RTX", "NOC", "GD", "LHX", "KTOS", "AVAV", "MRCY"],
    "우주": ["ASTS", "RKLB", "LUNR", "RDW"],
    "냉각": ["VRT", "MOD", "AAON", "NVT"],
    "사이버보안": ["CRWD", "PANW", "FTNT", "ZS", "S", "OKTA", "QLYS"],
    "클라우드": ["CRM", "NOW", "SNOW", "DDOG", "NET", "MDB"],
    "로보틱스": ["ISRG", "ROK", "TER", "PATH", "SYM"],
    # 2026-07-17 딥서치: NVIDIA가 2026년 실리콘 포토닉스 전략 투자($2B씩)를 단행한 Lumentum/Coherent,
    # 수주잔고 $7B인 Ciena, 2026년 상반기 주가 상승률 상위(S&P500 top 10 gainer)에 오른 Applied
    # Optoelectronics/Viavi/Corning을 후보로 구성.
    "광통신": ["LITE", "COHR", "CIEN", "AAOI", "VIAV", "GLW", "FN"],
    # AI 데이터센터 전력 수요 급증으로 하이퍼스케일러들이 직접 전력구매계약(PPA)을 맺는 원전/SMR
    # 사업자(Oklo-Meta 1.2GW 계약, Vistra-Meta 2,600MW PPA 등)와 데이터센터向 전력 공급 유틸리티.
    "원자력": ["OKLO", "SMR", "CEG", "VST", "TLN", "CCJ"],
}

# 테마(THEME_UNIVERSE 키) -> core.macro_cycle.SECTOR_ROTATION의 국면별 아웃퍼폼 섹터명 매핑.
# GICS 10개는 그대로 자기 자신(SECTOR_ROTATION 키와 동일한 한국어 표기), 니치 테마는 성격이 가장
# 가까운 GICS 섹터로 근사한다(공식 GICS 분류가 아니라 매크로 리포트용 참고 매핑). "커뮤니케이션"은
# SECTOR_ROTATION에 해당 섹터가 없어 매핑하지 않는다(경기 사이클 로테이션 이론에 별도 항목이 없음).
THEME_TO_CYCLE_SECTOR: dict[str, str] = {
    "기술": "기술", "금융": "금융", "헬스케어": "헬스케어", "임의소비재": "임의소비재",
    "필수소비재": "필수소비재", "에너지": "에너지", "산업재": "산업재", "소재": "소재",
    "유틸리티": "유틸리티", "부동산": "부동산",
    "반도체": "기술", "메모리/DRAM": "기술", "냉각": "기술", "사이버보안": "기술", "클라우드": "기술",
    "우주": "산업재", "방산": "산업재", "로보틱스": "산업재",
    "광통신": "기술", "원자력": "유틸리티",
}


def get_theme_macro_context(theme: str) -> dict:
    """테마 하나를 고르면 함께 보여줄 매크로 경제 맥락(시장 국면 + 경기 사이클 국면)을 모은다.

    core.market_regime의 최근 저장 스냅샷(스케줄러가 매일 미리 계산해둔 것 재사용, 추가 조회 없음)과,
    FRED_API_KEY가 설정돼 있으면 core.macro_cycle의 경기 사이클 국면을 함께 조회해, 이 테마에 매핑된
    섹터(THEME_TO_CYCLE_SECTOR)가 현재 국면에서 역사적으로 아웃퍼폼하는 섹터 목록에 포함되는지
    판정한다.

    Returns:
        {
            "market_regime": dict|None,  # get_latest_market_regime_snapshot() 결과
            "cycle_phase": dict|None,    # macro_cycle.determine_cycle_phase() 결과 (FRED 미설정 시 None)
            "mapped_sector": str|None,   # THEME_TO_CYCLE_SECTOR 매핑 (없으면 None)
            "is_favored_sector": bool|None,  # 매핑된 섹터가 현재 국면의 아웃퍼폼 목록에 있는지
        }
    """
    market_regime = get_latest_market_regime_snapshot()
    mapped_sector = THEME_TO_CYCLE_SECTOR.get(theme)

    cycle_phase = None
    is_favored = None
    if fred_is_configured():
        gdp_series = fred_get_series("GDPC1")
        unemployment_series = fred_get_series("UNRATE")
        if not gdp_series.empty and not unemployment_series.empty:
            gdp_growth = macro_cycle.yoy_growth(gdp_series, periods=4)
            cycle_phase = macro_cycle.determine_cycle_phase(gdp_growth, unemployment_series)
            if cycle_phase.get("phase") and mapped_sector:
                is_favored = mapped_sector in cycle_phase["sectors"]

    return {
        "market_regime": market_regime,
        "cycle_phase": cycle_phase,
        "mapped_sector": mapped_sector,
        "is_favored_sector": is_favored,
    }


TREND_LOOKBACK_DAYS = 20
TREND_THRESHOLD_PCT = 1.0  # RS 비율이 이 폭(%) 이상 움직여야 상승/하락으로 판정(잡음 방지)

# 사용자가 분석 기간(1개월/6개월/1년/3년/직접 선택)을 고를 수 있게 된 후(2026-07-15) 베타/상관계수는
# 더 이상 고정된 "최근 252거래일"이 아니라 선택된 기간 전체를 창(window)으로 쓴다. 그래서 최소
# 데이터 길이 기준도 "1년 데이터가 있어야 함" 전제였던 기존 30/20에서, "1개월(~21거래일)도 계산
# 가능해야 함" 전제로 낮췄다 — 짧은 기간을 고르면 통계가 더 노이즈에 민감해지는 건 사용자가 감수하는
# trade-off로 보고, 계산 자체를 막지는 않는다.
_MIN_ALIGNED_DAYS = 15
_MIN_RETURN_DAYS = 10

# 성장주 후보군에서 초대형주를 제외하기 위한 시가총액 분위수 (2026-07-15 추가).
# 대장주(시총 1위) 한 종목만 빼는 기존 방식은 애플이 대장주가 되면 마이크로소프트처럼 여전히
# 초대형주인 종목이 "성장주"로 잡히는 문제가 있었다 — 실제로 러셀 지수 재조정에서도 최근 애플/MS가
# 밸류 지수 쪽으로도 편입될 만큼 초대형주는 성장주 정의와 상충된다는 리서치 근거(2026-07-15,
# SECTOR_LEADER_GROWTH_RELATIONSHIP_SPEC.md 참고)를 반영해, 후보군 내 시가총액 상위 25%
# 전체를 성장주 후보에서 제외한다.
MEGA_CAP_EXCLUDE_QUANTILE = 0.75

# "대형주 추세추종 → 소형주 기회" 레깅(lagging) 후보 판정 임계값 (2026-07-15 추가).
# Lo-MacKinlay(1990)/Hou(2007)의 리드-래그(lead-lag) 연구에 따르면 같은 산업 내에서 대형주
# 수익률이 소형주 수익률을 선행한다(정보확산 지연) — 대장주가 이미 상승추세로 확인됐고, 성장주가
# 그 대장주와 충분히 연동돼 있는데(베타/상관계수 모두 임계값 이상) 아직 상대강도가 못 따라온
# (RS추세가 상승이 아닌) 종목을 "추격 후보"로 표시한다. 단, 거래비용 반영 시 이 예측력에 기반한
# 초과수익은 빠르게 사라진다는 한계도 리서치에서 확인됨(페이지 캡션에 명시).
LAG_BETA_THRESHOLD = 0.5
LAG_CORRELATION_THRESHOLD = 0.5


def get_theme_candidate_tickers(theme: str) -> list[str]:
    """테마의 후보 종목 티커 목록을 반환한다 (GICS 11개는 S&P500 유니버스, 니치 테마는 프리셋)."""
    gics_sector = THEME_TO_GICS_SECTOR.get(theme)
    if gics_sector:
        universe = screener.get_universe()
        return universe.loc[universe["Sector"] == gics_sector, "Symbol"].dropna().tolist()
    return list(NICHE_THEME_CANDIDATES.get(theme, []))


def _percentile_score(series: pd.Series) -> pd.Series:
    """배치 내 상대 순위를 0~100 백분위 점수로 변환한다. 값이 전부 결측이면 중립값(50)."""
    if series.dropna().empty:
        return pd.Series(50.0, index=series.index)
    return series.rank(pct=True, na_option="bottom") * 100


def compute_leader_and_growth(theme: str, top_n_growth: int = 3, use_cache: bool = True) -> dict:
    """테마의 대장주(시가총액 1위)와 성장주(시가총액 상위 25% 초대형주를 제외한 나머지 중
    이익성장률 백분위 상위 top_n_growth개)를 자동 선정한다.

    Returns:
        {"theme", "candidates_count", "leader": dict|None, "growth_stocks": list[dict]}
    """
    candidates = get_theme_candidate_tickers(theme)
    rows = []
    for ticker in candidates:
        fundamentals = screener.get_fundamentals(ticker, use_cache=use_cache)
        val_inputs = valuation.fetch_valuation_inputs(ticker)
        rows.append(
            {
                "ticker": ticker,
                "name": fundamentals.get("name") or ticker,
                "market_cap": fundamentals.get("market_cap") or 0,
                "earnings_growth": val_inputs.get("earningsGrowth"),
                "per": val_inputs.get("trailingPE"),
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        return {"theme": theme, "candidates_count": 0, "leader": None, "growth_stocks": []}

    df["market_cap"] = pd.to_numeric(df["market_cap"], errors="coerce").fillna(0)
    df = df.sort_values("market_cap", ascending=False).reset_index(drop=True)

    leader_row = df.iloc[0]
    leader = {
        "ticker": leader_row["ticker"],
        "name": leader_row["name"],
        "market_cap": float(leader_row["market_cap"]),
    }

    # 대장주 한 종목만 빼는 대신, 시가총액 상위 25%(MEGA_CAP_EXCLUDE_QUANTILE) 전체를 초대형주로
    # 보고 성장주 후보에서 제외한다(대장주는 항상 최댓값이라 이 필터에 자동으로 포함됨). 후보군이
    # 작아(예: 3개) 상위 25%를 잘라내면 아무도 안 남는 경우에는 대장주 한 종목만 제외하는 기존
    # 동작으로 폴백한다.
    market_cap_ceiling = df["market_cap"].quantile(MEGA_CAP_EXCLUDE_QUANTILE)
    growth_pool = df[df["market_cap"] < market_cap_ceiling].copy()
    if growth_pool.empty:
        growth_pool = df.iloc[1:].copy()
    growth_pool["earnings_growth"] = pd.to_numeric(growth_pool["earnings_growth"], errors="coerce")
    growth_pool["per"] = pd.to_numeric(growth_pool["per"], errors="coerce")
    # earnings_growth가 없는 종목은 PER로 대체(성장주는 대체로 고PER) — strategy_tuning.compute_style_scores
    # 의 growth_score 공식과 동일(그 함수는 모멘텀/퀄리티까지 계산해 가격 히스토리 조회가 추가로 필요하므로
    # 여기서는 성장 점수 계산에 필요한 부분만 얇게 재구현한다).
    growth_pool["growth_score"] = _percentile_score(growth_pool["earnings_growth"].fillna(growth_pool["per"]))
    growth_pool = growth_pool.sort_values("growth_score", ascending=False).head(top_n_growth)

    growth_stocks = [
        {
            "ticker": r["ticker"],
            "name": r["name"],
            "market_cap": float(r["market_cap"]),
            "earnings_growth": None if pd.isna(r["earnings_growth"]) else float(r["earnings_growth"]),
            "per": None if pd.isna(r["per"]) else float(r["per"]),
            "growth_score": float(r["growth_score"]),
        }
        for _, r in growth_pool.iterrows()
    ]

    return {
        "theme": theme,
        "candidates_count": len(candidates),
        "leader": leader,
        "growth_stocks": growth_stocks,
    }


def _abs_trend_label(close: pd.Series) -> str:
    """종목 자체의 절대 추세(ETF 대비가 아니라 그 종목 가격만으로 판단)를 "상승"/"하락"/"혼조"로
    라벨링한다. 200일선 위/아래 + 50/200일 골든·데드크로스를 core.market_regime의 기존 로직
    그대로 재사용한다(시장 국면 판단과 같은 잣대). "대형주 추세추종" 섹션에서 대장주가 실제로
    추세추종할 만한 상승세인지 판단하는 트리거로 쓰인다 — RS비율(ETF 대비 상대강도) 추세와는
    다른 개념(이 함수는 종목의 절대 가격 추세, RS추세는 ETF 대비 상대적 추세).
    """
    trend_position = score_trend_position(close)
    ma_cross = score_ma_cross(close)
    if trend_position is None or ma_cross is None:
        return "N/A"
    if trend_position["above_200sma"] and ma_cross["golden_cross"]:
        return "상승"
    if not trend_position["above_200sma"] and not ma_cross["golden_cross"]:
        return "하락"
    return "혼조"


def compute_relationship_metrics(
    ticker: str,
    etf_series: pd.Series,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> Optional[dict]:
    """종목과 대표 ETF 시계열 간 베타/상관계수/상대강도(RS) 비율 추세를 계산한다.

    데이터가 부족하면(신규 상장 등) None을 반환한다.

    start/end(2026-07-15 추가, 사용자가 페이지에서 분석 기간을 직접 고를 수 있게 됨)를 주면 베타/
    상관계수/RS 비율은 그 기간 전체를 창(window)으로 써서 계산한다(예전처럼 고정된 "최근 252거래일"이
    아님). 단, abs_trend(200일선 기준 절대 추세)는 짧은 기간을 골라도 계산 가능해야 하므로, 가격
    조회 자체는 `min(start, _default_start())`로 항상 200일선을 채울 만큼 충분히 과거까지 받아오고
    (200sma 계산용 여유분), 그중 start 이후 구간만 잘라 나머지 지표(beta/correlation/RS)에 쓴다.

    Returns:
        {"beta", "correlation", "rs_ratio_now", "rs_change_3m", "trend", "abs_trend", "aligned_close"}
        (trend: ETF 대비 상대강도 추세, abs_trend: 종목 자체의 절대 가격 추세[200일 미만 데이터면
        "N/A"], aligned_close: ETF와 겹치는 구간의 종가 원본 시계열 — 비교 차트 렌더링용)
    """
    fetch_start = min(start, _default_start()) if start else _default_start()
    price_df = get_price_history(ticker, start=fetch_start, end=end)
    if price_df is None or price_df.empty or "Close" not in price_df.columns:
        return None
    close = price_df["Close"].dropna()
    if close.empty:
        return None

    display_close = close.loc[close.index >= start] if start else close
    aligned = pd.concat([display_close.rename("stock"), etf_series.rename("etf")], axis=1).dropna()
    if len(aligned) < _MIN_ALIGNED_DAYS:
        return None

    returns = aligned.pct_change().dropna()
    if len(returns) < _MIN_RETURN_DAYS:
        return None

    etf_variance = returns["etf"].var()
    beta = float(returns["stock"].cov(returns["etf"]) / etf_variance) if etf_variance else None
    correlation = float(returns["stock"].corr(returns["etf"]))

    rs_ratio = aligned["stock"] / aligned["etf"]
    rs_ratio_indexed = rs_ratio / float(rs_ratio.iloc[0]) * 100
    rs_ratio_now = float(rs_ratio_indexed.iloc[-1])

    rs_change_3m = None
    if len(rs_ratio_indexed) > 63:
        past_63 = float(rs_ratio_indexed.iloc[-63])
        if past_63:
            rs_change_3m = (rs_ratio_now / past_63 - 1) * 100

    trend = "횡보"
    if len(rs_ratio_indexed) > TREND_LOOKBACK_DAYS:
        past = float(rs_ratio_indexed.iloc[-TREND_LOOKBACK_DAYS])
        if past:
            change_pct = (rs_ratio_now / past - 1) * 100
            if change_pct > TREND_THRESHOLD_PCT:
                trend = "상승"
            elif change_pct < -TREND_THRESHOLD_PCT:
                trend = "하락"

    return {
        "beta": beta,
        "correlation": correlation,
        "rs_ratio_now": rs_ratio_now,
        "rs_change_3m": rs_change_3m,
        "trend": trend,
        "abs_trend": _abs_trend_label(close),
        "aligned_close": aligned["stock"],
    }


def _normalize_from(series: pd.Series, start_date) -> pd.Series:
    """series를 start_date 이후 구간만 잘라 그 시점 값=100으로 정규화한다."""
    trimmed = series.loc[series.index >= start_date]
    if trimmed.empty:
        return trimmed
    return trimmed / float(trimmed.iloc[0]) * 100


def build_comparison_chart_series(etf_series: pd.Series, leader: Optional[dict], growth_stocks: list[dict]) -> dict[str, pd.Series]:
    """ETF/대장주/성장주를 전부 같은 기준일(모든 종목의 데이터가 겹치는 가장 늦은 시작일)=100으로
    정규화한 비교용 시계열 딕셔너리를 만든다. 데이터가 없는 종목은 조용히 제외한다.
    """
    entities = []
    if leader is not None and leader.get("aligned_close") is not None:
        entities.append((leader["ticker"], leader["aligned_close"]))
    for g in growth_stocks:
        if g.get("aligned_close") is not None:
            entities.append((g["ticker"], g["aligned_close"]))

    if not entities:
        return {}

    common_start = max([s.index[0] for _, s in entities] + [etf_series.index[0]])
    chart_series = {"ETF": _normalize_from(etf_series, common_start)}
    for label, series in entities:
        normalized = _normalize_from(series, common_start)
        if not normalized.empty:
            chart_series[label] = normalized
    return chart_series


def build_price_chart_series(
    etf_tickers: list[str],
    leader: Optional[dict],
    growth_stocks: list[dict],
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> dict[str, pd.Series]:
    """실제 가격 차트에 쓸 수 있도록 ETF/대장주/성장주의 종가 시계열을 같은 시작일 기준으로 잘라낸다.

    페이지에서 정규화 차트 아래에 실제 주가를 보여주기 위해 사용한다. 각 종목은 기존 price history
    캐시를 읽고, ETF는 프록시 티커 목록의 가격을 평균해 같은 기간에 맞춘다. start/end를 주면 그
    구간만 조회한다(사용자가 고른 분석 기간과 일치시키기 위함) — 안 주면 기존처럼 기본 lookback을 쓴다.
    """
    entities = []
    if leader is not None and leader.get("aligned_close") is not None:
        entities.append((leader["ticker"], leader["aligned_close"]))
    for g in growth_stocks:
        if g.get("aligned_close") is not None:
            entities.append((g["ticker"], g["aligned_close"]))

    if not entities:
        return {}

    etf_histories = []
    for ticker in etf_tickers:
        df = get_price_history(ticker, start=start or _default_start(), end=end, interval="1d")
        if df is None or df.empty or "Close" not in df.columns:
            continue
        close = df["Close"].dropna()
        if not close.empty:
            etf_histories.append(close)

    if etf_histories:
        etf_series = pd.concat(etf_histories, axis=1).mean(axis=1).dropna()
    else:
        etf_series = pd.Series(dtype=float)

    if etf_series.empty:
        return {}

    common_start = max([s.index[0] for _, s in entities] + [etf_series.index[0]])
    price_series = {"ETF": etf_series.loc[etf_series.index >= common_start]}
    for label, series in entities:
        trimmed = series.loc[series.index >= common_start]
        if not trimmed.empty:
            price_series[label] = trimmed
    return price_series


def build_price_chart_candidates(
    etf_tickers: list[str],
    leader: Optional[dict],
    growth_stocks: list[dict],
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> list[dict]:
    """실제 가격 차트에서 클릭으로 선택할 수 있는 후보 목록을 만든다."""
    price_series = build_price_chart_series(etf_tickers, leader, growth_stocks, start=start, end=end)
    candidates = []
    if price_series.get("ETF") is not None:
        candidates.append({"key": "ETF", "label": "대표 ETF", "ticker": "ETF", "series": price_series["ETF"]})
    if leader is not None and leader.get("ticker") and price_series.get(leader["ticker"]) is not None:
        candidates.append({
            "key": leader["ticker"],
            "label": f"대장주 {leader['ticker']}",
            "ticker": leader["ticker"],
            "series": price_series[leader["ticker"]],
        })
    for growth in growth_stocks:
        ticker = growth.get("ticker")
        if ticker and price_series.get(ticker) is not None:
            candidates.append({"key": ticker, "label": f"성장주 {ticker}", "ticker": ticker, "series": price_series[ticker]})
    return candidates


def _is_lag_candidate(leader: dict, growth_stock: dict) -> bool:
    """"대형주 추세추종 → 소형주 기회" 레깅(lagging) 후보 여부를 판정한다.

    대장주가 절대 가격 기준으로 상승추세(abs_trend == "상승")이고, 성장주가 그 대장주와 충분히
    연동돼 있는데(베타/상관계수 모두 LAG_*_THRESHOLD 이상) 아직 ETF 대비 상대강도가 못 따라온
    (trend가 "상승"이 아닌) 경우에만 True. 리드-래그 연구(Lo-MacKinlay 1990, Hou 2007)에 근거해
    "대형주가 먼저 움직이고 소형주에 정보가 늦게 반영된다"는 가설을 반영한 관찰용 플래그이며,
    수익을 보장하는 신호가 아니다(페이지에 그대로 안내).
    """
    if leader.get("abs_trend") != "상승":
        return False
    beta = growth_stock.get("beta")
    correlation = growth_stock.get("correlation")
    trend = growth_stock.get("trend")
    if beta is None or correlation is None or trend is None:
        return False
    return beta >= LAG_BETA_THRESHOLD and correlation >= LAG_CORRELATION_THRESHOLD and trend != "상승"


def analyze_theme_relationships(
    theme: str, top_n_growth: int = 3, start: Optional[str] = None, end: Optional[str] = None
) -> dict:
    """테마의 대표 ETF/대장주/성장주를 선정하고 셋의 정량적 관계를 계산한다 (페이지 진입점).

    start/end(2026-07-15 추가): 페이지에서 사용자가 고른 분석 기간(1개월/6개월/1년/3년/직접 선택).
    안 주면 기존처럼 기본 lookback(약 2.2년)을 그대로 쓴다.

    Returns:
        {
            "theme", "proxies": list[str], "etf_series": pd.Series|None, "candidates_count": int,
            "leader": dict|None (ticker/name/market_cap/beta/correlation/rs_ratio_now/rs_change_3m/
                trend/abs_trend),
            "growth_stocks": list[dict] (ticker/name/earnings_growth/per/growth_score/+관계지표/
                lag_candidate),
        }
    """
    proxies = THEME_UNIVERSE.get(theme, [])
    etf_series = theme_price_history(proxies, start=start, end=end) if proxies else None

    selection = compute_leader_and_growth(theme, top_n_growth=top_n_growth)
    result: dict = {
        "theme": theme,
        "start": start,
        "end": end,
        "proxies": proxies,
        "etf_series": etf_series,
        "candidates_count": selection["candidates_count"],
        "leader": None,
        "growth_stocks": [],
    }
    if etf_series is None or selection["leader"] is None:
        return result

    leader = dict(selection["leader"])
    metrics = compute_relationship_metrics(leader["ticker"], etf_series, start=start, end=end)
    if metrics:
        leader.update(metrics)
    result["leader"] = leader

    growth_stocks = []
    for g in selection["growth_stocks"]:
        g = dict(g)
        metrics = compute_relationship_metrics(g["ticker"], etf_series, start=start, end=end)
        if metrics:
            g.update(metrics)
        g["lag_candidate"] = _is_lag_candidate(leader, g)
        growth_stocks.append(g)
    result["growth_stocks"] = growth_stocks
    result["chart_series"] = build_comparison_chart_series(etf_series, leader, growth_stocks)

    return result
