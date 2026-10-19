// Kelimeler ekranı: hızlı ekleme (çevrimdışı sözlükle), liste/filtre, ayrıntı çekmecesi (düzenle/işaretle), öneriler.
import { get, post, put, api } from './api.js';
import { h, add, clear, icon, fmt, toast, drawer, debounce, highlight, speak, ICONS, osymLabel, osymChip } from './util.js';
import { plantSVG, stageLabel } from './plant.js';

const FILTERS = [
  ['all', 'Tümü'], ['new', 'Yeni'], ['learning', 'Öğreniliyor'], ['learned', 'Öğrenildi'], ['hard', 'Zor'], ['due', 'Vadesi gelen'],
  ['user', 'Eklediklerim'], ['reserve', 'Yedek'], ['flagged', 'İşaretli'], ['oneriler', 'Öneriler'],
];

export async function renderWords(main, state, params) {
  clear(main);
  let status = params.get('sekme') || 'all';
  let q = '', sort = 'order', offset = 0;
  main.appendChild(h('h1', null, 'Kelimeler'));

  // hızlı ekleme
  const word = h('input', { type: 'text', placeholder: 'Denemede gördüğün kelime (ör. alleviate)', style: { flex: '1 1 220px' } });
  const mean = h('input', { type: 'text', placeholder: 'Anlam (boş bırakırsan sözlükten gelir)', style: { flex: '2 1 260px' } });
  const hint = h('div', { class: 'small muted', style: { marginTop: '.35rem' } }, 'Kelime anında plana girer; internet varsa örnek cümle ve ipuçlarıyla otomatik zenginleştirilir.');
  const add = async () => {
    if (!word.value.trim()) return;
    try {
      const r = await post('/words', { text: word.value.trim(), meaning: mean.value.trim() || null });
      toast(r.status === 'existing' ? `"${r.lemma}" zaten listede${r.updates.length ? ' — ' + r.updates.join(', ') : ''}.` : `"${r.lemma}" eklendi${r.meaning ? ': ' + r.meaning : ''}. Sıradaki pakette öğreteceğim.`);
      word.value = ''; mean.value = ''; word.focus(); load();
    } catch (e) { toast(e.message, 'warn'); }
  };
  word.addEventListener('input', debounce(async () => {
    const w = word.value.trim();
    if (w.length < 3) { hint.textContent = ''; return; }
    try {
      const r = await get('/lookup?w=' + encodeURIComponent(w));
      clear(hint);
      if (r.existing) add(hint, h('span', { class: 'chip info' }, r.existing.status === 'active' ? 'zaten listede' : 'listede (pasif: ' + r.existing.pool + ')'), ' ');
      if (r.offline) { add(hint, 'Sözlük: ', h('b', null, r.offline.tr), r.offline.pos ? ` (${r.offline.pos})` : ''); if (!mean.value) mean.placeholder = r.offline.tr; }
      else add(hint, 'Çevrimdışı sözlükte yok — anlamı yazarsan hemen öğrenmeye başlarsın.');
    } catch (e) { /* yok */ }
  }, 300));
  [word, mean].forEach(i => i.addEventListener('keydown', (e) => { if (e.key === 'Enter') add(); }));
  const fileIn = h('input', { type: 'file', accept: '.xlsx,.csv,.txt,.tsv', style: { display: 'none' } });
  fileIn.onchange = async () => {
    const f = fileIn.files[0]; if (!f) return;
    try {
      const r = await api('/import?filename=' + encodeURIComponent(f.name), { method: 'POST', body: await f.arrayBuffer(), raw: true });
      toast(`${r.added} kelime eklendi, ${r.existing} zaten vardı.`); load();
    } catch (e) { toast(e.message, 'warn'); }
  };
  main.appendChild(h('div', { class: 'card' }, h('h2', null, icon('plus'), 'Hızlı ekle'),
    h('div', { class: 'row' }, word, mean, h('button', { class: 'btn primary', onclick: add }, 'Ekle')), hint,
    h('div', { class: 'row', style: { marginTop: '.6rem' } }, h('button', { class: 'btn sm', onclick: () => fileIn.click() }, icon('upload'), 'Liste içe aktar (xlsx/csv/txt)'), fileIn)));
  if (params.get('ekle')) setTimeout(() => word.focus(), 50);

  // filtreler
  const tabs = h('div', { class: 'tabs' });
  const search = h('input', { type: 'text', placeholder: 'Ara (İngilizce/Türkçe)…', style: { flex: '1' } });
  const sortSel = h('select', null, [['order', 'Öğrenme sırası'], ['alpha', 'A-Z'], ['hard', 'En zor'], ['due', 'Vade'], ['recent', 'Son çalışılan'], ['stage', 'Basamak']].map(([v, l]) => h('option', { value: v }, l)));
  const listEl = h('div', { class: 'wordlist' });
  const more = h('button', { class: 'btn sm', style: { marginTop: '.8rem' } }, 'Daha fazla');
  const listCard = h('div', { class: 'card' }, tabs, h('div', { class: 'row', style: { marginBottom: '.6rem' } }, h('span', { svg: ICONS.search, style: { width: '18px', display: 'inline-flex', color: 'var(--muted)' } }), search, sortSel), listEl, more);
  main.appendChild(listCard);

  search.addEventListener('input', debounce(() => { q = search.value.trim(); offset = 0; load(); }, 250));
  sortSel.onchange = () => { sort = sortSel.value; offset = 0; load(); };
  more.onclick = () => { offset += 100; load(true); };

  async function load(append = false) {
    if (status === 'oneriler') return loadSuggestions();
    more.classList.remove('hidden');
    const r = await get(`/words?q=${encodeURIComponent(q)}&status=${status}&sort=${sort}&offset=${offset}&limit=100`);
    clear(tabs);
    FILTERS.forEach(([k, l]) => tabs.appendChild(h('button', { class: status === k ? 'active' : '', onclick: () => { status = k; offset = 0; load(); } }, l,
      r.counts[k] !== undefined ? h('span', { class: 'n' }, fmt.num(r.counts[k])) : null)));
    if (!append) clear(listEl);
    if (!r.items.length && !append) listEl.appendChild(h('div', { class: 'muted', style: { padding: '1rem' } }, 'Kayıt yok.'));
    for (const w of r.items) {
      listEl.appendChild(h('div', { class: 'wl-row', onclick: () => openWord(w.id) },
        h('span', { svg: plantSVG(w.stage || 0, 38), title: stageLabel(w.stage || 0) }),
        h('div', null, h('div', { class: 'w' }, w.display), h('div', { class: 'small muted pos' }, [w.pos, w.pool !== 'main' ? w.pool : null, w.known_status === 'verified' ? 'biliyordun' : null].filter(Boolean).join(' · '))),
        h('div', { class: 'm' }, w.meaning || ''),
        h('div', { class: 'small ink2' }, w.due_day ? 'vade ' + fmt.date(w.due_day) : (w.stage ? '' : 'başlanmadı')),
        h('div', { class: 'small muted', style: { textAlign: 'right' } }, w.reps ? `${w.reps} tekrar` : '', w.wrong_total ? ` · ${w.wrong_total}✗` : '')));
    }
    more.classList.toggle('hidden', offset + 100 >= r.total);
  }

  async function loadSuggestions() {
    more.classList.add('hidden');
    clear(tabs);
    FILTERS.forEach(([k, l]) => tabs.appendChild(h('button', { class: status === k ? 'active' : '', onclick: () => { status = k; offset = 0; load(); } }, l)));
    clear(listEl);
    const r = await get('/suggestions');
    const items = r.pending;
    listEl.appendChild(h('p', { class: 'ink2' }, 'Listende olmayan, YDS\'de sık çıkan bağlaç/geçiş ifadeleri ve öbek fiiller. Onayladıkların sıradaki paketlere girer.'));
    if (!items.length) { listEl.appendChild(h('div', { class: 'muted' }, 'Bekleyen öneri yok.')); return; }
    const checks = new Map();
    const groups = { linker: 'Bağlaçlar / geçiş ifadeleri / edat öbekleri', phrasal: 'Öbek fiiller' };
    for (const [kind, title] of Object.entries(groups)) {
      const g = items.filter(i => i.kind === kind);
      if (!g.length) continue;
      const all = h('input', { type: 'checkbox' });
      listEl.appendChild(h('div', { class: 'section-title row' }, h('label', { class: 'check' }, all, `${title} (${g.length})`)));
      const box = h('div', { class: 'grid2' });
      g.forEach(s => {
        const cb = h('input', { type: 'checkbox', checked: (s.priority || 0) >= 3 });
        checks.set(s.id, cb);
        box.appendChild(h('label', { class: 'check', style: { alignItems: 'flex-start', padding: '.3rem 0' } }, cb,
          h('span', null, h('b', null, s.display), ' — ', s.meaning || '', h('div', { class: 'small muted' }, (s.priority >= 3 ? '★ çok sık · ' : '') + (s.reason || '')))));
      });
      all.onchange = () => g.forEach(s => { checks.get(s.id).checked = all.checked; });
      listEl.appendChild(box);
    }
    const decide = async (accept) => {
      const ids = [...checks.entries()].filter(([, c]) => c.checked).map(([id]) => id);
      if (!ids.length) return toast('Seçim yok');
      await post('/suggestions/decide', { ids, accept });
      toast(accept ? `${ids.length} ifade plana eklendi.` : `${ids.length} öneri reddedildi.`);
      loadSuggestions();
    };
    listEl.appendChild(h('div', { class: 'row', style: { marginTop: '1rem' } }, h('button', { class: 'btn primary', onclick: () => decide(true) }, 'Seçilenleri ekle'),
      h('button', { class: 'btn', onclick: () => decide(false) }, 'Seçilenleri reddet')));
  }

  load();
}

// ------------------------------------------------------------ ayrıntı çekmecesi
export async function openWord(id) {
  const body = h('div', null, h('div', { class: 'muted' }, 'Yükleniyor…'));
  const d = drawer(body);
  const render = async () => {
    let b;
    try { b = await get(`/words/${id}`); } catch (e) { clear(body); add(body, e.message); return; }
    clear(body);
    const w = b.word, c = b.card || {}, info = b.info || {};
    const meta = info._meta || {};
    add(body, 
      h('div', { class: 'row' }, h('span', { svg: plantSVG(c.stage || 0, 56) }), h('div', null, h('h1', { style: { margin: 0 } }, w.display),
        h('div', { class: 'muted', style: { fontWeight: 800 } }, [w.pos, w.level, stageLabel(c.stage || 0)].filter(Boolean).join(' · '))),
        h('button', { class: 'iconbtn', title: 'Dinle', onclick: () => speak(w.display), svg: ICONS.speaker })),
    );
    // anlam
    const mInp = h('input', { type: 'text', value: w.meaning_user || '', placeholder: w.meaning_src || w.meaning_gen || 'Kendi anlamın', style: { width: '100%' } });
    add(body, sec('Anlam'),
      w.meaning_src ? h('div', null, h('b', null, w.meaning_src), h('span', { class: 'small muted' }, '  (listendeki anlam — asla ezilmez)')) : null,
      !w.meaning_src && w.meaning_gen ? h('div', null, h('b', null, w.meaning_gen), ' ', h('span', { class: 'badge-unv' }, 'sözlük/yapay zekâ')) : null,
      h('div', { class: 'row', style: { marginTop: '.4rem' } }, mInp, h('button', { class: 'btn sm', onclick: async () => { await put(`/words/${id}/meaning`, { meaning: mInp.value }); toast('Anlamın kaydedildi (öncelikli).'); } }, 'Kaydet')));
    if (info.senses && info.senses.length) add(body, sec('YDS\'deki anlamları', meta.senses), h('div', null, info.senses.map(s => h('div', { class: 'small' }, '• ', h('b', null, (s.pos || '') + ': '), s.tr, h('span', { class: 'muted' }, ' — ' + (s.en || ''))))));
    // örnekler
    add(body, sec('Örnek cümleler (dönüşümlü kullanılır)'));
    const exs = [...b.examples].sort((x, y) => (osymLabel(y.source) ? 1 : 0) - (osymLabel(x.source) ? 1 : 0));   // gerçek ÖSYM cümleleri önce
    for (const e of exs) add(body, contentItem(e, 'example', id, render, h('div', null, highlight(e.en, e.form), e.tr ? h('div', { class: 'small ink2' }, e.tr) : null,
      h('div', { class: 'small muted' }, `${e.domain || ''} · ${e.times_shown}× gösterildi`)), async () => {
      const en = prompt('İngilizce cümle', e.en); if (en === null) return;
      const tr = prompt('Türkçe çeviri', e.tr || ''); if (tr === null) return;
      await put(`/words/${id}/example/${e.id}`, { en, tr }); toast('Düzenlendi'); render();
    }));
    // ipuçları
    add(body, sec('Hafıza ipuçları'));
    for (const m of b.mnemonics) add(body, contentItem(m, 'mnemonic', id, render, h('div', null, h('span', { class: 'chip', style: { marginRight: '.4rem' } },
      m.source === 'user' ? 'senin' : ({ association: 'çağrışım', etymology: 'köken', context: 'bağlam' }[m.kind] || m.kind)), m.text)));
    const memIn = h('textarea', { rows: 2, placeholder: 'Kendi mem\'ini yaz…', style: { width: '100%' } });
    add(body, memIn, h('button', { class: 'btn sm', onclick: async () => { if (!memIn.value.trim()) return; await post(`/words/${id}/mnemonic`, { text: memIn.value }); toast('Kaydedildi'); render(); } }, 'Mem ekle'));
    // ilişkiler
    for (const [f, lbl] of [['synonyms', 'Eş anlamlılar'], ['antonyms', 'Zıt anlamlılar']]) {
      const v = info[f] || [];
      add(body, sec(lbl, meta[f]), h('div', { class: 'row', style: { gap: '.35rem' } }, v.map(s => h('span', { class: 'chip' }, s)),
        h('button', { class: 'linkbtn', onclick: async () => { const nv = prompt(lbl + ' (virgülle ayır)', v.join(', ')); if (nv === null) return; await put(`/words/${id}/info/${f}`, { value: nv.split(',').map(s => s.trim()).filter(Boolean) }); render(); } }, '✎ düzenle')));
    }
    if ((info.family || []).length || w.family_src) add(body, sec('Kelime ailesi', meta.family), h('div', { class: 'row', style: { gap: '.35rem' } },
      w.family_src ? w.family_src.split(',').map(f => h('span', { class: 'chip brand' }, f.trim())) : null,
      (info.family || []).map(f => h('span', { class: 'chip', title: f.tr || '' }, f.w + (f.tr ? ' — ' + f.tr : '')))));
    if ((info.confusables || []).length || b.confusables.length) {
      add(body, sec('Karıştırılabilecek kelimeler', meta.confusables), h('div', null,
        (info.confusables || []).map(cf => h('div', { class: 'small' }, '• ', h('b', null, cf.w), ' — ', cf.why || '')),
        b.confusables.slice(0, 8).map(cf => h('div', { class: 'small ink2' }, '• ', h('b', null, cf.display), ` (${cf.meaning}) · ${cf.kind}`))));
    }
    if (w.osym_evidence) add(body, sec('ÖSYM kanıtı'), h('div', { class: 'small' }, w.osym_evidence));
    // durum
    add(body, sec('Öğrenme durumu'), h('div', { class: 'grid2' },
      kv('Basamak', `${c.stage || 0}/6 — ${stageLabel(c.stage || 0)}`), kv('Vade', c.due_day ? fmt.dateLong(c.due_day) : '—'),
      kv('Kararlılık (S)', c.stability ? c.stability.toFixed(1) + ' gün' : '—'), kv('Şu an hatırlama', b.retrievability !== null && b.retrievability !== undefined ? fmt.pct(b.retrievability) : '—'),
      kv('Tekrar / unutma', `${c.reps || 0} / ${c.lapses || 0}`), kv('Toplam yanlış', String(c.wrong_total || 0))));
    add(body, h('div', { class: 'row', style: { marginTop: '.8rem' } },
      h('button', { class: 'btn sm', onclick: async () => { await post(`/words/${id}/mark`, { action: c.flag_hard ? 'unhard' : 'hard' }); toast('Güncellendi'); render(); } }, icon('brain'), c.flag_hard ? 'Zor işaretini kaldır' : 'Zor olarak işaretle'),
      !c.stage ? h('button', { class: 'btn sm', onclick: async () => { await post(`/words/${id}/mark`, { action: 'known' }); toast('Doğrulama turuna alındı (iki soru).'); render(); } }, icon('check'), 'Biliyorum (doğrula)') : null,
      w.status === 'active' ? h('button', { class: 'btn sm danger', onclick: async () => { if (!confirm('Askıya alınsın mı? (planlardan çıkar, silinmez)')) return; await post(`/words/${id}/mark`, { action: 'suspend' }); toast('Askıya alındı'); render(); } }, 'Askıya al')
        : h('button', { class: 'btn sm', onclick: async () => { await post(`/words/${id}/mark`, { action: 'unsuspend' }); toast('Etkinleştirildi'); render(); } }, 'Etkinleştir')));
    if (b.history.length) {
      add(body, sec('Son cevaplar'), h('table', { class: 't' }, b.history.slice(0, 15).map(e => h('tr', null, h('td', null, fmt.dt(e.ts)), h('td', null, e.exercise),
        h('td', null, e.correct ? '✓' : '✗'), h('td', { class: 'muted' }, e.error_type || ''), h('td', { class: 'num' }, fmt.sec(e.total_ms))))));
    }
  };
  render();
  return d;
}

function sec(title, m) {
  return h('div', { class: 'section-title' }, title, m && m.source && m.source !== 'user' ? h('span', { class: m.verified ? 'badge-ok' : 'badge-unv', style: { marginLeft: '.4rem' } }, m.verified ? 'doğrulandı' : 'doğrulanmamış') : null);
}
function kv(k, v) { return h('div', { class: 'note' }, h('b', null, k), v); }

function contentItem(obj, target, wid, rerender, content, onEdit) {
  const real = osymLabel(obj.source);
  const badge = real ? osymChip(obj.source) : obj.source === 'user' ? h('span', { class: 'badge-ok' }, 'senin') : (obj.verified ? h('span', { class: 'badge-ok' }, 'doğrulandı') : h('span', { class: 'badge-unv' }, 'doğrulanmamış'));
  return h('div', { class: 'content-item' + (obj.flagged ? ' flagged' : '') }, content,
    h('div', { class: 'meta' }, badge, real ? null : h('span', { class: 'small muted' }, obj.source),
      !obj.verified && obj.source !== 'user' ? h('button', { class: 'linkbtn', onclick: async () => { await post(`/words/${wid}/verify_content`, { target, target_id: obj.id }); rerender(); } }, '✓ doğru') : null,
      onEdit ? h('button', { class: 'linkbtn', onclick: onEdit }, '✎ düzenle') : null,
      obj.flagged ? h('button', { class: 'linkbtn', onclick: async () => { await post(`/words/${wid}/unflag`, { target, target_id: obj.id }); rerender(); } }, 'işareti kaldır')
        : h('button', { class: 'linkbtn bad', onclick: async () => { const note = prompt('Ne yanlış? (isteğe bağlı)') ; if (note === null) return; await post(`/words/${wid}/flag`, { target, target_id: obj.id, note }); toast('İşaretlendi; artık gösterilmeyecek.'); rerender(); } }, '⚑ bu bilgi yanlış')));
}
