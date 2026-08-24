# Lokero Account & PostgreSQL Readiness

## Status

This document defines the production-safe transition from anonymous browser profiles and SQLite to authenticated multi-device accounts and PostgreSQL. It is intentionally incremental: existing user data remains valid throughout the rollout.

## 1. Account identity model

### Existing source of truth

`UserProfile` remains the owner of user data such as:

- location and radius
- favorite stores
- favorite products
- product-family favorites and alternative settings
- shopping-list data
- future notification preferences

`UserClient` remains the anonymous browser/PWA identity during the transition.

### New additive tables

`AccountIdentity` links a provider-verified auth subject to the existing `UserProfile`.

`AccountClientLink` associates one or more browser/PWA clients with that account identity.

The legacy `UserClient.user_id` uniqueness constraint is deliberately not altered while production is on SQLite. Authenticated requests can later resolve the canonical profile through `AccountIdentity`, while anonymous requests continue using the existing behavior.

### Registration/linking rule

When a verified identity is linked for the first time, the current anonymous client's existing `UserProfile` becomes the canonical account profile. No fresh profile is created. This preserves all anonymous data.

On a second device, the existing account identity remains canonical. The second client is linked to that identity instead of replacing the account profile.

### Provider rollout

1. E-mail/password via the existing Supabase frontend integration.
2. Google via the existing OAuth integration.
3. Apple only after the provider, redirect URI, credentials and production callback have been configured and tested end-to-end.

The backend must verify the Supabase access token/JWT before calling the account-linking service. The linking service must never treat an unverified provider subject supplied by the browser as trusted identity data.

## 2. Remaining auth implementation

Before account login is considered production-ready:

- add backend Supabase JWT/JWKS verification
- add an authenticated account-link endpoint
- resolve authenticated requests to the canonical account profile
- keep anonymous access working when no valid auth token is present
- add conflict handling for a client already linked to a different account
- add account logout/session-expiry tests
- add multi-device API integration tests
- update the auth page branding from legacy `LocalPrices` to `Lokero`
- expose Apple only after provider configuration is verified

## 3. Store coordinates and distance

The existing `Store` model already contains permanent address, postal code, city, latitude and longitude fields. No parallel location table is required.

Current user-facing distance uses Haversine/straight-line distance. Until a routing provider is implemented, the UI and API must not describe that value as driving distance.

Before a store is publicly released, require:

- complete street address
- postal code and city
- non-null latitude and longitude
- coordinate validation against the physical branch
- `benchmark_verified = true`

A later routing layer can calculate driving distance and route duration for display, travel costs and shopping optimization without replacing the stored branch coordinates.

## 4. PostgreSQL migration strategy

Do not replace `DATABASE_URL` in production without a verified migration.

### Stage A — prepare

- introduce a migration framework/baseline before destructive schema changes
- add a PostgreSQL driver and PostgreSQL service in a dedicated migration PR
- provision PostgreSQL with a persistent volume separately from the current SQLite database
- keep the application on SQLite during validation

### Stage B — snapshot

- stop application writes or enter a short maintenance window
- checkpoint SQLite WAL
- create a byte-for-byte database backup
- keep the original SQLite database read-only as rollback material

### Stage C — copy

- create PostgreSQL schema from the validated production models/migrations
- copy every table preserving primary keys and foreign keys
- reset PostgreSQL sequences to `MAX(id)` after import

### Stage D — validate

At minimum compare:

- row counts for every table
- user profile count
- anonymous client count
- favorite store/product/family counts
- shopping-list counts
- public store and current-offer counts
- foreign-key integrity
- unique-constraint integrity
- critical API smoke tests

Do not cut over if any verification differs unexpectedly.

### Stage E — cutover

- switch `DATABASE_URL` only after validation
- start the application against PostgreSQL
- run health/API/user-data smoke tests
- retain SQLite rollback copy for at least one release window

## 5. Backup policy

Target production policy:

- automated daily PostgreSQL logical backup (`pg_dump`, custom format)
- encryption before offsite transfer
- offsite storage independent of the application server
- multiple generations (suggested starting policy: 14 daily, 8 weekly, 6 monthly)
- backup job failure alerts
- scheduled restore test into an isolated temporary PostgreSQL database
- documented restore runbook

A backup is only considered reliable after a restore test has completed successfully.

## 6. Deployment safety

- no destructive migration without a tested rollback path
- no deletion of legacy anonymous profiles during account rollout
- no Apple login button before provider readiness
- no PostgreSQL cutover in the same change that introduces untested schema migrations
- CI must stay green before merge
