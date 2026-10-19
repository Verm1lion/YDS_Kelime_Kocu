"""Vektörel FSRS ileri simülasyonu (planlayıcı, sınav-günü projeksiyonu ve sanal öğrenci için ortak).

Gün 0 = bugün, H = sınava kalan gün (sınav günü indeksi). Hiçbir tekrar H'ye veya sonrasına düşmez.
Son pencere [H-final_days, H-1]: yeni kelime yok; tüm liste en az bir kez taranır (en riskli önce).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .fsrs_engine import VecFSRS


@dataclass
class SimInput:
    H: int                                  # sınava kalan gün
    final_days: int
    params: list[float]
    desired_retention: float
    S: np.ndarray                           # mevcut kartlar (tanıtılmış)
    D: np.ndarray
    last: np.ndarray                        # son tekrar günü (<=0)
    due: np.ndarray                         # vade günü (<=0 gecikmiş)
    n_new: int                              # tanıtılmamış kelime sayısı
    new_schedule: np.ndarray                # gün başına yeni kelime (uzunluk H)
    p_known_new: np.ndarray | None = None   # tanıtılmamışların taban bilinme olasılığı (n_new)
    capacity: np.ndarray | None = None      # gün başına en fazla tekrar (None = sınırsız)
    first_probs: tuple = (0.62, 0.25, 0.13)  # ilk oturum: temiz / 1 hata / 2+ hata
    hard_frac: float = 0.15                 # başarılı tekrarların 'Hard' oranı
    sweep: bool = True
    final_retention: float = 0.95           # son haftada hedef hatırlama
    runs: int = 24
    seed: int = 11
    true_params: list[float] | None = None  # sanal öğrenci için 'gerçek' bellek (yoksa params)
    word_difficulty: np.ndarray | None = None  # sanal öğrenci: kelime başı zorluk çarpanı (S'ye)


@dataclass
class SimResult:
    reviews: np.ndarray        # gün başına ortalama tekrar (vadesi gelen)
    sweeps: np.ndarray         # gün başına son hafta tarama tekrarı
    new: np.ndarray            # gün başına yeni
    backlog: np.ndarray        # kapasite yüzünden ertelenen
    r_exam_mean: float         # sınav günü ortalama hatırlama (tüm liste)
    r_exam_runs: np.ndarray    # koşu başına ortalama
    r_exam_card: np.ndarray    # kart başına ortalama (mevcut + yeni)
    introduced_by_end: float
    extra: dict = field(default_factory=dict)


LEARN_STEPS = 5  # oturum içinde FSRS'e işlenen cevap: 4 sınama basamağı + part sonu pekiştirme (session.FSRS_STEPS_PER_NEW)


def _first_session_state(vf: VecFSRS, rng, shape, probs):
    """Oturum içi merdiven sonrası (S, D): temiz -> Good; 1 hata -> Again+Good; 2+ -> Again+Again+Good."""
    u = rng.random(shape)
    cat = np.where(u < probs[0], 0, np.where(u < probs[0] + probs[1], 1, 2))
    # cevap dizileri: temiz [3]*4; 1 hata [1]+[3]*4; 2+ hata [1,1]+[3]*4
    g1 = np.where(cat == 0, 3, 1)
    s, d = vf.init_s(g1), vf.init_d(g1)
    g2 = np.where(cat == 2, 1, 3)
    s, d = vf.short_s(s, g2), vf.next_d(d, g2)
    three = np.full(shape, 3)
    for _ in range(LEARN_STEPS - 2):
        s, d = vf.short_s(s, three), vf.next_d(d, three)
    s3, d3 = vf.short_s(s, three), vf.next_d(d, three)
    s, d = np.where(cat >= 1, s3, s), np.where(cat >= 1, d3, d)
    s4, d4 = vf.short_s(s, three), vf.next_d(d, three)
    s, d = np.where(cat == 2, s4, s), np.where(cat == 2, d4, d)
    return s, d


def run(inp: SimInput) -> SimResult:
    H = int(inp.H)
    R = inp.runs
    rng = np.random.default_rng(inp.seed)
    vf = VecFSRS(inp.params)
    tv = VecFSRS(inp.true_params) if inp.true_params is not None else vf
    n0 = len(inp.S)
    M = n0 + int(inp.n_new)
    final_start = max(0, H - int(inp.final_days))
    ivf = (inp.desired_retention ** (1 / vf.decay) - 1) / vf.factor
    final_ret = max(inp.desired_retention, inp.final_retention)
    ivf_final = (final_ret ** (1 / vf.decay) - 1) / vf.factor

    S = np.ones((R, M))
    D = np.full((R, M), 5.0)
    last = np.zeros((R, M))
    due = np.full((R, M), 10 ** 6, dtype=float)
    intro = np.full(M, -1, dtype=int)
    if n0:
        S[:, :n0] = np.maximum(inp.S, 0.01)
        D[:, :n0] = inp.D
        last[:, :n0] = inp.last
        due[:, :n0] = np.minimum(inp.due, 10 ** 6)
    # yeni kelimelerin tanıtım günleri
    sched = np.zeros(H, dtype=int)
    sched[: len(inp.new_schedule)] = np.asarray(inp.new_schedule[:H], dtype=int)
    sched[final_start:] = 0
    k = n0
    for d in range(H):
        take = min(sched[d], M - k)
        if take > 0:
            intro[k:k + take] = d
            k += take
    intro[k:] = 10 ** 6  # sınavdan önce tanıtılamayanlar
    introduced = np.zeros((R, M), dtype=bool)
    introduced[:, :n0] = True
    wd = inp.word_difficulty if inp.word_difficulty is not None else np.ones(M)
    reviews = np.zeros((R, H))
    sweeps = np.zeros((R, H))
    backlog = np.zeros((R, H))
    swept = np.zeros((R, M), dtype=bool)
    clamped = np.zeros((R, M), dtype=bool)   # son haftaya taşınmış (tarama) vadeler
    idx_all = np.arange(M)
    if n0:
        clamped[:, :n0] = (inp.due >= final_start)[None, :] & (inp.last < final_start)[None, :] & (final_start > 0)

    for d in range(H):
        newmask = intro == d
        if newmask.any():
            cols = idx_all[newmask]
            s0, d0 = _first_session_state(vf, rng, (R, len(cols)), inp.first_probs)
            if inp.true_params is not None:
                s0 = s0 * wd[cols]
            S[:, cols] = s0
            D[:, cols] = d0
            last[:, cols] = d
            due[:, cols] = d + 1   # yeni kelimenin ilk tekrarı ertesi gün (cards.cap_first_review)
            introduced[:, cols] = True
        rev = introduced & (due <= d) & ~newmask[None, :]
        if inp.capacity is not None:
            cap = int(inp.capacity[d]) if d < len(inp.capacity) else int(inp.capacity[-1])
            cnt = rev.sum(axis=1)
            over = cnt > cap
            if over.any():
                rcur = tv.r(S, d - last)
                for r_i in np.where(over)[0]:
                    cand = np.where(rev[r_i])[0]
                    keep = cand[np.argsort(rcur[r_i, cand])[:cap]]
                    m = np.zeros(M, dtype=bool)
                    m[keep] = True
                    backlog[r_i, d] = len(cand) - cap
                    rev[r_i] = m
        # son pencere taraması: en az bir kez gözden geçir
        sw = np.zeros_like(rev)
        if inp.sweep and d >= final_start:
            need = introduced & ~swept & ~rev & (last < final_start) & (due >= H)
            remaining_days = H - d
            n_need = need.sum(axis=1)
            quota = np.ceil(n_need / max(1, remaining_days)).astype(int)
            if quota.max() > 0:
                rex = tv.r(S, H - last)
                for r_i in range(R):
                    if quota[r_i] <= 0:
                        continue
                    cand = np.where(need[r_i])[0]
                    pick = cand[np.argsort(rex[r_i, cand])[:quota[r_i]]]
                    sw[r_i, pick] = True
        act = rev | sw
        sw_like = (rev & clamped) | sw
        reviews[:, d] = (rev & ~clamped).sum(axis=1)
        sweeps[:, d] = sw_like.sum(axis=1)
        if act.any():
            el = np.maximum(d - last, 0)
            r_true = tv.r(S, el)
            success = rng.random((R, M)) < r_true
            hard = rng.random((R, M)) < inp.hard_frac
            g = np.where(success, np.where(hard, 2, 3), 1)
            S1, D1 = vf.step(S, D, el, g, np.zeros((R, M), dtype=bool))
            # başarısızsa aynı gün yeniden öğrenme (oturum içi tekrar): kısa vadeli Good
            S2 = vf.short_s(S1, np.full((R, M), 3))
            D2 = vf.next_d(D1, np.full((R, M), 3))
            S_new = np.where(success, S1, S2)
            D_new = np.where(success, D1, D2)
            S = np.where(act, S_new, S)
            D = np.where(act, D_new, D)
            last = np.where(act, d, last)
            ivl = np.maximum(1, np.round(S * (ivf_final if d >= final_start else ivf)))
            nd = d + ivl
            beyond = act & (nd >= H)
            new_clamped = np.zeros_like(act)
            if beyond.any():
                if d < final_start:
                    # son haftadan önce: son haftaya yük dengeli dağıt (tarama turu)
                    span = H - final_start
                    spread = final_start + (idx_all[None, :] * 7 + d) % max(1, span)
                    nd = np.where(beyond, spread, nd)
                    new_clamped = beyond
                else:
                    # son hafta içinde gözden geçirildi: sınava kadar yeni tekrar yok
                    nd = np.where(beyond, H, nd)
            due = np.where(act, nd, due)
            clamped = np.where(act, new_clamped, clamped)
            swept |= act & (d >= final_start)
    # sınav günü hatırlama
    rex = tv.r(S, H - last)
    pk = np.zeros(M)
    if inp.p_known_new is not None and inp.n_new:
        pk[n0:] = inp.p_known_new[: inp.n_new]
    r_exam = np.where(introduced, rex, pk[None, :])
    return SimResult(
        reviews=reviews.mean(axis=0), sweeps=sweeps.mean(axis=0), new=sched.astype(float),
        backlog=backlog.mean(axis=0), r_exam_mean=float(r_exam.mean()), r_exam_runs=r_exam.mean(axis=1),
        r_exam_card=r_exam.mean(axis=0), introduced_by_end=float(introduced.sum(axis=1).mean()),
    )
