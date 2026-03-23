@echo off
REM PriceAnalyzer – Windows çalıştırma scripti
chcp 65001 > nul

echo.
echo ========================================
echo         PriceAnalyzer v1.0
echo ========================================
echo.

REM Python kontrolü
python --version >nul 2>&1
if errorlevel 1 (
    echo [HATA] Python bulunamadi. Python 3.9+ kurun.
    pause
    exit /b 1
)

REM Sanal ortam
if not exist ".venv" (
    echo [*] Sanal ortam olusturuluyor...
    python -m venv .venv
)

call .venv\Scripts\activate.bat

REM Bağımlılıklar
echo [*] Bagimliliklar yukleniyor...
pip install -q -r requirements.txt

REM Dosya kontrolleri
set PRODUCTS_FILE=%PRODUCTS_FILE%
if "%PRODUCTS_FILE%"=="" set PRODUCTS_FILE=products.xlsx

set SITES_FILE=%SITES_FILE%
if "%SITES_FILE%"=="" set SITES_FILE=sites.txt

if not exist "%PRODUCTS_FILE%" (
    echo [UYARI] Urun dosyasi bulunamadi: %PRODUCTS_FILE%
    echo  Ornek dosya olusturmak icin: python create_sample_excel.py
    pause
    exit /b 1
)

if not exist "%SITES_FILE%" (
    echo [HATA] Site dosyasi bulunamadi: %SITES_FILE%
    pause
    exit /b 1
)

REM Çalıştır
echo [*] PriceAnalyzer calistiriliyor...
echo.
python -m price_analyzer.main --products "%PRODUCTS_FILE%" --sites "%SITES_FILE%" %*

if errorlevel 1 (
    echo.
    echo [HATA] PriceAnalyzer hata ile sonlandi.
) else (
    echo.
    echo [OK] Tamamlandi! Rapor 'output\' klasorunde.
)

pause
