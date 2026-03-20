"""Fiyat ve stok bilgisi ayrıştırıcı modülü."""

import logging
import re
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Bilinen para birimi sembolleri ve kodları
CURRENCY_PATTERNS = [
    (r"₺|TL|TRY", "TRY"),
    (r"\$|USD", "USD"),
    (r"€|EUR", "EUR"),
    (r"£|GBP", "GBP"),
]

# Sayısal fiyat regex'i: 1.234,56 veya 1,234.56 veya 1234.56 biçimlerini destekler
PRICE_REGEX = re.compile(
    r"(?:[\$€£₺]?\s*)"            # İsteğe bağlı sembol önde
    r"(\d{1,3}(?:[.,]\d{3})*"     # Binlik ayırıcılı sayı
    r"(?:[.,]\d{1,2})?|\d+)"      # Ondalık kısım
    r"(?:\s*(?:TL|TRY|USD|EUR|GBP|₺|\$|€|£))?",  # İsteğe bağlı birim sonda
    re.IGNORECASE,
)

# Stok miktarı regex'i
STOCK_REGEX = re.compile(
    r"(\d+)\s*(?:adet|pcs?|piece|stok|stock|qty|quantity|unit|birim)?",
    re.IGNORECASE,
)


def parse_price(text: str) -> Tuple[Optional[float], str]:
    """
    Metin içinden fiyat ve para birimini çıkarır.

    Returns:
        (fiyat_float, para_birimi) tuple'ı. Bulunamazsa (None, "")
    """
    if not text:
        return None, ""

    text = text.strip()

    # Para birimini tespit et
    currency = ""
    for pattern, code in CURRENCY_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            currency = code
            break

    # Fiyat değerini çıkar
    match = PRICE_REGEX.search(text)
    if not match:
        return None, currency

    raw = match.group(1)

    # 1.234,56 formatı (Türkçe)
    if re.match(r"^\d{1,3}(\.\d{3})*,\d{1,2}$", raw):
        raw = raw.replace(".", "").replace(",", ".")
    # 1,234.56 formatı (İngilizce)
    elif re.match(r"^\d{1,3}(,\d{3})*\.\d{1,2}$", raw):
        raw = raw.replace(",", "")
    # Sadece virgüllü ondalık: 1234,56
    elif "," in raw and "." not in raw:
        raw = raw.replace(",", ".")
    # Sadece noktalı binlik: 1.234 (ondalık değil)
    elif "." in raw and "," not in raw:
        parts = raw.split(".")
        if len(parts) == 2 and len(parts[1]) == 3:
            raw = raw.replace(".", "")

    try:
        return float(raw), currency
    except ValueError:
        logger.debug(f"Fiyat parse edilemedi: '{raw}'")
        return None, currency


def parse_stock(text: str) -> Optional[int]:
    """
    Metin içinden stok miktarını çıkarır.

    Returns:
        Stok adedi (int) veya None
    """
    if not text:
        return None

    text = text.strip()

    # Stok yok ifadeleri
    out_of_stock_patterns = [
        r"stok\s*(?:yok|d[iı]ş[iı])",
        r"out\s*of\s*stock",
        r"unavailable",
        r"mevcut\s*değil",
        r"tükendi",
        r"sold\s*out",
    ]
    for pattern in out_of_stock_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return 0

    # Stok var ama miktar belirtilmemiş
    in_stock_patterns = [
        r"in\s*stock",
        r"stok\s*(?:var|mevcut|da)",
        r"available",
        r"mevcut",
    ]
    for pattern in in_stock_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            # Sayı ara; yoksa -1 (bilinmiyor ama var)
            m = STOCK_REGEX.search(text)
            return int(m.group(1)) if m else -1

    # Doğrudan sayısal değer
    match = STOCK_REGEX.search(text)
    if match:
        return int(match.group(1))

    return None
