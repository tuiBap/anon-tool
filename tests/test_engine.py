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


def test_redacts_email_when_stuck_to_label_text() -> None:
    lines = [
        InputLine(
            page=1,
            line_no=1,
            text="Email Addresssteven.long@whitlockis.comStatusSent",
        )
    ]
    result = redact_lines(lines, default_profile())
    assert "[REDACTED_EMAIL]" in result.redacted_lines[0].text
    assert "steven.long@whitlockis.com" not in result.redacted_lines[0].text


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


def test_does_not_redact_plain_reference_prose_as_customer_id() -> None:
    lines = [
        InputLine(
            page=15,
            line_no=21,
            text="Do you have a reference? 6. Have you used a CA certificate or a Self-signed certificate?",
        ),
        InputLine(
            page=26,
            line_no=56,
            text="This is for reference. Please also respond to the previous comment.",
        ),
        InputLine(
            page=1,
            line_no=3,
            text="Entitlement Name ServiceContract SC-00998800-October/2025-Renewals",
        ),
    ]
    result = redact_lines(lines, default_profile())
    assert result.redacted_lines[0].text == lines[0].text
    assert result.redacted_lines[1].text == lines[1].text
    assert "[REDACTED_CUSTOMER_REF]" in result.redacted_lines[2].text


def test_benign_not_classified_does_not_raise_uncertain_warning() -> None:
    lines = [InputLine(page=5, line_no=18, text="138.00 Not Classified")]
    result = redact_lines(lines, default_profile())
    assert not any(w.rule_id == "uncertain.context" for w in result.warnings)


def test_preserves_kb_article_urls_even_on_customer_lines() -> None:
    lines = [
        InputLine(
            page=2,
            line_no=8,
            text=(
                "Customer update: https://portal.microfocus.com/s/article/KM000036664?language=en_US "
                "Confirmed events were being consumed"
            ),
        )
    ]
    result = redact_lines(lines, default_profile())
    output = result.redacted_lines[0].text
    assert "https://portal.microfocus.com/s/article/KM000036664?language=en_US" in output
    assert "[REDACTED_COMPANY]" not in output


def test_preserves_case_status_history_lines() -> None:
    lines = [
        InputLine(
            page=7,
            line_no=13,
            text="Changed Status from Pending Customer to Pending Support (New Activity).",
        ),
        InputLine(
            page=7,
            line_no=25,
            text="Changed Status from Pending Support (New Activity) to Pending Customer.",
        ),
    ]
    result = redact_lines(lines, default_profile())
    assert result.redacted_lines[0].text == lines[0].text
    assert result.redacted_lines[1].text == lines[1].text
    assert not any(span.rule_id == "context.customer_company" for span in result.spans)


def test_preserves_technical_phrase_that_looks_like_title_case_name() -> None:
    lines = [
        InputLine(page=115, line_no=40, text="Created By Database Connection Error"),
        InputLine(page=115, line_no=41, text="Created By David Bush"),
    ]
    result = redact_lines(lines, default_profile())
    assert result.redacted_lines[0].text == lines[0].text
    assert result.redacted_lines[1].text == "Created By [REDACTED_PERSON]"


def test_redacts_concatenated_salutation_name() -> None:
    lines = [
        InputLine(
            page=1,
            line_no=1,
            text="Thanks,Steven LongSenior ConsultantWhitlockIS",
        )
    ]
    result = redact_lines(lines, default_profile())
    assert "[REDACTED_PERSON]" in result.redacted_lines[0].text


def test_redacts_name_in_email_headers() -> None:
    lines = [
        InputLine(
            page=1,
            line_no=1,
            text="From: Steven Long <steven.long@whitlockis.com>",
        )
    ]
    result = redact_lines(lines, default_profile())
    out = result.redacted_lines[0].text
    assert "[REDACTED_PERSON]" in out
    assert "[REDACTED_EMAIL]" in out


def test_redacts_signature_style_name_with_suffix_token() -> None:
    lines = [
        InputLine(
            page=1,
            line_no=1,
            text="David BushNSE – OpenText, ArcSight Product Premium Support",
        )
    ]
    result = redact_lines(lines, default_profile())
    assert "[REDACTED_PERSON]" in result.redacted_lines[0].text


def test_does_not_redact_ui_labels_as_person_names() -> None:
    lines = [
        InputLine(page=128, line_no=1, text="Stop Logger"),
        InputLine(page=128, line_no=1, text="Demo Logs"),
        InputLine(page=128, line_no=1, text="Error Installing Folder"),
        InputLine(page=128, line_no=1, text="Additional Notes"),
        InputLine(page=128, line_no=1, text="Global Technical Support"),
        InputLine(page=128, line_no=2, text="Hi James"),
        InputLine(page=128, line_no=2, text="Issue Summary"),
        InputLine(page=127, line_no=6, text="Current Logger"),
        InputLine(page=127, line_no=6, text="Unknown Source"),
        InputLine(page=127, line_no=7, text="Hand Over"),
    ]
    result = redact_lines(lines, default_profile())
    assert [line.text for line in result.redacted_lines] == [line.text for line in lines]
    assert not any(span.rule_id == "context.name" for span in result.spans)


def test_sensitive_installation_order_does_not_raise_uncertain_warning() -> None:
    lines = [
        InputLine(
            page=13,
            line_no=16,
            text=(
                "Good day As per from the customer as below: Could you please get the vendor confirm "
                "which installer we should be installing now that we're getting this error? We are "
                "following the new path previously given, but knowing how sensitive the installation "
                "order is, and possibility of issues if done incorrectly, we want to avoid making any "
                "assumptions."
            ),
        )
    ]
    result = redact_lines(lines, default_profile())
    assert not any(w.rule_id == "uncertain.context" for w in result.warnings)
