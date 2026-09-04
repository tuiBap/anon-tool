# Changelog

All notable changes to anon-tool are documented in this file.

## 0.1.1 - 2026-09-04

### Changed

- Expanded person-name redaction for Markdown email headers and multi-recipient lists.
- Added support for `Last, First`, standalone signature, hyphenated-name, and explicit first/last-name field formats.
- Added contact-reference name detection while preserving known technical titles and interface labels.

### Tests

- Added regression coverage for the newly supported name formats and technical false positives.
- Verified the full 69-test suite and audited the supplied 542-line anonymized sample for known name leaks.
