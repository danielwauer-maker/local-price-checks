# Lovable frontend source

Controlled snapshot of:
`danielwauer-maker/price-radar-app-81-960e2446` (`main`)

This folder is design/frontend source only. The production backend, collectors,
database and Sparplan remain in the Local Price Checks application.

## Spareno production overlay

Spareno branding is a protected production overlay. Lovable must not overwrite
approved production branding without an explicit, reviewed sync approval.

Protected paths include:
- `public/brand/`
- `public/manifest.webmanifest`
- `src/brand.css`
- `src/components/brand/`

The sync tooling defaults to dry/safe mode. A write requires explicit approval
(`--apply` / `-Apply` or the confirmed workflow input), and protected branding
paths remain excluded even during an approved sync.

Internal legacy names such as `lokero_*` may remain for technical compatibility
until a separate refactoring sprint. They are not part of the public brand.
