# Sprint B2 data quality notes

For the first B2 rollout, quality should be auditable per market and per prospect/import run.

Recommended minimum metrics:

- extraction coverage: extracted products versus visible/expected products
- price validity rate
- product-name validity rate
- package-size completeness
- unit-price completeness when derivable
- validity-date completeness
- source URL/page provenance completeness
- duplicate rate
- suspicious/non-product rate
- manual sample pass rate

Keep the component metrics visible. An overall traffic-light score may summarize them, but public market activation should remain gated by explicit thresholds and critical-error checks.
