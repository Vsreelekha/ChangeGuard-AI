# ChangeGuard AI - Sample Checkout Application

## Overview
A Python checkout and billing application used to evaluate
ChangeGuard AI's code impact analysis and regression test selection.

## Modules
- app/checkout.py: Checkout workflow
- app/billing.py: Subtotal, tax and total calculations
- app/discount.py: Discount calculations
- app/inventory.py: Stock validation and updates

## Tests
- tests/test_checkout.py
- tests/test_billing.py
- tests/test_discount.py
- tests/test_inventory.py

## Setup
Install dependencies:

    python -m pip install -r sample_project/requirements.txt

## Run tests
From the repository root:

    python -m pytest sample_project/tests -v

## Baseline
The correct application currently passes all 19 tests.