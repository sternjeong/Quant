"""leader-follower-robust-v1 (2026-10-11 사전 등록) — sat-leader-v1 의 사후 발견 S3p(모든 섹터 대장주+추종주, 현 규칙)가
우연인지 견고한지 재검정. 판정·고정 규칙은 이 폴더의 SPEC.md. sat-selection-lab/lab.py 의 엔진(Env·체크포인트·시뮬레이션)을
그대로 재사용하고, lab.py 에 덧붙인 lf_* 전략(STRATEGIES 의 candidate: False 항목)만 쓴다. 기존 세 연구(sat-pool/leader/follower)의
STRATEGIES·CANDIDATES·N_TRIALS_TOTAL·decide()/analyze() 는 건드리지 않는다. core/*.py 는 고치지 않는다. 주문 경로와 연결되어 있지 않다.

ETF 시대만(2010-01~, yahoo_pit). CRSP 백엔드는 쓰지 않는다 — 사용자 지시가 "ETF era only; no CRSP" 라고 명시했다.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
import zlib
from datetime import datetime, timezone
from pathlib import Path
from statistics import pvariance
from typing import Any, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_LAB = Path(__file__).resolve().parents[1] / "sat-selection-lab" / "lab.py"
_spec = importlib.util.spec_from_file_location("sat_selection_lab", _LAB)
lab = sys.modules.setdefault("sat_selection_lab", importlib.util.module_from_spec(_spec))
if not hasattr(lab, "run_job"):
    _spec.loader.exec_module(lab)

from core import hypothesis_engine as he  # noqa: E402
from core import hypothesis_judge as hj  # noqa: E402
from core import research_power as rp  # noqa: E402

JOB_ID = "leader-follower-robust-v1"
TITLE = "새틀라이트 선정 견고성 — 섹터 대장주+추종주(사후 발견 S3p) 재검정, ETF 시대"
JUDGE_NAME = "leader-follower-robust-judge/v1"
RULES_VERSION = "leader-follower-robust-judge/v1 (2026-10-11)"

F_SIDS = [lab.lf_sid(r, L, "F") for r in lab.LF_RHOS for L in lab.LF_LS]   # 12 전략 × 4 보유 = 48 셀
CTRL_SIDS = [lab.lf_sid(lab.LF_CTRL_RHO, lab.LF_CTRL_L, v) for v in ("C1", "C2", "C4")]
REP_SID = lab.lf_sid(lab.LF_CTRL_RHO, lab.LF_CTRL_L, "F")                 # ρ=0.6, L=1 — gate (c) 비교 대상
N_TRIALS = len(F_SIDS) * len(lab.HOLDS)                                   # 48 (이 연구만의 시도 수 — 다른 연구와 합산하지 않는다)
MEDIAN_HOLD = sorted(lab.HOLDS)[2]                                        # 모호성 결정 ②: {1,3,6,12} 오름차순 인덱스 2 = 6개월
GATE_B_PCTL_MIN = 90.0
GATE_A_SHARE_MIN = 0.70
N_SUBPERIODS = 3


def third_bounds() -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    start, end = pd.Timestamp(lab.START), pd.Timestamp(lab.JUDGED_END)
    from datetime import timedelta

    total = int((end - start).days)
    b1 = start + timedelta(days=total // 3)
    b2 = start + timedelta(days=2 * total // 3)
    return [(start, b1), (b1, b2), (b2, end)]


def segment_third(r: pd.Series, a: pd.Timestamp, b: pd.Timestamp, last: bool) -> pd.Series:
    return r[(r.index >= a) & (r.index <= b if last else r.index < b)]


def active_ir_thirds(active: pd.Series) -> list[Optional[float]]:
    bounds = third_bounds()
    out = []
    for i, (a, b) in enumerate(bounds):
        seg = segment_third(active, a, b, last=(i == len(bounds) - 1))
        out.append(lab.info_ratio(seg) if len(seg) else None)
    return out


def c3_schedule_for_draw(env: "lab.Env", rng: np.random.Generator) -> dict[str, list[str]]:
    """한 번의 draw 전체 기간 계획: 대장주(L=1) 그대로 + 섹터별 F(ρ=0.6,L=1)가 뽑았을 추종주 수만큼 무작위 종목.
    상관·시총 계산은 env 캐시를 타므로 500회 반복해도 비싼 부분은 한 번만 계산된다."""
    sectors = list(env.all_sectors)
    out: dict[str, list[str]] = {}
    for d in env.monthly:
        if env.prev[d] is None:
            continue
        leaders_all, _followers_all, counts = lab.lf_pool_members(env, d, sectors, lab.LF_CTRL_RHO, lab.LF_CTRL_L)
        pool = set(leaders_all)
        for s in sectors:
            k = counts.get(s, 0)
            if not k:
                continue
            ls = env.leaders_n(d, s, lab.LF_CTRL_L)
            cand = sorted(t for t in env.sector_members(d, s) if t not in ls)
            if cand:
                take = min(k, len(cand))
                chosen = rng.choice(cand, size=take, replace=False)
                pool.update(str(x) for x in chosen)
        pool_list = sorted(pool)
        out[d.date().isoformat()] = env.inc_pick(d, pool_list) if pool_list else []
    return out


def c3_draw_active_ir(env: "lab.Env", schedule_picks: dict[str, list[str]], base_r: pd.Series) -> dict[int, Optional[float]]:
    out: dict[int, Optional[float]] = {}
    for h in lab.HOLDS:
        sched = [(d, list(schedule_picks.get(d.date().isoformat(), []))) for d in lab.hold_dates(env.monthly, h)]
        r = lab.simulate_cell(env, sched)["returns"]
        act = lab.active_returns(r, base_r)
        out[h] = lab.info_ratio(lab.segment(act, "conf"))
    return out


def decide_overall(cells48: list[dict], c3_dist: dict[int, list[float]], baseline_ok: bool,
                    rep_noop: Optional[str], power_conf: dict, power_full: dict) -> tuple[str, dict]:
    """사전 고정 판정. cells48: 48개 {rho,L,hold,sel_active_ir,conf_active_ir,conf_pctl,thirds(list3)}."""
    gates: dict[str, Any] = {}
    if rep_noop:
        return lab.NOT_EVALUABLE, {"reason": rep_noop}
    if not baseline_ok:
        return lab.NOT_EVALUABLE, {"reason": "기준선 재현 실패(등록부 IS 샤프와 ±0.05 초과 차이) — 같은 엔진이 아님"}

    both_pos = [c for c in cells48 if lab.finite(c["sel_active_ir"]) and lab.finite(c["conf_active_ir"])
                and c["sel_active_ir"] > 0 and c["conf_active_ir"] > 0]
    share_a = len(both_pos) / len(cells48) if cells48 else 0.0
    gates["a_share_both_halves_positive"] = {"share": round(share_a, 3), "n": len(both_pos), "of": len(cells48),
                                             "pass": bool(share_a >= GATE_A_SHARE_MIN)}

    pctls = [c["conf_pctl"] for c in cells48 if lab.finite(c.get("conf_pctl"))]
    median_pctl = float(np.median(pctls)) if pctls else None
    gates["b_median_random_percentile"] = {"median": median_pctl, "n": len(pctls),
                                           "pass": bool(median_pctl is not None and median_pctl >= GATE_B_PCTL_MIN)}

    rep_cell = next((c for c in cells48 if c["rho"] == lab.LF_CTRL_RHO and c["L"] == lab.LF_CTRL_L and c["hold"] == MEDIAN_HOLD), None)
    dist = sorted(x for x in c3_dist.get(MEDIAN_HOLD, []) if lab.finite(x))
    thr = float(np.percentile(dist, 95)) if dist else None
    rep_val = rep_cell["conf_active_ir"] if rep_cell else None
    gates["c_beats_c3_placebo"] = {"median_hold": MEDIAN_HOLD, "rep_conf_active_ir": rep_val, "c3_p95": thr,
                                   "n_c3": len(dist), "pass": bool(lab.finite(rep_val) and thr is not None and rep_val > thr)}

    ordered = sorted(cells48, key=lambda c: (c["conf_active_ir"] if lab.finite(c["conf_active_ir"]) else -1e18))
    median_cell = ordered[(len(ordered) - 1) // 2] if ordered else None  # 모호성 결정 ②: 아래쪽 중앙(짝수 48개)
    thirds = median_cell["thirds_active_ir"] if median_cell else []
    n_pos_thirds = sum(1 for x in thirds if lab.finite(x) and x > 0)
    gates["d_median_cell_subperiods"] = {"median_cell": {"rho": median_cell["rho"], "L": median_cell["L"], "hold": median_cell["hold"]}
                                         if median_cell else None, "thirds_active_ir": thirds, "n_positive": n_pos_thirds,
                                         "pass": bool(n_pos_thirds >= 2)}

    a_ok, b_ok, c_ok, d_ok = (gates["a_share_both_halves_positive"]["pass"], gates["b_median_random_percentile"]["pass"],
                              gates["c_beats_c3_placebo"]["pass"], gates["d_median_cell_subperiods"]["pass"])
    if a_ok and b_ok and c_ok and d_ok:
        verdict = lab.PASS
    elif a_ok and b_ok and not c_ok:
        verdict = "PARTIAL"
    else:
        verdict = "NOT_ROBUST"
    return verdict, gates


def run_job(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--max-units-per-run", type=int, default=0)
    a = p.parse_args(argv)
    out, ck = Path(a.out), Path(a.checkpoint)
    out.mkdir(parents=True, exist_ok=True)
    ck.mkdir(parents=True, exist_ok=True)
    smoke = bool(a.smoke)
    lab.set_profile(lab.ETF_PROFILE)
    n_random, chunk = (20, 10) if smoke else (lab.N_RANDOM, 50)
    n_c3, c3_chunk = (15, 5) if smoke else (500, 25)
    fp = {"rules": RULES_VERSION, "backend": "yahoo_pit", "smoke": smoke,
          "data_end": lab.DATA_END if not smoke else "synthetic", "n_random": n_random, "n_c3": n_c3}
    budget = lab.Budget(a.max_units_per_run)

    def on_term(signum, frame):  # noqa: ARG001
        budget.flag = True

    import signal as _signal
    old = _signal.signal(_signal.SIGTERM, on_term) if hasattr(_signal, "SIGTERM") else None
    need = ["B0"] + F_SIDS + CTRL_SIDS
    try:
        lab.log(f"{JOB_ID}: 데이터 준비")
        data, static = (lab.smoke_static_and_data(lab.log) if smoke else lab.real_static_and_data(lab.log, ck, fp))
        env = lab.make_env(data, static, smoke)
        env.static_meta = static.get("meta", {})

        plans: dict[str, dict] = {}
        for sid in need:
            path = ck / f"plan_{sid}.pkl"
            got = lab.load_ckpt(path, fp)
            if got is None:
                budget.check()
                lab.log(f"선정 계획 {sid}")
                got = lab.build_plan(env, sid)
                lab.atomic_pickle(path, {"fingerprint": fp, "payload": got})
                budget.done()
            plans[sid] = got

        cells: dict = {}
        holds_for = {"B0": [lab.BASELINE_HOLD]}
        for sid in F_SIDS + CTRL_SIDS:
            holds_for[sid] = list(lab.HOLDS)
        for sid, holds in holds_for.items():
            for h in holds:
                path = ck / f"cell_{sid}_{h}.pkl"
                got = lab.load_ckpt(path, fp)
                if got is None:
                    budget.check()
                    lab.log(f"시뮬레이션 {sid} {h}개월")
                    got = lab.simulate_cell(env, lab.schedule_for(plans[sid], env.monthly, h))
                    lab.atomic_pickle(path, {"fingerprint": fp, "payload": got})
                    budget.done()
                cells[(sid, h)] = got
        base_r = cells[("B0", lab.BASELINE_HOLD)]["returns"]

        randoms: dict = {}
        for sid in F_SIDS:
            for h in lab.HOLDS:
                path = ck / f"rand_{sid}_{h}.pkl"
                got = lab.load_ckpt(path, fp) or {"sel": [], "conf": []}
                while len(got["conf"]) < n_random:
                    budget.check()
                    i0 = len(got["conf"])
                    for i in range(i0, min(n_random, i0 + chunk)):
                        s_, c_ = lab.random_sim_stats(env, plans[sid], h, sid, i)
                        got["sel"].append(s_)
                        got["conf"].append(c_)
                    lab.atomic_pickle(path, {"fingerprint": fp, "payload": got})
                    budget.done()
                    lab.log(f"무작위 {sid} {h}개월 {len(got['conf'])}/{n_random}")
                randoms[(sid, h)] = got

        c3_path = ck / "c3_draws.pkl"
        c3 = lab.load_ckpt(c3_path, fp) or []
        while len(c3) < n_c3:
            budget.check()
            i0 = len(c3)
            for i in range(i0, min(n_c3, i0 + c3_chunk)):
                rng = np.random.default_rng([lab.RANDOM_SEED, zlib.crc32(b"C3") % 1_000_003, i])
                sched = c3_schedule_for_draw(env, rng)
                c3.append(c3_draw_active_ir(env, sched, base_r))
            lab.atomic_pickle(c3_path, {"fingerprint": fp, "payload": c3})
            budget.done()
            lab.log(f"C3 상관-위약 {len(c3)}/{n_c3}")
        c3_dist: dict[int, list[float]] = {h: [draw.get(h) for draw in c3 if lab.finite(draw.get(h))] for h in lab.HOLDS}

        ref, split = (None, None) if smoke else lab.read_registry_reference()
        repro = lab.check_baseline_reproduction(base_r, ref, split)
        if smoke:
            repro["note"] = "스모크(합성 데이터)라 등록부와 비교하지 않는다."
        baseline_ok = repro["status"] != "MISMATCH"

        bounds_years_conf = (pd.Timestamp(lab.JUDGED_END) - pd.Timestamp(lab.CONFIRM_START)).days / 365.25
        bounds_years_full = (pd.Timestamp(lab.JUDGED_END) - base_r.index[0]).days / 365.25
        power_conf = rp.power_report(bounds_years_conf, N_TRIALS)
        power_full = rp.power_report(bounds_years_full, N_TRIALS)

        cells48: list[dict] = []
        cell_table: dict[str, dict] = {}
        full_srs = []
        for sid in F_SIDS:
            spec = lab.STRATEGIES[sid]
            cell_table[sid] = {}
            for h in lab.HOLDS:
                r = cells[(sid, h)]["returns"]
                act = lab.active_returns(r, base_r)
                sel_ir = lab.info_ratio(lab.segment(act, "sel"))
                conf_ir = lab.info_ratio(lab.segment(act, "conf"))
                conf_stat = he.stats(lab.segment(r, "conf"))
                dist = [x for x in randoms.get((sid, h), {}).get("conf", []) if lab.finite(x)]
                pctl = lab.sl.percentile_of(conf_stat.get("sharpe_annual"), dist) if dist and lab.finite(conf_stat.get("sharpe_annual")) else None
                pctl_pct = round(pctl * 100, 2) if pctl is not None else None
                thirds = active_ir_thirds(act)
                row = {"rho": spec["rho"], "L": spec["L"], "hold": h, "sel_active_ir": sel_ir, "conf_active_ir": conf_ir,
                       "conf_sharpe": conf_stat.get("sharpe_annual"), "conf_mdd": conf_stat.get("max_drawdown"),
                       "random_conf_median": float(np.median(dist)) if dist else None,
                       "random_conf_p95": float(np.percentile(dist, 95)) if dist else None, "conf_pctl": pctl_pct,
                       "thirds_active_ir": thirds}
                cells48.append(row)
                cell_table[sid][str(h)] = row
                act_judged = lab.segment(act, "judged")
                s = he.stats(act_judged)
                if "sharpe_daily" in s:
                    full_srs.append(s["sharpe_daily"])
        var_pool = pvariance(full_srs) if len(full_srs) >= 2 else (lab.sl.DEFAULT_ACTIVE_SR_ANNUAL_SD / math.sqrt(lab.TRADING_DAYS)) ** 2

        ctrl_table: dict[str, dict] = {}
        for sid in CTRL_SIDS:
            ctrl_table[sid] = {}
            for h in lab.HOLDS:
                r = cells[(sid, h)]["returns"]
                act = lab.active_returns(r, base_r)
                conf_stat = he.stats(lab.segment(r, "conf"))
                ctrl_table[sid][str(h)] = {"sel_active_ir": lab.info_ratio(lab.segment(act, "sel")),
                                           "conf_active_ir": lab.info_ratio(lab.segment(act, "conf")),
                                           "conf_sharpe": conf_stat.get("sharpe_annual"), "conf_mdd": conf_stat.get("max_drawdown")}

        rep_act_j = lab.segment(lab.active_returns(cells[(REP_SID, lab.BASELINE_HOLD)]["returns"], base_r), "judged")
        rep_noop = rp.noop_guard(rep_act_j.to_numpy())
        rep_st = he.stats(rep_act_j)
        dsr = hj.deflated_sharpe(rep_st.get("sharpe_daily", 0.0), rep_st.get("n_days", 0), rep_st.get("skew", 0.0),
                                 rep_st.get("kurtosis", 3.0), N_TRIALS, var_pool)
        dsr = {**dsr, "dsr": round(float(dsr["dsr"]), 4), "n_trials": N_TRIALS, "active_sharpe_annual": rep_st.get("sharpe_annual"),
               "n_days": rep_st.get("n_days")}

        verdict, gates = decide_overall(cells48, c3_dist, baseline_ok, rep_noop, power_conf, power_full)

        per_cell_fail_kind = {}
        for row in cells48:
            key = f"rho{row['rho']}_L{row['L']}_h{row['hold']}"
            per_cell_fail_kind[key] = rp.classify_fail(row["conf_active_ir"], power_conf) if lab.finite(row["conf_active_ir"]) else "NOT_EVALUABLE"

        result = {
            "kind": "pre-registered verdict", "id": JOB_ID, "rules_version": RULES_VERSION, "judge": JUDGE_NAME, "smoke": smoke,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "rules": {"holds": list(lab.HOLDS), "rhos": list(lab.LF_RHOS), "leaders_per_sector": list(lab.LF_LS),
                      "median_hold_for_gate_c": MEDIAN_HOLD, "baseline_hold": lab.BASELINE_HOLD, "top_k": lab.TOP_K,
                      "selection_end": lab.SELECTION_END, "confirmation_start": lab.CONFIRM_START, "judged_end": lab.JUDGED_END,
                      "holdout_start": lab.HOLDOUT_START, "data_end": lab.DATA_END, "n_random": n_random, "n_c3_draws": n_c3,
                      "n_trials_total": N_TRIALS, "bps_one_way": 8.0, "gate_a_share_min": GATE_A_SHARE_MIN,
                      "gate_b_pctl_min": GATE_B_PCTL_MIN, "n_subperiods": N_SUBPERIODS},
            "strategies": {sid: lab.STRATEGIES[sid]["title"] for sid in F_SIDS + CTRL_SIDS},
            "baseline_reproduction": repro, "power": {"confirmation": power_conf, "full": power_full},
            "dsr_variance_daily": var_pool, "representative_cell": {"sid": REP_SID, "hold": lab.BASELINE_HOLD, "dsr_full_window": dsr,
                                                                     "noop_guard": rep_noop},
            "grid_48_cells": cells48, "grid_table": cell_table, "control_table": ctrl_table,
            "c3_placebo_distribution": {str(h): {"n": len(v), "median": float(np.median(v)) if v else None,
                                                 "p95": float(np.percentile(v, 95)) if v else None} for h, v in c3_dist.items()},
            "per_cell_fail_kind": per_cell_fail_kind,
            "gates": gates, "verdicts": {"study": f"SMOKE_ONLY({verdict})" if smoke else verdict},
            "verdicts_raw": {"study": verdict},
            "baseline": {"confirmation": {"sharpe": he.stats(
                lab.segment(base_r, "conf")).get("sharpe_annual")}},
            "meta": {**lab.static_meta(env), **getattr(env, "static_meta", {})},
        }
        report = build_report(result)
    except lab.Stop:
        lab.log("시간 예산 끝(또는 단위 상한) — 체크포인트 저장됨, 다음 회차에 이어서")
        return 3
    finally:
        if old is not None:
            _signal.signal(_signal.SIGTERM, old)
    lab.atomic_write(out / "results.json", json.dumps(result, ensure_ascii=False, indent=1, default=str))
    lab.atomic_write(out / "REPORT.md", report)
    lab.log(json.dumps(result["verdicts"], ensure_ascii=False))
    return 0


def _n(x, nd=2) -> str:
    return "—" if not lab.finite(x) else f"{x:.{nd}f}"


def _pc(x) -> str:
    return "—" if not lab.finite(x) else f"{x:.1%}"


def build_report(r: dict) -> str:
    smoke = r["smoke"]
    g = r["gates"]
    rep = r["baseline_reproduction"]
    L = [f"# {TITLE}{' (스모크 — 합성 데이터)' if smoke else ''}", "",
         f"사전 고정 판정 {JUDGE_NAME}. sat-leader-v1 의 사후 발견 S3p(모든 섹터 대장주+추종주)가 우연인지 견고한지 재검정한다 — "
         "같은 2010~2024 자료라 독립 시험이 아니다. 판정 구간 2010-01~2024-10-08(선정 ~2017-05-31 / 확인 2017-06-01~). "
         "2024-10-09 이후는 보고만(소진된 구간).", "",
         f"## 판정: **{r['verdicts']['study']}**", ""]
    if "reason" in g:
        L.append(f"- {g['reason']}")
    else:
        a, b, c, d = g["a_share_both_halves_positive"], g["b_median_random_percentile"], g["c_beats_c3_placebo"], g["d_median_cell_subperiods"]
        L += [f"- (a) 48 셀 중 선정·확인 둘 다 활성 샤프>0: {a['n']}/{a['of']} = {a['share']:.0%} ≥ {GATE_A_SHARE_MIN:.0%}: **{a['pass']}**",
              f"- (b) 확인 구간 무작위 백분위의 중앙값 {_n(b['median'], 1)} ≥ {GATE_B_PCTL_MIN:.0f}: **{b['pass']}**",
              f"- (c) ρ=0.6·L=1·{c['median_hold']}개월 확인 활성 IR {_n(c['rep_conf_active_ir'], 3)} > C3 상관-위약 95백분위 {_n(c['c3_p95'], 3)}"
              f"(n={c['n_c3']}): **{c['pass']}**",
              f"- (d) 중앙 셀(ρ={d['median_cell']['rho'] if d['median_cell'] else '—'}, L={d['median_cell']['L'] if d['median_cell'] else '—'}, "
              f"{d['median_cell']['hold'] if d['median_cell'] else '—'}개월)의 3등분 구간 중 활성 샤프>0: {d['n_positive']}/3 ≥ 2: **{d['pass']}**"]
    rc = r.get("representative_cell", {})
    dsr = rc.get("dsr_full_window") or {}
    L += ["", f"ROBUST_FORWARD_CANDIDATE·PARTIAL 모두 '전진 원장에 올릴 후보'일 뿐이다(core/forward_tournament_v2.py 후보는 동결 — "
          "이 연구가 바꾸지 않는다). 엔진 반영은 사용자 확인 뒤 별도 작업.", "",
          f"대표 셀(ρ=0.6·L=1·{lab.BASELINE_HOLD}개월) DSR(전체 판정 창 {r['power']['full']['years']}년, 시도 {N_TRIALS}개): {_n(dsr.get('dsr'), 3)} "
          f"(통과 조건 아님, 참고) · noop_guard: {rc.get('noop_guard') or '통과(활성 수익 있음)'}", "",
          rp.power_line(r["power"]["confirmation"]).replace("검정력(사전 계산)", "확인 구간 검정력(사전 계산)"),
          rp.power_line(r["power"]["full"]).replace("검정력(사전 계산)", "전체 판정 창 검정력(사전 계산)"), "",
          f"시도 수 = ρ 4개 × L 3개 × 보유기간 4개 = **{N_TRIALS}**(이 연구 전용 — 다른 연구의 시도 수와 합산하지 않는다). 통제(C1·C2·C4)와 "
          "C3 상관-위약 분포는 시도로 세지 않는다.", "",
          "## 기준선 재현", "",
          f"- 랩 기준선 {lab.ETF_PROFILE.comparison_baseline} 의 IS 연샤프 {_n(rep.get('ours'), 3)} vs 등록부 {_n(rep.get('registry'), 3)} "
          f"→ 차이 {_n(rep.get('diff'), 3)} (허용 ±{rep['tolerance']}) = **{rep['status']}**. {rep.get('note', '')}", "",
          "## ρ×L 격자 (48 셀, 보유기간별)", "",
          "| ρ | L | 보유 | 선정 활성IR | 확인 활성IR | 확인 샤프 | 확인 MDD | 무작위 중앙/p95 | 백분위 | fail_kind |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for row in sorted(r["grid_48_cells"], key=lambda x: (x["rho"], x["L"], x["hold"])):
        key = f"rho{row['rho']}_L{row['L']}_h{row['hold']}"
        L.append(f"| {row['rho']} | {row['L']} | {row['hold']}개월 | {_n(row['sel_active_ir'])} | {_n(row['conf_active_ir'])} | "
                 f"{_n(row['conf_sharpe'])} | {_pc(row['conf_mdd'])} | {_n(row['random_conf_median'])} / {_n(row['random_conf_p95'])} | "
                 f"{_n(row['conf_pctl'], 1)}% | {r['per_cell_fail_kind'].get(key, '—')} |")
    L += ["", "## 분해 통제 (ρ=0.6, L=1, 판정하지 않음)", "",
          "| 통제 | 보유 | 선정 활성IR | 확인 활성IR | 확인 샤프 | 확인 MDD |", "|---|---|---|---|---|---|"]
    for sid in CTRL_SIDS:
        for h in lab.HOLDS:
            x = r["control_table"][sid][str(h)]
            L.append(f"| {sid} | {h}개월 | {_n(x['sel_active_ir'])} | {_n(x['conf_active_ir'])} | {_n(x['conf_sharpe'])} | {_pc(x['conf_mdd'])} |")
    L += ["", "## C3 상관-위약 분포 (500회 시드 고정, 확인 구간 활성 IR)", "", "| 보유 | n | 중앙값 | p95 |", "|---|---|---|---|"]
    for h in lab.HOLDS:
        c3 = r["c3_placebo_distribution"].get(str(h), {})
        L.append(f"| {h}개월 | {c3.get('n', 0)} | {_n(c3.get('median'))} | {_n(c3.get('p95'))} |")
    L += ["", "## 이 연구가 증명하는 것과 증명하지 못하는 것", "",
          "- 증명하는 것: sat-leader-v1 에서 사후 발견한 '모든 섹터 대장주+추종주' 모양이 ρ·L·보유기간을 바꿔도, 그리고 상관 대신 무작위/크기순위로 "
          "추종주를 뽑아도 견고한지에 대한 과거 자료상의 증거.",
          f"- 증명하지 못하는 것: 이 연구는 S3p 를 발견한 바로 그 2010~2024 자료를 다시 보는 것이라 **독립 시험이 아니다**. ROBUST_FORWARD_CANDIDATE·"
          "PARTIAL 은 '전진 원장에 올릴 후보'일 뿐 수익 개선의 증거가 아니다. 진짜 확인은 앞으로 쌓이는 전진 원장으로만 온다. 확인 구간 약 "
          f"{r['power']['confirmation']['years']}년·시도 {N_TRIALS}개에서는 연 IR 이 {r['power']['confirmation']['mde_ir']:.2f} 보다 작은 효과를 "
          "가려낼 수 없다(FAIL_UNDERPOWERED 는 '효과 없음'이 아니라 '판별 불가'에 가깝다).", "",
          "## 모호성 결정 (자세한 근거는 SPEC.md)", "",
          "1. 추종주는 섹터당 시총 1위(L1)와의 상관만 본다(L>1 이어도 L2·L3 와는 상관을 보지 않는다).",
          f"2. gate (c) 의 '중간 보유기간' = {MEDIAN_HOLD}개월(격자 {list(lab.HOLDS)} 오름차순 인덱스 2).",
          "3. gate (d) 의 '중앙 셀' = 48 셀을 확인 활성 IR 오름차순 정렬한 아래쪽 중앙(24번째).",
          "4. C3 의 '활성 샤프'는 이 연구 전체와 같은 정의(후보−기준선 B0 6개월 일별 활성수익의 연 정보비율)로 계산했다.",
          "5. C1·C2·C4 는 F 와 같이 항상 전체 섹터(코어 보유 섹터로 좁히지 않음).", "",
          "## 한계", "",
          "- 생존편향(Yahoo 에 없는 상장폐지 종목 제외), 섹터 분류는 현재 S&P500 표(시점 기준 아님), 시가총액은 발행주식수 이력×종가 근사.",
          "- 같은 2010~2024 자료를 이미 여러 연구(sat-pool/leader/follower 등)가 본 데서 오는 과적합 — 이 연구 자체가 그 중 하나다.",
          "- 비용은 편도 8bp 단순 모델, 배당 포함 조정 가격 수익, 세금·슬리피지 없음."]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(run_job())
