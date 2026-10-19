"""Arayüz testi 2: tekrar alıştırmaları (cloze, eş anlamlı, yazma, bağlam), müdahale kartı, koyu tema ve mobil.

Kullanım: .venv\\Scripts\\python tools\\ui_smoke2.py <çıktı_klasörü>
"""
from __future__ import annotations

import os
import random
import shutil
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def prepare():
    from app import config, db, cards as C, seed_loader
    seed_loader.init_db()
    db.set_setting("setup_done", True)
    db.set_setting("placement_done", True)
    now = config.now_utc()
    ids = [r["id"] for r in db.q("SELECT id FROM words WHERE status='active' ORDER BY order_index LIMIT 60")]
    rng = random.Random(4)
    for k, wid in enumerate(ids):
        C.mark_introduced(wid, now - timedelta(days=12))
        C.apply_review(wid, 3, now - timedelta(days=12))
        C.apply_review(wid, 3 if k % 5 else 1, now - timedelta(days=5))
        C.set_stage(wid, 3 + (k % 4), now - timedelta(days=5))
    db.x("UPDATE cards SET due_day=?, due=? WHERE fsrs IS NOT NULL", (config.day_str(), config.iso(now - timedelta(hours=1))))
    db.x("UPDATE cards SET wrong_total=3 WHERE word_id=?", (ids[0],))
    # biraz geçmiş etkinlik (analiz grafikleri için)
    for d in range(1, 9):
        day = (config.study_day() - timedelta(days=d)).isoformat()
        db.x("INSERT INTO activity(session_id, ts, day, active_ms, device) VALUES(?,?,?,?,?)",
             ("x", config.iso(now - timedelta(days=d)), day, rng.randint(15, 80) * 60000, "desktop"))
    return ids


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())
    out.mkdir(parents=True, exist_ok=True)
    data = Path(tempfile.mkdtemp(prefix="yds_ui2_"))
    os.environ["YDS_DATA_DIR"] = str(data)
    os.environ["YDS_PORT"] = "8796"
    from app import config, runtime
    prepare()
    assert runtime.start_local()
    base = f"http://127.0.0.1:{config.LOCAL_PORT}"
    from playwright.sync_api import sync_playwright
    errors: list[str] = []
    seen: set[str] = set()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        ctx = browser.new_context(viewport={"width": 1280, "height": 860})
        page = ctx.new_page()
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
        page.goto(base + "/#/calis?mod=review")
        page.wait_for_timeout(2500)
        first_wrong_done = False
        for i in range(90):
            if page.query_selector(".feedback .btn.primary"):
                if "feedback" not in seen:
                    seen.add("feedback")
                    page.screenshot(path=str(out / "geri_bildirim_yanlis.png"))
                page.keyboard.press("Enter")
                page.wait_for_timeout(450)
                continue
            label = page.eval_on_selector(".ex-type", "e => e.textContent") if page.query_selector(".ex-type") else ""
            key = label.split(" — ")[-1]
            if key and key not in seen:
                seen.add(key)
                page.screenshot(path=str(out / f"ex_{len(seen):02d}_{key.replace(' ', '_').replace('→', '-')}.png"))
            if page.query_selector(".notice.warn") and "İnatçı" in (page.inner_text(".ex-card") if page.query_selector(".ex-card") else ""):
                page.keyboard.press("Enter")
            elif page.query_selector(".answer-input"):
                page.fill(".answer-input", "wrongword" if not first_wrong_done else "x")
                first_wrong_done = True
                page.keyboard.press("Enter")
            elif page.query_selector(".tiles"):
                for t in page.query_selector_all(".tile:not(.used)")[:len(page.query_selector_all(".slot"))]:
                    t.click()
            elif page.query_selector(".opt"):
                page.keyboard.press("1")
            elif page.query_selector(".intro-word"):
                page.keyboard.press("Enter")
            elif page.query_selector(".big-check"):
                break
            page.wait_for_timeout(650)
        page.screenshot(path=str(out / "oturum_son.png"))
        # koyu tema + analiz
        ctx2 = browser.new_context(viewport={"width": 1280, "height": 900}, color_scheme="dark")
        p2 = ctx2.new_page()
        p2.on("pageerror", lambda e: errors.append(f"pageerror(dark): {e}"))
        for route, name in (("#/bugun", "koyu_bugun"), ("#/analiz", "koyu_analiz")):
            p2.goto(base + "/" + route)
            p2.wait_for_timeout(3000)
            p2.screenshot(path=str(out / f"{name}.png"), full_page=True)
        # mobil
        ctx3 = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True)
        p3 = ctx3.new_page()
        p3.on("pageerror", lambda e: errors.append(f"pageerror(mobile): {e}"))
        p3.goto(base + "/#/bugun")
        p3.wait_for_timeout(3000)
        p3.screenshot(path=str(out / "mobil_bugun.png"))
        p3.goto(base + "/#/calis?mod=quick")
        p3.wait_for_timeout(2500)
        p3.screenshot(path=str(out / "mobil_hizli_tekrar.png"))
        browser.close()
    runtime.shutdown()
    shutil.rmtree(data, ignore_errors=True)
    print("görülen türler:", sorted(seen))
    if errors:
        print("HATALAR:")
        for e in errors:
            print(" ", e)
        return 1
    print("JS hatası yok.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
