from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InputLine:
    page: int
    line_no: int
    text: str


@dataclass(frozen=True)
class DetectedSpan:
    page: int
    line: int
    start: int
    end: int
    category: str
    confidence: str
    rule_id: str
    original_text: str


@dataclass(frozen=True)
class RedactionDecision:
    span_id: str
    replacement_token: str
    reason: str


@dataclass(frozen=True)
class ProcessingWarning:
    location: str
    message: str
    rule_id: str

