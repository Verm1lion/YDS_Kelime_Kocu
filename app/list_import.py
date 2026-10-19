"""Yeni kelime listesi içe aktarma (xlsx: aynı havuz biçimi veya 'kelime | anlam' sütunları; csv/txt: sekme/virgül/;)."""
from __future__ import annotations

import csv
import io
import tempfile
from pathlib import Path

from . import config, db
from . import textutil as tu
from . import words as W


def _rows_from_text(text: str) -> list[tuple[str, str]]:
    out = []
    sample = text[:2000]
    delim = "\t" if "\t" in sample else (";" if sample.count(";") > sample.count(",") else ",")
    for row in csv.reader(io.StringIO(text), delimiter=delim):
        if not row or not row[0].strip():
            continue
        w = row[0].strip()
        m = row[1].strip() if len(row) > 1 else ""
        if w.lower() in ("kelime", "word", "english", "ingilizce"):
            continue
        out.append((w, m))
    return out


def import_bytes(filename: str, data: bytes) -> dict:
    name = filename.lower()
    pairs: list[tuple[str, str]] = []
    if name.endswith((".xlsx", ".xlsm")):
        from . import importer
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            f.write(data)
            tmp = Path(f.name)
        try:
            parsed = importer.read_pool_xlsx(tmp)
            if parsed["items"]:
                pairs = [(it["display"], it.get("meaning") or "") for it in parsed["items"] if it["pool"] == "main"]
            else:
                import openpyxl
                wb = openpyxl.load_workbook(str(tmp), read_only=True, data_only=True)
                ws = wb.worksheets[0]
                for r in ws.iter_rows(values_only=True):
                    if r and r[0] and isinstance(r[0], str):
                        pairs.append((r[0].strip(), str(r[1]).strip() if len(r) > 1 and r[1] else ""))
        finally:
            tmp.unlink(missing_ok=True)
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("cp1254", errors="ignore")
        pairs = _rows_from_text(text)
    if not pairs:
        raise ValueError("Dosyada kelime bulunamadı")
    added, existing, ids = 0, 0, []
    for w, m in pairs:
        w = w.split("(")[0].strip()
        if not w or len(w) > 60:
            continue
        lemma = tu.norm_en(w)
        if db.q1("SELECT id FROM words WHERE lemma=? AND status='active'", (lemma,)):
            existing += 1
            continue
        ids.append(W.add_user_word(w, m or None, note="içe aktarma", enrich=False)["id"])
        added += 1
    from . import enrichment, projection
    enrichment.queue_missing(ids, reason="user_add")   # 8'lik paketler: kelime başına ayrı istek yok
    projection.invalidate()
    return {"added": added, "existing": existing, "total_rows": len(pairs)}
