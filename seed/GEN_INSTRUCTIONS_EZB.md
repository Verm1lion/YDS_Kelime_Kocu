# Ek talimat — Ezberbozan listesi maddeleri (paket 21 ve sonrası)

Önce `seed/GEN_INSTRUCTIONS.md`'yi oku; şema, alan kuralları, biçim ve doğrulama aynen geçerli. Bu paketlerdeki maddeler
"60 Günde Ezberbozan Kelimeler" kitabından geliyor ve girdide ek bir `hint` alanı var. Öğrenci A2–B1 düzeyinde; içerik
YDS'ye (akademik okuma, kelime/dil bilgisi soruları) hizmet etsin.

## `hint` alanı

- `section`: `day` (kitabın günlük hedef kelimesi), `pv` (öbek fiil), `combo` (edat kalıbı), `linker` (bağlaç / geçiş
  ifadesi), `garanti` (kitap dışı, ÖSYM'de çok çıkan kelime).
- `book_synonyms`: kitaptaki "Eş ya da Yakın Anlamlılar". `synonyms` listesine **önce bunları aynı sırayla** yaz (açıkça
  yanlış olan varsa çıkar), sonra gerekirse 1–2 tane ekle (toplam en fazla 6).
- `definition`: kitabın verdiği İngilizce tanım; `senses[0].en` için kullanabilirsin.
- `variants`: aynı kalıbın başka biçimleri (ör. `rely on` → `rely upon`). `synonyms`'e ekleyebilirsin.
- `linker_type` / `group`: bağlacın kitaptaki türü (BAĞLAÇ, EDAT, CÜMLE ZARFI…) ve anlam grubu (Sebep, Zıtlık…).
- `sub`: edat kalıbının türü (ör. `VERB + 'on'`, `ADJECTIVE + 'of'`, `'in' + NOUN`).
- `book_phrase`: kitaptaki yazım (ör. `charge sb with sth`); lemma'daki ` ... ` araya giren nesneyi gösterir.

## Bölüme göre kurallar

**day / garanti**: standart kurallar. Girdide `meaning` boşsa `meaning_tr` zorunlu (kısa, YDS'deki asıl anlam önce).

**pv (öbek fiil)**: standart öbek fiil kuralları. `senses[].pos` = "öbek fiil". Mem: parçacığın (up, out, off…) anlama
katkısını gösteren canlı bir sahne ya da ses benzerliği.

**combo (edat kalıbı)** — amaç, kelimeyle birlikte gelen EDATI ezberletmek:
- `senses[].pos`: fiil + edat → "fiil", sıfat + edat → "sıfat", isim + edat → "isim", `'in' + NOUN` türü → "ifade".
- `examples`: kalıp cümlede bitişik geçsin; en az 1 cümlede `form` lemma ile birebir aynı olsun (ör. "rely on",
  "capable of", "in advance"). Lemma ` ... ` içeriyorsa (charge ... with) araya nesne gelen cümleler kur ve `form`'u
  "charge ... with" gibi yaz (en az 1 örnekte form tam olarak lemma). Fiillerde çekimli biçim serbest ("relies on").
  Boşluğa başka bir edat konunca cümle yanlış olsun (YDS edat sorusu mantığı).
- `synonyms`: aynı anlamdaki kalıplar ya da tek kelimeler (rely on → depend on, count on; in advance → beforehand).
- `mnemonic`: EDATA odaklı kısa Türkçe ipucu; kalıbı BÜYÜK HARFLE yaz. Ör. "RELY ON → birine güvenmek = üstüne (ON)
  yaslanmak: sırtını ON'a dayarsın." / "CAPABLE OF → OF: -e muktedir; 'yapabilen' biri: capable OF doing."
- `family`: genelde []; `confusables`: aynı kelimenin başka edatla kullanımı varsa (ör. "consist in" — farkı).

**linker (bağlaç / geçiş ifadesi)** — YDS dil bilgisi ve cümle tamamlama sorularının kalbi:
- `senses[].pos`: girdideki `pos` (bağlaç, edat, zarf). `en`: işlevini anlatan kısa tanım ("introduces a contrast").
  Türü değiştiren önemli kullanım varsa ayrı anlam olarak ver (ör. "since": sebep / zaman).
- `examples`: dil bilgisi DOĞRU kullanım: bağlaç + yan cümle (Although SVO, SVO), edat + isim öbeği / -ing (Despite the
  rain, …), cümle zarfı noktalama ile (…; however, … / However, …). İlişki çift parçalıysa (both ... and, not only ...
  but also, so ... that, no sooner ... than) iki parça da cümlede geçsin, `form` "both ... and" gibi yazılsın. Cümle
  bağlacın ilişkisini (zıtlık, sebep, sonuç…) açıkça göstersin.
- `synonyms`: işlevce eş ifadeler (although → even though, though; despite → in spite of, notwithstanding;
  therefore → thus, hence, consequently). Lemma'nın kendisini yazma.
- `mnemonic`: kullanım kuralı + anlam ipucu, Türkçe, ifade BÜYÜK HARFLE. Ör. "DESPITE / IN SPITE OF + isim ya da -ing;
  ALTHOUGH + cümle. 'despite of' YOK!" / "WHEREAS → 'oysa': iki karşıt durumu yan yana koyar (A böyle, WHEREAS B şöyle)."
- `confusables`: sık karıştırılan bağlaçlar ve farkı (although ↔ despite: biri cümle, biri isim alır).
- `family`: []; `concrete`: false; `etymology`: biçimsel çözümleme ya da "".
