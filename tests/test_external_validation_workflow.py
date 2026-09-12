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
    assert "'/app/$REFERENCE_FILE' --persist" in text
    assert "Unsupported validation profile" in text


def test_external_validation_workflow_syncs_only_approved_assets_into_container():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "Sync approved validation assets into app container" in text
    assert "test -f scripts/validate_external_offers.py" in text
    assert "test -f scripts/diagnose_external_validation.py" in text
    assert "test -f '$REFERENCE_FILE'" in text
    assert "docker compose cp scripts/validate_external_offers.py app:/app/scripts/validate_external_offers.py" in text
    assert "docker compose cp scripts/diagnose_external_validation.py app:/app/scripts/diagnose_external_validation.py" in text
    assert "docker compose cp '$REFERENCE_FILE' app:/app/$REFERENCE_FILE" in text
    assert "docker compose exec -T app mkdir -p /app/scripts /app/data/external_validation" in text


def test_external_validation_workflow_runs_read_only_diagnostics_only_after_validation_failure():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "id: validation" in text
    assert "Diagnose validation mismatch read-only" in text
    assert "if: steps.validation.outcome == 'failure'" in text
    diagnostic_command = "python /app/scripts/diagnose_external_validation.py '/app/$REFERENCE_FILE'"
    assert diagnostic_command in text
    diagnostic_section = text.split("- name: Diagnose validation mismatch read-only", 1)[1].split(
        "- name: Report resulting ALDI Dierdorf readiness", 1
    )[0]
    assert "--persist" not in diagnostic_section


def test_external_validation_workflow_reports_canonical_readiness():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "build_multi_market_readiness" in text
    assert 'r[\\\"target_key\\\"]==\\\"aldi-dierdorf\\\"' in text
    assert "production_readiness(db)" not in text
