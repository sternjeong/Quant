"""H1~H4 스크립트를 순서대로 실행해 report_data.json으로 합친다.

H5(옵션 기반 헤지)는 이 저장소에 옵션 백테스트 인프라가 없어 실측을 생략하고(과제 지침에 따라
억지로 근사 시뮬레이션을 만들지 않음), 딥서치로 찾은 실전 프레이밍만 정성적 텍스트로 아래에
직접 기록한다(WebSearch 결과 기반, 출처 명시).
"""
from __future__ import annotations

import datetime
import json

from common import BTC_TICKER, MARKET_TICKER, PEER_TICKERS
import h1_market_beta_hedge
import h2_btc_beta_decomposition
import h3_low_beta_tilt
import h4_beta_weighted_sizing

H5_QUALITATIVE = {
    "hypothesis": "H5",
    "title": "옵션 기반 헤지(protective put / collar) — 정성적 프레이밍만 (실측 생략)",
    "why_no_backtest": (
        "이 저장소에는 옵션 가격결정/그릭스/옵션체인 이력 데이터 인프라가 없다(core/에 옵션 모듈 부재). "
        "IV 이력이나 옵션체인 스냅샷 없이 protective put/collar를 실측 백테스트하면 사실상 등가의 "
        "델타 헤지(=H1의 시장베타 헤지)를 재계산하는 것과 다르지 않아 새로운 정보가 없다. 억지로 "
        "근사 시뮬레이션을 만들지 말라는 과제 지침에 따라, 실전에서 언제/왜 유효한지만 딥서치 근거로 "
        "정리한다."
    ),
    "points": [
        "Protective put(주식 롱 + 풋 매수)은 하방을 무제한 방어하지만 프리미엄이 순수 비용으로 "
        "빠져나간다 — 이 프리미엄은 내재변동성(IV)에 비례하는데, IREN류 소형 테마주는 개별 IV가 "
        "구조적으로 높아(52주 실현변동성 90~120%대, H1/H3 실측 결과 참고) 상시 보험 비용이 매우 "
        "비싸다는 게 핵심 실전 제약이다.",
        "Collar(풋 매수 + 콜 매도)는 콜 프리미엄으로 풋 비용을 상쇄해 순비용을 낮추지만, 상단 "
        "수익을 행사가로 제한한다 — CBOE S&P500 95-110 Collar Index 실측 사례가 장기 수익률의 "
        "약 71%를 변동성 약 67% 수준에서 얻었다는 업계 참고치가 있다. 이는 지수 콜라 사례이며, "
        "개별 소형주(유동성이 낮고 옵션체인이 얕은 종목)는 스프레드 비용이 더 크고 콜 매도로 상단을 "
        "자르는 대가가 훨씬 뼈아프다 — H1/H3에서 실측된 이 종목군의 상단 폭발력(피벗 서사가 재평가될 "
        "때 단기간 수백% 상승) 자체가 이들의 핵심 알파원이기 때문에, 콜라의 상단 캡이 알파를 스스로 "
        "깎아먹는 구조적 모순이 있다.",
        "IV는 실적발표/계약 공시(예: 대형 AI 호스팅 계약 발표) 직전에 스파이크한다는 것이 옵션 시장의 "
        "일반적 패턴이다 — 이런 촉매 이벤트가 주가 변동의 핵심 동력인 이 종목군에서는 '가장 보험이 "
        "필요한 시점'과 '보험이 가장 비싸지는 시점'이 구조적으로 겹친다는 뜻이라, 상시 보유보다는 "
        "촉매 이벤트 직전에만 전술적으로 쓰는 편이 비용 대비 합리적일 수 있다는 정성적 시사점이 있다.",
        "결론(정성적): H1이 이미 보여주듯 '보험'에는 대가가 있고, 그 대가가 옵션에서는 프리미엄으로 "
        "더 명시적으로 드러날 뿐이다 — 옵션 헤지가 델타 헤지보다 우월하다고 말할 근거는 이 리서치 "
        "범위에서는 없으며, 오히려 얕은 유동성·높은 IV 탓에 실전에서는 델타 헤지보다 비용이 더 클 "
        "가능성이 높다.",
    ],
    "sources": [
        {"title": "Betting Against Beta (Frazzini & Pedersen, 2014, JFE)", "url": "https://pages.stern.nyu.edu/~lpederse/papers/BettingAgainstBeta.pdf"},
        {"title": "What Are Options Collars? — Charles Schwab", "url": "https://www.schwab.com/learn/story/what-are-options-collars"},
        {"title": "Collar (long stock + long put + short call) — Fidelity", "url": "https://www.fidelity.com/learning-center/investment-products/options/options-strategy-guide/collar"},
        {"title": "Protective Puts and Collars — Equicurious", "url": "https://equicurious.com/learn/derivatives/options-strategies-and-greeks/protective-puts-and-collars"},
    ],
}

PEER_CONTEXT_SOURCES = [
    {"title": "The Transformation Of Bitcoin Mining Into AI Hosting: Opportunities And Risks (Seeking Alpha)", "url": "https://seekingalpha.com/article/4895793-the-transformation-of-bitcoin-mining-into-ai-hosting-opportunities-and-risks"},
    {"title": "Miners Beat Bitcoin by 70% in 2026 as Terawulf Locks $12.8B in AI Contracts (news.Bitcoin.com)", "url": "https://news.bitcoin.com/miners-beat-bitcoin-by-70-in-2026-as-terawulf-locks-12-8b-in-ai-contracts/"},
    {"title": "Bitcoin miners' AI pivot faces $50 billion reality check, says VanEck (CoinDesk)", "url": "https://www.coindesk.com/markets/2026/06/16/bitcoin-miners-ai-pivot-faces-usd50-billion-reality-check-says-vaneck"},
    {"title": "Bitcoin Mining's AI Pivot: 2026 Thesis Update (insights4vc)", "url": "https://insights4vc.substack.com/p/bitcoin-minings-ai-pivot-2026-thesis"},
]


def main() -> None:
    print("H1 실행 중...")
    h1 = h1_market_beta_hedge.run()
    print("H2 실행 중...")
    h2 = h2_btc_beta_decomposition.run()
    print("H3 실행 중...")
    h3 = h3_low_beta_tilt.run()
    print("H4 실행 중...")
    h4 = h4_beta_weighted_sizing.run()

    report_data = {
        "meta": {
            "generated": datetime.datetime.now().isoformat(timespec="seconds"),
            "market_ticker": MARKET_TICKER,
            "btc_ticker": BTC_TICKER,
            "peer_tickers": PEER_TICKERS,
        },
        "h1": h1,
        "h2": h2,
        "h3": h3,
        "h4": h4,
        "h5": H5_QUALITATIVE,
        "peer_context_sources": PEER_CONTEXT_SOURCES,
        "bab_source": {
            "title": "Betting Against Beta (Frazzini & Pedersen, 2014, Journal of Financial Economics, Vol.111 No.1, pp.1-25)",
            "url": "https://pages.stern.nyu.edu/~lpederse/papers/BettingAgainstBeta.pdf",
        },
    }

    out_path = "report_data.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2, ensure_ascii=False, default=str)
    print(f"저장 완료: {out_path}")


if __name__ == "__main__":
    main()
