from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass

from anon_tool.rules.policy_profile_opentext import ProfileConfig
from anon_tool.types import DetectedSpan, InputLine, ProcessingWarning, RedactionDecision


@dataclass
class RedactionResult:
    redacted_lines: list[InputLine]
    spans: list[DetectedSpan]
    decisions: list[RedactionDecision]
    warnings: list[ProcessingWarning]
    counts_by_category: dict[str, int]
    residual_risk_checks: list[str]


def redact_lines(lines: list[InputLine], profile: ProfileConfig) -> RedactionResult:
    spans: list[DetectedSpan] = []
    warnings: list[ProcessingWarning] = []

    for line in lines:
        line_spans = _detect_pattern_spans(line, profile)
        line_spans.extend(_detect_context_names(line, profile))
        line_spans.extend(_detect_customer_company_context(line, profile))
        line_spans.extend(_detect_company_legal_names(line))
        line_spans.extend(_detect_keyword_redactions(line, profile))
        spans.extend(_dedupe_and_sort_spans(line_spans))
        warning = _detect_uncertain_line(line, profile, line_spans)
        if warning:
            warnings.append(warning)

    grouped: dict[tuple[int, int], list[DetectedSpan]] = defaultdict(list)
    for span in spans:
        grouped[(span.page, span.line)].append(span)

    decisions: list[RedactionDecision] = []
    redacted_lines: list[InputLine] = []
    category_counts = Counter()

    for line in lines:
        key = (line.page, line.line_no)
        line_spans = _resolve_overlaps(grouped.get(key, []))
        redacted_text = line.text
        offset = 0
        for idx, span in enumerate(line_spans):
            placeholder = _placeholder_for_category(span.category)
            start = span.start + offset
            end = span.end + offset
            redacted_text = redacted_text[:start] + placeholder + redacted_text[end:]
            offset += len(placeholder) - (end - start)
            decisions.append(
                RedactionDecision(
                    span_id=f"{span.page}:{span.line}:{idx}",
                    replacement_token=placeholder,
                    reason=f"{span.rule_id}:{span.category}",
                )
            )
            category_counts[span.category] += 1
        redacted_lines.append(InputLine(page=line.page, line_no=line.line_no, text=redacted_text))

    residual_risk_checks = _residual_scan(redacted_lines)
    if residual_risk_checks:
        for idx, item in enumerate(residual_risk_checks, start=1):
            warnings.append(
                ProcessingWarning(
                    location=f"residual:{idx}",
                    message=item,
                    rule_id="residual.scan",
                )
            )

    return RedactionResult(
        redacted_lines=redacted_lines,
        spans=spans,
        decisions=decisions,
        warnings=warnings,
        counts_by_category=dict(category_counts),
        residual_risk_checks=residual_risk_checks,
    )


def _detect_pattern_spans(line: InputLine, profile: ProfileConfig) -> list[DetectedSpan]:
    spans: list[DetectedSpan] = []
    preserve_spans = _collect_preserve_spans(line.text, profile)
    for rule in profile.pattern_rules:
        for match in rule.regex.finditer(line.text):
            if _overlaps_preserve(match.start(), match.end(), preserve_spans):
                continue
            spans.append(
                DetectedSpan(
                    page=line.page,
                    line=line.line_no,
                    start=match.start(),
                    end=match.end(),
                    category=rule.category,
                    confidence=rule.confidence,
                    rule_id=rule.rule_id,
                    original_text=match.group(0),
                )
            )
    return spans


def _collect_preserve_spans(text: str, profile: ProfileConfig) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for pattern in profile.preserve_patterns:
        for match in pattern.finditer(text):
            spans.append((match.start(), match.end()))
    return spans


def _overlaps_preserve(start: int, end: int, preserves: list[tuple[int, int]]) -> bool:
    for p_start, p_end in preserves:
        if start < p_end and end > p_start:
            return True
    return False


def _detect_context_names(line: InputLine, profile: ProfileConfig) -> list[DetectedSpan]:
    spans: list[DetectedSpan] = []
    blocked_name_terms = {
        "error",
        "warning",
        "exception",
        "database",
        "connection",
        "service",
        "server",
        "console",
        "manager",
        "system",
    }
    for pattern in profile.name_context_patterns:
        for match in pattern.finditer(line.text):
            value = match.group("name")
            if value.lower() in {"task manager", "operating system"}:
                continue
            if any(part.lower() in blocked_name_terms for part in value.split()):
                continue
            start = match.start("name")
            end = match.end("name")
            spans.append(
                DetectedSpan(
                    page=line.page,
                    line=line.line_no,
                    start=start,
                    end=end,
                    category="person_name",
                    confidence="medium",
                    rule_id="context.name",
                    original_text=value,
                )
            )
    return spans


def _detect_keyword_redactions(line: InputLine, profile: ProfileConfig) -> list[DetectedSpan]:
    text_l = line.text.lower()
    if any(k in text_l for k in profile.preserve_keywords):
        return []

    spans: list[DetectedSpan] = []
    for keyword in profile.sensitive_keywords:
        if keyword in text_l:
            m = re.search(re.escape(keyword), line.text, re.IGNORECASE)
            if not m:
                continue
            spans.append(
                DetectedSpan(
                    page=line.page,
                    line=line.line_no,
                    start=max(0, m.start() - 25),
                    end=min(len(line.text), m.end() + 35),
                    category="sensitive_context",
                    confidence="medium",
                    rule_id="keyword.sensitive_context",
                    original_text=line.text[max(0, m.start() - 25) : min(len(line.text), m.end() + 35)],
                )
            )
            break
    return spans


def _detect_customer_company_context(line: InputLine, profile: ProfileConfig) -> list[DetectedSpan]:
    text = line.text
    text_l = text.lower()
    if "customer friendly product" in text_l:
        return []
    if "changed status from" in text_l:
        return []
    preserve_spans = _collect_preserve_spans(text, profile)

    strict_labels = [
        "customer name",
        "company name",
        "account name",
    ]
    generic_labels = [
        "customer",
        "company",
        "organization",
        "org",
        "account",
        "prospect",
    ]
    spans: list[DetectedSpan] = []
    for label in strict_labels + generic_labels:
        idx = text_l.find(label)
        if idx < 0:
            continue
        after = idx + len(label)

        # Generic labels are only safe to treat as field names when followed by an immediate delimiter.
        strict_delimiter_required = label in generic_labels
        delim_positions = [p for p in (text.find(":", after), text.find("-", after), text.find("\t", after)) if p >= 0]
        nearby_delims = [p for p in delim_positions if p - after <= 2]
        if strict_delimiter_required and not nearby_delims:
            continue
        start = min(nearby_delims if strict_delimiter_required else delim_positions) + 1 if delim_positions else after
        value = text[start:].strip()
        if not value:
            continue
        # Stop at obvious field separators.
        cut_points = [len(value)]
        for sep in [" | ", " / ", " \t ", "\t\t", "  "]:
            pos = value.find(sep)
            if pos > 0:
                cut_points.append(pos)
        redacted_value = value[: min(cut_points)].strip()
        if len(redacted_value) < 2:
            continue
        red_start = text.find(redacted_value, start)
        if red_start < 0:
            continue
        red_end = red_start + len(redacted_value)
        if _overlaps_preserve(red_start, red_end, preserve_spans):
            continue
        spans.append(
            DetectedSpan(
                page=line.page,
                line=line.line_no,
                start=red_start,
                end=red_end,
                category="company_name",
                confidence="medium",
                rule_id="context.customer_company",
                original_text=text[red_start:red_end],
            )
        )
    return spans


def _detect_company_legal_names(line: InputLine) -> list[DetectedSpan]:
    pattern = re.compile(
        r"\b(?:[A-Z][A-Za-z0-9&'().-]*\s+){0,5}"
        r"(?:Inc|Incorporated|LLC|Ltd|Limited|Corp|Corporation|Co\.|GmbH|PLC|S\.A\.)\b"
    )
    spans: list[DetectedSpan] = []
    for match in pattern.finditer(line.text):
        spans.append(
            DetectedSpan(
                page=line.page,
                line=line.line_no,
                start=match.start(),
                end=match.end(),
                category="company_name",
                confidence="high",
                rule_id="pattern.company_legal_name",
                original_text=match.group(0),
            )
        )
    return spans


def _detect_uncertain_line(
    line: InputLine, profile: ProfileConfig, existing_spans: list[DetectedSpan]
) -> ProcessingWarning | None:
    text_l = line.text.lower()
    benign_phrases = [
        "not classified",
        "sensitive the installation",
        "sensitive installation",
        "sensitive the order",
        "sensitive order",
        "sensitive path",
    ]
    if any(phrase in text_l for phrase in benign_phrases):
        return None
    uncertain = any(k in text_l for k in profile.uncertain_keywords)
    has_signal = bool(existing_spans)
    if uncertain and not has_signal:
        return ProcessingWarning(
            location=f"p{line.page}:l{line.line_no}",
            message="Line contains potential restricted context but no explicit redaction hit.",
            rule_id="uncertain.context",
        )
    return None


def _dedupe_and_sort_spans(spans: list[DetectedSpan]) -> list[DetectedSpan]:
    seen: set[tuple[int, int, int, int, str]] = set()
    unique: list[DetectedSpan] = []
    for span in spans:
        key = (span.page, span.line, span.start, span.end, span.category)
        if key in seen:
            continue
        seen.add(key)
        unique.append(span)
    return sorted(unique, key=lambda s: (s.start, -(s.end - s.start)))


def _resolve_overlaps(spans: list[DetectedSpan]) -> list[DetectedSpan]:
    if not spans:
        return []
    sorted_spans = sorted(spans, key=lambda s: (s.start, -(s.end - s.start)))
    resolved: list[DetectedSpan] = []
    for span in sorted_spans:
        if not resolved:
            resolved.append(span)
            continue
        prev = resolved[-1]
        if span.start < prev.end:
            prev_len = prev.end - prev.start
            span_len = span.end - span.start
            prev_rank = _confidence_rank(prev.confidence)
            span_rank = _confidence_rank(span.confidence)
            if span_rank > prev_rank or (span_rank == prev_rank and span_len > prev_len):
                resolved[-1] = span
            continue
        resolved.append(span)
    return resolved


def _confidence_rank(value: str) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(value, 0)


def _placeholder_for_category(category: str) -> str:
    map_ = {
        "email": "[REDACTED_EMAIL]",
        "phone": "[REDACTED_PHONE]",
        "ip_address": "[REDACTED_IP]",
        "address": "[REDACTED_ADDRESS]",
        "pci_data": "[REDACTED_PCI]",
        "pii": "[REDACTED_PII]",
        "account_id": "[REDACTED_ACCOUNT_ID]",
        "customer_id": "[REDACTED_CUSTOMER_REF]",
        "internal_url": "[REDACTED_INTERNAL_URL]",
        "secret": "[REDACTED_SECRET]",
        "person_name": "[REDACTED_PERSON]",
        "company_name": "[REDACTED_COMPANY]",
        "sensitive_context": "[REDACTED_SENSITIVE_CONTEXT]",
    }
    return map_.get(category, "[REDACTED]")


def _residual_scan(lines: list[InputLine]) -> list[str]:
    checks = [
        ("email_like", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)),
        (
            "phone_like",
            re.compile(
                r"(?<![A-Z0-9])(?:\+?1[\s.-])?(?:\(\d{3}\)|\d{3})[\s.-]\d{3}[\s.-]\d{4}(?![A-Z0-9])"
            ),
        ),
        ("card_like", re.compile(r"\b(?:\d[ -]*?){13,19}\b")),
    ]
    findings: list[str] = []
    for line in lines:
        for label, pattern in checks:
            if pattern.search(line.text):
                findings.append(f"{label} match remains at p{line.page}:l{line.line_no}")
    return findings
