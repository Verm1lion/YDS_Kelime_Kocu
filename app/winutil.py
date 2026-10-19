"""Windows yardımcıları: tek örnek, başlangıçta otomatik çalışma, kısayollar, uygulama penceresi."""
from __future__ import annotations

import os
import subprocess
import sys
import urllib.request
import webbrowser
from pathlib import Path

from . import config

STARTUP_NAME = "YDS Kelime Koçu.lnk"


def is_running(port: int | None = None) -> bool:
    """Bu portta BİZİM uygulamamız mı çalışıyor?"""
    import json
    port = port or config.LOCAL_PORT
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1.5) as r:
            data = json.loads(r.read().decode("utf-8"))
            return r.status == 200 and data.get("app") == config.APP_NAME
    except Exception:
        return False


def port_free(port: int) -> bool:
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def choose_port() -> tuple[int, bool]:
    """(port, zaten_çalışıyor). Kayıtlı port → 8765… sırasıyla; başka program kullanıyorsa sonrakine geçer."""
    saved = config.data_dir() / "port.txt"
    cands: list[int] = []
    if "YDS_PORT" in os.environ:
        cands.append(int(os.environ["YDS_PORT"]))
    elif saved.exists():
        try:
            cands.append(int(saved.read_text().strip()))
        except ValueError:
            pass
    cands += [p for p in range(8765, 8795, 2) if p not in cands]
    for p in cands:
        if is_running(p):
            return p, True
        if port_free(p) and port_free(p + 1):
            try:
                saved.write_text(str(p))
            except OSError:
                pass
            return p, False
    return cands[0], False


def _browser_paths() -> list[str]:
    cands = [
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]
    return [c for c in cands if os.path.exists(c)]


def open_ui(path: str = "/") -> None:
    """Edge/Chrome 'uygulama penceresi' (adres çubuğu yok); yoksa varsayılan tarayıcı."""
    url = f"http://127.0.0.1:{config.LOCAL_PORT}{path}"
    for exe in _browser_paths():
        try:
            prof = config.data_dir() / "pencere_profili"
            subprocess.Popen([exe, f"--app={url}", f"--user-data-dir={prof}", "--window-size=1280,860",
                              "--no-first-run", "--no-default-browser-check"],
                             creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
            return
        except Exception:
            continue
    webbrowser.open(url)


def _shortcut(path: Path, target: str, args: str, icon: str | None, workdir: str) -> bool:
    try:
        import pythoncom
        from win32com.client import Dispatch
        pythoncom.CoInitialize()
        shell = Dispatch("WScript.Shell")
        sc = shell.CreateShortCut(str(path))
        sc.Targetpath = target
        sc.Arguments = args
        sc.WorkingDirectory = workdir
        if icon:
            sc.IconLocation = icon
        sc.save()
        return True
    except Exception:
        ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{path}');$s.TargetPath='{target}';"
              f"$s.Arguments='{args}';$s.WorkingDirectory='{workdir}';" + (f"$s.IconLocation='{icon}';" if icon else "") + "$s.Save()")
        try:
            subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, timeout=20,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return path.exists()
        except Exception:
            return False


def _launch_target() -> tuple[str, str, str | None]:
    if config.is_frozen():
        exe = sys.executable
        return exe, "", exe
    pyw = Path(sys.executable).with_name("pythonw.exe")
    main = config.resource_dir() / "run_app.pyw"
    icon = str(config.resource_dir() / "assets" / "app.ico")
    return str(pyw if pyw.exists() else sys.executable), f'"{main}"', icon


def startup_dir() -> Path:
    return Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def set_autostart(enabled: bool) -> bool:
    p = startup_dir() / STARTUP_NAME
    if not enabled:
        try:
            p.unlink()
        except FileNotFoundError:
            pass
        return True
    target, args, icon = _launch_target()
    return _shortcut(p, target, (args + " --background").strip(), icon, str(config.exe_dir()))


def autostart_enabled() -> bool:
    return (startup_dir() / STARTUP_NAME).exists()


def _desktop_dir() -> Path:
    desk = Path(os.path.join(os.environ.get("USERPROFILE", ""), "Desktop"))
    try:
        import ctypes.wintypes
        buf = ctypes.create_unicode_buffer(260)
        ctypes.windll.shell32.SHGetFolderPathW(None, 0x0010, None, 0, buf)
        if buf.value:
            desk = Path(buf.value)
    except Exception:
        pass
    return desk


def desktop_shortcut_exists() -> bool:
    return (_desktop_dir() / "YDS Kelime Koçu.lnk").exists()


def create_desktop_shortcut() -> bool:
    p = _desktop_dir() / "YDS Kelime Koçu.lnk"
    target, args, icon = _launch_target()
    return _shortcut(p, target, args, icon, str(config.exe_dir()))
