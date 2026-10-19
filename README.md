# YDS Kelime Koçu

Bilgisayarında lokal çalışan, tek kullanıcılı kelime ezber uygulaması. Tek görevi: **60 Günde Ezberbozan Kelimeler**
listesini (1.078 hedef kelime + 149 bağlaç + 85 öbek fiil + 470 edat kalıbı) ve kitap dışından yalnızca ÖSYM'de en çok
çıkan 123 "garanti" kelimeyi **22 Kasım 2026 (2026-YDS/2)** gününe kadar kalıcı ve hızlı tanınır hale getirmek.
Memrise akıcılığında bir çalışma ekranı; arkada seni ölçen, hatalarını analiz eden ve yöntemini verilerine göre
değiştiren bir sistem (FSRS aralıklı tekrar, sınav tarihine duyarlı planlayıcı, kontrollü deneyler, koç bildirimleri).

## Hızlı başlangıç

1. Masaüstündeki **YDS Kelime Koçu** kısayoluna çift tıkla. Uygulama kendi penceresinde açılır (Edge uygulama
   penceresi, adres çubuğu yok). Program dosyaları: `%LOCALAPPDATA%\Programs\YDSKelimeKocu\YDSKelimeKocu.exe`
   (kurulum/güncelleme: `tools\install.ps1`; derlenmiş kopya: `dist\YDSKelimeKocu\`).
2. İlk açılışta **kurulum anketi** (süren, saatlerin, haftalık tekrar günün, sessiz saatler) ve ~15 dakikalık
   **seviye tespiti** gelir. Test, listedeki hangi kelimeleri zaten bildiğini bulur; bunlar 4 farklı türde kontrol
   sorusundan (TR→EN, boşluk doldurma, eş anlamlı, yazma) hızlı ve doğru geçerse bilinen sayılır, ilk tekrar ~2 gün sonra.
3. **Bugün** ekranındaki büyük **"Bugünkü çalışmaya başla"** düğmesine bas. Önce vadesi gelen tekrarlar ayrı bir blok
   olarak gelir; ardından yeni kelimeler **partlarla** öğrenilir: kitabın her günü iki part (**Gün N · A** ve **Gün N · B**,
   10'ar kelime), ardından o günün **Ek** partı (bağlaçlar, garanti kelimeler, öbek fiiller, edat kalıpları; ≤13). Part
   içinde 5'li paketler. Bir part bitince çıkabilirsin. Her yeni kelime önce **öğretilir**, sonra sınanır (Memrise gibi):
   1. **Tanıtım kartı:** anlam, telaffuz, kelimenin hemen altında **eş / yakın anlamlılar** (kitaptakiler önce; listede
      olanların Türkçesiyle), ÖSYM cümlesi, hafıza ipucu, kitap günü etiketi.
   2. **Bak · kapat · yaz:** kelimeye bak, dinle; hazır olunca gizlenir ve ezberden yazarsın (yazılış kafaya kazınır).
   3. **Eşleştir:** paketteki 4–7 kelime ↔ Türkçe anlamları; doğru çiftte kelime sesli okunur.
   4. **Eş anlamlısından bul:** eş/yakın anlamlılar verilir, az önce öğrendiğin kelimeler arasından hedefi seçersin.
   5. Sonra sınama, kolaydan zora: **dinle ve seç** → TR→EN test → YDS boşluk doldurma → harflerden yazma.
   6. Part bitince **pekiştirme turu:** o partta öğrendiğin her kelime karışık sırayla bir kez daha (dinle / TR→EN).
   Yeni öğrenilen kelimenin **ilk tekrarı en geç ertesi gün** gelir; sonraki günlerde yazma ve eş anlamlı ile sürer.
   Öğretme adımları (2–4) tekrar takvimini (FSRS) etkilemez; takvimi yalnızca sınama cevapları belirler. Yarım bıraktığın
   part kaldığı yerden sürer ama zor adıma atlamaz: başlanmış kelime önce **"Hatırlayalım"** kartıyla yeniden gösterilir,
   sonra kaldığı sınama basamağının iki gerisinden devam eder.
4. **Çalış** sekmesi part merkezidir: bütün partların (gün gün) durumu, vadesi gelen ve zayıf kelime sayıları. İstediğin
   partları seçip **karışık hızlı test** (süreli, 3 can) ya da **normal test** yapabilirsin. Aynı gün yapılan ek testler
   tekrar takvimini bozmaz (son 12 saatte görülen kart FSRS'e yeniden işlenmez).

Klavye: `1–5` (veya `A–E`) şık seçer · `Enter` devam · `0` bilmiyorum · tanıtım kartında `Boşluk` telaffuz ·
dinle ve seç sorusunda `Boşluk`/`R` tekrar dinlet · harf kutucuklarında doğrudan yaz, `⌫` geri al. Doğru cevapta otomatik geçer.

**Doğru cevap sesli söylenir:** her alıştırmada (dinle ve seç, test, boşluk doldurma, yazma, eş anlamlı…) cevabı verdiğin
anda doğru kelime sesli tekrar edilir (boşlukta cümleye giren biçim; yanlışta da doğrusu). Doğru cevapta sonraki soruya
okuma bitince geçilir. Ayarlar → "Cevaplayınca doğru cevabı sesli söyle" ve "Dinle ve seç alıştırması" (sessiz ortamda
kapatınca yerine okumalı EN→TR test gelir). Tekrarlarda EN→TR payının yarısı da dinle ve seç olarak gelir.

**Boşluk doldurmadan sonra "gerçek cevap" paneli** her zaman açılır (doğru da bilsen): tam cümle, Türkçe çevirisi (kelimenin
karşılığı vurgulu), neden o kelime (anlam + boşluğun önündeki kelimeden biçim ipucu: "are ----" → -ing, "have ----" → V3,
"to ----" → yalın…; gerçek ÖSYM sorularında ipucu notu) ve diğer şıkların anlamları. `Enter`/`Boşluk` ile hemen geçilir.

**Ses ve efektler:** doğru/yanlış sesi, bitki büyüyünce ve kelime/part tamamlanınca kısa melodi (tarayıcıda üretilir,
çevrimdışı; Ayarlar → Ses efektleri, ses düzeyi, "Dinle"). Boşluk doldurmada doğru kelime boşluğa düşerek yerleşir
(yanlışta seçtiğin üstü çizili kalır); yazma ve harflerden kurmada yanlışta doğru kelime harf harf açılır (tutan harf yeşil);
doğru cevapta küçük parıltı. İşletim sisteminde "hareketi azalt" açıksa animasyonlar kapanır.

## Kelime listesi: 60 Günde Ezberbozan + garanti kelimeler

> **Repo notu:** kitaptan türetilen dosyalar (`seed/pool.json`, `seed/ezberbozan.json`, `tools/ezberbozan/`) telif
> nedeniyle GitHub'da yok, yalnızca yerel kurulumda. Bunlar yoksa uygulama `seed/pool_public.json` (akıllı havuz:
> 2.200 kart + 110 öbek fiil + 1.300 yedek) ile çalışır ve kitap testleri atlanır.

- Kaynak: kitabın sayfa fotoğrafları (`60_GUNDE_EZBERBOZAN_KELIMELER_GUNCEL_BASIM.zip`) yazıya döküldü
  (`tools/ezberbozan/raw/`), `tools/build_ezberbozan.py list|gen|apply` ile uygulamaya alındı (`seed/ezberbozan.json`).
- 1.–54. gün: 1.078 hedef kelime (kitap sırasıyla; günün ilk 6 kelimesinin kitaptaki Türkçe karşılığı ve eş/yakın
  anlamlıları fotoğraflarda var, kalanların içeriği uygulama için üretildi). 55. gün öbek fiiller (85), 56. gün edat
  kalıpları (470; "charge sb with sth" → `charge ... with`), 57. gün bağlaç tablosu (149; and/but/or hariç). Ek bölümler
  günlerin arasına dağıtılır: bağlaçlar kitaptaki anlam gruplarıyla (sebep, sonuç, zıtlık…), kalıplar ve öbek fiiller
  ÖSYM metinlerindeki sıklığa göre (önemliler önce).
- Kitap dışından yalnızca **garanti** kelimeler (123): ÖSYM tam sınav metinlerinin en az yarısında geçen ya da sınavların
  en az %10'unda şık olarak çıkan kelimeler ve ÖSYM'de en az 2 kez şık olarak sorulan öbek fiiller.
- Eski listenin kalanı (≈2.800) silinmedi, **yedekte**: Ayarlar → "Yedek kelimeleri de plana al".
- Veriyle kontrol (`tools/ezberbozan/osym_vocab_answers.json`, 2012–2026 ÖSYM kelime sorusu cevapları, 45 kelime):
  eski 2.310'luk liste cevapların %82'sini, kitabın 54 günü %60'ını, kitabın tamamı %64'ünü, kitap + garanti %71'ini
  kapsıyor. Tam sınav metinlerinde az bilinen (zipf < 4,5) kelimelerin eski liste %24'ünü, kitap + garanti %15–16'sını
  kapsıyor. Kitap kısa ve sık kelimelerden oluştuğu için öğrenilen kelime başına kazancı daha yüksek; puan modeli kapsama
  oranını etkin listeye göre yeniden ölçer (`score_model.list_covers_asked`).

## Arka plan servisi (koç)

- Uygulama sistem tepsisinde (saatin yanında, turuncu kitap-fide simgesi) çalışır. Bilgisayar açılınca otomatik başlar
  (Başlangıç klasöründe kısayol; Ayarlar'dan veya tepsi menüsünden kapatılabilir).
- Sabah günün planını, seçtiğin saatlerde giderek netleşen hatırlatmaları gönderir; sessiz saatlere uyar.
  Mesajlar hep somut sayıya dayanır (ör. "planın %40'ı bitti; kalan 25 dk'yı yapmazsan yarınki yük 45 dk'ya çıkıyor").
- Tepsi menüsü: Aç · Bugünkü çalışmaya başla · Hızlı tekrar · Analiz · Bildirimler · Başlangıçta çalıştır · Yedek al · Çıkış.

## Ekranlar

| Ekran | İçerik |
|---|---|
| **Bugün** | Başla düğmesi; 4 sayı (sınava kalan gün, öğrenilen/toplam, bugünkü plan %, sınav günü tahmini hakimiyet); hedef çizgili projeksiyon grafiği; planın gerekçesi; gerçekçilik kontrolü ve seçenekleri; seri takvimi; koç mesajları |
| **Çalış** | Dikkat dağıtmayan odak modu: tanıtım kartı, dinle ve seç, EN→TR, TR→EN, harflerden kurma, yazma, YDS boşluk doldurma, eş anlamlı, bağlamda anlam, ayırt etme, inatçı kelime kartı; Hızlı tekrar (süreli, 3 can), Zor kelimeler, Haftalık YDS testi |
| **Analiz** | Projeksiyon, çalışma takvimi (ısı haritası), günlük süre ve doğruluk, hata türleri, kelime özelliklerine/saate/oturum dakikasına/haftanın gününe göre performans, hız trendi, en zor 20 kelime, karışıklık çiftleri, öğrenme maliyeti, müdahaleler, strateji deneyleri ve günlüğü (geri alınabilir), haftalık rapor, deneme sınavları |
| **Kelimeler** | Hızlı ekleme (çevrimdışı sözlükle anlam önerisi), liste/filtre, kelime ayrıntısı (anlamını düzenle, örnek/ipucu/eş anlam düzenle, "bu bilgi yanlış" işareti), öneriler (eksik bağlaç ve öbek fiiller), liste içe aktarma |
| **Ayarlar** | Sınav tarihi, hedefler, süreler, saatler, tema, Gemini anahtarı, telefondan erişim (PIN + QR), yedekler ve CSV dışa aktarma |

Sağdaki **YDS puan tahmini** paneli her ekranda (çalışma ekranı hariç) durur ve **canlıdır**: her cevap, deneme sonucu ve
ayar değişikliğinden sonra yeniden hesaplanır (panel dakikada bir tazelenir). Eşik seçilebilir (50+ … 70+) ve şunları gösterir:
- **Bugün sınava girsen**, **sınav günü bu tempoyla**, **plana uyarsan** olasılıkları ve medyan puanlar;
- **İleriye dönük**: "+500 kelime öğrenirsen %…" gibi kilometre taşları (bu tempoyla ne zaman ulaşacağınla), listenin tamamı,
  "dil bilgisi/okuma yarım seviye artarsa" ve öğreneceğin kelime sayısına göre olasılık eğrisi.

Kelime bilgin uygulamada ölçülür (seviye testi + her cevap). Dil bilgisi/okuma becerin ölçülmez: önce **Ayarlar → İngilizce
seviyem**den (öz değerlendirme) başlar, **deneme sonucu** girdikçe (o günkü kelime bilginle değerlendirilerek) ve haftalık testteki
gerçek ÖSYM dil bilgisi sorularıyla gerçek performansına yaklaşır. Tahminin en büyük belirsizliği buradadır; deneme girmek onu en çok
daraltır.

## Gemini

LLM yalnızca içerik üretimi ve rapor metni için kullanılır; planlama ve puanlama tamamen deterministik koddur.
İnternet veya kota yokken çekirdek özelliklerin hepsi çalışır.

- Anahtar `%LOCALAPPDATA%\YDSKelimeKocu\.env` dosyasında (`GEMINI_API_KEY=...`). Ayarlar → Gemini'den değiştirilebilir.
- **Ücretsiz model zinciri** (4 Ekim 2026'da senin anahtarınla test edildi): `gemini-3.5-flash` (en iyi Türkçe ipucu/çeviri) →
  `gemini-flash-latest` → `gemini-2.5-flash` → `gemini-3.5-flash-lite`. Bir model yoğunluk (503) veya kota (429) verirse
  otomatik olarak sıradakine geçilir; her modelin ücretsiz kotası ayrıdır. Günlük kotası dolan model Pasifik gece
  yarısına (Türkiye saatiyle ~10:00/11:00) kadar dinlendirilir. Bu modeller yanıtlamadan önce "düşünür" ve düşünme de
  token bütçesinden yer; yanıt bütçe sınırında kesilirse aynı model bir kez geniş bütçeyle yeniden denenir.
  İstersen `.env`'e `GEMINI_MODEL=...` yazarak ilk modeli değiştirebilirsin.
- Listenin tamamı için içerik (3.585 madde × 3–4 örnek cümle + çeviri, eş/zıt anlam, kelime ailesi, karıştırılanlar,
  Türkçe hafıza ipucu, kök/köken) **uygulamayla birlikte gelir** ("doğrulanmamış" etiketiyle). Ezberbozan listesinin
  eksik 1.070 maddesi (kitap kelimeleri, bağlaçlar, edat kalıpları, öbek fiiller) `seed/GEN_INSTRUCTIONS_EZB.md` ile
  üretildi: edat kalıplarında hafıza ipucu edata, bağlaçlarda kullanım kuralına (although + cümle / despite + isim) odaklı.
  Kitaptaki dizgi hataları öğretilmez: "emphasize on" → emphasis on, "out of question" → out of the question,
  "on route" → en route; kitabın açıkça yanlış eş anlamlıları (invent ≠ discover gibi) çıkarıldı.
- **Gerçek ÖSYM cümleleri:** kelime ÖSYM sınavlarında geçtiyse (2012 ÜDS, 2013–2020 YDS kitapçıkları ve yayımlanan
  sorular, 2021–2026 analiz tablosu) o sınav cümlesi de karta eklenir — kelime bir sorunun **doğru cevabıysa** boşluğu
  doğru şıkla doldurulmuş soru cümlesi önce gelir. "ÖSYM · YDS 2013 İlkbahar · 1. soru" etiketiyle görünür; tanıtım
  kartında, bağlam sorusunda ve boşluk doldurmada önce gerçek cümleler kullanılır (sonra üretilenlerle dönüşümlü).
  İngilizcesi özgündür, Türkçesi yapay zekâ çevirisidir. Üretim: `tools\build_osym_examples.py` (ham metin → ajanlarla
  cümle kurma → ham metne ve cevap anahtarına karşı doğrulama → eşleme → çeviri + anlam kontrolü → `seed\osym_examples.json`).
  Liste değişince `match2` yalnızca cümlesi olmayan etkin maddeleri eşler (hazır çeviriler yeniden kullanılır, kelimenin
  cümlede başka anlamda geçtiği eşleşmeler elenir): Ezberbozan planında 1.902 maddenin 901'inde gerçek ÖSYM cümlesi var
  (toplam 3.432 cümle).
- Gemini yalnızca **plana giren ama içeriği olmayan** kelimeler için çalışır: deneme sınavından eklediğin ya da yedekten
  çektiğin kelimeler, onayladığın öneriler, içe aktardığın listeler ve "yedeği plana dahil et" açılırsa yedek kartlar.
  Kelime plana girdiği an kuyruğa alınır (8'lik paketler; senin eklediklerin önce). Bu içerik olmadan o kelimede
  YDS tipi boşluk doldurma ve eş anlam alıştırması kurulamaz, yalnızca anlam soruları kalır.
- Ayrıca **inatçı kelimeler** için mevcut ipucu tutmadığında yeni ipucu/kök/bağlam ve **haftalık rapor** anlatımını yazar
  (anahtar yoksa bunların hazır içerikli/şablon sürümü kullanılır). Plana girmemiş yedek kartlar için istek gönderilmez.
- Sınırlar: dakikada 8, günde 200 istek (Ayarlar'dan değiştirilebilir).

## Telefondan erişim

Ayarlar → Telefondan erişim: PIN belirle, "Erişim açık" seç. Aynı Wi-Fi'deki telefonda gösterilen adresi aç
(QR kod da var). Windows Güvenlik Duvarı ilk seferde izin isterse **Özel ağlar**a izin ver.

## Veri, yedek, güncelleme

- Veri: `%LOCALAPPDATA%\YDSKelimeKocu\` (veritabanı `yds_kocu.db`, yedekler `yedekler\`, ses önbelleği `ses\`, günlük `kayitlar\`).
- Her gün otomatik yedek (son 14 kopya); Ayarlar'dan anında yedek ve tüm veriyi CSV (zip) olarak indirme.
- Ham olay kaydı: her cevap için kelime, alıştırma türü, verilen cevap, doğru/yanlış, ilk tuşa kadar süre, toplam süre,
  ipucu, puan, hata türü, zaman damgası, oturum. Tüm analizler bu kayıttan yeniden hesaplanır.
- Yeni sürüm: exe'yi derle ve `powershell -ExecutionPolicy Bypass -File tools\install.ps1` çalıştır (çalışan uygulamayı
  kapatır, yeni dosyaları kopyalar, başlatır). Veri klasörüne dokunulmaz; şema değişiklikleri yalnızca ekleme yapan
  migration'larla ve öncesinde yedek alınarak uygulanır. Kısayollar her açılışta güncel exe yoluna yenilenir.

## Geliştirici notları

```powershell
cd YDS_Kelime_Kocu
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python run_app.pyw                 # geliştirme modunda çalıştır (veri: data_dev\)
.\.venv\Scripts\python -m pytest -q                # birim testleri
.\.venv\Scripts\python tools\simulate.py           # sanal öğrenci simülasyonu -> SIMULASYON_RAPORU.md/.html
.\.venv\Scripts\python tools\ui_smoke.py <klasör>  # arayüz duman testi (sistem Edge'i ile), ekran görüntüleri
.\.venv\Scripts\python -m PyInstaller --noconfirm --clean yds_kocu.spec   # exe -> dist\YDSKelimeKocu\
```

Tohum verisini xlsx'ten yeniden üretmek: `tools\build_seed.py` (pool, öneriler, karışabilir çiftler, çevrimdışı sözlük,
ÖSYM soruları, `VERI_RAPORU.md`); üretilen içeriği birleştirmek: `tools\merge_seed.py`.

Ortam değişkenleri: `YDS_DATA_DIR` (veri klasörü), `YDS_PORT` (varsayılan 8765; telefon 8766), `YDS_NO_SHORTCUTS`.

Mimari, algoritmalar ve faz planı: **MIMARI.md**. Veri incelemesi: **VERI_RAPORU.md**. Simülasyon: **SIMULASYON_RAPORU.md**.

Lisans notu: Nunito yazı tipi SIL Open Font License 1.1 ile dağıtılır. Örnek cümleler ve ipuçları yapay zekâ ile
üretilmiştir ("doğrulanmamış"); ÖSYM soruları yalnızca kişisel çalışma içindir.
