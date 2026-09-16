from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "scripts" / "deploy-production.sh"


def test_pending_lidl_repair_bundle_is_explicitly_allowlisted_before_single_file_rules():
    script = DEPLOY.read_text(encoding="utf-8")

    runner = "grep -Fxq 'app/sqlite_alembic.py' <<<\"$SCHEMA_FILES\""
    migration_01 = (
        "grep -Fxq 'migrations/versions/20260916_01_reconcile_lidl_puderbach_duplicate.py' "
        "<<<\"$SCHEMA_FILES\""
    )
    migration_02 = (
        "grep -Fxq 'migrations/versions/20260916_02_correct_lidl_puderbach_legacy_store.py' "
        "<<<\"$SCHEMA_FILES\""
    )
    exact_bundle = (
        "! grep -Evq '^(app/sqlite_alembic\\.py|"
        "migrations/versions/20260916_01_reconcile_lidl_puderbach_duplicate\\.py|"
        "migrations/versions/20260916_02_correct_lidl_puderbach_legacy_store\\.py)$' "
        "<<<\"$SCHEMA_FILES\""
    )
    bundle_message = (
        'Controlled migration bundle recognized: Lidl Puderbach repair + reviewed Alembic target.'
    )

    bundle_pos = script.index(bundle_message)
    assert script.rfind(runner, 0, bundle_pos) != -1
    assert script.rfind(migration_01, 0, bundle_pos) != -1
    assert script.rfind(migration_02, 0, bundle_pos) != -1
    assert script.rfind(exact_bundle, 0, bundle_pos) != -1

    # The combined pending-release rule must be evaluated before the legacy
    # single-file branches, otherwise a resumed multi-file release is rejected.
    single_01_message = "Controlled data repair recognized: roll back accidental Lidl Puderbach promotion."
    assert bundle_pos < script.index(single_01_message)


def test_lidl_bundle_allowlist_stays_fail_closed_for_any_fourth_schema_file():
    script = DEPLOY.read_text(encoding="utf-8")

    exact_bundle_pattern = (
        "^(app/sqlite_alembic\\.py|"
        "migrations/versions/20260916_01_reconcile_lidl_puderbach_duplicate\\.py|"
        "migrations/versions/20260916_02_correct_lidl_puderbach_legacy_store\\.py)$"
    )

    assert exact_bundle_pattern in script
    assert "grep -Evq" in script
    assert "ERROR: database/schema-related change detected outside the approved controlled release." in script
