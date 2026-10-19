"""Çalışma oturumu motoru.

Sıra: (1) vadesi gelen tekrarlar — en riskli önce, (2) ayırt etme / doğrulama görevleri,
(3) yeni kelimeler — mini paketler hâlinde: tanıtım kartı + oturum içi merdiven (L1-L4, en az 4 adım), Memrise
tarzı genişleyen aralıklarla iç içe test. Yanlış cevapta kelime birkaç soru sonra yeniden sorulur.
Her cevap: otomatik puan -> FSRS -> ham olay kaydı.
"""
from __future__ import annotations

import random
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from . import cards as C
from . import config, db
from . import distractors as D
from . import exercises as X
from . import grading as G
from . import rating as R
from . import strategy
from . import words as W

SESSIONS: dict[str, "Session"] = {}
_lock = threading.RLock()

# Önce öğret, sonra sına (kullanıcı isteği; Memrise gibi kelime önce farklı yollarla kafaya kazınır):
# tanıtım → öğretme katmanları (bak·kapat·yaz → eşleştir → eş anlamlısından bul) → sınama basamakları, kolaydan zora
# (dinle ve seç → TR→EN test → boşluk doldurma → harflerden yazma). Öğretme katmanları FSRS'e işlenmez ve kartın
# merdiven basamağını ilerletmez (basamak 1-4 = geçilen sınama basamağı); eşleştirme paket düzeyindedir.
TEACH_RUNGS = ["look_write", "match", "syn_pick"]
TEST_RUNGS = ["listen", "mcq_tr_en", "cloze", "tiles"]
LEARN_RUNGS = TEACH_RUNGS + TEST_RUNGS
MATCH_RUNG = LEARN_RUNGS.index("match")
FSRS_STEPS_PER_NEW = len(TEST_RUNGS) + 1   # oturum içinde FSRS'e işlenen cevap: 4 sınama + part sonu pekiştirme
REVIEW_RUNG_FOR_STAGE = {4: "typing", 5: "synonym"}          # sonraki tekrarlarda (L5-L6)
VERIFY_CHECKS = ["mcq_tr_en", "cloze", "synonym", "typing"]   # 'biliyorum' ve ön test: 4 farklı türde kontrol
ORPHAN_AFTER = timedelta(hours=1)  # tanıtılıp hiç adımı yapılmadan oturumu kapanan kelime yeniden yeni sayılır


@dataclass
class LearnState:
    word_id: int
    rung: int = 0
    ready_at: int = 0
    errors: int = 0
    introduced: bool = False
    done: bool = False
    pretest: str | None = None   # None | pending | passed | failed
    resume: bool = False         # yarım kalan merdiven: önce hatırlatma kartı, sonra test → boşluk → yazma
    match_errors: int = 0        # eşleştirmedeki hata sayısı


@dataclass
class Session:
    id: str
    mode: str
    device: str
    started: datetime
    day: str
    reviews: list[int] = field(default_factory=list)
    review_pos: int = 0
    new_words: list[int] = field(default_factory=list)
    new_pos: int = 0
    pack: list[LearnState] = field(default_factory=list)
    pack_size: int = 5
    requeue: list[dict] = field(default_factory=list)   # {word_id, type, ready_at, reason, tries}
    extra_tasks: list[dict] = field(default_factory=list)  # ayırt etme, doğrulama, müdahale
    answer_count: int = 0
    pending: dict = field(default_factory=dict)          # token -> {secret, task, payload, shown_at}
    stats: dict = field(default_factory=lambda: {"answers": 0, "correct": 0, "new": 0, "reviews": 0,
                                                 "learned": [], "errors": 0, "xp": 0, "streak": 0, "best_streak": 0})
    last_event: dict | None = None
    latencies: list[tuple[float, float, bool]] = field(default_factory=list)  # (t, norm_latency, correct)
    last_break_hint: float = 0.0
    lives: int = 3
    speed_limit: int = 6000
    max_items: int | None = None
    rng: random.Random = field(default_factory=random.Random)
    active_ms: int = 0
    finished: bool = False
    seen_review: set = field(default_factory=set)
    arms: dict = field(default_factory=dict)
    verify: dict = field(default_factory=dict)            # word_id -> {"checks": [...], "ok": int}
    interventions_done: set = field(default_factory=set)
    meta: dict = field(default_factory=dict)
    part_id: int | None = None
    label: str = ""


# ---------------------------------------------------------------- oturum başlatma
MODE_LABELS = {"daily": "Tekrarlar", "review": "Tekrarlar", "learn": "Yeni kelimeler", "quick": "Hızlı tekrar",
               "hard": "Zor kelimeler", "weekly": "Haftalık YDS testi", "final": "Son hafta turu", "verify": "Doğrulama"}


def start(mode: str = "daily", device: str = "desktop", limit: int | None = None,
          part_id: int | None = None, part_ids: list[int] | None = None) -> dict:
    """Oturum. 'daily' artık yalnızca vadesi gelen tekrarlardır; yeni kelimeler en fazla 15'lik partlarla öğrenilir
    (tekrar yoksa 'daily' doğrudan sıradaki partı açar). 'part_test' / 'quick' + part_ids: seçilen partlarla test."""
    from . import parts as P
    from . import planner
    now = config.now_utc()
    sid = uuid.uuid4().hex[:16]
    plan = planner.today_plan()
    if mode == "daily" and plan.get("phase") == "final":
        mode = "final"
    if mode == "daily" and not due_reviews(plan.get("review_cap")) and not distinguish_tasks(limit=1):
        nxt = P.next_part(create_new=True)
        if nxt:
            mode, part_id = "part", nxt["id"]
    if mode == "part" and part_id is None:
        nxt = P.next_part(create_new=plan.get("phase") != "final")
        part_id = nxt["id"] if nxt else None
    s = Session(id=sid, mode=mode, device=device, started=now, day=config.day_str())
    s.label = MODE_LABELS.get(mode, "")
    s.arms = strategy.begin_session(sid) if mode in ("daily", "learn", "part") else {}
    s.pack_size = int(strategy.session_value(s.arms, "pack_size", db.get_setting("pack_size", 5)))
    s.meta["plan"] = {k: plan.get(k) for k in ("reviews_planned", "new_planned", "minutes", "phase")}
    if mode in ("daily", "review"):
        s.reviews = due_reviews(plan.get("review_cap"))
        s.extra_tasks += distinguish_tasks(limit=3)
    if mode == "learn" and plan.get("phase") != "final":
        n_new = limit or max(0, int(plan.get("new_planned", 0)) - new_done_today())
        s.new_words = pick_new_words(n_new)
    if mode == "part" and part_id:
        p = P.get(int(part_id))
        if p:
            s.part_id = p["id"]
            s.label = f"Part {p['no']}" + (f" · {p['title']}" if p.get("title") else "")
            s.meta["part"] = {"id": p["id"], "no": p["no"], "total": p["total"], "title": p.get("title")}
            s.new_words = P.remaining_words(p["id"])
    if mode in ("part_test", "quick") and part_ids:
        ids = P.test_words([int(i) for i in part_ids])
        s.rng.shuffle(ids)
        s.reviews = ids[: limit] if limit else ids
        nos = [r["no"] for r in db.q(f"SELECT no FROM parts WHERE id IN ({','.join('?' * len(part_ids))}) ORDER BY no",
                                     tuple(int(i) for i in part_ids))]
        s.meta["parts"] = nos
        s.label = ("Hızlı test" if mode == "quick" else "Test") + " · " + (f"Part {nos[0]}" if len(nos) == 1 else f"{len(nos)} part")
        s.lives, s.speed_limit = 3, 6000
    elif mode == "quick":
        s.reviews = quick_words(limit or 60)
        s.lives = 3
        s.speed_limit = 6000
    if mode == "hard":
        s.reviews = hard_words(limit or 30)
    if mode == "weekly":
        from . import weekly
        s.reviews = weekly.test_words(limit or 40)
        s.meta["weekly"] = True
        qs = weekly.osym_questions_for(s.reviews)
        s.rng.shuffle(qs)
        s.extra_tasks += [{"kind": "osym", "q": q, "ready_at": 0} for q in qs[:3]]
    if mode == "final":
        s.reviews = due_reviews(plan.get("review_cap")) + final_sweep_words(plan.get("sweep_target", 300))
    if mode == "verify":
        s.extra_tasks += verify_tasks(limit=limit or 30)
    db.x("INSERT INTO sessions(id, mode, device, started_at, day, meta) VALUES(?,?,?,?,?,?)",
         (sid, mode, device, config.iso(now), s.day, db.jdump(s.meta)))
    with _lock:
        SESSIONS[sid] = s
    return {"session_id": sid, "mode": mode, "reviews": len(s.reviews), "new": len(s.new_words),
            "extra": len(s.extra_tasks), "plan": s.meta["plan"], "label": s.label, "part": s.meta.get("part")}


def get(sid: str) -> Session | None:
    with _lock:
        return SESSIONS.get(sid)


def risk_order(rows: list[dict]) -> list[dict]:
    now = config.now_utc()
    params = C.active_params()
    from . import fsrs_engine as fe
    for r in rows:
        if r.get("stability") and r.get("last_review"):
            r["_r"] = fe.retrievability(params, r["stability"], config.parse_iso(r["last_review"]), now)
        else:
            r["_r"] = 0.0
    rows.sort(key=lambda r: (r["state"] != 3, r["_r"], -(r.get("priority") or 0)))
    return rows


def due_reviews(cap: int | None = None) -> list[int]:
    today = config.day_str()
    exam = db.get_setting("exam_date")
    rows = db.q("""SELECT c.word_id, c.state, c.stability, c.last_review, c.due, w.priority
                   FROM cards c JOIN words w ON w.id=c.word_id
                   WHERE w.status='active' AND c.state IN (2,3) AND c.due_day IS NOT NULL AND c.due_day<=?
                     AND c.due_day < ?""", (today, exam))
    # yeniden öğrenme (dakika vadeli) kartları yalnızca vakti gelince (30 dk tolerans)
    soon = config.iso(config.now_utc() + timedelta(minutes=30))
    rows = [r for r in rows if r["state"] == 2 or (r["due"] or "") <= soon]
    rows = risk_order(rows)
    ids = [r["word_id"] for r in rows]
    if cap is not None and cap >= 0:
        ids = ids[:cap]
    return ids


def new_done_today() -> int:
    return int(db.val("SELECT COUNT(*) FROM cards WHERE introduced_at IS NOT NULL AND introduced_at>=?",
                      (config.iso(config.day_start_utc(config.study_day())),), default=0))


def recent_unsettled() -> set[int]:
    rows = db.q("""SELECT word_id FROM cards WHERE introduced_at IS NOT NULL AND
                   (stage < 4 OR stability IS NULL OR stability < 5) AND introduced_at >= ?""",
                (config.iso(config.now_utc() - timedelta(days=10)),))
    return {r["word_id"] for r in rows}


def confusable_map(ids: set[int] | None = None) -> dict[int, set[int]]:
    rows = db.q("SELECT word_a, word_b, kind FROM confusables WHERE kind!='aile'")
    m: dict[int, set[int]] = {}
    for r in rows:
        m.setdefault(r["word_a"], set()).add(r["word_b"])
        m.setdefault(r["word_b"], set()).add(r["word_a"])
    return m


def pick_new_words(n: int, exclude: set[int] | None = None, include_probable: bool = False) -> list[int]:
    """Öncelik sırasıyla; karışabilir kelimeler aynı pakete / yerleşmemiş eşleriyle birlikte gelmez.

    Bir parta girmiş kelime yeniden seçilmez (part oturumu onu kaldığı yerden sürdürür). `include_probable`:
    seviye testinde 'muhtemelen biliyor' denen kelimeler de alınır (partta 4 kontrolle doğrulanırlar).
    """
    if n <= 0:
        return []
    probable = "" if include_probable else "AND (c.known_status IS NULL OR c.known_status!='probable')"
    # yarım kalan tanıtımlar da alınır: kart gösterilip oturum hiç adım yapılmadan kapandıysa kelime askıda kalmasın
    rows = db.q(f"""SELECT c.word_id, c.known_status FROM cards c JOIN words w ON w.id=c.word_id
                    WHERE w.status='active' AND c.state=0 AND (c.introduced_at IS NULL OR c.introduced_at < ?)
                      {probable} AND NOT EXISTS (SELECT 1 FROM part_words pw WHERE pw.word_id=c.word_id)
                    ORDER BY w.order_index LIMIT ?""", (config.iso(config.now_utc() - ORPHAN_AFTER), n * 4 + 40))
    conf = confusable_map()
    blocked = recent_unsettled()
    chosen: list[int] = []
    deferred: list[int] = []
    exclude = exclude or set()
    for r in rows:
        wid = r["word_id"]
        if wid in exclude:
            continue
        partners = conf.get(wid, set())
        if partners & blocked or partners & set(chosen):
            deferred.append(wid)
            continue
        chosen.append(wid)
        if len(chosen) >= n:
            break
    # yeterli değilse ertelenenlerden, aynı pakete düşmeyecek şekilde ekle
    if len(chosen) < n:
        for wid in deferred:
            if len(chosen) >= n:
                break
            chosen.append(wid)
    return reorder_packs(chosen, conf, 5)


def reorder_packs(ids: list[int], conf: dict[int, set[int]], pack: int) -> list[int]:
    """Karışabilir eşler aynı 5'li pakete düşmesin diye sırayı hafifçe kaydırır."""
    out: list[int] = []
    pending = list(ids)
    while pending:
        cur_pack_start = (len(out) // pack) * pack
        cur = set(out[cur_pack_start:])
        for i, wid in enumerate(pending):
            if not (conf.get(wid, set()) & cur):
                out.append(pending.pop(i))
                break
        else:
            out.append(pending.pop(0))
    return out


def quick_words(n: int) -> list[int]:
    rows = db.q("""SELECT c.word_id, c.state, c.stability, c.last_review, c.due, w.priority FROM cards c
                   JOIN words w ON w.id=c.word_id WHERE w.status='active' AND c.stage>=2 AND c.state>=1""")
    rows = risk_order(rows)
    weak = rows[: n // 2]
    rest = rows[n // 2:]
    random.shuffle(rest)
    ids = [r["word_id"] for r in weak + rest[: n - len(weak)]]
    random.shuffle(ids)
    return ids


def hard_words(n: int) -> list[int]:
    rows = db.q("""SELECT c.word_id FROM cards c JOIN words w ON w.id=c.word_id
                   WHERE w.status='active' AND c.state>=1
                   ORDER BY c.flag_hard DESC, (c.wrong_total*1.0 + c.lapses*2.0) DESC, c.difficulty DESC LIMIT ?""", (n,))
    return [r["word_id"] for r in rows]


def final_sweep_words(n: int) -> list[int]:
    """Son hafta: sınav öncesi pencerede henüz gözden geçirilmemiş kelimeler (en riskli önce)."""
    win = C.exam_window()
    start = config.iso(config.day_start_utc(win.final_start))
    rows = db.q("""SELECT c.word_id, c.state, c.stability, c.last_review, c.due, w.priority FROM cards c
                   JOIN words w ON w.id=c.word_id
                   WHERE w.status='active' AND c.state>=1 AND (c.last_review IS NULL OR c.last_review < ?)""", (start,))
    rows = risk_order(rows)
    return [r["word_id"] for r in rows[:n]]


def distinguish_tasks(limit: int = 3) -> list[dict]:
    """İki kelime de oturduysa (merdiven ≥4, S ≥ 5 gün) 'ayırt etme' alıştırması."""
    rows = db.q("""SELECT f.word_a, f.word_b, f.kind, f.score FROM confusables f
                   JOIN cards a ON a.word_id=f.word_a JOIN cards b ON b.word_id=f.word_b
                   WHERE f.kind IN ('yazılış','yazılış+anlam','kullanıcı') AND f.distinguished_at IS NULL AND a.stage>=4 AND b.stage>=4
                     AND a.stability>=5 AND b.stability>=5
                   ORDER BY (f.kind LIKE 'yazılış%') DESC, f.score DESC LIMIT ?""", (limit * 3,))
    # kullanıcının gerçekten karıştırdığı çiftler önce
    confused = db.q("""SELECT word_id a, confused_with b, COUNT(*) n FROM events
                       WHERE confused_with IS NOT NULL AND ts >= ? GROUP BY word_id, confused_with
                       ORDER BY n DESC LIMIT ?""", (config.iso(config.now_utc() - timedelta(days=14)), limit))
    tasks = []
    seen = set()
    for r in confused:
        key = tuple(sorted((r["a"], r["b"])))
        if key in seen:
            continue
        ca, cb = C.get(key[0]), C.get(key[1])
        if ca and cb and (ca["stage"] or 0) >= 3 and (cb["stage"] or 0) >= 3:
            tasks.append({"kind": "distinguish", "a": key[0], "b": key[1], "ready_at": 0})
            seen.add(key)
    for r in rows:
        if len(tasks) >= limit:
            break
        key = (r["word_a"], r["word_b"])
        if key in seen:
            continue
        tasks.append({"kind": "distinguish", "a": key[0], "b": key[1], "ready_at": 0})
        seen.add(key)
    return tasks[:limit]


def verify_tasks(limit: int = 12) -> list[dict]:
    rows = db.q("""SELECT c.word_id FROM cards c JOIN words w ON w.id=c.word_id
                   WHERE w.status='active' AND c.known_status='probable' AND c.state=0
                   ORDER BY w.order_index LIMIT ?""", (limit,))
    return [{"kind": "verify", "word_id": r["word_id"], "ready_at": 0} for r in rows]


# ---------------------------------------------------------------- sonraki soru
def choose_review_exercise(s: Session, word_id: int) -> str:
    card = C.get(word_id) or {}
    stage = int(card.get("stage") or 0)
    if s.mode == "quick":
        return "speed"
    if s.mode == "weekly":
        return s.rng.choices(["cloze", "synonym", "context", "typing"], weights=[0.5, 0.2, 0.2, 0.1])[0]
    if s.mode == "final":
        if (card.get("lapses") or 0) > 1 or (card.get("stability") or 0) < 7:
            return "cloze"
        return "speed"
    if s.mode == "hard":
        return s.rng.choice(["typing", "cloze", "mcq_tr_en"])
    if stage < len(TEST_RUNGS):
        return _test_type(stage)
    if card.get("flag_hard") and card.get("last_intervention_at"):
        # inatçı kelime müdahalesi: bir süre üretim ve bağlam alıştırmaları
        return s.rng.choice(["typing", "cloze", "context"])
    if stage in REVIEW_RUNG_FOR_STAGE:
        return REVIEW_RUNG_FOR_STAGE[stage]
    # merdiven tamam: uyarlanabilir karışım
    mix = dict(strategy.exercise_mix(s.arms))
    recent_lapse = (card.get("lapses") or 0) > 0 and (card.get("stability") or 0) < 3
    if recent_lapse:
        mix = {"mcq_tr_en": 0.4, "context": 0.3, "cloze": 0.3}
    if mix.get("mcq_en_tr") and db.get_setting("listen_exercises", True):
        # tanıma payının yarısı 'dinle ve seç': kelimeyi duymak hatırlamayı destekler
        half = mix["mcq_en_tr"] / 2
        mix["mcq_en_tr"], mix["listen"] = half, mix.get("listen", 0) + half
    has_pair = any(p["kind"] in ("yazılış", "yazılış+anlam", "kullanıcı") for p in W.confusable_partners(word_id))         if "distinguish" in mix else False
    keys = [k for k in mix if k != "distinguish" or has_pair]
    weights = [mix[k] for k in keys]
    return s.rng.choices(keys, weights=weights)[0]


def _learn_type(rung: int) -> str:
    """Oturum içi basamak (öğretme + sınama)."""
    t = LEARN_RUNGS[min(rung, len(LEARN_RUNGS) - 1)]
    if t == "listen" and not db.get_setting("listen_exercises", True):
        return "mcq_en_tr"   # sesli ortam yoksa dinleme yerine okumalı test
    return t


def _test_type(stage: int) -> str:
    """Kartın merdiven basamağına (stage) karşılık gelen sınama türü (oturum dışı tekrarlar için)."""
    return _learn_type(len(TEACH_RUNGS) + min(max(stage, 0), len(TEST_RUNGS) - 1))


def next_item(sid: str) -> dict:
    s = get(sid)
    if not s:
        return {"type": "error", "message": "Oturum bulunamadı"}
    with _lock:
        item = _next(s)
    if item is None:
        return finish(sid)
    return item


def _register(s: Session, payload: dict, secret: dict, task: dict) -> dict:
    payload["session_progress"] = progress(s)
    s.pending[payload["token"]] = {"secret": secret, "task": task, "payload": payload, "shown_at": time.time()}
    return payload


def _next(s: Session) -> dict | None:
    if s.finished:
        return None
    if s.mode == "quick" and s.lives <= 0:
        return None
    if s.max_items and s.stats["answers"] >= s.max_items:
        return None
    level = strategy.distractor_level(s.arms)
    # 1) yeniden sorulacaklar (vakti gelen)
    for i, rq in enumerate(s.requeue):
        if rq["ready_at"] <= s.answer_count:
            s.requeue.pop(i)
            return _requeue_item(s, rq, level)
    # 2) müdahale / ayırt etme / doğrulama görevleri (tekrarların arasına serpiştirilir)
    if s.extra_tasks and (s.review_pos >= len(s.reviews) or s.answer_count % 6 == 5):
        item = _extra_item(s, s.extra_tasks.pop(0), level)
        if item:
            return item
    # 3) vadesi gelen tekrarlar
    while s.review_pos < len(s.reviews):
        wid = s.reviews[s.review_pos]
        s.review_pos += 1
        if wid in s.seen_review and s.mode not in ("quick",):
            continue
        s.seen_review.add(wid)
        typ = choose_review_exercise(s, wid)
        kw = {}
        if typ == "speed":
            kw["time_limit_ms"] = s.speed_limit
        if typ == "distinguish":
            partners = [p for p in W.confusable_partners(wid) if p["kind"] in ("yazılış", "yazılış+anlam", "kullanıcı")]
            if partners:
                kw["other"] = partners[0]["id"]
        p, sec = X.build(typ, wid, level, s.rng, **kw)
        return _register(s, p, sec, {"kind": "review", "word_id": wid, "requested": typ})
    # 4) yeni kelimeler (paket)
    item = _pack_item(s, level)
    if item:
        return item
    # 5) bekleyen requeue'lar (aralığı dolmamış olsa da)
    if s.requeue:
        s.requeue.sort(key=lambda r: r["ready_at"])
        rq = s.requeue.pop(0)
        return _requeue_item(s, rq, level)
    # 6) part sonu pekiştirme turu ve kalan ek görevler
    _queue_consolidation(s)
    while s.extra_tasks:
        item = _extra_item(s, s.extra_tasks.pop(0), level)
        if item:
            return item
    return None


def _extra_item(s: Session, t: dict, level: float) -> dict | None:
    if t["kind"] == "consolidate":
        return _consolidate_item(s, t, level)
    if t["kind"] == "verify":
        return _verify_item(s, t["word_id"])
    if t["kind"] == "osym":
        p, sec = X.osym(t["q"])
        return _register(s, p, sec, {"kind": "review", "word_id": sec["word_id"], "osym": True})
    if t["kind"] == "distinguish":
        built = X.distinguish(t["a"], t["b"], s.rng)
        if built:
            p, sec = built
            return _register(s, p, sec, {"kind": "distinguish", "word_id": sec["word_id"], "pair": [t["a"], t["b"]]})
    return None


def _requeue_item(s: Session, rq: dict, level: float) -> dict:
    typ = rq.get("type")
    if typ == "intervention":
        return _intervention_item(s, rq)
    if typ == "verify":
        return _verify_item(s, rq["word_id"])
    if typ == "reintro":
        p, sec = X.intro(rq["word_id"], "association")
        p["reintro"] = True
        p["type_label"] = "Tekrar bakalım"
        return _register(s, p, sec, {"kind": "reintro", "word_id": rq["word_id"]})
    p, sec = X.build(typ, rq["word_id"], level, s.rng)
    return _register(s, p, sec, {"kind": rq.get("reason", "relearn"), "word_id": rq["word_id"],
                                 "tries": rq.get("tries", 1)})


def _fill_pack(s: Session) -> None:
    while len([l for l in s.pack if not l.done]) == 0 and s.new_pos < len(s.new_words):
        s.pack = []
        size = s.pack_size
        pre_tiers = s.meta.get("pretest_tiers")
        if pre_tiers is None:
            from . import placement
            pre_tiers = s.meta["pretest_tiers"] = list(placement.pretest_tiers())
            s.meta["tier_map"] = placement.tier_map() if pre_tiers else {}
        while len(s.pack) < size and s.new_pos < len(s.new_words):
            l = LearnState(word_id=s.new_words[s.new_pos])
            s.new_pos += 1
            card = C.get(l.word_id) or {}
            stage = int(card.get("stage") or 0)
            if card.get("introduced_at") and int(card.get("state") or 0) >= 1 and 0 < stage < len(TEST_RUNGS):
                # yarım kalan merdiven (part kaldığı yerden): önce kelime yeniden öğretilir (hatırlatma kartı), sonra
                # kolaydan zora sürer — kaldığı sınama basamağının iki gerisinden (ör. 3'te kalan: test → boşluk → yazma)
                l.rung, l.resume = len(TEACH_RUNGS) + max(0, stage - 2), True
            elif card.get("known_status") == "probable" or (
                    pre_tiers and card.get("known_status") is None and s.meta["tier_map"].get(l.word_id) in pre_tiers):
                # ön test: seviye testine göre büyük olasılıkla biliyorsun — öğretmeden önce 4 kontrolle doğrula
                l.pretest = "pending"
                s.requeue.append({"word_id": l.word_id, "type": "verify", "ready_at": s.answer_count, "pretest": True})
            s.pack.append(l)


def _pack_item(s: Session, level: float) -> dict | None:
    _fill_pack(s)
    active = [l for l in s.pack if not l.done]
    if not active:
        return None
    waiting = _match_waiting(s)
    if waiting:
        item = _match_item(s, waiting)
        if item:
            return item
        return _pack_item(s, level)        # eşleştirme kurulamadı (tek kelime): basamak atlandı
    ready = [l for l in active if l.introduced and l.ready_at <= s.answer_count and l.rung != MATCH_RUNG]
    if ready:
        ready.sort(key=lambda l: (l.rung, l.ready_at))
        return _learn_item(s, ready[0], level)
    fresh = [l for l in active if not l.introduced and l.pretest != "pending"]
    if fresh:
        l = fresh[0]
        l.introduced = True
        l.ready_at = s.answer_count + 1
        mem_kind = strategy.assign_mem_kind(l.word_id)
        p, sec = X.intro(l.word_id, mem_kind)
        if l.resume:   # daha önce başlanmış kelime: yeni sayılmaz, kart "hatırlayalım" olarak gelir
            p["reintro"] = True
            p["type_label"] = "Hatırlayalım"
        else:
            C.mark_introduced(l.word_id, config.now_utc())
            strategy.note_learning(l.word_id, s.arms)
            s.stats["new"] += 1
        p["pack"] = {"index": [x.word_id for x in s.pack].index(l.word_id) + 1, "size": len(s.pack)}
        return _register(s, p, sec, {"kind": "intro", "word_id": l.word_id, "resume": l.resume})
    # hepsi tanıtıldı ama aralık dolmadı: en yakın olanı sor
    active = [l for l in active if l.introduced and l.rung != MATCH_RUNG]
    if not active:
        return None  # ön testler / eşleştirme bekleniyor (requeue'dan sunulur)
    active.sort(key=lambda l: l.ready_at)
    return _learn_item(s, active[0], level)


def _learn_item(s: Session, l: LearnState, level: float) -> dict:
    typ = _learn_type(l.rung)
    kw = {"n_options": 4 if typ in ("listen", "syn_pick") else 5}
    if typ == "syn_pick":
        # çeldiriciler az önce öğrenilen paket kelimeleri (ayırt etmeyi de çalıştırır)
        kw["pool_ids"] = [x.word_id for x in s.pack if x.word_id != l.word_id and x.introduced]
    p, sec = X.build(typ, l.word_id, max(0.2, level - 0.25), s.rng, **kw)
    return _register(s, p, sec, {"kind": "learn", "word_id": l.word_id, "rung": l.rung})


def _match_waiting(s: Session) -> list[LearnState] | None:
    """Paketin bütün kelimeleri tanıtılıp 'bak·kapat·yaz'ı geçtiyse eşleştirmeyi bekleyenler (yoksa None)."""
    act = [l for l in s.pack if not l.done and l.pretest != "pending"]
    waiting = [l for l in act if l.introduced and l.rung == MATCH_RUNG]
    if not waiting or any((not l.introduced) or l.rung < MATCH_RUNG for l in act):
        return None
    return waiting


def _match_item(s: Session, waiting: list[LearnState]) -> dict | None:
    ids = [l.word_id for l in waiting]
    fillers: list[int] = []
    if len(ids) < 4:
        # az kelimeli pakette önceden öğrenilenlerle tamamla (puan almazlar); karışabilir/aynı anlamlılar girmez
        conf = confusable_map()
        idx = W.index()["items"]
        pool = [w for w in s.stats["learned"] if w not in ids] + [
            r["word_id"] for r in db.q("SELECT word_id FROM cards WHERE stage>=1 AND word_id NOT IN (%s) "
                                       "ORDER BY RANDOM() LIMIT 12" % ",".join(map(str, ids)))]
        for w in pool:
            if len(ids) + len(fillers) >= 4:
                break
            c = idx.get(w)
            if not c or w in fillers or any(w in conf.get(t, set()) or (t in idx and D.related(idx[t], c)) for t in ids):
                continue
            fillers.append(w)
    if len(ids) + len(fillers) < 2:
        for l in waiting:                  # tek çiftlik eşleştirme anlamsız: bu katmanı atla
            l.rung += 1
        return None
    p, sec = X.match(ids, fillers, s.rng)
    return _register(s, p, sec, {"kind": "match", "word_id": ids[0], "word_ids": ids})


def _verify_item(s: Session, word_id: int) -> dict:
    v = s.verify.setdefault(word_id, {"checks": list(VERIFY_CHECKS), "ok": 0, "done": 0})
    typ = v["checks"][min(v["done"], len(v["checks"]) - 1)]
    p, sec = X.build(typ, word_id, 0.6, s.rng)
    p["verify"] = True
    p["type_label"] = f"Doğrulama {min(v['done'] + 1, len(v['checks']))}/{len(v['checks'])} — " + p.get("type_label", "")
    return _register(s, p, sec, {"kind": "verify", "word_id": word_id})


def _intervention_item(s: Session, rq: dict) -> dict:
    from . import interventions as I
    p = I.payload(rq["intervention_id"])
    p["token"] = uuid.uuid4().hex[:12]
    sec = {"type": "intervention", "word_id": rq["word_id"], "intervention_id": rq["intervention_id"]}
    return _register(s, p, sec, {"kind": "intervention", "word_id": rq["word_id"]})


def progress(s: Session) -> dict:
    total_new = len(s.new_words)
    learned_in_session = sum(1 for l in s.pack if l.done) + max(0, s.new_pos - len(s.pack))
    rv_total = len(s.reviews)
    done = s.review_pos + learned_in_session
    total = rv_total + total_new + len(s.extra_tasks)
    fraction = (done / total) if total else 1.0
    if s.mode == "part" and total_new:
        # part çubuğu her cevapta ilerler: kelime başına tanıtım + 4 basamak (ya da 4 kontrol)
        units = float(max(0, s.new_pos - len(s.pack)))
        for l in s.pack:
            if l.done:
                units += 1
            elif l.pretest == "pending":
                units += s.verify.get(l.word_id, {}).get("done", 0) / (len(VERIFY_CHECKS) + 1)
            else:
                units += (l.rung + (1 if l.introduced else 0)) / (len(LEARN_RUNGS) + 1)
        fraction = min(1.0, units / total_new)
    return {"reviews_done": s.review_pos, "reviews_total": rv_total, "new_done": learned_in_session,
            "new_total": total_new, "answers": s.stats["answers"], "correct": s.stats["correct"],
            "fraction": fraction, "lives": s.lives if s.mode == "quick" else None,
            "streak": s.stats["streak"], "label": s.label}


# ---------------------------------------------------------------- cevap
def answer(sid: str, token: str, payload: dict) -> dict:
    s = get(sid)
    if not s:
        return {"error": "Oturum bulunamadı"}
    with _lock:
        pend = s.pending.pop(token, None)
    if not pend:
        return {"error": "Soru bulunamadı (zaten cevaplandı)"}
    secret, task, shown = pend["secret"], pend["task"], pend["payload"]
    now = config.now_utc()
    typ = secret["type"]
    s.active_ms = max(s.active_ms, int(payload.get("session_active_ms") or 0))
    if typ == "intro":
        return _answer_intro(s, task, secret, shown, payload, now)
    if typ == "intervention":
        from . import interventions as I
        I.mark_shown(secret["intervention_id"])
        s.answer_count += 1
        return {"ok": True, "next": next_item(sid)}
    if typ == "match":
        return _answer_match(s, task, secret, payload, now)
    # ---- değerlendirme
    dont_know = bool(payload.get("dont_know"))
    timeout = bool(payload.get("timeout"))
    if typ in ("typing", "tiles", "look_write"):
        g = G.grade_text(secret, payload.get("text"), dont_know=dont_know)
    else:
        ai = payload.get("choice")
        g = G.grade_choice(secret, None if ai is None else int(ai), dont_know=dont_know, timeout=timeout)
    G.refine_error(secret["word_id"], typ, g)
    first_key = payload.get("first_key_ms")
    total = payload.get("total_ms")
    hints = int(payload.get("hints") or 0)
    latency = R.latency_for(typ, first_key, total, secret.get("n_words") or shown.get("n_words") or 0)
    rating_val, speed_cls = R.auto_rating(typ, g.correct, g.result, latency, hints)
    if g.correct and speed_cls == "yavaş" and not g.error_type:
        g.error_type = "yavaş doğru"
    kind = task["kind"]
    wid = secret["word_id"]
    card = C.get(wid) or {}
    stage_before = int(card.get("stage") or 0)
    stage_after = stage_before
    feed_fsrs = True
    if kind == "verify" or typ in TEACH_RUNGS:
        feed_fsrs = False   # doğrulama ve öğretme katmanları (bak·kapat·yaz, eş anlamlısından bul) sınama sayılmaz
    if s.mode in ("quick", "part_test"):
        # ek pratik: son 12 saatte tekrar edilmiş kartın zamanlamasını bozma
        last = card.get("last_review")
        if last and (now - config.parse_iso(last)) < timedelta(hours=12):
            feed_fsrs = False
        if s.mode == "quick":
            rating_val = min(rating_val, 3)
    fsrs_res = None
    if feed_fsrs:
        fsrs_res = C.apply_review(wid, rating_val, now)
    # ---- merdiven / kuyruk
    learned_now = False
    if kind == "learn":
        l = next((x for x in s.pack if x.word_id == wid), None)
        if l:
            if g.correct:
                l.rung += 1
                tests_done = l.rung - len(TEACH_RUNGS)
                if tests_done > 0:
                    stage_after = max(stage_before, tests_done)
                l.ready_at = s.answer_count + 2 + min(l.rung, 5)
                if l.rung >= len(LEARN_RUNGS):
                    l.done = True
                    learned_now = True
                    s.stats["learned"].append(wid)
                    s.meta.setdefault("ladder_done", []).append(wid)
            else:
                l.errors += 1
                l.ready_at = s.answer_count + 3
                if l.errors >= 3 and l.rung - 1 >= len(TEACH_RUNGS):   # sınamadan öğretme katmanına geri düşmez
                    l.rung -= 1
                if l.errors in (2, 4):
                    # ikinci/dördüncü hatada tanıtım kartını yeniden göster
                    s.requeue.append({"word_id": wid, "type": "reintro", "ready_at": s.answer_count + 1})
    elif kind in ("review", "relearn"):
        if g.correct:
            n_test = len(TEST_RUNGS)
            rung_type = REVIEW_RUNG_FOR_STAGE.get(stage_before) if stage_before >= n_test else _test_type(stage_before)
            # istenen basamak türü kurulamadıysa (ör. örnek cümle yok) yedek tür de basamağı sayar
            if s.mode not in ("quick",) and stage_before < C.STAGE_MAX and \
                    (typ == rung_type or task.get("requested") == rung_type):
                stage_after = stage_before + 1
        else:
            if stage_before > len(TEST_RUNGS):   # oturum içi merdivenin altına düşürme
                stage_after = stage_before - 1
            tries = task.get("tries", 0)
            if tries < 3 and s.mode not in ("quick", "weekly"):
                s.requeue.append({"word_id": wid, "type": "mcq_en_tr" if tries == 0 else "mcq_tr_en",
                                  "ready_at": s.answer_count + 4, "reason": "relearn", "tries": tries + 1})
        if kind == "review":
            s.stats["reviews"] += 1
    elif kind == "learn_retry":
        pass
    elif kind == "consolidate":
        # part sonu pekiştirme: unutulduysa oturum bitmeden bir kez daha (TR→EN), kart yarın zaten tekrar gelir
        if not g.correct:
            s.requeue.append({"word_id": wid, "type": "mcq_tr_en", "ready_at": s.answer_count + 3,
                              "reason": "relearn", "tries": 1})
    elif kind == "distinguish":
        pair = task.get("pair") or []
        if len(pair) == 2 and g.correct:
            a, b = sorted(pair)
            db.x("UPDATE confusables SET distinguished_at=? WHERE word_a=? AND word_b=?", (config.iso(now), a, b))
    elif kind == "verify":
        v = s.verify.setdefault(wid, {"checks": list(VERIFY_CHECKS), "ok": 0, "done": 0})
        v["done"] += 1
        fastish = speed_cls in ("çok hızlı", "hızlı", "normal") and hints == 0
        if g.correct and fastish:
            v["ok"] += 1
        if v["done"] < len(v["checks"]) and g.correct:
            s.requeue.insert(0, {"word_id": wid, "type": "verify", "ready_at": s.answer_count + 1})
        else:
            l = next((x for x in s.pack if x.word_id == wid), None)
            if v["ok"] >= len(v["checks"]):
                C.init_known(wid, now)
                stage_after = C.STAGE_MAX
                learned_now = True
                s.stats["learned"].append(wid)
                verdict = "verified"
                if l:
                    l.done = True
                    l.pretest = "passed" if l.pretest == "pending" else l.pretest
            else:
                db.x("UPDATE cards SET known_status='failed' WHERE word_id=?", (wid,))
                verdict = "failed"
                if l and l.pretest == "pending":
                    # ön testi geçemedi: tanıtım kartıyla normal öğrenme
                    l.pretest = "failed"
                    l.done = False
                elif l:
                    # tanıtım kartında 'biliyorum' denmişti: bu paketle normal öğrenmeye devam
                    l.done, l.introduced, l.rung, l.ready_at = False, True, 0, s.answer_count + 1
                    C.mark_introduced(wid, now)
                    s.stats["new"] += 1
            g.detail["verify_result"] = verdict
    if stage_after != stage_before:
        C.set_stage(wid, stage_after, now)
    if learned_now and kind == "learn":
        C.cap_first_review(wid, now)   # yeni öğrenilen kelimenin ilk tekrarı en geç ertesi gün
    # ---- istatistik
    s.answer_count += 1
    s.stats["answers"] += 1
    if g.correct:
        s.stats["correct"] += 1
        s.stats["streak"] += 1
        s.stats["best_streak"] = max(s.stats["best_streak"], s.stats["streak"])
        s.stats["xp"] += {1: 0, 2: 6, 3: 10, 4: 14}.get(rating_val, 10)
    else:
        s.stats["errors"] += 1
        s.stats["streak"] = 0
    if s.mode == "quick":
        if g.correct:
            s.speed_limit = max(2500, s.speed_limit - 250)
        else:
            s.lives -= 1
            s.speed_limit = min(6000, s.speed_limit + 500)
    norm = latency / max(1.0, R.thresholds(typ).fast)
    s.latencies.append((time.time(), norm, g.correct))
    # ---- olay kaydı
    minute = (s.active_ms / 60000.0) if s.active_ms else (now - s.started).total_seconds() / 60.0
    extra = {"latency": round(latency), "speed": speed_cls, "kind": kind, "rung": task.get("rung"),
             "example_id": secret.get("example_id"), "n_words": secret.get("n_words"),
             "distractor_level": strategy.distractor_level(s.arms), "detail": g.detail or None,
             "options": shown.get("options"), "fed_fsrs": feed_fsrs}
    direction = ("en_tr" if typ in G.EN_TR_TYPES else ("tr_en" if typ in G.PRODUCTION_TYPES else
                 ("context" if typ in G.CONTEXT_TYPES else typ)))
    eid = db.x("""INSERT INTO events(ts, day, session_id, word_id, mode, exercise, direction, prompt, answer, expected,
                       correct, result, first_key_ms, total_ms, hints, rating, error_type, confused_with,
                       stage_before, stage_after, fsrs_before, fsrs_after, r_before, elapsed_days, device,
                       minute_in_session, extra)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
               (config.iso(now), s.day, s.id, wid, "learn" if kind in ("learn", "consolidate") else s.mode, typ, direction,
                db.jdump({"prompt": shown.get("prompt"), "sentence": shown.get("sentence")}),
                g.answer_text, g.expected_text, 1 if g.correct else 0, g.result,
                first_key, total, hints, rating_val if feed_fsrs else None, None if g.correct else g.error_type,
                g.confused_with, stage_before, stage_after,
                db.jdump(fsrs_res["before"]) if fsrs_res and fsrs_res["before"] else None,
                db.jdump(fsrs_res["after"]) if fsrs_res else None,
                fsrs_res["r_before"] if fsrs_res else None, fsrs_res["elapsed_days"] if fsrs_res else None,
                s.device, round(minute, 2), db.jdump(extra)))
    if g.correct and g.error_type in ("yavaş doğru", "yazım hatası", "biçim"):
        db.x("UPDATE events SET error_type=? WHERE id=?", (g.error_type, eid))
    s.last_event = {"id": eid, "word_id": wid, "correct": g.correct, "kind": kind, "stage_before": stage_before,
                    "fsrs_before": fsrs_res["before"] if fsrs_res else None, "lapse": bool(
                        fsrs_res and fsrs_res["before"] and fsrs_res["before"].get("state") == 2 and rating_val == 1),
                    "fed": feed_fsrs, "ts": time.time(), "task": task}
    db.x("UPDATE sessions SET n_answers=n_answers+1, n_correct=n_correct+?, active_ms=MAX(active_ms, ?) WHERE id=?",
         (1 if g.correct else 0, s.active_ms, s.id))
    strategy.record_outcome(wid, g.correct, speed_cls, kind, typ, now)
    if g.confused_with:
        from . import distractors
        distractors.clear_cache(wid)
    # ---- inatçı kelime müdahalesi
    if not g.correct:
        from . import interventions as I
        iv = I.maybe_trigger(wid)
        if iv and wid not in s.interventions_done:
            s.interventions_done.add(wid)
            s.requeue.append({"word_id": wid, "type": "intervention", "intervention_id": iv,
                              "ready_at": s.answer_count})
    fb = X.feedback_info(wid)
    res = {
        "correct": g.correct, "result": g.result, "expected": g.expected_text, "rating": rating_val,
        "rating_label": {1: "Tekrar", 2: "Zor", 3: "İyi", 4: "Kolay"}[rating_val], "speed": speed_cls,
        "error_type": None if g.correct else g.error_type, "stage_before": stage_before, "stage_after": stage_after,
        "learned_now": learned_now, "feedback": fb, "event_id": eid,
        "correct_index": secret.get("correct"), "answer_text": secret.get("answer") or secret.get("answer_text"),
        "due_day": fsrs_res["due_day"] if fsrs_res else None, "lives": s.lives if s.mode == "quick" else None,
        "verify_result": g.detail.get("verify_result"), "progress": progress(s),
        "fatigue": fatigue_hint(s), "xp": s.stats["xp"],
    }
    if g.confused_with:
        c = W.index()["items"].get(g.confused_with)
        if c:
            res["confused"] = {"display": c["display"], "meaning": c["short"]}
    # cevaplandığı anda doğru cevap sesli tekrar edilir (İngilizce): şıklı sorularda doğru şık, diğerlerinde hedef kelime
    say = None
    if typ in ("mcq_tr_en", "cloze", "osym", "synonym", "distinguish", "syn_pick"):
        ci, opts = secret.get("correct"), shown.get("options") or []
        if ci is not None and 0 <= ci < len(opts):
            say = str(opts[ci]).replace(" / ", ", ")
    elif typ in ("mcq_en_tr", "listen", "context", "typing", "tiles", "look_write"):
        say = secret.get("answer") or (W.index()["items"].get(wid) or {}).get("display")
    res["say"] = say
    if typ in ("cloze", "osym") or (typ == "distinguish" and shown.get("sentence")):
        # boşluk doldurmadan sonra her zaman 'gerçek cevap' paneli (çeviri + neden bu kelime); kullanıcı geçebilir
        try:
            res["explain"] = X.explain_cloze(secret, shown)
        except Exception:
            res["explain"] = None
    res["next"] = next_item(sid)
    return res


def _answer_match(s: Session, task: dict, secret: dict, payload: dict, now: datetime) -> dict:
    """Eşleştirme sonucu (kelime başına hata sayısı). Öğretme katmanıdır: FSRS'e işlenmez, kartın basamağı değişmez;
    2+ hata yapılan kelimenin tanıtım kartı yeniden gösterilir."""
    mistakes: dict[int, int] = {}
    for k, v in (payload.get("mistakes") or {}).items():
        try:
            mistakes[int(k)] = max(0, int(v))
        except (TypeError, ValueError):
            continue
    ids = task.get("word_ids") or [secret["word_id"]]
    total = payload.get("total_ms")
    per = int(total / len(ids)) if total else None
    minute = (s.active_ms / 60000.0) if s.active_ms else (now - s.started).total_seconds() / 60.0
    s.answer_count += 1
    n_ok = 0
    for wid in ids:
        m = mistakes.get(wid, 0)
        ok = m == 0
        n_ok += ok
        l = next((x for x in s.pack if x.word_id == wid), None)
        if l and not l.done and l.rung == MATCH_RUNG:
            l.rung += 1
            l.ready_at = s.answer_count + 1
            l.match_errors = m
            if m:
                l.errors += 1
            if m >= 2:
                s.requeue.append({"word_id": wid, "type": "reintro", "ready_at": s.answer_count + 1})
        st = int((C.get(wid) or {}).get("stage") or 0)
        db.x("""INSERT INTO events(ts, day, session_id, word_id, mode, exercise, direction, correct, result, total_ms,
                                   first_key_ms, stage_before, stage_after, device, minute_in_session, extra)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
             (config.iso(now), s.day, s.id, wid, "learn", "match", "match", 1 if ok else 0,
              "correct" if ok else "wrong", per, payload.get("first_key_ms"), st, st, s.device, round(minute, 2),
              db.jdump({"kind": "match", "mistakes": m, "fed_fsrs": False})))
        s.stats["answers"] += 1
        if ok:
            s.stats["correct"] += 1
            s.stats["xp"] += 6
        else:
            s.stats["errors"] += 1
    if n_ok == len(ids):
        s.stats["streak"] += 1
        s.stats["best_streak"] = max(s.stats["best_streak"], s.stats["streak"])
    else:
        s.stats["streak"] = 0
    db.x("UPDATE sessions SET n_answers=n_answers+?, n_correct=n_correct+?, active_ms=MAX(active_ms, ?) WHERE id=?",
         (len(ids), n_ok, s.active_ms, s.id))
    return {"ok": True, "correct": n_ok == len(ids), "result": "correct" if n_ok == len(ids) else "wrong",
            "say": None, "xp": s.stats["xp"], "progress": progress(s), "next": next_item(s.id)}


def _queue_consolidation(s: Session) -> bool:
    """Part sonu pekiştirme turu: bu oturumda merdiveni bitiren kelimeler karışık sırayla birer kez daha sorulur
    (öğrendikten 10-20 dk sonra hatırlamak unutmayı yavaşlatır). Dinle ve seç ile TR→EN dönüşümlü."""
    if s.meta.get("consolidated") or s.mode not in ("part", "learn"):
        return False
    if s.new_pos < len(s.new_words) or any(not l.done for l in s.pack) or s.requeue:
        return False
    s.meta["consolidated"] = True
    words = list(dict.fromkeys(s.meta.get("ladder_done") or []))
    if len(words) < 3:
        return False
    s.rng.shuffle(words)
    for i, w in enumerate(words):
        s.extra_tasks.append({"kind": "consolidate", "word_id": w, "type": "mcq_tr_en" if i % 2 else "listen"})
    return True


def _consolidate_item(s: Session, t: dict, level: float) -> dict:
    typ = _test_type(0) if t["type"] == "listen" else t["type"]
    p, sec = X.build(typ, t["word_id"], level, s.rng, n_options=4)
    p["type_label"] = "Pekiştirme turu · " + (p.get("type_label") or "")
    return _register(s, p, sec, {"kind": "consolidate", "word_id": t["word_id"]})


def _answer_intro(s: Session, task: dict, secret: dict, shown: dict, payload: dict, now: datetime) -> dict:
    wid = secret["word_id"]
    s.answer_count += 1
    known = bool(payload.get("already_known")) and task.get("kind") == "intro" and not task.get("resume")
    db.x("""INSERT INTO events(ts, day, session_id, word_id, mode, exercise, direction, correct, result, total_ms,
                               stage_before, stage_after, device, extra)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
         (config.iso(now), s.day, s.id, wid, "learn", "intro", "intro", None, "known_claim" if known else "seen",
          payload.get("total_ms"), 0, 0, s.device,
          db.jdump({"mem_kind": shown.get("mem_kind"), "mnemonic_id": secret.get("mnemonic_id"),
                    "example_id": secret.get("example_id")})))
    if known:
        # beyan doğrulanmadan kabul edilmez: dört farklı türde kontrol sorusu
        for l in s.pack:
            if l.word_id == wid:
                l.done = True
        s.stats["new"] -= 1
        db.x("UPDATE cards SET known_status='probable', introduced_at=NULL WHERE word_id=?", (wid,))
        item = _verify_item(s, wid)
        return {"ok": True, "next": item}
    return {"ok": True, "next": next_item(s.id)}


def override(sid: str, event_id: int) -> dict:
    """'Aslında biliyordum': son yanlışı düzelt (kayda geçer)."""
    s = get(sid)
    if not s or not s.last_event or s.last_event["id"] != event_id or s.last_event["correct"]:
        return {"ok": False, "message": "Yalnızca son yanlış cevap düzeltilebilir"}
    le = s.last_event
    if time.time() - le["ts"] > 300:
        return {"ok": False, "message": "Süre doldu"}
    wid = le["word_id"]
    now = config.now_utc()
    ev = db.q1("SELECT * FROM events WHERE id=?", (event_id,))
    if le["fed"]:
        C.restore(wid, le["fsrs_before"], le["stage_before"], was_wrong=True, was_lapse=le["lapse"])
        res = C.apply_review(wid, 2, now)
    else:
        res = None
    db.x("UPDATE events SET extra=json_set(COALESCE(extra,'{}'), '$.overridden', 1) WHERE id=?", (event_id,))
    db.x("""INSERT INTO events(ts, day, session_id, word_id, mode, exercise, direction, correct, result, rating,
                               stage_before, stage_after, fsrs_before, fsrs_after, device, override_of, extra)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
         (config.iso(now), s.day, s.id, wid, ev["mode"], ev["exercise"], ev["direction"], 1, "override",
          2 if res else None, ev["stage_before"], ev["stage_before"],
          db.jdump(le["fsrs_before"]) if le["fsrs_before"] else None, db.jdump(res["after"]) if res else None,
          s.device, event_id, db.jdump({"note": "aslında biliyordum"})))
    # oturum içi tekrar kuyruğundan çıkar
    s.requeue = [r for r in s.requeue if not (r["word_id"] == wid and r.get("reason") in ("relearn", "learn_retry"))]
    if le["kind"] == "learn":
        for l in s.pack:
            if l.word_id == wid:
                l.errors = max(0, l.errors - 1)
                l.rung += 1
                C.set_stage(wid, max(le["stage_before"], l.rung), now)
                if l.rung >= len(LEARN_RUNGS):
                    l.done = True
    s.stats["correct"] += 1
    s.stats["errors"] = max(0, s.stats["errors"] - 1)
    return {"ok": True, "message": "Düzeltildi: 'Zor' olarak kaydedildi"}


def fatigue_hint(s: Session) -> str | None:
    """Son 5 dakikadaki cevap süreleri oturum başına göre %40+ uzadıysa mola öner."""
    now = time.time()
    if now - s.last_break_hint < 600 or len(s.latencies) < 20:
        return None
    t0 = s.latencies[0][0]
    if now - t0 < 600:
        return None
    first = [x[1] for x in s.latencies if x[0] - t0 <= 300]
    last = [x[1] for x in s.latencies if now - x[0] <= 300]
    if len(first) < 8 or len(last) < 8:
        return None
    first.sort()
    last.sort()
    m1, m2 = first[len(first) // 2], last[len(last) // 2]
    if m1 > 0 and m2 / m1 >= 1.4:
        s.last_break_hint = now
        pct = round((m2 / m1 - 1) * 100)
        mins = int(db.get_setting("break_minutes", 5))
        return f"Son 5 dakikada cevap sürelerin %{pct} uzadı; {mins} dk mola ver."
    return None


def heartbeat(sid: str, active_ms_delta: int, device: str = "desktop") -> None:
    if active_ms_delta <= 0:
        return
    active_ms_delta = min(int(active_ms_delta), 120000)
    now = config.now_utc()
    db.x("INSERT INTO activity(session_id, ts, day, active_ms, device) VALUES(?,?,?,?,?)",
         (sid, config.iso(now), config.day_str(), active_ms_delta, device))
    s = get(sid)
    if s:
        s.active_ms += active_ms_delta
        db.x("UPDATE sessions SET active_ms=? WHERE id=?", (s.active_ms, sid))


def finish(sid: str) -> dict:
    s = get(sid)
    if not s:
        return {"type": "done", "summary": {}}
    s.finished = True
    now = config.now_utc()
    db.x("UPDATE sessions SET ended_at=?, n_new=?, n_review=? WHERE id=?",
         (config.iso(now), len(s.stats["learned"]), s.stats["reviews"], sid))
    learned = []
    for wid in s.stats["learned"][:50]:
        it = W.index()["items"].get(wid)
        if it:
            learned.append({"id": wid, "display": it["display"], "meaning": it["short"]})
    acc = (s.stats["correct"] / s.stats["answers"]) if s.stats["answers"] else None
    summary = {"answers": s.stats["answers"], "correct": s.stats["correct"], "accuracy": acc,
               "learned": learned, "reviews": s.stats["reviews"], "active_min": round(s.active_ms / 60000, 1),
               "best_streak": s.stats["best_streak"], "xp": s.stats["xp"], "mode": s.mode, "label": s.label,
               "part_nos": s.meta.get("parts")}
    if s.mode == "quick":
        summary["quick_score"] = s.stats["correct"]
    try:
        from . import parts as P
        if s.part_id:
            still_open = P.refresh(s.part_id)
            p = P.get(s.part_id)
            summary["part"] = {"id": p["id"], "no": p["no"], "done": p["done"], "total": p["total"],
                               "finished": not still_open, "title": p.get("title")}
        if s.mode in ("daily", "review", "part", "learn"):
            info = P.today_info()
            op = info["open"]
            summary["next_part"] = ({"no": op["no"], "id": op["id"], "left": op["total"] - op["done"], "resume": bool(op["started"]),
                                     "title": op.get("title")}
                                    if op else ({"no": info["next_no"], "id": None, "left": info.get("next_size") or info["size"],
                                                 "resume": False, "title": info.get("next_title")}
                                                if info["next_available"] else None))
            summary["parts_today"] = {"planned": info["planned"], "finished": info["finished_today"]}
    except Exception:
        pass
    if s.meta.get("weekly"):
        from . import weekly
        summary["weekly"] = weekly.after_test(s.id)
    try:
        from . import projection
        projection.invalidate()
    except Exception:
        pass
    return {"type": "done", "summary": summary}


def cleanup_old(max_age_h: float = 12) -> None:
    now = config.now_utc()
    with _lock:
        for sid in list(SESSIONS):
            if (now - SESSIONS[sid].started) > timedelta(hours=max_age_h):
                SESSIONS.pop(sid, None)
