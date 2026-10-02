"""관제 허브 '새틀라이트 R&D 센터' 화면 — 현 규칙 기준선·후보 순위표·관문별 결과·진행 중 아이디어(읽기 전용).

원천: data/satellite_lab/registry.json(core.satellite_lab 등록부), data/satellite_lab/agent/*.json(야간 에이전트 상태),
data/research_jobs/state.json 의 satellite_lab 절(마지막 계산 실행). 읽기 실패는 해당 절만 '확인 불가'.
"""

from __future__ import annotations

import html
import json
from typing import Any

GATE_LABELS = {
    "G1_beats_random": "G1 무작위보다 나음",
    "G2_beats_incumbent_deflated": "G2 현 규칙보다 나음(다중검정 보정)",
    "G3_holdout": "G3 떼어 둔 2년",
    "G4_param_robust": "G4 파라미터 강건",
    "G5_risk": "G5 위험·표본",
}
STATUS_LABELS = {"pass": ("통과 — 사람 검토 대기", "active"), "fail": ("탈락", "failed"),
                 "queued": ("심판 대기", "unknown"), "error": ("계산 오류", "failed"), "reference": ("기준선", "unknown")}


def collect() -> dict[str, Any]:
    data: dict[str, Any] = {}
    try:
        from core import satellite_lab as sl

        reg = sl.load_registry()
        data["registry"] = reg
        data["rows"] = sl.leaderboard(reg)
        data["judge_version"] = sl.JUDGE_VERSION
        agents = []
        if sl.VARIANTS_DIR.is_dir():
            for d in sorted(p for p in sl.VARIANTS_DIR.glob("S-*") if p.is_dir()):
                if d.name in reg["variants"]:
                    continue
                st = sl.agent_state(d.name)
                try:
                    title = json.loads((d / "spec.json").read_text(encoding="utf-8")).get("title")
                except (OSError, ValueError):
                    title = None
                stage = ("폐기: " + st["abandoned"]) if st.get("abandoned") else (
                    "준비 완료(다음 연구 창에 동결)" if sl.agent_ready(d) else
                    "검사 실패 — 재작업 대기" if st.get("tested_hash") and not st.get("test_ok") else
                    "Critic 검토 대기" if st.get("test_ok") else "설계 중")
                agents.append({"id": d.name, "title": title, "stage": stage, "rounds": st.get("rounds", 0)})
        data["agents"] = agents
    except Exception as exc:  # noqa: BLE001
        data["error"] = type(exc).__name__
    try:
        from core.research_jobs import Config, load_state

        data["runner"] = load_state(Config()).get("satellite_lab") or {}
    except Exception:  # noqa: BLE001
        data["runner"] = {}
    return data


def _e(v: Any) -> str:
    return html.escape("—" if v is None else str(v))


def _pct(v: Any) -> str:
    return "—" if v is None else f"{float(v) * 100:.0f}"


def _num(v: Any, digits: int = 2) -> str:
    return "—" if v is None else f"{float(v):.{digits}f}"


def card_badge(data: dict) -> str:
    if "error" in data:
        return '<span class="badge unknown">확인 불가</span>'
    rows = data.get("rows") or []
    passed = sum(1 for r in rows if r["status"] == "pass")
    queued = sum(1 for r in rows if r["status"] == "queued")
    if passed:
        return f'<span class="badge active">검토 대기 {passed}</span>'
    return f'<span class="badge unknown">판정 {len(rows) - queued} · 대기 {queued}</span>'


def render_body(data: dict) -> str:
    parts = ['<p class="subtitle">새틀라이트(15%) 종목 선정 규칙을 계속 시험합니다. 아이디어는 시작 목록과 매일 03:00 에이전트가, '
             '판정은 결과를 보기 전에 고정한 코드가 합니다. 계산은 VM 연구 창(01~03시·13~17시 KST)의 빈 시간에 돕니다. '
             '통과해도 챔피언에 자동 반영되지 않습니다.</p>']
    if "error" in data:
        return "".join(parts) + f'<h2>등록부</h2><p>확인 불가 {_e(data["error"])}</p>'
    reg = data["registry"]
    inc = reg.get("incumbent") or {}
    st = inc.get("stats") or {}
    rows = [
        ("판정 규칙", f'{_e(data["judge_version"])} <small>결과를 보기 전에 고정 — 바꾸려면 새 버전</small>'),
        ("누적 시도 수 N", f'<b>{_e(reg.get("cumulative_trials", 0))}</b> <small>줄지 않음 — 커질수록 G2 통과 기준이 엄격해짐</small>'),
    ]
    if inc:
        rows += [
            ("현 규칙 IS 연샤프", f'{_num((st.get("is") or {}).get("sharpe_annual"))} '
                                 f'<small>(무작위 선정 중앙값 {_num(inc.get("random_is_median"))})</small>'),
            ("현 규칙 무작위 대비", f'IS {_pct(inc.get("random_percentile_is"))}백분위 · 떼어 둔 2년 '
                                  f'{_pct(inc.get("random_percentile_oos"))}백분위 '
                                  '<small>50이면 무작위와 같음, 95 이상이어야 우연보다 낫다고 봄</small>'),
            ("현 규칙 기간", f'{_e(inc.get("split") and "IS ~ " + inc["split"] + " · 이후 2년 떼어 둠")} · 계산 {_e(inc.get("computed_at"))}'),
        ]
    else:
        rows.append(("현 규칙 기준선", "아직 계산 전 — 다음 VM 연구 창에서 계산합니다"))
    runner = data.get("runner") or {}
    if runner:
        rows.append(("마지막 계산 실행", f'{_e(runner.get("last_finished_at") or runner.get("last_started_at"))} · 종료 코드 '
                                        f'{_e(runner.get("exit_code"))} · {_num(runner.get("duration"), 0)}초'))
    parts.append('<h2>기준선</h2><table>' + "".join(f'<tr><th>{html.escape(k)}</th><td>{v}</td></tr>' for k, v in rows) + '</table>')

    lb = data.get("rows") or []
    if not lb:
        parts.append('<h2>후보 순위</h2><p>아직 등록된 후보가 없습니다.</p>')
    else:
        trs = []
        for r in lb:
            label, tone = STATUS_LABELS.get(r["status"], (r["status"], "unknown"))
            gates = f'{r["gates_passed"]}/{r["n_gates"]}' if r["n_gates"] else "—"
            reasons = "<br>".join(html.escape(x) for x in (r["reasons"] or [])[:4])
            picks = r.get("latest_picks") or {}
            trs.append(
                f'<tr><td><b>{_e(r["id"])}</b><br><small>{_e(r["title"])} · {"시작 목록" if r["origin"] == "seed" else "에이전트"}</small></td>'
                f'<td><span class="badge {tone}">{html.escape(label)}</span></td>'
                f'<td>{gates}</td><td>{_num(r["active_is_sharpe"])}</td><td>{_pct(r["random_pct"])}</td>'
                f'<td>{_num(r["dsr"])}</td><td>{_num(r["is_sharpe"])} / {_num(r["oos_sharpe"])}</td>'
                f'<td><small>{_e(r["structure"])}<br>{_e(json.dumps(r["best_params"], ensure_ascii=False) if r["best_params"] else None)}</small></td>'
                f'<td><small>{_e(picks.get("date"))}: {_e(", ".join(picks.get("tickers") or []) or None)}</small></td>'
                f'<td><small>{reasons or "—"}</small></td></tr>')
        parts.append(
            '<h2>후보 순위</h2><p class="subtitle">현 규칙 대비 초과 연샤프(IS) 순. 백분위는 같은 구조로 무작위로 고른 200번과 비교한 위치입니다. '
            '숫자가 좋아 보여도 관문을 모두 넘지 못하면 탈락입니다.</p>'
            '<div style="overflow-x:auto"><table><tr><th>후보</th><th>상태</th><th>관문</th><th>현 규칙 대비<br>초과 샤프</th>'
            '<th>무작위 대비<br>백분위</th><th>DSR</th><th>샤프<br>IS / 2년</th><th>구조·파라미터</th><th>마지막 선정</th><th>탈락 사유</th></tr>'
            + "".join(trs) + '</table></div>')
        detail = []
        for v in reg["variants"].values():
            res = v.get("result") or {}
            if not res.get("gates"):
                continue
            items = "".join(f'<li>{"○" if g.get("pass") else "×"} {html.escape(GATE_LABELS.get(k, k))} '
                            f'<small>{html.escape(json.dumps({x: y for x, y in g.items() if x != "pass"}, ensure_ascii=False))}</small></li>'
                            for k, g in res["gates"].items())
            detail.append(f'<details><summary>{_e(v["id"])} {_e(v["spec"].get("title"))} — 관문 상세</summary>'
                          f'<p><small>{_e(v["spec"].get("thesis"))}<br>근거: {_e(v["spec"].get("source"))}</small></p><ul>{items}</ul></details>')
        parts.append('<h2>관문 상세</h2>' + "".join(detail) if detail else "")

    agents = data.get("agents") or []
    if agents:
        trs = "".join(f'<tr><td>{_e(a["id"])}</td><td>{_e(a["title"])}</td><td>{_e(a["stage"])}</td><td>{_e(a["rounds"])}</td></tr>'
                      for a in agents)
        parts.append('<h2>에이전트가 만드는 중</h2><table><tr><th>id</th><th>아이디어</th><th>단계</th><th>설계 횟수</th></tr>'
                     + trs + '</table>')
    parts.append('<p class="subtitle">한계: 무료 가격 소스에 없는 상장폐지 종목은 빠짐(생존편향), 배당·세금·슬리피지 미반영, '
                 'champion40 풀의 과거 시총은 근사치입니다. 성과 개선을 보장하지 않습니다.</p>')
    return "".join(parts)
