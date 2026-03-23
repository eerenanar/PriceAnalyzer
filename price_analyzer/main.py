"""PriceAnalyzer – Ana giriş noktası."""

import argparse
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime
from typing import Dict, List

from .config import load_config
from .excel_reader import read_product_codes
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

    # Ürün kodlarını oku
    try:
        product_codes = read_product_codes(cfg.files.products_file, cfg.excel)
    except Exception as e:
        logger.critical(f"Ürün dosyası okunamadı: {e}")
        sys.exit(1)

    # Filtre uygula
    if args.filter_codes:
        filter_set = {c.strip() for c in args.filter_codes.split(",")}
        product_codes = [c for c in product_codes if c in filter_set]
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

    # Scraper oluştur
    scraper_cls = SeleniumScraper if cfg.scraper.use_selenium else Scraper
    scraper = scraper_cls(cfg.scraper)

    # Scraping işlemi
    all_results: Dict[str, List[PriceResult]] = defaultdict(list)
    total = len(product_codes) * len(sites)
    done = 0

    try:
        for product_code in product_codes:
            logger.info(f"── Ürün: {product_code} ({len(sites)} site taranacak)")
            for site in sites:
                scraped_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                result = scraper.scrape_product(product_code, site, scraped_at)
                all_results[product_code].append(result)
                done += 1

                status_icon = "✓" if result.status == "OK" else "✗"
                price_str = f"{result.price:.2f} {result.currency}" if result.price else "-"
                logger.info(
                    f"  [{done}/{total}] {status_icon} {site.name:20s} | "
                    f"Fiyat: {price_str:15s} | Stok: {result.stock} | Durum: {result.status}"
                )
    finally:
        if cfg.scraper.use_selenium and hasattr(scraper, "close"):
            scraper.close()

    # Rapor oluştur
    output_path = build_report(dict(all_results), cfg.files.output_dir)

    logger.info("=" * 60)
    logger.info(f"Tamamlandı! Rapor: {output_path}")
    logger.info(f"Toplam ürün  : {len(product_codes)}")
    logger.info(f"Toplam tarama: {done}")
    logger.info("=" * 60)

    print(f"\nRapor oluşturuldu: {output_path}")


if __name__ == "__main__":
    main()
