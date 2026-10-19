// Partlar: yeni kelimeler en fazla 15'lik gruplar. Part part öğren; bitirdiğin partları seçip karışık test yap.
import { get } from './api.js';
import { h, add, clear, icon, fmt } from './util.js';
import { isCurrent, currentRoute } from './nav.js';

const STATUS = { tamam: ['Tamamlandı', 'good'], devam: ['Devam ediyor', 'warn'], yeni: ['Başlanmadı', ''] };

export async function renderParts(main, state, token) {
  token = token ?? currentRoute();
  clear(main);
  main.appendChild(h('div', { class: 'muted' }, 'Yükleniyor…'));
  let d;
  try { d = await get('/parts'); } catch (e) { if (isCurrent(token)) { clear(main); add(main, h('div', { class: 'notice bad' }, e.message)); } return; }
  if (!isCurrent(token)) return;
  clear(main);
  const t = d.today, parts = d.parts;
  const byId = Object.fromEntries(parts.map(p => [p.id, p]));
  const selected = new Set();
  const go = (q) => { location.hash = '#/calis?' + q; };

  // ---- üst kart: bugünkü çalışma + sıradaki part
  const op = t.open;
  const daySub = [d.reviews_due ? `${d.reviews_due} tekrar` : 'vadesi gelen tekrar yok',
    t.planned ? `bugün ${t.finished_today}/${t.planned} part` : null].filter(Boolean).join(' · ');
  main.appendChild(h('div', { class: 'card' },
    h('h2', null, icon('list'), 'Partlar'),
    h('div', { class: 'sub' }, `Yeni kelimeler en fazla ${t.size} kelimelik partlarla gelir. Bir part bitince çıkabilirsin; yarım bıraktığın part kaldığı yerden sürer. Bitirdiğin partları seçip karışık test yapabilirsin.`),
    h('div', { class: 'parts-top' },
      h('button', { class: 'btn primary lg', onclick: () => go('mod=daily') }, h('span', null, icon('bolt'), ' Bugünkü çalışma'),
        h('span', { class: 'btn-sub' }, daySub)),
      t.next_available ? h('button', { class: 'btn lg', onclick: () => go('mod=part' + (op ? `&part=${op.id}` : '')) },
        h('span', null, op ? `Devam et: Part ${op.no}` + (op.title ? ` · ${op.title}` : '') : `Sıradaki part: Part ${t.next_no}` + (t.next_title ? ` · ${t.next_title}` : '')),
        h('span', { class: 'btn-sub' }, op ? `${op.total - op.done} kelime kaldı` : (t.next_size ? `${t.next_size} yeni kelime` : `en fazla ${t.size} yeni kelime`))) : null)));

  if (!parts.length) {
    main.appendChild(h('div', { class: 'card' }, h('div', { class: 'muted' },
      `Henüz part yok. İlk ${t.size} kelimeyle başlamak için "Sıradaki part"a bas.`)));
    return;
  }

  // ---- part kartları (gün gün, en yeni gün üstte)
  const cards = [];
  const boxes = new Map();
  const byDay = new Map();
  [...parts].sort((a, b) => b.no - a.no).forEach(p => {
    const k = p.day || '';
    if (!byDay.has(k)) byDay.set(k, []);
    byDay.get(k).push(p);
  });
  const list = h('div');
  for (const [day, ps] of byDay) {
    ps.sort((a, b) => a.no - b.no);
    const selectable = ps.filter(p => p.testable);
    list.appendChild(h('div', { class: 'section-title parts-day' }, `${fmt.dateLong(day)} · ${ps.length} part`,
      selectable.length ? h('button', { class: 'linkbtn', onclick: () => { selectable.forEach(p => selected.add(p.id)); sync(); } }, 'hepsini seç') : null));
    list.appendChild(h('div', { class: 'parts-grid' }, ps.map(partCard)));
  }
  main.appendChild(list);

  // ---- seçim çubuğu (ekranın altına yapışır)
  const selInfo = h('span', { class: 'sel-info' });
  const quickBtn = h('button', { class: 'btn primary sm', onclick: () => startTest('quick') }, icon('bolt'), ' Karışık hızlı test');
  const testBtn = h('button', { class: 'btn sm', onclick: () => startTest('part_test') }, icon('check'), ' Normal test');
  const clearBtn = h('button', { class: 'btn ghost sm', onclick: () => { selected.clear(); sync(); } }, 'Seçimi temizle');
  main.appendChild(h('div', { class: 'sel-bar' }, selInfo, h('span', { class: 'spacer' }), quickBtn, testBtn, clearBtn));
  main.appendChild(h('div', { class: 'actions', style: { marginTop: '1rem' } },
    action('bolt', 'Hızlı tekrar', 'tüm listeden · süreli · 3 can', () => go('mod=quick')),
    action('brain', 'Zor kelimeler', 'en çok yanıldıkların', () => go('mod=hard'))));
  sync();

  function startTest(mode) {
    if (!selected.size) return;
    go(`mod=${mode}&parts=${[...selected].join(',')}`);
  }

  function sync() {
    const n = [...selected].reduce((a, id) => a + ((byId[id] && byId[id].testable) || 0), 0);
    selInfo.textContent = selected.size ? `${selected.size} part seçili · ${n} kelime` : 'Test için bir ya da birden çok part seç';
    quickBtn.disabled = testBtn.disabled = !n;
    clearBtn.style.visibility = selected.size ? 'visible' : 'hidden';
    cards.forEach(c => c.classList.toggle('selected', selected.has(+c.dataset.id)));
    boxes.forEach((cb, id) => { cb.checked = selected.has(id); });
  }

  function partCard(p) {
    const [stLabel, stCls] = STATUS[p.status] || STATUS.yeni;
    const cb = h('input', { type: 'checkbox', title: p.testable ? 'Teste ekle' : 'Henüz test edilecek kelime yok' });
    cb.disabled = !p.testable;
    cb.onchange = () => { if (cb.checked) selected.add(p.id); else selected.delete(p.id); sync(); };
    boxes.set(p.id, cb);
    const facts = [`${p.done}/${p.total} kelime`, p.due ? `${p.due} tekrar vadesi geldi` : null, p.weak ? `${p.weak} zayıf` : null].filter(Boolean).join(' · ');
    const c = h('div', { class: 'part-card', 'data-id': String(p.id) },
      h('div', { class: 'pc-head' }, h('label', { class: 'pc-title' }, cb, `Part ${p.no}`, p.title ? h('span', { class: 'pc-sub' }, p.title) : null), h('span', { class: 'chip ' + stCls }, stLabel)),
      h('div', { class: 'meter' + (p.status === 'tamam' ? ' good' : '') }, h('div', { style: { width: Math.round(100 * (p.total ? p.done / p.total : 0)) + '%' } })),
      h('div', { class: 'small ink2 pc-facts' }, facts),
      h('div', { class: 'row pc-actions' },
        p.status !== 'tamam' ? h('button', { class: 'btn sm primary', onclick: () => go(`mod=part&part=${p.id}`) }, p.status === 'devam' ? 'Devam et' : 'Başla') : null,
        p.testable ? h('button', { class: 'btn sm', onclick: () => go(`mod=part_test&parts=${p.id}`) }, 'Test') : null,
        p.testable ? h('button', { class: 'btn sm ghost', title: 'Karışık hızlı test', onclick: () => go(`mod=quick&parts=${p.id}`) }, icon('bolt'), ' Hızlı') : null));
    // kartın boş yerine tıklamak seçimi değiştirir
    c.onclick = (e) => {
      if (!p.testable || e.target.closest('button') || e.target.closest('input') || e.target.closest('label')) return;
      cb.checked = !cb.checked;
      cb.onchange();
    };
    cards.push(c);
    return c;
  }
}

function action(ic, title, sub, onclick) {
  return h('div', { class: 'action', onclick, tabindex: 0, role: 'button' }, h('div', { class: 'ic' }, icon(ic)), h('div', null, title, h('small', null, sub)));
}
