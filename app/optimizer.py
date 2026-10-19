"""FSRS-6 parametrelerinin kişisel kayıtlarla optimizasyonu (numpy; torch gerektirmez).

Kayıp: gün aşırı tekrarlarda (geçen süre ≥ 1 gün) tahmin edilen hatırlanabilirlik R ile gerçek sonuç
(puan > 1) arasındaki ikili çapraz entropi. Normalize uzayda Adam + merkezi sonlu farklar, varsayılana
L2 düzenlileştirme. Zaman bazlı doğrulama: son %20 tekrarda kayıp mevcut parametrelerden ≥%1 iyiyse benimsenir.
"""
from __future__ import annotations

from datetime import datetime

import numpy as np
from fsrs.scheduler import DEFAULT_PARAMETERS, LOWER_BOUNDS_PARAMETERS, UPPER_BOUNDS_PARAMETERS

from . import config, db
from .fsrs_engine import VecFSRS

LB = np.array(LOWER_BOUNDS_PARAMETERS, dtype=float)
UB = np.array(UPPER_BOUNDS_PARAMETERS, dtype=float)
MIN_TERMS = 400
MIN_WORDS = 100


def load_sequences() -> dict:
    rows = db.q("""SELECT word_id, ts, rating, extra FROM events WHERE rating IS NOT NULL ORDER BY word_id, ts, id""")
    seqs: dict[int, list[tuple[datetime, int]]] = {}
    for r in rows:
        ex = db.jload(r["extra"], {}) or {}
        if ex.get("overridden"):
            continue
        seqs.setdefault(r["word_id"], []).append((config.parse_iso(r["ts"]), int(r["rating"])))
    seqs = {k: v for k, v in seqs.items() if len(v) >= 2}
    if not seqs:
        return {"N": 0}
    N = len(seqs)
    L = max(len(v) for v in seqs.values())
    G = np.zeros((N, L), dtype=int)
    E = np.zeros((N, L), dtype=float)
    T = np.zeros((N, L), dtype=float)
    M = np.zeros((N, L), dtype=bool)
    for i, (wid, seq) in enumerate(seqs.items()):
        prev = None
        for j, (t, g) in enumerate(seq):
            G[i, j] = g
            M[i, j] = True
            T[i, j] = t.timestamp()
            if prev is not None:
                E[i, j] = (t - prev).days
            prev = t
    return {"N": N, "L": L, "G": G, "E": E, "T": T, "M": M}


def forward_loss(w: np.ndarray, data: dict, cutoff: float | None = None, part: str = "all") -> tuple[float, int]:
    vf = VecFSRS(w)
    G, E, T, M = data["G"], data["E"], data["T"], data["M"]
    N, L = G.shape
    S = vf.init_s(np.maximum(G[:, 0], 1))
    D = vf.init_d(np.maximum(G[:, 0], 1))
    tot = 0.0
    n = 0
    for j in range(1, L):
        m = M[:, j]
        if not m.any():
            break
        g = np.where(m, G[:, j], 3)
        el = E[:, j]
        pred = m & (el >= 1)
        if cutoff is not None:
            pred = pred & ((T[:, j] < cutoff) if part == "train" else (T[:, j] >= cutoff))
        if pred.any():
            r = np.clip(vf.r(S, el), 1e-4, 1 - 1e-4)
            y = (g > 1).astype(float)
            ll = -(y * np.log(r) + (1 - y) * np.log(1 - r))
            tot += float(ll[pred].sum())
            n += int(pred.sum())
        S2, D2 = vf.step(S, D, el, g, np.zeros(N, dtype=bool))
        S = np.where(m, S2, S)
        D = np.where(m, D2, D)
    return (tot / n if n else float("nan")), n


def optimize(init: list[float] | None = None, steps: int = 120, lr: float = 0.02, seed: int = 0) -> dict:
    data = load_sequences()
    if data.get("N", 0) == 0:
        return {"ok": False, "reason": "veri yok"}
    ts = data["T"][data["M"] & (data["E"] >= 1)]
    n_terms = int(len(ts))
    if n_terms < MIN_TERMS or data["N"] < MIN_WORDS:
        return {"ok": False, "reason": f"yetersiz veri ({n_terms} gün aşırı tekrar, {data['N']} kelime; "
                                       f"en az {MIN_TERMS}/{MIN_WORDS} gerekli)"}
    cutoff = float(np.quantile(ts, 0.8))
    w0 = np.array(init if init else DEFAULT_PARAMETERS, dtype=float)
    prior = np.array(DEFAULT_PARAMETERS, dtype=float)
    span = UB - LB
    u = (w0 - LB) / span
    u_prior = (prior - LB) / span
    lam = 3.0 / max(1.0, n_terms ** 0.5)

    def objective(uu):
        w = LB + np.clip(uu, 0, 1) * span
        loss, _ = forward_loss(w, data, cutoff, "train")
        return loss + lam * float(np.sum(((uu - u_prior) / 0.1) ** 2))

    m = np.zeros_like(u)
    v = np.zeros_like(u)
    b1, b2, eps = 0.9, 0.999, 1e-8
    best_u, best_f = u.copy(), objective(u)
    for t in range(1, steps + 1):
        grad = np.zeros_like(u)
        for k in range(len(u)):
            h = 1e-3
            up, dn = u.copy(), u.copy()
            up[k] = min(1.0, u[k] + h)
            dn[k] = max(0.0, u[k] - h)
            grad[k] = (objective(up) - objective(dn)) / max(1e-9, (up[k] - dn[k]))
        m = b1 * m + (1 - b1) * grad
        v = b2 * v + (1 - b2) * grad ** 2
        mh = m / (1 - b1 ** t)
        vh = v / (1 - b2 ** t)
        u = np.clip(u - lr * mh / (np.sqrt(vh) + eps), 0, 1)
        f = objective(u)
        if f < best_f - 1e-6:
            best_f, best_u = f, u.copy()
    w_new = LB + best_u * span
    val_cur, n_val = forward_loss(w0, data, cutoff, "val")
    val_new, _ = forward_loss(w_new, data, cutoff, "val")
    tr_cur, n_tr = forward_loss(w0, data, cutoff, "train")
    tr_new, _ = forward_loss(w_new, data, cutoff, "train")
    return {"ok": True, "params": [float(x) for x in w_new], "n_terms": n_terms, "n_words": data["N"],
            "val_loss_current": val_cur, "val_loss_new": val_new, "n_val": n_val,
            "train_loss_current": tr_cur, "train_loss_new": tr_new, "n_train": n_tr}


def weekly() -> dict:
    from . import cards, strategy
    cur = cards.active_params()
    res = optimize(cur)
    if not res.get("ok"):
        return res
    better = (res["n_val"] >= 100 and np.isfinite(res["val_loss_new"]) and
              res["val_loss_new"] < res["val_loss_current"] * 0.99)
    res["accepted"] = bool(better)
    if better:
        prev = db.q1("SELECT id FROM fsrs_params WHERE active=1 ORDER BY id DESC LIMIT 1")
        db.x("UPDATE fsrs_params SET active=0")
        pid = db.x("""INSERT INTO fsrs_params(ts, params, n_reviews, loss_before, loss_after, active, note)
                      VALUES(?,?,?,?,?,1,?)""",
                   (config.iso(config.now_utc()), db.jdump(res["params"]), res["n_terms"], res["val_loss_current"],
                    res["val_loss_new"], "haftalık optimizasyon"))
        n = cards.reschedule_all(res["params"])
        reason = (f"FSRS parametreleri senin {res['n_terms']} gün aşırı tekrarınla yeniden optimize edildi: "
                  f"doğrulama kaybı {res['val_loss_current']:.4f} → {res['val_loss_new']:.4f} "
                  f"(%{(1 - res['val_loss_new'] / res['val_loss_current']) * 100:.1f} iyileşme); {n} kartın vadesi güncellendi.")
        strategy.log_change("fsrs_params", "önceki", "kişisel", reason,
                            {k: v for k, v in res.items() if k != "params"} | {"prev_id": prev["id"] if prev else None},
                            experiment_id=prev["id"] if prev else None)
    else:
        db.x("""INSERT INTO fsrs_params(ts, params, n_reviews, loss_before, loss_after, active, note)
                VALUES(?,?,?,?,?,0,?)""",
             (config.iso(config.now_utc()), db.jdump(res["params"]), res["n_terms"], res["val_loss_current"],
              res["val_loss_new"], "reddedildi: doğrulamada iyileşme yok"))
    return {k: v for k, v in res.items() if k != "params"}
