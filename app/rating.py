"""Cevaptan ve süreden otomatik FSRS puanı + kişisel hız eşiklerinin kalibrasyonu.

Kurallar (kullanıcı tanımı):
  yanlış                          -> Again (1)
  doğru ama yavaş ya da ipuçlu    -> Hard  (2)
  doğru ve hızlı                  -> Good  (3)
  zor modda çok hızlı             -> Easy  (4)
Yazım hatası (1-2 harf) yanlış sayılmaz; en fazla Good alır.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from . import db

# Zor mod: üretim/bağlam gerektiren alıştırmalar
HARD_MODE = {"typing", "cloze", "synonym", "distinguish", "osym"}

# Ön değerler (ms): (çok hızlı, hızlı-eşiği, yavaş-eşiği) — veri biriktikçe kişisel değerlerle karışır
PRIORS: dict[str, tuple[int, int, int]] = {
    "mcq_en_tr": (1300, 2600, 6000),
    "listen": (2000, 3600, 8000),       # sesin çalınma süresi dahil
    "mcq_tr_en": (1500, 3000, 7000),
    "context": (2500, 5000, 11000),
    "tiles": (1500, 3000, 7000),       # ilk tuşa kadar
    "typing": (1500, 3200, 8000),      # ilk tuşa kadar
    "cloze": (2500, 5000, 12000),      # okuma süresi düşülmüş
    "osym": (3000, 6000, 15000),
    "synonym": (1800, 3500, 8000),
    "distinguish": (1500, 3000, 7000),
    "speed": (1000, 2000, 4500),
    "placement": (1300, 2600, 6000),
    "verify": (1500, 3000, 7000),
    "look_write": (1500, 3200, 9000),  # gizlendikten sonra ilk tuşa kadar
    "syn_pick": (2000, 4000, 9000),    # eş anlamlıları okuma dahil
    "match": (8000, 15000, 30000),     # tüm çiftler
}
K_PRIOR = 20  # öncelin "örnek sayısı" ağırlığı

_cache: dict[str, tuple[float, dict]] = {}


@dataclass
class Thresholds:
    very_fast: float
    fast: float
    slow: float
    n: int


def latency_for(exercise: str, first_key_ms: int | None, total_ms: int | None, n_words: int = 0) -> float:
    """Hatırlama süresi: üretim alıştırmalarında ilk tuşa kadar, seçmelilerde cevap süresi.
    Cümleli alıştırmalarda okuma süresi (kelime başı ~220 ms) düşülür."""
    if exercise in ("typing", "tiles"):
        v = first_key_ms if first_key_ms is not None else total_ms
    else:
        v = total_ms if total_ms is not None else first_key_ms
    v = float(v or 0)
    if exercise in ("cloze", "context", "osym") and n_words:
        v = max(400.0, v - 220.0 * n_words)
    return v


def _quantile(xs: list[float], q: float) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    pos = (len(xs) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def thresholds(exercise: str) -> Thresholds:
    now = time.time()
    hit = _cache.get(exercise)
    if hit and now - hit[0] < 120:
        return hit[1]["t"]
    base = exercise if exercise in PRIORS else "mcq_en_tr"
    pvf, pf, ps = PRIORS[base]
    custom = db.get_setting("speed_priors") or {}
    if isinstance(custom, dict) and base in custom:
        try:
            pvf, pf, ps = custom[base]
        except Exception:
            pass
    rows = db.q(
        "SELECT extra FROM events WHERE exercise=? AND correct=1 AND hints=0 AND result='correct' "
        "ORDER BY id DESC LIMIT 300", (base,))
    lat = []
    for r in rows:
        ex = db.jload(r["extra"], {})
        if ex and ex.get("latency") is not None:
            lat.append(float(ex["latency"]))
    n = len(lat)
    if n >= 5:
        evf, ef, es = _quantile(lat, 0.15), _quantile(lat, 0.5), _quantile(lat, 0.85)
        w = n / (n + K_PRIOR)
        vf = (1 - w) * pvf + w * evf
        f = (1 - w) * pf + w * ef
        s = (1 - w) * ps + w * max(es, ef * 1.6)
    else:
        vf, f, s = pvf, pf, ps
    t = Thresholds(very_fast=vf, fast=f, slow=s, n=n)
    _cache[exercise] = (now, {"t": t})
    return t


def invalidate_cache() -> None:
    _cache.clear()


def auto_rating(exercise: str, correct: bool, result: str, latency: float, hints: int,
                hard_mode_bonus: bool = True) -> tuple[int, str]:
    """(rating, hız sınıfı) döndürür. hız sınıfı: 'çok hızlı' | 'hızlı' | 'normal' | 'yavaş'"""
    th = thresholds(exercise)
    if latency <= th.very_fast:
        speed = "çok hızlı"
    elif latency <= th.fast:
        speed = "hızlı"
    elif latency <= th.slow:
        speed = "normal"
    else:
        speed = "yavaş"
    if not correct:
        return 1, speed
    if hints > 0 or speed == "yavaş":
        return 2, speed
    if result in ("typo", "form"):
        return 3 if speed != "yavaş" else 2, speed
    if hard_mode_bonus and exercise in HARD_MODE and speed == "çok hızlı":
        return 4, speed
    return 3, speed
