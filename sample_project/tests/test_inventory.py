import pytest
from sample_project.app.inventory import Inventory
from sample_project.app.inventory import Inventory

def test_check_available_stock():
    inventory = Inventory()
    assert inventory.check_stock("laptop", 2) is True


def test_check_insufficient_stock():
    inventory = Inventory()
    assert inventory.check_stock("laptop", 100) is False


def test_reduce_stock():
    inventory = Inventory()
    inventory.reduce_stock("laptop", 2)
    assert inventory.get_stock("laptop") == 8


def test_reduce_stock_below_zero():
    inventory = Inventory()
    with pytest.raises(ValueError):
        inventory.reduce_stock("laptop", 100)


def test_unknown_product_stock():
    inventory = Inventory()
    assert inventory.get_stock("tablet") == 0
