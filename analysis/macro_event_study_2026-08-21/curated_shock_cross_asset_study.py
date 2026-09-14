"""트랙 B x 트랙 E 결합 — 큐레이션된 10건의 충격 사건(curated_shock_events.py에서 이미
검증된 날짜, 여기서는 재검증하지 않고 그대로 재사용)에 대해 채권(TLT)·금(GLD)이 "안전자산
피난처(flight to safety)" 역할을 했는지 검증한다.

트랙 E의 기존 스터디들(CPI 가속/감속, FOMC 금리결정)은 모두 "서서히 진행되는" 정책/데이터
이벤트였다. 여기서는 반대로 "하루 만에 터지는" 급성 충격에 대해 같은 자산들이 어떻게
반응하는지 본다 — 시간 축이 다른 별개의 검증이라는 점을 리포트에 명시한다.

사전등록 가설 (결과를 보기 전에 여기 기록):
H1: 채권(TLT)은 사건일 종가~+5거래일에 평균적으로 양(+)의 반응을 보인다("안전자산으로의
    도피"). TLT는 2002-07월부터 존재하므로, 10건 중 TLT로 테스트 가능한 건수를 그대로 보고한다
    (2002년 이전 사건은 조용히 빼지 않고 명시).
H2: 금(GLD, 2004-11월 상장)은 채권보다 반응이 작고 덜 일관적이다 — 즉 급성 충격 국면에서는
    채권이 금보다 더 신뢰할 만한 안전자산이다(트랙 E의 기존 스터디는 "서서히 진행되는 연준
    정책"에 대한 반응이었고, 이건 다른 시간축의 별개 검증임을 리포트에 명시).
H3 (이 프로젝트에서 이미 3차례 독립적으로 확인된 "시스템 붕괴 vs 비시스템적 공포" 패턴의
    재현/확장 — 트랙 A/B/F 선행 사례를 명시적으로 인용): "시스템적 금융위기"(리먼 2008, SVB
    2023 — 실제 신용/은행 시스템 스트레스)와 "비시스템적 충격"(선거·셧다운·팬데믹선언·관세·
    우크라이나·브렉시트·9·11)을 나눠, 시스템적 사건에서 채권/금의 안전자산 매수세가 더 강하게
    나타나는지 검증한다. 테스트 가능한 시스템적 사건은 단 2건뿐이므로(n=2) 이는 매우 작은
    표본임을 명시하고, 평균이 아니라 개별 사례값을 그대로 보고한다.
"""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json

import pandas as pd

from core.market_data import get_multiple_price_history
from curated_shock_events import EVENTS

OUT_DIR = "/workspaces/Quant/analysis/macro_event_study_2026-08-21"
HORIZONS = [5, 20, 60]
ASSETS = {"TLT": "채권(TLT)", "GLD": "금(GLD)"}
ASSET_START = {"TLT": "2002-07-01", "GLD": "2004-11-01"}

SYSTEMIC = {"2008-09-15", "2023-03-10"}


def main():
    all_dates = sorted(set(e["date"] for e in EVENTS))
    start = "2001-01-01"
    end = "2026-08-20"

    hist = get_multiple_price_history(list(ASSETS.keys()), start=start, end=end, interval="1d")

    results = {}
    case_tables = {}
    for ticker, label in ASSETS.items():
        df = hist.get(ticker)
        if df is None or df.empty:
            print(f"[경고] {ticker} 데이터 없음", flush=True)
            continue
        close = df["Close"]
        idx = close.index
        asset_start = pd.Timestamp(ASSET_START[ticker])

        rows = []
        skipped_pre_listing = []
        for e in EVENTS:
            event_date = pd.Timestamp(e["date"])
            if event_date < asset_start:
                skipped_pre_listing.append(e["date"])
                continue
            pos = idx.searchsorted(event_date)
            if pos >= len(idx) or idx[pos] != event_date:
                print(f"[경고] {ticker}: {e['date']} 거래일 아님/데이터 없음, 스킵", flush=True)
                continue
            if pos + max(HORIZONS) >= len(idx):
                print(f"[경고] {ticker}: {e['date']} 이후 데이터 부족, 스킵", flush=True)
                continue
            day0_close = close.iloc[pos]
            fwd = {f"fwd_{h}d_pct": round(100 * (close.iloc[pos + h] / day0_close - 1), 3) for h in HORIZONS}
            rows.append({
                "date": e["date"], "label": e["label"], "category": e["category"],
                "systemic": e["date"] in SYSTEMIC, **fwd,
            })

        df_rows = pd.DataFrame(rows)
        case_tables[ticker] = rows
        print(f"\n=== {label} === (상장전 제외: {len(skipped_pre_listing)}건 {skipped_pre_listing}, "
              f"테스트가능 n={len(rows)})", flush=True)

        def summarize(sub):
            out = {"n": len(sub)}
            for h in HORIZONS:
                col = f"fwd_{h}d_pct"
                vals = sub[col].dropna()
                out[f"fwd_{h}d_mean_pct"] = round(vals.mean(), 3) if len(vals) else None
                out[f"fwd_{h}d_win_rate_pct"] = round(100 * (vals > 0).mean(), 1) if len(vals) else None
            return out

        overall = summarize(df_rows) if len(df_rows) else {"n": 0}
        systemic_sub = df_rows[df_rows["systemic"]] if len(df_rows) else pd.DataFrame()
        nonsystemic_sub = df_rows[~df_rows["systemic"]] if len(df_rows) else pd.DataFrame()

        print(f"  전체 n={overall.get('n')}, +5일={overall.get('fwd_5d_mean_pct')}%, "
              f"+20일={overall.get('fwd_20d_mean_pct')}%, +60일={overall.get('fwd_60d_mean_pct')}%"
              f"(승률{overall.get('fwd_60d_win_rate_pct')}%)", flush=True)
        for _, r in df_rows.iterrows():
            print(f"    [{'시스템적' if r['systemic'] else '비시스템'}] {r['date']} {r['label']}: "
                  f"+5일={r['fwd_5d_pct']}%, +20일={r['fwd_20d_pct']}%, +60일={r['fwd_60d_pct']}%", flush=True)

        results[ticker] = {
            "label": label,
            "skipped_pre_listing": skipped_pre_listing,
            "n_testable": len(rows),
            "overall": overall,
            "systemic": summarize(systemic_sub),
            "nonsystemic": summarize(nonsystemic_sub),
            "cases": rows,
        }

    with open(f"{OUT_DIR}/curated_shock_cross_asset_study.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
