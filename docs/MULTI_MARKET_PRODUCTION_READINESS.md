# Multi-Market Production Readiness

## Goal

The seven launch markets must reach one consistent production standard before the shopping optimizer treats collector data as authoritative.

Target markets:

1. Lidl Puderbach
2. EDEKA Fellenzer Puderbach
3. ALDI SÜD Dierdorf
4. Netto Marken-Discount Dierdorf
5. REWE Dierdorf / Hundertmark (external id `321019`)
6. ALDI SÜD Oberhonnefeld-Gierend
7. Netto Marken-Discount Oberhonnefeld-Gierend

## Source strategy

A store is `collector_primary` only when all of the following are true for the latest run:

- store is active
- collector run is `success`
- quality snapshot is present
- `quality_status=PASS`
- `benchmark_context=PRODUCTION`
- `benchmark_status=PASS`
- independent external validation for that exact run is `PASS`
- at least 10 external validation samples were checked

Until that gate is reached the store remains `external_primary`. An inactive store is `blocked`.

A configured target `external_id` is a hard identity constraint. For REWE Dierdorf the target id is `321019`; a different REWE market in Dierdorf must never be substituted if that exact market cannot be found.

Existing collector runs that predate the independent validation metadata intentionally remain `external_primary` until an external validation has been recorded for the exact run. This is conservative by design.

Run the operator check with:

```bash
python scripts/production_readiness.py
```

The script adds the repository root to `sys.path`, so the documented direct command works without a manually supplied `PYTHONPATH`. The command exits `0` only when all seven launch markets are collector-primary. It exits `2` while rollout is still in progress.

## Admin workflow

The full readiness cockpit is available at `/admin/collector/readiness`. It shows all seven launch markets with source strategy, collector status, quality, benchmark, score, imported offers, next-week coverage, and diagnostic metrics.

The daily operator view at `/admin/collector` provides a compact readiness summary and links to the detailed cockpit for diagnosis.

## Independent external validation

External leaflet/web research is no longer a competing primary data source for a production-ready collector. It is an independent benchmark layer.

A normal validation set contains 10–20 samples per store/week and checks, where available:

- product identity / brand
- package size
- action price
- unit price and unit
- validity window
- local stationary-store flag
- image presence
- negative controls for offers explicitly marked online-only

`validate_external_samples()` returns an `ExternalValidationResult` with score, sample-level mismatches, missing offers and online-only leaks. `persist_external_validation_result()` writes the result into the quality snapshot belonging to the exact collector run. Readiness reads only that run-scoped metadata; a validation from an older run cannot unlock a newer run.

Suggested operational thresholds:

- `PASS`: score >= 97, no missing reference offer, no online-only leak
- `WARN`: score >= 90 with a non-critical mismatch/missing reference
- `FAIL`: score < 90 or any online-only leak
- `INSUFFICIENT_SAMPLES`: fewer than 10 references

Even if a custom caller lowers `min_samples` while experimenting, the production readiness gate still requires `external_validation_checked >= 10`.

The benchmark is intentionally source-agnostic. Reference samples can come from an official local leaflet, official local retailer page or a manually curated gold set.

## Missing-offer detection

Every unmatched positive external reference is reported as `offer_missing`. This changes validation from only asking “are imported rows correct?” to also asking “which externally observed local offer is absent from the collector?”.

For full-page sources the next extension should feed all recognizable local offer cards into the same comparator and report:

```text
external recognizable offers / collector offers / unmatched candidates
```

Do not infer missing offers from raw page text without market and validity confirmation.

## Diagnostic N/A semantics

Historic quality snapshots store `0.0` for `price_anchor_match_rate` and `page_offer_recall` even when the collector never emitted those diagnostics. `quality_metric_for_display()` now distinguishes “not applicable/not measured” from a genuine measured zero.

Rules:

- explicit `<metric>_applicable=false` -> N/A
- explicit `<metric>_applicable=true` -> preserve the numeric value, including `0.0`
- historic snapshot with no anchor/page diagnostic evidence -> N/A
- historic snapshot with diagnostic evidence -> preserve the numeric value

This prevents a healthy REWE web-snapshot run from visually looking like it failed a Lidl/EDEKA-specific diagnostic.

## Week rollover

`next_week_window()` always returns the following Monday–Sunday window. `next_week_offer_counts()` counts only `local_store_offer=true` rows overlapping that window. This supports a rollout check that verifies that a newly published next week is actually represented in the local database before old data is treated as complete.

Retailer-specific validity can end on Saturday or Sunday; overlap with the weekly window is intentional.

## Definition of done for the rollout

- All seven target stores are present and active.
- Branch identities with configured external ids match exactly.
- Latest collector run for every target store succeeds.
- Every target store has quality PASS and `benchmark_context=PRODUCTION` with benchmark PASS.
- Independent 10–20 sample validation passes for the exact latest run of each target store.
- Online-only negative controls do not leak into local offers.
- Next-week data is detectable without replacing historical offer observations.
- Dashboard/UI uses N/A for diagnostics that were not applicable instead of misleading numeric zero.

Only after this gate should basket optimization be treated as beta-production quality across all seven launch stores.
