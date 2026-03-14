param(
    [Parameter(Mandatory = $true)][string]$WavPath,
    [Parameter(Mandatory = $true)][string]$OutputDir,
    [Parameter(Mandatory = $true)][string]$JobId
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 | Out-Null

$ErrorActionPreference = "Stop"

# ── Paths absolutos ────────────────────────────────────────────────────────────
$AbsWavFile = [System.IO.Path]::GetFullPath($WavPath)
$AbsStemsOut = [System.IO.Path]::GetFullPath((Join-Path "work\jobs\$JobId" "02_stems"))
$AbsCleanDir = [System.IO.Path]::GetFullPath($OutputDir)

# Nome base do arquivo de entrada (sem extensão) — Demucs usa isso para criar subpasta
$TrackName = [System.IO.Path]::GetFileNameWithoutExtension($AbsWavFile)

# Outputs finais esperados pelo pipeline
$VocalsRaw = Join-Path $AbsCleanDir "vocals_raw.wav"
$VocalsListen = Join-Path $AbsCleanDir "vocals_listen.wav"
# StemVocals sera definido dinamicamente apos demucsArgs
$StemVocals = $null


Write-Host "=== Fase B: Demucs — Separacao de Voz ==="
Write-Host "  Job ID   : $JobId"
Write-Host "  Entrada  : $AbsWavFile"
Write-Host "  Stems Out: $AbsStemsOut"
Write-Host "  Clean Out: $AbsCleanDir"

# ── Validacao ─────────────────────────────────────────────────────────────────
if (-Not (Test-Path $AbsWavFile)) {
    Write-Host "ERRO: Audio pre-processado nao encontrado: $AbsWavFile"
    exit 1
}

# ── Cria diretorios ───────────────────────────────────────────────────────────
New-Item -ItemType Directory -Path $AbsStemsOut -Force | Out-Null
New-Item -ItemType Directory -Path $AbsCleanDir -Force | Out-Null

# ── Executa Demucs ────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "=== Executando Demucs htdemucs_ft ==="

$demucsArgs = @(
    "run", "--no-capture-output", "-n", "demucs_env",
    "demucs",
    "-n", "htdemucs",
    "--segment", "7",
    "--overlap", "0.25",
    "--two-stems", "vocals",
    "-o", "`"$AbsStemsOut`"",
    "`"$AbsWavFile`""
)

# O Demucs cria pastas baseadas na versao do modelo
$StemSubDir = if ($demucsArgs -contains "htdemucs_ft") { "htdemucs_ft" } else { "htdemucs" }
$StemVocals = Join-Path $AbsStemsOut "$StemSubDir\$TrackName\vocals.wav"

Write-Host "CMD: conda $($demucsArgs -join ' ')"
Write-Host ""

# Execucao com streaming de output em tempo real
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = "conda"
$psi.Arguments = $demucsArgs -join " "
$psi.UseShellExecute = $false
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.CreateNoWindow = $true

$proc = [System.Diagnostics.Process]::Start($psi)
$sw = [System.Diagnostics.Stopwatch]::StartNew()
$lastHeartbeat = $sw.Elapsed

while (-Not $proc.HasExited) {
    # Read available output line by line without blocking
    while ($proc.StandardOutput.Peek() -ge 0) {
        $line = $proc.StandardOutput.ReadLine()
        if ($line) { Write-Host $line }
    }
    while ($proc.StandardError.Peek() -ge 0) {
        $line = $proc.StandardError.ReadLine()
        if ($line) { Write-Host $line -ForegroundColor Yellow }
    }

    $elapsed = $sw.Elapsed - $lastHeartbeat
    if ($elapsed.TotalSeconds -ge 15) {
        Write-Host "  [HEARTBEAT] Demucs rodando... $([int]$sw.Elapsed.TotalSeconds)s"
        $lastHeartbeat = $sw.Elapsed
    }
    Start-Sleep -Milliseconds 100
}

$proc.WaitForExit()
$demucsExit = $proc.ExitCode
$demucsExit = $proc.ExitCode
$sw.Stop()

Write-Host ""
Write-Host "  Demucs concluido em $([int]$sw.Elapsed.TotalSeconds)s (exit $demucsExit)"

if ($demucsExit -ne 0) {
    Write-Host "ERRO: Demucs falhou com exit code $demucsExit"
    exit 1
}

# ── Valida output do Demucs ───────────────────────────────────────────────────
if (-Not (Test-Path $StemVocals)) {
    Write-Host "ERRO: Stem de vocal nao encontrado apos Demucs: $StemVocals"
    Write-Host "  Verifique se o modelo htdemucs_ft esta instalado no ambiente demucs_env"
    Write-Host "  Comando para instalar: conda run -n demucs_env pip install demucs"
    exit 1
}

Write-Host ""
Write-Host "=== Fase C: Gerando Arquivos de Vocal ==="

# ── vocals_raw.wav — para alinhamento CTC ────────────────────────────────────
# Apenas highpass suave para preservar consoantes (4-8kHz criticos para onset)
# SEM loudnorm, SEM denoiser — o CTC precisa do sinal original
Write-Host "  Gerando vocals_raw.wav (alinhamento)..."
$ffmpegRaw = @(
    "-hide_banner", "-loglevel", "error", "-y",
    "-i", $StemVocals,
    "-ar", "16000",
    "-ac", "1",
    "-af", "highpass=f=80",
    $VocalsRaw
)
Write-Host "  CMD: ffmpeg $($ffmpegRaw -join ' ')"
& ffmpeg @ffmpegRaw

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERRO: FFmpeg falhou ao gerar vocals_raw.wav (exit $LASTEXITCODE)"
    exit 1
}
Write-Host "  OK: $VocalsRaw"

# ── vocals_listen.wav — para o video final ────────────────────────────────────
# Filtros de qualidade: denoiser leve, loudnorm, high/lowpass
# nr=6 preserva harmonicos vocais (nr alto demais remove vibrato)
# nt=c = colored noise (melhor para voz com instrumentais residuais)
Write-Host "  Gerando vocals_listen.wav (audio final)..."
$ffmpegListen = @(
    "-hide_banner", "-loglevel", "error", "-y",
    "-i", $StemVocals,
    "-ar", "44100",
    "-ac", "2",
    "-af", "highpass=f=120,lowpass=f=12000,afftdn=nf=-25:nr=6:nt=c,loudnorm=I=-16:TP=-1.5",
    $VocalsListen
)
Write-Host "  CMD: ffmpeg $($ffmpegListen -join ' ')"
& ffmpeg @ffmpegListen

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERRO: FFmpeg falhou ao gerar vocals_listen.wav (exit $LASTEXITCODE)"
    exit 1
}
Write-Host "  OK: $VocalsListen"

Write-Host ""
Write-Host "=== Fase B+C concluida ==="
Write-Host "  vocals_raw.wav    -> $VocalsRaw"
Write-Host "  vocals_listen.wav -> $VocalsListen"
Write-Host "  Stems em          -> $AbsStemsOut"
