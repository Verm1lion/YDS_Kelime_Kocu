// Küçük, bağımlılıksız SVG grafik kütüphanesi (dataviz kuralları: tek eksen, ince işaretler,
// ≥2 seride lejant + seçici doğrudan etiket, ipucu katmanı, açık/koyu tema jetonları).
import { h, clear } from './util.js';

const NS = 'http://www.w3.org/2000/svg';
const S = (tag, attrs = {}) => {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== null && v !== undefined) el.setAttribute(k, v);
  return el;
};

function niceTicks(min, max, n = 4) {
  if (max === min) { max = min + 1; }
  const span = max - min;
  const step0 = span / n;
  const mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const norm = step0 / mag;
  const step = (norm >= 5 ? 5 : norm >= 2 ? 2 : 1) * mag;
  const lo = Math.floor(min / step) * step, hi = Math.ceil(max / step) * step;
  const out = [];
  for (let v = lo; v <= hi + step / 2; v += step) out.push(+v.toFixed(10));
  return out;
}

function tooltipEl(wrap) {
  let tt = wrap.querySelector('.tooltip');
  if (!tt) { tt = h('div', { class: 'tooltip hidden' }); wrap.appendChild(tt); }
  return tt;
}

function placeTip(wrap, tt, x, y) {
  tt.classList.remove('hidden');
  const W = wrap.clientWidth;
  const tw = tt.offsetWidth;
  let left = x + 14;
  if (left + tw > W) left = x - tw - 14;
  tt.style.left = Math.max(0, left) + 'px';
  tt.style.top = Math.max(0, y - 10) + 'px';
}

function observe(container, render) {
  render();
  if (container._ro) container._ro.disconnect();
  let lastW = container.clientWidth;
  const ro = new ResizeObserver(() => {
    if (Math.abs(container.clientWidth - lastW) > 4) { lastW = container.clientWidth; render(); }
  });
  ro.observe(container);
  container._ro = ro;
}

// ------------------------------------------------------------ çizgi grafik
// series: [{name, color, points:[{x: Date|number, y}], dashed?}], target: {y, label}
export function lineChart(container, opt) {
  const render = () => {
    clear(container);
    container.classList.add('chart');
    const series = opt.series.filter(s => s.points.length);
    if (series.length >= 2 || opt.target) {
      const lg = h('div', { class: 'legend' });
      for (const s of series) lg.appendChild(h('span', null, h('span', { class: 'key', style: { background: s.color } }), s.name));
      if (opt.target) lg.appendChild(h('span', null, h('span', { class: 'key dash' }), opt.target.label));
      container.appendChild(lg);
    }
    const W = Math.max(280, container.clientWidth), H = opt.height || 220;
    const m = { l: 44, r: opt.endLabels === false ? 16 : 70, t: 12, b: 26 };
    const xs = series.flatMap(s => s.points.map(p => +p.x));
    let ys = series.flatMap(s => s.points.map(p => p.y)).filter(v => v !== null && !isNaN(v));
    if (opt.target) ys.push(opt.target.y);
    if (!xs.length) { container.appendChild(h('div', { class: 'muted small' }, opt.empty || 'Henüz veri yok.')); return; }
    let x0 = Math.min(...xs), x1 = Math.max(...xs);
    if (opt.xMax) x1 = Math.max(x1, +opt.xMax);
    if (x0 === x1) { x0 -= 86400000; x1 += 86400000; }
    let y0 = opt.yMin ?? Math.min(...ys), y1 = opt.yMax ?? Math.max(...ys);
    const ticks = niceTicks(y0, y1, 4);
    y0 = opt.yMin ?? ticks[0]; y1 = opt.yMax ?? ticks[ticks.length - 1];
    const X = (v) => m.l + (W - m.l - m.r) * ((+v - x0) / (x1 - x0));
    const Y = (v) => m.t + (H - m.t - m.b) * (1 - (v - y0) / ((y1 - y0) || 1));
    const svg = S('svg', { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: 'img', 'aria-label': opt.title || 'grafik' });
    for (const t of (opt.yMin !== undefined && opt.yMax !== undefined) ? niceTicks(y0, y1, 4).filter(t => t >= y0 && t <= y1) : ticks) {
      svg.appendChild(S('line', { x1: m.l, x2: W - m.r, y1: Y(t), y2: Y(t), stroke: 'var(--grid)', 'stroke-width': 1 }));
      const tx = S('text', { x: m.l - 6, y: Y(t) + 4, 'text-anchor': 'end', 'font-size': 11, fill: 'var(--axis-ink)' });
      tx.textContent = opt.yFormat ? opt.yFormat(t) : t;
      svg.appendChild(tx);
    }
    // x etiketleri (tarih)
    const nx = Math.min(6, Math.max(2, Math.floor((W - m.l - m.r) / 90)));
    for (let i = 0; i <= nx; i++) {
      const v = x0 + (x1 - x0) * i / nx;
      const tx = S('text', { x: X(v), y: H - 6, 'text-anchor': i === 0 ? 'start' : i === nx ? 'end' : 'middle', 'font-size': 11, fill: 'var(--axis-ink)' });
      tx.textContent = opt.xFormat ? opt.xFormat(v) : new Date(v).toLocaleDateString('tr-TR', { day: 'numeric', month: 'short' });
      svg.appendChild(tx);
    }
    svg.appendChild(S('line', { x1: m.l, x2: W - m.r, y1: H - m.b, y2: H - m.b, stroke: 'var(--axis)', 'stroke-width': 1 }));
    if (opt.target) {
      svg.appendChild(S('line', { x1: m.l, x2: W - m.r, y1: Y(opt.target.y), y2: Y(opt.target.y), stroke: 'var(--ink-2)', 'stroke-width': 1.5, 'stroke-dasharray': '5 4' }));
    }
    if (opt.marker) {
      const mx = X(opt.marker.x);
      svg.appendChild(S('line', { x1: mx, x2: mx, y1: m.t, y2: H - m.b, stroke: 'var(--line-2)', 'stroke-width': 1 }));
      const t = S('text', { x: mx - 4, y: H - m.b - 6, 'text-anchor': 'end', 'font-size': 11, fill: 'var(--muted)' });
      t.textContent = opt.marker.label; svg.appendChild(t);
    }
    const ends = [];
    for (const s of series) {
      const pts = s.points.filter(p => p.y !== null && !isNaN(p.y));
      if (!pts.length) continue;
      if (s.area) {
        const d = `M${X(pts[0].x)},${Y(y0)} ` + pts.map(p => `L${X(p.x)},${Y(p.y)}`).join(' ') + ` L${X(pts[pts.length - 1].x)},${Y(y0)} Z`;
        svg.appendChild(S('path', { d, fill: s.color, opacity: 0.1 }));
      }
      const d = pts.map((p, i) => `${i ? 'L' : 'M'}${X(p.x).toFixed(1)},${Y(p.y).toFixed(1)}`).join(' ');
      svg.appendChild(S('path', { d, fill: 'none', stroke: s.color, 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round', 'stroke-dasharray': s.dashed ? '6 4' : null }));
      const last = pts[pts.length - 1];
      svg.appendChild(S('circle', { cx: X(last.x), cy: Y(last.y), r: 4.5, fill: s.color, stroke: 'var(--chart-surface)', 'stroke-width': 2 }));
      ends.push({ s, y: Y(last.y), x: X(last.x), v: last.y });
    }
    if (opt.endLabels !== false) {
      ends.sort((a, b) => a.y - b.y);
      for (let i = 1; i < ends.length; i++) if (ends[i].y - ends[i - 1].y < 14) ends[i].skip = true;
      for (const e of ends) {
        if (e.skip) continue;
        const t = S('text', { x: e.x + 8, y: e.y + 4, 'font-size': 12, 'font-weight': 700, fill: 'var(--ink-2)' });
        t.textContent = opt.yFormat ? opt.yFormat(e.v) : e.v;
        svg.appendChild(t);
      }
    }
    const wrap = h('div', { style: { position: 'relative' } });
    wrap.appendChild(svg);
    container.appendChild(wrap);
    // ipucu: dikey kılavuz en yakın x'e oturur
    const cross = S('line', { y1: m.t, y2: H - m.b, stroke: 'var(--axis)', 'stroke-width': 1, visibility: 'hidden' });
    svg.appendChild(cross);
    const tt = tooltipEl(wrap);
    const allX = [...new Set(xs)].sort((a, b) => a - b);
    const hit = S('rect', { x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: 'transparent' });
    svg.appendChild(hit);
    const move = (ev) => {
      const r = svg.getBoundingClientRect();
      const px = (ev.clientX - r.left) * (W / r.width);
      let best = allX[0], bd = Infinity;
      for (const x of allX) { const d = Math.abs(X(x) - px); if (d < bd) { bd = d; best = x; } }
      cross.setAttribute('x1', X(best)); cross.setAttribute('x2', X(best)); cross.setAttribute('visibility', 'visible');
      clear(tt);
      tt.appendChild(h('div', { class: 'tt-h' }, opt.xFormat ? opt.xFormat(best) : new Date(best).toLocaleDateString('tr-TR', { day: 'numeric', month: 'long' })));
      for (const s of series) {
        const p = s.points.find(p => +p.x === best);
        if (!p || p.y === null) continue;
        tt.appendChild(h('div', { class: 'tt-r' }, h('span', { class: 'tt-k', style: { background: s.color } }),
          h('b', null, opt.yFormat ? opt.yFormat(p.y) : p.y), h('span', { class: 'muted' }, s.name)));
      }
      placeTip(wrap, tt, X(best) * (r.width / W), (ev.clientY - r.top));
    };
    hit.addEventListener('pointermove', move);
    hit.addEventListener('pointerleave', () => { tt.classList.add('hidden'); cross.setAttribute('visibility', 'hidden'); });
  };
  observe(container, render);
}

// ------------------------------------------------------------ sütun grafik (tek seri)
// data: [{label, value, tip?}], refLine: {y, label}
export function columnChart(container, opt) {
  const render = () => {
    clear(container);
    container.classList.add('chart');
    const data = opt.data;
    if (!data.length) { container.appendChild(h('div', { class: 'muted small' }, opt.empty || 'Henüz veri yok.')); return; }
    if (opt.refLine) {
      container.appendChild(h('div', { class: 'legend' }, h('span', null, h('span', { class: 'key box', style: { background: opt.color || 'var(--series-1)' } }), opt.seriesName || ''),
        h('span', null, h('span', { class: 'key dash' }), opt.refLine.label)));
    }
    const W = Math.max(280, container.clientWidth), H = opt.height || 200;
    const m = { l: 40, r: 10, t: 10, b: 26 };
    let maxV = Math.max(...data.map(d => d.value || 0), opt.refLine ? opt.refLine.y : 0, opt.yMax || 0);
    const ticks = niceTicks(0, maxV || 1, 4);
    const y1 = opt.yMax ?? ticks[ticks.length - 1];
    const Y = (v) => m.t + (H - m.t - m.b) * (1 - v / (y1 || 1));
    const band = (W - m.l - m.r) / data.length;
    const bw = Math.min(24, Math.max(3, band - 2));
    const svg = S('svg', { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: 'img', 'aria-label': opt.title || 'grafik' });
    for (const t of ticks.filter(t => t <= y1)) {
      svg.appendChild(S('line', { x1: m.l, x2: W - m.r, y1: Y(t), y2: Y(t), stroke: 'var(--grid)', 'stroke-width': 1 }));
      const tx = S('text', { x: m.l - 6, y: Y(t) + 4, 'text-anchor': 'end', 'font-size': 11, fill: 'var(--axis-ink)' });
      tx.textContent = opt.yFormat ? opt.yFormat(t) : t;
      svg.appendChild(tx);
    }
    const wrap = h('div', { style: { position: 'relative' } });
    const tt = tooltipEl(wrap);
    const every = Math.ceil(data.length / Math.max(2, Math.floor((W - m.l - m.r) / 46)));
    data.forEach((d, i) => {
      const cx = m.l + band * i + band / 2;
      const v = d.value || 0;
      const top = Y(v), base = Y(0);
      const hgt = Math.max(0, base - top);
      const r = Math.min(4, hgt, bw / 2);
      const x = cx - bw / 2;
      const path = hgt > 0 ? `M${x},${base} L${x},${top + r} Q${x},${top} ${x + r},${top} L${x + bw - r},${top} Q${x + bw},${top} ${x + bw},${top + r} L${x + bw},${base} Z` : '';
      if (path) svg.appendChild(S('path', { d: path, fill: d.color || opt.color || 'var(--series-1)', opacity: d.dim ? 0.45 : 1 }));
      if (i % every === 0 || data.length <= 14) {
        const tx = S('text', { x: cx, y: H - 8, 'text-anchor': 'middle', 'font-size': 11, fill: 'var(--axis-ink)' });
        tx.textContent = d.short ?? d.label;
        svg.appendChild(tx);
      }
      const hit = S('rect', { x: m.l + band * i, y: m.t, width: band, height: H - m.t - m.b, fill: 'transparent' });
      hit.addEventListener('pointermove', (ev) => {
        clear(tt);
        tt.appendChild(h('div', { class: 'tt-h' }, d.label));
        tt.appendChild(h('div', { class: 'tt-r' }, h('b', null, opt.yFormat ? opt.yFormat(v) : v), d.tip ? h('span', { class: 'muted' }, d.tip) : null));
        const r2 = svg.getBoundingClientRect();
        placeTip(wrap, tt, cx * (r2.width / W), ev.clientY - r2.top);
      });
      hit.addEventListener('pointerleave', () => tt.classList.add('hidden'));
      svg.appendChild(hit);
    });
    svg.appendChild(S('line', { x1: m.l, x2: W - m.r, y1: Y(0), y2: Y(0), stroke: 'var(--axis)', 'stroke-width': 1 }));
    if (opt.refLine) {
      svg.appendChild(S('line', { x1: m.l, x2: W - m.r, y1: Y(opt.refLine.y), y2: Y(opt.refLine.y), stroke: 'var(--ink-2)', 'stroke-width': 1.5, 'stroke-dasharray': '5 4' }));
    }
    wrap.insertBefore(svg, wrap.firstChild);
    container.appendChild(wrap);
  };
  observe(container, render);
}

// ------------------------------------------------------------ yatay çubuklar (tek seri)
export function hbars(container, rows, opt = {}) {
  clear(container);
  const max = opt.max ?? Math.max(...rows.map(r => r.value || 0), 1e-9);
  for (const r of rows) {
    const pct = Math.max(0, Math.min(1, (r.value || 0) / max));
    container.appendChild(h('div', { class: 'prob-row' + (r.emph ? ' target' : ''), title: r.tip || '' },
      h('span', { class: 'lbl' }, r.label),
      h('div', { class: 'track' }, h('div', { class: 'bar', style: { width: (pct * 100).toFixed(1) + '%', background: r.color || 'var(--series-1)' } })),
      h('span', { class: 'val' }, opt.format ? opt.format(r.value) : r.value)));
  }
}

// ------------------------------------------------------------ takvim ısı haritası (dakika)
export function heatmap(container, days, opt = {}) {
  clear(container);
  if (!days.length) { container.appendChild(h('div', { class: 'muted small' }, 'Henüz veri yok.')); return; }
  const wrap = h('div', { style: { position: 'relative' } });
  const grid = h('div', { class: 'heat', role: 'img', 'aria-label': 'Çalışma takvimi' });
  const first = new Date(days[0].day + 'T12:00:00');
  const pad = (first.getDay() + 6) % 7; // pazartesi başlangıç
  for (let i = 0; i < pad; i++) grid.appendChild(h('div', { class: 'c', style: { visibility: 'hidden' } }));
  const steps = opt.steps || [1, 15, 30, 60, 90];
  const tt = tooltipEl(wrap);
  for (const d of days) {
    const v = d.minutes || 0;
    let lvl = 0;
    steps.forEach((s, i) => { if (v >= s) lvl = i + 1; });
    const c = h('div', { class: 'c', style: { background: `var(--seq-${Math.min(5, lvl)})` }, tabindex: 0 });
    const show = (ev) => {
      clear(tt);
      tt.appendChild(h('div', { class: 'tt-h' }, new Date(d.day + 'T12:00:00').toLocaleDateString('tr-TR', { weekday: 'long', day: 'numeric', month: 'long' })));
      tt.appendChild(h('div', { class: 'tt-r' }, h('b', null, Math.round(v) + ' dk'), h('span', { class: 'muted' }, 'aktif çalışma')));
      const r = wrap.getBoundingClientRect(), cr = c.getBoundingClientRect();
      placeTip(wrap, tt, cr.left - r.left + 7, cr.top - r.top);
    };
    c.addEventListener('pointerenter', show);
    c.addEventListener('focus', show);
    c.addEventListener('pointerleave', () => tt.classList.add('hidden'));
    grid.appendChild(c);
  }
  wrap.appendChild(grid);
  container.appendChild(wrap);
  const lg = h('div', { class: 'heat-legend' }, 'az');
  for (let i = 0; i <= 5; i++) lg.appendChild(h('span', { class: 'c', style: { background: `var(--seq-${i})` } }));
  lg.appendChild(document.createTextNode('çok  (0 · 1 · 15 · 30 · 60 · 90+ dk)'));
  container.appendChild(lg);
}
