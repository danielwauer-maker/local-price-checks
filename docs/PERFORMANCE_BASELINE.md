# Performance baseline

Measured locally on 2026-09-03 in the isolated `codex/performance-sprint-1` worktree. These numbers are development-machine measurements, not production SLOs. The backend series uses FastAPI `TestClient`, SQLite, ten stores, 300 products and 1,200 current offers. Latency includes request handling and serialization; query counts are captured through SQLAlchemy. The reproducible runner is `scripts/benchmark_performance.py` and refuses to run without an explicit disposable `DATABASE_URL`.

## Baseline before the sprint

| Scenario | p50 | p95 | SQL queries | Response |
| --- | ---: | ---: | ---: | ---: |
| Bootstrap | 131.68 ms | 263.17 ms | 66 | 224,966 B |
| Markets | 11.84 ms | 15.38 ms | 6 | 3,893 B |
| Offers, limit 250 | 745.18 ms | 1,094.24 ms | 827 | 165,237 B |
| Alternatives, 1 item | 1,417.65 ms | 1,754.52 ms | 1,453 | 1,298 B |
| Alternatives, 3 items | 4,015.45 ms | 4,119.53 ms | 4,361 | 3,890 B |
| Alternatives, 5 items | 6,243.78 ms | 6,262.22 ms | 7,277 | 6,482 B |

The alternatives rows represent the old client behavior: one HTTP request per list item, executed sequentially. Query count is the median sample count.

## Browser baseline

The existing Playwright/FastAPI/SQLite/SSE integration harness was run against a real local server and browser.

| Scenario | Result |
| --- | ---: |
| Cold shell ready | 270 ms |
| Cold main data ready | 381 ms |
| Cold bootstrap | 138 ms |
| Cold bootstrap payload | 1,424 B |
| Cold requests / duplicates | 12 / 0 |
| Cold request waterfall | 144 ms |
| Warm shell ready | 209 ms |
| Warm main data ready | 257 ms |
| Warm bootstrap | 110 ms |
| Warm requests / duplicates | 12 / 0 |
| Warm request waterfall | 128 ms |
| Shared-list add visible on device B | 101 ms |
| Quantity update visible on device B | 58 ms |
| Checked update visible on device B | 74 ms |
| SSE reconnect | 50 ms |

Account realtime events measured 191 ms for preferences, 148 ms for favorite add, 167 ms for favorite removal, 65 ms for alternative preferences and 50 ms for family preferences.

The harness exposes shell-ready and main-data-ready timings rather than browser paint entries, so FCP, LCP and TTI are intentionally not claimed. Network transfer figures above are payload bytes measured by the local harness and exclude production transport compression and protocol overhead.

## Production frontend build baseline

| Asset | Raw | gzip |
| --- | ---: | ---: |
| Client entry | 297.87 kB | 94.18 kB |
| Lokero API chunk | 67.44 kB | 22.25 kB |
| Shopping-list route | 31.93 kB | 8.81 kB |
| Market map lazy chunk | 154.60 kB | 45.61 kB |

Route splitting and lazy loading were already active. The market map is kept out of the initial entry. The audit found no evidence that a broad bundler rewrite would outperform the lower-risk database and HTTP batching work in this sprint.

## Reproduction

Create an empty disposable database, apply the current migrations, and run:

```powershell
$env:PYTHONPATH=(Get-Location).Path
$env:DATABASE_URL='sqlite:///./data/performance-synthetic.sqlite3'
python scripts/benchmark_performance.py
```

The script seeds only an empty database. Do not point it at a real application database.
