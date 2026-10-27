# Codebook: synthetic order handoff

This is a **fictional** three-record dataset created solely to demonstrate a reproducible handoff. It does not contain customer, employee or transactional records.

## Study design

An invented example of orders in two fictional regional categories. One row represents one order, `order_id` is the primary key, and the three rows are not sampled from any real population. No statistical conclusions or performance claims can be drawn from them.

## Variables

| Column | Meaning | Unit or allowed values | Missingness |
|---|---|---|---|
| `order_id` | Stable artificial order identifier | ASCII letters, digits, underscores, hyphens; unique | None allowed |
| `region` | Invented region label | Nonempty alphabetical text, e.g. North or South | None allowed |
| `units` | Quantity ordered | Strictly positive integer units | None allowed |
| `unit_price_usd` | Artificial per-unit price | USD, nonnegative decimal with up to two fractional digits | None allowed |
| `revenue_usd` | Derived gross amount in tidy output only | USD, `units * unit_price_usd`, shown to two decimals | Derived, never imputed |

## Transformation and provenance

- Preserve `raw/orders.csv` unchanged. Its SHA-256 digest is recorded in `manifest.json`.
- Run `python examples/handoff/transform.py` from the repository root to print deterministic tidy CSV to stdout. The script reads raw data and does **not** write or overwrite input files.
- `tidy/orders.csv` contains exactly the same observations with the calculated `revenue_usd` column. Its SHA-256 digest is recorded separately.
- `python examples/handoff/verify.py` independently checks both checksums and exact raw-to-tidy reproduction. It makes no network requests.
- Record provenance, permission and confidentiality rules separately for any **real** handoff. Never treat this fictional example as a real dataset.
