$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

python -m pip install -r requirements.txt

python -m PyInstaller `
  --noconfirm `
  --clean `
  --windowed `
  --name AliExpressPedidos `
  --collect-all playwright `
  run_app.py

$appDir = Join-Path $PSScriptRoot "dist\AliExpressPedidos"
$dataDir = Join-Path $appDir "data"

New-Item -ItemType Directory -Force -Path $dataDir | Out-Null

Copy-Item -Force ".env" (Join-Path $appDir ".env")
Copy-Item -Force "contas.txt" (Join-Path $appDir "contas.txt")
Copy-Item -Force "README.md" (Join-Path $appDir "README.md")

Write-Host ""
Write-Host "Build concluido."
Write-Host "Abra este arquivo:"
Write-Host (Join-Path $appDir "AliExpressPedidos.exe")
