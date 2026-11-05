"""
Tests for restocking order API endpoints.
"""
from datetime import datetime, timedelta

import pytest


# Forecast data used below (server/data/demand_forecasts.json):
#   FLT-405: unit_cost 9.80,  lead_time_days 5
#   WDG-001: unit_cost 42.50, lead_time_days 14
#   MTR-304: unit_cost 310.0, lead_time_days 21
def make_payload(items=None, budget=10000):
    """Build a restocking order request body."""
    if items is None:
        items = [{"item_sku": "FLT-405", "quantity": 100}]
    return {"items": items, "budget": budget}


class TestRestockingEndpoints:
    """Test suite for restocking order endpoints."""

    def test_get_restocking_orders_empty(self, client):
        """Test that no restocking orders exist before any are submitted."""
        response = client.get("/api/restocking-orders")
        assert response.status_code == 200
        assert response.json() == []

    def test_create_restocking_order(self, client):
        """Test submitting a restocking order returns the created order."""
        response = client.post("/api/restocking-orders", json=make_payload())
        assert response.status_code == 201

        order = response.json()
        assert "id" in order
        assert order["order_number"].startswith("RST-")
        assert order["status"].lower() == "submitted"
        assert order["budget"] == 10000
        assert "submitted_date" in order
        assert "expected_delivery" in order
        assert "T" in order["submitted_date"]  # ISO format with time component

    def test_restocking_order_line_structure(self, client):
        """Test that order lines carry the looked-up item details."""
        response = client.post("/api/restocking-orders", json=make_payload())
        order = response.json()

        assert len(order["items"]) == 1
        line = order["items"][0]
        assert line["item_sku"] == "FLT-405"
        assert line["item_name"] == "Oil Filter Cartridge"
        assert line["quantity"] == 100
        assert isinstance(line["unit_cost"], (int, float))
        assert isinstance(line["lead_time_days"], int)
        assert line["supplier_name"]

    def test_restocking_order_total_calculation(self, client):
        """Test that total_value is the sum of quantity * unit cost per line."""
        payload = make_payload([
            {"item_sku": "FLT-405", "quantity": 100},  # 100 * 9.80 = 980.00
            {"item_sku": "WDG-001", "quantity": 10},   # 10 * 42.50 = 425.00
        ])
        order = client.post("/api/restocking-orders", json=payload).json()

        assert abs(order["total_value"] - 1405.00) < 0.01
        for line in order["items"]:
            assert abs(line["line_total"] - line["quantity"] * line["unit_cost"]) < 0.01

    def test_restocking_order_lead_time_is_max_of_lines(self, client):
        """Test that the order lead time is the slowest item's lead time."""
        payload = make_payload([
            {"item_sku": "FLT-405", "quantity": 10},  # 5 days
            {"item_sku": "WDG-001", "quantity": 10},  # 14 days
        ])
        order = client.post("/api/restocking-orders", json=payload).json()

        assert order["lead_time_days"] == 14

    def test_restocking_order_expected_delivery(self, client):
        """Test that expected delivery is submitted date plus lead time."""
        order = client.post("/api/restocking-orders", json=make_payload()).json()

        submitted = datetime.fromisoformat(order["submitted_date"])
        expected = datetime.fromisoformat(order["expected_delivery"])
        assert expected - submitted == timedelta(days=order["lead_time_days"])

    def test_restocking_order_ignores_client_prices(self, client):
        """Test that prices come from the server, not from the request."""
        payload = make_payload([
            {"item_sku": "FLT-405", "quantity": 10, "unit_cost": 0.01}
        ])
        order = client.post("/api/restocking-orders", json=payload).json()

        assert abs(order["items"][0]["unit_cost"] - 9.80) < 0.01

    def test_get_restocking_orders_returns_submitted_order(self, client):
        """Test that a submitted order is returned by the list endpoint."""
        created = client.post("/api/restocking-orders", json=make_payload()).json()

        response = client.get("/api/restocking-orders")
        assert response.status_code == 200

        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == created["id"]
        assert data[0]["order_number"] == created["order_number"]

    def test_get_restocking_orders_newest_first(self, client):
        """Test that the most recently submitted order is listed first."""
        first = client.post("/api/restocking-orders", json=make_payload()).json()
        second = client.post("/api/restocking-orders", json=make_payload()).json()

        data = client.get("/api/restocking-orders").json()
        assert [o["id"] for o in data] == [second["id"], first["id"]]
        assert first["order_number"] != second["order_number"]

    def test_restocking_order_over_budget(self, client):
        """Test that an order exceeding the budget is rejected."""
        # 100 * 9.80 = 980 > 500
        response = client.post("/api/restocking-orders", json=make_payload(budget=500))
        assert response.status_code == 400

        data = response.json()
        assert "detail" in data
        assert "exceeds budget" in data["detail"].lower()

    def test_restocking_order_over_budget_not_stored(self, client):
        """Test that a rejected order is not added to the list."""
        client.post("/api/restocking-orders", json=make_payload(budget=500))

        assert client.get("/api/restocking-orders").json() == []

    def test_restocking_order_exactly_on_budget(self, client):
        """Test that an order equal to the budget is accepted."""
        # 100 * 9.80 = 980
        response = client.post("/api/restocking-orders", json=make_payload(budget=980))
        assert response.status_code == 201

    def test_restocking_order_unknown_sku(self, client):
        """Test that an unknown SKU is rejected."""
        payload = make_payload([{"item_sku": "NOPE-999", "quantity": 1}])
        response = client.post("/api/restocking-orders", json=payload)
        assert response.status_code == 400

        data = response.json()
        assert "detail" in data
        assert "unknown" in data["detail"].lower()

    def test_restocking_order_duplicate_sku(self, client):
        """Test that the same SKU twice in one order is rejected."""
        payload = make_payload([
            {"item_sku": "FLT-405", "quantity": 1},
            {"item_sku": "FLT-405", "quantity": 2},
        ])
        response = client.post("/api/restocking-orders", json=payload)
        assert response.status_code == 400
        assert "duplicate" in response.json()["detail"].lower()

    def test_restocking_order_empty_items(self, client):
        """Test that an order with no items fails validation."""
        response = client.post("/api/restocking-orders", json=make_payload(items=[]))
        assert response.status_code == 422

    def test_restocking_order_zero_quantity(self, client):
        """Test that a zero quantity fails validation."""
        payload = make_payload([{"item_sku": "FLT-405", "quantity": 0}])
        response = client.post("/api/restocking-orders", json=payload)
        assert response.status_code == 422

    def test_restocking_order_negative_budget(self, client):
        """Test that a negative budget fails validation."""
        response = client.post("/api/restocking-orders", json=make_payload(budget=-1))
        assert response.status_code == 422

    def test_restocking_order_infinite_budget_rejected(self, client):
        """Test that a non-finite budget is rejected instead of bypassing the budget check."""
        # Raw body: Python's json.loads accepts the bare literal Infinity, so a
        # client can send it even though it is not valid JSON.
        response = client.post(
            "/api/restocking-orders",
            content='{"items": [{"item_sku": "FLT-405", "quantity": 1}], "budget": Infinity}',
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422

    def test_restocking_order_infinite_budget_does_not_poison_list(self, client):
        """Test that a rejected non-finite budget leaves the order list readable."""
        client.post(
            "/api/restocking-orders",
            content='{"items": [{"item_sku": "FLT-405", "quantity": 1}], "budget": Infinity}',
            headers={"Content-Type": "application/json"},
        )

        response = client.get("/api/restocking-orders")
        assert response.status_code == 200
        assert response.json() == []

    def test_restocking_order_quantity_upper_bound(self, client):
        """Test that an absurdly large quantity fails validation."""
        payload = make_payload([{"item_sku": "FLT-405", "quantity": 10**9}], budget=10**9)
        response = client.post("/api/restocking-orders", json=payload)
        assert response.status_code == 422

    def test_restocking_order_budget_upper_bound(self, client):
        """Test that an absurdly large budget fails validation."""
        response = client.post("/api/restocking-orders", json=make_payload(budget=1e15))
        assert response.status_code == 422

    def test_restocking_order_ids_unique_under_concurrency(self):
        """Test that concurrent submissions never share an id or order number."""
        from concurrent.futures import ThreadPoolExecutor

        from main import CreateRestockingOrderRequest, create_restocking_order

        def submit(_):
            request = CreateRestockingOrderRequest(
                items=[{"item_sku": "FLT-405", "quantity": 1}], budget=1000
            )
            return create_restocking_order(request)

        with ThreadPoolExecutor(max_workers=16) as pool:
            created = list(pool.map(submit, range(200)))

        assert len({o["id"] for o in created}) == 200
        assert len({o["order_number"] for o in created}) == 200

    def test_restocking_order_does_not_change_orders(self, client):
        """Test that restocking orders stay out of the main orders list."""
        before = len(client.get("/api/orders").json())

        client.post("/api/restocking-orders", json=make_payload())

        after = len(client.get("/api/orders").json())
        assert after == before
