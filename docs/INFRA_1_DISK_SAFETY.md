# INFRA-1 production deploy disk safety

Production builds now require at least 7 GiB free on the root filesystem after
safe pre-build cleanup. The threshold is intentionally close to twice the last
observed 3.6 GB app image: a build must be able to create replacement layers
while the active image remains available for rollback and uninterrupted
service. The gate is fail-closed if free bytes cannot be measured.

The cleanup removes unused BuildKit cache and dangling images only. It never
prunes volumes, stops containers, deletes databases/backups, or forcibly
removes an image referenced by a container. Both preflight phases and the
successful post-health state log `df -h /` and `docker system df`.

## Why the app image is large

The Docker build context is already bounded: `.dockerignore` excludes local
data, virtual environments, frontend sources, caches, databases, and logs. The
approximately 3.6 GB image is therefore explained primarily by runtime content:

- the full `python:3.12-bookworm` base rather than a slim base;
- Chromium plus its graphical/media/system dependencies installed by
  `playwright install --with-deps chromium`;
- Tesseract and German OCR language data;
- PDF/image/native libraries such as PyMuPDF, Pillow, and zxing-cpp;
- API serving, browser collection, PDF processing, and OCR all sharing one
  runtime image.

Changing the Python base or removing browser/OCR dependencies in INFRA-1 would
alter production collector behavior and is not a low-risk disk-safety change.
No image-runtime change is included in this PR.

## Recommended INFRA-2 image optimization

1. Record `docker image inspect`, `docker history --no-trunc`, and BuildKit
   layer sizes from a production-equivalent build.
2. Split the lightweight API runtime from a collector worker image containing
   Chromium, Tesseract, and PDF tooling; keep the existing data-volume contract.
3. Validate `python:3.12-slim-bookworm` in the collector image with browser,
   OCR, PDF, barcode, health, and live-collector smoke tests before adopting it.
4. Move test-only dependencies such as pytest out of production requirements.
5. Add an image-size budget only after the split establishes a reproducible
   baseline; do not hide growth by pruning volumes or active rollback images.
