# YDS Kelime Koçu — kurulum / güncelleme
# dist\YDSKelimeKocu klasörünü %LOCALAPPDATA%\Programs\YDSKelimeKocu altına kopyalar ve başlatır.
# Kullanıcı verisi (%LOCALAPPDATA%\YDSKelimeKocu) bu işlemden ETKİLENMEZ.
$ErrorActionPreference = "Stop"
$src = Join-Path $PSScriptRoot "..\dist\YDSKelimeKocu"
if (-not (Test-Path (Join-Path $src "YDSKelimeKocu.exe"))) { throw "Önce exe'yi derleyin: python -m PyInstaller --noconfirm --clean yds_kocu.spec" }
$dst = Join-Path $env:LOCALAPPDATA "Programs\YDSKelimeKocu"
Get-Process YDSKelimeKocu -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 1
if (Test-Path $dst) { Remove-Item -Recurse -Force $dst }
New-Item -ItemType Directory -Force (Split-Path $dst) | Out-Null
Copy-Item -Recurse $src $dst
Start-Process (Join-Path $dst "YDSKelimeKocu.exe")
Write-Output "Kuruldu: $dst"
