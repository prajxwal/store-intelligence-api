"""
POS data loader — reads the sample POS CSV and inserts into the database.
Handles per-item rows (order_id, product_id, brand_name, total_amount).
Run before or after the detection pipeline to enable conversion rate correlation.
"""

from __future__ import annotations

import asyncio
import csv
import glob
import logging
import os
import sys
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.database import init_db, get_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("pos_loader")

STORE_ID = "ST1008"


def find_pos_csv() -> str | None:
    """Find the POS CSV file in the project directory."""
    project_root = os.path.dirname(os.path.dirname(__file__))

    # Check multiple possible locations and name patterns
    patterns = [
        os.path.join(project_root, "POS*sample*transactions*.csv"),
        os.path.join(project_root, "POS*.csv"),
        os.path.join(project_root, "Dataset", "Brigade_Bangalore*.csv"),
        os.path.join(project_root, "Dataset", "POS*.csv"),
        os.path.join(project_root, "*.csv"),
    ]

    for pattern in patterns:
        matches = glob.glob(pattern)
        for m in matches:
            if "sample" in m.lower() or "pos" in m.lower() or "brigade" in m.lower():
                return m

    return None


async def load_pos_data():
    """Load POS transactions from CSV into the database."""

    csv_path = find_pos_csv()

    if not csv_path:
        logger.error("No POS CSV found. Place it in the project root or Dataset/ directory.")
        return

    logger.info(f"Loading POS data from: {csv_path}")

    # Initialize database
    await init_db()
    db = await get_db()

    try:
        inserted = 0

        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            logger.info(f"CSV columns: {fieldnames}")

            for row in reader:
                # Flexible column reading — handle both old and new format
                order_id = (
                    row.get("order_id", "")
                    or row.get("invoice_number", "")
                ).strip()

                order_date = row.get("order_date", "").strip()
                order_time = row.get("order_time", "").strip()
                store_id = row.get("store_id", STORE_ID).strip()
                product_id = row.get("product_id", "").strip()
                brand_name = row.get("brand_name", "").strip()
                total_amount = float(row.get("total_amount", 0) or 0)
                customer_name = row.get("customer_name", "").strip()

                # Parse timestamp
                try:
                    if order_date and order_time:
                        dt = datetime.strptime(f"{order_date} {order_time}", "%d-%m-%Y %H:%M:%S")
                        timestamp = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                    else:
                        continue
                except Exception:
                    continue

                await db.execute(
                    """INSERT INTO pos_transactions
                       (order_id, store_id, timestamp, order_date, order_time,
                        product_id, brand_name, total_amount, customer_name)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (order_id, store_id, timestamp, order_date, order_time,
                     product_id, brand_name, total_amount, customer_name),
                )
                inserted += 1

        await db.commit()

        # Count unique transactions (by distinct order_time)
        cursor = await db.execute(
            "SELECT COUNT(DISTINCT order_time) as cnt FROM pos_transactions WHERE store_id = ?",
            (STORE_ID,),
        )
        row = await cursor.fetchone()
        unique_orders = row["cnt"] if row else 0

        # Count unique brands
        cursor = await db.execute(
            "SELECT COUNT(DISTINCT brand_name) as cnt FROM pos_transactions WHERE store_id = ? AND brand_name != ''",
            (STORE_ID,),
        )
        row = await cursor.fetchone()
        unique_brands = row["cnt"] if row else 0

        logger.info(f"Loaded {inserted} item rows for store {STORE_ID}")
        logger.info(f"Unique transactions (by order_time): {unique_orders}")
        logger.info(f"Unique brands: {unique_brands}")

    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(load_pos_data())
