"""Tohum içerik doğrulayıcı.

Kullanım:
  python tools/validate_seed.py <batch_no>          # ör. 7  -> seed/gen_input/batch_07.json'u
                                                    #   seed/gen_output/batch_07_part*.jsonl ile karşılaştırır
  python tools/validate_seed.py all                 # tüm paketler (özet)

Kurallar (app/enrichment.py'deki LLM doğrulamasıyla aynı):
- Her girdi kelimesi tam bir kez; 'lemma' girdidekiyle aynı.
- examples: 3-5 adet; her birinde en, tr, form, domain; 'form' cümlede kelime sınırıyla geçmeli;
  tek kelimelik maddelerde en az 2 örnekte form == lemma (boşluk doldurma için).
- en: 8-40 kelime; tr boş olamaz.
- synonyms: liste (en fazla 6), antonyms: liste (en fazla 4), lemma'yı içeremez.
- family: [{w,pos,tr}] en fazla 6; confusables: [{w,why}] en fazla 4.
- mnemonic: 10-320 karakter; etymology: metin (boş olabilir); concrete: bool.
- senses: 1-4 adet [{pos,tr,en}].
- meaning_tr: girdi 'meaning' boşsa zorunlu.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import textutil as tu  # noqa: E402

IN_DIR = ROOT / "seed" / "gen_input"
OUT_DIR = ROOT / "seed" / "gen_output"


def item_forms(lemma: str) -> set[str]:
    base = lemma.replace(" ... ", " ").strip()
    forms = tu.all_forms(base, ["v", "n", "adj"])
    return {tu.norm_en(f) for f in forms}


def validate_item(inp: dict, out: dict) -> list[str]:
    errs: list[str] = []
    lemma = inp["lemma"]
    if tu.norm_en(out.get("lemma", "")) != lemma:
        errs.append(f"lemma uyuşmuyor: {out.get('lemma')!r} != {lemma!r}")
    if not inp.get("meaning") and not (out.get("meaning_tr") or "").strip():
        errs.append("meaning_tr gerekli (girdide anlam yok)")
    senses = out.get("senses")
    if not isinstance(senses, list) or not (1 <= len(senses) <= 4):
        errs.append("senses 1-4 öğeli liste olmalı")
    else:
        for s in senses:
            if not isinstance(s, dict) or not s.get("tr") or not s.get("en"):
                errs.append("senses öğesi {pos,tr,en} olmalı")
                break
    ex = out.get("examples")
    if not isinstance(ex, list) or not (3 <= len(ex) <= 5):
        errs.append("examples 3-5 öğeli liste olmalı")
        ex = ex if isinstance(ex, list) else []
    base_hits = 0
    is_multi = (" " in lemma) or ("..." in lemma)
    for i, e in enumerate(ex):
        if not isinstance(e, dict):
            errs.append(f"examples[{i}] nesne değil")
            continue
        en, tr, form = e.get("en", ""), e.get("tr", ""), e.get("form", "")
        if not en or not tr or not form or not e.get("domain"):
            errs.append(f"examples[{i}] en/tr/form/domain eksik")
            continue
        nw = len(en.split())
        if nw < 8 or nw > 40:
            errs.append(f"examples[{i}] uzunluk {nw} kelime (8-40)")
        if "..." in form:
            parts = [p.strip() for p in form.split("...") if p.strip()]
            if not all(re.search(r"(?<![A-Za-z])" + re.escape(p) + r"(?![A-Za-z])", en, re.I) for p in parts):
                errs.append(f"examples[{i}] form parçaları cümlede yok: {form!r}")
        elif not re.search(r"(?<![A-Za-z])" + re.escape(form) + r"(?![A-Za-z])", en, re.I):
            errs.append(f"examples[{i}] form cümlede birebir yok: {form!r}")
        if tu.norm_en(form) == lemma:
            base_hits += 1
    need = 1 if is_multi else 2
    if ex and base_hits < need:
        errs.append(f"form == lemma olan örnek sayısı {base_hits} (en az {need})")
    for key, mx in (("synonyms", 6), ("antonyms", 4)):
        v = out.get(key)
        if not isinstance(v, list) or len(v) > mx or any(not isinstance(s, str) or not s.strip() for s in v):
            errs.append(f"{key} en fazla {mx} metinlik liste olmalı")
        elif any(tu.norm_en(s) == lemma for s in v):
            errs.append(f"{key} kelimenin kendisini içeriyor")
    fam = out.get("family")
    if not isinstance(fam, list) or len(fam) > 6 or any(not isinstance(f, dict) or not f.get("w") for f in fam):
        errs.append("family en fazla 6 {w,pos,tr} öğeli liste olmalı")
    conf = out.get("confusables")
    if not isinstance(conf, list) or len(conf) > 4 or any(not isinstance(f, dict) or not f.get("w") for f in conf):
        errs.append("confusables en fazla 4 {w,why} öğeli liste olmalı")
    mn = out.get("mnemonic")
    if not isinstance(mn, str) or not (10 <= len(mn) <= 320):
        errs.append("mnemonic 10-320 karakter olmalı")
    if not isinstance(out.get("etymology", ""), str):
        errs.append("etymology metin olmalı")
    if not isinstance(out.get("concrete"), bool):
        errs.append("concrete true/false olmalı")
    return errs


def load_outputs(batch: str) -> tuple[list[dict], list[str]]:
    outs: list[dict] = []
    errs: list[str] = []
    for f in sorted(OUT_DIR.glob(f"batch_{batch}_part*.jsonl")):
        for ln, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            try:
                outs.append(json.loads(line))
            except json.JSONDecodeError as e:
                errs.append(f"{f.name}:{ln} JSON hatası: {e}")
    return outs, errs


def validate_batch(batch: str, verbose: bool = True) -> tuple[int, int, int]:
    inp = json.loads((IN_DIR / f"batch_{batch}.json").read_text(encoding="utf-8"))
    outs, errs = load_outputs(batch)
    by = {}
    dup = []
    for o in outs:
        k = tu.norm_en(o.get("lemma", ""))
        if k in by:
            dup.append(k)
        by[k] = o
    ok = bad = 0
    missing = []
    for it in inp:
        o = by.get(it["lemma"])
        if o is None:
            missing.append(it["lemma"])
            continue
        e = validate_item(it, o)
        if e:
            bad += 1
            if verbose:
                print(f"[HATA] {it['lemma']}: " + " | ".join(e))
        else:
            ok += 1
    extra = [k for k in by if k not in {i["lemma"] for i in inp}]
    if verbose:
        for e in errs:
            print("[JSON]", e)
        if dup:
            print("[TEKRAR]", ", ".join(dup))
        if extra:
            print("[FAZLA]", ", ".join(extra))
        print(f"batch_{batch}: geçerli {ok}/{len(inp)}, hatalı {bad}, eksik {len(missing)}")
        if missing:
            print("eksik:", ", ".join(missing))
    return ok, bad, len(missing)


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        return
    arg = sys.argv[1]
    if arg == "all":
        tot = [0, 0, 0]
        for f in sorted(IN_DIR.glob("batch_*.json")):
            b = f.stem.split("_")[1]
            r = validate_batch(b, verbose=False)
            print(f"batch_{b}: geçerli {r[0]}, hatalı {r[1]}, eksik {r[2]}")
            tot = [a + c for a, c in zip(tot, r)]
        print("TOPLAM geçerli/hatalı/eksik:", tot)
    else:
        validate_batch(f"{int(arg):02d}")


if __name__ == "__main__":
    main()
