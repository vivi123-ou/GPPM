# Khởi động TestPilot cho buổi trình diễn, dùng DB riêng (demo.db) nên không lẫn với dữ liệu thử nghiệm.
#   .\scripts\start_demo.ps1            giữ nguyên dữ liệu demo hiện có
#   .\scripts\start_demo.ps1 -Fresh     bắt đầu trống (DB cũ được đổi tên, không bị xoá)
param([switch]$Fresh, [int]$Port = 8000)

Set-Location (Split-Path $PSScriptRoot -Parent)
if ($Fresh -and (Test-Path demo.db)) {
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    Rename-Item demo.db "demo_$stamp.bak.db"
    Write-Host "Da luu DB cu: demo_$stamp.bak.db"
}
$env:TESTPILOT_DB = (Join-Path (Get-Location) "demo.db")
$env:DEMO_SHOP_URL = "http://127.0.0.1:$Port"
$env:PYTHONIOENCODING = "utf-8"
Write-Host "Mo trinh duyet: http://127.0.0.1:$Port/ai.html"
& .\.venv\Scripts\python -m uvicorn backend.main:app --host 127.0.0.1 --port $Port
