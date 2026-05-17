# Game Translator

Oyun içi diyalogları **ekran bölgesinden OCR ile okuyup** seçtiğiniz çeviri motoruyla anlık olarak çeviren bir Windows masaüstü uygulamasıdır. Çeviri sonucu hem ana pencerede hem de oyun üstünde sürüklenebilir bir **overlay** olarak gösterilir.

---

## Özellikler

- **3 çeviri motoru** — istediğin zaman geçiş yap
  - **LM Studio** — yerel AI, internet gerekmez (kaynak yoğun)
  - **DeepL Free** — 500.000 karakter/ay, yüksek kalite
  - **Google Translate** — gayri resmi ücretsiz endpoint, anahtar gerekmez
- **Akıllı OCR** (Tesseract)
  - Otomatik açık/koyu metin tespiti
  - Otsu eşikleme + medyan filtre + kontrast artışı
  - 2x / 3x / 4x büyütme seçenekleri
  - PSM modu seçimi (tek blok, tek satır, dağınık metin, ham satır)
- **Şeffaf overlay** — oyunun üstünde, motoruna göre renklenir, sürüklenebilir
- **Sürekli tarama** — ayarlanabilir aralıkla (0.5–15 sn) yeni metin yakaladığında otomatik çevirir
- **Benzerlik eşiği** — küçük OCR titremelerinde gereksiz yeniden çeviri yapmaz
- **Çoklu monitör** desteği
- **Yapılandırma** otomatik kaydedilir (`%APPDATA%/GameTranslator/config.json`)

---

## Kurulum

1. **Python 3.9+**
2. **Tesseract OCR** — `C:\Program Files\Tesseract-OCR\tesseract.exe` yoluna kurulu olmalı
   - Çevireceğin dilin paketi (`tur`, `jpn`, `kor` vb.) Tesseract kurulumunda seçili olmalı
   - Yoksa otomatik olarak `eng`'e düşer ve log'da uyarı verilir
3. Bağımlılıklar:
   ```
   pip install pillow pytesseract
   ```

---

## Kısayol Tuşları

| Tuş | İşlev |
|-----|-------|
| **F2** | Ekran bölgesi seç |
| **F3** | Tek seferlik çeviri yap |
| **F4** | Sürekli taramayı başlat / durdur |
| **ESC** | Overlay'i gizle (bölge seçerken iptal) |

---

## Hızlı Başlangıç

1. Uygulamayı çalıştır: `python translator.py`
2. **Motor** seç (Google en hızlı başlangıçtır — kurulum istemez)
3. **Kaynak / hedef dil** seç
4. **F2** ile oyundaki diyalog kutusunun bulunduğu alanı işaretle
5. **F3** ile tek çeviri dene veya **F4** ile sürekli tarama başlat

---

## Motor Ayarları

### LM Studio
- LM Studio'yu aç → bir model yükle → **Local Server**'ı başlat (varsayılan port 1234)
- Ayarlar penceresinden **URL** ve **Model** seç, **Bağlan** ile test et
- Avantaj: tamamen offline, gizlilik
- Dezavantaj: GPU/RAM yoğun — RDR2 gibi ağır oyunlarla aynı anda çalışınca FPS düşürebilir

### DeepL Free
- [deepl.com](https://www.deepl.com/) → API Free planına ücretsiz kayıt ol
- **API Key**'i Ayarlar penceresine yapıştır → **Test** ile aylık karakter kullanımını gör
- Avantaj: en yüksek çeviri kalitesi, hafif
- Dezavantaj: aylık 500k karakter limiti

### Google Translate
- API anahtarı gerekmez, hemen çalışır
- Avantaj: anında kullanılabilir
- Dezavantaj: gayri resmi endpoint olduğu için Google zaman zaman bloklayabilir

---

## OCR İpuçları

- **Büyütme**: küçük yazılar için 3x veya 4x dene
- **Metin modu**:
  - *Otomatik* — arka plan parlaklığına göre seçer
  - *Açık yazı* — koyu zemin üzerine açık metin
  - *Koyu yazı* — açık zemin üzerine koyu metin
  - *Oyun altyazısı* — **dağınık/karmaşık arka planlar için en iyisi**. Yerel arka plan çıkarma (top-hat) + adaptif eşikleme kullanır. Su, bulanık manzara, UI öğeleri vb. üstündeki parlak altyazıları temizce yakalar. Düz Otsu'nun başarısız olduğu yerlerde bunu dene.
- **PSM 6** çoğu diyalog kutusu için iyidir; tek satırlık alt yazılar için **PSM 7** dene
- **İşlenmiş görüntüyü önizle** seçeneği OCR'ın gerçekte ne gördüğünü gösterir — ayar yaparken çok faydalı

---

## Oyun Bağlamı

Ayarlar > **Oyun Bağlamı** alanına çevirinin tonunu yönlendirecek bir ipucu yazabilirsin (yalnızca LM Studio motorunda etkili):

> Örn: `Wild West, 1899, kovboy diyalogu`

DeepL ve Google bu alanı kullanmaz.

---

## Sorun Giderme

| Belirti | Çözüm |
|---------|-------|
| "Tesseract dil paketi bulunamadi" | İlgili dilin `.traineddata` paketini Tesseract klasörüne ekle |
| OCR boş metin döndürüyor | Bölgeyi sıkılaştır, büyütmeyi artır, metin modunu manuel seç |
| Google motoru hata veriyor | Geçici olarak DeepL veya LM Studio'ya geç — Google IP bloklaması zaman zaman olur |
| Overlay yanlış yerde | Üstüne tıklayıp sürükle, konum bir sonraki açılışa kadar kalır |
| LM Studio bağlanmıyor | LM Studio'da Local Server'ın çalıştığından ve URL'nin doğru olduğundan emin ol |

---

## Yapılandırma Dosyası

`%APPDATA%\GameTranslator\config.json` — pencere açılırken otomatik yüklenir, kapanırken kaydedilir. Manuel düzenlenebilir; bozulursa silmek yeterlidir.
