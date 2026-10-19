# YDS Kelime Koçu — ajanlar için notlar

Tek kullanıcılı, Windows'ta lokal çalışan YDS kelime ezber uygulaması: FastAPI + SQLite + vanilla JS arayüz (`web/`),
FSRS aralıklı tekrar (`fsrs`), sistem tepsisi (`pystray`), PyInstaller ile exe. Kullanıcı Türkçe konuşur; arayüz metinleri,
dokümanlar ve kod yorumları Türkçe. Ayrıntılar: README.md (kullanım), MIMARI.md (mimari ve algoritmalar).

## Kurulum ve doğrulama

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python -m pytest -q          # her değişiklikten sonra; tamamı geçmeli
.\.venv\Scripts\python run_app.pyw           # geliştirme modu, veri: data_dev\
```

Arayüz değişikliklerini `tools\ui_smoke.py` (Playwright + sistem Edge'i) ile, öğrenme/planlama değişikliklerini
`tools\simulate.py` (sanal öğrenci) ile kontrol et.

## Kurallar

- **Kullanıcının ilerlemesi asla kaybolmamalı.** Gerçek veri `%LOCALAPPDATA%\YDSKelimeKocu` altında; şema değişiklikleri
  yalnızca ekleme yapan migration'larla (`app/db.py`), sütun/tablo silme ya da yeniden adlandırma yok.
- Kullanıcının kendi girdileri (`meaning_user` vb.) tohum verisiyle üzerine yazılmaz.
- Gizli anahtar (Gemini) yalnızca `%LOCALAPPDATA%\YDSKelimeKocu\.env` içinde; koda, teste ya da dokümana yazma.
  Gemini yalnızca gerçekten gereken yerde çağrılır (plana giren ve içeriği eksik kelime, inatçı kelime müdahalesi,
  haftalık rapor); toplu arka plan üretimi ekleme.
- Çalışma akışı (README "Hızlı başlangıç"): her yeni kelime önce öğretilir, sonra kolaydan zora sınanır; partlar ≤15
  kelime; öğretme adımları FSRS'i etkilemez. Bu davranışları değiştirirken korunmalı.

## Repoda olmayan veri

"60 Günde Ezberbozan Kelimeler" kitabından türetilen dosyalar (`seed/pool.json`, `seed/ezberbozan.json`,
`tools/ezberbozan/`) telif nedeniyle yalnızca kullanıcının bilgisayarında. Bunlar yokken `config.pool_path()`
`seed/pool_public.json`'u (akıllı havuz: 2.200 kart + 110 öbek fiil + 1.300 yedek) kullanır ve kitap testleri
(`tests/test_ezberbozan.py`) atlanır. Bu dosyaları repoya ekleme.
