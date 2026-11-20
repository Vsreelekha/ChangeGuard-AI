import pytest
from sample_project.app.billing import (
    calculate_subtotal,
    calculate_tax,
    calculate_total
)
from sample_project.app.billing import (
    calculate_subtotal,
    calculate_tax,
    calculate_total
)


def test_calculate_subtotal():
    assert calculate_subtotal(100, 2) == 200


def test_calculate_tax():
    assert calculate_tax(100) == 18


def test_calculate_total_without_discount():
    assert calculate_total(1000, 0) == 1180


def test_calculate_total_with_discount():
    assert calculate_total(1000, 100) == 1062


def test_invalid_subtotal():
    with pytest.raises(ValueError):
        calculate_subtotal(-100, 2)
