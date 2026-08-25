# Sprint B2 proposal: region and market coverage

## Initial approved postal codes

The first manually approved coverage set is:

- 65618
- 65611
- 65606
- 57614
- 56305
- 56269
- 56316
- 57610

## Admin map concept

The Admin backend should provide an interactive German postal-code polygon map. Admins can click individual PLZ areas to toggle them between disabled and approved.

The map layer should be based on a maintained PLZ polygon dataset with a license that permits use in Lokero. The ESRI Germany postal-code dataset linked during planning is a useful reference for the desired interaction and geometry, but licensing/source-of-truth must be verified before bundling or redistributing its data.

Each PLZ region should have at least:

- postal code
- display name / locality where available
- polygon geometry or external geometry reference
- approved flag
- approval timestamp
- optional admin note

## Market discovery flow

For every approved PLZ, Lokero should discover candidate stores for the supported retailers and persist them in the store catalog. Discovery and scraping must be separate states:

1. PLZ approved
2. candidate markets discovered
3. market reviewed/eligible
4. collector source configured
5. latest scrape status and quality score
6. market publicly available

A discovered market must not become public merely because it was found. Collector readiness and data quality must be visible and gate publication.

## Automatic collection

Once a market is approved for collection and has a supported collector/source mapping, Lokero should schedule offer collection automatically. Failures are stored as collection runs and surfaced in Admin.

Sprint B2 should orchestrate discovery and coverage. Extractor accuracy remains owned by the dedicated collector/data-quality sprint; B2 must not silently claim unsupported retailers or poor-quality sources as production-ready.

## Offer quality gate

A market/prospect quality score should be based on measurable signals rather than one opaque percentage. Suggested dimensions:

- products extracted vs. expected/visible products
- valid price rate
- valid product-name rate
- package-size/unit-price completeness
- valid-from/valid-to completeness
- page/source provenance completeness
- duplicate rate
- suspicious/non-product rate
- manual audit sample pass rate

The Admin UI should show both the component metrics and an overall traffic-light status. Public activation should require a configurable minimum quality threshold and no critical collector errors.
