"""Partlar: yeni kelimeler en fazla 15'lik kalıcı gruplar hâlinde öğrenilir (Memrise seviyeleri gibi).

- Part, öğrenmeye başlanırken plan sırasındaki sıradaki ≤15 kelimeyle oluşur; üyelik kalıcıdır.
- Part oturumu yalnızca o partın kelimelerini öğretir (tanıtım + 4 basamak) ya da doğrular (4 kontrol); yarıda
  bırakılırsa kaldığı yerden sürer. Bütün kelimeleri bitince part 'tamamlandı' olur ve öyle kalır.
- Seçilen partların kelimeleriyle karışık hızlı test ya da normal test yapılabilir.
"""
from __future__ import annotations

import math

from . import config, db

MAX_SIZE = 15


def size() -> int:
    return max(5, min(MAX_SIZE, int(db.get_setting("part_size", MAX_SIZE))))


def _learn_steps() -> int:
    """Kartın oturum içinde ulaştığı basamak: sınama basamağı sayısı (öğretme katmanları basamak saymaz)."""
    from .session import TEST_RUNGS
    return len(TEST_RUNGS)


def _rows(part_ids: list[int] | None = None) -> list[dict]:
    """Part kelimeleri ve kart durumları (part sırasıyla)."""
    if part_ids is not None and not part_ids:
        return []
    where = "" if part_ids is None else f"WHERE pw.part_id IN ({','.join('?' * len(part_ids))})"
    return db.q(f"""SELECT pw.part_id, pw.word_id, pw.pos, w.status, c.stage, c.state, c.known_status, c.introduced_at,
                           c.due_day, c.lapses, c.wrong_total
                    FROM part_words pw JOIN words w ON w.id=pw.word_id LEFT JOIN cards c ON c.word_id=pw.word_id
                    {where} ORDER BY pw.part_id, pw.pos""", tuple(part_ids or ()))


def _word_done(r: dict) -> bool:
    """Oturum içi 4 basamağı bitmiş ya da 4 kontrolle doğrulanmış (plandan çıkan kelime de bitmiş sayılır)."""
    return r["status"] != "active" or (r["stage"] or 0) >= _learn_steps() or r["known_status"] == "verified"


def _stats(rows: list[dict]) -> dict:
    act = [r for r in rows if r["status"] == "active"]
    today = config.day_str()
    return {"total": len(act),
            "done": sum(1 for r in act if _word_done(r)),
            "started": sum(1 for r in act if r["introduced_at"] or r["known_status"] == "verified"),
            "learned": sum(1 for r in act if (r["stage"] or 0) >= 6),
            "testable": sum(1 for r in act if (r["state"] or 0) >= 1),
            "due": sum(1 for r in act if (r["state"] or 0) >= 1 and r["due_day"] and r["due_day"] <= today),
            "weak": sum(1 for r in act if (r["lapses"] or 0) > 0 or (r["wrong_total"] or 0) >= 3)}


def _with_stats(p: dict, rows: list[dict]) -> dict:
    st = _stats(rows)
    status = "tamam" if p["finished_at"] else ("devam" if st["started"] else "yeni")
    return {**p, **st, "status": status}


def list_parts() -> list[dict]:
    by: dict[int, list[dict]] = {}
    for r in _rows():
        by.setdefault(r["part_id"], []).append(r)
    return [_with_stats(p, by.get(p["id"], [])) for p in db.q("SELECT * FROM parts ORDER BY no")]


def get(part_id: int) -> dict | None:
    p = db.q1("SELECT * FROM parts WHERE id=?", (part_id,))
    return _with_stats(p, _rows([part_id])) if p else None


def refresh(part_id: int) -> bool:
    """Bütün kelimeleri bittiyse partı 'tamamlandı' işaretler; açık kaldıysa True döner."""
    rows = _rows([part_id])
    if rows and not all(_word_done(r) for r in rows):
        return True
    db.x("UPDATE parts SET finished_at=COALESCE(finished_at, ?) WHERE id=?", (config.iso(config.now_utc()), part_id))
    return False


def open_part() -> dict | None:
    """Bitmemiş en eski part: yarıda kalan part yenisinden önce bitirilir."""
    for p in db.q("SELECT id FROM parts WHERE finished_at IS NULL ORDER BY no"):
        if refresh(p["id"]):
            return get(p["id"])
    return None


def create(word_ids: list[int], title: str | None = None) -> int | None:
    if not word_ids:
        return None
    no = int(db.val("SELECT COALESCE(MAX(no), 0) FROM parts", default=0) or 0) + 1
    with db.tx() as conn:
        cur = conn.execute("INSERT INTO parts(no, created_at, day, size, title) VALUES(?,?,?,?,?)",
                           (no, config.iso(config.now_utc()), config.day_str(), len(word_ids), title))
        pid = cur.lastrowid
        conn.executemany("INSERT OR IGNORE INTO part_words(part_id, word_id, pos) VALUES(?,?,?)",
                         [(pid, w, i) for i, w in enumerate(word_ids)])
    return pid


def part_group(word_ids: list[int]) -> dict[int, str | None]:
    """Kelimelerin plan grubu (ör. 'Gün 3 · A', 'Gün 3 · Ek'): Ezberbozan günleri parta bölünmeden girer."""
    if not word_ids:
        return {}
    rows = db.q(f"SELECT id, json_extract(features, '$.part_group') g FROM words WHERE id IN "
                f"({','.join('?' * len(word_ids))})", tuple(word_ids))
    return {r["id"]: r["g"] for r in rows}


def next_part(create_new: bool = True) -> dict | None:
    """Yarım kalan part ya da (izin varsa) plan sırasındaki sıradaki ≤15 kelimeden yeni part. Kelimelerin plan grubu
    varsa (kitap günü A/B ya da Ek) part o grupla sınırlanır ve grubun adını taşır."""
    p = open_part()
    if p or not create_new:
        return p
    from .session import ORPHAN_AFTER, confusable_map, pick_new_words, reorder_packs
    ids = pick_new_words(size(), include_probable=True)
    if not ids:
        return None
    first = db.q1(f"""SELECT json_extract(features, '$.part_group') g FROM words WHERE id IN ({','.join('?' * len(ids))})
                      ORDER BY order_index LIMIT 1""", tuple(ids))
    title = first["g"] if first else None
    if title:
        # kitap günü grubu bölünmez: grubun henüz parta girmemiş bütün kelimeleri (karışabilir çiftler yalnızca ayrı
        # 5'li paketlere kaydırılır, başka parta ertelenmez)
        cutoff = config.iso(config.now_utc() - ORPHAN_AFTER)
        rows = db.q("""SELECT c.word_id FROM cards c JOIN words w ON w.id=c.word_id
                       WHERE w.status='active' AND json_extract(w.features, '$.part_group')=? AND c.state=0
                         AND (c.introduced_at IS NULL OR c.introduced_at < ?)
                         AND NOT EXISTS (SELECT 1 FROM part_words pw WHERE pw.word_id=c.word_id)
                       ORDER BY w.order_index""", (title, cutoff))
        ids = reorder_packs([r["word_id"] for r in rows][:MAX_SIZE], confusable_map(), 5)
    return get(create(ids, title=title) or 0)


def can_create() -> bool:
    from .session import pick_new_words
    return bool(pick_new_words(1, include_probable=True))


def remaining_words(part_id: int) -> list[int]:
    return [r["word_id"] for r in _rows([part_id]) if not _word_done(r)]


def test_words(part_ids: list[int]) -> list[int]:
    """Testte sorulabilecek kelimeler: en az bir kez cevaplanmış (FSRS kaydı olan) etkin kelimeler."""
    return [r["word_id"] for r in _rows(part_ids) if r["status"] == "active" and (r["state"] or 0) >= 1]


def backfill() -> int:
    """Part sisteminden önce tanıtılmış kelimeleri tanıtım sırasıyla 15'lik partlara yerleştirir (bir kez)."""
    if db.get_meta("parts_backfilled"):
        return 0
    n = 0
    if not db.val("SELECT COUNT(*) FROM parts", default=0):
        rows = db.q("""SELECT c.word_id, c.introduced_at FROM cards c JOIN words w ON w.id=c.word_id
                       WHERE c.introduced_at IS NOT NULL ORDER BY c.introduced_at, c.word_id""")
        # dengeli bölme: 16 kelime 15+1 değil 8+8 olur (her part yine en fazla 15)
        k = math.ceil(len(rows) / size()) if rows else 0
        bounds = [round(i * len(rows) / k) for i in range(k + 1)] if k else []
        for a, b in zip(bounds, bounds[1:]):
            chunk = rows[a:b]
            pid = create([r["word_id"] for r in chunk])
            first = chunk[0]["introduced_at"]
            db.x("UPDATE parts SET created_at=?, day=? WHERE id=?", (first, config.day_str(config.parse_iso(first)), pid))
            refresh(pid)
            n += 1
    db.set_meta("parts_backfilled", config.iso(config.now_utc()))
    return n


def _next_group_info(op: dict | None) -> dict:
    """Sıradaki (henüz kurulmamış) partın kitap günü grubu ve kelime sayısı: 'Gün 1 · B', 10."""
    if op:
        return {"next_title": op.get("title"), "next_size": op["total"] - op["done"]}
    row = db.q1("""SELECT json_extract(w.features, '$.part_group') g FROM cards c JOIN words w ON w.id=c.word_id
                   WHERE w.status='active' AND c.state=0
                     AND NOT EXISTS (SELECT 1 FROM part_words pw WHERE pw.word_id=c.word_id)
                   ORDER BY w.order_index LIMIT 1""")
    g = row["g"] if row else None
    if not g:
        return {"next_title": None, "next_size": None}
    n = db.val("""SELECT COUNT(*) FROM cards c JOIN words w ON w.id=c.word_id WHERE w.status='active' AND c.state=0
                  AND json_extract(w.features, '$.part_group')=?
                  AND NOT EXISTS (SELECT 1 FROM part_words pw WHERE pw.word_id=c.word_id)""", (g,), default=0)
    return {"next_title": g, "next_size": min(MAX_SIZE, int(n or 0))}


def today_info(plan: dict | None = None) -> dict:
    from . import planner
    plan = plan or planner.today_plan()
    k = size()
    new_planned = int(plan.get("new_planned") or 0)
    since = config.iso(config.day_start_utc(config.study_day()))
    op = open_part()
    last_no = int(db.val("SELECT COALESCE(MAX(no), 0) FROM parts", default=0) or 0)
    allow_new = plan.get("phase") != "final"
    # kitap planında partlar gün gruplarıdır (10 / 10 / ≤13): bugünkü part sayısı ortalama grup büyüklüğüyle hesaplanır
    row = db.q1("""SELECT COUNT(*) n, COUNT(DISTINCT json_extract(features, '$.part_group')) g FROM words
                   WHERE status='active' AND json_extract(features, '$.part_group') IS NOT NULL""")
    avg = (row["n"] / row["g"]) if row and row["g"] else k
    return {"size": k, "planned": math.ceil(new_planned / avg) if new_planned > 0 else 0,
            "finished_today": int(db.val("SELECT COUNT(*) FROM parts WHERE finished_at >= ?", (since,), default=0) or 0),
            "open": op, "next_no": op["no"] if op else last_no + 1, **_next_group_info(op),
            "next_available": bool(op) or (allow_new and can_create()), "total": last_no}
