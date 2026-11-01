"""Verify a synthetic data handoff without rewriting or contacting any external service."""

from __future__ import annotations

import hashlib
import json
import math
import runpy
from pathlib import Path


def _unique_manifest_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Fail closed on duplicate member names at every JSON object depth."""
    result: dict[str, object] = {}
    for name, value in pairs:
        if name in result:
            raise ValueError(f"Duplicate JSON manifest key: {name!r}")
        result[name] = value
    return result


def _reject_manifest_constant(value: str) -> None:
    """Reject Python's permissive NaN and Infinity non-JSON literals."""
    raise ValueError(f"Non-standard JSON manifest numeric value: {value}")


def _finite_manifest_float(value: str) -> float:
    """Do not silently decode oversized JSON numeric exponents as infinity."""
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"Non-finite JSON manifest numeric value: {value}")
    return number


def verify_package(directory: Path) -> int:
    """Verify raw provenance, tidy provenance and deterministic reproducibility."""
    raw = directory / "raw" / "orders.csv"
    tidy = directory / "tidy" / "orders.csv"
    codebook = directory / "CODEBOOK.md"
    recipe = directory / "transform.py"
    manifest_path = directory / "manifest.json"
    # Check the complete package boundary before reading metadata or executing
    # the verified recipe. The manifest and package root must be self-contained
    # just like the raw/tidy files and folders.
    for candidate in (
        directory, manifest_path, directory / "raw", directory / "tidy",
        raw, tidy, codebook, recipe,
    ):
        if candidate.is_symlink():
            relative = "." if candidate == directory else str(candidate.relative_to(directory))
            raise ValueError(f"Symbolic link in synthetic package: {relative}")
    # Never read from a FIFO, socket or device disguised as a deliverable.
    # FIFOs may block indefinitely even before checksum validation begins.
    for folder in (directory, directory / "raw", directory / "tidy"):
        if not folder.is_dir():
            raise ValueError(f"Directory required in synthetic package: {folder}")
    for file in (manifest_path, raw, tidy, codebook, recipe):
        if not file.is_file():
            raise ValueError(f"Regular file required in synthetic package: {file}")
    manifest = json.loads(
        manifest_path.read_text(encoding="utf-8"),
        object_pairs_hook=_unique_manifest_keys,
        parse_constant=_reject_manifest_constant,
        parse_float=_finite_manifest_float,
    )
    if (
        not isinstance(manifest, dict)
        or manifest.get("data_type") != "synthetic"
        or manifest.get("raw") != "raw/orders.csv"
        or manifest.get("tidy") != "tidy/orders.csv"
        or manifest.get("codebook") != "CODEBOOK.md"
        or manifest.get("recipe") != "transform.py"
    ):
        raise ValueError("Unexpected synthetic package manifest")
    if not codebook.read_text(encoding="utf-8").strip():
        raise ValueError("Data dictionary is missing or empty")
    for path, key in (
        (raw, "raw_sha256"),
        (tidy, "tidy_sha256"),
        (codebook, "codebook_sha256"),
        (recipe, "recipe_sha256"),
    ):
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        if checksum != manifest.get(key):
            raise ValueError(f"Checksum mismatch for {path.name}: package file was modified")
    # Never execute the recipe until its recorded fingerprint has been checked.
    # Use this verified package's recipe, not an unrelated import from sys.path.
    namespace = runpy.run_path(str(recipe), run_name="_verified_handoff_recipe")
    make_tidy = namespace.get("make_tidy")
    if not callable(make_tidy):
        raise ValueError("Verified recipe does not expose make_tidy")
    expected = make_tidy(raw)
    # Compare canonical UTF-8 bytes, not text opened in universal-newline
    # mode: read_text() silently treats CRLF or bare CR as LF on all platforms.
    if tidy.read_bytes() != expected.encode("utf-8"):
        raise ValueError("Tidy data does not reproduce from the unchanged raw dataset")
    return len(expected.splitlines()) - 1


if __name__ == "__main__":
    count = verify_package(Path(__file__).resolve().parent)
    print(f"PASS: {count} synthetic records, checksums and reproducible transformation")
