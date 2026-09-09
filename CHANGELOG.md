# Changelog

All notable changes to anon-tool are documented in this file.

## 0.2.0 - 2026-09-09

### Added

- Markdown (`.md`) and email message (`.eml`) inputs in the CLI, web uploader, and batch script.
- Email header and body decoding, with plain-text preference and HTML-only body conversion. Attachments are excluded.

### Tests

- Added input-reader and web-loading coverage; all 78 tests pass.
- Smoke-tested automatic and explicit CLI input selection, mixed-file web processing, and batch processing with Markdown, encoded plain-text email, and HTML-only email. Verified redaction and attachment exclusion.

## 0.1.1 - 2026-09-04

### Changed

- Expanded person-name redaction for Markdown email headers and multi-recipient lists.
- Added support for `Last, First`, standalone signature, hyphenated-name, and explicit first/last-name field formats.
- Added contact-reference name detection while preserving known technical titles and interface labels.

### Tests

- Added regression coverage for the newly supported name formats and technical false positives.
- Verified the full 69-test suite and audited the supplied 542-line anonymized sample for known name leaks.
