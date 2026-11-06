"""Verify a synthetic data handoff without rewriting or contacting any external service."""

from __future__ import annotations

import hashlib
import json
import math
import re
import runpy
from collections.abc import Iterator
from pathlib import Path

# The handoff manifest is a fixed, small inventory. Refuse accidental or
# malicious oversized metadata before parsing and allocating JSON objects.
MAX_MANIFEST_BYTES = 64 * 1024

# Only bytecode for the two declared modules is a routine cache artifact.
# A filename ending in .pyc is not proof that an unlisted module is safe.
_PACKAGE_BYTECODE = re.compile(
    r"(?:verify|transform)\.cpython-[0-9]{2,4}(?:\.opt-[12])?\.pyc\Z"
)


def _manifest_error_label(value: str, *, limit: int = 120) -> str:
    """Escape and bound untrusted JSON labels before emitting diagnostics."""
    if len(value) <= limit:
        return repr(value)
    return repr(value[:limit]) + " [truncated]"


def _bounded_unlisted_names(names: list[str]) -> str:
    """Escape and limit unexpected filesystem entry names in diagnostics."""
    examples = ", ".join(_manifest_error_label(name) for name in names[:3])
    if len(names) > 3:
        examples += f" (+{len(names) - 3} more)"
    return examples


def _unique_manifest_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Fail closed on duplicate member names at every JSON object depth."""
    result: dict[str, object] = {}
    for name, value in pairs:
        if name in result:
            raise ValueError(f"Duplicate JSON manifest key: {_manifest_error_label(name)}")
        result[name] = value
    return result


def _reject_manifest_constant(value: str) -> None:
    """Reject Python's permissive NaN and Infinity non-JSON literals."""
    raise ValueError(f"Non-standard JSON manifest numeric value: {value}")


def _finite_manifest_float(value: str) -> float:
    """Do not silently decode oversized JSON numeric exponents as infinity."""
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"Non-finite JSON manifest numeric value: {_manifest_error_label(value)}")
    return number


# Keep checksum and canonical-byte comparisons bounded even when a data
# deliverable grows beyond this intentionally small example.
CHUNK_BYTES = 64 * 1024


def _file_sha256(path: Path) -> str:
    """Hash raw file bytes without allocating the entire deliverable."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utf8_chunks(expected: str) -> Iterator[bytes]:
    """Yield UTF-8 fragments that cannot exceed CHUNK_BYTES real bytes.

    A Unicode code point uses at most four UTF-8 bytes. Slicing the string
    into CHUNK_BYTES characters, as opposed to bytes, could make one read
    four times larger than the claimed memory bound.
    """
    width = CHUNK_BYTES // 4
    for offset in range(0, len(expected), width):
        yield expected[offset : offset + width].encode("utf-8")


def _matches_utf8_file(path: Path, expected: str) -> bool:
    """Compare exact UTF-8 bytes in bounded chunks, including EOF and line endings."""
    with path.open("rb") as source:
        for chunk in _utf8_chunks(expected):
            if source.read(len(chunk)) != chunk:
                return False
        return source.read(1) == b""


def verify_package(directory: Path) -> int:
    """Verify raw provenance, tidy provenance and deterministic reproducibility."""
    raw = directory / "raw" / "orders.csv"
    tidy = directory / "tidy" / "orders.csv"
    codebook = directory / "CODEBOOK.md"
    recipe = directory / "transform.py"
    readme = directory / "README.md"
    verifier = directory / "verify.py"
    manifest_path = directory / "manifest.json"
    # Check the complete package boundary before reading metadata or executing
    # the verified recipe. The manifest and package root must be self-contained
    # just like the raw/tidy files and folders.
    for candidate in (
        directory, manifest_path, directory / "raw", directory / "tidy",
        raw, tidy, codebook, recipe, readme, verifier,
    ):
        if candidate.is_symlink():
            relative = "." if candidate == directory else str(candidate.relative_to(directory))
            raise ValueError(f"Symbolic link in synthetic package: {relative}")
    # Never read from a FIFO, socket or device disguised as a deliverable.
    # FIFOs may block indefinitely even before checksum validation begins.
    for folder in (directory, directory / "raw", directory / "tidy"):
        if not folder.is_dir():
            raise ValueError(f"Directory required in synthetic package: {folder}")
    for file in (manifest_path, raw, tidy, codebook, recipe, readme, verifier):
        if not file.is_file():
            raise ValueError(f"Regular file required in synthetic package: {file}")
        # Hard links also share an inode with another path. A checksum can
        # pass even when a supposedly independent deliverable is writable
        # through a file outside the package; refuse multi-linked files.
        if file.stat().st_nlink > 1:
            raise ValueError(
                f"Hard link in synthetic package: {file.relative_to(directory)}"
            )
    # The top-level handoff also has a fixed inventory. A stray .env, data
    # export, or nested folder must not ship merely because the checksums still
    # match. Python may create __pycache__ for the two declared source modules;
    # accept only those modules' conventional CPython cache filenames.
    allowed_root = {
        "README.md", "CODEBOOK.md", "transform.py", "verify.py",
        "manifest.json", "raw", "tidy", "__pycache__",
    }
    extra_root = sorted(entry.name for entry in directory.iterdir() if entry.name not in allowed_root)
    if extra_root:
        raise ValueError(
            f"Unlisted files in synthetic package root: {_bounded_unlisted_names(extra_root)}"
        )
    cache = directory / "__pycache__"
    if cache.is_symlink() or (
        cache.exists()
        and (
            not cache.is_dir()
            or any(
                not item.is_file() or item.is_symlink() or item.stat().st_nlink > 1
                or _PACKAGE_BYTECODE.fullmatch(item.name) is None
                for item in cache.iterdir()
            )
        )
    ):
        raise ValueError("Unlisted files in synthetic package Python cache")
    # The manifest names one data file in each folder. Additional files are
    # not covered by its checksums and could unintentionally expose datasets
    # when a teaching package is shared or published.
    for folder in (directory / "raw", directory / "tidy"):
        unexpected = sorted(
            entry.name for entry in folder.iterdir() if entry.name != "orders.csv"
        )
        if unexpected:
            raise ValueError(
                f"Unlisted files in synthetic package {folder.name}/: {_bounded_unlisted_names(unexpected)}"
            )
    if manifest_path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ValueError("Synthetic package manifest exceeds the maximum size")
    try:
        manifest = json.loads(
            manifest_path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_manifest_keys,
            parse_constant=_reject_manifest_constant,
            parse_float=_finite_manifest_float,
        )
    except RecursionError as exc:
        # An extremely deeply nested JSON array/object can exhaust CPython's
        # decoder recursion limit before the closed manifest schema is checked.
        raise ValueError("Synthetic package manifest is too deeply nested") from exc
    if (
        not isinstance(manifest, dict)
        or manifest.get("data_type") != "synthetic"
        or manifest.get("raw") != "raw/orders.csv"
        or manifest.get("tidy") != "tidy/orders.csv"
        or manifest.get("codebook") != "CODEBOOK.md"
        or manifest.get("recipe") != "transform.py"
    ):
        raise ValueError("Unexpected synthetic package manifest")
    # The manifest's human-readable identity is required, not an unchecked
    # optional field. Refuse empty, oversized, or control-character values so
    # verified handoffs cannot carry ambiguous or terminal-spoofed labels.
    name = manifest.get("name")
    if (
        not isinstance(name, str)
        or not (1 <= len(name) <= 120)
        or not name.isprintable()
        or name != name.strip()
    ):
        raise ValueError("Invalid synthetic package manifest name")
    # A checksum-verified handoff must not silently carry extra metadata,
    # such as paths or private notes that are outside its declared schema.
    # JSON parsing already checks duplicate keys and invalid numeric literals.
    allowed_manifest_keys = {
        "name", "data_type", "raw", "raw_sha256", "tidy", "tidy_sha256",
        "codebook", "codebook_sha256", "recipe", "recipe_sha256",
        "readme_sha256", "verifier_sha256",
    }
    unexpected_keys = sorted(set(manifest) - allowed_manifest_keys)
    if unexpected_keys:
        # The manifest itself is capped at 64 KiB, but its field names can
        # still overwhelm CLI/CI logs. Report only three bounded examples.
        examples = ", ".join(_manifest_error_label(key) for key in unexpected_keys[:3])
        if len(unexpected_keys) > 3:
            examples += f" (+{len(unexpected_keys) - 3} more)"
        raise ValueError(f"Unexpected JSON manifest keys: {examples}")
    if not codebook.read_text(encoding="utf-8").strip():
        raise ValueError("Data dictionary is missing or empty")
    for path, key in (
        (raw, "raw_sha256"),
        (tidy, "tidy_sha256"),
        (codebook, "codebook_sha256"),
        (recipe, "recipe_sha256"),
        (readme, "readme_sha256"),
        (verifier, "verifier_sha256"),
    ):
        checksum = _file_sha256(path)
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
    if not _matches_utf8_file(tidy, expected):
        raise ValueError("Tidy data does not reproduce from the unchanged raw dataset")
    # The canonical CSV writer emits one LF-terminated header and one line
    # per row. Counting linefeeds avoids allocating a second list of rows.
    return expected.count("\n") - 1


if __name__ == "__main__":
    count = verify_package(Path(__file__).resolve().parent)
    print(f"PASS: {count} synthetic records, checksums and reproducible transformation")
