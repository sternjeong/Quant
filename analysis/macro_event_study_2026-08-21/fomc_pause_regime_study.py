"""연준 "동결 국면"(장기 일시정지) 스터디 &mdash; 트랙 A 신규 이벤트 유형.

지금까지 이 프로젝트의 모든 FOMC 스터디(109건 금리변경 이벤트 스터디, 인상 성격 구분)는
전부 "금리가 바뀐 순간"만 봤다. 아무도 연준이 오래도록 금리를 그대로 두는 "장기 동결 국면"
자체를 본 적이 없다 &mdash; 이 국면이 그 자체로 유의미한지(안정적인 호황 국면일 수도), 아니면
그냥 조용한 무사건(non-event)인지 확인한다.

방법론: `fomc_rate_event_study.py`의 `build_target_rate_series()`(DFEDTAR + DFEDTARU/L
결합 연속 목표금리 시계열)와 `detect_rate_changes()`(변경일 탐지)를 그대로 재사용한다. 이번엔
변경 이벤트 자체가 아니라 "연속된 두 변경일 사이의 간격"(동결 구간)을 계산한다.

"장기 동결" 정의(결과를 보기 전에 사전 확정): 연속된 두 금리변경 이벤트 사이(또는 첫 이벤트
이전/마지막 이벤트 이후)의 간격이 180일(약 6개월) 이상인 구간만 "장기 동결"로 카운트한다.
이 기준은 결과를 본 뒤 조정하지 않는다.

사전등록 가설 (결과를 보기 전에 여기 기록):
H1: 장기 동결 국면 중 S&P500 수익률(연율화, 길이가 다른 동결 구간을 비교 가능하게)이 1990~2026
    전체 기간의 무조건부 연율화 수익률보다 높다 &mdash; 동결은 연준이 경제를 "위기도 아니고
    과열도 아닌 안정 상태"로 판단할 때 나오는 경우가 많아, 실제로 우호적인 배경일 수 있다는
    직관을 검증한다. 비교 전에 무조건부 기준선을 먼저 명시한다.
H2: 동결이 오래 지속될수록(이미 진행된 기간이 길수록) 그 시점부터의 +60거래일 순방향 수익률이
    더 약해진다 &mdash; "평온이 오래갈수록 다음 충격이 가까워진다"는 불안/안일함 누적 서사를,
    각 동결 구간의 200일차 시점 vs 30일차 시점의 +60거래일 수익률을 비교해 검증한다. 동결
    구간 수가 매우 적을 가능성이 크므로(180일 기준 때문에), 이건 구간 간 비교가 아니라 구간
    내부의 시계열 비교임을 명시하고 표본 수에 걸맞은 회의적 태도로 다룬다.
H3 (탐색적, 기존 발견과의 비교): 각 동결 구간이 실제로 어떻게 끝나는지(인상으로, 인하로,
    아니면 데이터가 끝나 아직 진행 중/절단됐는지) 태깅하고, 인하로 끝난 동결의 마지막
    20~60일 시장 움직임이 인상으로 끝난 동결보다 더 나빴는지 비공식적으로 확인한다 &mdash;
    이미 검증된 장단기 금리역전·VIX·신용스프레드 선행지표와는 다른 새로운 각도다.
"""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json

import pandas as pd

from core.market_data import get_multiple_price_history
from fomc_rate_event_study import build_target_rate_series, detect_rate_changes

OUT_DIR = "/workspaces/Quant/analysis/macro_event_study_2026-08-21"
PAUSE_MIN_DAYS = 180
DATA_END = "2026-08-20"


def main():
    print("금리 시계열 구축 중...", flush=True)
    rate = build_target_rate_series()
    events = detect_rate_changes(rate)
    change_dates = sorted(events.index.tolist())
    print(f"금리변경 이벤트 {len(change_dates)}건 ({change_dates[0].date()} ~ {change_dates[-1].date()})", flush=True)

    rate_start = rate.index.min()
    rate_end = min(rate.index.max(), pd.Timestamp(DATA_END))

    # 구간 경계: [시계열 시작, 변경1, 변경2, ..., 변경N, 데이터 끝]
    boundaries = [rate_start] + change_dates + [rate_end]

    spx_hist = get_multiple_price_history(["^GSPC"], start="1989-01-01", end=DATA_END, interval="1d")["^GSPC"]
    close = spx_hist["Close"]
    idx = close.index

    def ending_type(i):
        if i == len(boundaries) - 2:
            return "censored"  # 데이터가 끝나서 절단됨(현재도 진행 중일 수 있음)
        end_date = boundaries[i + 1]
        row = events.loc[end_date] if end_date in events.index else None
        if row is None:
            return "censored"
        return "hike" if row["change_bps"] > 0 else "cut"

    pauses = []
    for i in range(len(boundaries) - 1):
        start_dt, end_dt = boundaries[i], boundaries[i + 1]
        duration_days = (end_dt - start_dt).days
        if duration_days < PAUSE_MIN_DAYS:
            continue
        pauses.append({
            "start": start_dt, "end": end_dt, "duration_days": duration_days,
            "ending_type": ending_type(i),
        })

    print(f"\n180일 이상 장기 동결 구간: {len(pauses)}건", flush=True)
    for p in pauses:
        print(f"  {p['start'].date()} ~ {p['end'].date()} ({p['duration_days']}일, 종료유형={p['ending_type']})", flush=True)

    # 무조건부 연율화 기준선(1990~2026 전체, 거래일 단위)
    full_start = pd.Timestamp("1990-01-01")
    full_close = close[close.index >= full_start]
    total_days = (full_close.index[-1] - full_close.index[0]).days
    total_ret = full_close.iloc[-1] / full_close.iloc[0] - 1
    baseline_annualized = round(100 * ((1 + total_ret) ** (365.25 / total_days) - 1), 3)
    print(f"\n[H1 기준선] 1990~2026 무조건부 연율화 수익률 = {baseline_annualized}%", flush=True)

    # H1: 각 동결 구간의 연율화 수익률
    pause_results = []
    for p in pauses:
        seg = close[(close.index >= p["start"]) & (close.index <= p["end"])]
        if len(seg) < 2:
            continue
        seg_days = (seg.index[-1] - seg.index[0]).days
        seg_ret = seg.iloc[-1] / seg.iloc[0] - 1
        ann = round(100 * ((1 + seg_ret) ** (365.25 / seg_days) - 1), 3) if seg_days > 0 else None
        pause_results.append({**p, "total_return_pct": round(100 * seg_ret, 3), "annualized_pct": ann})

    valid_ann = [p["annualized_pct"] for p in pause_results if p["annualized_pct"] is not None]
    mean_pause_annualized = round(sum(valid_ann) / len(valid_ann), 3) if valid_ann else None
    n_beat_baseline = sum(1 for a in valid_ann if a > baseline_annualized)
    print(f"\n[H1] 동결 구간 평균 연율화 수익률 = {mean_pause_annualized}% (기준선 {baseline_annualized}%), "
          f"기준선 상회 구간 {n_beat_baseline}/{len(valid_ann)}", flush=True)
    for p in pause_results:
        print(f"  {p['start'].date()}~{p['end'].date()}: 연율화={p['annualized_pct']}%", flush=True)

    # H2: 동결 구간 내 day30 vs day200 기준 +60거래일 순방향 수익률
    print("\n[H2] 동결 구간 내부 day30 vs day200 기준 +60거래일 순방향 수익률", flush=True)
    h2_results = []
    for p in pause_results:
        seg_idx_start = idx.searchsorted(p["start"])
        seg_idx_end = idx.searchsorted(p["end"])
        day30_pos = seg_idx_start + 30
        day200_pos = seg_idx_start + 200
        entry = {"start": str(p["start"].date()), "end": str(p["end"].date())}
        if day30_pos + 60 <= seg_idx_end and day30_pos < len(idx):
            entry["fwd60_from_day30"] = round(100 * (close.iloc[day30_pos + 60] / close.iloc[day30_pos] - 1), 3)
        else:
            entry["fwd60_from_day30"] = None
        if day200_pos + 60 <= seg_idx_end and day200_pos < len(idx):
            entry["fwd60_from_day200"] = round(100 * (close.iloc[day200_pos + 60] / close.iloc[day200_pos] - 1), 3)
        else:
            entry["fwd60_from_day200"] = None
        h2_results.append(entry)
        print(f"  {entry['start']}~{entry['end']}: day30발={entry['fwd60_from_day30']}%, "
              f"day200발={entry['fwd60_from_day200']}%", flush=True)

    day30_vals = [e["fwd60_from_day30"] for e in h2_results if e["fwd60_from_day30"] is not None]
    day200_vals = [e["fwd60_from_day200"] for e in h2_results if e["fwd60_from_day200"] is not None]
    day30_mean = round(sum(day30_vals) / len(day30_vals), 3) if day30_vals else None
    day200_mean = round(sum(day200_vals) / len(day200_vals), 3) if day200_vals else None
    print(f"\n[H2] day30 평균(+60일)={day30_mean}%(n={len(day30_vals)}), "
          f"day200 평균(+60일)={day200_mean}%(n={len(day200_vals)})", flush=True)

    # H3: 종료유형별 마지막 20/60일 구간 반응
    print("\n[H3] 종료 유형별 동결 마지막 20/60거래일 반응", flush=True)
    h3_results = []
    for p in pause_results:
        if p["ending_type"] == "censored":
            continue
        end_pos = idx.searchsorted(p["end"])
        if end_pos >= len(idx):
            continue
        entry = {"start": str(p["start"].date()), "end": str(p["end"].date()), "ending_type": p["ending_type"]}
        for h in [20, 60]:
            pre_pos = end_pos - h
            if pre_pos >= 0:
                entry[f"pre_{h}d_pct"] = round(100 * (close.iloc[end_pos] / close.iloc[pre_pos] - 1), 3)
            else:
                entry[f"pre_{h}d_pct"] = None
        h3_results.append(entry)
        print(f"  {entry['start']}~{entry['end']} ({entry['ending_type']}): "
              f"종료전20일={entry.get('pre_20d_pct')}%, 종료전60일={entry.get('pre_60d_pct')}%", flush=True)

    cut_ending = [e for e in h3_results if e["ending_type"] == "cut"]
    hike_ending = [e for e in h3_results if e["ending_type"] == "hike"]

    def avg(lst, key):
        vals = [e[key] for e in lst if e.get(key) is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    print(f"\n[H3] 인하로 끝난 동결(n={len(cut_ending)}) 종료전20일 평균={avg(cut_ending,'pre_20d_pct')}%, "
          f"종료전60일 평균={avg(cut_ending,'pre_60d_pct')}%", flush=True)
    print(f"[H3] 인상으로 끝난 동결(n={len(hike_ending)}) 종료전20일 평균={avg(hike_ending,'pre_20d_pct')}%, "
          f"종료전60일 평균={avg(hike_ending,'pre_60d_pct')}%", flush=True)

    out = {
        "pause_min_days": PAUSE_MIN_DAYS,
        "baseline_annualized_pct": baseline_annualized,
        "pauses": [
            {"start": str(p["start"].date()), "end": str(p["end"].date()), "duration_days": p["duration_days"],
             "ending_type": p["ending_type"], "total_return_pct": p["total_return_pct"], "annualized_pct": p["annualized_pct"]}
            for p in pause_results
        ],
        "h1": {"mean_pause_annualized": mean_pause_annualized, "n_beat_baseline": n_beat_baseline, "n_total": len(valid_ann)},
        "h2": {"day30_mean": day30_mean, "day200_mean": day200_mean, "detail": h2_results},
        "h3": {
            "cut_ending_n": len(cut_ending), "cut_ending_pre20_mean": avg(cut_ending, "pre_20d_pct"),
            "cut_ending_pre60_mean": avg(cut_ending, "pre_60d_pct"),
            "hike_ending_n": len(hike_ending), "hike_ending_pre20_mean": avg(hike_ending, "pre_20d_pct"),
            "hike_ending_pre60_mean": avg(hike_ending, "pre_60d_pct"),
            "detail": h3_results,
        },
    }
    with open(f"{OUT_DIR}/fomc_pause_regime_study.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
