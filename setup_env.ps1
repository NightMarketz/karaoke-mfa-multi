<#
.SYNOPSIS
    Setup script for the Karaoke Pipeline environments.
.DESCRIPTION
    Creates/updates karaoke_env and demucs_env conda environments,
    clones HubertFA as a vendor dependency, and verifies Ollama.
#>

param(
    [switch]$SkipDemucs,
    [switch]$SkipOllama
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Karaoke Pipeline — Environment Setup"       -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# ── Detect conda ─────────────────────────────────────────

$conda = $null
$condaPaths = @(
    "$env:USERPROFILE\miniforge3\Scripts\conda.exe",
    "$env:USERPROFILE\miniconda3\Scripts\conda.exe",
    "$env:USERPROFILE\anaconda3\Scripts\conda.exe",
    "C:\ProgramData\miniforge3\Scripts\conda.exe"
)

foreach ($p in $condaPaths) {
    if (Test-Path $p) {
        $conda = $p
        break
    }
}

if (-not $conda) {
    $conda = Get-Command conda -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source
}

if (-not $conda) {
    Write-Host "ERROR: conda not found. Install Miniforge3 first:" -ForegroundColor Red
    Write-Host "  https://github.com/conda-forge/miniforge/releases" -ForegroundColor Yellow
    exit 1
}

Write-Host "[OK] conda: $conda" -ForegroundColor Green

# ── karaoke_env ──────────────────────────────────────────

Write-Host ""
Write-Host "── Setting up karaoke_env ──" -ForegroundColor Cyan

$envList = & $conda env list 2>$null
if ($envList -match "karaoke_env") {
    Write-Host "  karaoke_env already exists, updating..." -ForegroundColor Yellow
} else {
    Write-Host "  Creating karaoke_env (Python 3.10)..."
    & $conda create -n karaoke_env python=3.10 -y
}

$karaokePython = (& $conda run -n karaoke_env -- python -c "import sys; print(sys.executable)" 2>$null).Trim()

if (-not $karaokePython) {
    Write-Host "  ERROR: Could not find karaoke_env Python" -ForegroundColor Red
    exit 1
}

Write-Host "  Python: $karaokePython" -ForegroundColor Green

# Install main dependencies
Write-Host "  Installing Python dependencies..."
& $conda run -n karaoke_env -- pip install -r "$ProjectRoot\requirements.txt" --quiet

# Install espeak-ng for phonemizer (if not in PATH)
$espeak = Get-Command espeak-ng -ErrorAction SilentlyContinue
if (-not $espeak) {
    Write-Host ""
    Write-Host "  WARNING: espeak-ng not found in PATH." -ForegroundColor Yellow
    Write-Host "  phonemizer requires espeak-ng. Install it:" -ForegroundColor Yellow
    Write-Host "    choco install espeak-ng" -ForegroundColor Yellow
    Write-Host "    -or- download from https://github.com/espeak-ng/espeak-ng/releases" -ForegroundColor Yellow
} else {
    Write-Host "  [OK] espeak-ng: $($espeak.Source)" -ForegroundColor Green
}

Write-Host "  [OK] karaoke_env ready" -ForegroundColor Green

# ── demucs_env ───────────────────────────────────────────

if (-not $SkipDemucs) {
    Write-Host ""
    Write-Host "── Setting up demucs_env ──" -ForegroundColor Cyan

    if ($envList -match "demucs_env") {
        Write-Host "  demucs_env already exists" -ForegroundColor Yellow
    } else {
        Write-Host "  Creating demucs_env (Python 3.10)..."
        & $conda create -n demucs_env python=3.10 -y
        Write-Host "  Installing PyTorch + Demucs..."
        & $conda run -n demucs_env -- pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121 --quiet
        & $conda run -n demucs_env -- pip install demucs --quiet
    }

    $demucsPython = (& $conda run -n demucs_env -- python -c "import sys; print(sys.executable)" 2>$null).Trim()
    Write-Host "  [OK] demucs_env ready: $demucsPython" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "── Skipping demucs_env (--SkipDemucs) ──" -ForegroundColor Yellow
}

# ── HubertFA vendor ─────────────────────────────────────

Write-Host ""
Write-Host "── Setting up HubertFA ──" -ForegroundColor Cyan

$hubertfaDir = Join-Path $ProjectRoot "vendor\HubertFA"

if (Test-Path $hubertfaDir) {
    Write-Host "  vendor/HubertFA already exists" -ForegroundColor Yellow
} else {
    Write-Host "  Cloning HubertFA..."
    git clone https://github.com/wolfgitpr/HubertFA.git $hubertfaDir
}

# Install HubertFA ONNX dependencies in karaoke_env
$onnxReqs = Join-Path $hubertfaDir "requirements_onnx.txt"
if (Test-Path $onnxReqs) {
    Write-Host "  Installing HubertFA ONNX dependencies..."
    & $conda run -n karaoke_env -- pip install -r $onnxReqs --quiet
}

# Check for ONNX model
$onnxModel = Join-Path $ProjectRoot "models\hubertfa\model.onnx"
if (-not (Test-Path $onnxModel)) {
    Write-Host ""
    Write-Host "  WARNING: No ONNX model found at $onnxModel" -ForegroundColor Yellow
    Write-Host "  Download from: https://github.com/wolfgitpr/HubertFA/releases" -ForegroundColor Yellow
    Write-Host "  Place the .onnx file in models/hubertfa/" -ForegroundColor Yellow
}

Write-Host "  [OK] HubertFA ready" -ForegroundColor Green

# ── Ollama ───────────────────────────────────────────────

if (-not $SkipOllama) {
    Write-Host ""
    Write-Host "── Checking Ollama ──" -ForegroundColor Cyan

    $ollama = Get-Command ollama -ErrorAction SilentlyContinue
    if ($ollama) {
        Write-Host "  [OK] ollama: $($ollama.Source)" -ForegroundColor Green

        # Check for gemma4
        $models = & ollama list 2>$null
        if ($models -match "gemma4") {
            Write-Host "  [OK] gemma4 model found" -ForegroundColor Green
        } else {
            Write-Host "  WARNING: gemma4 model not found. Pull it:" -ForegroundColor Yellow
            Write-Host "    ollama pull gemma4:27b" -ForegroundColor Yellow
        }
    } else {
        Write-Host "  WARNING: Ollama not found in PATH." -ForegroundColor Yellow
        Write-Host "  Download from: https://ollama.com" -ForegroundColor Yellow
    }
}

# ── ffmpeg ───────────────────────────────────────────────

Write-Host ""
Write-Host "── Checking ffmpeg ──" -ForegroundColor Cyan

$ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
if ($ffmpeg) {
    Write-Host "  [OK] ffmpeg: $($ffmpeg.Source)" -ForegroundColor Green
} else {
    Write-Host "  WARNING: ffmpeg not found in PATH." -ForegroundColor Yellow
    Write-Host "  Download from: https://ffmpeg.org/download.html" -ForegroundColor Yellow
}

# ── Summary ──────────────────────────────────────────────

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Setup complete!" -ForegroundColor Green
Write-Host ""
Write-Host "  Next steps:" -ForegroundColor White
Write-Host "    1. Download HubertFA ONNX model → models/hubertfa/model.onnx" -ForegroundColor White
Write-Host "    2. Ensure Ollama is running: ollama serve" -ForegroundColor White
Write-Host "    3. Pull Gemma 4: ollama pull gemma4:27b" -ForegroundColor White
Write-Host "    4. Start the server:" -ForegroundColor White
Write-Host "       conda activate karaoke_env" -ForegroundColor Yellow
Write-Host "       python server.py" -ForegroundColor Yellow
Write-Host ""
Write-Host "  Web UI: http://localhost:5000" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
