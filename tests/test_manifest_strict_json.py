"""Handoff manifest parsing must reject ambiguity before running the recipe."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HANDOFF = Path(__file__).resolve().parents[1] / "examples" / "handoff"
sys.path.insert(0, str(HANDOFF))

from verify import MAX_MANIFEST_BYTES, verify_package  # noqa: E402


class StrictManifestTests(unittest.TestCase):
    def _check_invalid_manifest(self, manifest_text: str, message: str) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / "handoff"
            shutil.copytree(HANDOFF, package)
            (package / "manifest.json").write_text(manifest_text, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, message):
                verify_package(package)

    def test_original_package_still_reproduces(self) -> None:
        self.assertEqual(verify_package(HANDOFF), 3)

    def test_duplicate_sha256_keys_cannot_hide_conflicting_digests(self) -> None:
        original = (HANDOFF / "manifest.json").read_text(encoding="utf-8")
        bad_digest = "0" * 64
        for repeated in ('"raw_sha256"', '"r\\u0061w_sha256"'):
            with self.subTest(key=repeated):
                modified = original.replace(
                    '"raw_sha256":',
                    f'{repeated}: "{bad_digest}",\n  "raw_sha256":',
                    1,
                )
                self.assertNotEqual(modified, original)
                # Standard json.loads silently accepts this and keeps the last key.
                self.assertEqual(
                    json.loads(modified)["raw_sha256"],
                    json.loads(original)["raw_sha256"],
                )
                self._check_invalid_manifest(modified, "Duplicate JSON manifest key")

    def test_duplicate_ignored_nested_keys_are_rejected_too(self) -> None:
        original = (HANDOFF / "manifest.json").read_text(encoding="utf-8")
        modified = original.rstrip()[:-1] + (
            ',\n  "extra": {"status": "draft", "status": "approved"}\n}\n'
        )
        self._check_invalid_manifest(modified, "Duplicate JSON manifest key: 'status'")

    def test_python_json_extensions_and_overflow_are_rejected(self) -> None:
        original = (HANDOFF / "manifest.json").read_text(encoding="utf-8")
        for literal in ("NaN", "Infinity", "-Infinity", "1e9999", "-1e9999"):
            with self.subTest(value=literal):
                modified = original.rstrip()[:-1] + (
                    f',\n  "extra": {literal}\n}}\n'
                )
                self._check_invalid_manifest(modified, "JSON manifest numeric value")

    def test_oversized_manifest_is_rejected_before_parsing(self) -> None:
        original = (HANDOFF / "manifest.json").read_text(encoding="utf-8")
        assert len(original.encode("utf-8")) < MAX_MANIFEST_BYTES
        self._check_invalid_manifest(
            original + " " * (MAX_MANIFEST_BYTES + 1),
            "manifest exceeds the maximum size",
        )

    def test_deeply_nested_manifest_is_a_controlled_validation_error(self) -> None:
        original = (HANDOFF / "manifest.json").read_text(encoding="utf-8")
        nested = "[" * 1400 + "0" + "]" * 1400
        modified = original.rstrip()[:-1] + ', "extra": ' + nested + "}"
        assert len(modified.encode("utf-8")) < MAX_MANIFEST_BYTES
        self._check_invalid_manifest(modified, "manifest is too deeply nested")

    def test_manifest_at_maximum_size_remains_accepted(self) -> None:
        original = (HANDOFF / "manifest.json").read_text(encoding="utf-8")
        payload = original + " " * (MAX_MANIFEST_BYTES - len(original.encode("utf-8")))
        assert len(payload.encode("utf-8")) == MAX_MANIFEST_BYTES
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / "handoff"
            shutil.copytree(HANDOFF, package)
            # write_text() translates LF to CRLF on Windows, silently
            # exceeding the byte limit. Preserve the exact-size UTF-8 bytes.
            (package / "manifest.json").write_bytes(payload.encode("utf-8"))
            self.assertEqual(verify_package(package), 3)

    def test_unlisted_manifest_metadata_is_rejected(self) -> None:
        # The example handoff is a closed inventory: extra metadata is not
        # covered by checksums and must not travel with a verified package.
        original = (HANDOFF / "manifest.json").read_text(encoding="utf-8")
        for unexpected in (
            '"private_note": "not part of the handoff"',
            '"external_path": "../../outside.csv"',
            '"hidden_columns": ["personal_id", "address"]',
        ):
            with self.subTest(extra=unexpected):
                modified = original.rstrip()[:-1] + f",\n  {unexpected}\n}}\n"
                self._check_invalid_manifest(modified, "Unexpected JSON manifest keys")

    def test_manifest_requires_printable_bounded_name(self) -> None:
        original = json.loads((HANDOFF / "manifest.json").read_text(encoding="utf-8"))
        invalid_names = (
            None,
            "",
            "   ",
            " preceding-space",
            "trailing-space ",
            "bad\nline",
            "terminal\x1b[31mcolor",
            "x" * 121,
            5,
            ["looks", "like", "a", "name"],
        )
        for invalid in invalid_names:
            with self.subTest(name=repr(invalid)):
                payload = dict(original)
                payload["name"] = invalid
                self._check_invalid_manifest(
                    json.dumps(payload), "Invalid synthetic package manifest name"
                )
        without_name = dict(original)
        del without_name["name"]
        self._check_invalid_manifest(
            json.dumps(without_name), "Invalid synthetic package manifest name"
        )

    def test_manifest_preserves_valid_unicode_human_readable_name(self) -> None:
        original = json.loads((HANDOFF / "manifest.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / "handoff"
            shutil.copytree(HANDOFF, package)
            original["name"] = "Ejemplo de órdenes sintéticas, año 2026"
            (package / "manifest.json").write_text(
                json.dumps(original, ensure_ascii=False), encoding="utf-8"
            )
            self.assertEqual(verify_package(package), 3)

    def test_root_must_be_a_manifest_object(self) -> None:
        for text in ("null", "[]", "{}", '"synthetic"', "42"):
            with self.subTest(root=text):
                self._check_invalid_manifest(text, "Unexpected synthetic package manifest")


if __name__ == "__main__":
    unittest.main()
