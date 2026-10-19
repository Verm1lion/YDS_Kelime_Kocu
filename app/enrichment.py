"""LLM iş kuyruğu: zenginleştirme, müdahale içeriği, haftalık rapor metni.

Tüm üretilen içerik 'doğrulanmamış' olarak veritabanına yazılır; kullanıcının anlamı asla ezilmez.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import timedelta

from . import config, db, llm
from . import content_validate as CV
from . import textutil as tu
from . import words as W

BATCH = 8
MAX_ATTEMPTS = 6
_worker_lock = threading.Lock()

ENRICH_PROMPT = """Sen Türkiye'deki YDS sınavı (ÖSYM, akademik okuma ağırlıklı İngilizce) için içerik hazırlayan bir uzmansın.
Öğrenci B1 düzeyinde, hedefi 55+ puan. Aşağıdaki her madde için TEK bir JSON nesnesi üret; çıktı {"items": [...]} biçiminde olsun.

Şema (her madde):
{"lemma": "<girdideki lemma>", "meaning_tr": null veya (girdide anlam yoksa) kısa Türkçe anlam,
 "senses": [{"pos": "fiil|isim|sıfat|zarf|bağlaç|edat|öbek fiil", "tr": "kısa Türkçe", "en": "≤15 kelime İngilizce tanım"}] (1-3),
 "examples": [{"en": "...", "tr": "...", "form": "cümlede geçen biçim", "domain": "bilim|sağlık|tarih|sosyal|psikoloji|ekonomi|çevre|eğitim|teknoloji|dil"}] (TAM 4, farklı alanlar),
 "synonyms": [2-5 eş anlamlı], "antonyms": [0-3], "family": [{"w":"","pos":"","tr":""}] (0-5),
 "confusables": [{"w":"", "why":"kısa Türkçe: diğerinin anlamı + fark"}] (0-3),
 "mnemonic": "Türkçe anahtar-kelime yöntemi ipucu, İngilizce kelime BÜYÜK HARFLE, ≤220 karakter",
 "etymology": "Türkçe 1 cümle kök/ek çözümlemesi (emin değilsen yalnızca biçimsel; uydurma)",
 "concrete": true/false}

Kurallar: Örnekler ÖSYM okuma parçası üslubunda, 14-28 kelime, resmî ve bilgi veren; hedef kelime cümlede tam bir kez.
"form" cümlede birebir geçmeli. Tek kelimelik maddelerde en az 2 örnekte form tam olarak lemma olsun (boşluk doldurma için).
Öbek fiillerde parçalar bitişik dursun. Bağlamdan anlam tahmin edilebilsin. Türkçe çeviriler doğal ve doğru Türkçe karakterli.
Listedeki Türkçe anlamla çelişme.

Maddeler:
{items}
"""

INTERVENTION_PROMPT = """YDS'ye hazırlanan B1 düzeyindeki bir Türk öğrenci "{word}" ({meaning}) kelimesini {wrong} kez yanlış yaptı.
Hata profili: {profile}. {conf_line}
Ona yardım edecek yeni içerik üret. Yalnızca şu JSON'u döndür:
{{"mnemonic": "Öncekinden FARKLI yaklaşımla yeni Türkçe hafıza ipucu (anahtar kelime/ses benzerliği ya da canlı imge), İngilizce kelime BÜYÜK HARFLE, ≤220 karakter",
 "root": "Türkçe kök/ek/köken açıklaması (emin değilsen biçimsel çözümleme), 1-2 cümle",
 "examples": [{{"en": "ÖSYM üslubunda 14-28 kelimelik cümle", "tr": "doğal Türkçe çeviri", "form": "cümlede geçen biçim", "domain": "alan"}}] (2 adet, bağlamdan anlam açıkça çıkarılabilsin),
 "compare_tip": "{conf_word} ile farkını hatırlatan kısa Türkçe ipucu (karışık kelime yoksa boş)"}}
"""

REPORT_PROMPT = """Aşağıdaki sayılar bir YDS kelime çalışma uygulamasının haftalık verisidir (öğrenci: {name}).
Bu sayıları KULLANARAK (yeni sayı uydurma, yuvarlama dışında değiştirme) Türkçe, samimi ama net, motivasyon klişesi
olmayan bir haftalık rapor yaz: 1) haftanın özeti, 2) güçlü yanlar, 3) zayıf noktalar ve somut öneriler (sayılara dayalı),
4) gelecek hafta için 3 maddelik plan. En fazla ~250 kelime. Yalnızca şu JSON'u döndür: {{"text": "..."}}

Veri:
{stats}
"""


# ---------------------------------------------------------------- kuyruk
def queue(kind: str, payload: dict, dedupe_key: str | None = None) -> int:
    now = config.iso(config.now_utc())
    if dedupe_key:
        ex = db.q1("SELECT id FROM llm_jobs WHERE kind=? AND status IN ('queued','running') AND payload LIKE ?",
                   (kind, f'%"key": "{dedupe_key}"%'))
        if ex:
            return ex["id"]
        payload = {**payload, "key": dedupe_key}
    return db.x("INSERT INTO llm_jobs(kind, payload, status, created_at, updated_at) VALUES(?,?, 'queued', ?, ?)",
                (kind, json.dumps(payload, ensure_ascii=False), now, now))


def queue_enrich(word_ids: list[int], reason: str = "") -> list[int]:
    jobs = []
    for i in range(0, len(word_ids), BATCH):
        chunk = word_ids[i:i + BATCH]
        jobs.append(queue("enrich", {"word_ids": chunk, "reason": reason}))
    return jobs


def queue_missing(word_ids: list[int] | None = None, reason: str = "eksik içerik") -> int:
    """İçeriği olmayan etkin kelimeler (kullanıcı eklemeleri, onaylanan öneriler, plana alınan yedek) için iş oluşturur.

    Gemini yalnızca plana giren kelimeler için çalışır; `word_ids` verilirse yalnızca onlara bakılır.
    """
    rows = db.q("""SELECT w.id FROM words w WHERE w.status='active' AND NOT EXISTS
                   (SELECT 1 FROM examples e WHERE e.word_id=w.id) ORDER BY w.order_index""")
    only = set(word_ids) if word_ids is not None else None
    ids = [r["id"] for r in rows if only is None or r["id"] in only]
    queued = set()
    for r in db.q("SELECT payload FROM llm_jobs WHERE kind='enrich' AND status IN ('queued','running')"):
        queued |= set(json.loads(r["payload"]).get("word_ids", []))
    ids = [i for i in ids if i not in queued]
    queue_enrich(ids, reason=reason)
    return len(ids)


def queue_intervention(word_id: int, intervention_id: int, confused_with: int | None) -> int:
    return queue("intervention", {"word_id": word_id, "intervention_id": intervention_id,
                                  "confused_with": confused_with}, dedupe_key=f"iv{intervention_id}")


def queue_report(report_id: int) -> int:
    return queue("weekly_report", {"report_id": report_id}, dedupe_key=f"rep{report_id}")


# ---------------------------------------------------------------- işleyiciler
def _enrich(job: dict, payload: dict) -> str:
    ids = payload.get("word_ids", [])
    items = []
    for wid in ids:
        w = W.get_word(wid)
        if not w or w["status"] != "active":   # bu arada plandan çıkan kelime için kota harcama
            continue
        items.append({"lemma": w["lemma"], "display": w["display"], "kind": w["kind"], "pos": w.get("pos"),
                      "meaning": W.effective_meaning(w) or None, "family": w.get("family_src")})
    if not items:
        return "boş"
    obj, meta = llm.generate_json(ENRICH_PROMPT.replace("{items}", json.dumps(items, ensure_ascii=False, indent=1)),
                                  max_tokens=llm.MAX_BUDGET)
    outs = obj.get("items", obj) if isinstance(obj, dict) else obj
    if not isinstance(outs, list):
        raise llm.LLMError("beklenmeyen biçim", retry_after=30)
    by = {tu.norm_en(o.get("lemma", "")): o for o in outs if isinstance(o, dict)}
    now = config.iso(config.now_utc())
    src = f"gemini:{meta.get('model')}"
    done, partial, missing = 0, 0, []
    from .seed_loader import insert_content
    for it in items:
        o = by.get(it["lemma"])
        if not o:
            missing.append(it["lemma"])
            continue
        errs = CV.validate_item(it, o, strict_examples=False)
        wid = db.val("SELECT id FROM words WHERE lemma=?", (it["lemma"],))
        if errs:
            o["examples"] = CV.clean_examples(it, o.get("examples"))
            partial += 1
        if not o.get("examples") and not o.get("mnemonic"):
            missing.append(it["lemma"])
            continue
        with db.tx() as conn:
            insert_content(conn, wid, o, source=src, now=now)
        done += 1
    W.invalidate_index()
    if missing:
        ids_missing = [db.val("SELECT id FROM words WHERE lemma=?", (m,)) for m in missing]
        if payload.get("retry", 0) < 2:
            queue("enrich", {"word_ids": [i for i in ids_missing if i], "retry": payload.get("retry", 0) + 1,
                             "reason": payload.get("reason", "")})
    return f"{done} kelime zenginleştirildi ({partial} kısmi), {len(missing)} yeniden kuyrukta"


def _intervention(job: dict, payload: dict) -> str:
    wid = payload["word_id"]
    it = W.index()["items"].get(wid)
    if not it:
        return "kelime yok"
    iv = db.q1("SELECT * FROM interventions WHERE id=?", (payload["intervention_id"],))
    content = db.jload(iv["content"], {}) if iv else {}
    conf = W.index()["items"].get(payload.get("confused_with")) if payload.get("confused_with") else None
    prompt = INTERVENTION_PROMPT.format(
        word=it["display"], meaning=it["meaning"], wrong=content.get("wrong_total", "birkaç"),
        profile=json.dumps(content.get("error_profile", {}), ensure_ascii=False),
        conf_line=(f"En çok '{conf['display']}' ({conf['short']}) ile karıştırıyor." if conf else ""),
        conf_word=(conf["display"] if conf else "—"))
    obj, meta = llm.generate_json(prompt, max_tokens=8192)
    if not isinstance(obj, dict):
        raise llm.LLMError("beklenmeyen biçim", retry_after=30)
    now = config.iso(config.now_utc())
    src = f"gemini:{meta.get('model')}"
    added = []
    if obj.get("mnemonic"):
        db.x("INSERT INTO mnemonics(word_id, text, kind, source, verified, created_at) VALUES(?,?,?,?,0,?)",
             (wid, obj["mnemonic"].strip(), "association", src, now))
        added.append({"kind": "mnemonic", "title": "Yeni hafıza ipucu (yapay zekâ)", "text": obj["mnemonic"], "source": src})
    if obj.get("root"):
        db.x("INSERT INTO mnemonics(word_id, text, kind, source, verified, created_at) VALUES(?,?,?,?,0,?)",
             (wid, obj["root"].strip(), "etymology", src, now))
        added.append({"kind": "etymology", "title": "Kök / köken (yapay zekâ)", "text": obj["root"], "source": src})
    exs = CV.clean_examples({"lemma": it["lemma"]}, obj.get("examples"))
    for e in exs:
        db.x("""INSERT INTO examples(word_id, en, tr, form, domain, source, verified, created_at)
                VALUES(?,?,?,?,?,?,0,?)""", (wid, e["en"], e["tr"], e["form"], e["domain"], src, now))
    if exs:
        added.append({"kind": "examples", "title": "Yeni bağlamlar (yapay zekâ)", "items": exs})
    if obj.get("compare_tip") and conf:
        added.append({"kind": "tip", "title": f"{it['display']} / {conf['display']}", "text": obj["compare_tip"], "source": src})
    if iv and added:
        content.setdefault("sections", [])
        if not iv["shown_at"]:
            content["sections"] = added + content["sections"]
        else:
            content["llm_followup"] = added
        db.x("UPDATE interventions SET content=?, source=? WHERE id=?", (db.jdump(content), src, iv["id"]))
    return f"{len(added)} bölüm eklendi"


def _report(job: dict, payload: dict) -> str:
    rep = db.q1("SELECT * FROM weekly_reports WHERE id=?", (payload["report_id"],))
    if not rep:
        return "rapor yok"
    stats = db.jload(rep["stats"], {})
    prompt = REPORT_PROMPT.format(name=db.get_setting("user_name", "") or "adı belirtilmemiş",
                                  stats=json.dumps(stats, ensure_ascii=False, indent=1))
    obj, meta = llm.generate_json(prompt, max_tokens=8192, temperature=0.5)
    text = obj.get("text") if isinstance(obj, dict) else None
    if not text:
        raise llm.LLMError("rapor metni yok", retry_after=60)
    db.x("UPDATE weekly_reports SET text=?, source=? WHERE id=?", (text.strip(), f"gemini:{meta.get('model')}", rep["id"]))
    return "rapor yazıldı"


HANDLERS = {"enrich": _enrich, "intervention": _intervention, "weekly_report": _report}


def process_one() -> dict | None:
    """Sıradaki uygun işi çalıştırır. Anahtar yoksa hiçbir şey yapmaz."""
    if not llm.api_key():
        return None
    if not _worker_lock.acquire(blocking=False):
        return None
    try:
        now = config.iso(config.now_utc())
        job = db.q1("""SELECT * FROM llm_jobs WHERE status='queued' AND (not_before IS NULL OR not_before<=?)
                       ORDER BY CASE kind WHEN 'intervention' THEN 0 WHEN 'weekly_report' THEN 1 ELSE 2 END,
                                CASE WHEN payload LIKE '%"reason": "user_add"%' THEN 0 ELSE 1 END, id LIMIT 1""",
                    (now,))
        if not job:
            return None
        db.x("UPDATE llm_jobs SET status='running', attempts=attempts+1, updated_at=? WHERE id=?", (now, job["id"]))
        payload = json.loads(job["payload"] or "{}")
        try:
            msg = HANDLERS[job["kind"]](job, payload)
            db.x("UPDATE llm_jobs SET status='done', result=?, error=NULL, updated_at=? WHERE id=?",
                 (msg, config.iso(config.now_utc()), job["id"]))
            return {"id": job["id"], "kind": job["kind"], "ok": True, "result": msg}
        except llm.LLMError as e:
            attempts = (job["attempts"] or 0) + 1
            fatal = e.fatal or attempts >= MAX_ATTEMPTS
            delay = e.retry_after if e.retry_after is not None else 60 * (2 ** attempts)
            nb = config.iso(config.now_utc() + timedelta(seconds=delay))
            # bağlantı/anahtar sorunlarında deneme hakkı harcanmasın
            if "bağlantı yok" in str(e) or "anahtarı yok" in str(e) or "günlük istek" in str(e):
                db.x("UPDATE llm_jobs SET status='queued', attempts=attempts-1, error=?, not_before=?, updated_at=? WHERE id=?",
                     (str(e)[:400], nb, config.iso(config.now_utc()), job["id"]))
            else:
                db.x("UPDATE llm_jobs SET status=?, error=?, not_before=?, updated_at=? WHERE id=?",
                     ("failed" if fatal else "queued", str(e)[:400], nb, config.iso(config.now_utc()), job["id"]))
            return {"id": job["id"], "kind": job["kind"], "ok": False, "error": str(e)}
        except Exception as e:  # beklenmeyen hata: işi düşür, uygulamayı durdurma
            db.x("UPDATE llm_jobs SET status='failed', error=?, updated_at=? WHERE id=?",
                 (f"{type(e).__name__}: {e}"[:400], config.iso(config.now_utc()), job["id"]))
            return {"id": job["id"], "kind": job["kind"], "ok": False, "error": str(e)}
    finally:
        _worker_lock.release()


def reset_stuck() -> None:
    db.x("UPDATE llm_jobs SET status='queued' WHERE status='running'")


def retry_failed() -> int:
    n = db.val("SELECT COUNT(*) FROM llm_jobs WHERE status='failed'", default=0)
    db.x("UPDATE llm_jobs SET status='queued', attempts=0, not_before=NULL WHERE status='failed'")
    return n


def worker_loop(stop: threading.Event) -> None:
    reset_stuck()
    while not stop.is_set():
        try:
            r = process_one()
        except Exception:
            r = None
        stop.wait(2 if r else 30)
