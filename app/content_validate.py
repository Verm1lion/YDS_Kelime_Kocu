"""Üretilen kelime içeriği doğrulaması (tohum üretimi ve Gemini çıktısı için ortak)."""
from __future__ import annotations

import re

from . import textutil as tu


def validate_item(inp: dict, out: dict, strict_examples: bool = True) -> list[str]:
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
    if not isinstance(ex, list) or not ((3 if strict_examples else 1) <= len(ex) <= 5):
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
    if strict_examples and ex and base_hits < need:
        errs.append(f"form == lemma olan örnek sayısı {base_hits} (en az {need})")
    for key, mx in (("synonyms", 6), ("antonyms", 4)):
        v = out.get(key, [])
        if not isinstance(v, list) or len(v) > mx or any(not isinstance(s, str) or not s.strip() for s in v):
            errs.append(f"{key} en fazla {mx} metinlik liste olmalı")
        elif any(tu.norm_en(s) == lemma for s in v):
            errs.append(f"{key} kelimenin kendisini içeriyor")
    fam = out.get("family", [])
    if not isinstance(fam, list) or len(fam) > 6 or any(not isinstance(f, dict) or not f.get("w") for f in fam):
        errs.append("family en fazla 6 {w,pos,tr} öğeli liste olmalı")
    conf = out.get("confusables", [])
    if not isinstance(conf, list) or len(conf) > 4 or any(not isinstance(f, dict) or not f.get("w") for f in conf):
        errs.append("confusables en fazla 4 {w,why} öğeli liste olmalı")
    mn = out.get("mnemonic")
    if not isinstance(mn, str) or not (10 <= len(mn) <= 320):
        errs.append("mnemonic 10-320 karakter olmalı")
    if not isinstance(out.get("etymology", ""), str):
        errs.append("etymology metin olmalı")
    if "concrete" in out and not isinstance(out.get("concrete"), bool):
        errs.append("concrete true/false olmalı")
    return errs


def clean_examples(inp: dict, examples: list) -> list[dict]:
    """Geçerli örnekleri süzer (LLM çıktısında kısmi kabul için)."""
    ok = []
    for e in examples or []:
        if not isinstance(e, dict):
            continue
        en, tr, form = e.get("en", ""), e.get("tr", ""), e.get("form", "")
        if not en or not tr or not form:
            continue
        if not (8 <= len(en.split()) <= 40):
            continue
        if "..." not in form and not re.search(r"(?<![A-Za-z])" + re.escape(form) + r"(?![A-Za-z])", en, re.I):
            continue
        ok.append({"en": en.strip(), "tr": tr.strip(), "form": form.strip(), "domain": e.get("domain") or "genel"})
    return ok
