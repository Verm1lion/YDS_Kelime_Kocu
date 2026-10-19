"""Yollar, sabitler, .env okuma ve zaman yardımcıları."""
from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

APP_NAME = "YDS Kelime Koçu"
APP_ID = "YDSKelimeKocu"
VERSION = "1.0.0"
LOCAL_PORT = int(os.environ.get("YDS_PORT", "8765"))
LAN_PORT = int(os.environ.get("YDS_LAN_PORT", str(LOCAL_PORT + 1)))
DAY_START_HOUR = 4  # 04:00'ten önceki çalışmalar bir önceki güne sayılır


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_dir() -> Path:
    """Salt-okunur paket kaynakları (web/, seed/)."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def exe_dir() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


_DATA_DIR: Path | None = None


def data_dir() -> Path:
    global _DATA_DIR
    if _DATA_DIR is not None:
        return _DATA_DIR
    env = os.environ.get("YDS_DATA_DIR")
    if env:
        p = Path(env)
    elif is_frozen():
        p = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / APP_ID
    else:
        p = resource_dir() / "data_dev"
    p.mkdir(parents=True, exist_ok=True)
    _DATA_DIR = p
    return p


def set_data_dir(p: Path) -> None:
    """Testler ve simülasyon için."""
    global _DATA_DIR
    p.mkdir(parents=True, exist_ok=True)
    _DATA_DIR = p


def db_path() -> Path:
    return data_dir() / "yds_kocu.db"


def backup_dir() -> Path:
    p = data_dir() / "yedekler"
    p.mkdir(parents=True, exist_ok=True)
    return p


def tts_dir() -> Path:
    p = data_dir() / "ses"
    p.mkdir(parents=True, exist_ok=True)
    return p


def web_dir() -> Path:
    return resource_dir() / "web"


def seed_dir() -> Path:
    return resource_dir() / "seed"


def pool_path() -> Path:
    """Kelime listesi: yerel seed/pool.json (kitap planı; telif nedeniyle repoda yok) varsa o, yoksa repodaki
    seed/pool_public.json (akıllı havuz: 2.200 kart + 110 öbek fiil + 1.300 yedek)."""
    p = seed_dir() / "pool.json"
    return p if p.exists() else seed_dir() / "pool_public.json"


# ---------------------------------------------------------------- .env
def env_paths() -> list[Path]:
    paths = [data_dir() / ".env", exe_dir() / ".env"]
    if not is_frozen():
        paths.append(resource_dir() / ".env")
    out = []
    for p in paths:
        if p not in out:
            out.append(p)
    return out


def read_env() -> dict[str, str]:
    vals: dict[str, str] = {}
    for p in reversed(env_paths()):  # ilk yol en yüksek öncelik
        if not p.exists():
            continue
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                vals[k.strip()] = v.strip().strip('"').strip("'")
        except OSError:
            continue
    for k in ("GEMINI_API_KEY", "GEMINI_MODEL"):
        if os.environ.get(k):
            vals[k] = os.environ[k]
    return vals


def write_env_value(key: str, value: str) -> Path:
    p = data_dir() / ".env"
    lines: list[str] = []
    found = False
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.split("=", 1)[0].strip() == key:
                lines.append(f"{key}={value}")
                found = True
            else:
                lines.append(line)
    if not found:
        lines.append(f"{key}={value}")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


# ---------------------------------------------------------------- zaman
def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def local_now() -> datetime:
    return datetime.now().astimezone()


def study_day(dt: datetime | None = None) -> date:
    """Yerel saatle 'çalışma günü' (04:00 sınırı)."""
    dt = dt or now_utc()
    loc = dt.astimezone()
    return (loc - timedelta(hours=DAY_START_HOUR)).date()


def day_str(d: date | datetime | None = None) -> str:
    if d is None:
        d = study_day()
    if isinstance(d, datetime):
        d = study_day(d)
    return d.isoformat()


def parse_day(s: str) -> date:
    return date.fromisoformat(s)


def day_start_utc(d: date) -> datetime:
    """Çalışma gününün başlangıcı (yerel 04:00) UTC olarak."""
    loc = datetime(d.year, d.month, d.day, DAY_START_HOUR, 0, 0).astimezone()
    return loc.astimezone(timezone.utc)
