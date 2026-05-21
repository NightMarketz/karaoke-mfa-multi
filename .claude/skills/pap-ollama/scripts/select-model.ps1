param(
  [string]$Model = "qwen3.6:27b"
)

$ScriptPath = "$PSScriptRoot\run-ollama.ps1"

if (!(Test-Path $ScriptPath)) {
  Write-Error "Script não encontrado: $ScriptPath"
  exit 1
}

$content = Get-Content $ScriptPath -Raw -Encoding UTF8
$content = $content -replace '\$Model = ".*"', "`$Model = `"$Model`""
$content | Set-Content $ScriptPath -Encoding UTF8

Write-Host "Modelo PAP-Ollama alterado para: $Model" -ForegroundColor Cyan
