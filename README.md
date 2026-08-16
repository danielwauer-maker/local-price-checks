# Local Price Checks

Mobile-first Web-App für lokale Supermarkt-Preisvergleiche.

Local Price Checks verbindet persönliche Favoriten und die Einkaufsliste mit lokalen Wochenangeboten und soll beantworten: **Was sollte ich kaufen, wo ist es am günstigsten und lohnt sich ein zusätzlicher Markt?**

## MVP

- Favoriten
- Einkaufsliste
- aktuelle und kommende Angebote
- Barcode/GTIN per Handykamera oder Eingabe
- Hauptstandort via PLZ + Ort, ohne GPS-Freigabe
- Radius + favorisierte Märkte
- nur benchmark-freigegebene Märkte im Preisvergleich
- Sparplan

Der stabile KW33-Referenzbenchmark für REWE Dierdorf, Netto und ALDI SÜD liegt bei **756/762 = 99,21 %**. EDEKA/Lidl bleiben vorerst außerhalb des MVP-Vergleichs. REWE Straßenhaus ist angelegt, aber noch nicht vollständig benchmark-freigegeben.

## Lokal starten

```bash
cp .env.example .env
docker compose up --build
```

Dann `http://localhost:8000` öffnen.

Ohne Docker:

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Tests

```bash
pytest -q
```

## Repository-Regeln

Nicht versioniert werden: produktive SQLite-Datenbanken, Prospekt-PDFs, Support-Exports, Cookies/Browserprofile, `.env` und lokale Logs.

Weitere Details: `docs/MVP_SCOPE.md`, `docs/ARCHITECTURE.md`, `docs/DEPLOYMENT.md`.
