"""관제 허브 '에이전트 연구' 화면 — 가설 퍼널·누적 시도 수·최근 전이·에이전트 예산(읽기 전용).

원천: core.hypothesis_registry(quant.db), core.agent_budget(data/agent_usage.jsonl). 읽기 실패는 해당 절만 '확인 불가'.
"""

from __future__ import annotations

import html
from typing import Any

STAGES = [("draft", "초안"), ("frozen", "동결(심판 대기)"), ("judged_pass", "심판 통과"), ("shadow", "shadow 전진검증"),
          ("promotion_candidate", "승격 후보"), ("promoted_paper", "paper 승격"), ("judged_fail", "심판 탈락"),
          ("retired", "종료"), ("abandoned", "구현 포기")]


def collect() -> dict[str, Any]:
    data: dict[str, Any] = {}
    try:
        from core import hypothesis_registry as reg

        data["funnel"] = reg.funnel()
        data["events"] = reg.recent_events(15)
        data["candidates"] = reg.list_by_status(reg.PROMOTED, reg.CANDIDATE, reg.SHADOW)
    except Exception as exc:  # noqa: BLE001
        data["registry_error"] = type(exc).__name__
    try:
        from core import agent_budget

        data["budget"] = agent_budget.summary()
        data["roles"] = agent_budget.ROLES
        data["models"] = {r: agent_budget.effective(r).model for r in agent_budget.ROLES}
        data["model_choices"] = agent_budget.MODEL_CHOICES
        data["recent_runs"] = agent_budget.read_usage()[-10:]
    except Exception as exc:  # noqa: BLE001
        data["budget_error"] = type(exc).__name__
    return data


def _row(label: str, value: str) -> str:
    return f'<tr><th>{html.escape(label)}</th><td>{value}</td></tr>'


def _e(v: Any) -> str:
    return html.escape("—" if v is None else str(v))


ROLE_LABELS = {"scout": "Scout — 아이디어 수집", "writer": "Writer — 가설 작성(월·수·금)",
               "implementer": "Implementer — 신호 코드 작성", "critic": "Critic — 코드 검증(수익률 안 봄)",
               "postmortem": "Post-mortem — 실패 교훈(일)"}


def render_model_form(data: dict) -> str:
    """역할별 모델 선택. 저장하면 data/agent_models.json 에 기록되고 다음 배치부터 적용된다."""
    rows = []
    for role, cfg in data["roles"].items():
        cur = data["models"][role]
        opts = "".join(f'<option value="{m}"{" selected" if m == cur else ""}>{m}{" (기본)" if m == cfg.model else ""}</option>'
                       for m in data["model_choices"])
        rows.append(_row(ROLE_LABELS.get(role, role),
                         f'<select name="{html.escape(role)}" style="background:#0f1115;color:#e6e6e6;border:1px solid #2a2e37;'
                         f'border-radius:8px;padding:.35rem .5rem;font-size:.9rem">{opts}</select>'))
    return ('<h2>역할별 모델</h2><form method="post" action="/research/models">'
            f'<table>{"".join(rows)}</table>'
            '<p style="margin-top:.6rem"><button type="submit" style="background:#4c7dff;color:#fff;border:0;border-radius:8px;'
            'padding:.55rem 1.2rem;font-size:.9rem;cursor:pointer">저장</button> '
            '<small>다음 03:00 배치부터 적용 · 텔레그램 /models 로도 바꿀 수 있음 · 비싼 모델일수록 예산이 빨리 찹니다</small></p></form>')


def apply_model_form(form: dict[str, list[str]], actor: str = "hub") -> list[str]:
    """폼 값 중 바뀐 것만 저장하고 변경 목록을 돌려준다. 알 수 없는 역할·모델은 무시한다."""
    from core import agent_budget

    changed = []
    for role in agent_budget.ROLES:
        model = (form.get(role) or [None])[0]
        if model in agent_budget.MODEL_CHOICES and model != agent_budget.effective(role).model:
            agent_budget.set_model(role, model, actor)
            changed.append(f"{role}={model}")
    return changed


def card_badge(data: dict) -> str:
    if "registry_error" in data:
        return '<span class="badge unknown">확인 불가</span>'
    c = data["funnel"]["counts"]
    cand = c.get("promotion_candidate", 0)
    if cand:
        return f'<span class="badge active">승격 후보 {cand}</span>'
    return f'<span class="badge unknown">shadow {c.get("shadow", 0)} · 누적 시도 {data["funnel"]["cumulative_trials"]}</span>'


def render_body(data: dict) -> str:
    parts = ['<p class="subtitle">에이전트는 가설을 만들고, 판정은 코드가 합니다. 매일 03:00 KST 배치 · 실거래 경로 없음.</p>']
    if "registry_error" in data:
        parts.append(f'<h2>가설 퍼널</h2><table>{_row("상태", "확인 불가 " + _e(data["registry_error"]))}</table>')
    else:
        f = data["funnel"]
        rows = [_row(label, _e(f["counts"].get(key, 0))) for key, label in STAGES]
        rows.insert(0, _row("누적 시도 수 N", f"<b>{_e(f['cumulative_trials'])}</b> <small>줄지 않음 — 커질수록 통과 기준이 엄격해짐</small>"))
        rows.insert(1, _row("이번 주 동결", f"{_e(f['frozen_this_week'])} / {_e(f['weekly_freeze_cap'])}"))
        parts.append(f'<h2>가설 퍼널</h2><table>{"".join(rows)}</table>')
        rows = []
        for h in data["candidates"]:
            fwd = (h.get("judge") or {}).get("forward") or {}
            extra = f" — 전진 {fwd['n_days']}일 누적 {fwd['forward_cum']:+.2%}" if fwd else ""
            rows.append(_row(h["id"], _e(h["status"]) + " · " + _e(h["spec"]["thesis"][:90]) + _e(extra)))
        parts.append(f'<h2>paper 편입 · 승격 후보 · shadow</h2><table>{"".join(rows) or _row("없음", "")}</table>')
        rows = [_row(f"{e['at']:%m-%d %H:%M}" if e["at"] else "—",
                     f"{_e(e['id'])} {_e(e['from'])} → <b>{_e(e['to'])}</b> <small>{_e((e['note'] or '')[:140])}</small>")
                for e in data["events"]]
        parts.append(f'<h2>최근 상태 전이</h2><table>{"".join(rows) or _row("없음", "")}</table>')
    if "budget_error" in data:
        parts.append(f'<h2>에이전트 예산</h2><table>{_row("상태", "확인 불가")}</table>')
    else:
        b = data["budget"]
        rows = [_row("이번 주", f"${b['week_cost']:.2f} / ${b['weekly_cap']:.0f}"),
                _row("오늘 밤", f"${b['night_cost']:.2f} / ${b['nightly_cap']:.0f}"),
                _row("사용량 한도 도달(이번 주)", _e(b["limit_hits_week"]))]
        for role, cfg in data["roles"].items():
            rows.append(_row(role, f"{b['week_runs'][role]} / {cfg.weekly_runs}회 <small>최대 {cfg.max_turns}턴</small>"))
        parts.append(f'<h2>에이전트 예산 <small>(API 환산 금액)</small></h2><table>{"".join(rows)}</table>')
        parts.append(render_model_form(data))
        rows = [_row(str(r.get("at", ""))[5:16], f"{_e(r.get('role'))} {_e(r.get('target'))} · "
                     f"{'성공' if r.get('ok') else '실패'}{' · 한도' if r.get('limited') else ''} · ${r.get('cost_usd') or 0:.2f}")
                for r in reversed(data["recent_runs"])]
        parts.append(f'<h2>최근 에이전트 실행</h2><table>{"".join(rows) or _row("없음", "아직 실행 기록 없음")}</table>')
    return "".join(parts)
