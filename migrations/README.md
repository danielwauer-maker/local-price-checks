# Alembic migrations

`env.py` imports `app.model_registry`, so every application model is present in
the target metadata. The database URL is read exclusively from `DATABASE_URL`.

Existing production SQLite databases must first be backed up and verified
against the baseline, then stamped explicitly. Never run the baseline upgrade
over an already populated, unstamped database.
