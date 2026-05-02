# anon-tool

`anon-tool` is a local Python CLI for policy-aligned anonymization of CRM case exports.

## Features
- Input support for `.pdf`, `.txt`, and `.docx`
- Deterministic redaction rules (no model dependency)
- Typed placeholders such as `[REDACTED_EMAIL]`
- Sanitized PDF output for downstream summarization
- JSON redaction report (CLI mode; script runners keep report output temporary)
- Detailed audit logging

## Install
```bash
pip install -e .
```

## Usage
```bash
anon-tool redact \
  --input "C:\path\case.pdf" \
  --output "C:\path\case.sanitized.pdf" \
  --report "C:\path\case.report.json" \
  --chatgpt-export "C:\path\case.chatgpt.txt"
```

## Web UI
Launch the local dashboard interface:
```bash
anon-tool-web
```

Then open:
```text
http://127.0.0.1:7860
```

The web UI runs locally, uses the CPU processing path, and supports PDF, TXT, DOCX, or pasted text input.

### Options
- `--log-file <path>`
- `--log-raw-values true|false` (default `true`)
- `--warn-threshold <int>` (default `99999`)
- `--input-type auto|pdf|txt|docx` (default `auto`)
- `--also-write-txt <path>`
- `--chatgpt-export <path>`
- `--config <policy_rules.yaml>`

## One-Command Validation
From repo root on PowerShell:
```powershell
.\scripts\validate_case.ps1
```

With a real file:
```powershell
.\scripts\validate_case.ps1 -InputPath "C:\path\case.pdf" -FailOnWarnings
```

Default output location for `validate_case.ps1`:
- Sanitized PDF/TXT and log are written to the same directory as the input file.
- Optional override: `-WorkDir "C:\some\other\folder"`

## Standard Run Folder
Use this structure for repeatable runs:
```text
runs/
  input/      # place raw PDF, TXT, and DOCX files here
  output/     # sanitized pdf/txt
  reports/    # retained for CLI/manual use
  logs/       # redaction logs
  archive/    # optional post-run archive
```

## Batch Runner
Process all supported files in `runs/input`:
```powershell
.\scripts\run_batch.ps1
```

Batch options:

| Option | Description | Default |
|---|---|---|
| `-InputDir` | Folder to scan for PDF, TXT, and DOCX files | `.\\runs\\input` |
| `-OutputDir` | Folder for sanitized PDF/TXT outputs | same as `-InputDir` |
| `-ReportDir` | Kept for compatibility; batch runs use temporary reports | `.\\runs\\reports` |
| `-LogDir` | Folder for redaction logs | same as `-InputDir` |
| `-ArchiveDir` | Folder for source files when `-MoveToArchiveOnPass` is set | `.\\runs\\archive` |
| `-SummaryCsv` | Batch summary CSV output path | `.\\runs\\batch_summary.csv` |
| `-ChatGPTExportDir` | Optional folder for `.chatgpt.txt` outputs | (off) |
| `-Recurse` | Recursively scan supported inputs | off |
| `-FailOnWarnings` | Exit with code 2 if any file has warnings | off |
| `-StopOnError` | Stop processing on first CLI error | off |
| `-MoveToArchiveOnPass` | Move successfully processed source files to archive | off |

Process recursively and fail on warnings:
```powershell
.\scripts\run_batch.ps1 -Recurse -FailOnWarnings
```

Archive successfully processed source files into `runs/archive`:
```powershell
.\scripts\run_batch.ps1 -MoveToArchiveOnPass
```

Outputs:
- Sanitized files: `runs/output`
- Reports: CLI mode only (`--report`), scripts use temporary reports internally
- Logs: `runs/logs`
- Batch summary CSV: `runs/batch_summary.csv`

Run-level behavior:
- Exit code `1` if any CLI process failed.
- Exit code `2` if `-FailOnWarnings` is set and any file has warnings.

## Notes
- The output PDF is a normalized text rendering of the sanitized content.
- If detailed logging is enabled with raw values, logs may contain sensitive source data.
