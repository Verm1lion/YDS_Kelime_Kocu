"""Kelime verisi: etkin anlam, içerik paketi, bellek içi dizin, hızlı ekleme, öneriler."""
from __future__ import annotations

import json
import threading
from typing import Any

from . import config, db
from . import textutil as tu

_index_lock = threading.RLock()
_index: dict[str, Any] | None = None


def effective_meaning(w: dict) -> str:
    return (w.get("meaning_user") or w.get("meaning_src") or w.get("meaning_gen") or "").strip()


def invalidate_index() -> None:
    global _index
    with _index_lock:
        _index = None


def index() -> dict[str, Any]:
    """Çeldirici seçimi ve analiz için tüm etkin kelimelerin özet dizini."""
    global _index
    with _index_lock:
        if _index is not None:
            return _index
        rows = db.q("""SELECT w.id, w.lemma, w.display, w.kind, w.pos, w.meaning_src, w.meaning_user, w.meaning_gen,
                              w.zipf, w.pool, w.status, w.order_index, w.family_src, w.features,
                              c.stage, c.state, c.stability
                       FROM words w LEFT JOIN cards c ON c.word_id = w.id
                       WHERE w.status='active'""")
        syn = {}
        for r in db.q("SELECT word_id, value FROM word_info WHERE field='synonyms' AND active=1 AND flagged=0"):
            syn.setdefault(r["word_id"], set()).update(tu.norm_en(s) for s in db.jload(r["value"], []))
        ant = {}
        for r in db.q("SELECT word_id, value FROM word_info WHERE field='antonyms' AND active=1 AND flagged=0"):
            ant.setdefault(r["word_id"], set()).update(tu.norm_en(s) for s in db.jload(r["value"], []))
        fam = {}
        for r in db.q("SELECT word_id, value FROM word_info WHERE field='family' AND active=1 AND flagged=0"):
            for f in db.jload(r["value"], []):
                if isinstance(f, dict) and f.get("w"):
                    fam.setdefault(r["word_id"], set()).add(tu.norm_en(f["w"]))
        items = {}
        by_lemma = {}
        for r in rows:
            m = effective_meaning(r)
            fams = set(fam.get(r["id"], set()))
            if r.get("family_src"):
                for f in r["family_src"].replace(";", ",").split(","):
                    if f.strip():
                        fams.add(tu.norm_en(f))
            toks = tu.meaning_tokens(m)
            lem = r["lemma"]
            it = {
                "id": r["id"], "lemma": lem, "display": r["display"], "kind": r["kind"],
                "pos": r["pos"], "pos_codes": tu.pos_list(r["pos"]) or ["n"], "ppos": tu.primary_pos(r["pos"]),
                "meaning": m, "short": tu.short_meaning(m), "phrases": tu.meaning_phrases(m),
                "tokens": toks, "toks5": {t for t in toks if " " not in t and len(t) >= 5},
                "bg": {f"^{lem}$"[i:i + 2] for i in range(len(lem) + 1)},
                "zipf": r["zipf"] or 0.0, "pool": r["pool"],
                "stage": r["stage"] or 0, "state": r["state"] or 0, "stability": r["stability"],
                "synonyms": syn.get(r["id"], set()), "antonyms": ant.get(r["id"], set()),
                "family": fams, "order_index": r["order_index"],
            }
            items[r["id"]] = it
            by_lemma[r["lemma"]] = r["id"]
        _index = {"items": items, "by_lemma": by_lemma}
        return _index


# eş/yakın anlamlı kaynak önceliği: kullanıcı > Ezberbozan kitabı > tohum > LLM
SYN_SOURCE_RANK = {"user": 0, "ezberbozan": 1, "seed": 2}


def synonyms_for(word_id: int, n: int = 6) -> list[dict]:
    """Kelimenin eş/yakın anlamlıları (kitaptakiler önce); listede olanların Türkçe anlamıyla birlikte.
    Tanıtım kartında kelimenin yanında, 'eş anlamlısından bul' katmanında ve geri bildirimde gösterilir."""
    idx = index()
    me = idx["items"].get(word_id) or {}
    skip = {me.get("lemma")} | set(me.get("family") or ())
    rows = db.q("""SELECT value, source FROM word_info WHERE word_id=? AND field='synonyms' AND active=1 AND flagged=0
                   ORDER BY id""", (word_id,))
    rows.sort(key=lambda r: SYN_SOURCE_RANK.get(r["source"], 3))
    out, seen = [], set()
    for r in rows:
        for v in db.jload(r["value"], []) or []:
            if not isinstance(v, str):
                continue
            disp = " ".join(v.replace("…", " ").split()).strip(" ,;.")
            key = tu.norm_en(disp)
            if not key or key in seen or key in skip:
                continue
            seen.add(key)
            wid = idx["by_lemma"].get(key)
            out.append({"w": disp, "tr": idx["items"][wid]["short"] if wid else None})
            if len(out) >= n:
                return out
    return out


def get_word(word_id: int) -> dict | None:
    w = db.q1("SELECT * FROM words WHERE id=?", (word_id,))
    if w:
        w["meaning"] = effective_meaning(w)
        w["features"] = db.jload(w.get("features"), {})
    return w


def info_fields(word_id: int, include_flagged: bool = False) -> dict[str, Any]:
    sql = "SELECT id, field, value, source, verified, flagged FROM word_info WHERE word_id=? AND active=1"
    if not include_flagged:
        sql += " AND flagged=0"
    out: dict[str, Any] = {}
    meta: dict[str, Any] = {}
    for r in db.q(sql + " ORDER BY (source='user') DESC, id DESC", (word_id,)):
        if r["field"] in out:
            continue
        out[r["field"]] = db.jload(r["value"])
        meta[r["field"]] = {"id": r["id"], "source": r["source"], "verified": r["verified"], "flagged": r["flagged"]}
    out["_meta"] = meta
    return out


def examples(word_id: int, include_flagged: bool = False) -> list[dict]:
    sql = "SELECT * FROM examples WHERE word_id=? AND active=1"
    if not include_flagged:
        sql += " AND flagged=0"
    return db.q(sql + " ORDER BY id", (word_id,))


def mnemonics(word_id: int, include_flagged: bool = False) -> list[dict]:
    sql = "SELECT * FROM mnemonics WHERE word_id=? AND active=1"
    if not include_flagged:
        sql += " AND flagged=0"
    return db.q(sql + " ORDER BY (source='user') DESC, id DESC", (word_id,))


def pick_example(word_id: int, require_form: str | None = None, exclude_ids: set[int] | None = None,
                 for_cloze: bool = False) -> dict | None:
    """Dönüşümlü örnek: en az gösterilen + en eski gösterilen önce."""
    exs = examples(word_id)
    if exclude_ids:
        exs = [e for e in exs if e["id"] not in exclude_ids]
    if for_cloze:
        exs = [e for e in exs if e.get("form") and "..." not in (e.get("form") or "")]
    if require_form:
        pref = [e for e in exs if tu.norm_en(e.get("form") or "") == require_form]
        if pref:
            exs = pref
    if not exs:
        return None
    exs.sort(key=lambda e: (e["times_shown"] - (1 if is_osym(e) else 0), e["last_shown_at"] or "", e["id"]))
    return exs[0]


def is_osym(e: dict) -> bool:
    """Gerçek ÖSYM cümlesi: dönüşümde bir tur öne alınır (önce gerçekler, sonra üretilenler, sonra yine gerçekler...)."""
    return (e.get("source") or "").startswith("osym:")


def mark_example_shown(example_id: int) -> None:
    db.x("UPDATE examples SET times_shown=times_shown+1, last_shown_at=? WHERE id=?",
         (config.iso(config.now_utc()), example_id))


def bundle(word_id: int, include_flagged: bool = True) -> dict | None:
    w = get_word(word_id)
    if not w:
        return None
    card = db.q1("SELECT * FROM cards WHERE word_id=?", (word_id,)) or {}
    info = info_fields(word_id, include_flagged=include_flagged)
    return {
        "word": w,
        "card": {k: card.get(k) for k in ("stage", "state", "stability", "difficulty", "due", "due_day", "reps",
                                          "lapses", "wrong_total", "introduced_at", "learned_at", "known_status",
                                          "flag_hard", "last_review")},
        "info": info,
        "examples": examples(word_id, include_flagged=include_flagged),
        "mnemonics": mnemonics(word_id, include_flagged=include_flagged),
        "confusables": confusable_partners(word_id),
    }


def confusable_partners(word_id: int) -> list[dict]:
    rows = db.q("""SELECT c.kind, c.score, c.distinguished_at,
                          CASE WHEN c.word_a=? THEN c.word_b ELSE c.word_a END AS other
                   FROM confusables c WHERE c.word_a=? OR c.word_b=?""", (word_id, word_id, word_id))
    idx = index()["items"]
    out = []
    for r in rows:
        o = idx.get(r["other"])
        if o:
            out.append({"id": o["id"], "display": o["display"], "meaning": o["short"], "kind": r["kind"],
                        "score": r["score"]})
    out.sort(key=lambda x: -(x["score"] or 0))
    return out


# ---------------------------------------------------------------- ekleme / düzenleme
_offline: dict | None = None


def offline_lookup(lemma: str) -> dict | None:
    global _offline
    if _offline is None:
        p = config.seed_dir() / "dict_offline.json"
        _offline = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    lemma = tu.norm_en(lemma)
    if lemma in _offline:
        return _offline[lemma]
    # basit kök denemesi (çoğul / -ed / -ing)
    for suf, rep in (("ies", "y"), ("es", ""), ("s", ""), ("ed", ""), ("ed", "e"), ("ing", ""), ("ing", "e")):
        if lemma.endswith(suf) and len(lemma) > len(suf) + 2:
            cand = lemma[: -len(suf)] + rep
            if cand in _offline:
                return {**_offline[cand], "from": cand}
    return None


def add_user_word(text: str, meaning: str | None = None, pos: str | None = None, note: str | None = None,
                  enrich: bool = True) -> dict:
    """Deneme sınavından hızlı ekleme. Var olan kelimeyse (yedek/öneri) etkinleştirir.

    İçeriği olmayan kelime hemen zenginleştirme kuyruğuna girer (`enrich=False`: çağıran toplu kuyruğa alır).
    """
    from . import enrichment
    display = text.strip()
    lemma = tu.norm_en(display)
    if not lemma:
        raise ValueError("Boş kelime")
    now = config.iso(config.now_utc())
    existing = db.q1("SELECT * FROM words WHERE lemma=?", (lemma,))
    look = offline_lookup(lemma)
    if existing:
        updates = []
        if existing["status"] != "active" or existing["pool"] in ("reserve", "suggestion"):
            db.x("UPDATE words SET status='active', pool=CASE WHEN pool IN ('reserve','suggestion') THEN 'user' ELSE pool END, "
                 "order_index=?, updated_at=? WHERE id=?", (_front_order(), now, existing["id"]))
            updates.append("plana alındı")
        if meaning and meaning.strip():
            db.x("UPDATE words SET meaning_user=?, updated_at=? WHERE id=?", (meaning.strip(), now, existing["id"]))
            updates.append("anlam güncellendi")
        ensure_card(existing["id"])
        invalidate_index()
        if enrich:
            enrichment.queue_missing([existing["id"]], reason="user_add")
        return {"id": existing["id"], "lemma": lemma, "status": "existing", "updates": updates,
                "meaning": meaning or effective_meaning(existing)}
    gen_meaning = None
    if not meaning and look:
        gen_meaning = look.get("tr")
        if not pos:
            pos = look.get("pos")
    kind = "phrasal" if (" " in lemma and (pos or "").startswith("fiil")) else ("compound" if (" " in lemma or "-" in lemma) else "word")
    try:
        from wordfreq import zipf_frequency
        zipf = round(zipf_frequency(lemma, "en"), 2)
    except Exception:
        zipf = None
    feats = tu.word_features(lemma, pos, kind)
    wid = db.x("""INSERT INTO words(lemma, display, kind, pos, meaning_user, meaning_gen, pool, status, order_index,
                                    zipf, features, cov_weight, tags, created_at)
                  VALUES(?,?,?,?,?,?,'user','active',?,?,?,?,?,?)""",
               (lemma, display, kind, pos, (meaning or None), gen_meaning, _front_order(), zipf,
                db.jdump(feats), 0.0015, ("deneme sınavından" + (f" — {note}" if note else "")), now))
    ensure_card(wid)
    invalidate_index()
    # zenginleştirme kuyruğuna ekle (internet/anahtar varsa işlenir)
    if enrich:
        enrichment.queue_enrich([wid], reason="user_add")
    return {"id": wid, "lemma": lemma, "status": "new", "meaning": meaning or gen_meaning,
            "meaning_source": ("sen" if meaning else ("çevrimdışı sözlük" if gen_meaning else None))}


def _front_order() -> float:
    """Kullanıcı eklemeleri sıradaki ilk pakete girer."""
    pref = db.get_setting("user_added_priority", "front")
    mn = db.val("""SELECT MIN(w.order_index) FROM words w JOIN cards c ON c.word_id=w.id
                   WHERE w.status='active' AND c.stage=0 AND c.introduced_at IS NULL""", default=1.0)
    if pref == "front":
        return float(mn) - 1.0
    return float(mn) + 50.0


def ensure_card(word_id: int) -> None:
    db.x("INSERT OR IGNORE INTO cards(word_id, stage, state, updated_at) VALUES(?,0,0,?)",
         (word_id, config.iso(config.now_utc())))


def set_user_meaning(word_id: int, meaning: str | None) -> None:
    db.x("UPDATE words SET meaning_user=?, updated_at=? WHERE id=?",
         ((meaning or "").strip() or None, config.iso(config.now_utc()), word_id))
    invalidate_index()


def add_user_mnemonic(word_id: int, text: str) -> int:
    mid = db.x("INSERT INTO mnemonics(word_id, text, kind, source, verified, created_at) VALUES(?,?,?,?,1,?)",
               (word_id, text.strip(), "association", "user", config.iso(config.now_utc())))
    return mid


def flag_content(word_id: int, target: str, target_id: int | None, note: str | None = None) -> int:
    """'Bu bilgi yanlış' işareti: ilgili içerik gizlenir, kayıt tutulur."""
    now = config.iso(config.now_utc())
    table = {"example": "examples", "mnemonic": "mnemonics", "info": "word_info"}.get(target)
    if table and target_id:
        db.x(f"UPDATE {table} SET flagged=1 WHERE id=? AND word_id=?", (target_id, word_id))
    fid = db.x("INSERT INTO flags(ts, word_id, target, target_id, note) VALUES(?,?,?,?,?)",
               (now, word_id, target, target_id, note))
    invalidate_index()
    return fid


def unflag_content(word_id: int, target: str, target_id: int) -> None:
    table = {"example": "examples", "mnemonic": "mnemonics", "info": "word_info"}.get(target)
    if table:
        db.x(f"UPDATE {table} SET flagged=0 WHERE id=? AND word_id=?", (target_id, word_id))
        db.x("UPDATE flags SET resolved=1 WHERE word_id=? AND target=? AND target_id=?", (word_id, target, target_id))
    invalidate_index()


def verify_content(word_id: int, target: str, target_id: int) -> None:
    table = {"example": "examples", "mnemonic": "mnemonics", "info": "word_info"}.get(target)
    if table:
        db.x(f"UPDATE {table} SET verified=1, flagged=0 WHERE id=? AND word_id=?", (target_id, word_id))


def edit_example(word_id: int, example_id: int, en: str, tr: str) -> int:
    """Kullanıcı düzenlemesi: eski örnek pasif, yeni örnek 'user' kaynaklı ve doğrulanmış."""
    old = db.q1("SELECT * FROM examples WHERE id=? AND word_id=?", (example_id, word_id))
    if not old:
        raise ValueError("örnek bulunamadı")
    w = get_word(word_id)
    forms = tu.all_forms(w["lemma"], tu.pos_list(w.get("pos")))
    surface = tu.contains_form(en, forms) or old.get("form")
    db.x("UPDATE examples SET active=0 WHERE id=?", (example_id,))
    return db.x("""INSERT INTO examples(word_id, en, tr, form, domain, source, verified, created_at)
                   VALUES(?,?,?,?,?,'user',1,?)""",
                (word_id, en.strip(), tr.strip(), surface, old.get("domain"), config.iso(config.now_utc())))


def set_info(word_id: int, field: str, value: Any) -> int:
    db.x("UPDATE word_info SET active=0 WHERE word_id=? AND field=?", (word_id, field))
    rid = db.x("INSERT INTO word_info(word_id, field, value, source, verified, created_at) VALUES(?,?,?,'user',1,?)",
               (word_id, field, db.jdump(value), config.iso(config.now_utc())))
    invalidate_index()
    return rid


def suggestions(status: str = "pending") -> list[dict]:
    rows = db.q("""SELECT id, lemma, display, kind, pos, meaning_gen, meaning_src, tags, features, zipf
                   FROM words WHERE pool='suggestion' AND status=? ORDER BY kind, zipf DESC""", (status,))
    out = []
    for r in rows:
        f = db.jload(r["features"], {})
        out.append({"id": r["id"], "display": r["display"], "kind": r["kind"],
                    "meaning": r["meaning_src"] or r["meaning_gen"], "reason": r["tags"],
                    "priority": f.get("suggest_priority"), "relation": f.get("relation"), "zipf": r["zipf"] or 0})
    out.sort(key=lambda x: (x["kind"], -(x["priority"] or 0), -(x["zipf"] or 0)))
    return out


def decide_suggestions(ids: list[int], accept: bool) -> int:
    now = config.iso(config.now_utc())
    n = 0
    for wid in ids:
        if accept:
            db.x("UPDATE words SET status='active', pool='main', order_index=?, updated_at=? "
                 "WHERE id=? AND pool='suggestion'", (_front_order() + 5 + n * 0.01, now, wid))
            ensure_card(wid)
        else:
            db.x("UPDATE words SET status='rejected', updated_at=? WHERE id=? AND pool='suggestion'", (now, wid))
        n += 1
    invalidate_index()
    if accept and ids:
        from . import enrichment
        enrichment.queue_missing(ids, reason="öneri onaylandı")
    return n


def set_reserve_enabled(enabled: bool) -> None:
    db.set_setting("include_reserve", bool(enabled))
    st = "active" if enabled else "inactive"
    db.x("UPDATE words SET status=? WHERE pool='reserve' AND status IN ('active','inactive')", (st,))
    if enabled:
        for r in db.q("SELECT id FROM words WHERE pool='reserve'"):
            ensure_card(r["id"])
    invalidate_index()
    if enabled:
        from . import enrichment
        enrichment.queue_missing(reason="yedek plana alındı")
