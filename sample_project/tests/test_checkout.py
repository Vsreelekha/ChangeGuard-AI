import pytest
from sample_project.app.inventory import Inventory
from sample_project.app.checkout import checkout


def test_successful_checkout():
    inventory = Inventory()

    result = checkout(inventory, "laptop", 1000, 2)

    assert result["subtotal"] == 2000
    assert result["discount"] == 0
    assert result["total"] == 2360
    assert inventory.get_stock("laptop") == 8


def test_checkout_with_discount():
    inventory = Inventory()

    result = checkout(inventory, "phone", 1000, 1, 10)

    assert result["discount"] == 100
    assert result["total"] == 1062


def test_checkout_insufficient_stock():
    inventory = Inventory()

    with pytest.raises(ValueError):
        checkout(inventory, "laptop", 1000, 100)

    assert inventory.get_stock("laptop") == 10


def test_checkout_invalid_quantity():
    inventory = Inventory()

    with pytest.raises(ValueError):
        checkout(inventory, "laptop", 1000, 0)
def test_checkout_deducts_stock_only_once():
    inventory = Inventory()

    checkout(inventory, "laptop", 1000, 2)

    assert inventory.get_stock("laptop") == 8
def test_checkout_rejects_insufficient_stock():
    inventory = Inventory()

    with pytest.raises(ValueError, match="Insufficient stock"):
        checkout(inventory, "laptop", 1000, 100)

    assert inventory.get_stock("laptop") == 10
class InventoryWithoutStockProtection:
    def __init__(self):
        self.stock = 10

    def check_stock(self, product, quantity):
        return quantity <= self.stock

    def reduce_stock(self, product, quantity):
        self.stock -= quantity

    def get_stock(self, product):
        return self.stock


def test_checkout_rejects_insufficient_stock_at_checkout_level():
    inventory = InventoryWithoutStockProtection()

    with pytest.raises(ValueError, match="Insufficient stock"):
        checkout(inventory, "laptop", 1000, 100)

    assert inventory.get_stock("laptop") == 10
