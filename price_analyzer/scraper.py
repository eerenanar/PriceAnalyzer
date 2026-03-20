"""Web scraping motoru."""

import logging
import re
import time
from dataclasses import dataclass, field
from typing import List, Optional

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


@dataclass
class PriceResult:
    """Tek bir siteden alınan fiyat sonucu."""
    site_name: str
    product_code: str
    price: Optional[float]
    currency: str
    stock: Optional[int]
    url: str
    status: str  # "OK" | "NOT_FOUND" | "PARSE_ERROR" | "TIMEOUT" | "ERROR"
    scraped_at: str = ""


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
        """CSS seçici ile HTML'den metin çıkarır."""
        soup = BeautifulSoup(html, "lxml")
        el = soup.select_one(selector)
        return el.get_text(separator=" ", strip=True) if el else ""

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

        price_text = self._extract(html, site.price_selector)
        stock_text = self._extract(html, site.stock_selector)

        if not price_text:
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
        )


class SeleniumScraper(Scraper):
    """JavaScript gerektiren siteler için Selenium tabanlı scraper."""

    def __init__(self, cfg: ScraperConfig):
        super().__init__(cfg)
        self._driver = None

    def _get_driver(self):
        if self._driver is None:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from webdriver_manager.chrome import ChromeDriverManager
            from selenium.webdriver.chrome.service import Service

            options = Options()
            if self.cfg.headless:
                options.add_argument("--headless=new")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument(f"user-agent={self.HEADERS['User-Agent']}")

            service = Service(ChromeDriverManager().install())
            self._driver = webdriver.Chrome(service=service, options=options)
        return self._driver

    def _fetch(self, url: str) -> Optional[str]:
        try:
            driver = self._get_driver()
            driver.get(url)
            time.sleep(2)  # JS yüklenme süresi
            return driver.page_source
        except Exception as e:
            logger.warning(f"Selenium hata: {e}")
            return None

    def close(self):
        if self._driver:
            self._driver.quit()
            self._driver = None
