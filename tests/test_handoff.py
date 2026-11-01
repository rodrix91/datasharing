"""Regression tests for the independent synthetic research data handoff."""

from __future__ import annotations

from decimal import getcontext
import hashlib
import json
import shutil
import subprocess
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

    def test_noncanonical_tidy_newlines_fail_even_with_matching_manifest_hash(self) -> None:
        # Universal-newline text reads turn CRLF and CR into LF, which used to
        # mask a noncanonical CSV when its digest was updated in the manifest.
        for ending in (b"\r\n", b"\r"):
            with self.subTest(ending=repr(ending)), tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp) / "handoff"
                shutil.copytree(ROOT, directory)
                tidy = directory / "tidy" / "orders.csv"
                canonical = tidy.read_bytes()
                self.assertIn(b"\n", canonical)
                self.assertNotIn(b"\r", canonical)
                altered = canonical.replace(b"\n", ending)
                tidy.write_bytes(altered)
                self.assertNotEqual(altered, canonical)
                self.assertEqual(
                    tidy.read_text(encoding="utf-8"),
                    canonical.decode("utf-8"),
                    "Text-mode verification would silently normalize line endings",
                )
                path = directory / "manifest.json"
                manifest = json.loads(path.read_text(encoding="utf-8"))
                manifest["tidy_sha256"] = hashlib.sha256(altered).hexdigest()
                path.write_text(json.dumps(manifest), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "Tidy data does not reproduce"):
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

    def test_symlinked_deliverables_and_data_folders_are_rejected(self) -> None:
        # Identical external bytes can satisfy all four checksums, but cannot
        # be handed to a recipient as a self-contained package.
        for relative in (
            "raw", "tidy", "raw/orders.csv", "tidy/orders.csv",
            "CODEBOOK.md", "transform.py",
        ):
            with self.subTest(path=relative), tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp) / "handoff"
                shutil.copytree(ROOT, directory)
                self.assertEqual(verify_package(directory), 3)
                target = directory / relative
                outside = Path(tmp) / "external"
                if target.is_dir():
                    shutil.copytree(target, outside)
                    shutil.rmtree(target)
                else:
                    shutil.copyfile(target, outside)
                    target.unlink()
                try:
                    target.symlink_to(outside, target_is_directory=outside.is_dir())
                except (OSError, NotImplementedError) as error:
                    self.skipTest(f"symbolic links unavailable on this runner: {error}")
                with self.assertRaisesRegex(ValueError, "Symbolic link in synthetic package"):
                    verify_package(directory)

    def test_manifest_symlink_is_rejected_before_reading_external_metadata(self) -> None:
        # The manifest itself must not be redirected outside the handoff,
        # even when that external manifest contains the correct checksums.
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "handoff"
            shutil.copytree(ROOT, directory)
            original = directory / "manifest.json"
            outside = Path(tmp) / "external-manifest.json"
            shutil.copyfile(original, outside)
            original.unlink()
            try:
                original.symlink_to(outside)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"symbolic links unavailable on this runner: {error}")
            with self.assertRaisesRegex(
                ValueError, r"Symbolic link in synthetic package: manifest\.json"
            ):
                verify_package(directory)

    def test_package_root_symlink_is_rejected_even_with_valid_contents(self) -> None:
        # A shortcut to another directory is not a self-contained package
        # delivered at the requested path.
        with tempfile.TemporaryDirectory() as tmp:
            original = Path(tmp) / "real-handoff"
            alias = Path(tmp) / "handoff-link"
            shutil.copytree(ROOT, original)
            self.assertEqual(verify_package(original), 3)
            try:
                alias.symlink_to(original, target_is_directory=True)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"directory symlinks unavailable on this runner: {error}")
            with self.assertRaisesRegex(
                ValueError, r"Symbolic link in synthetic package: \."
            ):
                verify_package(alias)

    def test_modified_recipe_cannot_run_before_checksum_rejection(self) -> None:
        # Reproduce the actual standalone entrypoint from a separate package
        # directory, rather than relying on a cached imported Python module.
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "handoff"
            shutil.copytree(ROOT, directory)
            recipe = directory / "transform.py"
            marker = directory / "untrusted_recipe_executed.txt"
            recipe.write_text(
                'from pathlib import Path\n'
                'Path(__file__).with_name("untrusted_recipe_executed.txt").write_text('
                '"unexpected execution", encoding="utf-8")\n',
                encoding="utf-8",
            )
            completed = subprocess.run(
                [sys.executable, str(directory / "verify.py")],
                cwd=directory,
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("Checksum mismatch for transform.py", completed.stderr)
            self.assertFalse(marker.exists(), "A modified recipe executed before verification")

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
            "O001,North,2,-0.00",
            "O001,North,2,-0",
            "O001,North,2,1.999",
            "O001,North,2,nonsense",
        ):
            with self.subTest(row=row), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "orders.csv"
                path.write_text("order_id,region,units,unit_price_usd\n" + row + "\n", encoding="utf-8")
                with self.assertRaises(ValueError):
                    make_tidy(path)

    def test_price_must_use_plain_fixed_point_notation(self) -> None:
        # Decimal() accepts signed and exponential representations that
        # violate the codebook's fixed-point monetary input contract.
        invalid = (
            "1e2",
            "1E+2",
            "1e999999999",
            "0e0",
            "+2.00",
            ".50",
            "2.",
            "2.00e0",
            " 2.00",
            "2.00 ",
        )
        for price in invalid:
            with self.subTest(price=price), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "orders.csv"
                path.write_text(
                    "order_id,region,units,unit_price_usd\n"
                    f"O001,North,2,{price}\n",
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(ValueError, "Invalid quantity or price"):
                    make_tidy(path)

    def test_plain_fixed_point_prices_keep_exact_canonical_cents(self) -> None:
        for price, canonical, revenue in (
            ("0", "0.00", "0.00"),
            ("0.01", "0.01", "0.02"),
            ("12", "12.00", "24.00"),
            ("12.5", "12.50", "25.00"),
            ("12.50", "12.50", "25.00"),
        ):
            with self.subTest(price=price), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "orders.csv"
                path.write_text(
                    "order_id,region,units,unit_price_usd\n"
                    f"O001,North,2,{price}\n",
                    encoding="utf-8",
                )
                self.assertEqual(
                    make_tidy(path).splitlines()[1],
                    f"O001,North,2,{canonical},{revenue}",
                )

    def test_large_revenue_is_exact_to_the_cent_without_global_context_change(self) -> None:
        # Decimal multiplication uses only 28 significant digits by default.
        # These invoices must not silently gain or lose cents when the
        # coefficient or quantity exceeds that precision.
        cases = (
            (
                "1.25",
                "1234567890123456789012345678",
                "1543209862654320986265432097.50",
            ),
            (
                "123456789012345678901234567.89",
                "9",
                "1111111101111111110111111111.01",
            ),
            (
                "0.01",
                "1234567890123456789012345678",
                "12345678901234567890123456.78",
            ),
        )
        initial_precision = getcontext().prec
        for price, units, revenue in cases:
            with self.subTest(price=price, units=units), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "orders.csv"
                path.write_text(
                    "order_id,region,units,unit_price_usd\n"
                    f"O001,North,{units},{price}\n",
                    encoding="utf-8",
                )
                actual = make_tidy(path).splitlines()[1].split(",")
                self.assertEqual(
                    actual,
                    ["O001", "North", units, price, revenue],
                )
                self.assertEqual(getcontext().prec, initial_precision)

    def test_excel_utf8_bom_header_is_accepted_without_rewriting_raw(self) -> None:
        # Excel can prefix a UTF-8 CSV with a BOM. It is an encoding
        # signature, not part of the first column name.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "orders.csv"
            original = (
                "order_id,region,units,unit_price_usd\n"
                "O001,North,2,12.50\n"
                "O002,South,1,5.00\n"
            ).encode("utf-8-sig")
            path.write_bytes(original)
            actual = make_tidy(path)
            self.assertEqual(
                actual,
                "order_id,region,units,unit_price_usd,revenue_usd\n"
                "O001,North,2,12.50,25.00\n"
                "O002,South,1,5.00,5.00\n",
            )
            self.assertEqual(path.read_bytes(), original)

    def test_bom_elsewhere_in_header_is_not_silently_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "orders.csv"
            path.write_text(
                "order_id,\ufeffregion,units,unit_price_usd\n"
                "O001,North,2,12.50\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "Expected raw headers"):
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


    def test_broken_quoted_order_fields_are_rejected(self) -> None:
        header = "order_id,region,units,unit_price_usd\n"
        for record in (
            'O001,"North"junk,2,12.50\n',
            'O001,"North,2,12.50\n',
            'O001,"North\nstill unclosed,2,12.50\n',
        ):
            with self.subTest(record=record), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "orders.csv"
                path.write_bytes((header + record).encode("utf-8"))
                with self.assertRaisesRegex(ValueError, "Malformed CSV near source line"):
                    make_tidy(path)

    def test_blank_raw_records_are_not_silently_dropped(self) -> None:
        header = "order_id,region,units,unit_price_usd\n"
        first = "O001,North,2,12.50\n"
        second = "O002,South,1,5.00\n"
        for label, body, diagnostic in (
            ("before data", "\n" + first, "Blank CSV row before source line 3"),
            ("between data", first + "\n" + second, "Blank CSV row before source line 4"),
            ("after data", first + "\n", "Blank CSV row at source line 3"),
        ):
            for eol in ("\n", "\r\n"):
                with self.subTest(case=label, eol=repr(eol)), tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / "orders.csv"
                    path.write_bytes((header + body).replace("\n", eol).encode("utf-8"))
                    with self.assertRaisesRegex(ValueError, diagnostic):
                        make_tidy(path)

    def test_blank_before_multiline_record_cannot_hide_source_defect(self) -> None:
        header = "order_id,region,units,unit_price_usd\n"
        first = "O001,North,2,12.50\n"
        quoted = 'O002,"North\nSouth",1,5.00\n'
        for eol in ("\n", "\r\n", "\r"):
            with self.subTest(eol=repr(eol)), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "orders.csv"
                # Source line 3 is blank; the quoted value begins on line 4
                # and ends on line 5. DictReader.line_num alone reports 5.
                source = header + first + "\n" + quoted
                path.write_bytes(source.replace("\n", eol).encode("utf-8"))
                with self.assertRaisesRegex(ValueError, "Blank CSV row before source line 4"):
                    make_tidy(path)

    def test_multiline_without_blank_keeps_physical_error_location(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "orders.csv"
            path.write_bytes(
                b"order_id,region,units,unit_price_usd\r\n"
                b'O001,"North\r\nSouth",1,5.00\r\n'
            )
            with self.assertRaisesRegex(ValueError, "Invalid region on line 3"):
                make_tidy(path)

    def test_normal_quoted_fields_do_not_trigger_blank_record_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "orders.csv"
            path.write_text(
                'order_id,region,units,unit_price_usd\n'
                'O001,"North East",2,12.50\n',
                encoding="utf-8",
            )
            self.assertIn("O001,North East,2,12.50,25.00", make_tidy(path))

    def test_invalid_region_error_uses_physical_line_after_quoted_newline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "orders.csv"
            path.write_bytes(
                b"order_id,region,units,unit_price_usd\r\n"
                b"O001,North,2,12.50\r\n"
                b'O002,"North\r\nSouth",1,5.00\r\n'
            )
            with self.assertRaisesRegex(ValueError, "Invalid region on line 4"):
                make_tidy(path)

    def test_strict_csv_recipe_remains_checksum_verified(self) -> None:
        manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
        actual = hashlib.sha256((ROOT / "transform.py").read_bytes()).hexdigest()
        self.assertEqual(manifest["recipe_sha256"], actual)
        self.assertEqual(verify_package(ROOT), 3)



if __name__ == "__main__":
    unittest.main()
