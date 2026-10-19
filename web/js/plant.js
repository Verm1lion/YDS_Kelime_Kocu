// Kelimenin büyüme simgesi (merdiven basamağı 0-6): tohum → filiz → fide → tomurcuk → çiçek.
// Etrafındaki halka basamak ilerlemesini gösterir.

const STAGE_LABEL = ['Tohum', 'Filiz', 'Fide', 'Genç bitki', 'Tomurcuk', 'Açan çiçek', 'Çiçek (öğrenildi)'];
export const stageLabel = (s) => STAGE_LABEL[Math.max(0, Math.min(6, s | 0))];

export function plantSVG(stage, size = 40, wilted = false) {
  const s = Math.max(0, Math.min(6, stage | 0));
  const r = 21, c = 2 * Math.PI * r;
  const frac = s / 6;
  const ring = `<circle cx="24" cy="24" r="${r}" fill="none" stroke="var(--surface-3)" stroke-width="3"/>
    <circle cx="24" cy="24" r="${r}" fill="none" stroke="${s >= 6 ? 'var(--good)' : 'var(--brand-2)'}" stroke-width="3"
      stroke-linecap="round" stroke-dasharray="${(c * frac).toFixed(1)} ${c.toFixed(1)}" transform="rotate(-90 24 24)"/>`;
  const soil = `<ellipse cx="24" cy="36" rx="11" ry="3.2" fill="var(--soil)"/>`;
  let plant = '';
  const lean = wilted ? ' transform="rotate(18 24 35)"' : '';
  if (s === 0) {
    plant = `<ellipse cx="24" cy="33.5" rx="3.2" ry="2.4" fill="var(--soil)" stroke="#6b4a2b" stroke-width=".8"/>`;
  } else {
    const h = [0, 7, 10, 13, 15, 16, 17][s];
    const top = 35 - h;
    plant += `<path d="M24 35 L24 ${top}" stroke="var(--leaf-2)" stroke-width="2.2" stroke-linecap="round"/>`;
    const leaf = (y, dir, len) => `<path d="M24 ${y} q ${dir * len * .5} ${-len * .55} ${dir * len} ${-len * .2} q ${-dir * len * .45} ${len * .45} ${-dir * len} ${len * .2}z" fill="var(--leaf)"/>`;
    plant += leaf(35 - Math.min(h, 5), -1, s >= 2 ? 7 : 5) + leaf(35 - Math.min(h, 6) + 1, 1, s >= 2 ? 7 : 5);
    if (s >= 3) plant += leaf(top + 5, -1, 6) + leaf(top + 6, 1, 6);
    if (s === 4) plant += `<ellipse cx="24" cy="${top - 1.5}" rx="2.6" ry="3.6" fill="var(--leaf)"/><path d="M22.6 ${top - 3} q1.4 -2 2.8 0" fill="var(--petal)"/>`;
    if (s === 5) {
      for (let k = 0; k < 3; k++) {
        const a = -90 + (k - 1) * 40;
        const x = 24 + Math.cos(a * Math.PI / 180) * 3.5, y = top - 2 + Math.sin(a * Math.PI / 180) * 3.5;
        plant += `<ellipse cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" rx="2.4" ry="3.4" fill="var(--petal)" transform="rotate(${a + 90} ${x.toFixed(1)} ${y.toFixed(1)})"/>`;
      }
      plant += `<circle cx="24" cy="${top - 1}" r="2" fill="var(--petal-2)"/>`;
    }
    if (s >= 6) {
      for (let k = 0; k < 6; k++) {
        const a = k * 60;
        const x = 24 + Math.cos(a * Math.PI / 180) * 4, y = top - 3 + Math.sin(a * Math.PI / 180) * 4;
        plant += `<ellipse cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" rx="2.6" ry="3.6" fill="var(--petal)" transform="rotate(${a + 90} ${x.toFixed(1)} ${y.toFixed(1)})"/>`;
      }
      plant += `<circle cx="24" cy="${top - 3}" r="2.6" fill="var(--petal-2)"/>`;
    }
  }
  return `<svg class="plant" width="${size}" height="${size}" viewBox="0 0 48 48" role="img" aria-label="${STAGE_LABEL[s]}">${ring}${soil}<g${lean}>${plant}</g></svg>`;
}
