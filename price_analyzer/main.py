"""PriceAnalyzer – Ana giriş noktası."""

import argparse
import logging
import os
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from threading import Lock
from typing import Dict, List

from .config import load_config
from .excel_reader import read_products_with_offers
from .report import build_report
from .scraper import PriceResult, Scraper, SeleniumScraper, load_sites


def setup_logging(level: str, log_file: str) -> None:
    os.makedirs(os.path.dirname(log_file) if os.path.dirname(log_file) else ".", exist_ok=True)
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file, encoding="utf-8"),
    ]
    logging.basicConfig(level=getattr(logging, level, logging.INFO), format=fmt, handlers=handlers)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="PriceAnalyzer – Ürün fiyat karşılaştırma aracı",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Örnekler:
  python -m price_analyzer.main
  python -m price_analyzer.main --products urunler.xlsx --sites siteler.txt
  python -m price_analyzer.main --products urunler.xlsx --filter KOD1,KOD2
        """,
    )
    parser.add_argument("--config", default="config.ini", help="Yapılandırma dosyası (varsayılan: config.ini)")
    parser.add_argument("--products", help="Ürün kodları Excel dosyası (config.ini'yi geçersiz kılar)")
    parser.add_argument("--sites", help="Site listesi TXT dosyası (config.ini'yi geçersiz kılar)")
    parser.add_argument("--output", help="Çıktı klasörü (config.ini'yi geçersiz kılar)")
    parser.add_argument("--filter", dest="filter_codes", help="Virgülle ayrılmış ürün kodları filtresi")
    parser.add_argument("--filter-sites", dest="filter_sites", help="Virgülle ayrılmış site adları filtresi (ör. Digikey,Arrow)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg = load_config(args.config)

    # CLI argümanları config değerlerini geçersiz kılar
    if args.products:
        cfg.files.products_file = args.products
    if args.sites:
        cfg.files.sites_file = args.sites
    if args.output:
        cfg.files.output_dir = args.output

    setup_logging(cfg.logging.level, cfg.logging.log_file)
    logger = logging.getLogger(__name__)

    logger.info("=" * 60)
    logger.info("PriceAnalyzer başlatılıyor")
    logger.info(f"Ürün dosyası : {cfg.files.products_file}")
    logger.info(f"Site dosyası : {cfg.files.sites_file}")
    logger.info(f"Çıktı klasörü: {cfg.files.output_dir}")
    logger.info("=" * 60)

    # Ürün kodlarını ve teklif adetlerini oku
    try:
        product_codes, offer_quantities = read_products_with_offers(cfg.files.products_file, cfg.excel)
    except Exception as e:
        logger.critical(f"Ürün dosyası okunamadı: {e}")
        sys.exit(1)

    # Filtre uygula
    if args.filter_codes:
        filter_set = {c.strip() for c in args.filter_codes.split(",")}
        product_codes = [c for c in product_codes if c in filter_set]
        offer_quantities = {k: v for k, v in offer_quantities.items() if k in filter_set}
        logger.info(f"Filtre uygulandı – {len(product_codes)} ürün seçildi")

    if not product_codes:
        logger.warning("İşlenecek ürün kodu bulunamadı. Program sonlandırılıyor.")
        sys.exit(0)

    # Site yapılandırmalarını yükle
    try:
        sites = load_sites(cfg.files.sites_file)
    except Exception as e:
        logger.critical(f"Site dosyası okunamadı: {e}")
        sys.exit(1)

    if not sites:
        logger.critical("Hiç site yapılandırması bulunamadı. sites.txt dosyasını kontrol edin.")
        sys.exit(1)

    # Site filtresi
    if args.filter_sites:
        filter_site_set = {s.strip().lower() for s in args.filter_sites.split(",")}
        sites = [s for s in sites if s.name.lower() in filter_site_set]
        logger.info(f"Site filtresi uygulandı – {[s.name for s in sites]} taranacak")

    # Her site için ayrı bir scraper oluştur (paralel tarama)
    def make_scraper():
        scraper_cls = SeleniumScraper if cfg.scraper.use_selenium else Scraper
        return scraper_cls(cfg.scraper)

    logger.info(f"{len(sites)} site paralel olarak taranacak, her biri {len(product_codes)} ürün işleyecek")

    # Scraping işlemi – her site kendi worker thread'inde çalışır
    all_results: Dict[str, List[PriceResult]] = defaultdict(list)
    results_lock = Lock()
    total = len(product_codes) * len(sites)
    done = 0
    done_lock = Lock()

    def scrape_site(site):
        """Bir sitenin tüm ürünlerini sırayla tarar."""
        scraper = make_scraper()
        site_results = []
        try:
            for product_code in product_codes:
                scraped_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                result = scraper.scrape_product(product_code, site, scraped_at)
                site_results.append((product_code, result))

                nonlocal done
                with done_lock:
                    done += 1
                    current = done

                status_icon = "✓" if result.status == "OK" else "✗"
                price_str = f"{result.price:.5f} {result.currency}" if result.price else "-"
                logger.info(
                    f"  [{current}/{total}] {status_icon} {site.name:20s} | "
                    f"Fiyat: {price_str:15s} | Stok: {result.stock} | Durum: {result.status}"
                )
        finally:
            if hasattr(scraper, "close"):
                scraper.close()
        return site_results

    scrapers_to_close = []
    try:
        with ThreadPoolExecutor(max_workers=len(sites)) as executor:
            futures = {executor.submit(scrape_site, site): site for site in sites}
            for future in as_completed(futures):
                site = futures[future]
                try:
                    site_results = future.result()
                    with results_lock:
                        for product_code, result in site_results:
                            all_results[product_code].append(result)
                except Exception as e:
                    logger.error(f"{site.name} tarama hatası: {e}")
    finally:
        pass  # Her scraper kendi finally bloğunda kapatılıyor

    # NOT_FOUND olanları tekrar dene (arama sayfası redirect gecikmesi veya rate limit nedeniyle)
    retry_items = []
    for product_code, results_list in all_results.items():
        for i, result in enumerate(results_list):
            if result.status == "NOT_FOUND":
                site_match = [s for s in sites if s.name == result.site_name]
                if site_match:
                    retry_items.append((product_code, i, site_match[0]))

    if retry_items:
        logger.info(f"{len(retry_items)} NOT_FOUND ürün tekrar taranıyor (yeni session ile)...")
        # Her retry turunda yeni session oluştur (stale session sorununu önler)
        for retry_round in range(1, 3):  # 2 retry turu
            if not retry_items:
                break
            logger.info(f"  Retry turu {retry_round}: {len(retry_items)} ürün")
            retry_scraper = make_scraper()  # Her turda yeni session
            still_failed = []
            try:
                for product_code, idx, site in retry_items:
                    import time as _time
                    _time.sleep(2)  # Rate limit koruması için daha uzun bekleme
                    scraped_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    new_result = retry_scraper.scrape_product(product_code, site, scraped_at)
                    if new_result.status == "OK":
                        all_results[product_code][idx] = new_result
                        logger.info(
                            f"  [RETRY-{retry_round}] ✓ {site.name:20s} | {product_code} | "
                            f"Fiyat: {new_result.price:.5f} {new_result.currency} | Stok: {new_result.stock}"
                        )
                        with done_lock:
                            done += 1
                    else:
                        still_failed.append((product_code, idx, site))
            finally:
                if hasattr(retry_scraper, "close"):
                    retry_scraper.close()
            retry_items = still_failed

    # Özet raporunda site sırası sites.txt ile aynı olsun
    site_order = {site.name: i for i, site in enumerate(sites)}
    for code in all_results:
        all_results[code].sort(key=lambda r: site_order.get(r.site_name, 999))

    # Rapor oluştur
    output_path = build_report(dict(all_results), cfg.files.output_dir, offer_quantities, cfg.files.products_file)

    logger.info("=" * 60)
    logger.info(f"Tamamlandı! Rapor: {output_path}")
    logger.info(f"Toplam ürün  : {len(product_codes)}")
    logger.info(f"Toplam tarama: {done}")
    logger.info("=" * 60)

    print(f"\nRapor oluşturuldu: {output_path}")


if __name__ == "__main__":
    main()
