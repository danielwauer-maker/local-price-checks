import sqlite3
from pathlib import Path

from scripts.repair_sqlite_foreign_keys import repair_sqlite_foreign_keys


def _orphan_database(path: Path, *, unexpected: bool = False) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            PRAGMA foreign_keys=OFF;
            CREATE TABLE offers (id INTEGER PRIMARY KEY);
            CREATE TABLE offer_occurrences (
                id INTEGER PRIMARY KEY,
                offer_id INTEGER NOT NULL REFERENCES offers(id)
            );
            CREATE TABLE offer_price_references (
                id INTEGER PRIMARY KEY,
                offer_id INTEGER NOT NULL REFERENCES offers(id)
            );
            CREATE TABLE offer_provenance (
                id INTEGER PRIMARY KEY,
                offer_id INTEGER NOT NULL REFERENCES offers(id)
            );
            CREATE TABLE prospect_offer_reviews (
                id INTEGER PRIMARY KEY,
                offer_provenance_id INTEGER NOT NULL REFERENCES offer_provenance(id)
            );
            INSERT INTO offer_occurrences (id, offer_id) VALUES (1, 999);
            INSERT INTO offer_price_references (id, offer_id) VALUES (1, 999);
            INSERT INTO offer_provenance (id, offer_id) VALUES (1, 999);
            INSERT INTO prospect_offer_reviews (id, offer_provenance_id) VALUES (1, 1);
            """
        )
        if unexpected:
            connection.executescript(
                """
                CREATE TABLE unknown_children (
                    id INTEGER PRIMARY KEY,
                    offer_id INTEGER NOT NULL REFERENCES offers(id)
                );
                INSERT INTO unknown_children (id, offer_id) VALUES (1, 999);
                """
            )
        connection.commit()
    finally:
        connection.close()


def test_repair_script_is_dry_run_by_default_and_backs_up_before_apply(tmp_path: Path):
    database = tmp_path / "production-copy.sqlite3"
    backup = tmp_path / "production-copy.backup.sqlite3"
    _orphan_database(database)

    assert repair_sqlite_foreign_keys(database) == 0
    with sqlite3.connect(database) as connection:
        assert len(connection.execute("PRAGMA foreign_key_check").fetchall()) == 3

    assert repair_sqlite_foreign_keys(database, apply=True, backup_path=backup) == 0
    assert backup.is_file()
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    with sqlite3.connect(backup) as connection:
        assert len(connection.execute("PRAGMA foreign_key_check").fetchall()) == 3
        assert connection.execute("SELECT COUNT(*) FROM prospect_offer_reviews").fetchone()[0] == 1


def test_repair_script_aborts_on_unexpected_foreign_key_problems(tmp_path: Path):
    database = tmp_path / "unexpected.sqlite3"
    backup = tmp_path / "must-not-exist.sqlite3"
    _orphan_database(database, unexpected=True)

    assert repair_sqlite_foreign_keys(database, apply=True, backup_path=backup) == 2
    assert not backup.exists()
    with sqlite3.connect(database) as connection:
        assert len(connection.execute("PRAGMA foreign_key_check").fetchall()) == 4
