"""Pure quotation domain logic. No network calls, AI calls, or side effects.

Supplier adapters and database persistence belong to separate integration layers.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Iterable


@dataclass(frozen=True)
class PriceObservation:
    product_id: str
    supplier_id: str
    observed_at: datetime
    unit_price: Decimal
    currency: str
    available: bool = True
    shipping_cost: Decimal = Decimal("0")
    min_quantity: int = 1
    source_url: str = ""

    def __post_init__(self):
        if not self.product_id or not self.supplier_id:
            raise ValueError("product_id and supplier_id are required")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        try:
            price = Decimal(str(self.unit_price))
            shipping = Decimal(str(self.shipping_cost))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("invalid price") from exc
        if not price.is_finite() or price < 0 or not shipping.is_finite() or shipping < 0:
            raise ValueError("prices must be finite and nonnegative")
        if self.min_quantity < 1:
            raise ValueError("min_quantity must be positive")
        if not self.currency or len(self.currency) != 3 or not self.currency.isalpha():
            raise ValueError("currency must be an ISO 4217 code")
        object.__setattr__(self, "unit_price", price)
        object.__setattr__(self, "shipping_cost", shipping)
        object.__setattr__(self, "currency", self.currency.upper())


def latest_by_supplier(observations: Iterable[PriceObservation], product_id: str):
    """Latest snapshot for each supplier; history is never overwritten."""
    latest = {}
    for item in observations:
        if item.product_id != product_id:
            continue
        previous = latest.get(item.supplier_id)
        if previous is None or item.observed_at > previous.observed_at:
            latest[item.supplier_id] = item
    return latest


def rank_offers(observations: Iterable[PriceObservation], product_id: str,
                currency: str, quantity: int = 1):
    """Rank comparable offers only. No implicit FX or tax assumptions.

    The caller must first verify technical equivalence, tax basis, and freshness.
    Shipping is a fixed charge per order, not per unit.
    """
    if quantity < 1:
        raise ValueError("quantity must be positive")
    current = latest_by_supplier(observations, product_id)
    return sorted(
        (item for item in current.values()
         if item.available and item.currency == currency.upper()
         and quantity >= item.min_quantity),
        key=lambda item: (item.unit_price * quantity + item.shipping_cost,
                          item.supplier_id),
    )


def price_change_percent(old: PriceObservation, new: PriceObservation):
    """Signed percentage change, or None if a zero baseline prevents division."""
    if old.product_id != new.product_id or old.supplier_id != new.supplier_id:
        raise ValueError("observations must refer to the same product and supplier")
    if old.currency != new.currency:
        raise ValueError("currency conversion must occur before comparison")
    if old.unit_price == 0:
        return None
    return (new.unit_price - old.unit_price) * Decimal("100") / old.unit_price


def supplier_history(observations: Iterable[PriceObservation], product_id: str,
                     supplier_id: str):
    return sorted(
        (item for item in observations if item.product_id == product_id
         and item.supplier_id == supplier_id),
        key=lambda item: item.observed_at,
    )
