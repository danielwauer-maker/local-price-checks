# Frontend E2E and beta hardening

## Purpose

The browser suite validates the current Spareno frontend against deterministic fixtures. It never uses production users, production authentication, or live offer data. Every run builds the production frontend and serves the generated Cloudflare/Nitro worker through a local Node adapter before Playwright starts.

## Commands

From `frontend-lovable-source`:

```bash
bun install --frozen-lockfile
bun run test:e2e:install
bun run test:e2e:critical  # PR smoke, desktop Chromium
bun run test:e2e:matrix    # critical flows in all five browser profiles
bun run test:e2e:full      # full regression in all five profiles
```

The five profiles are desktop Chromium, desktop Firefox, desktop WebKit, mobile WebKit (390 × 844), and mobile Chromium (412 × 915). Explicit responsive coverage additionally checks 375 × 667, 768 × 1024, and 1440 × 900.

Failures retain a screenshot, trace, and video. Browser exceptions, unexpected console errors, and unexpected HTTP 5xx responses fail the test. Expected failures must be declared per test; there is no global console-error ignore.

## Deterministic environment

- Browser storage is seeded before application code runs.
- API reads and mutations are intercepted with per-test in-memory state.
- External map tiles and fonts are replaced by deterministic responses.
- Service workers are blocked during routed E2E flows so they cannot bypass API fixtures. Manifest and service-worker assets have a separate smoke test.
- `tests/conftest.py` creates a fresh process-scoped SQLite database outside the repository and removes it after pytest. PostgreSQL integration tests still create and drop their own uniquely named database via `POSTGRES_TEST_URL`.
- `VITE_E2E_MODE` and dummy Supabase values are scoped to the E2E build. No production authentication behavior is weakened.

## Covered current-product flows

| Area | Automated coverage |
| --- | --- |
| Routing | Main routes, direct URLs, reload, 404 boundary, bottom navigation, back/forward |
| Discovery | Radius change, market view, search, category expansion, product detail, search-state restoration |
| Favorites | Optimistic add/remove, favorites page consistency, product families, alternative preference and reload persistence |
| Favorite sharing | Owner opt-in, per-product visibility, public share rendering, privacy boundary, friend subscription controls |
| Shopping list | Offer add, rapid quantity changes, removal at zero, reload persistence, shared list/member state |
| Invites and return-to | Shopping-list invite preview and exact auth return path; public favorite link and exact auth return path |
| Realtime | Shared-list revision events and account favorite events reconcile visible state without reload |
| Friend favorites | Friend products and in-app notification preference mutation |
| Settings | Radius, travel cost, notification toggle, reload persistence |
| Auth surface | Login and registration entry states render without external credentials |
| Resilience | Expected 503 fallback, no blank UI, runtime/console/5xx gates |
| Quality | Axe serious/critical smoke, responsive overflow, PWA assets |

## Bugs fixed in this sprint

- Consecutive state mutations could read a stale React closure and lose rapid quantity or favorite updates. Store mutations now use a synchronous state reference.
- Search text was lost after product detail and browser Back. The query is now reflected in the URL with history-safe replacement.
- The splash could permanently intercept the UI after hydration trouble and delayed every first action for almost three seconds. It now has a CSS fail-safe and a shorter bounded duration.
- Favorite image links and the savings explanation had invalid or missing accessible names.
- The product-family modal lacked dialog semantics and an accessible close name.
- Pytest inherited a developer `.env` database and could run against a stale schema. Test discovery now forces an isolated temporary database.
- The E2E runner leaked the Vite child process on Windows. The runner now owns production build, preview server, browser process, and cleanup.

## Environment boundaries (not hidden by tests)

The current frontend implements shared shopping lists, invitations and members, checked/free-text list items, favorite sharing and public links, friend favorites, safe return-to handling, and event-driven account/list synchronization. The browser suite exercises those product components and state transitions. Its in-memory API and SSE transport provide isolated test data only; they do not replace routes, UI logic, mutations, privacy controls, or realtime reconciliation code.

Real email delivery, OAuth, password recovery, long-lived session restoration, and a true two-device run require a dedicated non-production Supabase project and test accounts. This repository suite verifies the credential-free auth UI, invite/favorite return-to contract, account-state reconciliation, and SSE-driven updates without an auth backdoor. A staging identity-provider run remains an external release check.

Coverage claims apply to the checked-in product surface and deterministic release gates, not third-party email/OAuth delivery or production infrastructure availability.

## Performance baseline

The production build currently completes locally in roughly 6 seconds end to end; its largest emitted client chunks are approximately 296 kB raw for the application entry, 212 kB for the client runtime, and 155 kB for the lazy-loaded map. A Chromium smoke records initial load, offers page, and favorite mutation timings as `performance-baseline.json`; only a generous 10-second beta-safety ceiling is enforced to avoid hardware-dependent flakiness. The E2E suite detected no request loops. Favorite and shopping-list mutations are optimistic, while shared-list and account events reconcile without reload; tests wait on DOM state, never fixed sleeps.

## CI gates

A pull request is gated by the complete SQLite backend suite, the PostgreSQL readiness suite, mandatory frontend lint, production frontend build, the critical five-profile Playwright matrix, and the Docker Compose build. Playwright failure artifacts are retained for seven days.
