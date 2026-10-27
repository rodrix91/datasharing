"""Regression tests for the independent synthetic research data handoff."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "examples" / "handoff"
sys.path.insert(0, str(ROOT))

from transform import make_tidy  # noqa: E402
from verify import verify_package  # noqa: E402


class SyntheticDataHandoffTests(unittest.TestCase):
    def test_complete_handoff_is_verified(self) -> None:
        self.assertEqual(verify_package(ROOT), 3)

    def test_raw_file_is_never_rewritten_by_transformation(self) -> None:
        raw = ROOT / "raw" / "orders.csv"
        before = hashlib.sha256(raw.read_bytes()).hexdigest()
        result = make_tidy(raw)
        self.assertEqual(result, (ROOT / "tidy" / "orders.csv").read_text(encoding="utf-8"))
        self.assertEqual(before, hashlib.sha256(raw.read_bytes()).hexdigest())

    def test_corrupt_raw_and_tidy_are_rejected(self) -> None:
        for file in ("raw/orders.csv", "tidy/orders.csv"):
            with self.subTest(path=file), tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp) / "handoff"
                shutil.copytree(ROOT, directory)
                target = directory / file
                target.write_text(target.read_text(encoding="utf-8") + "corrupt\n", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "Checksum mismatch"):
                    verify_package(directory)

    def test_corrupt_codebook_and_transformation_script_are_rejected(self) -> None:
        for file in ("CODEBOOK.md", "transform.py"):
            with self.subTest(path=file), tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp) / "handoff"
                shutil.copytree(ROOT, directory)
                target = directory / file
                target.write_text(
                    target.read_text(encoding="utf-8") + "\n# unexpected modification\n",
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(ValueError, "Checksum mismatch"):
                    verify_package(directory)

    def test_modified_or_missing_metadata_fingerprints_are_rejected(self) -> None:
        for key in ("raw_sha256", "tidy_sha256", "codebook_sha256", "recipe_sha256"):
            for replacement in (None, "0" * 64):
                with self.subTest(key=key, replacement=replacement), tempfile.TemporaryDirectory() as tmp:
                    directory = Path(tmp) / "handoff"
                    shutil.copytree(ROOT, directory)
                    path = directory / "manifest.json"
                    manifest = json.loads(path.read_text(encoding="utf-8"))
                    if replacement is None:
                        del manifest[key]
                    else:
                        manifest[key] = replacement
                    path.write_text(json.dumps(manifest), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "Checksum mismatch"):
                        verify_package(directory)

    def test_duplicate_order_id_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "orders.csv"
            raw.write_text(
                "order_id,region,units,unit_price_usd\n"
                "O001,North,2,12.50\nO001,South,1,5.00\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "duplicate order ID"):
                make_tidy(raw)

    def test_invalid_quantity_and_price_are_rejected(self) -> None:
        for row in (
            "O001,North,0,3.00",
            "O001,North,-2,3.00",
            "O001,North,2,NaN",
            "O001,North,2,Infinity",
            "O001,North,2,-5.00",
            "O001,North,2,1.999",
            "O001,North,2,nonsense",
        ):
            with self.subTest(row=row), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "orders.csv"
                path.write_text("order_id,region,units,unit_price_usd\n" + row + "\n", encoding="utf-8")
                with self.assertRaises(ValueError):
                    make_tidy(path)

    def test_malformed_headers_and_rows_are_rejected(self) -> None:
        for content in (
            "order_id,units,unit_price_usd\nO001,1,3.00\n",
            "order_id,region,units,unit_price_usd\n",
            "order_id,region,units,unit_price_usd\nO001,North,1,3.00,extra\n",
            "order_id,region,units,unit_price_usd\nO001,North,1\n",
            "order_id,region,units,unit_price_usd\n=IMPORT,North,1,3.00\n",
        ):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "orders.csv"
                path.write_text(content, encoding="utf-8")
                with self.assertRaises(ValueError):
                    make_tidy(path)

    def test_manifest_cannot_redirect_the_validator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "handoff"
            shutil.copytree(ROOT, directory)
            path = directory / "manifest.json"
            manifest = json.loads(path.read_text(encoding="utf-8"))
            manifest["raw"] = "../../some-other-data.csv"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Unexpected synthetic package manifest"):
                verify_package(directory)

    def test_empty_codebook_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "handoff"
            shutil.copytree(ROOT, directory)
            (directory / "CODEBOOK.md").write_text("", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Data dictionary"):
                verify_package(directory)


if __name__ == "__main__":
    unittest.main()
