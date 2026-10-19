# -*- mode: python ; coding: utf-8 -*-
# PyInstaller tanımı: .venv\Scripts\python -m PyInstaller --noconfirm --clean yds_kocu.spec
from pathlib import Path

ROOT = Path(SPECPATH)

seed_files = ["pool.json", "pool_public.json", "suggestions.json", "confusables.json", "dict_offline.json", "osym_questions.json", "content.jsonl",
              "osym_examples.json", "ezberbozan.json", "osym_vocab_answers.json"]
datas = [(str(ROOT / "web"), "web"), (str(ROOT / "assets"), "assets")]
datas += [(str(ROOT / "seed" / f), "seed") for f in seed_files if (ROOT / "seed" / f).exists()]

hiddenimports = [
    "uvicorn.loops.asyncio", "uvicorn.protocols.http.h11_impl", "uvicorn.lifespan.off", "uvicorn.logging",
    "h11", "pystray._win32", "win32com.client", "pythoncom", "pywintypes", "qrcode.image.svg",
    "app.main", "app.server", "app.session", "app.planner", "app.projection", "app.score_model", "app.coach",
    "app.enrichment", "app.llm", "app.placement", "app.weekly", "app.analysis", "app.strategy", "app.optimizer",
    "app.interventions", "app.backup", "app.tts", "app.tray", "app.winutil", "app.runtime", "app.list_import",
    "app.icon_art",
]
excludes = ["torch", "torchvision", "torchaudio", "pandas", "scipy", "matplotlib", "playwright", "pytest",
            "tkinter", "IPython", "jupyter", "notebook", "wordfreq", "cv2", "sklearn", "tensorflow"]

a = Analysis(
    [str(ROOT / "yds_kocu_main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="YDSKelimeKocu",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(ROOT / "assets" / "app.ico"),
    version=str(ROOT / "tools" / "version_info.txt"),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="YDSKelimeKocu")
