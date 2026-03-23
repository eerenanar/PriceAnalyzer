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
    r"(?:[\$€£₺]?\s*)"
    r"(\d{1,3}(?:,\d{3})+\.\d+"        # 1,234.5678  İngilizce binlik+ondalık
    r"|\d{1,3}(?:\.\d{3})+,\d+"        # 1.234,56    Türkçe binlik+ondalık
    r"|\d{1,3}(?:,\d{3}){2,}"          # 1,234,567   İngilizce binlik tam sayı (2+ grup)
    r"|\d+\.\d+"                        # 0.0028 / 0.10000 / 1.5 — noktalı ondalık
    r"|\d+,\d+"                         # 0,0143 / 1,5 — virgüllü ondalık
    r"|\d+)"                            # 100 — tam sayı
    r"(?:\s*(?:TL|TRY|USD|EUR|GBP|₺|\$|€|£))?",
    re.IGNORECASE,
)

# Stok miktarı regex'i
STOCK_REGEX = re.compile(
    r"(\d[\d.,]*\d|\d)\s*(?:adet|pcs?|piece|stok|stock|qty|quantity|unit|birim)?",
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

    # 1.234,56 formatı (Türkçe — binlik=nokta, ondalık=virgül)
    if re.match(r"^\d{1,3}(\.\d{3})+,\d+$", raw):
        raw = raw.replace(".", "").replace(",", ".")
    # 1,234.56 formatı (İngilizce — binlik=virgül, ondalık=nokta)
    elif re.match(r"^\d{1,3}(,\d{3})+\.\d+$", raw):
        raw = raw.replace(",", "")
    # Sadece virgüllü: 1234,56 → ondalık
    elif "," in raw and "." not in raw:
        raw = raw.replace(",", ".")
    # Sadece noktalı: 0.0028 veya 1.5 veya 1234.56 → hepsi ondalık olarak bırak
    # (binlik nokta kontrolü: sol=0 ise kesinlikle ondalık; sol>0 ve sağ tam 3 hane ise binlik)
    # Para birimi sembolü ($, €, vb.) varsa kesinlikle ondalık — dönüştürme
    elif "." in raw and "," not in raw:
        has_currency_symbol = bool(re.search(r"[$€£₺]", text))
        parts = raw.split(".")
        if (not has_currency_symbol
                and len(parts) == 2 and len(parts[1]) == 3
                and parts[0] != "0" and int(parts[0]) > 0):
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
        r"in[-\s]*stock",       # "In Stock", "In-Stock:", "In-Stock: 236,913"
        r"total\s*stock",       # "Total stock: 1,980,000 parts"
        r"stok\s*(?:var|mevcut|da)",
        r"available",
        r"mevcut",
    ]
    for pattern in in_stock_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            # Sayı ara; yoksa -1 (bilinmiyor ama var)
            m = STOCK_REGEX.search(text)
            return _parse_stock_int(m.group(1)) if m else -1

    # Doğrudan sayısal değer
    match = STOCK_REGEX.search(text)
    if match:
        return _parse_stock_int(match.group(1))

    return None


def _parse_stock_int(raw: str) -> int:
    """Virgül/nokta ayırıcılı stok sayısını int'e çevirir. Örn: '1,980,000' → 1980000"""
    cleaned = re.sub(r"[,.]", "", raw)
    try:
        return int(cleaned)
    except ValueError:
        return int(re.sub(r"\D", "", raw) or "0")
