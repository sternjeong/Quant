"""Quant VM 관제 허브 — 최상위 진입점.

nginx가 80번 포트(`/`)를 이 서버(기본 127.0.0.1:8000)로 프록시한다. 이 서버 자체는 stdlib만
사용하며(신규 의존성 없음), 각 앱/엔진의 상태를 보여주고 슬롯 클릭 시 해당 웹(Streamlit 등
자체 포트로 직접 이동) 또는 엔진 상태/리포트 페이지로 안내한다.

실행: python -m hub.server (deploy/quant-hub.service 참고)
"""

from __future__ import annotations

import html
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from hub.apps_registry import SLOTS, AppSlot  # noqa: E402
from hub import alpaca_status, engine_status, ops_status, research_status  # noqa: E402
from hub.status import UnitStatus, get_unit_status  # noqa: E402
from hub import ui  # noqa: E402

HOST = "127.0.0.1"  # nginx를 거치지 않는 외부 직접 접속은 차단(방화벽에 별도 포트 개방 불필요)
PORT = 8000

# 페이지 스타일은 hub/ui.py 의 공통 디자인 시스템이 담당한다(2026-09-25).


LOGIN_PAGE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>Quant 관제 센터 로그인</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing:border-box; }
  body { margin:0; min-height:100vh; display:flex; align-items:center; justify-content:center;
         background:radial-gradient(1200px 600px at 50% -10%,#1b2540 0%,#0f1115 60%);
         color:#e6e6e6; font-family:-apple-system,"Segoe UI","Noto Sans KR",sans-serif; padding:1.5rem; }
  .box { width:100%; max-width:380px; background:#181b21; border:1px solid #2a2e37;
         border-radius:16px; padding:2rem 1.75rem; box-shadow:0 20px 50px rgba(0,0,0,.45); }
  .logo { width:44px; height:44px; border-radius:12px; background:#4c7dff; display:flex;
          align-items:center; justify-content:center; font-weight:700; font-size:1.3rem; margin-bottom:1rem; }
  h1 { font-size:1.35rem; margin:0 0 .25rem; }
  p.sub { color:#9aa0a8; font-size:.88rem; margin:0 0 1.5rem; }
  label { display:block; font-size:.78rem; color:#9aa0a8; margin:0 0 .35rem; }
  input { width:100%; padding:.75rem .9rem; margin-bottom:1rem; background:#0f1115; color:inherit;
          border:1px solid #2a2e37; border-radius:10px; font-size:1rem; outline:none;
          transition:border-color .15s, box-shadow .15s; }
  input:focus { border-color:#4c7dff; box-shadow:0 0 0 3px rgba(76,125,255,.25); }
  button { width:100%; padding:.8rem; border:0; border-radius:10px; background:#4c7dff; color:#fff;
           font-size:1rem; font-weight:600; cursor:pointer; transition:background .15s; }
  button:hover { background:#6390ff; }
  button:disabled { opacity:.6; cursor:default; }
  .err { min-height:1.2rem; color:#f87171; font-size:.85rem; margin:-.25rem 0 .75rem; }
</style></head><body>
<form class="box" id="f" autocomplete="on">
  <div class="logo">Q</div>
  <h1>Quant VM 관제 센터</h1>
  <p class="sub">계속하려면 로그인하세요.</p>
  <label for="u">아이디</label>
  <input id="u" name="username" autocomplete="username" autocapitalize="none" required autofocus>
  <label for="p">비밀번호</label>
  <input id="p" name="password" type="password" autocomplete="current-password" required>
  <div class="err" id="e" role="alert"></div>
  <button id="b" type="submit">로그인</button>
</form>
<script>
(function () {
  var f = document.getElementById("f"), e = document.getElementById("e"), b = document.getElementById("b");
  function dest() {
    var n = new URLSearchParams(location.search).get("next");
    try {
      var u = new URL(n, location.origin), h = location.hostname;
      if (u.protocol === "https:" && (u.hostname === h || u.hostname.endsWith("." + h))) return u.href;
    } catch (x) {}
    return "/";
  }
  f.addEventListener("submit", function (ev) {
    ev.preventDefault();
    e.textContent = ""; b.disabled = true; b.textContent = "확인 중...";
    var bytes = new TextEncoder().encode(f.username.value + ":" + f.password.value), bin = "";
    bytes.forEach(function (c) { bin += String.fromCharCode(c); });
    fetch("/_login", { method: "POST", credentials: "same-origin", headers: { Authorization: "Basic " + btoa(bin) } })
      .then(function (r) {
        if (r.ok) { location.replace(dest()); return; }
        e.textContent = r.status === 401 ? "아이디 또는 비밀번호가 올바르지 않습니다." : "로그인에 실패했습니다 (" + r.status + ").";
        f.password.value = ""; f.password.focus(); b.disabled = false; b.textContent = "로그인";
      })
      .catch(function () {
        e.textContent = "서버에 연결하지 못했습니다."; b.disabled = false; b.textContent = "로그인";
      });
  });
})();
</script></body></html>"""


# 슬롯별 아이콘(행 왼쪽). 새 슬롯은 kind 기본 아이콘을 쓴다.
SLOT_ICONS = {
    "streamlit": "📊", "code-server": "💻", "scheduler": "⏱", "alpaca": "🧪", "research": "🤖", "ops": "🛡",
    "report-daily-briefing": "🗞", "report-champion-weekly": "🏆", "report-news-digest": "📰",
    "codex-telegram": "💬", "vm-health": "🩺",
}
KIND_ICONS = {"link": "↗", "web": "🌐", "engine": "⚙", "report": "📄", "alpaca": "🧪", "ops": "🛡", "research": "🤖"}


def _unit_pill(status: UnitStatus) -> tuple[str, str]:
    """(알약 HTML, 톤). systemd 상태를 사람 말로 바꾼다."""
    if not status.is_known:
        return ui.pill("확인 불가", "muted"), "muted"
    if status.is_active:
        return ui.pill("실행 중", "ok"), "ok"
    label = "실패" if status.active_state == "failed" else "멈춤"
    return ui.pill(label, "bad"), "bad"


# 타이머가 주기적으로 한 번씩 실행하고 끝나는(oneshot) 서비스: 평소에 inactive 인 것이 정상이다.
# 이런 슬롯은 서비스 대신 타이머가 살아 있는지와 서비스의 마지막 실행 결과로 판정한다(2026-09-25 — 전에는 개요에서
# VM 헬스체크가 늘 "멈춤"으로 보이고 판정 배너의 '서비스 멈춤' 개수에도 들어가 거짓 경보가 났다).
ONESHOT_TIMERS = {"quant-vm-health.service": "quant-vm-health.timer"}


def _slot_unit_pill(unit: str) -> tuple[str, str]:
    timer = ONESHOT_TIMERS.get(unit)
    if timer is None:
        return _unit_pill(get_unit_status(unit))
    svc, tmr = get_unit_status(unit), get_unit_status(timer)
    if not svc.is_known and not tmr.is_known:
        return ui.pill("확인 불가", "muted"), "muted"
    if svc.active_state == "failed" or _last_result(unit) not in ("", "success"):
        return ui.pill("마지막 실행 실패", "bad"), "bad"
    if tmr.is_known and not tmr.is_active:
        return ui.pill("타이머 멈춤", "bad"), "bad"
    if svc.is_active:
        return ui.pill("실행 중", "ok"), "ok"
    return ui.pill("대기(정상)", "ok"), "ok"


def _last_result(unit: str) -> str:
    try:
        from hub.engine_pages import _systemctl_props
    except ImportError:
        return ""
    return _systemctl_props(unit, "Result").get("Result", "")


def _badge_html(status: UnitStatus) -> str:
    return _unit_pill(status)[0]


def _slot_href(slot: AppSlot, host: str) -> str:
    if slot.kind == "web":
        return f"http://{host}:{slot.port}/"
    if slot.kind == "link":
        return slot.url or "/"
    if slot.kind == "report":
        return f"/reports/{slot.id}"
    if slot.kind == "alpaca":
        return "/alpaca"
    if slot.kind == "ops":
        return "/ops"
    if slot.kind == "research":
        return "/research"
    return f"/status/{slot.id}"


CATEGORY_ORDER = ["앱", "엔진", "연구·검증", "운영", "리포트"]
REFRESH_SECONDS = 60


def _report_badge(slot: AppSlot) -> str:
    path = latest_report_path(slot)
    if path is None:
        return ui.pill("아직 없음", "muted")
    stamp = datetime.fromtimestamp(path.stat().st_mtime).strftime("%m-%d %H:%M")
    return ui.pill(f"최신 {stamp}", "ok")


def _alpaca_overall() -> str | None:
    try:
        v = alpaca_status._latest_verification(PROJECT_ROOT)
    except Exception:  # noqa: BLE001
        return None
    if not v:
        return None
    return v.get("overall") or v.get("status")


def _overview(jobs: dict, unit_tones: list[str]) -> tuple[str, str]:
    """대시보드 맨 위 판정 배너와 지표 타일."""
    known = [t for t in unit_tones if t != "muted"]
    down = sum(1 for t in known if t == "bad")
    counts = jobs.get("counts") or {}
    job_err = counts.get("error", 0) + counts.get("missed", 0)
    job_late = counts.get("overdue", 0)
    try:
        backup = ops_status.read_backup()
    except Exception:  # noqa: BLE001
        backup = None
    backup_stale = bool(backup and backup.get("stale"))

    if down or job_err:
        parts = []
        if down:
            parts.append(f"서비스 {down}개가 멈춤")
        if job_err:
            parts.append(f"자동 작업 {job_err}개가 실패·누락")
        tone, title, sub = "bad", "확인이 필요합니다", " · ".join(parts) + " — 아래 빨간 항목을 눌러 보세요."
    elif job_late or backup_stale:
        parts = []
        if job_late:
            parts.append(f"예정 시각이 지났는데 기록이 없는 작업 {job_late}개")
        if backup_stale:
            parts.append("백업이 오래됨")
        tone, title, sub = "warn", "주의할 것이 있습니다", " · ".join(parts)
    elif not known:
        # 서비스 상태를 하나도 읽지 못했으면(systemd 없음 등) '정상'이라고 하지 않는다.
        tone, title = "muted", "서비스 상태를 확인할 수 없습니다"
        sub = ("자동 작업 기록은 정상입니다. " if jobs.get("ok") else "") + "VM 에서 열면 실제 서비스 상태가 보입니다."
    else:
        tone, title, sub = "ok", "모든 시스템 정상", "서비스와 오늘 예정된 자동 작업에 문제가 없습니다."

    svc_value = f"{len(known) - down}/{len(known)}" if known else "—"
    svc_tone = "bad" if down else ("ok" if known else "muted")
    if jobs.get("ok"):
        problems = counts.get("problem", 0)
        job_value = f"{problems}개 문제" if problems else "정상"
        job_tone = "bad" if job_err else ("warn" if problems else "ok")
        checked = sum(v for k, v in counts.items() if k not in ("problem", "disabled"))
        job_detail = f"확인한 작업 {checked}개"
    else:
        job_value, job_tone, job_detail = "—", "muted", "이력 확인 불가"
    if backup:
        b_value = ui.relative_age(backup.get("age_hours"))
        b_tone = "warn" if backup_stale else ("ok" if backup.get("last_run_ok") else "bad")
        b_detail = "원격 보관 켜짐" if backup.get("offsite") else "같은 디스크에만 보관"
    else:
        b_value, b_tone, b_detail = "—", "muted", "상태 파일 없음"
    a = _alpaca_overall()
    a_value, a_tone = (a, "ok" if a == "PASS" else "bad") if a else ("대기", "muted")

    tiles = ui.stats([
        ui.stat("서비스", svc_value, "실행 중 / 전체", svc_tone),
        ui.stat("자동 작업", job_value, job_detail, job_tone),
        ui.stat("마지막 백업", b_value, b_detail, b_tone),
        ui.stat("Alpaca 검증", a_value, "읽기 전용 자동 검증", a_tone),
    ])
    return ui.verdict(tone, title, sub), tiles


def render_dashboard(host: str) -> str:
    jobs = ops_status.job_health_summary()
    groups: dict[str, list[str]] = {}
    unit_tones: list[str] = []
    seen_units: set[str] = set()
    for slot in SLOTS:
        if slot.kind == "alpaca":
            end = alpaca_status.card_badge()
        elif slot.kind == "report":
            end = _report_badge(slot)
        elif slot.kind == "ops":
            end = ops_status.jobs_badge(jobs)
        elif slot.kind == "research":
            end = research_status.card_badge(research_status.collect())
        else:
            end, tone = _slot_unit_pill(slot.unit)
            if slot.unit not in seen_units:
                seen_units.add(slot.unit)
                unit_tones.append(tone)
            if slot.id == "scheduler":
                end = ops_status.jobs_badge(jobs) + end
        external = slot.kind in ("web", "link")
        groups.setdefault(slot.category, []).append(ui.row(
            slot.title, href=_slot_href(slot, host), icon=SLOT_ICONS.get(slot.id, KIND_ICONS.get(slot.kind, "•")),
            desc=slot.description, end_html=end, external=external))
    ordered = [c for c in CATEGORY_ORDER if c in groups] + [c for c in groups if c not in CATEGORY_ORDER]
    banner, tiles = _overview(jobs, unit_tones)
    guide = ui.row_list([ui.row(
        "사용 설명서", href="/guide", icon="📖",
        desc="처음이라면 여기부터 — 무엇을 어디서 보고, 알림이 오면 무엇을 하는지 정리했습니다.",
        end_html=ui.pill("항상 최신", "info"))])
    sections = "".join(ui.section(cat, ui.row_list(groups[cat]), cat_tag=True) for cat in ordered)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    body = (
        '<h1>Quant VM</h1><p class="lead">이 서버에서 돌고 있는 앱과 자동 작업의 현재 상태입니다.</p>'
        f'{banner}{tiles}<div style="margin-top:14px">{guide}</div>{sections}'
        f'<p class="stamp">마지막 갱신 {now} · {REFRESH_SECONDS}초마다 자동 새로고침</p>'
    )
    return ui.page("개요", body, active="/", refresh=REFRESH_SECONDS)


def _stamp() -> str:
    return f'<p class="stamp">마지막 갱신 {datetime.now():%Y-%m-%d %H:%M:%S}</p>'


def render_research_page() -> str:
    body = f'<h1>AI 에이전트 연구</h1>{research_status.render_body(research_status.collect())}{_stamp()}'
    return ui.page("AI 에이전트 연구", body, crumbs=(("/", "개요"), ("", "연구·검증")), refresh=REFRESH_SECONDS)


def render_ops_page() -> str:
    body = ops_status.render_body(ops_status.job_health_summary(), ops_status.read_backup(),
                                  ops_status.system_info(), ops_status.collect_timers())
    return ui.page("운영 상태", f'<h1>운영 상태</h1>{body}{_stamp()}', active="/ops", refresh=REFRESH_SECONDS)


def render_status_page(slot: AppSlot) -> str:
    """엔진 상세 — 슬롯 전용 화면이 있으면 그것을, 없으면 공통 화면을 보여준다(hub/engine_pages.py)."""
    try:
        from hub import engine_pages
    except ImportError:
        engine_pages = None
    custom = engine_pages.render(slot) if engine_pages is not None else None
    if custom:
        return custom
    status = get_unit_status(slot.unit)
    pill_html, tone = _unit_pill(status)
    title = {"ok": "실행 중", "bad": "멈춰 있습니다", "muted": "상태를 읽을 수 없습니다"}[tone]
    rows = [("systemd 유닛", f"<code>{html.escape(slot.unit)}</code>"), ("상태", pill_html),
            ("시작 시각", html.escape(status.since) if status.since else "정보 없음")]
    try:
        extra = engine_status.render_engine_body(slot.id)
    except Exception:  # noqa: BLE001 - 보조 본문이 실패해도 상태 화면은 보여 준다
        extra = ""
    body = (f'<h1>{html.escape(slot.title)}</h1><p class="lead">{html.escape(slot.description)}</p>'
            f'{ui.verdict(tone, title, "화면이 없는 백그라운드 서비스입니다. 결과는 텔레그램 알림으로 옵니다.")}'
            f'{ui.kv_table(rows)}<div style="margin-top:18px">{extra}</div>{_stamp()}')
    return ui.page(slot.title, body, crumbs=(("/", "개요"), ("", slot.category)))


def render_process_confirm_page(key: str) -> str:
    body = engine_status.render_confirm_body(key)
    return ui.page("자동 잡 켜기 확인", body,
                   crumbs=(("/", "개요"), ("/status/scheduler", "백그라운드 스케줄러"), ("", "켜기 확인")))


def render_alpaca_page() -> str:
    body = f'<h1>Alpaca paper 검증</h1>{alpaca_status.render_body(alpaca_status.collect())}{_stamp()}'
    return ui.page("Alpaca paper 검증", body, crumbs=(("/", "개요"), ("", "연구·검증")), refresh=REFRESH_SECONDS)


def render_no_report_page(slot: AppSlot) -> str:
    body = (f'<h1>{html.escape(slot.title)}</h1>'
            '<div class="empty">아직 생성된 리포트가 없습니다. 예정된 시각에 자동으로 만들어지면 여기에 나타납니다.</div>')
    return ui.page(slot.title, body, crumbs=(("/", "개요"), ("", "리포트")))


def find_slot(slot_id: str, *, kind: str | None = None) -> AppSlot | None:
    for slot in SLOTS:
        if slot.id == slot_id and (kind is None or slot.kind == kind):
            return slot
    return None


def latest_report_path(slot: AppSlot) -> Path | None:
    if not slot.report_glob:
        return None
    matches = sorted(
        PROJECT_ROOT.glob(slot.report_glob), key=lambda p: p.stat().st_mtime, reverse=True
    )
    return matches[0] if matches else None


def _same_origin_post(headers) -> bool:
    """같은 사이트에서 보낸 폼 POST 인지(CSRF 방어). 로그인 쿠키가 SameSite=Lax 라 다른 사이트 POST 에는 원래 쿠키가 안 실리고,
    이 검사는 그 위의 한 겹이다.

    허브 응답에는 Referrer-Policy: no-referrer 가 붙어 있어서 브라우저가 폼 POST 의 Origin 을 실제 주소 대신 'null' 로
    보낸다(2026-09-25 VM 에서 '저장 → forbidden' 으로 드러남). 그래서 Origin 이 실제 주소일 때만 Host 와 비교하고,
    그 밖에는 브라우저가 붙이는 Sec-Fetch-Site 로 판단한다(cross-site·same-site 는 거부 — app. 하위 도메인도 막는다).
    """
    fetch_site = (headers.get("Sec-Fetch-Site") or "").lower()
    if fetch_site in ("cross-site", "same-site"):
        return False
    origin = (headers.get("Origin") or "").strip()
    host = (headers.get("Host") or "").strip()
    if origin and origin != "null" and host:
        return urlparse(origin).netloc == host
    return True


class HubRequestHandler(BaseHTTPRequestHandler):
    server_version = "QuantHub/1.0"

    def log_message(self, format: str, *args) -> None:  # noqa: A002 (BaseHTTPRequestHandler 시그니처)
        pass  # 접속 로그는 journalctl 대신 systemd 자체 stdout 캡처에 맡기지 않고 조용히 무시

    def _send_html(self, body: str, status: int = 200) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path not in ("/research/models", "/processes/toggle", "/processes/confirm"):
            self._send_html("not found", 404)
            return
        if not _same_origin_post(self.headers):
            self._send_html("forbidden", 403)
            return
        length = min(int(self.headers.get("Content-Length") or 0), 4096)
        form = parse_qs(self.rfile.read(length).decode("utf-8", "replace"))

        if path == "/processes/confirm":
            # 주문을 내는 잡은 클릭 한 번으로 켜지 않는다 — 확인 화면을 한 번 거친다(텔레그램과 같은 규칙).
            self._send_html(render_process_confirm_page((form.get("key") or [""])[0]))
            return

        if path == "/processes/toggle":
            key = (form.get("key") or [""])[0]
            enabled = (form.get("enabled") or ["0"])[0] == "1"
            confirmed = (form.get("confirm") or ["0"])[0] == "1"
            applied, _ = engine_status.apply_toggle(key, enabled, confirmed)
            if not applied and enabled and not confirmed:
                self._send_html(render_process_confirm_page(key))
                return
            self._redirect("/status/scheduler")
            return

        try:
            research_status.apply_model_form(form)
        except Exception:  # noqa: BLE001
            self._send_html("save failed", 500)
            return
        self._redirect("/research")

    def _redirect(self, location: str) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        host = (self.headers.get("Host") or "").split(":")[0] or "localhost"

        if path in ("/", ""):
            self._send_html(render_dashboard(host))
        elif path == "/login":
            self._send_html(LOGIN_PAGE)
        elif path == "/research":
            self._send_html(render_research_page())
        elif path == "/ops":
            self._send_html(render_ops_page())
        elif path in ("/guide", "/guide/"):
            from hub.guide import render_guide_page

            self._send_html(render_guide_page())
        elif path == "/alpaca":
            self._send_html(render_alpaca_page())
        elif path == "/healthz":
            self._send_html("ok")
        elif path.startswith("/status/"):
            slot = find_slot(path.removeprefix("/status/"))
            self._send_html(render_status_page(slot)) if slot else self._send_html("not found", 404)
        elif path.startswith("/reports/"):
            slot = find_slot(path.removeprefix("/reports/"), kind="report")
            if slot is None:
                self._send_html("not found", 404)
                return
            report_path = latest_report_path(slot)
            if report_path is None:
                self._send_html(render_no_report_page(slot))
            else:
                self._send_html(report_path.read_text(encoding="utf-8"))
        else:
            self._send_html("not found", 404)


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), HubRequestHandler)
    print(f"Quant hub listening on {HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
