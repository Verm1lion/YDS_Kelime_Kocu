"""FSRS motoru.

- Tekil tekrarlar: resmî py-fsrs (Scheduler.review_card) — kart durumu JSON olarak saklanır.
- Projeksiyon / simülasyon / optimizasyon: aynı formüllerin numpy ile vektörel karşılığı
  (tests/test_fsrs_engine.py py-fsrs ile birebir aynı sonucu verdiğini doğrular).
- Sınav tarihine duyarlılık: hiçbir vade sınav gününe (ve sonrasına) düşmez; sınav öncesi son
  pencereye (final_days) sıkıştırılır ve yük dengelenerek dağıtılır.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Sequence

import numpy as np
from fsrs import Card, Rating, Scheduler, State
from fsrs.scheduler import DEFAULT_PARAMETERS, LOWER_BOUNDS_PARAMETERS, UPPER_BOUNDS_PARAMETERS

from . import config

RELEARN_STEP = timedelta(minutes=10)


def make_scheduler(params: Sequence[float] | None = None, desired_retention: float = 0.9,
                   maximum_interval: int = 36500, fuzz: bool = True) -> Scheduler:
    return Scheduler(
        parameters=tuple(params) if params else DEFAULT_PARAMETERS,
        desired_retention=float(desired_retention),
        learning_steps=(),               # ilk öğrenme oturum içi merdivenle yapılır
        relearning_steps=(RELEARN_STEP,),  # unutulan kelime aynı oturumda yeniden sorulur
        maximum_interval=max(1, int(maximum_interval)),
        enable_fuzzing=fuzz,
    )


def card_from_json(d: dict | None) -> Card:
    if not d:
        return Card(card_id=1)
    return Card.from_dict(d)


def card_to_json(c: Card) -> dict:
    return c.to_dict()


def retrievability(params: Sequence[float], stability: float | None, last_review: datetime | None,
                   at: datetime) -> float:
    if stability is None or last_review is None:
        return 0.0
    decay = -params[20]
    factor = 0.9 ** (1 / decay) - 1
    elapsed = max(0, (at - last_review).days)
    return (1 + factor * elapsed / stability) ** decay


def r_at_days(params: Sequence[float], stability, elapsed_days):
    """Vektörel: R(t) = (1 + F t/S)^decay."""
    decay = -params[20]
    factor = 0.9 ** (1 / decay) - 1
    s = np.maximum(np.asarray(stability, dtype=float), 1e-3)
    t = np.maximum(np.asarray(elapsed_days, dtype=float), 0.0)
    return (1 + factor * t / s) ** decay


def interval_for(params: Sequence[float], stability: float, desired_retention: float) -> float:
    decay = -params[20]
    factor = 0.9 ** (1 / decay) - 1
    return stability / factor * (desired_retention ** (1 / decay) - 1)


# ---------------------------------------------------------------- vektörel FSRS-6
class VecFSRS:
    """py-fsrs formüllerinin numpy karşılığı (bulanıklaştırma yok)."""

    def __init__(self, params: Sequence[float] | None = None):
        self.w = np.array(params if params is not None else DEFAULT_PARAMETERS, dtype=float)
        self.decay = -self.w[20]
        self.factor = 0.9 ** (1 / self.decay) - 1

    def init_s(self, g):
        return np.maximum(self.w[np.asarray(g, dtype=int) - 1], 0.001)

    def init_d(self, g, clamp=True):
        d = self.w[4] - np.exp(self.w[5] * (np.asarray(g, dtype=float) - 1)) + 1
        return np.clip(d, 1.0, 10.0) if clamp else d

    def r(self, s, t):
        return (1 + self.factor * np.maximum(t, 0) / np.maximum(s, 1e-3)) ** self.decay

    def next_d(self, d, g):
        g = np.asarray(g, dtype=float)
        delta = -(self.w[6] * (g - 3))
        d2 = d + (10.0 - d) * delta / 9.0
        easy0 = self.w[4] - math.exp(self.w[5] * 3) + 1
        nd = self.w[7] * easy0 + (1 - self.w[7]) * d2
        return np.clip(nd, 1.0, 10.0)

    def recall_s(self, d, s, r, g):
        g = np.asarray(g)
        s = np.maximum(s, 1e-3)
        hard = np.where(g == 2, self.w[15], 1.0)
        easy = np.where(g == 4, self.w[16], 1.0)
        return s * (1 + math.exp(self.w[8]) * (11 - d) * np.power(s, -self.w[9])
                    * (np.exp((1 - r) * self.w[10]) - 1) * hard * easy)

    def forget_s(self, d, s, r):
        s = np.maximum(s, 1e-3)
        long = self.w[11] * np.power(d, -self.w[12]) * (np.power(s + 1, self.w[13]) - 1) * np.exp((1 - r) * self.w[14])
        short = s / math.exp(self.w[17] * self.w[18])
        return np.minimum(long, short)

    def short_s(self, s, g):
        g = np.asarray(g, dtype=float)
        s = np.maximum(s, 1e-3)
        inc = np.exp(self.w[17] * (g - 3 + self.w[18])) * np.power(s, -self.w[19])
        inc = np.where(g >= 2, np.maximum(inc, 1.0), inc)
        return np.maximum(s * inc, 0.001)

    def step(self, s, d, elapsed_days, g, is_new):
        """Bir tekrar sonrası (s, d). elapsed_days: tam gün (py-fsrs ile aynı .days mantığı)."""
        g = np.asarray(g)
        is_new = np.asarray(is_new, dtype=bool)
        el = np.asarray(elapsed_days, dtype=float)
        s0 = self.init_s(np.where(is_new, g, 1))
        d0 = self.init_d(np.where(is_new, g, 1))
        safe_s = np.where(is_new, 1.0, s)
        safe_d = np.where(is_new, 5.0, d)
        r = self.r(safe_s, el)
        long_s = np.where(g == 1, self.forget_s(safe_d, safe_s, r), self.recall_s(safe_d, safe_s, r, g))
        same_day = el < 1
        st_s = self.short_s(safe_s, g)
        ns = np.where(same_day, st_s, long_s)
        ns = np.maximum(ns, 0.001)
        nd = self.next_d(safe_d, g)
        return np.where(is_new, s0, ns), np.where(is_new, d0, nd)

    def interval(self, s, desired_retention):
        iv = s / self.factor * (desired_retention ** (1 / self.decay) - 1)
        return np.maximum(np.round(iv), 1)


# ---------------------------------------------------------------- sınav tarihi kısıtı
@dataclass
class ExamWindow:
    exam: date
    final_days: int

    @property
    def last_review_day(self) -> date:
        return self.exam - timedelta(days=1)

    @property
    def final_start(self) -> date:
        return self.exam - timedelta(days=self.final_days)

    def max_interval_from(self, today: date) -> int:
        return max(1, (self.last_review_day - today).days)


def clamp_due_day(due_day: date, today: date, win: ExamWindow, load: dict[date, int] | None = None,
                  stability: float | None = None) -> date:
    """Vade sınavı geçiyorsa son pencereye taşır (en az yüklü güne)."""
    if due_day <= win.last_review_day:
        return due_day
    start = max(win.final_start, today + timedelta(days=1))
    end = win.last_review_day
    if start > end:
        return max(today, min(end, due_day))
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    if load is None:
        # kararlılık yüksekse pencerenin başına, düşükse sınava yakın
        if stability is None:
            return end
        idx = int(min(len(days) - 1, max(0, round((1 - min(stability, 60) / 60) * (len(days) - 1)))))
        return days[idx]
    best = min(days, key=lambda d: (load.get(d, 0), -(d - start).days))
    load[best] = load.get(best, 0) + 1
    return best


def due_to_day(due: datetime) -> date:
    return config.study_day(due)
