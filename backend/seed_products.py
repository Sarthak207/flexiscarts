"""
Populates the product catalog via the API instead of hand-editing a JSON
file and importing it through the Firebase console. Run this once against
a running backend:

    python seed_products.py --token <admin_jwt>

Or, get a token first:

    curl -X POST http://localhost:8000/auth/admin/login \\
      -H "Content-Type: application/json" \\
      -d '{"username": "admin", "password": "<your BOOTSTRAP_ADMIN_PASSWORD>"}'

NOTE on detection_label: these must match whatever class labels your
detection model actually outputs (see Milestone 3, Detect_Items rework).
The stock MobileNet-SSD used in the original script only recognizes 20-21
generic COCO/VOC classes -- "bottle" is realistic, "chips_packet" is NOT
a class that model can ever output (this was a real Phase 1 bug: the demo
catalog referenced labels the model could never produce). Update this
list once your actual model/classes are finalized.
"""
import argparse

import requests

DEFAULT_PRODUCTS = [
    {
        "sku": "SC-0001",
        "name": "Water Bottle 1L",
        "price": 20.00,
        "category": "beverages",
        "expected_weight_grams": 1050.0,  # full 1L bottle, approx
        "detection_label": "bottle",
    },
    # Add more products here once your model's actual detectable classes
    # (or barcode data, if that's added later) are known. Left as a short
    # starter list rather than a padded fake catalog.
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--token", required=True, help="Admin JWT from /auth/admin/login")
    args = parser.parse_args()

    headers = {"Authorization": f"Bearer {args.token}"}
    for product in DEFAULT_PRODUCTS:
        resp = requests.post(f"{args.base_url}/products", json=product, headers=headers)
        if resp.status_code == 201:
            print(f"Created product: {product['sku']} ({product['name']})")
        elif resp.status_code == 409:
            print(f"Already exists, skipping: {product['sku']}")
        else:
            print(f"Failed ({resp.status_code}) for {product['sku']}: {resp.text}")


if __name__ == "__main__":
    main()
