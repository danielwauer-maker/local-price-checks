# Performance audit and sprint report

## Executive result

The dominant delays were database and HTTP N+1 patterns, not route loading. The sprint removes those patterns without changing publication gates, market identity, offer validity, replacement confirmation, anonymous identity materialization or shared-list consistency. On the local synthetic fixture, offers dropped from 827 to 9 SQL queries and five alternatives from 7,277 queries across five requests to 10 queries in one batch request.

## Scope and method

The audit covered the React/TanStack frontend routes `/`, `/angebote`, `/liste`, `/favoriten`, `/maerkte`, product details, settings and sharing; FastAPI Lokero, bootstrap, market, offer, media, account, list, alternatives and SSE paths; SQLAlchemy relationship loading and indexes; the production bundle; and the existing real-browser SSE harness. Baseline details and caveats are in `docs/PERFORMANCE_BASELINE.md`.

Measurements use a deterministic disposable SQLite fixture with 300 products, 1,200 offers and ten stores. Endpoint p50/p95 values are local measurements. SQLite `EXPLAIN QUERY PLAN` verifies use of the new offer and occurrence indexes. PostgreSQL-compatible SQLAlchemy indexes and an Alembic migration preserve PostgreSQL readiness.

## Top five bottlenecks and prioritization

| Rank | Finding | Impact | Risk / effort | Decision |
| --- | --- | --- | --- | --- |
| 1 | Alternatives performed one HTTP request per item and repeated category/lazy-load matching queries per candidate | Critical | Medium | Batch endpoint, eager loading, bulk category lookup and precomputed matching descriptors |
| 2 | Offer serialization fetched occurrence, category, product/store and reference-price state per offer | Critical | Low-medium | Bulk maps and eager loading while preserving response semantics |
| 3 | Bootstrap repeated canonical/favorite/selected store resolution and loaded market media/logos per store | High | Low | Resolve store sets once and bulk-load media |
| 4 | Hot offer, occurrence, media and normal-price filters lacked compound indexes | High as data grows | Low | Portable compound indexes plus migration |
| 5 | Product images and retailer logos lacked consistent dimensions, async decoding and explicit cache policy | Medium, mobile-sensitive | Low | Browser hints and immutable-identity media caching |

SSE delivery itself was already fast locally (50–101 ms for the measured shared-list flows). Replacing its full-snapshot invalidation with delta event sourcing was therefore rejected for this sprint: it would add consistency risk without evidence that it is currently the top bottleneck.

## Frontend findings

- Production route splitting works. The 45.61 kB gzip map chunk is lazy and does not block initial navigation. The client entry is 94.18 kB gzip.
- Startup produced 12 requests with no duplicates in both cold and warm runs. Its waterfall was bounded at 144/128 ms, so no speculative startup request rewrite was made.
- React Query already uses a 30-second default `staleTime`, ten-minute garbage collection and disables refetch on focus/reconnect. Replacing those global rules risked stale price or realtime state.
- The shopping list was the important exception: every unchecked item independently requested alternatives. The route now issues one batch request for the set of relevant product IDs and shares the response with suggestion components. The query is cached for 60 seconds and invalidated naturally when the product-id key changes.
- Existing optimistic shared-list mutations and rollback behavior remain in place. SSE continues to invalidate and fetch an authoritative snapshot, preserving cross-device correctness.
- Images were already generally lazy. Product/list images and logos now declare dimensions and asynchronous decoding, reducing layout and decode pressure on mobile.
- No broad memoization or list virtualization was added: current render collections did not justify the complexity, and the measured delay was server-side.

### Startup request classification

| Class | Data | Policy |
| --- | --- | --- |
| A — needed for usable first view | HTML/app shell, bootstrap identity/region, current route data | Start immediately; keep bounded and deduplicated |
| B — important just after paint | current offers/markets for the active screen, account personalization | React Query cache; route-driven load |
| C — lazy | map implementation, product media beyond viewport, alternative suggestions, sharing-only state | route/component lazy load or `loading=lazy` |

No profile, market, offer or shared-state query was moved out of a correctness-critical path merely to improve a paint number.

## Backend and database changes

- Offer queries eager-load product and store relationships.
- Category slugs, latest offer occurrences and normal/reference prices are resolved in bounded bulk queries. The reference-price priority remains explicit offer reference, then store history, then retailer history.
- Alternatives eager-load relationships, bulk-load categories, deduplicate candidates by product and compute normalized family/token descriptors once per product rather than for every comparison.
- `POST /api/lokero/list/alternatives/batch` accepts at most 50 product IDs and a per-product limit of 1–5. Existing single-item endpoints remain compatible.
- Bootstrap resolves favorite and selected store IDs together and batches store media and retailer-logo reads.
- Slow-request observability now includes offer, market and alternatives paths.

Added indexes:

- `offers(store_id, local_store_offer, valid_from, valid_to)`
- `offer_occurrences(offer_id, collected_at)`
- product, store and retailer media lookup composites
- `normal_price_observations(master_product_id, store_id, is_regular_price, observed_at)`
- `normal_price_observations(master_product_id, retailer, is_regular_price, observed_at)`

On SQLite, `EXPLAIN QUERY PLAN` reports `ix_offers_public_store_validity` for current offers and the covering `ix_offer_occurrences_offer_collected` index for occurrence lookup. The migration was tested upgrade → downgrade → upgrade on a fresh database.

## Before and after

| Scenario | Before p50 / p95 | After p50 / p95 | Before → after queries | p50 change |
| --- | ---: | ---: | ---: | ---: |
| Bootstrap | 131.68 / 263.17 ms | 51.53 / 110.72 ms | 66 → 18 | -60.9% |
| Markets | 11.84 / 15.38 ms | 6.18 / 7.19 ms | 6 → 6 | -47.8% |
| Offers, limit 250 | 745.18 / 1,094.24 ms | 52.23 / 112.91 ms | 827 → 9 | -93.0% |
| Five alternatives | 6,243.78 / 6,262.22 ms | 186.91 / 248.15 ms | 7,277 → 10 | -97.0% |

The alternatives comparison is deliberately end-to-end at the API boundary: the old five sequential single-item requests versus the new one-request batch. Response size also fell from 6,482 to 5,805 bytes. The shopping-list route is expected to benefit directly because it now uses this batch path; no separate browser render claim is made without a stable render trace.

The production frontend output remains effectively unchanged at 94.18 kB gzip for the client entry and 8.81 kB gzip for the list route. A 105 KiB gzip client-entry budget is now enforced after the CI production build. It is a deterministic size guard, not a flaky wall-clock threshold.

## Realtime and shared lists

Measured baseline propagation was already immediate on the local real-browser harness: add 101 ms, quantity 58 ms, checked 74 ms and reconnect 50 ms. The existing flow uses optimistic sender updates, SSE notification and authoritative list refresh. It has no observed duplicate startup requests and no additional fast polling loop.

After the changes, the same harness measured add 96 ms, quantity 64 ms, checked 119 ms and reconnect 44 ms. This normal local variance does not support a claim that the SSE transport itself became faster; it does confirm that all realtime flows, SQLite concurrency and reconnect behavior remain intact after the surrounding query changes.

This sprint improves the DB/media work surrounding normal app refreshes but intentionally keeps full-list reload after an SSE revision. Delta events are a future optimization only when list size or fan-out data demonstrates a problem. The current in-process subscriber registry is the primary horizontal-scaling limitation; multi-instance deployment will require a shared broker.

## Cache strategy

| Category | Policy | Invalidation / reason |
| --- | --- | --- |
| Retailer logos and stable media identity | Public 24 h, `stale-while-revalidate` 7 d | URL/record identity changes when asset changes |
| Product media endpoint | Public 5 min, `stale-while-revalidate` 1 h | Shorter because product media may be corrected |
| Client alternatives batch | 60 s React Query freshness | Query key contains exact product-id set; list changes produce a new key |
| General query cache | Existing 30 s stale / 10 min GC | Avoids a global behavior change for offers and personalization |
| Offers, optimizer and routing | No new server result cache | Correctness and invalidation cost outweigh measured need |
| Shared list quantities/state | Never served from a new TTL cache | Optimistic mutation followed by SSE-authoritative refresh |

No price response cache was added, so current-offer validity and market filtering cannot be made stale by this sprint.

## Media assessment

Small-card images now provide browser dimensions, lazy loading where below the fold and `decoding="async"`. Media/logo endpoints send explicit cache headers. A server-side thumbnail generator was not added because the repository's current media records and fixture did not provide enough measured evidence about original image dimensions to design a lossless detail/card variant contract. That remains a targeted follow-up if production transfer telemetry shows oversized originals.

## Regression protection and validation

- Backend query-budget tests cap offers and alternatives batch paths at 12 queries on a synthetic fixture.
- Batch input limits, candidate deduplication and self-exclusion are tested.
- Scalar-versus-bulk normal-price resolution is tested to preserve explicit/store/retailer priority.
- The existing real browser/FastAPI/SQLite/SSE suite covers shared mutation visibility and reconnect.
- CI now enforces the deterministic client entry gzip budget.
- Full pytest, PostgreSQL readiness, frontend build/lint, critical browser matrix, integration and Docker build remain CI-required checks.

## Risks and remaining work

- Bootstrap still returns a large synthetic payload (about 225 kB with 1,200 fixture offers). Product pagination or route-specific bootstrap envelopes should be considered when real payload telemetry warrants an API contract change.
- SSE subscribers are process-local. Multiple application instances require Redis Streams, PostgreSQL `LISTEN/NOTIFY` plus durable revision checks, or another shared broker.
- Each SSE event still refreshes the full shared list. Very large or high-frequency lists may need revision-coalescing or carefully versioned delta payloads.
- Alternative similarity scoring remains CPU work proportional to the prefetched candidate set. Database/full-text or vector-assisted candidate narrowing should follow only with quality-recall benchmarks.
- The main client entry has limited budget headroom. Dependency additions should remain route-lazy; the new CI guard detects regressions.
- FCP/LCP and real mobile-network transfer are not yet continuously measured. A throttled Lighthouse/Web Vitals telemetry program would add production-relevant evidence without placing flaky latency gates in CI.

## Scaling recommendations

### Around 10k users

- Deploy PostgreSQL, validate query plans with production-like cardinality and enable slow-query sampling.
- Put media behind a CDN and verify cache hit ratio and source image dimensions.
- Track p50/p95/p99 by endpoint, query count, SSE reconnect rate and alternative candidate counts.

### Around 100k users

- Move SSE fan-out to a shared broker and add connection limits, backpressure and event coalescing.
- Add short, explicitly invalidated caches for market identity/coverage; keep prices and shared-list mutations revision-safe.
- Partition background collector/normalization work from request-serving resources and introduce read replicas only after consistency analysis.

### Around 1M users

- Partition offer/history data by time and/or geography, archive cold occurrences and precompute regional current-offer projections.
- Use globally distributed media delivery and region-aware API placement.
- Version shared-list events, use durable streams and compact snapshots, with idempotency and replay tests.
- Maintain offline quality evaluation for alternative candidate retrieval before adopting specialized search infrastructure.

These are capacity-stage recommendations, not changes required by the current local measurements.
