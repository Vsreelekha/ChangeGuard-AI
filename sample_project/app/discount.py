def calculate_discount(amount, discount_percent):
    if amount < 0:
        raise ValueError("Amount cannot be negative")

    if not 0 <= discount_percent <= 100:
        raise ValueError("Invalid discount percentage")

    return amount * discount_percent / 100