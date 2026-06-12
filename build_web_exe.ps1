$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

python -m pip install -r requirements.txt

python -m PyInstaller `
  --noconfirm `
  --clean `
  --windowed `
  --name AliExpressPedidosWeb `
  --collect-all playwright `
  --add-data "aliexpress_orders_sync\web_static;aliexpress_orders_sync\web_static" `
  run_web.py

$appDir = Join-Path $PSScriptRoot "dist\AliExpressPedidosWeb"
$dataDir = Join-Path $appDir "data"

New-Item -ItemType Directory -Force -Path $dataDir | Out-Null

Copy-Item -Force ".env" (Join-Path $appDir ".env")
Copy-Item -Force "contas.txt" (Join-Path $appDir "contas.txt")
Copy-Item -Force "README.md" (Join-Path $appDir "README.md")

$spreadsheet = Join-Path $PSScriptRoot "data\pedidos_aliexpress.xlsx"
if (Test-Path $spreadsheet) {
  Copy-Item -Force $spreadsheet (Join-Path $dataDir "pedidos_aliexpress.xlsx")
}

Write-Host ""
Write-Host "Build web concluido."
Write-Host "Abra este arquivo:"
Write-Host (Join-Path $appDir "AliExpressPedidosWeb.exe")
