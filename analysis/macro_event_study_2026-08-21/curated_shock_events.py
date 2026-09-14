"""정치/지정학/금융 충격 이벤트 큐레이션 스터디 (트랙 B).

트랙 A(연준 금리, 정기지표)와 달리 이 사건들은 API로 자동 탐지가 안 되므로, 널리 보도되어 날짜가
확실한 사건만 선별하고 실제 가격 데이터로 "그 날 정말 비정상적으로 움직였는지" 교차검증한 뒤에만
포함한다(검증 안 된 날짜는 넣지 않는다). 사건 유형을 다각화해서(무역정책·전쟁·팬데믹·금융권
연쇄부실·신용등급·선거) 어떤 유형의 충격이 시장에 어떻게 다르게 반응하는지 비교한다.

각 사건에 day(-1)도 같이 측정한다 — "사건 전날(예상/우려)"과 "사건 당일(실제)"을 구분해야
"소문에 팔고 뉴스에 사라"류 패턴(예: 2022 우크라이나 침공)을 놓치지 않는다.
"""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json
import pandas as pd

from core.market_data import get_multiple_price_history

OUT_DIR = "/workspaces/Quant/analysis/macro_event_study_2026-08-21"
HORIZONS = [1, 5, 20, 60]

EVENTS = [
    {"date": "2011-08-08", "category": "신용등급", "label": "S&P, 미국 국가신용등급 첫 강등(AAA→AA+)",
     "note": "2011-08-05(금) 장마감 후 발표, 다음 거래일(월) 반응"},
    {"date": "2016-11-09", "category": "선거", "label": "트럼프 1기 당선 확정",
     "note": "개표 중 선물시장은 급락(서킷브레이커), 정규장 개장 후 반전"},
    {"date": "2018-12-24", "category": "정책/정치", "label": "역대 최장 연방정부 셧다운 중 크리스마스이브 급락",
     "note": "셧다운 자체는 2018-12-22 시작, 이 날이 그 국면 중 최악의 단일 거래일"},
    {"date": "2020-03-11", "category": "팬데믹", "label": "WHO, 코로나19 팬데믹 공식 선언",
     "note": "연준의 3/16 긴급 금리인하와는 별개 사건 — 순수 보건당국 발표 자체의 반응"},
    {"date": "2022-02-24", "category": "지정학", "label": "러시아, 우크라이나 전면 침공",
     "note": "침공 하루 전(2/23)은 -1.84%, 침공 당일은 오히려 +1.50% — 대표적 '소문에 팔고 뉴스에 사라'"},
    {"date": "2023-03-10", "category": "금융권 부실", "label": "실리콘밸리은행(SVB) 파산·당국 인수",
     "note": "전날(3/9) 뱅크런 소식에 이미 -1.85%, 인수 당일도 추가 하락"},
    {"date": "2025-04-03", "category": "무역정책", "label": "'해방의 날' 관세 발표 다음날 반응",
     "note": "2025-04-02(수) 장마감 후 발표, 첫 반응은 4/3(-4.84%), 이튿날 4/4는 -5.97%로 더 악화"},
    # --- 아래는 "회복 못한/오래 걸린" 사례를 의도적으로 추가(선정 편향 보정용) ---
    {"date": "2001-09-17", "category": "테러", "label": "9·11 테러 이후 최초 개장일",
     "note": "공격은 9/11(화)이지만 거래소가 9/17(월)까지 나흘간 휴장 — 재개장 첫날 반응"},
    {"date": "2008-09-15", "category": "금융권 부실", "label": "리먼브라더스 파산 신청",
     "note": "글로벌 금융위기의 상징적 사건 — 이 이후 S&P500은 5개월간 추가로 -46% 더 하락했다"},
    {"date": "2016-06-24", "category": "선거", "label": "브렉시트(영국 EU 탈퇴) 국민투표 결과",
     "note": "투표 전날(6/23)은 +1.34%(잔류 우세 예상), 결과 발표일은 -3.59%로 반전"},
]


def main():
    all_dates = sorted(set([e["date"] for e in EVENTS]))
    start = (pd.Timestamp(min(all_dates)) - pd.DateOffset(days=30)).date().isoformat()
    end = (pd.Timestamp(max(all_dates)) + pd.DateOffset(days=100)).date().isoformat()

    spx_hist = get_multiple_price_history(["^GSPC"], start=start, end=end, interval="1d")["^GSPC"]
    close = spx_hist["Close"]
    idx = close.index

    rows = []
    for e in EVENTS:
        event_date = pd.Timestamp(e["date"])
        if event_date not in idx:
            print(f"[경고] {e['date']} 거래일 아님, 스킵", flush=True)
            continue
        pos = idx.get_loc(event_date)
        if pos < 1 or pos + max(HORIZONS) >= len(idx):
            print(f"[경고] {e['date']} 전후 데이터 부족, 스킵", flush=True)
            continue

        prior_close = close.iloc[pos - 1]
        day_before_close = close.iloc[pos - 2] if pos >= 2 else None
        day0_close = close.iloc[pos]

        day_minus1_ret = round(100 * (prior_close / day_before_close - 1), 3) if day_before_close is not None else None
        day0_ret = round(100 * (day0_close / prior_close - 1), 3)

        fwd = {}
        for h in HORIZONS:
            fwd[f"fwd_{h}d_pct"] = round(100 * (close.iloc[pos + h] / day0_close - 1), 3)

        row = {**e, "day_minus1_return_pct": day_minus1_ret, "day0_return_pct": day0_ret, **fwd}
        rows.append(row)
        print(f"[{e['category']}] {e['label']} ({e['date']}): 전일={day_minus1_ret}%, 당일={day0_ret}%, "
              f"+5일={fwd['fwd_5d_pct']}%, +20일={fwd['fwd_20d_pct']}%, +60일={fwd['fwd_60d_pct']}%", flush=True)

    with open(f"{OUT_DIR}/curated_shock_events.json", "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
