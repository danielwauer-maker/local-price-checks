# Local testing on Windows, laptop and smartphone

Local Price Checks is designed to run locally in Docker before the first server deployment.

## Requirements

- Windows 10/11
- Docker Desktop with Docker Compose
- Git
- Laptop and smartphone in the same WLAN/LAN for phone testing

## 1. Clone the repository

```powershell
git clone https://github.com/danielwauer-maker/local-price-checks.git
cd local-price-checks
```

## 2. Fast local start on the laptop

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-local.ps1
```

The script:

- creates `.env` from `.env.example` when needed,
- builds the Docker image,
- starts the app,
- detects the current LAN IPv4 address,
- prints the laptop and smartphone URLs,
- opens `http://localhost:8000` in the default browser.

Manual equivalent:

```powershell
copy .env.example .env
docker compose up --build -d
```

Laptop URL:

```text
http://localhost:8000
```

Health check:

```text
http://localhost:8000/health
```

## 3. Test from a smartphone over WLAN

Start the normal local stack, then open the printed LAN URL on the phone, for example:

```text
http://192.168.178.25:8000
```

The phone and laptop must be in the same network. If the page does not open, verify that Windows Firewall allows inbound TCP traffic to Docker/port 8000 and that the WLAN does not use client isolation.

All main MVP functions can be tested over HTTP: markets, postal-code location, favorites, product search, shopping list, current/upcoming offers and saving plan. Browser camera access may be blocked because mobile browsers require a secure context.

## 4. Local HTTPS for the phone camera

For a real camera barcode test run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-local-https.ps1
```

This starts the app plus a local Caddy reverse proxy at:

```text
https://<LAN-IP>:8443
```

Caddy creates a local development CA. Its root certificate is exported to:

```text
.local-dev\caddy-root.crt
```

The script trusts this certificate for the current Windows user. The phone must trust the same root certificate before the HTTPS page is considered secure.

### iPhone/iPad

1. Transfer `.local-dev/caddy-root.crt` to the device (AirDrop, Files, iCloud Drive or another local/private transfer).
2. Open the certificate and install the downloaded profile in **Settings > General > VPN & Device Management**.
3. Then enable trust in **Settings > General > About > Certificate Trust Settings**.
4. Open `https://<LAN-IP>:8443` in Safari/Chrome and test the scanner.

### Android

Android menus vary by manufacturer. Install `.local-dev/caddy-root.crt` as a CA certificate under the device security/certificate settings, then open `https://<LAN-IP>:8443`.

Only install the generated local CA on development devices. Remove it after local HTTPS testing if it is no longer required. The certificate and private CA data are never committed to Git.

## 5. Suggested MVP test flow

1. Open **Meine Märkte**.
2. Enter postal code and town; no GPS permission is requested.
3. Set a radius and select one or more verified markets.
4. Search a product and mark it as a favorite.
5. Add a product to the shopping list and change its quantity.
6. Open **Angebote** for current and upcoming offers.
7. Open **Sparplan** and verify that only selected markets are used.
8. Open **Scanner**, scan or enter a valid barcode.
9. For an unknown barcode, search an existing product and link it once.
10. Mark the recognized product as favorite or add it to the shopping list.
11. Open **Datenstatus** to inspect the latest collection state.

## 6. Stop local testing

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\stop-local.ps1
```

The SQLite database stays in `data/` and is reused on the next start.

## Collector during local testing

The automatic scheduler is disabled by default (`SCHEDULER_ENABLED=false`) so local startup does not immediately hit retailer sites. `Datenstatus > Jetzt sammeln` can trigger one collection attempt in development mode.

For scheduled testing set in `.env`:

```env
SCHEDULER_ENABLED=true
COLLECTION_HOUR=5
COLLECTION_MINUTE=30
COLLECTOR_BROWSER_ENABLED=true
```

Only active `benchmark_verified` stores are eligible for scheduled collection.
