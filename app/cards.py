"""Kart (FSRS) durumu işlemleri: tekrar uygula, geri al, sınav penceresine sıkıştır."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from fsrs import Card, Rating, State

from . import config, db
from . import fsrs_engine as fe

STAGE_MAX = 6
DURABLE_S = 21.0


def active_params() -> list[float]:
    row = db.q1("SELECT params FROM fsrs_params WHERE active=1 ORDER BY id DESC LIMIT 1")
    if row:
        p = db.jload(row["params"])
        if isinstance(p, list) and len(p) == 21:
            return p
    return list(fe.DEFAULT_PARAMETERS)


def exam_window() -> fe.ExamWindow:
    return fe.ExamWindow(exam=date.fromisoformat(db.get_setting("exam_date")),
                         final_days=int(db.get_setting("final_days", 7)))


def scheduler(fuzz: bool = True, today: date | None = None):
    """Son haftada (sınav penceresi) hedef hatırlama en az target_recall (%95) olur: zayıf kartlar sıklaşır."""
    dr = float(db.get_setting("desired_retention", 0.9))
    win = exam_window()
    today = today or config.study_day()
    if win.final_start <= today < win.exam:
        dr = max(dr, float(db.get_setting("target_recall", 0.95)))
    return fe.make_scheduler(active_params(), dr, fuzz=fuzz)


def get(word_id: int) -> dict | None:
    return db.q1("SELECT * FROM cards WHERE word_id=?", (word_id,))


def final_window_load(win: fe.ExamWindow, today: date) -> dict[date, int]:
    rows = db.q("SELECT due_day, COUNT(*) n FROM cards WHERE due_day>=? AND due_day<? GROUP BY due_day",
                (win.final_start.isoformat(), win.exam.isoformat()))
    return {date.fromisoformat(r["due_day"]): r["n"] for r in rows}


def clamp_for_exam(due: datetime, today: date, stability: float | None) -> tuple[datetime, date]:
    """Hiçbir tekrar sınav sonrasına planlanmaz.
    - Son haftadan önce yapılan tekrarın vadesi sınavı geçiyorsa: son haftanın en az yüklü gününe (tarama turu).
    - Son hafta içinde yapılan tekrarın vadesi sınavı geçiyorsa: sınava kadar yeni tekrar yok (vade = sınav günü).
    """
    win = exam_window()
    due_day = fe.due_to_day(due)
    if today >= win.exam or due_day <= win.last_review_day:
        return due, due_day
    if today >= win.final_start:
        return config.day_start_utc(win.exam) + timedelta(hours=2), win.exam
    load = final_window_load(win, today)
    new_day = fe.clamp_due_day(due_day, today, win, load=load, stability=stability)
    if new_day <= today:
        new_day = win.exam
    new_due = config.day_start_utc(new_day) + timedelta(hours=2)
    return min(due, new_due), new_day


def apply_review(word_id: int, rating: int, ts: datetime) -> dict:
    """FSRS tekrarını uygular; önce/sonra durumlarını döndürür (olay kaydı için)."""
    row = get(word_id)
    if row is None:
        db.x("INSERT OR IGNORE INTO cards(word_id, stage, state) VALUES(?,0,0)", (word_id,))
        row = get(word_id)
    before = db.jload(row.get("fsrs")) if row.get("fsrs") else None
    card = fe.card_from_json(before) if before else Card(card_id=word_id, due=ts)
    today = config.study_day(ts)
    sch = scheduler(today=today)
    params = sch.parameters
    r_before = None
    elapsed = None
    if card.last_review is not None and card.stability is not None:
        r_before = fe.retrievability(params, card.stability, card.last_review, ts)
        elapsed = (ts - card.last_review).total_seconds() / 86400.0
    prev_state = card.state if before else None
    new_card, _log = sch.review_card(card, Rating(int(rating)), review_datetime=ts)
    due, due_day = new_card.due, fe.due_to_day(new_card.due)
    if new_card.state == State.Review:
        due, due_day = clamp_for_exam(new_card.due, today, new_card.stability)
        new_card.due = due
    after = fe.card_to_json(new_card)
    lapses_add = 1 if (rating == 1 and prev_state == State.Review) else 0
    durable_now = (new_card.stability or 0) >= DURABLE_S
    db.x("""UPDATE cards SET fsrs=?, state=?, stability=?, difficulty=?, due=?, due_day=?, last_review=?,
                   reps=reps+1, lapses=lapses+?, wrong_total=wrong_total+?,
                   durable_at=CASE WHEN durable_at IS NULL AND ? THEN ? ELSE durable_at END,
                   updated_at=? WHERE word_id=?""",
         (db.jdump(after), int(new_card.state), new_card.stability, new_card.difficulty, config.iso(due),
          due_day.isoformat(), config.iso(ts), lapses_add, 1 if rating == 1 else 0,
          1 if durable_now else 0, config.iso(ts), config.iso(ts), word_id))
    return {"before": before, "after": after, "r_before": r_before, "elapsed_days": elapsed,
            "due_day": due_day.isoformat(), "stability": new_card.stability, "difficulty": new_card.difficulty,
            "state": int(new_card.state)}


def cap_first_review(word_id: int, ts: datetime) -> str | None:
    """Oturumda yeni öğrenilen kelimenin ilk tekrarı en geç ertesi gün (unutma ilk günlerde en hızlıdır; kullanıcı
    'öğrendiğimi hemen unutuyorum' dedi). FSRS kararlılığı değişmez, yalnızca vade öne çekilir."""
    row = get(word_id)
    if not row or not row.get("fsrs") or not row.get("due_day"):
        return None
    nxt = config.study_day(ts) + timedelta(days=1)
    if date.fromisoformat(row["due_day"]) <= nxt:
        return row["due_day"]
    due = config.day_start_utc(nxt) + timedelta(hours=2)
    card = fe.card_from_json(db.jload(row["fsrs"]))
    card.due = due
    db.x("UPDATE cards SET fsrs=?, due=?, due_day=? WHERE word_id=?",
         (db.jdump(fe.card_to_json(card)), config.iso(due), nxt.isoformat(), word_id))
    return nxt.isoformat()


def restore(word_id: int, fsrs_before: dict | None, stage_before: int | None, was_wrong: bool,
            was_lapse: bool) -> None:
    """'Aslında biliyordum' için son tekrarı geri alır."""
    if fsrs_before:
        c = fe.card_from_json(fsrs_before)
        due_day = fe.due_to_day(c.due)
        db.x("""UPDATE cards SET fsrs=?, state=?, stability=?, difficulty=?, due=?, due_day=?, last_review=?,
                       reps=MAX(reps-1,0), lapses=MAX(lapses-?,0), wrong_total=MAX(wrong_total-?,0), stage=COALESCE(?, stage)
                WHERE word_id=?""",
             (db.jdump(fsrs_before), int(c.state), c.stability, c.difficulty, config.iso(c.due), due_day.isoformat(),
              config.iso(c.last_review), 1 if was_lapse else 0, 1 if was_wrong else 0, stage_before, word_id))
    else:
        db.x("""UPDATE cards SET fsrs=NULL, state=0, stability=NULL, difficulty=NULL, due=NULL, due_day=NULL,
                       last_review=NULL, reps=0, lapses=0, wrong_total=MAX(wrong_total-?,0), stage=COALESCE(?, stage)
                WHERE word_id=?""", (1 if was_wrong else 0, stage_before, word_id))


def set_stage(word_id: int, stage: int, ts: datetime) -> None:
    stage = max(0, min(STAGE_MAX, int(stage)))
    db.x("""UPDATE cards SET stage=?,
                   learned_at=CASE WHEN ?>=? AND learned_at IS NULL THEN ? ELSE learned_at END,
                   updated_at=? WHERE word_id=?""",
         (stage, stage, STAGE_MAX, config.iso(ts), config.iso(ts), word_id))


def mark_introduced(word_id: int, ts: datetime) -> None:
    db.x("UPDATE cards SET introduced_at=COALESCE(introduced_at, ?), stage=MAX(stage, 0) WHERE word_id=?",
         (config.iso(ts), word_id))


def init_known(word_id: int, ts: datetime, stability_days: float | None = None) -> dict:
    """Doğrulanmış 'biliyorum' (4 farklı türde kontrol geçti): merdiveni tamamlanmış say, ama Good ile başlat —
    ilk tekrar ~2 gün sonra gelir, aralığı sonraki doğru cevaplar büyütür (Easy ~8 günlük ilk boşluk bırakıyordu)."""
    res = apply_review(word_id, 3, ts)
    db.x("UPDATE cards SET known_status='verified', stage=?, learned_at=COALESCE(learned_at, ?), "
         "introduced_at=COALESCE(introduced_at, ?) WHERE word_id=?",
         (STAGE_MAX, config.iso(ts), config.iso(ts), word_id))
    return res


def retrievability_now(row: dict, at: datetime | None = None) -> float | None:
    if not row or row.get("stability") is None or not row.get("last_review"):
        return None
    return fe.retrievability(active_params(), row["stability"], config.parse_iso(row["last_review"]),
                             at or config.now_utc())


def reschedule_all(params: list[float] | None = None) -> int:
    """Yeni parametrelerle tüm kartları olay kaydından yeniden hesaplar (haftalık optimizasyon sonrası)."""
    from fsrs import Scheduler
    sch = fe.make_scheduler(params or active_params(), float(db.get_setting("desired_retention", 0.9)), fuzz=False)
    rows = db.q("""SELECT word_id, ts, rating FROM events WHERE rating IS NOT NULL AND
                   (extra IS NULL OR extra NOT LIKE '%"overridden":1%') ORDER BY word_id, ts, id""")
    by: dict[int, list] = {}
    for r in rows:
        by.setdefault(r["word_id"], []).append(r)
    n = 0
    today = config.study_day()
    for wid, evs in by.items():
        c = Card(card_id=wid, due=config.parse_iso(evs[0]["ts"]))
        for e in evs:
            c, _ = sch.review_card(c, Rating(int(e["rating"])), review_datetime=config.parse_iso(e["ts"]))
        due, due_day = c.due, fe.due_to_day(c.due)
        if c.state == State.Review:
            due, due_day = clamp_for_exam(c.due, today, c.stability)
            c.due = due
        db.x("UPDATE cards SET fsrs=?, state=?, stability=?, difficulty=?, due=?, due_day=? WHERE word_id=?",
             (db.jdump(fe.card_to_json(c)), int(c.state), c.stability, c.difficulty, config.iso(due),
              due_day.isoformat(), wid))
        n += 1
    return n
