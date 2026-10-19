"""Seviye tespiti: listedeki hangi kelimeleri zaten bildiğini bulmak ve başlangıç stratejisini seçmek.

- Liste, wordfreq sıklığına göre 5 katmana (+ öbek fiiller) ayrılır.
- Uyarlamalı: 5'li bloklarda başarı yüksekse daha nadir katmana, düşükse daha sık katmana geçilir;
  her katmandan en az 10 soru; ~15 dk veya 150 soruda biter.
- Soru: EN→TR 5 şıklı + 'Bilmiyorum'. Süre ölçülür. Beyan yok: yalnızca cevap.
- Tahmin: P(doğru) = k + (1-k)·0,2 modeliyle katman başına bilinen oran k (ızgara sonsalı).
- Doğru ve hızlı cevaplanan kelimeler 'muhtemelen biliyor' → oturumlarda iki soruluk doğrulama turu.
"""
from __future__ import annotations

import random
import threading
import time
import uuid

import numpy as np

from . import config, db
from . import exercises as X
from . import grading as G
from . import rating as R
from . import words as W

TIERS = ["K1", "K2", "K3", "K4", "K5", "ÖF"]
TIER_LABEL = {"K1": "Çok sık (en yaygın %20)", "K2": "Sık", "K3": "Orta", "K4": "Seyrek", "K5": "Çok seyrek",
              "ÖF": "Öbek fiiller"}
MIN_PER_TIER = 10
MAX_ITEMS = 150
MAX_SECONDS = 15 * 60
GRID = np.linspace(0, 1, 101)

_state: dict[str, dict] = {}
_lock = threading.RLock()


def tier_map() -> dict[int, str]:
    rows = db.q("""SELECT w.id, w.kind, w.zipf FROM words w WHERE w.status='active' AND w.pool IN ('main','user')""")
    words = [r for r in rows if r["kind"] != "phrasal"]
    words.sort(key=lambda r: -(r["zipf"] or 0))
    n = len(words)
    out = {}
    for i, r in enumerate(words):
        out[r["id"]] = TIERS[min(4, int(5 * i / max(1, n)))]
    for r in rows:
        if r["kind"] == "phrasal":
            out[r["id"]] = "ÖF"
    return out


def _posterior(stats: dict) -> np.ndarray:
    g = 0.2
    lp = np.zeros_like(GRID)
    lp += stats["correct"] * np.log(GRID + (1 - GRID) * g + 1e-12)
    lp += stats["wrong"] * np.log((1 - GRID) * (1 - g) + 1e-12)
    lp += stats["dk"] * np.log(1 - GRID + 1e-12)
    lp -= lp.max()
    p = np.exp(lp)
    return p / p.sum()


def _summary(stats: dict) -> dict:
    p = _posterior(stats)
    mean = float(np.sum(GRID * p))
    sd = float(np.sqrt(np.sum((GRID - mean) ** 2 * p)))
    cdf = np.cumsum(p)
    lo = float(GRID[np.searchsorted(cdf, 0.1)])
    hi = float(GRID[min(len(GRID) - 1, np.searchsorted(cdf, 0.9))])
    return {"known_rate": mean, "sd": sd, "ci80": [lo, hi]}


def start() -> dict:
    pid = uuid.uuid4().hex[:12]
    tm = tier_map()
    by_tier: dict[str, list[int]] = {t: [] for t in TIERS}
    for wid, t in tm.items():
        card = db.q1("SELECT state FROM cards WHERE word_id=?", (wid,))
        if card and (card["state"] or 0) == 0:
            by_tier[t].append(wid)
    for t in by_tier:
        random.shuffle(by_tier[t])
    st = {"id": pid, "started": time.time(), "by_tier": by_tier, "tier_sizes": {t: len(v) for t, v in by_tier.items()},
          "stats": {t: {"n": 0, "correct": 0, "wrong": 0, "dk": 0, "fast": 0} for t in TIERS},
          "current": "K3", "block": [], "items": 0, "pending": {}, "results": [], "active_ms": 0, "rng": random.Random()}
    db.x("INSERT INTO placement(started_at) VALUES(?)", (config.iso(config.now_utc()),))
    st["db_id"] = db.val("SELECT MAX(id) FROM placement")
    with _lock:
        _state[pid] = st
    return {"placement_id": pid, "max_minutes": MAX_SECONDS // 60, "tiers": {t: TIER_LABEL[t] for t in TIERS}}


def _choose_tier(st: dict) -> str | None:
    stats = st["stats"]
    avail = [t for t in TIERS if st["by_tier"][t]]
    if not avail:
        return None
    under = [t for t in avail if stats[t]["n"] < (8 if t == "ÖF" else MIN_PER_TIER)]
    cur = st["current"]
    blk = st["block"]
    if len(blk) >= 5:
        acc = sum(blk) / len(blk)
        st["block"] = []
        idx = TIERS.index(cur) if cur in TIERS[:5] else 2
        if acc >= 0.8 and idx < 4:
            cur = TIERS[idx + 1]
        elif acc <= 0.4 and idx > 0:
            cur = TIERS[idx - 1]
        elif under:
            cur = min(under, key=lambda t: stats[t]["n"])
        st["current"] = cur
    if cur not in avail:
        cur = avail[0]
    if under and cur not in under and stats[cur]["n"] >= MIN_PER_TIER:
        cur = min(under, key=lambda t: stats[t]["n"])
        st["current"] = cur
        st["block"] = []
    if not under:
        # belirsizliği × katman büyüklüğü en yüksek olan
        def unc(t):
            s = _summary(stats[t])
            return s["sd"] * st["tier_sizes"][t]
        cur = max(avail, key=unc)
        st["current"] = cur
    return cur


def _done(st: dict) -> bool:
    if st["items"] >= MAX_ITEMS:
        return True
    if (st["active_ms"] / 1000.0 if st["active_ms"] else time.time() - st["started"]) >= MAX_SECONDS:
        return True
    stats = st["stats"]
    if all(stats[t]["n"] >= MIN_PER_TIER for t in TIERS[:5]) and stats["ÖF"]["n"] >= 8:
        if all(_summary(stats[t])["sd"] < 0.07 for t in TIERS):
            return True
    return False


def next_item(pid: str) -> dict:
    with _lock:
        st = _state.get(pid)
    if not st:
        return {"type": "error", "message": "Test bulunamadı"}
    if _done(st):
        return finish(pid)
    tier = _choose_tier(st)
    if tier is None:
        return finish(pid)
    wid = st["by_tier"][tier].pop()
    p, sec = X.mcq_en_tr(wid, 5, 0.5, st["rng"], typ="mcq_en_tr")
    p["type"] = "placement"
    p["type_label"] = "Seviye testi"
    p["placement"] = {"item": st["items"] + 1, "max": MAX_ITEMS, "elapsed_s": round(time.time() - st["started"]),
                      "max_s": MAX_SECONDS}
    st["pending"][p["token"]] = {"secret": sec, "tier": tier, "shown": time.time(), "payload": p}
    return p


def answer(pid: str, token: str, payload: dict) -> dict:
    with _lock:
        st = _state.get(pid)
    if not st:
        return {"error": "Test bulunamadı"}
    pend = st["pending"].pop(token, None)
    if not pend:
        return {"error": "Soru bulunamadı"}
    sec, tier = pend["secret"], pend["tier"]
    st["active_ms"] = max(st["active_ms"], int(payload.get("session_active_ms") or 0))
    dk = bool(payload.get("dont_know"))
    ch = payload.get("choice")
    g = G.grade_choice(sec, None if ch is None else int(ch), dont_know=dk)
    total = int(payload.get("total_ms") or 0)
    th = R.thresholds("placement")
    fast = g.correct and total <= th.fast * 1.25
    s = st["stats"][tier]
    s["n"] += 1
    if dk:
        s["dk"] += 1
    elif g.correct:
        s["correct"] += 1
        s["fast"] += 1 if fast else 0
    else:
        s["wrong"] += 1
    st["block"].append(1 if g.correct else 0)
    st["items"] += 1
    wid = sec["word_id"]
    st["results"].append({"word_id": wid, "tier": tier, "correct": g.correct, "dk": dk, "ms": total, "fast": fast})
    db.x("""INSERT INTO events(ts, day, session_id, word_id, mode, exercise, direction, answer, expected, correct, result,
                               total_ms, first_key_ms, error_type, confused_with, device, extra)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
         (config.iso(config.now_utc()), config.day_str(), f"placement-{pid}", wid, "placement", "placement", "en_tr",
          g.answer_text, g.expected_text, 1 if g.correct else 0, g.result, total, total,
          None if g.correct else g.error_type, g.confused_with, payload.get("device", "desktop"),
          db.jdump({"tier": tier, "latency": total, "fast": fast})))
    return {"correct": g.correct, "correct_index": sec["correct"], "feedback": X.feedback_info(wid),
            "next": next_item(pid)}


def finish(pid: str) -> dict:
    with _lock:
        st = _state.pop(pid, None)
    if not st:
        row = db.q1("SELECT result FROM placement WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 1")
        return {"type": "placement_done", "result": db.jload(row["result"], {}) if row else {}}
    tiers = []
    total_known = 0.0
    total_words = 0
    for t in TIERS:
        s = st["stats"][t]
        sm = _summary(s)
        size = st["tier_sizes"][t] + s["n"]
        enough = s["n"] >= 5
        tiers.append({"tier": t, "label": TIER_LABEL[t], "n": s["n"], "correct": s["correct"], "dont_know": s["dk"],
                      "fast": s["fast"], "known_rate": round(sm["known_rate"], 3) if enough else None,
                      "ci80": sm["ci80"] if enough else None, "size": size})
        if enough:
            total_known += sm["known_rate"] * size
            total_words += size
    lat = sorted(r["ms"] for r in st["results"] if r["correct"])
    if lat:
        med = lat[len(lat) // 2]
        p25 = lat[len(lat) // 4]
        p75 = lat[(3 * len(lat)) // 4]
    else:
        med = p25 = p75 = None
    probable = [r["word_id"] for r in st["results"] if r["correct"] and r["fast"]]
    now = config.iso(config.now_utc())
    for wid in probable:
        db.x("UPDATE cards SET known_status='probable' WHERE word_id=? AND state=0", (wid,))
    # kişisel hız öncelleri (MCQ)
    if med:
        pri = db.get_setting("speed_priors") or {}
        pri = dict(pri) if isinstance(pri, dict) else {}
        pri["mcq_en_tr"] = [int(p25 * 0.9), int(med), int(max(p75 * 1.6, med * 2.0))]
        pri["placement"] = pri["mcq_en_tr"]
        pri["speed"] = [int(p25 * 0.8), int(med * 0.85), int(p75 * 1.3)]
        db.set_setting("speed_priors", pri)
        R.invalidate_cache()
    overall = (total_known / total_words) if total_words else None
    strat = []
    hi_tiers = [t for t in tiers if t["known_rate"] is not None and t["known_rate"] >= 0.6]
    lo_tiers = [t for t in tiers if t["known_rate"] is not None and t["known_rate"] < 0.25]
    if any(t["known_rate"] is None for t in tiers):
        strat.append("Bazı katmanlarda yeterli soru yok (en az 5); o katmanlar için CEFR düzeyine dayalı tahmin kullanılır. "
                     "Testi Ayarlar'dan yeniden yapabilirsin.")
    if hi_tiers:
        strat.append("Bu katmanlarda kelimelerin çoğunu zaten biliyorsun: " + ", ".join(t["label"] for t in hi_tiers)
                     + ". Bu kelimeler öğretilmeden önce kısa bir ön testten geçecek; bildiklerin doğrudan uzun aralıklı tekrara gider.")
    if lo_tiers:
        strat.append("Şu katmanlarda doğrudan öğretim (tanıtım kartı + merdiven): " + ", ".join(t["label"] for t in lo_tiers) + ".")
    if med:
        speed_txt = "hızlı" if med <= 2500 else ("orta" if med <= 4000 else "yavaş")
        strat.append(f"Hız profilin: doğru cevaplarda medyan {med / 1000:.1f} sn ({speed_txt}); P25 {p25 / 1000:.1f} sn, "
                     f"P75 {p75 / 1000:.1f} sn. Hız eşiklerin buna göre kalibre edildi.")
        if med > 4000:
            strat.append("Tanıma hızın düşük: Hızlı tekrar modunu haftada en az 3 kez yapman önerilir (otomatiklik).")
    strat.append(f"Muhtemelen bildiğin {len(probable)} kelime doğrulama turuna alındı (iki soru: TR→EN ve YDS boşluk doldurma).")
    result = {"tiers": tiers, "overall_known": round(overall, 3) if overall is not None else None, "items": st["items"],
              "minutes": round((time.time() - st["started"]) / 60, 1),
              "speed": {"median_ms": med, "p25_ms": p25, "p75_ms": p75}, "probable": len(probable),
              "strategy": strat}
    db.x("UPDATE placement SET finished_at=?, result=? WHERE id=?", (now, db.jdump(result), st["db_id"]))
    db.set_setting("placement_done", True)
    # planlayıcı ve projeksiyon yeni bilgiyle yeniden hesaplanır
    from . import planner, projection
    planner._tier_cache = None
    projection.invalidate()
    plan = planner.today_plan(recompute=True)
    result["plan"] = {k: plan.get(k) for k in ("new_planned", "reviews_planned", "minutes", "rationale", "feasible",
                                               "new_rate", "finish_new_by", "projected_recall_plan")}
    return {"type": "placement_done", "result": result}


def pretest_tiers() -> set[str]:
    row = db.q1("SELECT result FROM placement WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 1")
    if not row:
        return set()
    res = db.jload(row["result"], {})
    return {t["tier"] for t in res.get("tiers", []) if (t.get("known_rate") or 0) >= 0.6}


def last_result() -> dict | None:
    row = db.q1("SELECT result, finished_at FROM placement WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 1")
    if not row:
        return None
    r = db.jload(row["result"], {})
    r["finished_at"] = row["finished_at"]
    return r
