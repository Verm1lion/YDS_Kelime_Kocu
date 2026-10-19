// Analiz ekranı: ısı haritası, günlük süre/doğruluk, hata türleri, özellik grupları, saat/dakika/gün,
// hız trendi, en zor kelimeler, karışıklık çiftleri, öğrenme maliyeti, müdahaleler, strateji günlüğü, raporlar.
import { get, post, del } from './api.js';
import { h, add, clear, icon, fmt, toast } from './util.js';
import { lineChart, columnChart, hbars, heatmap } from './charts.js';
import { mockDialog } from './app.js';
import { isCurrent, currentRoute } from './nav.js';

const POS_TR = { n: 'isim', v: 'fiil', adj: 'sıfat', adv: 'zarf' };

export async function renderAnalysis(main, state, token) {
  token = token ?? currentRoute();
  clear(main);
  main.appendChild(h('div', { class: 'muted' }, 'Analiz hesaplanıyor…'));
  let a, pr, reps, mocks;
  try {
    [a, pr, reps, mocks] = await Promise.all([get('/analysis'), get('/projection'), get('/reports'), get('/mocks')]);
  } catch (e) { if (isCurrent(token)) { clear(main); add(main, h('div', { class: 'notice bad' }, e.message)); } return; }
  if (!isCurrent(token)) return;
  clear(main);
  main.appendChild(h('h1', null, 'Analiz'));
  main.appendChild(h('p', { class: 'ink2' }, 'Tüm sayılar ham olay kaydından yeniden hesaplanır. ', h('a', { href: '/api/export/hepsi.zip' }, 'CSV olarak indir')));

  // projeksiyon
  const pc = h('div');
  const projCard = card('Sınav günü projeksiyonu', pr.message || '', pc);
  main.appendChild(projCard);
  const hist = (pr.history || []).map(x => ({ x: new Date(x.day + 'T12:00:00'), pace: x.pace, plan: x.plan, learned: x.learned }));
  lineChart(pc, { series: [
    { name: 'Bu tempoyla', color: 'var(--series-1)', points: hist.map(x => ({ x: x.x, y: x.pace })) },
    { name: 'Plana uyarsan', color: 'var(--series-2)', points: hist.map(x => ({ x: x.x, y: x.plan })) }],
    target: { y: pr.target, label: `hedef ${fmt.pct(pr.target)}` }, yMin: 0, yMax: 1, yFormat: (v) => '%' + Math.round(v * 100),
    xMax: new Date(pr.exam_date + 'T12:00:00'), marker: { x: new Date(pr.exam_date + 'T12:00:00'), label: 'sınav' } });
  if (pr.pace) projCard.appendChild(h('div', { class: 'row small ink2', style: { marginTop: '.5rem' } },
    `Tempo: günde ~${Math.round(pr.pace.new_per_day || 0)} yeni, ${Math.round(pr.pace.minutes_per_day || 0)} dk`,
    `· Hızlı tanıma oranı ${fmt.pct(pr.fast_fraction)}`, `· "Doğru ve hızlı" tahmini ${fmt.pct(pr.pace.fast_mean)}`,
    pr.pace.p10 !== undefined ? `· %80 aralık ${fmt.pct(pr.pace.p10)}–${fmt.pct(pr.pace.p90)}` : ''));

  // takvim + günlük
  const hm = h('div');
  main.appendChild(card('Çalışma takvimi', 'Günlük aktif çalışma süresi (60 sn işlemsizlik ve arka plan sayılmaz)', hm));
  // takvim: ilk çalışılan haftadan bugüne (boş geçmiş haftalar gösterilmez)
  const firstIdx = a.heatmap.findIndex(d => d.minutes > 0);
  let hmDays = firstIdx >= 0 ? a.heatmap.slice(firstIdx) : a.heatmap.slice(-1);
  heatmap(hm, hmDays);
  const daily = a.daily.filter(d => d.answers || d.minutes);
  const dm = h('div'), da = h('div');
  main.appendChild(h('div', { class: 'grid2', style: { marginTop: '1rem' } },
    card('Günlük süre (dk)', 'Planlanan bütçe kesikli çizgiyle', dm), card('Günlük doğruluk', 'Tüm alıştırmalar', da)));
  const budget = state.settings.weekday_minutes || 60;
  columnChart(dm, { data: daily.slice(-30).map(d => ({ label: fmt.date(d.day), short: d.day.slice(8), value: d.minutes, tip: `${d.answers} cevap · ${d.new} yeni` })),
    yFormat: (v) => Math.round(v), refLine: { y: budget, label: `hafta içi bütçe ${budget} dk` }, seriesName: 'aktif dk' });
  lineChart(da, { series: [{ name: 'Doğruluk', color: 'var(--series-1)', area: true, points: daily.filter(d => d.accuracy !== null).map(d => ({ x: new Date(d.day + 'T12:00:00'), y: d.accuracy })) }],
    yMin: 0, yMax: 1, yFormat: (v) => '%' + Math.round(v * 100), height: 200 });

  // hata türleri
  const et = h('div');
  const errs = a.errors;
  hbars(et, errs.types.filter(t => t.count).map(t => ({ label: t.type, value: t.count, tip: `${t.count} (${fmt.pct(t.share, 1)} tüm cevapların)` })), { format: (v) => fmt.num(v) });
  const errCard = card('Hata türleri', `${fmt.num(errs.total_answers)} cevap, ${fmt.num(errs.wrong)} yanlış. Şans doğrusu = seçmelide doğru, 3 gün içinde yazmada yanlış.`, et);
  if (errs.direction_gap_words.length) {
    errCard.appendChild(h('div', { class: 'section-title' }, 'Yön farkı: EN→TR biliyor, TR→EN bilmiyor'));
    errCard.appendChild(h('div', { class: 'row', style: { gap: '.35rem' } }, errs.direction_gap_words.map(w => h('span', { class: 'chip warn', title: `EN→TR ${fmt.pct(w.en_tr)} · TR→EN ${fmt.pct(w.tr_en)}` }, w.display))));
  }
  main.appendChild(errCard);

  // özellik grupları
  const fg = h('div', { class: 'grid2' });
  for (const [g, rows] of Object.entries(a.features.groups)) {
    const box = h('div');
    hbars(box, rows.filter(r => r.n >= 5).map(r => ({ label: POS_TR[r.group] || r.group, value: r.accuracy || 0, emph: r.weak,
      tip: `n=${r.n} · medyan ${fmt.sec(r.median_ms)}` })), { max: 1, format: (v) => '%' + Math.round(v * 100) });
    fg.appendChild(h('div', null, h('div', { class: 'section-title' }, g), box));
  }
  const featCard = card('Kelime özelliklerine göre doğruluk', `Genel doğruluk ${fmt.pct(a.features.overall_accuracy)}. Vurgulu satırlar ortalamanın ≥8 puan altında (n≥30).`, fg);
  if (a.features.weak_groups.length) featCard.insertBefore(h('div', { class: 'notice warn' }, icon('warn'), 'Zorlandığın gruplar: ' + a.features.weak_groups.join('; ')), fg);
  main.appendChild(featCard);

  // zaman
  const th = h('div'), tm = h('div'), tw = h('div');
  main.appendChild(h('div', { class: 'grid3', style: { marginTop: '1rem' } },
    card('Saate göre doğruluk', '', th), card('Oturum dakikasına göre', 'yorgunluk etkisi', tm), card('Haftanın gününe göre', '', tw)));
  const tcol = (rows) => rows.map(r => ({ label: r.label, short: r.label.split(':')[0].split(' ')[0], value: r.accuracy || 0, tip: `n=${r.n} · medyan ${fmt.sec(r.median_ms)}` }));
  columnChart(th, { data: tcol(a.time.by_hour), yMax: 1, yFormat: (v) => '%' + Math.round(v * 100), height: 180 });
  columnChart(tm, { data: tcol(a.time.by_session_minute), yMax: 1, yFormat: (v) => '%' + Math.round(v * 100), height: 180 });
  columnChart(tw, { data: tcol(a.time.by_weekday), yMax: 1, yFormat: (v) => '%' + Math.round(v * 100), height: 180 });
  if (a.late_hours) main.appendChild(h('div', { class: 'notice info', style: { marginTop: '.8rem' } }, icon('clock'),
    `${String(a.late_hours.cut).padStart(2, '0')}.00'den sonra doğruluğun %${Math.round(a.late_hours.drop * 100)} düşüyor; en iyi saatin ${String(a.late_hours.best_hour).padStart(2, '0')}.00.`));

  // hız trendi
  const sp = h('div');
  main.appendChild(card('Hız trendi', 'Doğru cevaplarda hatırlama süresinin kişisel "hızlı" eşiğine oranı (düşük = daha otomatik)', sp));
  lineChart(sp, { series: [{ name: 'Göreli süre', color: 'var(--series-1)', points: a.speed.map(s => ({ x: new Date(s.day + 'T12:00:00'), y: s.norm_latency })) }],
    yMin: 0, yFormat: (v) => v.toFixed(1) + '×', height: 180 });

  // zor kelimeler + karışıklıklar
  const hard = h('table', { class: 't' }, h('tr', null, h('th', null, 'Kelime'), h('th', null, 'Anlam'), h('th', { class: 'num' }, 'Yanlış'), h('th', { class: 'num' }, 'Unutma'), h('th', { class: 'num' }, 'Doğruluk')),
    a.hardest.map(w => h('tr', null, h('td', null, h('b', null, w.display)), h('td', { class: 'ink2' }, w.meaning), h('td', { class: 'num' }, w.wrong_total), h('td', { class: 'num' }, w.lapses), h('td', { class: 'num' }, fmt.pct(w.accuracy)))));
  const conf = h('table', { class: 't' }, h('tr', null, h('th', null, 'Çift'), h('th', { class: 'num' }, 'Karışma')),
    a.confusions.map(c => h('tr', null, h('td', null, h('b', null, c.a_display), ' (', c.a_meaning, ') ↔ ', h('b', null, c.b_display), ' (', c.b_meaning, ')'), h('td', { class: 'num' }, c.n))));
  main.appendChild(h('div', { class: 'grid2', style: { marginTop: '1rem' } },
    card('En zor 20 kelime', 'yanlış + unutma + zorluk', a.hardest.length ? hard : empty()),
    card('Karışıklık çiftleri', 'Seçmeli/yazma cevaplarında karıştırdığın kelimeler', a.confusions.length ? conf : empty())));

  // maliyet + müdahaleler
  const cost = a.cost;
  const costEl = cost.n ? h('div', { class: 'grid2' },
    stat('Kalıcı hale gelen', fmt.num(cost.n), 'merdiven tamam + S ≥ 7 gün'), stat('Medyan deneme', fmt.num(cost.median_attempts), `%90: ${cost.p90_attempts}`),
    stat('Medyan süre', fmt.num(cost.median_minutes, 1) + ' dk', 'kelime başına'), stat('Ortalama süre', fmt.num(cost.mean_minutes, 1) + ' dk', 'iş yükü tahmininde kullanılır'))
    : h('div', { class: 'muted small' }, 'Henüz kalıcı hale gelen kelime yok.');
  const iv = a.interventions;
  const ivRows = Object.entries(iv.by_kind || {});
  const ivEl = ivRows.length ? h('table', { class: 't' }, h('tr', null, h('th', null, 'Müdahale'), h('th', { class: 'num' }, 'Sayı'), h('th', { class: 'num' }, 'Öncesi'), h('th', { class: 'num' }, 'Sonrası'), h('th', { class: 'num' }, 'İşe yaradı')),
    ivRows.map(([k, v]) => h('tr', null, h('td', null, { mnemonic: 'yeni ipucu', etymology: 'kök/köken', compare: 'karşılaştırma', examples: 'yeni örnekler', switch: 'alıştırma değişimi' }[k] || k),
      h('td', { class: 'num' }, v.n), h('td', { class: 'num' }, fmt.pct(v.pre_acc)), h('td', { class: 'num' }, fmt.pct(v.post_acc)), h('td', { class: 'num' }, v.evaluated ? fmt.pct(v.success_rate) : '—'))))
    : h('div', { class: 'muted small' }, '4+ hata yapılan kelimelere otomatik müdahale yapılır; etkisi sonraki 3+ cevapta ölçülür.');
  main.appendChild(h('div', { class: 'grid2', style: { marginTop: '1rem' } }, card('Öğrenme maliyeti', 'kalıcı hale gelene kadar', costEl), card('İnatçı kelime müdahaleleri', `${a.stubborn.length} inatçı kelime`, ivEl)));

  // strateji günlüğü
  const sg = a.strategy;
  const exps = h('div', { class: 'col' }, sg.experiments.filter(e => e.status === 'running').map(e => {
    const arms = Object.entries(e.arms);
    return h('div', { class: 'note' }, h('b', null, `${e.label || e.variable} — deney sürüyor`),
      arms.length ? arms.map(([k, v]) => h('div', { class: 'small' }, `${v.label || k}: ${v.n} sonuç, başarı ${fmt.pct(v.rate)} · P(en iyi) ${fmt.pct(e.p_best[k])}`))
        : h('div', { class: 'small muted' }, 'henüz atama yok'));
  }));
  const log = h('div', { class: 'col' }, sg.log.length ? sg.log.map(l => h('div', { class: 'note' },
    h('b', null, `${fmt.dt(l.ts)} · ${l.variable}${l.reverted ? ' (geri alındı)' : ''}`), l.reason,
    !l.reverted && l.reason !== 'Kullanıcı tarafından geri alındı' && l.old_value !== l.new_value ? h('div', null, h('button', { class: 'linkbtn', onclick: async () => {
      await post(`/strategy/revert/${l.id}`); toast('Geri alındı.'); renderAnalysis(main, state, currentRoute());
    } }, '↶ geri al')) : null)) : h('div', { class: 'muted small' }, 'Henüz değişiklik yok. Kararlar yalnızca yeterli örnek birikince verilir (kol başına ≥40 kelime).'));
  const toggle = h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: sg.enabled, onchange: async (e) => { await post('/strategy/toggle', { enabled: e.target.checked }); toast('Kaydedildi'); } }), 'Deneyler açık');
  main.appendChild(h('div', { class: 'grid2', style: { marginTop: '1rem' } }, card('Strateji deneyleri', 'ölçüt: ertesi gün hatırlama (doğru ve yavaş değil)', toggle, exps), card('Strateji günlüğü', 'her değişiklik gerekçesi ve verisiyle', log)));

  // haftalık rapor
  const rep = reps[0];
  const repEl = rep ? h('div', null, h('div', { class: 'small muted' }, `${rep.week_start} haftası · kaynak: ${rep.source || 'şablon'}`),
    h('div', { style: { whiteSpace: 'pre-wrap', marginTop: '.4rem' } }, rep.text || '')) : h('div', { class: 'muted small' }, 'Haftalık rapor, haftalık tekrar gününde oluşturulur.');
  const mk = h('button', { class: 'btn sm', onclick: async () => { await post('/reports/make'); toast('Rapor oluşturuldu (LLM metni internet varsa gelir).'); renderAnalysis(main, state, currentRoute()); } }, icon('refresh'), 'Şimdi oluştur');
  // deneme sınavları
  const mockEl = h('div', null, mocks.length ? h('table', { class: 't' }, h('tr', null, h('th', null, 'Tarih'), h('th', { class: 'num' }, 'Doğru'), h('th', { class: 'num' }, 'Puan'), h('th', null, 'Not'), h('th', null, '')),
    mocks.map(m => h('tr', null, h('td', null, fmt.date(m.day)), h('td', { class: 'num' }, m.total_correct), h('td', { class: 'num' }, (m.total_correct * 1.25).toFixed(2)), h('td', { class: 'ink2' }, m.note || ''),
      h('td', null, h('button', { class: 'linkbtn bad', onclick: async () => { await del(`/mocks/${m.id}`); renderAnalysis(main, state, currentRoute()); } }, 'sil'))))) : h('div', { class: 'muted small' }, 'Deneme sonucu girilmedi. Puan tahmini bu sonuçlarla keskinleşir.'),
    h('button', { class: 'btn sm', style: { marginTop: '.6rem' }, onclick: mockDialog }, icon('plus'), 'Deneme sonucu ekle'));
  main.appendChild(h('div', { class: 'grid2', style: { marginTop: '1rem' } }, card('Haftalık rapor', 'sayılar uygulamadan, anlatım yapay zekâdan (yoksa şablon)', repEl, mk), card('Deneme sınavları', 'puan tahmin modelini besler', mockEl)));
}

function card(title, sub, ...children) {
  return h('div', { class: 'card', style: { marginTop: '1rem' } }, h('h2', null, title), sub ? h('div', { class: 'sub' }, sub) : null, ...children);
}
function stat(label, value, foot) {
  return h('div', { class: 'stat' }, h('div', { class: 'label' }, label), h('div', { class: 'value', style: { fontSize: '1.5rem' } }, value), foot ? h('div', { class: 'foot' }, foot) : null);
}
function empty() { return h('div', { class: 'muted small' }, 'Henüz veri yok.'); }
