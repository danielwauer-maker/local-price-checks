# ALDI SÜD data-quality hardening

This sprint hardens the stationary ALDI SÜD chain collector and audit after the first successful shared-source QA run exposed parser bleed between adjacent cards.

## Safety rules

- A Pfand/deposit amount must never become the promoted offer price.
- If the legacy parser selected a deposit value from a block that also contains a later offer, the row is rejected instead of borrowing the later offer's price.
- Explicit `Spare … %` promo/regular price pairs take precedence over arbitrary minimum-price selection when the current row is otherwise coherent.
- Broad section labels may be replaced only when the same source block immediately contains a more specific package-bearing product title.
- Missing official images are recovered only by existing image-alt matching; no image is invented or copied from another source.
- ALDI Web Audit remains shared-source/parser QA only. It does not satisfy independent external validation or the collector-primary gate.

## Manual verification after deployment

1. Run ALDI SÜD Dierdorf collection once.
2. Run the Web-Angebots-Audit once for the same period.
3. Confirm there is no offer whose promo price is a Pfand value such as `0,25 €`.
4. Confirm broad labels such as `Kühlung BBQ` do not survive when a concrete package-bearing product is present in the same card.
5. Check that recovered image counts improve where ALDI provides matching official image alt text.
6. Independently verify at least 10–20 offers before any external-validation PASS is recorded.
