from __future__ import annotations

import os
import sqlite3
import subprocess
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.sqlite_alembic import TARGET_REVISION, prepare_existing_sqlite_for_alembic


ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "scripts" / "deploy-production.sh"


def _upgrade(path: Path, revision: str) -> None:
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{path.as_posix()}"}
    subprocess.run(
        [os.sys.executable, "-m", "alembic", "upgrade", revision],
        check=True,
        cwd=ROOT,
        env=env,
    )


def _revision(path: Path) -> str | None:
    with sqlite3.connect(path) as connection:
        row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    return str(row[0]) if row else None


def test_sqlite_migration_target_matches_repository_head() -> None:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    head = ScriptDirectory.from_config(config).get_current_head()

    assert TARGET_REVISION == head == "20260918_01"


def test_pre_repair_production_revision_is_not_treated_as_current(tmp_path: Path) -> None:
    database = tmp_path / "pre-repair.sqlite3"
    backup = tmp_path / "pre-repair.backup.sqlite3"
    _upgrade(database, "20260910_01")

    dry_run = prepare_existing_sqlite_for_alembic(database)

    assert dry_run.initial_revision == "20260910_01"
    assert dry_run.final_revision == "20260910_01"
    assert dry_run.action == "upgrade-baseline"
    assert not dry_run.applied

    applied = prepare_existing_sqlite_for_alembic(
        database,
        apply=True,
        backup_path=backup,
    )

    assert applied.applied
    assert applied.initial_revision == "20260910_01"
    assert applied.final_revision == TARGET_REVISION
    assert applied.action == "upgraded-baseline"
    assert _revision(database) == "20260918_01"
    assert _revision(backup) == "20260910_01"


def test_deploy_treats_sqlite_target_change_as_controlled_migration_release() -> None:
    script = DEPLOY.read_text(encoding="utf-8")

    assert "app/sqlite_alembic\\.py$" in script
    assert "grep -Fxq 'app/sqlite_alembic.py'" in script
    assert "Controlled migration runner update recognized" in script
    assert "scripts/prepare_existing_sqlite_for_alembic.py" in script
