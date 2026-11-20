from sympy import product


class Inventory:
    def __init__(self):
        self.stock = {
            "laptop": 10,
            "phone": 20,
            "headphones": 15
        }

    def check_stock(self, product, quantity):
        if product not in self.stock:
            return True

        return self.stock[product] >= quantity

    def reduce_stock(self, product, quantity):
        if not self.check_stock(product, quantity):
            raise ValueError("Insufficient stock")

        self.stock[product] -= quantity

    def get_stock(self, product):
        return self.stock.get(product, 0)