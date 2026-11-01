# Reproducible synthetic data handoff

This **independent companion example** illustrates the four deliverables described in the preserved [data-sharing guide](../../README.md), without modifying that original text. All records are fictional.

| Deliverable | Example |
|---|---|
| Unmodified raw data | [raw/orders.csv](raw/orders.csv) |
| Reproducible tidy data | [tidy/orders.csv](tidy/orders.csv) |
| Data dictionary and study design | [CODEBOOK.md](CODEBOOK.md) |
| Exact transformation recipe | [transform.py](transform.py) |
| Checksums and package inventory | [manifest.json](manifest.json) |

## Reproduce and verify

Run these commands from the repository root with **Python 3.11 or later**, using only the standard library:

```bash
python examples/handoff/transform.py
python examples/handoff/verify.py
python -m unittest discover -s tests -v
```

The first command prints tidy CSV without writing files. The verifier checks SHA-256 fingerprints for **all four handoff deliverables**—raw data, tidy output, codebook and transformation script—against the manifest, then compares the saved tidy CSV to a fresh in-memory transformation. It rejects **duplicate manifest JSON keys** (including escaped aliases and duplicates nested inside extra fields), non-standard `NaN`/`Infinity` values, floating-point exponents that overflow to infinity, and manifests that are not objects, rather than trusting ambiguous integrity metadata. The verifier checks the transformation recipe's fingerprint **before executing it**, then uses the checked script from the specified package directory rather than importing an unrelated module from the Python search path. The checks catch accidental or unreviewed file drift; **they are not a sandbox**, do not authenticate a manifest that might itself be untrusted, and do not replace signed provenance or a code review for real datasets. The tests also prove that corrupted files, duplicate IDs, invalid quantities, malformed prices and **unclosed or incorrectly closed CSV quotation marks** fail validation. The transformer accepts UTF-8 CSV exports with or without an Excel byte-order mark (BOM), without changing the original raw file or the canonical tidy output. Prices must be plain, unsigned fixed-point decimals with at most two fractional digits; scientific notation, plus signs and surrounding spaces are rejected before arithmetic. It uses strict CSV parsing, **rejects blank physical CSV records even when the following record has quoted multiline cells, instead of silently dropping them**, and reports the actual physical source line (including quoted multiline cells), rather than silently accepting damaged records or reporting only their record position. Revenue is computed with enough local decimal precision for the full price coefficient and integer quantity, so even unusually large synthetic order totals retain **exact cents** instead of silently rounding at Python's default 28-digit Decimal precision; the global decimal context is left unchanged. The [CI workflow](../../.github/workflows/handoff.yml) repeats verification on Linux, Windows and macOS.

## Data handling

This is a tiny teaching example, **not real customer data**. Do not put confidential or personal data in a public GitHub repository. For actual data sharing, establish the data owner's permission, agreed access controls, retention rules, metadata and applicable ethics/privacy requirements before any transfer. Preserve source files, document every transformation and validate the handoff independently.
