"""Vektörel FSRS (numpy) ile resmî py-fsrs'in birebir aynı sonucu verdiğini doğrular."""
import random
from datetime import date, datetime, timedelta, timezone

import numpy as np
from fsrs import Card, Rating

from app import fsrs_engine as fe


def _py_sequence(seq, params=None):
    sch = fe.make_scheduler(params, 0.9, fuzz=False)
    t0 = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
    card = Card(card_id=1, due=t0)
    t = t0
    out = []
    for dt_h, g in seq:
        t = t + timedelta(hours=dt_h)
        card, _ = sch.review_card(card, Rating(g), review_datetime=t)
        out.append((card.stability, card.difficulty))
    return out


def _vec_sequence(seq, params=None):
    vf = fe.VecFSRS(params)
    t0 = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
    t = t0
    s = d = None
    last = None
    out = []
    for i, (dt_h, g) in enumerate(seq):
        t = t + timedelta(hours=dt_h)
        if i == 0:
            s, d = vf.step(np.array([1.0]), np.array([5.0]), np.array([0.0]), np.array([g]), np.array([True]))
        else:
            el = (t - last).days
            s, d = vf.step(s, d, np.array([float(el)]), np.array([g]), np.array([False]))
        last = t
        out.append((float(s[0]), float(d[0])))
    return out


def test_vectorized_matches_py_fsrs_random_sequences():
    rng = random.Random(42)
    for _ in range(300):
        n = rng.randint(1, 12)
        seq = []
        for _ in range(n):
            gap = rng.choice([0.05, 0.3, 2, 20, 30, 50, 100, 200, 400, 1000])  # saat
            g = rng.choices([1, 2, 3, 4], weights=[2, 2, 5, 1])[0]
            seq.append((gap, g))
        a = _py_sequence(seq)
        b = _vec_sequence(seq)
        for (s1, d1), (s2, d2) in zip(a, b):
            assert abs(s1 - s2) < 1e-6 * max(1.0, s1), (seq, a, b)
            assert abs(d1 - d2) < 1e-6, (seq, a, b)


def test_retrievability_matches():
    sch = fe.make_scheduler(None, 0.9, fuzz=False)
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    card, _ = sch.review_card(Card(card_id=1, due=t0), Rating.Good, review_datetime=t0)
    for days in (0, 1, 3, 10, 40):
        at = t0 + timedelta(days=days, hours=5)
        r1 = sch.get_card_retrievability(card, current_datetime=at)
        r2 = fe.retrievability(sch.parameters, card.stability, card.last_review, at)
        assert abs(r1 - r2) < 1e-12
        assert 0 < r2 <= 1


def test_interval_equals_stability_at_90_percent():
    p = fe.DEFAULT_PARAMETERS
    assert abs(fe.interval_for(p, 10.0, 0.9) - 10.0) < 1e-9
    assert fe.interval_for(p, 10.0, 0.95) < 10.0


def test_clamp_due_day_never_after_exam():
    win = fe.ExamWindow(exam=date(2026, 11, 22), final_days=7)
    today = date(2026, 11, 1)
    load = {}
    for k in range(200):
        d = fe.clamp_due_day(date(2026, 12, 1) + timedelta(days=k % 30), today, win, load=load)
        assert win.final_start <= d <= win.last_review_day
    # yük dengeli dağıtım
    assert max(load.values()) - min(load.values()) <= 1
