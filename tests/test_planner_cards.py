"""Planlayıcı ve tekrar zamanlayıcısı: sınav tarihi kısıtları, son hafta, tekrar çığı, kaçırılan gün."""
from datetime import date, datetime, timedelta, timezone

import numpy as np

from app import cards as C, config, planner, simcore


def _set_exam(db, days_from_today, final_days=7):
    exam = config.study_day() + timedelta(days=days_from_today)
    db.set_setting("exam_date", exam.isoformat())
    db.set_setting("final_days", final_days)
    return exam


def _some_words(db, n):
    return [r["id"] for r in db.q("SELECT id FROM words WHERE status='active' ORDER BY order_index LIMIT ?", (n,))]


def test_no_review_scheduled_after_exam(appdb):
    exam = _set_exam(appdb, 20)
    now = config.now_utc()
    for wid in _some_words(appdb, 60):
        # çok kolay: uzun aralıklar üretir
        for k, g in enumerate((4, 4, 4)):
            C.apply_review(wid, g, now + timedelta(days=k * 6))
    rows = appdb.q("SELECT due_day FROM cards WHERE due_day IS NOT NULL")
    assert rows
    for r in rows:
        assert date.fromisoformat(r["due_day"]) <= exam, r


def test_before_final_window_long_intervals_go_into_final_week(appdb):
    exam = _set_exam(appdb, 30, final_days=7)
    final_start = exam - timedelta(days=7)
    now = config.now_utc()
    wids = _some_words(appdb, 40)
    for wid in wids:
        C.apply_review(wid, 4, now)
        C.apply_review(wid, 4, now + timedelta(days=9))
    days = [date.fromisoformat(r["due_day"]) for r in appdb.q("SELECT due_day FROM cards WHERE due_day IS NOT NULL")]
    clamped = [d for d in days if d >= final_start]
    assert clamped, "uzun aralıklar son haftaya taşınmalı"
    assert all(d <= exam - timedelta(days=1) for d in clamped)
    # yük dengeli: hiçbir gün tümünü almamalı
    from collections import Counter
    cnt = Counter(clamped)
    assert max(cnt.values()) < len(clamped)


def test_review_inside_final_week_not_rescheduled_beyond(appdb):
    exam = _set_exam(appdb, 3, final_days=7)  # bugün son haftanın içinde
    wid = _some_words(appdb, 1)[0]
    now = config.now_utc()
    C.apply_review(wid, 3, now - timedelta(days=30))
    res = C.apply_review(wid, 4, now)
    d = date.fromisoformat(res["due_day"])
    assert d <= exam
    # sınava kadar yeni tekrar yok ya da kısa aralıklı (sınav öncesi)
    assert d == exam or d < exam


def test_final_window_uses_higher_retention(appdb):
    _set_exam(appdb, 3, final_days=7)
    sch = C.scheduler()
    assert sch.desired_retention >= 0.95
    _set_exam(appdb, 40, final_days=7)
    assert C.scheduler().desired_retention < 0.95


def test_plan_no_new_words_in_final_window(appdb):
    _set_exam(appdb, 5, final_days=7)
    p = planner.today_plan(recompute=True)
    assert p["phase"] == "final"
    assert p["new_planned"] == 0


def test_plan_divides_remaining_words_and_flags_realism(appdb):
    _set_exam(appdb, 49, final_days=7)
    appdb.set_setting("weekday_minutes", 30)
    appdb.set_setting("weekend_minutes", 30)
    p = planner.today_plan(recompute=True)
    assert p["phase"] in ("learning", "weekly")
    assert not p["feasible"] and p.get("realism")
    assert p["realism"]["need_weekday"] > 30
    appdb.set_setting("weekday_minutes", 600)
    appdb.set_setting("weekend_minutes", 600)
    p2 = planner.today_plan(recompute=True)
    assert p2["feasible"]
    assert p2["new_planned"] >= p["new_planned"]


def test_avalanche_guard_reduces_new_words(appdb):
    _set_exam(appdb, 40)
    appdb.set_setting("weekday_minutes", 30)
    appdb.set_setting("weekend_minutes", 30)
    now = config.now_utc()
    wids = _some_words(appdb, 400)
    for wid in wids:
        C.apply_review(wid, 3, now - timedelta(days=12))
    # hepsini bugüne vadele (kaçırılmış günler)
    appdb.x("UPDATE cards SET due_day=?, due=? WHERE fsrs IS NOT NULL",
            (config.day_str(), config.iso(now - timedelta(days=1))))
    p = planner.today_plan(recompute=True)
    assert p["reviews_due"] >= 400
    assert p["new_planned"] == 0
    assert p["review_cap"] is not None and p["review_cap"] < p["reviews_due"]
    # en riskli önce: session.due_reviews sınırı uygular
    from app import session
    ids = session.due_reviews(p["review_cap"])
    assert len(ids) == p["review_cap"]


def test_simulation_respects_exam_and_budget_shape():
    H = 30
    inp = simcore.SimInput(H=H, final_days=7, params=list(C.fe.DEFAULT_PARAMETERS), desired_retention=0.9,
                           S=np.array([]), D=np.array([]), last=np.array([]), due=np.array([]),
                           n_new=500, new_schedule=np.array([22] * 23 + [0] * 7), runs=6, seed=1)
    res = simcore.run(inp)
    assert len(res.reviews) == H and len(res.sweeps) == H
    assert res.new[23:].sum() == 0               # son hafta yeni yok
    assert res.introduced_by_end == 500
    assert 0.9 < res.r_exam_mean <= 1.0           # tamamı tanıtıldı -> yüksek hatırlama
    # son günlerde yığılma yok: son gün yükü ortalamanın 3 katını geçmez
    tot = res.reviews + res.sweeps
    assert tot[-1] <= 3 * max(1.0, tot[H - 7:].mean())


def test_weekly_day_ratio_zero(appdb):
    _set_exam(appdb, 49)
    cal = planner.calendar(config.study_day())
    wday = int(appdb.get_setting("weekly_review_day"))
    for d in range(1, cal["final_start"]):
        day = config.study_day() + timedelta(days=d)
        if day.weekday() == wday:
            assert cal["weights"][d] == 0
