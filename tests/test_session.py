"""Oturum akışı: tanıtım → merdiven, FSRS kaydı, olay günlüğü alanları, yeniden sorma, 'aslında biliyordum',
karışabilir kelimelerin aynı pakete girmemesi, beyan doğrulama."""
import json
from datetime import timedelta

from app import config, session


TEXT_TYPES = ("typing", "tiles", "look_write")


def _answer_correct(sid, item, fast=True):
    s = session.get(sid)
    sec = s.pending[item["token"]]["secret"]
    body = {"token": item["token"], "total_ms": 900 if fast else 20000, "first_key_ms": 500 if fast else 15000, "hints": 0}
    if item["type"] in TEXT_TYPES:
        body["text"] = sec["answer"]
    elif item["type"] == "match":
        body["mistakes"] = {}
    elif "options" in item:
        body["choice"] = item["correct"]
    return session.answer(sid, item["token"], body)


def _answer_wrong(sid, item):
    body = {"token": item["token"], "total_ms": 3000, "first_key_ms": 2000, "hints": 0}
    if item["type"] in TEXT_TYPES:
        body["text"] = "qqqq"
    elif item["type"] == "match":
        body["mistakes"] = {str(w): 2 for w in item["targets"]}
    else:
        body["choice"] = (item["correct"] + 1) % len(item["options"])
    return session.answer(sid, item["token"], body)


def _advance_to(sid, item, typ):
    """Doğru cevaplarla istenen alıştırma türüne kadar ilerle."""
    n = 0
    while item and item.get("type") not in (typ, "done") and n < 80:
        item = _answer_correct(sid, item)["next"]
        n += 1
    return item


def test_learning_ladder_and_event_log(appdb):
    appdb.set_setting("exam_date", (config.study_day() + timedelta(days=45)).isoformat())
    r = session.start("learn", limit=5)
    sid = r["session_id"]
    assert r["new"] == 5
    item = session.next_item(sid)
    seen_types = set()
    n = 0
    while item and item.get("type") not in ("done",) and n < 80:
        seen_types.add(item["type"])
        res = _answer_correct(sid, item)
        item = res["next"]
        n += 1
    # önce öğretme katmanları (bak·kapat·yaz, eşleştir, eş anlamlısından bul), sonra 4 sınama basamağı
    assert {"intro", "look_write", "match", "listen", "mcq_tr_en", "cloze", "tiles"} <= seen_types
    stages = appdb.q("SELECT stage, fsrs FROM cards WHERE introduced_at IS NOT NULL")
    assert len(stages) == 5
    assert all(s["stage"] == 4 and s["fsrs"] for s in stages)       # kartın basamağı = geçilen sınama basamağı
    per_word = appdb.q("""SELECT word_id, COUNT(*) n, COUNT(DISTINCT exercise) k FROM events
                          WHERE exercise!='intro' GROUP BY word_id""")
    assert all(r["n"] >= 7 and r["k"] >= 6 for r in per_word)        # en az 7 adım, 6 farklı türde
    ev = appdb.q("SELECT * FROM events WHERE exercise!='intro'")
    assert ev
    for e in ev:
        assert e["word_id"] and e["session_id"] == sid and e["exercise"]
        assert e["total_ms"] is not None and e["first_key_ms"] is not None
        assert e["correct"] in (0, 1) and e["ts"] and e["day"]
        fed = json.loads(e["extra"] or "{}").get("fed_fsrs", True)
        if e["exercise"] in session.TEACH_RUNGS:
            assert not fed and e["rating"] is None                   # öğretme katmanı FSRS'e işlenmez
        else:
            assert fed and e["rating"] in (1, 2, 3, 4)


def test_wrong_answer_requeue_and_override(appdb):
    r = session.start("learn", limit=3)
    sid = r["session_id"]
    item = session.next_item(sid)
    assert item["type"] == "intro"
    item = session.answer(sid, item["token"], {"token": item["token"], "total_ms": 3000})["next"]
    assert item["type"] == "look_write"                  # tanıtımdan hemen sonra: bak · kapat · yaz (öğretme)
    item = _advance_to(sid, item, "listen")              # öğretme katmanlarından sonra ilk sınama: dinle ve seç
    assert item["type"] == "listen"
    wid = item["word_id"]
    res = _answer_wrong(sid, item)
    assert not res["correct"] and res["rating"] == 1
    assert res["error_type"] in ("karıştırma", "yakın anlam", "hatırlayamama")
    ov = session.override(sid, res["event_id"])
    assert ov["ok"]
    o = appdb.q1("SELECT * FROM events WHERE override_of=?", (res["event_id"],))
    assert o and o["rating"] == 2 and o["result"] == "override"
    orig = appdb.q1("SELECT extra FROM events WHERE id=?", (res["event_id"],))
    assert '"overridden":1' in orig["extra"].replace(" ", "")


def test_confusable_pairs_not_in_same_pack(appdb):
    ids = session.pick_new_words(60)
    conf = session.confusable_map()
    for k in range(0, len(ids), 5):
        pack = set(ids[k:k + 5])
        for w in pack:
            assert not (conf.get(w, set()) & (pack - {w})), "karışabilir çift aynı pakette"


def test_known_claim_requires_verification(appdb):
    r = session.start("learn", limit=2)
    sid = r["session_id"]
    item = session.next_item(sid)
    wid = item["word_id"]
    res = session.answer(sid, item["token"], {"token": item["token"], "already_known": True, "total_ms": 800})
    nxt = res["next"]
    labels = []
    for k in range(len(session.VERIFY_CHECKS)):
        assert nxt.get("verify") and nxt["word_id"] == wid, f"{k + 1}. kontrol gelmedi"
        labels.append(nxt["type_label"])
        res = _answer_correct(sid, nxt)
        if k < len(session.VERIFY_CHECKS) - 1:
            assert res["verify_result"] is None      # 4 kontrol bitmeden karar yok
        nxt = res["next"]
    assert res["verify_result"] == "verified"
    assert labels[0].startswith("Doğrulama 1/4") and labels[-1].startswith("Doğrulama 4/4")
    card = appdb.q1("SELECT * FROM cards WHERE word_id=?", (wid,))
    assert card["known_status"] == "verified" and card["stage"] == 6
    # uzun boşluk yok: ilk tekrar birkaç gün içinde
    assert 0 < card["stability"] < 5
    assert config.parse_iso(card["due"]) - config.now_utc() <= timedelta(days=3)


def test_failed_verification_goes_to_normal_learning(appdb):
    r = session.start("learn", limit=2)
    sid = r["session_id"]
    item = session.next_item(sid)
    wid = item["word_id"]
    res = session.answer(sid, item["token"], {"token": item["token"], "already_known": True, "total_ms": 800})
    res = _answer_wrong(sid, res["next"])
    assert res["verify_result"] == "failed"
    card = appdb.q1("SELECT * FROM cards WHERE word_id=?", (wid,))
    assert card["known_status"] == "failed" and card["fsrs"] is None


def test_review_ladder_continues_after_session(appdb):
    from app import cards as C, simcore
    assert simcore.LEARN_STEPS == session.FSRS_STEPS_PER_NEW == len(session.TEST_RUNGS) + 1
    r = session.start("review")
    s = session.get(r["session_id"])
    wid = appdb.val("SELECT word_id FROM cards ORDER BY word_id LIMIT 1")
    appdb.x("UPDATE cards SET state=2 WHERE word_id=?", (wid,))
    expected = {0: "listen", 1: "mcq_tr_en", 2: "cloze", 3: "tiles", 4: "typing", 5: "synonym"}
    for stage, typ in expected.items():
        C.set_stage(wid, stage, config.now_utc())
        assert session.choose_review_exercise(s, wid) == typ


def test_learning_goes_from_easy_to_hard(appdb):
    """Kelime önce öğretilir; sonra dinle → test → boşluk doldurma → yazma (zorluk artarak)."""
    r = session.start("learn", limit=1)
    sid = r["session_id"]
    item, order = session.next_item(sid), []
    while item and item.get("type") != "done":
        order.append(item["type"])
        item = _answer_correct(sid, item)["next"]
    # tek kelimede eşleştirme kurulamaz (çift yok) → o katman atlanır; eş anlamlısı yoksa yerine anlam testi
    assert order[:2] == ["intro", "look_write"] and order[2] in ("syn_pick", "mcq_en_tr")
    assert order[3:] == ["listen", "mcq_tr_en", "cloze", "tiles"]


def test_listen_exercise_hides_the_word_and_can_be_turned_off(appdb):
    r = session.start("learn", limit=1)
    sid = r["session_id"]
    intro = session.next_item(sid)
    item = session.answer(sid, intro["token"], {"token": intro["token"], "total_ms": 3000})["next"]
    item = _advance_to(sid, item, "listen")
    assert item["type"] == "listen" and item["prompt"] is None
    assert item["audio"] == intro["display"] and len(item["options"]) == 4
    res = _answer_correct(sid, item)
    assert res["correct"] and res["say"] == intro["display"]      # doğru cevap sesli tekrar edilir
    appdb.set_setting("listen_exercises", False)                 # sessiz ortam: okumalı teste döner
    assert session._test_type(0) == "mcq_en_tr"
    appdb.set_setting("listen_exercises", True)
    assert session._test_type(0) == "listen"


def test_every_answer_carries_the_word_to_say(appdb):
    """Seçince/yazınca doğru cevap sesli söylenir: test, boşluk ve yazma adımlarında 'say' dolu gelir."""
    r = session.start("learn", limit=2)
    sid = r["session_id"]
    item, said = session.next_item(sid), {}
    while item and item.get("type") != "done":
        if item["type"] == "intro":
            item = session.answer(sid, item["token"], {"token": item["token"], "total_ms": 3000})["next"]
            continue
        sec = session.get(sid).pending[item["token"]]["secret"]
        if item["type"] == "match":
            item = _answer_correct(sid, item)["next"]
            continue
        if item["type"] in ("mcq_tr_en", "cloze", "syn_pick"):
            want = item["options"][item["correct"]].replace(" / ", ", ")   # boşlukta cümleye giren biçim
        elif item["type"] in ("listen", "look_write"):
            want = item["audio"]
        elif item["type"] == "mcq_en_tr":
            want = session.W.index()["items"][item["word_id"]]["display"]
        else:
            want = sec["answer"]
        res = _answer_correct(sid, item)
        said[item["type"]] = (res["say"], want)
        item = res["next"]
    assert {"look_write", "listen", "mcq_tr_en", "cloze", "tiles"} <= set(said)
    for typ, (say, want) in said.items():
        assert say and say == want, (typ, say, want)
    r = session.start("learn", limit=1)
    sid = r["session_id"]
    intro = session.next_item(sid)
    item = session.answer(sid, intro["token"], {"token": intro["token"], "total_ms": 3000})["next"]
    item = _advance_to(sid, item, "listen")
    res = _answer_wrong(sid, item)
    assert not res["correct"] and res["say"] == intro["display"]  # yanlışta da doğru cevap sesli


def test_mature_reviews_include_listening(appdb):
    from app import cards as C
    r = session.start("review")
    s = session.get(r["session_id"])
    wid = appdb.val("SELECT word_id FROM cards ORDER BY word_id LIMIT 1")
    appdb.x("UPDATE cards SET state=2, lapses=0, stability=30 WHERE word_id=?", (wid,))
    C.set_stage(wid, 6, config.now_utc())
    picks = [session.choose_review_exercise(s, wid) for _ in range(400)]
    assert "listen" in picks and "mcq_en_tr" in picks
    appdb.set_setting("listen_exercises", False)
    assert "listen" not in [session.choose_review_exercise(s, wid) for _ in range(200)]


def test_half_finished_intro_is_picked_again(appdb):
    r = session.start("learn", limit=2)
    sid = r["session_id"]
    item = session.next_item(sid)
    assert item["type"] == "intro"
    wid = item["word_id"]
    session.finish(sid)                                   # tanıtım görüldü, hiç adım yapılmadan oturum kapandı
    card = appdb.q1("SELECT state, introduced_at FROM cards WHERE word_id=?", (wid,))
    assert card["state"] == 0 and card["introduced_at"]
    assert wid not in session.pick_new_words(10)          # aynı oturum penceresinde tekrar seçilmez
    old = config.iso(config.now_utc() - session.ORPHAN_AFTER - timedelta(minutes=5))
    appdb.x("UPDATE cards SET introduced_at=? WHERE word_id=?", (old, wid))
    assert wid in session.pick_new_words(10)              # askıda kalmaz: yeniden yeni kelime olarak gelir


def test_migration_rechecks_words_verified_with_two_checks(appdb):
    from app import db
    a, b = [r["word_id"] for r in appdb.q("""SELECT c.word_id FROM cards c JOIN words w ON w.id=c.word_id
                                              WHERE w.status='active' ORDER BY c.word_id LIMIT 2""")]
    now = config.iso(config.now_utc())
    appdb.x("""UPDATE cards SET known_status='verified', state=2, stage=6, reps=1, stability=8.3, fsrs='{}', due=?,
               due_day='2099-01-01', last_review=?, learned_at=?, introduced_at=? WHERE word_id=?""", (now, now, now, now, a))
    appdb.x("UPDATE cards SET known_status='verified', state=2, stage=6, reps=3, stability=20 WHERE word_id=?", (b,))
    appdb.x("UPDATE meta SET value='1' WHERE key='schema_version'")
    assert db.migrate() == db.SCHEMA_VERSION
    ca = appdb.q1("SELECT * FROM cards WHERE word_id=?", (a,))
    assert ca["known_status"] == "probable" and ca["state"] == 0 and ca["stage"] == 0 and ca["fsrs"] is None
    assert ca["introduced_at"] is None and ca["due_day"] is None
    assert a in [t["word_id"] for t in session.verify_tasks(50)]          # sonraki oturumda 4 kontrol
    cb = appdb.q1("SELECT * FROM cards WHERE word_id=?", (b,))
    assert cb["known_status"] == "verified" and cb["stage"] == 6           # tekrarı olan karta dokunulmaz


def test_heartbeat_active_time(appdb):
    r = session.start("learn", limit=1)
    session.heartbeat(r["session_id"], 15000)
    session.heartbeat(r["session_id"], 999999)  # üst sınır 120 sn
    total = appdb.val("SELECT SUM(active_ms) FROM activity")
    assert total == 15000 + 120000


def test_match_layer_covers_the_pack_and_reteaches_mistakes(appdb):
    r = session.start("learn", limit=5)
    sid = r["session_id"]
    item = _advance_to(sid, session.next_item(sid), "match")
    assert item["type"] == "match"
    targets = item["targets"]
    assert len(targets) >= 4 and len(item["left"]) == len(item["right"]) >= 4
    assert all(item["pairs"][l["k"]] in {x["k"] for x in item["right"]} for l in item["left"])
    s = session.get(sid)
    assert all(l.rung == session.MATCH_RUNG for l in s.pack if l.word_id in targets)   # paket birlikte eşleştirir
    bad = targets[0]
    body = {"token": item["token"], "total_ms": 20000, "first_key_ms": 1500, "mistakes": {str(bad): 2}}
    res = session.answer(sid, item["token"], body)
    assert res["result"] == "wrong" and res["next"]
    ev = appdb.q("SELECT word_id, correct, rating, fsrs_after FROM events WHERE exercise='match'")
    assert {e["word_id"] for e in ev} == set(targets)
    assert all(e["rating"] is None and e["fsrs_after"] is None for e in ev)            # FSRS'e işlenmez
    assert {e["word_id"] for e in ev if not e["correct"]} == {bad}
    assert all(l.rung == session.MATCH_RUNG + 1 for l in s.pack if l.word_id in targets)
    assert any(rq["type"] == "reintro" and rq["word_id"] == bad for rq in s.requeue)   # 2 hata → tanıtım yeniden


def test_teaching_layers_do_not_schedule_and_first_review_is_tomorrow(appdb):
    r = session.start("learn", limit=1)
    sid = r["session_id"]
    intro = session.next_item(sid)
    wid = intro["word_id"]
    item = session.answer(sid, intro["token"], {"token": intro["token"], "total_ms": 3000})["next"]
    assert item["type"] == "look_write" and item["display"] == intro["display"] and item["prompt"]
    item = _answer_correct(sid, item)["next"]
    card = appdb.q1("SELECT fsrs, stage FROM cards WHERE word_id=?", (wid,))
    assert card["fsrs"] is None and card["stage"] == 0       # kodlama adımı tekrar takvimini başlatmaz
    while item and item.get("type") != "done":
        item = _answer_correct(sid, item)["next"]
    card = appdb.q1("SELECT stage, due_day FROM cards WHERE word_id=?", (wid,))
    tomorrow = (config.study_day() + timedelta(days=1)).isoformat()
    assert card["stage"] == 4 and card["due_day"] <= tomorrow   # yeni öğrenilen kelime en geç yarın tekrar


def test_part_ends_with_a_consolidation_round(appdb):
    r = session.start("learn", limit=4)
    sid = r["session_id"]
    item, seen = session.next_item(sid), []
    while item and item.get("type") != "done" and len(seen) < 150:
        seen.append(item)
        item = _answer_correct(sid, item)["next"]
    cons = [it for it in seen if str(it.get("type_label", "")).startswith("Pekiştirme turu")]
    learned = {it["word_id"] for it in seen if it["type"] == "tiles"}
    assert len(cons) == len(learned) == 4 and {it["word_id"] for it in cons} == learned
    assert {it["type"] for it in cons} <= {"listen", "mcq_tr_en", "mcq_en_tr"}
    first_cons = seen.index(cons[0])
    assert all(it["type"] != "intro" for it in seen[first_cons:])           # tüm kelimeler öğrenildikten sonra


def test_intro_shows_synonyms_next_to_the_word(appdb):
    from app import words as W
    wid = next(r["word_id"] for r in appdb.q("""SELECT DISTINCT word_id FROM word_info WHERE field='synonyms'
                                               AND word_id IN (SELECT id FROM words WHERE status='active') LIMIT 1"""))
    p, _ = session.X.intro(wid)
    assert p["synonyms"] and all(x["w"] for x in p["synonyms"])
    assert p["synonyms"] == W.synonyms_for(wid, 6)
    pk, _ = session.X.syn_pick(wid, [w for w in W.index()["items"] if w != wid][:6]) or (None, None)
    if pk:
        assert pk["options"][pk["correct"]] == W.index()["items"][wid]["display"] and len(pk["options"]) >= 3
