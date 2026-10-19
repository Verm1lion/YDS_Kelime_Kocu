"""SQLite erişimi ve şema migration'ları.

Kural: migration'lar yalnızca EKLER (tablo/kolon/indeks). Kullanıcı verisi
asla silinmez; her migration öncesi veritabanının yedeği alınır.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

from . import config

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None
_conn_path: Path | None = None

MIGRATIONS: list[tuple[int, str]] = [
    (1, """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS words (
  id INTEGER PRIMARY KEY,
  lemma TEXT NOT NULL UNIQUE,
  display TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'word',
  pos TEXT,
  meaning_src TEXT,
  meaning_user TEXT,
  meaning_gen TEXT,
  family_src TEXT,
  level TEXT,
  text_prob REAL, option_prob REAL, src_count INTEGER,
  osym_evidence TEXT, tags TEXT, sources TEXT,
  priority REAL,
  order_index REAL,
  zipf REAL,
  pool TEXT NOT NULL DEFAULT 'main',
  status TEXT NOT NULL DEFAULT 'active',
  plan_week INTEGER, plan_day INTEGER,
  features TEXT,
  cov_weight REAL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_words_pool ON words(pool, status, order_index);

CREATE TABLE IF NOT EXISTS cards (
  word_id INTEGER PRIMARY KEY REFERENCES words(id),
  fsrs TEXT,
  state INTEGER NOT NULL DEFAULT 0,
  stability REAL, difficulty REAL,
  due TEXT, due_day TEXT,
  last_review TEXT,
  stage INTEGER NOT NULL DEFAULT 0,
  reps INTEGER NOT NULL DEFAULT 0,
  lapses INTEGER NOT NULL DEFAULT 0,
  wrong_total INTEGER NOT NULL DEFAULT 0,
  introduced_at TEXT,
  learned_at TEXT,
  durable_at TEXT,
  known_status TEXT,
  flag_hard INTEGER NOT NULL DEFAULT 0,
  last_exercise TEXT,
  last_intervention_at TEXT,
  updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_cards_due ON cards(due_day);
CREATE INDEX IF NOT EXISTS idx_cards_stage ON cards(stage);

CREATE TABLE IF NOT EXISTS examples (
  id INTEGER PRIMARY KEY,
  word_id INTEGER NOT NULL,
  en TEXT NOT NULL, tr TEXT,
  form TEXT, domain TEXT,
  source TEXT NOT NULL,
  verified INTEGER NOT NULL DEFAULT 0,
  flagged INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1,
  times_shown INTEGER NOT NULL DEFAULT 0,
  last_shown_at TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_examples_word ON examples(word_id);

CREATE TABLE IF NOT EXISTS word_info (
  id INTEGER PRIMARY KEY,
  word_id INTEGER NOT NULL,
  field TEXT NOT NULL,
  value TEXT NOT NULL,
  source TEXT NOT NULL,
  verified INTEGER NOT NULL DEFAULT 0,
  flagged INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_word_info ON word_info(word_id, field);

CREATE TABLE IF NOT EXISTS mnemonics (
  id INTEGER PRIMARY KEY,
  word_id INTEGER NOT NULL,
  text TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'association',
  source TEXT NOT NULL,
  verified INTEGER NOT NULL DEFAULT 0,
  flagged INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mnemonics_word ON mnemonics(word_id);

CREATE TABLE IF NOT EXISTS confusables (
  word_a INTEGER NOT NULL, word_b INTEGER NOT NULL,
  kind TEXT NOT NULL, score REAL, source TEXT,
  distinguished_at TEXT,
  PRIMARY KEY (word_a, word_b)
);

CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  mode TEXT, device TEXT,
  started_at TEXT NOT NULL, ended_at TEXT, day TEXT,
  active_ms INTEGER NOT NULL DEFAULT 0,
  n_answers INTEGER NOT NULL DEFAULT 0, n_correct INTEGER NOT NULL DEFAULT 0,
  n_new INTEGER NOT NULL DEFAULT 0, n_review INTEGER NOT NULL DEFAULT 0,
  meta TEXT
);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL, day TEXT NOT NULL,
  session_id TEXT, word_id INTEGER,
  mode TEXT, exercise TEXT, direction TEXT,
  prompt TEXT, answer TEXT, expected TEXT,
  correct INTEGER, result TEXT,
  first_key_ms INTEGER, total_ms INTEGER,
  hints INTEGER NOT NULL DEFAULT 0,
  rating INTEGER,
  error_type TEXT, confused_with INTEGER,
  stage_before INTEGER, stage_after INTEGER,
  fsrs_before TEXT, fsrs_after TEXT,
  r_before REAL, elapsed_days REAL,
  device TEXT, minute_in_session REAL,
  override_of INTEGER,
  extra TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_word ON events(word_id, ts);
CREATE INDEX IF NOT EXISTS idx_events_day ON events(day);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);

CREATE TABLE IF NOT EXISTS activity (
  id INTEGER PRIMARY KEY,
  session_id TEXT, ts TEXT NOT NULL, day TEXT NOT NULL,
  active_ms INTEGER NOT NULL, device TEXT
);
CREATE INDEX IF NOT EXISTS idx_activity_day ON activity(day);

CREATE TABLE IF NOT EXISTS daily_plans (day TEXT PRIMARY KEY, computed_at TEXT, plan TEXT);

CREATE TABLE IF NOT EXISTS strategy_log (
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL,
  variable TEXT, old_value TEXT, new_value TEXT,
  reason TEXT, data TEXT, experiment_id INTEGER,
  reverted INTEGER NOT NULL DEFAULT 0, notified INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS experiments (
  id INTEGER PRIMARY KEY, variable TEXT NOT NULL, arms TEXT NOT NULL,
  unit TEXT, metric TEXT, status TEXT NOT NULL DEFAULT 'running',
  started_at TEXT, ended_at TEXT, result TEXT
);
CREATE TABLE IF NOT EXISTS exp_assignments (
  experiment_id INTEGER NOT NULL, unit_id TEXT NOT NULL, arm TEXT NOT NULL,
  assigned_at TEXT, outcome REAL, outcome_at TEXT,
  PRIMARY KEY (experiment_id, unit_id)
);

CREATE TABLE IF NOT EXISTS fsrs_params (
  id INTEGER PRIMARY KEY, ts TEXT, params TEXT, n_reviews INTEGER,
  loss_before REAL, loss_after REAL, active INTEGER NOT NULL DEFAULT 0, note TEXT
);

CREATE TABLE IF NOT EXISTS interventions (
  id INTEGER PRIMARY KEY, word_id INTEGER, ts TEXT, kind TEXT,
  content TEXT, source TEXT, shown_at TEXT,
  pre_stats TEXT, post_stats TEXT, effective INTEGER
);

CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY, ts TEXT, day TEXT, kind TEXT, key TEXT,
  title TEXT, body TEXT, level INTEGER NOT NULL DEFAULT 0,
  delivered INTEGER NOT NULL DEFAULT 0, read INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_notif_day ON notifications(day, key);

CREATE TABLE IF NOT EXISTS llm_jobs (
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, payload TEXT,
  status TEXT NOT NULL DEFAULT 'queued', attempts INTEGER NOT NULL DEFAULT 0,
  error TEXT, created_at TEXT, updated_at TEXT, not_before TEXT, result TEXT
);
CREATE TABLE IF NOT EXISTS llm_usage (day TEXT PRIMARY KEY, requests INTEGER NOT NULL DEFAULT 0, tokens INTEGER NOT NULL DEFAULT 0);

CREATE TABLE IF NOT EXISTS placement (id INTEGER PRIMARY KEY, started_at TEXT, finished_at TEXT, result TEXT);

CREATE TABLE IF NOT EXISTS mock_exams (
  id INTEGER PRIMARY KEY, day TEXT, total_correct INTEGER, sections TEXT, note TEXT, created_at TEXT
);

CREATE TABLE IF NOT EXISTS flags (
  id INTEGER PRIMARY KEY, ts TEXT, word_id INTEGER, target TEXT, target_id INTEGER,
  note TEXT, resolved INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS projections (day TEXT PRIMARY KEY, computed_at TEXT, data TEXT);

CREATE TABLE IF NOT EXISTS weekly_reports (
  id INTEGER PRIMARY KEY, week_start TEXT, created_at TEXT, stats TEXT, text TEXT, source TEXT
);
"""),
    # 'biliyorum' / ön test artık 4 farklı türde kontrol istiyor: eski 2 kontrolle doğrulanmış ve henüz hiç tekrarı
    # olmamış kartlar bir kez yeniden doğrulamaya alınır (olay kaydı olduğu gibi kalır; göçten önce yedek alınır).
    (2, """
UPDATE cards SET known_status='probable', state=0, stage=0, fsrs=NULL, stability=NULL, difficulty=NULL, due=NULL,
  due_day=NULL, last_review=NULL, reps=0, learned_at=NULL, introduced_at=NULL
  WHERE known_status='verified' AND reps<=1;
"""),
    # partlar: yeni kelimeler en fazla 15'lik kalıcı gruplar hâlinde öğrenilir ve seçilip test edilebilir
    (3, """
CREATE TABLE IF NOT EXISTS parts (
  id INTEGER PRIMARY KEY, no INTEGER NOT NULL, created_at TEXT, day TEXT, size INTEGER NOT NULL DEFAULT 0, finished_at TEXT
);
CREATE TABLE IF NOT EXISTS part_words (
  part_id INTEGER NOT NULL, word_id INTEGER NOT NULL, pos INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (part_id, word_id)
);
CREATE INDEX IF NOT EXISTS idx_part_words_word ON part_words(word_id);
"""),
    (4, """
ALTER TABLE parts ADD COLUMN title TEXT;
"""),
]

SCHEMA_VERSION = max(v for v, _ in MIGRATIONS)


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=OFF")
    return conn


def get_conn() -> sqlite3.Connection:
    global _conn, _conn_path
    path = config.db_path()
    with _lock:
        if _conn is None or _conn_path != path:
            if _conn is not None:
                try:
                    _conn.close()
                except Exception:
                    pass
            _conn = _connect(path)
            _conn_path = path
        return _conn


def close() -> None:
    global _conn, _conn_path
    with _lock:
        if _conn is not None:
            try:
                _conn.close()
            except Exception:
                pass
        _conn = None
        _conn_path = None


def current_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        return int(row[0]) if row else 0
    except sqlite3.OperationalError:
        return 0


def migrate() -> int:
    """Eksik migration'ları uygular; uygulamadan önce yedek alır."""
    conn = get_conn()
    with _lock:
        ver = current_version(conn)
        pending = [(v, sql) for v, sql in MIGRATIONS if v > ver]
        if not pending:
            return ver
        path = config.db_path()
        if ver > 0 and path.exists():
            bdir = config.backup_dir()
            dst = bdir / f"migration_v{ver}_to_v{SCHEMA_VERSION}_{config.now_utc().strftime('%Y%m%d_%H%M%S')}.db"
            try:
                src = sqlite3.connect(str(path))
                dconn = sqlite3.connect(str(dst))
                src.backup(dconn)
                dconn.close()
                src.close()
            except Exception:
                shutil.copy2(path, dst)
        for v, sql in pending:
            conn.execute("BEGIN")
            try:
                for stmt in _split_sql(sql):
                    try:
                        conn.execute(stmt)
                    except sqlite3.OperationalError as e:
                        # sütun ekleme tekrar çalışırsa (geri alınmış sürüm numarası) sütun zaten vardır
                        if "duplicate column" in str(e) and stmt.lstrip().upper().startswith("ALTER TABLE"):
                            continue
                        raise
                conn.execute(
                    "INSERT INTO meta(key,value) VALUES('schema_version',?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(v),))
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return SCHEMA_VERSION


def _split_sql(sql: str) -> list[str]:
    return [s.strip() for s in sql.split(";") if s.strip()]


def add_column_if_missing(table: str, column: str, decl: str) -> None:
    conn = get_conn()
    with _lock:
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


# ---------------------------------------------------------------- yardımcılar
def q(sql: str, params: Iterable[Any] = ()) -> list[dict]:
    conn = get_conn()
    with _lock:
        cur = conn.execute(sql, tuple(params))
        return [dict(r) for r in cur.fetchall()]


def q1(sql: str, params: Iterable[Any] = ()) -> dict | None:
    conn = get_conn()
    with _lock:
        r = conn.execute(sql, tuple(params)).fetchone()
        return dict(r) if r else None


def val(sql: str, params: Iterable[Any] = (), default: Any = None) -> Any:
    conn = get_conn()
    with _lock:
        r = conn.execute(sql, tuple(params)).fetchone()
        return r[0] if r and r[0] is not None else default


def x(sql: str, params: Iterable[Any] = ()) -> int:
    """Çalıştırır; lastrowid döner."""
    conn = get_conn()
    with _lock:
        cur = conn.execute(sql, tuple(params))
        return cur.lastrowid or 0


def xmany(sql: str, seq: Iterable[Iterable[Any]]) -> None:
    conn = get_conn()
    with _lock:
        conn.executemany(sql, [tuple(s) for s in seq])


@contextmanager
def tx():
    conn = get_conn()
    with _lock:
        conn.execute("BEGIN")
        try:
            yield conn
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise


def lock() -> threading.RLock:
    return _lock


# ---------------------------------------------------------------- settings
DEFAULT_SETTINGS: dict[str, Any] = {
    "user_name": "",
    "exam_date": "2026-11-22",
    "exam_name": "2026-YDS/2",
    "target_score": 55,
    "self_level": "B1",   # İngilizce seviyem (öz değerlendirme): puan modelinde dil bilgisi/okuma becerisinin önseli
    "sound_effects": True,   # doğru/yanlış sesleri (Web Audio, çevrimdışı)
    "sound_volume": 0.6,
    "speak_answers": True,   # cevaplanınca doğru cevabı sesli söyle (çevrimdışı SAPI sesi)
    "listen_exercises": True,   # "dinle ve seç" alıştırması (kapalıysa yerine okumalı test)
    "target_recall": 0.95,
    "final_days": 7,
    "weekday_minutes": 60,
    "weekend_minutes": 90,
    "study_hours": ["09:00", "20:00"],
    "morning_time": "08:30",
    "weekly_review_day": 6,          # 0=Pzt ... 6=Paz
    "weekly_review_new_ratio": 0.0,  # haftalık tekrar günü yeni kelime oranı
    "quiet_start": "23:30",
    "quiet_end": "08:00",
    "theme": "auto",
    "pack_size": 5,
    "desired_retention": 0.90,
    "new_per_day_override": None,
    "max_session_minutes": 20,
    "break_minutes": 5,
    "distractor_level": 0.5,
    "mem_kind_default": "association",
    "exercise_mix": {"cloze": 0.35, "mcq_en_tr": 0.2, "context": 0.1, "typing": 0.15, "synonym": 0.15, "distinguish": 0.05},
    "include_reserve": False,
    "setup_done": False,
    "placement_done": False,
    "lan_enabled": False,
    "lan_pin_hash": None,
    "notifications": True,
    "autostart": True,
    "llm_rpm": 8,
    "llm_daily_requests": 200,
    "experiments_enabled": True,
    "speed_priors": None,
    "user_added_priority": "front",
    "streak_min_minutes": 10,
}


def get_setting(key: str, default: Any = None) -> Any:
    row = q1("SELECT value FROM settings WHERE key=?", (key,))
    if row is None:
        if key in DEFAULT_SETTINGS:
            return DEFAULT_SETTINGS[key]
        return default
    try:
        return json.loads(row["value"])
    except Exception:
        return row["value"]


def set_setting(key: str, value: Any) -> None:
    x("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
      (key, json.dumps(value, ensure_ascii=False)))


def all_settings() -> dict[str, Any]:
    out = dict(DEFAULT_SETTINGS)
    for r in q("SELECT key, value FROM settings"):
        try:
            out[r["key"]] = json.loads(r["value"])
        except Exception:
            out[r["key"]] = r["value"]
    return out


def get_meta(key: str, default: Any = None) -> Any:
    row = q1("SELECT value FROM meta WHERE key=?", (key,))
    if not row:
        return default
    try:
        return json.loads(row["value"])
    except Exception:
        return row["value"]


def set_meta(key: str, value: Any) -> None:
    x("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
      (key, json.dumps(value, ensure_ascii=False)))


def jdump(o: Any) -> str:
    return json.dumps(o, ensure_ascii=False, separators=(",", ":"))


def jload(s: str | None, default: Any = None) -> Any:
    if s is None or s == "":
        return default
    try:
        return json.loads(s)
    except Exception:
        return default
