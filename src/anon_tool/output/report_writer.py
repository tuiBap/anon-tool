from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from anon_tool.redaction.engine import RedactionResult


def write_report(
    path: Path,
    input_file: Path,
    output_file: Path,
    policy_profile: str,
    result: RedactionResult,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    status = "success_with_warnings" if result.warnings else "success"
    payload = {
        "input_file": str(input_file),
        "output_file": str(output_file),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "policy_profile": policy_profile,
        "counts_by_category": result.counts_by_category,
        "warnings": [asdict(w) for w in result.warnings],
        "residual_risk_checks": result.residual_risk_checks,
        "status": status,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

