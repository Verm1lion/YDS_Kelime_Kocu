"""Çevrimdışı telaffuz: Windows SAPI (Microsoft Zira/David/Mark) ile WAV üretip önbelleğe alır."""
from __future__ import annotations

import hashlib
import re
import subprocess
import threading
from pathlib import Path

from . import config

_lock = threading.Lock()
_voice_name: str | None = None


def _safe(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9' \-.,]", "", text)[:200]


def cache_path(text: str, rate: int) -> Path:
    h = hashlib.sha1(f"{text}|{rate}".encode("utf-8")).hexdigest()[:16]
    return config.tts_dir() / f"{h}.wav"


def _sapi_win32(text: str, out: Path, rate: int) -> bool:
    try:
        import pythoncom
        import win32com.client
    except Exception:
        return False
    pythoncom.CoInitialize()
    voice = stream = best = v = None
    ok = False
    try:
        voice = win32com.client.Dispatch("SAPI.SpVoice")
        for v in voice.GetVoices():
            desc = v.GetDescription()
            if "English" in desc or "en-US" in desc:
                if best is None or "Zira" in desc:
                    best = v
        if best is not None:
            voice.Voice = best
        voice.Rate = rate
        stream = win32com.client.Dispatch("SAPI.SpFileStream")
        stream.Open(str(out), 3, False)
        voice.AudioOutputStream = stream
        voice.Speak(text)
        stream.Close()
        ok = out.exists() and out.stat().st_size > 1000
    except Exception:
        ok = False
    finally:
        # COM nesneleri CoUninitialize'dan önce bırakılmalı
        voice = stream = best = v = None
        import gc
        gc.collect()
        pythoncom.CoUninitialize()
    return ok


def _sapi_powershell(text: str, out: Path, rate: int) -> bool:
    ps = ("Add-Type -AssemblyName System.Speech; $s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
          "$v=$s.GetInstalledVoices()|Where-Object{$_.VoiceInfo.Culture.Name -like 'en-*'}|Select-Object -First 1; "
          "if($v){$s.SelectVoice($v.VoiceInfo.Name)}; $s.Rate=%d; $s.SetOutputToWaveFile('%s'); $s.Speak('%s'); $s.Dispose()"
          % (rate, str(out).replace("'", "''"), text.replace("'", "''")))
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], timeout=30,
                       capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return out.exists() and out.stat().st_size > 1000
    except Exception:
        return False


def get_audio(text: str, slow: bool = False) -> Path | None:
    text = _safe(text)
    if not text:
        return None
    rate = -4 if slow else -1
    out = cache_path(text, rate)
    if out.exists():
        return out
    with _lock:
        if out.exists():
            return out
        if _sapi_win32(text, out, rate) or _sapi_powershell(text, out, rate):
            return out
    return None
