from pathlib import Path


WORKFLOW = Path(".github/workflows/external-validation-production.yml")


def test_external_validation_workflow_is_manual_and_production_scoped():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in text
    assert "environment: production" in text
    assert "permissions:\n  contents: read" in text
    assert "cancel-in-progress: false" in text


def test_external_validation_workflow_uses_approved_profile_and_persists():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "type: choice" in text
    assert "aldi-dierdorf-2026-09-12" in text
    assert "data/external_validation/aldi-dierdorf-2026-09-12.json" in text
    assert "scripts/validate_external_offers.py '$REFERENCE_FILE' --persist" in text
    assert "Unsupported validation profile" in text


def test_external_validation_workflow_reports_canonical_readiness():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "build_multi_market_readiness" in text
    assert 'r[\\\"target_key\\\"]==\\\"aldi-dierdorf\\\"' in text
    assert "production_readiness(db)" not in text
