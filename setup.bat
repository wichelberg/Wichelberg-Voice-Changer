@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
echo === Wichelberg Voice Changer kurulum ===
echo.

rem 1) Proje klasorunde .venv ve paketler (global Python'a hicbir sey kurulmaz)
if not exist ".venv\Scripts\python.exe" (
    echo [1/3] .venv olusturuluyor ^(Python 3.11^)...
    py -3.11 -m venv .venv || goto :error
    ".venv\Scripts\python.exe" -m pip install --upgrade pip || goto :error
)
fc /b requirements.txt ".venv\installed-requirements.txt" >nul 2>&1
if errorlevel 1 (
    echo [1/3] Paketler kuruluyor...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :error
    copy /y requirements.txt ".venv\installed-requirements.txt" >nul
) else (
    echo [1/3] Paketler guncel.
)

rem 2) Ortak AI modelleri (models\shared): indir + sha256 dogrula
echo [2/3] Ortak AI modelleri kontrol ediliyor...
".venv\Scripts\python.exe" -m voicechanger.tools.setup_models || goto :error

rem 3) Hiz testi: CPU ve GPU olculur, oneri config\config.json'a yazilir (kurulu ses gerekir)
echo [3/3] Hiz testi...
".venv\Scripts\python.exe" -m voicechanger.tools.benchmark
if errorlevel 1 echo Hiz testi atlandi. Bir ses kurduktan sonra tekrar setup.bat calistir.

echo.
echo Kurulum bitti. Programi start.bat ile ac.
pause
exit /b 0

:error
echo.
echo Kurulum basarisiz. Yukaridaki mesaji kontrol et.
pause
exit /b 1
