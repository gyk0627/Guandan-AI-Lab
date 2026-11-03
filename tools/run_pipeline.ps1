# One-click pipeline: collect -> check -> export -> train -> evaluate.
#
# NOTE: this file is intentionally ASCII-only.
# Windows PowerShell 5.1 reads .ps1 files as ANSI unless they have a BOM,
# so non-ASCII text here would break parsing on a fresh machine.
#
# Usage:
#   .\tools\run_pipeline.ps1
#   .\tools\run_pipeline.ps1 -Games 2000 -Epochs 20
#   .\tools\run_pipeline.ps1 -SkipCollect            # reuse existing data
#   .\tools\run_pipeline.ps1 -SkipCollect -SkipExport
#
# Stops on the first failing step and reports which one.

param(
    [int]$Games = 5000,
    [int]$SeedStart = 40000,
    [int]$Epochs = 40,
    [int]$BatchSize = 64,
    [int]$EvalGames = 200,
    [string]$Level = "2",
    [switch]$SkipCollect,
    [switch]$SkipExport
)

$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
$py = Join-Path $repo ".venv\Scripts\python.exe"

if (-not (Test-Path $py)) {
    throw "Python not found: $py"
}

$env:PYTHONIOENCODING = "utf-8"

function Invoke-Step {
    param([string]$Name, [scriptblock]$Body)

    $started = Get-Date

    Write-Host ""
    Write-Host ("=" * 66) -ForegroundColor Cyan
    Write-Host "  $Name" -ForegroundColor Cyan
    Write-Host ("=" * 66) -ForegroundColor Cyan

    & $Body

    if ($LASTEXITCODE -ne 0) {
        throw "Step failed: $Name (exit code $LASTEXITCODE)"
    }

    $seconds = ((Get-Date) - $started).TotalSeconds
    Write-Host ("  [ok] {0:N0}s" -f $seconds) -ForegroundColor Green
}

Push-Location $repo

try {
    if (-not $SkipCollect) {
        Invoke-Step "1/5 collect $Games games" {
            & $py -X utf8 -m training.collect_data --games $Games --seed-start $SeedStart
        }
    } else {
        Write-Host "skip collect, reuse existing data" -ForegroundColor Yellow
    }

    Invoke-Step "2/5 dataset structure check" {
        & $py -X utf8 -m training.check_dataset
    }

    if (-not $SkipExport) {
        Invoke-Step "3/5 export (replay + candidate rebuild + verify)" {
            & $py -X utf8 -m training.export_dataset
        }
    } else {
        Write-Host "skip export" -ForegroundColor Yellow
    }

    Invoke-Step "4/5 train $Epochs epochs" {
        & $py -X utf8 -m training.train_bc --epochs $Epochs --batch-size $BatchSize --min-candidates 2
    }

    Invoke-Step "5/5 evaluate vs heuristic ($EvalGames pairs)" {
        & $py -X utf8 -m training.evaluate_neural --games $EvalGames --opponent heuristic --level $Level
    }

    Write-Host ""
    Write-Host "done. update models/README.md and docs/STATUS.md with the new numbers." -ForegroundColor Green
}
finally {
    Pop-Location
}
