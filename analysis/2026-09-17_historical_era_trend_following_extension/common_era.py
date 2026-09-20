"""공통 유틸 — 가격 로딩, 지표, 비용모델.

트랙C가 반복 지목한 남은 빈틈(agent_c_tenbagger.md persona, "표본 구간이 짧다(~4.25년)"):
지금까지의 모든 검증(IREN 피벗 바스켓 2022-05~2026-08, 비-AI 대조군 3개 2016~2026)은 전부
"최근 10년 안"의 사이클만 다뤘다 — 진짜 극단적인 베어마켓(-80~-95% 낙폭)을 겪어본 적이 없다.

이 모듈은 완전히 다른 두 시대의 고변동성 테마 바스켓을 정의한다:
  - CRYPTO_WINTER_2018: MARA/RIOT 자신의 AI 피벗 "이전" 역사(2017 ICO붐 절정 -> 2018 크립토윈터
    -90%대 낙폭 -> 2019 정체 -> 2020 코로나 폭락/회복 -> 2021 마니아 정점, IREN 상장 전 마감).
    같은 종목이지만 완전히 다른 시대·완전히 다른 서사(크립토 자체, AI 없음)라 "이 규칙이 이 종목군의
    변동성 프로파일 자체에 통하는가, 아니면 2022~2026 AI 슈퍼사이클 특유의 효과인가"를 가른다.
  - DOTCOM_BUBBLE_2000: 1998~2002 닷컴버블 — 인터넷/통신 테마로 폭등했다가 대부분 고점 대비
    80~95% 폭락한 시대. IREN 연구와는 테마·시대·자산군이 전혀 무관해 진짜 독립적인 표본이다.

analysis/2026-08-16_iren_volatile_momentum_stocks/backtest.py 의 find_common_start /
build_momentum_weights / run_rotation / donchian_trailing_stop_positions /
run_trend_following_single / run_trend_following_basket 를 import 로 그대로 재사용한다
(새 백테스트 로직 발명 없음).
"""
import sys

PROJECT_ROOT = "/opt/quant"
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, f"{PROJECT_ROOT}/analysis/2026-08-16_iren_volatile_momentum_stocks")

import pandas as pd

from core.market_data import get_multiple_price_history
from core.backtest_engine import calculate_metrics

OUT_DIR = f"{PROJECT_ROOT}/analysis/2026-09-17_historical_era_trend_following_extension"

FEE_BPS = 5.0  # 편도 5bp = 왕복 0.1% (트랙C/B 전체와 동일 관례)
COST_RATE = FEE_BPS / 10000.0

BENCH = ["SPY"]

# ---------------------------------------------------------------------------
# 바스켓 정의 — 시대별 독립 표본
# ---------------------------------------------------------------------------

BASKETS = {
    "crypto_winter_2018": {
        "label": "크립토 채굴주 — AI 피벗 이전(2017 ICO붐~2021, 진짜 크립토윈터 포함)",
        "tickers": ["MARA", "RIOT"],
        "representative": "RIOT",
        "load_start": "2017-01-01",
        "end": "2021-10-29",  # IREN이 나스닥에 상장(2021-11-05 인근)하기 직전까지로 끊어 후속
        # 연구(작업27~)와 표본이 겹치지 않게 한다.
        "narrative": (
            "MARA(옛 Marathon Patent Group)·RIOT(옛 Bioptix Inc)는 2017년 하반기 비트코인 채굴로 "
            "사업을 전환한 뒤(RIOT는 2017-10, 거래량이 15만주대에서 1400만주대로 폭증하며 명확히 "
            "확인됨), 2017년 12월 ICO/크립토 마니아 정점(RIOT 종가 $28.4, MARA $16.68)을 찍고 "
            "2018년 한 해 동안 -90%대로 무너진 '진짜 크립토윈터'를 실제로 겪었다(RIOT 2018-12 "
            "$1.51, MARA 2019-01 $1.36 — 정점 대비 각각 -95%/-92%). 이후 2019년 횡보, 2020년 "
            "코로나 폭락/급반등, 2021년 두 번째 마니아 정점까지 포함한다. IREN은 이 기간에 존재하지도 "
            "않았다(2021-11 나스닥 상장) — 즉 같은 종목(MARA/RIOT)이지만 AI 서사가 전혀 없던, "
            "지금까지 이 저장소가 한 번도 검증하지 않은 완전히 다른 시대의 표본이다."
        ),
    },
    "dotcom_bubble_2000": {
        "label": "닷컴버블 인터넷/통신 바스켓 (1998~2002, 진짜 -80~95% 약세장 포함)",
        "tickers": ["CSCO", "QCOM", "EBAY", "GLW", "CIEN", "AMZN"],
        "representative": "CSCO",
        "load_start": "1997-06-01",
        "end": "2002-12-31",
        "narrative": (
            "1998~2000년 인터넷/통신 인프라 붐(닷컴버블) 당시 가장 뜨거웠던 종목군 중 현재까지도 "
            "동일 티커로 거래되는 생존 종목만 골랐다(JDSU·PMCS·Sun Microsystems·Nortel 등 다수는 "
            "상장폐지/합병으로 yfinance에 이력이 없어 제외 — 생존편향을 그대로 명시). CSCO(-88%), "
            "QCOM(-83%), CIEN(-97%), GLW(-99%), AMZN(-95%), EBAY(-85%) 전부 2000~2002년 사이 "
            "고점 대비 극단적 낙폭을 실제로 겪은 진짜 약세장 표본 — IREN·크립토와도 테마가 무관하고 "
            "(인터넷 인프라 vs 크립토채굴/AI), 시대도 20여 년 전이라 이 저장소가 가진 어떤 표본과도 "
            "겹치지 않는 독립적인 검증이다."
        ),
    },
}


def cost_series(weights: pd.DataFrame) -> pd.Series:
    turnover = weights.diff().abs().sum(axis=1).fillna(0.0)
    return turnover * COST_RATE


def load_histories(tickers, start, end):
    return get_multiple_price_history(tickers, start=start, end=end, interval="1d")


def closes_frame(histories: dict) -> pd.DataFrame:
    closes = pd.DataFrame({t: df["Close"] for t, df in histories.items() if not df.empty})
    return closes.sort_index()


def metrics_from_returns(ret: pd.Series) -> tuple[dict, pd.Series]:
    equity = (1.0 + ret.fillna(0.0)).cumprod() * 100.0
    if len(equity) > 0:
        equity.iloc[0] = 100.0
    m = calculate_metrics(equity, [], equity.index[0], equity.index[-1])
    return m, equity
