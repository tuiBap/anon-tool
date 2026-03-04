from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Pattern


@dataclass(frozen=True)
class PatternRule:
    rule_id: str
    category: str
    placeholder: str
    regex: Pattern[str]
    confidence: str = "high"


@dataclass(frozen=True)
class ProfileConfig:
    policy_profile: str
    pattern_rules: list[PatternRule]
    preserve_patterns: list[Pattern[str]]
    sensitive_keywords: list[str]
    uncertain_keywords: list[str]
    preserve_keywords: list[str]
    name_context_labels: list[str]


def _compile(rule_id: str, category: str, placeholder: str, pattern: str, confidence: str = "high") -> PatternRule:
    return PatternRule(
        rule_id=rule_id,
        category=category,
        placeholder=placeholder,
        regex=re.compile(pattern, re.IGNORECASE),
        confidence=confidence,
    )


def default_profile() -> ProfileConfig:
    pattern_rules = [
        _compile("email.basic", "email", "[REDACTED_EMAIL]", r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"),
        _compile(
            "phone.us_intl",
            "phone",
            "[REDACTED_PHONE]",
            r"(?:(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]\d{4}\b",
        ),
        _compile("ipv4", "ip_address", "[REDACTED_IP]", r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
        _compile(
            "address.street",
            "address",
            "[REDACTED_ADDRESS]",
            r"\b\d{1,6}\s+[A-Z0-9][A-Z0-9\s.-]{2,40}\s(?:AVE|AVENUE|ST|STREET|BLVD|BOULEVARD|RD|ROAD|DR|DRIVE|LN|LANE|CT|COURT|WAY)\b",
            confidence="medium",
        ),
        _compile("payment.card", "pci_data", "[REDACTED_PCI]", r"\b(?:\d[ -]*?){13,19}\b", confidence="medium"),
        _compile("cvv", "pci_data", "[REDACTED_PCI]", r"\bCVV[:\s-]*\d{3,4}\b", confidence="high"),
        _compile("ssn.us", "pii", "[REDACTED_PII]", r"\b\d{3}-\d{2}-\d{4}\b"),
        _compile("gov.id", "pii", "[REDACTED_PII]", r"\b(?:employee|emp|staff|user)\s*(?:id|#|number)[:\s-]*[A-Z0-9-]{4,}\b"),
        _compile("case.reference", "account_id", "[REDACTED_ACCOUNT_ID]", r"\b(?:INC|CASE|SR)[-:\s]*\d{4,}\b"),
        _compile(
            "contract.reference",
            "customer_id",
            "[REDACTED_CUSTOMER_REF]",
            r"\b(?:ServiceContract|Contract|Entitlement|Reference)\b[^\n]{0,40}\b[A-Z0-9][A-Z0-9-]{5,}\b",
            confidence="medium",
        ),
        _compile(
            "url.internal",
            "internal_url",
            "[REDACTED_INTERNAL_URL]",
            r"\bhttps?://(?:intranet|internal|corp|localhost)[^\s]*",
        ),
        _compile(
            "secret.token",
            "secret",
            "[REDACTED_SECRET]",
            r"\b(?:api[_-]?key|token|secret|password)\b\s*[:=]\s*[^\s]{6,}",
            confidence="high",
        ),
    ]

    preserve_patterns = [
        re.compile(r"\bCase\s*[:#-]?\s*\d{5,}\b", re.IGNORECASE),
        re.compile(r"\bOCT\d{3,}\b", re.IGNORECASE),
    ]

    sensitive_keywords = [
        "confidential",
        "secret",
        "contact information",
        "mailing address",
        "payment card",
        "pci",
        "phi",
        "health information",
        "biometric",
        "sexual orientation",
        "government",
        "dod",
        "legal",
        "financial forecast",
        "source code",
        "named support engineer",
    ]

    uncertain_keywords = [
        "do not send",
        "sensitive",
        "insufficient privileges",
        "restricted",
        "classified",
        "regulated",
    ]

    preserve_keywords = [
        "symptoms",
        "troubleshooting",
        "operating system",
        "version",
        "error",
        "service",
        "performance",
        "freeze",
        "load",
        "manager unresponsive",
        "pending support",
        "pending customer",
    ]

    name_context_labels = [
        "created by",
        "last modified by",
        "case owner",
        "user",
        "nse for",
        "thanks,",
    ]

    return ProfileConfig(
        policy_profile="opentext_gisp_ai_v1",
        pattern_rules=pattern_rules,
        preserve_patterns=preserve_patterns,
        sensitive_keywords=sensitive_keywords,
        uncertain_keywords=uncertain_keywords,
        preserve_keywords=preserve_keywords,
        name_context_labels=name_context_labels,
    )


def load_profile(config_path: Path | None) -> ProfileConfig:
    profile = default_profile()
    if not config_path:
        return profile

    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency 'PyYAML'. Install dependencies or run without --config."
        ) from exc

    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return profile

    extra_patterns = data.get("patterns", [])
    merged_patterns = list(profile.pattern_rules)
    for entry in extra_patterns:
        if not isinstance(entry, dict):
            continue
        rule_id = entry.get("rule_id")
        category = entry.get("category")
        placeholder = entry.get("placeholder")
        pattern = entry.get("pattern")
        confidence = entry.get("confidence", "high")
        if not all(isinstance(x, str) and x for x in [rule_id, category, placeholder, pattern]):
            continue
        merged_patterns.append(_compile(rule_id, category, placeholder, pattern, confidence))

    sensitive_keywords = _merge_list(profile.sensitive_keywords, data.get("sensitive_keywords"))
    uncertain_keywords = _merge_list(profile.uncertain_keywords, data.get("uncertain_keywords"))
    preserve_keywords = _merge_list(profile.preserve_keywords, data.get("preserve_keywords"))
    name_context_labels = _merge_list(profile.name_context_labels, data.get("name_context_labels"))

    return ProfileConfig(
        policy_profile=str(data.get("policy_profile") or profile.policy_profile),
        pattern_rules=merged_patterns,
        preserve_patterns=profile.preserve_patterns,
        sensitive_keywords=sensitive_keywords,
        uncertain_keywords=uncertain_keywords,
        preserve_keywords=preserve_keywords,
        name_context_labels=name_context_labels,
    )


def _merge_list(base: list[str], extra: object) -> list[str]:
    merged = list(base)
    if isinstance(extra, list):
        for item in extra:
            if isinstance(item, str) and item not in merged:
                merged.append(item)
    return merged
