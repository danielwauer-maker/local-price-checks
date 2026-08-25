# Product taxonomy and deterministic search

## Architecture

`app/product_taxonomy.py` is the single source for the supermarket taxonomy,
classification rules, search terms and semantic product-family definitions.
The API, collectors, category seeding, reclassification CLI and existing
favorite-family endpoints consume this shared definition. The normal request
path uses no LLM, embedding, vector database or external search service.

The taxonomy has one practical parent/child level. Established production
slugs such as `kaese`, `fisch`, `getraenke` and `molkerei` remain the parent
rows, preserving their database IDs and existing `ProductAdminData`
references. Examples:

- `kaese` → `schnittkaese`, `hartkaese`, `weichkaese`, `frischkaese`,
  `mozzarella`, `feta-hirtenkaese`, `reibekaese`
- `fisch` → `fisch-produkte`, `raeucherfisch`, `fischkonserven`,
  `fisch-paniert`, `meeresfruechte`
- `getraenke` → `wasser`, `limonade`, `cola`, `energy`, `saft`, `eistee`,
  `kaffee`, `tee`

`ProductCategory.parent_id` stores this hierarchy. Parent-category searches
include products assigned to every descendant. The migration
`20260825_02_product_category_hierarchy` adds the nullable self-reference
without changing category IDs or existing product assignments.

Deployments must run `python -m alembic upgrade head` before starting the
application. The batch migration is exercised on SQLite and PostgreSQL; it is
additive and preserves existing category rows and assignments on both engines.

## Classification

Rules are ordered from specific to broad. For example, Fischstäbchen are
classified before generic fish, Frischkäse before dairy terms, Cola before
generic drinks and Buttercroissants before butter. A result contains category,
product family, reason and a small confidence label. If no reliable rule
matches, the product remains effectively unknown/`sonstiges`; the classifier
does not force an unrelated category.

Newly collected products continue to use `ensure_auto_category`. Existing
products are never mass-reclassified at application startup.

## Admin authority

`ProductAdminData.category_locked` is authoritative. Automatic collector
classification and the explicit backfill both skip locked rows, including a
deliberate locked assignment to `Sonstiges`. Manual category choices therefore
survive later collection and taxonomy changes.

## Search and ranking

`app/product_search.py` resolves category hierarchy and product-family
synonyms once, performs bounded alias and product candidate queries compatible
with SQLite and PostgreSQL, and ranks the candidates in Python. It does not
create a materialized index and does not issue per-product category queries.

The stable ranking is:

1. exact normalized product name
2. product name starts with the query
3. product name contains the query
4. brand match
5. direct product-family/synonym match
6. direct category match
7. child match through a parent category
8. another generated search-token match

Search tokens combine product name, brand, normalized key, assigned category,
ancestor categories, category search terms and the independently inferred
product family. Partial direct name searches such as `Thun` still work, while
family queries such as `Fisch`, `Cola`, `Coke` and `Käse` expand
deterministically. `GET /api/products` remains compatible and additionally
accepts an optional `category=<slug>` filter.

## Synonyms and product families

Synonyms are backend-owned. They live alongside the taxonomy and are shared by
search and favorite-family matching; the frontend contains no independent
fish/cola/cheese expansion logic.

Category and product family remain different concepts:

- category: a shelf/taxonomy position, for example `Käse > Schnittkäse`
- product family: a substitution intent, for example `kaese` or `cola`

The existing `FavoriteProductFamily` and `FavoriteProductPreference`
structures remain the persistence layer for Sprint D. No parallel family table
was added. Dietary attributes were intentionally not inferred from names;
reliable vegan/gluten-free/etc. source data can later use an additive tag model
without changing the taxonomy/search contract.

## Explicit reclassification

Preview all unlocked changes without writing:

```bash
python scripts/reclassify_products.py
```

The output contains product ID/name, previous category, proposed category,
status and matching rule plus totals for `inspected`, `changed`, `unchanged`,
`locked` and `unknown`.

Apply only after reviewing the dry run:

```bash
python scripts/reclassify_products.py --apply
```

The command never changes locked products. There is no automatic startup
backfill.
