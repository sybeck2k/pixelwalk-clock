# Test pixelwalk: runs lint, asset checks and unit tests, then starts the live demo.
#
#   scripts\check.cmd              checks, then the demo (opens http://localhost:8888)
#   scripts\check.cmd -NoDemo      checks only
#   scripts\check.cmd -DemoOnly    skip the checks
#   scripts\check.cmd -At "2026-12-24 21:29:50" -Speed 1
#
# The demo starts a few seconds before a minute change so you see the hero jump and bump the
# block. Edit scenarios\default.toml while it runs to change simulated inputs. Ctrl-C stops it.
param(
    [switch]$NoDemo,
    [switch]$DemoOnly,
    [string]$At,
    [double]$Speed = 1.0
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "Creating .venv (Python 3.13 or 3.12) ..." -ForegroundColor Cyan
    $made = $false
    foreach ($v in "3.12", "3.13") {
        & py "-$v" -m venv .venv 2>$null
        if ($LASTEXITCODE -eq 0) { $made = $true; break }
    }
    if (-not $made) { throw "Need Python 3.12 or 3.13 (py launcher). Pillow 11.3.0 has no 3.14 wheel." }
    & $py -m pip install -q -e ".[dev]"
    if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
}

function Step($name, [scriptblock]$cmd) {
    Write-Host "== $name" -ForegroundColor Cyan
    & $cmd
    if ($LASTEXITCODE -ne 0) { Write-Host "FAILED: $name" -ForegroundColor Red; exit 1 }
}

if (-not $DemoOnly) {
    Step "ruff"           { & $py -m ruff check src tests }
    Step "asset lint"     { & $py -m pixelwalk.tools.build_assets }
    Step "unit + golden"  { & $py -m pytest -q }
    Step "night at 10%"   { & $py -m pixelwalk.tools.led_preview --at "2026-07-01 23:00" --out out\led }
    Step "contact sheet"  { & $py -m pixelwalk.tools.contact_sheet --scale 3 --out out\contact.png }
    Step "weather sheet"  { & $py -m pixelwalk.tools.contact_sheet --weather --scale 3 --out out\weather.png }
    Write-Host "All checks passed." -ForegroundColor Green
    Write-Host "Art previews: assets\build\preview_*.png"
    Write-Host "Scenes: out\contact.png (every time of day and the 8 moon phases)"
    Write-Host "Weather: out\weather.png (every condition, the three biomes, wind, barometer)"
    Write-Host "24 h GIF: .venv\Scripts\python -m pixelwalk.tools.frame_dump --speed 1440 --seconds 60 --out out\day.gif"
}

if (-not $NoDemo) {
    if (-not $At) {
        # 10 simulated seconds before the next minute (real-time speed gives a full bump on screen)
        $At = (Get-Date).Date.AddHours((Get-Date).Hour).AddMinutes((Get-Date).Minute).AddSeconds(50) |
            Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    }
    Write-Host "== demo from $At at ${Speed}x  (http://localhost:8888, Ctrl-C to stop)" -ForegroundColor Cyan
    $null = Start-Job { Start-Sleep 3; Start-Process "http://localhost:8888" }
    & $py -m pixelwalk --profile dev --at $At --speed $Speed
}
