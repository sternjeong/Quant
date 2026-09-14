(function(){
  "use strict";
  var DATA = JSON.parse(document.getElementById('report-data').textContent);
  var NS = 'http://www.w3.org/2000/svg';

  function el(tag, attrs, children){
    var e = document.createElementNS(NS, tag);
    if(attrs){ for(var k in attrs){ e.setAttribute(k, attrs[k]); } }
    if(children){ children.forEach(function(c){ if(c) e.appendChild(c); }); }
    return e;
  }
  function txt(x,y,str,cls,anchor){
    var t = el('text', {x:x, y:y, class: cls||''});
    if(anchor) t.setAttribute('text-anchor', anchor);
    t.textContent = str;
    return t;
  }
  function svgRoot(w,h,extra){
    var attrs = {viewBox: '0 0 '+w+' '+h, class:'chart-svg'};
    if(extra) for(var k in extra) attrs[k]=extra[k];
    return el('svg', attrs);
  }
  function colorVar(name){
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }
  function fmtSigned(v, digits){
    digits = (digits===undefined)?1:digits;
    var s = Math.abs(v).toFixed(digits);
    return (v>=0? '+':'-') + s;
  }
  function fmtPlain(v, digits){
    digits = (digits===undefined)?1:digits;
    return v.toFixed(digits);
  }

  var tooltip = document.getElementById('tooltip');
  function showTip(evt, html){
    tooltip.innerHTML = html;
    tooltip.style.display = 'block';
    positionTip(evt);
  }
  function positionTip(evt){
    var pad = 16;
    tooltip.style.left = (evt.clientX + pad) + 'px';
    tooltip.style.top = (evt.clientY + pad) + 'px';
    requestAnimationFrame(function(){
      var r = tooltip.getBoundingClientRect();
      var x = evt.clientX + pad, y = evt.clientY + pad;
      if(r.right > window.innerWidth - 8) x = evt.clientX - pad - r.width;
      if(r.bottom > window.innerHeight - 8) y = evt.clientY - pad - r.height;
      tooltip.style.left = x + 'px';
      tooltip.style.top = y + 'px';
    });
  }
  function hideTip(){ tooltip.style.display = 'none'; }

  function niceStep(rawStep){
    var mag = Math.pow(10, Math.floor(Math.log10(Math.abs(rawStep))));
    var norm = rawStep/mag;
    var step;
    if(norm < 1.5) step = 1*mag; else if(norm < 3) step = 2*mag; else if(norm < 7) step = 5*mag; else step = 10*mag;
    return step;
  }
  function niceTicks(min, max, count){
    var range = (max-min) || 1;
    var step = niceStep(range/count);
    var start = Math.ceil(min/step)*step;
    var ticks = [];
    for(var v=start; v<=max+1e-9; v+=step){ ticks.push(Math.round(v*10000)/10000); }
    if(ticks.length===0) ticks.push(0);
    return ticks;
  }

  // ---------------------------------------------------------------
  // 1) Diverging bar — 종목별 초과 CAGR
  // ---------------------------------------------------------------
  function renderDivergingBar(containerId, items){
    var container = document.getElementById(containerId);
    var W = 760, rowH = 15, gap = 2.4;
    var marginTop = 10, marginBottom = 30, labelW = 92, rightPad = 56;
    var H = marginTop + marginBottom + items.length*(rowH+gap);
    var plotW = W - labelW - rightPad;

    var values = items.map(function(d){ return d.excess_cagr; });
    var min = Math.min(0, Math.min.apply(null, values));
    var max = Math.max(0, Math.max.apply(null, values));
    var padFrac = 0.08;
    var span = (max-min) || 1;
    min -= span*padFrac; max += span*padFrac;

    function xScale(v){ return labelW + (v-min)/(max-min)*plotW; }
    var zeroX = xScale(0);

    var svg = svgRoot(W,H);

    var ticks = niceTicks(min, max, 5);
    ticks.forEach(function(t){
      var x = xScale(t);
      svg.appendChild(el('line',{x1:x,x2:x,y1:marginTop-2,y2:H-marginBottom+2,class:'grid-line'}));
      svg.appendChild(txt(x, H-marginBottom+16, (t>0?'+':'')+t.toFixed(0)+'%p', 'tick-label', 'middle'));
    });
    svg.appendChild(el('line',{x1:zeroX,x2:zeroX,y1:marginTop-2,y2:H-marginBottom+2,class:'axis-line'}));

    var blue = colorVar('--blue'), red = colorVar('--red');

    items.forEach(function(d,i){
      var y = marginTop + i*(rowH+gap);
      var v = d.excess_cagr;
      var x1 = xScale(Math.min(0,v)), x2 = xScale(Math.max(0,v));
      var color = v>=0 ? blue : red;
      var g = el('g', {});
      var barY = y + (rowH-9)/2;
      var rect = el('rect', {x:x1, y:barY, width:Math.max(1,x2-x1), height:9, rx:2, ry:2, fill:color, class:'mark'});
      g.appendChild(rect);
      var isIndex = d.sector === 'S&P500';
      g.appendChild(txt(labelW-8, y+rowH-4, d.ticker, 'cat-label'+(isIndex?'':''), 'end'));
      var labelX = v>=0 ? x2+5 : x1-5;
      var anchor = v>=0 ? 'start' : 'end';
      g.appendChild(txt(labelX, y+rowH-4, fmtSigned(v,1), 'bar-label', anchor));

      g.addEventListener('mousemove', function(evt){
        showTip(evt,
          '<div class="tt-title">'+d.ticker+' <span style="font-weight:400;color:inherit;opacity:.7">· '+d.sector+'</span></div>'+
          '<div class="tt-row"><span>전략 CAGR</span><span class="tt-val">'+fmtPlain(d.cagr)+'%</span></div>'+
          '<div class="tt-row"><span>매수보유 CAGR</span><span class="tt-val">'+fmtPlain(d.bh_cagr)+'%</span></div>'+
          '<div class="tt-row"><span>초과 CAGR</span><span class="tt-val" style="color:'+color+'">'+fmtSigned(v,2)+'%p</span></div>'
        );
      });
      g.addEventListener('mouseleave', hideTip);
      svg.appendChild(g);
    });

    container.innerHTML = '';
    container.appendChild(svg);
  }

  // ---------------------------------------------------------------
  // 2) Dumbbell — 섹터별 base -> value (+ 참조선 ref)
  // ---------------------------------------------------------------
  function renderDumbbell(containerId, rows, opts){
    var container = document.getElementById(containerId);
    var W = 760, rowH = 34;
    var marginTop = 14, marginBottom = 30, labelW = 118, rightPad = 60;
    var H = marginTop + marginBottom + rows.length*rowH;
    var plotW = W - labelW - rightPad;

    var allVals = [];
    rows.forEach(function(r){ allVals.push(r.base, r.value, r.ref); });
    var min = Math.min.apply(null, allVals), max = Math.max.apply(null, allVals);
    var span = (max-min)||1;
    min -= span*0.12; max += span*0.12;

    function xScale(v){ return labelW + (v-min)/(max-min)*plotW; }

    var svg = svgRoot(W,H);
    var ticks = niceTicks(min,max,5);
    ticks.forEach(function(t){
      var x = xScale(t);
      svg.appendChild(el('line',{x1:x,x2:x,y1:marginTop-4,y2:H-marginBottom+2,class:'grid-line'}));
      svg.appendChild(txt(x, H-marginBottom+16, t.toFixed(0)+(opts.unit||''), 'tick-label','middle'));
    });

    var orange = colorVar('--orange'), blue = colorVar('--blue'), aqua = colorVar('--aqua');

    rows.forEach(function(r,i){
      var y = marginTop + i*rowH + rowH/2;
      var xBase = xScale(r.base), xVal = xScale(r.value), xRef = xScale(r.ref);
      var g = el('g', {});
      g.appendChild(txt(labelW-10, y+4, r.label, 'cat-label', 'end'));
      g.appendChild(el('line',{x1:xBase,x2:xVal,y1:y,y2:y,stroke:colorVar('--ink-muted'),'stroke-width':2}));
      // 참조선(S&P500 벤치마크) 작은 다이아몬드
      g.appendChild(el('rect',{x:xRef-3.5,y:y-3.5,width:7,height:7,fill:aqua,transform:'rotate(45 '+xRef+' '+y+')','class':'mark'}));
      var dotBase = el('circle',{cx:xBase,cy:y,r:5,fill:opts.surfaceFill||'var(--chart-surface)',stroke:orange,'stroke-width':2.5,class:'mark'});
      var dotVal = el('circle',{cx:xVal,cy:y,r:5.5,fill:blue,stroke:'var(--chart-surface)','stroke-width':1.5,class:'mark'});
      g.appendChild(dotBase); g.appendChild(dotVal);
      var labelX = xVal + (xVal>=xBase? 9 : -9);
      var anchor = xVal>=xBase ? 'start':'end';
      g.appendChild(txt(labelX, y+4, fmtPlain(r.value,1)+(opts.unit||''), 'bar-label', anchor));

      [dotBase,dotVal].forEach(function(dot, idx){
        dot.addEventListener('mousemove', function(evt){
          showTip(evt,
            '<div class="tt-title">'+r.label+'</div>'+
            '<div class="tt-row"><span><span class="tt-key" style="background:'+blue+'"></span>코스톨라니 전략</span><span class="tt-val">'+fmtPlain(r.value,2)+(opts.unit||'')+'</span></div>'+
            '<div class="tt-row"><span><span class="tt-key" style="background:'+orange+'"></span>매수보유</span><span class="tt-val">'+fmtPlain(r.base,2)+(opts.unit||'')+'</span></div>'+
            '<div class="tt-row"><span><span class="tt-key" style="background:'+aqua+'"></span>S&amp;P500 매수보유</span><span class="tt-val">'+fmtPlain(r.ref,2)+(opts.unit||'')+'</span></div>'
          );
        });
        dot.addEventListener('mouseleave', hideTip);
      });
      svg.appendChild(g);
    });

    container.innerHTML='';
    container.appendChild(svg);
  }

  // ---------------------------------------------------------------
  // 3) Equity curve (log scale) + crosshair tooltip
  // ---------------------------------------------------------------
  var LOG_TICK_CANDIDATES = [10,20,30,50,70,100,150,200,300,500,700,1000,1500,2000,3000,5000,7000,10000,15000,20000,30000,50000,70000,100000];

  function renderEquityLine(containerId, series, opts){
    opts = opts || {};
    var container = document.getElementById(containerId);
    var W = opts.width || 360, H = opts.height || 220;
    var marginTop = 10, marginBottom = 24, marginLeft = opts.marginLeft || 48, marginRight = 10;
    var plotW = W - marginLeft - marginRight, plotH = H - marginTop - marginBottom;

    var all = series.strategy.concat(series.bh, series.bench).filter(function(v){return v>0;});
    var min = Math.min.apply(null, all), max = Math.max.apply(null, all);
    var logMin = Math.log10(min*0.92), logMax = Math.log10(max*1.08);

    function yScale(v){ return marginTop + plotH - (Math.log10(v)-logMin)/(logMax-logMin)*plotH; }
    var n = series.dates.length;
    function xScale(i){ return marginLeft + i/(n-1)*plotW; }

    var svg = svgRoot(W,H);

    var ticks = LOG_TICK_CANDIDATES.filter(function(t){ return t>=Math.pow(10,logMin) && t<=Math.pow(10,logMax); });
    ticks.forEach(function(t){
      var y = yScale(t);
      svg.appendChild(el('line',{x1:marginLeft,x2:W-marginRight,y1:y,y2:y,class:'grid-line'}));
      var label = t>=1000 ? (t/1000)+'k' : String(t);
      svg.appendChild(txt(marginLeft-6, y+3, label, 'tick-label', 'end'));
    });
    svg.appendChild(el('line',{x1:marginLeft,x2:marginLeft,y1:marginTop,y2:H-marginBottom,class:'axis-line'}));

    function pathFor(arr){
      var d = '';
      for(var i=0;i<arr.length;i++){
        var x = xScale(i), y = yScale(arr[i]);
        d += (i===0?'M':'L') + x.toFixed(2) + ' ' + y.toFixed(2) + ' ';
      }
      return d;
    }
    var seriesDefs = [
      {key:'bench', color: colorVar('--aqua')},
      {key:'bh', color: colorVar('--orange')},
      {key:'strategy', color: colorVar('--blue')}
    ];
    seriesDefs.forEach(function(sd){
      svg.appendChild(el('path',{d:pathFor(series[sd.key]), fill:'none', stroke:sd.color, 'stroke-width':2, 'stroke-linejoin':'round','stroke-linecap':'round'}));
    });

    // x-axis: first/last date labels only
    svg.appendChild(txt(marginLeft, H-6, series.dates[0].slice(0,7), 'tick-label','start'));
    svg.appendChild(txt(W-marginRight, H-6, series.dates[n-1].slice(0,7), 'tick-label','end'));

    // crosshair
    var chLine = el('line',{x1:0,x2:0,y1:marginTop,y2:H-marginBottom,stroke:'var(--ink-muted)','stroke-width':1,'stroke-dasharray':'3,3',visibility:'hidden'});
    svg.appendChild(chLine);
    var hitRect = el('rect',{x:marginLeft,y:marginTop,width:plotW,height:plotH,fill:'transparent'});
    svg.appendChild(hitRect);

    hitRect.addEventListener('mousemove', function(evt){
      var rect = svg.getBoundingClientRect();
      var scaleX = W/rect.width;
      var localX = (evt.clientX-rect.left)*scaleX;
      var i = Math.round((localX-marginLeft)/plotW*(n-1));
      i = Math.max(0, Math.min(n-1, i));
      var x = xScale(i);
      chLine.setAttribute('x1',x); chLine.setAttribute('x2',x);
      chLine.setAttribute('visibility','visible');
      var blue=colorVar('--blue'), orange=colorVar('--orange'), aqua=colorVar('--aqua');
      showTip(evt,
        '<div class="tt-title">'+series.dates[i]+'</div>'+
        '<div class="tt-row"><span><span class="tt-key" style="background:'+blue+'"></span>전략</span><span class="tt-val">'+series.strategy[i].toFixed(1)+'</span></div>'+
        '<div class="tt-row"><span><span class="tt-key" style="background:'+orange+'"></span>매수보유</span><span class="tt-val">'+series.bh[i].toFixed(1)+'</span></div>'+
        '<div class="tt-row"><span><span class="tt-key" style="background:'+aqua+'"></span>S&amp;P500</span><span class="tt-val">'+series.bench[i].toFixed(1)+'</span></div>'
      );
    });
    hitRect.addEventListener('mouseleave', function(){ chLine.setAttribute('visibility','hidden'); hideTip(); });

    container.innerHTML='';
    container.appendChild(svg);
  }

  // ---------------------------------------------------------------
  // Assemble page from DATA
  // ---------------------------------------------------------------
  function build(){
    var jangi = DATA.styles['장기'];
    var sectorTickers = jangi.tickers.filter(function(t){ return t.sector !== 'S&P500'; });
    renderDivergingBar('chart-divbar', jangi.tickers);

    var cagrRows = jangi.sector_agg.map(function(s){
      return {label:s.sector, base:s.avg_cagr_bh, value:s.avg_cagr_strategy, ref:s.avg_cagr_bench};
    });
    renderDumbbell('chart-dumbbell-cagr', cagrRows, {unit:'%'});

    var mddRows = jangi.sector_agg.map(function(s){
      return {label:s.sector, base:s.avg_mdd_bh, value:s.avg_mdd_strategy, ref: jangi.overall.index_mdd_bh};
    });
    renderDumbbell('chart-dumbbell-mdd', mddRows, {unit:'%'});

    var panelDefs = [
      {key:'S&P500', title:'S&P500 지수', sub:'지수 자체를 코스톨라니 신호로 매매'},
      {key: DATA.selected_labels.best, title: DATA.selected_labels.best + ' · 최선의 사례', sub:'전략이 매수보유를 가장 크게 이긴 종목'},
      {key: DATA.selected_labels.defensive, title: DATA.selected_labels.defensive + ' · 낙폭 방어형', sub:'수익도 낙폭도 동시에 개선된 종목'},
      {key: DATA.selected_labels.worst, title: DATA.selected_labels.worst + ' · 최악의 사례', sub:'구조적 상승장에서 조기 이탈로 대패한 종목'}
    ];
    var grid = document.getElementById('equity-panels');
    panelDefs.forEach(function(p){
      var ex = DATA.equity_examples[p.key === 'S&P500' ? 'S&P500' : (p.key===DATA.selected_labels.best?'best':(p.key===DATA.selected_labels.defensive?'defensive':'worst'))];
      var panel = document.createElement('div');
      panel.className = 'sm-panel';
      var h4 = document.createElement('h4'); h4.textContent = p.title;
      var sub = document.createElement('p'); sub.className='sm-sub'; sub.textContent = p.sub;
      var chartDiv = document.createElement('div');
      var chartId = 'eq-'+p.key.replace(/[^A-Za-z0-9]/g,'');
      chartDiv.id = chartId;
      panel.appendChild(h4); panel.appendChild(sub); panel.appendChild(chartDiv);
      grid.appendChild(panel);
      renderEquityLine(chartId, ex);
    });

    if(DATA.portfolio_equity && document.getElementById('chart-portfolio-equity')){
      renderEquityLine('chart-portfolio-equity', DATA.portfolio_equity, {width:760, height:320, marginLeft:60});
    }
    if(DATA.vol_target_equity && document.getElementById('chart-vol-target-equity')){
      renderEquityLine('chart-vol-target-equity', DATA.vol_target_equity, {width:760, height:320, marginLeft:60});
    }
    if(DATA.momentum_50u_equity && document.getElementById('chart-momentum-50u-equity')){
      renderEquityLine('chart-momentum-50u-equity', DATA.momentum_50u_equity, {width:760, height:320, marginLeft:60});
    }
    if(DATA.momentum_unbiased_equity && document.getElementById('chart-momentum-unbiased-equity')){
      renderEquityLine('chart-momentum-unbiased-equity', DATA.momentum_unbiased_equity, {width:760, height:320, marginLeft:60});
    }
    if(DATA.unbiased_portfolio_equity && document.getElementById('chart-unbiased-portfolio-equity')){
      renderEquityLine('chart-unbiased-portfolio-equity', DATA.unbiased_portfolio_equity, {width:760, height:320, marginLeft:60});
    }
    if(DATA.bear_market_equity && document.getElementById('chart-bear-market-equity')){
      renderEquityLine('chart-bear-market-equity', DATA.bear_market_equity, {width:760, height:320, marginLeft:60});
    }
    if(DATA.practical_bull_equity && document.getElementById('chart-practical-bull')){
      renderEquityLine('chart-practical-bull', DATA.practical_bull_equity, {});
    }
    if(DATA.practical_bear_equity && document.getElementById('chart-practical-bear')){
      renderEquityLine('chart-practical-bear', DATA.practical_bear_equity, {});
    }
    if(DATA.regime_tilt_equity && document.getElementById('chart-regime-tilt-equity')){
      renderEquityLine('chart-regime-tilt-equity', DATA.regime_tilt_equity, {width:760, height:320, marginLeft:60});
    }
    if(DATA.leader_compare_equity && document.getElementById('chart-leader-compare-equity')){
      renderEquityLine('chart-leader-compare-equity', DATA.leader_compare_equity, {width:760, height:320, marginLeft:60});
    }
  }

  // ---------------------------------------------------------------
  // Table sort + tabs
  // ---------------------------------------------------------------
  function initTable(){
    document.querySelectorAll('.tab-btn').forEach(function(btn){
      btn.addEventListener('click', function(){
        document.querySelectorAll('.tab-btn').forEach(function(b){ b.classList.remove('active'); });
        document.querySelectorAll('.pane').forEach(function(p){ p.classList.remove('active'); });
        btn.classList.add('active');
        document.getElementById(btn.dataset.pane).classList.add('active');
      });
    });

    document.querySelectorAll('table.data-table').forEach(function(table){
      var tbody = table.querySelector('tbody');
      var state = {key:null, dir:1};
      table.querySelectorAll('th[data-key]').forEach(function(th){
        th.addEventListener('click', function(){
          var key = th.dataset.key;
          var dir = (state.key===key) ? -state.dir : -1;
          state = {key:key, dir:dir};
          var rows = Array.prototype.slice.call(tbody.querySelectorAll('tr'));
          rows.sort(function(a,b){
            var va = a.dataset[key], vb = b.dataset[key];
            var na = parseFloat(va), nb = parseFloat(vb);
            var cmp;
            if(!isNaN(na) && !isNaN(nb)){ cmp = na-nb; } else { cmp = String(va).localeCompare(String(vb)); }
            return cmp*dir;
          });
          rows.forEach(function(r){ tbody.appendChild(r); });
        });
      });
    });
  }

  if(document.readyState==='loading'){
    document.addEventListener('DOMContentLoaded', function(){ build(); initTable(); });
  } else { build(); initTable(); }
})();
