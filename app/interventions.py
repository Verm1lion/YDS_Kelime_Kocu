"""İnatçı kelimelere (4+ hata) otomatik müdahale ve etkisinin ölçülmesi.

Müdahale kartı: yeni hafıza ipucu, kök/köken açıklaması, karıştığı kelimeyle karşılaştırma, yeni örnek
cümleler ve sonraki tekrarlarda farklı alıştırma türü. LLM erişilebilirse yeni içerik üretimi kuyruğa alınır.
Etki: müdahale öncesi son 8 cevap doğruluğu vs. sonraki 3+ cevap doğruluğu.
"""
from __future__ import annotations

from datetime import timedelta

from . import config, db
from . import words as W

THRESHOLD = 4
EVERY = 3
COOLDOWN_DAYS = 3


def _accuracy(rows: list[dict]) -> float | None:
    rows = [r for r in rows if r["correct"] is not None]
    if not rows:
        return None
    return sum(1 for r in rows if r["correct"]) / len(rows)


def maybe_trigger(word_id: int) -> int | None:
    card = db.q1("SELECT wrong_total, last_intervention_at FROM cards WHERE word_id=?", (word_id,))
    if not card:
        return None
    wt = int(card["wrong_total"] or 0)
    if wt < THRESHOLD or (wt - THRESHOLD) % EVERY != 0:
        return None
    if card["last_intervention_at"]:
        if config.parse_iso(card["last_intervention_at"]) > config.now_utc() - timedelta(days=COOLDOWN_DAYS):
            return None
    return create(word_id, wt)


def create(word_id: int, wrong_total: int) -> int:
    now = config.now_utc()
    it = W.index()["items"].get(word_id)
    pre = db.q("""SELECT correct FROM events WHERE word_id=? AND correct IS NOT NULL AND mode!='placement'
                  ORDER BY id DESC LIMIT 8""", (word_id,))
    pre_acc = _accuracy(pre)
    # karıştırılan kelime
    conf = db.q1("""SELECT confused_with, COUNT(*) n FROM events WHERE word_id=? AND confused_with IS NOT NULL
                    GROUP BY confused_with ORDER BY n DESC LIMIT 1""", (word_id,))
    errs = db.q("""SELECT error_type, COUNT(*) n FROM events WHERE word_id=? AND correct=0 GROUP BY error_type
                   ORDER BY n DESC""", (word_id,))
    content: dict = {"wrong_total": wrong_total, "error_profile": {e["error_type"] or "?": e["n"] for e in errs},
                     "sections": []}
    kinds = []
    mems = W.mnemonics(word_id)
    shown_ids = {db.jload(r["extra"], {}).get("mnemonic_id") for r in
                 db.q("SELECT extra FROM events WHERE word_id=? AND exercise='intro'", (word_id,))}
    alt = [m for m in mems if m["id"] not in shown_ids]
    if alt:
        m = alt[0]
        content["sections"].append({"kind": "mnemonic" if m["kind"] != "etymology" else "etymology",
                                    "title": "Yeni hafıza ipucu" if m["kind"] != "etymology" else "Kök / köken",
                                    "text": m["text"], "source": m["source"], "id": m["id"]})
        kinds.append("mnemonic" if m["kind"] != "etymology" else "etymology")
    ety = next((m for m in mems if m["kind"] == "etymology"), None)
    if ety and "etymology" not in kinds:
        content["sections"].append({"kind": "etymology", "title": "Kök / köken", "text": ety["text"],
                                    "source": ety["source"], "id": ety["id"]})
        kinds.append("etymology")
    if conf and conf["confused_with"]:
        o = W.index()["items"].get(conf["confused_with"])
        if o and it:
            ex_o = W.pick_example(o["id"])
            content["sections"].append({
                "kind": "compare", "title": f"Karıştırdığın kelime: {o['display']} ({conf['n']} kez)",
                "a": {"display": it["display"], "meaning": it["meaning"]},
                "b": {"display": o["display"], "meaning": o["meaning"], "example": ex_o["en"] if ex_o else None},
                "tip": _compare_tip(it, o)})
            kinds.append("compare")
            a, b = sorted((word_id, o["id"]))
            db.x("INSERT OR IGNORE INTO confusables(word_a, word_b, kind, score, source) VALUES(?,?,?,?,?)",
                 (a, b, "kullanıcı", 1.0, "karışıklık"))
            db.x("UPDATE confusables SET distinguished_at=NULL WHERE word_a=? AND word_b=?", (a, b))
    exs = sorted(W.examples(word_id), key=lambda e: (e["times_shown"], e["id"]))[:2]
    if exs:
        content["sections"].append({"kind": "examples", "title": "Yeni bağlamlar",
                                    "items": [{"en": e["en"], "tr": e.get("tr"), "form": e.get("form")} for e in exs]})
        kinds.append("examples")
    content["sections"].append({"kind": "switch", "title": "Alıştırma değişiyor",
                                "text": "Bu kelime bir süre üretim (yazma) ve bağlam (boşluk doldurma) alıştırmalarıyla sorulacak."})
    kinds.append("switch")
    db.x("UPDATE cards SET flag_hard=1, last_intervention_at=? WHERE word_id=?", (config.iso(now), word_id))
    iid = db.x("""INSERT INTO interventions(word_id, ts, kind, content, source, pre_stats)
                  VALUES(?,?,?,?,?,?)""",
               (word_id, config.iso(now), "+".join(kinds), db.jdump(content), "çevrimdışı",
                db.jdump({"accuracy": pre_acc, "n": len(pre), "wrong_total": wrong_total})))
    from . import enrichment
    enrichment.queue_intervention(word_id, iid, conf["confused_with"] if conf else None)
    return iid


def _compare_tip(a: dict, b: dict) -> str:
    la, lb = a["lemma"], b["lemma"]
    i = 0
    while i < min(len(la), len(lb)) and la[i] == lb[i]:
        i += 1
    if i >= 2:
        return (f"İkisi de '{la[:i]}' ile başlıyor; farkı '{la[i:] or '—'}' / '{lb[i:] or '—'}' kısmında. "
                f"{a['display']} = {a['short']}; {b['display']} = {b['short']}.")
    return f"{a['display']} = {a['short']}; {b['display']} = {b['short']}. Anlamları farklı, cümledeki ipucuna bak."


def payload(iid: int) -> dict:
    r = db.q1("SELECT * FROM interventions WHERE id=?", (iid,))
    content = db.jload(r["content"], {}) if r else {}
    it = W.index()["items"].get(r["word_id"]) if r else None
    return {"type": "intervention", "type_label": "İnatçı kelime", "word_id": r["word_id"] if r else None,
            "display": it["display"] if it else "", "meaning": it["meaning"] if it else "",
            "wrong_total": content.get("wrong_total"), "sections": content.get("sections", []),
            "intervention_id": iid}


def mark_shown(iid: int) -> None:
    db.x("UPDATE interventions SET shown_at=COALESCE(shown_at, ?) WHERE id=?", (config.iso(config.now_utc()), iid))


def evaluate_all() -> int:
    n = 0
    for r in db.q("SELECT * FROM interventions WHERE effective IS NULL AND shown_at IS NOT NULL"):
        post = db.q("""SELECT correct FROM events WHERE word_id=? AND ts>? AND correct IS NOT NULL AND mode!='placement'
                       ORDER BY id LIMIT 6""", (r["word_id"], r["shown_at"]))
        if len(post) < 3:
            continue
        pre = db.jload(r["pre_stats"], {})
        acc = _accuracy(post)
        pre_acc = pre.get("accuracy") or 0.0
        eff = 1 if (acc is not None and (acc >= 0.67 or acc - pre_acc >= 0.2)) else 0
        db.x("UPDATE interventions SET post_stats=?, effective=? WHERE id=?",
             (db.jdump({"accuracy": acc, "n": len(post)}), eff, r["id"]))
        n += 1
    return n


def summary() -> dict:
    rows = db.q("SELECT kind, effective, pre_stats, post_stats FROM interventions")
    by: dict[str, dict] = {}
    for r in rows:
        for k in (r["kind"] or "").split("+"):
            d = by.setdefault(k, {"n": 0, "evaluated": 0, "effective": 0, "pre": [], "post": []})
            d["n"] += 1
            if r["effective"] is not None:
                d["evaluated"] += 1
                d["effective"] += r["effective"]
                pre = db.jload(r["pre_stats"], {}).get("accuracy")
                post = db.jload(r["post_stats"], {}).get("accuracy")
                if pre is not None:
                    d["pre"].append(pre)
                if post is not None:
                    d["post"].append(post)
    out = {}
    for k, d in by.items():
        out[k] = {"n": d["n"], "evaluated": d["evaluated"],
                  "success_rate": (d["effective"] / d["evaluated"]) if d["evaluated"] else None,
                  "pre_acc": (sum(d["pre"]) / len(d["pre"])) if d["pre"] else None,
                  "post_acc": (sum(d["post"]) / len(d["post"])) if d["post"] else None}
    recent = db.q("""SELECT i.id, i.word_id, i.ts, i.kind, i.effective, w.display FROM interventions i
                     JOIN words w ON w.id=i.word_id ORDER BY i.id DESC LIMIT 20""")
    return {"by_kind": out, "recent": recent}
