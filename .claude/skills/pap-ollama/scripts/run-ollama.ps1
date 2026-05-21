# .claude/skills/pap-ollama/scripts/run-ollama.ps1
$ErrorActionPreference = "Stop"

$Model = "qwen3.6:27b"
$PromptPath = ".claude/tasks/current-prompt.md"
$OutputPath = ".claude/tasks/current-output.md"

if (!(Test-Path $PromptPath)) {
  Write-Error "Prompt não encontrado: $PromptPath"
  exit 1
}

$Prompt = Get-Content $PromptPath -Raw -Encoding UTF8

$Body = @{
  model = $Model
  prompt = $Prompt
  stream = $false
  options = @{
    temperature = 0.15
    num_ctx = 65536
  }
} | ConvertTo-Json -Depth 8

$response = Invoke-RestMethod `
  -Method Post `
  -Uri "http://localhost:11434/api/generate" `
  -Body $Body `
  -ContentType "application/json; charset=utf-8"

$response.response | Set-Content $OutputPath -Encoding UTF8
Write-Host "Output salvo em: $OutputPath" -ForegroundColor Green
