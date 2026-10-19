"""Akıllı çeldirici seçimi.

Puanlama: aynı sözcük türü + benzer yazılış (bigram/OSA) + geçmişte karıştırılanlar + (zor seviyede)
anlamca yakın ama yanlış olanlar. Zorluk seviyesi (0-1) yükseldikçe benzer adaylar daha olası seçilir.
Kesin kurallar: doğru cevapla anlam çakışan / eş anlamlı olan / aynı aileden olan aday seçilmez.
"""
from __future__ import annotations

import math
import random
from typing import Iterable

from . import db
from . import textutil as tu
from . import words as W


def _bigrams(w: str) -> set[str]:
    w = f"^{w}$"
    return {w[i:i + 2] for i in range(len(w) - 1)}


_confusion_cache: dict[int, dict[int, int]] = {}


def confusion_counts(word_id: int) -> dict[int, int]:
    if word_id in _confusion_cache:
        return _confusion_cache[word_id]
    rows = db.q("""SELECT CASE WHEN word_id=? THEN confused_with ELSE word_id END AS other, COUNT(*) n
                   FROM events WHERE (word_id=? AND confused_with IS NOT NULL) OR confused_with=?
                   GROUP BY other""", (word_id, word_id, word_id))
    d = {r["other"]: r["n"] for r in rows if r["other"]}
    _confusion_cache[word_id] = d
    return d


def clear_cache(word_id: int | None = None) -> None:
    if word_id is None:
        _confusion_cache.clear()
    else:
        _confusion_cache.pop(word_id, None)


def related(t: dict, c: dict) -> bool:
    """Aday, hedefle anlamca/biçimce 'doğru' sayılabilecek kadar ilişkili mi?"""
    if c["id"] == t["id"]:
        return True
    if c["lemma"] in t["family"] or t["lemma"] in c["family"]:
        return True
    if c["lemma"].startswith(t["lemma"]) or t["lemma"].startswith(c["lemma"]):
        return True
    if c["lemma"] in t["synonyms"] or t["lemma"] in c["synonyms"]:
        return True
    if t["phrases"] & c["phrases"]:
        return True
    if t["toks5"] & c["toks5"]:  # tu.meanings_overlap ile aynı kural, önceden hesaplanmış
        return True
    return False


def score_candidates(t: dict, cands: Iterable[dict], mode: str) -> list[tuple[float, dict]]:
    conf = confusion_counts(t["id"])
    tb = t.get("bg") or _bigrams(t["lemma"])
    out = []
    for c in cands:
        if related(t, c):
            continue
        s = 0.0
        same_pos = c["ppos"] == t["ppos"] or bool(set(c["pos_codes"]) & set(t["pos_codes"]))
        if mode in ("cloze", "synonym"):
            if not same_pos or c["kind"] != t["kind"] and "phrasal" in (c["kind"], t["kind"]):
                continue
        s += 1.0 if same_pos else 0.0
        cb = c.get("bg") or _bigrams(c["lemma"])
        inter = len(tb & cb)
        jac = inter / max(1, len(tb) + len(cb) - inter)
        s += 2.0 * jac
        s += 0.4 * max(0.0, 1 - abs(len(c["lemma"]) - len(t["lemma"])) / 6)
        if conf.get(c["id"]):
            s += 1.5 + 0.5 * min(conf[c["id"]], 4)
        if c["kind"] == t["kind"]:
            s += 0.3
        # öğrenilmiş kelimeler çeldirici olarak daha öğretici
        if (c.get("stage") or 0) >= 1:
            s += 0.4
        # sıklık yakınlığı (YDS şıkları benzer düzeyde)
        if t["zipf"] and c["zipf"]:
            s += 0.3 * max(0.0, 1 - abs(t["zipf"] - c["zipf"]) / 2)
        out.append((s, c))
    return out


def pick(target_id: int, n: int, mode: str = "meaning", level: float = 0.5,
         exclude: set[int] | None = None, rng: random.Random | None = None,
         extra_filter=None) -> list[dict]:
    """mode: 'meaning' (Türkçe şıklar), 'word' (İngilizce şıklar), 'cloze', 'synonym'"""
    rng = rng or random.Random()
    idx = W.index()["items"]
    t = idx.get(target_id)
    if not t:
        return []
    exclude = set(exclude or ())
    cands = [c for cid, c in idx.items() if cid not in exclude and cid != target_id and c["meaning"]]
    if extra_filter:
        cands = [c for c in cands if extra_filter(c)]
    scored = score_candidates(t, cands, mode)
    if not scored:
        return []
    scored.sort(key=lambda x: -x[0])
    pool = scored[:80]
    lam = 0.6 + 5.0 * max(0.0, min(1.0, level))
    chosen: list[dict] = []
    seen_text: set[str] = {tu.norm_tr(t["short"])} if mode == "meaning" else {t["lemma"]}
    while pool and len(chosen) < n:
        weights = [math.exp(lam * (s - pool[0][0])) for s, _ in pool]
        tot = sum(weights)
        r = rng.random() * tot
        acc = 0.0
        pick_i = 0
        for i, wv in enumerate(weights):
            acc += wv
            if acc >= r:
                pick_i = i
                break
        _, c = pool.pop(pick_i)
        key = tu.norm_tr(c["short"]) if mode == "meaning" else c["lemma"]
        if key in seen_text:
            continue
        # seçilenler kendi aralarında da çakışmasın
        if any(related(c, o) for o in chosen):
            continue
        seen_text.add(key)
        chosen.append(c)
    return chosen


def level_for_word(word_id: int, base_level: float) -> float:
    """Kelime ilerledikçe (merdiven/kararlılık) çeldiriciler zorlaşır."""
    t = W.index()["items"].get(word_id)
    if not t:
        return base_level
    stage = t.get("stage") or 0
    stab = t.get("stability") or 0
    bump = 0.06 * stage + (0.15 if stab and stab > 10 else 0.0)
    return max(0.0, min(1.0, base_level + bump - 0.15))
