"""YDS puan olasılık modeli (gerçekçi, belirsizliği açık; her oturumdan sonra yeniden hesaplanır).

80 soru × 1,25 puan; yanlış doğruyu götürmez. Bölümler (ÖSYM yapısı):
  1-6 kelime (6) · 7-16 dil bilgisi (10) · 17-26 cloze (10) · 27-36 cümle tamamlama (10) · 37-42 çeviri (6)
  43-62 okuma (20) · 63-67 diyalog (5) · 68-71 yakın anlam (4) · 72-75 paragraf tamamlama (4) · 76-80 akışı bozan (5)

Model:
  - Kelime bilgisi (ölçülen): her liste kelimesinin hatırlanma olasılığı — öğrenilenlerde FSRS, öğrenilmeyenlerde seviye
    testinin katman oranları; metin kapsama oranı (xlsx kapsama eğrisi) ve ÖSYM'de şık olarak çıkma olasılığıyla
    ağırlıklı. Listedeki kelimeler 2021-26'da ilk kez sorulan kelimelerin ~%90,6'sını kapsıyor.
  - Dil bilgisi/okuma becerisi θ (uygulamada doğrudan ölçülmez): önseli öz değerlendirmeden (Ayarlar → İngilizce
    seviyem). Kalibrasyon: B1 + bugünkü tipik kelime bilgisi ≈ 47, + listenin tamamı ≈ 54 puan; A2-B1 ≈ 41 / 47.
    Sonsal: deneme sınavları (denemenin yapıldığı günkü kelime durumuyla) ve uygulamada çözülen gerçek ÖSYM dil
    bilgisi soruları.
  - Senaryolar: bugün girsen · sınav günü bu tempoyla · sınav günü plana uyarsan · "+N kelime öğrenirsen" · beceri yarım
    seviye artarsa. Hepsi aynı rastgele sayılarla (ortak rastgele sayılar) hesaplanır: farklar gürültü değil, kelime
    ve beceri farkıdır; eğri pürüzsüz ve tekdüze artar.
  - Belirsizlik: θ, kapsama etkisi (β), kelime projeksiyonu koşuları ve sınav günü şansı (soru başına).
"""
from __future__ import annotations

import json
import math
from datetime import date, timedelta

import numpy as np

from . import config, db, projection

SECTIONS = [
    # ad, soru sayısı, tür, α (θ=0 ve %92,1 kapsamada başarıyı belirler)
    ("Kelime bilgisi", 6, "vocab", 0.0),
    ("Dil bilgisi", 10, "grammar", -0.51),
    ("Cloze test", 10, "cloze", 0.0),
    ("Cümle tamamlama", 10, "read", -0.79),
    ("Çeviri", 6, "read", -0.51),
    ("Okuma", 20, "read", -0.79),
    ("Diyalog", 5, "read", -0.25),
    ("Yakın anlam", 4, "read", -1.10),
    ("Paragraf tamamlama", 4, "read", -1.10),
    ("Akışı bozan cümle", 5, "read", -0.79),
]
BASE_COVERAGE = 92.1
LIST_COVERS_ASKED = 0.906          # eski 2.310'luk listede (2021-26'da ilk kez sorulanlar üzerinden)
ASKED_CALIB = 0.906 / 0.822        # aynı liste gerçek ÖSYM kelime sorusu cevaplarının %82,2'sini kapsıyordu
P_OUTSIDE_KNOWN = 0.35
BETA_MEAN, BETA_SD = 0.13, 0.05
GUESS = 0.2
THETA_GRID = np.linspace(-3, 3, 241)
# öz değerlendirme → θ önseli (senin bugünkü kelime bilginle beklenen puan: A2 ~35, A2-B1 ~41, B1 ~47, B2 ~62)
LEVELS = {"A2": -1.3, "A2-B1": -0.8, "B1": -0.3, "B1-B2": 0.15, "B2": 0.6, "C1": 1.1}
LEVEL_LABELS = {"A2": "A2", "A2-B1": "A2–B1", "B1": "B1", "B1-B2": "B1–B2", "B2": "B2", "C1": "C1"}
THETA_PRIOR_SD = 0.6
HALF_LEVEL = 0.5
THRESHOLDS = [35, 40, 45, 50, 55, 60, 65, 70, 75]
MILESTONES = [250, 500, 1000, 1500]


def _sig(x):
    return 1.0 / (1.0 + np.exp(-x))


def section_probs(theta, beta, coverage, a_vocab):
    """Her bölüm için doğru cevap olasılığı (numpy yayınlama destekli)."""
    out = []
    for name, n, kind, alpha in SECTIONS:
        if kind == "vocab":
            p = a_vocab * 0.92 + (1 - a_vocab) * 0.27
            p = p * (0.85 + 0.15 * _sig(theta + 1.0))  # cümleyi anlama payı
        elif kind == "grammar":
            p = GUESS + (1 - GUESS) * _sig(theta + alpha)
        elif kind == "cloze":
            pv = a_vocab * 0.9 + (1 - a_vocab) * 0.27
            pg = GUESS + (1 - GUESS) * _sig(theta - 0.51 + beta * (coverage - 95.0) * 0.5)
            p = 0.5 * pv + 0.5 * pg
        else:
            p = GUESS + (1 - GUESS) * _sig(theta + alpha + beta * (coverage - BASE_COVERAGE))
        out.append(p)
    return out


def word_weights(ids: list[int]) -> tuple[np.ndarray, np.ndarray]:
    rows = {r["id"]: r for r in db.q("SELECT id, cov_weight, option_prob, kind FROM words")}
    cov = np.array([float((rows.get(i) or {}).get("cov_weight") or 0.0) for i in ids])
    opt = np.array([float((rows.get(i) or {}).get("option_prob") or 0.0) for i in ids])
    for k, i in enumerate(ids):
        if opt[k] <= 0:
            opt[k] = 0.3 if (rows.get(i) or {}).get("kind") == "phrasal" else 0.1
    return cov, opt


def vocab_state(card_r: np.ndarray, cov: np.ndarray, opt: np.ndarray) -> tuple[float, float]:
    coverage = BASE_COVERAGE + float(np.sum(card_r * cov))
    k = float(np.sum(card_r * opt) / max(1e-9, np.sum(opt)))
    lca = list_covers_asked()
    a_vocab = lca * k + (1 - lca) * P_OUTSIDE_KNOWN
    return coverage, a_vocab


_LCA: dict = {}


def list_covers_asked() -> float:
    """Etkin listenin gerçek ÖSYM kelime sorusu cevaplarını (2012-2026, seed/osym_vocab_answers.json) kapsama oranı,
    eski listenin ölçümüne göre ölçeklenmiş (kitap + garanti planında ~0,78; yedek de açılırsa ~0,95)."""
    n_active = int(db.val("SELECT COUNT(*) FROM words WHERE status='active'", default=0) or 0)
    if _LCA.get("n") == n_active:
        return _LCA["v"]
    v = LIST_COVERS_ASKED
    p = config.seed_dir() / "osym_vocab_answers.json"
    try:
        answers = json.loads(p.read_text(encoding="utf-8"))["answers"]
        from . import textutil as tu
        forms = set()
        for r in db.q("SELECT lemma FROM words WHERE status='active'"):
            parts = r["lemma"].split()
            for f in tu.all_forms(parts[0], ["v", "n", "adj", "adv"]) | {parts[0]}:
                forms.add(" ".join([f] + parts[1:]))
        if answers and n_active:
            v = min(0.95, ASKED_CALIB * sum(1 for a in answers if a in forms) / len(answers))
    except (OSError, ValueError, KeyError):
        pass
    _LCA.update({"n": n_active, "v": v})
    return v


def theta_prior() -> tuple[float, float, str]:
    lvl = str(db.get_setting("self_level", "B1") or "B1")
    if lvl not in LEVELS:
        lvl = "B1"
    return LEVELS[lvl], THETA_PRIOR_SD, lvl


def theta_posterior(mocks: list[dict], prior: tuple[float, float] = (LEVELS["B1"], THETA_PRIOR_SD),
                    grammar_answers: list[int] | None = None) -> np.ndarray:
    """θ ızgara sonsalı: önsel + denemeler (her biri kendi günündeki kelime durumuyla) + gerçek ÖSYM dil bilgisi soruları."""
    logp = -0.5 * ((THETA_GRID - prior[0]) / prior[1]) ** 2
    for m in mocks:
        total = m.get("total_correct")
        secs = db.jload(m.get("sections"), {}) if isinstance(m.get("sections"), str) else (m.get("sections") or {})
        ps = section_probs(THETA_GRID[:, None], BETA_MEAN, m["_coverage"], m["_a_vocab"])
        if secs:
            for (name, n, kind, alpha), p in zip(SECTIONS, ps):
                if name in secs and secs[name] is not None:
                    k = int(secs[name])
                    p = np.clip(p[:, 0], 1e-6, 1 - 1e-6)
                    logp += k * np.log(p) + (n - k) * np.log(1 - p)
        elif total is not None:
            mean = sum(n * p[:, 0] for (name, n, kind, alpha), p in zip(SECTIONS, ps))
            pbar = np.clip(mean / 80.0, 1e-6, 1 - 1e-6)
            k = int(total)
            # binom (bölümler arası heterojenlik için hafif şişirilmiş)
            logp += 0.8 * (k * np.log(pbar) + (80 - k) * np.log(1 - pbar))
    if grammar_answers:
        alpha = next(a for _, _, kind, a in SECTIONS if kind == "grammar")
        p = np.clip(GUESS + (1 - GUESS) * _sig(THETA_GRID + alpha), 1e-6, 1 - 1e-6)
        k, n = sum(grammar_answers), len(grammar_answers)
        logp += k * np.log(p) + (n - k) * np.log(1 - p)
    logp -= logp.max()
    post = np.exp(logp)
    return post / post.sum()


def _norm(s: str) -> str:
    return " ".join(str(s or "").lower().split())


def osym_grammar_answers() -> list[int]:
    """Uygulamada (haftalık testte) cevaplanan gerçek ÖSYM dil bilgisi soruları: 1 doğru, 0 yanlış."""
    p = config.seed_dir() / "osym_questions.json"
    if not p.exists():
        return []
    gram = {_norm(q["stem"]) for q in json.loads(p.read_text(encoding="utf-8")) if q.get("type") == "Dil Bilgisi"}
    out = []
    for r in db.q("SELECT correct, prompt FROM events WHERE exercise='osym' AND correct IS NOT NULL"):
        if _norm((db.jload(r["prompt"], {}) or {}).get("sentence")) in gram:
            out.append(int(r["correct"]))
    return out


def prior_known(ids: list[int]) -> np.ndarray:
    """Öğrenmeden önceki bilinme olasılığı (seviye testi katmanı / beyan / kelime düzeyi)."""
    from . import planner
    tiers = planner.placement_known_rates()
    tier_of = planner.word_tiers() if tiers else {}
    rows = {r["id"]: r for r in db.q("SELECT w.id, w.level, c.known_status FROM words w LEFT JOIN cards c ON c.word_id=w.id")}
    out = np.zeros(len(ids))
    for k, i in enumerate(ids):
        r = rows.get(i) or {}
        if r.get("known_status") in ("probable", "verified"):
            out[k] = 0.8
        elif r.get("known_status") == "failed":
            out[k] = 0.1
        else:
            pr = planner.CEFR_KNOWN.get(r.get("level"), planner.CEFR_KNOWN[None])
            out[k] = tiers.get(tier_of.get(i), pr) if tiers else pr
    return out


def _eta(n: int, rate: float, learning_days_left: int) -> dict:
    """n yeni kelimeye bu hızla ne zaman ulaşılır (haftalık tekrar günü öğrenme yok sayılır)."""
    if n <= 0:
        return {"date": config.day_str(), "reachable": True}
    if rate <= 0.05:
        return {"date": None, "reachable": False}
    days = int(math.ceil(n / rate * 7 / 6))
    return {"date": (config.study_day() + timedelta(days=days)).isoformat(), "reachable": days <= learning_days_left}


_cache: dict = {}


def compute(n_samples: int = 4000, seed: int = 17) -> dict:
    """Girdiler (cevaplar, denemeler, seviye, hedef, projeksiyon) değişmedikçe önbellekten; değişince yeniden hesaplanır."""
    proj = projection.compute()
    key = (id(proj), config.day_str(), db.val("SELECT MAX(id) FROM events", default=0),
           db.val("SELECT group_concat(id || '/' || day || '/' || COALESCE(total_correct, '') || '/' || COALESCE(sections, ''), ';') "
                  "FROM mock_exams", default=""),
           db.get_setting("self_level", "B1"), db.get_setting("target_score", 55), n_samples, seed)
    if _cache.get("key") == key:
        return _cache["res"]
    res = _compute(proj, n_samples, seed)
    _cache.update(key=key, res=res)
    return res


def _compute(proj: dict, n_samples: int, seed: int) -> dict:
    from . import cards as C
    from . import planner
    from .fsrs_engine import r_at_days
    target = int(float(db.get_setting("target_score", 55)))
    ids = proj.get("ids") or []
    card_r = np.array(proj.get("card_r") or [], dtype=float)
    if len(ids) != len(card_r) or not len(ids):
        return {"available": False, "message": "Projeksiyon henüz hazır değil."}
    card_r_plan = np.array(proj.get("card_r_plan") or card_r, dtype=float)
    cov_w, opt_w = word_weights(ids)
    st = planner.state_arrays(config.study_day())
    n_old, n_new = len(st["S"]), int(st["n_new"])
    # bugünkü kelime durumu: öğrenilenlerde FSRS hatırlanabilirliği, diğerlerinde seviye testi
    r_now = np.zeros(len(ids))
    if n_old:
        r_now[:n_old] = r_at_days(C.active_params(), st["S"], -st["last"])
    if n_new:
        r_now[n_old:] = st["p_known"][:n_new]
    pk_all = prior_known(ids)
    cov_now, av_now = vocab_state(r_now, cov_w, opt_w)
    cov_pace, av_pace = vocab_state(card_r, cov_w, opt_w)
    cov_plan, av_plan = vocab_state(card_r_plan, cov_w, opt_w)

    # θ: önsel + denemeler (o günkü kelime durumuyla) + gerçek ÖSYM dil bilgisi soruları
    mu0, sd0, lvl = theta_prior()
    intro = {r["word_id"]: r["introduced_at"] for r in db.q("SELECT word_id, introduced_at FROM cards")}
    mocks = db.q("SELECT * FROM mock_exams ORDER BY day")
    for m in mocks:
        cutoff = config.iso(config.day_start_utc(date.fromisoformat(m["day"]) + timedelta(days=1)))
        then = np.array([bool(intro.get(i)) and intro[i] < cutoff for i in ids])
        m["_coverage"], m["_a_vocab"] = vocab_state(np.where(then, r_now, pk_all), cov_w, opt_w)
    gram = osym_grammar_answers()
    post = theta_posterior(mocks, (mu0, sd0), gram)

    rng = np.random.default_rng(seed)
    thetas = rng.choice(THETA_GRID, size=n_samples, p=post) + rng.normal(0, 0.03, n_samples)
    betas = np.clip(rng.normal(BETA_MEAN, BETA_SD, n_samples), 0.0, None)
    U = rng.random((n_samples, 80))                      # ortak rastgele sayılar: soru başına şans
    col = np.repeat(np.arange(len(SECTIONS)), [s[1] for s in SECTIONS])
    runs = np.array(proj.get("runs") or [proj["pace"]["mean"]], dtype=float)
    scale = rng.choice(runs / max(1e-9, runs.mean()), size=n_samples)

    def scores(cov, av, th=thetas, spread=False):
        if spread:   # kelime projeksiyonu koşuları arasındaki belirsizlik
            cov = BASE_COVERAGE + (cov - BASE_COVERAGE) * scale
            av = np.clip(av * scale, 0, 1)
        ps = section_probs(th, betas, cov, av)
        P = np.stack([np.broadcast_to(np.clip(p, 0, 1), (n_samples,)) for p in ps], axis=1)
        return (U < P[:, col]).sum(axis=1) * 1.25

    ths = sorted(set(THRESHOLDS + [target]))

    def summary(score) -> dict:
        return {"p": {str(t): float(np.mean(score >= t)) for t in ths}, "median": float(np.median(score)),
                "interval80": [float(np.quantile(score, 0.1)), float(np.quantile(score, 0.9))]}

    s_now, s_pace, s_plan = scores(cov_now, av_now), scores(cov_pace, av_pace, spread=True), scores(cov_plan, av_plan, spread=True)
    pace_info = proj.get("pace") or {}
    pace_ok = (pace_info.get("label") or "") != "veri yetersiz (plan varsayıldı)"
    scenarios = [
        {"key": "now", "label": "Bugün sınava girsen", **summary(s_now)},
        {"key": "pace", "label": "Sınav günü · bu tempoyla" + ("" if pace_ok else " (veri az: plan varsayıldı)"),
         **summary(s_pace)},
        {"key": "plan", "label": "Sınav günü · plana uyarsan", **summary(s_plan)},
    ]

    # ileriye dönük: "+N kelime öğrenirsen" (plan sırasıyla; öğrenilen kelime sınav günü ~r_learn ile hatırlanır)
    old_exam = card_r[:n_old]
    pk_new = st["p_known"][:n_new]
    lifted = card_r_plan[n_old:][card_r_plan[n_old:] > pk_new + 0.15] if n_new else np.array([])
    r_learn = float(np.clip(lifted.mean() if len(lifted) else 0.9, 0.8, 0.96))

    def with_new(n: int) -> tuple[float, float]:
        r = np.concatenate([old_exam, np.where(np.arange(n_new) < n, np.maximum(r_learn, pk_new), pk_new)])
        return vocab_state(r, cov_w, opt_w)

    plan = planner.today_plan()
    cal = planner.calendar(config.study_day())
    learn_days = max(0, int(cal["final_start"]))
    rate_pace = float(pace_info.get("new_per_day") or 0) if pace_ok else float(plan.get("new_rate") or 0)
    rate_plan = float(plan.get("new_rate") or plan.get("new_planned") or 0)
    steps = [0] + [m for m in MILESTONES if m < n_new] + ([n_new] if n_new else [])
    milestones = []
    for n in steps:
        cov_m, av_m = with_new(n)
        label = "Yeni kelime öğrenmezsen" if n == 0 else (f"Listenin tamamı (+{n})" if n == n_new else f"+{n} kelime")
        milestones.append({"words": n, "label": label, "eta_pace": _eta(n, rate_pace, learn_days),
                           "eta_plan": _eta(n, rate_plan, learn_days), **summary(scores(cov_m, av_m))})
    skill = summary(scores(cov_plan, av_plan, th=thetas + HALF_LEVEL, spread=True))
    grid = sorted(set([0, n_new] + [int(round(n_new * k / 20)) for k in range(1, 20)])) if n_new else [0]
    curve = [{"words": n, "p": summary(scores(*with_new(n)))["p"]} for n in grid]
    by_exam_pace = int(min(n_new, rate_pace * learn_days * 6 / 7))

    # geriye dönük alanlar (haftalık rapor, eski panel)
    at_least = [{"score": t, "p": float(np.mean(s_pace >= t))} for t in range(30, 85, 5)]
    bands = [{"lo": lo, "hi": lo + 5, "p": float(np.mean((s_pace >= lo) & (s_pace < lo + 5)))} for lo in range(25, 80, 5)]
    sec_means = [{"name": name, "n": n, "expected": float(np.mean(np.clip(p, 0, 1)) * n)}
                 for (name, n, kind, alpha), p in zip(SECTIONS, section_probs(thetas, betas, cov_pace, av_pace))]
    theta_mean = float(np.sum(THETA_GRID * post))
    theta_sd = float(math.sqrt(np.sum((THETA_GRID - theta_mean) ** 2 * post)))
    pl = planner.placement_known_rates()
    placement_known = None
    row = db.q1("SELECT result FROM placement WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 1")
    if row:
        placement_known = (db.jload(row["result"], {}) or {}).get("overall_known")
    learned = int(db.val("""SELECT COUNT(*) FROM cards c JOIN words w ON w.id=c.word_id WHERE w.status='active'
                            AND (c.stage>=4 OR c.known_status='verified')""", default=0) or 0)
    basis = [f"Önsel: {LEVEL_LABELS[lvl]} (öz değerlendirme)"]
    if placement_known is not None:
        basis.append(f"seviye testi: listenin %{placement_known * 100:.0f}'i")
    basis.append(f"{learned} kelime öğrenildi")
    basis.append(f"{len(mocks)} deneme" if mocks else "deneme yok")
    if gram:
        basis.append(f"{len(gram)} gerçek ÖSYM dil bilgisi sorusu")
    return {
        "available": True,
        "target": target,
        "thresholds": ths,
        "scenarios": scenarios,
        "milestones": milestones,
        "skill_up": {"label": f"Dil bilgisi/okuma yarım seviye artarsa (plana uyarak)", **skill},
        "curve": {"points": curve, "by_exam_pace": by_exam_pace, "n_new": n_new},
        "inputs": {"level": lvl, "level_label": LEVEL_LABELS[lvl], "theta_prior": mu0, "placement_known": placement_known,
                   "learned": learned, "known_now": float(np.sum(r_now)), "list_size": len(ids),
                   "mocks": len(mocks), "osym_grammar": len(gram), "pace_per_day": rate_pace, "pace_ok": pace_ok,
                   "r_learn": r_learn, "tiers": bool(pl)},
        # geriye dönük
        "p_target": float(np.mean(s_pace >= target)),
        "median": float(np.median(s_pace)),
        "interval80": [float(np.quantile(s_pace, 0.1)), float(np.quantile(s_pace, 0.9))],
        "at_least": at_least, "bands": bands, "best_band": max(bands, key=lambda b: b["p"]),
        "now_median": float(np.median(s_now)), "now_p_target": float(np.mean(s_now >= target)),
        "coverage_exam": cov_pace, "coverage_now": cov_now, "vocab_known_exam": av_pace, "vocab_known_now": av_now,
        "sections": sec_means, "mock_count": len(mocks),
        "theta": {"mean": theta_mean, "sd": theta_sd},
        "basis": " · ".join(basis),
        "note": ("Kelime bilgin her cevaptan sonra ölçülür; dil bilgisi/okuma becerin uygulamada ölçülmez — önce seviyenden, "
                 "deneme sonucu girdikçe gerçek performansından tahmin edilir. En büyük belirsizlik buradadır."),
        "computed_at": config.iso(config.now_utc()),
    }


def add_mock(day: str, total_correct: int | None, sections: dict | None, note: str | None = None) -> int:
    if total_correct is None and sections:
        total_correct = int(sum(int(v) for v in sections.values() if v is not None))
    if total_correct is None:
        raise ValueError("Toplam doğru veya bölüm doğruları gerekli")
    if not (0 <= int(total_correct) <= 80):
        raise ValueError("Toplam doğru 0-80 arası olmalı")
    date.fromisoformat(day)
    return db.x("INSERT INTO mock_exams(day, total_correct, sections, note, created_at) VALUES(?,?,?,?,?)",
                (day, int(total_correct), db.jdump(sections or {}), note, config.iso(config.now_utc())))
