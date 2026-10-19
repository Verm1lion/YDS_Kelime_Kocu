# Mimari ve Faz Planı — YDS Kelime Koçu

## 1. Teknoloji seçimi (ve neden)

| Katman | Seçim | Gerekçe |
|---|---|---|
| Çekirdek | **Python 3.10 + FastAPI + uvicorn** | Önerilen yığın; planlama/analiz/simülasyon için numpy ile aynı dilde. Gereksiz çatı yok. |
| Veri | **SQLite (WAL)**, düz `sqlite3` | Tek kullanıcı, tek dosya, kolay yedek. ORM yok; şema `db.py`'de, yalnızca ekleyen migration'lar. |
| Aralıklı tekrar | **py-fsrs 6.3 (resmî)** + aynı formüllerin **numpy** karşılığı | Tekil tekrarlar resmî kütüphaneyle; projeksiyon/simülasyon/optimizasyon için vektörel sürüm (testle birebir eşitliği doğrulanır). torch gerektiren resmî optimizer yerine numpy optimizasyonu → exe küçük kalır. |
| Arayüz | **Tarayıcıda açılan tek sayfa** (vanilla ES modules, SVG grafikler, Nunito) | Derleme adımı yok, çevrimdışı; Edge "uygulama penceresi" ile masaüstü uygulaması gibi açılır; telefonda da çalışır. |
| Arka plan | **pystray** tepsi simgesi + Windows bildirimleri, Başlangıç klasörü kısayolu | Hafif; ayrı servis kurulumu ve yönetici izni gerektirmez. |
| Telaffuz | **Windows SAPI** (Zira/David) → WAV önbelleği; yedek olarak tarayıcı sesi | Tam çevrimdışı. |
| LLM | **Gemini REST** (urllib), kalıcı iş kuyruğu, ücretsiz model zinciri (3.5-flash → flash-latest → 2.5-flash → 3.5-flash-lite) | Yalnızca içerik/rapor metni; anahtar `.env`'de; 429/503'te model değiştirir, günlük kota dolan modeli Pasifik gece yarısına kadar dinlendirir; düşünme token'larıyla kesilen yanıtı (MAX_TOKENS) aynı modelde bir kez geniş bütçeyle yeniden dener; yalnızca plana giren içeriksiz kelimeler (kullanıcının eklediği önce) ve müdahale/rapor için istek açar; internet yoksa kuyrukta bekler. |
| Paket | **PyInstaller tek klasör** (`dist\YDSKelimeKocu\YDSKelimeKocu.exe`, özel simge) | Tek klasör: hızlı açılış, daha az antivirüs yanlış alarmı. |

Veri `%LOCALAPPDATA%\YDSKelimeKocu` altında: exe güncellenince ilerleme kaybolmaz.

## 2. Bileşenler

```
YDSKelimeKocu.exe
 ├─ runtime: uvicorn 127.0.0.1:8765 (+ isteğe bağlı 0.0.0.0:8766, PIN korumalı)
 ├─ coach.loop (dakikada bir): gün dönümü → plan + yedek; sabah planı, hatırlatmalar, tempo/saat uyarıları,
 │      haftalık işler (FSRS optimizasyonu, hedef hatırlama seçimi, oturum süresi uyarlaması, haftalık rapor),
 │      günlük işler (deney kararları, müdahale etkisi, eksik içerik kuyruğu)
 ├─ enrichment.worker_loop: Gemini iş kuyruğu
 └─ tray: menü + bildirim
web/ (index.html, js/app.js, study.js, analysis.js, words.js, settings.js, charts.js, plant.js)
app/
 ├─ db.py            şema + migration + ayarlar          ├─ session.py      oturum motoru (kuyruk, paketler, requeue)
 ├─ seed_loader.py   tohum verisi yükleme                ├─ exercises.py    alıştırma yükleri
 ├─ words.py         kelime dizini, hızlı ekleme         ├─ distractors.py  akıllı çeldiriciler
 ├─ cards.py         FSRS durumları, sınav penceresi     ├─ grading.py      cevap değerlendirme + hata türü
 ├─ fsrs_engine.py   py-fsrs sarmalayıcı + VecFSRS       ├─ rating.py       otomatik puan + hız kalibrasyonu
 ├─ simcore.py       vektörel ileri simülasyon           ├─ planner.py      günlük plan, çığ koruması, gerçekçilik
 ├─ projection.py    sınav günü projeksiyonu             ├─ score_model.py  YDS puan olasılıkları
 ├─ placement.py     uyarlamalı seviye testi             ├─ strategy.py     deneyler + strateji günlüğü
 ├─ interventions.py inatçı kelime müdahaleleri          ├─ analysis.py     tüm analizler (olay kaydından)
 ├─ optimizer.py     FSRS parametre optimizasyonu        ├─ weekly.py       haftalık test + rapor
 ├─ llm.py / enrichment.py  Gemini + iş kuyruğu          ├─ coach.py        bildirim mantığı + seri
 └─ backup.py, tts.py, auth.py, winutil.py, tray.py, server.py, main.py
```

## 3. Veri modeli (özet)

- `words`: lemma, listedeki anlam (`meaning_src`, **asla ezilmez**), kullanıcı anlamı (`meaning_user`, öncelikli), üretilmiş
  anlam, tür, seviye, öncelik/sıra, ÖSYM kanıtı, wordfreq Zipf, kapsama ağırlığı, havuz (main/reserve/user/suggestion).
- `cards`: FSRS durumu (py-fsrs JSON), S/D, vade günü (sınav penceresine sıkıştırılmış), merdiven basamağı (0–6),
  tekrar/unutma/yanlış sayıları, tanıtım/öğrenilme/kalıcılık zamanları, doğrulama durumu.
- `events`: **ham olay kaydı** — her cevap: kelime, alıştırma, yön, istem, verilen/beklenen cevap, doğru/yanlış, sonuç
  (typo/form/dontknow/timeout/override), ilk tuşa kadar süre, toplam süre, ipucu, puan, hata türü, karıştırılan kelime,
  basamak önce/sonra, FSRS önce/sonra, R, geçen gün, cihaz, oturum dakikası. "Aslında biliyordum" ayrı bir olay olarak
  kaydedilir; asıl olay `overridden` işaretlenir.
- `activity`: aktif süre (60 sn işlemsizlik veya arka planda sayaç durur; 15 sn'lik nabızlar).
- İçerik: `examples`, `mnemonics`, `word_info` (kaynak + doğrulandı + işaretlendi alanlarıyla), `confusables`.
  `examples.source='osym:<sınav · soru>'`: gerçek ÖSYM cümlesi (`seed/osym_examples.json`, dosya özeti değişince eksikler
  eklenir); örnek seçimi ve boşluk doldurma bunları dönüşümde bir tur önde tutar.
- Strateji: `experiments`, `exp_assignments`, `strategy_log`, `fsrs_params`; `interventions`; `daily_plans`,
  `projections`, `notifications`, `llm_jobs`, `weekly_reports`, `mock_exams`, `placement`, `flags`.

## 4. Öğrenme akışı

1. **Tanıtım kartı**: kelime, telaffuz (normal/yavaş), anlam, YDS anlamları, örnek cümle (dönüşümlü), hafıza ipucu
   (senin mem'in her zaman önce; değilse deneydeki tür: çağrışım / köken / bağlam), kelime ailesi, ÖSYM kanıtı.
   "Bunu zaten biliyorum" ve seviye testinin ön testi → 4 farklı türde doğrulama (TR→EN, YDS boşluk doldurma, eş anlamlı,
   yazma); hepsi hızlı ve doğruysa bilinen sayılır ve Good ile başlar (ilk tekrar ~2 gün; eski Easy ~8 gün boşluk bırakıyordu).
2. **Partlar** (`parts.py`): yeni kelimeler en fazla 15 kelimelik kalıcı gruplarla öğrenilir. Part, başlanırken plan
   sırasındaki sıradaki ≤15 kelimeyle (seviye testinin "muhtemelen biliyor" dediği kelimeler dâhil; bunlar 4 kontrolle
   doğrulanır) oluşur; kelimenin plan grubu varsa (`features.part_group`: "Gün 3 · A" / "Gün 3 · B" / "Gün 3 · Ek")
   part o grupla sınırlanır ve grubun adını taşır (`parts.title`, şema v4); yarım kalan part yenisinden önce bitirilir. Sürdürmede başlanmış kelime (state ≥1, basamak 1–3)
   önce "Hatırlayalım" tanıtım kartıyla gelir (yeni sayılmaz, "zaten biliyorum" yok), sonra basamak max(0, b−2)'den
   kolaydan zora sürer; kartın basamağı düşürülmez (stage = max(eski, rung+1)). Günlük oturum ("daily")
   artık yalnızca vadesi gelen tekrarlardır; tekrar yoksa doğrudan sıradaki part açılır. Seçilen partların kelimeleriyle
   `part_test` (normal) ve `quick` (süreli, 3 can) testleri; son 12 saatte görülen kart bu testlerde FSRS'e işlenmez.
   Part sisteminden önce öğrenilen kelimeler ilk açılışta tanıtım sırasıyla partlara yerleştirilir.
   **Oturum içi merdiven** (5'li paket, genişleyen aralıklarla iç içe), kullanıcı isteğiyle önce öğretim (Memrise gibi),
   sonra kolaydan zora sınama: tanıtım (eş/yakın anlamlılar kelimenin yanında; `words.synonyms_for`, kitaptakiler önce)
   → **öğretme katmanları** `TEACH_RUNGS` = bak·kapat·yaz (`look_write`) → eşleştir (`match`, paket düzeyinde: paketin
   bütün kelimeleri bak·kapat·yaz'ı geçince tek öğe; 4'ten az kelimede önceden öğrenilenlerle tamamlanır, tek çiftse atlanır;
   kelime başına hata sayısı döner, 2+ hatada tanıtım yeniden) → eş anlamlısından bul (`syn_pick`, çeldiriciler paket
   kelimeleri; eş anlamlısı yoksa EN→TR) → **sınama basamakları** `TEST_RUNGS` = dinle ve seç (`listen`) → TR→EN → YDS
   boşluk doldurma → harflerden kur. Öğretme katmanları FSRS'e işlenmez ve kartın basamağını ilerletmez: `cards.stage`
   1–4 = geçilen sınama basamağı (bitki, part bitişi, analizler bu ölçeği kullanır). Sınamada 3 hatada bir basamak geri
   iner ama öğretme katmanına düşmez. Part sonunda **pekiştirme turu** (`consolidate`: merdiveni bitiren her kelime bir kez,
   dinle/TR→EN dönüşümlü; FSRS'e işlenir, yanlışta TR→EN ile bir kez daha). Merdiveni bitiren kelimenin ilk tekrarı en geç
   ertesi gün (`cards.cap_first_review`). FSRS'e işlenen oturum içi cevap = `FSRS_STEPS_PER_NEW` (4 + pekiştirme) =
   `simcore.LEARN_STEPS`. `listen_exercises` kapalıysa dinle ve seç yerine EN→TR.
   Her cevapta `say` alanı döner (şıklı türlerde doğru şık; EN→TR/dinle/yazmada kelime) ve arayüz bunu sesli okur
   (`speak_answers`); otomatik geçiş okuma bitince (en geç 3 sn) olur.
   Yanlışta kelime 3 soru sonra tekrar; 2. ve 4. hatada tanıtım kartı yeniden. Tanıtılıp hiç adımı yapılmadan oturumu
   kapanan kelime 1 saat sonra yeniden yeni kelime sayılır (askıda kalmaz).
3. **Sonraki tekrarlar** merdiveni sürdürür: L5 TR→EN yazma → L6 eş anlamlısı. Merdiven bitince karışım (deneyle
   uyarlanır): cloze, EN→TR, bağlam, yazma, eş anlamlı, ayırt etme; EN→TR payının yarısı dinle ve seç olarak sorulur.
   Unutulan kelime oturum içinde 4 soru sonra yeniden sorulur (FSRS yeniden öğrenme adımı).
4. **Karışabilir kelimeler** (yazılışı benzer 441 çift, anlamı çakışan 3.023 çift) aynı pakette/yerleşmemiş eşiyle
   birlikte öğretilmez; ikisi de oturunca (basamak ≥4, S ≥5 gün) "ayırt etme" alıştırması gelir.
5. **Çeldiriciler**: aynı tür, benzer yazılış (bigram/OSA), geçmişte karıştırdıkların, yakın sıklık; anlamı çakışan veya eş
   anlamlı adaylar elenir. Kelime ilerledikçe ve deneydeki zorluk koluna göre benzerlik ağırlığı artar.

### Otomatik puanlama (FSRS)

| Durum | Puan |
|---|---|
| yanlış / bilmiyorum / süre doldu | Again (1) |
| doğru ama yavaş (kişisel %85 dilimi üstü) veya ipuçlu | Hard (2) |
| doğru ve hızlı | Good (3) |
| zor modda (yazma, boşluk doldurma, eş anlamlı, ayırt etme, ÖSYM) çok hızlı (kişisel %15 dilimi) | Easy (4) |
| 1–2 harf yazım hatası | yanlış sayılmaz, en fazla Good |

Hız eşikleri her alıştırma türü için kişisel sürelerinden (son 300 doğru cevap; seviye testinden öncel) kalibre edilir;
cümleli alıştırmalarda okuma süresi düşülür.

## 5. Sınav tarihine duyarlı zamanlama

- Hiçbir tekrar sınav gününe veya sonrasına planlanmaz.
- Son haftadan **önce** yapılan bir tekrarın vadesi sınavı geçiyorsa son haftanın en az yüklü gününe taşınır
  (= tüm listenin hızlı turu); son hafta **içinde** yapılan tekrardan sonra vade sınavı geçiyorsa yeni tekrar konmaz.
- Son haftada hedef hatırlama en az %95'e çıkar (zayıf kelimeler sıklaşır); yeni kelime gelmez.

## 6. Planlayıcı

- Kalan yeni kelimeler, kalan öğrenme günlerine (son hafta ve haftalık tekrar günleri hariç) o günün süre bütçesiyle
  orantılı bölünür (2 günlük tampon). Gelecek yük, **vektörel FSRS Monte Carlo** ile tahmin edilir.
- Bütçeye sığmıyorsa **gerçekçilik kontrolü**: gereken süre, yedeğe alınacak kelime sayısı veya ulaşılabilir hedef oranı
  seçenek olarak sunulur; varsayılan olarak bütçeye sığan en yüksek hız uygulanır.
- **Tekrar çığı koruması**: vadesi gelen tekrarlar bütçeyi aşarsa yeni kelime sıfırlanır, en riskli N tekrar bugün, kalan
  risk sırasıyla ertesi günlere yayılır (kaçırılan gün sonrası yığılma yok).
- Maliyetler (kelime başı cevap sayısı, saniye/cevap, yeniden öğrenme oranı) kendi verinle Bayesçi güncellenir.
- Haftalık: hedef hatırlama oranı (0,85–0,94) simülasyonla seçilir; değişiklik strateji günlüğüne yazılır.

## 7. Ölçüm ve uyarlama

- **Hata türleri**: hatırlayamama, karıştırma (hangi kelimeyle), yazım hatası, yakın anlam, yön farkı, bağlamda
  tanıyamama, yavaş doğru, şans doğrusu (seçmelide doğru, 3 gün içinde yazmada yanlış), biçim (aile biçimi).
- **Özellik/zaman analizi**: tür, uzunluk, soyut/somut, phrasal, kök-ek, CEFR, sıklık katmanı; saat, oturum dakikası, gün.
- **İnatçı kelime** (4, 7, 10… hata): yeni ipucu, kök/köken, karıştığı kelimeyle karşılaştırma, yeni bağlamlar, alıştırma
  değişimi (+ Gemini ile yeni içerik). Etki: önceki 8 cevap vs sonraki 3–6 cevap.
- **Deneyler**: paket büyüklüğü (4/5/7), ipucu türü, çeldirici zorluğu, alıştırma karışımı. Dengeli rastgele atama;
  ölçüt ertesi gün hatırlama (doğru ve yavaş değil). Her kolda ≥40 sonuç olmadan karar yok; P(en iyi) ≥ 0,95 ve
  fark ≥ 3 puan ise benimsenir, gerekçesi ve verisiyle günlüğe yazılır, bildirilir, tek tıkla geri alınır.
- **FSRS optimizasyonu** (haftalık): ≥400 gün aşırı tekrar ve ≥100 kelime olunca; zaman bazlı doğrulamada kayıp ≥%1
  iyileşirse benimsenir ve tüm kartlar olay kaydından yeniden hesaplanır.
- **Oturum süresi**: oturum dakikasına göre doğruluk düşüşü varsa mola aralığı ona göre ayarlanır; oturum içinde son 5 dk
  cevap süreleri %40+ uzarsa mola önerilir.

## 8. Projeksiyon ve puan tahmini

- **Sınav günü hakimiyeti**: her kelimenin sınav günündeki hatırlanma olasılığı (FSRS R), iki senaryoda: son 7 günün
  temposu ve plana uyulması. Tanıtılmamış kelimeler için seviye testi (yoksa CEFR) taban olasılığı.
- **YDS puanı**: 10 bölümlü model (kelime 6, dil bilgisi 10, cloze 10, cümle tamamlama 10, çeviri 6, okuma 20, diyalog 5,
  yakın anlam 4, paragraf tamamlama 4, akışı bozan 5). Kelime soruları liste kelimelerinin ÖSYM şık olasılığıyla ağırlıklı
  hatırlanmasına, okuma tipi bölümler metin kapsamasına (xlsx kapsama eğrisi: %92,1 → %96,9) ve genel beceriye (θ) bağlı.
  θ önseli öz değerlendirmeden (Ayarlar → İngilizce seviyem: A2 −1,3 · A2–B1 −0,8 · B1 −0,3 · B1–B2 0,15 · B2 0,6 · C1 1,1;
  sd 0,6; kalibrasyon: B1 + tipik bugünkü kelime ≈ 47, + listenin tamamı ≈ 54 puan — xlsx'in "B1 + liste ≈ 55" varsayımı).
  Sonsal: deneme sonuçları (her biri denemenin günündeki kelime durumuyla: sonradan öğrenilen kelimeler öğrenilmemiş sayılır)
  ve haftalık testteki gerçek ÖSYM dil bilgisi soruları. Belirsizlik Monte Carlo ile: θ, kapsama etkisi, kelime
  projeksiyonu koşuları, soru başına şans.
- **Senaryolar** (ortak rastgele sayılarla; farklar gürültü değil): bugün girsen · sınav günü bu tempoyla · plana uyarsan ·
  "+250/+500/+1000/+1500 kelime / listenin tamamı" (plan sırasıyla, öğrenilen kelime sınav günü plandaki tipik
  hatırlamayla) ve tempoya göre ulaşma tarihi · dil bilgisi/okuma yarım seviye artarsa · kelime sayısı → olasılık eğrisi.
  Sonuç, girdiler (son cevap, denemeler, seviye, hedef, projeksiyon) değişmedikçe önbellekten döner; panel dakikada bir
  sessizce tazelenir.

## 9. Faz planı ve durum

| Faz | İçerik | Durum |
|---|---|---|
| **1 — Çekirdek** | İçe aktarma, tohum içerik (2.520 madde), kurulum + seviye testi, öğrenme akışı + FSRS + otomatik puan, olay kaydı, günlük plan + Bugün ekranı, yedekleme, exe | ✅ |
| **2 — Analiz** | Hata türleri, süre kalibrasyonu, inatçı kelimeler, haftalık tekrar günü + ÖSYM soruları, analiz ekranı | ✅ |
| **3 — Koç** | Tepsi servisi, bildirimler, sınav günü projeksiyonu, yeniden planlama, gerçekçilik kontrolü, seri ve zor gün modu | ✅ |
| **4 — Kendini geliştirme** | Strateji deneyleri, FSRS kişisel optimizasyonu, LLM müdahaleleri, haftalık rapor, telefondan erişim (PIN) | ✅ |

Doğrulama: `tests/` (63 birim/entegrasyon testi), `tools/simulate.py` (sanal öğrenci, 3 senaryo), `tools/ui_smoke*.py`
(sistem Edge'i ile arayüz testleri, JS hatası denetimi).
