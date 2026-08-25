# Admin category hardening

Lokero treats automatic product classification as an initial suggestion, not as an authority over explicit admin review.

## Manual category correction

The existing admin product editor remains the primary UI for assigning a category. Saving a category through the admin correction path:

- stores the selected `ProductCategory` on `ProductAdminData`,
- sets `category_locked=true`,
- remembers the product's observed `normalized_key` as an `admin-correction` alias,
- records a detailed `AdminAuditLog` entry with old/new category, lock state, actor and notes.

A locked category must not be overwritten by the reclassification script. Clearing the category removes the category lock so the product can be classified or reviewed again later.

## Learning model

This is deliberately human-in-the-loop learning, not uncontrolled online model training.

The first safe learning layer is exact product identity: the observed product key is retained as an admin correction alias that resolves later occurrences back to the curated master product. Its locked category therefore remains authoritative.

Broad taxonomy rules are **not** generated automatically from one manual correction. Repeated corrections can be analysed later to propose classifier rules, which should only become global rules after review and tests.

## History

Product correction history is stored in `AdminAuditLog` and can be read with `product_correction_history(...)`. The global Admin `Audit-Log` view remains the operational history UI.

No schema change or data migration is required for this hardening task.
