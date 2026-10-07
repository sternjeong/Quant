from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
INPUT = ROOT / "data/research_inputs/crsp_delisted"
REQUIRED_DAILY = {"permno", "date", "prc", "ret", "vol", "shrout"}
REQUIRED_DELIST = {"permno", "date", "dlret", "dlstcd"}
WARNINGS = {"mom12_le_minus50pct": "mom12", "drawdown_le_minus60pct": "drawdown",
            "vol60_ge_80pct": "vol60", "price_le_5usd": "price", "dollar_volume_change_le_minus70pct": "dollar_volume_change"}


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def synthetic():
    rows, events = [], []
    ix = pd.bdate_range("2018-01-01", periods=900)
    rng = np.random.default_rng(260107)
    for permno in range(20):
        ret = rng.normal(.0002, .02, len(ix))
        if permno < 8:
            ret[-150:] = -.008
        price = 30 * np.cumprod(1 + ret)
        for dt, r, p in zip(ix, ret, price):
            rows.append((permno, dt, p, r, 10000, 1000000, 2000))
        if permno < 8:
            events.append((permno, ix[-1], -.7, 500, 2000))
    events.extend([(98, ix[-1], -88.0, 500, 2000), (99, ix[-1], -99.0, 500, 2000)])
    return pd.DataFrame(rows, columns=["permno", "date", "prc", "ret", "vol", "shrout", "siccd"]), pd.DataFrame(events, columns=["permno", "date", "dlret", "dlstcd", "siccd"])


def features(hist, event_date):
    h = hist.loc[hist.date <= event_date].copy()
    h["ret"] = pd.to_numeric(h.ret, errors="coerce")
    # CRSP special/missing return codes are outside a valid simple-return range.
    h = h.loc[h.ret >= -1.0].tail(252)
    if len(h) < 252:
        return None
    r = h.ret
    total = (1 + r).cumprod()
    price = abs(float(h.prc.iloc[-1]))
    dollar = abs(pd.to_numeric(h.prc, errors="coerce")) * pd.to_numeric(h.vol, errors="coerce")
    prior = dollar.iloc[:192].mean()
    recent = dollar.iloc[-20:].mean()
    return {"mom6": float(total.iloc[-1] / total.iloc[-127] - 1),
            "mom12": float(total.iloc[-1] - 1),
            "drawdown": float((total / total.cummax() - 1).min()),
            "vol60": float(r.tail(60).std(ddof=1) * np.sqrt(252)), "price": price,
            "dollar_volume_change": float(recent / prior - 1) if prior and prior > 0 else np.nan,
            "siccd": int(h.siccd.iloc[-1]) if "siccd" in h and pd.notna(h.siccd.iloc[-1]) else None}


def analyze(daily, delists):
    daily = daily.copy(); delists = delists.copy()
    daily["date"] = pd.to_datetime(daily.date); delists["date"] = pd.to_datetime(delists.date)
    daily["permno"] = pd.to_numeric(daily.permno, errors="coerce")
    delists["permno"] = pd.to_numeric(delists.permno, errors="coerce")
    daily = daily.dropna(subset=["permno", "date"]).sort_values(["permno", "date"])
    delists = delists.dropna(subset=["permno", "date", "dlret"])
    delists["dlret"] = pd.to_numeric(delists.dlret, errors="coerce")
    valid_dlret = delists.dlret.between(-1.0, 1.0, inclusive="both")
    events = delists[valid_dlret & (delists.dlret <= -.50)].sort_values("date").drop_duplicates("permno", keep="first").copy()
    events["label"] = "adverse_delist_dlret_le_-50pct"
    positives, controls = [], []
    by_id = {int(k): v for k, v in daily.groupby("permno", sort=False)}
    all_ids = set(by_id)
    for e in events.itertuples(index=False):
        h = by_id.get(int(e.permno))
        if h is None:
            continue
        # Landmark is the 126th observed trading record before the event date.
        pre = h[h.date < e.date]
        if len(pre) < 378:
            continue
        landmark = pd.Timestamp(pre.iloc[-126].date)
        f = features(h, landmark)
        if f is None:
            continue
        positives.append({"permno": int(e.permno), "date": str(landmark.date()), **f,
                          "dlret": float(e.dlret), "dlstcd": int(e.dlstcd) if pd.notna(e.dlstcd) else None})
        # Deterministic same-year controls without a delist event in the forward 252-row window.
        candidates = []
        for cid in all_ids:
            if cid == int(e.permno):
                continue
            ch = by_id[cid]
            point = ch[ch.date <= landmark]
            if len(point) < 252:
                continue
            future = ch[(ch.date > landmark) & (ch.date <= landmark + pd.Timedelta(370, unit="D"))]
            if len(future) < 126 or ((delists.permno == cid) & (delists.date > landmark) & (delists.date <= landmark + pd.Timedelta(370, unit="D"))).any():
                continue
            cf = features(ch, landmark)
            if cf is None:
                continue
            if f["siccd"] is not None and (cf["siccd"] is None or cf["siccd"] // 100 != f["siccd"] // 100):
                continue
            candidates.append((cid, cf))
        candidates.sort(key=lambda x: ((x[0] * 2654435761 + int(landmark.strftime("%Y%m%d"))) % 2147483647, x[0]))
        for cid, cf in candidates[:5]:
            controls.append({"permno": cid, "date": str(landmark.date()), **cf, "dlret": None, "dlstcd": None})
    return positives, controls, events


def signal_table(cases, controls):
    rows = []
    limits = {"mom12_le_minus50pct": lambda d: d.mom12 <= -.50,
              "drawdown_le_minus60pct": lambda d: d.drawdown <= -.60,
              "vol60_ge_80pct": lambda d: d.vol60 >= .80,
              "price_le_5usd": lambda d: d.price <= 5,
              "dollar_volume_change_le_minus70pct": lambda d: d.dollar_volume_change <= -.70}
    c, n = pd.DataFrame(cases), pd.DataFrame(controls)
    for name, fn in limits.items():
        if c.empty or n.empty:
            rows.append({"signal": name, "case_rate": None, "control_rate": None, "risk_ratio": None, "ci95": None})
            continue
        a, b = int(fn(c).sum()), int(fn(n).sum())
        ca, cn = len(c), len(n)
        rr = ((a + .5) / (ca + 1)) / ((b + .5) / (cn + 1))
        rng = np.random.default_rng(260107)
        boots = []
        case_groups = {k: v for k, v in c.groupby("permno")}
        control_groups = {k: v for k, v in n.groupby("permno")}
        case_ids, control_ids = np.array(list(case_groups)), np.array(list(control_groups))
        for _ in range(2000):
            c_sample = pd.concat([case_groups[k] for k in rng.choice(case_ids, len(case_ids), replace=True)], ignore_index=True)
            n_sample = pd.concat([control_groups[k] for k in rng.choice(control_ids, len(control_ids), replace=True)], ignore_index=True)
            ab, bb = int(fn(c_sample).sum()), int(fn(n_sample).sum())
            boots.append(((ab + .5) / (len(c_sample) + 1)) / ((bb + .5) / (len(n_sample) + 1)))
        rows.append({"signal": name, "case_rate": a / ca, "control_rate": b / cn, "risk_ratio": rr,
                     "ci95": [float(np.quantile(boots, .025)), float(np.quantile(boots, .975))], "cases_flagged": a, "controls_flagged": b})
    return rows


def main(argv=None):
    p = argparse.ArgumentParser(); p.add_argument("--out", required=True); p.add_argument("--checkpoint", required=True); p.add_argument("--smoke", action="store_true")
    a = p.parse_args(argv); out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    daily_path, delist_path = INPUT / "daily.csv", INPUT / "delists.csv"
    if a.smoke:
        daily, delists = synthetic()
        hashes = {"daily": "SYNTHETIC", "delists": "SYNTHETIC"}
    elif daily_path.exists() and delist_path.exists():
        daily, delists = pd.read_csv(daily_path), pd.read_csv(delist_path)
        hashes = {"daily": digest(daily_path), "delists": digest(delist_path)}
    else:
        payload = {"id": "delisted-precursors-v1", "verdicts": {"study": "NOT_EVALUABLE_DATA"}, "smoke": False,
                   "input_status": "CRSP_EXPORT_NOT_FOUND", "expected_files": [str(daily_path.relative_to(ROOT)), str(delist_path.relative_to(ROOT))],
                   "required_daily_columns": sorted(REQUIRED_DAILY), "required_delist_columns": sorted(REQUIRED_DELIST),
                   "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        (out / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        (out / "REPORT.md").write_text("# 상장폐지 사전 위험신호 연구\n\nCRSP 내보내기 파일이 VM 입력 경로에 아직 없습니다. 상폐 성과 판정은 수행하지 않았습니다. SPEC의 파일·열 계약에 따라 자료를 배치한 뒤 별도 재시도가 필요합니다.\n", encoding="utf-8")
        return 0
    missing = {"daily": sorted(REQUIRED_DAILY - set(daily)), "delists": sorted(REQUIRED_DELIST - set(delists))}
    if any(missing.values()):
        verdict = "NOT_EVALUABLE_DATA"
        cases, controls, events = [], [], pd.DataFrame()
        table = []
    else:
        cases, controls, events = analyze(daily, delists)
        table = signal_table(cases, controls)
        years = (pd.to_datetime(delists.date).max() - pd.to_datetime(delists.date).min()).days / 365.25 if len(delists) else 0
        verdict = "SMOKE_ONLY" if a.smoke else ("EVALUABLE_DESCRIPTIVE" if len(cases) >= 100 and years >= 5 else "NOT_EVALUABLE_SAMPLE")
    dlret_numeric = pd.to_numeric(delists.dlret, errors="coerce") if "dlret" in delists else pd.Series(dtype=float)
    payload = {"id": "delisted-precursors-v1", "smoke": a.smoke, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "verdicts": {"study": verdict}, "input_sha256": hashes, "missing_columns": missing,
               "daily_rows": len(daily), "delist_rows": len(delists), "adverse_events_dlret_le_minus50pct": int((dlret_numeric.between(-1.0, 1.0) & (dlret_numeric <= -.5)).sum()),
               "unique_adverse_firms": len(cases), "severe_delist_dlret_le_minus80pct": int((dlret_numeric.between(-1.0, 1.0) & (dlret_numeric <= -.8)).sum()),
               "dlret_missing_code_counts": {str(code): int((dlret_numeric == code).sum()) for code in (-55.0, -66.0, -88.0, -99.0)},
               "cases_with_features": len(cases), "controls": len(controls), "period": [str(pd.to_datetime(daily.date).min().date()), str(pd.to_datetime(daily.date).max().date())],
               "siccd_available": "siccd" in daily, "industry_match_status": "matched_sic2" if "siccd" in daily else "NOT_EVALUABLE_INDUSTRY_MATCH", "warning_signals": table}
    (out / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    lines = ["# 상장폐지·급락 종목 사전 위험신호 결과", "", f"판정: **{verdict}** · 사건 {payload['adverse_events_dlret_le_minus50pct']}건 · 기준일 특성 계산 {len(cases)}건 · 대조 관측 {len(controls)}건", "",
             "CRSP 상폐수익률(dlret ≤ -50%)을 사건으로 삼았고, 상폐일 126 거래 관측치 전에 알 수 있던 신호만 사용했습니다. 지수 편출은 상폐로 라벨링하지 않았습니다.", "",
             "| 사전 신호 | 사건 비율 | 대조군 비율 | 위험비 | 95% 구간 |", "|---|---:|---:|---:|---:|"]
    for row in table:
        fmt = lambda x: "—" if x is None else f"{x:.3f}"
        ci = "—" if row["ci95"] is None else f"[{row['ci95'][0]:.2f}, {row['ci95'][1]:.2f}]"
        lines.append(f"| {row['signal']} | {fmt(row['case_rate'])} | {fmt(row['control_rate'])} | {fmt(row['risk_ratio'])} | {ci} |")
    lines += ["", "기술적 관찰 연구이며 종목 제외 규칙으로 바로 쓰지 않습니다. `NOT_EVALUABLE_*`는 데이터/표본이 판정을 뒷받침하지 못했다는 뜻입니다."]
    (out / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
