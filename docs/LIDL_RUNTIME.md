# Lidl production runtime

## Root cause (2026-08-20)

The production support state showed a Lidl Puderbach run stuck at `running`
with zero received/imported offers after more than 13 minutes. The historical
viewer diagnostic had traversed 37 visual states to reach page 72 of 73.

The first Schwarz leaflet API response already contains the complete logical
page list, `image`/`zoom` assets and `pdfUrl`/`hiResPdfUrl`. The old collector
still clicked through every spread, captured screenshots and then applied a
runtime OCR monkey patch to every captured page serially. The admin background
job also started a second visual diagnostic traversal after collection.

## Canonical path

The production Lidl path is now:

1. resolve the store-specific leaflet;
2. open the viewer once and capture the complete Schwarz manifest;
3. extract authoritative structured page offers;
4. fetch direct page assets concurrently, with a persistent URL/content-hash
   cache;
5. run bounded parallel OCR only for local pages without authoritative
   structured hits;
6. download the official manifest PDF directly and archive it before import;
7. import, attach page provenance, and persist quality/benchmark status.

Catalogue-link enrichment does not suppress OCR for mixed grocery pages.
Explicit online-shop pages are excluded before OCR and online markers are not
imported.

## Runtime controls

- total collector deadline: 540 seconds;
- admin hard-stop watchdog: 550 seconds;
- viewer manifest: 65 seconds;
- structured extraction: 20 seconds;
- direct assets: 80 seconds;
- OCR fallback: 240 seconds;
- artifact archive: 80 seconds;
- individual OCR subprocess: 18 seconds;
- page asset downloads: concurrent batches of up to eight;
- OCR: up to four concurrent workers.

`collection_run_progress` persists `phase`, `error_type`, `pages_total`,
`pages_structured`, `pages_ocr`, `pages_done`, `assets_cached`, and
`elapsed_seconds`. A timeout with no usable result is `failed`; a timeout after
usable offers is a technical `warning`.

## Live smoke result

Executed in the production Docker image against the official Lidl Puderbach
leaflet for 17.08.2026–22.08.2026:

- elapsed: 128.4 seconds;
- viewer navigation: 0;
- pages: 72 total, 24 with structured candidates, 60 selective OCR
  fallback (overlap is intentional), 72 done;
- offers: 109 received, 109 imported;
- archive: 1 official 72-page PDF;
- provenance: 109 links;
- run status: `success`;
- quality status: `WARN` (low image/package coverage remains visible);
- benchmark status: `PASS`;
- explicit online-marker imports: 0;
- detected: Lavazza Caffè Crema, Pepsi / Schwip Schwap, helle kernlose
  Trauben, Funny-Frisch Pom-Bär.

The result is below the two-to-three-minute target and eliminates unbounded
`running` states.
