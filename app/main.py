"""Giriş noktası (exe): sunucu + arka plan koçu + sistem tepsisi."""
from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import traceback


def _setup_logging() -> None:
    from . import config
    logdir = config.data_dir() / "kayitlar"
    logdir.mkdir(parents=True, exist_ok=True)
    logfile = logdir / "uygulama.log"
    try:
        if logfile.exists() and logfile.stat().st_size > 2_000_000:
            logfile.replace(logdir / "uygulama.old.log")
    except OSError:
        pass
    f = open(logfile, "a", encoding="utf-8", buffering=1)
    if sys.stdout is None or getattr(sys, "frozen", False):
        sys.stdout = f
    if sys.stderr is None or getattr(sys, "frozen", False):
        sys.stderr = f
    logging.basicConfig(stream=f, level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="YDSKelimeKocu")
    ap.add_argument("--background", action="store_true", help="arayüzü açmadan tepside başla")
    ap.add_argument("--no-tray", action="store_true")
    args = ap.parse_args(argv)
    _setup_logging()
    from . import config, db, runtime, seed_loader, winutil
    port, running = winutil.choose_port()
    config.LOCAL_PORT, config.LAN_PORT = port, port + 1
    if running:
        if not args.background:
            winutil.open_ui()
        return 0
    try:
        seed_loader.init_db()
    except Exception:
        traceback.print_exc()
        raise
    if not runtime.start_local():
        print("Yerel sunucu başlatılamadı (port dolu olabilir).")
        return 1
    if db.get_setting("lan_enabled", False):
        runtime.set_lan(True)
    runtime.start_background()
    if not os.environ.get("YDS_NO_SHORTCUTS"):
        try:
            # kısayollar her açılışta geçerli exe yoluna yenilenir (taşıma/güncelleme sonrası bozulmasın)
            if db.get_setting("autostart", True):
                winutil.set_autostart(True)
            if not db.get_meta("first_run_done") or winutil.desktop_shortcut_exists():
                winutil.create_desktop_shortcut()
        except Exception:
            traceback.print_exc()
        db.set_meta("first_run_done", True)
    if not args.background:
        winutil.open_ui()
    stop = threading.Event()
    if args.no_tray:
        try:
            stop.wait()
        except KeyboardInterrupt:
            pass
    else:
        from . import tray
        tray.run(on_quit=stop.set)
    runtime.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
