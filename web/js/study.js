// Çalışma ekranı: alıştırma çizicileri, klavye, zamanlama, geri bildirim.
import { get, post } from './api.js';
import { h, add, clear, icon, ICONS, fmt, toast, speak, highlight, blankify, FLAME, osymLabel, osymChip } from './util.js';
import { plantSVG, stageLabel } from './plant.js';
import { setActiveStudy, clearActiveStudy } from './nav.js';
import * as sfx from './sfx.js';

const IDLE_MS = 60000;

// ------------------------------------------------------------ aktif süre izleyici
class ActiveTimer {
  constructor(onBeat) {
    this.total = 0; this.q = 0; this.firstKey = null; this.pending = 0;
    this.last = performance.now(); this.lastInput = Date.now(); this.onBeat = onBeat;
    this.onInput = () => { this.lastInput = Date.now(); };
    ['keydown', 'pointerdown', 'pointermove', 'touchstart', 'wheel'].forEach(e => window.addEventListener(e, this.onInput, { passive: true }));
    this.iv = setInterval(() => this.tick(), 1000);
    this.beat = setInterval(() => this.flush(), 15000);
  }
  active() { return document.visibilityState === 'visible' && document.hasFocus() && (Date.now() - this.lastInput) < IDLE_MS; }
  tick() {
    const now = performance.now();
    const d = Math.min(now - this.last, 2000);
    this.last = now;
    if (this.active()) { this.total += d; this.q += d; this.pending += d; }
  }
  startQuestion() { this.tick(); this.q = 0; this.firstKey = null; this.qStart = performance.now(); this.lastInput = Date.now(); }
  markKey() { if (this.firstKey === null) { this.tick(); this.firstKey = Math.round(this.q + (performance.now() - this.last)); } }
  questionMs() { this.tick(); return Math.round(this.q); }
  flush() { this.tick(); if (this.pending > 500) { const p = Math.round(this.pending); this.pending = 0; this.onBeat(p); } }
  stop() {
    this.flush();
    clearInterval(this.iv); clearInterval(this.beat);
    ['keydown', 'pointerdown', 'pointermove', 'touchstart', 'wheel'].forEach(e => window.removeEventListener(e, this.onInput));
  }
}

// ------------------------------------------------------------ oturum
export async function runStudy(root, opts) {
  const { mode = 'daily', limit = null, onExit, placement = false, partId = null, partIds = null } = opts;
  document.body.classList.add('studying');
  clear(root);
  const top = h('div', { class: 'study-top' });
  const closeBtn = h('button', { class: 'close', title: 'Oturumu bitir (Esc)', svg: ICONS.x });
  const label = h('div', { class: 'study-label' });
  const bar = h('div');
  const progress = h('div', { class: 'progress' }, bar);
  const counters = h('div', { class: 'counters' });
  add(top, closeBtn, label, progress, counters);
  const stage = h('div');
  add(root, top, stage);

  let sid = null, pid = null, current = null, keyHandler = null, finished = false, settings = opts.settings || {};
  sfx.configure(settings);
  let answers = 0, correct = 0, xp = 0, lastBreakAt = 0;
  const timer = new ActiveTimer((ms) => { if (sid) post(`/session/${sid}/heartbeat`, { active_ms: ms, device: device() }).catch(() => {}); });
  const maxMin = (settings.max_session_minutes || 20);

  const ep = placement ? {
    next: () => get(`/placement/${pid}/next`),
    answer: (b) => post(`/placement/${pid}/answer`, b),
    finish: () => post(`/placement/${pid}/finish`),
  } : {
    next: () => get(`/session/${sid}/next`),
    answer: (b) => post(`/session/${sid}/answer`, b),
    finish: () => post(`/session/${sid}/finish`),
  };

  const cleanup = () => {
    timer.stop();
    if (keyHandler) document.removeEventListener('keydown', keyHandler);
    keyHandler = null;
    document.removeEventListener('keydown', escHandler);
    document.body.classList.remove('studying');
    clearActiveStudy(handle);
  };
  // başka ekrana geçilirse (geri tuşu vb.) oturumun zamanlayıcı ve klavye dinleyicileri kapanır
  const handle = { cleanup: () => { if (!finished && sid) post('/session/' + sid + '/finish').catch(() => {}); finished = true; cleanup(); } };
  setActiveStudy(handle);

  const exit = async (summary) => {
    if (finished) return;
    finished = true;
    let res = summary;
    if (!res) { try { res = await ep.finish(); } catch (e) { res = null; } }
    if (keyHandler) document.removeEventListener('keydown', keyHandler);
    timer.stop();
    if (placement) { cleanup(); onExit && onExit(res); return; }
    showSummary(res && res.summary ? res.summary : null);
  };
  closeBtn.onclick = () => {
    if (finished) { cleanup(); onExit && onExit(null); return; }
    if (answers > 0 && !confirm('Oturumu bitirmek istiyor musun? İlerlemen kaydedildi.')) return;
    exit();
  };
  const escHandler = (e) => { if (e.key === 'Escape' && document.body.classList.contains('studying') && !document.querySelector('.modal')) closeBtn.click(); };
  document.addEventListener('keydown', escHandler);

  const setProgress = (p) => {
    if (!p) return;
    bar.style.width = Math.round((p.fraction || 0) * 100) + '%';
    clear(counters);
    if (p.lives !== null && p.lives !== undefined) {
      const hearts = h('span', { class: 'hearts' });
      for (let i = 0; i < 3; i++) hearts.appendChild(h('span', { style: { color: i < p.lives ? 'var(--bad)' : 'var(--line-2)' }, svg: i < p.lives ? ICONS.heart : ICONS.heartEmpty }));
      counters.appendChild(hearts);
    }
    add(counters, h('span', { title: 'Doğru' }, '✓ ', String(p.correct ?? correct)));
    if ((p.streak || 0) >= 3) add(counters, h('span', { class: 'flame' + (p.streak % 5 === 0 ? ' combo' : ''), title: 'Doğru serisi', svg: FLAME }), h('span', null, String(p.streak)));
  };

  // alıştırma türü → çizici (fonksiyon bildirimleri yukarı taşınır)
  const RENDER = {
    intro: renderIntro,
    intervention: renderIntervention,
    tiles: renderTiles,
    typing: renderTyping,
    look_write: renderLookWrite,
    match: renderMatch,
  };

  // ---------------------------------------------------------- başlat
  try {
    if (placement) {
      const r = await post('/placement/start');
      pid = r.placement_id;
    } else {
      const r = await post('/session/start', { mode, limit, device: device(), part_id: partId, part_ids: partIds });
      sid = r.session_id;
      label.textContent = r.label || '';
      if (!r.reviews && !r.new && !r.extra) {
        timer.stop();
        return showNothing(r);
      }
    }
    const first = await ep.next();
    show(first);
  } catch (e) {
    clear(stage);
    add(stage, h('div', { class: 'notice bad' }, icon('warn'), e.message));
  }

  function device() { return matchMedia('(max-width: 760px)').matches ? 'mobile' : 'desktop'; }

  // ---------------------------------------------------------- öğe gösterimi
  function show(item) {
    if (finished) return;  // oturum kapandıktan sonra gecikmeli zamanlayıcılar ekrana yazmaz
    if (!item || item.type === 'done' || item.type === 'placement_done') return exit(item);
    if (item.type === 'error') { add(stage, h('div', { class: 'notice bad' }, item.message || 'Hata')); return; }
    current = item;
    if (keyHandler) document.removeEventListener('keydown', keyHandler);
    keyHandler = null;
    setProgress(item.session_progress);
    if (item.placement) {
      bar.style.width = Math.round(100 * Math.min(1, Math.max(item.placement.item / item.placement.max, item.placement.elapsed_s / item.placement.max_s))) + '%';
    }
    // mola kontrolü
    if (!placement && timer.total - lastBreakAt > maxMin * 60000 && item.type !== 'intro') {
      lastBreakAt = timer.total;
      return showBreak(item);
    }
    clear(stage);
    timer.startQuestion();
    const R = RENDER[item.type] || renderChoice;
    R(item);
  }

  function submit(body, ui) {
    body.token = current.token;
    body.total_ms = timer.questionMs();
    body.first_key_ms = timer.firstKey ?? body.total_ms;
    body.session_active_ms = Math.round(timer.total);
    body.device = device();
    if (keyHandler) { document.removeEventListener('keydown', keyHandler); keyHandler = null; }
    const item = current;
    return ep.answer(body).then(res => { onResult(item, res, body, ui); }).catch(e => {
      toast(e.message, 'warn');
    });
  }

  // ---------------------------------------------------------- sonuç
  function onResult(item, res, body, ui) {
    if (item.type === 'intro' || item.type === 'intervention') { show(res.next); return; }
    if (item.type === 'match') {
      const n = (item.targets || []).length || 1;
      const bad = Object.keys(body.mistakes || {}).filter(k => (item.targets || []).includes(+k) && body.mistakes[k] > 0).length;
      answers += n; correct += n - bad;
      if (res.xp !== undefined) { const gain = res.xp - xp; xp = res.xp; if (gain > 0) popXP(gain); }
      if (res.progress) setProgress(res.progress);
      setTimeout(() => { if (!finished && current === item) show(res.next); }, 650);
      return;
    }
    if (placement) {
      // seviye testinde geri bildirim beklenmez: kısa vurgu ve otomatik geçiş
      answers++;
      if (res.correct) correct++;
      ui && ui.reveal && ui.reveal({ correct_index: res.correct_index, correct: res.correct }, body);
      setTimeout(() => show(res.next), res.correct ? 350 : 850);
      return;
    }
    answers++;
    if (res.correct) correct++;
    if (res.xp !== undefined) { const gain = res.xp - xp; xp = res.xp; if (gain > 0 && res.correct) popXP(gain); }
    if (res.progress) setProgress(res.progress);
    if (res.fatigue) toast(res.fatigue, 'warn', 7000);
    if (res.verify_result === 'verified') toast('Doğrulandı: 4 kontrolün hepsini geçtin; kelime birkaç gün sonra kısa bir tekrarla gelecek.', '', 3500);
    if (res.verify_result === 'failed') toast('Doğrulanamadı: kelime normal öğrenmeye alındı.', 'warn', 3000);
    ui && ui.reveal && ui.reveal(res, body);
    // ses: doğru / yazım hatası / yanlış; bitki büyüdü, kelime çiçek açtı, 5'li seri
    if (res.correct) (res.result === 'correct' ? sfx.correct : sfx.almost)(); else sfx.wrong();
    if (res.learned_now) setTimeout(sfx.bloom, 260);
    else if (res.stage_after > res.stage_before) setTimeout(sfx.levelUp, 240);
    if (res.correct && res.progress && res.progress.streak && res.progress.streak % 5 === 0) setTimeout(sfx.combo, 420);
    // doğru cevap her bölümde sesli tekrar edilir (kelimeyi duymak hafızayı güçlendirir); ding/bonk'tan hemen sonra
    const spoke = res.say && settings.speak_answers !== false
      ? new Promise((r) => setTimeout(() => speak(res.say).then(r), 280)) : Promise.resolve();
    if (res.stage_after !== undefined && res.stage_after !== res.stage_before) growPlant(res.stage_after, res.stage_after > res.stage_before);
    // boşluk doldurmadan sonra her zaman 'gerçek cevap' paneli (çeviri + neden bu kelime); Enter/Boşluk ile geçilir
    const explained = !!res.explain;
    const fb = explained ? explainPanel(item, res, body) : feedback(item, res, body);
    if (fb) stage.querySelector('.ex-card').appendChild(fb.el);
    const next = () => show(res.next);
    if (res.correct && res.result === 'correct' && !item.compare && !explained) {
      const delay = res.learned_now ? 1400 : (res.stage_after > res.stage_before ? 900 : 600);
      // kelime okunmadan sonraki soruya geçme (okuma en geç 3 sn)
      Promise.all([new Promise((r) => setTimeout(r, delay)), spoke]).then(() => { if (!finished && current === item) next(); });
    } else {
      const go = () => { document.removeEventListener('keydown', kh); next(); };
      const kh = (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); }
      };
      keyHandler = kh;
      setTimeout(() => document.addEventListener('keydown', kh), 250);
      fb && fb.cont && (fb.cont.onclick = go);
      if (res.correct && !explained) setTimeout(() => { if (current === item && keyHandler === kh) go(); }, 2200);
    }
  }

  function growPlant(stageNow, up) {
    const wrap = stage.querySelector('.plant-wrap');
    if (!wrap) return;
    wrap.innerHTML = plantSVG(stageNow, 44, !up);
    const svg = wrap.querySelector('svg');
    if (svg && up) { svg.classList.add('grow'); wrap.title = stageLabel(stageNow); }
    if (up) {
      const card = stage.querySelector('.ex-card');
      if (card) card.appendChild(h('div', { class: 'pop-xp', style: { top: '64px', color: 'var(--leaf-2)' } }, stageLabel(stageNow)));
    }
  }

  function popXP(gain) {
    const card = stage.querySelector('.ex-card');
    if (!card) return;
    card.appendChild(h('div', { class: 'pop-xp' }, '+' + gain));
  }

  // ---------------------------------------------------------- efektler
  const calm = () => matchMedia('(prefers-reduced-motion: reduce)').matches;

  // doğru cevapta küçük parıltı patlaması (kartın içinde, hedef öğenin ortasından)
  function burst(anchor, color = 'var(--good)', n = 14) {
    const cardEl = stage.querySelector('.ex-card');
    if (calm() || !cardEl || !anchor) return;
    const cr = cardEl.getBoundingClientRect(), ar = anchor.getBoundingClientRect();
    const x = ar.left + ar.width / 2 - cr.left, y = ar.top + ar.height / 2 - cr.top;
    for (let i = 0; i < n; i++) {
      const a = (Math.PI * 2 * i) / n + Math.random() * 0.5, d = 38 + Math.random() * 48;
      const p = h('span', { class: 'burst', style: { left: x + 'px', top: y + 'px', background: i % 3 ? color : 'var(--brand)' } });
      p.style.setProperty('--dx', (Math.cos(a) * d).toFixed(1) + 'px');
      p.style.setProperty('--dy', (Math.sin(a) * d).toFixed(1) + 'px');
      cardEl.appendChild(p);
      setTimeout(() => p.remove(), 800);
    }
  }

  // boşluk doldurma: doğru kelime boşluğa düşerek yerleşir; yanlışta seçilen kelime üstü çizili kalır
  function fillBlanks(sentEl, answer, ok, chosen) {
    const blanks = sentEl ? [...sentEl.querySelectorAll('.blank')] : [];
    if (!blanks.length || !answer) return;
    const split = (t) => (blanks.length > 1 && t && t.includes('/') ? t.split('/').map(s => s.trim()) : [t]);
    const right = split(answer), was = split(chosen);
    blanks.forEach((b, k) => {
      clear(b);
      const r = right[k] ?? right[0], w = was[k] ?? was[0];
      if (!ok && w && w !== r) b.appendChild(h('span', { class: 'was' }, w));
      b.appendChild(document.createTextNode(r));
      b.classList.add('filled');
      b.style.animationDelay = (k * 120 + (ok ? 0 : 220)) + 'ms';
    });
    if (ok) setTimeout(() => burst(blanks[0]), 120);
  }

  // yazma / harflerden kurma: doğru kelime harf harf döner (tutan harf yeşil, hatalı kırmızı)
  function revealWord(afterEl, word, typed) {
    if (!afterEl || !word) return;
    const t = (typed || '').trim().toLowerCase();
    const row = h('div', { class: 'reveal-word', 'aria-label': 'Doğrusu: ' + word });
    [...word].forEach((ch, i) => {
      const sp = ch === ' ';
      const s = h('span', { class: sp ? 'sp' : (t[i] === ch.toLowerCase() ? 'ok' : 'miss') }, sp ? '' : ch);
      s.style.animationDelay = (i * 55) + 'ms';
      row.appendChild(s);
    });
    afterEl.insertAdjacentElement('afterend', row);
  }

  function trHighlight(text, hit) {
    if (!hit) return document.createTextNode(text);
    const f = document.createDocumentFragment();
    f.appendChild(document.createTextNode(text.slice(0, hit[0])));
    f.appendChild(h('mark', null, text.slice(hit[0], hit[1])));
    f.appendChild(document.createTextNode(text.slice(hit[1])));
    return f;
  }

  // 'gerçek cevap' paneli: boşluk doldurmadan sonra her zaman (doğru ya da yanlış); Enter/Boşluk ile geçilir
  function explainPanel(item, res, body) {
    const x = res.explain;
    const ok = res.correct;
    const chosen = body.choice !== undefined && body.choice !== null ? item.options[body.choice] : null;
    const el = h('div', { class: 'feedback explain ' + (ok ? (res.result === 'correct' ? 'good' : 'warn') : 'bad') });
    const head = ok ? 'Doğru!' : (res.result === 'timeout' ? 'Süre doldu — gerçek cevap:' : 'Gerçek cevap:');
    el.appendChild(h('div', { class: 'title' }, icon(ok ? 'check' : 'x'), head, h('span', { class: 'answer' }, x.answer),
      x.meaning ? h('span', { class: 'ink2 mean' }, '= ' + x.meaning) : null));
    if (x.full_sentence) el.appendChild(h('div', { class: 'ex-sent' }, highlight(x.full_sentence, x.answer.includes('/') ? null : x.answer)));
    if (x.translation) el.appendChild(h('div', { class: 'ex-tr' }, h('span', { class: 'lbl-cap' }, 'Çeviri '), trHighlight(x.translation, x.tr_hit)));
    const why = h('ul', { class: 'why' });
    if (x.meaning) why.appendChild(h('li', null, h('b', null, 'Anlam: '), `boşluğa “${x.meaning}” anlamı geliyor`, x.tr_hit ? ' (çeviride vurgulu).' : '.'));
    if (x.form_cue) why.appendChild(h('li', null, h('b', null, 'Biçim: '), x.form_cue));
    if (x.note) why.appendChild(h('li', null, h('b', null, 'İpucu: '), x.note));
    if (why.children.length) el.appendChild(h('div', null, h('div', { class: 'lbl-cap' }, 'Neden ', h('span', { class: 'kw' }, `“${x.answer}”`), '?'), why));
    const others = x.options.filter(o => !o.correct);
    if (others.length) {
      el.appendChild(h('div', null, h('div', { class: 'lbl-cap' }, 'Diğer şıklar'),
        h('div', { class: 'opt-means' }, others.map(o => h('div', { class: 'om' + (o.text === chosen ? ' picked' : '') },
          h('b', null, o.text), o.meaning ? h('span', null, ' = ' + o.meaning) : h('span', { class: 'muted' }, ' (liste dışı)')))),
        x.same_kind ? h('div', { class: 'small muted' }, 'Şıkların hepsi aynı türde; soruyu ayıran anlam.') : null));
    }
    if (!ok && res.feedback && res.feedback.mnemonic) {
      el.appendChild(h('div', { class: 'mem-box small' }, h('div', { class: 'mem-head' }, icon('lightbulb'), 'Hafıza ipucu'), res.feedback.mnemonic.text));
    }
    const row = h('div', { class: 'row' });
    if (!ok && res.event_id && !placement && res.result !== 'timeout') {
      const ov = h('button', { class: 'btn sm' }, icon('check'), 'Aslında biliyordum');
      ov.onclick = async () => {
        ov.disabled = true;
        try {
          const r = await post(`/session/${sid}/override`, { event_id: res.event_id });
          toast(r.message || 'Düzeltildi');
          if (r.ok) { el.classList.remove('bad'); el.classList.add('warn'); }
        } catch (e) { toast(e.message, 'warn'); }
      };
      row.appendChild(ov);
    }
    row.appendChild(h('span', { class: 'spacer' }));
    const cont = h('button', { class: 'btn primary' }, 'Devam et ', h('kbd', null, 'Enter'));
    row.appendChild(cont);
    el.appendChild(row);
    return { el, cont };
  }

  function feedback(item, res, body) {
    if (res.correct && res.result === 'correct' && !item.compare) {
      if (res.learned_now) {
        const el = h('div', { class: 'feedback good' }, h('div', { class: 'title' }, icon('sparkle'), 'Kelime çiçek açtı — tamamen öğrenildi!'));
        return { el };
      }
      return null;
    }
    const f = res.feedback || {};
    const cls = res.correct ? (res.result === 'correct' ? 'good' : 'warn') : 'bad';
    const el = h('div', { class: 'feedback ' + cls });
    let title;
    if (res.result === 'typo') title = 'Yazım hatası — anlamı doğru bildin';
    else if (res.result === 'form') title = 'Aynı aileden başka bir biçim yazdın';
    else if (res.correct) title = 'Doğru';
    else if (res.result === 'timeout') title = 'Süre doldu';
    else if (res.result === 'dontknow') title = 'Sorun değil, şimdi öğren:';
    else title = 'Doğrusu:';
    el.appendChild(h('div', { class: 'title' }, icon(res.correct ? 'check' : 'x'), title,
      res.error_type && !res.correct ? h('span', { class: 'chip bad' }, res.error_type) : null));
    el.appendChild(h('div', { class: 'row' }, h('span', { class: 'answer' }, f.display || ''), h('span', { class: 'ink2' }, '= ' + (f.meaning || ''))));
    if (f.synonyms && f.synonyms.length) el.appendChild(h('div', { class: 'small ink2' }, h('b', null, '≈ '), f.synonyms.join(', ')));
    if (res.confused) {
      el.appendChild(h('div', { class: 'small ink2' }, 'Seçtiğin ', h('b', null, res.confused.display), ' = ', res.confused.meaning));
    }
    if (item.compare) {
      el.appendChild(h('div', { class: 'grid2' }, item.compare.map(c => h('div', { class: 'note' }, h('b', null, c.display), c.meaning))));
    }
    if (f.example && !res.correct) {
      el.appendChild(h('div', { class: 'small' }, highlight(f.example.en, f.example.form)));
      if (f.example.tr) el.appendChild(h('div', { class: 'small ink2' }, f.example.tr));
    }
    if (f.mnemonic && !res.correct) {
      el.appendChild(h('div', { class: 'mem-box small' }, h('div', { class: 'mem-head' }, icon('lightbulb'), 'İpucu'), f.mnemonic.text));
    }
    const row = h('div', { class: 'row' });
    let cont = null;
    if (!res.correct && res.event_id && !placement && res.result !== 'timeout') {
      const ov = h('button', { class: 'btn sm' }, icon('check'), 'Aslında biliyordum');
      ov.onclick = async () => {
        ov.disabled = true;
        try {
          const r = await post(`/session/${sid}/override`, { event_id: res.event_id });
          toast(r.message || 'Düzeltildi');
          if (r.ok) { el.classList.remove('bad'); el.classList.add('warn'); }
        } catch (e) { toast(e.message, 'warn'); }
      };
      row.appendChild(ov);
    }
    row.appendChild(h('span', { class: 'spacer' }));
    cont = h('button', { class: 'btn primary' }, 'Devam et ', h('kbd', null, 'Enter'));
    row.appendChild(cont);
    el.appendChild(row);
    return { el, cont };
  }

  // ---------------------------------------------------------- ortak parçalar
  function card(item, ...children) {
    const head = h('div', { class: 'ex-head' },
      h('span', { class: 'ex-type' }, item.type_label || ''),
      item.verify ? h('span', { class: 'chip info' }, 'beyan doğrulanıyor') : null,
      item.kind === 'phrasal' ? h('span', { class: 'chip' }, 'öbek fiil') : null,
      h('span', { class: 'plant-wrap', title: stageLabel(item.stage), svg: plantSVG(item.stage || 0, 44) }));
    const c = h('div', { class: 'ex-card' }, head, ...children);
    stage.appendChild(c);
    return c;
  }

  function dontKnowBtn(onClick) {
    return h('div', { class: 'side-actions' },
      h('button', { class: 'dontknow', onclick: onClick, title: 'Bilmiyorum (0)' }, h('span', { svg: ICONS.question }), 'Bilmiyorum'));
  }

  // ---------------------------------------------------------- çiziciler
  function renderIntro(item) {
    const audio = h('div', { class: 'audio' },
      h('button', { title: 'Dinle (Boşluk)', onclick: () => speak(item.display), svg: ICONS.speaker }),
      h('button', { title: 'Yavaş dinle', onclick: () => speak(item.display, true), svg: ICONS.turtle }));
    const left = h('div', null,
      h('div', { class: 'lbl-cap' }, 'İngilizce', item.book ? h('span', { class: 'chip book' }, item.book) : null),
      h('div', { class: 'row' }, h('div', { class: 'intro-word' }, item.display), audio),
      h('div', { class: 'muted', style: { fontWeight: 800 } }, item.pos || '', item.level ? ' · ' + item.level : ''),
      synChips(item.synonyms, true),
      item.variants && item.variants.length ? h('div', { class: 'small ink2' }, 'ayrıca: ', h('b', { class: 'kw' }, item.variants.join(', '))) : null,
      item.usage ? h('div', null, h('span', { class: 'chip usage' }, item.usage)) : null,
      item.definition ? h('div', { class: 'small muted', style: { fontStyle: 'italic' } }, item.definition) : null,
      h('div', { class: 'lbl-cap' }, 'Türkçe'),
      h('div', { class: 'intro-meaning' }, item.meaning),
      item.senses && item.senses.length > 1 ? h('div', { class: 'small ink2', style: { marginTop: '.3rem' } },
        item.senses.map(s => h('div', null, '• ', h('b', null, s.pos ? s.pos + ': ' : ''), s.tr))) : null,
      item.example ? h('div', null, h('div', { class: 'lbl-cap' }, 'Örnek cümle', ' ', unverified(item.example)),
        h('div', { class: 'sentence', style: { fontSize: '1.1rem', margin: '.4rem 0' } }, highlight(item.example.en, item.example.form),
          item.example.tr ? h('span', { class: 'tr' }, item.example.tr) : null),
        item.example.source !== 'user' ? h('button', { class: 'linkbtn bad', onclick: async (ev) => {
          await post(`/words/${item.word_id}/flag`, { target: 'example', target_id: item.example.id, note: 'çalışırken işaretlendi' });
          ev.target.textContent = '⚑ işaretlendi'; ev.target.disabled = true;
        } }, '⚑ bu cümle/çeviri yanlış') : null) : null,
    );
    const memEl = h('div');
    const renderMem = () => {
      clear(memEl);
      if (item.mnemonic) {
        const kindLbl = { association: 'Hafıza ipucu (mem)', etymology: 'Kök / köken', user: 'Senin mem\'in' }[item.mnemonic.kind] || 'Hafıza ipucu';
        memEl.appendChild(h('div', { class: 'mem-box' }, h('div', { class: 'mem-head' }, icon('lightbulb'),
          item.mnemonic.source === 'user' ? 'Senin mem\'in' : kindLbl, ' ', unverified(item.mnemonic)), item.mnemonic.text,
          item.mnemonic.source !== 'user' ? h('div', null, h('button', {
            class: 'linkbtn bad', onclick: async () => {
              await post(`/words/${item.word_id}/flag`, { target: 'mnemonic', target_id: item.mnemonic.id, note: 'çalışırken işaretlendi' });
              toast('İşaretlendi: bu ipucu bir daha gösterilmeyecek.');
            }
          }, '⚑ bu bilgi yanlış')) : null));
      }
      const ta = h('textarea', { rows: 2, placeholder: 'Kendi mem\'ini yaz (seninki her zaman önceliklidir)…', style: { width: '100%', marginTop: '.6rem' } });
      const save = h('button', { class: 'btn sm', onclick: async () => {
        if (!ta.value.trim()) return;
        await post(`/words/${item.word_id}/mnemonic`, { text: ta.value.trim() });
        item.mnemonic = { text: ta.value.trim(), source: 'user', kind: 'user', verified: 1 };
        toast('Mem kaydedildi.'); renderMem();
      } }, 'Mem\'imi kaydet');
      add(memEl, h('details', { style: { marginTop: '.5rem' } }, h('summary', { class: 'small muted', style: { cursor: 'pointer', fontWeight: 800 } }, 'Kendi mem\'ini ekle'), ta, save));
    };
    renderMem();
    const right = h('div', null, memEl,
      item.family && item.family.length ? h('div', null, h('div', { class: 'lbl-cap' }, 'Kelime ailesi'),
        h('div', { class: 'row', style: { gap: '.35rem' } }, item.family.map(f => h('span', { class: 'chip' }, f)))) : null,
      item.osym ? h('div', { class: 'small muted', style: { marginTop: '.6rem' } }, icon('target'), ' ÖSYM: ', item.osym) : null);
    const knowBtn = item.reintro ? null : h('button', { class: 'btn' }, icon('check'), 'Bunu zaten biliyorum');
    const contBtn = h('button', { class: 'btn primary lg' }, 'Devam et ', h('kbd', null, 'Enter'));
    const c = card(item, h('div', { class: 'intro-grid' }, left, right),
      h('div', { class: 'row', style: { marginTop: '1.2rem' } }, item.pack ? h('span', { class: 'muted small' }, `Paket: ${item.pack.index}/${item.pack.size}`) : null,
        h('span', { class: 'spacer' }), knowBtn, contBtn));
    if (knowBtn) knowBtn.onclick = () => submit({ already_known: true });
    contBtn.onclick = () => submit({});
    keyHandler = (e) => {
      if (e.target.tagName === 'TEXTAREA') return;
      if (e.key === 'Enter') { e.preventDefault(); submit({}); }
      else if (e.key === ' ') { e.preventDefault(); speak(item.display); }
    };
    document.addEventListener('keydown', keyHandler);
    if (settings.autoplay !== false) setTimeout(() => speak(item.display), 250);
  }

  function renderIntervention(item) {
    const secs = (item.sections || []).map(s => {
      if (s.kind === 'compare') {
        return h('div', { class: 'note' }, h('b', null, s.title), h('div', { class: 'grid2', style: { marginTop: '.3rem' } },
          h('div', null, h('b', null, s.a.display), ' = ', s.a.meaning), h('div', null, h('b', null, s.b.display), ' = ', s.b.meaning,
            s.b.example ? h('div', { class: 'small ink2' }, s.b.example) : null)), s.tip ? h('div', { class: 'small' }, s.tip) : null);
      }
      if (s.kind === 'examples') {
        return h('div', { class: 'note' }, h('b', null, s.title), (s.items || []).map(e => h('div', { class: 'small', style: { marginTop: '.3rem' } },
          highlight(e.en, e.form), e.tr ? h('div', { class: 'ink2' }, e.tr) : null)));
      }
      return h('div', { class: s.kind === 'mnemonic' || s.kind === 'etymology' ? 'mem-box' : 'note' },
        h('div', { class: 'mem-head' }, icon('lightbulb'), s.title), s.text);
    });
    const cont = h('button', { class: 'btn primary lg' }, 'Anladım, devam ', h('kbd', null, 'Enter'));
    card(item, h('div', { class: 'notice warn' }, icon('warn'), h('div', null, h('b', null, `İnatçı kelime: ${item.display}`),
      ` — ${item.wrong_total} kez yanlış. Farklı bir yoldan deneyelim.`)),
      h('div', { class: 'prompt-mid' }, item.display), h('div', { class: 'prompt-pos' }, item.meaning),
      h('div', { class: 'col' }, secs), h('div', { class: 'row', style: { marginTop: '1rem' } }, h('span', { class: 'spacer' }), cont));
    cont.onclick = () => submit({});
    keyHandler = (e) => { if (e.key === 'Enter') { e.preventDefault(); submit({}); } };
    document.addEventListener('keydown', keyHandler);
  }

  function renderChoice(item) {
    const t = item.type;
    const parts = [];
    let sentEl = null;   // boşluklu cümle (cevapta kelime boşluğa yerleşir)
    let listenWord = null;   // dinle ve seç: cevaptan sonra kelimenin yazılışı balonun altında belirir
    let synEl = null;        // eş anlamlısından bul: cevaptan sonra eş anlamlıların Türkçesi açılır
    if (t === 'cloze' || t === 'osym') {
      if (t === 'osym') parts.push(h('div', { class: 'chip brand' }, item.source_label || 'ÖSYM'));
      else if (osymLabel(item.source)) parts.push(osymChip(item.source));
      sentEl = h('div', { class: 'sentence' }, blankify(item.sentence));
      parts.push(sentEl);
    } else if (t === 'context') {
      parts.push(h('div', { class: 'prompt-pos', style: { marginTop: '1rem' } }, 'Cümlede vurgulanan kelimenin anlamı?'));
      if (osymLabel(item.source)) parts.push(osymChip(item.source));
      parts.push(h('div', { class: 'sentence' }, highlight(item.sentence, item.highlight)));
    } else if (t === 'synonym') {
      parts.push(h('div', { class: 'prompt-big' }, item.prompt));
      parts.push(h('div', { class: 'prompt-pos' }, 'eş anlamlısı hangisi?'));
      if (item.sentence) parts.push(h('div', { class: 'sentence', style: { fontSize: '1.05rem' } }, highlight(item.sentence, item.highlight)));
    } else if (t === 'distinguish') {
      if (item.sentence) { sentEl = h('div', { class: 'sentence' }, blankify(item.sentence)); parts.push(sentEl); }
      else parts.push(h('div', { class: 'prompt-mid' }, item.prompt));
      parts.push(h('div', { class: 'prompt-pos' }, 'Karışan iki kelimeyi ayırt et'));
    } else if (t === 'mcq_tr_en') {
      parts.push(h('div', { class: 'prompt-mid' }, item.prompt));
      parts.push(h('div', { class: 'prompt-pos' }, (item.pos || '') + ' · İngilizcesi?'));
    } else if (t === 'syn_pick') {
      // eş anlamlısından bul: eş/yakın anlamlılar verilir, az önce öğrenilen kelimeler arasından hedef seçilir
      parts.push(h('div', { class: 'prompt-pos', style: { marginTop: '.5rem' } }, 'Eş / yakın anlamlıları bunlar olan kelime hangisi?'));
      synEl = synChips(item.synonyms, false, 'big');
      parts.push(synEl);
      parts.push(h('div', { class: 'prompt-pos' }, item.pos || ''));
    } else if (t === 'listen') {
      // dinle ve seç (Memrise tarzı): kelime yalnızca sesli; balona tıkla ya da Boşluk / R ile yeniden dinle
      const blob = h('button', { class: 'listen-blob', type: 'button', title: 'Tekrar dinle (Boşluk)', svg: ICONS.speaker });
      const play = () => { blob.classList.remove('playing'); void blob.offsetWidth; blob.classList.add('playing'); speak(item.audio); };
      blob.onclick = play;
      parts.push(h('div', { class: 'prompt-pos', style: { marginTop: '.6rem' } }, 'Duyduğun kelimenin anlamını seç'));
      listenWord = h('div', { class: 'listen-word' });
      parts.push(h('div', { class: 'listen-wrap' }, blob, listenWord));
      setTimeout(() => { if (current === item) play(); }, 300);
    } else {
      parts.push(h('div', { class: 'prompt-big' }, item.prompt));
      parts.push(h('div', { class: 'prompt-pos' }, (item.pos || '') + (t === 'placement' ? ' · Türkçesi?' : '')));
    }
    let tbar = null;
    if (item.time_limit_ms) { tbar = h('div', { class: 'timerbar' }, h('div')); parts.unshift(tbar); }
    const long = item.options.some(o => o.length > 34) || t === 'distinguish';
    const letters = item.letters;
    const opts = item.options.map((o, i) => h('button', { class: 'opt' },
      h('span', { class: 'num' }, letters ? letters[i] : String(i + 1)), h('span', { class: 'txt' }, o)));
    const grid = h('div', { class: 'options' + (long ? ' one' : '') }, opts);
    let answered = false;
    const choose = (i, extra = {}) => {
      if (answered) return;
      answered = true;
      timer.markKey();
      if (tbar) tbar.firstChild.style.animationPlayState = 'paused';
      submit(Object.assign({ choice: i }, extra), {
        reveal: (res) => {
          opts.forEach((b, k) => {
            if (k === res.correct_index) b.classList.add('correct');
            else if (k === i) b.classList.add('wrong');
            else b.classList.add('dim');
          });
          const hit = res.correct_index === i;
          if (sentEl) fillBlanks(sentEl, item.options[res.correct_index], hit, item.options[i]);
          else if (hit) burst(opts[i]);
          if (!hit && opts[res.correct_index]) setTimeout(() => opts[res.correct_index].classList.add('reveal'), 160);
          if (listenWord) showListenWord(res);
          if (synEl) synEl.classList.add('reveal');
        }
      });
    };
    opts.forEach((b, i) => b.addEventListener('click', () => choose(i)));
    const revealAll = (res) => {
      opts.forEach((b, k) => b.classList.add(k === res.correct_index ? 'correct' : 'dim'));
      if (sentEl) fillBlanks(sentEl, item.options[res.correct_index], false, null);
      if (listenWord) showListenWord(res);
      if (synEl) synEl.classList.add('reveal');
    };
    function showListenWord(res) {
      listenWord.textContent = res.say || item.audio || '';
      listenWord.classList.add('show');
    }
    const dk = dontKnowBtn(() => { if (!answered) { answered = true; submit({ dont_know: true }, { reveal: revealAll }); } });
    const c = card(item, ...parts, grid, h('div', { class: 'keyhint' }, h('kbd', null, letters ? 'A–E / 1–5' : '1–' + opts.length), ' seç · ', h('kbd', null, '0'), ' bilmiyorum',
      t === 'listen' ? [' · ', h('kbd', null, 'Boşluk'), ' tekrar dinle'] : null));
    c.appendChild(dk);
    keyHandler = (e) => {
      if (e.ctrlKey || e.altKey || e.metaKey) return;
      if (t === 'listen' && (e.key === ' ' || e.key === 'r' || e.key === 'R')) { e.preventDefault(); speak(item.audio); return; }
      let k = -1;
      if (/^[1-9]$/.test(e.key)) k = +e.key - 1;
      else if (letters && /^[a-eA-E]$/.test(e.key)) k = 'abcde'.indexOf(e.key.toLowerCase());
      if (k >= 0 && k < opts.length) { e.preventDefault(); choose(k); }
      else if (e.key === '0' || e.key === '?') { e.preventDefault(); dk.querySelector('button').click(); }
    };
    document.addEventListener('keydown', keyHandler);
    if (item.time_limit_ms && tbar) {
      const inner = tbar.firstChild;
      inner.style.transition = `transform ${item.time_limit_ms}ms linear`;
      inner.style.transform = 'scaleX(1)';
      requestAnimationFrame(() => requestAnimationFrame(() => { inner.style.transform = 'scaleX(0)'; }));
      const to = setTimeout(() => { if (!answered && current === item) { answered = true; submit({ timeout: true }, { reveal: revealAll }); } }, item.time_limit_ms);
      grid.addEventListener('click', () => clearTimeout(to), { once: true });
    }
  }

  function renderTyping(item) {
    let hints = 0;
    const input = h('input', { type: 'text', class: 'answer-input', autocomplete: 'off', autocapitalize: 'off', spellcheck: 'false', placeholder: 'İngilizcesini yaz…' });
    const hintBtn = h('button', { class: 'btn sm' }, icon('lightbulb'), 'İpucu');
    hintBtn.onclick = () => {
      const seq = item.hint_seq || [];
      if (hints < seq.length) { input.value = seq[hints]; hints++; input.focus(); }
    };
    let answered = false;
    const send = () => {
      if (answered) return;
      if (!input.value.trim()) return;
      answered = true;
      submit({ text: input.value, hints }, {
        reveal: (res) => {
          const good = res.correct && res.result === 'correct';
          input.classList.add(good ? 'correct' : (res.correct ? 'almost' : 'wrong'));
          input.disabled = true;
          if (good) burst(input);
          else revealWord(input, res.answer_text || res.expected, input.value);   // yazım hatasında da doğru yazılış
        }
      });
    };
    input.addEventListener('keydown', (e) => {
      timer.markKey();
      if (e.key === 'Enter') { e.preventDefault(); send(); }
    });
    const dk = dontKnowBtn(() => {
      if (answered) return;
      answered = true;
      submit({ dont_know: true, hints }, { reveal: (res) => { input.classList.add('wrong'); input.disabled = true; revealWord(input, res.answer_text || res.expected, ''); } });
    });
    const c = card(item, h('div', { class: 'prompt-mid' }, item.prompt), h('div', { class: 'prompt-pos' }, (item.pos || '') + ` · ${item.answer_len} harf`),
      input, h('div', { class: 'hintbar' }, hintBtn, h('button', { class: 'btn sm primary', onclick: send }, 'Kontrol et ', h('kbd', null, 'Enter'))),
      h('div', { class: 'keyhint' }, 'Yazım (1-2 harf) hatası yanlış sayılmaz.'));
    c.appendChild(dk);
    setTimeout(() => input.focus(), 50);
  }

  // eş/yakın anlamlı çipleri (listede olanların Türkçesi: tanıtımda hemen, sorularda cevaptan sonra)
  function synChips(list, showTr, size = '') {
    if (!list || !list.length) return null;
    return h('div', { class: 'syn-chips ' + size + (showTr ? ' reveal' : '') },
      h('span', { class: 'syn-lbl', title: 'Eş / yakın anlamlılar' }, '≈'),
      list.map(x => h('span', { class: 'chip syn', title: x.tr || '' }, h('span', { class: 'kw' }, x.w), x.tr ? h('small', null, x.tr) : null)));
  }

  // Bak · kapat · yaz: önce kelimeye bak (ses + anlam + eş anlamlılar), sonra kelime gizlenir ve ezberden yazılır
  function renderLookWrite(item) {
    let phase = 'look', peeks = 0, answered = false;
    const word = h('div', { class: 'lw-word' }, item.display);
    const blanks = h('div', { class: 'lw-blanks' }, [...item.display].map(ch => h('span', { class: ch === ' ' ? 'sp' : '' }, ch === ' ' ? ' ' : '')));
    const say = h('button', { class: 'icon-btn', title: 'Dinle', onclick: () => speak(item.audio || item.display), svg: ICONS.speaker });
    const top = h('div', { class: 'lw-top' }, word, say);
    const hint = h('div', { class: 'lw-hint' }, 'Kelimeye iyice bak, sesini dinle, içinden tekrar et. Hazır olunca kelime gizlenecek ve ezberden yazacaksın.');
    const input = h('input', { type: 'text', class: 'answer-input', autocomplete: 'off', autocapitalize: 'off', spellcheck: 'false', placeholder: 'Ezberden yaz…' });
    const goBtn = h('button', { class: 'btn primary lg' }, 'Ezberledim, yaz ', h('kbd', null, 'Enter'));
    const peekBtn = h('button', { class: 'btn sm' }, icon('eye'), 'Bir daha göster');
    const checkBtn = h('button', { class: 'btn sm primary' }, 'Kontrol et ', h('kbd', null, 'Enter'));
    const writeRow = h('div', { class: 'lw-write' }, input, h('div', { class: 'hintbar' }, peekBtn, checkBtn));
    writeRow.style.display = 'none';
    const toWrite = () => {
      if (phase !== 'look') return;
      phase = 'write';
      top.replaceChild(blanks, word);
      hint.textContent = 'Şimdi ezberden yaz (anlamı yukarıda).';
      goBtn.style.display = 'none';
      writeRow.style.display = '';
      timer.startQuestion();
      setTimeout(() => input.focus(), 30);
    };
    peekBtn.onclick = () => {
      if (answered) return;
      peeks++;
      top.replaceChild(word, blanks);
      setTimeout(() => { if (!answered && word.parentNode) top.replaceChild(blanks, word); input.focus(); }, 1400);
    };
    const send = () => {
      if (answered || phase !== 'write' || !input.value.trim()) return;
      answered = true;
      submit({ text: input.value, hints: peeks }, {
        reveal: (res) => {
          const good = res.correct && res.result === 'correct';
          input.classList.add(good ? 'correct' : (res.correct ? 'almost' : 'wrong'));
          input.disabled = true;
          if (word.parentNode !== top) top.replaceChild(word, blanks);
          word.classList.add(good ? 'ok' : 'bad');
          if (good) burst(input); else revealWord(input, res.answer_text || res.expected, input.value);
        }
      });
    };
    goBtn.onclick = toWrite;
    checkBtn.onclick = send;
    input.addEventListener('keydown', (e) => { timer.markKey(); if (e.key === 'Enter') { e.preventDefault(); send(); } });
    card(item, top, h('div', { class: 'prompt-mid', style: { marginTop: '.4rem' } }, item.prompt),
      h('div', { class: 'prompt-pos' }, (item.pos || '') + ` · ${item.answer_len} harf`), synChips(item.synonyms, true),
      hint, h('div', { class: 'row', style: { justifyContent: 'center', marginTop: '.8rem' } }, goBtn), writeRow);
    keyHandler = (e) => {
      if (phase === 'look' && e.key === 'Enter') { e.preventDefault(); toWrite(); }
      else if (phase === 'look' && e.key === ' ') { e.preventDefault(); speak(item.audio || item.display); }
    };
    document.addEventListener('keydown', keyHandler);
    if (settings.autoplay !== false) setTimeout(() => { if (current === item) speak(item.audio || item.display); }, 250);
  }

  // Eşleştir: kelimeler ↔ Türkçe anlamları; doğru çift yeşil yanıp kaybolur ve kelime sesli okunur
  function renderMatch(item) {
    const L = item.left || [], Rr = item.right || [];
    const letters = 'ABCDEFGH';
    const mistakes = {};
    let selL = null, selR = null, anchor = null, done = 0, finishedM = false;
    const wordOfR = {};
    for (const [lk, rk] of Object.entries(item.pairs || {})) {
      const l = L.find(x => x.k === lk);
      if (l) wordOfR[rk] = l.word_id;
    }
    const mk = (x, i, side) => h('button', { class: 'mbtn ' + side, type: 'button' },
      h('span', { class: 'num' }, side === 'en' ? String(i + 1) : letters[i]), h('span', { class: side === 'en' ? 'txt kw' : 'txt' }, x.text));
    const lb = L.map((x, i) => mk(x, i, 'en'));
    const rb = Rr.map((x, i) => mk(x, i, 'tr'));
    const clearSel = () => { lb.forEach(b => b.classList.remove('sel')); rb.forEach(b => b.classList.remove('sel')); selL = selR = anchor = null; };
    const tryPair = () => {
      if (selL === null || selR === null) return;
      const l = L[selL], r = Rr[selR], bl = lb[selL], br = rb[selR];
      if (item.pairs[l.k] === r.k) {
        [bl, br].forEach(b => { b.classList.remove('sel'); b.classList.add('matched'); b.disabled = true; });
        sfx.correct();
        burst(br, 'var(--good)', 8);
        if (settings.speak_answers !== false) speak(l.text);
        done++;
        clearSel();
        if (done >= L.length) finishMatch();
      } else {
        const w = anchor === 'tr' ? wordOfR[r.k] : l.word_id;
        mistakes[w] = (mistakes[w] || 0) + 1;
        [bl, br].forEach(b => { b.classList.remove('wrong'); void b.offsetWidth; b.classList.add('wrong'); });
        sfx.wrong();
        setTimeout(() => { bl.classList.remove('wrong'); br.classList.remove('wrong'); }, 450);
        clearSel();
      }
    };
    const pickL = (i) => {
      if (finishedM || lb[i].disabled) return;
      timer.markKey();
      lb.forEach(b => b.classList.remove('sel'));
      selL = i; lb[i].classList.add('sel');
      if (anchor === null) anchor = 'en';
      speak(L[i].text);
      tryPair();
    };
    const pickR = (i) => {
      if (finishedM || rb[i].disabled) return;
      timer.markKey();
      rb.forEach(b => b.classList.remove('sel'));
      selR = i; rb[i].classList.add('sel');
      if (anchor === null) anchor = 'tr';
      tryPair();
    };
    lb.forEach((b, i) => b.addEventListener('click', () => pickL(i)));
    rb.forEach((b, i) => b.addEventListener('click', () => pickR(i)));
    function finishMatch() {
      if (finishedM) return;
      finishedM = true;
      setTimeout(() => submit({ mistakes, total_ms: timer.questionMs() }), 450);
    }
    card(item, h('div', { class: 'prompt-pos', style: { marginTop: '.4rem' } }, 'Kelimeleri anlamlarıyla eşleştir'),
      h('div', { class: 'match-grid' }, h('div', { class: 'match-col' }, lb), h('div', { class: 'match-col' }, rb)),
      h('div', { class: 'keyhint' }, h('kbd', null, '1–' + L.length), ' kelime · ', h('kbd', null, 'A–' + letters[Rr.length - 1]), ' anlam'));
    keyHandler = (e) => {
      if (e.ctrlKey || e.altKey || e.metaKey) return;
      if (/^[1-9]$/.test(e.key) && +e.key <= L.length) { e.preventDefault(); pickL(+e.key - 1); }
      else if (/^[a-hA-H]$/.test(e.key)) {
        const i = letters.indexOf(e.key.toUpperCase());
        if (i < Rr.length) { e.preventDefault(); pickR(i); }
      }
    };
    document.addEventListener('keydown', keyHandler);
  }

  function renderTiles(item) {
    const target = [];
    const used = new Set();
    const wordMode = item.tile_mode === 'words';
    const slots = h('div', { class: 'slots' + (wordMode ? ' wordmode' : '') });
    const tiles = item.tiles.map((t, i) => h('button', { class: 'tile' }, t));
    let answered = false;
    let lastAdded = -1;   // yeni yerleşen harf kutusu "pop" ile gelir
    const totalLen = item.answer_len;
    const build = () => wordMode ? target.map(i => item.tiles[i]).join(' ') : target.map(i => item.tiles[i]).join('');
    const slot = (k) => h('div', { class: 'slot' + (target[k] !== undefined ? ' filled' : '') + (k === lastAdded ? ' pop' : '') },
      target[k] !== undefined ? item.tiles[target[k]] : '');
    const redraw = () => {
      clear(slots);
      const n = wordMode ? Math.max(target.length + 1, 2) : totalLen;
      for (let k = 0; k < n; k++) slots.appendChild(slot(k));
      lastAdded = -1;
      tiles.forEach((b, i) => b.classList.toggle('used', used.has(i)));
    };
    const revealTiles = (res, typed) => {
      const good = res.correct && res.result === 'correct';
      [...slots.children].forEach((s, k) => { s.style.animationDelay = (k * 45) + 'ms'; });
      slots.classList.add(good ? 'good' : (res.correct ? 'almost' : 'bad'));
      if (good) burst(slots); else revealWord(slots, res.answer_text || res.expected, typed);
    };
    const send = () => {
      if (answered) return;
      answered = true;
      const typed = build();
      submit({ text: typed }, { reveal: (res) => revealTiles(res, typed) });
    };
    const pick = (i) => {
      if (answered || used.has(i)) return;
      timer.markKey();
      used.add(i); target.push(i); lastAdded = target.length - 1; sfx.tick(); redraw();
      if (!wordMode && build().length >= totalLen) setTimeout(send, 120);
      if (wordMode && build().length >= totalLen) setTimeout(send, 120);
    };
    const undo = () => { if (answered) return; const i = target.pop(); if (i !== undefined) { used.delete(i); redraw(); } };
    tiles.forEach((b, i) => b.addEventListener('click', () => pick(i)));
    const dk = dontKnowBtn(() => { if (!answered) { answered = true; submit({ dont_know: true }, { reveal: (res) => revealTiles(res, '') }); } });
    const c = card(item, h('div', { class: 'prompt-mid' }, item.prompt), h('div', { class: 'prompt-pos' }, (item.pos || '') + ' · harflerden kur'),
      slots, h('div', { class: 'tiles' }, tiles),
      h('div', { class: 'hintbar' }, h('button', { class: 'btn sm', onclick: undo }, '⌫ Geri al'), wordMode ? h('button', { class: 'btn sm primary', onclick: send }, 'Kontrol et') : null),
      h('div', { class: 'keyhint' }, 'Klavyeyle de yazabilirsin · ', h('kbd', null, '⌫'), ' geri al'));
    c.appendChild(dk);
    redraw();
    keyHandler = (e) => {
      if (e.ctrlKey || e.altKey || e.metaKey) return;
      if (e.key === 'Backspace') { e.preventDefault(); undo(); return; }
      if (e.key === 'Enter') { e.preventDefault(); if (wordMode || target.length) send(); return; }
      if (e.key === '0' && !wordMode) { dk.querySelector('button').click(); return; }
      if (e.key.length === 1) {
        const ch = e.key.toLowerCase();
        const idx = item.tiles.findIndex((t, i) => !used.has(i) && (wordMode ? t.startsWith(ch) : t === ch));
        if (idx >= 0) { e.preventDefault(); pick(idx); }
      }
    };
    document.addEventListener('keydown', keyHandler);
  }

  // ---------------------------------------------------------- mola / özet / boş plan
  function showBreak(nextItem) {
    clear(stage);
    const mins = settings.break_minutes || 5;
    const acc = answers ? correct / answers : null;
    let cd = null;
    const info = h('div', { class: 'muted' });
    const c = h('div', { class: 'ex-card', style: { textAlign: 'center' } },
      h('div', { class: 'big-check', svg: ICONS.coffee }),
      h('h2', { style: { marginTop: '1rem' } }, `${Math.round(timer.total / 60000)} dakikadır çalışıyorsun`),
      h('p', { class: 'ink2' }, `${answers} cevap · doğruluk ${fmt.pct(acc)}. Kısa oturumlar ve molalar kalıcılığı artırır.`),
      info,
      h('div', { class: 'row', style: { justifyContent: 'center', marginTop: '1rem' } },
        h('button', { class: 'btn', onclick: () => {
          let left = mins * 60;
          clearInterval(cd);
          cd = setInterval(() => { left--; info.textContent = `Mola: ${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}`; if (left <= 0) { clearInterval(cd); info.textContent = 'Mola bitti — hazırsan devam!'; } }, 1000);
        } }, icon('coffee'), `${mins} dk mola ver`),
        h('button', { class: 'btn primary', onclick: () => { clearInterval(cd); show(nextItem); } }, 'Devam et ', h('kbd', null, 'Enter')),
        h('button', { class: 'btn ghost', onclick: () => { clearInterval(cd); exit(); } }, 'Bugünlük bu kadar')));
    stage.appendChild(c);
    keyHandler = (e) => { if (e.key === 'Enter') { e.preventDefault(); clearInterval(cd); show(nextItem); } };
    document.addEventListener('keydown', keyHandler);
  }

  async function streakCelebration(card) {
    try {
      const t = await get('/today');
      const st = t.streak;
      const key = 'yds-streak-shown-' + (t.plan && t.plan.day);
      let shown = null;
      try { shown = localStorage.getItem(key); } catch (e) { /* yok */ }
      if (!st.today_done || shown) return;
      try { localStorage.setItem(key, '1'); } catch (e) { /* yok */ }
      const days = ['Pt', 'Sa', 'Ça', 'Pe', 'Cu', 'Ct', 'Pz'];
      card.insertBefore(h('div', { class: 'note', style: { textAlign: 'center', margin: '1rem 0', background: 'var(--warn-bg)' } },
        h('div', { style: { fontSize: '1.4rem', fontWeight: 900 } }, 'Günlük seri büyüyor! ', h('span', { svg: FLAME, style: { width: '26px', display: 'inline-flex', verticalAlign: 'middle' } })),
        h('div', { class: 'ink2', style: { margin: '.3rem 0 .6rem' } }, `Mevcut seri: ${st.current} gün`),
        h('div', { class: 'week', style: { justifyContent: 'center', maxWidth: '420px', margin: '0 auto' } }, st.week.map((w, i) => h('div', { class: 'd' }, days[i],
          h('div', { class: 'dot' + (w.done ? ' done' : '') + (w.freeze ? ' freeze' : '') }, w.done ? '✓' : (w.freeze ? '❄' : '')))))), card.children[2] || null);
    } catch (e) { /* sessiz */ }
  }

  function summaryTitle(s) {
    if (!s) return 'Oturum tamamlandı';
    const pt = s.part && s.part.title ? ` (${s.part.title})` : '';
    if (s.part) return s.part.finished ? `Part ${s.part.no}${pt} tamamlandı` : `Part ${s.part.no}${pt}: ${s.part.done}/${s.part.total} kelime bitti`;
    if (s.mode === 'quick') return `${s.label || 'Hızlı tekrar'}: ${s.quick_score ?? 0} doğru`;
    if (s.mode === 'part_test') return `${s.label || 'Test'}: ${s.correct}/${s.answers} doğru`;
    if (s.mode === 'daily' || s.mode === 'review') return 'Tekrarlar tamamlandı';
    return 'Oturum tamamlandı';
  }

  function showSummary(s) {
    clear(stage);
    bar.style.width = '100%';
    const learned = (s && s.learned) || [];
    const np = s && s.next_part;
    const goNext = () => { cleanup(); runStudy(root, { ...opts, mode: 'part', partId: np.id || null, partIds: null, limit: null }); };
    const pt = s && s.parts_today;
    const c = h('div', { class: 'ex-card', style: { textAlign: 'center' } },
      h('div', { class: 'big-check', svg: ICONS.check }),
      h('h1', { style: { marginTop: '1rem' } }, summaryTitle(s)),
      pt && pt.planned ? h('div', { class: 'ink2', style: { fontWeight: 800 } }, `Bugün ${pt.finished}/${pt.planned} part tamamlandı`) : null,
      s ? h('div', { class: 'grid4', style: { margin: '1rem 0', textAlign: 'left' } },
        stat('Cevap', fmt.num(s.answers)), stat('Doğruluk', fmt.pct(s.accuracy)), stat('Aktif süre', (s.active_min ?? 0) + ' dk'),
        stat('En uzun seri', fmt.num(s.best_streak))) : null,
      learned.length ? h('div', { style: { textAlign: 'left' } }, h('div', { class: 'section-title' }, `Bu oturumda öğrenilenler (${learned.length})`),
        h('div', { class: 'summary-words' }, learned.map(w => h('div', { class: 'sw' }, h('span', { svg: plantSVG(3, 36) }), h('div', null, h('b', null, w.display), h('span', { class: 'small ink2' }, w.meaning)))))) : null,
      s && s.weekly ? h('div', { class: 'notice info', style: { textAlign: 'left', marginTop: '1rem' } }, icon('info'),
        `Haftalık test doğruluğu ${fmt.pct(s.weekly.accuracy)}. Haftalık rapor Analiz ekranında.`) : null,
      h('div', { class: 'row', style: { justifyContent: 'center', marginTop: '1.4rem' } },
        h('button', { class: 'btn', onclick: () => { cleanup(); onExit && onExit(s); } }, icon('home'), 'Ana sayfa'),
        h('button', { class: 'btn', onclick: () => { cleanup(); location.hash = '#/calis'; } }, icon('list'), 'Partlar'),
        np ? h('button', { class: 'btn primary', onclick: goNext }, (np.resume || (s.part && !s.part.finished) ? `Devam et: Part ${np.no}` : `Sıradaki part: Part ${np.no}`) + (np.title ? ` · ${np.title}` : ''), ' ', h('kbd', null, 'Enter'))
          : (s && !s.part && s.mode !== 'daily' ? h('button', { class: 'btn primary', onclick: () => { cleanup(); runStudy(root, { ...opts }); } }, 'Bir tur daha') : null)));
    stage.appendChild(c);
    if (s && s.part && s.part.finished) setTimeout(() => { sfx.bloom(); burst(c.querySelector('.big-check'), 'var(--good)', 22); }, 200);
    if (s && s.answers) streakCelebration(c);
    keyHandler = (e) => { if (e.key === 'Enter') { e.preventDefault(); if (np) goNext(); else { cleanup(); onExit && onExit(s); } } };
    document.addEventListener('keydown', keyHandler);
  }

  function showNothing(r) {
    clear(stage);
    stage.appendChild(h('div', { class: 'ex-card', style: { textAlign: 'center' } },
      h('div', { class: 'big-check', svg: ICONS.trophy }),
      h('h1', { style: { marginTop: '1rem' } }, mode === 'daily' ? 'Bugünkü plan tamam!' : 'Bu modda şu an soru yok'),
      h('p', { class: 'ink2' }, 'Vadesi gelen tekrar ve planlı yeni kelime kalmadı. İstersen ek çalışma yapabilirsin:'),
      h('div', { class: 'row', style: { justifyContent: 'center' } },
        h('button', { class: 'btn', onclick: () => { cleanup(); runStudy(root, { ...opts, mode: 'quick' }); } }, icon('bolt'), 'Hızlı tekrar'),
        h('button', { class: 'btn', onclick: () => { cleanup(); runStudy(root, { ...opts, mode: 'hard' }); } }, icon('brain'), 'Zor kelimeler'),
        h('button', { class: 'btn', onclick: () => { cleanup(); runStudy(root, { ...opts, mode: 'part', partId: null, partIds: null, limit: null }); } }, icon('plus'), 'Sıradaki part'),
        h('button', { class: 'btn primary', onclick: () => { cleanup(); onExit && onExit(null); } }, 'Ana sayfa'))));
  }

  function stat(label, value) {
    return h('div', { class: 'stat' }, h('div', { class: 'label' }, label), h('div', { class: 'value', style: { fontSize: '1.5rem' } }, value));
  }

  function unverified(obj) {
    if (!obj) return null;
    if (obj.source === 'user') return null;
    if (osymLabel(obj.source)) return osymChip(obj.source);
    return obj.verified ? h('span', { class: 'badge-ok' }, 'doğrulandı') : h('span', { class: 'badge-unv', title: 'Yapay zekâ üretimi; doğrulanmamış' }, 'doğrulanmamış');
  }
}

