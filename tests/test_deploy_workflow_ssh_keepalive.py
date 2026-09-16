from pathlib import Path


def test_production_deploy_ssh_sessions_have_keepalives() -> None:
    workflow = Path(".github/workflows/deploy-production.yml").read_text(encoding="utf-8")

    ssh_commands = [line for line in workflow.splitlines() if line.strip().startswith("ssh -o BatchMode=yes")]
    assert len(ssh_commands) == 3

    assert workflow.count("-o ServerAliveInterval=30 -o ServerAliveCountMax=20 -o TCPKeepAlive=yes") == 3
