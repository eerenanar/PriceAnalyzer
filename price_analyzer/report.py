"""Excel rapor oluşturucu modülü."""

import logging
import os
import re
from datetime import datetime
from typing import Dict, List, Optional

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .scraper import PriceResult

logger = logging.getLogger(__name__)

# Renk sabitleri
COLOR_HEADER_BG = "1F4E79"   # Koyu mavi
COLOR_HEADER_FG = "FFFFFF"   # Beyaz
COLOR_CHEAPEST  = "E2EFDA"   # Açık yeşil
COLOR_ODD_ROW   = "F2F2F2"   # Açık gri
COLOR_ERROR     = "FCE4D6"   # Açık turuncu


def _safe_sheet_name(name: str, max_len: int = 31) -> str:
    """Excel sheet adı için geçersiz karakterleri temizler."""
    name = re.sub(r"[\\/*?:\[\]]", "_", name)
    return name[:max_len]


def _apply_header_style(cell, bold: bool = True):
    cell.font = Font(bold=bold, color=COLOR_HEADER_FG)
    cell.fill = PatternFill(fill_type="solid", fgColor=COLOR_HEADER_BG)
    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _auto_fit_columns(ws):
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            try:
                cell_len = len(str(cell.value)) if cell.value else 0
                max_len = max(max_len, cell_len)
            except Exception:
                pass
        ws.column_dimensions[col_letter].width = min(max_len + 4, 50)


def _find_cheapest(results: List[PriceResult]) -> Optional[PriceResult]:
    """OK durumundaki sonuçlar arasından en ucuz olanı döndürür."""
    valid = [r for r in results if r.status == "OK" and r.price is not None]
    if not valid:
        return None
    return min(valid, key=lambda r: r.price)


def build_report(
    all_results: Dict[str, List[PriceResult]],
    output_dir: str,
) -> str:
    """
    Tüm ürünler için Excel raporu oluşturur.

    Args:
        all_results: {ürün_kodu: [PriceResult, ...]} sözlüğü
        output_dir: Çıktı klasörü

    Returns:
        Oluşturulan Excel dosyasının yolu
    """
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = os.path.join(output_dir, f"output_{timestamp}.xlsx")

    wb = openpyxl.Workbook()

    # ── Sheet 1: Özet ──────────────────────────────────────────────────────────
    ws_summary = wb.active
    ws_summary.title = "Özet - En Ucuz Fiyatlar"

    summary_headers = [
        "Ürün Kodu", "En Ucuz Fiyat", "Para Birimi",
        "Stok Adedi", "Kaynak Site", "URL", "Tarama Tarihi",
    ]
    ws_summary.append(summary_headers)
    for col_idx, header in enumerate(summary_headers, 1):
        _apply_header_style(ws_summary.cell(row=1, column=col_idx))
    ws_summary.row_dimensions[1].height = 25

    for row_idx, (product_code, results) in enumerate(all_results.items(), start=2):
        cheapest = _find_cheapest(results)

        if cheapest:
            stock_display = (
                "Stok Yok" if cheapest.stock == 0
                else ("Var" if cheapest.stock == -1 else str(cheapest.stock))
            )
            row_data = [
                product_code,
                cheapest.price,
                cheapest.currency,
                stock_display,
                cheapest.site_name,
                cheapest.url,
                cheapest.scraped_at,
            ]
            fill_color = COLOR_CHEAPEST
        else:
            row_data = [product_code, "Bulunamadı", "", "", "", "", ""]
            fill_color = COLOR_ERROR

        ws_summary.append(row_data)

        for col_idx in range(1, len(summary_headers) + 1):
            cell = ws_summary.cell(row=row_idx, column=col_idx)
            if fill_color:
                cell.fill = PatternFill(fill_type="solid", fgColor=fill_color)
            cell.alignment = Alignment(horizontal="left", vertical="center")

    # Fiyat sütununa format uygula
    for row in ws_summary.iter_rows(min_row=2, min_col=2, max_col=2):
        for cell in row:
            if isinstance(cell.value, (int, float)):
                cell.number_format = '#,##0.00'

    _auto_fit_columns(ws_summary)
    ws_summary.freeze_panes = "A2"

    # ── Per-Ürün Sheetleri ─────────────────────────────────────────────────────
    detail_headers = [
        "Site Adı", "Birim Fiyat", "Para Birimi",
        "Stok Adedi", "URL", "Durum", "Tarama Tarihi",
    ]

    for product_code, results in all_results.items():
        sheet_name = _safe_sheet_name(product_code)
        ws = wb.create_sheet(title=sheet_name)

        ws.append(detail_headers)
        for col_idx, header in enumerate(detail_headers, 1):
            _apply_header_style(ws.cell(row=1, column=col_idx))
        ws.row_dimensions[1].height = 25

        cheapest = _find_cheapest(results)

        for row_idx, result in enumerate(results, start=2):
            stock_display = (
                "Stok Yok" if result.stock == 0
                else ("Var" if result.stock == -1 else (str(result.stock) if result.stock is not None else ""))
            )
            row_data = [
                result.site_name,
                result.price,
                result.currency,
                stock_display,
                result.url,
                result.status,
                result.scraped_at,
            ]
            ws.append(row_data)

            # Satır rengi: en ucuz = yeşil, hata = turuncu, çift/tek = gri/beyaz
            if cheapest and result is cheapest:
                bg = COLOR_CHEAPEST
            elif result.status != "OK":
                bg = COLOR_ERROR
            elif row_idx % 2 == 0:
                bg = COLOR_ODD_ROW
            else:
                bg = None

            for col_idx in range(1, len(detail_headers) + 1):
                cell = ws.cell(row=row_idx, column=col_idx)
                if bg:
                    cell.fill = PatternFill(fill_type="solid", fgColor=bg)
                cell.alignment = Alignment(horizontal="left", vertical="center")

        # Fiyat formatı
        for row in ws.iter_rows(min_row=2, min_col=2, max_col=2):
            for cell in row:
                if isinstance(cell.value, (int, float)):
                    cell.number_format = '#,##0.00'

        _auto_fit_columns(ws)
        ws.freeze_panes = "A2"

    wb.save(output_path)
    logger.info(f"Rapor oluşturuldu: {output_path}")
    return output_path
