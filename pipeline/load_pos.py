"""
POS data loader — reads the Brigade_Bangalore CSV and inserts into the database.
Run this before or after the detection pipeline to enable conversion rate correlation.
"""

from __future__ import annotations

import asyncio
import csv
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


async def load_pos_data():
    """Load POS transactions from CSV into the database."""
    
    csv_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "Dataset",
        "Brigade_Bangalore_10_April_26 (1)bc6219c.csv",
    )
    
    if not os.path.exists(csv_path):
        logger.error(f"POS CSV not found at: {csv_path}")
        return

    # Initialize database
    await init_db()
    db = await get_db()

    try:
        seen_invoices = set()
        inserted = 0

        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            
            for row in reader:
                invoice = row.get("invoice_number", "").strip()
                if not invoice or invoice in seen_invoices:
                    continue
                seen_invoices.add(invoice)

                order_date = row.get("order_date", "").strip()
                order_time = row.get("order_time", "").strip()
                store_id = row.get("store_id", STORE_ID).strip()
                customer = row.get("customer_name", "Guest").strip()
                basket_value = float(row.get("total_amount", 0) or 0)

                # Parse timestamp
                try:
                    dt = datetime.strptime(f"{order_date} {order_time}", "%d-%m-%Y %H:%M:%S")
                    timestamp = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                except Exception:
                    continue

                await db.execute(
                    """INSERT OR IGNORE INTO pos_transactions 
                       (transaction_id, store_id, timestamp, order_date, order_time, 
                        customer_name, basket_value)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (invoice, store_id, timestamp, order_date, order_time, 
                     customer, basket_value),
                )
                inserted += 1

        await db.commit()
        logger.info(f"Loaded {inserted} unique POS transactions for store {STORE_ID}")

        # Verify
        cursor = await db.execute("SELECT COUNT(*) as cnt FROM pos_transactions")
        row = await cursor.fetchone()
        logger.info(f"Total POS records in DB: {row['cnt']}")

    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(load_pos_data())
