from app import textutil as tu


def test_typo_tolerance_and_distance():
    assert tu.osa_distance("foster", "fotser") == 1  # bitişik yer değiştirme
    assert tu.osa_distance("vulnerable", "vulnerabel") == 1
    assert tu.typo_tolerance("cat") == 0
    assert tu.typo_tolerance("adapt") == 1
    assert tu.typo_tolerance("unprecedented") == 2


def test_verb_forms_and_detect():
    assert tu.verb_forms("stop")["past"] == "stopped"
    assert tu.verb_forms("refer")["past"] == "referred"
    assert tu.verb_forms("visit")["past"] == "visited"
    assert tu.verb_forms("offer")["past"] == "offered"
    assert tu.verb_forms("study")["s"] == "studies"
    assert tu.verb_forms("arise")["pp"] == "arisen"
    assert tu.verb_forms("bring about")["past"] == "brought about"
    assert tu.verb_forms("foster")["ing"] == "fostering"
    assert tu.verb_forms("diminish")["s"] == "diminishes"
    assert tu.detect_form("foster", "fostered", ["v"]) == "past"
    assert tu.detect_form("intervention", "interventions", ["n"]) == "pl"
    assert tu.detect_form("foster", "Foster", ["v"]) == "base"
    assert tu.inflect("hinder", "past", "v") == "hindered"
    assert tu.noun_plural("hypothesis") == "hypotheses"


def test_blank_and_contains():
    s = "Teachers can foster curiosity in students."
    assert tu.blank_sentence(s, "foster") == "Teachers can ---- curiosity in students."
    assert tu.contains_form(s, {"foster", "fostered"}) == "foster"
    assert tu.blank_sentence("Fostering trust takes time.", "foster") is None


def test_meaning_overlap():
    assert tu.meanings_overlap("geliştirmek, teşvik etmek", "teşvik etmek, özendirmek")
    assert not tu.meanings_overlap("savunmasız, kırılgan", "kaçınılmaz, önlenemez")
    assert tu.short_meaning("oluşturmak, teşkil etmek; sayılmak") == "oluşturmak, teşkil etmek"


def test_auto_rating_rules(appdb):
    from app import rating as R
    th = R.thresholds("typing")
    assert R.auto_rating("mcq_en_tr", False, "wrong", 500, 0)[0] == 1           # yanlış -> Again
    assert R.auto_rating("mcq_en_tr", True, "correct", th.slow + 5000, 0)[0] == 2  # yavaş -> Hard
    assert R.auto_rating("typing", True, "correct", 800, 1)[0] == 2              # ipucu -> Hard
    assert R.auto_rating("mcq_en_tr", True, "correct", 1000, 0)[0] == 3          # kolay modda hızlı -> Good
    assert R.auto_rating("typing", True, "correct", 300, 0)[0] == 4              # zor modda çok hızlı -> Easy
    assert R.auto_rating("typing", True, "typo", 300, 0)[0] == 3                 # yazım hatası en fazla Good


def test_grading_typo_confusion_form(appdb):
    from app import grading as G, words as W
    idx = W.index()
    adapt = idx["by_lemma"].get("adapt") or next(iter(idx["by_lemma"].values()))
    secret = {"type": "typing", "word_id": idx["by_lemma"]["foster"], "answer": "foster"}
    assert G.grade_text(secret, "foster").result == "correct"
    g = G.grade_text(secret, "fostre")
    assert g.correct and g.result == "typo"
    assert G.grade_text(secret, "to foster").result == "correct"
    g = G.grade_text(secret, "")
    assert not g.correct and g.error_type == "hatırlayamama"
    # listedeki başka bir kelime -> karıştırma (yazım hatası sayılmaz)
    vul = idx["by_lemma"]["vulnerable"]
    g = G.grade_text({"type": "typing", "word_id": vul, "answer": "vulnerable"}, "susceptible")
    assert not g.correct and g.confused_with == idx["by_lemma"]["susceptible"]
    assert g.error_type in ("karıştırma", "yakın anlam")
