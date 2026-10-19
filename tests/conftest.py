import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _reset_caches():
    from app import db, words, planner, projection, rating, distractors, strategy
    db.close()
    words.invalidate_index()
    words._offline = None
    planner._tier_cache = None
    projection.invalidate()
    rating.invalidate_cache()
    distractors.clear_cache()
    strategy._session_arms.clear()


@pytest.fixture()
def appdb(monkeypatch):
    d = Path(tempfile.mkdtemp(prefix="yds_test_"))
    from app import config
    config.set_data_dir(d)
    _reset_caches()
    from app import seed_loader, db
    seed_loader.init_db()
    db.set_setting("setup_done", True)
    yield db
    _reset_caches()
    shutil.rmtree(d, ignore_errors=True)
