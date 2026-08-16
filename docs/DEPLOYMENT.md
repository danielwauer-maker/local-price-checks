# Deployment-Plan

## Phase 1: lokal

1. `.env.example` nach `.env` kopieren.
2. `docker compose up --build`.
3. `http://localhost:8000/health` prüfen.
4. Mobile Browseransicht testen.

## Phase 2: Server

- GitHub als Source of Truth
- CI muss Tests und Docker-Build bestehen
- Deployment als Docker-Container
- persistentes Datenvolume
- Reverse Proxy (Caddy oder Nginx)
- HTTPS zwingend für den produktiven Kamera-Barcode-Workflow
- Backup der Datenbank
- Healthcheck und Logs

## Phase 3: Pipeline

GitHub Push -> CI -> Docker Build -> Deploy -> DB-Migration -> Healthcheck -> Smoke-Test.
