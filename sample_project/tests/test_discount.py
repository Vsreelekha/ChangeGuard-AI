import pytest
from sample_project.app.discount import calculate_discount
from sample_project.app.discount import calculate_discount

def test_calculate_10_percent_discount():
    assert calculate_discount(1000, 10) == 100


def test_zero_discount():
    assert calculate_discount(1000, 0) == 0


def test_full_discount():
    assert calculate_discount(1000, 100) == 1000


def test_invalid_discount():
    with pytest.raises(ValueError):
        calculate_discount(1000, 120)


def test_negative_amount():
    with pytest.raises(ValueError):
        calculate_discount(-100, 10)
