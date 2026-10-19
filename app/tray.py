"""Sistem tepsisi simgesi ve Windows bildirimleri (pystray)."""
from __future__ import annotations

import threading

from . import config, db

_icon = None


def _image():
    from PIL import Image
    p = config.resource_dir() / "assets" / "app.png"
    if p.exists():
        return Image.open(p)
    from .icon_art import render_icon
    return render_icon(64)


def notify(title: str, body: str) -> None:
    if _icon is not None:
        try:
            _icon.notify(body, title)
        except Exception:
            pass


def run(on_quit=None) -> None:
    import pystray
    from pystray import Menu, MenuItem as Item
    from . import coach, winutil

    def open_app(icon=None, item=None):
        winutil.open_ui()

    def open_page(path):
        return lambda icon, item: winutil.open_ui(path)

    def today_label(item):
        try:
            from . import planner
            p = planner.progress_today()
            return f"Bugün: %{round(p['fraction'] * 100)} · kalan ≈ {p['remaining_min']} dk"
        except Exception:
            return "Bugün"

    def toggle_notif(icon, item):
        db.set_setting("notifications", not db.get_setting("notifications", True))

    def toggle_auto(icon, item):
        en = not winutil.autostart_enabled()
        winutil.set_autostart(en)
        db.set_setting("autostart", en)

    def backup(icon, item):
        from . import backup as B
        p = B.backup_now()
        notify("Yedek alındı", p.name)

    def quit_app(icon, item):
        icon.stop()
        if on_quit:
            on_quit()

    menu = Menu(
        Item("Aç", open_app, default=True),
        Item(today_label, None, enabled=False),
        Menu.SEPARATOR,
        Item("Bugünkü çalışmaya başla", open_page("/#/calis?mod=daily")),
        Item("Hızlı tekrar", open_page("/#/calis?mod=quick")),
        Item("Analiz", open_page("/#/analiz")),
        Menu.SEPARATOR,
        Item("Bildirimler", toggle_notif, checked=lambda i: bool(db.get_setting("notifications", True))),
        Item("Bilgisayar açılınca başlat", toggle_auto, checked=lambda i: winutil.autostart_enabled()),
        Item("Şimdi yedek al", backup),
        Menu.SEPARATOR,
        Item("Çıkış", quit_app),
    )
    global _icon
    _icon = pystray.Icon("yds_kocu", _image(), config.APP_NAME, menu)
    coach.set_notifier(notify)
    _icon.run()
