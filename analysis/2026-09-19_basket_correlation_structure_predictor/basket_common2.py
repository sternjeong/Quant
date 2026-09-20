"""공통 유틸 — 가격 로딩, 지표, 비용모델. (신규 2개 바스켓 전용)

이 리포트의 문제의식: historical_era_trend_following_extension(작업88)이 6개 시대/바스켓(IREN·
해운·대마초·태양광·크립토윈터·닷컴버블) 중 정확히 절반(IREN·크립토윈터·태양광)에서만 "돈치안20일+
15%트레일링스탑 추세추종이 매수후보유·로테이션을 모두 이긴다"는 패턴이 재현됐다고 보고하며, 그
차이가 "종목 수가 적고 상관관계가 극단적으로 높은 바스켓(동일 비즈니스모델)에서는 재현되고, 개별
기업 펀더멘털이 이질적인 바스켓에서는 로테이션의 분산 이점이 이긴다"는 가설로 재구성했다 — 단
"대마초는 이 가설의 반례라 확정 규칙으로 승격하지 않고 가설로만 남김"이라고 스스로 명시했다.

이 모듈은 그 가설을 사후 패턴매칭이 아니라 사전등록(pre-registration) 방식으로 검증하기 위한
2개의 새 바스켓을 정의한다 — 상관구조를 먼저 예측하고, 그 예측대로 재현 여부가 갈리는지를
나중에 확인한다(구조는 basket_common.py/2026-09-14_nonai_control_basket_volatility_momentum 와
동일, 새 바스켓만 추가):

  - EV_SPAC_BUST: 2020~2021년 SPAC 합병으로 상장한 전기차 스타트업 4종(WKHS/HYLN/LCID/PSNY) —
    전부 "양산 지연·현금소진·같은 SPAC 붐 서사"라는 동일 실패 각본을 공유하는, 사업모델이 사실상
    동일한 바스켓. 사전예측: 상관관계 HIGH → IREN 패턴 재현 예측.
  - BIOTECH_CATALYST: 희귀질환 임상단계/상업화 바이오텍 5종(SRPT/IONS/RARE/ALNY/BMRN) — 각자
    전혀 다른 적응증·전혀 다른 임상 타임라인의 개별 촉매(FDA 승인/거부, 임상 결과 발표)로 주가가
    움직여 같은 업종이라는 것 외엔 공유하는 서사가 없는, 펀더멘털이 이질적인 바스켓. 사전예측:
    상관관계 LOW → IREN 패턴 미재현(로테이션 또는 매수후보유가 우세) 예측.

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

OUT_DIR = f"{PROJECT_ROOT}/analysis/2026-09-19_basket_correlation_structure_predictor"

END = "2026-09-18"
FEE_BPS = 5.0  # 편도 5bp = 왕복 0.1% (트랙C/B 전체와 동일 관례)
COST_RATE = FEE_BPS / 10000.0

# ---------------------------------------------------------------------------
# 신규 바스켓 정의 — 상관구조를 사전에 예측한 뒤(predicted_high_correlation), 실제 상관관계와
# 백테스트 결과를 나중에 대조한다(correlation_metrics.py / structural_hypothesis_test.py).
# ---------------------------------------------------------------------------

BASKETS = {
    "ev_spac_bust": {
        "label": "EV SPAC 붐-버스트 (2020-21 상장, 동일 실패각본)",
        "tickers": ["WKHS", "HYLN", "LCID", "PSNY"],
        "representative": "LCID",
        "predicted_high_correlation": True,
        "predicted_reproduce": True,
        "narrative": (
            "2020~2021년 SPAC 합병 붐을 타고 상장한 전기차 스타트업들 — Workhorse(WKHS)·"
            "Hyliion(HYLN)·Lucid(LCID)·Polestar(PSNY). 브랜드·기술은 다르지만 전부 '양산 지연 → "
            "현금 소진 → 대규모 증자/감원'이라는 동일한 실패 각본을 순차적으로 밟았고, 금리·EV "
            "수요 둔화 같은 같은 거시 요인에 동시에 노출된다는 점에서 IREN류(부채로 짓는 캡엑스 + "
            "서사 촉매 중심 가격형성)와 구조적으로 가장 가까운 신규 바스켓이다."
        ),
    },
    "biotech_catalyst": {
        "label": "희귀질환 바이오텍 촉매주 (이종 임상 파이프라인)",
        "tickers": ["SRPT", "IONS", "RARE", "ALNY", "BMRN"],
        "representative": "SRPT",
        "predicted_high_correlation": False,
        "predicted_reproduce": False,
        "narrative": (
            "Sarepta(SRPT, 듀시엔 근이영양증)·Ionis(IONS, 안티센스 플랫폼)·Ultragenyx(RARE)·"
            "Alnylam(ALNY, RNAi)·BioMarin(BMRN) — 전부 고변동성 희귀질환 바이오텍이지만, 주가를 "
            "움직이는 촉매(개별 신약의 FDA 승인/거부, 개별 임상시험 결과 발표)가 서로 완전히 "
            "독립적이다. '같은 업종'이라는 것 외에 공유하는 거시 서사가 없어, 종목 수는 IREN(6종)과 "
            "비슷하지만 상관구조는 정반대(낮음)일 것으로 예측되는 대조 바스켓."
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
