from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts" / "run-production-release.sh"
DEPLOY = ROOT / "scripts" / "deploy-production.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "deploy-production.yml"


def test_release_wrapper_uses_versioned_post_success_marker_as_deployment_truth():
    script = WRAPPER.read_text()

    assert 'SUCCESS_MARKER="$BACKUP_DIR/.last-successful-release"' in script
    assert 'MARKER_VERSION="v2"' in script
    assert 'git merge-base --is-ancestor "$LAST_SUCCESSFUL_SHA" "$TARGET_SHA"' in script
    assert 'git reset --hard "$LAST_SUCCESSFUL_SHA"' in script

    deploy_call = 'FORCE_FULL_REDEPLOY="$FORCE_FULL_REDEPLOY" bash "$DEPLOY_SCRIPT" "$TARGET_SHA"'
    marker_write = 'printf \'%s %s\\n\' "$MARKER_VERSION" "$TARGET_SHA" > "${SUCCESS_MARKER}.tmp"'
    marker_commit = 'mv "${SUCCESS_MARKER}.tmp" "$SUCCESS_MARKER"'

    assert deploy_call in script
    assert marker_write in script
    assert marker_commit in script
    assert script.index(deploy_call) < script.index(marker_write) < script.index(marker_commit)


def test_release_wrapper_forces_bootstrap_and_legacy_marker_redeploy():
    script = WRAPPER.read_text()

    assert 'FORCE_FULL_REDEPLOY=1' in script
    assert 'Legacy/unverified successful-release marker detected; forcing a full redeploy.' in script
    assert 'No verified successful-release marker yet; forcing a full bootstrap deploy.' in script
    assert 'Checkout already matches unverified marker target; deploy will still rebuild and recreate production services.' in script


def test_release_wrapper_guards_dirty_checkout_before_normalization():
    script = WRAPPER.read_text()

    dirty_guard = 'git status --porcelain --untracked-files=no'
    fetch = 'git fetch --prune origin main'
    reset = 'git reset --hard "$LAST_SUCCESSFUL_SHA"'

    assert dirty_guard in script
    assert script.index(dirty_guard) < script.index(fetch) < script.index(reset)


def test_deploy_script_force_full_redeploy_bypasses_same_sha_short_circuit():
    script = DEPLOY.read_text()

    assert 'FORCE_FULL_REDEPLOY="${FORCE_FULL_REDEPLOY:-0}"' in script
    assert '&& "$FORCE_FULL_REDEPLOY" -eq 0' in script
    assert 'Forcing full production rebuild/recreate because deployment proof is missing or unverified.' in script

    force_block = 'if [[ "$FORCE_FULL_REDEPLOY" -eq 1 ]]; then'
    assert force_block in script
    force_pos = script.index(force_block)
    assert script.index('APP=1', force_pos) > force_pos
    assert script.index('FRONTEND=1', force_pos) > force_pos
    assert script.index('GATEWAY=1', force_pos) > force_pos


def test_production_workflow_invokes_release_wrapper_not_raw_deploy_script():
    workflow = WORKFLOW.read_text()

    assert "scripts/run-production-release.sh" in workflow
    assert "/tmp/local-price-checks-release.sh" in workflow
    assert "bash /tmp/local-price-checks-release.sh '$TARGET_SHA'" in workflow
    assert "git show '${TARGET_SHA}:scripts/deploy-production.sh' > /tmp/local-price-checks-deploy.sh" not in workflow
