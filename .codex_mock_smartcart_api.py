from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse
import json


SESSION = {
    "id": 1,
    "user_id": 1,
    "cart_id": "cart-01",
    "status": "active",
    "started_at": "2026-07-06T15:35:00+05:30",
    "ended_at": None,
}

ITEMS = [
    {
        "id": 1,
        "product_id": 1,
        "product_name": "Amul Butter",
        "quantity": 2,
        "unit_price_snapshot": 58.00,
        "weight_verified": True,
        "added_at": "2026-07-06T15:36:00+05:30",
    },
    {
        "id": 2,
        "product_id": 2,
        "product_name": "Tata Salt",
        "quantity": 1,
        "unit_price_snapshot": 28.00,
        "weight_verified": True,
        "added_at": "2026-07-06T15:37:00+05:30",
    },
    {
        "id": 3,
        "product_id": 3,
        "product_name": "Parle-G Biscuits",
        "quantity": 3,
        "unit_price_snapshot": 10.00,
        "weight_verified": False,
        "added_at": "2026-07-06T15:38:00+05:30",
    },
]


def total():
    return round(sum(item["unit_price_snapshot"] * item["quantity"] for item in ITEMS), 2)


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Device-Key")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(204, {})

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/sessions/active":
            self._send(200, SESSION)
            return
        if path == "/sessions/1":
            self._send(200, {"session_id": 1, "status": "active", "items": ITEMS, "total": total()})
            return
        if path == "/recommendations/for-shopper/1":
            self._send(
                200,
                {
                    "basis": "trending",
                    "items": [
                        {"id": 4, "name": "Mother Dairy Curd", "price": 35.00},
                        {"id": 5, "name": "Britannia Bread", "price": 45.00},
                    ],
                },
            )
            return
        self._send(404, {"detail": "Not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/sessions/start":
            self._send(201, SESSION)
            return
        if path == "/sessions/1/close":
            self._send(
                200,
                {
                    "session_id": 1,
                    "lines": [
                        {
                            "product_name": item["product_name"],
                            "quantity": item["quantity"],
                            "unit_price": item["unit_price_snapshot"],
                            "line_total": round(item["unit_price_snapshot"] * item["quantity"], 2),
                        }
                        for item in ITEMS
                    ],
                    "total": total(),
                    "closed_at": "2026-07-06T15:45:00+05:30",
                },
            )
            return
        self._send(404, {"detail": "Not found"})


if __name__ == "__main__":
    HTTPServer(("localhost", 8000), Handler).serve_forever()
