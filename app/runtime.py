"""Sunucu iş parçacıkları (yerel + isteğe bağlı LAN) ve arka plan döngüleri."""
from __future__ import annotations

import threading
import time

import uvicorn

from . import config

_app = None
_servers: dict[str, tuple[uvicorn.Server, threading.Thread]] = {}
_stop = threading.Event()
_bg_threads: list[threading.Thread] = []


def app():
    global _app
    if _app is None:
        from .server import create_app
        _app = create_app()
    return _app


def _start_server(name: str, host: str, port: int) -> bool:
    if name in _servers:
        return True
    cfg = uvicorn.Config(app(), host=host, port=port, log_level="warning", access_log=False, loop="asyncio",
                         http="h11", ws="none", lifespan="off")
    srv = uvicorn.Server(cfg)
    th = threading.Thread(target=srv.run, name=f"uvicorn-{name}", daemon=True)
    th.start()
    for _ in range(100):
        if srv.started:
            break
        if not th.is_alive():
            return False
        time.sleep(0.05)
    _servers[name] = (srv, th)
    return bool(srv.started)


def _stop_server(name: str) -> None:
    item = _servers.pop(name, None)
    if item:
        srv, th = item
        srv.should_exit = True
        th.join(timeout=5)


def start_local() -> bool:
    return _start_server("local", "127.0.0.1", config.LOCAL_PORT)


def set_lan(enabled: bool) -> bool:
    if enabled:
        return _start_server("lan", "0.0.0.0", config.LAN_PORT)
    _stop_server("lan")
    return True


def start_background() -> None:
    from . import coach, enrichment
    for target, name in ((coach.loop, "coach"), (enrichment.worker_loop, "llm")):
        th = threading.Thread(target=target, args=(_stop,), name=name, daemon=True)
        th.start()
        _bg_threads.append(th)

    def cleanup():
        from . import session
        while not _stop.wait(1800):
            try:
                session.cleanup_old()
            except Exception:
                pass
    th = threading.Thread(target=cleanup, name="cleanup", daemon=True)
    th.start()
    _bg_threads.append(th)

    def warm():
        """İlk ekranın hızlı açılması için plan, projeksiyon ve puan tahminini önceden hesapla."""
        try:
            from . import planner, projection, score_model
            planner.today_plan()
            projection.compute()
            score_model.compute()
        except Exception:
            pass
    th = threading.Thread(target=warm, name="warm", daemon=True)
    th.start()
    _bg_threads.append(th)


def shutdown() -> None:
    _stop.set()
    for name in list(_servers):
        _stop_server(name)
    from . import db
    db.close()
