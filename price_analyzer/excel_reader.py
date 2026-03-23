"""Excel dosyasından ürün kodlarını ve teklif adetlerini okuyan modül."""

import logging
from typing import Dict, List, Tuple

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
    products, _ = read_products_with_offers(file_path, cfg)
    return products


def read_products_with_offers(
    file_path: str, cfg: ExcelConfig
) -> Tuple[List[str], Dict[str, Tuple[int, int]]]:
    """
    Excel dosyasından ürün kodlarını ve Teklif-1 / Teklif-2 adetlerini okur.

    Args:
        file_path: Excel dosyasının yolu
        cfg: Excel yapılandırması

    Returns:
        (product_codes, offer_quantities)
        offer_quantities: {ürün_kodu: (teklif1_adet, teklif2_adet)}
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
    code_idx = column_letter_to_index(cfg.product_column)
    offer1_idx = column_letter_to_index(cfg.offer1_column)
    offer2_idx = column_letter_to_index(cfg.offer2_column)

    codes: List[str] = []
    quantities: Dict[str, Tuple[int, int]] = {}

    for row in ws.iter_rows(min_row=cfg.start_row, values_only=True):
        if code_idx >= len(row):
            continue
        cell_value = row[code_idx]
        if cell_value is None:
            continue
        code = str(cell_value).strip()
        if not code:
            continue

        def _int_qty(val) -> int:
            if val is None:
                return 0
            s = str(val).strip()
            # "-" veya boş → 0
            if not s or s == "-" or s.strip("-").strip() == "":
                return 0
            # "5,000.00" veya "5.000,00" → virgül ve nokta kaldır, float al
            import re
            digits = re.sub(r"[,\s]", "", s)  # binlik ayırıcı virgülü ve boşlukları kaldır
            try:
                return max(0, int(float(digits)))
            except (ValueError, TypeError):
                return 0

        qty1 = _int_qty(row[offer1_idx] if offer1_idx < len(row) else None)
        qty2 = _int_qty(row[offer2_idx] if offer2_idx < len(row) else None)

        codes.append(code)
        quantities[code] = (qty1, qty2)

    wb.close()
    logger.info(f"{len(codes)} ürün kodu okundu: {file_path}")
    return codes, quantities
