"""관제 허브 '클라우드 작업' 화면 — 무거운 계산을 Claude 클라우드에 맡기고 결과를 본다(core/offload_queue.py).

라우트(hub/server.py): GET /offload, /offload/<id>   POST /offload/submit
"""

from __future__ import annotations

import html
from typing import Optional

from core import offload_queue as oq
from hub import ui

E = html.escape

STATUS_PILL = {"queued": ("대기", "muted"), "running": ("실행 중", "info"), "done": ("완료", "ok"),
               "partial": ("일부 완료", "warn"), "failed": ("실패", "bad")}

FORM_CSS = """<style>
.oform label{display:block;color:var(--text-2);font-size:.8rem;margin:.6rem 0 .3rem}
.oform textarea,.oform select,.oform input{width:100%;min-height:44px;padding:.55rem .7rem;border:1px solid var(--border-2);
  border-radius:10px;background:var(--surface-2);box-sizing:border-box}
.oform textarea{min-height:120px}
.oform .two{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px}
@media(max-width:520px){.oform .two{grid-template-columns:1fr}}
pre.result{white-space:pre-wrap;overflow-wrap:anywhere}
</style>"""


def _pill(status: str) -> str:
    label, tone = STATUS_PILL.get(status, (status, "muted"))
    return ui.pill(label, tone)


def card_badge() -> str:
    # 대기열을 처음 받는 일(clone)은 '클라우드 작업' 화면에서만 한다 — 개요가 GitHub 때문에 느려지지 않게.
    if not (oq.QUEUE_DIR / ".git").is_dir():
        return ui.pill("열어서 확인", "muted")
    try:
        counts = oq.summary(oq.list_jobs(10))
    except Exception:  # noqa: BLE001 - 개요는 GitHub 문제와 무관하게 떠야 한다
        return ui.pill("확인 불가", "muted")
    pills = []
    if counts["running"]:
        pills.append(ui.pill(f"실행 중 {counts['running']}", "info"))
    if counts["queued"]:
        pills.append(ui.pill(f"대기 {counts['queued']}", "muted"))
    if counts["failed"]:
        pills.append(ui.pill(f"실패 {counts['failed']}", "bad"))
    return "".join(pills) or ui.pill("대기 없음", "ok")


def _form(error: str = "", values: Optional[dict] = None) -> str:
    v = values or {}
    repos = '<option value="">(저장소 없이)</option>' + "".join(
        f'<option{" selected" if v.get("repo", oq.REPOS[0]) == r else ""}>{E(r)}</option>' for r in oq.REPOS)
    err = f'<p class="note bad" role="alert">{E(error)}</p>' if error else ""
    return (f'<details class="panel"{" open" if error or v else ""} style="margin:12px 0"><summary><b>+ 클라우드에 작업 맡기기</b></summary>'
            f'{err}<form class="oform" method="post" action="/offload/submit">'
            '<label for="of-task">할 일 (클라우드는 이 글만 봅니다 — 무엇을 돌리고, 무엇을 보고하고, 어떤 파일을 남길지 적기)</label>'
            f'<textarea id="of-task" name="task" required maxlength="20000" placeholder="예: Quant 전체 테스트를 돌리고 실패한 테스트만 이유와 함께 정리. 코드는 바꾸지 말 것.">{E(v.get("task", ""))}</textarea>'
            '<div class="two">'
            f'<div><label for="of-repo">저장소</label><select id="of-repo" name="repo">{repos}</select></div>'
            f'<div><label for="of-ref">브랜치 (비우면 기본)</label><input id="of-ref" name="ref" maxlength="100" value="{E(v.get("ref", ""))}"></div>'
            f'<div><label for="of-timeout">제한 시간(분)</label><input id="of-timeout" name="timeout" type="number" min="5" max="55" value="{E(v.get("timeout", "50"))}"></div>'
            '</div><p style="margin-top:12px"><button class="btn primary" type="submit">클라우드에 맡기기</button></p>'
            '<p class="meta">제출하면 GitHub 대기열에 올라가고 클라우드 작업자가 바로 시작합니다. 코드 변경은 claude/offload-&lt;번호&gt; 브랜치로만 오고 main 에는 손대지 않습니다. Claude 사용량이 차감됩니다.</p>'
            '</form></details>')


def render_body(error: str = "", values: Optional[dict] = None, message: str = "") -> str:
    try:
        jobs = oq.list_jobs(30)
    except Exception as exc:  # noqa: BLE001
        return (ui.verdict("muted", "대기열을 읽지 못했습니다", str(exc)[:200]) + _form(error, values))
    counts = oq.summary(jobs)
    if counts["running"] or counts["queued"]:
        tone, title = "info", f"클라우드에서 처리 중 {counts['running']}개 · 대기 {counts['queued']}개"
    elif counts["failed"]:
        tone, title = "warn", f"최근 실패한 작업 {counts['failed']}개"
    else:
        tone, title = "ok", "진행 중인 작업이 없습니다"
    sub = "무거운 계산(전체 테스트·백테스트·데이터 처리)은 VM 대신 여기서 — VM 2코어는 그대로 여유를 유지합니다."
    tiles = ui.stats([
        ui.stat("실행 중", str(counts["running"]), "", "info" if counts["running"] else ""),
        ui.stat("대기", str(counts["queued"]), "", ""),
        ui.stat("완료", str(counts["done"] + counts["partial"]), f"최근 {len(jobs)}개 중", "ok"),
        ui.stat("실패", str(counts["failed"]), "", "bad" if counts["failed"] else "ok"),
    ])
    rows = [ui.row(j.title, href=f"/offload/{j.id}", icon="☁",
                   desc=f"{j.id} · {j.repo or '저장소 없음'}{'@' + j.ref if j.ref else ''} · {j.source}",
                   end_html=_pill(j.status)) for j in jobs]
    msg = f'<p class="note">{E(message)}</p>' if message else ""
    help_html = ui.callout(
        "VM 터미널·다른 Claude 세션에서는 <code>offload submit \"할 일\" --repo sternjeong/Quant</code>, "
        "<code>offload list</code>, <code>offload result &lt;번호&gt;</code> 로 같은 대기열을 씁니다. "
        f'클라우드 루틴 설정·실행 기록: <a href="{E(oq.ROUTINE_URL)}" target="_blank" rel="noopener">claude.ai ↗</a>',
        icon="💡")
    return (f'{msg}{ui.verdict(tone, title, sub)}{tiles}{_form(error, values)}'
            f'{ui.section("작업 목록", ui.row_list(rows))}{help_html}')


def render_detail_body(job_id: str) -> Optional[str]:
    job = oq.get_job(job_id)
    if job is None:
        return None
    files = oq.artifacts(job.id) if job.result else []
    rows = [("상태", _pill(job.status)), ("저장소", E(job.repo or "-") + (f" @ <code>{E(job.ref)}</code>" if job.ref else "")),
            ("제출", E(job.created_at) + f" · {E(job.source)}"), ("제한 시간", f"{job.timeout_min}분")]
    if job.repo and job.status in ("done", "partial"):
        rows.append(("코드 변경 브랜치", f"<code>claude/offload-{E(job.id)}</code> (변경이 있었다면)"))
    if files:
        rows.append(("결과 파일", "<br>".join(f"<code>{E(n)}</code> ({s:,} B)" for n, s in files[:30])
                     + f'<br><span class="meta">VM 에서 받기: offload result {E(job.id)} --out ~/offload/{E(job.id)}</span>'))
    result = (f'<pre class="result">{E(job.result)}</pre>' if job.result else
              '<div class="empty">아직 결과가 없습니다. 클라우드 작업자가 시작하면 여기에 나타납니다.</div>')
    return (f'<h1>클라우드 작업</h1><p class="lead">{E(job.title)}</p>{ui.kv_table(rows)}'
            f'{ui.section("결과 (RESULT.md)", result)}{ui.section("맡긴 일 (TASK.md)", f"<pre class=result>{E(job.task)}</pre>")}')


def _one(form: dict, key: str) -> str:
    return (form.get(key) or [""])[0]


def handle_submit(form: dict) -> tuple[str, Optional[str], dict]:
    values = {k: _one(form, k) for k in ("task", "repo", "ref", "timeout")}
    try:
        job = oq.submit(values["task"], repo=values["repo"], ref=values["ref"].strip(),
                        timeout_min=int(values["timeout"] or 50), source="hub")
    except (oq.OffloadError, ValueError) as exc:
        return "/offload", str(exc), values
    return f"/offload/{job.id}", None, {}


HEAD_EXTRA = FORM_CSS
