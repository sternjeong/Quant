"""frontier-lev-rebal-v1 — 끝없는 적립에서 2배 다리 되돌림 정책 (사전 등록 2026-11-12).

질문: '시장 80% + 2배 다리 20%' 는 지금까지 모든 관문을 통과한 유일한 후보지만, 모든 근거가
'10·20년 뒤 전부 판다'는 가정에서 나왔다. 사용자는 끝없이 굴리고 팔지 않는다. 그러면
  (ㄱ) 2배 다리가 저절로 커져 계좌 레버리지가 올라간다(동의하지 않은 위험),
  (ㄴ) 해마다 양도세 공제 250만 원을 100% 버린다.
되돌림 정책 6개를 30년(끝없음 대리) 가상 역사에서 세후 IRR·계좌 낙폭·말기 다리 비중으로 잰다.

판정 문턱·비교 대상·구간은 아래 상수와 SPEC.md 에 결과를 보기 전에 고정했다. 가격 격자(기간·손절률·이동평균
길이)를 키우는 연구가 아니다 — 다리 자체는 필터 없는 고정 2배이고, 바뀌는 것은 '언제 얼마를 팔아 세금을 내는가'다.
"""

from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def _find_root(start: Path) -> Path:
    for p in [start, *start.parents]:
        if (p / "core" / "tax_fx.py").exists() and (p / "research" / "jobs").is_dir():
            return p
    raise RuntimeError("저장소 루트를 찾지 못했다")


PROJECT_ROOT = _find_root(Path(__file__).resolve())
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _load(name: str, rel: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


L = _load("dca_lab", "research/jobs/dca-dip-deploy-v1/lab.py")  # 공용 실험실(Runner·부트스트랩·세금 상수)
from core import research_power as rp  # noqa: E402

# =================================================================================================
# 사전 등록 상수 (결과를 보기 전에 고정 — 이후 바꾸지 않는다)
# =================================================================================================
RULES_VERSION = "frontier-lev-rebal-v1/2026-11-12"

# 계좌·돈
LUMP_KRW, MONTHLY_KRW = 10_000_000.0, 150_000.0   # 시나리오 B (목표 문서 기준)
BUY_COST = L.FEE + L.FX_SPREAD                    # 0.1% 수수료 + 0.05% 환전
SELL_COST = L.FEE + L.FX_SPREAD
CGT, ALLOWANCE = L.CGT, L.ALLOWANCE               # 22%, 연 250만 원

# 다리 (필터 없음 — 가격 타이밍을 쓰지 않는다. l15f-robust-v1 에서 w20|none 이 ROBUST)
TARGET_W = 0.20
MULT, FIN_SPREAD, LEG_FEE = 2.0, 0.010, 0.009
BAND_PP = 0.10                                    # 띠: 다리 비중 ≥ 30% 면 깎는다

# 구간·가상 역사
HORIZON_MONTHS = 360                              # 30년 = '끝없음' 대리
REPORT_MONTHS = 180                               # 15년 (보고만)
DAYS_PER_MONTH, BLOCK_DAYS = 21, 63
N_PATHS, SEED = 2000, 20261112
ERAS = {"selection": ("1927-07-01", "1966-12-31"), "confirmation": ("1967-01-01", "2007-12-31")}
REPORT_ERAS = {"post2008": ("2008-01-01", "2100-01-01")}   # 이미 여러 연구가 본 구간 — 보고만

# 판정 문턱
WIN_MIN, MED_MIN, P10_MIN, MDD_GAP_MAX = 0.60, 0.003, -0.015, 0.10
A0_MED_MIN, A0_MDD_GAP_MAX = 0.002, 0.01

ARMS = ["A0_NONE", "A1_CONTRIB", "A2_ANNUAL", "A3_BAND10", "A4_ALLOW", "A5_BAND_ALLOW"]
ARM_NOTE = {
    "A0_NONE": "적립금을 늘 80/20 으로 넣고 절대 팔지 않는다(다리가 흐르게 둔다)",
    "A1_CONTRIB": "적립금을 모자란 쪽부터 넣어 비중을 되돌린다(팔지 않음 → 세금 0)",
    "A2_ANNUAL": "A1 + 매년 1월 전체를 80/20 으로 되돌린다(팔 때 세금)",
    "A3_BAND10": "A1 + 다리 비중이 30% 를 넘은 달에만 20% 로 깎는다",
    "A4_ALLOW": "A1 + 매년 12월, 그해 공제 한도(250만 원)만큼만 다리를 팔아 시장을 산다(세금 0)",
    "A5_BAND_ALLOW": "A1 + 다리 비중 30% 초과 시 깎되, 그해 공제 한도 안에서만(세금 0)",
}


# =================================================================================================
# 가상 역사 / 실제 역사 월 수익
# =================================================================================================

def leg_daily(mkt: np.ndarray, rf: np.ndarray) -> np.ndarray:
    """일일 리셋 2배 상품의 일 수익(필터 없음) — lev-base-v1·l15f-robust-v1 과 같은 식."""
    return MULT * mkt - (MULT - 1.0) * (rf + FIN_SPREAD / 252) - LEG_FEE / 252


def era_arrays(data: dict, lo: str, hi: str) -> tuple[np.ndarray, np.ndarray]:
    mkt, rf = data["mkt"], data["rf"].reindex(data["mkt"].index).fillna(0.0)
    m = (mkt.index >= pd.Timestamp(lo)) & (mkt.index <= pd.Timestamp(hi)) & mkt.notna().to_numpy()
    return mkt[m].to_numpy(dtype=float), rf[m].to_numpy(dtype=float)


def bootstrap_monthly(mkt: np.ndarray, rf: np.ndarray, months: int, n_paths: int, seed: int,
                      block: int, chunk: int = 250) -> tuple[np.ndarray, np.ndarray]:
    """원형 블록 부트스트랩 가상 역사 → 월 성장배수 (경로, 달). 하루 단위로 2배 상품을 굴린 뒤 21일씩 곱한다."""
    d_need = months * DAYS_PER_MONTH
    rows = L.block_paths(len(mkt), d_need, block, n_paths, seed).astype(np.int32)
    fm = np.empty((n_paths, months)); fl = np.empty((n_paths, months))
    for i in range(0, n_paths, chunk):
        r = rows[i:i + chunk]
        rm, rrf = mkt[r], rf[r]
        rl = leg_daily(rm, rrf)
        fm[i:i + chunk] = (1.0 + rm).reshape(-1, months, DAYS_PER_MONTH).prod(axis=2)
        fl[i:i + chunk] = (1.0 + rl).reshape(-1, months, DAYS_PER_MONTH).prod(axis=2)
    return fm, fl


def real_monthly(data: dict) -> tuple[np.ndarray, np.ndarray, pd.PeriodIndex]:
    """실제 역사(달력 월) 성장배수 — 보고용 비교."""
    mkt = data["mkt"].dropna()
    rf = data["rf"].reindex(mkt.index).fillna(0.0)
    legs = pd.Series(leg_daily(mkt.to_numpy(dtype=float), rf.to_numpy(dtype=float)), index=mkt.index)
    per = mkt.index.to_period("M")
    fm = (1.0 + mkt).groupby(per).prod()
    fl = (1.0 + legs).groupby(per).prod()
    return fm.to_numpy(dtype=float), fl.to_numpy(dtype=float), fm.index


# =================================================================================================
# 계좌 (이동평균 취득원가·연 공제·판 날 즉시 세금 차감)
# =================================================================================================

def _sell(V, B, gross, year_gain):
    """자산에서 평가액 gross 만큼 판다 → (V, B, 현금, 실현이익, 낸 세금). 취득원가는 이동평균."""
    gross = np.clip(gross, 0.0, V)
    frac = np.where(V > 0, gross / np.where(V > 0, V, 1.0), 0.0)
    basis_out = frac * B
    gain = gross - basis_out
    before = CGT * np.maximum(0.0, year_gain - ALLOWANCE)
    after = CGT * np.maximum(0.0, year_gain + gain - ALLOWANCE)
    tax = after - before
    return V - gross, B - basis_out, gross * (1.0 - SELL_COST) - tax, gain, tax


def _buy(V, B, cash):
    return V + cash * (1.0 - BUY_COST), B + cash


def simulate(fm: np.ndarray, fl: np.ndarray, arm: str, cal_month: np.ndarray,
             want_twr: bool = False) -> dict[str, Any]:
    """팔지 않는(또는 정책대로 파는) 적립 계좌. fm/fl: (경로, 달) 성장배수. arm='MKT' 는 시장 그냥 보유."""
    P, M = fm.shape
    Vm = np.zeros(P); Bm = np.zeros(P); Vl = np.zeros(P); Bl = np.zeros(P)
    year_gain = np.zeros(P); tax_paid = np.zeros(P); n_sell = np.zeros(P)
    vals = np.zeros((P, M + 1)); expo = np.zeros((P, M))
    twr = np.zeros((P, M)) if want_twr else None

    for t in range(M):
        if cal_month[t] == 0:
            year_gain = np.zeros(P)
        cash = np.full(P, MONTHLY_KRW + (LUMP_KRW if t == 0 else 0.0))
        tot = Vm + Vl
        if arm == "MKT":
            alloc_l = np.zeros(P)
        elif t == 0 or arm == "A0_NONE":
            alloc_l = TARGET_W * cash                      # 첫날 목돈은 목표 비중, A0 는 늘 고정 비율
        else:
            alloc_l = np.clip(TARGET_W * (tot + cash) - Vl, 0.0, cash)   # 모자란 쪽부터
        Vl, Bl = _buy(Vl, Bl, alloc_l)
        Vm, Bm = _buy(Vm, Bm, cash - alloc_l)

        if arm not in ("MKT", "A0_NONE", "A1_CONTRIB") and t > 0:
            tot = Vm + Vl
            tgt = TARGET_W * tot
            over = Vl - tgt
            if arm == "A2_ANNUAL" and cal_month[t] == 0:
                g = np.maximum(over, 0.0)
                Vl, Bl, cashp, gain, tax = _sell(Vl, Bl, g, year_gain)
                year_gain = year_gain + gain; tax_paid = tax_paid + tax; n_sell += (g > 0)
                Vm, Bm = _buy(Vm, Bm, cashp)
                g2 = np.maximum(-over, 0.0)
                Vm, Bm, cashp, gain, tax = _sell(Vm, Bm, g2, year_gain)
                year_gain = year_gain + gain; tax_paid = tax_paid + tax; n_sell += (g2 > 0)
                Vl, Bl = _buy(Vl, Bl, cashp)
            elif arm in ("A3_BAND10", "A5_BAND_ALLOW"):
                hit = (Vl > 0) & (Vl >= (TARGET_W + BAND_PP) * np.maximum(tot, 1e-9))
                g = np.where(hit, np.maximum(over, 0.0), 0.0)
                if arm == "A5_BAND_ALLOW":
                    g = np.minimum(g, _allowance_gross(Vl, Bl, year_gain))
                Vl, Bl, cashp, gain, tax = _sell(Vl, Bl, g, year_gain)
                year_gain = year_gain + gain; tax_paid = tax_paid + tax; n_sell += (g > 0)
                Vm, Bm = _buy(Vm, Bm, cashp)
            elif arm == "A4_ALLOW" and cal_month[t] == 11:
                g = np.minimum(np.maximum(over, 0.0), _allowance_gross(Vl, Bl, year_gain))
                Vl, Bl, cashp, gain, tax = _sell(Vl, Bl, g, year_gain)
                year_gain = year_gain + gain; tax_paid = tax_paid + tax; n_sell += (g > 0)
                Vm, Bm = _buy(Vm, Bm, cashp)

        tot = Vm + Vl
        expo[:, t] = np.where(tot > 0, (Vm + MULT * Vl) / np.where(tot > 0, tot, 1.0), 1.0)
        Vm = Vm * fm[:, t]; Vl = Vl * fl[:, t]
        vals[:, t + 1] = Vm + Vl
        if want_twr:
            twr[:, t] = np.where(tot > 0, vals[:, t + 1] / np.where(tot > 0, tot, 1.0) - 1.0, 0.0)

    gross = Vm + Vl
    w_end = np.where(gross > 0, Vl / np.where(gross > 0, gross, 1.0), 0.0)
    unreal = (Vm - Bm) + (Vl - Bl)
    tax_fin = CGT * np.maximum(0.0, year_gain + unreal - ALLOWANCE) - CGT * np.maximum(0.0, year_gain - ALLOWANCE)
    terminal = gross * (1.0 - SELL_COST) - tax_fin
    vals[:, 0] = LUMP_KRW + MONTHLY_KRW
    peak = np.maximum.accumulate(vals, axis=1)
    mdd = np.min(vals / np.where(peak > 0, peak, 1.0) - 1.0, axis=1)
    out = {"terminal": terminal, "irr": irr_vec(terminal, M), "mdd": mdd, "w_end": w_end,
           "tax": tax_paid + tax_fin, "n_sell": n_sell, "exposure": expo.mean(axis=1)}
    if want_twr:
        out["twr"] = twr
    return out


def _allowance_gross(V, B, year_gain):
    """그해 남은 공제(250만 원) 안에서 실현이익이 딱 차도록 팔 수 있는 평가액. 이익이 없으면 0(손실 확정은 하지 않는다)."""
    rate = np.where(V > 0, 1.0 - B / np.where(V > 0, V, 1.0), 0.0)
    room = np.maximum(0.0, ALLOWANCE - year_gain)
    return np.where(rate > 1e-9, room / np.where(rate > 1e-9, rate, 1.0), 0.0)


def irr_vec(terminal: np.ndarray, months: int) -> np.ndarray:
    """월 적립 흐름의 연 IRR(이분법, 경로별). 흐름: 0달 목돈+적립, 1~M-1달 적립, M달 청산액."""
    n = months - 1
    lo = np.full(terminal.shape, -0.9); hi = np.full(terminal.shape, 1.0)

    def npv(i):
        i = np.where(np.abs(i) < 1e-12, 1e-12, i)
        ann = (1.0 - (1.0 + i) ** (-n)) / i
        return -(LUMP_KRW + MONTHLY_KRW) - MONTHLY_KRW * ann + terminal * (1.0 + i) ** (-months)

    for _ in range(90):
        mid = 0.5 * (lo + hi)
        pos = npv(mid) > 0          # npv 는 i 에 대해 감소 → 양수면 참 IRR 이 더 높다
        lo = np.where(pos, mid, lo); hi = np.where(pos, hi, mid)
    r = 0.5 * (lo + hi)
    out = (1.0 + r) ** 12 - 1.0
    return np.where(np.isfinite(out) & (terminal > 0), out, np.nan)


# =================================================================================================
# 판정
# =================================================================================================

def compare(arm: dict, base: dict) -> list[dict]:
    return [{"diff_irr": float(a - b), "win": bool(x > y)}
            for a, b, x, y in zip(arm["irr"], base["irr"], arm["terminal"], base["terminal"])]


def era_block(res: dict[str, dict]) -> dict[str, Any]:
    mkt, a0 = res["MKT"], res["A0_NONE"]
    out = {}
    for arm in ARMS:
        r = res[arm]
        k_mkt = L.kpi_pairs_verdict(compare(r, mkt), WIN_MIN, MED_MIN, P10_MIN)
        mdd_ok = float(np.median(r["mdd"])) >= float(np.median(mkt["mdd"])) - MDD_GAP_MAX
        k_mkt["checks"]["mdd_within"] = bool(mdd_ok)
        k_mkt["pass"] = bool(all(k_mkt["checks"].values()))
        k_a0 = L.kpi_pairs_verdict(compare(r, a0), 0.0, A0_MED_MIN, -1e9)
        a0_mdd_ok = float(np.median(r["mdd"])) >= float(np.median(a0["mdd"])) - A0_MDD_GAP_MAX
        k_a0["checks"] = {"median_irr": k_a0["median_diff_irr"] >= A0_MED_MIN, "mdd_within": bool(a0_mdd_ok)}
        k_a0["pass"] = bool(all(k_a0["checks"].values()))
        out[arm] = {"vs_market": k_mkt, "vs_A0": k_a0,
                    "median_irr": float(np.nanmedian(r["irr"])), "median_mdd": float(np.median(r["mdd"])),
                    "median_w_end": float(np.median(r["w_end"])), "median_exposure": float(np.median(r["exposure"])),
                    "median_tax_krw": float(np.median(r["tax"])), "median_n_sell": float(np.median(r["n_sell"])),
                    "median_terminal_krw": float(np.median(r["terminal"]))}
    out["MKT"] = {"median_irr": float(np.nanmedian(mkt["irr"])), "median_mdd": float(np.median(mkt["mdd"])),
                  "median_terminal_krw": float(np.median(mkt["terminal"])), "median_tax_krw": float(np.median(mkt["tax"]))}
    return out


# =================================================================================================
# 본문
# =================================================================================================

def body(run):
    smoke = run.smoke
    months = 60 if smoke else HORIZON_MONTHS
    rep_months = 36 if smoke else REPORT_MONTHS
    n_paths = 60 if smoke else N_PATHS
    block = 21 if smoke else BLOCK_DAYS

    data = run.stage("data", lambda: (L.load_long_synthetic() if smoke else L.load_long_real()))
    source = data["source"]
    cal = np.arange(months) % 12          # 가상 역사: 첫 달을 1월로 본다

    def do_era(name: str, lo: str, hi: str, seed_add: int):
        mkt, rf = era_arrays(data, lo, hi)
        if len(mkt) < block * 4:
            return {"n_days": int(len(mkt)), "skipped": True}
        fm, fl = bootstrap_monthly(mkt, rf, months, n_paths, SEED + seed_add, block)
        res = {}
        for arm in ["MKT", *ARMS]:
            run.check_time()
            res[arm] = simulate(fm, fl, arm, cal)
        blk = era_block(res)
        blk["short"] = era_block({a: simulate(fm[:, :rep_months], fl[:, :rep_months], a, cal[:rep_months])
                                  for a in ["MKT", *ARMS]})
        blk["n_days"] = int(len(mkt)); blk["n_paths"] = int(n_paths); blk["months"] = int(months)
        return blk

    eras: dict[str, Any] = {}
    for i, (name, (lo, hi)) in enumerate([*ERAS.items(), *REPORT_ERAS.items()]):
        eras[name] = run.stage(f"era_{name}", lambda name=name, lo=lo, hi=hi, i=i: do_era(name, lo, hi, 101 * (i + 1)))

    # 실제 역사(겹치지 않는 구간 + 전체 한 경로) — 보고만
    def do_real():
        fm, fl, per = real_monthly(data)
        cm = np.array([p.month - 1 for p in per])
        rows, full = [], None
        for s in range(0, len(fm) - months + 1, months):
            sl = slice(s, s + months)
            r = {a: simulate(fm[None, sl], fl[None, sl], a, cm[sl]) for a in ["MKT", *ARMS]}
            rows.append({"start": str(per[s]), "end": str(per[s + months - 1]),
                         **{a: {"irr": float(r[a]["irr"][0]), "mdd": float(r[a]["mdd"][0]),
                                "w_end": float(r[a]["w_end"][0]), "tax": float(r[a]["tax"][0])} for a in ["MKT", *ARMS]}})
            if len(rows) >= (2 if smoke else 99):
                break
        n = len(fm)
        fr = {a: simulate(fm[None, :n], fl[None, :n], a, cm[:n], want_twr=True) for a in ["MKT", *ARMS]}
        full = {"start": str(per[0]), "end": str(per[-1]), "months": int(n),
                **{a: {"irr": float(fr[a]["irr"][0]), "mdd": float(fr[a]["mdd"][0]), "w_end": float(fr[a]["w_end"][0]),
                       "exposure": float(fr[a]["exposure"][0]), "tax": float(fr[a]["tax"][0]),
                       "n_sell": float(fr[a]["n_sell"][0])} for a in ["MKT", *ARMS]}}
        act = {a: (fr[a]["twr"][0] - fr["MKT"]["twr"][0]).tolist() for a in ARMS}
        return {"windows": rows, "full": full, "active": act}

    real = run.stage("real", do_real)

    # 판정 — 두 era(selection·confirmation) 모두 통과해야 한다
    power = rp.power_report(months / 12.0, len(ARMS))
    verdicts: dict[str, str] = {}
    for arm in ARMS:
        act = np.array(real["active"].get(arm, []), dtype=float)
        noop = rp.noop_guard(act.tolist())
        if noop is not None:
            verdicts[arm] = "NOT_EVALUABLE"
            continue
        ok = [eras[e].get(arm, {}).get("vs_market", {}).get("pass") for e in ERAS]
        if all(bool(x) for x in ok):
            v = "BEATS_MARKET"
        else:
            ir = float(np.nanmean(act) / np.nanstd(act) * math.sqrt(12)) if len(act) > 2 and np.nanstd(act) > 0 else None
            v = rp.classify_fail(ir, power)
        if all(bool(eras[e].get(arm, {}).get("vs_A0", {}).get("pass")) for e in ERAS):
            v += "+POLICY_BEATS_A0"
        verdicts[arm] = v
    best = max(ARMS, key=lambda a: min(eras[e].get(a, {}).get("median_irr", -9) for e in ERAS))
    verdicts["frontier_pick"] = best
    w_end = [eras[e].get("A0_NONE", {}).get("median_w_end") for e in ERAS]
    w_end = [x for x in w_end if x is not None]
    verdicts["drift"] = (f"A0_NONE 말기 다리 비중 중앙 {np.median(w_end) * 100:.1f}% (목표 {TARGET_W:.0%})"
                         if w_end else "측정 불가")

    result = {"id": "frontier-lev-rebal-v1", "rules_version": RULES_VERSION, "smoke": smoke, "source": source,
              "scenario": {"lump_krw": LUMP_KRW, "monthly_krw": MONTHLY_KRW, "months": months,
                           "target_leg_weight": TARGET_W, "band_pp": BAND_PP, "n_paths": n_paths, "block_days": block},
              "thresholds": {"win_min": WIN_MIN, "median_irr_min": MED_MIN, "p10_irr_min": P10_MIN,
                             "mdd_gap_max": MDD_GAP_MAX, "a0_median_irr_min": A0_MED_MIN, "a0_mdd_gap_max": A0_MDD_GAP_MAX},
              "power": power, "eras": L.rnd(eras), "real_history": L.rnd(real["windows"]),
              "real_full": L.rnd(real["full"]), "verdicts": verdicts}
    return result, report(result)


def report(r: dict) -> str:
    e = r["eras"]
    sc = r["scenario"]
    lines = [f"# 끝없는 적립에서 2배 다리 되돌림 정책 v1 (frontier-lev-rebal-v1/{RULES_VERSION.split('/')[-1]})", "",
             "'시장 80% + 2배 다리 20%' 는 지금까지 모든 관문을 통과한 유일한 후보지만, 근거는 모두 '10·20년 뒤 전부 판다'는 가정에서 나왔다.",
             "팔지 않고 끝없이 굴리면 다리가 저절로 커져 계좌 레버리지가 올라가고, 해마다 양도세 공제 250만 원을 버린다.",
             f"여기서는 되돌림 정책 6개를 {sc['months'] // 12}년 가상 역사({sc['n_paths']}개 × 두 시대)에서 세후로 잰다.", "",
             f"**판정:** " + " · ".join(f"{k} **{v}**" for k, v in r["verdicts"].items() if k in ARMS), "",
             "통과는 '전진 원장 후보'일 뿐 엔진 채택이 아니다. 엔진은 바뀌지 않았다.", "",
             "## 규칙 (결과를 보기 전에 고정)", "",
             f"- 계좌: 처음 {sc['lump_krw']:,.0f} 원 + 매달 {sc['monthly_krw']:,.0f} 원. 매수·매도마다 0.15%(수수료 0.1% + 환전 0.05%).",
             "  취득원가는 이동평균, 양도세 22% × max(0, 그해 실현이익 − 250만 원)을 판 즉시 현금에서 뺀다(실제 납부는 다음 해 5월 — 보수적 근사).",
             f"- 다리: 필터 없는 고정 2배(일일 리셋, 차입 가산 연 1% + 보수 연 0.9%). 목표 비중 {TARGET_W:.0%}, 띠 {BAND_PP:.0%}p.",
             "- 팔(6개): " + " · ".join(f"{a}={ARM_NOTE[a]}" for a in ARMS),
             "- 기준: 같은 돈으로 시장 그냥 보유(MKT), 그리고 '정책 없음'(A0_NONE).",
             f"- 가상 역사: 원형 블록 부트스트랩(블록 {sc['block_days']}거래일), 시대마다 경로 {sc['n_paths']}개 — selection(1927~1966 일자) · confirmation(1967~2007 일자). 2008+ 는 보고만.",
             f"- 통과(BEATS_MARKET) ⇔ **두 시대 모두** ① 시장보다 많이 남은 경로 ≥ {WIN_MIN:.0%} ② 세후 IRR 차이 중앙값 ≥ {MED_MIN * 100:+.1f}%p ③ 10분위 ≥ {P10_MIN * 100:+.1f}%p ④ 계좌 낙폭 중앙값이 시장보다 {MDD_GAP_MAX * 100:.0f}%p 넘게 나쁘지 않음.",
             f"- 덧붙임(POLICY_BEATS_A0) ⇔ 두 시대 모두 A0 대비 IRR 차이 중앙값 ≥ {A0_MED_MIN * 100:+.1f}%p 이고 낙폭이 A0 보다 {A0_MDD_GAP_MAX * 100:.0f}%p 넘게 나쁘지 않음.",
             f"- 팔 6개·비교 2개뿐이고 비중·띠·공제는 결과를 보기 전에 고정했다(격자 탐색 아님). 1927~2024 가격은 이미 여러 연구가 본 자료다.", "",
             "- " + rp.power_line(r["power"]), "",
             f"자료: {r['source']}", ""]
    for name in [*ERAS, *REPORT_ERAS]:
        b = e.get(name, {})
        if not b or b.get("skipped"):
            lines += [f"## {name} — 자료 부족으로 건너뜀", ""]
            continue
        tag = " (보고만)" if name in REPORT_ERAS else ""
        lines += [f"## {name}{tag} — 가상 역사 {b.get('n_paths')}개, {b.get('months')}달", "",
                  "| 팔 | 이긴 비율 | IRR 차이 중앙/10분위 (대 시장) | 세후 IRR 중앙 | 계좌 낙폭 중앙 | 말기 다리 비중 | 평균 노출 | 낸 세금 중앙 | 판 횟수 | 관문 |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
        m = b.get("MKT", {})
        lines.append(f"| 시장 그냥 보유 | — | — | {L.pct(m.get('median_irr'))} | {L.pct(m.get('median_mdd'), True)} | — | 1.00 | {m.get('median_tax_krw', 0) / 1e4:,.0f}만 원 | 0 | 기준 |")
        for a in ARMS:
            x = b.get(a, {})
            vm = x.get("vs_market", {})
            ck = ",".join(k for k, v in vm.get("checks", {}).items() if not v) or "모두 충족"
            lines.append(f"| {a} | {L.pct(vm.get('share_win'))} | {L.pct(vm.get('median_diff_irr'), True, 2)} / {L.pct(vm.get('p10_diff_irr'), True, 2)} | "
                         f"{L.pct(x.get('median_irr'))} | {L.pct(x.get('median_mdd'), True)} | {L.pct(x.get('median_w_end'))} | "
                         f"{x.get('median_exposure', float('nan')):.2f} | {x.get('median_tax_krw', 0) / 1e4:,.0f}만 원 | {x.get('median_n_sell', 0):.0f} | {ck} |")
        lines.append("")
    lines += ["## 실제 역사(겹치지 않는 구간 · 보고만)", "",
              "| 구간 | " + " | ".join(ARMS) + " | 시장 |", "|---|" + "---|" * (len(ARMS) + 1)]
    for w in r["real_history"]:
        lines.append(f"| {w['start']}~{w['end']} | " + " | ".join(L.pct(w[a]["irr"]) for a in ARMS) + f" | {L.pct(w['MKT']['irr'])} |")
    f = r["real_full"]
    lines += ["", f"전체 한 경로({f['start']}~{f['end']}, {f['months']}달): " +
              " · ".join(f"{a} IRR {L.pct(f[a]['irr'])}/낙폭 {L.pct(f[a]['mdd'], True)}/말기 다리 {L.pct(f[a]['w_end'])}" for a in ["MKT", *ARMS]), "",
              "## 주의", "",
              "- 계좌 낙폭은 **월말 가치** 기준이라 달 안의 더 깊은 낙폭은 빠진다(모든 팔에 같게 적용).",
              "- 가상 역사는 블록을 섞은 '겹치지 않는' 표본이지만 원재료는 같은 미국 역사다. 완전히 새로운 정보는 아니다.",
              "- 다리는 **합성 2배**다. 실제 상품(SSO)·실제 환율·정밀 세금은 engine-candidate-v1 이 2006~2024 한 역사에서만 확인했다.",
              "- 환율은 1,300원 고정 근사, 배당 원천징수는 넣지 않았다(총수익 지수 그대로).",
              "- 세금은 '판 즉시 차감'이라 실제(다음 해 5월 납부)보다 약간 불리하다. 금융소득·건강보험료는 넣지 않았다.",
              "- 통과해도 **전진 원장에 올릴 후보**일 뿐이고, 레버리지는 폭락 때 계좌 낙폭을 키운다. 투자 조언이 아니다."]
    return "\n".join(lines)


if __name__ == "__main__":
    runner = L.Runner(RULES_VERSION)
    raise SystemExit(runner.run(body))
