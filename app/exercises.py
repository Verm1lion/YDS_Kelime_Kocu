"""Alıştırma yükleri (istemciye giden soru verisi + sunucuda saklanan doğru cevap)."""
from __future__ import annotations

import random
import re
import string
import uuid

from . import db
from . import distractors as D
from . import textutil as tu
from . import words as W

# Zorluk merdiveni (kullanıcı tanımı)
LADDER = ["mcq_en_tr", "mcq_tr_en", "tiles", "typing", "cloze", "synonym"]
LADDER_TR = {
    "mcq_en_tr": "İngilizce → Türkçe", "mcq_tr_en": "Türkçe → İngilizce", "tiles": "Harflerden kur",
    "typing": "Yaz", "cloze": "YDS boşluk doldurma", "synonym": "Eş anlamlısı", "context": "Bağlamda anlam",
    "distinguish": "Ayırt et", "speed": "Hızlı tur", "intro": "Tanıtım", "verify": "Doğrulama",
    "placement": "Seviye testi", "listen": "Dinle ve seç",
    "look_write": "Bak · kapat · yaz", "match": "Eşleştir", "syn_pick": "Eş anlamlısından bul",
}
POS_LABEL = {"n": "isim", "v": "fiil", "adj": "sıfat", "adv": "zarf", "conj": "bağlaç", "prep": "edat", "phr": "ifade"}

COMMON_LETTERS = "eeeaaaiioonnrrsstlcdmuph"


def _new_token() -> str:
    return uuid.uuid4().hex[:12]


def _word(word_id: int) -> dict:
    it = W.index()["items"].get(word_id)
    if it is None:
        W.invalidate_index()
        it = W.index()["items"].get(word_id)
    return it


def _pos_label(it: dict) -> str:
    return it.get("pos") or POS_LABEL.get(it["ppos"], "")


def base_payload(it: dict, typ: str, **kw) -> dict:
    p = {"token": _new_token(), "type": typ, "type_label": LADDER_TR.get(typ, typ), "word_id": it["id"],
         "stage": it.get("stage") or 0, "kind": it["kind"]}
    p.update(kw)
    return p


def feedback_info(word_id: int, example: dict | None = None) -> dict:
    """Cevaptan sonra gösterilen kısa bilgi (doğru cevap + örnek + mem)."""
    it = _word(word_id)
    ex = example or W.pick_example(word_id)
    mems = W.mnemonics(word_id)
    mem = next((m for m in mems if m["kind"] == "association"), mems[0] if mems else None)
    return {
        "display": it["display"], "meaning": it["meaning"], "pos": _pos_label(it),
        "synonyms": [x["w"] for x in W.synonyms_for(word_id, 4)],
        "example": ({"id": ex["id"], "en": ex["en"], "tr": ex.get("tr"), "form": ex.get("form"),
                     "source": ex["source"], "verified": ex["verified"]} if ex else None),
        "mnemonic": ({"id": mem["id"], "text": mem["text"], "source": mem["source"], "kind": mem["kind"],
                      "verified": mem["verified"]} if mem else None),
    }


# ---------------------------------------------------------------- tanıtım kartı
def intro(word_id: int, mem_kind: str = "association") -> tuple[dict, dict]:
    it = _word(word_id)
    w = W.get_word(word_id)
    info = W.info_fields(word_id)
    ex = W.pick_example(word_id)
    mems = W.mnemonics(word_id)
    user_mem = next((m for m in mems if m["source"] == "user"), None)
    chosen = user_mem
    if not chosen:
        chosen = next((m for m in mems if m["kind"] == mem_kind), None) or (mems[0] if mems else None)
    if mem_kind == "context" and not user_mem and ex:
        chosen = None  # bağlam türü: mem yerine örnek cümle vurgulanır
    fam = []
    if w.get("family_src"):
        fam += [f.strip() for f in w["family_src"].replace(";", ",").split(",") if f.strip()]
    for f in info.get("family") or []:
        if isinstance(f, dict) and f.get("w") and f["w"] not in fam:
            fam.append(f"{f['w']} ({f.get('tr', '')})" if f.get("tr") else f["w"])
    p = base_payload(it, "intro",
                     display=it["display"], pos=_pos_label(it), meaning=it["meaning"],
                     senses=info.get("senses") or [], family=fam[:5],
                     example=({"id": ex["id"], "en": ex["en"], "tr": ex.get("tr"), "form": ex.get("form"),
                               "source": ex["source"], "verified": ex["verified"]} if ex else None),
                     mnemonic=({"id": chosen["id"], "text": chosen["text"], "source": chosen["source"],
                                "kind": chosen["kind"], "verified": chosen["verified"]} if chosen else None),
                     mem_kind=mem_kind if not user_mem else "user",
                     osym=w.get("osym_evidence"), level=w.get("level"), tags=w.get("tags"),
                     synonyms=W.synonyms_for(word_id, 6), book=book_label(w),
                     variants=(w.get("features") or {}).get("variants") or [],
                     usage=usage_label(w), definition=info.get("definition"))
    secret = {"type": "intro", "word_id": word_id, "example_id": ex["id"] if ex else None,
              "mnemonic_id": chosen["id"] if chosen else None}
    if ex:
        W.mark_example_shown(ex["id"])
    return p, secret


def book_label(w: dict | None) -> str | None:
    """Kelime Ezberbozan listesindeyse kartta gösterilen etiket (ör. 'Ezberbozan · 3. gün')."""
    f = (w or {}).get("features") or {}
    if isinstance(f, str):
        f = db.jload(f, {})
    if f.get("garanti"):
        return "Garanti · ÖSYM'de çok çıkıyor"
    if not f.get("ezb_day"):
        return None
    return f"Ezberbozan · {f['ezb_day']}. gün" + (f" · {f['ezb_section']}" if f.get("ezb_section") else "")


def usage_label(w: dict | None) -> str | None:
    """Bağlaç/edat kalıbı türü: 'Bağlaç · Zıtlık' / 'Edat kalıbı · VERB + on'."""
    f = (w or {}).get("features") or {}
    if f.get("linker_type") or f.get("linker_group"):
        return " · ".join(x for x in ((f.get("linker_type") or "").title(), f.get("linker_group")) if x)
    if f.get("combo_type"):
        return "Edat kalıbı · " + f["combo_type"].replace("'", "")
    return None


# ---------------------------------------------------------------- öğretme katmanları (kodlama; sınama değil)
def look_write(word_id: int) -> tuple[dict, dict]:
    """Bak · kapat · yaz: kelime anlamı, eş anlamlıları ve sesiyle görünür; hazır olunca gizlenir ve ezberden yazılır
    (yazım ve biçim kafaya kazınır)."""
    it = _word(word_id)
    target = " ".join(it["display"].replace("...", " ").split())
    p = base_payload(it, "look_write", display=target, audio=target, prompt=it["short"] or it["meaning"],
                     full_meaning=it["meaning"], pos=_pos_label(it), synonyms=W.synonyms_for(word_id, 4),
                     answer_len=len(target))
    return p, {"type": "look_write", "word_id": word_id, "answer": target}


def syn_pick(word_id: int, pool_ids: list[int] | None = None, level: float = 0.5, rng=None) -> tuple[dict, dict] | None:
    """Eş anlamlısından bul: kelimenin eş/yakın anlamlıları verilir; az önce öğrenilen paket kelimeleri arasından
    hedef seçilir (YDS'de şıklar ve paragraf soruları eş anlamlılarla kurulur)."""
    rng = rng or random.Random()
    it = _word(word_id)
    syns = W.synonyms_for(word_id, 4)
    if not syns:
        return None
    idx = W.index()["items"]
    syn_keys = {tu.norm_en(x["w"]) for x in syns} | set(it["synonyms"]) | {it["lemma"]}

    def ok(c):
        return (c["id"] != word_id and c["lemma"] not in syn_keys and it["lemma"] not in c["synonyms"]
                and not (set(c["synonyms"]) & syn_keys) and not D.related(it, c))

    cands = [idx[w] for w in (pool_ids or []) if w in idx]
    cands = [c for c in cands if ok(c)]
    rng.shuffle(cands)
    chosen = cands[:3]
    if len(chosen) < 3:
        chosen += D.pick(word_id, 3 - len(chosen), mode="word", level=D.level_for_word(word_id, level), rng=rng,
                         exclude={c["id"] for c in chosen}, extra_filter=ok)
    if len(chosen) < 2:
        return None
    opts = [(word_id, it["display"])] + [(c["id"], c["display"]) for c in chosen[:3]]
    rng.shuffle(opts)
    correct = [i for i, (w, _) in enumerate(opts) if w == word_id][0]
    p = base_payload(it, "syn_pick", synonyms=syns, pos=_pos_label(it), options=[t for _, t in opts], correct=correct)
    return p, {"type": "syn_pick", "word_id": word_id, "correct": correct, "option_words": [w for w, _ in opts]}


def match(word_ids: list[int], filler_ids: list[int] | None = None, rng=None) -> tuple[dict, dict]:
    """Eşleştir: paketteki kelimeler ↔ Türkçe anlamları. Çiftler istemcide anında denetlenir (doğru çiftte kelime
    sesli okunur); sonuç kelime başına hata sayısıyla gelir. Dolgu kelimeler (önceden öğrenilenler) puan almaz."""
    rng = rng or random.Random()
    ids = list(dict.fromkeys(list(word_ids) + [w for w in (filler_ids or []) if w not in word_ids]))
    items = {w: _word(w) for w in ids}
    # anlamları çakışan çiftlerde (vanish / disappear) kısa anlam ayırt ettirmez: o kelimelerde tam anlam gösterilir
    full = {a for a in ids for b in ids if a != b and tu.meanings_overlap(items[a]["meaning"], items[b]["meaning"])}
    left, right, seen_tr = [], [], set()
    for w in ids:
        it = items[w]
        tr = (it["meaning"] if w in full else it["short"]) or it["meaning"] or ""
        if tr in seen_tr:                      # aynı anlam iki kez çıkmasın
            if w not in word_ids:
                continue
            tr = it["meaning"] or tr
        seen_tr.add(tr)
        left.append({"k": uuid.uuid4().hex[:8], "word_id": w, "text": it["display"]})
        right.append({"k": uuid.uuid4().hex[:8], "word_id": w, "text": tr})
    pairs = {a["k"]: b["k"] for a, b in zip(left, right)}
    rng.shuffle(left)
    rng.shuffle(right)
    first = _word(word_ids[0])
    p = base_payload(first, "match", left=left, right=right, pairs=pairs, targets=list(word_ids))
    return p, {"type": "match", "word_id": word_ids[0], "word_ids": list(word_ids)}


# ---------------------------------------------------------------- çoktan seçmeli
def mcq_en_tr(word_id: int, n_options: int = 5, level: float = 0.5, rng=None, typ: str = "mcq_en_tr") -> tuple[dict, dict]:
    rng = rng or random.Random()
    it = _word(word_id)
    ds = D.pick(word_id, n_options - 1, mode="meaning", level=D.level_for_word(word_id, level), rng=rng)
    opts = [(it["id"], it["short"] or it["meaning"])] + [(d["id"], d["short"]) for d in ds]
    rng.shuffle(opts)
    correct = [i for i, (wid, _) in enumerate(opts) if wid == word_id][0]
    p = base_payload(it, typ, prompt=it["display"], pos=_pos_label(it),
                     options=[t for _, t in opts], correct=correct)
    secret = {"type": typ, "word_id": word_id, "correct": correct, "option_words": [w for w, _ in opts]}
    return p, secret


def listen(word_id: int, n_options: int = 4, level: float = 0.5, rng=None) -> tuple[dict, dict]:
    """Dinle ve seç (Memrise tarzı): İngilizce kelime sesli okunur, yazısı gösterilmez; Türkçe anlamı seçilir."""
    p, s = mcq_en_tr(word_id, n_options, level, rng, typ="listen")
    p["audio"] = p.pop("prompt")
    p["prompt"] = None
    return p, s


def mcq_tr_en(word_id: int, n_options: int = 5, level: float = 0.5, rng=None) -> tuple[dict, dict]:
    rng = rng or random.Random()
    it = _word(word_id)
    ds = D.pick(word_id, n_options - 1, mode="word", level=D.level_for_word(word_id, level), rng=rng)
    opts = [(it["id"], it["display"])] + [(d["id"], d["display"]) for d in ds]
    rng.shuffle(opts)
    correct = [i for i, (wid, _) in enumerate(opts) if wid == word_id][0]
    p = base_payload(it, "mcq_tr_en", prompt=it["short"] or it["meaning"], full_meaning=it["meaning"],
                     pos=_pos_label(it), options=[t for _, t in opts], correct=correct)
    secret = {"type": "mcq_tr_en", "word_id": word_id, "correct": correct, "option_words": [w for w, _ in opts]}
    return p, secret


# ---------------------------------------------------------------- harf kutucukları
def tiles(word_id: int, rng=None) -> tuple[dict, dict]:
    rng = rng or random.Random()
    it = _word(word_id)
    target = " ".join(it["display"].lower().replace("...", " ").split())
    if " " in target:
        parts = target.split(" ")
        pool = list(parts)
        extras = ["up", "out", "off", "on", "in", "down", "with", "for", "over", "away", "back", "to"]
        extras = [e for e in extras if e not in parts]
        pool += rng.sample(extras, k=min(2, len(extras)))
        mode = "words"
    else:
        letters = [ch for ch in target]
        n_extra = 2 if len(letters) <= 6 else 3
        extra = [rng.choice(COMMON_LETTERS) for _ in range(n_extra)]
        pool = letters + extra
        mode = "letters"
    rng.shuffle(pool)
    p = base_payload(it, "tiles", prompt=it["short"] or it["meaning"], full_meaning=it["meaning"], pos=_pos_label(it),
                     tiles=pool, tile_mode=mode, answer_len=len(target))
    secret = {"type": "tiles", "word_id": word_id, "answer": target}
    return p, secret


# ---------------------------------------------------------------- yazma
def typing(word_id: int) -> tuple[dict, dict]:
    it = _word(word_id)
    target = " ".join(it["display"].replace("...", " ").split())
    p = base_payload(it, "typing", prompt=it["short"] or it["meaning"], full_meaning=it["meaning"],
                     pos=_pos_label(it), answer_len=len(target), first_letter=target[0],
                     hint_seq=[target[:k] for k in range(1, max(2, len(target) - 1))][:4])
    secret = {"type": "typing", "word_id": word_id, "answer": target}
    return p, secret


# ---------------------------------------------------------------- YDS boşluk doldurma
def _form_key_for(it: dict, ex: dict) -> str | None:
    return tu.detect_form(it["lemma"], ex.get("form") or "", it["pos_codes"] + (["v"] if it["kind"] == "phrasal" else []))


def cloze(word_id: int, level: float = 0.5, rng=None) -> tuple[dict, dict] | None:
    rng = rng or random.Random()
    it = _word(word_id)
    exs = [e for e in W.examples(word_id) if e.get("form") and "..." not in e["form"]]
    if not exs:
        return None
    # önce gerçek ÖSYM cümlesi (bir tur önde), sonra lemma biçimi, en az gösterilen
    exs.sort(key=lambda e: (e["times_shown"] - (1 if W.is_osym(e) else 0), tu.norm_en(e["form"]) != it["lemma"],
                            e["last_shown_at"] or ""))
    for ex in exs:
        blanked = tu.blank_sentence(ex["en"], ex["form"])
        if not blanked:
            continue
        fk = _form_key_for(it, ex)
        if fk is None:
            continue
        pos_code = "v" if fk in ("s", "past", "pp", "ing") else ("n" if fk == "pl" else it["ppos"])
        need = (lambda c, pc=pos_code: pc in c["pos_codes"]) if fk != "base" else None
        ds = D.pick(word_id, 4, mode="cloze", level=D.level_for_word(word_id, level), rng=rng, extra_filter=need)
        if len(ds) < 3:
            continue
        target_surface = tu.norm_en(ex["form"]) if fk != "base" else it["lemma"]
        opts = [(it["id"], target_surface)]
        for d in ds:
            opts.append((d["id"], tu.inflect(d["lemma"], fk, pos_code)))
        if blanked.lstrip().startswith("----"):
            opts = [(wid, t[:1].upper() + t[1:]) for wid, t in opts]
        rng.shuffle(opts)
        correct = [i for i, (wid, _) in enumerate(opts) if wid == word_id][0]
        W.mark_example_shown(ex["id"])
        p = base_payload(it, "cloze", sentence=blanked, options=[t for _, t in opts], correct=correct,
                         letters=list("ABCDE")[:len(opts)], n_words=len(ex["en"].split()),
                         translation=ex.get("tr"), example_id=ex["id"], full_sentence=ex["en"],
                         source=ex["source"], verified=ex["verified"])
        secret = {"type": "cloze", "word_id": word_id, "correct": correct, "option_words": [w for w, _ in opts],
                  "example_id": ex["id"], "n_words": len(ex["en"].split())}
        return p, secret
    return None


def context(word_id: int, level: float = 0.5, rng=None) -> tuple[dict, dict] | None:
    """Bağlamda anlam: cümlede vurgulu kelimenin Türkçe anlamı."""
    rng = rng or random.Random()
    it = _word(word_id)
    ex = W.pick_example(word_id)
    if not ex or not ex.get("form"):
        return None
    p, s = mcq_en_tr(word_id, 5, level, rng, typ="context")
    W.mark_example_shown(ex["id"])
    p.update({"sentence": ex["en"], "highlight": ex["form"], "translation": ex.get("tr"), "example_id": ex["id"],
              "n_words": len(ex["en"].split()), "source": ex["source"], "verified": ex["verified"]})
    s.update({"example_id": ex["id"], "n_words": len(ex["en"].split())})
    return p, s


# ---------------------------------------------------------------- eş anlamlı
def synonym(word_id: int, level: float = 0.5, rng=None) -> tuple[dict, dict] | None:
    rng = rng or random.Random()
    it = _word(word_id)
    syns = [s for s in it["synonyms"] if s and s != it["lemma"] and s not in it["family"]]
    if not syns:
        return None
    idx = W.index()
    # listedeki/öğrenilmiş eş anlamlılar önce, sonra yaygın olanlar
    def syn_score(s):
        wid = idx["by_lemma"].get(s)
        st = idx["items"][wid]["stage"] if wid else 0
        return (wid is not None) * 2 + (st or 0) * 0.3 + rng.random()
    syns.sort(key=syn_score, reverse=True)
    ans = syns[0]
    ans_id = idx["by_lemma"].get(ans)
    ans_item = idx["items"].get(ans_id) if ans_id else None

    def not_related_to_answer(c):
        if c["lemma"] in syns:
            return False
        if ans_item and D.related(ans_item, c):
            return False
        return True

    ds = D.pick(word_id, 4, mode="synonym", level=D.level_for_word(word_id, level), rng=rng,
                exclude={ans_id} if ans_id else None, extra_filter=not_related_to_answer)
    if len(ds) < 3:
        return None
    opts = [(None, ans)] + [(d["id"], d["display"]) for d in ds]
    rng.shuffle(opts)
    correct = [i for i, (wid, t) in enumerate(opts) if t == ans][0]
    ex = W.pick_example(word_id)
    p = base_payload(it, "synonym", prompt=it["display"], pos=_pos_label(it), options=[t for _, t in opts],
                     correct=correct, sentence=(ex["en"] if ex else None), highlight=(ex["form"] if ex else None),
                     example_id=(ex["id"] if ex else None), n_words=(len(ex["en"].split()) if ex else 0))
    secret = {"type": "synonym", "word_id": word_id, "correct": correct, "option_words": [w for w, _ in opts],
              "answer_text": ans, "n_words": (len(ex["en"].split()) if ex else 0)}
    return p, secret


# ---------------------------------------------------------------- ayırt etme
def distinguish(word_a: int, word_b: int, rng=None) -> tuple[dict, dict] | None:
    rng = rng or random.Random()
    a, b = _word(word_a), _word(word_b)
    if not a or not b:
        return None
    if D.related(a, b) or D.related(b, a):
        return None  # eş anlamlılarda 'ayırt etme' anlamsız: ikisi de doğru olabilir
    target, other = (a, b) if rng.random() < 0.5 else (b, a)
    exs = [e for e in W.examples(target["id"]) if e.get("form") and "..." not in e["form"]]
    sentence = None
    ex = None
    if exs and rng.random() < 0.7:
        ex = sorted(exs, key=lambda e: (e["times_shown"], e["id"]))[0]
        sentence = tu.blank_sentence(ex["en"], ex["form"])
    opts = [(target["id"], target["display"]), (other["id"], other["display"])]
    rng.shuffle(opts)
    correct = [i for i, (wid, _) in enumerate(opts) if wid == target["id"]][0]
    p = base_payload(target, "distinguish", prompt=target["short"] or target["meaning"], sentence=sentence,
                     options=[t for _, t in opts], correct=correct, pair=[a["id"], b["id"]],
                     n_words=(len(ex["en"].split()) if ex else 0),
                     translation=(ex.get("tr") if ex else None), full_sentence=(ex["en"] if ex else None),
                     source=(ex["source"] if ex else None),
                     compare=[{"display": a["display"], "meaning": a["meaning"]},
                              {"display": b["display"], "meaning": b["meaning"]}])
    secret = {"type": "distinguish", "word_id": target["id"], "correct": correct,
              "option_words": [w for w, _ in opts], "pair": [a["id"], b["id"]],
              "example_id": ex["id"] if ex else None, "n_words": (len(ex["en"].split()) if ex else 0)}
    return p, secret


# ---------------------------------------------------------------- hızlı tur
def speed(word_id: int, time_limit_ms: int, level: float = 0.4, rng=None) -> tuple[dict, dict]:
    p, s = mcq_en_tr(word_id, 4, level, rng, typ="speed")
    p["time_limit_ms"] = time_limit_ms
    s["time_limit_ms"] = time_limit_ms
    return p, s


def build(typ: str, word_id: int, level: float = 0.5, rng=None, **kw) -> tuple[dict, dict]:
    """İstenen tür kurulamazsa (örnek/eş anlamlı yoksa) uygun bir türe düşer."""
    rng = rng or random.Random()
    if typ == "intro":
        return intro(word_id, kw.get("mem_kind", "association"))
    if typ == "mcq_en_tr":
        return mcq_en_tr(word_id, kw.get("n_options", 5), level, rng)
    if typ == "listen":
        return listen(word_id, kw.get("n_options", 4), level, rng)
    if typ == "look_write":
        return look_write(word_id)
    if typ == "syn_pick":
        r = syn_pick(word_id, kw.get("pool_ids"), level, rng)
        return r or mcq_en_tr(word_id, 4, level, rng)
    if typ == "match":   # tek kelimelik bağlamda (ör. tekrar) eşleştirme kurulamaz
        return mcq_en_tr(word_id, 4, level, rng)
    if typ == "mcq_tr_en":
        return mcq_tr_en(word_id, kw.get("n_options", 5), level, rng)
    if typ == "tiles":
        return tiles(word_id, rng)
    if typ == "typing":
        return typing(word_id)
    if typ == "speed":
        return speed(word_id, kw.get("time_limit_ms", 6000), level, rng)
    if typ == "cloze":
        r = cloze(word_id, level, rng)
        if r:
            return r
        r = context(word_id, level, rng)
        if r:
            return r
        return mcq_en_tr(word_id, 5, level, rng)
    if typ == "context":
        r = context(word_id, level, rng)
        return r or mcq_en_tr(word_id, 5, level, rng)
    if typ == "synonym":
        r = synonym(word_id, level, rng)
        if r:
            return r
        r = cloze(word_id, level, rng)
        return r or mcq_tr_en(word_id, 5, level, rng)
    if typ == "distinguish" and kw.get("other"):
        r = distinguish(word_id, kw["other"], rng)
        if r:
            return r
    return mcq_en_tr(word_id, 5, level, rng)

# ---------------------------------------------------------------- "gerçek cevap" paneli (boşluk doldurma açıklaması)
_BE = {"is", "are", "am", "was", "were", "be", "been", "being"}
_HAVE = {"has", "have", "had", "having"}
_MODALS = {"can", "could", "may", "might", "must", "should", "will", "would", "shall", "cannot"}
_PREPS = {"by", "of", "in", "for", "without", "after", "before", "about", "on", "at", "from", "with", "into", "upon",
          "despite", "instead", "besides", "through"}
_DETS = {"a", "an", "the", "this", "that", "these", "those", "its", "their", "his", "her", "our", "your", "my", "such",
         "each", "every", "no", "any", "some", "many", "much", "several", "both"}
_TR_LIGHT = {"etmek", "olmak", "yapmak", "kılmak", "bulunmak", "getirmek", "vermek"}
_TR_WORD = re.compile(r"[0-9A-Za-zÇĞİÖŞÜçğıöşüÂâÎîÛû]+")


def _tr_stems(meaning: str | None) -> list[str]:
    """Anlamın içerik kelimelerinden Türkçe kökler: 'teşvik etmek, beslemek' → ['teşvik', 'besle'] (ünsüz yumuşaması için
    uzun kelimelerde son harf düşer: 'okuryazarlık' → 'okuryazarlı' → 'okuryazarlığı'nı yakalar)."""
    out: list[str] = []
    for group in tu.meaning_groups(meaning):
        for item in group:
            for w in re.split(r"[\s/()]+", tu.norm_tr(item)):
                w = w.strip("-'.,;:")
                if len(w) < 4 or w in _TR_LIGHT or w in tu._TR_STOP:
                    continue
                if w.endswith(("mek", "mak")) and len(w) >= 7:
                    w = w[:-3]
                out.append(w[:-1] if len(w) > 6 else w)
    return list(dict.fromkeys(out))


def tr_hit(translation: str | None, meaning: str | None) -> list[int] | None:
    """Çeviride kelimenin Türkçe karşılığının konumu [başlangıç, bitiş] (bulunamazsa None)."""
    if not translation or not meaning:
        return None
    low = tu.tr_lower(translation)
    spans = [(m.start(), m.end()) for m in _TR_WORD.finditer(translation)]
    for stem in _tr_stems(meaning):
        for s, e in spans:
            if low[s:e].startswith(stem):
                return [s, e]
    return None


def form_cue(sentence: str, fk: str | None, pos_code: str | None) -> str | None:
    """Boşluğun önündeki kelimeden dil bilgisi ipucu (ör. 'are ----' → şimdiki zaman, -ing)."""
    before = re.findall(r"[A-Za-z']+", (sentence.split("----")[0] if "----" in sentence else "").lower())
    prev = before[-1] if before else ""
    prev2 = before[-2] if len(before) > 1 else ""
    if fk == "ing":
        if prev in _BE:
            return f"“{prev} ----” → sürerlik/şimdiki zaman: fiil -ing alır."
        if prev in _PREPS:
            return f"“{prev} ----” → edattan sonra fiil -ing (isim-fiil) olur."
        return "Fiil burada -ing biçiminde (isim-fiil ya da sıfat-fiil)."
    if fk in ("past", "pp"):
        if prev in _HAVE or (prev == "been" and prev2 in _HAVE):
            return f"“{prev} ----” → have/has/had + fiilin 3. hâli (V3)."
        if prev in _BE:
            return f"“{prev} ----” → edilgen yapı: be + fiilin 3. hâli (V3)."
        return "Fiil geçmiş zaman / 3. hâl (V2/V3) biçiminde."
    if fk == "s":
        return "Özne tekil (he/she/it): geniş zamanda fiil -s alır."
    if fk == "pl":
        return "Boşluğa çoğul bir isim geliyor."
    if pos_code == "v":
        if prev == "to":
            return "“to ----” → mastar: fiilin yalın hâli."
        if prev in _MODALS:
            return f"“{prev} ----” → kip fiilinden sonra fiilin yalın hâli."
        return "Boşluğa fiilin yalın hâli geliyor."
    if pos_code == "n":
        return f"“{prev} ----” → belirleyiciden sonra isim gelir." if prev in _DETS else "Boşluğa bir isim geliyor."
    if pos_code == "adj":
        return "Boşluğa ismi niteleyen bir sıfat geliyor."
    if pos_code == "adv":
        return "Boşluğa fiili/sıfatı niteleyen bir zarf geliyor."
    return None


def explain_cloze(secret: dict, shown: dict) -> dict | None:
    """Boşluk doldurmadan sonra 'gerçek cevap' paneli: tam cümle, çeviri (karşılığı vurgulu), neden bu kelime
    (anlam + biçim ipucu, varsa ÖSYM notu) ve diğer şıkların anlamları. Tamamen yerel veriden (çevrimdışı)."""
    opts = shown.get("options") or []
    ci = secret.get("correct")
    sentence = shown.get("sentence") or ""
    if ci is None or not (0 <= ci < len(opts)) or "----" not in sentence:
        return None
    idx = W.index()["items"]
    words = list(secret.get("option_words") or [])
    answer = opts[ci]
    options = []
    for k, txt in enumerate(opts):
        it = idx.get(words[k]) if k < len(words) and words[k] else None
        options.append({"text": txt, "meaning": tu.short_meaning(it["meaning"], 3, 64) if it and it.get("meaning") else None,
                        "pos": _pos_label(it) if it else None, "correct": k == ci})
    tgt = idx.get(words[ci]) if ci < len(words) and words[ci] else None
    full = shown.get("full_sentence")
    if not full:
        parts = [a.strip() for a in answer.split("/")] if sentence.count("----") > 1 else [answer]
        full = sentence
        for a in parts:
            full = full.replace("----", a, 1)
    tr = shown.get("translation")
    if not tr:   # gerçek ÖSYM sorusu: aynı cümlenin çevirisi örneklerde olabilir
        row = db.q1("SELECT tr FROM examples WHERE en=? AND tr IS NOT NULL LIMIT 1", (full,))
        tr = row["tr"] if row else None
    fk = tu.detect_form(tgt["lemma"], answer, tgt["pos_codes"] + (["v"] if tgt["kind"] == "phrasal" else [])) if tgt else None
    pos_code = "v" if fk in ("s", "past", "pp", "ing") else ("n" if fk == "pl" else (tgt["ppos"] if tgt else None))
    pos_of = {o["pos"] for o in options if o["pos"]}
    return {"answer": answer, "meaning": tgt["meaning"] if tgt else None, "pos": _pos_label(tgt) if tgt else None,
            "full_sentence": full, "translation": tr, "tr_hit": tr_hit(tr, tgt["meaning"] if tgt else None),
            "form_cue": form_cue(sentence, fk, pos_code), "note": shown.get("note"), "options": options,
            "same_kind": len(pos_of) == 1 and len(options) > 2}


# ---------------------------------------------------------------- gerçek ÖSYM sorusu (haftalık test)
def osym(q: dict) -> tuple[dict, dict]:
    it = _word(q["word_id"])
    idx = W.index()["by_lemma"]
    opts = q["options"]
    correct = "ABCDE".index(q["answer"]) if q.get("answer") in list("ABCDE") else 0
    words = [idx.get(tu.norm_en(o)) for o in opts]
    words[correct] = q["word_id"]
    p = base_payload(it, "osym", sentence=q["stem"], options=opts, correct=correct, letters=list("ABCDE"),
                     n_words=len(q["stem"].split()), source_label=f"ÖSYM {q.get('session', '')} · soru {q.get('no', '')}",
                     note=q.get("note"))
    p["type_label"] = "Gerçek ÖSYM sorusu"
    secret = {"type": "osym", "word_id": q["word_id"], "correct": correct, "option_words": words,
              "n_words": len(q["stem"].split())}
    return p, secret
