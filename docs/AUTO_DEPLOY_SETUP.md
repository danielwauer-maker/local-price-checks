# Automatic production deployment

Production deployment is triggered only after the `CI` workflow completed successfully for `main`.

## GitHub environment and secrets

Create a GitHub Environment named `production` and add these secrets:

- `DEPLOY_HOST` — production server hostname or IP
- `DEPLOY_USER` — dedicated SSH deploy user
- `DEPLOY_PORT` — SSH port (optional, defaults to `22`)
- `DEPLOY_SSH_KEY` — private Ed25519 key for the deploy user
- `DEPLOY_KNOWN_HOSTS` — pinned `known_hosts` entry for the production host

Do not disable SSH host-key verification.

## Server requirements

The deploy user must be able to:

- read and fast-forward `/opt/local-price-checks`
- run `git fetch`, `git checkout`, and `git merge --ff-only`
- run `docker compose build`, `docker compose up`, `docker compose ps`, and `docker compose logs`
- read the project's `.env`

The server checkout must use `main` and have no tracked local modifications.

## Safety behavior

`scripts/deploy-production.sh`:

- refuses to deploy over tracked local changes
- requires a fast-forward from the currently deployed commit
- deploys the exact SHA whose CI completed successfully
- rebuilds/recreates only affected services when possible
- refuses automatic deployment of database/schema-related changes (exit code 42)
- waits for `http://127.0.0.1:8083/health`
- prints container status and logs on health failure

Database/schema changes intentionally require a manual release until migrations, backups, and rollback are fully automated.

## One-time server bootstrap

After this change reaches `main`, pull it manually once so the server has the deploy helper before the first automatic deployment:

```bash
cd /opt/local-price-checks
git fetch origin
git pull --ff-only origin main
chmod +x scripts/deploy-production.sh
```

After GitHub secrets are configured, future successful merges to `main` deploy automatically.
