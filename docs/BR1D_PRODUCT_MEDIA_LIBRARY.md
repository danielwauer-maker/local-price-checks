# BR-1D – Product Media Library

## Ziel

BR-1D erweitert die bestehende `MediaAsset`-Architektur zu einer belastbaren, MasterProduct-zentrierten Medienbibliothek. Bestehende `MediaAsset`-IDs, Offer-/Produkt-IDs und Bildhistorie bleiben unverändert.

Es entsteht **keine konkurrierende Produktbild-Identität**. `MediaAsset` bleibt das Bildobjekt, `MediaAssetMetadata` bleibt die bestehende Source-/Ranking-Erweiterung. Die neue 1:1-Tabelle `product_media_library_metadata` ergänzt ausschließlich Provenance, technische Qualität und Review-Zustand.

## Auswahlregeln

Öffentliche Bildauswahl priorisiert defensiv:

1. explizit manuell bevorzugt
2. manuell verifiziert
3. belastbare Quellklasse (`manufacturer_official`, `official_product`, `official_retailer`, `retailer_cdn`, PDF/Crop)
4. bestehendes Primary innerhalb derselben Qualitätsklasse
5. technische Qualität
6. Audit-/Fallback-Eignung

Dadurch darf ein neuer Collector-Fund ein manuell bevorzugtes oder verifiziertes Bild nicht verdrängen. Ein besser klassifiziertes offizielles Bild darf weiterhin einen unreviewten Prospekt-Crop ersetzen, wie bereits vor BR-1D vorgesehen.

`rejected`, `broken`, erkannte Placeholder und Händlerlogos werden nicht öffentlich ausgewählt. Explizit abgelehnte/unbrauchbare Bilder werden inaktiv gesetzt, **nicht gelöscht**. Damit bleiben Quelle, Datei und Review-Historie nachvollziehbar und bestehende Coverage-Auswertungen zählen sie nicht als brauchbare Bildabdeckung. Eine spätere explizite saubere Review kann dieselbe Media-ID reaktivieren.

## Provenance und Qualität

Für neu beobachtete bzw. erneut beobachtete Bilder können gespeichert werden:

- Source/Collector-Name
- Händler
- Source URL (weiterhin auf `MediaAsset`)
- Canonical URL / External Product ID (weiterhin `MediaAssetMetadata`)
- first observed / last observed
- Lizenz-/Nutzungshinweis
- Confidence
- Breite/Höhe
- Format
- Seitenverhältnis
- SHA-256 Content Hash
- einfacher perceptual dHash
- Quality Score
- Placeholder-/Logo-Signal
- Review-Status, Grund, Actor und Zeitpunkt
- manual preferred

Hashes sind **nur Diagnostik**. Gleicher Hash führt weder zu Produktfusion noch zu Media-ID-Fusion. Die Admin-Library weist Dubletten innerhalb eines MasterProducts aus.

## Collector-Integration

Die bestehende zentrale Funktion `persist_collected_product_images` bleibt der Integrationspunkt. Remote-Bilder werden weiterhin lokal in `admin_media` persistiert und behalten ihre Remote-URL als Provenance. Prospekt-Crops werden weiterhin aus dem kontrollierten Data-Verzeichnis übernommen.

REWE/andere strukturierte Web-Collector liefern `CollectedOffer.image_url`; EDEKA übernimmt `WebOfferRecord.image_url` in `CollectedOffer`. BR-1D nutzt diese bestehenden Felder und ergänzt die Media-Library-Metadaten, ohne die Händler-Collector selbst neu zu strukturieren.

Wichtig: Ein erneut gefundener `prospect_crop` setzt sich nicht mehr automatisch als Primary über ein bereits besseres Bild.

## Frontend

`ProductImage.tsx` bleibt kompatibel. Es nutzt weiterhin explizites `imageUrl` oder `/api/lokero/product-media/{productId}` und fällt bei Ladefehlern auf `ProductThumb` zurück. Die öffentliche Endpoint-Auflösung profitiert automatisch von der neuen serverseitigen Auswahl; es ist kein paralleler Frontend-Bildspeicher nötig.

## Admin-Vorbereitung für BR-1E

BR-1D stellt serverseitig bereit:

- `GET /admin/product-media/{product_id}/library`
- `POST /admin/product-media/{product_id}/{media_id}/preferred`
- `POST /admin/product-media/{product_id}/{media_id}/review`

Damit kann BR-1E die UI für Alternativen, Provenance, Qualität, Verifizieren, Ablehnen, Defekt-/Placeholder-/Logo-Markierung und Preferred-Auswahl direkt darauf aufbauen.

Die bestehende physische Admin-Löschung bleibt für echte Löschfälle erhalten und entfernt nun auch die neue 1:1-Library-Metadatenzeile FK-sicher. Für Qualitäts-/Identitätsfehler ist Review/Inaktivierung statt Löschung vorgesehen.

## Migration

Revision: `20260910_01`

- rein additiv: neue Tabelle
- keine bestehenden IDs werden geändert
- keine historischen Bilder werden automatisch umgehängt, fusioniert oder erraten
- bestehende MediaAssets werden bewusst nicht blind backfilled
- Metadaten entstehen lazy bei erneuter Beobachtung oder Admin-Review

## Production Release

BR-1D enthält eine Schemaänderung. Der aktuelle Production-Deploy ist fail-closed und akzeptiert nur explizit freigegebene Migrationen. Daher darf nach Merge **kein normaler Deploy** gestartet werden, bevor `20260910_01` in einem separaten kontrollierten Production-Schema-Release freigegeben wurde.

Für diesen separaten Release gelten:

1. Production-Allowlist gezielt um genau BR-1D erweitern
2. SQLite WAL checkpoint
3. externer Backup
4. Migration dry-run
5. Upgrade
6. App neu starten
7. `/health` prüfen
8. Scheduler prüfen
9. Collection Problems prüfen
10. Alembic Revision `20260910_01` verifizieren

PostgreSQL-Cutover ist dafür nicht erforderlich.
