"""
Tests for the /api/tasks and /api/purchase-orders endpoints.
"""
import pytest


@pytest.fixture
def backlog_item_id(client):
    """A valid backlog item id to attach purchase orders to."""
    response = client.get("/api/backlog")
    return response.json()[0]["id"]


def po_payload(backlog_item_id, **overrides):
    payload = {
        "backlog_item_id": backlog_item_id,
        "supplier_name": "Acme Components",
        "quantity": 100,
        "unit_cost": 12.5,
        "expected_delivery_date": "2025-12-01",
        "notes": "Rush order",
    }
    payload.update(overrides)
    return payload


class TestTasksEndpoints:
    """Test suite for task endpoints."""

    def test_get_tasks_initially_empty(self, client):
        """Test that no API tasks exist before any are created."""
        response = client.get("/api/tasks")
        assert response.status_code == 200
        assert response.json() == []

    def test_create_task(self, client):
        """Test creating a task returns 201 with the client-facing shape."""
        response = client.post(
            "/api/tasks",
            json={"title": "  Review stock  ", "priority": "high", "dueDate": "2025-10-08"},
        )
        assert response.status_code == 201

        task = response.json()
        assert task["title"] == "Review stock"  # whitespace trimmed
        assert task["priority"] == "high"
        assert task["dueDate"] == "2025-10-08"
        assert task["status"] == "pending"
        assert isinstance(task["id"], int)
        # API ids stay above the client's built-in mock task ids (1..n)
        assert task["id"] >= 1000

    def test_get_tasks_newest_first(self, client):
        """Test that tasks are returned newest first."""
        client.post("/api/tasks", json={"title": "first", "dueDate": "2025-10-01"})
        client.post("/api/tasks", json={"title": "second", "dueDate": "2025-10-02"})

        titles = [t["title"] for t in client.get("/api/tasks").json()]
        assert titles == ["second", "first"]

    def test_create_task_default_priority(self, client):
        """Test that priority defaults to medium."""
        response = client.post("/api/tasks", json={"title": "x", "dueDate": "2025-10-01"})
        assert response.status_code == 201
        assert response.json()["priority"] == "medium"

    def test_create_task_invalid_priority(self, client):
        """Test that an unknown priority is rejected."""
        response = client.post(
            "/api/tasks", json={"title": "x", "priority": "urgent", "dueDate": "2025-10-01"}
        )
        assert response.status_code == 400

    def test_create_task_invalid_due_date(self, client):
        """Test that a malformed due date is rejected."""
        response = client.post("/api/tasks", json={"title": "x", "dueDate": "10/01/2025"})
        assert response.status_code == 400

    def test_create_task_empty_title(self, client):
        """Test that an empty title fails validation."""
        response = client.post("/api/tasks", json={"title": "", "dueDate": "2025-10-01"})
        assert response.status_code == 422

    def test_toggle_task(self, client):
        """Test toggling a task back and forth between pending and completed."""
        task_id = client.post("/api/tasks", json={"title": "x", "dueDate": "2025-10-01"}).json()["id"]

        response = client.patch(f"/api/tasks/{task_id}")
        assert response.status_code == 200
        assert response.json()["status"] == "completed"

        response = client.patch(f"/api/tasks/{task_id}")
        assert response.json()["status"] == "pending"

    def test_toggle_nonexistent_task(self, client):
        """Test toggling a task that doesn't exist."""
        response = client.patch("/api/tasks/999999")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_delete_task(self, client):
        """Test deleting a task removes it from the list."""
        task_id = client.post("/api/tasks", json={"title": "x", "dueDate": "2025-10-01"}).json()["id"]

        response = client.delete(f"/api/tasks/{task_id}")
        assert response.status_code == 200
        assert client.get("/api/tasks").json() == []

    def test_delete_nonexistent_task(self, client):
        """Test deleting a task that doesn't exist."""
        response = client.delete("/api/tasks/999999")
        assert response.status_code == 404

    def test_task_ids_not_reused_after_delete(self, client):
        """Test that a new task never gets the id of a surviving task after a delete."""
        first = client.post("/api/tasks", json={"title": "a", "dueDate": "2025-10-01"}).json()
        second = client.post("/api/tasks", json={"title": "b", "dueDate": "2025-10-01"}).json()
        client.delete(f"/api/tasks/{first['id']}")
        third = client.post("/api/tasks", json={"title": "c", "dueDate": "2025-10-01"}).json()

        assert third["id"] != second["id"]


class TestPurchaseOrderEndpoints:
    """Test suite for purchase order endpoints."""

    def test_create_purchase_order(self, client, backlog_item_id):
        """Test creating a purchase order for a backlog item."""
        response = client.post("/api/purchase-orders", json=po_payload(backlog_item_id))
        assert response.status_code == 201

        po = response.json()
        assert po["id"].startswith("PO-")
        assert po["backlog_item_id"] == backlog_item_id
        assert po["supplier_name"] == "Acme Components"
        assert po["quantity"] == 100
        assert po["unit_cost"] == 12.5
        assert po["status"] == "pending"
        assert po["notes"] == "Rush order"
        assert "created_date" in po

    def test_get_purchase_order_by_backlog_item(self, client, backlog_item_id):
        """Test fetching the purchase order linked to a backlog item."""
        created = client.post("/api/purchase-orders", json=po_payload(backlog_item_id)).json()

        response = client.get(f"/api/purchase-orders/{backlog_item_id}")
        assert response.status_code == 200
        assert response.json()["id"] == created["id"]

    def test_get_nonexistent_purchase_order(self, client):
        """Test fetching a purchase order for a backlog item without one."""
        response = client.get("/api/purchase-orders/nonexistent-999")
        assert response.status_code == 404
        assert "detail" in response.json()

    def test_backlog_reflects_purchase_order(self, client, backlog_item_id):
        """Test that /api/backlog flags the item once it has a purchase order."""
        before = {b["id"]: b for b in client.get("/api/backlog").json()}
        assert before[backlog_item_id]["has_purchase_order"] is False

        client.post("/api/purchase-orders", json=po_payload(backlog_item_id))

        after = {b["id"]: b for b in client.get("/api/backlog").json()}
        assert after[backlog_item_id]["has_purchase_order"] is True

    def test_duplicate_purchase_order_rejected(self, client, backlog_item_id):
        """Test that a backlog item can only have one purchase order."""
        client.post("/api/purchase-orders", json=po_payload(backlog_item_id))
        response = client.post("/api/purchase-orders", json=po_payload(backlog_item_id))
        assert response.status_code == 409

    def test_purchase_order_unknown_backlog_item(self, client):
        """Test that an unknown backlog item is a 404."""
        response = client.post("/api/purchase-orders", json=po_payload("nonexistent-999"))
        assert response.status_code == 404

    def test_purchase_order_invalid_date(self, client, backlog_item_id):
        """Test that a malformed delivery date is rejected."""
        response = client.post(
            "/api/purchase-orders", json=po_payload(backlog_item_id, expected_delivery_date="soon")
        )
        assert response.status_code == 400

    @pytest.mark.parametrize(
        "overrides",
        [
            {"quantity": 0},
            {"quantity": -5},
            {"unit_cost": 0},
            {"unit_cost": -1.0},
            {"supplier_name": ""},
        ],
    )
    def test_purchase_order_validation(self, client, backlog_item_id, overrides):
        """Test that non-positive quantities/costs and empty suppliers fail validation."""
        response = client.post("/api/purchase-orders", json=po_payload(backlog_item_id, **overrides))
        assert response.status_code == 422
