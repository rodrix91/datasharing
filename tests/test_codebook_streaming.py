"""Streaming codebook validation must preserve UTF-8 and integrity guarantees."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / "examples" / "handoff"
sys.path.insert(0, str(ROOT))

from verify import CHUNK_BYTES, verify_package  # noqa: E402


def replace_codebook(directory: Path, payload: bytes) -> None:
    """Replace only the codebook and record its exact new content checksum."""
    (directory / "CODEBOOK.md").write_bytes(payload)
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["codebook_sha256"] = hashlib.sha256(payload).hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


class StreamingCodebookTests(unittest.TestCase):
    def test_large_unicode_codebook_is_verified_without_read_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "handoff"
            shutil.copytree(ROOT, directory)
            content = "## Data dictionary\n" + "Países, órdenes y 字段.\n" * (CHUNK_BYTES // 6)
            payload = content.encode("utf-8")
            self.assertGreater(len(payload), CHUNK_BYTES)
            replace_codebook(directory, payload)

            # The metadata parser may read its small manifest. The codebook
            # itself must never be loaded with Path.read_text in one allocation.
            original_read_text = Path.read_text

            def checked_read_text(path: Path, *args: object, **kwargs: object) -> str:
                if path.name == "CODEBOOK.md":
                    raise AssertionError("codebook must be read in bounded chunks")
                return original_read_text(path, *args, **kwargs)

            with patch.object(Path, "read_text", checked_read_text):
                self.assertEqual(verify_package(directory), 3)

    def test_only_unicode_whitespace_is_not_a_valid_dictionary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "handoff"
            shutil.copytree(ROOT, directory)
            payload = ("\u2003" * (CHUNK_BYTES // 3 + 5) + "\r\n\t").encode("utf-8")
            replace_codebook(directory, payload)
            with self.assertRaisesRegex(ValueError, "Data dictionary is missing or empty"):
                verify_package(directory)

    def test_late_malformed_utf8_is_rejected_even_after_visible_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "handoff"
            shutil.copytree(ROOT, directory)
            payload = b"# Data dictionary\n" + b"x" * (CHUNK_BYTES * 2) + b"\xff"
            replace_codebook(directory, payload)
            with self.assertRaises(UnicodeDecodeError):
                verify_package(directory)

    def test_rehashed_codebook_rejects_hidden_terminal_controls(self) -> None:
        # A matching manifest checksum does not make control bytes safe.
        # Put the byte after the first streaming chunk to test full coverage.
        for label, unsafe_byte in (
            ("nul", b"\x00"),
            ("escape", b"\x1b"),
            ("delete", b"\x7f"),
        ):
            with self.subTest(control=label), tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp) / "handoff"
                shutil.copytree(ROOT, directory)
                payload = (
                    b"# Data dictionary\n"
                    + b"Visible description " * (CHUNK_BYTES // 15 + 2)
                    + unsafe_byte
                    + b"\n"
                )
                replace_codebook(directory, payload)
                with self.assertRaisesRegex(ValueError, "unsafe control characters"):
                    verify_package(directory)

    def test_readable_codebook_accepts_normal_formatting_and_unicode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "handoff"
            shutil.copytree(ROOT, directory)
            payload = "# Data dictionary\r\n\tRegión y código: 東京, 🧾\n".encode("utf-8")
            replace_codebook(directory, payload)
            self.assertEqual(verify_package(directory), 3)


if __name__ == "__main__":
    unittest.main()
