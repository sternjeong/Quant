"""트랙 B 확장 — 2018~2019 미중 무역전쟁 관세 발표 시리즈: "반복되는 충격에 시장이
둔감해지는가?"

지금까지 트랙B(curated_shock_events.py)는 전부 "1회성" 충격(신용등급 강등, 팬데믹 선언,
전쟁 발발 등 — 사건당 1건)이었다. 미중 무역전쟁은 이 프로젝트에서 처음으로 다루는 "같은
유형의 충격이 여러 번 반복된 시리즈"라서, 새로운 질문을 던질 수 있다 — 같은 종류의 나쁜
뉴스가 반복되면 시장의 반응 크기가 점점 줄어드는가("이벤트 피로/둔감화")?

**날짜 검증 원칙(트랙B 전통 그대로)**: 기억에 의존해 나열하지 않고, 각 후보 날짜를 실제
S&P500 가격 반응으로 교차검증한 뒤에만 포함한다. 이 검증 과정에서 다음을 조정했다:
  - 2019-05-05(일)는 거래일이 아니라서 트럼프의 관세 위협 트윗이 시장에 처음 반영된
    다음 거래일(2019-05-06, 월)을 이벤트일로 썼다.
  - 2019-05-10(25%로 실제 관세 인상 발효일)은 5/6 트윗 위협과 사실상 같은 에스컬레이션
    사이클의 "이미 예상된 결과"라서 중복 계산을 피하려고 대표 이벤트에서 제외했다
    (반응도 +0.37%로 미미해 이미 소화된 뉴스임을 시사).
  - 2018-09-17(3차 $200B 관세 발표)과 2018-09-24(그 발효일)도 같은 이유로 발표일(9/17)만
    대표로 썼다.
  - 2019-08-26(중국 보복관세에 대한 추가 트윗)은 8/23 사건과 같은 하루짜리 에스컬레이션의
    연장선이라 별도 이벤트로 세지 않았다.
결과적으로 에스컬레이션 8건 + 디에스컬레이션(1단계 무역합의) 1건, 총 9건으로 확정했다.

사전 등록 가설(결과를 계산하기 전에 적어둔다):
  H1(이벤트 피로/둔감화): 시리즈의 각 에스컬레이션 사건에 대한 "당일(day-0) S&P500 가격
      반응의 절대크기"가 사건 순서가 뒤로 갈수록 평균적으로 작아진다 — 사건 순서(1~8)와
      절대반응크기 사이의 스피어만 순위상관을 계산해 확인한다. n=8로는 통계적 유의성을
      주장하지 않고, 상관의 방향과 크기만 정직하게 보고한다(음의 상관 = 가설 지지).
  H2(대조군): 디에스컬레이션 사건(2019-12-13, 1단계 무역합의)의 반응은 H1이 예측하는
      "피로해진" 후반 에스컬레이션 사건들과 비교해 동등하거나 더 큰 양(+)의 반응을 보일
      것이다 — "좋은 뉴스는 똑같이 둔감해지지 않았는가"를 정직하게 확인한다.
  H3: 이 시리즈의 에스컬레이션 사건들의 평균 +60거래일 순방향 수익률/회복률은, 이 프로젝트의
      다른 트랙B 1회성 충격들의 평균 회복률(메모리에 기록된 "10건 중 8건이 60거래일 내
      회복")보다 나쁠 것이다 — 반복되는 장기전형 충격은 2022년 긴축장(우크라이나 침공이
      회복 못한 유일한 예외였던 배경)과 비슷하게 작동할 수 있다는 가설. 비교 기준선(8/10=80%)을
      먼저 명시하고 이 스터디의 회복률을 그것과 나란히 비교한다."""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json

import pandas as pd

from core.market_data import get_multiple_price_history

OUT_DIR = "/workspaces/Quant/analysis/macro_event_study_2026-08-21"
HORIZONS = [1, 5, 20, 60]
BASELINE_RECOVERY_RATE = 80.0  # 트랙B 기존 10건 중 8건 회복(메모리 기록, 인용)
BASELINE_N = 10

# 검증 완료된 최종 이벤트 목록(순서=에스컬레이션 시퀀스 번호)
ESCALATION_EVENTS = [
    {"seq": 1, "date": "2018-03-22", "label": "무역법 301조 관세 각서 서명(1차 경고)"},
    {"seq": 2, "date": "2018-06-15", "label": "340억달러 관세 리스트 최초 발표"},
    {"seq": 3, "date": "2018-07-06", "label": "1차 관세($34B) 실제 발효"},
    {"seq": 4, "date": "2018-08-23", "label": "2차 관세($16B) 발효"},
    {"seq": 5, "date": "2018-09-17", "label": "3차 관세($200B) 발표(9/24 10% 발효 예고)"},
    {"seq": 6, "date": "2019-05-06", "label": "트럼프, 관세 25%로 인상 위협 트윗(5/5 일요일→5/6 첫 거래일 반영)"},
    {"seq": 7, "date": "2019-08-01", "label": "잔여 $300B에 신규 10% 관세 부과 트윗"},
    {"seq": 8, "date": "2019-08-23", "label": "중국 보복관세 발표 + 트럼프 '미국기업 대체처 모색 지시' 트윗"},
]
DEESCALATION_EVENT = {"date": "2019-12-13", "label": "1단계(Phase One) 무역합의 공식 발표"}


def verify_and_build_row(e: dict, close: pd.Series, idx: pd.DatetimeIndex) -> dict | None:
    event_date = pd.Timestamp(e["date"])
    if event_date not in idx:
        print(f"[경고] {e['date']} 거래일 아님 — 스킵", flush=True)
        return None
    pos = idx.get_loc(event_date)
    if pos < 2 or pos + max(HORIZONS) >= len(idx):
        print(f"[경고] {e['date']} 전후 데이터 부족 — 스킵", flush=True)
        return None

    day_before2_close = close.iloc[pos - 2]
    prior_close = close.iloc[pos - 1]
    day0_close = close.iloc[pos]
    day_minus1_ret = round(100 * (prior_close / day_before2_close - 1), 3)
    day0_ret = round(100 * (day0_close / prior_close - 1), 3)

    fwd = {}
    for h in HORIZONS:
        fwd[f"fwd_{h}d_pct"] = round(100 * (close.iloc[pos + h] / day0_close - 1), 3)
    recovered_vs_prior = bool(close.iloc[pos + 60] >= prior_close)

    return {**e, "day_minus1_return_pct": day_minus1_ret, "day0_return_pct": day0_ret,
            "abs_day0_return_pct": abs(day0_ret), "recovered_60d_vs_prior": recovered_vs_prior, **fwd}


def spearman_rank_corr(x: list, y: list) -> float:
    """외부 라이브러리(scipy) 없이 순위상관을 직접 계산한다(작은 표본, 동점 없음 가정)."""
    def ranks(vals):
        order = sorted(range(len(vals)), key=lambda i: vals[i])
        r = [0] * len(vals)
        for rank, idx_ in enumerate(order, start=1):
            r[idx_] = rank
        return r
    rx, ry = ranks(x), ranks(y)
    n = len(x)
    d2 = sum((a - b) ** 2 for a, b in zip(rx, ry))
    return round(1 - 6 * d2 / (n * (n ** 2 - 1)), 4)


def main():
    all_dates = [e["date"] for e in ESCALATION_EVENTS] + [DEESCALATION_EVENT["date"]]
    start = (pd.Timestamp(min(all_dates)) - pd.DateOffset(days=15)).date().isoformat()
    end = (pd.Timestamp(max(all_dates)) + pd.DateOffset(days=100)).date().isoformat()

    spx_hist = get_multiple_price_history(["^GSPC"], start=start, end=end, interval="1d")["^GSPC"]
    close = spx_hist["Close"]
    idx = close.index

    print("=== 에스컬레이션 이벤트 검증 및 반응 측정 ===", flush=True)
    rows = []
    for e in ESCALATION_EVENTS:
        row = verify_and_build_row(e, close, idx)
        if row:
            rows.append(row)
            print(f"  #{e['seq']} {e['date']} {e['label']}: 당일={row['day0_return_pct']}%, "
                  f"+60일={row['fwd_60d_pct']}%, 회복={row['recovered_60d_vs_prior']}", flush=True)

    print("\n=== 디에스컬레이션(1단계 합의) 검증 ===", flush=True)
    deesc_row = verify_and_build_row(DEESCALATION_EVENT, close, idx)
    print(f"  {DEESCALATION_EVENT['date']}: 전일(루머일)={deesc_row['day_minus1_return_pct']}%, "
          f"당일(공식발표)={deesc_row['day0_return_pct']}%, +60일={deesc_row['fwd_60d_pct']}%", flush=True)

    print("\n=== H1: 사건 순서 vs 절대 반응크기 스피어만 상관 ===", flush=True)
    seq = [r["seq"] for r in rows]
    abs_ret = [r["abs_day0_return_pct"] for r in rows]
    rho = spearman_rank_corr(seq, abs_ret)
    print(f"  n={len(rows)}, 스피어만 rho={rho} (음수=피로/둔감화 가설 지지, 양수=반대)", flush=True)
    for r in rows:
        print(f"    #{r['seq']} {r['date']}: |당일반응|={r['abs_day0_return_pct']}%", flush=True)

    print("\n=== H3: 회복률 비교 ===", flush=True)
    n_recovered = sum(1 for r in rows if r["recovered_60d_vs_prior"])
    recovery_rate = round(100 * n_recovered / len(rows), 1)
    mean_fwd60 = round(sum(r["fwd_60d_pct"] for r in rows) / len(rows), 3)
    win_rate_fwd60 = round(100 * sum(1 for r in rows if r["fwd_60d_pct"] > 0) / len(rows), 1)
    print(f"  기준선(기존 트랙B 1회성 충격, 메모리 인용): {BASELINE_N}건 중 {BASELINE_RECOVERY_RATE}% 회복", flush=True)
    print(f"  이 스터디(무역전쟁 에스컬레이션 {len(rows)}건): {n_recovered}/{len(rows)}건 회복({recovery_rate}%), "
          f"+60일 평균={mean_fwd60}%(승률{win_rate_fwd60}%)", flush=True)

    out = {
        "escalation_events": rows,
        "deescalation_event": deesc_row,
        "h1_spearman_rho": rho,
        "h3": {
            "baseline_n": BASELINE_N, "baseline_recovery_rate_pct": BASELINE_RECOVERY_RATE,
            "n_events": len(rows), "n_recovered": n_recovered, "recovery_rate_pct": recovery_rate,
            "mean_fwd60_pct": mean_fwd60, "win_rate_fwd60_pct": win_rate_fwd60,
        },
    }
    with open(f"{OUT_DIR}/trade_war_tariff_series_study.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    print("\nDONE")


if __name__ == "__main__":
    main()
