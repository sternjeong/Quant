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
        from core import rnd_topics

        data["topics"] = rnd_topics.all_states()
    except Exception as exc:  # noqa: BLE001
        data["topics_error"] = type(exc).__name__
    try:
        from core import core_rnd

        data["core_registry"] = core_rnd.load_registry()
        from datetime import date as _d

        q = core_rnd.quarter_of(_d.today())
        data["core_quarter"] = q
        data["core_agent"] = core_rnd.agent_state(q)
    except Exception as exc:  # noqa: BLE001
        data["core_error"] = type(exc).__name__
    try:
        from core import crypto_shadow, geo_shadow

        rows = crypto_shadow.load_ledger()
        data["crypto"] = {"records": len(rows), "last": rows[-1] if rows else None}
        data["geo"] = {"months": [r["month"] for r in geo_shadow.load_ledger()]}
    except Exception:  # noqa: BLE001
        pass
    try:
        from core import forward_tournament as ft

        rows = ft.load_ledger()
        data["tournament"] = {"records": len(rows), "last": rows[-1].get("date") if rows else None,
                              "labels": {k: v["label"] for k, v in ft.CANDIDATES.items()}}
    except Exception:  # noqa: BLE001
        pass
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
        from core.research_jobs import Config, load_state, load_job_definitions

        cfg = Config()
        state = load_state(cfg)
        data["runner"] = state.get("satellite_lab") or {}
        jobs, invalid = load_job_definitions(cfg)
        data["research_jobs"] = [{"id": j.id, "title": j.title,
                                  "status": (state.get("jobs", {}).get(j.id) or {}).get("status", "pending")}
                                 for j in sorted(jobs.values(), key=lambda j: (j.priority, j.id))]
        data["invalid_jobs"] = invalid
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


def render_topics(data: dict) -> str:
    """연구 주제 켜기/끄기 — 끄면 멈추고(아무것도 지우지 않음) 다시 켜면 이어진다."""
    if "topics_error" in data:
        return f'<h2>연구 주제</h2><p>확인 불가 {_e(data["topics_error"])}</p>'
    rows = []
    for key, t in (data.get("topics") or {}).items():
        state = '<span class="badge active">켜짐</span>' if t["on"] else '<span class="badge failed">꺼짐</span>'
        btn_label, btn_val = ("끄기", "0") if t["on"] else ("켜기", "1")
        btn = (f'<form method="post" action="/rnd/topics" style="display:inline">'
               f'<input type="hidden" name="key" value="{html.escape(key)}"><input type="hidden" name="on" value="{btn_val}">'
               f'<button type="submit" style="background:{"#5a2a2a" if t["on"] else "#2a5a34"};color:#fff;border:0;border-radius:8px;'
               f'padding:.35rem .9rem;cursor:pointer">{btn_label}</button></form>')
        changed = f'<br><small>{_e(t["changed_at"])} · {_e(t["actor"])}</small>' if t.get("changed_at") else ""
        rows.append(f'<tr><td><b>{_e(t["label"])}</b><br><small>{_e(t["what"])}</small></td><td>{state}{changed}</td>'
                    f'<td><small>끄면 멈춤: {_e(t["pauses"])}</small></td><td>{btn}</td></tr>')
    return ('<h2>연구 주제 켜기/끄기</h2><p class="subtitle">끄면 그 주제의 새 아이디어·재작업·판정이 멈춥니다. 이미 만든 아이디어·기록·누적 시도 수·대기열은 '
            '그대로 남아 다시 켜면 그 자리에서 이어집니다. 바뀐 설정은 다음 03:00 배치·다음 연구 창부터 적용됩니다.</p>'
            '<table><tr><th>주제</th><th>상태</th><th>꺼져 있는 동안</th><th></th></tr>' + "".join(rows) + '</table>')


def render_core(data: dict) -> str:
    if "core_error" in data:
        return f'<h2>코어 분기 연구</h2><p>확인 불가 {_e(data["core_error"])}</p>'
    reg = data.get("core_registry") or {}
    ag = data.get("core_agent") or {}
    rows = []
    for v in (reg.get("ideas") or {}).values():
        res = v.get("result") or {}
        label, tone = STATUS_LABELS.get(v["status"], (v["status"], "unknown"))
        rows.append(f'<tr><td><b>{_e(v["id"])}</b><br><small>{_e(v["idea"].get("title"))} · {_e(v["idea"].get("topic"))}</small></td>'
                    f'<td><span class="badge {tone}">{html.escape(label)}</span></td>'
                    f'<td><small>{_e(json.dumps(v["idea"].get("config"), ensure_ascii=False))} · 매도 {_e(v["idea"].get("exit_rule", {}).get("kind"))}</small></td>'
                    f'<td><small>{"<br>".join(html.escape(x) for x in (res.get("reasons") or [])[:3]) or "—"}</small></td></tr>')
    head = (f'<p class="subtitle">분기마다 AI 가 근거 있는 코어 아이디어(선정·보유 중 매도 시점)를 최대 3개 제안하고 같은 판정으로 시험합니다. '
            f'누적 시도 수 <b>{_e(reg.get("cumulative_trials"))}</b>(이전 코어 연구 229개 포함). 이번 분기 {_e(data.get("core_quarter"))}: '
            f'제안 {_e(ag.get("runs", 0))}회 · 등록 {_e(len(ag.get("frozen") or []))}개'
            + (f' · 형식 오류 {_e(len(ag.get("errors") or {}))}개' if ag.get("errors") else "") + '</p>')
    table = ('<table><tr><th>아이디어</th><th>상태</th><th>설정</th><th>사유</th></tr>' + "".join(rows) + '</table>') if rows else '<p>아직 등록된 아이디어가 없습니다.</p>'
    return '<h2>코어 분기 연구</h2>' + head + table


def render_shadows(data: dict) -> str:
    c = data.get("crypto") or {}
    g = data.get("geo") or {}
    t = data.get("tournament") or {}
    last = c.get("last") or {}
    on = ", ".join(f'{t.split("-")[0]} {"보유" if v.get("on") else "현금"}' for t, v in (last.get("assets") or {}).items())
    return ('<h2>앞으로 기록(배분 미반영)</h2><table>'
            f'<tr><th>코인 추세 기록</th><td>{_e(c.get("records", 0))}일 · 최근 {_e(last.get("date"))} {html.escape(on)} · 12개월(252거래일) 뒤 판정</td></tr>'
            f'<tr><th>앞으로 토너먼트</th><td>{_e(t.get("records", 0))}일 · 최근 {_e(t.get("last"))} · '
            f'{html.escape(" · ".join(f"{k} {v}" for k, v in (t.get("labels") or {}).items()))} · 252거래일 뒤 판정(주간 엔진 점검에 경과)</td></tr>'
            f'<tr><th>AI 국제정세 의견</th><td>{_e(len(g.get("months") or []))}개월 · {_e(", ".join(g.get("months") or []) or "아직 없음")} · 24개월 뒤 판정</td></tr>'
            '</table>')


def render_body(data: dict) -> str:
    parts = ['<p class="subtitle">새틀라이트 종목 선정·진입 타이밍·매도 규칙과 코어 분기 연구를 계속 시험합니다. 아이디어는 시작 목록과 03:00 AI 에이전트가, '
             '판정은 결과를 보기 전에 고정한 코드가 합니다. 계산은 VM 연구 창의 빈 시간에 돕니다. 통과해도 챔피언에 자동 반영되지 않습니다.</p>',
             render_topics(data), render_research_jobs(data), render_core(data), render_shadows(data), '<h2>새틀라이트 R&amp;D</h2>']
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


def render_research_jobs(data: dict) -> str:
    labels = {"pending": "대기", "running": "계산 중", "in_progress": "이어 계산 대기",
              "done": "완료", "failed": "실패", "cancelled": "취소"}
    jobs = data.get("research_jobs", [])
    def table(rows):
        rendered = [f'<tr><td><b>{_e(j["title"])}</b><br><small>{_e(j["id"])}</small></td>'
                    f'<td>{_e(labels.get(j["status"], j["status"]))}</td></tr>' for j in rows]
        return '<table><tr><th>연구</th><th>상태</th></tr>' + ''.join(rendered) + '</table>'
    asset_jobs = [j for j in jobs if j.get("id", "").startswith(("core-universe-expansion-", "delisted-precursors-"))]
    general_jobs = [j for j in jobs if j not in asset_jobs]
    errors = [f'<tr><td>{_e(k)}</td><td>정의 오류: {_e(v)}</td></tr>' for k, v in data.get("invalid_jobs", {}).items()]
    general = table(general_jobs) if general_jobs else '<p>현재 일반 VM 연구가 없습니다.</p>'
    if errors:
        general += '<table>' + ''.join(errors) + '</table>'
    asset = ('<h2>자산군 확장·생존편향 연구</h2><p>현재 코어에 없는 자산군 ETF를 소수 후보에 추가해 비교하고, CRSP 상장폐지 수익률을 포함해 사전 위험신호를 분석합니다. '
             'S&amp;P 지수 편출은 상장폐지와 구별합니다. CRSP 입력이 없으면 데이터 대기/미평가로 보고하며, 후보군·챔피언 전략은 자동 변경하지 않습니다.</p>'
             + (table(asset_jobs) if asset_jobs else '<p>등록된 자산군·생존편향 연구가 없습니다.</p>'))
    return ('<h2>사전 등록 VM 연구</h2><p>코인 결합·연도별 패배 분해 등 고정한 연구를 VM 실행기가 계산합니다. '
            '아래 작업은 위 주제 토글과 별도로 실행됩니다. 결과와 실패 사유는 '
            '<a href="/reports/report-research-results">검증 연구 결과</a>에서 확인합니다. '
            '좋은 결과도 자동으로 챔피언에 반영되지 않습니다.</p>'
            + general + asset)
