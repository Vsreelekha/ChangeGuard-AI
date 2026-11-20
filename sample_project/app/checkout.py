from sample_project.app.billing import calculate_subtotal, calculate_total
from sample_project.app.discount import calculate_discount

def checkout(inventory, product, price, quantity, discount_percent=0):
    if price < 0 or quantity <= 0:
        raise ValueError("Invalid price or quantity")

    if not inventory.check_stock(product, quantity):
        raise ValueError("Insufficient stock")

    subtotal = calculate_subtotal(price, quantity)
    discount = calculate_discount(subtotal, discount_percent)
    total = calculate_total(subtotal, discount)

    inventory.reduce_stock(product, quantity)

    return {
        "product": product,
        "quantity": quantity,
        "subtotal": round(subtotal, 2),
        "discount": round(discount, 2),
        "total": total
    }
