// DOM yardımcıları. Kullanıcı/LLM kaynaklı metin daima textContent ile eklenir.

export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v === null || v === undefined || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
      else if (k === 'dataset') Object.assign(el.dataset, v);
      else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
      else if (k === 'svg') el.innerHTML = v; // yalnızca güvenilir, statik SVG
      else if (k === 'value') el.value = v;
      else if (k === 'checked') el.checked = !!v;
      else el.setAttribute(k, v === true ? '' : v);
    }
  }
  append(el, children);
  return el;
}

export function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

export function add(el, ...children) { return append(el, children); }

export function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }

const P = (d) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`;
export const ICONS = {
  home: P('<path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/><path d="M10 20v-6h4v6"/>'),
  bolt: P('<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>'),
  chart: P('<path d="M4 20V10"/><path d="M10 20V4"/><path d="M16 20v-7"/><path d="M22 20H2"/>'),
  list: P('<path d="M8 6h13"/><path d="M8 12h13"/><path d="M8 18h13"/><circle cx="4" cy="6" r="1"/><circle cx="4" cy="12" r="1"/><circle cx="4" cy="18" r="1"/>'),
  gear: P('<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>'),
  sun: P('<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>'),
  moon: P('<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>'),
  speaker: P('<path d="M11 5L6 9H2v6h4l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/><path d="M19 5a10 10 0 0 1 0 14"/>'),
  turtle: P('<path d="M11 5L6 9H2v6h4l5 4z"/><path d="M15.5 9.5a3.5 3.5 0 0 1 0 5"/>'),
  question: P('<circle cx="12" cy="12" r="10"/><path d="M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3"/><path d="M12 17h.01"/>'),
  check: P('<path d="M20 6L9 17l-5-5"/>'),
  x: P('<path d="M18 6L6 18M6 6l12 12"/>'),
  heart: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 21s-7.5-4.6-9.6-9.2C.9 8.5 3 5 6.5 5c2 0 3.6 1.1 5.5 3.2C13.9 6.1 15.5 5 17.5 5 21 5 23.1 8.5 21.6 11.8 19.5 16.4 12 21 12 21z"/></svg>',
  heartEmpty: P('<path d="M12 21s-7.5-4.6-9.6-9.2C.9 8.5 3 5 6.5 5c2 0 3.6 1.1 5.5 3.2C13.9 6.1 15.5 5 17.5 5 21 5 23.1 8.5 21.6 11.8 19.5 16.4 12 21 12 21z"/>'),
  plus: P('<path d="M12 5v14M5 12h14"/>'),
  flag: P('<path d="M4 22V4"/><path d="M4 4h12l-2 4 2 4H4"/>'),
  edit: P('<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>'),
  clock: P('<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>'),
  refresh: P('<path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/>'),
  download: P('<path d="M12 3v12"/><path d="M7 10l5 5 5-5"/><path d="M5 21h14"/>'),
  upload: P('<path d="M12 21V9"/><path d="M7 14l5-5 5 5"/><path d="M5 3h14"/>'),
  phone: P('<rect x="7" y="2" width="10" height="20" rx="2"/><path d="M11 18h2"/>'),
  info: P('<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>'),
  warn: P('<path d="M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>'),
  trophy: P('<path d="M8 21h8M12 17v4M7 4h10v5a5 5 0 0 1-10 0z"/><path d="M17 5h3v2a3 3 0 0 1-3 3M7 5H4v2a3 3 0 0 0 3 3"/>'),
  target: P('<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>'),
  calendar: P('<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>'),
  brain: P('<path d="M9 3a3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 2 5 3 3 0 0 0 3 3h1V3z"/><path d="M15 3a3 3 0 0 1 3 3 3 3 0 0 1 2 5 3 3 0 0 1-2 5 3 3 0 0 1-3 3h-1V3z"/>'),
  sparkle: P('<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/>'),
  book: P('<path d="M2 4h7a3 3 0 0 1 3 3v14a2 2 0 0 0-2-2H2z"/><path d="M22 4h-7a3 3 0 0 0-3 3v14a2 2 0 0 1 2-2h8z"/>'),
  search: P('<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>'),
  key: P('<circle cx="7.5" cy="15.5" r="4.5"/><path d="M10.7 12.3L21 2M16 7l3 3"/>'),
  lightbulb: P('<path d="M9 18h6M10 22h4"/><path d="M12 2a7 7 0 0 0-4 12.7V17h8v-2.3A7 7 0 0 0 12 2z"/>'),
  eye: P('<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>'),
  back: P('<path d="M15 18l-6-6 6-6"/>'),
  coffee: P('<path d="M17 8h1a4 4 0 0 1 0 8h-1"/><path d="M3 8h14v9a4 4 0 0 1-4 4H7a4 4 0 0 1-4-4z"/><path d="M6 2v3M10 2v3M14 2v3"/>'),
};
export const FLAME = '<svg viewBox="0 0 24 24"><path fill="#ff9f1c" d="M12 2c1 4 6 6 6 12a6 6 0 0 1-12 0c0-3 2-5 3-6 0 2 1 3 2 3 0-3-1-6 1-9z"/><path fill="#ffd34d" d="M12 13c1 1.5 3 2.5 3 4.5a3 3 0 0 1-6 0c0-1.5 1-2.5 1.5-3 .2 1 .8 1.5 1.5 1.5 0-1-.4-2 0-3z"/></svg>';

export function icon(name, cls) {
  const s = h('span', { class: 'i ' + (cls || ''), svg: ICONS[name] || '' });
  s.style.display = 'inline-flex';
  return s;
}

// gerçek ÖSYM cümlesi: kaynak 'osym:YDS 2013 İlkbahar · 1. soru'
export function osymLabel(source) {
  return typeof source === 'string' && source.startsWith('osym:') ? source.slice(5) : null;
}
export function osymChip(source) {
  return h('span', { class: 'chip brand osym-chip', title: 'Gerçek ÖSYM sınav cümlesi (Türkçe çevirisi yapay zekâ ile yazıldı)' },
    'ÖSYM · ' + osymLabel(source));
}

export const fmt = {
  pct: (x, d = 0) => (x === null || x === undefined || isNaN(x)) ? '—' : '%' + (x * 100).toFixed(d),
  num: (x, d = 0) => (x === null || x === undefined || isNaN(x)) ? '—' : Number(x).toLocaleString('tr-TR', { maximumFractionDigits: d, minimumFractionDigits: d }),
  sec: (ms) => (ms === null || ms === undefined) ? '—' : (ms / 1000).toLocaleString('tr-TR', { maximumFractionDigits: 1 }) + ' sn',
  date: (s) => { if (!s) return '—'; const d = new Date(s.length <= 10 ? s + 'T12:00:00' : s); return d.toLocaleDateString('tr-TR', { day: 'numeric', month: 'short' }); },
  dateLong: (s) => { if (!s) return '—'; const d = new Date(s.length <= 10 ? s + 'T12:00:00' : s); return d.toLocaleDateString('tr-TR', { day: 'numeric', month: 'long', year: 'numeric' }); },
  time: (s) => { if (!s) return '—'; return new Date(s).toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' }); },
  dt: (s) => { if (!s) return '—'; return new Date(s).toLocaleString('tr-TR', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }); },
};

let toastWrap;
export function toast(msg, kind = '', ms = 3500) {
  if (!toastWrap) { toastWrap = h('div', { class: 'toast-wrap' }); document.body.appendChild(toastWrap); }
  const t = h('div', { class: 'toast ' + kind }, msg);
  toastWrap.appendChild(t);
  setTimeout(() => t.remove(), ms);
}

export function overlay(kind, content, onClose) {
  const scrim = h('div', { class: 'scrim' });
  const box = h('div', { class: kind });
  const close = () => { scrim.remove(); box.remove(); document.removeEventListener('keydown', esc); onClose && onClose(); };
  const esc = (e) => { if (e.key === 'Escape') close(); };
  scrim.addEventListener('click', close);
  document.addEventListener('keydown', esc);
  box.appendChild(h('button', { class: 'iconbtn close-x', onclick: close, 'aria-label': 'Kapat', svg: ICONS.x }));
  append(box, [content]);
  document.body.append(scrim, box);
  return { close, box };
}
export const modal = (c, f) => overlay('modal', c, f);
export const drawer = (c, f) => overlay('drawer', c, f);

export function debounce(fn, ms) {
  let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

let speaking = null;   // aynı anda tek okuma: yenisi öncekini keser

export function speak(text, slow = false, maxMs = 3000) {
  // önce sunucu SAPI sesi (çevrimdışı), olmazsa tarayıcı sesi; okuma bitince (en geç maxMs) çözülen söz döner
  return new Promise((resolve) => {
    let done = false;
    const fin = () => { if (!done) { done = true; resolve(); } };
    setTimeout(fin, maxMs);
    try { if (speaking) speaking.pause(); } catch (e) { /* yok */ }
    const a = new Audio(`/api/tts?text=${encodeURIComponent(text)}&slow=${slow ? 1 : 0}`);
    speaking = a;
    a.onended = fin;
    a.play().catch(() => {
      try {
        const u = new SpeechSynthesisUtterance(text);
        u.lang = 'en-US'; u.rate = slow ? 0.7 : 0.95;
        const v = speechSynthesis.getVoices().find(v => v.lang && v.lang.startsWith('en'));
        if (v) u.voice = v;
        u.onend = fin; u.onerror = fin;
        speechSynthesis.cancel(); speechSynthesis.speak(u);
      } catch (e) { fin(); }
    });
  });
}

export function highlight(sentence, form) {
  // cümlede hedef biçimi <mark> ile vurgular (güvenli: text node'larla)
  const frag = document.createDocumentFragment();
  if (!form) { frag.appendChild(document.createTextNode(sentence)); return frag; }
  const parts = form.includes('...') ? form.split('...').map(s => s.trim()).filter(Boolean) : [form];
  let rest = sentence;
  for (const p of parts) {
    const re = new RegExp('(^|[^A-Za-z])(' + p.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')(?![A-Za-z])', 'i');
    const m = rest.match(re);
    if (!m) continue;
    const start = m.index + m[1].length;
    frag.appendChild(document.createTextNode(rest.slice(0, start)));
    frag.appendChild(h('mark', null, rest.slice(start, start + m[2].length)));
    rest = rest.slice(start + m[2].length);
  }
  frag.appendChild(document.createTextNode(rest));
  return frag;
}

export function blankify(sentence) {
  const frag = document.createDocumentFragment();
  const parts = sentence.split('----');
  parts.forEach((p, i) => {
    frag.appendChild(document.createTextNode(p));
    if (i < parts.length - 1) frag.appendChild(h('span', { class: 'blank' }, '?'));
  });
  return frag;
}
