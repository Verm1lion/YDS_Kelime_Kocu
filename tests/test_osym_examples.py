"""Gerçek ÖSYM cümleleri: bir kez yüklenir, örnek seçiminde önce gelir; üretim aracı uydurma cümleyi ve yanlış şıkkı eler."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _tool():
    spec = importlib.util.spec_from_file_location("build_osym_examples", ROOT / "tools" / "build_osym_examples.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_installer_bundles_every_seed_file_the_app_reads():
    """Uygulamanın seed/ altından okuduğu her dosya exe paketinde olmalı (yds_kocu.spec dosyaları tek tek listeler)."""
    import re
    spec = (ROOT / "yds_kocu.spec").read_text(encoding="utf-8")
    read = {"content.jsonl"}
    for py in (ROOT / "app").glob("*.py"):
        read |= set(re.findall(r'seed_dir\(\) / "([^"]+)"', py.read_text(encoding="utf-8")))
    missing = [f for f in sorted(read) if f'"{f}"' not in spec]
    assert not missing, f"pakete eklenmemiş tohum dosyası: {missing}"


def test_shipped_real_sentences_are_loaded(appdb):
    n = appdb.val("SELECT COUNT(*) FROM examples WHERE source LIKE 'osym:%'")
    words = appdb.val("SELECT COUNT(DISTINCT word_id) FROM examples WHERE source LIKE 'osym:%'")
    assert n > 2000 and words > 1000
    bad = appdb.q("""SELECT en FROM examples WHERE source LIKE 'osym:%' AND
                     (verified!=1 OR tr IS NULL OR length(tr) < 10 OR instr(en, '----') > 0)""")
    assert not bad


def test_real_sentences_load_once_and_come_first(appdb, tmp_path):
    from app import exercises as X, seed_loader, words as W
    appdb.x("DELETE FROM examples WHERE source LIKE 'osym:%'")         # yalnızca bu testin cümlesiyle
    appdb.x("DELETE FROM meta WHERE key='osym_examples_sha'")
    row = appdb.q1("""SELECT w.id, w.lemma FROM words w WHERE w.kind='word' AND w.status='active'
                      AND EXISTS (SELECT 1 FROM examples e WHERE e.word_id=w.id) ORDER BY w.id LIMIT 1""")
    wid, lemma = row["id"], row["lemma"]
    sent = f"Researchers have long argued that the {lemma} of modern societies depends on reliable information."
    data = {"version": 1, "items": [{"lemma": lemma, "en": sent, "tr": "Araştırmacılar uzun zamandır bunu savunuyor.",
                                     "form": lemma, "domain": "sınav", "source": "YDS 2021/1 · 1. soru", "asked": True,
                                     "year": 2021}]}
    p = tmp_path / "osym_examples.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert seed_loader.load_osym_examples(p) == 1
    assert seed_loader.load_osym_examples(p) == 0                     # aynı dosya: yeniden eklenmez
    ex = W.pick_example(wid)
    assert ex["en"] == sent and ex["source"] == "osym:YDS 2021/1 · 1. soru" and ex["verified"] == 1
    W.mark_example_shown(ex["id"])
    assert W.pick_example(wid)["source"] == "seed"                    # gösterildikten sonra dönüşüm sürer
    W.mark_example_shown(W.pick_example(wid)["id"])
    shown = W.pick_example(wid)
    assert shown["source"] == "seed" or shown["en"] == sent


def test_tool_rejects_invented_sentences_and_wrong_answers():
    t = _tool()
    raw = ("1. - 6. sorularda ...\nUNICEF is deeply committed to creating a world in\nwhich all children, regardless of their gender or\n"
           "socioeconomic background, have ---- to free,\ncompulsory and quality education.\nA) B) C)\nE)D)\n"
           "access\ndedication\ninsight\naddiction\ntendency\nThe study of ancient languages helps re-\n"
           "searchers understand how early societies were organised.\n")
    raws = t._raw_forms(raw)
    key = {"1": "A"}
    stem = ("UNICEF is deeply committed to creating a world in which all children, regardless of their gender or "
            "socioeconomic background, have ---- to free, compulsory and quality education.")
    good = {"q": 1, "stem": stem, "fills": [{"q": 1, "letter": "A", "option": "access"}],
            "sentence": stem.replace("----", "access")}
    assert t._verify(good, raw, raws, key) is None
    wrong = {**good, "fills": [{"q": 1, "letter": "B", "option": "dedication"}], "sentence": stem.replace("----", "dedication")}
    assert "cevap" in t._verify(wrong, raw, raws, key)
    assert t._verify({"q": 9, "sentence": "The study of ancient languages helps researchers understand how early societies were organised."},
                     raw, raws, key) is None                           # satır sonu bölünmesi onarılmış cümle kabul
    invented = {"q": 9, "sentence": "Modern cities increasingly rely on renewable energy sources to reduce their emissions."}
    assert t._verify(invented, raw, raws, key) == "ham metinde yok"
    assert t.fill_blanks("They ---- to decide what penalties ----.", "tried / would have to pay") == \
        "They tried to decide what penalties would have to pay."
    assert t.exam_label("2012_UDS_Sonbahar_Ingilizce_Saglik_TAM") == ("ÜDS 2012 Sonbahar (Sağlık)", 2012)
    assert t.exam_label("2019_YDS_2_yuzde10") == ("YDS 2019/2", 2019)
