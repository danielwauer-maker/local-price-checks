# Lidl local-offer semantics and PDF extraction

## Production finding (Puderbach, 20 August 2026)

The official Schwarz flyer response is not a local-offer catalogue. In the
analysed 72-page leaflet it contained 182 `flyer.products` entries and 182
matching shop hotspots. Their `/p/...`, `productId` and
`flyx_content=p-...` identifiers point to the Lidl online shop. Treating
`productDetails` as local evidence therefore imported mostly shop/non-food
catalogue rows.

The same response exposed an official 72-page PDF with a text layer on every
page (about 122,700 characters). Product names, promotional prices, package
sizes and unit prices for the local leaflet are available there. The optional
`flyer.texts` collection was present but empty in this production payload;
`keyWords` and `altText` were useful for page context, not reliable price-card
structure.

The previous import-time Schwarz hardening monkey patch was removed. The Lidl
collector now invokes one explicit production parser; the generic manifest
parser remains an ordinary fallback for non-Schwarz payload shapes.

## Canonical source order

1. Official PDF text blocks and their page coordinates.
2. Optional `flyer.texts`, page `keyWords` and `altText`.
3. Manifest links as semantic regions and exclusion evidence.
4. OCR only for pages without a sufficient PDF text layer.

Every PDF offer retains its prospect page. Local product images are generated
as deterministic crops from the official page and persisted through the common
media lifecycle. Shop product images are never attached to local PDF offers.

## Source semantics

- `local_prospect`: explicit in-store/local evidence or an accepted PDF card.
- `shop_online`: `/p/...`, `productId`, `flyx_content=p-...`, or explicit online
  markers without contrary explicit in-store evidence.
- `navigation_recipe`: recipe/navigation links; useful as layout regions but
  not offers.
- `lidl_plus`: Lidl Plus navigation or app-specific pricing context.
- `editorial`: other non-price editorial elements.

Shop rows are passed to the canonical importer as non-local rejection records,
so they increment `rejected_online`, not `quality_rejected`. Quality import rate
uses eligible (non-online) received rows.

## Live acceptance result

Isolated production-context smoke test against Lidl Puderbach:

```text
runtime_seconds=62.5
run_status=success
offers_received=397
offers_imported=184
online_rejected=213
quality_rejected=0
food_offers=68
nonfood_local_offers=116
shop_hotspots_seen=183
pdf_text_offers=219
manifest_text_offers=0
ocr_offers=0
pages_done=72
image_rate=100.0
package_rate=89.6
unit_price_rate=89.6
provenance_rate=100.0
quality_status=PASS
benchmark_status=PASS
archive_pages=72
```

Lavazza Caffè Crema, Pepsi/Schwip Schwap, helle kernlose Trauben and
Funny-Frisch Pom-Bär were all imported. No LIVARNO product was imported. Five
PARKSIDE rows remained as local non-food leaflet offers; they represented 2.7%
of imports and no longer dominated the result.

## Brand learning

Brand inference remains shared across retailers and is deliberately
conservative. A prefix is accepted only when the brand is already backed by an
admin-corrected product/alias or a manual prospect review. Generic first words
such as `Frische`, `Bio`, `Deutsche` and `Helle` are never treated as brands.
