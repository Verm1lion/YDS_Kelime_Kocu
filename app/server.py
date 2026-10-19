"""FastAPI uygulaması: API + tarayıcı arayüzü."""
from __future__ import annotations

import io
import json
import traceback
from datetime import date, timedelta
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import auth, config, db
from . import words as W


def create_app() -> FastAPI:
    app = FastAPI(title=config.APP_NAME, version=config.VERSION, docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def lan_guard(request: Request, call_next):
        host = request.client.host if request.client else None
        if not auth.is_local(host):
            if not db.get_setting("lan_enabled", False):
                return JSONResponse({"error": "Telefondan erişim kapalı"}, status_code=403)
            path = request.url.path
            open_paths = ("/", "/index.html", "/api/health", "/api/auth/pin", "/manifest.webmanifest")
            if not (path in open_paths or path.startswith("/static/")):
                if not auth.valid_token(request.cookies.get(auth.COOKIE)):
                    return JSONResponse({"error": "PIN gerekli", "need_pin": True}, status_code=401)
        try:
            return await call_next(request)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=500)

    web = config.web_dir()
    app.mount("/static", StaticFiles(directory=str(web)), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index():
        html = (web / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    @app.get("/manifest.webmanifest")
    def manifest():
        return JSONResponse({"name": config.APP_NAME, "short_name": "YDS Koç", "start_url": "/", "display": "standalone",
                             "background_color": "#fffaf0", "theme_color": "#ffb400",
                             "icons": [{"src": "/static/icon.png", "sizes": "256x256", "type": "image/png"}]})

    @app.get("/api/health")
    def health():
        return {"ok": True, "app": config.APP_NAME, "version": config.VERSION}

    # ------------------------------------------------------------ özet / bugün
    @app.get("/api/bootstrap")
    def bootstrap(request: Request):
        s = db.all_settings()
        return {"settings": {k: s.get(k) for k in ("user_name", "exam_date", "exam_name", "theme", "setup_done",
                                                   "placement_done", "target_recall", "target_score", "final_days")},
                "local": auth.is_local(request.client.host if request.client else None),
                "version": config.VERSION}

    @app.get("/api/today")
    def today():
        from . import coach, planner, projection
        plan = planner.today_plan()
        prog = planner.progress_today()
        total = db.val("SELECT COUNT(*) FROM words WHERE status='active'", default=0)
        learned = db.val("""SELECT COUNT(*) FROM cards c JOIN words w ON w.id=c.word_id
                            WHERE w.status='active' AND c.stage>=6""", default=0)
        started = db.val("""SELECT COUNT(*) FROM cards c JOIN words w ON w.id=c.word_id
                            WHERE w.status='active' AND c.introduced_at IS NOT NULL""", default=0)
        proj = projection.compute()
        notes = coach.recent(8)
        sugg = db.val("SELECT COUNT(*) FROM words WHERE pool='suggestion' AND status='pending'", default=0)
        due_now = plan.get("reviews_due", 0)
        return {
            "plan": plan, "progress": prog, "streak": coach.streak(),
            "numbers": {"days_to_exam": plan.get("days_to_exam"), "learned": learned, "started": started, "total": total,
                        "plan_pct": round(prog["fraction"] * 100), "mastery": proj.get("pace", {}).get("mean"),
                        "target": proj.get("target"), "mastery_plan": proj.get("plan", {}).get("mean")},
            "projection_message": proj.get("message"),
            "notifications": notes, "suggestions_pending": sugg, "due_now": due_now,
            "placement_done": db.get_setting("placement_done", False),
            "setup_done": db.get_setting("setup_done", False),
            "hard_count": db.val("SELECT COUNT(*) FROM cards WHERE flag_hard=1 OR wrong_total>=4", default=0),
            "parts": parts_today(plan),
        }

    def parts_today(plan):
        from . import parts as P
        try:
            return P.today_info(plan)
        except Exception:
            return None

    @app.post("/api/plan/recompute")
    def plan_recompute():
        from . import planner, projection
        projection.invalidate()
        return planner.today_plan(recompute=True)

    @app.post("/api/plan/prioritize")
    def plan_prioritize(body: dict = Body(...)):
        """Gerçekçilik seçeneği: başlanmamış en düşük öncelikli N kelimeyi yedeğe al (silinmez)."""
        from . import planner, projection
        n = max(0, int(body.get("n", 0)))
        cand = db.q("""SELECT w.id, w.order_index, json_extract(w.features, '$.ezb_section') sec,
                              json_extract(w.features, '$.garanti') gar
                       FROM words w JOIN cards c ON c.word_id=w.id
                       WHERE w.status='active' AND w.pool='main' AND c.introduced_at IS NULL AND c.state=0""")
        # önce az sorulan edat kalıpları ve öbek fiiller, sonra kitabın son günleri; bağlaçlar ve garanti kelimeler en son
        trim_rank = {"edat kalıbı": 0, "öbek fiil": 1, None: 2, "bağlaç": 3}
        cand.sort(key=lambda r: (4 if r["gar"] else trim_rank.get(r["sec"], 2), -(r["order_index"] or 0)))
        rows = cand[:n]
        now = config.iso(config.now_utc())
        for r in rows:
            db.x("UPDATE words SET status='inactive', pool='reserve', tags=COALESCE(tags||', ','')||'önceliklendirme ile yedeğe alındı', "
                 "updated_at=? WHERE id=?", (now, r["id"]))
        W.invalidate_index()
        projection.invalidate()
        planner.today_plan(recompute=True)
        from . import strategy
        strategy.log_change("liste_kapsamı", None, len(rows), f"Gerçekçilik kontrolü: en düşük öncelikli {len(rows)} kelime yedeğe alındı "
                            "(Ayarlar → 'Yedek kartları plana dahil et' ile geri açılır).", {"n": len(rows)}, notify=False)
        return {"moved": len(rows)}

    @app.get("/api/projection")
    def get_projection(force: bool = False):
        from . import projection
        p = projection.compute(force=force)
        return {k: v for k, v in p.items() if k not in ("card_r", "ids", "runs")}

    @app.get("/api/score")
    def get_score():
        from . import score_model
        return score_model.compute()

    @app.get("/api/mocks")
    def mocks():
        return db.q("SELECT * FROM mock_exams ORDER BY day DESC")

    @app.post("/api/mocks")
    def add_mock(body: dict = Body(...)):
        from . import score_model, projection
        try:
            mid = score_model.add_mock(body.get("day") or config.day_str(), body.get("total_correct"),
                                       body.get("sections"), body.get("note"))
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"id": mid, "score": score_model.compute()}

    @app.delete("/api/mocks/{mid}")
    def del_mock(mid: int):
        db.x("DELETE FROM mock_exams WHERE id=?", (mid,))
        return {"ok": True}

    # ------------------------------------------------------------ oturum
    @app.post("/api/session/start")
    def session_start(body: dict = Body(default={})):
        from . import session
        ids = body.get("part_ids")
        return session.start(body.get("mode", "daily"), body.get("device", "desktop"), body.get("limit"),
                             part_id=body.get("part_id"), part_ids=[int(i) for i in ids] if ids else None)

    @app.get("/api/parts")
    def parts_list():
        from . import parts as P, planner, session
        plan = planner.today_plan()
        return {"parts": P.list_parts(), "today": P.today_info(plan),
                "reviews_due": len(session.due_reviews(plan.get("review_cap"))) if plan.get("phase") != "final" else 0}

    @app.get("/api/session/{sid}/next")
    def session_next(sid: str):
        from . import session
        return session.next_item(sid)

    @app.post("/api/session/{sid}/answer")
    def session_answer(sid: str, body: dict = Body(...)):
        from . import session
        res = session.answer(sid, body.get("token", ""), body)
        if "error" in res:
            raise HTTPException(404, res["error"])
        return res

    @app.post("/api/session/{sid}/override")
    def session_override(sid: str, body: dict = Body(...)):
        from . import session
        return session.override(sid, int(body.get("event_id", 0)))

    @app.post("/api/session/{sid}/heartbeat")
    def session_heartbeat(sid: str, body: dict = Body(...)):
        from . import session
        session.heartbeat(sid, int(body.get("active_ms", 0)), body.get("device", "desktop"))
        return {"ok": True}

    @app.post("/api/session/{sid}/finish")
    def session_finish(sid: str):
        from . import session
        return session.finish(sid)

    # ------------------------------------------------------------ seviye testi
    @app.post("/api/placement/start")
    def placement_start():
        from . import placement
        return placement.start()

    @app.get("/api/placement/{pid}/next")
    def placement_next(pid: str):
        from . import placement
        return placement.next_item(pid)

    @app.post("/api/placement/{pid}/answer")
    def placement_answer(pid: str, body: dict = Body(...)):
        from . import placement
        return placement.answer(pid, body.get("token", ""), body)

    @app.post("/api/placement/{pid}/finish")
    def placement_finish(pid: str):
        from . import placement
        return placement.finish(pid)

    @app.get("/api/placement/result")
    def placement_result():
        from . import placement
        return placement.last_result() or {}

    # ------------------------------------------------------------ ayarlar / kurulum
    @app.get("/api/settings")
    def get_settings():
        s = db.all_settings()
        s.pop("lan_pin_hash", None)
        s["data_dir"] = str(config.data_dir())
        s["env_path"] = str(config.data_dir() / ".env")
        return s

    @app.post("/api/settings")
    def post_settings(body: dict = Body(...)):
        allowed = set(db.DEFAULT_SETTINGS) - {"lan_pin_hash", "setup_done"}
        changed = {}
        for k, v in body.items():
            if k in allowed:
                db.set_setting(k, v)
                changed[k] = v
        if "include_reserve" in changed:
            W.set_reserve_enabled(bool(changed["include_reserve"]))
        if "autostart" in changed:
            try:
                from . import winutil
                winutil.set_autostart(bool(changed["autostart"]))
            except Exception:
                pass
        if changed.keys() & {"exam_date", "final_days", "weekday_minutes", "weekend_minutes", "weekly_review_day",
                             "weekly_review_new_ratio", "new_per_day_override", "desired_retention", "include_reserve",
                             "target_recall"}:
            from . import planner, projection
            projection.invalidate()
            if "exam_date" in changed or "final_days" in changed:
                from . import cards
                cards.reschedule_all()
            planner.today_plan(recompute=True)
        return {"ok": True, "changed": list(changed)}

    @app.post("/api/setup")
    def setup(body: dict = Body(...)):
        keys = ["user_name", "exam_date", "weekday_minutes", "weekend_minutes", "study_hours", "morning_time",
                "weekly_review_day", "quiet_start", "quiet_end", "target_recall", "target_score", "final_days", "self_level"]
        for k in keys:
            if k in body and body[k] is not None:
                db.set_setting(k, body[k])
        db.set_setting("setup_done", True)
        from . import planner, projection
        projection.invalidate()
        return {"ok": True, "plan": planner.today_plan(recompute=True)}

    # ------------------------------------------------------------ kelimeler
    @app.get("/api/words")
    def list_words(q: str = "", status: str = "all", sort: str = "order", offset: int = 0, limit: int = 100):
        where = ["w.status IN ('active','inactive')"] if status != "suggestions" else ["w.pool='suggestion'"]
        params: list[Any] = []
        if q:
            where.append("(w.lemma LIKE ? OR w.meaning_src LIKE ? OR w.meaning_user LIKE ? OR w.meaning_gen LIKE ?)")
            params += [f"%{q.lower()}%", f"%{q}%", f"%{q}%", f"%{q}%"]
        st_map = {"new": "c.introduced_at IS NULL AND w.status='active'", "learning": "c.introduced_at IS NOT NULL AND c.stage<6",
                  "learned": "c.stage>=6", "hard": "(c.flag_hard=1 OR c.wrong_total>=4)", "due": "c.due_day<=?",
                  "reserve": "w.pool='reserve'", "user": "w.pool='user'", "flagged":
                  "w.id IN (SELECT word_id FROM flags WHERE resolved=0)", "active": "w.status='active'"}
        if status in st_map:
            where.append(st_map[status])
            if status == "due":
                params.append(config.day_str())
        order = {"order": "w.order_index", "alpha": "w.lemma", "hard": "(c.wrong_total + c.lapses*2) DESC",
                 "due": "c.due_day", "recent": "c.last_review DESC", "stage": "c.stage DESC"}.get(sort, "w.order_index")
        sql = f"""SELECT w.id, w.lemma, w.display, w.kind, w.pos, w.meaning_src, w.meaning_user, w.meaning_gen, w.pool,
                         w.status, w.level, w.tags, c.stage, c.state, c.stability, c.due_day, c.reps, c.lapses,
                         c.wrong_total, c.known_status, c.flag_hard, c.last_review
                  FROM words w LEFT JOIN cards c ON c.word_id=w.id WHERE {' AND '.join(where)}
                  ORDER BY {order} LIMIT ? OFFSET ?"""
        rows = db.q(sql, params + [limit, offset])
        total = db.val(f"SELECT COUNT(*) FROM words w LEFT JOIN cards c ON c.word_id=w.id WHERE {' AND '.join(where)}",
                       params, default=0)
        for r in rows:
            r["meaning"] = r["meaning_user"] or r["meaning_src"] or r["meaning_gen"]
        counts = {k: db.val(f"SELECT COUNT(*) FROM words w LEFT JOIN cards c ON c.word_id=w.id WHERE w.status='active' AND {v}",
                            [config.day_str()] if k == "due" else [], default=0)
                  for k, v in st_map.items() if k in ("new", "learning", "learned", "hard", "due")}
        return {"items": rows, "total": total, "counts": counts}

    @app.get("/api/words/{wid}")
    def word_detail(wid: int):
        b = W.bundle(wid)
        if not b:
            raise HTTPException(404, "Kelime yok")
        b["history"] = db.q("""SELECT ts, exercise, correct, result, rating, error_type, total_ms, first_key_ms
                               FROM events WHERE word_id=? AND correct IS NOT NULL ORDER BY id DESC LIMIT 30""", (wid,))
        from . import cards
        b["retrievability"] = cards.retrievability_now(cards.get(wid))
        return b

    @app.post("/api/words")
    def add_word(body: dict = Body(...)):
        try:
            res = W.add_user_word(body.get("text", ""), body.get("meaning"), body.get("pos"), body.get("note"))
        except ValueError as e:
            raise HTTPException(400, str(e))
        from . import projection
        projection.invalidate()
        return res

    @app.get("/api/lookup")
    def lookup(w: str):
        r = W.offline_lookup(w)
        ex = db.q1("SELECT id, status, pool FROM words WHERE lemma=?", (w.strip().lower(),))
        return {"offline": r, "existing": ex}

    @app.put("/api/words/{wid}/meaning")
    def set_meaning(wid: int, body: dict = Body(...)):
        W.set_user_meaning(wid, body.get("meaning"))
        return {"ok": True}

    @app.post("/api/words/{wid}/mnemonic")
    def add_mem(wid: int, body: dict = Body(...)):
        if not (body.get("text") or "").strip():
            raise HTTPException(400, "Boş metin")
        return {"id": W.add_user_mnemonic(wid, body["text"])}

    @app.post("/api/words/{wid}/flag")
    def flag(wid: int, body: dict = Body(...)):
        return {"id": W.flag_content(wid, body.get("target", "word"), body.get("target_id"), body.get("note"))}

    @app.post("/api/words/{wid}/unflag")
    def unflag(wid: int, body: dict = Body(...)):
        W.unflag_content(wid, body.get("target"), int(body.get("target_id")))
        return {"ok": True}

    @app.post("/api/words/{wid}/verify_content")
    def verify_content(wid: int, body: dict = Body(...)):
        W.verify_content(wid, body.get("target"), int(body.get("target_id")))
        return {"ok": True}

    @app.put("/api/words/{wid}/example/{eid}")
    def edit_example(wid: int, eid: int, body: dict = Body(...)):
        try:
            return {"id": W.edit_example(wid, eid, body.get("en", ""), body.get("tr", ""))}
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.put("/api/words/{wid}/info/{field}")
    def edit_info(wid: int, field: str, body: dict = Body(...)):
        if field not in ("synonyms", "antonyms", "family", "confusables", "etymology", "senses"):
            raise HTTPException(400, "alan")
        return {"id": W.set_info(wid, field, body.get("value"))}

    @app.post("/api/words/{wid}/mark")
    def mark(wid: int, body: dict = Body(...)):
        act = body.get("action")
        now = config.iso(config.now_utc())
        if act == "hard":
            db.x("UPDATE cards SET flag_hard=1 WHERE word_id=?", (wid,))
        elif act == "unhard":
            db.x("UPDATE cards SET flag_hard=0 WHERE word_id=?", (wid,))
        elif act == "known":
            # beyan doğrulanmadan kabul edilmez: doğrulama turuna alınır
            db.x("UPDATE cards SET known_status='probable' WHERE word_id=? AND state=0", (wid,))
        elif act == "suspend":
            db.x("UPDATE words SET status='suspended', updated_at=? WHERE id=?", (now, wid))
        elif act == "unsuspend":
            db.x("UPDATE words SET status='active', updated_at=? WHERE id=?", (now, wid))
            W.ensure_card(wid)
        else:
            raise HTTPException(400, "işlem")
        W.invalidate_index()
        return {"ok": True}

    @app.get("/api/suggestions")
    def suggestions():
        return {"pending": W.suggestions("pending"), "accepted": len(db.q(
            "SELECT id FROM words WHERE pool='main' AND kind IN ('linker') AND status='active'"))}

    @app.post("/api/suggestions/decide")
    def suggestions_decide(body: dict = Body(...)):
        n = W.decide_suggestions([int(i) for i in body.get("ids", [])], bool(body.get("accept")))
        from . import projection
        projection.invalidate()
        return {"ok": True, "n": n}

    @app.post("/api/import")
    async def import_list(request: Request, filename: str = "liste.txt"):
        from . import list_import
        data = await request.body()
        try:
            return list_import.import_bytes(filename, data)
        except ValueError as e:
            raise HTTPException(400, str(e))

    # ------------------------------------------------------------ analiz / strateji / raporlar
    @app.get("/api/analysis")
    def analysis_all():
        from . import analysis
        return analysis.overview()

    @app.post("/api/strategy/revert/{log_id}")
    def strategy_revert(log_id: int):
        from . import strategy
        return strategy.revert(log_id)

    @app.post("/api/strategy/toggle")
    def strategy_toggle(body: dict = Body(...)):
        db.set_setting("experiments_enabled", bool(body.get("enabled")))
        return {"ok": True}

    @app.get("/api/reports")
    def reports():
        from . import weekly
        return weekly.reports()

    @app.post("/api/reports/make")
    def make_report():
        from . import weekly
        return {"id": weekly.make_report()}

    @app.get("/api/notifications")
    def notifications():
        from . import coach
        return coach.recent(50)

    @app.post("/api/notifications/read")
    def notifications_read():
        db.x("UPDATE notifications SET read=1 WHERE read=0")
        return {"ok": True}

    @app.post("/api/weekly_jobs")
    def run_weekly_jobs():
        from . import coach
        return coach.weekly_jobs()

    # ------------------------------------------------------------ LLM
    @app.get("/api/llm/status")
    def llm_status():
        from . import llm
        st = llm.status()
        st["recent"] = db.q("SELECT id, kind, status, attempts, error, result, updated_at FROM llm_jobs ORDER BY id DESC LIMIT 15")
        return st

    @app.post("/api/llm/key")
    def llm_key(body: dict = Body(...)):
        key = (body.get("key") or "").strip()
        p = config.write_env_value("GEMINI_API_KEY", key)
        if body.get("model"):
            config.write_env_value("GEMINI_MODEL", body["model"].strip())
        from . import llm, enrichment
        llm._available = None
        res = llm.test_connection() if key else {"ok": False}
        queued = enrichment.queue_missing() if res.get("ok") else 0
        return {"ok": True, "path": str(p), "test": res, "queued_words": queued}

    @app.post("/api/llm/test")
    def llm_test():
        from . import llm
        return llm.test_connection()

    @app.post("/api/llm/retry")
    def llm_retry():
        from . import enrichment
        return {"n": enrichment.retry_failed()}

    @app.post("/api/llm/enrich_missing")
    def llm_enrich_missing():
        from . import enrichment
        return {"queued_words": enrichment.queue_missing()}

    # ------------------------------------------------------------ yedek / dışa aktarma
    @app.get("/api/backups")
    def backups():
        from . import backup
        return {"items": backup.list_backups(), "dir": str(config.backup_dir())}

    @app.post("/api/backup")
    def backup_now():
        from . import backup
        return {"path": str(backup.backup_now())}

    @app.get("/api/export/{name}")
    def export(name: str):
        from . import backup
        if name == "hepsi.zip":
            return Response(backup.export_zip(), media_type="application/zip",
                            headers={"Content-Disposition": "attachment; filename=yds_kocu_veri.zip"})
        base = name[:-4] if name.endswith(".csv") else name
        if base not in backup.EXPORTS:
            raise HTTPException(404, "yok")
        return Response(backup.export_csv(base), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f"attachment; filename={base}.csv"})

    # ------------------------------------------------------------ ses
    @app.get("/api/tts")
    def tts(text: str, slow: int = 0):
        from . import tts as T
        p = T.get_audio(text, bool(slow))
        if not p:
            raise HTTPException(404, "ses üretilemedi")
        return FileResponse(str(p), media_type="audio/wav", headers={"Cache-Control": "max-age=31536000"})

    # ------------------------------------------------------------ telefon erişimi
    @app.get("/api/lan")
    def lan_info():
        addrs = auth.lan_addresses()
        url = f"http://{addrs[0]}:{config.LAN_PORT}/" if addrs else None
        qr = None
        if url:
            try:
                import qrcode
                import qrcode.image.svg
                img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=8)
                buf = io.BytesIO()
                img.save(buf)
                qr = buf.getvalue().decode("utf-8")
            except Exception:
                qr = None
        return {"enabled": db.get_setting("lan_enabled", False), "addresses": addrs, "port": config.LAN_PORT,
                "url": url, "has_pin": auth.has_pin(), "qr_svg": qr}

    @app.post("/api/lan")
    def lan_set(body: dict = Body(...)):
        if body.get("pin"):
            try:
                auth.set_pin(str(body["pin"]))
            except ValueError as e:
                raise HTTPException(400, str(e))
        if "enabled" in body:
            en = bool(body["enabled"])
            if en and not auth.has_pin():
                raise HTTPException(400, "Önce PIN belirle")
            db.set_setting("lan_enabled", en)
            from . import runtime
            runtime.set_lan(en)
        return lan_info()

    @app.post("/api/auth/pin")
    def auth_pin(request: Request, body: dict = Body(...)):
        host = request.client.host if request.client else "?"
        try:
            tok = auth.check_pin(str(body.get("pin", "")), host)
        except PermissionError as e:
            raise HTTPException(429, str(e))
        if not tok:
            raise HTTPException(401, "PIN hatalı")
        resp = JSONResponse({"ok": True})
        resp.set_cookie(auth.COOKIE, tok, max_age=auth.TOKEN_TTL, httponly=True, samesite="lax")
        return resp

    return app
