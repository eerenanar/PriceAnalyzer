"""Yapılandırma yükleyici modülü."""

import configparser
import os
from dataclasses import dataclass, field


@dataclass
class FilesConfig:
    products_file: str = "products.xlsx"
    sites_file: str = "sites.txt"
    output_dir: str = "output"


@dataclass
class ExcelConfig:
    product_column: str = "A"
    header_row: int = 1
    start_row: int = 2


@dataclass
class ScraperConfig:
    request_timeout: int = 15
    delay_between_requests: float = 1.5
    max_retries: int = 3
    use_selenium: bool = False
    headless: bool = True


@dataclass
class LoggingConfig:
    level: str = "INFO"
    log_file: str = "logs/price_analyzer.log"


@dataclass
class AppConfig:
    files: FilesConfig = field(default_factory=FilesConfig)
    excel: ExcelConfig = field(default_factory=ExcelConfig)
    scraper: ScraperConfig = field(default_factory=ScraperConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


def load_config(config_path: str = "config.ini") -> AppConfig:
    """config.ini dosyasını okuyarak AppConfig nesnesi döndürür."""
    cfg = AppConfig()

    if not os.path.exists(config_path):
        return cfg

    parser = configparser.ConfigParser()
    parser.read(config_path, encoding="utf-8")

    if parser.has_section("files"):
        s = parser["files"]
        cfg.files.products_file = s.get("products_file", cfg.files.products_file)
        cfg.files.sites_file = s.get("sites_file", cfg.files.sites_file)
        cfg.files.output_dir = s.get("output_dir", cfg.files.output_dir)

    if parser.has_section("excel"):
        s = parser["excel"]
        cfg.excel.product_column = s.get("product_column", cfg.excel.product_column).strip().upper()
        cfg.excel.header_row = s.getint("header_row", cfg.excel.header_row)
        cfg.excel.start_row = s.getint("start_row", cfg.excel.start_row)

    if parser.has_section("scraper"):
        s = parser["scraper"]
        cfg.scraper.request_timeout = s.getint("request_timeout", cfg.scraper.request_timeout)
        cfg.scraper.delay_between_requests = s.getfloat("delay_between_requests", cfg.scraper.delay_between_requests)
        cfg.scraper.max_retries = s.getint("max_retries", cfg.scraper.max_retries)
        cfg.scraper.use_selenium = s.getboolean("use_selenium", cfg.scraper.use_selenium)
        cfg.scraper.headless = s.getboolean("headless", cfg.scraper.headless)

    if parser.has_section("logging"):
        s = parser["logging"]
        cfg.logging.level = s.get("level", cfg.logging.level).upper()
        cfg.logging.log_file = s.get("log_file", cfg.logging.log_file)

    return cfg
