"""Ezberbozan planı: kitap günleri partlara bölünmeden gelir (Gün N · A/B/Ek), kitabın eş anlamlıları kelimenin yanında,
kitap dışı yalnızca garanti kelimeler etkin, eski liste yedekte, puan modeli kapsama oranını etkin listeye göre ölçer."""
import json

import pytest

from app import config, parts as P, session, words as W

# Kitap verisi (seed/ezberbozan.json + kitap tabanlı seed/pool.json) telif nedeniyle repoda yok; yalnızca yerelde koşar.
pytestmark = pytest.mark.skipif(not (config.seed_dir() / "ezberbozan.json").exists() or
                                not (config.seed_dir() / "pool.json").exists(),
                                reason="kitap verisi yok (yalnızca yerel kurulumda)")


def _ezb():
    return json.loads((config.seed_dir() / "ezberbozan.json").read_text(encoding="utf-8"))


def test_active_list_is_the_book_plus_guaranteed_words(appdb):
    data = _ezb()
    want = {it["lemma"] for it in data["items"]}
    active = {r["lemma"] for r in appdb.q("SELECT lemma FROM words WHERE status='active'")}
    assert want <= active and len(active - want) == 0          # etkin liste = kitap + garanti (kullanıcı eklemesi yok)
    c = data["counts"]
    assert c["day_words"] == 1078 and c["garanti"] > 100 and c["total"] == len(want)
    inactive = appdb.val("SELECT COUNT(*) FROM words WHERE status='inactive' AND pool='reserve'")
    assert inactive > 2000                                     # eski liste silinmedi, yedekte
    order = [r["lemma"] for r in appdb.q("SELECT lemma FROM words WHERE status='active' ORDER BY order_index LIMIT 3")]
    assert order == [it["lemma"] for it in data["items"][:3]] == ["necessary", "occur", "penetrate"]


def test_parts_follow_the_book_days(appdb):
    titles = []
    for _ in range(3):
        p = P.next_part()
        titles.append((p["title"], p["total"]))
        for w in P.remaining_words(p["id"]):                     # partı bitmiş say (sıradakine geç)
            appdb.x("UPDATE cards SET stage=4 WHERE word_id=?", (w,))
        P.refresh(p["id"])
    assert titles[0] == ("Gün 1 · A", 10) and titles[1] == ("Gün 1 · B", 10)
    assert titles[2][0] == "Gün 1 · Ek" and 5 <= titles[2][1] <= 13
    r = session.start("part")
    assert r["label"].startswith("Part 4 · Gün 2 · A")


def test_book_synonyms_come_first_next_to_the_word(appdb):
    wid = W.index()["by_lemma"]["necessary"]
    syn = W.synonyms_for(wid, 6)
    assert [x["w"] for x in syn[:3]] == ["essential", "needed", "required"]
    p, _ = session.X.intro(wid)
    assert p["synonyms"][0]["w"] == "essential" and p["book"] == "Ezberbozan · 1. gün"
    assert appdb.val("SELECT COUNT(*) FROM word_info WHERE source='ezberbozan' AND field='synonyms'") > 300
    lk = W.index()["by_lemma"].get("although")
    if lk:
        pl, _ = session.X.intro(lk)
        assert pl["usage"] and "Zıtlık" in pl["usage"]          # bağlaç türü ve anlam grubu kartta


def test_score_model_measures_coverage_of_the_new_list(appdb):
    from app import score_model as S
    v = S.list_covers_asked()
    assert 0.6 <= v <= 0.9                                       # kitap + garanti: gerçek cevapların ~%71'i (ölçekli ~0,78)


def test_packaging_includes_book_seed_files():
    from pathlib import Path
    spec = (Path(__file__).resolve().parent.parent / "yds_kocu.spec").read_text(encoding="utf-8")
    assert '"ezberbozan.json"' in spec and '"osym_vocab_answers.json"' in spec
