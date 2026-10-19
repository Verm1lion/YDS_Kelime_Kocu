"""Üretilen tohum içerik parçalarını (seed/gen_output) doğrulayıp seed/content.jsonl'de birleştirir.

Kullanım: .venv\\Scripts\\python tools\\merge_seed.py
Geçersiz maddeler atlanır ve raporlanır (uygulama onları Gemini kuyruğuyla tamamlar).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import textutil as tu  # noqa: E402
from app.content_validate import validate_item  # noqa: E402

IN_DIR = ROOT / "seed" / "gen_input"
OUT_DIR = ROOT / "seed" / "gen_output"
TARGET = ROOT / "seed" / "content.jsonl"


def main() -> None:
    inputs = {}
    for f in sorted(IN_DIR.glob("batch_*.json")):
        for it in json.loads(f.read_text(encoding="utf-8")):
            inputs[it["lemma"]] = it
    good: dict[str, dict] = {}
    bad: dict[str, list[str]] = {}
    for f in sorted(OUT_DIR.glob("batch_*_part*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            lem = tu.norm_en(o.get("lemma", ""))
            inp = inputs.get(lem)
            if not inp:
                continue
            errs = validate_item(inp, o)
            if errs:
                bad[lem] = errs
                continue
            o["lemma"] = lem
            good[lem] = o
    missing = [l for l in inputs if l not in good]
    order = list(inputs)
    with TARGET.open("w", encoding="utf-8") as out:
        for lem in order:
            if lem in good:
                out.write(json.dumps(good[lem], ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"birleştirildi: {len(good)}/{len(inputs)} madde -> {TARGET}")
    print(f"geçersiz: {len(bad)}  eksik (üretilmemiş/geçersiz): {len(missing)}")
    for lem, errs in list(bad.items())[:20]:
        print("  ", lem, "|", "; ".join(errs[:3]))


if __name__ == "__main__":
    main()
