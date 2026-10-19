// Ses efektleri: tarayıcıda Web Audio ile üretilir (dosya yok, çevrimdışı). Ayarlar → Ses efektleri / ses düzeyi.
let ctx = null;
let enabled = true;
let volume = 0.6;

export function configure(settings = {}) {
  enabled = settings.sound_effects !== false;
  const v = Number(settings.sound_volume);
  volume = Number.isFinite(v) ? Math.max(0, Math.min(1, v)) : 0.6;
}

function ac() {
  if (!enabled || volume <= 0) return null;
  try {
    if (!ctx) ctx = new (window.AudioContext || window.webkitAudioContext)();
    if (ctx.state === 'suspended') ctx.resume();
    return ctx;
  } catch (e) { return null; }   // ses aygıtı yok / tarayıcı izin vermedi: sessizce geç
}

// tek nota: hızlı atak, üstel sönüm (tıklama/çatlama yapmaz)
function tone(c, { freq, type = 'sine', at = 0, dur = 0.18, gain = 0.2, slideTo = null }) {
  const t0 = c.currentTime + at;
  const o = c.createOscillator();
  const g = c.createGain();
  o.type = type;
  o.frequency.setValueAtTime(freq, t0);
  if (slideTo) o.frequency.exponentialRampToValueAtTime(slideTo, t0 + dur);
  g.gain.setValueAtTime(0.0001, t0);
  g.gain.exponentialRampToValueAtTime(Math.max(0.0002, gain * volume), t0 + 0.006);
  g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
  o.connect(g);
  g.connect(c.destination);
  o.start(t0);
  o.stop(t0 + dur + 0.03);
}

const play = (fn) => () => { const c = ac(); if (c) fn(c); };

// doğru: parlak, yükselen iki nota (Memrise tarzı "ding")
export const correct = play((c) => {
  tone(c, { freq: 880, dur: 0.14, gain: 0.2 });
  tone(c, { freq: 1318.5, at: 0.075, dur: 0.3, gain: 0.18 });
  tone(c, { freq: 2637, at: 0.075, dur: 0.16, gain: 0.035 });
});

// yanlış: kısa, yumuşak, alçalan "bonk" (cezalandırmadan haber verir)
export const wrong = play((c) => {
  tone(c, { freq: 233, type: 'triangle', dur: 0.24, gain: 0.26, slideTo: 155 });
  tone(c, { freq: 116.5, dur: 0.26, gain: 0.14 });
});

// yazım hatası / zor ama doğru: nötr tek nota
export const almost = play((c) => {
  tone(c, { freq: 659.25, dur: 0.2, gain: 0.16 });
});

// bitki büyüdü (basamak atladı): yükselen üçlü
export const levelUp = play((c) => {
  [659.25, 830.61, 987.77].forEach((f, i) => tone(c, { freq: f, at: i * 0.07, dur: 0.2, gain: 0.12 }));
});

// kelime çiçek açtı / part bitti: arpej + parıltı
export const bloom = play((c) => {
  [523.25, 659.25, 783.99, 1046.5, 1318.5].forEach((f, i) => tone(c, { freq: f, at: i * 0.075, dur: 0.32, gain: 0.12 }));
  tone(c, { freq: 2093, at: 0.38, dur: 0.4, gain: 0.04 });
});

// doğru serisi (5, 10, 15 ...)
export const combo = play((c) => {
  [987.77, 1318.5].forEach((f, i) => tone(c, { freq: f, at: i * 0.06, dur: 0.16, gain: 0.1 }));
});

// harf kutusu yerleşti: çok hafif tık
export const tick = play((c) => {
  tone(c, { freq: 1500, type: 'square', dur: 0.025, gain: 0.025 });
});
