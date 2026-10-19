"""Koç: bildirimler, hatırlatmalar, seri ve arka plan görevlerinin zamanlaması.

Her mesaj somut sayıya dayanır; genel motivasyon cümlesi yoktur. Sessiz saatlere uyulur.
"""
from __future__ import annotations

import threading
import traceback
from datetime import date, datetime, time as dtime, timedelta

from . import config, db

_notifier = None  # tray tarafından ayarlanır: callable(title, body)
_lock = threading.Lock()


def set_notifier(fn) -> None:
    global _notifier
    _notifier = fn


def _hm(s: str) -> dtime:
    h, m = (int(x) for x in s.split(":"))
    return dtime(h, m)


def in_quiet_hours(now: datetime | None = None) -> bool:
    now = (now or config.local_now()).astimezone()
    qs, qe = _hm(db.get_setting("quiet_start", "23:30")), _hm(db.get_setting("quiet_end", "08:00"))
    t = now.time()
    if qs <= qe:
        return qs <= t < qe
    return t >= qs or t < qe


def notify(kind: str, title: str, body: str, key: str | None = None, level: int = 0, force: bool = False) -> int | None:
    day = config.day_str()
    if key and db.q1("SELECT id FROM notifications WHERE day=? AND key=?", (day, key)):
        return None
    nid = db.x("INSERT INTO notifications(ts, day, kind, key, title, body, level) VALUES(?,?,?,?,?,?,?)",
               (config.iso(config.now_utc()), day, kind, key, title, body, level))
    if db.get_setting("notifications", True) and (force or not in_quiet_hours()):
        if _notifier:
            try:
                _notifier(title, body)
                db.x("UPDATE notifications SET delivered=1 WHERE id=?", (nid,))
            except Exception:
                pass
    return nid


def recent(limit: int = 20) -> list[dict]:
    return db.q("SELECT * FROM notifications ORDER BY id DESC LIMIT ?", (limit,))


# ---------------------------------------------------------------- seri
def streak() -> dict:
    """10 dk (ayarlanabilir) çalışılan günler seriyi sürdürür; 7 günde bir kaçırılan gün affedilir."""
    min_min = float(db.get_setting("streak_min_minutes", 10))
    rows = db.q("SELECT day, SUM(active_ms) ms FROM activity GROUP BY day")
    mins = {r["day"]: (r["ms"] or 0) / 60000.0 for r in rows}
    today = config.study_day()
    done = lambda d: mins.get(d.isoformat(), 0) >= min_min  # noqa: E731
    cur = 0
    freezes_used: list[str] = []
    d = today if done(today) else today - timedelta(days=1)
    last_freeze: date | None = None
    while True:
        if done(d):
            cur += 1
            d -= timedelta(days=1)
            continue
        # tek gün affı: önceki gün çalışılmışsa ve son 7 günde af kullanılmamışsa
        prev = d - timedelta(days=1)
        if done(prev) and (last_freeze is None or (last_freeze - d).days >= 7) and cur > 0:
            freezes_used.append(d.isoformat())
            last_freeze = d
            d = prev
            continue
        break
    # en iyi seri (affı yok sayarak basit hesap)
    best = 0
    run = 0
    if mins:
        start = date.fromisoformat(min(mins))
        x = start
        while x <= today:
            run = run + 1 if done(x) else 0
            best = max(best, run)
            x += timedelta(days=1)
    week = []
    monday = today - timedelta(days=today.weekday())
    for i in range(7):
        dd = monday + timedelta(days=i)
        week.append({"day": dd.isoformat(), "done": done(dd), "minutes": round(mins.get(dd.isoformat(), 0)),
                     "freeze": dd.isoformat() in freezes_used, "future": dd > today})
    return {"current": cur, "best": max(best, cur), "today_done": done(today),
            "today_minutes": round(mins.get(today.isoformat(), 0), 1), "min_minutes": min_min,
            "freezes": freezes_used, "week": week}


# ---------------------------------------------------------------- mesaj üreticileri
def _hello(text: str) -> str:
    """"Mert, bugün: …" — ad girilmemişse yalnızca cümle (büyük harfle)."""
    name = (db.get_setting("user_name", "") or "").strip()
    return f"{name}, {text}" if name else text[:1].upper() + text[1:]


def morning_message() -> tuple[str, str]:
    from . import planner
    p = planner.today_plan()
    parts = []
    if p.get("reviews_planned"):
        parts.append(f"{p['reviews_planned']} tekrar")
    if p.get("new_planned"):
        parts.append(f"{p['new_planned']} yeni kelime")
    if p.get("sweep_target"):
        parts.append(f"{p['sweep_target']} kelimelik hızlı tur")
    if p.get("weekly_test"):
        parts.append("haftalık YDS testi")
    body = _hello("bugün: ") + (" + ".join(parts) if parts else "plan boş") + f" ≈ {p.get('minutes', 0)} dk."
    if p.get("phase") == "final":
        body += f" Sınava {p.get('days_to_exam')} gün: yeni kelime yok, liste taraması."
    return "Günün planı", body


def reminder_message(level: int) -> tuple[str, str] | None:
    from . import planner
    prog = planner.progress_today()
    if prog["fraction"] >= 0.999:
        return None
    t = planner.tomorrow_load_if_skipped()
    pct = round(prog["fraction"] * 100)
    rem = prog["remaining_min"]
    if level <= 1:
        body = _hello(f"bugünkü planın %{pct}'i bitti; kalan ≈ {rem} dk.")
    elif level == 2:
        body = _hello(f"bugünkü planın %{pct}'i bitti. Kalan {rem} dk'yı yapmazsan yarınki yük "
                f"{t['tomorrow_planned']} dk yerine {t['tomorrow_if_skip']} dk'ya çıkıyor.")
    else:
        body = (f"Son çağrı: {t['left_reviews']} tekrar ve {t['left_new']} yeni kelime bekliyor. "
                f"Yalnızca 10 dk'lık zor gün oturumu bile seriyi korur ve en riskli {min(60, t['left_reviews'])} tekrarı kurtarır.")
    return ("Çalışma hatırlatması", body)


def pace_message() -> tuple[str, str] | None:
    from . import projection, planner
    pr = projection.compute()
    pc = projection.pace()
    plan = planner.today_plan()
    if pc["days_observed"] < 3:
        return None
    need = plan.get("minutes") or 0
    avg = pc["minutes_per_day"]
    head = f"Son 7 günün ortalaması {avg:.0f} dk/gün; hedef için {need} dk gerekiyor."
    finish = (pr.get("pace") or {}).get("finish_date")
    fs = pr.get("final_start")
    if not finish or finish == "—" or not fs:
        return ("Tempo", head) if avg + 5 < need else None
    f_d, exam, fs_d = date.fromisoformat(finish), date.fromisoformat(plan["exam_date"]), date.fromisoformat(fs)
    if f_d > exam:
        return ("Tempo", f"{head} Bu tempoyla liste sınavdan {(f_d - exam).days} gün sonra bitiyor.")
    if f_d > fs_d:
        return ("Tempo", f"{head} Bu tempoyla yeni kelimeler sınava {(exam - f_d).days} gün kala bitiyor; "
                         f"son tekrar haftasına {(f_d - fs_d).days} gün taşıyor.")
    return ("Tempo", head) if avg + 5 < need else None


def hour_message() -> tuple[str, str] | None:
    from . import analysis
    eff = analysis.late_hour_effect()
    if not eff:
        return None
    return ("Saat önerisi", f"{eff['cut']:02d}.00'den sonra doğruluğun %{eff['drop'] * 100:.0f} düşüyor "
                            f"(%{eff['early_acc'] * 100:.0f} → %{eff['late_acc'] * 100:.0f}); yarın {eff['best_hour']:02d}.00'de başla.")


def realism_message() -> tuple[str, str] | None:
    from . import planner
    p = planner.today_plan()
    if p.get("realism"):
        return ("Gerçekçilik kontrolü", p["realism"]["message"])
    return None


def missed_day_message() -> tuple[str, str] | None:
    from . import planner
    y = (config.study_day() - timedelta(days=1)).isoformat()
    act = db.val("SELECT SUM(active_ms) FROM activity WHERE day=?", (y,), default=0) or 0
    had_before = db.val("SELECT COUNT(*) FROM activity WHERE day<?", (y,), default=0) or 0
    if act > 0 or not had_before:
        return None
    p = planner.today_plan()
    if p.get("review_cap"):
        return ("Dünkü açık", f"Dün çalışmadın; yük tek güne yığılmadı: bugün en riskli {p['review_cap']} tekrar, "
                              f"kalan {p['reviews_due'] - p['review_cap']} tekrar sonraki günlere yayıldı.")
    return ("Dünkü açık", f"Dün çalışmadın; bugünkü plan yeniden hesaplandı: {p['reviews_planned']} tekrar (en riskliler önce) "
                          f"+ {p['new_planned']} yeni ≈ {p['minutes']} dk.")


# ---------------------------------------------------------------- zamanlayıcı
_state = {"last_day": None}


def tick(now: datetime | None = None) -> list[str]:
    """Dakikada bir çağrılır. Yapılan işlerin listesini döner (test/izleme için)."""
    from . import backup, planner, projection, strategy, interventions
    done = []
    now = (now or config.local_now()).astimezone()
    today = config.study_day()
    key = today.isoformat()
    meta_day = db.get_meta("coach_day")
    if meta_day != key:
        db.set_meta("coach_day", key)
        db.set_meta("coach_sent", {})
        planner.today_plan(recompute=True)
        projection.invalidate()
        try:
            backup.daily_backup()
            done.append("yedek")
        except Exception:
            traceback.print_exc()
        done.append("plan")
    sent = db.get_meta("coach_sent", {}) or {}

    def once(k: str) -> bool:
        if sent.get(k):
            return False
        sent[k] = True
        db.set_meta("coach_sent", sent)
        return True

    if not db.get_setting("setup_done", False):
        return done
    t = now.time()
    mt = _hm(db.get_setting("morning_time", "08:30"))
    if t >= mt and not in_quiet_hours(now) and once("morning"):
        title, body = morning_message()
        notify("plan", title, body, key="morning")
        m = missed_day_message()
        if m:
            notify("plan", m[0], m[1], key="missed", level=1)
        r = realism_message()
        if r:
            notify("gerçekçilik", r[0], r[1], key="realism", level=2)
        done.append("sabah")
    hours = [_hm(h) for h in (db.get_setting("study_hours") or [])]
    for i, h in enumerate(sorted(hours)):
        start = datetime.combine(now.date(), h, tzinfo=now.tzinfo)
        if now >= start and now - start < timedelta(hours=3) and once(f"remind-{i}"):
            level = min(3, i + 1)
            msg = reminder_message(level)
            if msg:
                notify("hatırlatma", msg[0], msg[1], key=f"remind-{i}", level=level)
                done.append(f"hatırlatma-{i}")
            if i == 0 and once("pace"):
                pm = pace_message()
                if pm:
                    notify("tempo", pm[0], pm[1], key="pace", level=1)
    # son hatırlatma: sessiz saatlerden 60 dk önce
    qs = _hm(db.get_setting("quiet_start", "23:30"))
    last_call = (datetime.combine(now.date(), qs, tzinfo=now.tzinfo) - timedelta(minutes=60))
    if last_call <= now < last_call + timedelta(minutes=30) and once("last-call"):
        msg = reminder_message(3)
        if msg:
            notify("hatırlatma", msg[0], msg[1], key="last-call", level=3)
    # haftada bir saat önerisi
    if now.weekday() == 2 and t >= dtime(12, 0) and once("hour-tip"):
        hm = hour_message()
        if hm:
            notify("analiz", hm[0], hm[1], key="hour-tip", level=1)
    # haftalık görevler (haftalık tekrar günü 05:00 sonrası)
    wday = int(db.get_setting("weekly_review_day", 6))
    if now.weekday() == wday and t >= dtime(5, 0) and once("weekly-jobs"):
        weekly_jobs()
        done.append("haftalık")
    # günlük: deney değerlendirme, müdahale etkisi
    if t >= dtime(5, 0) and once("daily-jobs"):
        try:
            strategy.evaluate()
            interventions.evaluate_all()
            from . import enrichment
            enrichment.queue_missing()
        except Exception:
            traceback.print_exc()
    return done


def weekly_jobs() -> dict:
    from . import optimizer, planner, weekly
    out = {}
    try:
        out["fsrs"] = optimizer.weekly()
    except Exception as e:
        out["fsrs"] = {"error": str(e)}
    try:
        out["retention"] = planner.choose_retention()
    except Exception as e:
        out["retention"] = {"error": str(e)}
    try:
        out["session"] = adapt_session_length()
    except Exception as e:
        out["session"] = {"error": str(e)}
    try:
        out["report"] = weekly.make_report()
    except Exception as e:
        out["report"] = {"error": str(e)}
    return out


def adapt_session_length() -> dict | None:
    """Oturumun kaçıncı dakikasından sonra doğruluk düşüyorsa oturum süresini ona göre ayarla."""
    from . import analysis, strategy
    f = analysis.session_fatigue(30)
    cur = int(db.get_setting("max_session_minutes", 20))
    if not f:
        return None
    new = max(10, min(40, int(f["drop_after_min"])))
    if new != cur:
        db.set_setting("max_session_minutes", new)
        strategy.log_change("max_session_minutes", cur, new,
                            f"Oturumun {f['drop_after_min']}. dakikasından sonra doğruluk %{f['base_acc'] * 100:.0f} → "
                            f"%{(f['acc'] or 0) * 100:.0f}; oturum/mola aralığı {new} dk yapıldı.", f)
    return f


def loop(stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            tick()
        except Exception:
            traceback.print_exc()
        stop.wait(60)
