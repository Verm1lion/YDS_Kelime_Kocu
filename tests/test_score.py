"""Puan modeli: seviye önseli, ileriye dönük senaryolar, deneme günündeki kelime durumu, gerçek ÖSYM soruları, canlı önbellek."""
import json
from datetime import timedelta

from app import config, db, score_model as SM


def _p(x, t):
    return x["p"][str(t)]


def test_self_level_prior_moves_the_estimate(appdb):
    appdb.set_setting("self_level", "B1")
    b1 = SM.compute()
    appdb.set_setting("self_level", "A2-B1")
    a2b1 = SM.compute()
    assert a2b1["inputs"]["level"] == "A2-B1" and "A2–B1" in a2b1["basis"]
    now_b1, now_a2 = b1["scenarios"][0], a2b1["scenarios"][0]
    assert now_a2["median"] < now_b1["median"]
    assert _p(a2b1["scenarios"][2], 55) < _p(b1["scenarios"][2], 55)


def test_forward_scenarios_are_monotonic_in_words_and_skill(appdb):
    appdb.set_setting("self_level", "A2-B1")
    r = SM.compute()
    t = r["target"]
    words = [m["words"] for m in r["milestones"]]
    assert words[0] == 0 and words == sorted(words) and r["milestones"][-1]["label"].startswith("Listenin tamamı")
    ps = [_p(m, t) for m in r["milestones"]]
    assert all(a <= b + 1e-9 for a, b in zip(ps, ps[1:])) and ps[-1] > ps[0]          # daha çok kelime → daha yüksek
    for thr in r["thresholds"]:
        curve = [_p(c, thr) for c in r["curve"]["points"]]
        assert all(a <= b + 1e-9 for a, b in zip(curve, curve[1:]))                  # ortak rastgele sayılar: pürüzsüz
    now, pace, plan = r["scenarios"]
    assert _p(plan, t) >= _p(now, t)
    assert _p(r["skill_up"], t) > _p(plan, t)                                        # beceri artışı ayrı bir kaldıraç
    assert all(m["eta_pace"]["date"] for m in r["milestones"][1:])


def test_old_mock_is_judged_with_that_days_vocabulary(appdb):
    """Kelimeler denemeden SONRA öğrenildiyse aynı puan daha yüksek beceri demektir."""
    ids = [r["word_id"] for r in appdb.q("""SELECT c.word_id FROM cards c JOIN words w ON w.id=c.word_id
                                             WHERE w.status='active' ORDER BY w.order_index LIMIT 400""")]
    now = config.now_utc()
    for wid in ids:
        appdb.x("""UPDATE cards SET state=2, stability=40, difficulty=5, last_review=?, due_day=?, introduced_at=?, stage=6
                   WHERE word_id=?""", (config.iso(now), (config.study_day() + timedelta(days=40)).isoformat(),
                                        config.iso(now), wid))
    from app import projection
    projection.invalidate()
    yesterday = (config.study_day() - timedelta(days=1)).isoformat()
    m = SM.add_mock(yesterday, 40, None, "dün")
    before = SM.compute()["theta"]["mean"]
    db.x("UPDATE mock_exams SET day=? WHERE id=?", (config.day_str(), m))
    today = SM.compute()["theta"]["mean"]
    assert before > today


def test_real_osym_grammar_answers_update_skill(appdb):
    appdb.set_setting("self_level", "A2-B1")
    base = SM.compute()["theta"]["mean"]
    qs = json.loads((config.seed_dir() / "osym_questions.json").read_text(encoding="utf-8"))
    gram = [q for q in qs if q["type"] == "Dil Bilgisi"]
    for q in gram * 2:
        db.x("""INSERT INTO events(ts, day, session_id, word_id, mode, exercise, direction, prompt, correct, result)
                VALUES(?,?,?,?,?,?,?,?,1,'correct')""",
             (config.iso(config.now_utc()), config.day_str(), "t", 1, "weekly", "osym", "context",
              json.dumps({"prompt": None, "sentence": q["stem"]})))
    r = SM.compute()
    assert r["inputs"]["osym_grammar"] == 2 * len(gram) and r["theta"]["mean"] > base


def test_live_cache_recomputes_only_when_inputs_change(appdb):
    a = SM.compute()
    assert SM.compute() is a                                                         # değişiklik yok: önbellek
    SM.add_mock(config.day_str(), 50, None, "x")
    b = SM.compute()
    assert b is not a and b["mock_count"] == 1
