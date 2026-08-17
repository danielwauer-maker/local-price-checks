# Lovable frontend source

This directory is the controlled design/frontend snapshot used by Local Price Checks.

Source project:
`danielwauer-maker/price-radar-app-81-960e2446` (`main`)

The production application remains in the main Local Price Checks codebase. This folder is only the Lovable React/Vite design source that we integrate against the real FastAPI backend, collectors, database and Sparplan logic.

## Sync policy

Use `scripts/sync-lovable-source.ps1` on Windows or `scripts/sync-lovable-source.sh` on Linux/macOS to refresh this folder from the Lovable repository. The scripts intentionally exclude:

- `.git/`
- `.env` and `.env.*`
- `.lovable/`
- `node_modules/`
- `dist/`

After a sync, review the changes and commit them to `local-price-checks`. Do not deploy the Lovable demo data as backend truth.
