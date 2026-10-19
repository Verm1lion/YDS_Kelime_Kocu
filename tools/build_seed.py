"""Geliştirme aracı: xlsx'ten seed/ dosyalarını ve VERI_RAPORU.md'yi üretir.

Kullanım: .venv\\Scripts\\python tools\\build_seed.py [--batches N]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import importer, textutil as tu  # noqa: E402
from app.suggestions_data import LINKERS, PHRASAL_VERBS  # noqa: E402

BASE = ROOT.parent  # ...\INGILIZCE
XLSX = BASE / "YDS_Kelime_Calismasi" / "YDS_Akilli_Kelime_Havuzu.xlsx"
TXT = BASE / "YDS_Kelime_Calismasi" / "YDS_Havuz_Anki_Quizlet.txt"
SOURCES = BASE / "YDS_Kelime_Calismasi" / "Kaynaklar"
ANALYSIS = BASE / "Analiz" / "YDS_Kelime_ve_Soru_Analizi.xlsx"
SEED = ROOT / "seed"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batches", type=int, default=20)
    args = ap.parse_args()
    SEED.mkdir(exist_ok=True)

    parsed = importer.read_pool_xlsx(XLSX)
    items = parsed["items"]
    importer.assign_order(items)
    importer.add_zipf(items)
    importer.coverage_weights(items)
    for it in items:
        it["features"] = tu.word_features(it["lemma"], it.get("pos"), it["kind"])

    known = {it["lemma"] for it in items}
    known_forms = set(known)
    for it in items:
        if it.get("family"):
            for f in it["family"].replace(";", ",").split(","):
                if f.strip():
                    known_forms.add(tu.norm_en(f))

    # öneriler: listede olmayan bağlaç/geçiş ifadeleri ve öbek fiiller
    sugg = []
    heat = {tu.norm_en(h["phrase"]): h for h in importer.read_linker_heatmap(ANALYSIS)}
    for phrase, rel, tr, prio in LINKERS:
        lem = tu.norm_en(phrase)
        if lem in known_forms:
            continue
        h = heat.get(lem)
        sugg.append({"lemma": lem, "display": phrase, "kind": "linker", "pool": "suggestion", "pos": "bağlaç",
                     "meaning": tr, "relation": rel, "suggest_priority": prio,
                     "suggest_reason": (f"YDS bağlaç/geçiş ifadesi ({rel}); 2021–26 yayımlanan sorularda {h['total']} geçiş"
                                        if h and h.get("total") else f"YDS bağlaç/geçiş ifadesi ({rel})")})
    for phrase, tr, prio in PHRASAL_VERBS:
        lem = tu.norm_en(phrase)
        if lem in known_forms:
            continue
        sugg.append({"lemma": lem, "display": phrase, "kind": "phrasal", "pool": "suggestion", "pos": "fiil",
                     "meaning": tr, "suggest_priority": prio,
                     "suggest_reason": "YDS'de sık geçen öbek/edatlı fiil; listende yok"})
    for s in sugg:
        s["features"] = tu.word_features(s["lemma"], s.get("pos"), s["kind"])
        s["order_index"] = None
        s["cov_weight"] = 0.003
    try:
        from wordfreq import zipf_frequency
        for s in sugg:
            s["zipf"] = round(zipf_frequency(s["lemma"].replace(" ... ", " "), "en"), 2)
    except Exception:
        pass

    confus = importer.find_confusables(items)
    offline = importer.build_offline_dict(SOURCES, items + sugg)
    questions = importer.read_osym_questions(ANALYSIS)

    (SEED / "pool.json").write_text(json.dumps({"version": 1, "source": str(XLSX.name), "items": items},
                                               ensure_ascii=False, indent=0), encoding="utf-8")
    (SEED / "suggestions.json").write_text(json.dumps(sugg, ensure_ascii=False, indent=0), encoding="utf-8")
    (SEED / "confusables.json").write_text(json.dumps(confus, ensure_ascii=False, indent=0), encoding="utf-8")
    (SEED / "dict_offline.json").write_text(json.dumps(offline, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (SEED / "osym_questions.json").write_text(json.dumps(questions, ensure_ascii=False, indent=1), encoding="utf-8")

    report = importer.data_report(XLSX, TXT, parsed, confus)
    report += "\n## 11. Öneri listesi (listende olmayan YDS ifadeleri)\n\n"
    report += f"- Bağlaç/geçiş/edat öbeği önerisi: **{sum(1 for s in sugg if s['kind'] == 'linker')}**\n"
    report += f"- Öbek fiil önerisi: **{sum(1 for s in sugg if s['kind'] == 'phrasal')}**\n"
    report += "- Uygulamada Kelimeler → Öneriler sekmesinden onaylanınca plana girer.\n"
    report += f"\n## 12. Çevrimdışı sözlük\n\n- Hızlı ekleme için {len(offline)} kelimelik İngilizce→Türkçe sözlük (liste + Turksev + AFL + Seyfi).\n"
    report += f"- Gerçek ÖSYM kelime/dil bilgisi sorusu (haftalık test için): {len(questions)}\n"
    (ROOT / "VERI_RAPORU.md").write_text(report, encoding="utf-8")

    # içerik üretimi için girdi paketleri (ana liste + öbek fiiller + öneriler)
    gen = [it for it in items if it["pool"] == "main"]
    gen.sort(key=lambda i: i["order_index"])
    gen += sorted(sugg, key=lambda s: (-s["suggest_priority"], s["lemma"]))
    gdir = SEED / "gen_input"
    gdir.mkdir(exist_ok=True)
    for f in gdir.glob("batch_*.json"):
        f.unlink()
    n = args.batches
    size = math.ceil(len(gen) / n)
    for b in range(n):
        chunk = gen[b * size:(b + 1) * size]
        if not chunk:
            continue
        payload = [{"lemma": c["lemma"], "display": c["display"], "kind": c["kind"], "pos": c.get("pos"),
                    "meaning": c.get("meaning"), "family": c.get("family")} for c in chunk]
        (gdir / f"batch_{b + 1:02d}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"items={len(items)} main={sum(1 for i in items if i['pool'] == 'main')} "
          f"reserve={sum(1 for i in items if i['pool'] == 'reserve')} suggestions={len(sugg)} "
          f"confusables={len(confus)} dict={len(offline)} questions={len(questions)} gen={len(gen)} batch_size={size}")


if __name__ == "__main__":
    main()
