# EDEKA market PDF pipeline

EDEKA market pages are discovery sources. The immutable, market-specific PDF is
the primary offer artifact:

`market page -> PDF discovery/archive -> layout extraction -> import -> QA`

If a current PDF is already registered, collection reuses it even when the
landing page is temporarily unavailable. New markets use the same generic PDF
discovery path; there is no parser branch for market ID `071378`.

## Extraction and diagnostics

The parser inspects every page before choosing a path. A usable native text
layer is preferred. Image-only pages are rendered at high resolution and OCRed
with German word bounding boxes. Red offer-price regions form the spatial
anchors for product cards. Product title, quantity, unit price, reference price
and a provenance crop are resolved within the associated card region.

Diagnostics are stored under
`DATA_DIR/diagnostics/edeka/<pdf_sha256>/analysis.json` and include, per page:

- text objects and character count
- embedded images
- native-text usability and OCR requirement
- image dimensions and OCR word count
- detected price candidates
- accepted and rejected product candidates with bounding boxes

The aggregate QA signal includes `price_anchors_detected`,
`price_anchors_matched`, `price_anchors_unmatched`,
`pages_with_unmatched_prices`, and `page_offer_recall`. An unmatched local price
anchor prevents an EDEKA production run from reporting clean quality.

The extraction result is cached as `extraction-v1.json` beside the analysis and
keyed by the PDF SHA-256. Reuse reconstructs store-specific offer identity and
source URLs, while the immutable page extraction and crops remain shared.

## Provenance and media

The original PDF remains in `ProspectArchive` with SHA-256, page count, market,
validity, source URL and bytes. Every imported row carries its PDF page into
`OfferOccurrence` and `OfferProvenance`. Duplicate public offers may therefore
retain multiple page occurrences.

Each accepted card produces a `prospect_crop`, used as audit evidence and as the
public fallback. Media priority remains:

`official_product > retailer_cdn > pdf_embedded > prospect_crop`

The current Fellenzer source exposes no safely identity-matched isolated product
images, so the verified run intentionally reports `official_image_rate=0.0` and
`crop_fallback_rate=100.0` instead of assigning fuzzy web images.

## Frozen production fixture

The real fixture `tests/fixtures/edeka_fellenzer_kw34_real_ocr.json` contains 40
hand-verified cards from eight pages of the official KW34/2026 Fellenzer PDF,
covering produce, meat, cheese, beverages, packaged food and non-food.

- PDF SHA-256: `89c7fcd23e0adc36e3227d0f95f26b30943a19955c9b346affcd1d063aa8faa8`
- pages: 26
- native-text pages: 2
- OCR pages: 24
- Golden precision: 100%
- Golden recall: 100%

The isolated production smoke on 2026-08-20 produced:

- runtime: 180.6 seconds
- offers received/imported: 158/158
- price anchors detected/matched: 160/160
- page offer recall: 100%
- provenance/occurrence/image rate: 100%/100%/100%
- package/unit-price rate: 85.5%/86.7%
- run/quality/benchmark: `success` / `PASS` / `PASS`

Two PDF pages contain useful native text but no offer cards. The 24 raster offer
pages require OCR; OCR is not applied to the native pages. The 160 matched
visual anchors yield 158 imported rows after exact same-page duplicate
suppression.
