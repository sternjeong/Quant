"""검증 연구 leader-catch-v1: 다음 주도 업종·종목을 그 시점의 정보만으로 미리 알아볼 수 있었나. (사전 등록, 2026-10-12)

왜: QQQ 가 2010~2024 에 잘했다는 것은 사후에야 안다. 진짜 질문은 '그 시점에 알 수 있던 정보로 다음 리더를 가려낼 수 있었나'다.
승자를 이름으로 정하지 않고, 리더십이 계속 바뀐 장기 자료(Ken French 일별 12·49 산업, 규모×B/M 25개; 판정 1927-07~2007-12)에서
사전 신호 8종 + 합성 1종의 적중률·순위 IC·알파·안정성을 잰다. 2008~ 와 ETF 메뉴(2010~2024-09)는 보고(ETF 는 '지지' 표시만).

규칙은 SPEC.md·lab.py 에 결과를 보기 전에 고정했다(바꾸려면 새 id). 종료 코드: 0 완료, 3 진행 중(체크포인트 저장), 그 외 실패.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from core import research_power as rp  # noqa: E402

_spec = importlib.util.spec_from_file_location("leader_catch_lab", Path(__file__).resolve().parent / "lab.py")
lab = sys.modules.setdefault("leader_catch_lab", importlib.util.module_from_spec(_spec))
if not hasattr(lab, "Context"):
    _spec.loader.exec_module(lab)

import numpy as np  # noqa: E402

JUDGE_VERSION = "leader-catch-judge/v1"
EXIT_DONE, EXIT_IN_PROGRESS = 0, 3
UNIV_NAMES = {"ind12": "FF 12 산업", "ind49": "FF 49 산업", "ports25": "규모×B/M 25개"}


# ---------------------------------------------------------------- 유틸
def clean(o):
    """JSON 직렬화용: numpy → 기본형, NaN/inf → None."""
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return float(o) if math.isfinite(float(o)) else None
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o


def atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def save_json(path: Path, obj) -> None:
    atomic_write(path, json.dumps(clean(obj), ensure_ascii=False))


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def pct(v, nd=1, sign=False):
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "—"
    return f"{v * 100:+.{nd}f}%" if sign else f"{v * 100:.{nd}f}%"


def num(v, nd=2, sign=False):
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "—"
    return f"{v:+.{nd}f}" if sign else f"{v:.{nd}f}"


def ci_txt(h):
    if not h or h.get("mean") is None:
        return "—"
    lo, hi = h.get("lo"), h.get("hi")
    return f"{h['mean']*100:.1f}% [{pct(lo) if lo is not None else '—'}, {pct(hi) if hi is not None else '—'}]"


# ---------------------------------------------------------------- 작업 목록
def work_items(universes_only=False):
    items = []
    for u in lab.UNIVERSES:
        items += [("cell", u, s) for s in lab.SIGNALS]
        items.append(("conc", u, None))
    if not universes_only:
        items += [("etf", "etf", s) for s in lab.ETF_SIGNALS]
    return items


def item_file(ckpt: Path, kind, u, s) -> Path:
    return ckpt / (f"{kind}_{u}_{s}.json" if s else f"{kind}_{u}.json")


# ---------------------------------------------------------------- 조립
def assemble(ckpt: Path, power: dict, smoke: bool, source: str, etf_meta: dict, data_end: str) -> dict:
    universes, cell_flags = {}, {s: [] for s in lab.SIGNALS}
    confirmed_cells = 0
    for u in lab.UNIVERSES:
        cells = {s: load_json(item_file(ckpt, "cell", u, s)) for s in lab.SIGNALS}
        for s, c in cells.items():
            cell_flags[s].append(c["confirmed"])
            confirmed_cells += 1 if c["confirmed"] else 0
        conc = load_json(item_file(ckpt, "conc", u, None))
        universes[u] = {"name": UNIV_NAMES[u], "k": lab.TOP_K[u], "cells": cells, "concentration": conc}
    sig_verdicts = {s: lab.signal_verdict(cell_flags[s]) for s in lab.SIGNALS}
    overall = lab.overall_verdict(sig_verdicts)
    robust = [s for s in lab.SIGNALS if sig_verdicts[s] == "ROBUST"]
    etf = {}
    for s in lab.ETF_SIGNALS:
        etf[s] = load_json(item_file(ckpt, "etf", "etf", s))
    verdicts = {"overall": overall,
                "controls": "NOT_DISCRIMINATING" if any(sig_verdicts[c] == "ROBUST" for c in lab.CONTROLS) else "DISCRIMINATING",
                "robust_signals": ",".join(robust) if robust else "none",
                "confirmed_cells": f"{confirmed_cells}/{lab.N_TRIALS}"}
    verdicts.update({f"{s}_{'control' if s in lab.CONTROLS else 'signal'}": sig_verdicts[s] for s in lab.SIGNALS})
    noop = [f"{u}/{s}" for u in lab.UNIVERSES for s in lab.SIGNALS if universes[u]["cells"][s].get("noop_guard")]
    return {"judge_version": JUDGE_VERSION, "smoke": smoke, "source": source, "data_end": data_end,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "verdicts": verdicts, "signal_verdicts": sig_verdicts, "power": power, "noop_cells": noop,
            "rule": rule_dict(), "universes": universes, "etf": etf, "etf_meta": etf_meta}


def rule_dict() -> dict:
    return {"windows": {"judged": [lab.MAIN_START, lab.MAIN_END], "selection": [lab.SEL_START, lab.SEL_END],
                        "confirmation": [lab.CONF_START, lab.CONF_END], "report_only": [lab.POST_START, None],
                        "subperiods": lab.SUBPERIODS, "etf": [lab.ETF_START, lab.ETF_END]},
            "top_k": lab.TOP_K, "signals": lab.SIGNAL_NAMES, "momentum_like": lab.MOMENTUM_LIKE, "controls": lab.CONTROLS,
            "cost_bps_one_way": lab.COST_BPS, "hold": "1 month (rebalance first trading day, signal = previous close, executed next day)",
            "pass_rule": {"hit_chance": lab.HIT_CHANCE, "hit_primary": "next 1 month, confirmation half, circular block bootstrap CI lower bound",
                          "alpha": "CAPM alpha vs equal-weighted universe, NW(6) monthly, confirmation half, t >= %.1f and alpha > 0" % lab.T_MIN,
                          "subperiods_positive_min": lab.SUB_MIN_POSITIVE, "robust_min_universes": lab.ROBUST_MIN_UNIVERSES},
            "bootstrap": {"block_months": lab.BOOT_BLOCK, "draws": lab.BOOT_DRAWS, "seed": lab.BOOT_SEED}}


# ---------------------------------------------------------------- 보고서
def paragraph(res: dict) -> list[str]:
    """2008 이후 약함이 '신호가 약해져서'인가 '리더십 집중' 때문인가 — 서술이며 검정이 아니다(규칙은 SPEC.md)."""
    L = []
    ic_pre, ic_post, sh_pre, sh_post = [], [], [], []
    for u in lab.UNIVERSES:
        un = res["universes"][u]
        for s in ("F1", "C"):
            c = un["cells"][s]["windows"]
            if c["full"]["ic"].get("mean") is not None and c["post2008"]["ic"].get("mean") is not None:
                ic_pre.append(c["full"]["ic"]["mean"])
                ic_post.append(c["post2008"]["ic"]["mean"])
        cs = un["concentration"]["summary"]
        if cs["pre2008"].get("top3_share_pos") is not None and cs["post2008"].get("top3_share_pos") is not None:
            sh_pre.append(cs["pre2008"]["top3_share_pos"])
            sh_post.append(cs["post2008"]["top3_share_pos"])
    if not ic_pre or not sh_pre:
        return ["자료가 부족해 서술하지 못했다."]
    a, b = float(np.mean(ic_pre)), float(np.mean(ic_post))
    p, q = float(np.mean(sh_pre)), float(np.mean(sh_post))
    weaker = b <= 0.5 * a
    more = q >= p + 0.03
    L.append(f"F1·C 신호의 평균 순위 IC 는 1927~2007 {num(a, 3)} → 2008 이후 {num(b, 3)}, "
             f"상위 3 구성원이 양의 수익 합계에서 차지한 몫은 {pct(p)} → {pct(q)} (세 유니버스 평균).")
    if weaker and more:
        L.append("서술: 2008 이후에는 신호의 예측력(IC)이 절반 이하로 줄었고 동시에 소수 리더 쏠림도 커졌다. 두 설명이 함께 있다.")
    elif weaker:
        L.append("서술: 쏠림은 크게 달라지지 않았는데 신호의 예측력(IC)이 절반 이하로 줄었다. 약해진 쪽은 신호 쪽에 가깝다.")
    elif more:
        L.append("서술: 신호의 예측력(IC)은 절반 이상 유지됐지만 소수 리더 쏠림이 커졌다. 쏠림(집중) 쪽 설명과 맞는다.")
    else:
        L.append("서술: IC 도 쏠림도 뚜렷하게 달라지지 않았다. 2008 이후 알파가 약한 것은 두 설명 어느 쪽으로도 갈리지 않고, "
                 "짧은 표본의 잡음일 수 있다.")
    L.append("(기준: IC 가 이전의 50% 이하면 '약화', 상위 3 몫이 3%p 이상 늘면 '쏠림 증가' — 서술용 고정 기준이며 통계 검정이 아니다.)")
    return L


def render(r: dict) -> str:
    v, pw = r["verdicts"], r["power"]
    L = [f"# 주도주 사전 식별 검증 leader-catch-v1 ({JUDGE_VERSION}){' — 스모크(가짜 데이터)' if r['smoke'] else ''}", "",
         "다음 리더를 **그 시점의 정보만으로** 미리 가려낼 수 있었나. 승자를 이름으로 정하지 않고, 리더십이 계속 바뀐 장기 자료에서 "
         f"사전 신호 8종 + 합성 1종을 시험한다. 판정 구간 **{lab.MAIN_START} ~ {lab.MAIN_END}**(선택 반 {lab.SEL_START}~{lab.SEL_END}, "
         f"확인 반 {lab.CONF_START}~{lab.CONF_END}). 2008~ 와 ETF 메뉴는 보고용.", "",
         f"**종합 판정: {v['overall']}** · 대조군 점검: {v['controls']} · 확인된 칸 {v['confirmed_cells']} · 견고한 신호: {v['robust_signals']}", "",
         rp.power_line(pw),
         f"다중 검정: 신호 {len(lab.SIGNALS)}개 × 유니버스 {len(lab.UNIVERSES)}개 = {lab.N_TRIALS}칸(n_trials={lab.N_TRIALS}). "
         "각 칸은 세 관문(적중률 CI·알파 t≥2·하위 구간 3/4)을 모두 넘어야 하고, 신호는 2개 이상 유니버스에서 확인돼야 견고하다. "
         "그래도 우연 통과 가능성이 0은 아니며, 대조군(F7 저변동성·F8 단기 반전)이 같이 통과하면 이 시험은 변별력이 없다고 읽는다.", ""]
    if r["noop_cells"]:
        L += [f"**NOT_EVALUABLE(noop_guard)**: {', '.join(r['noop_cells'])} — 포트폴리오가 기준선과 매일 같음.", ""]
    L += ["## 판정 규칙 (사전 고정)", "",
          "- 칸(유니버스×신호) 확인: 확인 반의 **다음 1개월 적중률**(선택한 구성원이 그달 유니버스 수익 상위 3분위에 든 비율, 기회 수준 1/3) "
          "원형 블록 부트스트랩(12개월 블록·1,000회·시드 20261012) 95% CI **하한 > 1/3** AND 확인 반 CAPM 알파(동일가중 유니버스 대비, 월별 NW6) **> 0 이고 t ≥ 2.0** "
          "AND 4개 하위 구간 중 알파 > 0 이 **3개 이상**.",
          "- 신호 견고: 3개 유니버스 중 **2곳 이상**에서 확인. 대조군(F7·F8) 중 하나라도 견고하면 NOT_DISCRIMINATING.", ""]

    L += ["## 판정 요약", "", "| 신호 | 종류 | " + " | ".join(UNIV_NAMES[u] for u in lab.UNIVERSES) + " | 판정 |", "|---|---|" + "---|" * (len(lab.UNIVERSES) + 1)]
    for s in lab.SIGNALS:
        cells = [r["universes"][u]["cells"][s] for u in lab.UNIVERSES]
        L.append(f"| {s} {lab.SIGNAL_NAMES[s]} | {'대조군' if s in lab.CONTROLS else '모멘텀류'} | "
                 + " | ".join(("확인" if c["confirmed"] else ("평가 불가" if c["confirmed"] is None else "미확인")
                               + (f" ({c['fail_kind']})" if c.get("fail_kind") == "FAIL_UNDERPOWERED" else "")) for c in cells)
                 + f" | **{r['signal_verdicts'][s]}** |")
    L.append("")

    for u in lab.UNIVERSES:
        un = r["universes"][u]
        L += [f"## {un['name']} (상위 {un['k']}개, 동일가중, 월 1회, 편도 {lab.COST_BPS:.0f}bp)", "",
              "확인 반(1967~2007) 기준 판정 열 + 선택 반 비교. 알파는 연율, t 는 NW(6).", "",
              "| 신호 | 확인 반 적중률(1m) 95% CI | 확인 반 IC (t) | 확인 반 알파 vs 동일가중 (t) | 하위구간 알파>0 (동일가중/시장) | CAGR / 샤프 / MDD (판정 구간) | 판정 |",
              "|---|---|---|---|---|---|---|"]
        for s in lab.SIGNALS:
            c = un["cells"][s]
            cf, fu = c["windows"]["conf"], c["windows"]["full"]["port"]
            L.append(f"| {s} | {ci_txt(cf['hit1'])} | {num(cf['ic'].get('mean'), 3, True)} ({num(cf['ic'].get('t'), 1)}) | "
                     f"{pct(cf['port'].get('alpha_ew'), 1, True)} ({num(cf['port'].get('t_ew'), 1)}) | "
                     f"{c['n_positive_subperiods_ew']}/4, {c['n_positive_subperiods_mkt']}/4 | "
                     f"{pct(fu.get('cagr'))} / {num(fu.get('sharpe'))} / {pct(fu.get('mdd'), 0)} | {c['verdict']} |")
        L += ["", "선택 반(1927~1966)·전체 판정 구간의 같은 지표(참고) — 적중률(1m·12m), IC, 시장 대비 알파:", "",
              "| 신호 | 선택 반 적중 1m | 전체 적중 1m | 전체 적중 12m | 선택 반 IC (t) | 전체 IC (t) | 전체 알파 vs 시장 (t) | 전체 알파 vs 동일가중 (t) | 200일선 필터 포함 CAGR/샤프/MDD (보고) |",
              "|---|---|---|---|---|---|---|---|---|"]
        for s in lab.SIGNALS:
            c = un["cells"][s]
            sel, fu = c["windows"]["sel"], c["windows"]["full"]
            fp, ff = fu["port"], c["with_market_filter"]["full"]
            L.append(f"| {s} | {ci_txt(sel['hit1'])} | {ci_txt(fu['hit1'])} | {ci_txt(fu['hit12'])} | "
                     f"{num(sel['ic'].get('mean'), 3, True)} ({num(sel['ic'].get('t'), 1)}) | {num(fu['ic'].get('mean'), 3, True)} ({num(fu['ic'].get('t'), 1)}) | "
                     f"{pct(fp.get('alpha_mkt'), 1, True)} ({num(fp.get('t_mkt'), 1)}) | {pct(fp.get('alpha_ew'), 1, True)} ({num(fp.get('t_ew'), 1)}) | "
                     f"{pct(ff.get('cagr'))} / {num(ff.get('sharpe'))} / {pct(ff.get('mdd'), 0)} |")
        L += ["", "하위 구간 알파(동일가중 대비, 연율) · 10년 단위 IC(감쇠):", "",
              "| 신호 | " + " | ".join(f"{a[:4]}~{b[:4]}" for a, b in lab.SUBPERIODS) + " | "
              + " | ".join(f"IC {d}s" for d in lab.DECADES) + " |", "|---|" + "---|" * (len(lab.SUBPERIODS) + len(lab.DECADES))]
        for s in lab.SIGNALS:
            c = un["cells"][s]
            L.append(f"| {s} | " + " | ".join(pct(x.get("alpha_ew"), 1, True) for x in c["subperiods"]) + " | "
                     + " | ".join(num(d.get("ic"), 3, True) for d in c["decades"]) + " |")
        L += ["", f"2008~ 보고(판정 아님) — 적중률(1m)·IC·알파(동일가중)·CAGR/샤프/MDD:", "",
              "| 신호 | 적중 1m | IC (t) | 알파 vs 동일가중 (t) | CAGR / 샤프 / MDD | 200일선 필터 CAGR/샤프/MDD |", "|---|---|---|---|---|---|"]
        for s in lab.SIGNALS:
            c = un["cells"][s]
            po, pp, pf = c["windows"]["post2008"], c["windows"]["post2008"]["port"], c["with_market_filter"]["post2008"]
            L.append(f"| {s} | {ci_txt(po['hit1'])} | {num(po['ic'].get('mean'), 3, True)} ({num(po['ic'].get('t'), 1)}) | "
                     f"{pct(pp.get('alpha_ew'), 1, True)} ({num(pp.get('t_ew'), 1)}) | "
                     f"{pct(pp.get('cagr'))} / {num(pp.get('sharpe'))} / {pct(pp.get('mdd'), 0)} | "
                     f"{pct(pf.get('cagr'))} / {num(pf.get('sharpe'))} / {pct(pf.get('mdd'), 0)} |")
        L.append("")

    L += ["## 리더십 집중도 진단 (보고만)", "",
          "달력 연도별 수익 상위 3개 구성원이 양의 수익 합계에서 차지한 몫, 상위 3 평균 − 전체 평균, 지난해 수익 순위와의 상관(리더십 지속), 지난해 상위 3과 겹친 수 — 연도 평균.", "",
          "| 유니버스 | 구간 | 연수 | 상위3 몫 | 상위3−평균 | 분산(횡단 표준편차) | 순위 지속 상관 | 상위3 겹침(기회 수준 9/N) |", "|---|---|---|---|---|---|---|---|"]
    for u in lab.UNIVERSES:
        cs = r["universes"][u]["concentration"]["summary"]
        n = r["universes"][u]["concentration"].get("n_members")
        for key, lbl in (("pre2008", "1927~2007"), ("post2008", "2008~")):
            x = cs[key]
            L.append(f"| {UNIV_NAMES[u]} | {lbl} | {x['years']} | {pct(x['top3_share_pos'])} | {pct(x['top3_minus_mean'], 1, True)} | "
                     f"{pct(x['dispersion'])} | {num(x['persistence'], 2, True)} | {num(x['top3_overlap'], 2)} (9/{n}={9 / n:.2f}) |"
                     if n else f"| {UNIV_NAMES[u]} | {lbl} | {x['years']} | — | — | — | — | — |")
    L += ["", "### 2008 이후 약함: 신호 약화 vs 리더십 집중 (서술, 검정 아님)", ""] + paragraph(r) + [""]

    L += ["## ETF 메뉴 연구 (보조 — '지지' 표시만, 판정 아님)", "",
          f"메뉴(고정): {', '.join(lab.ETF_MENU)} (QQQ 등 사후 승자는 넣지 않음). 구간 {lab.ETF_START}~{lab.ETF_END}, 상위 {lab.ETF_K}개 동일가중, 월 1회. "
          "**이 메뉴 자체가 어느 정도 사후적으로 고른 것**(오늘 살아남은 인기 ETF·섹터라는 점)이라 장기 French 자료보다 증거 가치가 낮다. "
          "SUPPORTING = 적중률 점추정 > 1/3 AND 평균 IC > 0 AND SPY 대비 알파 > 0.", ""]
    if r["etf_meta"].get("error"):
        L += [f"ETF 가격을 받지 못해 건너뜀: {r['etf_meta']['error']}", ""]
    else:
        L += ["| 신호 | 종류 | 적중 1m 95% CI | 적중 12m | IC (t) | 알파 vs SPY (t) | 알파 vs 동일가중 (t) | CAGR / 샤프 / MDD | 지지 |", "|---|---|---|---|---|---|---|---|---|"]
        for s in lab.ETF_SIGNALS:
            e = r["etf"].get(s)
            if not e:
                continue
            p = e["port"]
            L.append(f"| {s} | {'대조군' if e['control'] else '모멘텀류'} | {ci_txt(e['hit1'])} | {ci_txt(e['hit12'])} | {num(e['ic'].get('mean'), 3, True)} ({num(e['ic'].get('t'), 1)}) | "
                     f"{pct(p.get('alpha_mkt'), 1, True)} ({num(p.get('t_mkt'), 1)}) | {pct(p.get('alpha_ew'), 1, True)} ({num(p.get('t_ew'), 1)}) | "
                     f"{pct(p.get('cagr'))} / {num(p.get('sharpe'))} / {pct(p.get('mdd'), 0)} | {'SUPPORTING' if e['supporting'] else '—'} |")
        L.append("")
    L += ["## 읽는 법", "",
          "- 이 연구는 엔진을 바꾸지 않는다. CONFIRMED 는 '그 시점 정보로 리더를 미리 가려낸 증거가 있었다'까지이며 채택이 아니다.",
          "- 모멘텀류가 견고한데 대조군도 견고하면, 신호가 아니라 유니버스·기간 특성(예: 저변동 우위)이 결과를 만든 것일 수 있다.",
          "- 산업·스타일 포트폴리오는 개별 종목이 아니라 묶음이라 리더십이 느리게 바뀐다. 개별 종목 결론으로 옮기지 않는다.", ""]
    return "\n".join(L)


# ---------------------------------------------------------------- 실행
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--smoke", action="store_true", help="가짜 자료로 끝까지(네트워크 없음)")
    ap.add_argument("--max-cells", type=int, default=0, help="(확인용) 이번 실행에서 계산할 최대 항목 수; 남으면 종료 코드 3")
    a = ap.parse_args(argv)
    out, ckpt = Path(a.out), Path(a.checkpoint)
    out.mkdir(parents=True, exist_ok=True)
    ckpt.mkdir(parents=True, exist_ok=True)
    deadline = float(os.environ.get("RESEARCH_JOB_DEADLINE_EPOCH") or time.time() + 86400)

    years = (lab.pd.Timestamp(lab.MAIN_END) - lab.pd.Timestamp(lab.MAIN_START)).days / 365.25
    power = rp.power_report(years, lab.N_TRIALS)  # 결과를 보기 전에 계산(구간·시도 수만 쓴다)

    fp = {"smoke": a.smoke, "judge": JUDGE_VERSION}
    prev = load_json(ckpt / "meta.json")
    if prev and prev.get("fingerprint") != fp:   # 모드가 바뀌면 처음부터
        for f in ckpt.glob("*.json"):
            f.unlink()
    save_json(ckpt / "meta.json", {"fingerprint": fp})

    pending = [it for it in work_items() if not item_file(ckpt, it[0], it[1], it[2]).exists()]
    print(f"[1/3] 남은 항목 {len(pending)}/{len(work_items())}", flush=True)

    data, etf_data, etf_err = None, None, None
    ctxs: dict[str, lab.Context] = {}
    done_now = 0

    def out_of_time() -> bool:
        return (not a.smoke and time.time() > deadline - 45) or (a.max_cells and done_now >= a.max_cells)

    for kind, u, s in pending:
        if out_of_time():
            print(f"체크포인트: {done_now}개 계산 — 시간 예산 소진(또는 --max-cells)", flush=True)
            return EXIT_IN_PROGRESS
        if kind in ("cell", "conc"):
            if data is None:
                data = lab.synthetic_data() if a.smoke else lab.load_real()
            if u not in ctxs:
                ctxs.clear()  # 메모리: 한 번에 한 유니버스만 보관(항목이 유니버스 순서로 정렬돼 있다)
                ctxs[u] = lab.Context(data[u], data["mkt"], data["rf"], lab.TOP_K[u], u)
            ctx = ctxs[u]
            if kind == "cell":
                res = lab.evaluate_cell(ctx, s, power, rp)
                print(f"  {u}/{s}: {res['verdict']}", flush=True)
            else:
                rows = lab.concentration_table(ctx)
                res = {"rows": rows, "summary": lab.concentration_summary(rows), "n_members": len(ctx.members)}
        else:  # etf — 보조 연구: 자료를 못 받아도 실패로 만들지 않고 사유를 기록한다
            if etf_data is None and etf_err is None:
                try:
                    etf_data = lab.synthetic_etf() if a.smoke else lab.load_etf_real()
                except Exception as exc:  # noqa: BLE001
                    etf_err = f"{type(exc).__name__}: {exc}"
            if etf_err:
                save_json(ckpt / "etf_error.json", {"error": etf_err})
                save_json(item_file(ckpt, kind, u, s), None)
                done_now += 1
                continue
            if "etf" not in ctxs:
                ctxs.clear()
                ctxs["etf"] = lab.Context(etf_data["rets"], etf_data["mkt"], etf_data["rf"], lab.ETF_K, "etf")
            res = lab.evaluate_etf(ctxs["etf"], s)
        save_json(item_file(ckpt, kind, u, s), res)
        done_now += 1

    print("[2/3] 조립·보고서", flush=True)
    if data is None:
        data = lab.synthetic_data() if a.smoke else lab.load_real()
    err = load_json(ckpt / "etf_error.json")
    etf_meta = {"error": err["error"]} if err else {"missing": (etf_data or {}).get("missing", [])}
    result = assemble(ckpt, power, a.smoke, data["source"], etf_meta, str(data["rf"].index[-1].date()))
    if err:
        result["etf"] = {}
    save_json(out / "results.json", result)
    atomic_write(out / "REPORT.md", render(clean(result)))
    print(json.dumps(result["verdicts"], ensure_ascii=False), flush=True)
    return EXIT_DONE


if __name__ == "__main__":
    sys.exit(main())
