# anon-tool Quickstart (Coworkers)

This guide gets you from zero to processing Salesforce case files.

## 1) Prerequisites
- Windows 10/11
- Python 3.10+ on PATH
- Git
- Access to this repository

Check Python:
```powershell
python --version
```

## 2) Clone and install
```powershell
git clone <REPO_URL>
cd anon-tool
python -m pip install -e .[dev]
```

## 3) If PowerShell blocks scripts
Run this once per PowerShell session:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

## 4) Standard folders
Use these repo folders:
- `runs/input` -> put raw PDF, TXT, and DOCX files here
- `runs/output` -> sanitized PDF/TXT output
- `runs/reports` -> retained for CLI/manual report output
- `runs/logs` -> detailed logs
- `runs/archive` -> optional source archive

## 5) Single-file validation (recommended first)
```powershell
.\scripts\validate_case.ps1 -InputPath "C:\path\Case_12345678 ~ Salesforce - Unlimited Edition.pdf" -FailOnWarnings
```

Important:
- Use PowerShell parameter style with a single dash: `-InputPath`, `-FailOnWarnings`
- Do not use double dashes (`--InputPath`) for `.ps1` script parameters

Expected result:
- `PASS`
- `Warnings: 0` (because `-FailOnWarnings`)
- Output files (sanitized PDF/TXT, log) are written to the same folder as the input file by default.
- Optional override: add `-WorkDir "C:\some\other\folder"`

## 6) Batch run for multiple files
Put PDF, TXT, or DOCX files in `runs/input`, then:
```powershell
.\scripts\run_batch.ps1 -FailOnWarnings -MoveToArchiveOnPass
```

What this does:
- Processes all supported files in `runs/input`
- Writes outputs/logs (reports are generated internally and removed)
- Moves successfully processed source files to `runs/archive`
- Writes summary CSV: `runs/batch_summary.csv`

Supported batch flags:
- `-InputDir` (default `.\\runs\\input`)
- `-OutputDir` (default: same as `-InputDir`)
- `-ReportDir` (kept for compatibility; no `.report.json` retention)
- `-LogDir` (default: same as `-InputDir`)
- `-ArchiveDir` (default `.\\runs\\archive`)
- `-SummaryCsv` (default `.\\runs\\batch_summary.csv`)
- `-ChatGPTExportDir` (optional folder for `.chatgpt.txt`)
- `-Recurse` (recursive supported-file discovery)
- `-FailOnWarnings` (treat warning count > 0 as failure)
- `-StopOnError` (exit on first CLI error)
- `-MoveToArchiveOnPass` (archive source files on successful CLI run)

Batch exit behavior:
- Exit code `1` if any input file fails in CLI execution.
- Exit code `2` if `-FailOnWarnings` is enabled and any file has warnings.

## 7) Direct CLI (optional, advanced)
```powershell
$env:PYTHONPATH="src"
python -m anon_tool.cli redact `
  --input "C:\path\case.pdf" `
  --output ".\runs\output\case.sanitized.pdf" `
  --report ".\runs\reports\case.report.json" `
  --also-write-txt ".\runs\output\case.sanitized.txt" `
  --warn-threshold 0
```

### Optional convenience command from anywhere
Install editable package so `anon-tool` command is available:
```powershell
python -m pip install -e .
```

Then use:
```powershell
anon-tool redact --input "C:\path\case.pdf" --output ".\runs\output\case.sanitized.pdf" --report ".\runs\reports\case.report.json" --also-write-txt ".\runs\output\case.sanitized.txt" --warn-threshold 0
```

### Optional PowerShell shortcut (recommended)
Add a helper function so you do not need full script paths:
1. Open your PowerShell profile:
```powershell
notepad $PROFILE
```
2. Add:
```powershell
function anon-validate {
    param(
        [Parameter(Mandatory=$true)][string]$InputPath,
        [switch]$FailOnWarnings
    )
    & "C:\Users\dbush\Projects\anon-tool\anon-tool\scripts\validate_case.ps1" -InputPath $InputPath -FailOnWarnings:$FailOnWarnings
}
```
3. Restart PowerShell (or run `. $PROFILE`)

Now run from any folder:
```powershell
anon-validate -InputPath "C:\path\case.pdf" -FailOnWarnings
```

## 8) Output review checklist
- Confirm no direct personal/customer identifiers remain.
- Confirm technical troubleshooting context is still readable.
- Confirm report status is `success` and warnings are `0` for strict runs.

## 9) Common issues
- `running scripts is disabled`:
  - Run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`
- `No module named ...`:
  - Re-run `python -m pip install -e .[dev]`
- `Input file not found: --InputPath`:
  - You used `--InputPath` instead of `-InputPath`
  - Re-run with single-dash PowerShell parameters
- `CLI exited with code 2`:
  - Warning threshold exceeded (usually due to `-FailOnWarnings`)
  - For CLI runs, check the command output or `--report` file for warning details

## 10) Security note
Logs may contain sensitive source values by design for debugging.
Treat files under `runs/logs` as sensitive.

## 11) Script behavior note
`validate_case.ps1` and `run_batch.ps1` do not keep `*.report.json` files as artifacts.
If you need persisted redaction reports, use direct CLI commands and provide an explicit `--report` path.
