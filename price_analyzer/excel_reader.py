"""Excel dosyasından ürün kodlarını okuyan modül."""

import logging
from typing import List

import openpyxl

from .config import ExcelConfig

logger = logging.getLogger(__name__)


def column_letter_to_index(letter: str) -> int:
    """Excel sütun harfini 0 tabanlı indekse çevirir. (A -> 0, B -> 1, ...)"""
    letter = letter.upper()
    result = 0
    for char in letter:
        result = result * 26 + (ord(char) - ord("A") + 1)
    return result - 1


def read_product_codes(file_path: str, cfg: ExcelConfig) -> List[str]:
    """
    Excel dosyasından ürün kodlarını okur.

    Args:
        file_path: Excel dosyasının yolu
        cfg: Excel yapılandırması

    Returns:
        Ürün kodlarının listesi
    """
    try:
        wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    except FileNotFoundError:
        logger.error(f"Excel dosyası bulunamadı: {file_path}")
        raise
    except Exception as e:
        logger.error(f"Excel dosyası açılırken hata: {e}")
        raise

    ws = wb.active
    col_idx = column_letter_to_index(cfg.product_column)

    codes: List[str] = []
    for row_idx, row in enumerate(ws.iter_rows(min_row=cfg.start_row, values_only=True), start=cfg.start_row):
        if col_idx >= len(row):
            continue
        cell_value = row[col_idx]
        if cell_value is None:
            continue
        code = str(cell_value).strip()
        if code:
            codes.append(code)

    wb.close()
    logger.info(f"{len(codes)} ürün kodu okundu: {file_path}")
    return codes
