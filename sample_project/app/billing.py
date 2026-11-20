TAX_RATE = 0.18


def calculate_subtotal(price, quantity):
    if price < 0 or quantity <= 0:
        raise ValueError("Invalid price or quantity")

    return price * quantity


def calculate_tax(amount):
    if amount < 0:
        raise ValueError("Amount cannot be negative")

    return amount * TAX_RATE


def calculate_total(subtotal, discount):
    if subtotal < 0 or discount < 0 or discount > subtotal:
        raise ValueError("Invalid subtotal or discount")

    discounted_amount = subtotal - discount
    tax = calculate_tax(discounted_amount)

    return round(discounted_amount + tax, 2)