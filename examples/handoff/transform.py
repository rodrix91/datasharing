"""Deterministic raw-to-tidy transform for synthetic order data only."""

from __future__ import annotations

import csv
import io
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

RAW_COLUMNS = ["order_id", "region", "units", "unit_price_usd"]
TIDY_COLUMNS = [*RAW_COLUMNS, "revenue_usd"]


def make_tidy(raw_path: Path) -> str:
    """Return canonical, line-feed-delimited tidy CSV without changing the raw file."""
    with raw_path.open("r", encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != RAW_COLUMNS:
            raise ValueError(f"Expected raw headers {RAW_COLUMNS!r}")
        result = io.StringIO(newline="")
        writer = csv.writer(result, lineterminator="\n")
        writer.writerow(TIDY_COLUMNS)
        seen: set[str] = set()
        count = 0
        for line, row in enumerate(reader, start=2):
            order_id = row.get("order_id") or ""
            region = row.get("region") or ""
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"Malformed CSV row {line}")
            if not re.fullmatch(r"[A-Za-z0-9_-]+", order_id) or order_id in seen:
                raise ValueError(f"Invalid or duplicate order ID on line {line}")
            if not re.fullmatch(r"[A-Za-z ]+", region) or not region.strip():
                raise ValueError(f"Invalid region on line {line}")
            try:
                units_text = row["units"]
                if not re.fullmatch(r"[1-9][0-9]*", units_text):
                    raise ValueError("Units must be a positive integer")
                units = int(units_text)
                price = Decimal(row["unit_price_usd"])
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise ValueError(f"Invalid quantity or price on line {line}") from exc
            if not price.is_finite() or price < 0 or price.as_tuple().exponent < -2:
                raise ValueError(f"Price must be nonnegative with at most 2 decimals (line {line})")
            revenue = price * units
            writer.writerow([order_id, region, str(units), f"{price:.2f}", f"{revenue:.2f}"])
            seen.add(order_id)
            count += 1
        if count == 0:
            raise ValueError("Raw dataset must contain at least one row")
        return result.getvalue()


if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    print(make_tidy(here / "raw" / "orders.csv"), end="")
