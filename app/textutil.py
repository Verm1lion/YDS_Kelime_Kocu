"""Metin yardımcıları: normalizasyon, yazım-hatası toleransı, anlam parçalama,
İngilizce çekim (çeldiricileri cümledeki biçime uydurmak için), morfoloji."""
from __future__ import annotations

import re
import unicodedata

# ---------------------------------------------------------------- normalizasyon
_APOS = str.maketrans({"’": "'", "‘": "'", "`": "'", "´": "'", "–": "-", "—": "-"})


def norm_en(s: str | None) -> str:
    if not s:
        return ""
    s = s.translate(_APOS).strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def norm_answer(s: str | None) -> str:
    """Yazma cevabı için: 'to ' öneki, noktalama, tire/boşluk farkı."""
    s = norm_en(s)
    s = re.sub(r"[.,;:!?\"()]", "", s)
    if s.startswith("to ") and len(s) > 3:
        s = s[3:]
    s = s.replace("-", " ")
    return re.sub(r"\s+", " ", s).strip()


def tr_lower(s: str) -> str:
    return s.replace("İ", "i").replace("I", "ı").lower()


def norm_tr(s: str | None) -> str:
    if not s:
        return ""
    s = tr_lower(s.translate(_APOS).strip())
    return re.sub(r"\s+", " ", s)


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


# ---------------------------------------------------------------- mesafe
def osa_distance(a: str, b: str, max_d: int | None = None) -> int:
    """Optimal string alignment (Damerau-Levenshtein, bitişik yer değiştirme dahil)."""
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if max_d is not None and abs(la - lb) > max_d:
        return max_d + 1
    prev2: list[int] | None = None
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        best = cur[0]
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and prev2 is not None and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                v = min(v, prev2[j - 2] + 1)
            cur[j] = v
            if v < best:
                best = v
        if max_d is not None and best > max_d:
            return max_d + 1
        prev2, prev = prev, cur
    return prev[lb]


def typo_tolerance(target: str) -> int:
    n = len(target.replace(" ", ""))
    if n <= 3:
        return 0
    if n <= 6:
        return 1
    return 2


def similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    d = osa_distance(a, b)
    return 1.0 - d / max(len(a), len(b))


def common_prefix(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


# ---------------------------------------------------------------- Türkçe anlam
_PAREN = re.compile(r"\([^)]*\)")


def meaning_groups(meaning: str | None) -> list[list[str]]:
    """'oluşturmak, teşkil etmek; sayılmak' -> [['oluşturmak','teşkil etmek'],['sayılmak']]"""
    if not meaning:
        return []
    groups = []
    for g in meaning.split(";"):
        items = [i.strip() for i in g.split(",") if i.strip()]
        if items:
            groups.append(items)
    return groups


def short_meaning(meaning: str | None, max_items: int = 2, max_len: int = 42) -> str:
    groups = meaning_groups(meaning)
    if not groups:
        return meaning or ""
    items = groups[0][:max_items]
    s = ", ".join(items)
    if len(s) > max_len and len(items) > 1:
        s = items[0]
    return s


_TR_STOP = {"bir", "ve", "ile", "olarak", "şekilde", "biçimde", "olmak", "etmek", "yapmak", "-den", "-dan",
            "den", "dan", "ya", "da", "de", "veya", "ait", "için", "gibi", "çok", "en", "daha", "şey", "kimse"}


def meaning_tokens(meaning: str | None) -> set[str]:
    """Anlam çakışması kontrolü için anahtar parçalar (tam ifade + içerik kelimeleri)."""
    out: set[str] = set()
    for g in meaning_groups(meaning):
        for item in g:
            t = norm_tr(_PAREN.sub("", item)).strip(" -")
            if not t:
                continue
            out.add(t)
            for w in re.split(r"[\s/]+", t):
                w = w.strip("-'")
                if len(w) >= 4 and w not in _TR_STOP:
                    out.add(w)
    return out


def meaning_phrases(meaning: str | None) -> set[str]:
    out = set()
    for g in meaning_groups(meaning):
        for item in g:
            t = norm_tr(_PAREN.sub("", item)).strip(" -")
            if t:
                out.add(t)
    return out


def meanings_overlap(m1: str | None, m2: str | None) -> bool:
    p1, p2 = meaning_phrases(m1), meaning_phrases(m2)
    if p1 & p2:
        return True
    # tek kelimelik anlamlarda kök çakışması ("artırmak" / "artırmak, çoğaltmak")
    t1 = {t for t in meaning_tokens(m1) if " " not in t and len(t) >= 5}
    t2 = {t for t in meaning_tokens(m2) if " " not in t and len(t) >= 5}
    return bool(t1 & t2)


# ---------------------------------------------------------------- POS
POS_MAP = {
    "isim": "n", "fiil": "v", "sıfat": "adj", "zarf": "adv", "bağlaç": "conj", "edat": "prep",
    "öbek fiil": "v", "phrasal": "v", "ifade": "phr", "zamir": "pron",
}
POS_TR = {"n": "isim", "v": "fiil", "adj": "sıfat", "adv": "zarf", "conj": "bağlaç", "prep": "edat", "phr": "ifade", "pron": "zamir"}


def pos_list(pos: str | None) -> list[str]:
    if not pos:
        return []
    out = []
    for p in re.split(r"[/,]", pos):
        p = norm_tr(p)
        code = POS_MAP.get(p)
        if code and code not in out:
            out.append(code)
    return out


def primary_pos(pos: str | None) -> str:
    lst = pos_list(pos)
    return lst[0] if lst else "n"


# ---------------------------------------------------------------- İngilizce çekim
IRREGULAR = {
    # lemma: (past, past participle, 3sg optional)
    "arise": ("arose", "arisen"), "awake": ("awoke", "awoken"), "bear": ("bore", "borne"),
    "beat": ("beat", "beaten"), "become": ("became", "become"), "begin": ("began", "begun"),
    "bend": ("bent", "bent"), "bind": ("bound", "bound"), "bite": ("bit", "bitten"),
    "bleed": ("bled", "bled"), "blow": ("blew", "blown"), "break": ("broke", "broken"),
    "breed": ("bred", "bred"), "bring": ("brought", "brought"), "build": ("built", "built"),
    "burst": ("burst", "burst"), "buy": ("bought", "bought"), "cast": ("cast", "cast"),
    "catch": ("caught", "caught"), "choose": ("chose", "chosen"), "cling": ("clung", "clung"),
    "come": ("came", "come"), "cost": ("cost", "cost"), "creep": ("crept", "crept"),
    "cut": ("cut", "cut"), "deal": ("dealt", "dealt"), "dig": ("dug", "dug"),
    "do": ("did", "done"), "draw": ("drew", "drawn"), "drink": ("drank", "drunk"),
    "drive": ("drove", "driven"), "eat": ("ate", "eaten"), "fall": ("fell", "fallen"),
    "feed": ("fed", "fed"), "feel": ("felt", "felt"), "fight": ("fought", "fought"),
    "find": ("found", "found"), "flee": ("fled", "fled"), "fly": ("flew", "flown"),
    "forbid": ("forbade", "forbidden"), "forecast": ("forecast", "forecast"),
    "foresee": ("foresaw", "foreseen"), "forget": ("forgot", "forgotten"),
    "forgive": ("forgave", "forgiven"), "forgo": ("forwent", "forgone"), "forego": ("forewent", "foregone"),
    "forsake": ("forsook", "forsaken"), "freeze": ("froze", "frozen"), "get": ("got", "gotten"),
    "give": ("gave", "given"), "go": ("went", "gone"), "grind": ("ground", "ground"),
    "grow": ("grew", "grown"), "hang": ("hung", "hung"), "have": ("had", "had"),
    "hear": ("heard", "heard"), "hide": ("hid", "hidden"), "hit": ("hit", "hit"),
    "hold": ("held", "held"), "hurt": ("hurt", "hurt"), "keep": ("kept", "kept"),
    "know": ("knew", "known"), "lay": ("laid", "laid"), "lead": ("led", "led"),
    "lean": ("leaned", "leaned"), "leave": ("left", "left"), "lend": ("lent", "lent"),
    "let": ("let", "let"), "lie": ("lay", "lain"), "lose": ("lost", "lost"),
    "make": ("made", "made"), "mean": ("meant", "meant"), "meet": ("met", "met"),
    "mislead": ("misled", "misled"), "mistake": ("mistook", "mistaken"),
    "outdo": ("outdid", "outdone"), "overcome": ("overcame", "overcome"),
    "override": ("overrode", "overridden"), "overrun": ("overran", "overrun"),
    "oversee": ("oversaw", "overseen"), "overtake": ("overtook", "overtaken"),
    "overthrow": ("overthrew", "overthrown"), "pay": ("paid", "paid"), "put": ("put", "put"),
    "quit": ("quit", "quit"), "read": ("read", "read"), "rid": ("rid", "rid"),
    "ride": ("rode", "ridden"), "ring": ("rang", "rung"), "rise": ("rose", "risen"),
    "run": ("ran", "run"), "say": ("said", "said"), "see": ("saw", "seen"),
    "seek": ("sought", "sought"), "sell": ("sold", "sold"), "send": ("sent", "sent"),
    "set": ("set", "set"), "shake": ("shook", "shaken"), "shed": ("shed", "shed"),
    "shine": ("shone", "shone"), "shoot": ("shot", "shot"), "show": ("showed", "shown"),
    "shrink": ("shrank", "shrunk"), "shut": ("shut", "shut"), "sing": ("sang", "sung"),
    "sink": ("sank", "sunk"), "sit": ("sat", "sat"), "sleep": ("slept", "slept"),
    "slide": ("slid", "slid"), "speak": ("spoke", "spoken"), "spend": ("spent", "spent"),
    "spin": ("spun", "spun"), "split": ("split", "split"), "spread": ("spread", "spread"),
    "spring": ("sprang", "sprung"), "stand": ("stood", "stood"), "steal": ("stole", "stolen"),
    "stick": ("stuck", "stuck"), "sting": ("stung", "stung"), "strike": ("struck", "struck"),
    "strive": ("strove", "striven"), "swear": ("swore", "sworn"), "sweep": ("swept", "swept"),
    "swim": ("swam", "swum"), "swing": ("swung", "swung"), "take": ("took", "taken"),
    "teach": ("taught", "taught"), "tear": ("tore", "torn"), "tell": ("told", "told"),
    "think": ("thought", "thought"), "throw": ("threw", "thrown"), "thrust": ("thrust", "thrust"),
    "tread": ("trod", "trodden"), "undergo": ("underwent", "undergone"),
    "underlie": ("underlay", "underlain"), "understand": ("understood", "understood"),
    "undertake": ("undertook", "undertaken"), "undo": ("undid", "undone"),
    "uphold": ("upheld", "upheld"), "upset": ("upset", "upset"), "wake": ("woke", "woken"),
    "wear": ("wore", "worn"), "weave": ("wove", "woven"), "weep": ("wept", "wept"),
    "win": ("won", "won"), "wind": ("wound", "wound"), "withdraw": ("withdrew", "withdrawn"),
    "withhold": ("withheld", "withheld"), "withstand": ("withstood", "withstood"),
    "write": ("wrote", "written"), "outgrow": ("outgrew", "outgrown"), "offset": ("offset", "offset"),
    "inlay": ("inlaid", "inlaid"), "forbear": ("forbore", "forborne"), "befall": ("befell", "befallen"),
    "beset": ("beset", "beset"), "behold": ("beheld", "beheld"), "broadcast": ("broadcast", "broadcast"),
}

VOWELS = set("aeiou")
_STRESSED_ENDINGS = ("fer", "cur", "mit", "pel", "trol", "gret", "quip", "quit", "bed")
_NO_DOUBLE = {"offer", "differ", "suffer", "proffer", "limit", "vomit", "summit"}


def _double_final(v: str) -> bool:
    """Son ünsüzün çiftlenmesi: stop->stopped, refer->referred, ama visit->visited."""
    if len(v) < 3 or v in _NO_DOUBLE:
        return False
    a, b, c = v[-3], v[-2], v[-1]
    if c in "wxy" or c in VOWELS or b not in VOWELS or a in VOWELS:
        return False
    if len(v) <= 4:  # tek heceli: stop, plan, drop, ban
        return True
    if v == "deter":
        return True
    return v.endswith(_STRESSED_ENDINGS)


def verb_forms(lemma: str) -> dict[str, str]:
    v = lemma
    if " " in v:  # öbek fiil: ilk kelime çekimlenir
        head, rest = v.split(" ", 1)
        f = verb_forms(head)
        return {k: f"{w} {rest}" for k, w in f.items()}
    if v.endswith("oo"):
        s3 = v + "s"
    elif v.endswith(("s", "sh", "ch", "x", "z", "o")):
        s3 = v + "es"
    elif v.endswith("y") and len(v) > 1 and v[-2] not in VOWELS:
        s3 = v[:-1] + "ies"
    else:
        s3 = v + "s"
    if v in IRREGULAR:
        past, pp = IRREGULAR[v]
    else:
        if v.endswith("e"):
            past = v + "d"
        elif v.endswith("y") and len(v) > 1 and v[-2] not in VOWELS:
            past = v[:-1] + "ied"
        elif _double_final(v):
            past = v + v[-1] + "ed"
        else:
            past = v + "ed"
        pp = past
    if v.endswith("ie"):
        ing = v[:-2] + "ying"
    elif v.endswith("e") and not v.endswith(("ee", "ye", "oe")) and len(v) > 2:
        ing = v[:-1] + "ing"
    elif _double_final(v) and v not in IRREGULAR:
        ing = v + v[-1] + "ing"
    else:
        ing = v + "ing"
    return {"base": v, "s": s3, "past": past, "pp": pp, "ing": ing}


def noun_plural(n: str) -> str:
    if " " in n:
        head, last = n.rsplit(" ", 1)
        return f"{head} {noun_plural(last)}"
    irregular = {"phenomenon": "phenomena", "criterion": "criteria", "analysis": "analyses",
                 "hypothesis": "hypotheses", "crisis": "crises", "thesis": "theses", "basis": "bases",
                 "datum": "data", "medium": "media", "stimulus": "stimuli", "nucleus": "nuclei",
                 "fungus": "fungi", "bacterium": "bacteria", "curriculum": "curricula",
                 "index": "indices", "appendix": "appendices", "child": "children", "man": "men",
                 "woman": "women", "foot": "feet", "tooth": "teeth", "mouse": "mice", "person": "people",
                 "diagnosis": "diagnoses", "synthesis": "syntheses", "emphasis": "emphases",
                 "consensus": "consensuses", "species": "species", "series": "series"}
    if n in irregular:
        return irregular[n]
    if n.endswith(("s", "sh", "ch", "x", "z")):
        return n + "es"
    if n.endswith("y") and len(n) > 1 and n[-2] not in VOWELS:
        return n[:-1] + "ies"
    if n.endswith("fe"):
        return n[:-2] + "ves"
    return n + "s"


def all_forms(lemma: str, pos_codes: list[str] | None = None) -> set[str]:
    lemma = norm_en(lemma)
    out = {lemma}
    pos_codes = pos_codes or ["n", "v", "adj"]
    if "v" in pos_codes:
        out |= set(verb_forms(lemma).values())
    if "n" in pos_codes:
        out.add(noun_plural(lemma))
    return out


def detect_form(lemma: str, surface: str, pos_codes: list[str] | None = None) -> str | None:
    """Cümledeki biçimin lemma'ya göre çekim anahtarını bulur (base/s/past/pp/ing/pl)."""
    lemma, surface = norm_en(lemma), norm_en(surface)
    if surface == lemma:
        return "base"
    pos_codes = pos_codes or ["v", "n"]
    if "v" in pos_codes or " " in lemma:
        vf = verb_forms(lemma)
        for k in ("s", "past", "pp", "ing"):
            if vf[k] == surface:
                return "past" if k == "pp" and vf["pp"] == vf["past"] else k
    if "n" in pos_codes and noun_plural(lemma) == surface:
        return "pl"
    return None


def inflect(lemma: str, form_key: str | None, pos_code: str) -> str:
    lemma = norm_en(lemma)
    if not form_key or form_key == "base":
        return lemma
    if form_key == "pl":
        return noun_plural(lemma)
    if pos_code == "v" or " " in lemma:
        return verb_forms(lemma).get(form_key, lemma)
    return lemma


# ---------------------------------------------------------------- morfoloji
PREFIXES = ["counter", "inter", "trans", "super", "under", "over", "anti", "mis", "dis", "non", "pre", "sub",
            "un", "in", "im", "il", "ir", "re", "de", "en", "em", "co", "ex"]
SUFFIXES = ["ization", "isation", "ability", "ibility", "ically", "ation", "ition", "ment", "ness", "ity",
            "ance", "ence", "ancy", "ency", "ship", "hood", "ism", "ist", "able", "ible", "ical", "ious",
            "eous", "ous", "ive", "ful", "less", "ally", "ly", "ize", "ise", "ify", "ate", "tion", "sion",
            "ial", "al", "ic", "ent", "ant", "ary", "ery", "ory", "ward", "wise", "en", "er", "or"]
ABSTRACT_SUFFIXES = ("tion", "sion", "ment", "ness", "ity", "ance", "ence", "ancy", "ency", "ism", "ship", "hood", "dom", "ure", "acy")


def morphology(word: str) -> dict:
    w = norm_en(word)
    if " " in w or "-" in w:
        return {"type": "compound", "prefix": None, "suffix": None}
    pre = next((p for p in PREFIXES if w.startswith(p) and len(w) - len(p) >= 4), None)
    suf = next((s for s in SUFFIXES if w.endswith(s) and len(w) - len(s) >= 3), None)
    typ = "derived" if (pre or suf) else "simple"
    return {"type": typ, "prefix": pre, "suffix": suf}


def guess_abstract(word: str, pos_code: str) -> bool | None:
    w = norm_en(word)
    if pos_code == "n":
        return w.endswith(ABSTRACT_SUFFIXES) or None
    return None


def word_features(lemma: str, pos: str | None, kind: str) -> dict:
    m = morphology(lemma)
    pc = primary_pos(pos)
    return {
        "len": len(lemma.replace(" ", "")),
        "len_band": "kısa (≤6)" if len(lemma) <= 6 else ("orta (7-9)" if len(lemma) <= 9 else "uzun (10+)"),
        "pos": pc,
        "multi_pos": len(pos_list(pos)) > 1,
        "morph": m["type"],
        "prefix": m["prefix"],
        "suffix": m["suffix"],
        "phrasal": kind == "phrasal",
        "abstract_guess": guess_abstract(lemma, pc),
    }


def contains_form(sentence: str, forms: set[str]) -> str | None:
    """Cümlede verilen biçimlerden birini (kelime sınırıyla) bulur; bulunan yüzeyi döndürür."""
    s = norm_en(sentence)
    for f in sorted(forms, key=len, reverse=True):
        if not f:
            continue
        m = re.search(r"(?<![a-z])" + re.escape(f) + r"(?![a-z])", s)
        if m:
            return sentence[m.start():m.end()]
    return None


def blank_sentence(sentence: str, surface: str) -> str | None:
    """Hedef biçimi '----' ile değiştirir (ilk geçiş, büyük/küçük harf duyarsız)."""
    m = re.search(r"(?<![A-Za-z])" + re.escape(surface) + r"(?![A-Za-z])", sentence, flags=re.IGNORECASE)
    if not m:
        return None
    return sentence[:m.start()] + "----" + sentence[m.end():]
