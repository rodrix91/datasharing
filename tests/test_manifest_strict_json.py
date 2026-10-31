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

from verify import verify_package  # noqa: E402


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

    def test_root_must_be_a_manifest_object(self) -> None:
        for text in ("null", "[]", "{}", '"synthetic"', "42"):
            with self.subTest(root=text):
                self._check_invalid_manifest(text, "Unexpected synthetic package manifest")


if __name__ == "__main__":
    unittest.main()
