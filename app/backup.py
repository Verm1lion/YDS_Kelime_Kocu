"""Günlük otomatik yedek (son 14 kopya) ve CSV dışa aktarma."""
from __future__ import annotations

import csv
import io
import sqlite3
import zipfile
from pathlib import Path

from . import config, db

KEEP = 14


def _backup_to(dst: Path) -> None:
    src = db.get_conn()
    with db.lock():
        dconn = sqlite3.connect(str(dst))
        try:
            src.backup(dconn)
        finally:
            dconn.close()


def daily_backup() -> Path | None:
    d = config.backup_dir()
    name = f"yds_kocu_{config.day_str()}.db"
    dst = d / name
    if dst.exists():
        return None
    _backup_to(dst)
    prune()
    db.set_meta("last_backup", config.iso(config.now_utc()))
    return dst


def backup_now(label: str = "elle") -> Path:
    d = config.backup_dir()
    dst = d / f"yds_kocu_{config.day_str()}_{label}_{config.now_utc().strftime('%H%M%S')}.db"
    _backup_to(dst)
    prune()
    return dst


def prune() -> None:
    d = config.backup_dir()
    daily = sorted(d.glob("yds_kocu_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in daily[KEEP:]:
        try:
            p.unlink()
        except OSError:
            pass
    mig = sorted(d.glob("migration_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in mig[5:]:
        try:
            p.unlink()
        except OSError:
            pass


def list_backups() -> list[dict]:
    d = config.backup_dir()
    out = []
    for p in sorted(d.glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True):
        out.append({"name": p.name, "size_kb": round(p.stat().st_size / 1024), "path": str(p)})
    return out


EXPORTS = {
    "events": "SELECT * FROM events ORDER BY id",
    "kelimeler": """SELECT w.id, w.lemma, w.display, w.kind, w.pos, w.meaning_src, w.meaning_user, w.meaning_gen, w.level,
                           w.priority, w.order_index, w.zipf, w.pool, w.status, c.stage, c.state, c.stability, c.difficulty,
                           c.due_day, c.last_review, c.reps, c.lapses, c.wrong_total, c.introduced_at, c.learned_at,
                           c.known_status, c.flag_hard
                    FROM words w LEFT JOIN cards c ON c.word_id=w.id ORDER BY w.order_index""",
    "oturumlar": "SELECT * FROM sessions ORDER BY started_at",
    "aktif_sure": "SELECT * FROM activity ORDER BY id",
    "strateji_gunlugu": "SELECT * FROM strategy_log ORDER BY id",
    "mudahaleler": "SELECT * FROM interventions ORDER BY id",
    "deneme_sinavlari": "SELECT * FROM mock_exams ORDER BY day",
    "ornek_cumleler": "SELECT * FROM examples ORDER BY word_id, id",
    "isaretler": "SELECT * FROM flags ORDER BY id",
}


def export_csv(name: str) -> bytes:
    sql = EXPORTS[name]
    rows = db.q(sql)
    buf = io.StringIO()
    if rows:
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return ("﻿" + buf.getvalue()).encode("utf-8")


def export_zip() -> bytes:
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w", zipfile.ZIP_DEFLATED) as z:
        for name in EXPORTS:
            z.writestr(f"{name}.csv", export_csv(name))
    return mem.getvalue()
