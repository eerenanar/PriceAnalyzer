"""Web scraping motoru."""

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import cloudscraper
from bs4 import BeautifulSoup

from .config import ScraperConfig
from .parser import parse_price, parse_stock

logger = logging.getLogger(__name__)


@dataclass
class SiteConfig:
    """Bir tedarikçi sitesinin yapılandırması."""
    name: str
    search_url_template: str
    price_selector: str
    stock_selector: str
    # Opsiyonel: fiyat kırılım tablosunun satır seçici (ör. "table.price-table tr")
    # Varsa her satırdan (miktar, fiyat) çiftleri çıkarılır
    price_table_row_selector: str = ""


@dataclass
class PriceResult:
    """Tek bir siteden alınan fiyat sonucu."""
    site_name: str
    product_code: str
    price: Optional[float]          # qty=1 (veya en düşük kırılım) için fiyat
    currency: str
    stock: Optional[int]
    url: str
    status: str  # "OK" | "NOT_FOUND" | "PARSE_ERROR" | "TIMEOUT" | "ERROR"
    scraped_at: str = ""
    # Fiyat kırılım listesi: [(min_qty, unit_price), ...]  — boşsa tek fiyat var
    price_breaks: List[Tuple[int, float]] = field(default_factory=list)

    def price_for_qty(self, qty: int) -> Optional[float]:
        """Verilen adete göre en uygun birim fiyatı döndürür.
        Kırılım yoksa sabit fiyatı döndürür.
        qty <= 0 ise en düşük kırılım fiyatını döndürür.
        """
        if not self.price_breaks:
            return self.price
        if qty <= 0:
            return self.price_breaks[0][1] if self.price_breaks else self.price
        # Adedi aşmayan en büyük kırılımı bul
        best_price = self.price_breaks[0][1]
        for min_qty, unit_price in self.price_breaks:
            if qty >= min_qty:
                best_price = unit_price
        return best_price


def load_sites(sites_file: str) -> List[SiteConfig]:
    """
    sites.txt dosyasını okuyarak SiteConfig listesi döndürür.

    Format: SiteAdı | AramaURLŞablonu | FiyatSelector | StokSelector
    """
    sites: List[SiteConfig] = []
    try:
        with open(sites_file, encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = [p.strip() for p in line.split("|")]
                if len(parts) < 4:
                    logger.warning(f"sites.txt satır {line_num}: Eksik alan, atlanıyor → {line}")
                    continue
                sites.append(SiteConfig(
                    name=parts[0],
                    search_url_template=parts[1],
                    price_selector=parts[2],
                    stock_selector=parts[3],
                    price_table_row_selector=parts[4] if len(parts) > 4 else "",
                ))
    except FileNotFoundError:
        logger.error(f"sites.txt bulunamadı: {sites_file}")
        raise

    logger.info(f"{len(sites)} site yapılandırması yüklendi.")
    return sites


class Scraper:
    """HTTP tabanlı web scraper."""

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    def __init__(self, cfg: ScraperConfig):
        self.cfg = cfg
        self.session = cloudscraper.create_scraper()
        self.session.headers.update(self.HEADERS)

    def _fetch(self, url: str) -> Optional[str]:
        """Verilen URL'yi çeker ve HTML string döndürür."""
        for attempt in range(1, self.cfg.max_retries + 1):
            try:
                resp = self.session.get(url, timeout=self.cfg.request_timeout)
                if resp.status_code == 429:
                    wait = 2 ** attempt
                    logger.warning(f"Rate limit (429) – {wait}s bekleniyor: {url}")
                    time.sleep(wait)
                    continue
                if resp.status_code != 200:
                    logger.warning(f"HTTP {resp.status_code}: {url}")
                    return None
                return resp.text
            except Exception as e:
                logger.warning(f"İstek hatası (deneme {attempt}/{self.cfg.max_retries}): {e}")
                if attempt < self.cfg.max_retries:
                    time.sleep(2 ** attempt)
        return None

    def _extract(self, html: str, selector: str) -> str:
        """CSS seçici ile HTML'den metin çıkarır.
        Birden fazla eşleşme varsa fiyat gibi görünen ($ veya rakamla başlayan) ilkini döndürür.
        Geçersiz veya boş selector ise boş string döndürür.
        """
        if not selector or selector.strip() in ("-", ""):
            return ""
        soup = BeautifulSoup(html, "lxml")
        try:
            els = soup.select(selector)
        except Exception:
            return ""
        if not els:
            return ""
        # Fiyat gibi görünen ilk elementi tercih et
        for el in els:
            text = el.get_text(separator=" ", strip=True)
            if text and (text[0] in "$€£₺" or (text[0].isdigit() and "+" not in text)):
                return text
        return els[0].get_text(separator=" ", strip=True)

    def _extract_price_breaks(self, html: str, row_selector: str) -> List[Tuple[int, float]]:
        """Fiyat kırılım tablosundan [(min_qty, unit_price), ...] listesi çıkarır.
        tr/td tabanlı (Digikey, Newark) ve div tabanlı (Arrow) yapıları destekler.
        Her satırda "N+" formatındaki miktar ve "$X.XXXX" formatındaki fiyat aranır.
        """
        if not row_selector or row_selector.strip() in ("-", ""):
            return []
        soup = BeautifulSoup(html, "lxml")
        rows = soup.select(row_selector)
        breaks: List[Tuple[int, float]] = []
        for row in rows:
            # tr/td yapısı
            cells = row.find_all(["td", "th"])
            if cells:
                texts = [c.get_text(strip=True) for c in cells]
            else:
                # div yapısı: doğrudan child elementlerin metinleri
                texts = [c.get_text(strip=True) for c in row.children
                         if hasattr(c, "get_text") and c.get_text(strip=True)]
            if len(texts) < 2:
                continue
            # "1+", "10+", "1,000+" veya sadece "1", "10", "100" formatındaki miktar
            qty_text = texts[0]
            qty_match = re.search(r"[\d,]+", qty_text)
            if not qty_match:
                continue
            try:
                min_qty = int(qty_match.group().replace(",", ""))
            except ValueError:
                continue
            # Fiyat: 3 sütunlu tablolarda (qty, unit_price, ext_price) → ikinci sütun
            # 2 sütunlu tablolarda (qty, unit_price) → ikinci sütun
            # Her iki durumda da texts[1] birim fiyat
            price_text = texts[1] if len(texts) >= 2 else texts[-1]
            price, _ = parse_price(price_text)
            if price is None:
                # Fallback: son sütunu dene
                price, _ = parse_price(texts[-1])
            if price is None:
                continue
            breaks.append((min_qty, price))
        breaks.sort(key=lambda x: x[0])
        return breaks

    def _extract_maritex_data(self, html: str) -> Tuple[List[Tuple[int, float]], str, Optional[int]]:
        """Maritex arama sayfasından fiyat kırılımlarını ve stok bilgisini çıkarır.
        Birden fazla sonuç olabilir; 'For business clients only' / disabled stok içerenleri atlar,
        ilk geçerli ürünü kullanır.
        Fiyat formatı: Avrupa stili virgüllü ondalık ("0,0040").
        Para birimi: tablo başlığından okunur ("PLN/pcs.", "USD/pcs." vb.).
        Returns (breaks, currency, stock)
        """
        soup = BeautifulSoup(html, "lxml")
        items = soup.select("div.product-list-item")

        for item in items:
            # "For business clients only" veya disabled stok içerenleri atla
            if item.select_one("div.product-order__stocks--disabled"):
                continue
            if "For business clients only" in item.get_text():
                continue

            # Para birimi: tablo başlığından al ("Net price USD/pcs." → "USD")
            currency = ""
            header = item.select_one("table.product-prices thead")
            if header:
                m = re.search(r"\b([A-Z]{3})/pcs", header.get_text())
                if m:
                    currency = m.group(1)

            # Fiyat kırılımları
            breaks: List[Tuple[int, float]] = []
            rows = item.select("table.product-prices tbody tr")
            for row in rows:
                cells = row.find_all("td")
                if len(cells) < 2:
                    continue
                qty_text = cells[0].get_text(strip=True)   # "100+"
                price_text = cells[1].get_text(strip=True) # "0,0040"

                qty_match = re.search(r"[\d]+", qty_text.replace(",", "").replace(".", ""))
                if not qty_match:
                    continue
                try:
                    min_qty = int(qty_match.group())
                except ValueError:
                    continue

                # Virgül = ondalık ayırıcı
                price_clean = price_text.replace(",", ".").strip()
                price_match = re.search(r"\d+\.\d+|\d+", price_clean)
                if not price_match:
                    continue
                try:
                    price = float(price_match.group())
                except ValueError:
                    continue

                if price > 0:
                    breaks.append((min_qty, price))

            if not breaks:
                continue

            breaks.sort(key=lambda x: x[0])

            # Stok: badge--success title veya text'inden
            stock: Optional[int] = None
            stock_el = item.select_one("div.product-stock .badge--success")
            if stock_el:
                raw = stock_el.get("title") or stock_el.get_text(strip=True)
                stock_clean = re.sub(r"[^\d]", "", raw)
                if stock_clean:
                    try:
                        stock = int(stock_clean)
                    except ValueError:
                        pass

            return breaks, currency, stock

        return [], "", None

    def _fetch_rutronik(self, search_html: str) -> Optional[str]:
        """Rutronik: arama sayfası HTML'sinden ilk /product/ linkini bulur,
        ürün sayfasını fetch edip döndürür. Cloudscraper yeterli — browser gerektirmez.
        """
        soup = BeautifulSoup(search_html, "lxml")
        product_link = soup.select_one("td.td-description a[href*='/product/']")
        if not product_link:
            product_link = soup.select_one("a[href*='/product/']")
        if not product_link:
            logger.warning("Rutronik: ürün linki bulunamadı")
            return None

        product_url = product_link["href"]
        if not product_url.startswith("http"):
            product_url = "https://www.rutronik24.com" + product_url
        logger.debug(f"Rutronik: ürün sayfasına yönlendiriliyor → {product_url}")
        return self._fetch(product_url)

    def _extract_rutronik_price_breaks(self, html: str) -> Tuple[List[Tuple[int, float]], str]:
        """Rutronik ürün sayfasındaki fiyat tablosundan kırılımları çıkarır.
        Avrupa formatı: miktar "10.000" (nokta=binlik), fiyat "0,0007 $" (virgül=ondalık).
        Returns (breaks, currency)
        """
        soup = BeautifulSoup(html, "lxml")
        breaks: List[Tuple[int, float]] = []
        currency = "USD"

        rows = soup.select("table.occalc_pa_table tr")
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            qty_text = cells[0].get_text(strip=True)
            price_text = cells[1].get_text(strip=True)

            # Miktar: "10.000" → nokta binlik ayırıcı → kaldır → int
            qty_clean = qty_text.replace(".", "").replace(",", "").strip()
            qty_match = re.search(r"\d+", qty_clean)
            if not qty_match:
                continue
            try:
                min_qty = int(qty_match.group())
            except ValueError:
                continue

            # Fiyat: "0,0007 $" → virgülü noktaya çevir
            cur_match = re.search(r"[$€£]", price_text)
            if cur_match:
                currency = {"$": "USD", "€": "EUR", "£": "GBP"}.get(cur_match.group(), "USD")
            price_clean = price_text.replace(",", ".").strip()
            price_match = re.search(r"\d+\.\d+", price_clean)
            if not price_match:
                continue
            try:
                price = float(price_match.group())
            except ValueError:
                continue

            if price > 0:
                breaks.append((min_qty, price))

        breaks.sort(key=lambda x: x[0])
        return breaks, currency

    def scrape_product(self, product_code: str, site: SiteConfig, scraped_at: str) -> PriceResult:
        """
        Belirli bir sitede ürün kodunu arar ve sonucu döndürür.
        """
        url = site.search_url_template.replace("{code}", product_code)

        time.sleep(self.cfg.delay_between_requests)

        html = self._fetch(url)
        if html is None:
            return PriceResult(
                site_name=site.name,
                product_code=product_code,
                price=None,
                currency="",
                stock=None,
                url=url,
                status="TIMEOUT",
                scraped_at=scraped_at,
            )

        # Rutronik: stok arama sayfasından, fiyat kırılımları ürün sayfasından alınır
        rutronik_search_html = None
        if "rutronik24.com" in url:
            rutronik_search_html = html
            html = self._fetch_rutronik(html) or html

        price_breaks = self._extract_price_breaks(html, site.price_table_row_selector)
        price_text = self._extract(html, site.price_selector)
        stock_text = self._extract(html, site.stock_selector)

        # Newark için özel kırılım ve stok çıkarıcıyı kullan (liste veya PDP sayfası)
        site_currency = ""
        if hasattr(self, "_extract_newark_price_breaks") and "newark.com" in site.search_url_template:
            price_breaks, site_currency = self._extract_newark_price_breaks(html)
            # Stok: liste sayfası veya PDP sayfası selector'larından birini dene
            if not stock_text:
                soup_tmp = BeautifulSoup(html, "lxml")
                for stk_sel in [
                    "div[class*='PDPAvailabilityPrimaryStatusstyles__StatusMessage-']",
                    "div[class*='AvailabilityPrimaryStatusstyles__StatusMessage-']",
                ]:
                    els = soup_tmp.select(stk_sel)
                    if els:
                        stock_text = els[0].get_text(strip=True)
                        break

        # Rutronik için özel kırılım çıkarıcıyı kullan
        if "rutronik24.com" in site.search_url_template:
            price_breaks, site_currency = self._extract_rutronik_price_breaks(html)
            # Stok: ürün sayfasında login gerekiyor, arama sayfasından oku
            if not stock_text and rutronik_search_html:
                soup_tmp = BeautifulSoup(rutronik_search_html, "lxml")
                stock_el = soup_tmp.select_one("span.stock-status")
                if stock_el:
                    stock_text = stock_el.get_text(strip=True)

        # Maritex için özel kırılım ve stok çıkarıcıyı kullan
        if "maritex.eu" in site.search_url_template:
            m_breaks, m_currency, m_stock = self._extract_maritex_data(html)
            if m_breaks:
                price_breaks = m_breaks
                site_currency = m_currency
            if m_stock is not None:
                stock_text = str(m_stock)

        # TTI için özel kırılım ve stok çıkarıcıyı kullan
        if hasattr(self, "_extract_tti_price_breaks") and "tti.com" in site.search_url_template:
            price_breaks, site_currency = self._extract_tti_price_breaks(html)
            if not stock_text:
                soup_tmp = BeautifulSoup(html, "lxml")
                stock_el = soup_tmp.select_one("#ATS")
                if stock_el:
                    stock_text = stock_el.get_text(separator=" ", strip=True)

        # Zaikostore için özel kırılım ve stok çıkarıcıyı kullan
        if hasattr(self, "_extract_zaikostore_price_breaks") and "zaikostore.com" in site.search_url_template:
            price_breaks, site_currency = self._extract_zaikostore_price_breaks(html)
            # Stok: rightSide h2 içindeki "In Stock: X,XXX" değerini oku
            if not stock_text:
                soup_tmp = BeautifulSoup(html, "lxml")
                right = soup_tmp.select_one("div.rightSide h2")
                if right:
                    stock_text = right.get_text(strip=True)

        # Fiyat kırılımları varsa en düşük kırılımı (1+ fiyatı) price olarak kullan
        if price_breaks:
            price = price_breaks[0][1]
            # Para birimini: önce site özel çıkarıcıdan, sonra price_text'ten al
            if site_currency:
                currency = site_currency
            else:
                _, currency = parse_price(price_text) if price_text else (None, "")
        elif not price_text:
            return PriceResult(
                site_name=site.name,
                product_code=product_code,
                price=None,
                currency="",
                stock=None,
                url=url,
                status="NOT_FOUND",
                scraped_at=scraped_at,
            )
        else:
            price, currency = parse_price(price_text)

        stock = parse_stock(stock_text)

        if price is None:
            status = "PARSE_ERROR"
        else:
            status = "OK"

        return PriceResult(
            site_name=site.name,
            product_code=product_code,
            price=price,
            currency=currency,
            stock=stock,
            url=url,
            status=status,
            scraped_at=scraped_at,
            price_breaks=price_breaks,
        )


class SeleniumScraper(Scraper):
    """JavaScript gerektiren siteler için Selenium tabanlı scraper."""

    def __init__(self, cfg: ScraperConfig):
        super().__init__(cfg)
        self._driver = None
        self._uc_driver = None

    def scrape_product(self, product_code: str, site: SiteConfig, scraped_at: str) -> PriceResult:
        """Selenium siteleri için delay uygulamaz — WebDriverWait kendi bekleme mekanizmasını kullanır."""
        # Digikey HTTP ile çalışıyor, ona delay uygula; diğer Selenium sitelerine uygulama
        if "digikey.com" not in site.search_url_template:
            orig = self.cfg.delay_between_requests
            self.cfg.delay_between_requests = 0
            result = super().scrape_product(product_code, site, scraped_at)
            self.cfg.delay_between_requests = orig
            return result
        return super().scrape_product(product_code, site, scraped_at)

    def _get_driver(self):
        if self._driver is None:
            import os
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from webdriver_manager.chrome import ChromeDriverManager
            from selenium.webdriver.chrome.service import Service

            options = Options()
            if self.cfg.headless:
                options.add_argument("--headless=new")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_argument("--window-size=1280,800")
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option("useAutomationExtension", False)
            options.add_argument(f"user-agent={self.HEADERS['User-Agent']}")

            # Her thread için ayrı kalıcı profil dizini: cookie/session korunur,
            # aynı anda birden fazla Chrome örneği profil kilidi çakışması yaşamaz
            import threading
            thread_id = threading.current_thread().ident or os.getpid()
            profile_dir = os.path.join(
                os.path.expanduser("~"), f".price_analyzer_chrome_profile_{thread_id}"
            )
            os.makedirs(profile_dir, exist_ok=True)
            options.add_argument(f"--user-data-dir={profile_dir}")

            service = Service(ChromeDriverManager().install())
            self._driver = webdriver.Chrome(service=service, options=options)
            self._driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
                "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            })
        return self._driver

    def _fetch(self, url: str) -> Optional[str]:
        """URL'yi alır ve site bazlı özel mantığı uygular."""
        if "digikey.com" in url:
            return self._fetch_digikey(url)
        if "arrow.com" in url:
            return self._fetch_arrow(url)
        if "newark.com" in url:
            return self._fetch_newark(url)
        if "zaikostore.com" in url:
            return self._fetch_zaikostore(url)
        if "tti.com" in url:
            return self._fetch_tti(url)
        # Genel Selenium fetch (Digikey vb.)
        try:
            driver = self._get_driver()
            driver.get(url)
            time.sleep(5)
            return driver.page_source
        except Exception as e:
            logger.warning(f"Selenium hata: {e}")
            return None

    def _fetch_digikey(self, url: str) -> Optional[str]:
        """Digikey: browser gerektirmez, cloudscraper ile HTTP isteği yapar."""
        for attempt in range(1, self.cfg.max_retries + 1):
            try:
                resp = self.session.get(url, timeout=self.cfg.request_timeout)
                if resp.status_code == 429:
                    wait = 2 ** attempt
                    logger.warning(f"Digikey rate limit (429) – {wait}s bekleniyor")
                    time.sleep(wait)
                    continue
                if resp.status_code != 200:
                    logger.warning(f"Digikey HTTP {resp.status_code}: {url}")
                    return None
                return resp.text
            except Exception as e:
                logger.warning(f"Digikey istek hatası (deneme {attempt}): {e}")
                if attempt < self.cfg.max_retries:
                    time.sleep(2 ** attempt)
        return None

    def _fetch_arrow(self, url: str) -> Optional[str]:
        """Arrow: arama sayfasından 'View Product' linkini takip eder.
        WebDriverWait ile sabit bekleme yerine element yüklenince devam eder.
        """
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        try:
            driver = self._get_driver()
            driver.get(url)

            # Arama sayfasında /en/products/ linkini bekle (max 15s)
            try:
                WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/en/products/']"))
                )
            except Exception:
                pass  # Bulunamazsa mevcut sayfayı kullan

            soup = BeautifulSoup(driver.page_source, "lxml")
            product_link = soup.find("a", href=re.compile(r"/en/products/"))
            if product_link:
                product_url = "https://www.arrow.com" + product_link["href"]
                logger.debug(f"Arrow: ürün sayfasına yönlendiriliyor → {product_url}")
                driver.get(product_url)

                # Ürün sayfasında fiyat elementini bekle (max 15s)
                try:
                    WebDriverWait(driver, 15).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "div.css-8hkf9j"))
                    )
                except Exception:
                    pass

            return driver.page_source
        except Exception as e:
            logger.warning(f"Arrow Selenium hata: {e}")
            return None

    def _fetch_zaikostore(self, url: str) -> Optional[str]:
        """Zaikostore: arama sayfasından ilk sonucun ürün detay linkine tıklar,
        ardından ürün sayfasının HTML'sini döndürür.
        Akamai bot koruması nedeniyle Selenium gerektirir.
        """
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        try:
            driver = self._get_driver()
            driver.get(url)

            # İlk sonuç satırındaki stockDetail linkini bekle (max 15s)
            try:
                WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='stockDetail']"))
                )
            except Exception:
                pass  # Bulunamazsa mevcut sayfayı döndür

            soup = BeautifulSoup(driver.page_source, "lxml")
            detail_link = soup.select_one("a[href*='stockDetail']")
            if detail_link:
                href = detail_link.get("href", "")
                product_url = "https://www.zaikostore.com" + href
                logger.debug(f"Zaikostore: ürün sayfasına yönlendiriliyor → {product_url}")
                driver.get(product_url)

                # Ürün sayfasında stok veya fiyat elementini bekle (max 15s)
                try:
                    WebDriverWait(driver, 15).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "div.rightSide, #price_list"))
                    )
                except Exception:
                    pass

            return driver.page_source
        except Exception as e:
            logger.warning(f"Zaikostore Selenium hata: {e}")
            return None

    def _extract_zaikostore_price_breaks(self, html: str) -> Tuple[List[Tuple[int, float]], str]:
        """Zaikostore ürün sayfasından fiyat kırılımlarını çıkarır.
        Fiyatlar #price_list tablosundaki td.price elementlerinden okunur.
        Miktar aralıkları (ör. "1 - 9,999") ilk sütundan parse edilir.
        Returns (breaks, currency)
        """
        soup = BeautifulSoup(html, "lxml")
        breaks: List[Tuple[int, float]] = []
        currency = "USD"  # Zaikostore USD kullanır

        rows = soup.select("#price_list table tr")
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            qty_text = cells[0].get_text(strip=True)
            price_text = cells[1].get_text(strip=True)

            # Miktar: "1 - 9,999" veya "40,000 -" formatından minimum qty'yi al
            qty_match = re.search(r"[\d,]+", qty_text)
            if not qty_match:
                continue
            try:
                min_qty = int(qty_match.group().replace(",", ""))
            except ValueError:
                continue

            # Fiyat: "$0.002" veya "0.002" formatı
            price_match = re.search(r"[\d]+\.[\d]+", price_text)
            if not price_match:
                continue
            try:
                price = float(price_match.group())
            except ValueError:
                continue

            if price > 0:
                breaks.append((min_qty, price))

        breaks.sort(key=lambda x: x[0])
        return breaks, currency

    def _fetch_newark(self, url: str) -> Optional[str]:
        """Newark: arama veya PDP sayfasının HTML'sini döndürür.
        Tek ürün sonucu olduğunda site direkt PDP'ye yönlendirir.
        """
        import random
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        try:
            driver = self._get_driver()

            # 403 gelirse driver'ı yeniden başlatıp tekrar dene
            for attempt in range(1, 3):
                try:
                    driver.get(url)
                except Exception:
                    # Session çöktüyse driver'ı yeniden başlat
                    self.close()
                    driver = self._get_driver()
                    driver.get(url)

                # İnsan benzeri rastgele bekleme (1.5–3.5s)
                time.sleep(random.uniform(1.5, 3.5))

                # 403 sayfası kontrolü
                if "Access Denied" in driver.title or "403" in driver.title:
                    logger.warning(f"Newark 403 (deneme {attempt}) – driver yeniden başlatılıyor")
                    self.close()
                    driver = self._get_driver()
                    time.sleep(random.uniform(4.0, 7.0))
                    continue
                break

            # Liste sayfası: PriceBreak divi veya PDP: PriceTable bekle (max 10s)
            try:
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR,
                        "div[class*='PriceBreakupTableCellstyles__PriceBreak-'], "
                        "table[class*='ProductPriceTablestyles__PriceTable-']"
                    ))
                )
            except Exception:
                pass

            return driver.page_source
        except Exception as e:
            logger.warning(f"Newark Selenium hata: {e}")
            return None

    def _extract_newark_price_breaks(self, html: str) -> Tuple[List[Tuple[int, float]], str]:
        """Newark'a özel fiyat kırılımı çıkarıcı.
        Liste sayfası: PriceBreakupTableCellstyles__PriceBreak- divleri
        PDP sayfası: ProductPriceTablestyles__PriceTable- tablosu
        Returns (breaks, currency)
        """
        soup = BeautifulSoup(html, "lxml")

        # Liste sayfası: PriceBreak divleri
        break_divs = soup.select("div[class*='PriceBreakupTableCellstyles__PriceBreak-']")
        if break_divs:
            breaks: List[Tuple[int, float]] = []
            currency = ""
            for div in break_divs:
                texts = [c.get_text(strip=True) for c in div.children
                         if hasattr(c, "get_text") and c.get_text(strip=True)]
                if len(texts) < 2:
                    continue
                qty_match = re.search(r"[\d,]+", texts[0])
                if not qty_match:
                    continue
                try:
                    min_qty = int(qty_match.group().replace(",", ""))
                except ValueError:
                    continue
                price, cur = parse_price(texts[-1])
                if price is None:
                    continue
                if cur:
                    currency = cur
                breaks.append((min_qty, price))
            if breaks:
                breaks.sort(key=lambda x: x[0])
                return breaks, currency

        # PDP sayfası: ProductPriceTable tablosu — ilk td'den currency oku
        breaks = self._extract_price_breaks(html, "table[class*='ProductPriceTablestyles__PriceTable-'] tr")
        currency = ""
        if breaks:
            # İlk fiyat içeren td metninden currency çıkar
            tds = soup.select("table[class*='ProductPriceTablestyles__PriceTable-'] td")
            for td in tds:
                _, cur = parse_price(td.get_text(strip=True))
                if cur:
                    currency = cur
                    break
        return breaks, currency

    def _get_uc_driver(self):
        """TTI için undetected_chromedriver instance'ı döndürür (bot tespitini atlar).
        İlk çağrıda TTI ana sayfasını ziyaret ederek cookie/session ısıtır.
        """
        if self._uc_driver is None:
            import os
            import threading
            import undetected_chromedriver as uc

            options = uc.ChromeOptions()
            if self.cfg.headless:
                options.add_argument("--headless=new")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--window-size=1280,900")

            thread_id = threading.current_thread().ident or os.getpid()
            profile_dir = os.path.join(
                os.path.expanduser("~"), f".price_analyzer_uc_profile_{thread_id}"
            )
            os.makedirs(profile_dir, exist_ok=True)
            options.add_argument(f"--user-data-dir={profile_dir}")

            self._uc_driver = uc.Chrome(options=options, headless=self.cfg.headless)

            # Cookie ısıtma: ana sayfa ziyareti
            try:
                self._uc_driver.get("https://www.tti.com/")
                time.sleep(3)
            except Exception:
                pass

        return self._uc_driver

    def _fetch_tti(self, url: str) -> Optional[str]:
        """TTI: arama veya ürün sayfasını fetch eder.
        - Tek sonuç: TTI otomatik olarak direkt ürün sayfasına yönlendirir.
        - Çok sonuç: arama sayfasından ilk 't-part-search-part-number' linkini takip eder.
        undetected_chromedriver ile Imperva bot korumasını atlar.
        """
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        try:
            driver = self._get_uc_driver()
            driver.get(url)

            # Fiyat tablosu veya arama linki yüklenene kadar bekle (max 20s)
            try:
                WebDriverWait(driver, 20).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR,
                        'table.c-part-detail__quantity-price-table, '
                        'a[name="t-part-search-part-number"]'
                    ))
                )
            except Exception:
                pass

            soup = BeautifulSoup(driver.page_source, "lxml")

            # Zaten ürün sayfasındaysa (direkt yönlendirme) döndür
            if soup.select_one("table.c-part-detail__quantity-price-table"):
                logger.debug(f"TTI: direkt ürün sayfasına yönlendirildi")
                return driver.page_source

            # Arama sayfasındaysa: ilk ürün linkini bul ve takip et
            link = soup.select_one('a[name="t-part-search-part-number"]')
            if not link:
                logger.warning(f"TTI: ürün bulunamadı → {url}")
                return None

            product_url = "https://www.tti.com" + link["href"]
            logger.debug(f"TTI: ürün sayfasına yönlendiriliyor → {product_url}")
            driver.get(product_url)

            try:
                WebDriverWait(driver, 20).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "table.c-part-detail__quantity-price-table")
                    )
                )
            except Exception:
                pass

            return driver.page_source
        except Exception as e:
            logger.warning(f"TTI Selenium hata: {e}")
            return None

    def _extract_tti_price_breaks(self, html: str) -> Tuple[List[Tuple[int, float]], str]:
        """TTI ürün sayfasındaki fiyat tablosundan kırılımları çıkarır.
        Format: miktar "10,000" (virgül binlik), fiyat "$0.00089".
        Returns (breaks, currency)
        """
        soup = BeautifulSoup(html, "lxml")
        breaks: List[Tuple[int, float]] = []
        currency = "USD"

        rows = soup.select("table.c-part-detail__quantity-price-table tbody tr")
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            qty_text = cells[0].get_text(strip=True)
            price_text = cells[1].get_text(strip=True)

            qty_clean = qty_text.replace(",", "").strip()
            qty_match = re.search(r"\d+", qty_clean)
            if not qty_match:
                continue
            try:
                min_qty = int(qty_match.group())
            except ValueError:
                continue

            price, cur = parse_price(price_text)
            if cur:
                currency = cur
            if price is None:
                continue

            breaks.append((min_qty, price))

        breaks.sort(key=lambda x: x[0])
        return breaks, currency

    def close(self):
        if self._driver:
            self._driver.quit()
            self._driver = None
        if self._uc_driver:
            self._uc_driver.quit()
            self._uc_driver = None
