param(
  [string]$ServerName = "127.0.0.1",
  [int]$ServerPort = 7860,
  [string]$AuthUser = "",
  [string]$AuthPassword = "",
  [Alias('h','?')][switch]$Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Show-Help {
  Write-Host "Usage:"
  Write-Host "  .\scripts\launch_web.ps1 [-ServerName 127.0.0.1] [-ServerPort 7860]"
  Write-Host ""
  Write-Host "Examples:"
  Write-Host "  .\scripts\launch_web.ps1"
  Write-Host "  .\scripts\launch_web.ps1 -ServerPort 7861"
  Write-Host "  .\scripts\launch_web.ps1 -ServerName 0.0.0.0 -AuthUser admin -AuthPassword <password>"
}

if ($Help) {
  Show-Help
  exit 0
}

if ([bool]$AuthUser -ne [bool]$AuthPassword) {
  throw "Provide both -AuthUser and -AuthPassword, or neither."
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")
$srcPath = Join-Path $repoRoot "src"

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
  throw "Python was not found on PATH. Install Python 3.10+ and try again."
}

$env:PYTHONPATH = $srcPath

$argsList = @(
  "-m", "anon_tool.web",
  "--server-name", $ServerName,
  "--server-port", "$ServerPort"
)

if ($AuthUser -and $AuthPassword) {
  $argsList += @("--auth-user", $AuthUser, "--auth-password", $AuthPassword)
}

Write-Host "[web] Launching Anon Tool at http://${ServerName}:$ServerPort"
Write-Host "[web] Press Ctrl+C in this window to stop it."
& $python.Source @argsList
