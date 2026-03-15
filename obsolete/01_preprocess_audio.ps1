param(
    [Parameter(Mandatory=$true)][string]$InputAudio,
    [Parameter(Mandatory=$true)][string]$OutputDir,
    [Parameter(Mandatory=$true)][string]$JobId
)
chcp 65001 >$null
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

# Helper to get absolute normalized path
function Get-AbsPath($RelativePath) {
    return [System.IO.Path]::GetFullPath($RelativePath)
}

$AbsInput = Get-AbsPath $InputAudio
$AbsOutWav = Get-AbsPath "work\jobs\$JobId\01_wav\song.wav"

Write-Host "=== Fase A: Preprocess ==="
Write-Host "CWD: $pwd"
Write-Host "Input: $AbsInput"
Write-Host "Output: $AbsOutWav"

if (-Not (Test-Path -Path $AbsInput)) {
    Write-Error "Falta arquivo de audio em $AbsInput!"
    exit 1
}

$outDir = Split-Path $AbsOutWav
if (-Not (Test-Path $outDir)) {
    New-Item -ItemType Directory -Path $outDir -Force | Out-Null
}

Write-Host "CMD: ffmpeg -hide_banner -loglevel error -y -i `"$AbsInput`" -ar 44100 -ac 2 -c:a pcm_s16le `"$AbsOutWav`""
ffmpeg -hide_banner -loglevel error -y -i "$AbsInput" -ar 44100 -ac 2 -c:a pcm_s16le "$AbsOutWav"

if ($LASTEXITCODE -eq 0) {
    $size = (Get-Item $AbsOutWav).Length
    Write-Host "Conversão concluída: $AbsOutWav ($size bytes)" -ForegroundColor Green
}
else {
    Write-Error "Falha na conversão de áudio (ffmpeg exit $LASTEXITCODE)."
    exit 1
}
