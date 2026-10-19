"""60 Günde Ezberbozan Kelimeler (kitap sayfası fotoğraflarından yazıya dökülen liste) → uygulamanın kelime planı.

Kullanım (.venv\\Scripts\\python tools\\build_ezberbozan.py <adım>):
  list   tools/ezberbozan/raw/*.json → seed/ezberbozan.json: temiz liste (gün/sıra, tür, kitaptaki Türkçe karşılık,
         eş/yakın anlamlılar), ek bölümler (55. gün öbek fiiller, 56. gün edat kalıpları, 57. gün bağlaçlar) ve kitap
         dışından yalnızca "garanti" kelimeler (ÖSYM tam sınav metinlerinin en az yarısında geçen ya da sınavların en az
         %10'unda şık olarak çıkan); hepsi part gruplarıyla sıralı.
  gen    içeriği (örnek cümle, mem, eş anlamlı…) olmayan maddeler için seed/gen_input/batch_21+.json
         (ajanlar GEN_INSTRUCTIONS.md + GEN_INSTRUCTIONS_EZB.md ile üretir; tools/merge_seed.py birleştirir).
  apply  seed/pool.json'u yeniden yazar: liste 'main' (kitap sırası + ek partlar), kalan eski havuz 'reserve'
         (silinmez; Ayarlar'dan plana alınabilir). Kitabın eş anlamlıları seed_loader ile word_info'ya girer.
"""
from __future__ import annotations

import collections
import glob
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import textutil as tu  # noqa: E402

RAW = ROOT / "tools" / "ezberbozan" / "raw"
OUT = ROOT / "seed" / "ezberbozan.json"
POOL = ROOT / "seed" / "pool.json"
GEN_IN = ROOT / "seed" / "gen_input"
OSYM_RAW = ROOT / "tools" / "osym_work" / "raw"

GARANTI_TEXT, GARANTI_OPT = 50.0, 10.0      # % tam sınav metni / % sınavda şık
PV_ASKED_MIN = 2                            # havuzdaki öbek fiil: ÖSYM'de en az 2 kez şık
EK_QUOTA = [("linker", 4), ("garanti", 3), ("pv", 2), ("combo", 4)]   # her kitap gününün ardından "Ek" partı
PART_A = 10                                 # kitap günü 20 kelime → A (10) + B (10)
SKIP_LINKERS = {"and", "but", "or"}         # her öğrencinin bildiği temel bağlaçlar
TYPO = {"neverthless": "nevertheless", "meanhile": "meanwhile"}
PLACEHOLDERS = {"sb", "sth", "smb", "smt", "someone", "something", "sy", "st"}
POS_EN = {"adj": "sıfat", "v": "fiil", "n": "isim", "adv": "zarf", "n/v": "isim/fiil", "v/n": "fiil/isim",
          "phr v": "öbek fiil", "prep": "edat", "n phr": "isim", "conj": "bağlaç", "adj/n": "sıfat/isim"}
LINKER_POS = {"BAĞLAÇ": "bağlaç", "FANTBOYS": "bağlaç", "PARALEL YAPI": "bağlaç", "CÜMLE BAŞINDA DEVRİK": "bağlaç",
              "EDAT": "edat", "CÜMLE ZARFI": "zarf", "AÇIKLAMA ZARFI": "zarf"}
# kitaptaki birkaç satır doğrudan uygulama maddesine çevrilemiyor: elle karşılık
LINKER_FIX = {
    "however + adj/adv": None,                      # 'however' maddesinin 2. anlamı olarak eklenir
    "no matter how + adj/adv": "no matter how",
    "given / considering": None,                    # 'given that' / 'considering that' maddelerine not
    "not….but….": "not ... but",
}
SLASH_FIX = {"at profit / loss": ("at a profit", ["at a loss"]), "at first / initially": ("at first", ["initially"]),
             "set on / out / about": ("set out", ["set about", "set on"]),
             "send off / out": ("send out", ["send off"])}      # 'yaymak, salmak' anlamı send out'a ait
# kitaptaki dizgi/İngilizce hataları: yanlış kalıp öğretilmesin (ÖSYM yanlış kalıbı çeldirici olarak kullanır)
PHRASE_FIX = {"emphasize on": "emphasis on", "out of question": "out of the question", "on route": "en route",
              "catch up (with)": "catch up with", "except (for)": "except for"}
PHRASE_VARIANTS = {"catch up with": ["catch up"], "except for": ["except"]}
# standart olmayan ve doğrusu zaten listede olan kalıplar (effect on / impact on) öğretilmez
SKIP_COMBOS = {"effect over", "impact over"}
TR_FIX = {"en route": "yolda, (bir yere) giderken", "emphasis on": "-e vurgu, -e verilen önem"}
SYN_DROP = {"respectively": {"individually"}}     # kitabın açıkça yanlış "eş anlamlısı" (respectively = sırasıyla)
MERGE_INTO = {",so (that)": ("so that", "(virgülden sonra: , so that) bu yüzden, bu sayede")}
# 4+ kelimelik "eş anlamlı" satırı bir tanımsa (kitapta bazen tanım yazılmış) eş anlamlı sayılmaz
VERBAL_STARTS = {"be", "go", "take", "pay", "bring", "at", "make", "give", "put", "get", "come", "in", "on", "by", "keep",
                 "look", "prevent"}


def tr_cap_lower(s: str | None) -> str | None:
    """Kitaptaki 'Gerekli, zaruri' / 'ÇÜNKÜ' → 'gerekli, zaruri' / 'çünkü' (Türkçe büyük-küçük harf)."""
    if not s:
        return s
    s = " ".join(str(s).split())
    # tamamen büyük harfli sözcükler (kitap tablosu) tek tek küçültülür; karışık satırda açıklama kısmı korunur
    s = re.sub(r"[^\W\d_]{2,}", lambda m: tu.tr_lower(m.group(0)) if m.group(0).isupper() else m.group(0), s)
    s = re.sub(r"(?<=[…\.])([^\W\d_])(?=[…\.])", lambda m: tu.tr_lower(m.group(1)), s)   # "…R….rmaz" → "…r….rmaz"
    return tu.tr_lower(s[:1]) + s[1:]


def clean_phrase(p: str) -> str:
    p = p.replace("…", "...").replace("*", "").strip()
    p = re.sub(r"\s*\.\.\.\s*", " ... ", p)
    p = re.sub(r"\(also\)", "also", p)
    p = " ".join(p.split()).strip(" .")
    p = re.sub(r"^(\.\.\.\s*)+", "", p).strip()
    p = re.sub(r"(\s*\.\.\.)+$", "", p).strip()
    low = p.lower()
    return TYPO.get(low, low) if p[:1].isupper() or low in TYPO else p


def split_variants(p: str) -> tuple[str, list[str]]:
    """'be based on / upon' → ('be based on', ['be based upon']); 'until / till' → ('until', ['till'])."""
    key = " ".join(p.lower().split())
    if key in SLASH_FIX:
        return SLASH_FIX[key]
    if "/" not in p:
        return p, []
    parts = [x.strip() for x in p.split("/") if x.strip()]
    main, alts = parts[0], []
    for x in parts[1:]:
        if " " in main and " " not in x:
            alts.append(" ".join(main.split()[:-1] + [x]))
        else:
            alts.append(x)
    return main, alts


def placeholder_lemma(p: str) -> str:
    """'charge sb with sth' → 'charge ... with'; 'apologize for sth' → 'apologize for'."""
    toks = p.split()
    out: list[str] = []
    for t in toks:
        if t.lower().strip(".,") in PLACEHOLDERS:
            if out and out[-1] != "...":
                out.append("...")
        else:
            out.append(t)
    while out and out[-1] == "...":
        out.pop()
    return " ".join(out)


def load_raw() -> list[dict]:
    pages = []
    for f in sorted(RAW.glob("a*.json")):
        pages += json.loads(f.read_text(encoding="utf-8"))["pages"]
    return pages


def exam_freq(phrases: list[str]) -> dict[str, int]:
    """Kalıbın ÖSYM metinlerinde (2012-2020 tam/örnek sınavlar) kaç kez geçtiği — ek bölümlerin sıralaması için."""
    text = "\n".join(Path(f).read_text(encoding="utf-8") for f in glob.glob(str(OSYM_RAW / "*.txt"))).lower()
    out = {}
    for p in phrases:
        parts = [x.strip() for x in p.split("...") if x.strip()]
        if not parts:
            out[p] = 0
            continue
        pat = r"(?<![a-z])" + r"(?![a-z]).{1,40}?(?<![a-z])".join(re.escape(x) for x in parts) + r"(?![a-z])"
        out[p] = len(re.findall(pat, text))
    return out


def fnum(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------- list
def build_list() -> dict:
    pages = load_raw()
    pool = json.loads(POOL.read_text(encoding="utf-8"))["items"]
    pidx = {it["lemma"]: it for it in pool}
    items: list[dict] = []
    seen: set[str] = set()

    # ---- 1-54. gün hedef kelimeler
    days = sorted([p for p in pages if p.get("kind") == "day"], key=lambda p: p["day"])
    for p in days:
        dets = p.get("details") or []
        k = 0
        for i, w in enumerate(p["target_words"]):
            disp = " ".join(w.split())
            if disp != "Milky Way":
                disp = disp.lower()
            lem = tu.norm_en(disp)
            det = dets[i] if i < len(dets) else None
            if det and tu.norm_en(det.get("word", "")).split()[:1] != lem.split()[:1]:
                det = next((d for d in dets if tu.norm_en(d.get("word", "")).split()[:1] == lem.split()[:1]), None)
            if lem in seen:
                continue
            seen.add(lem)
            k += 1
            syns, definition = [], None
            for s_ in (det or {}).get("synonyms") or []:
                s_ = " ".join(str(s_).replace("?", "").split()).strip(" ,;.")
                if not s_ or tu.norm_en(s_) == lem:
                    continue
                words = s_.lower().split()
                if len(words) >= 4 and words[0] not in VERBAL_STARTS:
                    definition = definition or s_
                    continue
                if s_.startswith("made up of") and lem in ("consist of", "be composed of"):
                    s_ = "be made up of"
                syns.append(s_.lower())
            items.append({
                "lemma": lem, "display": disp, "section": "day", "day": p["day"], "pos_in_day": k,
                "pos": POS_EN.get((det or {}).get("pos") or "", None) if det else None,
                "tr": tr_cap_lower((det or {}).get("tr")), "synonyms": syns[:6], "definition": definition,
                "kind": ("phrasal" if (" " in lem and ((det or {}).get("pos") in ("v", "phr v") or
                                                        (pidx.get(lem) or {}).get("kind") == "phrasal" or
                                                        lem.split()[0] in VERB_HEADS))
                         else ("compound" if " " in lem else "word")),
            })

    # ---- ek bölümler
    tables = [p for p in pages if p.get("kind") == "table"]
    pv, combos, linkers = [], [], collections.OrderedDict()
    however_extra = None
    merge_notes: list[tuple[str, str]] = []
    for p in tables:
        for e in p["entries"]:
            sec = (e.get("section") or "").strip()
            raw = (e.get("phrase") or "").strip()
            tr = tr_cap_lower(e.get("tr"))
            if p["day"] == 57:
                key = " ".join(raw.replace("*", "").lower().split())
                if key in LINKER_FIX and LINKER_FIX[key] is None:
                    if key.startswith("however"):
                        however_extra = tr
                    continue
                if key in MERGE_INTO:
                    merge_notes.append((MERGE_INTO[key][0], MERGE_INTO[key][1]))
                    continue
                phrase = LINKER_FIX.get(key) or clean_phrase(raw)
                phrase = TYPO.get(phrase, phrase)
                phrase = PHRASE_FIX.get(phrase, phrase)
                main, alts = split_variants(phrase)
                main = clean_phrase(main)
                lem = tu.norm_en(main)
                if lem in SKIP_LINKERS:
                    continue
                typ = (e.get("type") or "").strip()
                pos = "/".join(dict.fromkeys(LINKER_POS.get(t.strip(), "bağlaç") for t in typ.split("/"))) if typ else "bağlaç"
                if typ.startswith("So +") or typ.startswith("Such +"):
                    pos = "bağlaç"
                grp = re.sub(r"[“”\"]", "", sec).replace("anlamı veren yapılar", "").replace("anlamına gelen yapılar", "") \
                    .replace("bildiren yapılar", "").replace("ifadeleri", "").replace("yapıları", "").strip(" -") if sec else None
                cur = linkers.get(lem)
                if cur:
                    if tr and tr not in cur["tr"]:
                        cur["tr"] = f"{cur['tr']}; {tr}" if cur["tr"] else tr
                    if grp and grp not in (cur["group"] or ""):
                        cur["group"] = f"{cur['group']}, {grp}" if cur["group"] else grp
                    for a in alts:
                        if a not in cur["variants"]:
                            cur["variants"].append(a)
                    continue
                linkers[lem] = {"lemma": lem, "display": main, "section": "linker", "day": 57, "pos": pos, "tr": tr,
                                "linker_type": typ or None, "group": grp, "variants": alts,
                                "kind": "compound" if " " in lem else "word"}
            else:
                fixed = PHRASE_FIX.get(" ".join(raw.lower().split()))
                main, alts = split_variants(fixed or clean_phrase(raw))
                main = placeholder_lemma(main.lower())
                alts = [placeholder_lemma(a.lower()) for a in alts]
                lem = tu.norm_en(main)
                if not lem or lem in SKIP_COMBOS:
                    continue
                if p["day"] == 55:
                    pv.append({"lemma": lem, "display": main, "section": "pv", "day": 55, "pos": "öbek fiil", "tr": tr,
                               "variants": alts, "kind": "phrasal", "book_phrase": raw})
                else:
                    head = sec.split("+")[0].strip().upper() if "+" in sec else ""
                    if sec.startswith("VERB"):
                        pos, kind = "fiil", "phrasal"
                    elif sec.startswith("ADJ"):
                        pos, kind = "sıfat", "compound"
                    elif sec.startswith("NOUN"):
                        pos, kind = "isim", "compound"
                    else:
                        pos, kind = "ifade", "compound"
                    tr = TR_FIX.get(lem, tr)
                    combos.append({"lemma": lem, "display": main, "section": "combo", "day": 56, "pos": pos, "tr": tr,
                                   "sub": sec, "variants": alts, "kind": kind if " " in lem else "word", "book_phrase": raw})
    for lem_, note_ in merge_notes:
        if lem_ in linkers:
            linkers[lem_]["tr"] = f"{linkers[lem_]['tr']}; {note_}"
    for lst_ in (list(linkers.values()), pv, combos):
        for it_ in lst_:
            for v_ in PHRASE_VARIANTS.get(it_["lemma"], []):
                if v_ not in it_["variants"]:
                    it_["variants"].append(v_)
    if however_extra and "however" in linkers:
        linkers["however"]["tr"] = f"{linkers['however']['tr']}; (+ sıfat/zarf) {however_extra}"
    for k_ in ("given that", "considering that"):
        if k_ in linkers:
            linkers[k_]["note"] = "edat olarak da: given / considering + isim (… göz önüne alındığında)"

    def dedupe(lst: list[dict]) -> list[dict]:
        out = []
        for it in lst:
            if it["lemma"] in seen:
                continue
            seen.add(it["lemma"])
            out.append(it)
        return out

    linker_l = dedupe(list(linkers.values()))
    pv_l = dedupe(pv)
    combo_l = dedupe(combos)

    # ---- garanti: kitap dışı, ÖSYM kanıtı en güçlü kelimeler
    gar = []
    for it in pool:
        if it["pool"] != "main" or it["lemma"] in seen:
            continue
        if it["kind"] == "phrasal":
            ok = int(it.get("osym_asked") or 0) >= PV_ASKED_MIN
        else:
            ok = fnum(it.get("text_prob")) >= GARANTI_TEXT or fnum(it.get("option_prob")) >= GARANTI_OPT
        if ok:
            gar.append({"lemma": it["lemma"], "display": it["display"], "section": "garanti", "day": None,
                        "pos": it.get("pos"), "tr": None, "kind": it["kind"],
                        "evidence": it.get("osym_evidence"), "prio": fnum(it.get("priority"))
                        + (20 * int(it.get("osym_asked") or 0))})
            seen.add(it["lemma"])

    # ---- sıralama: ek bölümler ÖSYM sıklığına göre (önemliler erken gelsin), garanti öncelik puanına göre
    freq = exam_freq([it["display"] for it in linker_l + pv_l + combo_l])
    for lst in (linker_l, pv_l, combo_l):
        for it in lst:
            it["osym_freq"] = freq.get(it["display"], 0)
            pit = pidx.get(it["lemma"])
            if pit and pit.get("osym_asked"):
                it["osym_freq"] += 10 * int(pit["osym_asked"])
        if lst is not linker_l:          # bağlaçlar kitaptaki anlam gruplarıyla (sebep, sonuç, zıtlık…) birlikte öğrenilir
            lst.sort(key=lambda it: -it["osym_freq"])
    gar.sort(key=lambda it: -it["prio"])
    streams = {"linker": linker_l, "garanti": gar, "pv": pv_l, "combo": combo_l}

    # ---- part grupları: Gün N · A (10) / B (10) / Ek (≤13)
    ordered: list[dict] = []
    by_day = collections.defaultdict(list)
    for it in items:
        by_day[it["day"]].append(it)
    pos_ = {k: 0 for k in streams}
    ek_size = sum(q for _, q in EK_QUOTA)

    def take_ek() -> list[dict]:
        got = []
        for name, q in EK_QUOTA:
            lst = streams[name]
            got += lst[pos_[name]: pos_[name] + q]
            pos_[name] = min(len(lst), pos_[name] + q)
        for name, _ in EK_QUOTA:            # boşalan akışın payını sıradakilerle doldur
            lst = streams[name]
            while len(got) < ek_size and pos_[name] < len(lst):
                got.append(lst[pos_[name]])
                pos_[name] += 1
        return got

    for d in range(1, 55):
        words = by_day.get(d, [])
        for i, it in enumerate(words):
            it["group"] = f"Gün {d} · {'A' if i < PART_A else 'B'}"
            ordered.append(it)
        for it in take_ek():
            it["group_ek"] = f"Gün {d} · Ek"
            ordered.append(it)
    n = 0
    while any(pos_[k] < len(v) for k, v in streams.items()):
        n += 1
        for it in take_ek():
            it["group_ek"] = f"Ek · {n}"
            ordered.append(it)
    for i, it in enumerate(ordered, 1):
        it["order"] = i
        it["part_group"] = it.pop("group_ek", None) or it.pop("group", None)
        it.pop("group", None) if it.get("section") != "linker" else None
    data = {"version": 1, "source": "60 Günde Ezberbozan Kelimeler (güncel basım) — kitap fotoğraflarından yazıya dökme",
            "garanti_rule": f"kitap dışı: ÖSYM tam sınav metinlerinin ≥%{GARANTI_TEXT:g}'inde geçen ya da sınavların "
                            f"≥%{GARANTI_OPT:g}'inde şık olarak çıkan kelime; öbek fiilde ÖSYM'de ≥{PV_ASKED_MIN} kez şık",
            "counts": {"day_words": len(items), "linker": len(linker_l), "pv": len(pv_l), "combo": len(combo_l),
                       "garanti": len(gar), "total": len(ordered)},
            "items": ordered}
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")
    return data


VERB_HEADS = {"give", "cut", "take", "come", "carry", "figure", "cope", "end", "deal", "point", "result", "stick",
              "date", "wipe", "account", "search", "look", "depend", "conform", "shed", "differ", "lead", "focus",
              "contribute", "consist", "deprive", "attribute", "rely", "comply", "stem", "be", "set", "bring", "make",
              "put", "turn", "get", "go", "run", "break", "call", "keep", "pass", "hold", "prey", "devote", "abide"}


# ---------------------------------------------------------------- gen
def content_lemmas() -> set[str]:
    have = set()
    p = ROOT / "seed" / "content.jsonl"
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            have.add(tu.norm_en(json.loads(line)["lemma"]))
    for f in GEN_IN.glob("batch_*.json"):             # zaten bir pakete alınmış maddeler (üretim sürüyor)
        for it in json.loads(f.read_text(encoding="utf-8")):
            have.add(it["lemma"])
    return have


def build_gen(batch_size: int = 110) -> list[Path]:
    data = json.loads(OUT.read_text(encoding="utf-8"))
    pool = {it["lemma"]: it for it in json.loads(POOL.read_text(encoding="utf-8"))["items"]}
    have = content_lemmas()
    todo = []
    for it in data["items"]:
        if it["lemma"] in have:
            continue
        p = pool.get(it["lemma"]) or {}
        inp = {"lemma": it["lemma"], "display": it["display"], "kind": it.get("kind") or p.get("kind") or "word",
               "pos": it.get("pos") or p.get("pos"), "meaning": p.get("meaning") or it.get("tr"),
               "family": p.get("family")}
        hint = {"section": it["section"]}
        if it.get("synonyms"):
            hint["book_synonyms"] = it["synonyms"]
        for k in ("linker_type", "group", "sub", "variants", "note", "book_phrase", "definition"):
            if it.get(k):
                hint[k] = it[k]
        inp["hint"] = hint
        todo.append(inp)
    existing = sorted(int(re.search(r"batch_(\d+)", f.name).group(1)) for f in GEN_IN.glob("batch_*.json"))
    start = (existing[-1] + 1) if existing else 1
    out = []
    for k in range(0, len(todo), batch_size):
        no = start + k // batch_size
        f = GEN_IN / f"batch_{no:02d}.json"
        f.write_text(json.dumps(todo[k:k + batch_size], ensure_ascii=False, indent=0), encoding="utf-8")
        out.append(f)
    print(f"içerik üretilecek madde: {len(todo)} → {len(out)} paket ({out[0].name if out else '-'} …)")
    return out


# ---------------------------------------------------------------- apply
def apply_pool() -> dict:
    data = json.loads(OUT.read_text(encoding="utf-8"))
    src = json.loads(POOL.read_text(encoding="utf-8"))
    pool = src["items"]
    pidx = {it["lemma"]: it for it in pool}
    content = {}
    for line in (ROOT / "seed" / "content.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            o = json.loads(line)
            content[tu.norm_en(o["lemma"])] = o
    try:
        from wordfreq import zipf_frequency
    except Exception:          # pragma: no cover
        zipf_frequency = None
    # kitabın eş/yakın anlamlıları: içeriği ajanla üretilen maddelerde yalnızca ajanın onayladıkları (açıkça yanlış olanlar
    # çıkarıldı: invent ≠ discover); diğerlerinde kitaptaki liste, elle ayıklanan birkaç yanlış hariç
    reviewed = set()
    for f in GEN_IN.glob("batch_*.json"):
        if int(re.search(r"batch_(\d+)", f.name).group(1)) >= 21:
            reviewed |= {x["lemma"] for x in json.loads(f.read_text(encoding="utf-8"))}
    for it in data["items"]:
        if not it.get("synonyms"):
            continue
        gen = {tu.norm_en(x) for x in (content.get(it["lemma"]) or {}).get("synonyms") or []}
        bad = SYN_DROP.get(it["lemma"], set())
        it["synonyms"] = [x for x in it["synonyms"] if tu.norm_en(x) not in bad
                          and (it["lemma"] not in reviewed or tu.norm_en(x) in gen)]
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")
    chosen = set()
    new_items = []
    for it in data["items"]:
        lem = it["lemma"]
        chosen.add(lem)
        c = content.get(lem) or {}
        sense_pos = [s.get("pos") for s in (c.get("senses") or []) if s.get("pos")]
        feats_extra = {"ezb_day": it.get("day"), "ezb_section": {"pv": "öbek fiil", "combo": "edat kalıbı",
                                                                  "linker": "bağlaç"}.get(it["section"]),
                       "part_group": it["part_group"], "ezb_order": it["order"]}
        if it.get("variants"):
            feats_extra["variants"] = it["variants"]
        if it.get("linker_type"):
            feats_extra["linker_type"] = it["linker_type"]
        if it.get("group") and it["section"] == "linker":
            feats_extra["linker_group"] = it["group"]
        if it.get("sub"):
            feats_extra["combo_type"] = it["sub"]
        if it["section"] == "garanti":
            feats_extra["garanti"] = True
            feats_extra.pop("ezb_day")
            feats_extra.pop("ezb_section")
        p = pidx.get(lem)
        if p:
            p["pool"] = "main"
            p["order_index"] = float(it["order"])
            f = dict(p.get("features") or {})
            f.update({k: v for k, v in feats_extra.items() if v is not None})
            p["features"] = f
            if it["section"] != "garanti":
                srcs = [s.strip() for s in (p.get("sources") or "").split(",") if s.strip()]
                if "Ezberbozan" not in srcs:
                    srcs.insert(0, "Ezberbozan")
                p["sources"] = ", ".join(srcs)
                p["tags"] = "Ezberbozan" + (f" · {it['day']}. gün" if it.get("day") else "")
            else:
                p["tags"] = "garanti (ÖSYM)"
            if not p.get("meaning") and (it.get("tr") or c.get("meaning_tr") or c.get("senses")):
                p["meaning"] = it.get("tr") or c.get("meaning_tr") or "; ".join(
                    x["tr"] for x in (c.get("senses") or [])[:2] if x.get("tr"))
            if not p.get("pos") and (it.get("pos") or sense_pos):
                p["pos"] = it.get("pos") or "/".join(dict.fromkeys(sense_pos[:2]))
            continue
        meaning = it.get("tr") or c.get("meaning_tr") or "; ".join(s["tr"] for s in (c.get("senses") or [])[:2] if s.get("tr"))
        pos = it.get("pos") or "/".join(dict.fromkeys(sense_pos[:2])) or None
        z = round(zipf_frequency(lem.replace(" ... ", " "), "en"), 2) if zipf_frequency else None
        feats = tu.word_features(lem, pos, it.get("kind") or "word")
        feats.update({k: v for k, v in feats_extra.items() if v is not None})
        new_items.append({
            "lemma": lem, "display": it["display"], "kind": it.get("kind") or "word", "pool": "main",
            "pos": pos, "meaning": meaning, "family": None, "level": None, "text_prob": None, "option_prob": None,
            "src_count": None, "osym_evidence": None,
            "tags": "Ezberbozan" + (f" · {it['day']}. gün" if it.get("day") else ""), "sources": "Ezberbozan",
            "priority": None, "rank": None, "plan_week": None, "plan_day": it.get("day"),
            "order_index": float(it["order"]), "zipf": z,
            "cov_weight": 0.002 if " " in lem else 0.0005, "features": feats,
        })
    # kalan eski havuz: yedeğe (silinmez), eski sırasıyla en sona
    rest = [p for p in pool if p["lemma"] not in chosen]
    rest.sort(key=lambda p: (p["pool"] != "main", p.get("order_index") or 1e9))
    base = 100000.0
    for i, p in enumerate(rest):
        p["pool"] = "reserve"
        p["order_index"] = base + i
    items = [p for p in pool if p["lemma"] in chosen] + new_items + rest
    items.sort(key=lambda p: p["order_index"])
    src["items"] = items
    src["version"] = int(src.get("version") or 1) + 1
    src["source"] = (src.get("source") or "") + " | Ezberbozan + garanti planı"
    POOL.write_text(json.dumps(src, ensure_ascii=False, indent=0), encoding="utf-8")
    c_ = collections.Counter(p["pool"] for p in items)
    print(f"havuz: {len(items)} madde | main {c_['main']} | reserve {c_['reserve']} | yeni eklenen {len(new_items)}")
    # karışabilir çiftler yeni listeyle yeniden (aynı pakete girmesinler; ayırt etme alıştırması)
    from app import importer
    conf = importer.find_confusables(items)
    (ROOT / "seed" / "confusables.json").write_text(json.dumps(conf, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"karışabilir çift: {len(conf)}")
    miss = [it["lemma"] for it in data["items"] if it["lemma"] not in content]
    print(f"içeriği olmayan liste maddesi: {len(miss)}", miss[:20])
    return {"main": c_["main"], "reserve": c_["reserve"], "new": len(new_items), "no_content": len(miss)}


if __name__ == "__main__":
    step = sys.argv[1] if len(sys.argv) > 1 else "list"
    if step == "list":
        d = build_list()
        print(json.dumps(d["counts"], ensure_ascii=False))
    elif step == "gen":
        build_gen()
    elif step == "apply":
        apply_pool()
