"""요일효과가 최근 30년 사이 사라진 걸 확인한 뒤 남은 질문: 계절성("5월에 팔고 떠나라")과
대선주기 효과도 최근 30년만 떼어보면 사라지거나 약해지는가, 아니면 여전히 버티는가? 전체 76년
평균만 믿고 "여전히 유효하다"고 결론 내리면 안 된다는 게 요일효과의 교훈이었으므로, 같은 방식
(1996년 이후로 구간을 쪼개서)으로 나머지 두 효과도 재검증한다."""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json

import pandas as pd

from core.market_data import get_multiple_price_history

OUT_DIR = "/workspaces/Quant/analysis/macro_event_study_2026-08-21"
RECENT_CUTOFF = 1996
YEAR_LABELS = {1: "1년차", 2: "2년차", 3: "3년차", 0: "4년차"}


def summarize(rets, label):
    n = len(rets)
    mean = round(sum(rets) / n, 3)
    win = round(100 * sum(1 for r in rets if r > 0) / n, 1)
    print(f"[{label}] n={n}, 평균={mean}%, 승률={win}%", flush=True)
    return {"n": n, "mean_pct": mean, "win_rate_pct": win}


def main():
    print("S&P500 일별 데이터 조회 중...", flush=True)
    spx_hist = get_multiple_price_history(["^GSPC"], start="1950-01-01", end="2026-08-20", interval="1d")["^GSPC"]
    close = spx_hist["Close"]
    current_year = pd.Timestamp.today().year

    # --- 1) 계절성(5~10월 vs 11~4월), 최근 30년만 ---
    print("\n=== 계절성: 1996년 이후만 ===", flush=True)
    unfav_recent, fav_recent = [], []
    for y in range(RECENT_CUTOFF, current_year):
        try:
            unfav_start, unfav_end = pd.Timestamp(y, 5, 1), pd.Timestamp(y, 10, 31)
            seg = close.loc[unfav_start:unfav_end]
            if len(seg) > 100:
                unfav_recent.append(round(100 * (seg.iloc[-1] / close.asof(unfav_start - pd.Timedelta(days=1)) - 1), 3))
        except Exception:
            pass
        try:
            fav_start, fav_end = pd.Timestamp(y, 11, 1), pd.Timestamp(y + 1, 4, 30)
            seg = close.loc[fav_start:fav_end]
            if len(seg) > 100 and y + 1 < current_year + 1:
                fav_recent.append(round(100 * (seg.iloc[-1] / close.asof(fav_start - pd.Timedelta(days=1)) - 1), 3))
        except Exception:
            pass

    s_unfav_recent = summarize(unfav_recent, "5~10월(최근30년)")
    s_fav_recent = summarize(fav_recent, "11~4월(최근30년)")

    # --- 2) 대선주기, 최근 30년만(1996~) ---
    print("\n=== 대선주기: 1996년 이후만 ===", flush=True)
    cycle_recent = {1: [], 2: [], 3: [], 0: []}
    for y in range(RECENT_CUTOFF, current_year):
        seg = close[close.index.year == y]
        if len(seg) < 100:
            continue
        prior = close[close.index < seg.index[0]]
        if len(prior) == 0:
            continue
        ret = round(100 * (seg.iloc[-1] / prior.iloc[-1] - 1), 3)
        cycle_recent[y % 4].append(ret)

    cycle_summary_recent = {}
    for cy in [1, 2, 3, 0]:
        cycle_summary_recent[str(cy)] = summarize(cycle_recent[cy], f"{YEAR_LABELS[cy]}(최근30년)")

    out_json = {
        "seasonality_recent": {"unfavorable": s_unfav_recent, "favorable": s_fav_recent},
        "cycle_recent": cycle_summary_recent,
        "recent_cutoff": RECENT_CUTOFF,
    }
    with open(f"{OUT_DIR}/recent_period_recheck.json", "w", encoding="utf-8") as f:
        json.dump(out_json, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
