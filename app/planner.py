"""Günlük plan, sınav tarihine duyarlı yeni kelime dağılımı, tekrar çığı koruması, gerçekçilik kontrolü.

- Kalan yeni kelimeler, kalan öğrenme günlerine (son pencere hariç) ve o günün ayrılan süresine göre bölünür.
- Haftalık tekrar gününde yeni kelime yok/az (ayarlanabilir); o gün YDS tarzı karışık test.
- Son `final_days` gün: yeni kelime yok; tüm listenin hızlı turları + zayıf kelimeler.
- Tekrar yükü günlük bütçeyi aşarsa yeni kotası otomatik düşer; aşan tekrarlar risk sırasıyla ertesi güne kayar.
- İleriye dönük yük, vektörel FSRS simülasyonuyla (simcore) hesaplanır.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np

from . import cards as C
from . import config, db, simcore

# Seviye testi yoksa B1 öğrencinin listedeki kelimeyi zaten bilme olasılığı (xlsx 'Bilmeme' varsayımından, temkinli)
CEFR_KNOWN = {"B1": 0.75, "B2": 0.45, "C1": 0.2, "C2": 0.1, None: 0.25}
PRIOR_SEC_PER_ITEM = 9.0
PRIOR_ANSWERS_PER_NEW = 10.0  # tanıtım + 3 öğretme katmanı + 4 sınama + pekiştirme + ~1 hata (ölçüldükçe kişiselleşir)
PRIOR_REVIEW_FACTOR = 1.15
SWEEP_FACTOR = 0.6
WEEKLY_TEST_ITEMS = 40


# ---------------------------------------------------------------- maliyetler
def costs(days: int = 14) -> dict:
    since = (config.study_day() - timedelta(days=days)).isoformat()
    act_ms = db.val("SELECT SUM(active_ms) FROM activity WHERE day>=?", (since,), default=0) or 0
    n_items = db.val("SELECT COUNT(*) FROM events WHERE day>=? AND result!='override'", (since,), default=0) or 0
    k = 80.0
    emp = (act_ms / 1000.0 / n_items) if n_items >= 10 and act_ms > 0 else PRIOR_SEC_PER_ITEM
    emp = min(max(emp, 3.0), 40.0)
    sec_item = (k * PRIOR_SEC_PER_ITEM + n_items * emp) / (k + n_items)
    rows = db.q("""SELECT e.word_id, COUNT(*) n FROM events e JOIN cards c ON c.word_id=e.word_id
                   WHERE e.day>=? AND e.mode='learn' AND c.introduced_at IS NOT NULL GROUP BY e.word_id""", (since,))
    nw = len(rows)
    apn_emp = (sum(r["n"] for r in rows) / nw) if nw else PRIOR_ANSWERS_PER_NEW
    apn = (30 * PRIOR_ANSWERS_PER_NEW + nw * apn_emp) / (30 + nw)
    n_rev = db.val("SELECT COUNT(*) FROM events WHERE day>=? AND mode IN ('daily','review','hard','final') "
                   "AND json_extract(extra,'$.kind')='review'", (since,), default=0) or 0
    n_rl = db.val("SELECT COUNT(*) FROM events WHERE day>=? AND json_extract(extra,'$.kind')='relearn'",
                  (since,), default=0) or 0
    rf_emp = (1 + n_rl / n_rev) if n_rev >= 20 else PRIOR_REVIEW_FACTOR
    rf = (50 * PRIOR_REVIEW_FACTOR + n_rev * rf_emp) / (50 + n_rev)
    return {"sec_per_item": round(sec_item, 2), "answers_per_new": round(apn, 2), "review_factor": round(rf, 3),
            "sec_per_review": round(sec_item * rf, 2), "min_per_new": round(sec_item * apn / 60.0, 3),
            "sec_per_sweep": round(sec_item * SWEEP_FACTOR, 2), "n_items": n_items, "n_new_measured": nw}


# ---------------------------------------------------------------- takvim
def budget_minutes(d: date) -> float:
    if d.weekday() >= 5:
        return float(db.get_setting("weekend_minutes", 90))
    return float(db.get_setting("weekday_minutes", 60))


def calendar(today: date) -> dict:
    exam = date.fromisoformat(db.get_setting("exam_date"))
    final_days = int(db.get_setting("final_days", 7))
    H = max(0, (exam - today).days)
    final_start = max(0, H - final_days)
    wday = int(db.get_setting("weekly_review_day", 6))
    ratio = float(db.get_setting("weekly_review_new_ratio", 0.0))
    budgets = np.array([budget_minutes(today + timedelta(days=d)) for d in range(max(H, 1))])
    weights = np.zeros(max(H, 1))
    mean_b = budgets[:final_start].mean() if final_start > 0 else 1.0
    today_weekly_active = weekly_day_active(today)
    for d in range(final_start):
        dd = today + timedelta(days=d)
        w = budgets[d] / mean_b
        if dd.weekday() == wday and (d > 0 or today_weekly_active):
            w *= ratio
        weights[d] = w
    return {"exam": exam, "H": H, "final_start": final_start, "final_days": final_days, "budgets": budgets,
            "weights": weights, "weekly_day": wday}


def weekly_day_active(today: date) -> bool:
    """Haftalık tekrar günü ancak geçen hafta yeterince kelime öğrenildiyse (≥50) uygulanır
    (ör. ilk gün pazara denk gelirse yeni kelimeyle başlanır)."""
    if today.weekday() != int(db.get_setting("weekly_review_day", 6)):
        return False
    n = db.val("SELECT COUNT(*) FROM cards WHERE introduced_at>=?",
               (config.iso(config.day_start_utc(today - timedelta(days=7))),), default=0) or 0
    return n >= 50


# ---------------------------------------------------------------- durum
def state_arrays(today: date) -> dict:
    rows = db.q("""SELECT c.word_id, c.state, c.stability, c.difficulty, c.last_review, c.due_day, c.known_status, w.level
                   FROM cards c JOIN words w ON w.id=c.word_id WHERE w.status='active'
                   ORDER BY w.order_index""")
    S, D, last, due = [], [], [], []
    ids_old, ids_new = [], []
    n_new = 0
    pk = []
    tiers = placement_known_rates()
    tier_of = word_tiers() if tiers else {}
    for r in rows:
        if r["state"] and r["stability"]:
            S.append(r["stability"])
            D.append(r["difficulty"] or 5.0)
            lr = config.study_day(config.parse_iso(r["last_review"])) if r["last_review"] else today
            last.append((lr - today).days)
            dd = date.fromisoformat(r["due_day"]) if r["due_day"] else today
            due.append((dd - today).days)
            ids_old.append(r["word_id"])
        else:
            n_new += 1
            ids_new.append(r["word_id"])
            if r["known_status"] == "probable":
                pk.append(0.8)
            elif r["known_status"] == "failed":
                pk.append(0.1)
            else:
                prior = CEFR_KNOWN.get(r.get("level"), CEFR_KNOWN[None])
                pk.append(tiers.get(tier_of.get(r["word_id"]), prior) if tiers else prior)
    return {"S": np.array(S, dtype=float), "D": np.array(D, dtype=float), "last": np.array(last, dtype=float),
            "due": np.array(due, dtype=float), "n_new": n_new, "p_known": np.array(pk, dtype=float),
            "ids": ids_old + ids_new}


def placement_known_rates() -> dict:
    row = db.q1("SELECT result FROM placement WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 1")
    if not row:
        return {}
    res = db.jload(row["result"], {})
    return {t["tier"]: t["known_rate"] for t in res.get("tiers", []) if t.get("known_rate") is not None}


_tier_cache: dict | None = None


def word_tiers() -> dict[int, str]:
    global _tier_cache
    if _tier_cache is None:
        from . import placement
        _tier_cache = placement.tier_map()
    return _tier_cache


def first_probs() -> tuple:
    """İlk öğrenme oturumundaki hata dağılımı (kişisel)."""
    rows = db.q("""SELECT word_id, SUM(CASE WHEN correct=0 THEN 1 ELSE 0 END) err FROM events
                   WHERE mode='learn' AND exercise!='intro' AND day >= ? GROUP BY word_id""",
                ((config.study_day() - timedelta(days=21)).isoformat(),))
    n = len(rows)
    prior = np.array([0.62, 0.25, 0.13])
    if n < 15:
        return tuple(prior)
    c0 = sum(1 for r in rows if (r["err"] or 0) == 0)
    c1 = sum(1 for r in rows if (r["err"] or 0) == 1)
    c2 = n - c0 - c1
    emp = np.array([c0, c1, c2], dtype=float) / n
    w = n / (n + 40)
    p = (1 - w) * prior + w * emp
    return tuple(p / p.sum())


# ---------------------------------------------------------------- simülasyon tabanlı seçim
def schedule_for(rate: float, cal: dict, n_new: int) -> np.ndarray:
    H = cal["H"]
    sched = np.zeros(max(H, 1), dtype=int)
    remaining = n_new
    acc = 0.0
    for d in range(cal["final_start"]):
        acc += rate * cal["weights"][d]
        take = int(math.floor(acc))
        acc -= take
        take = min(take, remaining)
        sched[d] = take
        remaining -= take
    return sched


def load_minutes(res: simcore.SimResult, sched: np.ndarray, cst: dict, cal: dict) -> np.ndarray:
    H = cal["H"]
    mins = (res.reviews[:H] * cst["sec_per_review"] / 60.0 + sched[:H] * cst["min_per_new"]
            + res.sweeps[:H] * cst["sec_per_sweep"] / 60.0)
    today = config.study_day()
    for d in range(min(H, cal["final_start"])):
        if (today + timedelta(days=d)).weekday() == cal["weekly_day"]:
            mins[d] += WEEKLY_TEST_ITEMS * cst["sec_per_item"] / 60.0
    return mins


def simulate(rate: float, cal: dict, st: dict, cst: dict, retention: float, runs: int = 10, seed: int = 3,
             capacity: np.ndarray | None = None) -> tuple[simcore.SimResult, np.ndarray, np.ndarray]:
    sched = schedule_for(rate, cal, st["n_new"])
    inp = simcore.SimInput(H=cal["H"], final_days=cal["final_days"], params=C.active_params(),
                           desired_retention=retention, S=st["S"], D=st["D"], last=st["last"], due=st["due"],
                           n_new=st["n_new"], new_schedule=sched, p_known_new=st["p_known"], capacity=capacity,
                           first_probs=first_probs(), runs=runs, seed=seed)
    res = simcore.run(inp)
    mins = load_minutes(res, sched, cst, cal)
    return res, sched, mins


def choose_rate(cal: dict, st: dict, cst: dict, retention: float) -> dict:
    """Bitirme hızı (tampon 2 gün) ve bütçeye sığan en yüksek hız."""
    n_new = st["n_new"]
    wsum_total = float(cal["weights"][: cal["final_start"]].sum())
    buffer_w = float(cal["weights"][max(0, cal["final_start"] - 2): cal["final_start"]].sum())
    wsum = max(1e-6, wsum_total - buffer_w if wsum_total - buffer_w > wsum_total * 0.6 else wsum_total)
    rate_finish = (n_new / wsum) if n_new else 0.0
    budgets = cal["budgets"][: cal["H"]]
    if cal["H"] <= 0:
        return {"rate": 0.0, "feasible": True, "overload": 0.0}
    res_f, sched_f, mins_f = simulate(rate_finish, cal, st, cst, retention)
    over_f = float(np.max(mins_f / np.maximum(budgets, 1))) if len(mins_f) else 0.0
    out = {"rate_finish": rate_finish, "overload_finish": over_f, "mins_finish": mins_f, "res_finish": res_f,
           "sched_finish": sched_f}
    if over_f <= 1.05 or n_new == 0:
        out.update({"rate": rate_finish, "feasible": True, "overload": over_f, "res": res_f, "sched": sched_f,
                    "mins": mins_f})
        return out
    lo, hi = 0.0, rate_finish
    best = (0.0, None, None, None)
    for _ in range(7):
        mid = (lo + hi) / 2
        res, sched, mins = simulate(mid, cal, st, cst, retention)
        over = float(np.max(mins / np.maximum(budgets, 1)))
        if over <= 1.0:
            lo = mid
            best = (mid, res, sched, mins)
        else:
            hi = mid
    if best[1] is None:
        res, sched, mins = simulate(0.0, cal, st, cst, retention)
        best = (0.0, res, sched, mins)
    out.update({"rate": best[0], "feasible": False, "overload": float(np.max(best[3] / np.maximum(budgets, 1))),
                "res": best[1], "sched": best[2], "mins": best[3]})
    return out


# ---------------------------------------------------------------- günün planı
def reviews_due_today(today: date) -> int:
    exam = db.get_setting("exam_date")
    return int(db.val("""SELECT COUNT(*) FROM cards c JOIN words w ON w.id=c.word_id WHERE w.status='active'
                         AND c.state IN (2,3) AND c.due_day<=? AND c.due_day<?""",
                      (today.isoformat(), exam), default=0))


def today_plan(recompute: bool = False) -> dict:
    today = config.study_day()
    key = today.isoformat()
    if not recompute:
        row = db.q1("SELECT plan, computed_at FROM daily_plans WHERE day=?", (key,))
        if row:
            p = db.jload(row["plan"], {})
            if p:
                return p
    p = compute_plan(today)
    db.x("INSERT INTO daily_plans(day, computed_at, plan) VALUES(?,?,?) ON CONFLICT(day) DO UPDATE SET "
         "computed_at=excluded.computed_at, plan=excluded.plan", (key, config.iso(config.now_utc()), db.jdump(p)))
    return p


def compute_plan(today: date) -> dict:
    cal = calendar(today)
    cst = costs()
    st = state_arrays(today)
    retention = float(db.get_setting("desired_retention", 0.9))
    H = cal["H"]
    budget = budget_minutes(today)
    due_now = reviews_due_today(today)
    n_verify = int(db.val("SELECT COUNT(*) FROM cards WHERE known_status='probable' AND state=0", default=0))
    plan: dict = {"day": today.isoformat(), "days_to_exam": H, "budget": budget, "exam_date": cal["exam"].isoformat(),
                  "final_start": (today + timedelta(days=cal["final_start"])).isoformat(), "costs": cst,
                  "desired_retention": retention, "remaining_new": st["n_new"], "verify_pending": n_verify,
                  "rationale": [], "computed_at": config.iso(config.now_utc())}
    if H <= 0:
        plan.update({"phase": "after_exam", "reviews_due": due_now, "reviews_planned": due_now,
                     "review_cap": None, "new_planned": 0, "minutes": round(due_now * cst["sec_per_review"] / 60),
                     "feasible": True})
        plan["rationale"].append("Sınav tarihi geçti; yalnızca vadesi gelen tekrarlar. Ayarlardan yeni sınav tarihi girebilirsin.")
        return plan
    is_final = cal["final_start"] <= 0
    is_weekly = weekly_day_active(today) and not is_final
    ch = choose_rate(cal, st, cst, retention)
    sched = ch["sched"]
    mins = ch["mins"]
    rate = ch["rate"]
    override = db.get_setting("new_per_day_override")
    new_today = int(sched[0]) if len(sched) else 0
    if override and not is_final:
        new_today = int(override) if not is_weekly else int(round(int(override) * cal["weights"][0]))
        plan["rationale"].append(f"Yeni kelime sayısı ayarlardan elle {override}/gün olarak sabitlendi.")
    review_min = due_now * cst["sec_per_review"] / 60.0
    review_cap = None
    # tekrar çığı koruması
    if review_min > budget:
        review_cap = int(budget * 60 / cst["sec_per_review"])
        plan["rationale"].append(
            f"Vadesi gelen {due_now} tekrar bugünkü {budget:.0f} dk'yı aşıyor; en riskli {review_cap} tanesi bugün, "
            f"kalanı risk sırasıyla sonraki günlere yayıldı. Yeni kelime bugün yok.")
        new_today = 0
    elif review_min + new_today * cst["min_per_new"] > budget * 1.05 and not override:
        fit = max(0, int((budget - review_min) / cst["min_per_new"]))
        if fit < new_today:
            plan["rationale"].append(
                f"Tekrar yükü ({due_now} tekrar ≈ {review_min:.0f} dk) nedeniyle yeni kelime {new_today} → {fit} düşürüldü (tekrar çığı koruması).")
            new_today = fit
    sweep_target = 0
    weekly_items = 0
    if is_final:
        phase = "final"
        new_today = 0
        days_left = max(1, H)
        unswept = int(db.val("""SELECT COUNT(*) FROM cards c JOIN words w ON w.id=c.word_id WHERE w.status='active'
                                AND c.state>=1 AND (c.last_review IS NULL OR c.last_review < ?)
                                AND (c.due_day IS NULL OR c.due_day >= ?)""",
                             (config.iso(config.day_start_utc(today - timedelta(days=cal["final_days"] - H))),
                              cal["exam"].isoformat()), default=0))
        sweep_target = int(math.ceil(unswept / days_left))
        plan["rationale"].append(
            f"Son {cal['final_days']} gün: yeni kelime yok. Bugün vadesi gelen {due_now} tekrar + listenin hızlı turundan "
            f"{sweep_target} kelime (henüz bu hafta görülmemiş {unswept} kelime ÷ {days_left} gün).")
    elif is_weekly:
        phase = "weekly"
        weekly_items = WEEKLY_TEST_ITEMS
        plan["rationale"].append(
            f"Haftalık tekrar günü: yeni kelime {'yok' if new_today == 0 else str(new_today)}; vadesi gelen tekrarlar + "
            f"haftanın kelimeleri, zayıf ve eski kelimelerden {WEEKLY_TEST_ITEMS} soruluk YDS tarzı karışık test.")
    else:
        phase = "learning"
    learning_days = int(np.count_nonzero(cal["weights"][: cal["final_start"]] > 0))
    if phase == "learning" and st["n_new"]:
        plan["rationale"].insert(0,
            f"Kalan {st['n_new']} yeni kelime, sınava kadarki {learning_days} öğrenme gününe (son {cal['final_days']} gün ve "
            f"haftalık tekrar günleri hariç) ve ayırdığın süreye göre bölündü: bugün {new_today} yeni kelime.")
    reviews_planned = due_now if review_cap is None else review_cap
    sec_rev = cst["sec_per_review"] if phase != "final" else (cst["sec_per_review"] + cst["sec_per_sweep"]) / 2
    minutes = (reviews_planned * sec_rev / 60.0 + new_today * cst["min_per_new"]
               + sweep_target * cst["sec_per_sweep"] / 60.0 + weekly_items * cst["sec_per_item"] / 60.0
               + n_verify * 2 * cst["sec_per_item"] / 60.0 * (1 if phase != "final" else 0))
    res = ch["res"]
    proj_plan = float(res.r_exam_mean) if res is not None else None
    finish_day = None
    if len(sched) and sched.sum() >= st["n_new"] and st["n_new"]:
        last_nz = int(np.max(np.nonzero(sched)[0]))
        finish_day = (today + timedelta(days=last_nz)).isoformat()
    plan.update({
        "phase": phase, "reviews_due": due_now, "reviews_planned": reviews_planned, "review_cap": review_cap,
        "new_planned": int(new_today), "new_rate": round(rate, 1), "sweep_target": sweep_target,
        "weekly_test": is_weekly, "minutes": round(minutes), "feasible": bool(ch["feasible"]),
        "overload": round(float(ch["overload"]), 2), "projected_recall_plan": proj_plan,
        "finish_new_by": finish_day, "learning_days_left": learning_days,
        "forecast": {"minutes": [round(float(x), 1) for x in mins[:H]], "reviews": [round(float(x)) for x in res.reviews[:H]],
                     "new": [int(x) for x in sched[:H]], "sweeps": [round(float(x)) for x in res.sweeps[:H]],
                     "budgets": [float(b) for b in cal["budgets"][:H]]},
    })
    if not ch["feasible"]:
        plan["realism"] = realism(cal, st, cst, retention, ch)
        plan["rationale"].append(plan["realism"]["message"])
    else:
        peak = float(np.max(mins)) if len(mins) else 0
        plan["rationale"].append(
            f"Bu dağılımla en yoğun gün ≈ {peak:.0f} dk; plana uyarsan sınav günü tahmini hakimiyet %{(proj_plan or 0) * 100:.0f}.")
    return plan


def realism(cal: dict, st: dict, cst: dict, retention: float, ch: dict) -> dict:
    """Hedef mevcut süreyle tutmuyorsa açıkça söyle ve seçenek sun."""
    budgets = cal["budgets"][: cal["H"]]
    mins_f = ch["mins_finish"]
    ratio = float(np.max(mins_f / np.maximum(budgets, 1)))
    wk = float(db.get_setting("weekday_minutes", 60))
    we = float(db.get_setting("weekend_minutes", 90))
    need_wk = int(math.ceil(wk * ratio / 5.0) * 5)
    need_we = int(math.ceil(we * ratio / 5.0) * 5)
    fit_total = int(ch["sched"].sum()) if ch.get("sched") is not None else 0
    drop = max(0, st["n_new"] - fit_total)
    proj = float(ch["res"].r_exam_mean) if ch.get("res") is not None else None
    target = float(db.get_setting("target_recall", 0.95))
    msg = (f"Gerçekçilik kontrolü: mevcut süreyle ({wk:.0f}/{we:.0f} dk) {st['n_new']} kelimenin tamamı son haftadan önce "
           f"bitmiyor; en yoğun gün bütçenin %{ratio * 100:.0f}'i. Seçenekler: (1) süreyi hafta içi {need_wk}, hafta sonu "
           f"{need_we} dk'ya çıkar; (2) listeyi önceliklendir — en düşük öncelikli {drop} kelimeyi yedeğe al; "
           f"(3) hedef oranı %{target * 100:.0f} yerine %{(proj or 0) * 100:.0f} kabul et.")
    return {"message": msg, "need_weekday": need_wk, "need_weekend": need_we, "drop_words": drop,
            "projected_recall": proj, "overload": ratio}


def progress_today() -> dict:
    plan = today_plan()
    today = config.day_str()
    cst = plan.get("costs") or costs()
    rv = db.val("""SELECT COUNT(DISTINCT word_id) FROM events WHERE day=? AND rating IS NOT NULL
                   AND json_extract(extra,'$.kind') IN ('review')""", (today,), default=0) or 0
    nw = db.val("SELECT COUNT(*) FROM cards WHERE introduced_at>=?",
                (config.iso(config.day_start_utc(config.study_day())),), default=0) or 0
    sw = 0
    act = db.val("SELECT SUM(active_ms) FROM activity WHERE day=?", (today,), default=0) or 0
    planned = (plan.get("reviews_planned", 0) * cst["sec_per_review"] + plan.get("new_planned", 0) * cst["min_per_new"] * 60
               + plan.get("sweep_target", 0) * cst["sec_per_sweep"])
    done = (min(rv, plan.get("reviews_planned", 0) + plan.get("sweep_target", 0)) * cst["sec_per_review"]
            + min(nw, plan.get("new_planned", 0)) * cst["min_per_new"] * 60)
    frac = (done / planned) if planned > 0 else (1.0 if act > 0 else 0.0)
    remaining_min = max(0.0, (planned - done) / 60.0)
    return {"reviews_done": rv, "new_done": nw, "active_min": round(act / 60000.0, 1), "fraction": min(1.0, frac),
            "remaining_min": round(remaining_min), "planned_min": plan.get("minutes"), "sweeps_done": sw}


def tomorrow_load_if_skipped() -> dict:
    """Bugünün kalanını yapmazsan yarınki yük (dk)."""
    plan = today_plan()
    prog = progress_today()
    fc = plan.get("forecast") or {}
    mins = fc.get("minutes") or []
    tomorrow = mins[1] if len(mins) > 1 else (mins[0] if mins else 0)
    cst = plan.get("costs") or costs()
    left_rev = max(0, plan.get("reviews_planned", 0) - prog["reviews_done"])
    left_new = max(0, plan.get("new_planned", 0) - prog["new_done"])
    ld = max(1, plan.get("learning_days_left", 1) - 1)
    extra = left_rev * cst["sec_per_review"] / 60.0 + (left_new / ld) * cst["min_per_new"]
    return {"tomorrow_planned": round(tomorrow), "tomorrow_if_skip": round(tomorrow + extra),
            "left_reviews": left_rev, "left_new": left_new}


def choose_retention() -> dict | None:
    """Haftalık: hedef hatırlama oranını simülasyonla seç (sınav günü hatırlama en yüksek, bütçe aşılmadan)."""
    today = config.study_day()
    cal = calendar(today)
    if cal["H"] <= cal["final_days"]:
        return None
    st = state_arrays(today)
    cst = costs()
    cur = float(db.get_setting("desired_retention", 0.9))
    results = []
    for r in (0.85, 0.88, 0.90, 0.92, 0.94):
        ch = choose_rate(cal, st, cst, r)
        results.append({"r": r, "feasible": ch["feasible"], "overload": ch["overload"],
                        "recall": float(ch["res"].r_exam_mean), "rate": ch["rate"]})
    feas = [x for x in results if x["feasible"]]
    best = max(feas, key=lambda x: x["recall"]) if feas else min(results, key=lambda x: x["overload"])
    out = {"current": cur, "best": best, "results": results}
    if abs(best["r"] - cur) >= 0.015:
        cur_res = next((x for x in results if abs(x["r"] - cur) < 1e-6), None)
        if cur_res is None or best["recall"] - cur_res["recall"] >= 0.005 or (not cur_res["feasible"] and best["feasible"]):
            db.set_setting("desired_retention", best["r"])
            from . import strategy
            reason = (f"Hedef hatırlama oranı %{cur * 100:.0f} → %{best['r'] * 100:.0f}: simülasyonda sınav günü hatırlama "
                      f"%{best['recall'] * 100:.1f}" + (f" (mevcut ayarla %{cur_res['recall'] * 100:.1f})" if cur_res else "")
                      + f", günlük yük bütçenin %{best['overload'] * 100:.0f}'i.")
            strategy.log_change("desired_retention", cur, best["r"], reason, out)
            out["changed"] = True
    return out
