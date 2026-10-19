"""Kendini uyarlayan strateji: kontrollü deneyler + strateji günlüğü.

Değişkenler deneylerle (çok kollu haydut / A-B) test edilir. Ölçüt: kelimenin bir SONRAKİ GÜNDEKİ
ilk tekrarında doğru ve yavaş olmayan cevap oranı (gecikmeli hatırlama). Her kolda en az MIN_N sonuç
olmadan karar verilmez. Karar: Beta sonsal dağılımlarından P(en iyi) ≥ 0.95 ve fark ≥ 3 puan.
Her değişiklik gerekçesi ve verisiyle 'strategy_log'a yazılır, bildirilir, geri alınabilir.
"""
from __future__ import annotations

import random
from datetime import timedelta

import numpy as np

from . import config, db

MIN_N = 40
MAX_N = 160
P_BEST = 0.95
MIN_LIFT = 0.03

VARIABLES: dict[str, dict] = {
    "mem_kind": {"arms": ["association", "etymology", "context"], "unit": "word", "setting": "mem_kind_default",
                 "label": "Hafıza ipucu türü", "fmt": {"association": "çağrışım", "etymology": "köken", "context": "bağlam"}},
    "pack_size": {"arms": [4, 5, 7], "unit": "session", "setting": "pack_size", "label": "Paket büyüklüğü"},
    "distractor_level": {"arms": [0.35, 0.55, 0.8], "unit": "session", "setting": "distractor_level",
                         "label": "Çeldirici zorluğu", "fmt": {0.35: "kolay", 0.55: "orta", 0.8: "zor"}},
    "exercise_mix": {"arms": ["dengeli", "cloze_ağırlıklı", "üretim_ağırlıklı"], "unit": "session",
                     "setting": "exercise_mix_name", "label": "Alıştırma karışımı"},
}

MIXES = {
    "dengeli": {"cloze": 0.3, "mcq_en_tr": 0.2, "context": 0.15, "typing": 0.15, "synonym": 0.15, "distinguish": 0.05},
    "cloze_ağırlıklı": {"cloze": 0.5, "mcq_en_tr": 0.1, "context": 0.15, "typing": 0.1, "synonym": 0.1, "distinguish": 0.05},
    "üretim_ağırlıklı": {"cloze": 0.25, "mcq_en_tr": 0.1, "context": 0.1, "typing": 0.3, "synonym": 0.2, "distinguish": 0.05},
}

_session_arms: dict = {}


def enabled() -> bool:
    return bool(db.get_setting("experiments_enabled", True))


def _fmt(var: str, v) -> str:
    f = VARIABLES.get(var, {}).get("fmt", {})
    return str(f.get(v, v))


def running(var: str) -> dict | None:
    return db.q1("SELECT * FROM experiments WHERE variable=? AND status='running' ORDER BY id DESC LIMIT 1", (var,))


def ensure_experiments() -> None:
    if not enabled():
        return
    for var, spec in VARIABLES.items():
        if running(var):
            continue
        last = db.q1("SELECT * FROM experiments WHERE variable=? ORDER BY id DESC LIMIT 1", (var,))
        if last and last["status"] in ("paused",):
            continue
        if last and last["ended_at"] and config.parse_iso(last["ended_at"]) > config.now_utc() - timedelta(days=10):
            continue  # karar sonrası 10 gün bekle
        db.x("INSERT INTO experiments(variable, arms, unit, metric, status, started_at) VALUES(?,?,?,?, 'running', ?)",
             (var, db.jdump(spec["arms"]), spec["unit"], "gecikmeli_hatırlama", config.iso(config.now_utc())))


def current(var: str, default=None):
    spec = VARIABLES.get(var)
    if spec:
        v = db.get_setting(spec["setting"], None)
        if v is not None:
            return v
    return default


def _counts(exp_id: int) -> dict[str, int]:
    rows = db.q("SELECT arm, COUNT(*) n FROM exp_assignments WHERE experiment_id=? GROUP BY arm", (exp_id,))
    return {r["arm"]: r["n"] for r in rows}


def _balanced_arm(exp: dict, rng: random.Random | None = None):
    rng = rng or random.Random()
    arms = db.jload(exp["arms"], [])
    counts = _counts(exp["id"])
    mn = min(counts.get(str(a), 0) for a in arms)
    cands = [a for a in arms if counts.get(str(a), 0) == mn]
    return rng.choice(cands)


def begin_session(sid: str) -> dict:
    """Oturum düzeyindeki değişkenler için kol seçimi."""
    arms: dict = {}
    if enabled():
        ensure_experiments()
        for var, spec in VARIABLES.items():
            if spec["unit"] != "session":
                continue
            exp = running(var)
            if exp:
                arms[var] = _balanced_arm(exp)
                arms[f"_{var}_exp"] = exp["id"]
    _session_arms[sid] = arms
    return arms


def session_value(arms: dict | None, var: str, default):
    if arms and var in arms:
        return arms[var]
    return current(var, default)


def distractor_level(arms: dict | None = None) -> float:
    return float(session_value(arms, "distractor_level", 0.55))


def exercise_mix(arms: dict | None = None) -> dict:
    name = session_value(arms, "exercise_mix", None)
    if name in MIXES:
        return MIXES[name]
    mix = db.get_setting("exercise_mix")
    return mix if isinstance(mix, dict) and mix else MIXES["dengeli"]


def note_learning(word_id: int, arms: dict | None) -> None:
    """Oturumda öğrenilen kelimeyi, o oturumun deney kollarıyla eşle (sonuç ilk gecikmeli tekrarda)."""
    if not arms:
        return
    now = config.iso(config.now_utc())
    for var in ("pack_size", "distractor_level", "exercise_mix"):
        eid = arms.get(f"_{var}_exp")
        if eid and var in arms:
            db.x("INSERT OR IGNORE INTO exp_assignments(experiment_id, unit_id, arm, assigned_at) VALUES(?,?,?,?)",
                 (eid, f"w{word_id}", str(arms[var]), now))


def assign_mem_kind(word_id: int) -> str:
    # kullanıcının kendi mem'i her zaman önceliklidir (exercises.intro bunu uygular)
    if not enabled():
        return str(current("mem_kind", "association"))
    ensure_experiments()
    exp = running("mem_kind")
    if not exp:
        return str(current("mem_kind", "association"))
    row = db.q1("SELECT arm FROM exp_assignments WHERE experiment_id=? AND unit_id=?", (exp["id"], f"w{word_id}"))
    if row:
        return row["arm"]
    # etymology/bağlam içeriği yoksa çağrışım
    arm = _balanced_arm(exp)
    if arm == "etymology" and not db.val("SELECT 1 FROM mnemonics WHERE word_id=? AND kind='etymology' AND flagged=0",
                                         (word_id,)):
        arm = "association"
    db.x("INSERT OR IGNORE INTO exp_assignments(experiment_id, unit_id, arm, assigned_at) VALUES(?,?,?,?)",
         (exp["id"], f"w{word_id}", str(arm), config.iso(config.now_utc())))
    return str(arm)


def record_outcome(word_id: int, correct: bool, speed: str, kind: str, exercise: str, ts) -> None:
    """Gecikmeli (ertesi gün veya sonrası) ilk tekrar sonucu açık atamaları kapatır."""
    if kind not in ("review",):
        return
    rows = db.q("""SELECT experiment_id, unit_id, assigned_at FROM exp_assignments
                   WHERE unit_id=? AND outcome IS NULL""", (f"w{word_id}",))
    if not rows:
        return
    today = config.study_day(ts)
    val = 1.0 if (correct and speed != "yavaş") else (0.5 if correct else 0.0)
    for r in rows:
        if config.study_day(config.parse_iso(r["assigned_at"])) < today:
            db.x("UPDATE exp_assignments SET outcome=?, outcome_at=? WHERE experiment_id=? AND unit_id=?",
                 (val, config.iso(ts), r["experiment_id"], r["unit_id"]))


def arm_stats(exp_id: int) -> dict[str, dict]:
    rows = db.q("""SELECT arm, COUNT(outcome) n, SUM(outcome) s, COUNT(*) assigned FROM exp_assignments
                   WHERE experiment_id=? GROUP BY arm""", (exp_id,))
    return {r["arm"]: {"n": r["n"] or 0, "success": float(r["s"] or 0), "assigned": r["assigned"],
                       "rate": (float(r["s"] or 0) / r["n"]) if r["n"] else None} for r in rows}


def p_best(stats: dict[str, dict], samples: int = 6000, seed: int = 7) -> dict[str, float]:
    rng = np.random.default_rng(seed)
    arms = list(stats)
    if not arms:
        return {}
    draws = np.stack([rng.beta(1 + stats[a]["success"], 1 + stats[a]["n"] - stats[a]["success"], samples)
                      for a in arms])
    best = np.argmax(draws, axis=0)
    return {a: float(np.mean(best == i)) for i, a in enumerate(arms)}


def _cast(var: str, arm: str):
    for a in VARIABLES[var]["arms"]:
        if str(a) == str(arm):
            return a
    return arm


def evaluate() -> list[dict]:
    """Koşan deneyleri değerlendirir; yeterli kanıt varsa kazanan kolu benimser."""
    decisions = []
    for exp in db.q("SELECT * FROM experiments WHERE status='running'"):
        var = exp["variable"]
        st = arm_stats(exp["id"])
        arms = [str(a) for a in db.jload(exp["arms"], [])]
        for a in arms:
            st.setdefault(a, {"n": 0, "success": 0.0, "assigned": 0, "rate": None})
        ns = [st[a]["n"] for a in arms]
        if min(ns) < MIN_N:
            continue
        pb = p_best(st)
        leader = max(pb, key=pb.get)
        rates = {a: st[a]["rate"] for a in arms}
        others = [rates[a] for a in arms if a != leader and rates[a] is not None]
        lift = (rates[leader] - max(others)) if others else 0.0
        data = {"arms": st, "p_best": pb, "lift": lift, "min_n": MIN_N}
        if pb[leader] >= P_BEST and lift >= MIN_LIFT:
            old = current(var)
            new = _cast(var, leader)
            db.set_setting(VARIABLES[var]["setting"], new)
            db.x("UPDATE experiments SET status='decided', ended_at=?, result=? WHERE id=?",
                 (config.iso(config.now_utc()), db.jdump(data), exp["id"]))
            reason = (f"{VARIABLES[var]['label']}: '{_fmt(var, new)}' kolunda ertesi gün hatırlama %{rates[leader] * 100:.0f}, "
                      f"diğerlerinde en fazla %{max(others) * 100:.0f} (her kolda ≥{MIN_N} kelime, P(en iyi)={pb[leader]:.2f}).")
            lid = log_change(var, old, new, reason, data, exp["id"])
            decisions.append({"variable": var, "new": new, "log_id": lid})
        elif min(ns) >= MAX_N:
            db.x("UPDATE experiments SET status='no_difference', ended_at=?, result=? WHERE id=?",
                 (config.iso(config.now_utc()), db.jdump(data), exp["id"]))
            log_change(var, current(var), current(var),
                       f"{VARIABLES[var]['label']}: kollar arasında anlamlı fark yok (her kolda ≥{MAX_N}); mevcut ayar korunuyor.",
                       data, exp["id"], notify=False)
    return decisions


def log_change(variable: str, old, new, reason: str, data: dict | None = None, experiment_id: int | None = None,
               notify: bool = True) -> int:
    now = config.iso(config.now_utc())
    lid = db.x("""INSERT INTO strategy_log(ts, variable, old_value, new_value, reason, data, experiment_id)
                  VALUES(?,?,?,?,?,?,?)""",
               (now, variable, db.jdump(old), db.jdump(new), reason, db.jdump(data or {}), experiment_id))
    if notify:
        from . import coach
        coach.notify("strateji", "Strateji güncellendi", reason, key=f"strategy-{lid}", level=1)
    return lid


def revert(log_id: int) -> dict:
    row = db.q1("SELECT * FROM strategy_log WHERE id=?", (log_id,))
    if not row or row["reverted"]:
        return {"ok": False}
    var = row["variable"]
    old = db.jload(row["old_value"])
    if var in VARIABLES:
        db.set_setting(VARIABLES[var]["setting"], old)
        db.x("UPDATE experiments SET status='paused' WHERE variable=? AND status='running'", (var,))
    elif var == "desired_retention":
        db.set_setting("desired_retention", old)
    elif var == "fsrs_params":
        db.x("UPDATE fsrs_params SET active=0")
        if row["experiment_id"]:
            db.x("UPDATE fsrs_params SET active=1 WHERE id=?", (row["experiment_id"],))
        from . import cards
        cards.reschedule_all()
    elif var in ("max_session_minutes", "new_per_day_override", "break_minutes"):
        db.set_setting(var, old)
    db.x("UPDATE strategy_log SET reverted=1 WHERE id=?", (log_id,))
    db.x("""INSERT INTO strategy_log(ts, variable, old_value, new_value, reason, data)
            VALUES(?,?,?,?,?,?)""", (config.iso(config.now_utc()), var, row["new_value"], row["old_value"],
                                     "Kullanıcı tarafından geri alındı", "{}"))
    return {"ok": True}


def overview() -> dict:
    exps = []
    for e in db.q("SELECT * FROM experiments ORDER BY id DESC LIMIT 20"):
        st = arm_stats(e["id"])
        exps.append({"id": e["id"], "variable": e["variable"], "label": VARIABLES.get(e["variable"], {}).get("label"),
                     "status": e["status"], "arms": {k: {**v, "label": _fmt(e["variable"], _cast(e["variable"], k))
                                                         if e["variable"] in VARIABLES else k} for k, v in st.items()},
                     "p_best": p_best(st) if st else {}, "started_at": e["started_at"], "ended_at": e["ended_at"]})
    log = db.q("SELECT * FROM strategy_log ORDER BY id DESC LIMIT 100")
    for l in log:
        l["data"] = db.jload(l["data"], {})
        l["old_value"] = db.jload(l["old_value"])
        l["new_value"] = db.jload(l["new_value"])
    return {"experiments": exps, "log": log, "enabled": enabled(),
            "current": {v: current(v) for v in VARIABLES}}
