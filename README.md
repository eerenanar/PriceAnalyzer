# PriceAnalyzer

Excel'deki ürün kodlarını birden fazla tedarikçi sitesinde otomatik olarak araştıran, fiyat ve stok verilerini toplayarak karşılaştırmalı Excel raporu oluşturan Python uygulaması.

---

## Hızlı Başlangıç

```bash
# 1. Bağımlılıkları kur
pip install -r requirements.txt

# 2. Örnek ürün Excel'i oluştur (isteğe bağlı)
python create_sample_excel.py

# 3. sites.txt dosyasını düzenle (site yapılandırmalarını ekle)
nano sites.txt

# 4. Çalıştır
./run.sh
```

---

## Kullanım

### Varsayılan Dosyalarla

```bash
./run.sh           # Linux/macOS
run.bat            # Windows
```

### Özel Parametrelerle

```bash
python -m price_analyzer.main \
  --products benim_urunler.xlsx \
  --sites    benim_siteler.txt \
  --output   sonuclar/

# Sadece belirli ürünler
python -m price_analyzer.main --filter "KOD1,KOD2,KOD3"
```

### Ortam Değişkenleriyle (run.sh için)

```bash
PRODUCTS_FILE=urunler.xlsx SITES_FILE=siteler.txt ./run.sh
```

---

## Dosyalar

| Dosya                   | Açıklama                                    |
|-------------------------|---------------------------------------------|
| `products.xlsx`         | Ürün kodlarını içeren girdi Excel (siz sağlarsınız) |
| `sites.txt`             | Tedarikçi site yapılandırmaları             |
| `config.ini`            | Genel ayarlar                               |
| `run.sh`                | Linux/macOS çalıştırma scripti              |
| `run.bat`               | Windows çalıştırma scripti                  |
| `create_sample_excel.py`| Örnek products.xlsx oluşturur               |
| `output/`               | Oluşturulan raporlar                        |
| `logs/`                 | Log dosyaları                               |

---

## sites.txt Formatı

Her satır bir tedarikçi sitesini tanımlar:

```
SiteAdı | AramaURLŞablonu | FiyatCSSSeçici | StokCSSSeçici
```

- `{code}` → ürün koduyla değiştirilir
- `#` ile başlayan satırlar yorum satırıdır

**Örnek:**

```
Tedarikci1 | https://tedarikci1.com/search?q={code} | .product-price | .stock-info
Tedarikci2 | https://tedarikci2.com/urun/{code}      | #price-box     | #stock-count
```

CSS seçiciler **BeautifulSoup** `select_one()` metoduyla kullanılır.

---

## Çıktı Excel Yapısı

- **Sheet 1 – Özet**: Her ürün için en ucuz fiyat, stok adedi ve kaynak site
- **Per-ürün sheetleri**: Her siteden alınan tüm fiyat ve stok detayları

---

## Yapılandırma (config.ini)

```ini
[scraper]
use_selenium = false    # JS gerektiren siteler için true yapın
delay_between_requests = 1.5  # Saniye cinsinden istek aralığı
max_retries = 3

[excel]
product_column = A  # Ürün kodlarının bulunduğu sütun
start_row = 2       # Verinin başladığı satır
```

---

## Gereksinimler

- Python 3.9+
- Detaylı gereksinimler için: [REQUIREMENTS.md](REQUIREMENTS.md)
