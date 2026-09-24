"""챔피언 코어 슬리브 변형 shadow book (관측 전용, 일봉 전용).

목적: 원전략(챔피언 코어 top4)을 절대 바꾸지 않고, 그 변형들이 매일 어떤 목표 집합을 냈을지를 병행 기록해
"hold-band 가 회전율·비용을 실제로 줄였는가"를 나중에 같은 규칙(core.candidate_ledger)으로 검증할 수 있게 한다.
docs/ENGINE_UPGRADE_ROADMAP.md 의 "top 4 매수·6위 유지 hold-band 를 독립 실험" 항목의 관측 인프라다.

## 변형
- baseline_v1  : 현재 챔피언 코어 그대로(절대모멘텀 통과 종목 중 모멘텀 상위 4).
- hold_band_v1 : 슬롯 4개. 직전 보유 종목은 절대모멘텀을 통과하는 종목 순위(모멘텀 내림차순, 통과 종목만 세는 순위)가
  HOLD_BAND_RANK(6) 이내면 유지한다. 신규 진입은 상위 4위(top4) 안에서만, 비어 있는 슬롯 수만큼 순위 순으로 채운다.
  유지 종목을 순위 때문에 강제로 밀어내지 않으므로 보유는 항상 4개 이하다. 절대모멘텀 탈락이나 데이터 결측은 순위 밖(청산)이다.
  (요구사항의 "6위 밖으로 밀릴 때만 청산"을 슬롯 4 제약과 절대모멘텀 통과 조건 아래에서 구체화한 정책이다.)

## 지켜야 할 경계
- 원전략 결정은 읽기만 한다(core.champion_strategy.compute_core_recommendation 결과를 수정하지 않는다). 주문 경로
  (core.paper_execution, scripts/champion_paper_trade.py)는 import 하지 않는다.
- 상태(직전 보유)는 data/cache/strategy_variants_state.json 에 원자적으로 저장해 재시작 후에도 이어진다. 같은 결정일을
  다시 실행해도 상태가 두 번 전진하지 않는다(그 날의 직전 보유를 따로 저장해 재계산). 상태 파일이 손상되면 조용히
  초기화하지 않고 옆에 .corrupt-* 로 보존한 뒤 결과에 state_reset 을 남긴다.
- 진입·청산·비용·horizon·판정은 core.candidate_ledger 의 기존 규칙을 그대로 쓴다. 이 모듈은 새 통계 규칙을 만들지 않는다.
  표본 미달·PIT 미인증이면 원장 규칙에 따라 항상 '미입증'이다. 성과 개선을 주장하지 않는다.
- 시장필터가 unknown(new_orders_allowed=False)인 날은 두 변형 모두 상태·기록을 갱신하지 않는다(ENG-03 과 같은 보수적 처리).
"""

from __future__ import annotations

import json
import os
import copy
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from core import candidate_ledger as cl
from core.trade_ledger import COST_SCENARIOS_BPS

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_CACHE_PATH = PROJECT_ROOT / "data" / "cache" / "strategy_variants_state.json"
REPORT_DIR = PROJECT_ROOT / "data" / "reports"

SOURCE = "champion_core_variants"
CORE_SLOTS = 4  # core.champion_strategy.CORE_TOP_N 과 같은 값(원전략 슬롯 수)
HOLD_BAND_RANK = 6
HISTORY_MAX_DAYS = 800

VARIANTS: dict[str, dict] = {
    "baseline_v1": {"strategy_version": "champion_core/baseline_v1", "hold_rank": None,
                    "description": "현재 챔피언 코어 top4 그대로"},
    "hold_band_v1": {"strategy_version": "champion_core/hold_band_v1", "hold_rank": HOLD_BAND_RANK,
                     "description": "top4 신규 진입, 기존 보유는 6위 밖으로 밀릴 때만 청산"},
}

DISCLAIMER = (
    "관측 전용 shadow book 이다. 아래 수치는 성과 개선의 증거가 아니며, 판정은 core.candidate_ledger 의 규칙 "
    "(표본 부족·PIT 미인증이면 항상 '미입증')을 그대로 따른다. 원전략(챔피언)의 실제 결정은 바뀌지 않는다."
)


# ---------------------------------------------------------------------------
# 순수 함수: 목표 집합
# ---------------------------------------------------------------------------
def select_targets(
    eligible_ranked: list[str], prev_holdings: list[str], *, slots: int = CORE_SLOTS, hold_rank: Optional[int] = None,
) -> dict:
    """변형의 목표 집합을 정한다. eligible_ranked 는 절대모멘텀 통과 종목을 모멘텀 내림차순으로 나열한 목록.

    hold_rank=None 이면 baseline(상위 slots). 아니면 hold-band: 직전 보유 중 순위<=hold_rank 유지, 빈 슬롯을 top-slots
    신규 종목으로 순위 순 충원. Returns {"targets", "retained", "entered", "exited"} (targets 는 순위 순).
    """
    rank = {t: i + 1 for i, t in enumerate(eligible_ranked)}
    top = eligible_ranked[:slots]
    if hold_rank is None:
        targets = list(top)
        retained = [t for t in prev_holdings if t in targets]
    else:
        retained = [t for t in prev_holdings if t in rank and rank[t] <= hold_rank]
        vacant = max(0, slots - len(retained))
        entrants = [t for t in top if t not in retained][:vacant]
        targets = sorted(retained + entrants, key=lambda t: rank[t])
    prev = set(prev_holdings)
    return {
        "targets": targets,
        "retained": [t for t in targets if t in prev],
        "entered": [t for t in targets if t not in prev],
        "exited": [t for t in prev_holdings if t not in targets],
    }


# ---------------------------------------------------------------------------
# 상태 영속 (JSON, 원자적 저장)
# ---------------------------------------------------------------------------
def _empty_state() -> dict:
    return {"version": 1, "variants": {}, "history": {}}


def load_state(path: Optional[Path] = None) -> tuple[dict, Optional[str]]:
    """(상태, state_reset 사유). 손상 파일은 보존하고 사유를 반환한다(조용한 초기화 금지)."""
    p = Path(path or STATE_CACHE_PATH)
    if not p.exists():
        return _empty_state(), None
    try:
        with open(p, encoding="utf-8") as f:
            state = json.load(f)
        if not isinstance(state, dict) or "variants" not in state:
            raise ValueError("unexpected structure")
        state.setdefault("history", {})
        return state, None
    except Exception as exc:  # noqa: BLE001
        backup = p.with_name(p.name + f".corrupt-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}")
        try:
            os.replace(p, backup)
        except OSError:
            pass
        return _empty_state(), f"state file unreadable ({type(exc).__name__}); preserved as {backup.name}"


def save_state(state: dict, path: Optional[Path] = None) -> None:
    p = Path(path or STATE_CACHE_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, p)


# ---------------------------------------------------------------------------
# 기록
# ---------------------------------------------------------------------------
def _get_core_recommendation() -> dict:
    from core import champion_strategy

    return champion_strategy.compute_core_recommendation()


def _cutoff_date(rec: dict, as_of: date) -> date:
    """정보가 닿는 마지막 거래일(가능하면 last_trading_date) — 날짜만 주면 그 날 장 마감 후로 해석된다."""
    lt = rec.get("last_trading_date")
    return pd.Timestamp(lt).date() if lt else as_of


def _build_candidate_set(
    name: str, ranked: pd.DataFrame, plan: dict, weights: dict, prev_holdings: list[str], cutoff: date, rank_of: dict,
) -> cl.FrozenCandidateSet:
    cfg = VARIANTS[name]
    targets = set(plan["targets"])
    records = []
    for _, row in ranked.iterrows():
        t = str(row["ticker"])
        mom = row.get("momentum_pct")
        scores = {"momentum_pct": None if pd.isna(mom) else float(mom), "eligible_rank": rank_of.get(t),
                  "passes_absolute_momentum": bool(row.get("passes_absolute_momentum")),
                  "previously_held": t in prev_holdings}
        if t in targets:
            reason = ("new_entry_top4" if t in plan["entered"] else f"retained(rank={rank_of.get(t)})")
            records.append(cl.CandidateRecord(t, "selected", reason, scores=scores, rank=rank_of.get(t),
                                              order_proposal={"target_weight": weights.get(t), "sleeve": "core",
                                                              "variant": name}))
        elif pd.isna(mom):
            records.append(cl.CandidateRecord(t, "missing_data", "core_history_unavailable", scores=scores))
        elif not scores["passes_absolute_momentum"]:
            records.append(cl.CandidateRecord(t, "rejected", "fails_absolute_momentum", scores=scores))
        else:
            records.append(cl.CandidateRecord(t, "held", f"not_in_target(rank={rank_of.get(t)})", scores=scores,
                                              rank=rank_of.get(t)))
    return cl.FrozenCandidateSet(SOURCE, cfg["strategy_version"], cutoff, records,
                                 {"variant": name, "description": cfg["description"], "hold_rank": cfg["hold_rank"],
                                  "slots": CORE_SLOTS})


def record_variant_shadow(as_of: Any = None, session=None) -> dict:
    """오늘의 챔피언 코어 추천에서 각 변형의 목표 집합을 계산해 상태에 반영하고 후보 원장에 별도 strategy_version 으로 기록한다.

    관측 전용: 원전략 추천(dict)은 읽기만 하며 수정하지 않는다. 멱등: 같은 결정일 재실행은 상태를 다시 전진시키지 않고
    원장에도 중복 행을 만들지 않는다. Returns {"as_of","cutoff_date","status","variants":{...},"state_reset"}.
    """
    from core.champion_strategy import CORE_WEIGHT

    as_of_date = cl._as_date(as_of)
    rec = _get_core_recommendation()
    rec_before = copy.deepcopy({k: v for k, v in rec.items() if k != "ranked"})
    out: dict[str, Any] = {"as_of": as_of_date.isoformat(), "status": "recorded", "variants": {},
                           "champion_top4": list(rec.get("top4") or []), "state_reset": None}
    if rec.get("new_orders_allowed") is not True:
        out["status"] = "skipped_new_orders_blocked"
        out["reason"] = str(rec.get("allocation_reason", ""))
        return out

    cutoff = _cutoff_date(rec, as_of_date)
    out["cutoff_date"] = cutoff.isoformat()
    ranked: pd.DataFrame = rec["ranked"]
    eligible = [str(t) for t, ok in zip(ranked["ticker"], ranked["passes_absolute_momentum"]) if ok]
    rank_of = {t: i + 1 for i, t in enumerate(eligible)}
    invested = CORE_WEIGHT - float(rec.get("cash_weight_from_filter", 0.0))

    state, reset = load_state()
    out["state_reset"] = reset
    for name, cfg in VARIANTS.items():
        vs = state["variants"].get(name, {})
        if vs.get("as_of") == cutoff.isoformat():
            prev = list(vs.get("prior_holdings", []))  # 같은 결정일 재실행: 그 날의 직전 보유로 재계산
        elif vs.get("as_of") and vs["as_of"] > cutoff.isoformat():
            out["variants"][name] = {"status": "stale_as_of", "state_as_of": vs["as_of"]}
            continue
        else:
            prev = list(vs.get("holdings", []))
        plan = select_targets(eligible, prev, hold_rank=cfg["hold_rank"])
        n = len(plan["targets"])
        weights = {t: (invested / n if n else 0.0) for t in plan["targets"]}
        state["variants"][name] = {"as_of": cutoff.isoformat(), "holdings": plan["targets"], "prior_holdings": prev}
        hist = state["history"].setdefault(name, {})
        hist[cutoff.isoformat()] = {"holdings": plan["targets"], "weights": weights}
        for old in sorted(hist)[:-HISTORY_MAX_DAYS]:
            hist.pop(old)
        cset = _build_candidate_set(name, ranked, plan, weights, prev, cutoff, rank_of)
        ledger_res = cl.record_candidate_set(cset, session=session)
        out["variants"][name] = {"strategy_version": cfg["strategy_version"], **plan, "weights": weights,
                                 "ledger": ledger_res}
    save_state(state)

    after = {k: v for k, v in rec.items() if k != "ranked"}
    out["champion_decision_unchanged"] = bool(rec_before == after)
    return out


# ---------------------------------------------------------------------------
# 회전율 · 거래 횟수 · 비용 영향
# ---------------------------------------------------------------------------
def _cost_assumptions() -> dict:
    """편도 비용(bp) 시나리오. core.cost_calibration 이 실측을 제공하면 함께 쓰고, 없으면 가정 5/10/25bp 만 쓴다.

    cost_calibration 은 다른 작업에서 만들어지는 중이라 API 를 확정하지 못했다: 알려진 후보 함수명만 방어적으로 시도하고
    실패하면 가정값으로 돌아간다(출처를 결과에 표시).
    """
    scenarios = {n: sc["fee_bps"] + sc["slippage_bps"] for n, sc in COST_SCENARIOS_BPS.items()}
    source = "assumed(core.trade_ledger.COST_SCENARIOS_BPS)"
    try:
        from core import cost_calibration as cc  # type: ignore

        for fn_name in ("calibrated_one_way_bps", "get_calibrated_one_way_bps"):
            fn = getattr(cc, fn_name, None)
            if callable(fn):
                v = fn()
                if isinstance(v, (int, float)) and v == v and v > 0:
                    scenarios["calibrated"] = float(v)
                    source = f"assumed + measured(core.cost_calibration.{fn_name})"
                    break
    except Exception:  # noqa: BLE001 - 선택적 의존성: 없거나 API 가 다르면 가정값만
        pass
    return {"scenarios_one_way_bps": scenarios, "source": source}


def compare_turnover(state: Optional[dict] = None) -> dict:
    """변형별 회전율·거래 횟수·비용 영향 표.

    연속 기록일 사이의 전환만 센다(첫 기록일의 초기 진입은 제외). traded = Σ|Δ비중|(매수+매도, NAV 비중),
    편도 회전율 = traded/2, 거래 횟수 = 비중이 바뀐 종목 수, 비용 영향(NAV bp) = traded × 편도 bp. 관측된 전환 수가
    적으면 그 사실(n_transitions)을 그대로 보여 주며 연율화하지 않는다.
    """
    if state is None:
        state, _ = load_state()
    assumptions = _cost_assumptions()
    variants: dict[str, dict] = {}
    for name in VARIANTS:
        hist = state.get("history", {}).get(name, {})
        days = sorted(hist)
        n_tr, traded_sum, trades, entries, exits = 0, 0.0, 0, 0, 0
        for d0, d1 in zip(days, days[1:]):
            w0, w1 = hist[d0]["weights"], hist[d1]["weights"]
            names = set(w0) | set(w1)
            traded_sum += sum(abs(w1.get(t, 0.0) - w0.get(t, 0.0)) for t in names)
            trades += sum(1 for t in names if abs(w1.get(t, 0.0) - w0.get(t, 0.0)) > 1e-9)
            entries += sum(1 for t in w1 if t not in w0)
            exits += sum(1 for t in w0 if t not in w1)
            n_tr += 1
        variants[name] = {
            "days_recorded": len(days), "n_transitions": n_tr, "trades": trades, "entries": entries, "exits": exits,
            "traded_notional_sum": traded_sum,
            "avg_one_way_turnover_per_transition": (traded_sum / 2 / n_tr) if n_tr else None,
            "cost_drag_bp_of_nav": {s: traded_sum * bp for s, bp in assumptions["scenarios_one_way_bps"].items()},
        }
    base, hb = variants.get("baseline_v1"), variants.get("hold_band_v1")
    diff = None
    if base and hb and base["n_transitions"] == hb["n_transitions"] and base["n_transitions"] > 0:
        diff = {
            "trades": hb["trades"] - base["trades"],
            "traded_notional_sum": hb["traded_notional_sum"] - base["traded_notional_sum"],
            "cost_drag_bp_of_nav": {s: hb["cost_drag_bp_of_nav"][s] - base["cost_drag_bp_of_nav"][s]
                                    for s in base["cost_drag_bp_of_nav"]},
            "note": "hold_band_v1 - baseline_v1. 음수면 hold-band 의 회전·비용이 더 적었다는 뜻(수익 비교 아님).",
        }
    return {"variants": variants, "difference": diff, "cost_source": assumptions["source"],
            "scenarios_one_way_bps": assumptions["scenarios_one_way_bps"],
            "note": "회전율·비용만의 비교다. 수익·초과수익 개선은 판정하지 않으며 원장 규칙의 verdict 만 따른다."}


# ---------------------------------------------------------------------------
# 리포트
# ---------------------------------------------------------------------------
def _variant_ledger_summary(name: str, session) -> dict:
    from core.models import CandidateBatch, CandidateDecision

    sv = VARIANTS[name]["strategy_version"]
    with cl._session_scope(session) as s:
        n_batches = s.query(CandidateBatch).filter_by(strategy_version=sv).count()
        n_decisions = s.query(CandidateDecision).filter_by(strategy_version=sv).count()
        rep = cl.build_ledger_report(session=s, strategy_version=sv, n_boot=500, n_random_draws=200)
    p = rep["primary"]
    return {
        "strategy_version": sv, "batches_recorded": n_batches, "decisions_recorded": n_decisions,
        "primary_horizon_days": p["horizon_days"],
        "final_samples_primary": {"selected": p["groups"]["selected"]["n"], "rest": p["groups"]["rest"]["n"]},
        "n_missing_outcome": p["n_missing_outcome"], "verdict": p["verdict"], "verdict_reasons": p["verdict_reasons"],
        "warnings": p["warnings"], "pit_certified_fraction": p["pit_certified_fraction"],
    }


def _render_md(report: dict) -> str:
    L = [f"# 전략 연구 shadow book 리포트 ({report['as_of']})", "", report["disclaimer"], "",
         "## 변형별 기록·표본·판정", "",
         "| 변형 | strategy_version | 배치 | 판단 기록 | 확정 표본(채택/비교군, 20거래일) | verdict | 사유 |",
         "|---|---|---|---|---|---|---|"]
    for name, v in report["variants"].items():
        fs = v["final_samples_primary"]
        L.append(f"| {name} | {v['strategy_version']} | {v['batches_recorded']} | {v['decisions_recorded']} | "
                 f"{fs['selected']}/{fs['rest']} | {v['verdict']} | {', '.join(v['verdict_reasons']) or '-'} |")
    t = report["turnover"]
    L += ["", "## 회전율·거래 횟수 (연속 기록일 전환 기준)", "",
          "| 변형 | 기록일 | 전환 수 | 거래 횟수 | 진입 | 청산 | 평균 편도 회전율/전환 |", "|---|---|---|---|---|---|---|"]
    for name, v in t["variants"].items():
        avg = v["avg_one_way_turnover_per_transition"]
        L.append(f"| {name} | {v['days_recorded']} | {v['n_transitions']} | {v['trades']} | {v['entries']} | "
                 f"{v['exits']} | {'n/a' if avg is None else f'{avg:.3f}'} |")
    L += ["", f"## 비용 영향 (NAV bp 누적, 비용 출처: {t['cost_source']})", ""]
    scen = list(t["scenarios_one_way_bps"])
    L += ["| 변형 | " + " | ".join(f"{s}({t['scenarios_one_way_bps'][s]:g}bp/편도)" for s in scen) + " |",
          "|---|" + "---|" * len(scen)]
    for name, v in t["variants"].items():
        L.append(f"| {name} | " + " | ".join(f"{v['cost_drag_bp_of_nav'][s]:.1f}" for s in scen) + " |")
    if t["difference"]:
        d = t["difference"]
        L.append("| hold_band − baseline | " + " | ".join(f"{d['cost_drag_bp_of_nav'][s]:.1f}" for s in scen) + " |")
    else:
        L += ["", "전환 수가 없거나 두 변형의 기록일이 달라 차이를 계산하지 않았다."]
    L += ["", t["note"], "", "## 한계", "",
          "- 표본이 쌓이기 전에는 회전율 차이도 우연일 수 있다(전환 수를 함께 볼 것).",
          "- 후보가 17자산 코어 유니버스뿐이라 원장 표본이 느리게 쌓인다.",
          "- 비용은 가정값(또는 실측 모듈이 있을 때 그 값)이며 수익 영향은 다루지 않는다."]
    return "\n".join(L) + "\n"


def write_research_report(out_dir: Any = None, session=None, as_of: Any = None) -> dict:
    """data/reports/strategy_research_YYYY-MM-DD.md + .json 을 만든다. 성과 개선을 주장하지 않는다.

    Returns {"as_of","md_path","json_path","variants":{...},"turnover":{...}}.
    """
    as_of_date = cl._as_date(as_of)
    out = Path(out_dir) if out_dir else REPORT_DIR
    out.mkdir(parents=True, exist_ok=True)
    variants = {name: _variant_ledger_summary(name, session) for name in VARIANTS}
    report = {
        "as_of": as_of_date.isoformat(), "disclaimer": DISCLAIMER, "variants": variants,
        "turnover": compare_turnover(), "ledger_version": cl.LEDGER_VERSION,
        "rules": {"primary_horizon_days": cl.PRIMARY_HORIZON_DAYS, "primary_cost_scenario": cl.PRIMARY_COST_SCENARIO,
                  "primary_target": cl.PRIMARY_TARGET, "hold_band_rank": HOLD_BAND_RANK, "slots": CORE_SLOTS},
    }
    stem = f"strategy_research_{as_of_date.isoformat()}"
    md_path, json_path = out / f"{stem}.md", out / f"{stem}.json"
    md_path.write_text(_render_md(report), encoding="utf-8")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return {**report, "md_path": str(md_path), "json_path": str(json_path)}
