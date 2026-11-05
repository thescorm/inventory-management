import threading
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from typing import List, Optional
from pydantic import BaseModel, Field
from mock_data import inventory_items, orders, demand_forecasts, backlog_items, spending_summary, monthly_spending, category_spending, recent_transactions, purchase_orders, restocking_orders, tasks

app = FastAPI(title="Factory Inventory Management System")

# Guards id assignment for restocking orders (see create_restocking_order)
restocking_lock = threading.Lock()
# Guards id assignment / mutation for tasks and purchase orders (same reasoning)
tasks_lock = threading.Lock()
purchase_orders_lock = threading.Lock()
# Client-side mock tasks use small integer ids (1..n); API-created tasks start
# well above that so the client can tell the two apart by id alone.
TASK_ID_START = 1000

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    """Return 422 errors without echoing the rejected input back.

    FastAPI's default body includes each error's `input`. For a non-finite number
    such as `Infinity` that value cannot be serialised to JSON, so the default
    handler would crash with a 500 instead of reporting the validation error.
    """
    errors = [{"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": errors})

# Quarter mapping for date filtering
QUARTER_MAP = {
    'Q1-2025': ['2025-01', '2025-02', '2025-03'],
    'Q2-2025': ['2025-04', '2025-05', '2025-06'],
    'Q3-2025': ['2025-07', '2025-08', '2025-09'],
    'Q4-2025': ['2025-10', '2025-11', '2025-12']
}

def filter_by_month(items: list, month: Optional[str]) -> list:
    """Filter items by month/quarter based on order_date field"""
    if not month or month == 'all':
        return items

    if month.startswith('Q'):
        # Handle quarters
        if month in QUARTER_MAP:
            months = QUARTER_MAP[month]
            return [item for item in items if any(m in item.get('order_date', '') for m in months)]
    else:
        # Direct month match
        return [item for item in items if month in item.get('order_date', '')]

    return items

def apply_filters(items: list, warehouse: Optional[str] = None, category: Optional[str] = None,
                 status: Optional[str] = None) -> list:
    """Apply common filters to a list of items"""
    filtered = items

    if warehouse and warehouse != 'all':
        filtered = [item for item in filtered if item.get('warehouse') == warehouse]

    if category and category != 'all':
        filtered = [item for item in filtered if item.get('category', '').lower() == category.lower()]

    if status and status != 'all':
        filtered = [item for item in filtered if item.get('status', '').lower() == status.lower()]

    return filtered

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Data models
class InventoryItem(BaseModel):
    id: str
    sku: str
    name: str
    category: str
    warehouse: str
    quantity_on_hand: int
    reorder_point: int
    unit_cost: float
    location: str
    last_updated: str

class Order(BaseModel):
    id: str
    order_number: str
    customer: str
    items: List[dict]
    status: str
    order_date: str
    expected_delivery: str
    total_value: float
    actual_delivery: Optional[str] = None
    warehouse: Optional[str] = None
    category: Optional[str] = None

class DemandForecast(BaseModel):
    id: str
    item_sku: str
    item_name: str
    current_demand: int
    forecasted_demand: int
    trend: str
    period: str
    # Restocking fields. Optional so older data without them still validates.
    unit_cost: Optional[float] = None
    quantity_on_hand: Optional[int] = None
    supplier_name: Optional[str] = None
    lead_time_days: Optional[int] = None

class BacklogItem(BaseModel):
    id: str
    order_id: str
    item_sku: str
    item_name: str
    quantity_needed: int
    quantity_available: int
    days_delayed: int
    priority: str
    has_purchase_order: Optional[bool] = False

class PurchaseOrder(BaseModel):
    id: str
    backlog_item_id: str
    supplier_name: str
    quantity: int
    unit_cost: float
    expected_delivery_date: str
    status: str
    created_date: str
    notes: Optional[str] = None

class CreatePurchaseOrderRequest(BaseModel):
    backlog_item_id: str
    supplier_name: str = Field(min_length=1, max_length=200)
    # Bounds mirror the restocking request: keep absurd values out of the float math.
    quantity: int = Field(gt=0, le=1_000_000)
    unit_cost: float = Field(gt=0, le=1_000_000, allow_inf_nan=False)
    expected_delivery_date: str
    notes: Optional[str] = Field(default=None, max_length=1000)

class Task(BaseModel):
    id: int
    title: str
    priority: str
    # camelCase on purpose: the client's TasksModal reads and writes `dueDate`.
    dueDate: str
    status: str

class CreateTaskRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    priority: str = "medium"
    dueDate: str

class RestockingOrderLine(BaseModel):
    # The client only sends SKU and quantity; price, supplier and lead time are
    # looked up server-side so a caller cannot submit its own prices.
    item_sku: str
    # Upper bound keeps absurd values from reaching the float math below.
    quantity: int = Field(gt=0, le=1_000_000)

class CreateRestockingOrderRequest(BaseModel):
    items: List[RestockingOrderLine] = Field(min_length=1)
    # allow_inf_nan=False matters: Python's JSON parser accepts a bare `Infinity`,
    # which would pass `ge=0` and then defeat the over-budget check, storing an
    # order whose budget cannot be serialised back to JSON.
    budget: float = Field(ge=0, le=100_000_000, allow_inf_nan=False)

class RestockingOrderItem(BaseModel):
    item_sku: str
    item_name: str
    quantity: int
    unit_cost: float
    supplier_name: str
    lead_time_days: int
    line_total: float

class RestockingOrder(BaseModel):
    id: str
    order_number: str
    items: List[RestockingOrderItem]
    budget: float
    total_value: float
    status: str
    submitted_date: str
    lead_time_days: int
    expected_delivery: str

# API endpoints
@app.get("/")
def root():
    return {"message": "Factory Inventory Management System API", "version": "1.0.0"}

@app.get("/api/inventory", response_model=List[InventoryItem])
def get_inventory(
    warehouse: Optional[str] = None,
    category: Optional[str] = None
):
    """Get all inventory items with optional filtering"""
    return apply_filters(inventory_items, warehouse, category)

@app.get("/api/inventory/{item_id}", response_model=InventoryItem)
def get_inventory_item(item_id: str):
    """Get a specific inventory item"""
    item = next((item for item in inventory_items if item["id"] == item_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item

@app.get("/api/orders", response_model=List[Order])
def get_orders(
    warehouse: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    month: Optional[str] = None
):
    """Get all orders with optional filtering"""
    filtered_orders = apply_filters(orders, warehouse, category, status)
    filtered_orders = filter_by_month(filtered_orders, month)
    return filtered_orders

@app.get("/api/orders/{order_id}", response_model=Order)
def get_order(order_id: str):
    """Get a specific order"""
    order = next((order for order in orders if order["id"] == order_id), None)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order

@app.get("/api/demand", response_model=List[DemandForecast])
def get_demand_forecasts():
    """Get demand forecasts"""
    return demand_forecasts

@app.post("/api/restocking-orders", response_model=RestockingOrder, status_code=201)
def create_restocking_order(request: CreateRestockingOrderRequest):
    """Submit a restocking order for items from the demand forecast"""
    forecasts_by_sku = {f["item_sku"]: f for f in demand_forecasts}

    lines = []
    seen_skus = set()
    for line in request.items:
        if line.item_sku in seen_skus:
            raise HTTPException(status_code=400, detail=f"Duplicate SKU in order: {line.item_sku}")
        seen_skus.add(line.item_sku)

        forecast = forecasts_by_sku.get(line.item_sku)
        # Only forecast items carry cost, supplier and lead-time data, so anything
        # else (or an item missing any of those fields) cannot be ordered.
        if not forecast or any(forecast.get(k) is None for k in ("unit_cost", "supplier_name", "lead_time_days")):
            raise HTTPException(status_code=400, detail=f"Unknown or non-restockable SKU: {line.item_sku}")

        lines.append({
            "item_sku": forecast["item_sku"],
            "item_name": forecast["item_name"],
            "quantity": line.quantity,
            "unit_cost": forecast["unit_cost"],
            "supplier_name": forecast["supplier_name"],
            "lead_time_days": forecast["lead_time_days"],
            "line_total": round(line.quantity * forecast["unit_cost"], 2),
        })

    total_value = round(sum(line["line_total"] for line in lines), 2)
    if total_value > request.budget:
        raise HTTPException(
            status_code=400,
            detail=f"Order total {total_value} exceeds budget {request.budget}"
        )

    # Items ship from different suppliers in parallel, so the order is complete
    # only when the slowest item arrives: order lead time is the maximum line lead time.
    lead_time_days = max(line["lead_time_days"] for line in lines)
    submitted = datetime.now().replace(microsecond=0)

    # Sync handlers run in a threadpool, so reading the length and appending must
    # be one atomic step or two concurrent orders could get the same id.
    with restocking_lock:
        sequence = len(restocking_orders) + 1
        order = {
            "id": str(sequence),
            "order_number": f"RST-{sequence:04d}",
            "items": lines,
            "budget": request.budget,
            "total_value": total_value,
            "status": "Submitted",
            "submitted_date": submitted.isoformat(),
            "lead_time_days": lead_time_days,
            "expected_delivery": (submitted + timedelta(days=lead_time_days)).isoformat(),
        }
        restocking_orders.append(order)
    return order

@app.get("/api/restocking-orders", response_model=List[RestockingOrder])
def get_restocking_orders():
    """Get submitted restocking orders, newest first"""
    return list(reversed(restocking_orders))

@app.get("/api/backlog", response_model=List[BacklogItem])
def get_backlog():
    """Get backlog items with purchase order status"""
    # Add has_purchase_order flag to each backlog item
    result = []
    for item in backlog_items:
        item_dict = dict(item)
        # Check if this backlog item has a purchase order
        has_po = any(po["backlog_item_id"] == item["id"] for po in purchase_orders)
        item_dict["has_purchase_order"] = has_po
        result.append(item_dict)
    return result

def parse_iso_date(value: str, field: str) -> str:
    """Return the value if it is a valid YYYY-MM-DD date, else raise 400."""
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{field} must be a valid date in YYYY-MM-DD format")
    return value

@app.post("/api/purchase-orders", response_model=PurchaseOrder, status_code=201)
def create_purchase_order(request: CreatePurchaseOrderRequest):
    """Create a purchase order for a backlog item (one PO per backlog item)"""
    if not any(b["id"] == request.backlog_item_id for b in backlog_items):
        raise HTTPException(status_code=404, detail=f"Backlog item {request.backlog_item_id} not found")
    parse_iso_date(request.expected_delivery_date, "expected_delivery_date")

    # Check-then-append must be atomic, otherwise two concurrent requests could
    # both pass the duplicate check and create two POs for one backlog item.
    with purchase_orders_lock:
        if any(po["backlog_item_id"] == request.backlog_item_id for po in purchase_orders):
            raise HTTPException(status_code=409, detail="A purchase order already exists for this backlog item")
        po = {
            "id": f"PO-{len(purchase_orders) + 1:04d}",
            "backlog_item_id": request.backlog_item_id,
            "supplier_name": request.supplier_name,
            "quantity": request.quantity,
            "unit_cost": request.unit_cost,
            "expected_delivery_date": request.expected_delivery_date,
            "status": "pending",
            "created_date": datetime.now().strftime("%Y-%m-%d"),
            "notes": request.notes,
        }
        purchase_orders.append(po)
    return po

@app.get("/api/purchase-orders/{backlog_item_id}", response_model=PurchaseOrder)
def get_purchase_order_by_backlog_item(backlog_item_id: str):
    """Get the purchase order linked to a backlog item"""
    for po in purchase_orders:
        if po["backlog_item_id"] == backlog_item_id:
            return po
    raise HTTPException(status_code=404, detail=f"No purchase order for backlog item {backlog_item_id}")

@app.get("/api/tasks", response_model=List[Task])
def get_tasks():
    """Get user-created tasks, newest first"""
    return list(reversed(tasks))

@app.post("/api/tasks", response_model=Task, status_code=201)
def create_task(request: CreateTaskRequest):
    """Create a task"""
    if request.priority not in ("high", "medium", "low"):
        raise HTTPException(status_code=400, detail="priority must be one of: high, medium, low")
    parse_iso_date(request.dueDate, "dueDate")
    with tasks_lock:
        # max()+1 rather than len(): after a delete, len() would hand out an id
        # that is still in use by a later task.
        next_id = max((t["id"] for t in tasks), default=TASK_ID_START - 1) + 1
        task = {
            "id": next_id,
            "title": request.title.strip(),
            "priority": request.priority,
            "dueDate": request.dueDate,
            "status": "pending",
        }
        tasks.append(task)
    return task

@app.patch("/api/tasks/{task_id}", response_model=Task)
def toggle_task(task_id: int):
    """Toggle a task between pending and completed"""
    with tasks_lock:
        for task in tasks:
            if task["id"] == task_id:
                task["status"] = "completed" if task["status"] == "pending" else "pending"
                return task
    raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: int):
    """Delete a task"""
    with tasks_lock:
        for i, task in enumerate(tasks):
            if task["id"] == task_id:
                # Delete in place (see mock_data.py); create_task derives new ids from max id.
                del tasks[i]
                return {"message": f"Task {task_id} deleted"}
    raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

@app.get("/api/dashboard/summary")
def get_dashboard_summary(
    warehouse: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    month: Optional[str] = None
):
    """Get summary statistics for dashboard with optional filtering"""
    # Filter inventory
    filtered_inventory = apply_filters(inventory_items, warehouse, category)

    # Filter orders
    filtered_orders = apply_filters(orders, warehouse, category, status)
    filtered_orders = filter_by_month(filtered_orders, month)

    total_inventory_value = sum(item["quantity_on_hand"] * item["unit_cost"] for item in filtered_inventory)
    low_stock_items = len([item for item in filtered_inventory if item["quantity_on_hand"] <= item["reorder_point"]])
    pending_orders = len([order for order in filtered_orders if order["status"] in ["Processing", "Backordered"]])
    total_backlog_items = len(backlog_items)

    return {
        "total_inventory_value": round(total_inventory_value, 2),
        "low_stock_items": low_stock_items,
        "pending_orders": pending_orders,
        "total_backlog_items": total_backlog_items,
        "total_orders_value": sum(order["total_value"] for order in filtered_orders)
    }

@app.get("/api/spending/summary")
def get_spending_summary():
    """Get spending summary statistics"""
    return spending_summary

@app.get("/api/spending/monthly")
def get_monthly_spending():
    """Get monthly spending breakdown"""
    return monthly_spending

@app.get("/api/spending/categories")
def get_category_spending():
    """Get spending by category"""
    return category_spending

@app.get("/api/spending/transactions")
def get_recent_transactions():
    """Get recent transactions"""
    return recent_transactions

@app.get("/api/reports/quarterly")
def get_quarterly_reports():
    """Get quarterly performance reports"""
    # Calculate quarterly statistics from orders
    quarters = {}

    for order in orders:
        order_date = order.get('order_date', '')
        # Determine quarter
        if '2025-01' in order_date or '2025-02' in order_date or '2025-03' in order_date:
            quarter = 'Q1-2025'
        elif '2025-04' in order_date or '2025-05' in order_date or '2025-06' in order_date:
            quarter = 'Q2-2025'
        elif '2025-07' in order_date or '2025-08' in order_date or '2025-09' in order_date:
            quarter = 'Q3-2025'
        elif '2025-10' in order_date or '2025-11' in order_date or '2025-12' in order_date:
            quarter = 'Q4-2025'
        else:
            continue

        if quarter not in quarters:
            quarters[quarter] = {
                'quarter': quarter,
                'total_orders': 0,
                'total_revenue': 0,
                'delivered_orders': 0,
                'avg_order_value': 0
            }

        quarters[quarter]['total_orders'] += 1
        quarters[quarter]['total_revenue'] += order.get('total_value', 0)
        if order.get('status') == 'Delivered':
            quarters[quarter]['delivered_orders'] += 1

    # Calculate averages and fulfillment rate
    result = []
    for q, data in quarters.items():
        if data['total_orders'] > 0:
            data['avg_order_value'] = round(data['total_revenue'] / data['total_orders'], 2)
            data['fulfillment_rate'] = round((data['delivered_orders'] / data['total_orders']) * 100, 1)
        result.append(data)

    # Sort by quarter
    result.sort(key=lambda x: x['quarter'])
    return result

@app.get("/api/reports/monthly-trends")
def get_monthly_trends():
    """Get month-over-month trends"""
    months = {}

    for order in orders:
        order_date = order.get('order_date', '')
        if not order_date:
            continue

        # Extract month (format: YYYY-MM-DD)
        month = order_date[:7]  # Gets YYYY-MM

        if month not in months:
            months[month] = {
                'month': month,
                'order_count': 0,
                'revenue': 0,
                'delivered_count': 0
            }

        months[month]['order_count'] += 1
        months[month]['revenue'] += order.get('total_value', 0)
        if order.get('status') == 'Delivered':
            months[month]['delivered_count'] += 1

    # Convert to list and sort
    result = list(months.values())
    result.sort(key=lambda x: x['month'])
    return result

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
