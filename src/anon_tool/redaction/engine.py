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
        line_spans.extend(_detect_labeled_pii_context(line, profile))
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
    spans.extend(_collect_software_version_spans(text))
    return spans


def _collect_software_version_spans(text: str) -> list[tuple[int, int]]:
    version_pattern = re.compile(
        r"\b(?:[A-Z][A-Z0-9_.+-]*\s+){0,4}"
        r"(?:version|versions?|ver\.?|v)\s+"
        r"\d+(?:\.\d+){1,5}(?:[-+][A-Z0-9_.-]+)?\b"
        r"(?:\s*\((?:patch|build|hotfix|hf)\s+\d+\))?",
        re.IGNORECASE,
    )
    package_pattern = re.compile(
        r"\b[A-Z][A-Z0-9_.+-]*(?:\s+[A-Z][A-Z0-9_.+-]*){0,4}\s+"
        r"\d+(?:\.\d+){1,5}(?:[-+][A-Z0-9_.-]+)?\b",
        re.IGNORECASE,
    )

    spans: list[tuple[int, int]] = []
    for pattern in (version_pattern, package_pattern):
        for match in pattern.finditer(text):
            if _software_version_match_is_safe_to_preserve(text, match):
                spans.append((match.start(), match.end()))
    return spans


def _software_version_match_is_safe_to_preserve(text: str, match: re.Match[str]) -> bool:
    value = match.group(0)
    lower_value = value.lower()
    if re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", value):
        return False
    if re.search(r"\b(?:version|versions?|ver\.?|v)\b", lower_value):
        return True

    prefix = value[: re.search(r"\d", value).start()].strip()
    if not prefix:
        return False
    blocked_prefixes = {
        "is",
        "was",
        "are",
        "were",
        "ip",
        "ipv4",
        "host",
        "server",
        "address",
        "gateway",
        "dns",
        "proxy",
        "node",
        "client",
    }
    if prefix.lower() in blocked_prefixes:
        return False
    before = text[: match.start()].rstrip()
    if before.endswith(("/", "\\", "@", "=")):
        return False
    return _looks_like_software_package_name(prefix)


def _looks_like_software_package_name(value: str) -> bool:
    tokens = value.split()
    if not tokens:
        return False
    token = tokens[-1]
    return (
        bool(re.search(r"[A-Za-z]\d|\d[A-Za-z]", token))
        or bool(re.search(r"[._+-]", token))
        or bool(re.search(r"[a-z][A-Z]", token))
        or (token.isupper() and len(token) >= 2)
    )


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
        "support",
    }
    for pattern in profile.name_context_patterns:
        for match in pattern.finditer(line.text):
            value = match.group("name")
            for start_offset, end_offset, normalized in _normalize_context_name(value):
                if normalized.lower() in {"task manager", "operating system"}:
                    continue
                if any(part.lower() in blocked_name_terms for part in normalized.split()):
                    continue
                start = match.start("name") + start_offset
                end = match.start("name") + end_offset
                spans.append(
                    DetectedSpan(
                        page=line.page,
                        line=line.line_no,
                        start=start,
                        end=end,
                        category="person_name",
                        confidence="medium",
                        rule_id="context.name",
                        original_text=normalized,
                    )
                )
    return spans


def _detect_labeled_pii_context(line: InputLine, profile: ProfileConfig) -> list[DetectedSpan]:
    text = line.text
    preserve_spans = _collect_preserve_spans(text, profile)
    spans: list[DetectedSpan] = []

    label_patterns: list[tuple[str, str, str]] = [
        (
            "context.contact_name",
            "person_name",
            r"(?:\b(?:Contact Name|Full Name|Display Name)\s+|^Name\s+)(?P<value>[A-Z][A-Z'-]+(?:\s+[A-Z][A-Z'-]+){1,3}|[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b(?=\s+(?:Account Name|Company|Customer|Email|Phone|Reference|Contact Region)\b|[,;]|$)",
        ),
        (
            "context.contact_name",
            "person_name",
            r"\bContact Name\s+(?P<value>[A-Z][A-Z'-]+|[A-Z][a-z]+)\s+\[REDACTED_",
        ),
        (
            "context.salesforce_user_name",
            "person_name",
            r"\b(?:Created By|Last Modified By|Case Owner)\s+(?P<value>[A-Z][A-Za-z0-9_.'-]+(?:\s+[A-Z][A-Za-z0-9_.'-]+){1,3})\b",
        ),
        (
            "context.concatenated_user_name",
            "person_name",
            r"\bUser(?P<value>[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\b",
        ),
        (
            "context.salutation_name",
            "person_name",
            r"\b(?:Hi|Hello|Dear)\s+(?P<value>[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})(?=[,:\s])",
        ),
        (
            "context.signature_name",
            "person_name",
            r"\b(?:Regards|Best Regards|Thanks|Thank you),?\s*(?P<value>[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\b",
        ),
        (
            "context.transcript_speaker",
            "person_name",
            r"^(?P<value>[A-Z][A-Za-z'.-]+(?:\s+[A-Z][A-Za-z'.-]+){1,3})\s+(?:(?:started|stopped)\s+transcription|\d{1,2}:\d{2})\b",
        ),
        (
            "context.case_owner_change",
            "person_name",
            r"\bCase Owner from\s+(?P<value>[A-Z][A-Za-z_.'-]+(?:\s+[A-Z][A-Za-z_.'-]+){1,3})\s+to\b",
        ),
        (
            "context.case_owner_change",
            "person_name",
            r"\bCase Owner from\s+[A-Z][A-Za-z_.'-]+(?:\s+[A-Z][A-Za-z_.'-]+){1,3}\s+to\s+(?P<value>[A-Z][A-Za-z_.'-]+(?:\s+[A-Z][A-Za-z_.'-]+){1,3})\b",
        ),
        (
            "context.labeled_phone",
            "phone",
            r"\b(?:Phone|Mobile|Cell|Business Phone|Partner Business Phone)\s*(?P<value>(?:\+?1\s*)?\d{10})(?!\d)\b",
        ),
        (
            "context.username",
            "account_id",
            r"\b(?:user(?:name)?|login|owner|assigned\s+to)\s*(?:is|:|=)?\s*(?P<value>[A-Z0-9_.\\-]{3,})\b",
        ),
    ]
    for rule_id, category, pattern in label_patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            value = match.group("value")
            if _is_ignored_context_value(value):
                continue
            start = match.start("value")
            end = match.end("value")
            if _overlaps_preserve(start, end, preserve_spans):
                continue
            spans.append(
                DetectedSpan(
                    page=line.page,
                    line=line.line_no,
                    start=start,
                    end=end,
                    category=category,
                    confidence="high",
                    rule_id=rule_id,
                    original_text=value,
                )
            )

    spans.extend(_detect_sensitive_artifacts(line, preserve_spans))
    return spans


def _is_ignored_context_value(value: str) -> bool:
    normalized = value.strip().lower()
    ignored_values = {
        "new activity",
        "pending customer",
        "pending support",
        "support portal",
        "value not assigned",
        "unknown source",
    }
    ignored_parts = {
        "account",
        "address",
        "case",
        "comment",
        "company",
        "contact",
        "customer",
        "email",
        "error",
        "information",
        "manager",
        "mobile",
        "name",
        "phone",
        "portal",
        "product",
        "service",
        "status",
        "support",
        "system",
        "user",
        "version",
    }
    return normalized in ignored_values or any(part in ignored_parts for part in normalized.split())


def _detect_sensitive_artifacts(line: InputLine, preserve_spans: list[tuple[int, int]]) -> list[DetectedSpan]:
    artifact_patterns: list[tuple[str, str, str]] = [
        ("url.salesforce", "internal_url", r"\bhttps?://[^\s<>'\")\]]*\.salesforce\.com/[^\s<>'\")\]]*"),
        ("url.internal_host", "internal_url", r"\bhttps?://[A-Z0-9_-]+(?::\d{2,5})?(?:/[^\s<>'\")\]]*)?"),
        ("url.any", "internal_url", r"\bhttps?://[^\s<>'\")\]]+"),
        (
            "hostname.internal",
            "internal_url",
            r"\b(?:[A-Z]{2}\d{2}[A-Z]{3,}\d{3,}|[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.(?:local|internal|corp|lan|mil|otxlab\.net))(?::\d{2,5})?\b",
        ),
        (
            "path.internal",
            "internal_url",
            r"(?:[A-Z]:\\(?:[^\\/:*?\"<>|\r\n]+\\)*[^\\/:*?\"<>|\r\n]+|\\\\[A-Z0-9_.-]+\\[^\s]+|/(?:opt|etc|var|home|users|usr|tmp|srv|mnt|root)(?:/[^\s,;:)\]]+)+)",
        ),
        ("salesforce.ref", "account_id", r"\bref:![A-Z0-9.:-]+!?[A-Z0-9.:!-]*\b"),
        ("salesforce.object_id", "account_id", r"\b(?:500|701)[A-Z0-9]{12,15}\b"),
        ("subscription.said", "customer_id", r"\b(?:Sub\s*)?SAID[A-Z0-9-]{6,}\b"),
        ("arcsight.entity_id", "account_id", r"\b(?:MA|VM)-[A-Z0-9+/=_-]{12,}\b"),
        ("log.device_id", "account_id", r"\b(?:New device found|First event from)\s+\[(?P<device>[A-Z0-9_.-]{5,})\]?"),
    ]
    spans: list[DetectedSpan] = []
    for rule_id, category, pattern in artifact_patterns:
        for match in re.finditer(pattern, line.text, re.IGNORECASE):
            start = match.start("device") if "device" in match.groupdict() else match.start()
            end = match.end("device") if "device" in match.groupdict() else match.end()
            if _overlaps_preserve(start, end, preserve_spans):
                continue
            spans.append(
                DetectedSpan(
                    page=line.page,
                    line=line.line_no,
                    start=start,
                    end=end,
                    category=category,
                    confidence="high",
                    rule_id=rule_id,
                    original_text=line.text[start:end],
                )
            )
    return spans


def _normalize_context_name(value: str) -> list[tuple[int, int, str]]:
    trimmed = value.strip()
    if not trimmed:
        return []

    if " " in trimmed:
        return [(0, len(trimmed), trimmed)]

    pieces = list(re.finditer(r"[A-Z][a-z]+", trimmed))
    if len(pieces) < 2:
        return []

    title_words = {
        "admin",
        "administrator",
        "associate",
        "consultant",
        "director",
        "engineer",
        "head",
        "lead",
        "manager",
        "officer",
        "partner",
        "president",
        "senior",
        "specialist",
        "support",
        "tech",
        "technical",
        "supervisor",
    }

    selected: list[re.Match[str]] = []
    for piece in pieces:
        token = piece.group(0).lower()
        if token in title_words:
            break
        selected.append(piece)
        if len(selected) >= 3:
            break

    if len(selected) < 2:
        return []

    start = selected[0].start()
    end = selected[-1].end()
    return [(start, end, trimmed[start:end])]


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
        start = match.start()
        original_text = match.group(0)
        for label in ["Account Name", "Company Name", "DNB Company Name", "DNB VI Company Name", "Company"]:
            label_match = re.search(rf"\b{re.escape(label)}\s+", original_text, re.IGNORECASE)
            if label_match:
                start = match.start() + label_match.end()
                original_text = line.text[start : match.end()]
        spans.append(
            DetectedSpan(
                page=line.page,
                line=line.line_no,
                start=start,
                end=match.end(),
                category="company_name",
                confidence="high",
                rule_id="pattern.company_legal_name",
                original_text=original_text,
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
        ("email_like", re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)),
        (
            "phone_like",
            re.compile(
                r"(?<![A-Z0-9])(?:\+?1[\s.-])?(?:\(\d{3}\)|\d{3})[\s.-]\d{3}[\s.-]\d{4}(?![A-Z0-9])"
            ),
        ),
        ("card_like", re.compile(r"\b(?:\d[ -]*?){13,19}\b")),
        ("url_like", re.compile(r"\bhttps?://[^\s<>'\")]+", re.IGNORECASE)),
        (
            "hostname_like",
            re.compile(
                r"\b(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+"
                r"(?:local|internal|corp|lan|mil|com|net|org|gov|edu)\b",
                re.IGNORECASE,
            ),
        ),
        (
            "internal_path_like",
            re.compile(
                r"(?:[A-Z]:\\(?:[^\\/:*?\"<>|\r\n]+\\)*[^\\/:*?\"<>|\r\n]+"
                r"|\\\\[A-Z0-9_.-]+\\[^\s]+"
                r"|/(?:opt|etc|var|home|users|usr|tmp|srv|mnt|root)(?:/[^\s]+)+)",
                re.IGNORECASE,
            ),
        ),
        (
            "username_like",
            re.compile(
                r"\b(?:[A-Z0-9_.-]{2,}\\[A-Z0-9_.-]{2,}"
                r"|(?:user(?:name)?|login|owner|assigned\s+to)\s*[:=]\s*[A-Z][A-Z0-9._-]{2,})\b",
                re.IGNORECASE,
            ),
        ),
        (
            "jwt_like",
            re.compile(r"\beyJ[A-Z0-9_-]{10,}\.[A-Z0-9_-]{10,}\.[A-Z0-9_-]{10,}\b", re.IGNORECASE),
        ),
        (
            "ssh_key_like",
            re.compile(
                r"-----BEGIN (?:OPENSSH|RSA|DSA|EC) PRIVATE KEY-----"
                r"|\bssh-(?:rsa|ed25519|ecdsa)\s+[A-Z0-9+/=]{20,}",
                re.IGNORECASE,
            ),
        ),
        (
            "cloud_token_like",
            re.compile(
                r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"
                r"|\bAIza[A-Z0-9_-]{35}\b"
                r"|\bgh[pousr]_[A-Z0-9_]{20,}\b"
                r"|\bsv=\d{4}-\d{2}-\d{2}&[^\s]+?\bsig=",
                re.IGNORECASE,
            ),
        ),
    ]
    findings: list[str] = []
    for line in lines:
        for label, pattern in checks:
            for match in pattern.finditer(line.text):
                if _residual_match_is_ignored(line.text, match):
                    continue
                findings.append(f"{label} match remains at p{line.page}:l{line.line_no}")
                break
    return findings


def _residual_match_is_ignored(text: str, match: re.Match[str]) -> bool:
    matched = match.group(0).lower()
    text_l = text.lower()
    if "portal.microfocus.com/s/article/km" in text_l:
        return True
    if matched == "salesforce.com" and "all rights reserved" in text_l:
        return True
    if matched == "default.com" and "default.com.arcsight" in text_l:
        return True
    return False
