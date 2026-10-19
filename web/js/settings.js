// Ayarlar ve kurulum sihirbazı (anket → seviye testi → sonuç + ilk plan).
import { get, post } from './api.js';
import { h, add, clear, icon, fmt, toast, ICONS } from './util.js';
import { isCurrent, currentRoute } from './nav.js';
import * as sfx from './sfx.js';

const DAYS = ['Pazartesi', 'Salı', 'Çarşamba', 'Perşembe', 'Cuma', 'Cumartesi', 'Pazar'];

function field(label, input, help) {
  return h('label', { class: 'field' }, label, input, help ? h('span', { class: 'small muted', style: { fontWeight: 600 } }, help) : null);
}
function num(v, min, max, step = 1) { return h('input', { type: 'number', value: v ?? '', min, max, step }); }
function timeInput(v) { return h('input', { type: 'time', value: v || '' }); }
function daySelect(v) { return h('select', null, DAYS.map((d, i) => h('option', { value: i, selected: +v === i }, d))); }
// İngilizce seviyem (öz değerlendirme): puan tahmini dil bilgisi/okuma becerisini bundan başlatır
const LEVELS = [['A2', 'A2 — temel'], ['A2-B1', 'A2–B1'], ['B1', 'B1 — orta'], ['B1-B2', 'B1–B2'], ['B2', 'B2 — orta üstü'], ['C1', 'C1 — ileri']];
function levelSelect(v) { return h('select', null, LEVELS.map(([k, l]) => h('option', { value: k, selected: (v || 'B1') === k }, l))); }
const LEVEL_HELP = 'puan tahmini dil bilgisi/okuma becerini buradan başlatır; deneme sonucu girdikçe gerçek performansın belirler';

function timesEditor(list) {
  const wrap = h('div', { class: 'times' });
  const vals = [...(list || [])];
  const draw = () => {
    clear(wrap);
    vals.forEach((t, i) => {
      const inp = timeInput(t);
      inp.onchange = () => { vals[i] = inp.value; };
      add(wrap, inp, h('button', { class: 'linkbtn bad', onclick: (e) => { e.preventDefault(); vals.splice(i, 1); draw(); } }, '×'));
    });
    add(wrap, h('button', { class: 'btn sm', onclick: (e) => { e.preventDefault(); vals.push('20:00'); draw(); } }, icon('plus'), 'saat'));
  };
  draw();
  wrap.values = () => vals.filter(Boolean).sort();
  return wrap;
}

// ------------------------------------------------------------ ayarlar
export async function renderSettings(main, state, applyTheme, renderTopbar, token) {
  token = token ?? currentRoute();
  clear(main);
  const s = await get('/settings');
  if (!isCurrent(token)) return;
  state.settings = s;
  main.appendChild(h('h1', null, 'Ayarlar'));

  const name = h('input', { type: 'text', value: s.user_name });
  const exam = h('input', { type: 'date', value: s.exam_date });
  const examName = h('input', { type: 'text', value: s.exam_name || '' });
  const target = num(Math.round((s.target_recall || 0.95) * 100), 50, 100);
  const targetScore = num(s.target_score, 0, 100);
  const level = levelSelect(s.self_level);
  const finalDays = num(s.final_days, 0, 21);
  const wk = num(s.weekday_minutes, 0, 600, 5), we = num(s.weekend_minutes, 0, 600, 5);
  const hours = timesEditor(s.study_hours);
  const morning = timeInput(s.morning_time);
  const wday = daySelect(s.weekly_review_day);
  const wratio = num(Math.round((s.weekly_review_new_ratio || 0) * 100), 0, 100, 5);
  const qs = timeInput(s.quiet_start), qe = timeInput(s.quiet_end);
  const sessMin = num(s.max_session_minutes, 5, 90), brk = num(s.break_minutes, 1, 30);
  const pack = num(s.pack_size, 3, 10);
  const npd = num(s.new_per_day_override ?? '', 0, 300);
  const theme = h('select', null, [['auto', 'Sistem'], ['light', 'Açık'], ['dark', 'Koyu']].map(([v, l]) => h('option', { value: v, selected: s.theme === v }, l)));
  const notif = h('input', { type: 'checkbox', checked: s.notifications });
  const auto = h('input', { type: 'checkbox', checked: s.autostart });
  const reserve = h('input', { type: 'checkbox', checked: s.include_reserve });
  const exps = h('input', { type: 'checkbox', checked: s.experiments_enabled });
  // ses efektleri: doğru/yanlış, bitki büyümesi, part bitişi (Web Audio, çevrimdışı)
  const sfxOn = h('input', { type: 'checkbox', checked: s.sound_effects !== false });
  const sayOn = h('input', { type: 'checkbox', checked: s.speak_answers !== false });
  const listenOn = h('input', { type: 'checkbox', checked: s.listen_exercises !== false });
  const sfxVol = h('input', { type: 'range', min: 0, max: 100, step: 5, value: Math.round((s.sound_volume ?? 0.6) * 100), style: { width: '160px' } });
  const sfxTry = h('button', { class: 'btn sm', type: 'button', onclick: () => {
    sfx.configure({ sound_effects: true, sound_volume: +sfxVol.value / 100 });
    sfx.correct(); setTimeout(sfx.wrong, 600); setTimeout(sfx.bloom, 1300);
  } }, icon('speaker'), ' Dinle');

  const save = async () => {
    const body = {
      user_name: name.value.trim(), exam_date: exam.value, exam_name: examName.value,
      target_recall: (+target.value || 95) / 100, target_score: +targetScore.value || 55, self_level: level.value, final_days: +finalDays.value,
      weekday_minutes: +wk.value, weekend_minutes: +we.value, study_hours: hours.values(), morning_time: morning.value,
      weekly_review_day: +wday.value, weekly_review_new_ratio: (+wratio.value || 0) / 100, quiet_start: qs.value, quiet_end: qe.value,
      max_session_minutes: +sessMin.value, break_minutes: +brk.value, pack_size: +pack.value,
      new_per_day_override: npd.value === '' ? null : +npd.value, theme: theme.value, notifications: notif.checked,
      autostart: auto.checked, include_reserve: reserve.checked, experiments_enabled: exps.checked,
      sound_effects: sfxOn.checked, sound_volume: +sfxVol.value / 100,
      speak_answers: sayOn.checked, listen_exercises: listenOn.checked,
    };
    try {
      await post('/settings', body);
      applyTheme(body.theme);
      state.settings = await get('/settings');
      renderTopbar();
      toast('Kaydedildi; plan yeniden hesaplandı.');
    } catch (e) { toast(e.message, 'warn'); }
  };

  add(main, 
    card('Profil ve sınav', null,
      h('div', { class: 'grid3' }, field('Adın', name), field('Sınav tarihi', exam), field('Sınav adı', examName),
        field('Hedef hatırlama (%)', target, 'sınav günü listenin en az bu kadarını doğru ve hızlı tanımak'),
        field('Hedef puan', targetScore, 'puan tahmin panelinde vurgulanır'), field('İngilizce seviyem (tahminim)', level, LEVEL_HELP),
        field('Son tekrar dönemi (gün)', finalDays, 'bu dönemde yeni kelime gelmez'))),
    card('Zaman', null,
      h('div', { class: 'grid3' }, field('Hafta içi dakika', wk), field('Hafta sonu dakika', we), field('Sabah planı bildirimi', morning)),
      field('Tercih ettiğin çalışma saatleri (hatırlatmalar)', hours),
      h('div', { class: 'grid3', style: { marginTop: '.6rem' } }, field('Haftalık tekrar günü', wday), field('O gün yeni kelime oranı (%)', wratio, '0 = hiç'),
        field('Oturum/mola aralığı (dk)', sessMin)),
      h('div', { class: 'grid3' }, field('Sessiz saat başlangıcı', qs), field('Sessiz saat bitişi', qe), field('Mola süresi (dk)', brk))),
    card('Öğrenme', 'Bu değerler deneylerle otomatik ayarlanabilir; değişiklikler Analiz → Strateji günlüğünde.',
      h('div', { class: 'grid3' }, field('Paket büyüklüğü', pack), field('Günlük yeni kelime (elle sabitle)', npd, 'boş = planlayıcı belirler'),
        field('Tema', theme)),
      h('div', { class: 'col', style: { marginTop: '.6rem' } },
        h('label', { class: 'check' }, exps, 'Strateji deneyleri açık (paket büyüklüğü, ipucu türü, çeldirici zorluğu, alıştırma karışımı)'),
        h('label', { class: 'check' }, reserve, 'Yedek kelimeleri de plana al (kitap dışı eski liste; plan yalnızca Ezberbozan + garanti kelimelerle başlar)'),
        h('label', { class: 'check' }, notif, 'Windows bildirimleri'),
        h('label', { class: 'check' }, auto, 'Bilgisayar açılınca koç servisini başlat (sistem tepsisi)'),
        h('div', { class: 'row', style: { marginTop: '.3rem' } },
          h('label', { class: 'check' }, sfxOn, 'Ses efektleri (doğru/yanlış, bitki büyümesi, part bitişi)'),
          h('span', { class: 'small muted' }, 'ses düzeyi'), sfxVol, sfxTry),
        h('label', { class: 'check' }, sayOn, 'Cevaplayınca doğru cevabı sesli söyle (her alıştırmada)'),
        h('label', { class: 'check' }, listenOn, '"Dinle ve seç" alıştırması (kapalıysa yerine okumalı test gelir — sessiz ortam için)'))),
    h('div', { class: 'row', style: { marginTop: '1rem' } }, h('button', { class: 'btn primary lg', onclick: save }, 'Kaydet')),
  );

  // Gemini
  const llmBox = h('div');
  main.appendChild(card('Gemini (içerik üretimi)', 'Yalnızca örnek cümle/ipucu/rapor metni üretir; planlama ve puanlama deterministik koddur. İnternet veya kota yoksa çekirdek özellikler çalışmaya devam eder.', llmBox));
  const drawLLM = async () => {
    const st = await get('/llm/status');
    clear(llmBox);
    const key = h('input', { type: 'password', placeholder: st.configured ? '•••••••• (kayıtlı)' : 'API anahtarı', style: { flex: '1' } });
    const model = h('input', { type: 'text', placeholder: st.model || 'gemini-2.5-flash', style: { width: '200px' } });
    add(llmBox, 
      h('div', { class: 'row' }, key, model, h('button', { class: 'btn sm primary', onclick: async () => {
        if (!key.value.trim()) return toast('Anahtar boş');
        const r = await post('/llm/key', { key: key.value.trim(), model: model.value.trim() || null });
        toast('Kaydedildi: ' + r.path); drawLLM();
      } }, 'Kaydet'), h('button', { class: 'btn sm', onclick: async () => {
        const r = await post('/llm/test'); toast(r.ok ? `Bağlantı tamam (${r.model})` : 'Hata: ' + r.error, r.ok ? '' : 'warn', 6000);
      } }, 'Test et')),
      h('div', { class: 'row small ink2', style: { marginTop: '.5rem' } },
        h('span', { class: 'chip ' + (st.configured ? 'good' : 'warn') }, st.configured ? 'anahtar var' : 'anahtar yok'),
        `model: ${st.model}`, `· bugün ${st.usage_today.requests}/${st.daily_limit} istek`, `· ${st.rpm} istek/dk`,
        `· kuyruk: ${Object.entries(st.jobs).map(([k, v]) => k + ' ' + v).join(', ') || 'boş'}`),
      h('div', { class: 'row', style: { marginTop: '.5rem' } },
        h('button', { class: 'btn sm', onclick: async () => { const r = await post('/llm/enrich_missing'); toast(`${r.queued_words} kelime kuyruğa alındı`); drawLLM(); } }, 'Eksik içerikleri kuyruğa al'),
        h('button', { class: 'btn sm', onclick: async () => { const r = await post('/llm/retry'); toast(`${r.n} başarısız iş yeniden denenecek`); drawLLM(); } }, 'Başarısızları yeniden dene')),
      st.recent.length ? h('table', { class: 't', style: { marginTop: '.6rem' } }, st.recent.slice(0, 8).map(j => h('tr', null, h('td', null, j.kind), h('td', null, j.status),
        h('td', { class: 'small ink2' }, j.result || j.error || ''), h('td', { class: 'small muted' }, fmt.dt(j.updated_at))))) : null);
  };
  drawLLM();

  // telefon
  const lanBox = h('div');
  main.appendChild(card('Telefondan erişim', 'Aynı Wi-Fi\'deki telefonundan tekrar yapabilirsin (PIN korumalı). Windows Güvenlik Duvarı ilk seferde izin isteyebilir: "Özel ağlar"a izin ver.', lanBox));
  const drawLan = async () => {
    const l = await get('/lan');
    clear(lanBox);
    const pin = h('input', { type: 'password', inputmode: 'numeric', placeholder: l.has_pin ? 'yeni PIN (isteğe bağlı)' : '4-8 haneli PIN' });
    const en = h('input', { type: 'checkbox', checked: l.enabled });
    add(lanBox, h('div', { class: 'row' }, pin, h('label', { class: 'check' }, en, 'Erişim açık'),
      h('button', { class: 'btn sm primary', onclick: async () => {
        try { await post('/lan', { pin: pin.value || null, enabled: en.checked }); toast('Kaydedildi'); drawLan(); } catch (e) { toast(e.message, 'warn'); }
      } }, 'Uygula')));
    if (l.enabled && l.url) {
      const qr = h('div', { style: { width: '180px', background: '#fff', padding: '8px', borderRadius: '12px' } });
      if (l.qr_svg) qr.innerHTML = l.qr_svg;  // sunucuda üretilen QR (güvenilir)
      add(lanBox, h('div', { class: 'row', style: { marginTop: '.8rem', alignItems: 'flex-start' } }, qr,
        h('div', null, h('div', null, 'Telefonda aç: ', h('b', null, l.url)), h('div', { class: 'small muted' }, 'Diğer adresler: ' + l.addresses.join(', ')),
          h('div', { class: 'small muted' }, 'Ana ekrana ekleyerek uygulama gibi kullanabilirsin.'))));
    }
  };
  drawLan();

  // veri
  const dataBox = h('div');
  main.appendChild(card('Veri, yedek ve dışa aktarma', `Veri klasörü: ${s.data_dir} · .env: ${s.env_path}`, dataBox));
  const drawData = async () => {
    const b = await get('/backups');
    clear(dataBox);
    add(dataBox, 
      h('div', { class: 'row' }, h('button', { class: 'btn sm', onclick: async () => { const r = await post('/backup'); toast('Yedek: ' + r.path); drawData(); } }, icon('download'), 'Şimdi yedekle'),
        h('a', { class: 'btn sm', href: '/api/export/hepsi.zip' }, icon('download'), 'Tüm veriyi CSV (zip)'),
        ...['events', 'kelimeler', 'oturumlar', 'strateji_gunlugu'].map(n => h('a', { class: 'btn sm', href: `/api/export/${n}.csv` }, n + '.csv'))),
      h('div', { class: 'small muted', style: { marginTop: '.5rem' } }, `Her gün otomatik yedek alınır (son 14 kopya). Klasör: ${b.dir}`),
      h('table', { class: 't', style: { marginTop: '.4rem' } }, b.items.slice(0, 6).map(x => h('tr', null, h('td', null, x.name), h('td', { class: 'num' }, x.size_kb + ' KB')))),
      h('div', { class: 'row', style: { marginTop: '.8rem' } },
        h('button', { class: 'btn sm', onclick: () => { location.hash = '#/kurulum?adim=seviye'; } }, icon('target'), 'Seviye testini yeniden yap'),
        h('button', { class: 'btn sm', onclick: () => { location.hash = '#/kurulum'; } }, 'Kurulum anketini yeniden aç'),
        h('button', { class: 'btn sm', onclick: async () => { const r = await post('/weekly_jobs'); toast('Haftalık işler çalıştı: ' + (r.fsrs && (r.fsrs.reason || (r.fsrs.accepted ? 'FSRS güncellendi' : 'FSRS değişmedi'))), '', 6000); } }, 'Haftalık optimizasyonu şimdi çalıştır')));
  };
  drawData();
  main.appendChild(h('p', { class: 'muted small', style: { marginTop: '1.2rem' } }, `YDS Kelime Koçu · Nunito yazı tipi SIL Open Font License ile kullanılmıştır.`));
}

function card(title, sub, ...children) {
  return h('div', { class: 'card', style: { marginTop: '1rem' } }, h('h2', null, title), sub ? h('div', { class: 'sub' }, sub) : null, ...children);
}

// ------------------------------------------------------------ kurulum sihirbazı
export async function renderSetup(main, state, params, runStudy, token) {
  token = token ?? currentRoute();
  clear(main);
  const s = await get('/settings');
  if (!isCurrent(token)) return;
  const step = params.get('adim') || 'anket';
  const wrap = h('div', { class: 'wizard' });
  main.appendChild(wrap);
  const steps = (n) => h('div', { class: 'steps' }, [0, 1, 2].map(i => h('span', { class: i <= n ? 'on' : '' })));

  if (step === 'seviye') {
    add(wrap, steps(1), h('div', { class: 'card' }, h('h1', null, 'Seviye tespiti (~15 dk)'),
      h('p', { class: 'ink2' }, 'Amaç genel seviyeni ölçmek değil: listendeki hangi kelimeleri zaten bildiğini bulmak ve boşa zaman harcamamak. Sorular sıklık katmanlarından uyarlamalı seçilir; süren ölçülür. "Biliyorum" beyanı yok — yalnızca cevapların sayılır. Emin değilsen tahmin etme, "Bilmiyorum"a bas (0).'),
      h('ul', { class: 'planlist' }, h('li', null, 'Her soruda İngilizce kelimenin Türkçesini seç (1–5 tuşları).'),
        h('li', null, 'Doğru ve hızlı bildiklerin kısa bir doğrulama turuna girer; geçersen uzun aralıklı tekrara gider.'),
        h('li', null, 'Test sonunda katman bazında bildiğin oran, hız profilin ve ilk planın gösterilir.')),
      h('div', { class: 'row', style: { marginTop: '1rem' } },
        h('button', { class: 'btn ghost', onclick: async () => { await post('/settings', {}); location.hash = '#/bugun'; } }, 'Şimdilik atla'),
        h('span', { class: 'spacer' }),
        h('button', { class: 'btn primary lg', onclick: () => {
          runStudy(main, { placement: true, settings: s, onExit: (res) => showPlacementResult(main, res && res.result) });
        } }, 'Teste başla'))));
    return;
  }

  // anket
  const name = h('input', { type: 'text', value: s.user_name || '', placeholder: 'Adın' });
  const exam = h('input', { type: 'date', value: s.exam_date });
  const target = num(Math.round((s.target_recall || 0.95) * 100), 50, 100);
  const tscore = num(s.target_score || 55, 0, 100);
  const lvl = levelSelect(s.self_level);
  const wk = num(s.weekday_minutes, 10, 600, 5), we = num(s.weekend_minutes, 10, 600, 5);
  const hours = timesEditor(s.study_hours);
  const morning = timeInput(s.morning_time);
  const wday = daySelect(s.weekly_review_day);
  const qs = timeInput(s.quiet_start), qe = timeInput(s.quiet_end);
  add(wrap, steps(0), h('div', { class: 'card' },
    h('div', { class: 'row' }, h('img', { src: '/static/icon.png', style: { width: '64px' } }), h('div', null, h('h1', { style: { margin: 0 } }, 'Hoş geldin!'),
      h('div', { class: 'ink2' }, 'Kısa bir kurulum: süren, saatlerin ve hedefin. Sonra ~15 dakikalık seviye tespiti.'))),
    h('div', { class: 'section-title' }, 'Hedef'),
    h('div', { class: 'grid2' }, field('Adın', name), field('Sınav tarihi', exam, '2026-YDS/2 varsayılan'),
      field('Hedef hatırlama (%)', target, 'sınav günü listenin en az bu kadarı'), field('Hedef puan', tscore, '55 = 80 sorudan 44 doğru'),
      field('İngilizce seviyem (tahminim)', lvl, LEVEL_HELP)),
    h('div', { class: 'section-title' }, 'Ayırabileceğin süre (aktif çalışma)'),
    h('div', { class: 'grid2' }, field('Hafta içi (dk/gün)', wk), field('Hafta sonu (dk/gün)', we)),
    field('Tercih ettiğin çalışma saatleri', hours, 'bu saatlerde plan bitmemişse hatırlatma gelir'),
    h('div', { class: 'section-title' }, 'Düzen'),
    h('div', { class: 'grid2' }, field('Sabah planı bildirimi', morning), field('Haftalık tekrar günü', wday, 'o gün yeni kelime yok; YDS tarzı karışık test')),
    h('div', { class: 'grid2' }, field('Sessiz saatler başlangıç', qs), field('Sessiz saatler bitiş', qe)),
    h('div', { class: 'row', style: { marginTop: '1.2rem' } }, h('span', { class: 'spacer' }),
      h('button', { class: 'btn primary lg', onclick: async () => {
        try {
          await post('/setup', {
            user_name: name.value.trim(), exam_date: exam.value, target_recall: (+target.value || 95) / 100, target_score: +tscore.value || 55,
            self_level: lvl.value,
            weekday_minutes: +wk.value, weekend_minutes: +we.value, study_hours: hours.values(), morning_time: morning.value,
            weekly_review_day: +wday.value, quiet_start: qs.value, quiet_end: qe.value,
          });
          state.settings = await get('/settings');
          location.hash = '#/kurulum?adim=seviye';
        } catch (e) { toast(e.message, 'warn'); }
      } }, 'Devam: seviye tespiti'))));
}

function showPlacementResult(main, r) {
  clear(main);
  document.body.classList.remove('studying');
  const wrap = h('div', { class: 'wizard' });
  main.appendChild(wrap);
  if (!r) { add(wrap, h('div', { class: 'card' }, h('h2', null, 'Test tamamlanmadı'), h('a', { class: 'btn primary', href: '#/bugun' }, 'Ana sayfa'))); return; }
  const tiers = h('div');
  for (const t of r.tiers) {
    if (t.known_rate === null || t.known_rate === undefined) {
      tiers.appendChild(h('div', { class: 'tier-row' }, h('span', { style: { fontWeight: 800 } }, t.label),
        h('span', { class: 'small muted' }, `yetersiz veri (${t.n} soru) — CEFR tahmini kullanılacak`), h('span')));
      continue;
    }
    tiers.appendChild(h('div', { class: 'tier-row' }, h('span', { style: { fontWeight: 800 } }, t.label),
      h('div', { class: 'tbar', title: `%80 güven aralığı ${Math.round(t.ci80[0] * 100)}–${Math.round(t.ci80[1] * 100)}` },
        h('div', { class: 'f', style: { width: Math.round(t.known_rate * 100) + '%' } }),
        h('div', { class: 'ci', style: { left: Math.round(t.ci80[0] * 100) + '%', width: Math.max(1, Math.round((t.ci80[1] - t.ci80[0]) * 100)) + '%' } })),
      h('span', { class: 'tabular', style: { fontWeight: 900, textAlign: 'right' } }, `%${Math.round(t.known_rate * 100)}`)));
  }
  const plan = r.plan || {};
  add(wrap, h('div', { class: 'steps' }, [0, 1, 2].map(() => h('span', { class: 'on' }))),
    h('div', { class: 'card' }, h('h1', null, 'Seviye tespiti sonucu'),
      h('p', { class: 'ink2' }, `${r.items} soru, ${r.minutes} dk. ` + (r.overall_known !== null && r.overall_known !== undefined
        ? `Listenin tahminen %${Math.round(r.overall_known * 100)}'ini zaten biliyorsun.` : 'Tahmin için yeterli cevap yok.')),
      h('div', { class: 'section-title' }, 'Katman bazında bilinen oran (çizgi: %80 güven aralığı)'), tiers,
      h('div', { class: 'section-title' }, 'Hız profili'),
      h('div', null, r.speed && r.speed.median_ms ? `Doğru cevaplarda medyan ${fmt.sec(r.speed.median_ms)} (P25 ${fmt.sec(r.speed.p25_ms)}, P75 ${fmt.sec(r.speed.p75_ms)}).` : 'Yeterli veri yok.'),
      h('div', { class: 'section-title' }, 'İlk strateji'),
      h('ul', { class: 'planlist' }, (r.strategy || []).map(x => h('li', null, x))),
      h('div', { class: 'section-title' }, 'İlk plan ve gerekçesi'),
      h('div', { class: 'note' }, h('b', null, `Bugün: ${plan.new_planned ?? 0} yeni + ${plan.reviews_planned ?? 0} tekrar ≈ ${plan.minutes ?? 0} dk`),
        h('ul', { class: 'planlist' }, (plan.rationale || []).map(x => h('li', null, x)))),
      h('div', { class: 'row', style: { marginTop: '1rem' } }, h('span', { class: 'spacer' }),
        h('a', { class: 'btn primary lg', href: '#/bugun' }, 'Çalışmaya başla'))));
}
