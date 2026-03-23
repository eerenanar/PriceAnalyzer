#!/usr/bin/env bash
# PriceAnalyzer – Linux/macOS çalıştırma scripti

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ──────────────────────────────────────────────
# Renk kodları
# ──────────────────────────────────────────────
GREEN="\033[0;32m"
YELLOW="\033[1;33m"
RED="\033[0;31m"
BLUE="\033[0;34m"
NC="\033[0m"  # Renksiz

print_step() { echo -e "${BLUE}▶ $1${NC}"; }
print_ok()   { echo -e "${GREEN}✓ $1${NC}"; }
print_warn() { echo -e "${YELLOW}⚠ $1${NC}"; }
print_err()  { echo -e "${RED}✗ $1${NC}"; }

echo -e "${BLUE}"
echo "╔═══════════════════════════════════════╗"
echo "║          PriceAnalyzer v1.0           ║"
echo "╚═══════════════════════════════════════╝"
echo -e "${NC}"

# ──────────────────────────────────────────────
# Python kontrolü
# ──────────────────────────────────────────────
print_step "Python kontrol ediliyor..."
if ! command -v python3 &> /dev/null; then
    print_err "Python 3 bulunamadı. Lütfen Python 3.9+ kurun."
    exit 1
fi

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
print_ok "Python $PYTHON_VERSION bulundu"

# ──────────────────────────────────────────────
# Sanal ortam
# ──────────────────────────────────────────────
if [ ! -d ".venv" ]; then
    print_step "Sanal ortam oluşturuluyor..."
    python3 -m venv .venv
    print_ok "Sanal ortam oluşturuldu (.venv)"
fi

source .venv/bin/activate
print_ok "Sanal ortam aktif"

# ──────────────────────────────────────────────
# Bağımlılıklar
# ──────────────────────────────────────────────
print_step "Bağımlılıklar kontrol ediliyor..."
pip install -q -r requirements.txt
print_ok "Bağımlılıklar hazır"

# ──────────────────────────────────────────────
# Dosya kontrolleri
# ──────────────────────────────────────────────
PRODUCTS_FILE="${PRODUCTS_FILE:-products.xlsx}"
SITES_FILE="${SITES_FILE:-sites.txt}"

if [ ! -f "$PRODUCTS_FILE" ]; then
    print_warn "Ürün dosyası bulunamadı: $PRODUCTS_FILE"
    echo "  Örnek dosya oluşturmak için: python create_sample_excel.py"
    exit 1
fi

if [ ! -f "$SITES_FILE" ]; then
    print_err "Site dosyası bulunamadı: $SITES_FILE"
    echo "  sites.txt dosyasını oluşturun ve site yapılandırmalarını ekleyin."
    exit 1
fi

# ──────────────────────────────────────────────
# Çalıştır
# ──────────────────────────────────────────────
print_step "PriceAnalyzer çalıştırılıyor..."
echo ""

python3 -m price_analyzer.main \
    --products "$PRODUCTS_FILE" \
    --sites    "$SITES_FILE" \
    "$@"

EXIT_CODE=$?

echo ""
if [ $EXIT_CODE -eq 0 ]; then
    print_ok "PriceAnalyzer tamamlandı. Çıktı 'output/' klasöründe."
else
    print_err "PriceAnalyzer hata ile sonlandı (kod: $EXIT_CODE)"
fi

exit $EXIT_CODE
