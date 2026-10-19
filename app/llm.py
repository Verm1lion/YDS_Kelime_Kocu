"""Gemini istemcisi (yalnızca içerik üretimi ve rapor metni).

- Anahtar .env'de: GEMINI_API_KEY=... (isteğe bağlı GEMINI_MODEL=..., GEMINI_FALLBACKS=a,b,c)
- Ücretsiz modeller zinciri: birincil model kota (429) veya yoğunluk (503) verirse bir sonrakine geçilir; her modelin
  ücretsiz kotası ayrıdır. Günlük kota dolan model ertesi güne kadar dinlendirilir (bekleme süreleri kalıcıdır).
- Hız sınırı: dakikada `llm_rpm` istek, günde `llm_daily_requests` istek.
- İnternet/anahtar/kota yoksa iş kuyrukta bekler; çekirdek özellikler etkilenmez.
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from . import config, db

API = "https://generativelanguage.googleapis.com/v1beta"
# 2026-10-04'te ücretsiz anahtarla denendi: kalite sırası (3.5-flash en iyi Türkçe ipucu/çeviri)
DEFAULT_CHAIN = ["gemini-3.5-flash", "gemini-flash-latest", "gemini-2.5-flash", "gemini-3.5-flash-lite"]
# Düşünen modellerde düşünme token'ları da maxOutputTokens'tan düşer; kesilen yanıt bu sınıra kadar genişletilip
# bir kez yeniden denenir (32000 zincirdeki tüm modellerde denendi; geçersiz değer 400 verip modeli bir gün dinlendirir).
MAX_BUDGET = 32000

_lock = threading.Lock()
_last_call = 0.0
_available: set[str] | None = None
_available_at = 0.0
_last_model: str | None = None
_model_cache = None  # geriye dönük uyumluluk (sunucu anahtar değişince sıfırlar)


class LLMError(Exception):
    def __init__(self, msg: str, retry_after: float | None = None, fatal: bool = False):
        super().__init__(msg)
        self.retry_after = retry_after
        self.fatal = fatal


def api_key() -> str | None:
    return (config.read_env().get("GEMINI_API_KEY") or "").strip() or None


def chain() -> list[str]:
    env = config.read_env()
    out: list[str] = []
    first = (env.get("GEMINI_MODEL") or "").strip()
    if first:
        out.append(first)
    extra = [m.strip() for m in (env.get("GEMINI_FALLBACKS") or "").split(",") if m.strip()]
    for m in extra + DEFAULT_CHAIN:
        if m not in out:
            out.append(m)
    return out


def configured_model() -> str:
    return chain()[0]


# ---------------------------------------------------------------- kullanım ve bekleme
def usage_today() -> dict:
    row = db.q1("SELECT requests, tokens FROM llm_usage WHERE day=?", (config.day_str(),))
    return {"requests": row["requests"] if row else 0, "tokens": row["tokens"] if row else 0}


def _add_usage(tokens: int, model: str) -> None:
    db.x("""INSERT INTO llm_usage(day, requests, tokens) VALUES(?,1,?) ON CONFLICT(day) DO UPDATE SET
            requests=requests+1, tokens=tokens+excluded.tokens""", (config.day_str(), int(tokens or 0)))
    mu = db.get_meta("llm_model_usage", {}) or {}
    day = config.day_str()
    mu = {d: v for d, v in mu.items() if d >= (config.study_day() - timedelta(days=7)).isoformat()}
    mu.setdefault(day, {})
    mu[day][model] = mu[day].get(model, 0) + 1
    db.set_meta("llm_model_usage", mu)


def _cooldowns() -> dict:
    cd = db.get_meta("llm_cooldowns", {}) or {}
    now = time.time()
    return {m: v for m, v in cd.items() if v.get("until", 0) > now}


def _set_cooldown(model: str, seconds: float, reason: str) -> None:
    cd = _cooldowns()
    cd[model] = {"until": time.time() + max(5.0, seconds), "reason": reason[:160]}
    db.set_meta("llm_cooldowns", cd)


def _pacific_offset_hours(dt_utc: datetime) -> int:
    """ABD Pasifik saati: Mart'ın 2. pazarı 10:00 UTC – Kasım'ın 1. pazarı 09:00 UTC arası PDT (UTC-7), diğer zamanlar PST (UTC-8)."""
    y = dt_utc.year
    march1, nov1 = datetime(y, 3, 1, tzinfo=timezone.utc), datetime(y, 11, 1, tzinfo=timezone.utc)
    dst_start = march1 + timedelta(days=(6 - march1.weekday()) % 7 + 7, hours=10)
    dst_end = nov1 + timedelta(days=(6 - nov1.weekday()) % 7, hours=9)
    return -7 if dst_start <= dt_utc < dst_end else -8


def _seconds_until_quota_reset(now: datetime | None = None) -> float:
    """Ücretsiz günlük kotalar Pasifik gece yarısı sıfırlanır; 5 dk pay bırakılır."""
    now = now or datetime.now(timezone.utc)
    local = now + timedelta(hours=_pacific_offset_hours(now))
    next_midnight_local = (local + timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)
    reset_utc = next_midnight_local - timedelta(hours=_pacific_offset_hours(next_midnight_local))
    if reset_utc <= now:
        reset_utc += timedelta(days=1)
    return (reset_utc - now).total_seconds()


def status() -> dict:
    key = api_key()
    u = usage_today()
    q = db.q("SELECT status, COUNT(*) n FROM llm_jobs GROUP BY status")
    cds = _cooldowns()
    mu = (db.get_meta("llm_model_usage", {}) or {}).get(config.day_str(), {})
    return {"configured": bool(key), "model": _last_model or configured_model(), "chain": chain(),
            "cooldowns": {m: {"minutes": round((v["until"] - time.time()) / 60), "reason": v.get("reason")}
                          for m, v in cds.items()},
            "usage_today": u, "usage_by_model": mu,
            "daily_limit": int(db.get_setting("llm_daily_requests", 200)), "rpm": int(db.get_setting("llm_rpm", 8)),
            "jobs": {r["status"]: r["n"] for r in q}}


# ---------------------------------------------------------------- HTTP
class _HttpFail(Exception):
    def __init__(self, code: int, text: str, headers=None):
        super().__init__(f"HTTP {code}")
        self.code = code
        self.text = text
        self.headers = headers or {}


def _http(method: str, url: str, body: dict | None, key: str, timeout: float = 240) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json", "x-goog-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise _HttpFail(e.code, e.read().decode("utf-8", errors="ignore")[:4000], dict(e.headers or {}))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise LLMError(f"bağlantı yok: {e}", retry_after=300)


def _parse_429(text: str) -> tuple[float, bool]:
    """(bekleme saniyesi, günlük kota mı)"""
    per_day = "PerDay" in text or "per day" in text.lower()
    delay = 60.0
    m = re.search(r'"retryDelay"\s*:\s*"(\d+(?:\.\d+)?)s"', text)
    if m:
        delay = float(m.group(1))
    if per_day:
        delay = max(delay, _seconds_until_quota_reset())
    return delay, per_day


def available_models(key: str) -> set[str] | None:
    global _available, _available_at
    if _available is not None and time.time() - _available_at < 6 * 3600:
        return _available
    try:
        res = _http("GET", f"{API}/models?pageSize=300", None, key, timeout=30)
        _available = {m["name"].split("/", 1)[-1] for m in res.get("models", [])
                      if "generateContent" in (m.get("supportedGenerationMethods") or [])}
        _available_at = time.time()
    except (LLMError, _HttpFail):
        return None
    return _available


_MD = re.compile(r"(\*\*|__)")


def _sanitize(o):
    if isinstance(o, str):
        return _MD.sub("", o).strip()
    if isinstance(o, list):
        return [_sanitize(x) for x in o]
    if isinstance(o, dict):
        return {k: _sanitize(v) for k, v in o.items()}
    return o


def _parse_json(text: str):
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("\n") + 1:] if "\n" in text else text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        cut = text.rfind("}")
        if cut > 0:
            for tail in ("]}", "]", ""):
                try:
                    return json.loads(text[: cut + 1] + tail)
                except json.JSONDecodeError:
                    continue
    raise LLMError("geçersiz JSON yanıt", retry_after=10)


def generate_json(prompt: str, max_tokens: int = 8192, temperature: float = 0.7) -> tuple[object, dict]:
    """JSON döndüren tek çağrı; ücretsiz model zincirinde kota/yoğunluğa göre model değiştirir."""
    global _last_call, _last_model
    key = api_key()
    if not key:
        raise LLMError("Gemini anahtarı yok (.env: GEMINI_API_KEY)", retry_after=3600)
    daily = int(db.get_setting("llm_daily_requests", 200))
    if usage_today()["requests"] >= daily:
        raise LLMError("günlük istek sınırına ulaşıldı", retry_after=_seconds_until_quota_reset())
    avail = available_models(key)
    models = [m for m in chain() if avail is None or m in avail]
    cds = _cooldowns()
    ready = [m for m in models if m not in cds]
    if not ready:
        wait = min((v["until"] - time.time()) for v in cds.values()) if cds else 300
        raise LLMError("tüm modeller dinleniyor (kota/yoğunluk)", retry_after=max(30, wait))
    last_err = "?"
    attempts = [(m, max_tokens) for m in ready]
    while attempts:
        model, budget = attempts.pop(0)
        rpm = max(1, int(db.get_setting("llm_rpm", 8)))
        with _lock:
            wait = _last_call + 60.0 / rpm - time.time()
            if wait > 0:
                time.sleep(wait)
            _last_call = time.time()
        body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": temperature,
                                     "maxOutputTokens": budget}}
        try:
            res = _http("POST", f"{API}/models/{model}:generateContent", body, key)
        except _HttpFail as e:
            if e.code == 429:
                delay, per_day = _parse_429(e.text)
                _set_cooldown(model, delay, "günlük kota doldu" if per_day else "dakikalık sınır")
                last_err = f"{model}: kota (429)"
                continue
            if e.code in (500, 502, 503, 504):
                _set_cooldown(model, 300, f"sunucu yoğun ({e.code})")
                last_err = f"{model}: sunucu {e.code}"
                continue
            if e.code == 404:
                _set_cooldown(model, 7 * 86400, "model kullanılamıyor (404)")
                last_err = f"{model}: 404"
                continue
            if e.code in (401, 403) or "API key not valid" in e.text or "API_KEY_INVALID" in e.text:
                raise LLMError(f"anahtar geçersiz/izin yok ({e.code})", fatal=True)
            _set_cooldown(model, 86400, f"istek reddedildi ({e.code})")
            last_err = f"{model}: HTTP {e.code} {e.text[:120]}"
            continue
        usage = res.get("usageMetadata", {})
        _add_usage(int(usage.get("totalTokenCount") or 0), model)
        cands = res.get("candidates") or []
        if not cands:
            _set_cooldown(model, 600, "boş yanıt")
            last_err = f"{model}: boş yanıt"
            continue
        parts = (cands[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        try:
            obj = _parse_json(text)
        except LLMError:
            cut = cands[0].get("finishReason") == "MAX_TOKENS"
            if cut and budget == max_tokens and budget < MAX_BUDGET:
                attempts.insert(0, (model, min(MAX_BUDGET, max(budget * 4, 8192))))
            last_err = f"{model}: yanıt token sınırında kesildi ({budget})" if cut else f"{model}: geçersiz JSON"
            continue
        _last_model = model
        return _sanitize(obj), {"model": model, "tokens": usage.get("totalTokenCount")}
    cds = _cooldowns()
    wait = min((v["until"] - time.time()) for v in cds.values()) if cds else 120
    raise LLMError(f"hiçbir model yanıt vermedi ({last_err})", retry_after=max(30, min(wait, 3600)))


def test_connection() -> dict:
    try:
        obj, meta = generate_json('Sadece şu JSON\'u döndür: {"ok": true, "mesaj": "merhaba"}', max_tokens=2048, temperature=0)
        return {"ok": True, "model": meta.get("model"), "response": obj}
    except LLMError as e:
        return {"ok": False, "error": str(e)}
