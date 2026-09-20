"""공통 유틸 — 가격 로딩, 지표, 비용모델.

트랙 C가 반복 지목한 빈틈: 지금까지 검토한 고변동성 테마 바스켓(IREN/CIFR/CLSK/WULF/HUT/BTDR,
대조군으로 시도했던 MARA/RIOT/Bitfarms)이 전부 AI/HPC로 피벗한 종목이라, "변동성 모멘텀 자체의
효과"와 "AI 테마 효과"를 분리할 진짜 대조군이 없었다(작업29, iren_volatile_momentum_stocks_research
'순수 무피벗 대조군을 찾으려 했으나... 대조군이 사실상 존재하지 않음').

이 모듈은 AI 서사와 무관한 3개의 독립 고변동성 테마 바스켓을 정의한다:
  - SHIPPING: 2021 해운 운임 슈퍼사이클(코로나 공급망 병목) — 붐→버스트, 상품 사이클 서사
  - CANNABIS: 대마초 합법화 테마 — 구조적 장기 하락, 방향이 IREN과 정반대인 대조 사례
  - SOLAR: 태양광/클린에너지 ESG 테마 — 2020-21 붐, 2022-23 버스트, 상품/금리 서사

작업27(analysis/2026-08-16_iren_volatile_momentum_stocks/{common,backtest}.py)의 함수를 그대로
재사용한다(비용모델·지표 계산·돈치안 로직 등 새로 발명하지 않음) — 이 파일은 바스켓 정의와 데이터
로딩만 새로 추가한다.
"""
import sys

PROJECT_ROOT = "/opt/quant"
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, f"{PROJECT_ROOT}/analysis/2026-08-16_iren_volatile_momentum_stocks")

import pandas as pd

from core.market_data import get_multiple_price_history
from core.backtest_engine import calculate_metrics

OUT_DIR = f"{PROJECT_ROOT}/analysis/2026-09-14_nonai_control_basket_volatility_momentum"

END = "2026-09-12"
FEE_BPS = 5.0  # 편도 5bp = 왕복 0.1% (트랙C/B 전체와 동일 관례)
COST_RATE = FEE_BPS / 10000.0

# ---------------------------------------------------------------------------
# 대조군 바스켓 정의 — 전부 AI/HPC 서사 없음, IREN류와 유사한 "레버리지+변동성+서사 촉매" 구조
# ---------------------------------------------------------------------------

BASKETS = {
    "shipping": {
        "label": "해운 운임 슈퍼사이클 (2021 붐→버스트)",
        "tickers": ["ZIM", "SBLK", "DAC", "FRO", "STNG"],
        "representative": "ZIM",
        "narrative": (
            "코로나 공급망 병목으로 컨테이너/벌크/탱커 운임이 사상 최고치로 치솟은 2021년 상품 "
            "사이클 — 부채로 선박을 확장한다는 점에서 IREN류의 '부채로 짓는 캡엑스' 구조와 닮았지만 "
            "서사는 AI가 아니라 순수 해운 물동량/운임 사이클이다."
        ),
    },
    "cannabis": {
        "label": "대마초 합법화 테마 (구조적 장기 하락)",
        "tickers": ["TLRY", "CGC", "ACB", "CRON"],
        "representative": "TLRY",
        "narrative": (
            "2018~2019년 합법화 기대로 급등했다가 이후 공급과잉·규제 지연으로 다년간 구조적으로 "
            "무너진 테마 — IREN류와 정반대 방향(장기 우상향이 아니라 장기 우하향)의 고변동성 테마라, "
            "'추세추종+트레일링스탑' 규율이 상승장 특유의 효과인지 방향과 무관한 효과인지를 가른다."
        ),
    },
    "solar": {
        "label": "태양광/클린에너지 ESG 테마 (2020-21 붐, 2022-23 버스트)",
        "tickers": ["ENPH", "SEDG", "RUN", "FSLR", "PLUG"],
        "representative": "ENPH",
        "narrative": (
            "2020-21년 ESG 자금유입·저금리로 급등했다가 2022년 금리인상과 함께 대부분 고점 대비 "
            "80~90% 폭락한 테마 — IREN류처럼 '붐→버스트 사이클'을 가졌지만 서사가 AI가 아니라 "
            "재생에너지/금리다."
        ),
    },
}

BENCH = ["SPY"]


def cost_series(weights: pd.DataFrame) -> pd.Series:
    turnover = weights.diff().abs().sum(axis=1).fillna(0.0)
    return turnover * COST_RATE


def load_histories(tickers, start="2005-01-01", end=END):
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
