from pathlib import Path


def test_production_deploy_rejects_stale_ci_completions_before_ssh():
    workflow = Path(".github/workflows/deploy-production.yml").read_text(encoding="utf-8")

    assert "Reject stale CI completion" in workflow
    assert "git ls-remote" in workflow
    assert "refs/heads/main" in workflow
    assert 'if [[ "$TARGET_SHA" != "$LATEST_MAIN_SHA" ]]' in workflow
    assert 'echo "deploy=false" >> "$GITHUB_OUTPUT"' in workflow
    assert "Skipping stale CI completion" in workflow

    gated_steps = (
        "Check deployment configuration",
        "Configure SSH",
        "Deploy successful main commit",
        "Report collection health details",
        "One-time Docker storage cleanup",
    )
    for step_name in gated_steps:
        marker = f"- name: {step_name}"
        _, remainder = workflow.split(marker, 1)
        step = remainder.split("\n      - name:", 1)[0]
        assert "steps.target.outputs.deploy == 'true'" in step


def test_production_deploy_uses_guarded_target_sha_for_release():
    workflow = Path(".github/workflows/deploy-production.yml").read_text(encoding="utf-8")

    deploy_section = workflow.split("- name: Deploy successful main commit", 1)[1]
    deploy_section = deploy_section.split("\n      - name:", 1)[0]
    assert "TARGET_SHA: ${{ steps.target.outputs.target_sha }}" in deploy_section
    assert "run-production-release.sh '$TARGET_SHA'" in deploy_section
