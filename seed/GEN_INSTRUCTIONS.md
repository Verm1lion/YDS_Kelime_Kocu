# Tohum içerik üretimi — talimatlar

Bağlam: Türkiye'deki YDS sınavına (ÖSYM, akademik İngilizce okuma ağırlıklı, 80 çoktan seçmeli soru) hazırlanan
B1 seviyesinde bir Türk öğrenci (hedef 55+ puan) için kelime ezber uygulaması. Bu içerik doğrudan uygulamada
gösterilecek: tanıtım kartı, boşluk doldurma (cloze), eş anlamlı bulma, bağlamda tanıma alıştırmaları ve hafıza ipuçları.

## Görev

`seed/gen_input/batch_XX.json` dosyasındaki HER madde için, girdi sırasıyla, satır başına bir JSON nesnesi yaz:
`seed/gen_output/batch_XX_partYY.jsonl` (YY = 01, 02, 03 … ; her part dosyasında 15–20 madde).
İçeriği KENDİN yaz. Script/şablon ile üretme, dış API çağırma, başka dosyaya dokunma.

## Şema (her satır tek bir JSON nesnesi)

```json
{"lemma": "foster",
 "meaning_tr": null,
 "senses": [{"pos": "fiil", "tr": "geliştirmek, teşvik etmek", "en": "to encourage the development of something"},
            {"pos": "fiil", "tr": "(başkasının çocuğuna) bakıp büyütmek", "en": "to care for a child that is not legally yours"}],
 "examples": [
   {"en": "Teachers who ask open-ended questions can foster curiosity and independent thinking in their students.", "tr": "Açık uçlu sorular soran öğretmenler, öğrencilerinde merak ve bağımsız düşünmeyi geliştirebilir.", "form": "foster", "domain": "eğitim"},
   {"en": "Governments that wish to foster innovation often provide tax incentives for research and development.", "tr": "İnovasyonu teşvik etmek isteyen hükümetler genellikle araştırma ve geliştirme için vergi teşvikleri sağlar.", "form": "foster", "domain": "ekonomi"},
   {"en": "Regular social contact has been shown to foster resilience in elderly people living alone.", "tr": "Düzenli sosyal temasın, yalnız yaşayan yaşlılarda psikolojik dayanıklılığı geliştirdiği gösterilmiştir.", "form": "foster", "domain": "sağlık"},
   {"en": "Trade along the Silk Road fostered cultural exchange between distant civilizations for centuries.", "tr": "İpek Yolu boyunca yapılan ticaret, yüzyıllar boyunca uzak medeniyetler arasındaki kültürel alışverişi teşvik etti.", "form": "fostered", "domain": "tarih"}],
 "synonyms": ["promote", "encourage", "nurture", "cultivate"],
 "antonyms": ["hinder", "discourage", "suppress"],
 "family": [{"w": "fostering", "pos": "isim", "tr": "teşvik etme, geliştirme"}, {"w": "foster parent", "pos": "isim", "tr": "koruyucu ebeveyn"}],
 "confusables": [{"w": "faster", "why": "yazılışı benzer; 'daha hızlı' demek"}, {"w": "forest", "why": "harfleri benzer; 'orman'"}],
 "mnemonic": "FOSTER → 'fosfor': Bitkiye FOSfor gübresi verirsin, büyümesini TEŞVİK EDER ve GELİŞTİRİR.",
 "etymology": "Eski İngilizce 'fōstrian' (beslemek) → beslemek, büyütmek; mecazen bir şeyin gelişmesini sağlamak.",
 "concrete": false}
```

### Alan kuralları

- **lemma**: girdideki `lemma` ile birebir aynı.
- **meaning_tr**: girdide `meaning` null/boşsa kısa Türkçe anlam(lar) yaz; doluysa `null`.
- **senses**: 1–3 anlam, akademik metinlerdeki/YDS'deki önem sırasıyla. `pos` Türkçe (isim, fiil, sıfat, zarf, bağlaç, edat, öbek fiil),
  `tr` kısa Türkçe karşılık, `en` en fazla 15 kelimelik İngilizce tanım. Girdideki anlamla çelişme; önemli bir akademik anlam eksikse ekleyebilirsin.
- **examples**: TAM 4 cümle, 4 FARKLI alan (`domain`: bilim, sağlık, tarih, sosyal, psikoloji, ekonomi, çevre, eğitim, teknoloji, dil).
  - ÖSYM okuma parçası üslubu: resmî, akademik, bilgi veren; 14–28 kelime. Siyasi/tartışmalı içerik ve uydurma kesin istatistik/isim kullanma.
  - Hedef kelime cümlede TAM BİR KEZ geçsin. `form` = cümlede kullanılan biçim, cümlede birebir (büyük/küçük harf hariç) geçmeli.
  - Tek kelimelik maddelerde **en az 2 cümlede form tam olarak lemma olsun** (ör. "can foster", "to foster") — boşluk doldurma için.
    Diğerlerinde çekimli biçim kullanılabilir (fostered, fosters, interventions …).
  - Öbek fiil / çok kelimeli maddelerde parçalar bitişik dursun (en az 1 cümlede form == lemma); araya nesne giriyorsa form'u
    "brought ... about" gibi " ... " ile yaz.
  - Bağlamdan anlam tahmin edilebilsin (güçlü ipucu) ve boşluğa aynı türden başka bir kelime kolayca uymasın.
  - En az 3 cümle birincil YDS anlamını kullansın.
  - `tr`: cümlenin doğal, akıcı Türkçe çevirisi (kelime kelime değil). Türkçe karakterleri doğru kullan (ç, ğ, ı, İ, ö, ş, ü).
- **synonyms**: 2–5 eş anlamlı (aynı tür ve birincil anlam), YDS adayının bilmesi gereken düzeyde; ÖSYM'nin "yakın anlamlı cümle"
  sorularında kullandığı türden. Lemma'yı veya aile biçimlerini yazma. Bağlaçlar için işlevce eş olanlar (however → nevertheless).
- **antonyms**: 0–3 zıt anlamlı.
- **family**: 0–5 türev/akraba biçim `{w, pos, tr}` (lemma'nın kendisi hariç); girdideki `family` alanındakileri mutlaka ekle.
- **confusables**: 0–3 Türk öğrencilerin karıştırdığı kelime `{w, why}` (yazılışı benzer: adapt/adopt; anlamı yakın: affect/effect).
  `why` kısa Türkçe: diğer kelimenin anlamı + fark.
- **mnemonic**: Türkçe hafıza ipucu (anahtar kelime yöntemi). İngilizce kelimenin (bir kısmının) SESİNE benzeyen Türkçe kelime/ifade bul
  ve anlamla canlı bir mini sahnede birleştir. İngilizce kelimeyi BÜYÜK HARFLE yaz. 1–2 cümle, en fazla ~220 karakter.
  Örnek: "VULNERABLE → 'vur-ne-rahat': Kalkanı olmayan askeri VURmak ne rahat — savunmasızdır." Ses benzerliği zorsa güçlü bir görsel
  imge ya da kök çözümlemesi kullan. Anlam konusunda asla yanıltmasın.
- **etymology**: Türkçe, 1 cümle: kök/ön ek/son ek çözümlemesi veya hafızaya yardım eden köken. Emin değilsen yalnızca biçimsel
  çözümleme yaz; uydurma köken yazma. Yararlı bir şey yoksa "".
- **concrete**: elle tutulur/gözle görülür bir şeyi gösteriyorsa true (vessel, debris), soyut kavram/eylem/niteliklerde false.

## Biçim

- Her satır geçerli JSON (çift tırnak, kaçışlar doğru, sonda virgül yok). UTF-8; Türkçe karakterleri doğrudan yaz.
- Part dosyalarını Write aracıyla yaz (her biri 15–20 madde, girdi sırasıyla). Bir maddeyi düzeltmen gerekirse o maddenin bulunduğu
  part dosyasını baştan yaz (aynı madde iki dosyada olmasın).

## Doğrulama (zorunlu)

Tüm part dosyalarını yazdıktan sonra proje klasöründe (`C:\Users\MSI\Desktop\INGILIZCE\YDS_Kelime_Kocu`) şunu çalıştır:

```
.venv\Scripts\python.exe tools\validate_seed.py XX
```

(XX = paket numarası, ör. 07). Hata/eksik varsa düzelt ve tekrar çalıştır; "geçerli N/N, hatalı 0, eksik 0" olana kadar devam et.
Son mesajında yalnızca kısa bir özet ver: paket numarası, geçerli madde sayısı.
