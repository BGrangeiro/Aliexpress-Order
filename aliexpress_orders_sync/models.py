from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class Order:
    """Normalized AliExpress order data used by the spreadsheet sync layer."""

    order_id: str
    order_date: date | None
    item_description: str
    quantity: int
    total_value: Decimal | None
    currency: str
    responsible: str
    delivery_status: str
    tracking_number: str
    payment_method: str = ""
