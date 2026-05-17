# SubLens

> Windows için gerçek zamanlı OCR tabanlı oyun diyalog çevirmeni — ekranın herhangi bir bölgesindeki metni okur ve çeviriyi oyununun üzerinde sürüklenebilir bir overlay olarak gösterir.

<p align="center">
  <img src="SubLens.ico" alt="SubLens" width="80"/>
</p>

---

## Özellikler

- **3 çeviri motoru** — istediğin zaman geçiş yap
  - **LM Studio** — tamamen yerel AI, internet gerekmez (kaynak yoğun)
  - **DeepL Free** — 500.000 karakter/ay, yüksek kalite
  - **Google Translate** — gayri resmi ücretsiz endpoint, API anahtarı gerekmez
- **Akıllı OCR** (Tesseract tabanlı)
  - 6 ön işleme modu (otomatik, açık yazı, koyu yazı, altyazı top-hat, konturlu, equalize)
  - Otsu eşikleme + medyan filtre + kontrast artışı
  - 2× / 3× / 4× büyütme seçenekleri
  - PSM modu seçimi (tek blok, tek satır, dağınık metin, ham satır)
  - Otomatik en iyi mod tespiti (6 modu dener, en yüksek güven skorunu seçer)
- **Şeffaf overlay** — oyunun üstünde yüzer, motora göre renklenir, sürüklenebilir
- **Sürekli tarama** — ayarlanabilir aralık (0,5–15 sn), yeni metin algılandığında otomatik çeviri
- **Benzerlik eşiği** — küçük OCR titremelerinde gereksiz yeniden çeviri yapmaz
- **LRU çeviri önbelleği** — 200 girdi, gereksiz API çağrısını engeller
- **Global hotkey** — tam ekran oyunlarda da çalışır (F2 / F3 / F4 + Ctrl+Alt+R/T/G/H)
- **Auto-pause** — hedef oyun penceresi pasifleşince tarama duraklatılır
- **Glossary** — özel isimleri ve terimleri çeviriden koru
- **Sistem tepsisi** — uygulamayı tepsiye küçült, çift tıkla geri getir
- **Çoklu monitör** desteği
- **Yapılandırma** `%APPDATA%\SubLens\config.json` dosyasına otomatik kaydedilir

---

## Gereksinimler

| Bağımlılık | Notlar |
|---|---|
| Python 3.9+ | |
| [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) | `C:\Program Files\Tesseract-OCR\` yoluna kur |
| Pillow | `pip install pillow` |
| pytesseract | `pip install pytesseract` |
| PySide6 | `pip install PySide6` |
| mss *(isteğe bağlı)* | Hızlı çoklu monitör yakalama — `pip install mss` |
| keyboard *(isteğe bağlı)* | Global hotkey — `pip install keyboard` |
| pywin32 *(isteğe bağlı)* | Auto-pause özelliği — `pip install pywin32` |

Hepsini tek komutla kur:

```bash
pip install pillow pytesseract PySide6 mss keyboard pywin32
```

> **Tesseract dil paketleri** — Tesseract kurulumunda ihtiyaç duyduğun dilleri seç (`eng`, `tur`, `jpn`, `kor` vb.). Bir paket eksikse uygulama otomatik olarak `eng`'e düşer ve log'da uyarı verir.

---

## Kurulum

```bash
git clone https://github.com/bnsware/SubLens.git
cd SubLens
pip install pillow pytesseract PySide6 mss keyboard pywin32
python sublens.py
```

---

## Hızlı Başlangıç

1. `python sublens.py` ile uygulamayı başlat
2. **Çeviri motoru** seç (Google, kurulum gerektirmez — başlangıç için idealdir)
3. **Kaynak** ve **hedef dil** seç
4. Oyundaki diyalog kutusunu çerçevelemek için **F2**'ye bas
5. Tek seferlik çeviri için **F3**, sürekli tarama için **F4**'e bas

---

## Kısayol Tuşları

| Tuş | Fonksiyon |
|---|---|
| **F2** | Ekran bölgesi seç |
| **F3** | Tek seferlik çeviri |
| **F4** | Sürekli taramayı başlat / durdur |
| **ESC** | Overlay'i gizle / bölge seçimini iptal et |
| **Ctrl+Alt+R** | Bölge seç (global) |
| **Ctrl+Alt+T** | Tek çeviri (global) |
| **Ctrl+Alt+G** | Taramayı aç/kapat (global) |
| **Ctrl+Alt+H** | Overlay'i gizle (global) |

---

## Motor Ayarları

### LM Studio
1. LM Studio'yu aç → bir model yükle → **Local Server**'ı başlat (varsayılan port: 1234)
2. SubLens Ayarlar penceresinde **URL** ve **Model** gir, **Bağlan** ile test et
- ✅ Tamamen offline, gizlilik dostu
- ⚠️ GPU/RAM yoğun — ağır oyunlarda aynı anda çalışınca FPS düşürebilir

### DeepL Free
1. [deepl.com](https://www.deepl.com/) adresinde ücretsiz hesap aç → Free API anahtarı al
2. Anahtarı SubLens Ayarlar penceresine yapıştır → aylık kullanımı görmek için **Test** et
- ✅ En yüksek çeviri kalitesi, düşük kaynak tüketimi
- ⚠️ Aylık 500k karakter limiti

### Google Translate
- API anahtarı gerekmez, anında çalışır
- ✅ Sıfır kurulum
- ⚠️ Gayri resmi endpoint — Google zaman zaman hız limiti veya blok uygulayabilir

---

## OCR İpuçları

- **Büyütme**: küçük yazılar için 3× veya 4× dene
- **OCR Modu**:
  - *Otomatik* — arka plan parlaklığına göre modu seçer
  - *Açık yazı* — koyu zemin üzerine açık metin
  - *Koyu yazı* — açık zemin üzerine koyu metin
  - *Altyazı (top-hat)* — **karmaşık/dağınık arka planlar için en iyisi** (su, bulanık manzara, UI öğeleri). Yerel arka plan çıkarma + adaptif eşikleme kullanır. RDR2, Spider-Man 2 gibi oyunlarda harika çalışır.
  - *Konturlu altyazı* — kontür/stroke içeren oyun altyazıları için
  - *Equalize* — çok değişken arka planlar için histogram dengeleme
- **PSM 6** çoğu diyalog kutusu için iyidir; tek satırlık altyazılar için **PSM 7** dene
- **İşlenmiş görüntüyü önizle** seçeneğini aç — Tesseract'ın tam olarak ne gördüğünü gösterir, ayar yaparken paha biçilmez

---

## Oyun Bağlamı (yalnızca LM Studio)

Ayarlar → **Oyun Bağlamı** alanına çevirinin tonunu yönlendirecek bir ipucu yaz:

> Örn: `Wild West, 1899, kovboy diyalogu`

DeepL ve Google bu alanı kullanmaz.

---

## Glossary (Terim Koruma)

Ayarlar → **Glossary** bölümüne, satır başına bir terim ekle:

```
Arthur=Arthur
RedDead
Guarma=Guarma
```

- Yalnız `terim` — kelimeyi olduğu gibi bırakır (çevirmez)
- `kaynak=hedef` — çeviriden sonra kaynak terimi hedefle değiştirir

---

## Sorun Giderme

| Belirti | Çözüm |
|---|---|
| "Tesseract dil paketi bulunamadi" | İlgili dilin `.traineddata` dosyasını Tesseract klasörüne ekle |
| OCR boş metin döndürüyor | Bölgeyi sıkılaştır, büyütmeyi artır veya OCR modunu manuel seç |
| Google motoru hata veriyor | Geçici olarak DeepL veya LM Studio'ya geç — Google IP bloklaması zaman zaman olur |
| Overlay yanlış yerde | Üstüne tıklayıp sürükle, konum bir sonraki açılışa kadar kalır |
| LM Studio bağlanmıyor | LM Studio'da Local Server'ın çalıştığından ve URL'nin doğru olduğundan emin ol |
| Çeviri sırasında FPS düşüyor | Tarama aralığını artır veya DeepL/Google'a geç |

---

## Yapılandırma Dosyası

`%APPDATA%\SubLens\config.json` — uygulama açılırken yüklenir, kapanırken kaydedilir. Manuel düzenlenebilir; sıfırlamak için silmek yeterlidir.

---

## Bağımsız EXE Oluşturma

```bash
python _build.py
```

Oluşan `SubLens.exe` dosyası `dist/` klasörüne yerleştirilir. Tesseract EXE içine gömülüdür — hedef makinede ayrı kurulum gerekmez.

---

## Proje Yapısı

```
SubLens/
├── sublens.py        # Ana uygulama (PySide6)
├── _build.py         # PyInstaller derleme betiği
├── SubLens.spec      # PyInstaller spec dosyası
├── SubLens.ico       # Uygulama ikonu
├── READMEapp.md      # Uygulama içi yardım belgesi
├── sublens.bat       # Çalıştırma yardımcısı
└── calistir.bat      # Alternatif başlatıcı
```

---

## Lisans

Bu proje **MIT Lisansı** ile yayınlanmıştır. Ayrıntılar için [LICENSE](LICENSE) dosyasına bak.

---

## Teşekkürler

- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) — UB Mannheim Windows derlemeleri
- [PySide6](https://doc.qt.io/qtforpython/) — Qt for Python
- [mss](https://python-mss.readthedocs.io/) — hızlı ekran yakalama
- [DeepL API](https://www.deepl.com/docs-api) — yüksek kaliteli sinir ağı çevirisi
