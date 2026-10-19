"""Sınav günü projeksiyonu: FSRS hatırlanabilirlik modeliyle her kelimenin sınav günündeki hatırlanma olasılığı.

İki senaryo:
  - 'tempo': son 7 günün gerçek temposu (günlük yeni kelime + tekrar kapasitesi) sürerse
  - 'plan' : bugünkü plana uyulursa
"""
from __future__ import annotations

import threading
import time
from datetime import date, timedelta

import numpy as np

from . import cards as C
from . import config, db, planner, simcore

_cache: dict = {}
_lock = threading.Lock()
TTL = 900


def invalidate() -> None:
    with _lock:
        _cache.clear()


def pace(days: int = 7) -> dict:
    today = config.study_day()
    since = today - timedelta(days=days)
    rows = db.q("SELECT substr(introduced_at,1,10) d, COUNT(*) n FROM cards WHERE introduced_at>=? GROUP BY d",
                (config.iso(config.day_start_utc(since)),))
    n_new = sum(r["n"] for r in rows)
    act_days = db.q("SELECT day, SUM(active_ms) ms FROM activity WHERE day>=? AND day<? GROUP BY day",
                    (since.isoformat(), today.isoformat()))
    minutes = [r["ms"] / 60000.0 for r in act_days]
    first = db.val("SELECT MIN(day) FROM activity", default=None)
    span = days
    if first:
        span = max(1, min(days, (today - date.fromisoformat(first)).days))
    reviews = db.val("""SELECT COUNT(*) FROM events WHERE day>=? AND day<? AND json_extract(extra,'$.kind')='review'""",
                     (since.isoformat(), today.isoformat()), default=0) or 0
    return {"new_per_day": n_new / span, "minutes_per_day": (sum(minutes) / span) if minutes else 0.0,
            "reviews_per_day": reviews / span, "days_observed": span if first else 0, "active_days": len(minutes)}


def fast_fraction() -> float:
    """Olgun kartlarda doğru cevapların 'hızlı' olma oranı (doğru ve hızlı tanıma için)."""
    rows = db.q("""SELECT json_extract(extra,'$.speed') sp FROM events WHERE correct=1 AND rating IS NOT NULL
                   AND stage_before>=4 AND day>=?""", ((config.study_day() - timedelta(days=14)).isoformat(),))
    if len(rows) < 30:
        return 0.9
    fast = sum(1 for r in rows if r["sp"] in ("çok hızlı", "hızlı", "normal"))
    return fast / len(rows)


def compute(force: bool = False) -> dict:
    with _lock:
        hit = _cache.get("p")
        if hit and not force and time.time() - hit[0] < TTL:
            return hit[1]
    today = config.study_day()
    cal = planner.calendar(today)
    st = planner.state_arrays(today)
    cst = planner.costs()
    retention = float(db.get_setting("desired_retention", 0.9))
    target = float(db.get_setting("target_recall", 0.95))
    total_words = len(st["S"]) + st["n_new"]
    out: dict = {"day": today.isoformat(), "target": target, "total_words": total_words, "H": cal["H"]}
    if cal["H"] <= 0:
        r_now = _current_recall(st)
        out.update({"pace": {"mean": r_now}, "plan": {"mean": r_now}, "history": history()})
        return out
    plan = planner.today_plan()
    # plan senaryosu
    ch = planner.choose_rate(cal, st, cst, retention)
    res_plan = ch["res"]
    # tempo senaryosu
    pc = pace()
    if pc["days_observed"] >= 3:
        rate_new = pc["new_per_day"]
        sched = np.zeros(cal["H"], dtype=int)
        acc = 0.0
        remaining = st["n_new"]
        for d in range(cal["final_start"]):
            acc += rate_new
            k = int(acc)
            acc -= k
            k = min(k, remaining)
            sched[d] = k
            remaining -= k
        cap_val = max(10.0, pc["minutes_per_day"] * 60.0 / max(cst["sec_per_review"], 1.0))
        capacity = np.full(cal["H"], cap_val)
        inp = simcore.SimInput(H=cal["H"], final_days=cal["final_days"], params=C.active_params(),
                               desired_retention=retention, S=st["S"], D=st["D"], last=st["last"], due=st["due"],
                               n_new=st["n_new"], new_schedule=sched, p_known_new=st["p_known"], capacity=capacity,
                               first_probs=planner.first_probs(), runs=16, seed=5)
        res_pace = simcore.run(inp)
        pace_label = "son 7 günün temposu"
        finish = _finish_date(today, cal, st["n_new"], rate_new)
    else:
        res_pace = res_plan
        pace_label = "veri yetersiz (plan varsayıldı)"
        finish = plan.get("finish_new_by")
    ff = fast_fraction()
    learned = int(db.val("SELECT COUNT(*) FROM cards c JOIN words w ON w.id=c.word_id WHERE w.status='active' AND c.stage>=6",
                         default=0))
    started = int(db.val("SELECT COUNT(*) FROM cards c JOIN words w ON w.id=c.word_id WHERE w.status='active' AND c.introduced_at IS NOT NULL",
                         default=0))
    out.update({
        "pace": {"mean": float(res_pace.r_exam_mean), "p10": float(np.quantile(res_pace.r_exam_runs, 0.1)),
                 "p90": float(np.quantile(res_pace.r_exam_runs, 0.9)), "label": pace_label,
                 "fast_mean": float(res_pace.r_exam_mean) * ff, "new_per_day": pc["new_per_day"],
                 "minutes_per_day": pc["minutes_per_day"], "finish_date": finish},
        "plan": {"mean": float(res_plan.r_exam_mean), "fast_mean": float(res_plan.r_exam_mean) * ff,
                 "feasible": ch["feasible"]},
        "fast_fraction": ff, "learned": learned, "started": started,
        "final_start": (today + timedelta(days=cal["final_start"])).isoformat(),
        "exam_date": cal["exam"].isoformat(),
        "card_r": res_pace.r_exam_card.tolist(), "runs": res_pace.r_exam_runs.tolist(), "ids": st["ids"],
        "card_r_plan": res_plan.r_exam_card.tolist(),
        "card_r_runs_sd": float(np.std(res_pace.r_exam_runs)),
    })
    out["history"] = save_history(out)
    out["message"] = (f"Bu tempoyla sınav günü listenin %{out['pace']['mean'] * 100:.0f}'ini hatırlayacaksın, "
                      f"hedef %{target * 100:.0f}.")
    with _lock:
        _cache["p"] = (time.time(), out)
    return out


def _finish_date(today: date, cal: dict, n_new: int, rate: float) -> str | None:
    if n_new <= 0:
        return None
    if rate <= 0.05:
        return "—"
    days = 0
    left = n_new
    d = 0
    while left > 0 and d < 400:
        dd = today + timedelta(days=d)
        if dd.weekday() != cal["weekly_day"]:
            left -= rate
        d += 1
    return (today + timedelta(days=d - 1)).isoformat()


def _current_recall(st: dict) -> float:
    if not len(st["S"]):
        return 0.0
    from .fsrs_engine import r_at_days
    r = r_at_days(C.active_params(), st["S"], -st["last"])
    return float(np.sum(r) / (len(st["S"]) + st["n_new"]))


def save_history(out: dict) -> list[dict]:
    data = {"pace": out["pace"]["mean"], "plan": out["plan"]["mean"], "learned": out.get("learned"),
            "started": out.get("started")}
    db.x("INSERT INTO projections(day, computed_at, data) VALUES(?,?,?) ON CONFLICT(day) DO UPDATE SET "
         "computed_at=excluded.computed_at, data=excluded.data",
         (out["day"], config.iso(config.now_utc()), db.jdump(data)))
    return history()


def history() -> list[dict]:
    rows = db.q("SELECT day, data FROM projections ORDER BY day")
    return [{"day": r["day"], **db.jload(r["data"], {})} for r in rows]
