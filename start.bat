@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1

rem Ilk calistirmada proje klasorunde .venv olustur ve paketleri SADECE oraya kur
if not exist ".venv\Scripts\python.exe" (
    echo [kurulum] .venv olusturuluyor ^(Python 3.11^)...
    py -3.11 -m venv .venv || goto :error
    ".venv\Scripts\python.exe" -m pip install --upgrade pip || goto :error
)

rem requirements.txt degistiyse paketleri guncelle
fc /b requirements.txt ".venv\installed-requirements.txt" >nul 2>&1
if errorlevel 1 (
    echo [kurulum] Paketler kuruluyor...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :error
    copy /y requirements.txt ".venv\installed-requirements.txt" >nul
)

call ".venv\Scripts\activate.bat"
python -m voicechanger %*
if errorlevel 1 goto :error
exit /b 0

:error
echo.
echo Bir hata olustu. Yukaridaki mesaji kontrol et.
pause
exit /b 1