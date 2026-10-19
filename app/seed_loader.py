"""İlk kurulumda ve sürüm yükseltmelerinde tohum verisini veritabanına yükler.

Kural: Kullanıcı verisi (anlam düzenlemeleri, kendi mem'leri, olay kaydı, kart durumu) asla
değiştirilmez. Yeni tohum içeriği yalnızca o kelimede tohum içeriği yoksa eklenir.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import config, db
from . import textutil as tu


def init_db() -> None:
    db.migrate()
    if (db.val("SELECT COUNT(*) FROM words", default=0) or 0) == 0:
        load_pool()
    load_confusables()
    load_seed_content()
    load_osym_examples()
    load_ezberbozan()
    from . import parts
    parts.backfill()   # part sisteminden önce öğrenilen kelimeler partlara (bir kez)
    db.set_meta("app_version", config.VERSION)


def load_osym_examples(path: Path | None = None) -> int:
    """Gerçek ÖSYM cümleleri (kelimenin sınavda geçtiği ya da doğru cevap olarak sorulduğu cümle; İngilizcesi özgün,
    Türkçesi yapay zekâ çevirisi). Dosya değiştiyse eksikler eklenir; var olan örneklere ve kullanıcı verisine dokunulmaz."""
    path = path or (config.seed_dir() / "osym_examples.json")
    if not path.exists():
        return 0
    raw = path.read_bytes()
    digest = hashlib.sha1(raw).hexdigest()
    if db.get_meta("osym_examples_sha") == digest:
        return 0
    items = json.loads(raw.decode("utf-8")).get("items", [])
    ids = {r["lemma"]: r["id"] for r in db.q("SELECT id, lemma FROM words")}
    have = {(r["word_id"], r["en"]) for r in db.q("SELECT word_id, en FROM examples WHERE source LIKE 'osym:%'")}
    now = config.iso(config.now_utc())
    n = 0
    with db.tx() as conn:
        for it in items:
            wid = ids.get(it["lemma"])
            if not wid or (wid, it["en"]) in have:
                continue
            conn.execute("""INSERT INTO examples(word_id, en, tr, form, domain, source, verified, created_at)
                            VALUES(?,?,?,?,?,?,1,?)""",
                         (wid, it["en"], it["tr"], it["form"], it.get("domain"), "osym:" + it["source"], now))
            have.add((wid, it["en"]))
            n += 1
    db.set_meta("osym_examples_sha", digest)
    return n


def load_ezberbozan(path: Path | None = None) -> int:
    """60 Günde Ezberbozan kitabının eş/yakın anlamlıları (ve kitapta tanım verilmişse tanımı) — kaynak 'ezberbozan',
    doğrulanmış; tanıtım kartında kelimenin yanında önce gösterilir. Dosya değişince eksikler eklenir."""
    path = path or (config.seed_dir() / "ezberbozan.json")
    if not path.exists():
        return 0
    raw = path.read_bytes()
    digest = hashlib.sha1(raw).hexdigest()
    if db.get_meta("ezberbozan_sha") == digest:
        return 0
    items = json.loads(raw.decode("utf-8")).get("items", [])
    ids = {r["lemma"]: r["id"] for r in db.q("SELECT id, lemma FROM words")}
    have = {(r["word_id"], r["field"]) for r in db.q("SELECT word_id, field FROM word_info WHERE source='ezberbozan'")}
    now = config.iso(config.now_utc())
    rows = []
    for it in items:
        wid = ids.get(it["lemma"])
        if not wid:
            continue
        if it.get("synonyms") and (wid, "synonyms") not in have:
            rows.append((wid, "synonyms", db.jdump(it["synonyms"]), "ezberbozan", 1, now))
        if it.get("definition") and (wid, "definition") not in have:
            rows.append((wid, "definition", db.jdump(it["definition"]), "ezberbozan", 1, now))
    db.xmany("""INSERT INTO word_info(word_id, field, value, source, verified, created_at)
                VALUES(?,?,?,?,?,?)""", rows)
    db.set_meta("ezberbozan_sha", digest)
    from . import words
    words.invalidate_index()
    return len(rows)


def load_pool(path: Path | None = None) -> int:
    path = path or config.pool_path()
    data = json.loads(path.read_text(encoding="utf-8"))
    now = config.iso(config.now_utc())
    n = 0
    include_reserve = bool(db.get_setting("include_reserve", False))
    with db.tx() as conn:
        for it in data["items"]:
            status = "active" if it["pool"] == "main" or (it["pool"] == "reserve" and include_reserve) else "inactive"
            cur = conn.execute(
                """INSERT OR IGNORE INTO words(lemma, display, kind, pos, meaning_src, family_src, level, text_prob,
                       option_prob, src_count, osym_evidence, tags, sources, priority, order_index, zipf, pool, status,
                       plan_week, plan_day, features, cov_weight, created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (it["lemma"], it["display"], it["kind"], it.get("pos"), it.get("meaning"), it.get("family"),
                 it.get("level"), it.get("text_prob"), it.get("option_prob"), it.get("src_count"),
                 it.get("osym_evidence"), it.get("tags"), it.get("sources"), it.get("priority"),
                 it.get("order_index"), it.get("zipf"), it["pool"], status, it.get("plan_week"), it.get("plan_day"),
                 db.jdump(it.get("features") or {}), it.get("cov_weight") or 0.0, now))
            n += cur.rowcount
        sp = config.seed_dir() / "suggestions.json"
        if sp.exists():
            for s in json.loads(sp.read_text(encoding="utf-8")):
                feats = dict(s.get("features") or {})
                feats["suggest_priority"] = s.get("suggest_priority")
                feats["relation"] = s.get("relation")
                conn.execute(
                    """INSERT OR IGNORE INTO words(lemma, display, kind, pos, meaning_gen, tags, order_index, zipf, pool,
                           status, features, cov_weight, created_at)
                       VALUES(?,?,?,?,?,?,?,?, 'suggestion','pending',?,?,?)""",
                    (s["lemma"], s["display"], s["kind"], s.get("pos"), s.get("meaning"), s.get("suggest_reason"),
                     None, s.get("zipf"), db.jdump(feats), s.get("cov_weight") or 0.003, now))
        conn.execute("""INSERT OR IGNORE INTO cards(word_id, stage, state, updated_at)
                        SELECT id, 0, 0, ? FROM words WHERE status='active'""", (now,))
    db.set_meta("pool_loaded_at", now)
    return n


def load_confusables() -> int:
    p = config.seed_dir() / "confusables.json"
    if not p.exists():
        return 0
    data = json.loads(p.read_text(encoding="utf-8"))
    digest = hashlib.sha1(p.read_bytes()).hexdigest()
    if db.get_meta("confusables_digest") == digest:
        return 0
    ids = {r["lemma"]: r["id"] for r in db.q("SELECT id, lemma FROM words")}
    rows = []
    for c in data:
        a, b = ids.get(c["a"]), ids.get(c["b"])
        if a and b:
            a, b = (a, b) if a < b else (b, a)
            rows.append((a, b, c["kind"], c.get("score"), "otomatik"))
    db.xmany("INSERT OR IGNORE INTO confusables(word_a, word_b, kind, score, source) VALUES(?,?,?,?,?)", rows)
    db.set_meta("confusables_digest", digest)
    return len(rows)


def content_files() -> list[Path]:
    d = config.seed_dir()
    files = []
    if (d / "content.jsonl").exists():
        files.append(d / "content.jsonl")
    return files


def load_seed_content(force: bool = False) -> int:
    files = content_files()
    if not files:
        return 0
    h = hashlib.sha1()
    for f in files:
        h.update(f.read_bytes())
    digest = h.hexdigest()
    if not force and db.get_meta("seed_content_digest") == digest:
        return 0
    ids = {r["lemma"]: r["id"] for r in db.q("SELECT id, lemma FROM words")}
    have = {r["word_id"] for r in db.q("SELECT DISTINCT word_id FROM examples WHERE source='seed'")}
    now = config.iso(config.now_utc())
    n = 0
    with db.tx() as conn:
        for f in files:
            for line in f.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except json.JSONDecodeError:
                    continue
                wid = ids.get(tu.norm_en(o.get("lemma", "")))
                if not wid or wid in have:
                    continue
                insert_content(conn, wid, o, source="seed", now=now)
                have.add(wid)
                n += 1
    db.set_meta("seed_content_digest", digest)
    from . import words
    words.invalidate_index()
    return n


def insert_content(conn, wid: int, o: dict, source: str, now: str) -> None:
    """Üretilmiş içerik nesnesini (tohum veya LLM) tablolara yazar. Doğrulanmamış olarak."""
    for e in o.get("examples") or []:
        if not e.get("en"):
            continue
        conn.execute("""INSERT INTO examples(word_id, en, tr, form, domain, source, verified, created_at)
                        VALUES(?,?,?,?,?,?,0,?)""",
                     (wid, e["en"].strip(), (e.get("tr") or "").strip(), (e.get("form") or "").strip(),
                      e.get("domain"), source, now))
    for field in ("senses", "synonyms", "antonyms", "family", "confusables", "etymology", "concrete"):
        if field in o and o[field] not in (None, "", []):
            conn.execute("""INSERT INTO word_info(word_id, field, value, source, verified, created_at)
                            VALUES(?,?,?,?,0,?)""", (wid, field, db.jdump(o[field]), source, now))
    if o.get("mnemonic"):
        conn.execute("""INSERT INTO mnemonics(word_id, text, kind, source, verified, created_at)
                        VALUES(?,?,'association',?,0,?)""", (wid, o["mnemonic"].strip(), source, now))
    if o.get("etymology"):
        conn.execute("""INSERT INTO mnemonics(word_id, text, kind, source, verified, created_at)
                        VALUES(?,?,'etymology',?,0,?)""", (wid, o["etymology"].strip(), source, now))
    if o.get("meaning_tr"):
        conn.execute("UPDATE words SET meaning_gen=COALESCE(meaning_gen, ?) WHERE id=?", (o["meaning_tr"].strip(), wid))
    if isinstance(o.get("concrete"), bool):
        row = conn.execute("SELECT features FROM words WHERE id=?", (wid,)).fetchone()
        feats = db.jload(row[0], {}) if row else {}
        feats["concrete"] = o["concrete"]
        conn.execute("UPDATE words SET features=? WHERE id=?", (db.jdump(feats), wid))
