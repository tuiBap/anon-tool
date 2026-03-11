param(
  [string]$InputDir = ".\runs\input",
  [string]$OutputDir = "",
  [string]$ReportDir = ".\runs\reports",
  [string]$LogDir = "",
  [string]$ArchiveDir = ".\runs\archive",
  [string]$SummaryCsv = ".\runs\batch_summary.csv",
  [string]$ChatGPTExportDir = "",
  [switch]$Recurse,
  [switch]$FailOnWarnings,
  [switch]$StopOnError,
  [switch]$MoveToArchiveOnPass,
  [Alias('h','?')][switch]$Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step {
  param([string]$Message)
  Write-Host "[batch] $Message"
}

function Get-WarnCountFromCliOutput {
  param([string[]]$Lines)
  $joined = $Lines -join "`n"
  $match = [regex]::Match($joined, 'Warnings:\s*(\d+)')
  if ($match.Success) {
    return [int]$match.Groups[1].Value
  }
  return -1
}

function Show-UsageAndExamples {
  Write-Host "Usage: .\scripts\run_batch.ps1 [-InputDir <path>] [-OutputDir <path>] [-ReportDir <path>] [-LogDir <path>] [-ChatGPTExportDir <path>] [-ArchiveDir <path>] [-SummaryCsv <path>] [-Recurse] [-FailOnWarnings] [-StopOnError] [-MoveToArchiveOnPass]"
  Write-Host ""
  Write-Host "Examples:"
  Write-Host "  .\scripts\run_batch.ps1"
  Write-Host "  .\scripts\run_batch.ps1 -InputDir .\runs\input -Recurse -FailOnWarnings -MoveToArchiveOnPass"
}

function Show-Help {
  Write-Host "Usage:"
  Write-Host "  .\scripts\run_batch.ps1 [-InputDir <path>] [-OutputDir <path>] [-ReportDir <path>] [-LogDir <path>] [-ChatGPTExportDir <path>] [-ArchiveDir <path>] [-SummaryCsv <path>] [-Recurse] [-FailOnWarnings] [-StopOnError] [-MoveToArchiveOnPass] [-Help]"
  Write-Host ""
  Write-Host "Arguments:"
  Write-Host "  -InputDir             Folder containing PDFs to process (default: .\runs\input)."
  Write-Host "  -OutputDir            Folder for sanitized outputs (default: same as InputDir)."
  Write-Host "  -ReportDir            Kept for compatibility; no redaction report JSON is written."
  Write-Host "  -LogDir               Folder for anonymization logs (default: same as InputDir)."
  Write-Host "  -ChatGPTExportDir     Optional folder for ChatGPT export files (off unless specified)."
  Write-Host "  -ArchiveDir           Folder for successful source PDFs when -MoveToArchiveOnPass is used."
  Write-Host "  -SummaryCsv           Summary CSV path (default: .\runs\batch_summary.csv)."
  Write-Host "  -Recurse              Recursively find PDFs in subfolders."
  Write-Host "  -FailOnWarnings       Fail with code 2 when any file has warnings."
  Write-Host "  -StopOnError          Stop immediately on first CLI error."
  Write-Host "  -MoveToArchiveOnPass   Move successfully processed source PDFs into ArchiveDir."
  Write-Host "  -Help, -h, -?         Show this help text and exit."
  Write-Host ""
  Write-Host "Outputs:"
  Write-Host "  - Sanitized PDFs/TXT in OutputDir"
  Write-Host "  - Redaction logs in LogDir"
  Write-Host "  - batch_summary.csv at SummaryCsv"
  Write-Host ""
  Write-Host "Examples:"
  Write-Host "  .\scripts\run_batch.ps1"
  Write-Host "  .\scripts\run_batch.ps1 -InputDir .\runs\input -Recurse -FailOnWarnings"
  Write-Host "  .\scripts\run_batch.ps1 -InputDir .\runs\input -MoveToArchiveOnPass -StopOnError"
}

if ($PSBoundParameters.Count -eq 0) {
  Show-UsageAndExamples
  exit 0
}

if ($Help) {
  Show-Help
  exit 0
}

if (-not (Test-Path -LiteralPath ".\src\anon_tool\cli.py")) {
  throw "Run this script from repo root. Missing .\src\anon_tool\cli.py"
}

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
  throw "Python is not available on PATH."
}

$outputDirWasSpecified = $PSBoundParameters.ContainsKey("OutputDir")
$logDirWasSpecified = $PSBoundParameters.ContainsKey("LogDir")
if (-not $outputDirWasSpecified) { $OutputDir = $InputDir }
if (-not $logDirWasSpecified) { $LogDir = $InputDir }

$chatgptExportEnabled = -not [string]::IsNullOrWhiteSpace($ChatGPTExportDir)
if ($chatgptExportEnabled) {
  New-Item -ItemType Directory -Path $ChatGPTExportDir -Force | Out-Null
}

if (-not (Test-Path -LiteralPath $InputDir)) {
  throw "InputDir does not exist: $InputDir"
}

New-Item -ItemType Directory -Force -Path $OutputDir, $LogDir, $ArchiveDir | Out-Null

$searchArgs = @{
  LiteralPath = $InputDir
  Filter = "*.pdf"
  File = $true
}
if ($Recurse) { $searchArgs["Recurse"] = $true }

$pdfs = @(Get-ChildItem @searchArgs | Sort-Object FullName)
if ($pdfs.Count -eq 0) {
  Write-Step "No PDF files found in $InputDir"
  exit 0
}

$warnThreshold = if ($FailOnWarnings) { 0 } else { 99999 }
$env:PYTHONPATH = "src"

$results = New-Object System.Collections.Generic.List[object]

Write-Step ("Found {0} PDF file(s)" -f $pdfs.Count)

foreach ($pdf in $pdfs) {
  $stem = [IO.Path]::GetFileNameWithoutExtension($pdf.Name)
  $safeStem = ($stem -replace '[\\/:*?"<>|]', "_")
  $outPdf = Join-Path $OutputDir ($safeStem + ".sanitized.pdf")
  $outTxt = Join-Path $OutputDir ($safeStem + ".sanitized.txt")
  $outReport = New-TemporaryFile
  $outLog = Join-Path $LogDir ($safeStem + ".redaction.log")
  $chatgptExportPath = ""
  $chatgptArgs = @()
  if ($chatgptExportEnabled) {
    $chatgptExportPath = Join-Path $ChatGPTExportDir ($safeStem + ".chatgpt.txt")
    $chatgptArgs = @("--chatgpt-export", $chatgptExportPath)
  }

  Write-Step ("Processing: {0}" -f $pdf.FullName)
  $cliOutput = & python -m anon_tool.cli redact `
    --input $pdf.FullName `
    --output $outPdf `
    --report $outReport `
    --also-write-txt $outTxt `
    --log-file $outLog `
    --warn-threshold $warnThreshold `
    @chatgptArgs 2>&1
  $exitCode = $LASTEXITCODE
  $warnCount = Get-WarnCountFromCliOutput $cliOutput
  if ($warnCount -ge 0) {
    $status = if ($warnCount -eq 0) { "success" } else { "success_with_warnings" }
  }
  else {
    $status = "unknown"
  }
  $errorMessage = ""

  if ($exitCode -ne 0) {
    $errorMessage = "CLI exit code $exitCode"
    if ($StopOnError) {
      throw "Stopping on error for $($pdf.Name): $errorMessage"
    }
  }
  elseif ($MoveToArchiveOnPass) {
    $archiveTarget = Join-Path $ArchiveDir $pdf.Name
    if (Test-Path -LiteralPath $archiveTarget) {
      $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
      $name = [IO.Path]::GetFileNameWithoutExtension($pdf.Name)
      $ext = [IO.Path]::GetExtension($pdf.Name)
      $archiveTarget = Join-Path $ArchiveDir ("{0}_{1}{2}" -f $name, $stamp, $ext)
    }
    Move-Item -LiteralPath $pdf.FullName -Destination $archiveTarget -Force
  }

  $results.Add([PSCustomObject]@{
    input_file = $pdf.FullName
    output_pdf = (Resolve-Path -LiteralPath $outPdf -ErrorAction SilentlyContinue).Path
    output_txt = (Resolve-Path -LiteralPath $outTxt -ErrorAction SilentlyContinue).Path
    report_file = ""
    log_file = (Resolve-Path -LiteralPath $outLog -ErrorAction SilentlyContinue).Path
    cli_exit_code = $exitCode
    warning_count = $warnCount
    status = $status
    error = $errorMessage
  }) | Out-Null

  if ($outReport -and (Test-Path -LiteralPath $outReport)) {
    Remove-Item -LiteralPath $outReport -Force -ErrorAction SilentlyContinue
  }
}

$summaryDir = Split-Path -Parent $SummaryCsv
if ($summaryDir) {
  New-Item -ItemType Directory -Force -Path $summaryDir | Out-Null
}
$results | Export-Csv -LiteralPath $SummaryCsv -NoTypeInformation -Encoding UTF8

$total = $results.Count
$failures = @($results | Where-Object { $_.cli_exit_code -ne 0 }).Count
$withWarnings = @($results | Where-Object { $_.warning_count -gt 0 }).Count

Write-Host ""
Write-Host "Batch Summary"
Write-Host "-------------"
Write-Host ("Total files:     {0}" -f $total)
Write-Host ("CLI failures:    {0}" -f $failures)
Write-Host ("With warnings:   {0}" -f $withWarnings)
Write-Host ("Summary CSV:     {0}" -f (Resolve-Path -LiteralPath $SummaryCsv).Path)

if ($failures -gt 0) {
  exit 1
}
if ($FailOnWarnings -and $withWarnings -gt 0) {
  exit 2
}
exit 0
