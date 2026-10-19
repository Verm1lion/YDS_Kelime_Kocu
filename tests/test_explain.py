"""Boşluk doldurmadan sonra 'gerçek cevap' paneli: çeviri (karşılığı vurgulu), neden bu kelime, diğer şıklar."""
import random

from app import exercises as X, session


def _cloze_word(appdb):
    for r in appdb.q("""SELECT w.id FROM words w JOIN examples e ON e.word_id=w.id WHERE w.status='active'
                        AND w.kind='word' AND e.tr IS NOT NULL GROUP BY w.id ORDER BY w.order_index LIMIT 60"""):
        built = X.cloze(r["id"], 0.5, random.Random(3))
        if built:
            return built
    raise AssertionError("boşluk doldurma kurulamadı")


def test_explanation_has_translation_reason_and_other_options(appdb):
    p, sec = _cloze_word(appdb)
    x = X.explain_cloze(sec, p)
    ans = p["options"][sec["correct"]]
    assert x["answer"] == ans and ans.lower() in x["full_sentence"].lower()
    assert x["translation"] and x["meaning"]
    assert len(x["options"]) == len(p["options"]) and sum(o["correct"] for o in x["options"]) == 1
    assert all(o["meaning"] for o in x["options"])                       # her şıkkın anlamı (neden olmaz)
    if x["tr_hit"]:
        s, e = x["tr_hit"]
        assert 0 <= s < e <= len(x["translation"])


def test_grammar_cues_and_turkish_highlight():
    assert "-ing" in X.form_cue("Scientists believe our surroundings are ---- allergies.", "ing", "v")
    assert "V3" in X.form_cue("The results have ---- the theory.", "pp", "v")
    assert "edilgen" in X.form_cue("The rules were ---- in 1990.", "past", "v")
    assert "yalın" in X.form_cue("It is vital to ---- the risks.", "base", "v")
    assert "isim" in X.form_cue("This led to a ---- in prices.", "base", "n")
    tr = "Pek çok bilim insanı, steril ortamların alerjileri körüklediğine inanıyor."
    s, e = X.tr_hit(tr, "teşvik etmek, beslemek, körüklemek")
    assert tr[s:e] == "körüklediğine"


def test_session_cloze_answer_always_brings_the_panel(appdb):
    r = session.start("learn", limit=2)
    sid = r["session_id"]
    item, seen = session.next_item(sid), 0
    results = []
    while item and item.get("type") != "done" and seen < 150:
        s = session.get(sid)
        sec = s.pending[item["token"]]["secret"]
        body = {"token": item["token"], "total_ms": 900, "first_key_ms": 500, "hints": 0}
        if item["type"] in ("typing", "tiles", "look_write"):
            body["text"] = sec["answer"]
        elif item["type"] == "match":
            body["mistakes"] = {}
        elif "options" in item:
            wrong = item["type"] == "cloze" and not any(t == "wrong" for t, _ in results)
            body["choice"] = (item["correct"] + 1) % len(item["options"]) if wrong else item["correct"]
        res = session.answer(sid, item["token"], body)
        if item["type"] == "cloze":
            results.append(("wrong" if not res["correct"] else "right", res))
        else:
            assert "explain" not in res                                 # yalnızca boşluk doldurmada
        item, seen = res["next"], seen + 1
    kinds = {k for k, _ in results}
    assert {"wrong", "right"} <= kinds, "hem yanlış hem doğru boşluk doldurma cevabı görülmeli"
    for _, res in results:
        assert res["explain"] and res["explain"]["answer"] and res["explain"]["options"]
