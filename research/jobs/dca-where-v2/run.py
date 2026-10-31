"""검증 연구 dca-where-v2 (2026-10-22 사전 등록): 팔지 않는 월 적립의 새 돈을 '어디에' 넣을까 — 반등 확인·나눠 넣기·상대 가격·스타일·49 산업.

사용자 요청(2026-10-22): '어디에 넣느냐'도 설계해 달라. 길게 보고 싸게 사서 누리자는 원칙, 웬만해서는 팔지 않음, 월 10만 원.
dca-asset-pick-v1 은 12 산업 중 한 곳에 몰아 넣는 단순 규칙이었다. v2 는 v1 에 없던 축을 더한다:
  - 떨어지는 칼 피하기: 많이 빠졌지만 20주선을 다시 넘은(반등 확인) 산업만 산다.
  - 몰림 막기: 상위 3·5 곳에 나눠 넣기, 시장 70% + 고른 곳 30%.
  - 상대 가격: 시장 대비 가격이 자기 5년 평균보다 가장 싸진 산업.
  - 스타일: 대형·소형 × 성장·중립·가치 6 묶음 중 3년간 가장 뒤처진 것, 소형 가치주.
  - 더 세밀한 메뉴: 49 산업 중 3년 수익 하위 5.
계좌·구간·판정은 dca-asset-pick-v1 과 같다(팔지 않음, 시나리오 M 월 10만 원, 청산 세후, 1927~1966·1967~2007 두 반쪽 × 10·20년). 엔진은 바뀌지 않는다.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import signal as _signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "research/jobs/dca-dip-deploy-v1"))

import lab as L  # noqa: E402

V1 = L._load_mod("_dca_asset_pick_v1", "research/jobs/dca-asset-pick-v1/run.py")

JOB_ID = "dca-where-v2"
RULES_VERSION = "dca-where-v2/2026-10-22"

# --- 고정 상수 (사전 등록) ---------------------------------------------------------------------------
MONTHLY_KRW = 100_000
SCENARIOS = {"M": (0, MONTHLY_KRW), "H": (10_000_000, MONTHLY_KRW)}
PRIMARY = "M"
HORIZONS = (10, 20)
JUDGED_SETS = ("selection", "confirmation")
BASE = "MKT"
ARMS = ("DDCONF", "TILT30", "REV3", "MOM3", "RELLOW", "STYLE_LAG", "SV", "REV49_5")
N_TRIALS = len(ARMS)
LABELS = {"MKT": "시장(기준)",
          "DDCONF": "1년 고점 −20% 이하 + 20주선 재돌파한 산업 중 가장 빠진 곳(없으면 시장)",
          "TILT30": "시장 70% + DDCONF 30%",
          "REV3": "3년 수익 하위 3 산업에 나눔",
          "MOM3": "12-1개월 수익 상위 3 산업에 나눔",
          "RELLOW": "시장 대비 가격이 자기 5년 평균보다 가장 싸진 산업",
          "STYLE_LAG": "6 스타일 중 3년 수익 가장 낮은 것",
          "SV": "소형 가치주",
          "REV49_5": "49 산업 중 3년 수익 하위 5 에 나눔"}
STYLES = {"SMALL LoBM": "소형 성장", "ME1 BM3": "소형 중립", "SMALL HiBM": "소형 가치",
          "BIG LoBM": "대형 성장", "ME5 BM3": "대형 중립", "BIG HiBM": "대형 가치"}
DD_ROWS, DD_LEVEL, MA_WEEKS = 252, -0.20, 20
REV_ROWS, MOM_ROWS, MOM_SKIP, REL_ROWS = 756, 252, 21, 1260
TILT_W = 0.30

WIN_SHARE_MIN = V1.WIN_SHARE_MIN
MEDIAN_IRR_MIN = V1.MEDIAN_IRR_MIN
P10_IRR_MIN = V1.P10_IRR_MIN
MDD_TOL = V1.MDD_TOL
PASS, FAIL = "BEATS_MARKET", "FAIL"
DEADLINE_MARGIN = 120.0
SIZE_LIMIT = 190_000


class _Stop(Exception):
    pass


# =================================================================================================
# 자료
# =================================================================================================

def load_real() -> dict[str, Any]:
    from core import french_factors as ff

    ff3, i12, i49, p25 = ff.load("ff3_daily"), ff.load("ind12_daily"), ff.load("ind49_daily"), ff.load("ports25_daily")
    if any(x is None for x in (ff3, i12, i49, p25)) or any(c not in p25 for c in STYLES):
        raise RuntimeError("Ken French 일별 FF3 / 12·49 산업 / 25 규모×BM 자료를 받지 못함")
    out = L.lab._normalize(ff3["RF"], ff3["Mkt-RF"] + ff3["RF"], i12, i49)
    idx = out["rf"].index
    st = L.lab.to_weekdays(p25[list(STYLES)].astype(float))
    out["styles"] = L.lab.clean_industry(st).reindex(idx)
    out["source"] = "Ken French data library (daily, weekday calendar; FF3 market, 12 & 49 industries VW, 25 size×BM VW corners/middles)"
    return out


def load_synthetic(seed: int = 7) -> dict[str, Any]:
    d = L.lab.synthetic_data(seed=seed)
    idx = d["rf"].index
    rng = np.random.default_rng(seed + 5)
    beta = np.array([1.3, 1.15, 1.2, 1.0, 0.95, 1.05])
    st = d["mkt"].to_numpy()[:, None] * beta + rng.normal(0.00005, 0.005, (len(idx), 6))
    d["styles"] = pd.DataFrame(st, index=idx, columns=list(STYLES))
    return d


# =================================================================================================
# 고르기 (행 t 의 선택 = 행 t−1 종가까지의 자료)
# =================================================================================================

def weekly_above_ma(px: pd.DataFrame) -> pd.DataFrame:
    """각 열의 주 종가 > 20주 평균(그 주 마지막 거래일에 확정, 다음 주 마지막 날 전까지 유지)."""
    per = px.index.to_period("W-FRI")
    last = np.r_[per[1:] != per[:-1], True]
    wk = px[last]
    above = (wk > wk.rolling(MA_WEEKS, min_periods=MA_WEEKS).mean()).astype(float).where(wk.notna())
    return above.reindex(px.index).ffill()


def tables(ind_px: pd.DataFrame, i49_px: pd.DataFrame, st_px: pd.DataFrame, mkt_px: pd.Series) -> dict[str, np.ndarray]:
    dd = ind_px / ind_px.rolling(DD_ROWS, min_periods=DD_ROWS).max() - 1.0
    up = weekly_above_ma(ind_px)
    rel = ind_px.div(mkt_px, axis=0)
    t = {"dd": dd, "up": up,
         "rev12": ind_px / ind_px.shift(REV_ROWS) - 1.0,
         "mom12": ind_px.shift(MOM_SKIP) / ind_px.shift(MOM_ROWS) - 1.0,
         "rel": rel / rel.rolling(REL_ROWS, min_periods=REL_ROWS).mean() - 1.0,
         "revst": st_px / st_px.shift(REV_ROWS) - 1.0,
         "rev49": i49_px / i49_px.shift(REV_ROWS) - 1.0}
    return {k: v.shift(1).to_numpy(dtype=float) for k, v in t.items()}


def lowest(row: np.ndarray, k: int) -> list[int]:
    ok = np.flatnonzero(np.isfinite(row))
    if len(ok) < k:
        return []
    return list(ok[np.argsort(row[ok], kind="stable")[:k]])


def ddconf_pick(tb: dict, r: int) -> int:
    dd, up = tb["dd"][r], tb["up"][r]
    cand = np.flatnonzero(np.isfinite(dd) & (dd <= DD_LEVEL) & (up == 1.0))
    return int(cand[np.argmin(dd[cand])]) if len(cand) else -1


def allocation(arm: str, r: int, tb: dict, off: dict) -> list[tuple[int, float]]:
    """한 적립의 [(열, 비중)]. 고를 수 없으면 시장(열 0)."""
    mk = [(0, 1.0)]
    if arm == BASE:
        return mk
    if arm in ("DDCONF", "TILT30"):
        j = ddconf_pick(tb, r)
        if j < 0:
            return mk
        return [(off["i12"] + j, 1.0)] if arm == "DDCONF" else [(0, 1 - TILT_W), (off["i12"] + j, TILT_W)]
    if arm == "REV3":
        js = lowest(tb["rev12"][r], 3)
        return [(off["i12"] + j, 1 / 3) for j in js] or mk
    if arm == "MOM3":
        js = lowest(-tb["mom12"][r], 3)
        return [(off["i12"] + j, 1 / 3) for j in js] or mk
    if arm == "RELLOW":
        js = lowest(tb["rel"][r], 1)
        return [(off["i12"] + js[0], 1.0)] if js else mk
    if arm == "STYLE_LAG":
        js = lowest(tb["revst"][r], 1)
        return [(off["st"] + js[0], 1.0)] if js else mk
    if arm == "SV":
        return [(off["sv"], 1.0)]
    if arm == "REV49_5":
        js = lowest(tb["rev49"][r], 5)
        return [(off["i49"] + j, 0.2) for j in js] or mk
    raise ValueError(arm)


def run_window(px, cg, days, tb, off, s, e, scen) -> dict:
    init, monthly = SCENARIOS[scen]
    rows = L.contribution_rows(days, s, e)
    end_row = days.searchsorted(e, side="right") - 1
    start_row = rows[0]
    amounts = np.full(len(rows), float(monthly))
    lump = 0
    if init > 0:
        rows = np.concatenate([[rows[0]], rows])
        amounts = np.concatenate([[float(init)], amounts])
        lump = 1
    out = {}
    for arm in (BASE,) + ARMS:
        rr, aa, am = [], [], []
        for i, (r, amt) in enumerate(zip(rows, amounts)):
            alloc = [(0, 1.0)] if i < lump else allocation(arm, r, tb, off)
            for c, w in alloc:
                if not np.isfinite(px[r, c]):
                    c = 0
                rr.append(r)
                aa.append(c)
                am.append(amt * w)
        rr, aa, am = np.array(rr), np.array(aa), np.array(am)
        sim = L.simulate_buy_only(px, cg, rr, am, rr.copy(), aa, end_row, start_row)
        u = np.zeros(px.shape[1])
        np.add.at(u, aa, am / px[rr, aa])
        v_end = np.nan_to_num(u * px[end_row])
        out[arm] = {"irr": L.xirr_monthly(amounts, rows, end_row, sim["terminal"], days), "terminal": sim["terminal"],
                    "mdd": sim["mdd"], "top_share": float(v_end.max() / max(v_end.sum(), 1e-12)),
                    "mkt_share": float(np.sum(am[aa == 0]) / am.sum())}
    return out


# =================================================================================================
# 실행
# =================================================================================================

def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--smoke", action="store_true")
    a = p.parse_args(argv)
    out, ck = Path(a.out), Path(a.checkpoint)
    out.mkdir(parents=True, exist_ok=True)
    ck.mkdir(parents=True, exist_ok=True)
    fp = {"rules": RULES_VERSION, "smoke": bool(a.smoke)}
    dl_epoch = float(os.environ.get("RESEARCH_JOB_DEADLINE_EPOCH") or 0) or None
    t0 = time.time()

    def log(s):
        print(s, flush=True)

    def check_time():
        if dl_epoch is not None and time.time() > dl_epoch - DEADLINE_MARGIN:
            raise _Stop()

    def stage(name, fn):
        path = ck / f"{name}.pkl"
        got = V1._load_ckpt(path, fp)
        if got is None:
            check_time()
            got = fn()
            V1._atomic_pickle(path, {"fingerprint": fp, "payload": got})
            log(f"단계 저장: {name} ({time.time() - t0:.0f}초)")
        return got

    def on_term(signum, frame):  # noqa: ARG001
        raise _Stop()

    old = _signal.signal(_signal.SIGTERM, on_term) if hasattr(_signal, "SIGTERM") else None
    try:
        data = stage("inputs", lambda: load_synthetic() if a.smoke else load_real())
        days = data["mkt"].dropna().index
        mkt_px = L.level(data["mkt"].reindex(days))
        i12 = data["ind12"].reindex(days).apply(L.level)
        i49 = data["ind49"].reindex(days).apply(L.level)
        st = data["styles"].reindex(days).apply(L.level)
        panel = pd.concat([mkt_px.rename("MKT"), i12.add_prefix("i12:"), i49.add_prefix("i49:"), st.add_prefix("st:")], axis=1)
        off = {"i12": 1, "i49": 1 + i12.shape[1], "st": 1 + i12.shape[1] + i49.shape[1]}
        off["sv"] = off["st"] + list(STYLES).index("SMALL HiBM")
        px = panel.to_numpy(dtype=float)
        cg = np.cumprod(1 + data["rf"].reindex(days).fillna(0.0).to_numpy() * (1 - L.INTEREST_TAX))
        tb = tables(i12, i49, st, mkt_px)
        cells: dict[str, dict] = {}
        for hz in HORIZONS:
            sets = L.window_sets(days, hz, a.smoke)
            for scen in SCENARIOS:
                def compute(sets=sets, scen=scen):
                    res = {}
                    for sn, wins in sets.items():
                        rr = []
                        for s, e in wins:
                            rr.append(((s, e), run_window(px, cg, days, tb, off, s, e, scen)))
                            check_time()
                        res[sn] = {arm: L.summarize_pairs(V1.pair_rows(rr, arm)) for arm in ARMS}
                        for arm in (BASE,) + ARMS:
                            res[sn].setdefault(arm, {})
                            if rr:
                                res[sn][arm]["median_top_share"] = float(np.nanmedian([x[1][arm]["top_share"] for x in rr]))
                                res[sn][arm]["median_mkt_share"] = float(np.nanmedian([x[1][arm]["mkt_share"] for x in rr]))
                        res[sn]["_base"] = {"median_irr": float(np.nanmedian([x[1][BASE]["irr"] for x in rr])) if rr else None,
                                            "median_mdd": float(np.nanmedian([x[1][BASE]["mdd"] for x in rr])) if rr else None}
                    return res
                cells[f"{scen}|{hz}y"] = stage(f"cell_{scen}_{hz}y", compute)
        last_row = len(days) - 1
        names = list(panel.columns)
        now = {arm: [(names[c], round(w, 3)) for c, w in allocation(arm, last_row, tb, off)] for arm in ARMS}
        result = build_result(cells, now, str(days[-1].date()), a.smoke, data.get("source"))
        if a.smoke:
            c10 = cells[f"{PRIMARY}|10y"]["selection"]
            cov = {"all_cells": len(cells) == len(SCENARIOS) * len(HORIZONS),
                   "judged_nonempty": all(cells[f"{PRIMARY}|{h}y"][s][ARMS[0]].get("n_windows", 0) > 0 for h in HORIZONS for s in JUDGED_SETS),
                   "ddconf_picks_industries": any(cells[k][sn]["DDCONF"].get("median_mkt_share", 1.0) < 1.0 for k in cells for sn in cells[k]),
                   "tilt_keeps_market": c10["TILT30"]["median_mkt_share"] >= 1 - TILT_W - 1e-9,
                   "split_less_concentrated": c10["REV3"]["median_top_share"] < 1.0,
                   "arms_differ": len({round(c10[k].get("median_diff_irr", 0), 8) for k in ARMS}) > 3}
            result["smoke_coverage"] = cov
            bad = [k for k, v in cov.items() if not v]
            if bad:
                raise RuntimeError(f"스모크가 다음 상태를 지나지 않음: {bad}")
    except _Stop:
        log(f"시간 예산 끝 — 체크포인트 저장됨, 다음 회차에 이어서 ({time.time() - t0:.0f}초)")
        return 3
    finally:
        if old is not None:
            _signal.signal(_signal.SIGTERM, old)
    text = json.dumps(result, ensure_ascii=False, separators=(",", ":"), default=str)
    (out / "results.json").write_text(text, encoding="utf-8")
    (out / "REPORT.md").write_text(render(result), encoding="utf-8")
    log(json.dumps(result["verdicts"], ensure_ascii=False))
    log(f"완료 ({time.time() - t0:.0f}초)")
    return 0


def build_result(cells, now, last_day, smoke, source) -> dict:
    verdicts: dict[str, Any] = {}
    checks: dict[str, dict] = {}
    for arm in ARMS:
        ch = {f"{s}|{h}y": V1.checks_for(cells[f"{PRIMARY}|{h}y"][s][arm]) for h in HORIZONS for s in JUDGED_SETS}
        checks[arm] = ch
        ok = all(c is not None and all(v is True for v in c.values()) for c in ch.values())
        verdicts[arm] = f"SMOKE_ONLY({PASS if ok else FAIL})" if smoke else (PASS if ok else FAIL)
    verdicts["passed"] = f"{sum(v == PASS for k, v in verdicts.items() if k in ARMS)}/{N_TRIALS}"
    verdicts["scenario"] = f"M: {MONTHLY_KRW:,} KRW/month, never sell, after liquidation tax, 1927-2007 halves, 10y+20y, vs market"
    return V1._r({"judge_version": RULES_VERSION, "smoke": smoke, "source": source,
                  "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "verdicts": verdicts, "checks": checks, "cells": cells, "last_day": last_day, "allocation_now": now,
                  "rule": {"monthly_krw": MONTHLY_KRW, "horizons": list(HORIZONS),
                           "thresholds": {"win_share_min": WIN_SHARE_MIN, "median_irr_min": MEDIAN_IRR_MIN,
                                          "p10_irr_min": P10_IRR_MIN, "mdd_tol": MDD_TOL},
                           "params": {"dd_rows": DD_ROWS, "dd_level": DD_LEVEL, "ma_weeks": MA_WEEKS, "rev_rows": REV_ROWS,
                                      "mom": [MOM_ROWS, MOM_SKIP], "rel_rows": REL_ROWS, "tilt": TILT_W},
                           "styles": STYLES, "labels": LABELS}})


def render(r: dict) -> str:
    v = r["verdicts"]
    _p, _yn = V1._p, V1._yn
    out = [f"# 팔지 않는 적립 — 새 돈을 어디에 넣을까 v2 ({r['judge_version']}){' — 스모크(가짜 데이터)' if r['smoke'] else ''}", "",
           "월 10만 원을 늘 바로 넣고 절대 팔지 않을 때, 넣을 곳을 고르는 규칙이 시장 전체보다 세후로 많이 남기는지 1927~2024 미국 자료로 본다. "
           "v1(12 산업 한 곳 몰빵)에 반등 확인·나눠 넣기·상대 가격·스타일·49 산업을 더했다.", "",
           f"**판정(대 시장, 두 반쪽 × 10·20년 모두): 통과 {v['passed']}**", ""]
    out += [f"- {LABELS[a]}: **{v[a]}**" for a in ARMS]
    out += ["", "통과는 엔진 반영이 아니다. 엔진은 바뀌지 않았다.", "",
            "## 규칙 (결과를 보기 전에 고정)", "",
            "- 매달 첫 거래일 10만 원, 전날 종가까지의 자료로 고른 곳을 그날 종가에 산다. 절대 팔지 않는다. 끝에 모두 판다고 보고 양도세 22%(250만 원 공제). "
            "수수료 0.1% + 환전 0.05%, 환율 1,300 원 고정.",
            "- 구간: 매달 시작하는 10·20년. 선택 반쪽(끝 ≤ 1966)·확인 반쪽(1967~2007). 2008 이후 끝은 보고만.",
            f"- 통과: 네 칸 모두 ① 시장보다 많이 남은 구간 ≥ {WIN_SHARE_MIN:.0%} ② 세후 IRR 차이 중앙값 ≥ +{MEDIAN_IRR_MIN * 100:.1f}%p "
            f"③ 10분위 ≥ {P10_IRR_MIN * 100:.1f}%p ④ 계좌 최대낙폭 중앙값이 {MDD_TOL * 100:.0f}%p 넘게 나쁘지 않음.", ""]
    for h in HORIZONS:
        for sn in ("selection", "confirmation", "post2008"):
            cell = r["cells"][f"M|{h}y"][sn]
            out += [f"## {h}년 구간 — {sn}{' (보고만)' if sn == 'post2008' else ''}", "",
                    f"시장 세후 IRR 중앙값 {_p(cell['_base']['median_irr'], nd=2)}, 계좌 최대낙폭 중앙값 {_p(cell['_base']['median_mdd'])}", "",
                    "| 넣을 곳 | 구간 | 이긴 비율 | IRR 차이 중앙값 / 10분위 | 남은 돈 비율 | 최대낙폭 (시장) | 가장 큰 종목 비중 | 시장에 간 돈 | ①②③④ |",
                    "|---|---|---|---|---|---|---|---|---|"]
            for arm in ARMS:
                s = cell[arm]
                if not s.get("n_windows"):
                    continue
                ch = r["checks"][arm].get(f"{sn}|{h}y")
                chs = "".join(_yn(x)[0] for x in ch.values()) if ch else "—"
                out.append(f"| {LABELS[arm]} | {s['n_windows']} | {_p(s['share_win'], nd=0)} | {_p(s['median_diff_irr'], True, 2)}p / "
                           f"{_p(s['p10_diff_irr'], True, 2)}p | {s['median_terminal_ratio']:.3f} | {_p(s.get('median_strategy_mdd'))} "
                           f"({_p(s.get('median_base_mdd'))}) | {_p(s.get('median_top_share'), nd=0)} | {_p(s.get('median_mkt_share'), nd=0)} | {chs} |")
            out.append("")
    out += ["## 보고 — 이미 1,000만 원을 시장에 보유 + 월 10만 원 고르기(시나리오 H)", "",
            "| 넣을 곳 | 길이 | 반쪽 | 이긴 비율 | IRR 차이 중앙값 |", "|---|---|---|---|---|"]
    for h in HORIZONS:
        for sn in JUDGED_SETS:
            for arm in ARMS:
                s = r["cells"][f"H|{h}y"][sn][arm]
                if s.get("n_windows"):
                    out.append(f"| {LABELS[arm]} | {h}년 | {sn} | {_p(s['share_win'], nd=0)} | {_p(s['median_diff_irr'], True, 2)}p |")
    out += ["", f"## 지금 넣는다면 ({r['last_day']}, 자료 마지막 날)", ""]
    out += [f"- {LABELS[a]} → " + ", ".join(f"{n} {w:.0%}" for n, w in r["allocation_now"][a]) for a in ARMS]
    out += ["", "## 주의", "",
            "- 구간이 크게 겹친다. 두 반쪽에서 독립적인 20년은 반쪽마다 2개 남짓이다. 시도 8개라 우연히 하나쯤 통과할 수 있다.",
            "- Ken French 학술 포트폴리오(산업·규모×BM)는 실제 ETF 와 비용·구성이 다르다. 49 산업은 늦게 생긴 산업이 있어 자료가 있는 것만 후보다.",
            "- 소형·가치 효과는 1990 년대 이후, 특히 2007 년 이후 약해졌다고 알려져 있다 — 2008+ 보고 칸을 함께 볼 것.",
            "- 배당 원천징수는 넣지 않았다. 세금은 근사이며 신고용이 아니다. 투자 조언이 아니다."]
    if r["smoke"]:
        out += ["", "스모크 실행: 가짜 데이터·짧은 구간이라 숫자에 의미가 없다."]
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
