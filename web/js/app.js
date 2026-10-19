// Ana kabuk: yönlendirme, üst çubuk, tema, puan paneli, Bugün ekranı.
import { get, post, setPinHandler } from './api.js';
import { h, add, clear, icon, ICONS, fmt, toast, modal, FLAME } from './util.js';
import { lineChart, hbars } from './charts.js';
import { runStudy } from './study.js';
import { renderParts } from './parts.js';
import { nextRoute, isCurrent, currentRoute } from './nav.js';
import { renderAnalysis } from './analysis.js';
import { renderWords } from './words.js';
import { renderSettings, renderSetup } from './settings.js';

const state = { boot: null, settings: {} };
const main = document.getElementById('main');
const side = document.getElementById('side');
const layout = document.getElementById('layout');

const NAV = [
  { id: 'bugun', label: 'Bugün', icon: 'home' },
  { id: 'calis', label: 'Çalış', icon: 'bolt' },
  { id: 'analiz', label: 'Analiz', icon: 'chart' },
  { id: 'kelimeler', label: 'Kelimeler', icon: 'list' },
  { id: 'ayarlar', label: 'Ayarlar', icon: 'gear' },
];

// ------------------------------------------------------------ tema
function applyTheme(t) {
  const root = document.documentElement;
  if (t === 'light' || t === 'dark') root.dataset.theme = t; else delete root.dataset.theme;
  try { localStorage.setItem('yds-theme', t || 'auto'); } catch (e) { /* yok */ }
}
try { applyTheme(localStorage.getItem('yds-theme') || 'auto'); } catch (e) { /* yok */ }

// ------------------------------------------------------------ üst çubuk
function renderTopbar() {
  const top = document.getElementById('topbar');
  clear(top);
  const nav = h('nav', { class: 'nav' }, NAV.map(n => h('a', { href: '#/' + n.id, dataset: { r: n.id } }, h('span', { svg: ICONS[n.icon] }), n.label)));
  const flame = h('span', { class: 'flame', id: 'streak', title: 'Günlük seri' }, h('span', { svg: FLAME }), h('span', { id: 'streak-n' }, '0'));
  const themeBtn = h('button', { class: 'iconbtn', title: 'Tema', onclick: () => {
    const cur = document.documentElement.dataset.theme || 'auto';
    const nxt = cur === 'auto' ? (matchMedia('(prefers-color-scheme: dark)').matches ? 'light' : 'dark') : (cur === 'dark' ? 'light' : 'dark');
    applyTheme(nxt); post('/settings', { theme: nxt }).catch(() => {});
    themeBtn.innerHTML = nxt === 'dark' ? ICONS.sun : ICONS.moon;
  }, svg: (document.documentElement.dataset.theme === 'dark') ? ICONS.sun : ICONS.moon });
  add(top, h('a', { class: 'brand', href: '#/bugun' }, h('img', { src: '/static/icon.png', alt: '' }),
    h('span', null, 'YDS Kelime Koçu', h('small', null, (state.settings.exam_name || '2026-YDS/2') + ' · ' + fmt.dateLong(state.settings.exam_date)))),
    nav, h('div', { class: 'right' }, flame, themeBtn));
  const mob = document.getElementById('mobilenav');
  clear(mob);
  NAV.forEach(n => mob.appendChild(h('a', { href: '#/' + n.id, dataset: { r: n.id } }, h('span', { svg: ICONS[n.icon] }), n.label)));
}

function markNav(r) {
  document.querySelectorAll('[data-r]').forEach(a => a.classList.toggle('active', a.dataset.r === r));
}

// ------------------------------------------------------------ puan paneli
// ------------------------------------------------------------ puan tahmini (yan panel, canlı)
const SCORE_THR = [50, 55, 60, 65, 70];

export async function renderScorePanel(quiet = false) {
  const token = currentRoute();
  let box = side.querySelector('.card.score');
  if (!quiet || !box) {
    clear(side);
    box = h('div', { class: 'card score' }, h('h3', null, 'YDS puan tahmini'), h('div', { class: 'muted small' }, 'hesaplanıyor…'));
    side.appendChild(box);
  }
  try {
    const s = await get('/score');
    if (!isCurrent(token)) return;
    if (quiet && state.score && state.score.computed_at === s.computed_at) return;   // girdiler değişmedi
    state.score = s;
    drawScore(box, s);
  } catch (e) {
    if (!quiet) { clear(box); add(box, h('h3', null, 'YDS puan tahmini'), h('div', { class: 'muted small' }, e.message)); }
  }
}

function drawScore(box, s) {
  clear(box);
  if (!s.available) { add(box, h('h3', null, 'YDS puan tahmini'), h('div', { class: 'muted small' }, s.message || 'Hazır değil')); return; }
  const opts = [...new Set([...SCORE_THR, s.target])].sort((a, b) => a - b);
  const thr = opts.includes(state.scoreThr) ? state.scoreThr : s.target;
  const pct = (v) => (v < 0.005 ? '<%1' : '%' + Math.round(v * 100));
  const pOf = (x) => x.p[String(thr)];
  const sc = Object.fromEntries(s.scenarios.map(x => [x.key, x]));
  const time = new Date(s.computed_at).toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' });
  const short = (d) => new Date(d + 'T12:00:00').toLocaleDateString('tr-TR', { day: 'numeric', month: 'short' });
  const eta = (m) => (m.eta_pace.date && m.eta_pace.reachable ? `bu tempoyla ~${short(m.eta_pace.date)}` : 'bu tempoyla sınava yetişmez');
  add(box,
    h('div', { class: 'score-head' }, h('h3', null, 'YDS puan tahmini'),
      h('span', { class: 'chip good live', title: 'Her cevap, deneme ve ayar değişikliğinden sonra yeniden hesaplanır' }, '● canlı · ' + time)),
    h('div', { class: 'thr-chips', role: 'group', 'aria-label': 'Puan eşiği' }, opts.map(t => h('button', {
      class: 'chip' + (t === thr ? ' brand' : ''), 'aria-pressed': t === thr ? 'true' : 'false',
      onclick: () => { state.scoreThr = t; drawScore(box, s); },
    }, `${t}+`))),
    h('div', { class: 'score-big' }, h('div', { class: 'v' }, pct(pOf(sc.plan))),
      h('div', { class: 'l' }, `sınav günü ${thr}+ alma olasılığın`, h('br'), h('span', { class: 'muted' }, 'plana uyarsan'))),
    s.scenarios.map(x => h('div', { class: 'kv' }, h('span', null, x.label, h('small', null, ` · medyan ${Math.round(x.median)}`)),
      h('b', null, pct(pOf(x))))),
    h('div', { class: 'section-title' }, `İleriye dönük · sınav günü ${thr}+`),
    s.milestones.map(m => h('div', { class: 'kv' }, h('span', null, m.label, m.words ? h('small', null, ' · ' + eta(m)) : null),
      h('b', null, pct(pOf(m))))),
    h('div', { class: 'kv' }, h('span', null, s.skill_up.label), h('b', null, pct(pOf(s.skill_up)))));
  const chartBox = h('div');
  add(box, h('div', { class: 'small ink2', style: { marginTop: '.6rem', fontWeight: 800 } }, `Öğreneceğin yeni kelime → ${thr}+ olasılığı`), chartBox);
  lineChart(chartBox, {
    series: [{ name: `${thr}+ olasılığı`, color: 'var(--series-1)', points: s.curve.points.map(p => ({ x: p.words, y: p.p[String(thr)] })) }],
    yMin: 0, yMax: 1, height: 150, endLabels: false, yFormat: (v) => '%' + Math.round(v * 100), xFormat: (v) => '+' + Math.round(v),
    marker: s.curve.by_exam_pace ? { x: s.curve.by_exam_pace, label: 'bu tempoyla' } : null,
    title: `Öğreneceğin yeni kelime sayısına göre ${thr}+ alma olasılığı`,
  });
  const dist = h('div');
  add(box,
    h('div', { class: 'basis', style: { marginTop: '.5rem' } }, s.basis),
    h('div', { class: 'muted small' }, s.note),
    h('div', { class: 'row', style: { marginTop: '.6rem' } },
      h('button', { class: 'btn sm', onclick: mockDialog }, icon('plus'), 'Deneme sonucu ekle'),
      h('button', { class: 'btn sm ghost', onclick: () => { location.hash = '#/ayarlar'; } }, `Seviyem: ${s.inputs.level_label}`)),
    h('details', { style: { marginTop: '.6rem' } }, h('summary', { class: 'small', style: { cursor: 'pointer', fontWeight: 800 } }, 'Puan dağılımı (sınav günü, bu tempoyla)'), dist));
  hbars(dist, s.at_least.filter(r => r.score >= 35 && r.score <= 75).reverse().map(r => ({
    label: `≥ ${r.score} puan`, value: r.p, emph: r.score === thr, tip: `Sınavdan en az ${r.score} puan alma olasılığı`,
  })), { max: 1, format: (v) => '%' + Math.round(v * 100) });
}

// canlı: panel görünürken dakikada bir sessizce tazelenir (girdiler değişmediyse sunucu önbellekten döner)
setInterval(() => {
  if (document.hidden || document.body.classList.contains('studying') || !side.querySelector('.card.score')) return;
  renderScorePanel(true);
}, 60000);
document.addEventListener('visibilitychange', () => {
  if (!document.hidden && side.querySelector('.card.score') && !document.body.classList.contains('studying')) renderScorePanel(true);
});

const SECTIONS = ['Kelime bilgisi', 'Dil bilgisi', 'Cloze test', 'Cümle tamamlama', 'Çeviri', 'Okuma', 'Diyalog', 'Yakın anlam', 'Paragraf tamamlama', 'Akışı bozan cümle'];
const SEC_N = [6, 10, 10, 10, 6, 20, 5, 4, 4, 5];
export function mockDialog() {
  const day = h('input', { type: 'date', value: new Date().toISOString().slice(0, 10) });
  const total = h('input', { type: 'number', min: 0, max: 80, placeholder: '0-80' });
  const secInputs = SECTIONS.map((s, i) => h('input', { type: 'number', min: 0, max: SEC_N[i], placeholder: `/${SEC_N[i]}`, style: { width: '80px' } }));
  const note = h('input', { type: 'text', placeholder: 'ör. Yediiklim deneme 3' });
  const body = h('div', null, h('h2', null, 'Deneme sınavı sonucu'),
    h('p', { class: 'ink2 small' }, 'Toplam doğru sayısını gir (yanlışlar götürmez). İstersen bölüm bölüm doğruları da girebilirsin; model dil bilgisi/okuma becerini bundan tahmin eder.'),
    h('div', { class: 'grid2' }, h('label', { class: 'field' }, 'Tarih', day), h('label', { class: 'field' }, 'Toplam doğru (80 soru)', total)),
    h('details', { style: { margin: '.8rem 0' } }, h('summary', { style: { cursor: 'pointer', fontWeight: 800 } }, 'Bölüm bölüm (isteğe bağlı)'),
      h('div', { class: 'grid2', style: { marginTop: '.5rem' } }, SECTIONS.map((s, i) => h('label', { class: 'field' }, `${s} (${SEC_N[i]})`, secInputs[i])))),
    h('label', { class: 'field' }, 'Not', note));
  const save = h('button', { class: 'btn primary' }, 'Kaydet');
  body.appendChild(h('div', { class: 'row', style: { marginTop: '1rem' } }, h('span', { class: 'spacer' }), save));
  const m = modal(body);
  save.onclick = async () => {
    const sections = {};
    secInputs.forEach((inp, i) => { if (inp.value !== '') sections[SECTIONS[i]] = +inp.value; });
    try {
      await post('/mocks', { day: day.value, total_correct: total.value === '' ? null : +total.value, sections: Object.keys(sections).length ? sections : null, note: note.value });
      m.close(); toast('Deneme sonucu kaydedildi; tahmin güncellendi.'); renderScorePanel();
    } catch (e) { toast(e.message, 'warn'); }
  };
}

// ------------------------------------------------------------ Bugün
async function renderToday(token) {
  clear(main);
  main.appendChild(h('div', { class: 'muted' }, 'Yükleniyor…'));
  let d;
  try { d = await get('/today'); } catch (e) { if (isCurrent(token)) { clear(main); add(main, h('div', { class: 'notice bad' }, e.message)); } return; }
  if (!isCurrent(token)) return;  // kullanıcı bu arada başka ekrana geçti: geç gelen yanıtı yazma
  if (!d.setup_done) { location.hash = '#/kurulum'; return; }
  clear(main);
  const p = d.plan, n = d.numbers, prog = d.progress;
  document.getElementById('streak-n').textContent = String(d.streak.current);
  const name = (state.settings.user_name || '').trim();
  const parts = [];
  const pi = d.parts;   // partlar: en fazla 15'lik yeni kelime grupları
  if (p.reviews_planned) parts.push(`${p.reviews_planned} tekrar`);
  if (p.new_planned) parts.push(pi && pi.planned ? `${pi.planned} part (${p.new_planned} kelime)` : `${p.new_planned} yeni kelime`);
  if (p.sweep_target) parts.push(`${p.sweep_target} hızlı tur`);
  if (p.weekly_test) parts.push('haftalık test');
  const done = prog.fraction >= 0.999;
  const startBtn = h('button', { class: 'btn primary xl', onclick: () => { location.hash = '#/calis?mod=daily'; } },
    done ? 'Ek çalışma yap' : (prog.fraction > 0 ? 'Çalışmaya devam et' : 'Bugünkü çalışmaya başla'),
    h('span', { class: 'btn-sub' }, done ? 'Bugünkü plan tamamlandı 🎉' : `${parts.join(' + ') || 'plan'} ≈ ${p.minutes} dk`));
  const phaseNote = p.phase === 'final' ? h('div', { class: 'notice info' }, icon('target'), `Son ${state.settings.final_days || 7} gün: yeni kelime yok — listenin hızlı turları, zayıf kelimeler ve hız çalışması.`)
    : p.phase === 'weekly' ? h('div', { class: 'notice info' }, icon('calendar'), 'Bugün haftalık tekrar günü: yeni kelime yok/az; YDS tarzı karışık test seni bekliyor.') : null;
  const hero = h('div', { class: 'hero' },
    h('div', { class: 'start' },
      h('div', { class: 'hello' }, `Merhaba${name ? ' ' + name : ''} — sınava `, h('b', null, `${n.days_to_exam} gün`), ' kaldı.'),
      startBtn,
      h('div', { class: 'meter' + (done ? ' good' : '') }, h('div', { style: { width: Math.round(prog.fraction * 100) + '%' } })),
      h('div', { class: 'small ink2' }, `Bugün: ${prog.reviews_done} tekrar, ${prog.new_done} yeni` +
        (pi && pi.planned ? ` (${pi.finished_today}/${pi.planned} part)` : '') + ` · aktif ${prog.active_min} dk · kalan ≈ ${prog.remaining_min} dk`),
      phaseNote),
    h('div', { class: 'stats' },
      tile('Sınava kalan gün', String(n.days_to_exam), fmt.dateLong(p.exam_date)),
      tile('Öğrenilen / toplam', h('span', null, fmt.num(n.learned), h('small', null, ' / ' + fmt.num(n.total))), `${fmt.num(n.started)} kelime başlandı`, n.total ? n.learned / n.total : 0),
      tile('Bugünkü plan', '%' + n.plan_pct, `${prog.active_min} / ${p.minutes} dk`, n.plan_pct / 100),
      tile('Sınav günü hakimiyet', n.mastery !== null && n.mastery !== undefined ? fmt.pct(n.mastery) : '—', `hedef ${fmt.pct(n.target)} · plana uyarsan ${fmt.pct(n.mastery_plan)}`, n.mastery, n.mastery >= n.target)));
  main.appendChild(hero);

  // projeksiyon
  const projCard = h('div', { class: 'card', style: { marginTop: '1.2rem' } },
    h('h2', null, icon('target'), 'Sınav günü projeksiyonu'),
    h('div', { class: 'sub' }, d.projection_message || ''));
  const chartBox = h('div');
  projCard.appendChild(chartBox);
  main.appendChild(projCard);
  get('/projection').then(pr => {
    const hist = (pr.history || []).map(x => ({ x: new Date(x.day + 'T12:00:00'), pace: x.pace, plan: x.plan }));
    const series = [
      { name: 'Bu tempoyla', color: 'var(--series-1)', points: hist.map(x => ({ x: x.x, y: x.pace })) },
      { name: 'Plana uyarsan', color: 'var(--series-2)', points: hist.map(x => ({ x: x.x, y: x.plan })) },
    ];
    lineChart(chartBox, { series, target: { y: pr.target, label: `hedef ${fmt.pct(pr.target)}` }, yMin: 0, yMax: 1, height: 200,
      yFormat: (v) => '%' + Math.round(v * 100), xMax: new Date(pr.exam_date + 'T12:00:00'),
      marker: { x: new Date(pr.exam_date + 'T12:00:00'), label: 'sınav' }, title: 'Sınav günü hatırlama projeksiyonu' });
    if (hist.length < 2) chartBox.appendChild(h('div', { class: 'muted small' }, 'Grafik her gün bir nokta ekler; birkaç gün sonra eğilim görünür.'));
    if (pr.pace && pr.pace.finish_date && pr.pace.finish_date !== '—') {
      projCard.appendChild(h('div', { class: 'small ink2', style: { marginTop: '.4rem' } },
        `Bu tempoyla (günde ~${Math.round(pr.pace.new_per_day)} yeni, ${Math.round(pr.pace.minutes_per_day)} dk) yeni kelimeler ${fmt.dateLong(pr.pace.finish_date)} tarihinde bitiyor; son hafta ${fmt.dateLong(pr.final_start)} başlıyor.`));
    }
  }).catch(() => {});

  // plan + gerekçe
  const planCard = h('div', { class: 'card' }, h('h2', null, icon('calendar'), 'Bugünün planı'),
    h('div', { class: 'sub' }, `${parts.join(' + ') || 'plan boş'} ≈ ${p.minutes} dk · bütçe ${p.budget} dk`),
    h('ul', { class: 'planlist' }, (p.rationale || []).map(r => h('li', null, r))));
  if (p.realism) {
    const r = p.realism;
    planCard.appendChild(h('div', { class: 'notice warn', style: { marginTop: '.6rem' } }, icon('warn'), h('div', null,
      h('b', null, 'Gerçekçilik kontrolü: hedef mevcut süreyle tutmuyor.'),
      h('div', { class: 'row', style: { marginTop: '.5rem' } },
        h('button', { class: 'btn sm', onclick: async () => {
          await post('/settings', { weekday_minutes: r.need_weekday, weekend_minutes: r.need_weekend });
          toast('Süre güncellendi; plan yeniden hesaplandı.'); renderToday();
        } }, `Süreyi artır (${r.need_weekday}/${r.need_weekend} dk)`),
        h('button', { class: 'btn sm', onclick: () => prioritizeDialog(r.drop_words) }, `Listeyi önceliklendir (${r.drop_words} kelime yedeğe)`),
        h('button', { class: 'btn sm', onclick: async () => {
          const t = Math.max(0.5, Math.floor((r.projected_recall || 0.8) * 100) / 100);
          await post('/settings', { target_recall: t });
          toast(`Hedef %${Math.round(t * 100)} yapıldı.`); renderToday();
        } }, `Hedefi düşür (%${Math.round((r.projected_recall || 0) * 100)})`)))));
  }
  const extra = h('div', { class: 'actions', style: { marginTop: '.9rem' } },
    action('list', 'Partlar', pi && pi.total ? `${pi.total} part · seçip test et` : '15\'lik kelime grupları', () => { location.hash = '#/calis'; }),
    action('bolt', 'Hızlı tekrar', 'süreli · 3 can · otomatiklik', () => { location.hash = '#/calis?mod=quick'; }),
    action('brain', 'Zor kelimeler', `${d.hard_count} kelime`, () => { location.hash = '#/calis?mod=hard'; }),
    action('clock', 'Zor gün modu', '10 dk · seriyi korur', () => { location.hash = '#/calis?mod=daily&dk=10'; }),
    p.phase === 'weekly' ? action('trophy', 'Haftalık YDS testi', '40 soru', () => { location.hash = '#/calis?mod=weekly'; }) : null,
    !d.placement_done ? action('target', 'Seviye testi', '~15 dk · bildiklerini bul', () => { location.hash = '#/kurulum?adim=seviye'; }) : null,
    d.suggestions_pending ? action('sparkle', 'Öneriler', `${d.suggestions_pending} bağlaç / öbek fiil`, () => { location.hash = '#/kelimeler?sekme=oneriler'; }) : null,
    action('plus', 'Kelime ekle', 'denemede gördüğün', () => { location.hash = '#/kelimeler?ekle=1'; }));
  planCard.appendChild(extra);
  main.appendChild(planCard);

  // seri + koç
  const st = d.streak;
  const week = h('div', { class: 'week' }, st.week.map(w => h('div', { class: 'd' },
    ['Pt', 'Sa', 'Ça', 'Pe', 'Cu', 'Ct', 'Pz'][new Date(w.day + 'T12:00:00').getDay() === 0 ? 6 : new Date(w.day + 'T12:00:00').getDay() - 1],
    h('div', { class: 'dot' + (w.done ? ' done' : '') + (w.freeze ? ' freeze' : '') + (w.day === p.day ? ' today' : ''), title: `${w.minutes} dk` },
      w.done ? '✓' : (w.freeze ? '❄' : (w.future ? '' : '·'))))));
  const streakCard = h('div', { class: 'card' }, h('h2', null, h('span', { svg: FLAME, style: { width: '22px', display: 'inline-flex' } }), `Seri: ${st.current} gün`),
    h('div', { class: 'sub' }, `Günde en az ${st.min_minutes} dk çalışmak seriyi sürdürür; 7 günde bir kaçırılan gün affedilir (❄). En iyi seri: ${st.best} gün.`),
    week);
  const coachCard = h('div', { class: 'card' }, h('h2', null, icon('info'), 'Koç'),
    d.notifications.length ? h('div', { class: 'notes' }, d.notifications.slice(0, 5).map(nn => h('div', { class: 'note' }, h('b', null, `${nn.title} · ${fmt.time(nn.ts)}`), nn.body)))
      : h('div', { class: 'muted small' }, 'Bildirimler burada görünecek: sabah planı, hatırlatmalar, tempo ve saat önerileri.'));
  main.appendChild(h('div', { class: 'grid2', style: { marginTop: '1rem' } }, streakCard, coachCard));
}

function tile(label, value, foot, frac, good) {
  return h('div', { class: 'stat' }, h('div', { class: 'label' }, label), h('div', { class: 'value' }, value),
    foot ? h('div', { class: 'foot' }, foot) : null,
    frac !== undefined && frac !== null ? h('div', { class: 'meter' + (good ? ' good' : '') }, h('div', { style: { width: Math.round(Math.max(0, Math.min(1, frac)) * 100) + '%' } })) : null);
}

function action(ic, title, sub, onclick) {
  return h('div', { class: 'action', onclick, tabindex: 0, role: 'button' }, h('div', { class: 'ic', svg: ICONS[ic] }), h('div', null, title, h('small', null, sub)));
}

function prioritizeDialog(n) {
  const body = h('div', null, h('h2', null, 'Listeyi önceliklendir'),
    h('p', { class: 'ink2' }, `Henüz başlanmamış ${n} kelime yedeğe alınacak (silinmez; Ayarlar → Yedek ile geri açılır). Önce sınavda az görülen edat kalıpları ve öbek fiiller, sonra kitabın son günleri; bağlaçlar ve garanti kelimeler en son.`));
  const ok = h('button', { class: 'btn primary' }, 'Yedeğe al');
  body.appendChild(h('div', { class: 'row' }, h('span', { class: 'spacer' }), ok));
  const m = modal(body);
  ok.onclick = async () => {
    try { const r = await post('/plan/prioritize', { n }); m.close(); toast(`${r.moved} kelime yedeğe alındı.`); renderToday(); }
    catch (e) { toast(e.message, 'warn'); }
  };
}

// ------------------------------------------------------------ çalış
function renderStudy(params) {
  const mode = params.get('mod') || 'daily';
  const limit = params.get('limit') ? +params.get('limit') : null;
  const dk = params.get('dk') ? +params.get('dk') : null;
  const partId = params.get('part') ? +params.get('part') : null;
  const partIds = params.get('parts') ? params.get('parts').split(',').map(Number).filter(Boolean) : null;
  const settings = Object.assign({}, state.settings);
  if (dk) settings.max_session_minutes = dk;
  // part oturumları ve part testleri bitince Partlar ekranına döner
  const back = (mode === 'part' || partIds) ? '#/calis' : '#/bugun';
  runStudy(main, { mode, limit, partId, partIds, settings, onExit: () => { location.hash = back; } });
}

// ------------------------------------------------------------ PIN (telefon)
function renderPin() {
  layout.classList.add('full');
  clear(side); clear(main);
  const inp = h('input', { type: 'password', inputmode: 'numeric', placeholder: 'PIN', style: { fontSize: '1.6rem', textAlign: 'center' } });
  const go = async () => {
    try { await post('/auth/pin', { pin: inp.value }); location.hash = '#/bugun'; location.reload(); }
    catch (e) { toast(e.message, 'warn'); }
  };
  inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') go(); });
  main.appendChild(h('div', { class: 'card wizard', style: { textAlign: 'center', marginTop: '10vh' } },
    h('img', { src: '/static/icon.png', style: { width: '72px' } }), h('h1', null, 'YDS Kelime Koçu'),
    h('p', { class: 'ink2' }, 'Telefondan erişim için bilgisayardaki PIN\'i gir.'), inp,
    h('div', { style: { marginTop: '1rem' } }, h('button', { class: 'btn primary lg', onclick: go }, 'Giriş'))));
  setTimeout(() => inp.focus(), 50);
}
setPinHandler(() => { if (!location.hash.startsWith('#/pin')) location.hash = '#/pin'; });

// ------------------------------------------------------------ yönlendirme
async function route() {
  const token = nextRoute();
  const raw = location.hash.replace(/^#\/?/, '') || 'bugun';
  const [path, qs] = raw.split('?');
  const params = new URLSearchParams(qs || '');
  document.body.classList.remove('studying');
  layout.classList.remove('full');
  markNav(path);
  window.scrollTo(0, 0);
  if (path === 'pin') return renderPin();
  if (!state.boot) {
    try {
      state.boot = await get('/bootstrap');
      state.settings = await get('/settings');
      if (state.settings.theme) applyTheme(state.settings.theme);
      renderTopbar();
      markNav(path);
    } catch (e) { clear(main); add(main, h('div', { class: 'notice bad' }, e.message)); return; }
    if (!isCurrent(token)) return;
  }
  const sidePages = ['bugun', 'analiz', 'kelimeler', 'ayarlar'];
  if (sidePages.includes(path)) { if (!side.firstChild || state.sideStale) { state.sideStale = false; renderScorePanel(); } }
  else { clear(side); layout.classList.add('full'); }
  if (path === 'bugun') return renderToday(token);
  if (path === 'calis') {
    if (!state.settings.setup_done) { location.hash = '#/kurulum'; return; }  // önce kurulum anketi + seviye testi
    state.sideStale = true;
    return params.get('mod') ? renderStudy(params) : renderParts(main, state, token);   // düz Çalış: part merkezi
  }
  if (path === 'analiz') return renderAnalysis(main, state, token);
  if (path === 'kelimeler') return renderWords(main, state, params);
  if (path === 'ayarlar') return renderSettings(main, state, applyTheme, renderTopbar, token);
  if (path === 'kurulum') { clear(side); layout.classList.add('full'); return renderSetup(main, state, params, runStudy, token); }
  location.hash = '#/bugun';
}

window.addEventListener('hashchange', route);
route();
