"""Verify a synthetic data handoff without rewriting or contacting any external service."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from transform import make_tidy


def verify_package(directory: Path) -> int:
    """Verify raw provenance, tidy provenance and deterministic reproducibility."""
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if (
        manifest.get("data_type") != "synthetic"
        or manifest.get("raw") != "raw/orders.csv"
        or manifest.get("tidy") != "tidy/orders.csv"
        or manifest.get("codebook") != "CODEBOOK.md"
        or manifest.get("recipe") != "transform.py"
    ):
        raise ValueError("Unexpected synthetic package manifest")
    raw = directory / "raw" / "orders.csv"
    tidy = directory / "tidy" / "orders.csv"
    for path, key in ((raw, "raw_sha256"), (tidy, "tidy_sha256")):
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        if checksum != manifest.get(key):
            raise ValueError(f"Checksum mismatch for {path.name}: source was modified")
    if not (directory / "CODEBOOK.md").read_text(encoding="utf-8").strip():
        raise ValueError("Data dictionary is missing or empty")
    expected = make_tidy(raw)
    if tidy.read_text(encoding="utf-8") != expected:
        raise ValueError("Tidy data does not reproduce from the unchanged raw dataset")
    return len(expected.splitlines()) - 1


if __name__ == "__main__":
    count = verify_package(Path(__file__).resolve().parent)
    print(f"PASS: {count} synthetic records, checksums and reproducible transformation")
