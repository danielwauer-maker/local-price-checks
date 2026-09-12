from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts" / "run-production-release.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "deploy-production.yml"


def test_release_wrapper_uses_post_success_marker_as_deployment_truth():
    script = WRAPPER.read_text()

    assert 'SUCCESS_MARKER="$BACKUP_DIR/.last-successful-release"' in script
    assert 'git merge-base --is-ancestor "$LAST_SUCCESSFUL_SHA" "$TARGET_SHA"' in script
    assert 'git reset --hard "$LAST_SUCCESSFUL_SHA"' in script

    deploy_call = 'bash "$DEPLOY_SCRIPT" "$TARGET_SHA"'
    marker_write = 'printf \'%s\\n\' "$TARGET_SHA" > "${SUCCESS_MARKER}.tmp"'
    marker_commit = 'mv "${SUCCESS_MARKER}.tmp" "$SUCCESS_MARKER"'

    assert deploy_call in script
    assert marker_write in script
    assert marker_commit in script
    assert script.index(deploy_call) < script.index(marker_write) < script.index(marker_commit)


def test_production_workflow_invokes_release_wrapper_not_raw_deploy_script():
    workflow = WORKFLOW.read_text()

    assert "scripts/run-production-release.sh" in workflow
    assert "/tmp/local-price-checks-release.sh" in workflow
    assert "bash /tmp/local-price-checks-release.sh '$TARGET_SHA'" in workflow
    assert "git show '${TARGET_SHA}:scripts/deploy-production.sh' > /tmp/local-price-checks-deploy.sh" not in workflow
