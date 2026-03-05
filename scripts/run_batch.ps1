param(
  [string]$InputDir = ".\runs\input",
  [string]$OutputDir = ".\runs\output",
  [string]$ReportDir = ".\runs\reports",
  [string]$LogDir = ".\runs\logs",
  [string]$ArchiveDir = ".\runs\archive",
  [string]$SummaryCsv = ".\runs\batch_summary.csv",
  [switch]$Recurse,
  [switch]$FailOnWarnings,
  [switch]$StopOnError,
  [switch]$MoveToArchiveOnPass
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step {
  param([string]$Message)
  Write-Host "[batch] $Message"
}

if (-not (Test-Path -LiteralPath ".\src\anon_tool\cli.py")) {
  throw "Run this script from repo root. Missing .\src\anon_tool\cli.py"
}

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
  throw "Python is not available on PATH."
}

if (-not (Test-Path -LiteralPath $InputDir)) {
  throw "InputDir does not exist: $InputDir"
}

New-Item -ItemType Directory -Force -Path $OutputDir,$ReportDir,$LogDir,$ArchiveDir | Out-Null

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
  $outReport = Join-Path $ReportDir ($safeStem + ".report.json")
  $outLog = Join-Path $LogDir ($safeStem + ".redaction.log")

  Write-Step ("Processing: {0}" -f $pdf.FullName)
  python -m anon_tool.cli redact `
    --input $pdf.FullName `
    --output $outPdf `
    --report $outReport `
    --also-write-txt $outTxt `
    --log-file $outLog `
    --warn-threshold $warnThreshold

  $exitCode = $LASTEXITCODE
  $warningCount = -1
  $status = "error"
  $errorMessage = ""

  if (Test-Path -LiteralPath $outReport) {
    $report = Get-Content -LiteralPath $outReport -Raw -Encoding UTF8 | ConvertFrom-Json
    $warningCount = @($report.warnings).Count
    $status = [string]$report.status
  }

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
    report_file = (Resolve-Path -LiteralPath $outReport -ErrorAction SilentlyContinue).Path
    log_file = (Resolve-Path -LiteralPath $outLog -ErrorAction SilentlyContinue).Path
    cli_exit_code = $exitCode
    warning_count = $warningCount
    status = $status
    error = $errorMessage
  }) | Out-Null
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
