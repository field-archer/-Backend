$ErrorActionPreference = "Stop"

if (-not $env:MOCK_UAV_PORT) { $env:MOCK_UAV_PORT = "9090" }
Write-Host "[mock_uav] starting mock rosbridge + uav/ugv sim on ws://127.0.0.1:$env:MOCK_UAV_PORT"
python "$PSScriptRoot/server.py"

