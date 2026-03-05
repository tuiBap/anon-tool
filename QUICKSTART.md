# anon-tool Quickstart (Coworkers)

This guide gets you from zero to processing Salesforce case PDFs.

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
- `runs/input` -> put raw PDFs here
- `runs/output` -> sanitized PDF/TXT output
- `runs/reports` -> JSON redaction reports
- `runs/logs` -> detailed logs
- `runs/archive` -> optional source archive

## 5) Single-file validation (recommended first)
```powershell
.\scripts\validate_case.ps1 -InputPath "C:\path\Case_12345678 ~ Salesforce - Unlimited Edition.pdf" -FailOnWarnings
```

Expected result:
- `PASS`
- `Warnings: 0` (because `-FailOnWarnings`)

## 6) Batch run for multiple PDFs
Put PDFs in `runs/input`, then:
```powershell
.\scripts\run_batch.ps1 -FailOnWarnings -MoveToArchiveOnPass
```

What this does:
- Processes all PDFs in `runs/input`
- Writes outputs/reports/logs
- Moves successfully processed source PDFs to `runs/archive`
- Writes summary CSV: `runs/batch_summary.csv`

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

## 8) Output review checklist
- Confirm no direct personal/customer identifiers remain.
- Confirm technical troubleshooting context is still readable.
- Confirm report status is `success` and warnings are `0` for strict runs.

## 9) Common issues
- `running scripts is disabled`:
  - Run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`
- `No module named ...`:
  - Re-run `python -m pip install -e .[dev]`
- `CLI exited with code 2`:
  - Warning threshold exceeded (usually due to `-FailOnWarnings`)
  - Check `runs/reports/*.report.json` for warning details

## 10) Security note
Logs may contain sensitive source values by design for debugging.
Treat files under `runs/logs` as sensitive.

