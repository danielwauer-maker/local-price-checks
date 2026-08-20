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
3. Manifest links as exact product identity and availability evidence.
4. OCR only for pages without a sufficient PDF text layer.

Every PDF offer retains its prospect page and deterministic audit crop. An
exact manifest product may additionally supply a higher-ranked official public
image when product identity, variant and price evidence are compatible.

## Source semantics

- `LOCAL_ONLY`: price-bearing local PDF offer without a shop identity.
- `LOCAL_AND_ONLINE`: price-bearing local PDF offer with an exact additional
  shop identity. `/p/...`, `productId` and `flyx_content=p-...` never override
  this local evidence.
- `ONLINE_ONLY`: manifest/shop item without corresponding local PDF evidence,
  or an item on an explicit online-shop-only insert.
- `NAVIGATION`: recipe, Lidl Plus and other navigation links.
- `EDITORIAL`: other non-product editorial elements.

Shop rows are passed to the canonical importer as non-local rejection records,
so they increment `rejected_online`, not `quality_rejected`. Quality import rate
uses eligible (non-online) received rows.

The current non-food availability, ranked-media acceptance and live metrics are
documented in `LIDL_LOCAL_NONFOOD_MEDIA.md`.

## Brand learning

Brand inference remains shared across retailers and is deliberately
conservative. A prefix is accepted only when the brand is already backed by an
admin-corrected product/alias or a manual prospect review. Generic first words
such as `Frische`, `Bio`, `Deutsche` and `Helle` are never treated as brands.
