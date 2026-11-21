from datetime import datetime, timezone, timedelta
from decimal import Decimal

import pytest

from src.agent_engine.quotations import (
    PriceObservation, latest_by_supplier, price_change_percent,
    rank_offers, supplier_history,
)


NOW = datetime(2026, 11, 21, tzinfo=timezone.utc)


def offer(supplier, price, *, days=0, shipping="0", currency="EUR",
          available=True, minimum=1):
    return PriceObservation("drill", supplier, NOW + timedelta(days=days),
                            Decimal(price), currency, available,
                            Decimal(shipping), minimum)


def test_latest_observation_is_used_without_discarding_history():
    observations = [offer("A", "100"), offer("A", "90", days=20)]
    assert latest_by_supplier(observations, "drill")["A"].unit_price == 90
    assert len(supplier_history(observations, "drill", "A")) == 2


def test_ranking_includes_shipping_and_excludes_unavailable():
    observations = [offer("A", "80", shipping="30"),
                    offer("B", "95"), offer("C", "60", available=False)]
    assert [x.supplier_id for x in rank_offers(observations, "drill", "EUR")] == ["B", "A"]


def test_currencies_are_not_silently_mixed():
    observations = [offer("A", "50", currency="USD"), offer("B", "80")]
    assert [x.supplier_id for x in rank_offers(observations, "drill", "EUR")] == ["B"]


def test_price_change():
    assert price_change_percent(offer("A", "100"), offer("A", "90", days=20)) == Decimal("-10")
    assert price_change_percent(offer("A", "0"), offer("A", "90")) is None


def test_rejects_naive_timestamp():
    with pytest.raises(ValueError):
        PriceObservation("drill", "A", datetime(2026, 11, 21), Decimal("10"), "EUR")


def test_minimum_order_quantity():
    observations = [offer("A", "10", minimum=5), offer("B", "12")]
    assert [x.supplier_id for x in rank_offers(observations, "drill", "EUR", quantity=1)] == ["B"]
