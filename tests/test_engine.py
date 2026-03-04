from anon_tool.redaction.engine import redact_lines
from anon_tool.rules.policy_profile_opentext import default_profile
from anon_tool.types import InputLine


def test_redacts_email_phone_and_name_context() -> None:
    lines = [
        InputLine(page=1, line_no=1, text="NSE for ArcSight, David Bush - dbush@opentext.com"),
        InputLine(page=1, line_no=2, text="Call me at 847-267-9330."),
    ]
    result = redact_lines(lines, default_profile())

    out = [line.text for line in result.redacted_lines]
    assert "[REDACTED_EMAIL]" in out[0]
    assert "[REDACTED_PERSON]" in out[0]
    assert "[REDACTED_PHONE]" in out[1]
    assert result.counts_by_category["email"] >= 1


def test_preserves_technical_context() -> None:
    lines = [
        InputLine(
            page=1,
            line_no=1,
            text="Symptoms: ArcSight Console freezes and manager unresponsive under heavy usage.",
        )
    ]
    result = redact_lines(lines, default_profile())
    assert result.redacted_lines[0].text == lines[0].text


def test_warns_on_uncertain_context_without_match() -> None:
    lines = [InputLine(page=1, line_no=1, text="This section is restricted and sensitive.")]
    result = redact_lines(lines, default_profile())
    assert any(w.rule_id == "uncertain.context" for w in result.warnings)


def test_redacts_customer_and_company_names() -> None:
    lines = [
        InputLine(page=1, line_no=1, text="Customer Name: Whitlockis LLC"),
        InputLine(page=1, line_no=2, text="Company: Acme Corporation"),
    ]
    result = redact_lines(lines, default_profile())
    out = [line.text for line in result.redacted_lines]
    assert "[REDACTED_COMPANY]" in out[0]
    assert "[REDACTED_COMPANY]" in out[1]


def test_preserves_salesforce_case_id_and_octane_id() -> None:
    lines = [
        InputLine(page=1, line_no=1, text="Case: 02981447"),
        InputLine(page=1, line_no=2, text="Internal tracking ID: OCT123456"),
        InputLine(page=1, line_no=3, text="Contact: dbush@opentext.com"),
    ]
    result = redact_lines(lines, default_profile())
    out = [line.text for line in result.redacted_lines]
    assert out[0] == "Case: 02981447"
    assert out[1] == "Internal tracking ID: OCT123456"
    assert "[REDACTED_EMAIL]" in out[2]


def test_residual_phone_scan_ignores_contract_style_ids() -> None:
    lines = [
        InputLine(page=1, line_no=1, text="Entitlement Ref: SC-00998800-October/2025-Renewals"),
        InputLine(page=1, line_no=2, text="No call required."),
    ]
    result = redact_lines(lines, default_profile())
    assert not any("phone_like" in item for item in result.residual_risk_checks)


def test_benign_not_classified_does_not_raise_uncertain_warning() -> None:
    lines = [InputLine(page=5, line_no=18, text="138.00 Not Classified")]
    result = redact_lines(lines, default_profile())
    assert not any(w.rule_id == "uncertain.context" for w in result.warnings)
