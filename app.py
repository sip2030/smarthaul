from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import List, Dict, Any

from database import get_connection, init_db
from auth import hash_password, verify_password

app = FastAPI(title="SmartHaul API", version="0.1.0")
templates = Jinja2Templates(directory="templates")
init_db()


class BookingCreate(BaseModel):
    customer_id: str
    service_type: str
    pickup: str
    destination: str
    price: float


class ReportCreate(BaseModel):
    user_id: str
    type: str
    description: str


class UserCreate(BaseModel):
    name: str
    email: str
    role: str
    password: str


class VendorCreate(BaseModel):
    name: str
    category: str
    location: str
    rating: float = 0.0


class LoginRequest(BaseModel):
    email: str
    password: str


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html", context={"request": request})


@app.get("/health")
def health():
    return {"status": "ok", "service": "smarthaul"}


@app.get("/auth", response_class=HTMLResponse)
def auth_page(request: Request):
    return templates.TemplateResponse(request=request, name="auth.html", context={"request": request})


@app.get("/workspace", response_class=HTMLResponse)
def workspace_page(request: Request):
    return templates.TemplateResponse(request=request, name="workspace.html", context={"request": request})


@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request):
    return templates.TemplateResponse(request=request, name="admin.html", context={"request": request})


@app.get("/ai", response_class=HTMLResponse)
def ai_page(request: Request):
    return templates.TemplateResponse(request=request, name="ai.html", context={"request": request})


@app.get("/support", response_class=HTMLResponse)
def support_page(request: Request):
    return templates.TemplateResponse(request=request, name="support.html", context={"request": request})


@app.get("/tracking", response_class=HTMLResponse)
def tracking_page(request: Request):
    return templates.TemplateResponse(request=request, name="tracking.html", context={"request": request})


@app.get("/messaging", response_class=HTMLResponse)
def messaging_page(request: Request):
    return templates.TemplateResponse(request=request, name="messaging.html", context={"request": request})


@app.get("/moderation", response_class=HTMLResponse)
def moderation_page(request: Request):
    return templates.TemplateResponse(request=request, name="moderation.html", context={"request": request})


@app.get("/analytics", response_class=HTMLResponse)
def analytics_page(request: Request):
    return templates.TemplateResponse(request=request, name="analytics.html", context={"request": request})


@app.get("/map", response_class=HTMLResponse)
def map_page(request: Request):
    return templates.TemplateResponse(request=request, name="map.html", context={"request": request})


@app.get("/calls", response_class=HTMLResponse)
def calls_page(request: Request):
    return templates.TemplateResponse(request=request, name="calls.html", context={"request": request})


@app.get("/notifications", response_class=HTMLResponse)
def notifications_page(request: Request):
    return templates.TemplateResponse(request=request, name="notifications.html", context={"request": request})


@app.get("/chatbot", response_class=HTMLResponse)
def chatbot_page(request: Request):
    return templates.TemplateResponse(request=request, name="chatbot.html", context={"request": request})


@app.post("/bookings")
def create_booking(payload: BookingCreate):
    conn = get_connection()
    cursor = conn.execute(
        "INSERT INTO bookings (customer_id, service_type, pickup, destination, price, status) VALUES (?, ?, ?, ?, ?, ?)",
        (payload.customer_id, payload.service_type, payload.pickup, payload.destination, payload.price, "pending"),
    )
    conn.commit()
    booking_id = cursor.lastrowid
    conn.close()
    return {
        "id": booking_id,
        "customer_id": payload.customer_id,
        "service_type": payload.service_type,
        "pickup": payload.pickup,
        "destination": payload.destination,
        "price": payload.price,
        "status": "pending",
    }


@app.get("/bookings")
def list_bookings():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM bookings ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(row) for row in rows]


@app.get("/vendors")
def list_vendors():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM vendors ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(row) for row in rows]


@app.post("/vendors")
def create_vendor(payload: VendorCreate):
    conn = get_connection()
    cursor = conn.execute(
        "INSERT INTO vendors (name, category, location, rating) VALUES (?, ?, ?, ?)",
        (payload.name, payload.category, payload.location, payload.rating),
    )
    conn.commit()
    vendor_id = cursor.lastrowid
    conn.close()
    return {"id": vendor_id, **payload.dict()}


@app.post("/ai/support")
def ai_support(payload: dict):
    message = payload.get("message", "").lower()
    if "haulage" in message:
        reply = "You can book haulage services by selecting the haulage option, choosing your pickup and destination, and confirming the request."
    elif "vendor" in message:
        reply = "You can browse trusted vendors in the marketplace and place a booking or order directly from their profile."
    else:
        reply = "SmartHaul can help you book rides, haul cargo, find vendors, and report concerns."
    return {"reply": reply}


@app.post("/reports")
def create_report(payload: ReportCreate):
    conn = get_connection()
    cursor = conn.execute(
        "INSERT INTO reports (user_id, report_type, description, status) VALUES (?, ?, ?, ?)",
        (payload.user_id, payload.type, payload.description, "pending"),
    )
    conn.commit()
    report_id = cursor.lastrowid
    conn.close()
    return {
        "id": report_id,
        "user_id": payload.user_id,
        "type": payload.type,
        "description": payload.description,
        "status": "pending",
    }


@app.get("/admin/metrics")
def admin_metrics():
    conn = get_connection()
    bookings_count = conn.execute("SELECT COUNT(*) AS count FROM bookings").fetchone()["count"]
    vendors_count = conn.execute("SELECT COUNT(*) AS count FROM vendors").fetchone()["count"]
    reports_count = conn.execute("SELECT COUNT(*) AS count FROM reports").fetchone()["count"]
    conn.close()
    return {
        "bookings": bookings_count,
        "vendors": vendors_count,
        "reports": reports_count,
        "active_services": 3,
    }


@app.post("/auth/register")
def register_user(payload: UserCreate):
    conn = get_connection()
    existing = conn.execute("SELECT id FROM users WHERE email = ?", (payload.email,)).fetchone()
    if existing:
        conn.close()
        return {"message": "User already exists"}
    hashed = hash_password(payload.password)
    conn.execute(
        "INSERT INTO users (name, email, role, password) VALUES (?, ?, ?, ?)",
        (payload.name, payload.email, payload.role, hashed),
    )
    conn.commit()
    conn.close()
    return {"message": "User registered successfully"}


@app.post("/auth/login")
def login(payload: LoginRequest):
    conn = get_connection()
    user = conn.execute("SELECT * FROM users WHERE email = ?", (payload.email,)).fetchone()
    conn.close()
    if not user:
        return {"message": "Invalid credentials"}
    if verify_password(payload.password, user["password"]):
        return {"message": "Login successful", "role": user["role"], "email": user["email"]}
    return {"message": "Invalid credentials"}


@app.get("/dashboard/overview")
def dashboard_overview():
    return {
        "customers": 1200,
        "providers": 320,
        "vendors": 180,
        "satisfaction": 94,
    }
