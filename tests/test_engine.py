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


def test_redacts_uppercase_name_in_email_headers() -> None:
    lines = [
        InputLine(
            page=1,
            line_no=1,
            text="From: JOHN SMITH <john.smith@example.com>",
        )
    ]
    result = redact_lines(lines, default_profile())
    out = result.redacted_lines[0].text
    assert "[REDACTED_PERSON]" in out
    assert "JOHN SMITH" not in out
    assert "[REDACTED_EMAIL]" in out


def test_redacts_markdown_email_recipient_lists_and_last_first_names() -> None:
    lines = [
        InputLine(
            page=1,
            line_no=1,
            text=(
                "- **To:** Ehret, Phillip (SSC/SPC) <phillip.ehret@example.com>; "
                "Laurie Odelius <laurie.odelius@example.com>; "
                "Lauzon-Bray, Maxime (SSC/SPC) <maxime.lauzon-bray@example.com>; "
                "Emma Gilfillan <emma.gilfillan@example.com>; "
                "David Bush <david.bush@example.com>"
            ),
        )
    ]
    result = redact_lines(lines, default_profile())
    out = result.redacted_lines[0].text
    for name in [
        "Ehret, Phillip",
        "Laurie Odelius",
        "Lauzon-Bray, Maxime",
        "Emma Gilfillan",
        "David Bush",
    ]:
        assert name not in out
    assert out.count("[REDACTED_PERSON]") == 5
    assert out.count("[REDACTED_EMAIL]") == 5


def test_redacts_standalone_recipient_signature_and_contact_names() -> None:
    lines = [
        InputLine(page=1, line_no=1, text="Ehret, Phillip (SSC/SPC)<[REDACTED_EMAIL]>"),
        InputLine(page=1, line_no=2, text="Keith Stover;"),
        InputLine(page=1, line_no=3, text="Laurie Odelius;"),
        InputLine(
            page=1,
            line_no=4,
            text="Boulanger, Steve (SSC/SPC) <[REDACTED_EMAIL]>;",
        ),
        InputLine(page=1, line_no=5, text="Phillip Ehret"),
        InputLine(page=1, line_no=6, text="Maxime Lauzon-Bray (He/Him/Il)"),
        InputLine(
            page=1,
            line_no=7,
            text="For urgent matters, please contact Gilbert Sabat at [REDACTED_EMAIL].",
        ),
        InputLine(
            page=1,
            line_no=8,
            text="Please contact my manager: Dexter Alexander ([REDACTED_EMAIL]).",
        ),
    ]
    result = redact_lines(lines, default_profile())
    output = "\n".join(line.text for line in result.redacted_lines)
    for name in [
        "Ehret, Phillip",
        "Keith Stover",
        "Laurie Odelius",
        "Boulanger, Steve",
        "Phillip Ehret",
        "Maxime Lauzon-Bray",
        "Gilbert Sabat",
        "Dexter Alexander",
    ]:
        assert name not in output
    assert output.count("[REDACTED_PERSON]") == 8


def test_redacts_explicit_first_and_last_name_fields() -> None:
    lines = [
        InputLine(page=1, line_no=1, text="First Name: Phillip Last Name: Ehret"),
        InputLine(page=1, line_no=2, text="Given Name = Laurie"),
        InputLine(page=1, line_no=3, text="Surname: Odelius"),
        InputLine(page=1, line_no=4, text="FirstName Emma LastName Gilfillan"),
    ]
    result = redact_lines(lines, default_profile())
    output = "\n".join(line.text for line in result.redacted_lines)
    for name in ["Phillip", "Ehret", "Laurie", "Odelius", "Emma", "Gilfillan"]:
        assert name not in output
    assert output.count("[REDACTED_PERSON]") == 6


def test_name_tightening_preserves_technical_standalone_lines() -> None:
    lines = [
        InputLine(page=1, line_no=1, text="Message Hub"),
        InputLine(page=1, line_no=2, text="Logger Standard Edition"),
        InputLine(page=1, line_no=3, text="Technical Advisor"),
        InputLine(page=1, line_no=4, text="Principal Product Manager"),
        InputLine(page=1, line_no=5, text="OpenText Cybersecurity"),
        InputLine(page=1, line_no=6, text="Enterprise Security Operations"),
        InputLine(page=1, line_no=7, text="Pre-Sales Solution Architect"),
    ]
    result = redact_lines(lines, default_profile())
    assert [line.text for line in result.redacted_lines] == [line.text for line in lines]


def test_redacts_api_key_with_space_separator() -> None:
    lines = [InputLine(page=1, line_no=1, text="API key = abc123def456")]
    result = redact_lines(lines, default_profile())
    out = result.redacted_lines[0].text
    assert "[REDACTED_SECRET]" in out
    assert "abc123def456" not in out


def test_redacts_urls_hostnames_paths_and_usernames_before_residual_scan() -> None:
    lines = [
        InputLine(page=1, line_no=1, text="Portal: https://support.example.com/case/123"),
        InputLine(page=1, line_no=2, text="Manager host esm-prod-01.internal.local is slow"),
        InputLine(page=1, line_no=3, text=r"Log path C:\ArcSight\current\logs\console.log"),
        InputLine(page=1, line_no=4, text=r"Login: ACME\jsmith"),
    ]
    result = redact_lines(lines, default_profile())
    output = "\n".join(line.text for line in result.redacted_lines)
    assert "https://support.example.com/case/123" not in output
    assert "esm-prod-01.internal.local" not in output
    assert r"C:\ArcSight\current\logs\console.log" not in output
    assert r"ACME\jsmith" not in output
    assert not result.residual_risk_checks


def test_residual_scan_flags_tokens_and_keys() -> None:
    lines = [
        InputLine(
            page=1,
            line_no=1,
            text="JWT eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.sflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c",
        ),
        InputLine(
            page=1,
            line_no=2,
            text="SSH ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAID7t3W2h5s6A2q1J8K9z0lMNpQrStUvWxYz",
        ),
        InputLine(page=1, line_no=3, text="AWS key AKIAIOSFODNN7EXAMPLE"),
    ]
    result = redact_lines(lines, default_profile())
    checks = "\n".join(result.residual_risk_checks)
    assert "jwt_like match remains" in checks
    assert "ssh_key_like match remains" in checks
    assert "cloud_token_like match remains" in checks


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


def test_redacts_salesforce_contact_phone_and_service_account_fields() -> None:
    lines = [
        InputLine(page=1, line_no=1, text="Contact Name Gabriel Davis Account Name Example Corp"),
        InputLine(page=1, line_no=2, text="Preferred Language English Phone 7197218126"),
        InputLine(page=1, line_no=3, text="Last Modified By SFDCProd ServiceAcct, 4/15/2026"),
    ]
    result = redact_lines(lines, default_profile())
    out = [line.text for line in result.redacted_lines]
    assert "Gabriel Davis" not in out[0]
    assert "[REDACTED_PERSON]" in out[0]
    assert "7197218126" not in out[1]
    assert "[REDACTED_PHONE]" in out[1]
    assert "SFDCProd ServiceAcct" not in out[2]
    assert "[REDACTED_PERSON]" in out[2]


def test_redacts_salutation_transcript_and_case_owner_names() -> None:
    lines = [
        InputLine(page=1, line_no=1, text="Hi Omoyemi,"),
        InputLine(page=1, line_no=2, text="David Bush started transcription"),
        InputLine(page=1, line_no=3, text="Chuck Grochowski   0:05"),
        InputLine(page=1, line_no=4, text="ActionChanged Case Owner from Silvana Samper to David Bush."),
    ]
    result = redact_lines(lines, default_profile())
    output = "\n".join(line.text for line in result.redacted_lines)
    for name in ["Omoyemi", "David Bush", "Chuck Grochowski", "Silvana Samper"]:
        assert name not in output
    assert output.count("[REDACTED_PERSON]") >= 5


def test_redacts_urls_internal_hosts_paths_refs_and_subscription_ids() -> None:
    lines = [
        InputLine(page=1, line_no=1, text="https://microfocus.my.salesforce.com/500Q400000YTXoKIAX/p 29/31"),
        InputLine(page=1, line_no=2, text="Link attached: https://rdapps.otxlab.net/quixy/#/viewEntity/OCTIM77JK4629476"),
        InputLine(page=1, line_no=3, text="CWSAPI for https://DC01SIM0041:9003/cwsapi/services/v1 id [MA-j4vwgo8BABCAFSX6vdyNCw==.VM-9Lrwgo8BABCAFyX6vdyNCw==]"),
        InputLine(page=1, line_no=4, text="/opt/arcsight/arcmc/userdata/logs/pgsql/serverlog"),
        InputLine(page=1, line_no=5, text="Subject [ ref:!00D1t0vhDP.!500Q40YTXoK:ref ]"),
        InputLine(page=1, line_no=6, text="Cannot access downloads for Sub SAID2153185232-A."),
    ]
    result = redact_lines(lines, default_profile())
    output = "\n".join(line.text for line in result.redacted_lines)
    assert "salesforce.com" not in output
    assert "rdapps.otxlab.net" not in output
    assert "DC01SIM0041" not in output
    assert "/opt/arcsight" not in output
    assert "ref:!00D1t0vhDP" not in output
    assert "SAID2153185232-A" not in output


def test_redacts_username_value_after_concatenated_username_label() -> None:
    lines = [
        InputLine(page=1, line_no=1, text="Internal HPRC account has been deleted for usernameSP20d7b4"),
        InputLine(page=1, line_no=2, text="Internal HPRC account has been disabled for username SP20d7b4"),
    ]
    result = redact_lines(lines, default_profile())
    output = "\n".join(line.text for line in result.redacted_lines)
    assert "SP20d7b4" not in output
    assert output.count("[REDACTED_ACCOUNT_ID]") == 2


def test_redacts_partially_redacted_contact_name_and_concatenated_user_name() -> None:
    lines = [
        InputLine(page=1, line_no=1, text="Contact Name AMALESWARA [REDACTED_COMPANY]"),
        InputLine(page=1, line_no=2, text="UserCharles Okocha"),
    ]
    result = redact_lines(lines, default_profile())
    output = "\n".join(line.text for line in result.redacted_lines)
    assert "AMALESWARA" not in output
    assert "Charles Okocha" not in output
    assert output.count("[REDACTED_PERSON]") == 2


def test_redacts_device_ids_in_log_context_without_warning_on_java_package_names() -> None:
    lines = [
        InputLine(
            page=1,
            line_no=1,
            text="[INFO ][default.com.arcsight.agent.loadable._DeviceEventCounter] New device found [xohlx217310.68.154.116]",
        ),
        InputLine(
            page=1,
            line_no=2,
            text="[default.com.arcsight.agent.loadable._EventCounter] First event from [pgwlx1035] received.",
        ),
        InputLine(page=1, line_no=3, text="Copyright © 2000-2026 salesforce.com, inc. All rights reserved."),
        InputLine(page=1, line_no=4, text="https://portal.microfocus.com/s/article/KM000045377"),
    ]
    result = redact_lines(lines, default_profile())
    output = "\n".join(line.text for line in result.redacted_lines)
    assert "xohlx217310.68.154.116" not in output
    assert "pgwlx1035" not in output
    assert not result.residual_risk_checks


def test_preserves_software_package_versions_that_look_like_ipv4() -> None:
    lines = [
        InputLine(
            page=1,
            line_no=1,
            text=(
                "Below is the information from the scan regarding the log4j CVE findings "
                "for the SEIM SmartConnectors version 8.5.0.1 (patch 1) currently installed."
            ),
        ),
        InputLine(page=1, line_no=2, text="ArcMC 3.3.0.0 is also installed."),
        InputLine(page=1, line_no=3, text="The server IP is 10.20.30.40."),
    ]
    result = redact_lines(lines, default_profile())
    output = "\n".join(line.text for line in result.redacted_lines)
    assert "SmartConnectors version 8.5.0.1 (patch 1)" in output
    assert "ArcMC 3.3.0.0" in output
    assert "10.20.30.40" not in output
    assert "[REDACTED_IP]" in output


def test_profile_tracks_august_2026_ai_policy() -> None:
    assert default_profile().policy_profile == "opentext_gisp_ai_2026_08_11"


def test_redacts_new_customer_and_prospect_labels() -> None:
    lines = [
        InputLine(page=1, line_no=1, text="Prospect Name: Example Health Ltd"),
        InputLine(page=1, line_no=2, text="End Customer: Acme Manufacturing"),
        InputLine(page=1, line_no=3, text="Tenant: customer-prod-01"),
    ]
    result = redact_lines(lines, default_profile())
    output = "\n".join(line.text for line in result.redacted_lines)
    assert "Example Health" not in output
    assert "Acme Manufacturing" not in output
    assert "customer-prod-01" not in output
    assert output.count("[REDACTED_COMPANY]") == 3


def test_redacts_phi_and_sensitive_personal_data_labels() -> None:
    lines = [
        InputLine(page=1, line_no=1, text="Medical Record Number: MRN-123456"),
        InputLine(page=1, line_no=2, text="Diagnosis: DX-998877"),
        InputLine(page=1, line_no=3, text="Date of Birth: 04/15/1981"),
        InputLine(page=1, line_no=4, text="Passport Number: X1234567"),
    ]
    result = redact_lines(lines, default_profile())
    output = "\n".join(line.text for line in result.redacted_lines)
    assert "MRN-123456" not in output
    assert "DX-998877" not in output
    assert "04/15/1981" not in output
    assert "X1234567" not in output
    assert "[REDACTED_PHI]" in output
    assert "[REDACTED_PII]" in output


def test_redacts_financial_results_and_forecasts() -> None:
    lines = [
        InputLine(page=1, line_no=1, text="Financial forecast: Q4 revenue will be 42M."),
        InputLine(page=1, line_no=2, text="Bookings forecast for EMEA is not public."),
    ]
    result = redact_lines(lines, default_profile())
    output = "\n".join(line.text for line in result.redacted_lines)
    assert "42M" not in output
    assert "EMEA" not in output
    assert output.count("[REDACTED_FINANCIAL]") == 2


def test_policy_restriction_context_warns_without_blocking_redaction() -> None:
    lines = [
        InputLine(
            page=1,
            line_no=1,
            text="Document owner restriction: do not process through AI systems.",
        )
    ]
    result = redact_lines(lines, default_profile())
    assert result.redacted_lines[0].text == "[REDACTED_SENSITIVE_CONTEXT]"
    assert any(w.rule_id == "policy.ai_restriction" for w in result.warnings)


def test_card_detection_requires_luhn_validation() -> None:
    lines = [
        InputLine(page=1, line_no=1, text="PCI card: 4111 1111 1111 1111"),
        InputLine(page=1, line_no=2, text="Support reference: 1234 5678 9012 3456"),
        InputLine(page=1, line_no=3, text="UNITED KINGDOM +44 20 3695 6800"),
    ]
    result = redact_lines(lines, default_profile())
    output = "\n".join(line.text for line in result.redacted_lines)
    assert "4111 1111 1111 1111" not in output
    assert "[REDACTED_PCI]" in output
    assert "1234 5678 9012 3456" in output
    assert "+44 20 3695 6800" in output
    assert not any("card_like" in item for item in result.residual_risk_checks)
