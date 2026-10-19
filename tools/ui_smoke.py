"""Arayüz duman testi: geçici veriyle sunucuyu başlatır, sistem Edge'i ile (Playwright) tüm ekranları gezer,
alıştırmaları klavyeyle cevaplar, ekran görüntüleri alır ve JS hatalarını raporlar.

Kullanım: .venv\\Scripts\\python tools\\ui_smoke.py <çıktı_klasörü> [--dark] [--mobile]
"""
from __future__ import annotations

import os
import random
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())
    out.mkdir(parents=True, exist_ok=True)
    dark = "--dark" in sys.argv
    mobile = "--mobile" in sys.argv
    data = Path(tempfile.mkdtemp(prefix="yds_ui_"))
    os.environ["YDS_DATA_DIR"] = str(data)
    os.environ["YDS_PORT"] = "8795"
    from app import config, runtime, seed_loader
    seed_loader.init_db()
    assert runtime.start_local(), "sunucu başlamadı"
    base = f"http://127.0.0.1:{config.LOCAL_PORT}"
    from playwright.sync_api import sync_playwright
    errors: list[str] = []
    shots = 0

    def shot(page, name):
        nonlocal shots
        shots += 1
        page.screenshot(path=str(out / f"{shots:02d}_{name}.png"), full_page=False)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        ctx = browser.new_context(viewport={"width": 390, "height": 844} if mobile else {"width": 1366, "height": 860},
                                  color_scheme="dark" if dark else "light", device_scale_factor=1)
        page = ctx.new_page()
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
        page.goto(base + "/")
        page.wait_for_timeout(1500)
        shot(page, "kurulum")
        # kurulum anketi
        page.click("text=Devam: seviye tespiti")
        page.wait_for_timeout(800)
        shot(page, "seviye_giris")
        page.click("text=Teste başla")
        page.wait_for_timeout(1200)
        shot(page, "seviye_soru")
        rng = random.Random(3)
        for i in range(36):
            page.keyboard.press(str(rng.randint(1, 5)) if rng.random() < 0.85 else "0")
            page.wait_for_timeout(650)
        shot(page, "seviye_ilerleme")
        page.once("dialog", lambda d: d.accept())
        page.click(".study-top .close")
        page.wait_for_timeout(2500)
        shot(page, "seviye_sonuc")
        page.click("text=Çalışmaya başla")
        page.wait_for_timeout(2500)
        shot(page, "bugun")
        page.goto(base + "/#/calis?mod=daily")
        page.wait_for_timeout(1500)
        shot(page, "calis_ilk")
        lbl = page.eval_on_selector(".study-label", "e => e.textContent") if page.query_selector(".study-label") else ""
        if not lbl.startswith("Part") and not lbl.startswith("Tekrar"):
            errors.append(f"oturum etiketi beklenmiyordu: {lbl!r}")
        seen = set()
        for i in range(110):
            card = page.query_selector(".ex-card")
            if not card:
                page.wait_for_timeout(500)
                continue
            typ = page.eval_on_selector(".ex-type", "e => e.textContent") if page.query_selector(".ex-type") else ""
            if (page.query_selector(".answer-input:disabled") or page.query_selector(".opt.correct")
                    or page.query_selector(".slots.good")) and not page.query_selector(".feedback .btn.primary"):
                page.wait_for_timeout(600)       # cevaplandı, otomatik geçiş bekleniyor
                continue
            fb = page.query_selector(".feedback .btn.primary")
            if fb:
                if "fb" not in seen:
                    seen.add("fb")
                    shot(page, "geri_bildirim")
                page.keyboard.press("Enter")
                page.wait_for_timeout(500)
                continue
            if page.query_selector(".intro-word"):
                if "intro" not in seen:
                    seen.add("intro")
                    shot(page, "tanitim_karti")
                page.keyboard.press("Enter")
            elif page.query_selector(".lw-top") and page.is_visible("text=Ezberledim"):
                # bak · kapat · yaz: kelimeye bak → Enter (gizlenir) → ezberden yaz
                if "look_write" not in seen:
                    seen.add("look_write")
                    shot(page, "bak_kapat_yaz")
                word = page.eval_on_selector(".lw-word", "e => e.textContent") if page.query_selector(".lw-word") else "test"
                page.keyboard.press("Enter")
                page.wait_for_timeout(300)
                page.fill(".answer-input", word)
                page.keyboard.press("Enter")
            elif page.query_selector(".match-grid"):
                # eşleştir: her kelime için anlamları sırayla dene (yanlış çift sallanır, doğru çift yeşil kalır)
                if "match" not in seen:
                    seen.add("match")
                    shot(page, "eslestir")
                n_l = len(page.query_selector_all(".match-col:first-child .mbtn"))
                for li in range(n_l):
                    for rj in range(n_l):
                        lb = page.query_selector_all(".match-col:first-child .mbtn")[li]
                        if "matched" in (lb.get_attribute("class") or ""):
                            break
                        rb = page.query_selector_all(".match-col:last-child .mbtn")[rj]
                        if "matched" in (rb.get_attribute("class") or ""):
                            continue
                        lb.click()
                        rb.click()
                        page.wait_for_timeout(500)
                page.wait_for_timeout(900)
            elif page.query_selector(".answer-input"):
                if "typing" not in seen:
                    seen.add("typing")
                    shot(page, "yazma")
                page.fill(".answer-input", "test")
                page.keyboard.press("Enter")
            elif page.query_selector(".tiles"):
                if "tiles" not in seen:
                    seen.add("tiles")
                    shot(page, "harfler")
                tiles = page.query_selector_all(".tile:not(.used)")
                n = len(page.query_selector_all(".slot"))
                for t in tiles[:n]:
                    t.click()
                    page.wait_for_timeout(40)
            elif page.query_selector(".opt"):
                key = f"mcq-{typ}"
                if key not in seen:
                    seen.add(key)
                    shot(page, "secmeli_" + str(len(seen)))
                page.keyboard.press(str(rng.randint(1, 3)))
            elif page.query_selector(".ex-card .btn.primary"):
                page.keyboard.press("Enter")   # müdahale kartı, mola ekranı vb.
            elif page.query_selector(".big-check"):
                break
            page.wait_for_timeout(700)
        shot(page, "calis_son")
        h_now = page.evaluate("location.hash")
        if h_now.startswith("#/calis") and not page.query_selector(".study-top"):
            errors.append("çalışma rotasında çalışma ekranı yok (geç gelen başka ekran üstüne yazdı)")
        page.once("dialog", lambda d: d.accept())
        if page.query_selector(".study-top .close"):
            page.click(".study-top .close")
            page.wait_for_timeout(2000)
            shot(page, "ozet")
        # partlar merkezi: part seç → karışık hızlı test
        page.goto(base + "/#/calis")
        page.wait_for_timeout(2000)
        shot(page, "partlar")
        if not page.query_selector(".part-card"):
            errors.append("partlar ekranında part kartı yok")
        cb = page.query_selector(".part-card input[type=checkbox]:not([disabled])")
        if cb:
            cb.click()
            page.wait_for_timeout(300)
            shot(page, "partlar_secim")
            page.click("text=Karışık hızlı test")
            page.wait_for_timeout(2000)
            lbl = page.eval_on_selector(".study-label", "e => e.textContent") if page.query_selector(".study-label") else ""
            if not lbl.startswith("Hızlı test"):
                errors.append(f"part hızlı test etiketi beklenmiyordu: {lbl!r}")
            shot(page, "part_hizli_test")
            for _ in range(4):
                if page.query_selector(".opt"):
                    page.keyboard.press("1")
                page.wait_for_timeout(900)
            page.once("dialog", lambda d: d.accept())
            if page.query_selector(".study-top .close"):
                page.click(".study-top .close")
                page.wait_for_timeout(1500)
                shot(page, "part_hizli_ozet")
        else:
            errors.append("seçilebilir (test edilebilir) part yok")
        for route, name in (("#/analiz", "analiz"), ("#/kelimeler", "kelimeler"), ("#/ayarlar", "ayarlar"),
                            ("#/kelimeler?sekme=oneriler", "oneriler")):
            page.goto(base + "/" + route)
            page.wait_for_timeout(2500)
            shot(page, name)
        page.goto(base + "/#/kelimeler")
        page.wait_for_timeout(1500)
        rows = page.query_selector_all(".wl-row")
        if rows:
            rows[0].click()
            page.wait_for_timeout(1500)
            shot(page, "kelime_ayrinti")
        page.goto(base + "/#/bugun")
        page.wait_for_timeout(2500)
        shot(page, "bugun_son")
        page.screenshot(path=str(out / "bugun_tam.png"), full_page=True)
        browser.close()
    runtime.shutdown()
    shutil.rmtree(data, ignore_errors=True)
    print(f"{shots} ekran görüntüsü: {out}")
    if errors:
        print("HATALAR:")
        for e in errors:
            print(" ", e)
        return 1
    print("JS hatası yok.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
