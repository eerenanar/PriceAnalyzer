# PriceAnalyzer – Gereksinim Dokümanı

## Proje Özeti

PriceAnalyzer, bir Excel dosyasındaki ürün kodlarını birden fazla web sitesinde otomatik olarak araştıran, fiyat ve stok bilgilerini toplayarak karşılaştırmalı bir rapor Excel'i oluşturan bir Python uygulamasıdır.

---

## 1. Girdiler

### 1.1 Ürün Listesi (`products.xlsx`)
- Kullanıcı tarafından sağlanan Excel dosyası
- İlk sütun ürün kodlarını içerir (varsayılan: `A` sütunu, `1.` satırdan itibaren)
- Başlık satırı isteğe bağlıdır (yapılandırılabilir)

### 1.2 Site Listesi (`sites.txt`)
- Her satır bir tedarikçi sitesini tanımlar
- Format (pipe `|` ile ayrılmış):
  ```
  SiteAdı | AramaURLŞablonu | FiyatCSSSeçici | StokCSSSeçici
  ```
- `{code}` yer tutucusu ürün kodu ile değiştirilir
- Örnek:
  ```
  Tedarikci1 | https://tedarikci1.com/search?q={code} | .product-price | .stock-info
  Tedarikci2 | https://tedarikci2.com/urun/{code}      | #price-box     | #stock-count
  ```
- `#` ile başlayan satırlar yorum satırıdır, atlanır

---

## 2. İşlem Akışı

```
products.xlsx
      │
      ▼
[Ürün Kodlarını Oku]
      │
      ▼
sites.txt
      │
      ▼
[Site Yapılandırmalarını Oku]
      │
      ▼
Her ürün için:
  └── Her site için:
        ├── Arama URL'sini oluştur
        ├── Sayfayı çek (requests / Selenium)
        ├── Fiyatı parse et
        ├── Stok bilgisini parse et
        └── Sonuçları kaydet
      │
      ▼
[Rapor Excel'i Oluştur]
      │
      ├── Sheet 1: Özet (en ucuz fiyat, stok, kaynak site)
      └── Her ürün için ayrı sheet: Tüm fiyatlar ve detaylar
```

---

## 3. Çıktı: `output_YYYYMMDD_HHMMSS.xlsx`

### 3.1 Sheet 1 – Özet (En Ucuz Fiyatlar)

| Sütun             | Açıklama                                         |
|-------------------|--------------------------------------------------|
| Ürün Kodu         | Excel'den alınan ürün kodu                       |
| En Ucuz Fiyat     | Tüm siteler arasındaki minimum birim fiyatı      |
| Para Birimi       | Fiyatın para birimi (TRY, USD, EUR, vb.)         |
| Stok Adedi        | En ucuz fiyatın bulunduğu sitedeki stok miktarı  |
| Kaynak Site       | En ucuz fiyatın bulunduğu site adı               |
| URL               | Ürünün bulunduğu tam sayfa adresi                |
| Tarama Tarihi     | Verinin çekildiği tarih ve saat                  |

### 3.2 Per-Ürün Sheetleri – Detay

Her ürün için `[ÜRÜN_KODU]` adında bir sheet oluşturulur.

| Sütun         | Açıklama                              |
|---------------|---------------------------------------|
| Site Adı      | Tedarikçi sitesinin adı               |
| Birim Fiyat   | Sitedeki birim fiyatı                 |
| Para Birimi   | Fiyatın para birimi                   |
| Stok Adedi    | Sitedeki mevcut stok miktarı          |
| URL           | Ürünün bulunduğu tam sayfa adresi     |
| Durum         | Başarılı / Bulunamadı / Hata          |
| Tarama Tarihi | Verinin çekildiği tarih ve saat       |

---

## 4. Yapılandırma (`config.ini`)

```ini
[files]
products_file = products.xlsx
sites_file    = sites.txt
output_dir    = output

[excel]
product_column  = A       ; Ürün kodlarının bulunduğu sütun
header_row      = 1       ; Başlık satırı (0 = başlık yok)
start_row       = 2       ; Verinin başladığı satır

[scraper]
request_timeout   = 15    ; Saniye cinsinden istek zaman aşımı
delay_between_requests = 1.5  ; İstekler arası bekleme süresi (saniye)
max_retries       = 3     ; Başarısız istek için yeniden deneme sayısı
use_selenium      = false ; JS gerektiren siteler için Selenium kullan
headless          = true  ; Selenium headless modda çalışsın mı

[logging]
level   = INFO
log_file = price_analyzer.log
```

---

## 5. Teknik Gereksinimler

| Kategori          | Gereksinim                                         |
|-------------------|----------------------------------------------------|
| Dil               | Python 3.9+                                        |
| HTTP İstemcisi    | `requests` + `cloudscraper` (anti-bot bypass)      |
| HTML Ayrıştırma   | `BeautifulSoup4` + `lxml`                          |
| JS Desteği        | `selenium` + `webdriver-manager` (isteğe bağlı)   |
| Excel Okuma       | `openpyxl`                                         |
| Excel Yazma       | `openpyxl`                                         |
| Para Birimi Parse | Regex tabanlı otomatik tespit                      |
| Çalıştırma        | CLI script (`run.sh` / `run.bat`)                  |
| Loglama           | `logging` modülü, dosya + konsol çıktısı           |

---

## 6. Klasör Yapısı

```
PriceAnalyzer/
├── REQUIREMENTS.md          # Bu doküman
├── README.md                # Kullanım kılavuzu
├── config.ini               # Yapılandırma dosyası
├── sites.txt                # Site listesi ve CSS seçicileri
├── products.xlsx            # Girdi: ürün kodları (kullanıcı sağlar)
├── run.sh                   # Linux/macOS çalıştırma scripti
├── run.bat                  # Windows çalıştırma scripti
├── requirements.txt         # Python bağımlılıkları
├── price_analyzer/
│   ├── __init__.py
│   ├── main.py              # Ana giriş noktası
│   ├── config.py            # Yapılandırma yükleyici
│   ├── excel_reader.py      # Ürün kodu okuyucu
│   ├── scraper.py           # Web scraping motoru
│   ├── parser.py            # Fiyat ve stok ayrıştırıcı
│   └── report.py            # Excel rapor oluşturucu
├── output/                  # Oluşturulan raporlar
└── logs/                    # Log dosyaları
```

---

## 7. Kullanım

```bash
# Bağımlılıkları yükle
pip install -r requirements.txt

# Çalıştır (varsayılan dosyalarla)
./run.sh

# Özel dosyalarla çalıştır
python -m price_analyzer.main \
  --products benim_urunler.xlsx \
  --sites benim_siteler.txt \
  --output sonuclar/

# Sadece belirli ürünler için
python -m price_analyzer.main --products products.xlsx --filter "KOD1,KOD2,KOD3"
```

---

## 8. Hata Yönetimi

| Durum                         | Davranış                                              |
|-------------------------------|-------------------------------------------------------|
| Site ulaşılamaz               | Hata loglanır, diğer sitelerle devam edilir           |
| Ürün sitede bulunamadı        | "Bulunamadı" olarak raporlanır                        |
| Fiyat parse edilemiyor        | "Parse Hatası" olarak raporlanır                      |
| Excel okuma hatası            | Hata mesajı ile program durur                         |
| Rate limiting / 429 hatası    | Bekleme süresi artırılarak yeniden denenir            |
| Ağ zaman aşımı                | Max retry sonrası "Zaman Aşımı" olarak raporlanır     |

---

## 9. Notlar

- Siteler `sites.txt`'e kolayca eklenip çıkarılabilir.
- CSS seçicileri site yapısı değiştiğinde sadece `sites.txt` güncellenerek düzeltilir.
- Selenium, yalnızca `config.ini`'de `use_selenium = true` yapıldığında devreye girer.
- Çıktı Excel dosyası tarih damgalı olarak `output/` klasörüne kaydedilir.
