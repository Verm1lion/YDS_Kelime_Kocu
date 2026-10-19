"""Cevap değerlendirme ve hata türü sınıflandırması.

Hata türleri:
  hatırlayamama, karıştırma, yazım hatası, yakın anlam, yön farkı, bağlamda tanıyamama,
  yavaş doğru (kırılgan), şans doğrusu (analizde geriye dönük), biçim (aile biçimi yazıldı)
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import db
from . import textutil as tu
from . import words as W

EN_TR_TYPES = {"mcq_en_tr", "listen", "context", "speed", "placement", "verify"}
PRODUCTION_TYPES = {"mcq_tr_en", "typing", "tiles", "look_write", "syn_pick"}
CONTEXT_TYPES = {"cloze", "context", "osym"}


@dataclass
class Grade:
    correct: bool
    result: str                 # correct | typo | form | wrong | dontknow | timeout
    answer_text: str = ""
    expected_text: str = ""
    confused_with: int | None = None
    error_type: str | None = None
    detail: dict = field(default_factory=dict)


def _near_meaning(t: dict, c: dict) -> bool:
    if t["synonyms"] & c["synonyms"]:
        return True
    if c["lemma"] in t["synonyms"] or t["lemma"] in c["synonyms"]:
        return True
    if tu.meanings_overlap(t["meaning"], c["meaning"]):
        return True
    t1 = [x for x in t["tokens"] if " " not in x and len(x) >= 5]
    t2 = [x for x in c["tokens"] if " " not in x and len(x) >= 5]
    return any(tu.common_prefix(a, b) >= 5 for a in t1 for b in t2)


def _orth_close(a: str, b: str) -> bool:
    return tu.osa_distance(a, b, max_d=3) <= (2 if max(len(a), len(b)) >= 6 else 1)


def grade_choice(secret: dict, answer_index: int | None, dont_know: bool = False, timeout: bool = False) -> Grade:
    idx = W.index()["items"]
    t = idx.get(secret["word_id"])
    opts = secret.get("option_words") or []
    exp_i = secret["correct"]
    if dont_know or answer_index is None or answer_index < 0:
        return Grade(False, "timeout" if timeout else "dontknow", "", str(exp_i), error_type="hatırlayamama")
    if answer_index == exp_i:
        return Grade(True, "correct", str(answer_index), str(exp_i))
    other = opts[answer_index] if 0 <= answer_index < len(opts) else None
    g = Grade(False, "wrong", str(answer_index), str(exp_i), confused_with=other)
    c = idx.get(other) if other else None
    if c and t:
        g.error_type = "yakın anlam" if _near_meaning(t, c) else "karıştırma"
        g.detail["orth_close"] = _orth_close(t["lemma"], c["lemma"])
    else:
        g.error_type = "karıştırma"
    return g


def grade_text(secret: dict, text: str | None, dont_know: bool = False) -> Grade:
    idx = W.index()
    t = idx["items"].get(secret["word_id"])
    expected = secret["answer"]
    exp_n = tu.norm_answer(expected)
    ans_n = tu.norm_answer(text or "")
    if dont_know or not ans_n or ans_n in ("?", "bilmiyorum"):
        return Grade(False, "dontknow", text or "", expected, error_type="hatırlayamama")
    if ans_n == exp_n:
        return Grade(True, "correct", text or "", expected)
    other_id = idx["by_lemma"].get(ans_n) or idx["by_lemma"].get(tu.norm_en(text or ""))
    if other_id and other_id != secret["word_id"]:
        c = idx["items"][other_id]
        et = "yakın anlam" if (t and _near_meaning(t, c)) else "karıştırma"
        return Grade(False, "wrong", text or "", expected, confused_with=other_id, error_type=et)
    if t and (ans_n in {tu.norm_answer(f) for f in t["family"]} or
              ans_n in {tu.norm_answer(f) for f in tu.all_forms(t["lemma"], t["pos_codes"])}):
        return Grade(True, "form", text or "", expected, error_type="biçim")
    d = tu.osa_distance(ans_n, exp_n, max_d=3)
    if d <= tu.typo_tolerance(exp_n):
        return Grade(True, "typo", text or "", expected, error_type="yazım hatası", detail={"distance": d})
    if t and ans_n in {tu.norm_answer(s) for s in t["synonyms"]}:
        return Grade(False, "wrong", text or "", expected, error_type="yakın anlam")
    sim = tu.similarity(ans_n, exp_n)
    return Grade(False, "wrong", text or "", expected, error_type="hatırlayamama" if sim < 0.5 else "yanlış yazım",
                 detail={"similarity": round(sim, 2)})


def refine_error(word_id: int, exercise: str, g: Grade) -> None:
    """Yön farkı ve bağlam hatalarını geçmişe bakarak belirler."""
    if g.correct or g.error_type in ("yazım hatası",):
        return
    if exercise in PRODUCTION_TYPES:
        last = db.q1("""SELECT correct FROM events WHERE word_id=? AND exercise IN ('mcq_en_tr','listen','context','speed')
                        ORDER BY id DESC LIMIT 1""", (word_id,))
        if last and last["correct"] == 1 and g.error_type in ("hatırlayamama", "yanlış yazım", None):
            g.error_type = "yön farkı"
    elif exercise in CONTEXT_TYPES:
        last = db.q1("""SELECT correct FROM events WHERE word_id=? AND exercise IN ('mcq_en_tr','listen','speed')
                        ORDER BY id DESC LIMIT 1""", (word_id,))
        if last and last["correct"] == 1 and g.error_type in ("hatırlayamama", "karıştırma", None):
            g.error_type = "bağlamda tanıyamama"
