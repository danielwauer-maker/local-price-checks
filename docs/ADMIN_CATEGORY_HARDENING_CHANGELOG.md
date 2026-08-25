# Admin category hardening changelog

Implemented on branch `feat/admin-category-hardening`.

- Manual category corrections remain authoritative by setting `category_locked` when a category is selected.
- Clearing the category removes the category lock.
- Exact observed product keys are retained as `admin-correction` aliases so later matching imports resolve to the curated master product.
- Product corrections now record old/new category, lock state, actor and notes in `AdminAuditLog`.
- Added `product_correction_history(...)` helper for per-product correction history.
- Added `apply_manual_category_correction(...)` for category-only edits that do not alter name/brand/package data.
- Invalid category IDs are rejected.
- Added regression tests for lock/unlock behaviour, alias learning and correction history.
- No schema migration is required.
