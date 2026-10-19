"""Gemini model zinciri: kota/yoğunlukta model değiştirme, günlük kota bekletmesi, zenginleştirme kuyruğu (ağsız)."""
import json

import pytest


@pytest.fixture()
def fake_llm(appdb, monkeypatch):
    from app import llm
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(llm, "available_models", lambda key: None)
    monkeypatch.setattr(llm, "_last_call", 0.0)
    appdb.set_setting("llm_rpm", 6000)
    calls = []

    def install(behaviour):
        def fake_http(method, url, body, key, timeout=240):
            model = url.split("/models/")[1].split(":")[0]
            calls.append(model)
            b = behaviour.get(model, "ok")
            if b == "ok":
                return {"candidates": [{"content": {"parts": [{"text": json.dumps({"ok": True, "m": "**kalın** metin"})}]}}],
                        "usageMetadata": {"totalTokenCount": 10}}
            code, text = b
            raise llm._HttpFail(code, text)
        monkeypatch.setattr(llm, "_http", fake_http)
    return llm, calls, install


def test_rotates_on_overload_and_daily_quota(fake_llm):
    llm, calls, install = fake_llm
    quota = json.dumps({"error": {"code": 429, "details": [{"violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]},
                                                           {"retryDelay": "40s"}]}})
    install({"gemini-3.5-flash": (503, "high demand"), "gemini-flash-latest": (429, quota)})
    obj, meta = llm.generate_json("x")
    assert meta["model"] == "gemini-2.5-flash"
    assert obj["m"] == "kalın metin"                       # markdown temizlendi
    assert calls == ["gemini-3.5-flash", "gemini-flash-latest", "gemini-2.5-flash"]
    cds = llm._cooldowns()
    assert cds["gemini-3.5-flash"]["until"] - __import__("time").time() <= 301   # yoğunluk: 5 dk
    left = cds["gemini-flash-latest"]["until"] - __import__("time").time()
    assert abs(left - llm._seconds_until_quota_reset()) < 10 and left > 60   # günlük kota: Pasifik gece yarısına kadar
    # dinlenen modeller atlanır
    calls.clear()
    llm.generate_json("y")
    assert calls == ["gemini-2.5-flash"]


def test_truncated_thinking_response_retries_once_with_bigger_budget(fake_llm, monkeypatch):
    llm, calls, install = fake_llm
    budgets = []

    def thinking_http(method, url, body, key, timeout=240):
        model = url.split("/models/")[1].split(":")[0]
        mt = body["generationConfig"]["maxOutputTokens"]
        budgets.append((model, mt))
        if mt < 8192:                                    # düşünme bütçeyi yedi: görünür metin yok
            return {"candidates": [{"finishReason": "MAX_TOKENS", "content": {"role": "model"}}],
                    "usageMetadata": {"totalTokenCount": mt}}
        return {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": '{"ok": true}'}]}}],
                "usageMetadata": {"totalTokenCount": 50}}
    monkeypatch.setattr(llm, "_http", thinking_http)
    obj, meta = llm.generate_json("x", max_tokens=200)
    assert obj == {"ok": True} and meta["model"] == "gemini-3.5-flash"   # zincirde aşağı düşmeden aynı model
    assert budgets == [("gemini-3.5-flash", 200), ("gemini-3.5-flash", 8192)]
    assert "gemini-3.5-flash" not in llm._cooldowns()

    # hep kesilirse: model başına tek genişletme, sonra sıradaki model; hata nedenini söyler
    budgets.clear()

    def always_cut(method, url, body, key, timeout=240):
        model = url.split("/models/")[1].split(":")[0]
        budgets.append((model, body["generationConfig"]["maxOutputTokens"]))
        return {"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": '{"ok": tr'}]}}]}
    monkeypatch.setattr(llm, "_http", always_cut)
    with pytest.raises(llm.LLMError) as ei:
        llm.generate_json("x", max_tokens=200)
    assert [b for m, b in budgets if m == "gemini-3.5-flash"] == [200, 8192]
    assert len(budgets) == 2 * len(llm.DEFAULT_CHAIN)
    assert "kesildi" in str(ei.value) and not ei.value.fatal
    # zaten geniş bütçeli istek (zenginleştirme) yeniden denenmez
    budgets.clear()
    with pytest.raises(llm.LLMError):
        llm.generate_json("x", max_tokens=llm.MAX_BUDGET)
    assert len(budgets) == len(llm.DEFAULT_CHAIN)


def test_all_models_failing_raises_retryable(fake_llm):
    llm, calls, install = fake_llm
    install({m: (503, "busy") for m in llm.DEFAULT_CHAIN})
    with pytest.raises(llm.LLMError) as ei:
        llm.generate_json("x")
    assert not ei.value.fatal and ei.value.retry_after >= 30


def test_invalid_key_is_fatal(fake_llm):
    llm, calls, install = fake_llm
    install({"gemini-3.5-flash": (400, "API key not valid. Please pass a valid API key.")})
    with pytest.raises(llm.LLMError) as ei:
        llm.generate_json("x")
    assert ei.value.fatal


def test_daily_limit_stops_requests(fake_llm):
    llm, calls, install = fake_llm
    install({})
    llm.db.set_setting("llm_daily_requests", 3)
    for _ in range(3):
        llm.generate_json("x")
    with pytest.raises(llm.LLMError) as ei:
        llm.generate_json("x")
    assert "günlük istek" in str(ei.value) and len(calls) == 3


def test_enrichment_only_for_words_entering_the_plan(fake_llm, monkeypatch):
    llm, calls, install = fake_llm
    from app import db, enrichment, list_import, words as W

    def jobs():
        return [json.loads(j["payload"]) for j in db.q("SELECT payload FROM llm_jobs WHERE kind='enrich' ORDER BY id")]
    reserve = db.q("""SELECT w.id, w.lemma, w.display FROM words w WHERE w.pool='reserve' AND NOT EXISTS
                      (SELECT 1 FROM examples e WHERE e.word_id=w.id) ORDER BY w.id LIMIT 3""")
    a, b, c = reserve
    # gece işi plana girmemiş yedek kartlar için istek açmaz
    enrichment.queue_missing()
    assert not {i for j in jobs() for i in j["word_ids"]} & {r["id"] for r in db.q("SELECT id FROM words WHERE pool='reserve'")}
    db.x("DELETE FROM llm_jobs")
    # deneme sınavından yedekteki bir kelime eklenince hemen kuyruğa girer; ikinci ekleme yinelemez
    assert W.add_user_word(a["display"])["status"] == "existing"
    W.add_user_word(a["display"])
    assert [j["word_ids"] for j in jobs()] == [[a["id"]]]
    # önce gelen toplu iş olsa bile kullanıcının eklediği kelime önce işlenir
    db.x("DELETE FROM llm_jobs")
    db.x("UPDATE words SET status='active' WHERE id=?", (b["id"],))
    enrichment.queue_enrich([b["id"]], reason="yedek plana alındı")
    W.add_user_word(a["display"])
    prompts = []

    def fake_generate(prompt, max_tokens=0, temperature=0):
        prompts.append(prompt)
        return {"items": []}, {"model": "gemini-test"}
    monkeypatch.setattr(llm, "generate_json", fake_generate)
    enrichment.process_one()
    assert f'"lemma": "{a["lemma"]}"' in prompts[0] and f'"lemma": "{b["lemma"]}"' not in prompts[0]
    # bu arada plandan çıkan kelime için istek gönderilmez
    db.x("DELETE FROM llm_jobs")
    enrichment.queue_enrich([c["id"]], reason="x")
    prompts.clear()
    r = enrichment.process_one()
    assert r["ok"] and r["result"] == "boş" and prompts == []
    # listeden içe aktarma kelime başına değil 8'lik paketlerle kuyruğa girer
    db.x("DELETE FROM llm_jobs")
    data = "\n".join(f"zqxword{k}\tanlam {k}" for k in range(10)).encode("utf-8")
    assert list_import.import_bytes("liste.txt", data)["added"] == 10
    assert [len(j["word_ids"]) for j in jobs()] == [8, 2]


def test_enrich_job_end_to_end_with_fake_model(fake_llm, monkeypatch):
    llm, calls, install = fake_llm
    from app import enrichment, words as W
    r = W.add_user_word("serendipity", meaning="tesadüfen güzel bir şey bulma")
    item = {"lemma": "serendipity", "meaning_tr": None,
            "senses": [{"pos": "isim", "tr": "mutlu tesadüf", "en": "finding good things by chance"}],
            "examples": [{"en": f"Many scientific discoveries owe a great deal to serendipity rather than careful planning {k}.",
                          "tr": "Birçok bilimsel keşif dikkatli planlamadan çok mutlu tesadüfe borçludur.",
                          "form": "serendipity", "domain": "bilim"} for k in range(4)],
            "synonyms": ["chance", "luck"], "antonyms": [], "family": [], "confusables": [],
            "mnemonic": "SERENDIPITY → 'seren dip': Denizin dibinde tesadüfen hazine bulursun.", "etymology": "", "concrete": False}

    def fake_generate(prompt, max_tokens=0, temperature=0):
        return {"items": [item]}, {"model": "gemini-test"}
    monkeypatch.setattr(llm, "generate_json", fake_generate)
    res = enrichment.process_one()
    assert res["ok"]
    assert len(W.examples(r["id"])) == 4
    assert W.examples(r["id"])[0]["source"] == "gemini:gemini-test" and W.examples(r["id"])[0]["verified"] == 0
    assert W.get_word(r["id"])["meaning_user"] == "tesadüfen güzel bir şey bulma"   # kullanıcı anlamı ezilmedi


def test_quota_reset_follows_pacific_dst():
    from datetime import datetime, timezone
    from app import llm
    # 4 Ekim 2026 07:51 UTC (PDT): sıfırlanma ertesi gün 07:05 UTC
    s = llm._seconds_until_quota_reset(datetime(2026, 10, 4, 7, 51, tzinfo=timezone.utc))
    assert abs(s - (23 * 3600 + 14 * 60)) < 2
    # 10 Kasım 2026 03:00 UTC (PST): sıfırlanma aynı gün 08:05 UTC
    s = llm._seconds_until_quota_reset(datetime(2026, 11, 10, 3, 0, tzinfo=timezone.utc))
    assert abs(s - (5 * 3600 + 5 * 60)) < 2
