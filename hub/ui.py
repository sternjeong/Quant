"""관제 센터 공통 디자인 시스템 — 모든 허브 페이지가 같은 모양·같은 부품을 쓰게 한다.

참고한 방향(2026-09-25, 폰 크기로 실제 화면을 보고 정함):
- 상태 페이지(GitHub Status, Better Stack): 맨 위의 한 줄 판정, 서비스별 한 줄 행 + 상태 알약, N일 가동 막대.
- 개발 도구 대시보드(Linear, Vercel): 거의 검은 배경, 얇은 테두리, 절제된 색, 또렷한 글꼴, 넉넉한 여백.

원칙:
- 폰이 기본 화면이다(사용자는 폰으로만 본다). 가로 스크롤이 생기면 안 되고, 터치 영역은 44px 이상.
- 색은 상태를 뜻할 때만 쓴다: 초록=정상, 노랑=주의, 빨강=문제, 회색=알 수 없음/꺼짐. 장식용 색은 파란 강조 하나.
- 텍스트 인자는 escape 한다. 이미 escape 된 HTML 조각을 받는 인자는 이름이 *_html 이다.
- 표준 라이브러리만 쓴다(허브는 stdlib 서버). 글꼴 CSS 하나만 CDN 에서 받고, 실패해도 시스템 글꼴로 보인다.

기존 페이지 본문(ops_status, alpaca_status, research_status 등)이 쓰는 기본 요소(table, h2, .badge, .subtitle, small)도
여기서 새 모양으로 스타일한다 — 그래서 그 모듈들은 코드를 바꾸지 않아도 새 디자인을 입는다.
"""

from __future__ import annotations

import html
from typing import Iterable, Optional, Sequence

E = html.escape

FONT_CSS = "https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css"

# 톤: ok(정상) warn(주의) bad(문제) muted(꺼짐/알 수 없음) info(정보/강조)
TONES = ("ok", "warn", "bad", "muted", "info")

CSS = """
:root{
  color-scheme:dark;
  --bg:#08090a; --surface:#0f1012; --surface-2:#16171a; --surface-3:#1d1e22;
  --border:#232428; --border-2:#2e3035;
  --text:#f4f4f5; --text-2:#a4a6ad; --text-3:#6c6f78;
  --accent:#7c8cff; --accent-soft:rgba(124,140,255,.12);
  --ok:#3ecf8e; --ok-soft:rgba(62,207,142,.12);
  --warn:#f5a524; --warn-soft:rgba(245,165,36,.13);
  --bad:#f0616d; --bad-soft:rgba(240,97,109,.13);
  --muted:#8b8e96; --muted-soft:rgba(139,142,150,.12);
  --info:#7c8cff; --info-soft:rgba(124,140,255,.12);
  --radius:14px; --radius-sm:10px;
  --mono:ui-monospace,"JetBrains Mono","SFMono-Regular",Menlo,Consolas,monospace;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--text);line-height:1.55;
  font-family:"Pretendard Variable",Pretendard,-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Noto Sans KR","Segoe UI",sans-serif;
  font-feature-settings:"tnum";-webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}
code,.mono{font-family:var(--mono);font-size:.86em}
code{background:var(--surface-2);border:1px solid var(--border);border-radius:6px;padding:.05rem .35rem}
pre{font-family:var(--mono);font-size:.82rem;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-sm);
  padding:.75rem .9rem;overflow-x:auto;margin:.5rem 0}
.topbar{position:sticky;top:0;z-index:10;background:rgba(8,9,10,.82);backdrop-filter:saturate(1.4) blur(12px);
  -webkit-backdrop-filter:saturate(1.4) blur(12px);border-bottom:1px solid var(--border)}
.topbar-in{max-width:980px;margin:0 auto;padding:0 16px;height:56px;display:flex;align-items:center;gap:12px}
.brand{display:flex;align-items:center;gap:10px;font-weight:650;letter-spacing:-.01em;white-space:nowrap}
.logo{width:28px;height:28px;border-radius:8px;display:grid;place-items:center;font-weight:800;font-size:.9rem;
  background:linear-gradient(135deg,#8b9bff 0%,#5a6cf0 100%);color:#fff;box-shadow:0 0 0 1px rgba(255,255,255,.08) inset}
.nav{display:flex;gap:2px;margin-left:auto;overflow-x:auto;scrollbar-width:none}
.nav::-webkit-scrollbar{display:none}
.nav a{padding:.45rem .65rem;border-radius:8px;color:var(--text-2);font-size:.87rem;white-space:nowrap}
.nav a:hover{color:var(--text);background:var(--surface-2)}
.nav a.on{color:var(--text);background:var(--surface-3)}
.wrap{max-width:980px;margin:0 auto;padding:20px 16px 72px}
.crumb{font-size:.85rem;color:var(--text-3);margin:4px 0 12px}
.crumb a{color:var(--text-2)} .crumb a:hover{color:var(--text)}
h1{font-size:1.6rem;line-height:1.25;letter-spacing:-.025em;margin:.2rem 0 .35rem;font-weight:700}
.lead,p.subtitle{color:var(--text-2);margin:0 0 1.25rem;font-size:.98rem}
h2{font-size:1.05rem;letter-spacing:-.01em;margin:2rem 0 .7rem;font-weight:650}
h3.cat,.sec-title{font-size:.74rem;font-weight:600;letter-spacing:.09em;text-transform:uppercase;color:var(--text-3);
  margin:1.9rem 0 .6rem}
p{margin:.4rem 0} small,.meta{color:var(--text-3);font-size:.8rem}
.stamp{color:var(--text-3);font-size:.78rem;margin-top:2.2rem;text-align:center}
.muted{color:var(--text-2)}
.verdict{display:flex;gap:14px;align-items:center;padding:18px;border-radius:var(--radius);border:1px solid var(--border);
  background:var(--surface);margin:6px 0 14px}
.verdict .ic{flex:0 0 auto;width:42px;height:42px;border-radius:50%;display:grid;place-items:center;font-size:1.25rem;font-weight:800}
.verdict .t{font-size:1.12rem;font-weight:700;letter-spacing:-.015em}
.verdict .s{color:var(--text-2);font-size:.88rem;margin-top:2px}
.verdict.ok{border-color:rgba(62,207,142,.35);background:linear-gradient(180deg,rgba(62,207,142,.08),var(--surface) 70%)}
.verdict.ok .ic{background:var(--ok-soft);color:var(--ok);box-shadow:0 0 0 6px rgba(62,207,142,.06)}
.verdict.warn{border-color:rgba(245,165,36,.35);background:linear-gradient(180deg,rgba(245,165,36,.08),var(--surface) 70%)}
.verdict.warn .ic{background:var(--warn-soft);color:var(--warn)}
.verdict.bad{border-color:rgba(240,97,109,.4);background:linear-gradient(180deg,rgba(240,97,109,.09),var(--surface) 70%)}
.verdict.bad .ic{background:var(--bad-soft);color:var(--bad)}
.verdict.muted .ic{background:var(--muted-soft);color:var(--muted)}
.stats{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin:0 0 6px}
@media(min-width:720px){.stats{grid-template-columns:repeat(4,minmax(0,1fr))}}
.stat{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-sm);padding:12px 14px;min-width:0}
.stat .k{font-size:.76rem;color:var(--text-3);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.stat .v{font-size:1.28rem;font-weight:700;letter-spacing:-.02em;margin-top:2px;font-variant-numeric:tabular-nums}
.stat .d{font-size:.76rem;color:var(--text-2);margin-top:1px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.stat .v.ok{color:var(--ok)} .stat .v.warn{color:var(--warn)} .stat .v.bad{color:var(--bad)} .stat .v.muted{color:var(--muted)}
.list{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);overflow:hidden}
.row{display:flex;align-items:center;gap:12px;padding:14px;min-height:60px;border-top:1px solid var(--border)}
.list > .row:first-child{border-top:0}
a.row:hover{background:var(--surface-2)} a.row:active{background:var(--surface-3)}
.row .ico{flex:0 0 auto;width:36px;height:36px;border-radius:10px;display:grid;place-items:center;background:var(--surface-3);
  font-size:1.05rem;border:1px solid var(--border)}
.row .body{flex:1 1 auto;min-width:0}
.row .ttl{font-weight:600;font-size:.97rem;letter-spacing:-.01em;display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.row .dsc{color:var(--text-2);font-size:.84rem;margin-top:1px;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
.row .end{flex:0 0 auto;display:flex;align-items:center;gap:6px;max-width:48%;flex-wrap:wrap;justify-content:flex-end}
.row .chev{color:var(--text-3);font-size:1.2rem;margin-left:2px}
.row .ext{color:var(--text-3);font-size:.85rem}
.pill,.badge{display:inline-flex;align-items:center;gap:6px;font-size:.74rem;font-weight:600;line-height:1;
  padding:.36rem .6rem;border-radius:999px;white-space:nowrap;background:var(--muted-soft);color:var(--text-2)}
.pill::before,.badge::before{content:"";width:6px;height:6px;border-radius:50%;background:currentColor;flex:0 0 auto}
.pill.ok,.badge.active{background:var(--ok-soft);color:var(--ok)}
.pill.warn{background:var(--warn-soft);color:var(--warn)}
.pill.bad,.badge.inactive{background:var(--bad-soft);color:var(--bad)}
.pill.muted,.badge.unknown{background:var(--muted-soft);color:var(--muted)}
.pill.info{background:var(--info-soft);color:var(--info)}
.pill.plain::before{display:none}
.strip{display:flex;gap:2px;align-items:stretch;height:26px;margin:8px 0 4px}
.strip i{flex:1 1 0;border-radius:2px;background:var(--surface-3);min-width:2px}
.strip i.ok{background:#2fb57a} .strip i.warn{background:var(--warn)} .strip i.bad{background:var(--bad)}
.strip i.muted{background:#2a2c31} .strip i.none{background:var(--surface-3);opacity:.55}
.strip-legend{display:flex;justify-content:space-between;color:var(--text-3);font-size:.74rem}
.panel{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:16px}
.panel + .panel{margin-top:10px}
.callout{display:flex;gap:12px;align-items:flex-start;background:var(--accent-soft);border:1px solid rgba(124,140,255,.28);
  border-radius:var(--radius);padding:14px 16px;margin:10px 0}
.callout .ico{font-size:1.2rem;line-height:1.4}
.callout.warn{background:var(--warn-soft);border-color:rgba(245,165,36,.3)}
.callout.bad{background:var(--bad-soft);border-color:rgba(240,97,109,.35)}
.empty{color:var(--text-2);text-align:center;padding:26px 16px;border:1px dashed var(--border-2);border-radius:var(--radius)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:10px}
.card{display:block;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:16px}
.card:hover{border-color:var(--border-2);background:var(--surface-2)}
.card h2{font-size:1rem;margin:0 0 .3rem} .card p{color:var(--text-2);font-size:.86rem;margin:0 0 .7rem}
.kind{color:var(--text-3);font-size:.7rem;text-transform:uppercase;letter-spacing:.06em;margin-left:.4rem}
a.back{color:var(--text-2);font-size:.85rem}
.tbl,table{width:100%;border-collapse:separate;border-spacing:0;background:var(--surface);border:1px solid var(--border);
  border-radius:var(--radius-sm);overflow:hidden;font-size:.86rem}
th,td{text-align:left;padding:.62rem .8rem;border-bottom:1px solid var(--border);vertical-align:top}
tr:last-child th,tr:last-child td{border-bottom:0}
th{color:var(--text-2);font-weight:500;width:38%} thead th{width:auto;font-size:.76rem;color:var(--text-3);background:var(--surface-2)}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch;border-radius:var(--radius-sm)}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;min-height:40px;padding:0 14px;border-radius:10px;
  background:var(--surface-3);border:1px solid var(--border-2);color:var(--text);font-weight:600;font-size:.88rem;cursor:pointer}
.btn:hover{background:#25262b} .btn.primary{background:var(--text);color:#0b0b0c;border-color:transparent}
input,select,textarea{font:inherit;color:inherit}
@media(max-width:420px){ h1{font-size:1.42rem} .row{padding:13px 12px} .row .end{max-width:44%} }
"""

NAV = (("/", "개요"), ("/ops", "운영"), ("/guide", "설명서"))

_LOGOUT_JS = "fetch('/_logout',{method:'POST'}).then(function(){location.href='/login'});return false"


def pill(text: str, tone: str = "muted", *, plain: bool = False) -> str:
    tone = tone if tone in TONES else "muted"
    return f'<span class="pill {tone}{" plain" if plain else ""}">{E(str(text))}</span>'


def verdict(tone: str, title: str, subtitle: str = "") -> str:
    icon = {"ok": "✓", "warn": "!", "bad": "!", "muted": "?", "info": "i"}.get(tone, "?")
    sub = f'<div class="s">{E(subtitle)}</div>' if subtitle else ""
    return (f'<div class="verdict {E(tone)}" role="status"><div class="ic" aria-hidden="true">{icon}</div>'
            f'<div><div class="t">{E(title)}</div>{sub}</div></div>')


def stat(label: str, value: str, detail: str = "", tone: str = "") -> str:
    tone_cls = f" {tone}" if tone in TONES else ""
    det = f'<div class="d">{E(detail)}</div>' if detail else ""
    return f'<div class="stat"><div class="k">{E(label)}</div><div class="v{tone_cls}">{E(value)}</div>{det}</div>'


def stats(items_html: Iterable[str]) -> str:
    return f'<div class="stats">{"".join(items_html)}</div>'


def row(title: str, *, href: Optional[str] = None, icon: str = "", desc: str = "", end_html: str = "",
        external: bool = False, title_extra_html: str = "") -> str:
    """서비스·잡 한 줄. href 가 있으면 누를 수 있는 행이 된다. external 이면 새 탭(↗ 표시)."""
    ico = f'<div class="ico" aria-hidden="true">{E(icon)}</div>' if icon else ""
    dsc = f'<div class="dsc">{E(desc)}</div>' if desc else ""
    if external:
        tail = '<span class="ext" aria-hidden="true">↗</span>'
    elif href:
        tail = '<span class="chev" aria-hidden="true">›</span>'
    else:
        tail = ""
    inner = (f'{ico}<div class="body"><div class="ttl">{E(title)}{title_extra_html}</div>{dsc}</div>'
             f'<div class="end">{end_html}{tail}</div>')
    if href:
        target = ' target="_blank" rel="noopener"' if external else ""
        return f'<a class="row" href="{E(href)}"{target}>{inner}</a>'
    return f'<div class="row">{inner}</div>'


def row_list(rows_html: Iterable[str]) -> str:
    rows_html = list(rows_html)
    if not rows_html:
        return '<div class="empty">표시할 항목이 없습니다.</div>'
    return f'<div class="list">{"".join(rows_html)}</div>'


def section(title: str, body_html: str, *, cat_tag: bool = False) -> str:
    """cat_tag=True 면 대시보드 카테고리 제목(<h3 class="cat">)을 쓴다 — 기존 테스트·앵커 호환."""
    head = f'<h3 class="cat">{E(title)}</h3>' if cat_tag else f'<h2>{E(title)}</h2>'
    return head + body_html


def strip(cells: Sequence[tuple[str, str]], left: str = "", right: str = "") -> str:
    """가동 막대. cells=[(tone, 툴팁), ...] 오래된 것 → 최근 순서. tone: ok/warn/bad/muted/none."""
    allowed = ("ok", "warn", "bad", "muted", "none")
    bars = "".join(f'<i class="{t if t in allowed else "none"}" title="{E(tip)}"></i>' for t, tip in cells)
    legend = f'<div class="strip-legend"><span>{E(left)}</span><span>{E(right)}</span></div>' if (left or right) else ""
    return f'<div class="strip" role="img" aria-label="{E(right or "실행 이력")}">{bars}</div>{legend}'


def callout(text_html: str, *, icon: str = "💡", tone: str = "") -> str:
    tone_cls = f" {tone}" if tone in ("warn", "bad") else ""
    return f'<div class="callout{tone_cls}"><div class="ico" aria-hidden="true">{E(icon)}</div><div>{text_html}</div></div>'


def kv_table(rows: Iterable[tuple[str, str]]) -> str:
    """(이름, 값 HTML) 목록. 이름은 escape, 값은 이미 escape 된 HTML."""
    body = "".join(f"<tr><th>{E(k)}</th><td>{v}</td></tr>" for k, v in rows)
    return f'<table class="tbl">{body}</table>'


def page(title: str, body_html: str, *, active: str = "", crumbs: Sequence[tuple[str, str]] = (),
         refresh: Optional[int] = None, head_extra: str = "", show_nav: bool = True) -> str:
    """페이지 전체. crumbs=[(href, 이름)] 은 제목 위 경로(예: 개요 › 운영). href 가 빈 문자열이면 링크 없음."""
    refresh_meta = f'<meta http-equiv="refresh" content="{int(refresh)}">' if refresh else ""
    nav = ""
    if show_nav:
        links = "".join(f'<a href="{E(h)}" class="{"on" if h == active else ""}">{E(t)}</a>' for h, t in NAV)
        nav = f'<nav class="nav" aria-label="관제 센터 메뉴">{links}<a href="#" onclick="{_LOGOUT_JS}">로그아웃</a></nav>'
    crumb = ""
    if crumbs:
        parts = " › ".join(f'<a href="{E(h)}">{E(t)}</a>' if h else E(t) for h, t in crumbs)
        crumb = f'<div class="crumb">{parts}</div>'
    return (
        '<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
        '<meta name="robots" content="noindex"><meta name="theme-color" content="#08090a">'
        f'{refresh_meta}<title>{E(title)} · Quant 관제 센터</title>'
        f'<link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin><link rel="stylesheet" href="{FONT_CSS}">'
        f'<style>{CSS}</style>{head_extra}</head><body>'
        '<header class="topbar"><div class="topbar-in">'
        '<a class="brand" href="/"><span class="logo">Q</span><span>관제 센터</span></a>'
        f'{nav}</div></header>'
        f'<main class="wrap">{crumb}{body_html}</main></body></html>'
    )


def relative_age(hours: Optional[float]) -> str:
    """'3시간 전', '2일 전' 같은 사람용 표시."""
    if hours is None:
        return "기록 없음"
    if hours < 1:
        return f"{max(1, int(hours * 60))}분 전"
    if hours < 48:
        return f"{int(hours)}시간 전"
    return f"{int(hours // 24)}일 전"
