# Admin user management

Lokero's current production identity is still anonymous-first. The admin backend therefore exposes a deliberately narrow deletion action for anonymous/test profiles only.

## Current behavior

- `/admin/users` shows whether a profile is anonymous or linked to an external `AccountIdentity`.
- Anonymous profiles can be deleted manually after an explicit browser confirmation.
- The POST endpoint also requires a profile-specific confirmation token (`DELETE-<user_id>`).
- Registered profiles are rejected with HTTP 409. Their future deletion flow must revoke/delete the external auth identity as well as Lokero data.
- Deletion removes profile-owned favorites, shopping data, product-family preferences, region interest, pricing/rating feedback, client/device metadata, coarse activity aggregates, reviewer grants, anonymous client rows and the `UserProfile` itself.
- The admin audit log keeps a minimal deletion event without retaining the deleted profile data.

## Follow-up

When Supabase auth is wired end to end, add a separate registered-account deletion service that first handles the external identity lifecycle and then removes the canonical Lokero profile and all linked device clients. Do not reuse the anonymous test-user endpoint for that purpose.
