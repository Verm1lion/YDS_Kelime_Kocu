"""Geliştirme aracı: gerçek ÖSYM cümleleri — kelimenin sınavda geçtiği ya da doğru cevap olarak SORULDUĞU cümle.

Aşamalar (çalışma dosyaları tools/osym_work/ altında):
  raw       PDF'lerden ham metin + cevap anahtarı; 2021-2026 analiz tablosundaki soruları doğrudan cümleye çevirir
            (sent/xlsx.json). Diğer sınavların cümleleri ajanlarca sent/<sınav>.json olarak yeniden kurulur
            (boşluklar cevap anahtarındaki doğru şıkla doldurulur; AJAN_TALIMATI.md).
  match     sent/*.json'u ham metne karşı doğrular (uydurma cümle elenir), liste kelimeleriyle eşler, kelime başına
            en fazla 3 cümle seçer (önce kelimenin doğru cevap olduğu soru, sonra en yeni sınav) ve çeviri partileri
            yazar (tr_in/*.json).
  match2    artımlı: osym_examples'ta henüz cümlesi olmayan ETKİN maddeler için eşleştirir (liste değişince, ör. Ezberbozan);
            çevirisi zaten olan cümlede çeviri girdiye konur (yalnızca anlam kontrolü gerekir) → tr_in2/*.json
  assemble  tr_out/*.json + tr_out2/*.json (çeviri + anlam kontrolü) → seed/osym_examples.json

Kullanım: .venv\\Scripts\\python tools\\build_osym_examples.py raw|match|assemble
"""
from __future__ import annotations

import json
import math
import re
import sys
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import textutil as tu  # noqa: E402

BASE = ROOT.parent
PDF_DIR = BASE / "YDS_Kelime_Calismasi" / "Kaynaklar" / "01_OSYM_Resmi_Sinavlar"
ANALYSIS = BASE / "Analiz" / "YDS_Kelime_ve_Soru_Analizi.xlsx"
WORK = ROOT / "tools" / "osym_work"
SEED = ROOT / "seed"
PER_WORD = 3
TR_CHARS = re.compile(r"[ğĞışŞİçÇöÖüÜ]")
# PDF'inin fontlarında metin eşlemesi yok (ham metin okunamaz): cümleler font kodları çözülerek kuruldu ve sayfa
# görüntülerine karşı doğrulandı (4 Ekim 2026'da 3. ve 10. sorular elle karşılaştırıldı). Ham metin denetimi atlanır.
PAGE_VERIFIED = {"2020_YDS_1_yuzde10"}


# ---------------------------------------------------------------- etiketler
def exam_label(stem: str) -> tuple[str, int]:
    """'2013_YDS_Sonbahar_yuzde10' -> ('YDS 2013 Sonbahar', 2013)."""
    p = stem.split("_")
    year = int(p[0])
    if p[1] == "UDS":
        field = {"Fen": "Fen", "Saglik": "Sağlık", "Sosyal": "Sosyal"}.get(p[4], p[4])
        return f"ÜDS {year} {p[2].replace('Ilkbahar', 'İlkbahar')} ({field})", year
    if p[2] == "Ornek":
        return f"YDS {year} örnek sorular", year
    term = p[2].replace("Ilkbahar", "İlkbahar")
    return (f"YDS {year}/{term}" if term.isdigit() else f"YDS {year} {term}"), year


def session_label(s: str) -> tuple[str, int]:
    """Analiz tablosundaki oturum: '2021/1' -> ('YDS 2021/1', 2021); '2025/İng' -> ('YDS 2025 (İng.)', 2025)."""
    y, t = (str(s).split("/") + [""])[:2]
    return (f"YDS {y}/{t}" if t.isdigit() else f"YDS {y} ({t}.)"), int(y)


# ---------------------------------------------------------------- raw
def parse_key(text: str) -> dict[int, str]:
    """Tam kitapçığın sonundaki cevap anahtarı (1-80)."""
    pairs = [(int(m.group(1)), m.group(2), m.start()) for m in re.finditer(r"(?<!\d)(\d{1,2})\.\s{0,3}([A-E])(?=\s)", text)]
    key: dict[int, str] = {}
    for n, letter, _ in pairs[-80:]:
        key[n] = letter
    return key if sorted(key) == list(range(1, 81)) else {}


def fill_blanks(stem: str, answer: str) -> str | None:
    blanks = stem.count("----")
    parts = [a.strip() for a in str(answer).split("/")] if blanks > 1 else [str(answer).strip()]
    if blanks == 0 or len(parts) != blanks:
        return None
    out = stem
    for a in parts:
        out = out.replace("----", a, 1)
    return re.sub(r"\s+", " ", out).strip()


def split_sentences(text: str) -> list[str]:
    text = re.sub(r"\((?:I|II|III|IV|V)\)\s*", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z\"“(])", text) if s.strip()]


def xlsx_items() -> list[dict]:
    import openpyxl
    wb = openpyxl.load_workbook(str(ANALYSIS), read_only=True, data_only=True)
    rows = list(wb["Tüm Sorular"].iter_rows(values_only=True))
    hdr = rows[0]
    items = []
    for r in rows[1:]:
        d = dict(zip(hdr, r))
        typ, stem, ans = d.get("Soru Tipi") or "", str(d.get("Soru Kökü") or "").strip(), d.get("Doğru Cevabın Metni")
        label, year = session_label(d.get("Oturum"))
        base = {"exam": f"xlsx_{d.get('Oturum')}", "label": label, "year": year, "q": d.get("Soru No")}
        if not stem or typ.startswith("Diyalog"):
            continue
        if "----" in stem and ans:
            filled = fill_blanks(stem, ans)
            if filled:
                kind = "kelime" if typ.startswith("Kelime") else ("dilbilgisi" if typ.startswith("Dil") else "tamamlama")
                for s in split_sentences(filled):
                    items.append({**base, "type": kind, "sentence": s, "option": str(ans).strip(),
                                  "letter": d.get("Doğru Cevap"), "asked": [a.strip() for a in str(ans).split("/")]})
            continue
        if TR_CHARS.search(stem) and ans and not TR_CHARS.search(str(ans)):
            for s in split_sentences(str(ans)):      # TR→EN çeviri: doğru şık İngilizce cümle
                items.append({**base, "type": "ceviri", "sentence": s})
            continue
        if not TR_CHARS.search(stem):
            for s in split_sentences(stem):
                items.append({**base, "type": "okuma", "sentence": s})
            if typ.startswith("Yakın") and ans and not TR_CHARS.search(str(ans)):
                for s in split_sentences(str(ans)):
                    items.append({**base, "type": "okuma", "sentence": s})
    return items


def cmd_raw() -> None:
    from pypdf import PdfReader
    (WORK / "raw").mkdir(parents=True, exist_ok=True)
    (WORK / "sent").mkdir(parents=True, exist_ok=True)
    exams = []
    for pdf in sorted(PDF_DIR.glob("*.pdf")):
        text = "\n".join((p.extract_text() or "") for p in PdfReader(str(pdf)).pages)
        stem = pdf.stem
        label, year = exam_label(stem)
        kind = "tam" if "TAM" in stem else ("ornek" if "Ornek" in stem else "yuzde10")
        key = parse_key(text) if kind == "tam" else {}
        (WORK / "raw" / f"{stem}.txt").write_text(text, encoding="utf-8")
        exams.append({"id": stem, "label": label, "year": year, "kind": kind, "chars": len(text),
                      "key": {str(k): v for k, v in key.items()},
                      "inline_answers": len(re.findall(r"DOĞRU CEVAP\s*:\s*[A-E]", text))})
        print(f"{stem:45s} {label:28s} {kind:8s} anahtar={len(key):2d} satır_içi={exams[-1]['inline_answers']}")
    (WORK / "exams.json").write_text(json.dumps(exams, ensure_ascii=False, indent=1), encoding="utf-8")
    items = xlsx_items()
    (WORK / "sent" / "xlsx.json").write_text(json.dumps({"exam": "xlsx", "items": items}, ensure_ascii=False, indent=1),
                                             encoding="utf-8")
    print(f"analiz tablosu (2021-2026): {len(items)} cümle")


# ---------------------------------------------------------------- match: doğrulama
def _norm(s: str) -> str:
    s = (s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
         .replace("–", "-").replace("—", "-").lower())
    s = re.sub(r"[^a-z0-9' ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _raw_forms(text: str) -> tuple[str, str]:
    """Ham metnin iki normal biçimi: satır sonu bölünmeleri birleştirilmiş ve olduğu gibi (cloze '(18)----' işareti atılır)."""
    text = re.sub(r"\(\d{1,2}\)\s*----", " ---- ", text)
    return _norm(re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)), _norm(text)


def _found(sentence: str, raws: tuple[str, str], need: float = 0.85) -> bool:
    """Cümle ham metinde var mı: beşer kelimelik pencerelerin en az %85'i birebir bulunmalı (uydurma cümle elenir)."""
    words = _norm(sentence).split()
    if len(words) < 6:
        return False
    wins = [" ".join(words[i:i + 5]) for i in range(0, max(1, len(words) - 4), 2)]
    return sum(1 for w in wins if w in raws[0] or w in raws[1]) / len(wins) >= need


def _parts(option: str) -> list[str]:
    return [p.strip() for p in str(option).split("/")] if "/" in str(option) else [str(option).strip()]


def _tail_key(raw: str) -> dict[str, str]:
    """Örnek soru kitapçığı gibi sonda 'CEVAP ANAHTARI' olanlar."""
    i = raw.upper().rfind("CEVAP ANAHTARI")
    if i < 0:
        return {}
    return {m.group(1): m.group(2) for m in re.finditer(r"(?<!\d)(\d{1,2})\s*[.\-)]?\s*([A-E])(?=\s|$)", raw[i:])}


def _inline_answer(raw: str, stem: str) -> str | None:
    """Yüzde 10'luk yayında sorunun altındaki 'DOĞRU CEVAP: X' (kökün son kelimelerinden sonra gelen ilk işaret)."""
    words = re.findall(r"[A-Za-z']+", stem)
    for n in (5, 4, 3):
        if len(words) < n:
            continue
        m = re.search(r"\W+".join(re.escape(w) for w in words[-n:]), raw)
        if m:
            a = re.search(r"(?:CEVAP|YANIT)\s*:\s*([A-E])", raw[m.end(): m.end() + 3000])
            return a.group(1) if a else None
    return None


def _verify(it: dict, raw: str, raws: tuple[str, str], key: dict[str, str]) -> str | None:
    """Hata nedeni (geçerliyse None)."""
    s = (it.get("sentence") or "").strip()
    if not s or TR_CHARS.search(s) or "----" in s:
        return "boş/Türkçe/boşluklu"
    if not 6 <= len(s.split()) <= 70:
        return "uzunluk"
    fills = it.get("fills") or []
    if not fills:
        return None if _found(s, raws) else "ham metinde yok"
    stem = re.sub(r"\(\d{1,2}\)\s*----", "----", it.get("stem") or "")   # cloze: "(17)----"
    if stem.strip() == "----":
        # paragraf tamamlama: boşluk cümlenin tamamı, doğru şık cümlesi metinde şık olarak geçer
        if not _found(s, raws):
            return "şık cümlesi ham metinde yok"
        f = fills[0]
        want = key.get(str(f.get("q"))) if key else _inline_answer(raw, s)
        return None if want and want == f.get("letter") else f"cevap tutmuyor (q{f.get('q')}: {f.get('letter')} / anahtar {want})"
    if "----" not in stem or not _found(stem, raws, 0.8):
        return "kök ham metinde yok"
    parts = [p for f in fills for p in _parts(f.get("option", ""))]
    if stem.count("----") != len(parts):
        return "boşluk sayısı tutmuyor"
    filled = stem
    for p in parts:
        filled = filled.replace("----", p, 1)
    if SequenceMatcher(None, _norm(filled), _norm(s)).ratio() < 0.97:
        return "doldurulmuş cümle kökle tutmuyor"
    for f in fills:
        if not all(_norm(p) in raws[0] or _norm(p) in raws[1] for p in _parts(f.get("option", ""))):
            return "şık ham metinde yok"
        want = key.get(str(f.get("q"))) if key else _inline_answer(raw, stem)
        if not want or want != f.get("letter"):
            return f"cevap tutmuyor (q{f.get('q')}: {f.get('letter')} / anahtar {want})"
    return None


def load_sentences() -> list[dict]:
    exams = {e["id"]: e for e in json.loads((WORK / "exams.json").read_text(encoding="utf-8"))}
    out, report = [], []
    for f in sorted((WORK / "sent").glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        if f.stem == "xlsx":
            out += [{**it, "asked": it.get("asked") or [], "src_kind": "tablo"} for it in data["items"]]
            report.append((f.stem, len(data["items"]), 0, {}))
            continue
        ex = exams[f.stem]
        raw = (WORK / "raw" / f"{ex['id']}.txt").read_text(encoding="utf-8")
        raws = _raw_forms(raw)
        key = ex["key"] or _tail_key(raw)
        ok = bad = 0
        why: dict[str, int] = defaultdict(int)
        for it in data.get("items", []):
            if ex["id"] in PAGE_VERIFIED:
                s = (it.get("sentence") or "").strip()
                err = None if s and not TR_CHARS.search(s) and "----" not in s and 6 <= len(s.split()) <= 70 else "uzunluk/biçim"
            else:
                err = _verify(it, raw, raws, key)
            if err:
                bad += 1
                why[err.split(" (")[0]] += 1
                continue
            ok += 1
            out.append({"exam": ex["id"], "label": ex["label"], "year": ex["year"], "q": it.get("q"),
                        "type": it.get("type"), "sentence": re.sub(r"\s+", " ", it["sentence"]).strip(),
                        "asked": [p for fl in it.get("fills") or [] for p in _parts(fl.get("option", ""))],
                        "src_kind": ex["kind"]})
        report.append((f.stem, ok, bad, dict(why)))
    for name, ok, bad, why in report:
        print(f"  {name:45s} geçerli {ok:4d}  elenen {bad:3d}  {why if why else ''}")
    # aynı cümle birden çok kitapçıkta (2012 ÜDS ortak soruları): soru bilgisi olan ve en yeni tutulur
    best: dict[str, dict] = {}
    for it in out:
        k = _norm(it["sentence"])
        cur = best.get(k)
        if not cur or (bool(it["asked"]), it["year"]) > (bool(cur["asked"]), cur["year"]):
            best[k] = it
    return list(best.values())


# ---------------------------------------------------------------- match: eşleme ve seçim
def load_entries() -> list[dict]:
    pool = json.loads((SEED / "pool.json").read_text(encoding="utf-8"))["items"]
    sugg = json.loads((SEED / "suggestions.json").read_text(encoding="utf-8"))
    out = []
    for it in pool + sugg:
        lemma = tu.norm_en(it["lemma"])
        codes = tu.pos_list(it.get("pos")) or ["n", "v", "adj"]
        if it["kind"] == "phrasal" and "v" not in codes:
            codes = ["v"] + codes
        forms = tu.all_forms(lemma, codes) if it["kind"] in ("word", "phrasal") else {lemma}
        out.append({"lemma": lemma, "kind": it["kind"], "pool": it["pool"], "codes": codes, "forms": forms,
                    "meaning": tu.short_meaning(it.get("meaning"), 4, 90)})
    return out


def _score(c: dict) -> float:
    n = len(c["sentence"].split())
    return ((10 if c["asked"] else 0) + (c["year"] - 2012) * 0.5 + (1 if c["base"] else 0)
            + (1 if 10 <= n <= 35 else 0) - (2 if n > 45 else 0))


def cmd_match() -> None:
    sents = load_sentences()
    print(f"doğrulanmış tekil cümle: {len(sents)}")
    entries = load_entries()
    single: dict[str, list[int]] = defaultdict(list)
    multi: list[tuple[str, int]] = []
    for i, e in enumerate(entries):
        for f in e["forms"]:
            if " " in f or "-" in f:
                multi.append((f, i))
            else:
                single[f].append(i)
    cands: dict[int, list[dict]] = defaultdict(list)
    for si, s in enumerate(sents):
        text = s["sentence"]
        toks = set(re.findall(r"[a-z]+", text.lower()))
        hit = {i for t in toks for i in single.get(t, [])}
        hit |= {i for f, i in multi if f.split(" ")[0].split("-")[0] in toks and tu.contains_form(text, {f})}
        asked = {_norm(a) for a in s["asked"]}
        for i in hit:
            e = entries[i]
            surface = tu.contains_form(text, e["forms"])
            if not surface:
                continue
            cands[i].append({"sid": si, "sentence": text, "surface": surface, "year": s["year"],
                             "exam": s.get("exam"), "base": tu.norm_en(surface) == e["lemma"],
                             "asked": bool(asked & {_norm(f) for f in e["forms"]})})
    chosen: dict[int, list[dict]] = {}
    for i, cs in cands.items():
        cs.sort(key=_score, reverse=True)
        pick: list[dict] = []
        for c in cs:                      # önce farklı sınavlardan
            if len(pick) < PER_WORD and all(p["exam"] != c["exam"] for p in pick):
                pick.append(c)
        for c in cs:
            if len(pick) < PER_WORD and c not in pick:
                pick.append(c)
        chosen[i] = pick
    by_sid: dict[int, list[dict]] = defaultdict(list)
    for i, pick in chosen.items():
        for c in pick:
            by_sid[c["sid"]].append({"lemma": entries[i]["lemma"], "meaning": entries[i]["meaning"],
                                     "surface": c["surface"], "asked": c["asked"]})
    main = [i for i, e in enumerate(entries) if e["pool"] == "main"]
    print(f"gerçek cümlesi olan madde: {len(chosen)} / {len(entries)} "
          f"(ana liste {sum(1 for i in main if i in chosen)} / {len(main)}; "
          f"sorulduğu cümle olan {sum(1 for p in chosen.values() if any(c['asked'] for c in p))})")
    sids = sorted(by_sid)
    (WORK / "tr_in").mkdir(exist_ok=True)
    for old in (WORK / "tr_in").glob("*.json"):
        old.unlink()
    size = 110
    for b in range(0, len(sids), size):
        items = [{"sid": sid, "en": sents[sid]["sentence"], "words": by_sid[sid]} for sid in sids[b:b + size]]
        (WORK / "tr_in" / f"batch_{b // size + 1:02d}.json").write_text(
            json.dumps({"batch": b // size + 1, "items": items}, ensure_ascii=False, indent=1), encoding="utf-8")
    meta = {str(sid): {k: sents[sid].get(k) for k in ("exam", "label", "year", "q", "type")} for sid in sids}
    (WORK / "tr_in" / "_meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    print(f"çevrilecek cümle: {len(sids)} → {math.ceil(len(sids) / size)} parti (tr_in/)")


def cmd_match2() -> None:
    sents = load_sentences()
    pool = json.loads((SEED / "pool.json").read_text(encoding="utf-8"))["items"]
    active = {tu.norm_en(it["lemma"]) for it in pool if it["pool"] == "main"}
    have: dict[str, int] = defaultdict(int)
    for it in json.loads((SEED / "osym_examples.json").read_text(encoding="utf-8"))["items"]:
        have[it["lemma"]] += 1
    seen_l: set[str] = set()
    entries = []
    for e in load_entries():
        if e["lemma"] in active and not have.get(e["lemma"]) and e["lemma"] not in seen_l:
            seen_l.add(e["lemma"])
            entries.append(e)
    tr_by_en: dict[str, str] = {}
    for fin in sorted((WORK / "tr_in").glob("batch_*.json")):
        fout = WORK / "tr_out" / fin.name
        if not fout.exists():
            continue
        src = {it["sid"]: it["en"] for it in json.loads(fin.read_text(encoding="utf-8"))["items"]}
        for o in json.loads(fout.read_text(encoding="utf-8"))["items"]:
            if o.get("ok") and o.get("tr") and o.get("sid") in src:
                tr_by_en[src[o["sid"]]] = o["tr"]
    single: dict[str, list[int]] = defaultdict(list)
    multi: list[tuple[str, int]] = []
    for i, e in enumerate(entries):
        for f in e["forms"]:
            (multi.append((f, i)) if (" " in f or "-" in f) else single[f].append(i))
    cands: dict[int, list[dict]] = defaultdict(list)
    for si, s in enumerate(sents):
        text = s["sentence"]
        toks = set(re.findall(r"[a-z]+", text.lower()))
        hit = {i for t in toks for i in single.get(t, [])}
        hit |= {i for f, i in multi if f.split(" ")[0].split("-")[0] in toks and tu.contains_form(text, {f})}
        asked = {_norm(a) for a in s["asked"]}
        for i in hit:
            e = entries[i]
            surface = tu.contains_form(text, e["forms"])
            if surface:
                cands[i].append({"sid": si, "sentence": text, "surface": surface, "year": s["year"],
                                 "exam": s.get("exam"), "base": tu.norm_en(surface) == e["lemma"],
                                 "asked": bool(asked & {_norm(f) for f in e["forms"]})})
    by_sid: dict[int, list[dict]] = defaultdict(list)
    for i, cs in cands.items():
        cs.sort(key=_score, reverse=True)
        pick: list[dict] = []
        for c in cs:
            if len(pick) < PER_WORD and all(p["exam"] != c["exam"] for p in pick):
                pick.append(c)
        for c in cs:
            if len(pick) < PER_WORD and c not in pick:
                pick.append(c)
        for c in pick:
            by_sid[c["sid"]].append({"lemma": entries[i]["lemma"], "meaning": entries[i]["meaning"],
                                     "surface": c["surface"], "asked": c["asked"]})
    d = WORK / "tr_in2"
    d.mkdir(exist_ok=True)
    for old in d.glob("*.json"):
        old.unlink()
    sids = sorted(by_sid)
    size = 110
    for b in range(0, len(sids), size):
        items = [{"sid": sid, "en": sents[sid]["sentence"], "tr": tr_by_en.get(sents[sid]["sentence"]),
                  "words": by_sid[sid]} for sid in sids[b:b + size]]
        (d / f"batch_{b // size + 1:02d}.json").write_text(
            json.dumps({"batch": b // size + 1, "items": items}, ensure_ascii=False, indent=1), encoding="utf-8")
    meta = {str(sid): {k: sents[sid].get(k) for k in ("exam", "label", "year", "q", "type")} for sid in sids}
    (d / "_meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    print(f"yeni madde: {len(cands)} / {len(entries)} cümlesiz etkin madde; cümle {len(sids)} "
          f"(çevirisi hazır {sum(1 for s_ in sids if sents[s_]['sentence'] in tr_by_en)}) → tr_in2/")


# ---------------------------------------------------------------- assemble
DOMAIN = {"Fen": "bilim", "Sağlık": "sağlık", "Sosyal": "sosyal"}


def _tidy(s: str) -> str:
    """Alıntı birden çok cümleye yayıldığında kalan eşsiz baş/son tırnağı atar."""
    s = s.strip()
    if s.startswith("“") and s.count("“") > s.count("”"):
        s = s[1:]
    if s.endswith("”") and s.count("”") > s.count("“"):
        s = s[:-1]
    if s.count('"') % 2 and (s.startswith('"') or s.endswith('"')):
        s = s[1:] if s.startswith('"') else s[:-1]
    return s.strip()


def cmd_assemble() -> None:
    meta = json.loads((WORK / "tr_in" / "_meta.json").read_text(encoding="utf-8"))
    if (WORK / "tr_in2" / "_meta.json").exists():
        meta.update(json.loads((WORK / "tr_in2" / "_meta.json").read_text(encoding="utf-8")))
    items, rejected, sense_off = [], 0, 0
    pairs = [(fin, WORK / "tr_out" / fin.name) for fin in sorted((WORK / "tr_in").glob("batch_*.json"))]
    pairs += [(fin, WORK / "tr_out2" / fin.name) for fin in sorted((WORK / "tr_in2").glob("batch_*.json"))]
    for fin, fout in pairs:
        if not fout.exists():
            print(f"  eksik çeviri: {fout.name}")
            continue
        src = {it["sid"]: it for it in json.loads(fin.read_text(encoding="utf-8"))["items"]}
        for o in json.loads(fout.read_text(encoding="utf-8"))["items"]:
            it = src.get(o.get("sid"))
            tr = (o.get("tr") or "").strip()
            if not it or not o.get("ok") or len(tr.split()) < 3:
                rejected += 1
                continue
            m = meta[str(it["sid"])]
            sense = {w["lemma"]: bool(w.get("sense_ok")) for w in o.get("words") or []}
            field = re.search(r"\((Fen|Sağlık|Sosyal)\)", m["label"] or "")
            for w in it["words"]:
                if not sense.get(w["lemma"]):
                    sense_off += 1
                    continue
                label = m["label"] + (f" · {m['q']}. soru" if m.get("q") else "")
                items.append({"lemma": w["lemma"], "en": _tidy(it["en"]), "tr": _tidy(tr), "form": w["surface"],
                              "domain": DOMAIN.get(field.group(1), "sınav") if field else "sınav",
                              "source": label, "asked": w["asked"], "year": m["year"]})
    per: dict[str, int] = defaultdict(int)
    final = []
    for x in sorted(items, key=lambda x: (not x["asked"], -x["year"])):
        if per[x["lemma"]] < PER_WORD:
            per[x["lemma"]] += 1
            final.append(x)
    (SEED / "osym_examples.json").write_text(json.dumps({"version": 1, "items": final}, ensure_ascii=False, indent=1),
                                             encoding="utf-8")
    print(f"seed/osym_examples.json: {len(final)} cümle, {len(per)} madde "
          f"(sorulduğu cümle {sum(1 for x in final if x['asked'])}); elenen çeviri {rejected}, anlam uymayan {sense_off}")


if __name__ == "__main__":
    cmds = {"raw": cmd_raw, "match": cmd_match, "match2": cmd_match2, "assemble": cmd_assemble}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print(__doc__)
        sys.exit(1)
    cmds[sys.argv[1]]()
