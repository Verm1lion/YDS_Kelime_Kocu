"""Partlar: ≤15 kelimelik kalıcı gruplar, kaldığı yerden devam, tekrar bloğu ayrı, seçilen partlarla test."""
from app import config, parts as P, session


def _answer_correct(sid, item):
    s = session.get(sid)
    sec = s.pending[item["token"]]["secret"]
    body = {"token": item["token"], "total_ms": 900, "first_key_ms": 500, "hints": 0}
    if item["type"] in ("typing", "tiles", "look_write"):
        body["text"] = sec["answer"]
    elif item["type"] == "match":
        body["mistakes"] = {}
    elif "options" in item:
        body["choice"] = item["correct"]
    return session.answer(sid, item["token"], body)


def _label(p: dict) -> str:
    return f"Part {p['no']}" + (f" · {p['title']}" if p.get("title") else "")


def _run(sid, limit=500):
    """Oturumu sonuna kadar doğru cevaplarla yürütür; görülen öğeleri döndürür."""
    item, seen = session.next_item(sid), []
    while item and item.get("type") != "done" and len(seen) < limit:
        seen.append(item)
        item = _answer_correct(sid, item)["next"]
    return seen, item


def _finish_part(mode="daily"):
    r = session.start(mode)
    assert r["mode"] == "part"
    seen, done = _run(r["session_id"])
    return r, seen, done


def test_daily_without_reviews_opens_a_part_of_at_most_15(appdb):
    r, seen, done = _finish_part("daily")
    p1 = P.get(r["part"]["id"])
    n1 = p1["total"]
    assert 1 <= n1 <= 15 and r["new"] == n1 and r["label"] == _label(p1)
    words = {it["word_id"] for it in seen}
    assert len(words) == n1                                   # oturum yalnızca partın kelimeleri
    summ = done["summary"]
    assert summ["part"] == {"id": p1["id"], "no": 1, "done": n1, "total": n1, "finished": True, "title": p1.get("title")}
    assert summ["next_part"]["no"] == 2 and summ["next_part"]["id"] is None
    assert p1["status"] == "tamam" and p1["done"] == n1
    # ikinci part farklı kelimelerle oluşur; birinci partın üyeliği değişmez
    r2, seen2, _ = _finish_part("part")
    assert r2["label"] == _label(P.get(r2["part"]["id"])) and r2["label"].startswith("Part 2")
    assert not ({it["word_id"] for it in seen2} & words)
    assert set(P.remaining_words(p1["id"])) == set() and len(P._rows([p1["id"]])) == n1


def test_part_resumes_where_it_was_left(appdb):
    r = session.start("part")
    sid = r["session_id"]
    pid = r["part"]["id"]
    ids = ",".join(str(w) for w in P.remaining_words(pid))
    item = session.next_item(sid)
    for _ in range(300):                                      # sınama basamaklarına geçmiş kelimeler varken yarıda bırak
        item = _answer_correct(sid, item)["next"]
        if len(appdb.q(f"SELECT 1 FROM cards WHERE word_id IN ({ids}) AND stage BETWEEN 1 AND 3")) >= 2:
            break
    session.finish(sid)
    assert P.open_part()["id"] == pid                         # yeni part açılmaz, yarım kalan sürer
    remaining = P.remaining_words(pid)
    assert 0 < len(remaining) <= 15
    in_progress = {row["word_id"]: row["stage"] for row in appdb.q(
        "SELECT word_id, stage FROM cards WHERE word_id IN (%s) AND stage BETWEEN 1 AND 3" % ",".join(map(str, remaining)))}
    assert in_progress, "yarım kalan merdiven olmalı"
    r2 = session.start("part")
    assert r2["part"]["id"] == pid and r2["new"] == len(remaining)
    s2 = session.get(r2["session_id"])
    seen, done = _run(r2["session_id"])
    for wid, stage in in_progress.items():
        mine = [it for it in seen if it["word_id"] == wid and it["type"] != "match"
                and not str(it.get("type_label", "")).startswith("Pekiştirme")]
        # önce kelime yeniden öğretilir (yeni sayılmaz), sonra kaldığı sınama basamağının iki gerisinden kolaydan zora
        assert mine[0]["type"] == "intro" and mine[0].get("reintro") and mine[0]["type_label"] == "Hatırlayalım"
        start = len(session.TEACH_RUNGS) + max(0, stage - 2)
        assert [it["type"] for it in mine[1:]] == [session._learn_type(k) for k in range(start, len(session.LEARN_RUNGS))]
    assert s2.stats["new"] == len(remaining) - len(in_progress)
    assert done["summary"]["part"]["finished"]


def test_daily_with_due_reviews_is_a_review_block_without_new_words(appdb):
    r, seen, _ = _finish_part("daily")
    ids = [w for w in P._rows([r["part"]["id"]])][:5]
    for row in ids:
        appdb.x("UPDATE cards SET due_day=?, due=? WHERE word_id=?",
                (config.day_str(), config.iso(config.now_utc()), row["word_id"]))
    d = session.start("daily")
    assert d["mode"] == "daily" and d["label"] == "Tekrarlar" and d["new"] == 0 and d["reviews"] == 5
    _, done = _run(d["session_id"])
    assert done["summary"]["next_part"]["no"] == 2           # tekrarlar bitince sıradaki part önerilir


def test_tests_on_selected_parts_only_use_those_words(appdb):
    r1, _, _ = _finish_part("part")
    r2, _, _ = _finish_part("part")
    p1, p2 = r1["part"]["id"], r2["part"]["id"]
    w1 = set(P.test_words([p1]))
    w2 = set(P.test_words([p2]))
    assert len(w1) == P.get(p1)["total"] and len(w2) == P.get(p2)["total"] and not (w1 & w2)
    t = session.start("part_test", part_ids=[p1])
    assert t["label"] == "Test · Part 1" and t["reviews"] == len(w1)
    seen, done = _run(t["session_id"])
    assert {it["word_id"] for it in seen} <= w1
    # aynı gün yapılan ek test FSRS zamanlamasını bozmaz
    ev = appdb.q("SELECT rating FROM events WHERE session_id=?", (t["session_id"],))
    assert ev and all(e["rating"] is None for e in ev)
    q = session.start("quick", part_ids=[p1, p2])
    assert q["label"] == "Hızlı test · 2 part" and q["reviews"] == len(w1) + len(w2)
    item = session.next_item(q["session_id"])
    assert item["type"] == "speed" and item["word_id"] in (w1 | w2)
    assert item["session_progress"]["lives"] == 3


def test_existing_words_are_backfilled_into_parts(appdb):
    r = session.start("learn", limit=16)                      # part sisteminden önceki gibi
    _run(r["session_id"])
    appdb.x("DELETE FROM meta WHERE key='parts_backfilled'")
    assert P.backfill() == 2
    parts = P.list_parts()
    assert [p["total"] for p in parts] == [8, 8] and all(p["status"] == "tamam" for p in parts)   # 15+1 değil, dengeli
    assert P.backfill() == 0                                  # bir kez


def test_probable_words_are_verified_with_four_checks_inside_the_part(appdb):
    nxt = session.pick_new_words(15, include_probable=True)
    probable = nxt[:2]
    for wid in probable:
        appdb.x("UPDATE cards SET known_status='probable' WHERE word_id=?", (wid,))
    r = session.start("part")
    assert set(probable) <= set(P.remaining_words(r["part"]["id"]))
    seen, done = _run(r["session_id"])
    for wid in probable:
        checks = [it for it in seen if it["word_id"] == wid and it.get("verify")]
        assert len(checks) == len(session.VERIFY_CHECKS)
        assert not any(it["type"] == "intro" for it in seen if it["word_id"] == wid)
    card = appdb.q1("SELECT known_status, stage FROM cards WHERE word_id=?", (probable[0],))
    assert card["known_status"] == "verified" and card["stage"] == 6
    assert done["summary"]["part"]["finished"]
