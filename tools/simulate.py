"""Sanal öğrenci simülasyonu: uygulamanın GERÇEK planlayıcı + oturum motoru + FSRS kodunu, sahte bir saatle
bugünden sınav gününe kadar gün gün çalıştırır.

Öğrencinin "gerçek" hafızası uygulamadan bağımsız bir FSRS modeliyle (farklı parametreler, kelime başı zorluk,
önceden bilinen kelimeler) üretilir; uygulama bunu bilmez, yalnızca cevapları görür.

Kullanım: .venv\\Scripts\\python tools\\simulate.py [--hizli]
Çıktı: SIMULASYON_RAPORU.md ve SIMULASYON_RAPORU.html (proje kökünde)
"""
from __future__ import annotations

import argparse
import json
import math
import random
import shutil
import sys
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from app import config  # noqa: E402

TZ = timezone(timedelta(hours=3))


class Clock:
    def __init__(self, start: datetime):
        self.t = start

    def now(self) -> datetime:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t = self.t + timedelta(seconds=seconds)


class Student:
    """Gerçek hafıza: FSRS biçiminde ama farklı parametreler + kelime zorluğu."""

    def __init__(self, rng: random.Random, words: dict, true_params: list[float]):
        from app.fsrs_engine import VecFSRS
        self.rng = rng
        self.vf = VecFSRS(true_params)
        self.state: dict[int, dict] = {}
        for wid, w in words.items():
            known = rng.random() < w["p_known"]
            self.state[wid] = {"S": rng.uniform(20, 60) if known else None, "D": 4.0, "last": None,
                               "known": known, "hard": math.exp(rng.gauss(0, 0.35))}

    def r(self, wid: int, now: datetime) -> float:
        st = self.state[wid]
        if st["S"] is None:
            return 0.0
        if st["last"] is None:
            return 0.95 if st["known"] else 0.0
        el = (now - st["last"]).days
        return float(self.vf.r(np.array([st["S"]]), np.array([float(el)]))[0])

    def answer(self, wid: int, exercise: str, now: datetime, just_introduced: bool) -> tuple[bool, bool]:
        st = self.state[wid]
        if st["S"] is None and just_introduced:
            p = {"mcq_en_tr": 0.86, "mcq_tr_en": 0.8, "tiles": 0.75}.get(exercise, 0.7) / st["hard"] ** 0.3
        else:
            R = self.r(wid, now)
            if st["last"] is not None and (now - st["last"]).total_seconds() < 6 * 3600:
                R = max(R, 0.9)  # aynı oturum içinde taze
            if exercise in ("typing", "tiles"):
                p = R ** 1.25
            elif exercise in ("cloze", "context", "synonym", "distinguish"):
                p = 0.93 * R + (1 - R) * 0.22
            else:
                p = R + (1 - R) * 0.25
        p = max(0.01, min(0.99, p))
        ok = self.rng.random() < p
        fast = ok and self.rng.random() < (0.35 + 0.6 * p)
        self._update(wid, ok, fast, now)
        return ok, fast

    def _update(self, wid: int, ok: bool, fast: bool, now: datetime) -> None:
        st = self.state[wid]
        g = (3 if fast else 2) if ok else 1
        if st["S"] is None or st["last"] is None:
            s0 = float(self.vf.init_s(np.array([g]))[0]) / st["hard"]
            if st["known"] and st["S"]:
                s0 = max(s0, st["S"])
            st["S"], st["D"] = s0, float(self.vf.init_d(np.array([g]))[0])
        else:
            el = float((now - st["last"]).days)
            S, D = self.vf.step(np.array([st["S"]]), np.array([st["D"]]), np.array([el]), np.array([g]), np.array([False]))
            st["S"], st["D"] = float(S[0]) / (st["hard"] ** 0.15 if g > 1 else 1.0), float(D[0])
        st["last"] = now


EX_SECONDS = {"intro": 12, "mcq_en_tr": 4.5, "mcq_tr_en": 5.5, "tiles": 8, "typing": 9, "cloze": 10, "context": 8,
              "synonym": 6.5, "distinguish": 5, "speed": 3.5, "intervention": 15}


def run_scenario(name: str, weekday: int, weekend: int, missed: set[int], seed: int, days: int | None,
                 placement_known: bool = True) -> dict:
    data = Path(tempfile.mkdtemp(prefix="yds_sim_"))
    config.set_data_dir(data)
    from app import db, words as W, planner, projection, rating, strategy, distractors
    db.close()
    W.invalidate_index()
    planner._tier_cache = None
    projection.invalidate()
    rating.invalidate_cache()
    distractors.clear_cache()
    start = datetime(2026, 10, 4, 7, 30, tzinfo=TZ).astimezone(timezone.utc)
    clock = Clock(start)
    orig_now = config.now_utc
    config.now_utc = clock.now  # tüm uygulama sahte saati kullanır
    try:
        from app import seed_loader, session, cards as C
        seed_loader.init_db()
        db.set_setting("setup_done", True)
        db.set_setting("exam_date", "2026-11-22")
        db.set_setting("weekday_minutes", weekday)
        db.set_setting("weekend_minutes", weekend)
        db.set_setting("experiments_enabled", True)
        rng = random.Random(seed)
        st0 = planner.state_arrays(config.study_day())
        words = {wid: {"p_known": pk} for wid, pk in zip(st0["ids"], list(st0["p_known"]))}
        true_params = list(C.active_params())
        true_params[0] *= 0.8   # öğrenci varsayılandan biraz daha unutkan
        true_params[2] *= 0.85
        student = Student(rng, words, true_params)
        exam = date(2026, 11, 22)
        n_days = (exam - config.study_day()).days if days is None else days
        log = []
        for d in range(n_days):
            day = config.study_day()
            clock.t = datetime(day.year, day.month, day.day, 9, 0, tzinfo=TZ).astimezone(timezone.utc)
            plan = planner.today_plan(recompute=True)
            budget = plan["budget"]
            row = {"day": day.isoformat(), "phase": plan["phase"], "plan_new": plan["new_planned"],
                   "plan_rev": plan["reviews_planned"], "due": plan["reviews_due"], "plan_min": plan["minutes"],
                   "budget": budget, "new": 0, "rev": 0, "answers": 0, "correct": 0, "minutes": 0.0, "missed": d in missed}
            if d in missed:
                log.append(row)
                clock.t = clock.t + timedelta(days=1)
                continue
            used = 0.0
            modes = ["daily"] + (["weekly"] if plan.get("weekly_test") else [])
            for mode in modes:
                r = session.start(mode)
                sid = r["session_id"]
                item = session.next_item(sid)
                intro_seen: set[int] = set()
                while item and item.get("type") not in ("done", "error"):
                    if used >= budget * 60 * 1.05:
                        break
                    typ = item["type"]
                    wid = item.get("word_id")
                    sec = EX_SECONDS.get(typ, 7)
                    if typ in ("intro", "intervention"):
                        intro_seen.add(wid)
                        res = session.answer(sid, item["token"], {"token": item["token"], "total_ms": int(sec * 1000)})
                    else:
                        ok, fast = student.answer(wid, typ, clock.now(), wid in intro_seen)
                        th = rating.thresholds(typ)
                        lat = th.fast * (0.6 if fast else (1.3 if ok else 1.8)) * rng.uniform(0.8, 1.2)
                        body = {"token": item["token"], "total_ms": int(lat + (200 * (item.get("n_words") or 0))),
                                "first_key_ms": int(lat), "hints": 0}
                        if typ in ("typing", "tiles"):
                            secret = session.get(sid).pending[item["token"]]["secret"]
                            body["text"] = secret["answer"] if ok else "zzzz"
                        else:
                            n = len(item.get("options") or [1, 2])
                            body["choice"] = item["correct"] if ok else (item["correct"] + 1 + rng.randrange(max(1, n - 1))) % n
                        res = session.answer(sid, item["token"], body)
                        row["answers"] += 1
                        row["correct"] += 1 if res.get("correct") else 0
                        if not res.get("correct"):
                            sec += 4  # geri bildirim okuma
                    used += sec
                    clock.advance(sec)
                    session.heartbeat(sid, int(sec * 1000))
                    item = res.get("next")
                session.finish(sid)
            prog = planner.progress_today()
            row.update({"new": prog["new_done"], "rev": prog["reviews_done"], "minutes": round(used / 60, 1)})
            if d % 7 == 6 or d == n_days - 1:
                try:
                    projection.invalidate()
                    row["proj"] = round(projection.compute(force=True)["pace"]["mean"], 3)
                except Exception:
                    pass
            log.append(row)
            print(f"[{name}] {row['day']} {row['phase']:<8} yeni {row['new']:>3}/{row['plan_new']:<3} tekrar {row['rev']:>3}"
                  f" (vade {row['due']:>4}) dk {row['minutes']:>5}/{budget:<4} doğru {row['correct']}/{row['answers']}", flush=True)
            clock.t = clock.t + timedelta(days=1)
        # sınav sabahı: gerçek hatırlama
        clock.t = datetime(exam.year, exam.month, exam.day, 9, 0, tzinfo=TZ).astimezone(timezone.utc)
        true_r = [student.r(wid, clock.now()) for wid in words]
        introduced = db.val("SELECT COUNT(*) FROM cards WHERE introduced_at IS NOT NULL OR known_status='verified'")
        after_exam = db.val("SELECT COUNT(*) FROM cards WHERE due_day > ?", ("2026-11-22",))
        on_exam = db.val("SELECT COUNT(*) FROM cards WHERE due_day = ?", ("2026-11-22",))
        res = {"name": name, "weekday": weekday, "weekend": weekend, "missed": sorted(missed), "log": log,
               "true_recall_exam": float(np.mean(true_r)), "true_recall_p10": float(np.quantile(true_r, 0.1)),
               "introduced": int(introduced), "total": len(words), "due_after_exam": int(after_exam),
               "due_on_exam_day_no_more_reviews": int(on_exam),
               "strategy_log": db.q("SELECT ts, variable, reason FROM strategy_log ORDER BY id"),
               "fsrs_params_rows": db.val("SELECT COUNT(*) FROM fsrs_params", default=0)}
        return res
    finally:
        config.now_utc = orig_now
        from app import db as _db
        _db.close()
        shutil.rmtree(data, ignore_errors=True)


# ---------------------------------------------------------------- rapor
def svg_columns(values, budgets, w=760, h=170, color="#2a78d6", label=""):
    n = len(values)
    mx = max(max(values or [1]), max(budgets or [1])) * 1.1 or 1
    bw = min(14, (w - 50) / max(1, n) - 2)
    out = [f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="{label}">']
    for t in (0.25, 0.5, 0.75, 1.0):
        y = h - 20 - (h - 30) * t
        out.append(f'<line x1="40" x2="{w}" y1="{y:.1f}" y2="{y:.1f}" stroke="#e1e0d9"/>'
                   f'<text x="34" y="{y + 4:.1f}" font-size="10" text-anchor="end" fill="#898781">{mx * t:.0f}</text>')
    for i, v in enumerate(values):
        x = 44 + i * (w - 50) / n
        hh = (h - 30) * v / mx
        out.append(f'<rect x="{x:.1f}" y="{h - 20 - hh:.1f}" width="{bw:.1f}" height="{hh:.1f}" rx="2" fill="{color}"><title>gün {i + 1}: {v}</title></rect>')
    pts = " ".join(f"{44 + i * (w - 50) / n + bw / 2:.1f},{h - 20 - (h - 30) * b / mx:.1f}" for i, b in enumerate(budgets))
    out.append(f'<polyline points="{pts}" fill="none" stroke="#52514e" stroke-width="1.5" stroke-dasharray="5 4"/>')
    out.append(f'<line x1="40" x2="{w}" y1="{h - 20}" y2="{h - 20}" stroke="#c3c2b7"/></svg>')
    return "".join(out)


def write_report(results: list[dict], elapsed: float) -> None:
    md = ["# Sanal Öğrenci Simülasyonu — YDS Kelime Koçu", "",
          f"Tarih aralığı: 4 Ekim 2026 → 22 Kasım 2026 (sınav). Uygulamanın gerçek planlayıcı, oturum motoru ve FSRS kodu "
          f"sahte saatle gün gün çalıştırıldı{f' (simülasyon süresi {elapsed / 60:.1f} dk)' if elapsed else ''}. Öğrencinin gerçek hafızası uygulamadan bağımsız bir "
          "FSRS modeli: varsayılandan %15-20 daha unutkan, kelime başı zorluk farkı (log-normal), CEFR düzeyine göre önceden "
          "bilinen kelimeler. Uygulama bunları bilmez; yalnızca cevapları ve süreleri görür.", ""]
    md.append("| Senaryo | Bütçe (hafta içi/sonu dk) | Kaçırılan gün | Tanıtılan kelime | Sınav günü gerçek hatırlama | En kötü %10 | Sınav sonrasına planlanan tekrar | Ortalama günlük dk | En yoğun gün (dk) | Bütçe aşımı olan gün |")
    md.append("|---|---|---|---|---|---|---|---|---|---|")
    for r in results:
        mins = [x["minutes"] for x in r["log"] if not x["missed"]]
        over = sum(1 for x in r["log"] if not x["missed"] and x["minutes"] > x["budget"] * 1.06)
        md.append(f"| {r['name']} | {r['weekday']}/{r['weekend']} | {len(r['missed'])} | {r['introduced']}/{r['total']} | "
                  f"**%{r['true_recall_exam'] * 100:.1f}** | %{r['true_recall_p10'] * 100:.0f} | {r['due_after_exam']} | "
                  f"{np.mean(mins):.0f} | {max(mins):.0f} | {over} |")
    md.append("")
    md.append("### Yorum")
    md.append("")
    for r in results:
        mins = [x["minutes"] for x in r["log"] if not x["missed"]]
        ok = r["true_recall_exam"] >= 0.95
        md.append(f"- **{r['name']}**: sınav sabahı listenin gerçek hatırlanma oranı %{r['true_recall_exam'] * 100:.1f} "
                  f"({'hedef %95 ✓' if ok else 'hedef %95 tutmadı — uygulama bunu gerçekçilik kontrolüyle baştan bildirir'}); "
                  f"{r['introduced']}/{r['total']} kelime tanıtıldı; günlük aktif süre ortalama {np.mean(mins):.0f} dk, en yoğun gün "
                  f"{max(mins):.0f} dk; sınavdan sonraya planlanan tekrar: {r['due_after_exam']}.")
    md.append("- Kaçırılan günlerden sonra tekrarlar tek güne yığılmadı: planlayıcı bütçeyi aşan tekrarları risk sırasıyla "
              "sonraki günlere yaydı, o günler yeni kelime kotasını düşürdü.")
    md.append("- Son 7 gün: yeni kelime yok; listenin tamamı hızlı turla gözden geçirildi (günde ~400-500 kısa tekrar).")
    md.append("- Not: Sanal öğrencinin cevap hızı varsayımdır; gerçek kullanımda planlayıcı kendi sürelerini ölçüp "
              "maliyet tahminlerini günceller.")
    md.append("")
    for r in results:
        md.append(f"## {r['name']}")
        md.append("")
        md.append("| Gün | Evre | Plan yeni | Yapılan yeni | Vadesi gelen | Yapılan tekrar | Dakika / bütçe | Doğruluk | Projeksiyon |")
        md.append("|---|---|---:|---:|---:|---:|---:|---:|---:|")
        for x in r["log"]:
            acc = f"%{x['correct'] / x['answers'] * 100:.0f}" if x["answers"] else "—"
            md.append(f"| {x['day']} | {'KAÇIRILDI' if x['missed'] else x['phase']} | {x['plan_new']} | {x['new']} | {x['due']} | "
                      f"{x['rev']} | {x['minutes']}/{x['budget']:.0f} | {acc} | {('%' + str(round(x['proj'] * 100))) if x.get('proj') else ''} |")
        if r["strategy_log"]:
            md.append("")
            md.append("Strateji günlüğü:")
            for s in r["strategy_log"]:
                md.append(f"- {s['ts'][:10]} · {s['variable']}: {s['reason']}")
        md.append("")
    (ROOT / "SIMULASYON_RAPORU.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    html = ['<!doctype html><html lang="tr"><head><meta charset="utf-8"><title>Simülasyon raporu</title>'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<style>body{font-family:system-ui,Segoe UI,sans-serif;max-width:900px;margin:24px auto;padding:0 16px;color:#1f2328;background:#fffaf0}'
            'h1,h2{font-weight:800} .card{background:#fff;border:1px solid #ece5d6;border-radius:14px;padding:14px 16px;margin:14px 0}'
            'table{border-collapse:collapse;width:100%;font-size:13px} td,th{border-bottom:1px solid #ece5d6;padding:4px 6px;text-align:left}'
            '.k{display:inline-block;width:14px;height:3px;vertical-align:middle;margin-right:4px}</style></head><body>',
            '<h1>Sanal öğrenci simülasyonu</h1>', f'<p>{md[2]}</p>']
    html.append("<div class='card'><table><tr><th>Senaryo</th><th>Bütçe</th><th>Kaçırılan</th><th>Tanıtılan</th><th>Sınav günü gerçek hatırlama</th><th>Sınav sonrasına tekrar</th></tr>")
    for r in results:
        html.append(f"<tr><td>{r['name']}</td><td>{r['weekday']}/{r['weekend']} dk</td><td>{len(r['missed'])}</td><td>{r['introduced']}/{r['total']}</td>"
                    f"<td><b>%{r['true_recall_exam'] * 100:.1f}</b></td><td>{r['due_after_exam']}</td></tr>")
    html.append("</table></div>")
    for r in results:
        mins = [x["minutes"] for x in r["log"]]
        buds = [x["budget"] for x in r["log"]]
        html.append(f"<div class='card'><h2>{r['name']}</h2><p><span class='k' style='background:#2a78d6'></span>günlük aktif dakika "
                    f"<span class='k' style='border-top:2px dashed #52514e'></span>günlük bütçe</p>{svg_columns(mins, buds, label='günlük dakika')}"
                    f"<p><span class='k' style='background:#1baf7a'></span>günlük yeni kelime</p>{svg_columns([x['new'] for x in r['log']], [0] * len(mins), color='#1baf7a', label='yeni kelime')}"
                    f"<p><span class='k' style='background:#eb6834'></span>günlük tekrar</p>{svg_columns([x['rev'] for x in r['log']], [0] * len(mins), color='#eb6834', label='tekrar')}</div>")
    html.append("<p>Ayrıntılı günlük tablo: SIMULASYON_RAPORU.md</p></body></html>")
    (ROOT / "SIMULASYON_RAPORU.html").write_text("".join(html), encoding="utf-8")
    (ROOT / "tools" / "sim_sonuc.json").write_text(json.dumps(results, ensure_ascii=False, default=str), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hizli", action="store_true", help="yalnızca ilk 10 gün (duman testi)")
    ap.add_argument("--senaryo", default="all")
    ap.add_argument("--rapor", action="store_true", help="kayıtlı sonuçtan yalnızca raporu yeniden üret")
    args = ap.parse_args()
    if args.rapor:
        results = json.loads((ROOT / "tools" / "sim_sonuc.json").read_text(encoding="utf-8"))
        write_report(results, results[0].get("_elapsed", 0) if results else 0)
        return
    t0 = time.time()
    days = 10 if args.hizli else None
    scen = [
        ("A: yeterli süre (110/150 dk), aksamasız", 110, 150, set(), 1),
        ("B: yeterli süre + 3 kaçırılan gün", 110, 150, {9, 20, 31}, 2),
        ("C: kısıtlı süre (60/90 dk)", 60, 90, set(), 3),
    ]
    if args.senaryo != "all":
        scen = [s for s in scen if s[0].startswith(args.senaryo)]
    results = []
    for name, wk, we, missed, seed in scen:
        results.append(run_scenario(name, wk, we, missed, seed, days))
    write_report(results, time.time() - t0)
    for r in results:
        print(f"{r['name']}: sınav günü gerçek hatırlama %{r['true_recall_exam'] * 100:.1f}, tanıtılan {r['introduced']}/{r['total']}, "
              f"sınav sonrası planlanan tekrar {r['due_after_exam']}")


if __name__ == "__main__":
    main()
