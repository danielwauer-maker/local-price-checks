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

The script creates `.env` when needed, builds the Docker image, starts the app, detects the current LAN IPv4 address, prints laptop/phone URLs and opens `http://localhost:8000`.

Laptop URL:

```text
http://localhost:8000
```

Health check:

```text
http://localhost:8000/health
```

## 3. Load real prospect data for a deterministic first test

The automatic collector can be tested later. For the first functional test it is safer to import the already validated REWE/Netto/ALDI prospect PDFs from your PC. The files are copied only into the ignored `data/import/` folder and are never committed to Git.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\import-local-pdfs.ps1 `
  -RewePdf "C:\Path\REWE-KW33.pdf" `
  -NettoPdf "C:\Path\Netto-KW33.pdf" `
  -AldiPdf "C:\Path\ALDI-KW33.pdf"
```

The REWE prospect is imported into REWE Dierdorf; the validated regional Netto/ALDI prospects are imported into both currently verified local stores of their respective chain. Store identities remain separate.

Then open:

```text
http://localhost:8000/datenstatus
```

## 4. Test from a smartphone over WLAN

Start the normal local stack and open the LAN URL printed by the script, for example:

```text
http://192.168.178.25:8000
```

The phone and laptop must be in the same network. If the page does not open, verify Windows Firewall access to Docker/port 8000 and that WLAN client isolation is disabled.

All main MVP functions work over HTTP: market map, postal-code location, favorites, product search, shopping list, current/upcoming offers, saving plan and the **camera-photo barcode fallback**.

### Barcode camera modes

The scanner offers two camera paths:

1. **Live camera** using the browser's `BarcodeDetector`. This requires a secure HTTPS context and browser support.
2. **Take photo** using the phone's normal camera/file capture. The uploaded image is decoded by the Local Price Checks server with ZXing-C++; no external barcode service receives the image. This fallback can be used even when the browser has no `BarcodeDetector` implementation.

The server rejects images above 8 MB and only accepts a decoded code after the app's own GTIN check-digit validation.

## 5. Optional local HTTPS for live camera scanning

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-local-https.ps1
```

This starts Caddy at:

```text
https://<LAN-IP>:8443
```

Caddy creates a local development CA. Its root certificate is exported to:

```text
.local-dev\caddy-root.crt
```

### iPhone/iPad

1. Transfer `.local-dev/caddy-root.crt` to the development device.
2. Install the profile under **Settings > General > VPN & Device Management**.
3. Enable trust under **Settings > General > About > Certificate Trust Settings**.
4. Open `https://<LAN-IP>:8443` and test **Live-Kamera**.

### Android

Install `.local-dev/caddy-root.crt` as a user CA certificate in the device security/certificate settings and open `https://<LAN-IP>:8443`.

Only install this generated local CA on development devices. Remove it after testing when no longer needed. Certificates/private CA data are ignored by Git.

## 6. Suggested MVP end-to-end test

1. Open **Meine Märkte**.
2. Enter PLZ and town. The browser never requests GPS permission.
3. Confirm the map center/radius and select one or more verified markets.
4. Open **Produkte suchen** and mark a product as favorite.
5. Check whether its current/upcoming offer appears under **Favoriten** and on the start page.
6. Add products to the shopping list and change quantities.
7. Open **Sparplan** and verify that only selected stores are used.
8. Check the merchandise total, estimated travel cost, best one-store alternative and multi-store recommendation.
9. Open **Scanner** and try manual EAN input.
10. Use **Foto aufnehmen** on the phone; for an unknown barcode, link it once to a product.
11. Re-scan and add the recognized product to favorites or the shopping list.
12. Optionally start local HTTPS and test the live scanner.
13. Open **Datenstatus** and inspect each market's latest collection state.

## 7. Collector during local testing

The scheduler is disabled by default so opening the local app does not immediately hit retailer sites. **Datenstatus > Jetzt sammeln** triggers a manual attempt in development mode.

The collector now tries:

1. the migrated 1.4 structured DOM/network collector,
2. then official prospect PDF discovery + the benchmarked PDF parser as fallback.

For scheduled testing set:

```env
SCHEDULER_ENABLED=true
COLLECTION_HOUR=5
COLLECTION_MINUTE=30
COLLECTOR_BROWSER_ENABLED=true
```

Only active `benchmark_verified` stores are eligible for scheduled collection.

## 8. Stop local testing

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\stop-local.ps1
```

The SQLite database remains in `data/` and is reused on the next start.
