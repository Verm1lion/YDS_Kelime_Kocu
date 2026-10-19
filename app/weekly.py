"""Haftalık tekrar günü: YDS tarzı karışık test + haftalık rapor (sayılar uygulamadan, anlatım LLM'den)."""
from __future__ import annotations

import json
import random
from datetime import date, timedelta

from . import config, db
from . import words as W


def test_words(n: int = 40) -> list[int]:
    week_ago = config.iso(config.now_utc() - timedelta(days=7))
    this_week = [r["word_id"] for r in db.q(
        """SELECT c.word_id FROM cards c JOIN words w ON w.id=c.word_id WHERE w.status='active' AND c.stage>=2
           AND c.introduced_at>=?""", (week_ago,))]
    weak = [r["word_id"] for r in db.q(
        """SELECT c.word_id FROM cards c JOIN words w ON w.id=c.word_id WHERE w.status='active' AND c.stage>=2
           ORDER BY (c.flag_hard*3 + c.lapses*2 + c.wrong_total) DESC, c.difficulty DESC LIMIT 80""")]
    old = [r["word_id"] for r in db.q(
        """SELECT c.word_id FROM cards c JOIN words w ON w.id=c.word_id WHERE w.status='active' AND c.stage>=3
           AND c.introduced_at<?""", (week_ago,))]
    rng = random.Random()
    rng.shuffle(this_week)
    rng.shuffle(old)
    picked: list[int] = []

    def take(src, k):
        for w in src:
            if len(picked) >= len_target[0]:
                return
            if k <= 0:
                return
            if w not in picked:
                picked.append(w)
                k -= 1

    len_target = [n]
    take(this_week, int(n * 0.5))
    take(weak, int(n * 0.3))
    take(old, n - len(picked))
    take(this_week + weak, n - len(picked))
    rng.shuffle(picked)
    return picked


def osym_questions_for(word_ids: list[int]) -> list[dict]:
    """Gerçek ÖSYM kelime soruları (cevabı öğrenilmiş liste kelimesi olanlar)."""
    p = config.seed_dir() / "osym_questions.json"
    if not p.exists():
        return []
    qs = json.loads(p.read_text(encoding="utf-8"))
    idx = W.index()
    out = []
    for q in qs:
        if q["type"] != "Kelime Bilgisi":
            continue
        ans = (q.get("answer_text") or "").lower().strip()
        wid = idx["by_lemma"].get(ans)
        if wid is None:
            for lem, i in idx["by_lemma"].items():
                if ans.startswith(lem) and len(lem) >= 4:
                    wid = i
                    break
        if wid and (idx["items"][wid].get("stage") or 0) >= 3:
            out.append({**q, "word_id": wid})
    return out


def week_stats(end: date | None = None) -> dict:
    end = end or config.study_day()
    start = end - timedelta(days=6)
    prev_start = start - timedelta(days=7)
    from . import analysis, projection, planner, coach
    daily = analysis.daily_series(14)
    this = [d for d in daily if start.isoformat() <= d["day"] <= end.isoformat()]
    prev = [d for d in daily if prev_start.isoformat() <= d["day"] < start.isoformat()]

    def agg(rows):
        ans = sum(r["answers"] for r in rows)
        acc_n = sum((r["accuracy"] or 0) * r["answers"] for r in rows)
        return {"minutes": round(sum(r["minutes"] for r in rows)), "days_studied": sum(1 for r in rows if r["minutes"] >= 1),
                "answers": ans, "accuracy": round(acc_n / ans, 3) if ans else None,
                "new_words": sum(r["new"] for r in rows), "reviews": sum(r["reviews"] for r in rows)}
    a_this, a_prev = agg(this), agg(prev)
    err = analysis.error_types(7)
    proj = projection.compute()
    plan = planner.today_plan()
    hist = projection.history()
    week_ago_proj = next((h for h in reversed(hist) if h["day"] <= start.isoformat()), None)
    hardest = [h["display"] for h in analysis.hardest_words(8)]
    conf = [f"{c['a_display']}/{c['b_display']} ({c['n']})" for c in analysis.confusion_pairs(5)]
    learned_total = db.val("SELECT COUNT(*) FROM cards c JOIN words w ON w.id=c.word_id WHERE w.status='active' AND c.stage>=6", default=0)
    total = db.val("SELECT COUNT(*) FROM words WHERE status='active'", default=0)
    try:
        from . import score_model
        sm = score_model.compute()
        score = {"median": round(sm["median"], 1), "p_target": round(sm["p_target"], 2)} if sm.get("available") else None
    except Exception:
        score = None
    return {
        "hafta": f"{start.isoformat()} – {end.isoformat()}",
        "bu_hafta": a_this, "gecen_hafta": a_prev,
        "ogrenilen_toplam": learned_total, "liste_toplam": total,
        "sinav_gunu_projeksiyon": round(proj["pace"]["mean"], 3) if proj.get("pace") else None,
        "bir_hafta_onceki_projeksiyon": round(week_ago_proj["pace"], 3) if week_ago_proj and week_ago_proj.get("pace") else None,
        "hedef": float(db.get_setting("target_recall", 0.95)),
        "hata_turleri": {t["type"]: t["count"] for t in err["types"] if t["count"]},
        "en_zor_kelimeler": hardest, "karisiklik_ciftleri": conf,
        "seri": coach.streak()["current"], "plan_gunluk_dk": plan.get("minutes"),
        "puan_tahmini": score, "sinava_kalan_gun": plan.get("days_to_exam"),
    }


def template_text(st: dict) -> str:
    t, p = st["bu_hafta"], st["gecen_hafta"]
    lines = [f"Bu hafta {t['days_studied']} gün, toplam {t['minutes']} dk çalıştın; {t['new_words']} yeni kelime, "
             f"{t['reviews']} tekrar yaptın."]
    if t["accuracy"] is not None:
        diff = ""
        if p["accuracy"] is not None:
            d = (t["accuracy"] - p["accuracy"]) * 100
            diff = f" (geçen hafta %{p['accuracy'] * 100:.0f}, {'+' if d >= 0 else ''}{d:.0f} puan)"
        lines.append(f"Doğruluk %{t['accuracy'] * 100:.0f}{diff}.")
    if st.get("sinav_gunu_projeksiyon") is not None:
        lines.append(f"Bu tempoyla sınav günü listenin %{st['sinav_gunu_projeksiyon'] * 100:.0f}'ini hatırlarsın; "
                     f"hedef %{st['hedef'] * 100:.0f}.")
    if st["hata_turleri"]:
        top = max(st["hata_turleri"].items(), key=lambda x: x[1])
        lines.append(f"En sık hata türü: {top[0]} ({top[1]} kez).")
    if st["en_zor_kelimeler"]:
        lines.append("En zor kelimeler: " + ", ".join(st["en_zor_kelimeler"][:6]) + ".")
    if st["karisiklik_ciftleri"]:
        lines.append("Karışıklık çiftleri: " + ", ".join(st["karisiklik_ciftleri"]) + ".")
    if st.get("puan_tahmini"):
        hedef = int(float(db.get_setting("target_score", 55)))
        lines.append(f"Puan tahmini (medyan) {st['puan_tahmini']['median']:.0f}; {hedef}+ olasılığı %{st['puan_tahmini']['p_target'] * 100:.0f}.")
    if t["minutes"] and st.get("plan_gunluk_dk"):
        avg = t["minutes"] / 7
        lines.append(f"Günlük ortalaman {avg:.0f} dk; bugünkü plan {st['plan_gunluk_dk']} dk.")
    return "\n".join(lines)


def make_report() -> int:
    st = week_stats()
    end = config.study_day()
    start = (end - timedelta(days=6)).isoformat()
    ex = db.q1("SELECT id FROM weekly_reports WHERE week_start=?", (start,))
    text = template_text(st)
    if ex:
        db.x("UPDATE weekly_reports SET stats=?, created_at=? WHERE id=? AND (source IS NULL OR source='şablon')",
             (db.jdump(st), config.iso(config.now_utc()), ex["id"]))
        rid = ex["id"]
    else:
        rid = db.x("INSERT INTO weekly_reports(week_start, created_at, stats, text, source) VALUES(?,?,?,?, 'şablon')",
                   (start, config.iso(config.now_utc()), db.jdump(st), text))
    from . import enrichment
    enrichment.queue_report(rid)
    return rid


def after_test(session_id: str) -> dict:
    evs = db.q("SELECT exercise, correct, error_type, word_id FROM events WHERE session_id=? AND correct IS NOT NULL",
               (session_id,))
    by = {}
    for e in evs:
        d = by.setdefault(e["exercise"], [0, 0])
        d[0] += 1
        d[1] += e["correct"] or 0
    rid = make_report()
    acc = (sum(e["correct"] or 0 for e in evs) / len(evs)) if evs else None
    return {"accuracy": acc, "by_type": {k: {"n": v[0], "accuracy": v[1] / v[0]} for k, v in by.items()},
            "report_id": rid}


def reports(limit: int = 10) -> list[dict]:
    rows = db.q("SELECT * FROM weekly_reports ORDER BY id DESC LIMIT ?", (limit,))
    for r in rows:
        r["stats"] = db.jload(r["stats"], {})
    return rows
