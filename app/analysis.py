"""Hata ve performans analizi — tamamı ham olay kaydından (events) yeniden hesaplanır."""
from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from . import config, db
from . import words as W

ERROR_TYPES = ["hatırlayamama", "karıştırma", "yazım hatası", "yakın anlam", "yön farkı", "bağlamda tanıyamama",
               "yavaş doğru", "şans doğrusu", "yanlış yazım", "biçim"]
MCQ_TYPES = ("mcq_en_tr", "listen", "syn_pick", "mcq_tr_en", "context", "speed", "cloze", "synonym")
PROD_TYPES = ("typing", "tiles")
DOW = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]


def _events(days: int | None = None, where: str = "", params: tuple = ()) -> list[dict]:
    sql = "SELECT * FROM events WHERE mode!='placement' AND correct IS NOT NULL AND result!='override'"
    p: list = []
    if days:
        sql += " AND day>=?"
        p.append((config.study_day() - timedelta(days=days)).isoformat())
    if where:
        sql += " AND " + where
        p += list(params)
    return db.q(sql + " ORDER BY ts", p)


def _local(ts: str) -> datetime:
    return config.parse_iso(ts).astimezone()


def _acc(rows) -> float | None:
    rows = list(rows)
    return (sum(1 for r in rows if r["correct"]) / len(rows)) if rows else None


def _lat(r) -> float | None:
    ex = db.jload(r.get("extra"), {}) or {}
    return ex.get("latency")


def lucky_guesses(evs: list[dict]) -> set[int]:
    """Çoktan seçmelide doğru ama 3 gün içinde aynı kelimenin üretiminde (yazma/harf) yanlış → şans doğrusu."""
    prod_fail = defaultdict(list)
    for e in evs:
        if e["exercise"] in PROD_TYPES and not e["correct"]:
            prod_fail[e["word_id"]].append(config.parse_iso(e["ts"]))
    out = set()
    for e in evs:
        if e["exercise"] in MCQ_TYPES and e["correct"] and e["word_id"] in prod_fail:
            t = config.parse_iso(e["ts"])
            if any(timedelta(0) < f - t <= timedelta(days=3) for f in prod_fail[e["word_id"]]):
                out.add(e["id"])
    return out


def direction_gap_words(evs: list[dict]) -> list[dict]:
    """EN→TR biliyor, TR→EN bilmiyor (kelime düzeyi)."""
    by = defaultdict(lambda: {"en_tr": [], "tr_en": []})
    for e in evs:
        if e["direction"] in ("en_tr", "tr_en"):
            by[e["word_id"]][e["direction"]].append(e["correct"])
    out = []
    idx = W.index()["items"]
    for wid, d in by.items():
        a, b = d["en_tr"][-6:], d["tr_en"][-6:]
        if len(a) >= 2 and len(b) >= 2:
            ra, rb = sum(a) / len(a), sum(b) / len(b)
            if ra >= 0.75 and rb <= 0.5:
                it = idx.get(wid)
                out.append({"word_id": wid, "display": it["display"] if it else wid, "en_tr": ra, "tr_en": rb})
    return sorted(out, key=lambda x: x["tr_en"])


def error_types(days: int | None = None) -> dict:
    evs = _events(days)
    wrong = [e for e in evs if not e["correct"]]
    c = Counter(e["error_type"] or "hatırlayamama" for e in wrong)
    slow = sum(1 for e in evs if e["correct"] and e["error_type"] == "yavaş doğru")
    typo = sum(1 for e in evs if e["result"] == "typo")
    lucky = lucky_guesses(evs)
    c["yavaş doğru"] = slow
    c["yazım hatası"] = c.get("yazım hatası", 0) + typo
    c["şans doğrusu"] = len(lucky)
    gap = direction_gap_words(evs)
    total = len(evs)
    rows = [{"type": t, "count": c.get(t, 0), "share": (c.get(t, 0) / total) if total else 0} for t in ERROR_TYPES
            if c.get(t, 0) or t in ERROR_TYPES[:8]]
    return {"total_answers": total, "wrong": len(wrong), "types": rows, "direction_gap_words": gap[:20],
            "lucky_count": len(lucky)}


def feature_groups(days: int | None = None) -> dict:
    evs = _events(days)
    words = {r["id"]: r for r in db.q("SELECT id, kind, pos, level, zipf, features FROM words")}
    from . import placement
    tiers = placement.tier_map()
    groups: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for e in evs:
        w = words.get(e["word_id"])
        if not w:
            continue
        f = db.jload(w["features"], {}) or {}
        pos = {"n": "isim", "v": "fiil", "adj": "sıfat", "adv": "zarf", "conj": "bağlaç"}.get(f.get("pos"), f.get("pos") or "?")
        groups["Tür"][pos].append(e)
        groups["Uzunluk"][f.get("len_band") or "?"].append(e)
        conc = f.get("concrete")
        if conc is None:
            conc_lbl = "soyut (tahmini)" if f.get("abstract_guess") else "belirsiz"
        else:
            conc_lbl = "somut" if conc else "soyut"
        groups["Soyut/somut"][conc_lbl].append(e)
        groups["Phrasal verb"]["phrasal" if w["kind"] == "phrasal" else "tek kelime"].append(e)
        groups["Kök-ek yapısı"][{"derived": "türemiş (ek/önek)", "simple": "yalın", "compound": "bileşik"}.get(
            f.get("morph"), "?")].append(e)
        groups["CEFR"][w["level"] or "yok"].append(e)
        groups["Sıklık katmanı"][tiers.get(e["word_id"], "?")].append(e)
    overall = _acc(evs) or 0
    out = {}
    for g, d in groups.items():
        rows = []
        for k, lst in d.items():
            acc = _acc(lst)
            lats = [x for x in (_lat(r) for r in lst if r["correct"]) if x]
            rows.append({"group": k, "n": len(lst), "accuracy": acc,
                         "median_ms": statistics.median(lats) if lats else None,
                         "weak": bool(len(lst) >= 30 and acc is not None and acc <= overall - 0.08)})
        out[g] = sorted(rows, key=lambda r: -r["n"])
    weak = [f"{g}: {r['group']} (%{r['accuracy'] * 100:.0f}, n={r['n']})" for g, rows in out.items() for r in rows if r["weak"]]
    return {"overall_accuracy": overall, "groups": out, "weak_groups": weak}


def time_analysis(days: int | None = 30) -> dict:
    evs = _events(days)
    by_hour = defaultdict(list)
    by_dow = defaultdict(list)
    by_min = defaultdict(list)
    for e in evs:
        t = _local(e["ts"])
        by_hour[t.hour].append(e)
        by_dow[t.weekday()].append(e)
        m = e.get("minute_in_session")
        if m is not None:
            by_min[int(m // 5) * 5].append(e)

    def rowify(d, label):
        rows = []
        for k in sorted(d):
            lst = d[k]
            lats = [x for x in (_lat(r) for r in lst if r["correct"]) if x]
            rows.append({"key": k, "label": label(k), "n": len(lst), "accuracy": _acc(lst),
                         "median_ms": statistics.median(lats) if lats else None})
        return rows
    return {"by_hour": rowify(by_hour, lambda h: f"{h:02d}:00"),
            "by_weekday": rowify(by_dow, lambda d: DOW[d]),
            "by_session_minute": rowify(by_min, lambda m: f"{m}-{m + 5} dk")}


def late_hour_effect(days: int = 30) -> dict | None:
    """Koç mesajı: belirli saatten sonra doğruluk düşüyor mu?"""
    ta = time_analysis(days)["by_hour"]
    best = None
    for cut in (21, 22, 23):
        late = [r for r in ta if r["key"] >= cut or r["key"] < 4]
        early = [r for r in ta if 4 <= r["key"] < cut]
        nl = sum(r["n"] for r in late)
        ne = sum(r["n"] for r in early)
        if nl < 40 or ne < 40:
            continue
        al = sum((r["accuracy"] or 0) * r["n"] for r in late) / nl
        ae = sum((r["accuracy"] or 0) * r["n"] for r in early) / ne
        if ae - al >= 0.08 and (best is None or ae - al > best["drop"]):
            good = [r for r in early if r["n"] >= 25]
            top = max(good, key=lambda r: r["accuracy"] or 0) if good else None
            best = {"cut": cut, "drop": ae - al, "late_acc": al, "early_acc": ae,
                    "best_hour": top["key"] if top else 20}
    return best


def session_fatigue(days: int = 30) -> dict | None:
    """Oturumun kaçıncı dakikasından sonra doğruluk düşüyor (oturum süresi önerisi için)."""
    rows = time_analysis(days)["by_session_minute"]
    rows = [r for r in rows if r["n"] >= 30]
    if len(rows) < 3:
        return None
    base = rows[0]["accuracy"] or 0
    for r in rows[1:]:
        if (r["accuracy"] or 0) <= base - 0.08:
            return {"drop_after_min": r["key"], "base_acc": base, "acc": r["accuracy"]}
    return None


def daily_series(days: int = 60) -> list[dict]:
    since = (config.study_day() - timedelta(days=days)).isoformat()
    act = {r["day"]: r["ms"] for r in db.q("SELECT day, SUM(active_ms) ms FROM activity WHERE day>=? GROUP BY day", (since,))}
    ev = {r["day"]: r for r in db.q("""SELECT day, COUNT(*) n, SUM(correct) c,
                                              SUM(CASE WHEN json_extract(extra,'$.kind')='review' THEN 1 ELSE 0 END) rv
                                       FROM events WHERE day>=? AND correct IS NOT NULL AND mode!='placement' GROUP BY day""", (since,))}
    newd = defaultdict(int)
    for r in db.q("SELECT introduced_at FROM cards WHERE introduced_at IS NOT NULL AND introduced_at>=?",
                  (config.iso(config.day_start_utc(date.fromisoformat(since))),)):
        newd[config.study_day(config.parse_iso(r["introduced_at"])).isoformat()] += 1
    out = []
    d0 = date.fromisoformat(since)
    today = config.study_day()
    d = d0
    while d <= today:
        k = d.isoformat()
        e = ev.get(k)
        out.append({"day": k, "minutes": round((act.get(k) or 0) / 60000.0, 1), "answers": e["n"] if e else 0,
                    "accuracy": (e["c"] / e["n"]) if e and e["n"] else None, "reviews": e["rv"] if e else 0,
                    "new": newd.get(k, 0)})
        d += timedelta(days=1)
    return out


def heatmap(days: int = 120) -> list[dict]:
    return [{"day": r["day"], "minutes": r["minutes"]} for r in daily_series(days)]


def hardest_words(n: int = 20) -> list[dict]:
    rows = db.q("""SELECT c.word_id, c.lapses, c.wrong_total, c.difficulty, c.stability, c.stage, w.display, w.pos,
                          (SELECT COUNT(*) FROM events e WHERE e.word_id=c.word_id AND e.correct IS NOT NULL AND e.mode!='placement') n,
                          (SELECT SUM(correct) FROM events e WHERE e.word_id=c.word_id AND e.correct IS NOT NULL AND e.mode!='placement') ok
                   FROM cards c JOIN words w ON w.id=c.word_id WHERE c.reps>0
                   ORDER BY (c.wrong_total*1.0 + c.lapses*1.5 + COALESCE(c.difficulty,5)*0.3) DESC LIMIT ?""", (n,))
    idx = W.index()["items"]
    for r in rows:
        r["meaning"] = idx.get(r["word_id"], {}).get("short", "")
        r["accuracy"] = (r["ok"] / r["n"]) if r["n"] else None
    return rows


def confusion_pairs(n: int = 30) -> list[dict]:
    rows = db.q("""SELECT word_id, confused_with, COUNT(*) n, MAX(ts) last FROM events
                   WHERE confused_with IS NOT NULL GROUP BY word_id, confused_with ORDER BY n DESC LIMIT ?""", (n * 2,))
    idx = W.index()["items"]
    pairs = {}
    for r in rows:
        key = tuple(sorted((r["word_id"], r["confused_with"])))
        p = pairs.setdefault(key, {"a": key[0], "b": key[1], "n": 0, "last": r["last"]})
        p["n"] += r["n"]
        p["last"] = max(p["last"], r["last"])
    out = []
    for p in sorted(pairs.values(), key=lambda x: -x["n"])[:n]:
        a, b = idx.get(p["a"]), idx.get(p["b"])
        if a and b:
            out.append({**p, "a_display": a["display"], "b_display": b["display"], "a_meaning": a["short"],
                        "b_meaning": b["short"]})
    return out


def speed_trend(days: int = 60) -> list[dict]:
    """Doğru cevaplarda (ilk tuş/cevap) gecikmenin kişisel 'hızlı' eşiğine oranı — günlük medyan."""
    from . import rating as R
    evs = _events(days, "correct=1")
    by = defaultdict(list)
    for e in evs:
        lat = _lat(e)
        if not lat:
            continue
        th = R.PRIORS.get(e["exercise"], R.PRIORS["mcq_en_tr"])[1]
        by[e["day"]].append(lat / th)
    return [{"day": d, "norm_latency": statistics.median(v), "n": len(v)} for d, v in sorted(by.items())]


def learning_cost() -> dict:
    """Kelime başına kalıcı hale gelene kadar (merdiven tamam ve S ≥ 7 gün) deneme sayısı ve dakika."""
    rows = db.q("""SELECT c.word_id, c.learned_at, c.stability, c.stage FROM cards c WHERE c.learned_at IS NOT NULL
                   AND c.stage>=6 AND c.stability>=7 AND (c.known_status IS NULL OR c.known_status!='verified')""")
    costs = []
    for r in rows:
        ev = db.q("""SELECT total_ms FROM events WHERE word_id=? AND ts<=? AND mode!='placement'""",
                  (r["word_id"], config.iso(config.parse_iso(r["learned_at"]) + timedelta(days=30))))
        att = len(ev)
        ms = sum((e["total_ms"] or 0) + 2500 for e in ev)
        costs.append({"word_id": r["word_id"], "attempts": att, "minutes": ms / 60000.0})
    if not costs:
        return {"n": 0}
    att = sorted(c["attempts"] for c in costs)
    mins = sorted(c["minutes"] for c in costs)
    return {"n": len(costs), "median_attempts": att[len(att) // 2], "median_minutes": round(mins[len(mins) // 2], 2),
            "mean_minutes": round(sum(mins) / len(mins), 2),
            "p90_attempts": att[int(len(att) * 0.9)] if len(att) > 2 else att[-1]}


def stubborn(threshold: int = 4) -> list[dict]:
    rows = db.q("""SELECT c.word_id, c.wrong_total, c.lapses, c.stage, c.stability, w.display,
                          (SELECT COUNT(*) FROM interventions i WHERE i.word_id=c.word_id) iv,
                          (SELECT MAX(effective) FROM interventions i WHERE i.word_id=c.word_id) eff
                   FROM cards c JOIN words w ON w.id=c.word_id WHERE c.wrong_total>=? ORDER BY c.wrong_total DESC LIMIT 50""",
                (threshold,))
    return rows


def overview() -> dict:
    from . import interventions, strategy
    return {
        "daily": daily_series(60), "heatmap": heatmap(140), "errors": error_types(),
        "features": feature_groups(), "time": time_analysis(30), "hardest": hardest_words(20),
        "confusions": confusion_pairs(20), "speed": speed_trend(60), "cost": learning_cost(),
        "stubborn": stubborn(), "interventions": interventions.summary(), "strategy": strategy.overview(),
        "late_hours": late_hour_effect(), "fatigue": session_fatigue(),
    }
