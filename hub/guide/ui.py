"""설명서 화면의 CSS·JS. 외부 CDN·프레임워크 없이 파일 안에 전부 들어 있다.

폰 화면(좁은 세로 화면)을 기준으로 만든다.
  - 본문은 탭(섹션)으로 나눠 한 번에 하나만 보여 준다. 첫 화면에서 전체 구조가 한눈에 보이고,
    원하는 곳까지 끝없이 스크롤하지 않아도 된다.
  - 검색창은 화면 위에 고정된다. 검색 중에는 탭과 상관없이 모든 섹션에서 일치하는 항목만 보여 준다.
  - JS 가 꺼져 있으면 모든 섹션이 그냥 펼쳐진 한 장의 문서로 보인다(설명이 사라지지 않는다).
"""

from __future__ import annotations

# <html class="js"> 를 최대한 빨리 달아, 섹션이 잠깐 전부 보였다가 접히는 깜빡임을 막는다.
JS_FLAG = '<script>document.documentElement.className="js";</script>'

GUIDE_STYLE = """
<style>
  :root { color-scheme: dark;
    --bg:#0f1115; --card:#181b21; --line:#2a2e37; --fg:#e6e6e6; --mut:#9aa0a8; --dim:#8a919c; --acc:#7aa2ff; }
  * { box-sizing:border-box; }
  body { background:var(--bg); color:var(--fg); margin:0; line-height:1.6;
         font-family:-apple-system,"Segoe UI","Noto Sans KR",sans-serif;
         -webkit-text-size-adjust:100%; overflow-wrap:anywhere; }
  .wrap { max-width:960px; margin:0 auto; padding:1rem 1rem 4rem; }
  a { color:var(--acc); }
  h1 { font-size:1.4rem; margin:.3rem 0 .2rem; }
  h2 { font-size:1.2rem; margin:1.2rem 0 .2rem; }
  h3 { font-size:.95rem; margin:1.2rem 0 .35rem; color:var(--mut); letter-spacing:.02em; }
  p { margin:.35rem 0; }
  .sub { color:var(--mut); margin:0 0 .6rem; font-size:.92rem; }
  .meta { color:var(--dim); font-size:.8rem; }
  .sec-lead { color:var(--mut); font-size:.86rem; margin:.1rem 0 .7rem; }

  /* 상단 고정 바: 검색 + 섹션 탭 */
  .bar { position:sticky; top:0; z-index:20; background:var(--bg); border-bottom:1px solid var(--line);
         margin:0 -1rem; padding:.5rem 1rem .4rem; }
  input.q { width:100%; padding:.7rem .85rem; background:var(--card); color:inherit; border:1px solid var(--line);
            border-radius:10px; font-size:1rem; }
  input.q:focus { outline:none; border-color:#3d5691; }
  nav.tabs { display:flex; gap:.35rem; overflow-x:auto; margin-top:.45rem; padding-bottom:.15rem;
             scrollbar-width:none; -webkit-overflow-scrolling:touch; }
  nav.tabs::-webkit-scrollbar { display:none; }
  nav.tabs a { flex:0 0 auto; background:var(--card); border:1px solid var(--line); border-radius:999px;
               padding:.35rem .75rem; text-decoration:none; font-size:.85rem; color:#cfd6e4; white-space:nowrap; }
  nav.tabs a .n { color:var(--dim); font-size:.76rem; margin-left:.3rem; }
  html.js nav.tabs a.on { background:#26304a; border-color:#3d5691; color:#dbe5ff; }
  #qinfo { display:none; color:var(--mut); font-size:.83rem; margin:.5rem 0 0; }
  html.js body.searching #qinfo { display:block; }

  /* 과업 중심 진입점 */
  .quick { display:flex; flex-wrap:wrap; gap:.4rem; margin:.7rem 0 .2rem; }
  .quick button { background:#141b2d; border:1px solid #2a3a63; color:#c8d6ff; border-radius:10px;
                  padding:.5rem .7rem; font-size:.86rem; font-family:inherit; cursor:pointer; text-align:left; }
  html:not(.js) .quick { display:none; }

  /* 섹션(탭 본문) */
  html.js main > section.sec { display:none; }
  html.js main > section.sec.on { display:block; }
  html.js body.searching main > section.sec { display:block; }
  html.js body.searching main > section.sec.empty { display:none; }
  /* 검색 중에는 묶음 제목·필터를 숨겨 결과만 남긴다 */
  html.js body.searching main h3, html.js body.searching .chips,
  html.js body.searching .quick, html.js body.searching .sec-lead { display:none; }
  html:not(.js) main > section.sec > h2 { margin-top:2rem; padding-top:.7rem; border-top:1px solid var(--line); }

  details.entry { background:var(--card); border:1px solid var(--line); border-radius:12px; margin:.5rem 0; }
  details.entry > summary { cursor:pointer; padding:.75rem .9rem; list-style:none; }
  details.entry > summary::-webkit-details-marker { display:none; }
  details.entry > summary .t { font-weight:600; }
  details.entry > summary .s { display:block; color:var(--mut); font-size:.85rem; margin-top:.15rem; }
  details.entry[open] > summary { border-bottom:1px solid var(--line); }
  details.entry:target { border-color:#3d5691; }
  .body { padding:.7rem .9rem .85rem; }
  .body h4 { font-size:.8rem; color:#8fb0ff; margin:.85rem 0 .2rem; letter-spacing:.02em; }
  .body h4:first-child { margin-top:.1rem; }
  .body ul, .body ol { margin:.2rem 0 .2rem 1.1rem; padding:0; }
  .body li { margin:.2rem 0; }

  .pill { display:inline-block; font-size:.7rem; padding:.1rem .5rem; border-radius:999px; margin-left:.4rem;
          background:#26304a; color:#a9c0ff; font-weight:600; vertical-align:middle; }
  .pill.ok { background:#123d24; color:#4ade80; } .pill.off { background:#3d1212; color:#f87171; }
  .pill.warn { background:#4a3a12; color:#fbbf24; } .pill.mute { background:#2a2e37; color:#c9c9c9; }
  .stale { background:#3a2e12; border:1px solid #6b5416; color:#fbbf24; border-radius:8px; padding:.4rem .7rem;
           font-size:.82rem; margin:.5rem 0; }
  .callout { background:#141b2d; border:1px solid #2a3a63; border-radius:10px; padding:.7rem .9rem; margin:.6rem 0; }

  /* 모듈 그룹 필터 */
  .chips { display:flex; flex-wrap:wrap; gap:.35rem; margin:.2rem 0 .6rem; }
  .chips button { background:var(--card); border:1px solid var(--line); color:#cfd6e4; border-radius:999px;
                  padding:.3rem .7rem; font-size:.82rem; font-family:inherit; cursor:pointer; }
  .chips button.on { background:#26304a; border-color:#3d5691; color:#dbe5ff; }
  html:not(.js) .chips { display:none; }

  table { width:100%; border-collapse:collapse; font-size:.86rem; }
  th, td { text-align:left; padding:.5rem .45rem; border-bottom:1px solid #22262e; vertical-align:top; }
  th { color:var(--dim); font-weight:600; font-size:.78rem; }
  .scroll { overflow-x:auto; }
  code { background:#0b0d11; border:1px solid var(--line); border-radius:6px; padding:.05rem .35rem; font-size:.85em; }
  pre { background:#0b0d11; border:1px solid var(--line); border-radius:8px; padding:.6rem .7rem; overflow-x:auto;
        font-size:.83rem; margin:.4rem 0; }
  .risk-쓰기, .risk-주문 { color:#fbbf24; }
  .totop { position:fixed; right:.9rem; bottom:.9rem; z-index:30; display:none; border:1px solid var(--line);
           background:#181b21e6; color:#cfd6e4; border-radius:999px; width:2.6rem; height:2.6rem; font-size:1rem;
           font-family:inherit; cursor:pointer; }
  html.js .totop.on { display:block; }

  /* 폰 가로폭: 표를 카드처럼 쌓아 가로 스크롤이 필요 없게 한다 */
  @media (max-width:620px) {
    table.stack thead { position:absolute; width:1px; height:1px; overflow:hidden; clip:rect(0 0 0 0); }
    table.stack tr { display:block; border:1px solid var(--line); border-radius:10px; background:var(--card);
                     padding:.45rem .6rem; margin:.4rem 0; }
    table.stack td { display:block; border:none; padding:.15rem 0; }
    table.stack td:before { content:attr(data-label); display:block; color:var(--dim); font-size:.72rem; }
    .scroll { overflow-x:visible; }
  }
</style>
"""

GUIDE_JS = """
<script>
(function(){
  var doc = document;
  var tabs = [].slice.call(doc.querySelectorAll('nav.tabs a'));
  var secs = [].slice.call(doc.querySelectorAll('main > section.sec'));
  var q = doc.getElementById('q');
  var qinfo = doc.getElementById('qinfo');
  var toTop = doc.getElementById('totop');

  function show(id, scroll){
    var found = false;
    secs.forEach(function(s){ var on = (s.id === 'sec-' + id); if (on) { found = true; } s.classList.toggle('on', on); });
    if (!found && secs.length) { secs[0].classList.add('on'); id = secs[0].id.slice(4); }
    tabs.forEach(function(a){ a.classList.toggle('on', a.getAttribute('data-sec') === id); });
    try { history.replaceState(null, '', '#' + id); } catch (e) {}
    if (scroll) { window.scrollTo(0, 0); }
    return id;
  }

  tabs.forEach(function(a){
    a.addEventListener('click', function(ev){ ev.preventDefault(); show(a.getAttribute('data-sec'), true); });
  });

  // 과업 진입점: 해당 섹션을 열고 그 항목을 펼쳐 준다.
  [].slice.call(doc.querySelectorAll('[data-goto]')).forEach(function(b){
    b.addEventListener('click', function(){
      if (q && q.value) { q.value = ''; filter(); }
      show(b.getAttribute('data-goto'), true);
      var target = doc.getElementById(b.getAttribute('data-open') || '');
      if (target) {
        target.open = true;
        setTimeout(function(){ target.scrollIntoView({block:'start'}); }, 0);
      }
    });
  });

  // 모듈 그룹 칩
  var chips = [].slice.call(doc.querySelectorAll('.chips button[data-group]'));
  chips.forEach(function(c){
    c.addEventListener('click', function(){
      var g = c.getAttribute('data-group');
      chips.forEach(function(o){ o.classList.toggle('on', o === c); });
      [].slice.call(doc.querySelectorAll('#sec-modules [data-group-of]')).forEach(function(el){
        el.style.display = (g === '*' || el.getAttribute('data-group-of') === g) ? '' : 'none';
      });
    });
  });

  function filter(){
    var t = q ? q.value.trim().toLowerCase() : '';
    var searching = t.length > 0;
    doc.body.classList.toggle('searching', searching);
    var hits = 0;
    [].slice.call(doc.querySelectorAll('details.entry')).forEach(function(d){
      var hit = !searching || d.textContent.toLowerCase().indexOf(t) !== -1;
      d.style.display = hit ? '' : 'none';
      if (searching) { d.open = hit; if (hit) { hits++; } }
    });
    [].slice.call(doc.querySelectorAll('tr.row')).forEach(function(r){
      var hit = !searching || r.textContent.toLowerCase().indexOf(t) !== -1;
      r.style.display = hit ? '' : 'none';
      if (searching && hit) { hits++; }
    });
    if (searching) {
      secs.forEach(function(s){
        var alive = [].slice.call(s.querySelectorAll('details.entry, tr.row')).some(function(el){
          return el.style.display !== 'none';
        });
        s.classList.toggle('empty', !alive);
      });
      if (qinfo) {
        qinfo.textContent = hits
          ? ('"' + q.value.trim() + '" 검색 결과 ' + hits + '건 (모든 섹션에서 찾았습니다)')
          : ('"' + q.value.trim() + '" 에 해당하는 설명이 없습니다. 더 짧은 말로 찾아 보세요.');
      }
    } else {
      secs.forEach(function(s){ s.classList.remove('empty'); });
    }
  }
  if (q) {
    q.addEventListener('input', filter);
    q.addEventListener('search', filter);
  }

  if (toTop) {
    toTop.addEventListener('click', function(){ window.scrollTo(0, 0); });
    window.addEventListener('scroll', function(){ toTop.classList.toggle('on', window.scrollY > 500); });
  }

  show((location.hash || '').replace('#', '') || 'start', false);
  window.addEventListener('hashchange', function(){ show((location.hash || '').replace('#', ''), true); });
})();
</script>
"""
