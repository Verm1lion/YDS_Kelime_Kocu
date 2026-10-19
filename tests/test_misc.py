"""Migration, puan modeli, strateji kararları, yedek, analiz, koç mesajları."""
from datetime import timedelta

import numpy as np


def test_migration_idempotent_and_preserves_data(appdb):
    from app import config
    from app import db, seed_loader
    v1 = db.current_version(db.get_conn())
    wid = db.val("SELECT id FROM words LIMIT 1")
    db.x("UPDATE words SET meaning_user='benim anlamım' WHERE id=?", (wid,))
    seed_loader.init_db()  # ikinci kez
    assert db.current_version(db.get_conn()) == v1 == db.SCHEMA_VERSION
    assert db.val("SELECT meaning_user FROM words WHERE id=?", (wid,)) == "benim anlamım"
    import json
    main = sum(1 for it in json.loads(config.pool_path().read_text(encoding="utf-8"))["items"]
               if it["pool"] == "main")
    assert db.val("SELECT COUNT(*) FROM words WHERE pool='main'") == main


def test_user_meaning_never_overwritten_by_seed(appdb):
    from app import db, seed_loader
    wid = db.val("SELECT id FROM words WHERE lemma='foster'")
    src = db.val("SELECT meaning_src FROM words WHERE id=?", (wid,))
    seed_loader.load_seed_content(force=True)
    assert db.val("SELECT meaning_src FROM words WHERE id=?", (wid,)) == src


def test_score_model_monotonic_in_mastery(appdb):
    from app import score_model as SM
    th = np.array([0.0])
    lo = SM.section_probs(th, 0.13, 93.0, 0.3)
    hi = SM.section_probs(th, 0.13, 97.0, 0.9)
    n = [s[1] for s in SM.SECTIONS]
    assert sum(a * p[0] for a, p in zip(n, hi)) > sum(a * p[0] for a, p in zip(n, lo))


def test_score_compute_and_mock_update(appdb):
    from app import score_model as SM
    base = SM.compute()
    assert base["available"]
    assert 0 <= base["p_target"] <= 1
    ps = [a["p"] for a in base["at_least"]]
    assert all(ps[i] >= ps[i + 1] for i in range(len(ps) - 1))  # 'en az' olasılıkları azalan
    SM.add_mock((__import__("datetime").date.today()).isoformat(), 62, None, "test")
    after = SM.compute()
    assert after["median"] > base["median"]  # iyi deneme sonucu tahmini yukarı çeker


def test_strategy_no_decision_without_samples(appdb):
    from app import strategy, config, db
    strategy.ensure_experiments()
    exp = strategy.running("pack_size")
    for k in range(10):
        db.x("INSERT INTO exp_assignments(experiment_id, unit_id, arm, assigned_at, outcome) VALUES(?,?,?,?,?)",
             (exp["id"], f"w{k}", "5", config.iso(config.now_utc()), 1.0))
    assert strategy.evaluate() == []
    # yeterli örnek + net fark -> karar
    for arm, rate in (("4", 0.55), ("5", 0.6), ("7", 0.9)):
        for k in range(60):
            db.x("INSERT OR IGNORE INTO exp_assignments(experiment_id, unit_id, arm, assigned_at, outcome) VALUES(?,?,?,?,?)",
                 (exp["id"], f"x{arm}-{k}", arm, config.iso(config.now_utc()), 1.0 if k < rate * 60 else 0.0))
    dec = strategy.evaluate()
    assert any(d["variable"] == "pack_size" and d["new"] == 7 for d in dec)
    log = db.q1("SELECT * FROM strategy_log WHERE variable='pack_size' ORDER BY id DESC")
    assert log and "P(en iyi)" in log["reason"]
    assert strategy.revert(log["id"])["ok"]
    assert db.get_setting("pack_size") == 5


def test_backup_and_export(appdb):
    from app import backup
    p = backup.daily_backup()
    assert p is not None and p.exists()
    assert backup.daily_backup() is None  # aynı gün ikinci yedek yok
    data = backup.export_csv("kelimeler")
    assert data.startswith("﻿".encode("utf-8")) and b"lemma" in data
    assert len(backup.export_zip()) > 1000


def test_quick_add_offline_dictionary(appdb):
    from app import words as W, db
    r = W.add_user_word("alleviate")
    assert r["status"] in ("new", "existing")
    r2 = W.add_user_word("serendipitousnessx", meaning="deneme anlam")
    assert r2["status"] == "new" and r2["meaning"] == "deneme anlam"
    row = db.q1("SELECT * FROM words WHERE id=?", (r2["id"],))
    assert row["pool"] == "user" and row["meaning_user"] == "deneme anlam"
    first = db.q1("""SELECT w.id FROM words w JOIN cards c ON c.word_id=w.id WHERE w.status='active' AND c.introduced_at IS NULL
                     ORDER BY w.order_index LIMIT 1""")
    assert first["id"] == r2["id"]  # sıradaki pakete girer
    assert db.val("SELECT COUNT(*) FROM llm_jobs WHERE kind='enrich'") >= 1


def test_coach_messages_are_numeric(appdb):
    from app import coach, planner
    title, body = coach.morning_message()
    assert any(ch.isdigit() for ch in body)
    msg = coach.reminder_message(2)
    assert msg is None or any(ch.isdigit() for ch in msg[1])


def test_analysis_runs_on_empty_and_after_session(appdb):
    from app import analysis, session
    analysis.overview()
    r = session.start("learn", limit=3)
    sid = r["session_id"]
    item = session.next_item(sid)
    for _ in range(10):
        if item.get("type") == "done":
            break
        body = {"token": item["token"], "total_ms": 1500, "first_key_ms": 800}
        if "options" in item:
            body["choice"] = 0
        elif item["type"] in ("typing", "tiles"):
            body["text"] = "x"
        item = session.answer(sid, item["token"], body)["next"]
    ov = analysis.overview()
    assert ov["errors"]["total_answers"] > 0
    assert "groups" in ov["features"]
