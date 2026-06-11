$ErrorActionPreference = "Stop"

$Model = "qwen3.6:27b"
$PromptPath = ".Codex/tasks/current-prompt.md"
$OutputPath = ".Codex/tasks/current-output.md"

if (!(Test-Path $PromptPath)) {
  Write-Error "Prompt not found: $PromptPath"
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
Write-Host "Output saved to: $OutputPath" -ForegroundColor Green
