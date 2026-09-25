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

HOST = "127.0.0.1"  # nginx를 거치지 않는 외부 직접 접속은 차단(방화벽에 별도 포트 개방 불필요)
PORT = 8000

PAGE_STYLE = """
<style>
  :root { color-scheme: dark; }
  body { background:#0f1115; color:#e6e6e6; font-family:-apple-system,"Segoe UI",sans-serif;
         margin:0; padding:2.5rem 1.5rem; }
  h1 { font-size:1.6rem; margin-bottom:.25rem; }
  p.subtitle { color:#9aa0a8; margin-top:0; margin-bottom:2rem; }
  .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(260px,1fr));
          gap:1rem; max-width:1100px; }
  .card { display:block; background:#181b21; border:1px solid #2a2e37; border-radius:12px;
          padding:1.1rem 1.3rem; text-decoration:none; color:inherit;
          transition:border-color .15s ease; }
  .card:hover { border-color:#4c7dff; }
  .card h2 { font-size:1.05rem; margin:0 0 .35rem; }
  .card p { color:#9aa0a8; font-size:.85rem; margin:0 0 .7rem; line-height:1.4; }
  .badge { display:inline-block; font-size:.72rem; padding:.15rem .55rem; border-radius:999px;
           font-weight:600; }
  .badge.active { background:#123d24; color:#4ade80; }
  .badge.inactive { background:#3d1212; color:#f87171; }
  .badge.unknown { background:#333844; color:#c9c9c9; }
  .kind { color:#5b6472; font-size:.72rem; text-transform:uppercase; letter-spacing:.05em;
          margin-left:.4rem; }
  a.back { color:#4c7dff; font-size:.85rem; text-decoration:none; }
  h2 { font-size:1.05rem; margin:1.6rem 0 .5rem; }
  h3.cat { font-size:.78rem; text-transform:uppercase; letter-spacing:.08em; color:#5b6472;
           margin:1.6rem 0 .6rem; max-width:1100px; }
  .stamp { color:#5b6472; font-size:.75rem; margin-top:1.5rem; }
  table { border-collapse:collapse; width:100%; max-width:760px; background:#181b21;
          border:1px solid #2a2e37; border-radius:10px; overflow:hidden; }
  th, td { text-align:left; padding:.55rem .8rem; border-bottom:1px solid #2a2e37; font-size:.85rem;
           vertical-align:top; }
  th { color:#9aa0a8; font-weight:500; width:38%; }
  small { color:#9aa0a8; }
</style>
"""

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


# 사용 설명서 진입 카드 — 슬롯(systemd 유닛)이 아니라 허브 자체 기능이라 SLOTS 와 별개로 항상 맨 앞에 둔다.
GUIDE_CARD = (
    '<a class="card" href="/guide" style="border-color:#4c7dff">'
    '<h2>📖 사용 설명서<span class="kind">guide</span></h2>'
    '<p>대시보드를 어떻게 쓰는지, 각 화면과 엔진 모듈이 무엇인지, 자동 잡과 알림은 어떻게 읽는지 정리했습니다. '
    '엔진이 업데이트되면 함께 갱신됩니다.</p>'
    '<span class="badge active">항상 최신</span></a>'
)


def _badge_html(status: UnitStatus) -> str:
    if not status.is_known:
        css, label = "unknown", "상태 확인 불가"
    elif status.is_active:
        css, label = "active", f"{status.active_state}/{status.sub_state}"
    else:
        css, label = "inactive", f"{status.active_state}/{status.sub_state}"
    return f'<span class="badge {css}">{html.escape(label)}</span>'


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


def _card(slot: AppSlot, host: str, badge: str) -> str:
    href = _slot_href(slot, host)
    target = ' target="_blank" rel="noopener"' if slot.kind in ("web", "link") else ""
    return (
        f'<a class="card" href="{html.escape(href)}"{target}>'
        f'<h2>{html.escape(slot.title)}<span class="kind">{html.escape(slot.kind)}</span></h2>'
        f'<p>{html.escape(slot.description)}</p>'
        f'{badge}'
        f'</a>'
    )


def _report_badge(slot: AppSlot) -> str:
    path = latest_report_path(slot)
    if path is None:
        return '<span class="badge unknown">아직 없음</span>'
    stamp = datetime.fromtimestamp(path.stat().st_mtime).strftime("%m-%d %H:%M")
    return f'<span class="badge active">최신 {stamp}</span>'


def render_dashboard(host: str) -> str:
    jobs = ops_status.job_health_summary()
    groups: dict[str, list[str]] = {}
    for slot in SLOTS:
        if slot.kind == "alpaca":
            badge = alpaca_status.card_badge()
        elif slot.kind == "report":
            badge = _report_badge(slot)
        elif slot.kind == "ops":
            badge = ops_status.jobs_badge(jobs)
        elif slot.kind == "research":
            badge = research_status.card_badge(research_status.collect())
        else:
            badge = _badge_html(get_unit_status(slot.unit))
            if slot.id == "scheduler":
                badge += " " + ops_status.jobs_badge(jobs)
        groups.setdefault(slot.category, []).append(_card(slot, host, badge))
    ordered = [c for c in CATEGORY_ORDER if c in groups] + [c for c in groups if c not in CATEGORY_ORDER]
    sections = "".join(
        f'<h3 class="cat">{html.escape(cat)}</h3><div class="grid">{"".join(groups[cat])}</div>' for cat in ordered
    )
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return (
        '<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<meta http-equiv="refresh" content="{REFRESH_SECONDS}">'
        f'<title>Quant VM 관제 센터</title>{PAGE_STYLE}</head><body>'
        '<a class="back" style="float:right" href="#" '
        'onclick="fetch(\'/_logout\',{method:\'POST\'}).then(function(){location.href=\'/login\'});return false">'
        '로그아웃</a><h1>Quant VM 관제 센터</h1>'
        '<p class="subtitle">이 서버에서 돌고 있는 앱과 엔진들. 카드를 누르면 해당 웹 또는 '
        '상태 화면으로 이동합니다.</p>'
        f'<div class="grid">{GUIDE_CARD}</div>'
        f'{sections}'
        f'<p class="stamp">마지막 갱신 {now} · {REFRESH_SECONDS}초마다 자동 새로고침</p>'
        '</body></html>'
    )


def render_research_page() -> str:
    return (
        '<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<meta http-equiv="refresh" content="{REFRESH_SECONDS}">'
        f'<title>AI 에이전트 연구</title>{PAGE_STYLE}</head><body>'
        '<p><a class="back" href="/">&larr; 관제 센터로</a></p><h1>AI 에이전트 연구</h1>'
        f'{research_status.render_body(research_status.collect())}'
        f'<p class="stamp">마지막 갱신 {datetime.now():%Y-%m-%d %H:%M:%S}</p></body></html>'
    )


def render_ops_page() -> str:
    body = ops_status.render_body(ops_status.job_health_summary(), ops_status.read_backup(),
                                  ops_status.system_info(), ops_status.collect_timers())
    return (
        '<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<meta http-equiv="refresh" content="{REFRESH_SECONDS}">'
        f'<title>운영 상태</title>{PAGE_STYLE}</head><body>'
        '<p><a class="back" href="/">&larr; 관제 센터로</a></p><h1>운영 상태</h1>'
        f'{body}<p class="stamp">마지막 갱신 {datetime.now():%Y-%m-%d %H:%M:%S}</p></body></html>'
    )


def render_status_page(slot: AppSlot) -> str:
    status = get_unit_status(slot.unit)
    since = html.escape(status.since) if status.since else "정보 없음"
    return (
        '<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        f'<title>{html.escape(slot.title)} 상태</title>{PAGE_STYLE}</head><body>'
        '<p><a class="back" href="/">&larr; 관제 센터로</a></p>'
        f'<h1>{html.escape(slot.title)}</h1>'
        f'<p class="subtitle">{html.escape(slot.description)}</p>'
        f'{_badge_html(status)}'
        f'<p style="margin-top:1rem;color:#9aa0a8;font-size:.85rem">'
        f'systemd unit: {html.escape(slot.unit)}<br>since: {since}</p>'
        f'<div style="margin-top:1.4rem">{engine_status.render_engine_body(slot.id)}</div>'
        '</body></html>'
    )


def render_process_confirm_page(key: str) -> str:
    return (
        '<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>자동 잡 켜기 확인</title>{PAGE_STYLE}</head><body>'
        '<p><a class="back" href="/status/scheduler">&larr; 백그라운드 스케줄러로</a></p>'
        f'{engine_status.render_confirm_body(key)}'
        '</body></html>'
    )


def render_alpaca_page() -> str:
    return (
        '<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>Alpaca paper 검증</title>{PAGE_STYLE}</head><body>'
        '<p><a class="back" href="/">&larr; 관제 센터로</a></p>'
        '<h1>Alpaca paper 검증</h1>'
        f'{alpaca_status.render_body(alpaca_status.collect())}'
        '</body></html>'
    )


def render_no_report_page(slot: AppSlot) -> str:
    return (
        '<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        f'<title>{html.escape(slot.title)}</title>{PAGE_STYLE}</head><body>'
        '<p><a class="back" href="/">&larr; 관제 센터로</a></p>'
        f'<h1>{html.escape(slot.title)}</h1>'
        '<p class="subtitle">아직 생성된 리포트가 없습니다.</p>'
        '</body></html>'
    )


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
