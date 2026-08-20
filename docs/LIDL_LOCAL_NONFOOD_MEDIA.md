# Lidl local non-food and product media

## Availability evidence

Lidl offer availability is evaluated in this order:

1. official PDF page and visible price-bearing product block;
2. product name and price from the PDF text layer;
3. the product/price bounding region on that page;
4. exact manifest identity (`productId`, canonical URL and variant metadata);
5. the shop link itself.

A shop URL never overrides local PDF evidence. A price-bearing item on a local
prospect page is `LOCAL_AND_ONLINE` when the same bounded region has an exact
shop identity. A manifest product without corresponding local PDF evidence is
`ONLINE_ONLY`. Explicit online-shop pages remain `ONLINE_ONLY` even though the
shop insert itself contains prices. Editorial and navigation links are not
product candidates.

The frozen page-1 acceptance fixture contains Lavazza Caffè Crema, Pepsi /
Schwip Schwap, Funny-Frisch Pom-Bär, helle kernlose Trauben, LIVARNO
Musselin-Bettwäsche and PARKSIDE Elektro-Kettensäge. All six must import. Its
additional manifest-only product must be rejected online.

## Media lifecycle

`MediaAssetMetadata` is additive so deployed SQLite databases do not require an
in-place `media_assets` migration. Product media sources and public priorities
are:

1. `official_product` (300)
2. `retailer_cdn` (200)
3. `prospect_crop` (100)

An admin-curated image remains an explicit override. Official images are
accepted only through exact product identity and compatible variant/price
evidence; similar names are insufficient. Every local PDF offer keeps its
prospect crop as audit media. The public API selects the highest-ranked public
asset, while the admin prospect-media route selects the audit crop.

## Quality metrics

- `image_rate`: any usable product image
- `official_image_rate`: `official_product` or `retailer_cdn` coverage
- `crop_fallback_rate`: products whose best available source is a prospect crop
- `weighted_image_rate`: official coverage plus half-weighted crop-only coverage
- `local_only`: local PDF offers without online product identity
- `local_and_online`: local PDF offers with an exact additional shop identity
- `online_only_rejected`: candidates rejected because no local evidence exists

The weighted image rate contributes to the quality score, so crop-only coverage
does not receive the same score as isolated official product imagery. Image
availability itself remains separately visible through `image_rate`.

## Production acceptance (Puderbach, 20 August 2026)

```text
run_status=success
offers_received=364
offers_imported=214
local_only=180
local_and_online=34
online_only_rejected=150
image_rate=100.0
official_image_rate=11.3
crop_fallback_rate=88.7
provenance_rate=100.0
quality_status=PASS
benchmark_status=PASS
pages_ocr=0
runtime_seconds=61.4
```

The page-1 LIVARNO bedding and PARKSIDE chainsaw are imported. Both retain the
page crop for audit. Their exact 135×200 and PEKS 2200 B1 identities also have
isolated official public images. Lavazza, Pepsi/Schwip Schwap and Pom-Bär have
no exact product metadata in this flyer and therefore correctly retain the
prospect crop as their public fallback instead of receiving a guessed image.
