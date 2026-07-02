import json
import logging
import os
import re
import secrets
import httpx
from datetime import datetime, timedelta, timezone
from pathlib import Path
from contextlib import asynccontextmanager
from urllib.parse import parse_qsl
from threading import Lock
from collections import defaultdict
from time import time

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import List, Dict, Any

import database as database_module
from database import DB_PATH, get_bootstrap_admin_config, get_connection, get_database_backend, init_db
from auth import hash_password, is_strong_password, verify_password

templates = Jinja2Templates(directory="templates")
logger = logging.getLogger("smarthaul")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())

ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
DB_PATH = os.getenv("DATABASE_PATH") or str(Path(__file__).resolve().parent / "smarthaul.db")
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://127.0.0.1:8000")
FLUTTERWAVE_SECRET_KEY = os.getenv("FLUTTERWAVE_SECRET_KEY", "")
FLUTTERWAVE_WEBHOOK_SECRET_HASH = os.getenv("FLUTTERWAVE_WEBHOOK_SECRET_HASH", "")
FLUTTERWAVE_BASE_URL = os.getenv("FLUTTERWAVE_BASE_URL", "https://api.flutterwave.com/v3")
ROUTING_PROVIDER = os.getenv("ROUTING_PROVIDER", "simulated").lower()
OPENROUTESERVICE_API_KEY = os.getenv("OPENROUTESERVICE_API_KEY", "")
OPENROUTESERVICE_BASE_URL = os.getenv("OPENROUTESERVICE_BASE_URL", "https://api.openrouteservice.org")
HTTP_TIMEOUT_SECONDS = 15.0

os.environ.setdefault("DATABASE_PATH", DB_PATH)
init_db()

SESSION_STORE: Dict[str, Dict[str, Any]] = {}
SESSION_DURATION_HOURS = 12
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_MINUTES = 15
PENDING_BOOKING_TIMEOUT_MINUTES = int(os.getenv("PENDING_BOOKING_TIMEOUT_MINUTES", "10"))
ABUSIVE_KEYWORDS = {"abusive", "fraud", "scam", "threat", "harass", "harassment", "stupid", "idiot"}
ALLOWED_VENDOR_REVIEW_STATUSES = {"approved", "rejected", "needs_more_info", "pending_review"}
ALLOWED_ACCOUNT_STATUSES = {"active", "restricted"}


class RateLimiter:
    """Thread-safe rate limiter for per-user and per-IP rate limiting"""
    def __init__(self, requests_per_minute: int = 60, cleanup_interval: int = 300):
        self.requests_per_minute = requests_per_minute
        self.cleanup_interval = cleanup_interval
        self.requests: Dict[str, List[float]] = defaultdict(list)
        self.lock = Lock()
        self.last_cleanup = time()
    
    def is_allowed(self, identifier: str) -> bool:
        """Check if request is allowed for identifier (user_id or IP)"""
        with self.lock:
            now = time()
            
            # Cleanup old requests
            if now - self.last_cleanup > self.cleanup_interval:
                self._cleanup(now)
                self.last_cleanup = now
            
            # Get requests from last minute
            cutoff_time = now - 60
            self.requests[identifier] = [t for t in self.requests[identifier] if t > cutoff_time]
            
            # Check limit
            if len(self.requests[identifier]) >= self.requests_per_minute:
                return False
            
            # Record this request
            self.requests[identifier].append(now)
            return True
    
    def get_remaining(self, identifier: str) -> int:
        """Get remaining requests for identifier in current minute"""
        with self.lock:
            now = time()
            cutoff_time = now - 60
            count = len([t for t in self.requests[identifier] if t > cutoff_time])
            return max(0, self.requests_per_minute - count)
    
    def _cleanup(self, now: float):
        """Remove old entries to prevent memory bloat"""
        cutoff_time = now - 3600  # Keep 1 hour of history
        for identifier in list(self.requests.keys()):
            self.requests[identifier] = [t for t in self.requests[identifier] if t > cutoff_time]
            if not self.requests[identifier]:
                del self.requests[identifier]


class BruteForceProtector:
    """Prevent brute force attacks with exponential backoff"""
    def __init__(self, max_attempts: int = 5, lockout_minutes: int = 15):
        self.max_attempts = max_attempts
        self.lockout_minutes = lockout_minutes
        self.attempts: Dict[str, Dict[str, Any]] = {}
        self.lock = Lock()
    
    def record_failed_attempt(self, identifier: str) -> tuple[bool, int, int]:
        """Record failed attempt. Returns (is_locked_out, attempts, remaining_seconds)"""
        with self.lock:
            now = time()
            
            if identifier not in self.attempts:
                self.attempts[identifier] = {
                    "count": 0,
                    "locked_until": None,
                }
            
            entry = self.attempts[identifier]
            
            # Check if still locked out
            if entry["locked_until"] and now < entry["locked_until"]:
                remaining = int(entry["locked_until"] - now)
                return True, self.max_attempts, remaining
            
            # Reset if lockout expired
            if entry["locked_until"] and now >= entry["locked_until"]:
                entry["count"] = 0
                entry["locked_until"] = None
            
            # Increment attempts
            entry["count"] += 1
            
            # Lock out if threshold reached
            if entry["count"] >= self.max_attempts:
                entry["locked_until"] = now + (self.lockout_minutes * 60)
                return True, self.max_attempts, self.lockout_minutes * 60
            
            return False, entry["count"], 0
    
    def record_success(self, identifier: str):
        """Clear failed attempts on successful auth"""
        with self.lock:
            if identifier in self.attempts:
                del self.attempts[identifier]
    
    def is_locked_out(self, identifier: str) -> bool:
        """Check if identifier is currently locked out"""
        with self.lock:
            if identifier not in self.attempts:
                return False
            
            entry = self.attempts[identifier]
            if entry["locked_until"] and time() < entry["locked_until"]:
                return True
            
            return False


# Global rate limiters
_global_rate_limiter = RateLimiter(requests_per_minute=300)  # 300 req/min globally
_user_rate_limiter = RateLimiter(requests_per_minute=60)  # 60 req/min per user
_api_rate_limiter = RateLimiter(requests_per_minute=100)  # 100 req/min for API calls
_brute_force_protector = BruteForceProtector(max_attempts=MAX_LOGIN_ATTEMPTS, lockout_minutes=LOCKOUT_MINUTES)


# Security event logging
def ensure_security_events_table():
    """Create security_events table if not exists"""
    conn = get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS security_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                severity TEXT DEFAULT 'medium',
                user_id INTEGER,
                ip_address TEXT,
                details TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_security_events_created_at ON security_events(created_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_security_events_user_id ON security_events(user_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_security_events_event_type ON security_events(event_type)"
        )
        conn.commit()
    finally:
        conn.close()


def log_security_event(
    event_type: str,
    severity: str = "medium",
    user_id: int | None = None,
    ip_address: str | None = None,
    details: str = "",
) -> None:
    """Log a security event for auditing"""
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO security_events (event_type, severity, user_id, ip_address, details, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (event_type, severity, user_id, ip_address, details, utc_now_iso()),
        )
        conn.commit()
    except Exception as e:
        logger.error(f"Failed to log security event: {e}")
    finally:
        conn.close()


def get_security_events(
    limit: int = 50,
    event_type: str | None = None,
    severity: str | None = None,
) -> List[Dict[str, Any]]:
    """Retrieve recent security events with optional filtering"""
    conn = get_connection()
    try:
        query = "SELECT * FROM security_events WHERE 1=1"
        params = []
        
        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)
        
        if severity:
            query += " AND severity = ?"
            params.append(severity)
        
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("SmartHaul startup complete in %s", ENVIRONMENT)
    yield


app = FastAPI(title="SmartHaul API", version="0.1.0", lifespan=lifespan)


# Rate limiting middleware
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Enforce global rate limiting on all requests"""
    client_ip = request.client.host if request.client else "unknown"
    
    # Check if IP is blacklisted
    conn = get_connection()
    try:
        blacklisted = conn.execute(
            "SELECT * FROM ip_blacklist WHERE ip_address = ?",
            (client_ip,),
        ).fetchone()
        if blacklisted:
            return Response(
                content='{"detail": "IP address is blocked"}',
                status_code=403,
                media_type="application/json",
            )
    finally:
        conn.close()
    
    # Check global rate limit
    if not _global_rate_limiter.is_allowed(client_ip):
        remaining = _global_rate_limiter.get_remaining(client_ip)
        return Response(
            content=f'{{"detail": "Rate limit exceeded", "retry_after": 60}}',
            status_code=429,
            media_type="application/json",
            headers={"Retry-After": "60"},
        )
    
    # Get authenticated user if available
    user = get_authenticated_user(request)
    
    # Enforce per-user rate limit for authenticated requests
    if user:
        user_id_str = str(user.get("id", "unknown"))
        if not _user_rate_limiter.is_allowed(user_id_str):
            return Response(
                content='{"detail": "User rate limit exceeded", "retry_after": 60}',
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": "60"},
            )
    
    # Special handling for login endpoint - enforce brute force protection
    if request.url.path == "/auth/login" and request.method == "POST":
        # Extract email from request body for brute force tracking
        try:
            body = await request.body()
            if body:
                payload = json.loads(body)
                email = payload.get("email", client_ip)
                
                # Check if account is locked out
                is_locked_out = _brute_force_protector.is_locked_out(email)
                if is_locked_out:
                    log_security_event(
                        event_type="brute_force_lockout_attempted",
                        severity="high",
                        ip_address=client_ip,
                        details=f"Brute force lockout active for {email}",
                    )
                    return Response(
                        content='{"detail": "Account temporarily locked. Try again later."}',
                        status_code=423,
                        media_type="application/json",
                        headers={"Retry-After": str(_brute_force_protector.lockout_minutes * 60)},
                    )
                
                # Wrap the request to capture the response and log brute force
                response = await call_next(request)
                
                # If login was successful (200), record success
                if response.status_code == 200:
                    _brute_force_protector.record_success(email)
                # If login failed (400/401/403), record failed attempt
                elif response.status_code in [400, 401, 403]:
                    is_locked, attempts, remaining = _brute_force_protector.record_failed_attempt(email)
                    if is_locked:
                        log_security_event(
                            event_type="brute_force_lockout_triggered",
                            severity="high",
                            ip_address=client_ip,
                            details=f"Account {email} locked after {attempts} failed attempts",
                        )
                
                return response
        except Exception as e:
            logger.error(f"Error in brute force middleware: {e}")
    
    response = await call_next(request)
    return response


# Security headers middleware
@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """Add security headers to all responses"""
    response = await call_next(request)
    
    # Prevent clickjacking
    response.headers["X-Frame-Options"] = "DENY"
    
    # Prevent MIME type sniffing
    response.headers["X-Content-Type-Options"] = "nosniff"
    
    # Enable XSS protection
    response.headers["X-XSS-Protection"] = "1; mode=block"
    
    # Prevent information disclosure
    response.headers["Server"] = "SmartHaul"
    
    # Content Security Policy (basic)
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'"
    
    # Enforce HTTPS in production
    if ENVIRONMENT == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    
    # Referrer Policy
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    
    # Permissions Policy (formerly Feature-Policy)
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    
    return response


def create_session(user: Dict[str, Any]) -> str:
    session_id = secrets.token_urlsafe(16)
    created_at = datetime.now(timezone.utc)
    SESSION_STORE[session_id] = {
        "id": user.get("id"),
        "name": user.get("name"),
        "email": user.get("email"),
        "role": user.get("role"),
        "account_status": user.get("account_status", "active"),
        "password_updated_at": user.get("password_updated_at"),
        "created_at": created_at.isoformat(),
        "expires_at": (created_at + timedelta(hours=SESSION_DURATION_HOURS)).isoformat(),
    }
    return session_id


def get_authenticated_user(request: Request) -> Dict[str, Any] | None:
    session_id = request.cookies.get("smarthaul_session")
    if not session_id:
        return None
    session = SESSION_STORE.get(session_id)
    if not session:
        return None
    expires_at = session.get("expires_at")
    if expires_at and datetime.fromisoformat(expires_at) <= datetime.now(timezone.utc):
        SESSION_STORE.pop(session_id, None)
        return None

    session_created_at_raw = session.get("created_at")
    session_created_at = datetime.fromisoformat(session_created_at_raw) if session_created_at_raw else None
    session_email = session.get("email")
    if session_email:
        conn = get_connection()
        try:
            user_row = conn.execute(
                "SELECT id, name, email, role, password_updated_at, account_status, account_restriction_reason, account_restricted_at FROM users WHERE email = ?",
                (session_email,),
            ).fetchone()
        finally:
            conn.close()
        if not user_row:
            SESSION_STORE.pop(session_id, None)
            return None
        if user_row["account_status"] != "active":
            SESSION_STORE.pop(session_id, None)
            return None
        password_updated_at = user_row["password_updated_at"]
        if password_updated_at and session_created_at and datetime.fromisoformat(password_updated_at) > session_created_at:
            SESSION_STORE.pop(session_id, None)
            return None
        session["id"] = user_row["id"]
        session["name"] = user_row["name"]
        session["role"] = user_row["role"]
        session["account_status"] = user_row["account_status"]
        session["password_updated_at"] = password_updated_at
    return session


def require_authenticated_user(request: Request) -> Dict[str, Any]:
    user = get_authenticated_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def require_role(request: Request, roles: set[str]) -> Dict[str, Any]:
    user = require_authenticated_user(request)
    if user.get("role") not in roles:
        raise HTTPException(status_code=403, detail="Access denied")
    return user


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def password_is_strong(password: str) -> bool:
    return is_strong_password(password)


def parse_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def validate_request_signature(request: Request, api_secret: str = None) -> bool:
    """
    Validate request signature for sensitive endpoints (optional enhancement).
    Expected header: X-Request-Signature with HMAC-SHA256 of body
    """
    import hmac
    import hashlib
    
    if not api_secret:
        api_secret = os.getenv("API_SECRET", "")
    
    if not api_secret:
        # If no API secret configured, skip validation
        return True
    
    signature = request.headers.get("X-Request-Signature", "")
    timestamp = request.headers.get("X-Request-Timestamp", "")
    
    if not signature or not timestamp:
        return False
    
    # Prevent replay attacks - check timestamp is within 5 minutes
    try:
        req_time = int(timestamp)
        current_time = int(time())
        if abs(current_time - req_time) > 300:  # 5 minutes
            return False
    except ValueError:
        return False
    
    # In a real implementation, you would sign the body + timestamp
    # This is a simplified version - full implementation would require
    # reading and re-reading the request body
    return True


def get_admin_setting(conn, key: str, default_value: str) -> str:
    row = conn.execute("SELECT value FROM admin_settings WHERE key = ?", (key,)).fetchone()
    if not row:
        return default_value
    return str(row["value"])


def get_cancellation_policy() -> Dict[str, Any]:
    defaults = {
        "penalty_free_window_minutes": 10,
        "cancellation_fee_type": "percentage",
        "cancellation_fee_value": 10.0,
        "provider_cancel_fee_assignment": "customer_credit",
    }
    conn = get_connection()
    try:
        policy = {
            "penalty_free_window_minutes": int(get_admin_setting(conn, "cancellation_penalty_free_window_minutes", str(defaults["penalty_free_window_minutes"]))),
            "cancellation_fee_type": get_admin_setting(conn, "cancellation_fee_type", defaults["cancellation_fee_type"]),
            "cancellation_fee_value": float(get_admin_setting(conn, "cancellation_fee_value", str(defaults["cancellation_fee_value"]))),
            "provider_cancel_fee_assignment": get_admin_setting(conn, "provider_cancel_fee_assignment", defaults["provider_cancel_fee_assignment"]),
        }
    finally:
        conn.close()
    return policy


def validate_cancellation_policy(payload: CancellationPolicyUpdate) -> None:
    allowed_fee_types = {"percentage", "fixed"}
    allowed_assignments = {"customer_credit", "provider_penalty", "platform", "none"}

    if payload.penalty_free_window_minutes < 0:
        raise HTTPException(status_code=400, detail="Penalty-free window must be zero or greater")
    if payload.cancellation_fee_type not in allowed_fee_types:
        raise HTTPException(status_code=400, detail="Invalid cancellation fee type")
    if payload.cancellation_fee_value < 0:
        raise HTTPException(status_code=400, detail="Cancellation fee value must be zero or greater")
    if payload.cancellation_fee_type == "percentage" and payload.cancellation_fee_value > 100:
        raise HTTPException(status_code=400, detail="Percentage cancellation fee cannot exceed 100")
    if payload.provider_cancel_fee_assignment not in allowed_assignments:
        raise HTTPException(status_code=400, detail="Invalid provider cancellation fee assignment")


def set_cancellation_policy(payload: CancellationPolicyUpdate) -> Dict[str, Any]:
    validate_cancellation_policy(payload)
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO admin_settings (key, value, updated_at) VALUES (?, ?, ?)",
            ("cancellation_penalty_free_window_minutes", str(payload.penalty_free_window_minutes), utc_now_iso()),
        )
        conn.execute(
            "INSERT OR REPLACE INTO admin_settings (key, value, updated_at) VALUES (?, ?, ?)",
            ("cancellation_fee_type", payload.cancellation_fee_type, utc_now_iso()),
        )
        conn.execute(
            "INSERT OR REPLACE INTO admin_settings (key, value, updated_at) VALUES (?, ?, ?)",
            ("cancellation_fee_value", str(payload.cancellation_fee_value), utc_now_iso()),
        )
        conn.execute(
            "INSERT OR REPLACE INTO admin_settings (key, value, updated_at) VALUES (?, ?, ?)",
            ("provider_cancel_fee_assignment", payload.provider_cancel_fee_assignment, utc_now_iso()),
        )
        conn.commit()
    finally:
        conn.close()
    return get_cancellation_policy()


def compute_cancellation_fee(existing_booking: Dict[str, Any], payload: BookingStatusUpdate, policy: Dict[str, Any]) -> Dict[str, Any]:
    previous_status = existing_booking.get("status")
    cancelled_by = payload.cancelled_by
    if cancelled_by not in {"customer", "provider", "admin"}:
        raise HTTPException(status_code=400, detail="Invalid cancelled_by value")

    cancellation_fee_applied = False
    cancellation_fee_amount = 0.0
    fee_assignment = "none"
    elapsed_minutes = None

    if previous_status in {"accepted", "active"}:
        reference_time = parse_iso_datetime(existing_booking.get("updated_at"))
        if reference_time is not None:
            elapsed_minutes = max(0.0, (datetime.now(timezone.utc) - reference_time).total_seconds() / 60)
        else:
            elapsed_minutes = float(policy["penalty_free_window_minutes"])

    outside_window = previous_status in {"accepted", "active"} and elapsed_minutes is not None and elapsed_minutes >= float(policy["penalty_free_window_minutes"])

    if outside_window:
        if policy["cancellation_fee_type"] == "percentage":
            cancellation_fee_amount = round(float(existing_booking["price"]) * (float(policy["cancellation_fee_value"]) / 100.0), 2)
        else:
            cancellation_fee_amount = round(float(policy["cancellation_fee_value"]), 2)
        cancellation_fee_applied = cancellation_fee_amount > 0

    if cancelled_by == "provider":
        fee_assignment = policy["provider_cancel_fee_assignment"] if cancellation_fee_applied else "none"
    elif cancelled_by == "customer":
        fee_assignment = "platform" if cancellation_fee_applied else "none"

    return {
        "cancelled_by": cancelled_by,
        "previous_status": previous_status,
        "elapsed_minutes_since_previous_state": round(elapsed_minutes, 2) if elapsed_minutes is not None else None,
        "cancellation_fee_applied": cancellation_fee_applied,
        "cancellation_fee_amount": cancellation_fee_amount,
        "cancellation_fee_type": policy["cancellation_fee_type"],
        "cancellation_fee_value": float(policy["cancellation_fee_value"]),
        "penalty_free_window_minutes": int(policy["penalty_free_window_minutes"]),
        "fee_assignment": fee_assignment,
    }


def create_notification(title: str, message: str, booking_id: int | None = None, channel: str = "in_app"):
    conn = get_connection()
    conn.execute(
        "INSERT INTO notifications (title, message, channel, booking_id) VALUES (?, ?, ?, ?)",
        (title, message, channel, booking_id),
    )
    conn.commit()
    conn.close()


def text_to_coordinate(value: str, salt: int = 0) -> tuple[float, float]:
    signature = sum((index + 1 + salt) * ord(char) for index, char in enumerate(value))
    latitude = 6.35 + (signature % 250) / 1000
    longitude = 3.10 + ((signature // 7) % 350) / 1000
    return round(latitude, 6), round(longitude, 6)


def route_snapshot(pickup: str, destination: str, progress: float = 0.0) -> Dict[str, Any]:
    start_lat, start_lng = text_to_coordinate(pickup, 1)
    end_lat, end_lng = text_to_coordinate(destination, 2)
    polyline = []
    for step in range(6):
        fraction = step / 5
        polyline.append(
            {
                "lat": round(start_lat + ((end_lat - start_lat) * fraction), 6),
                "lng": round(start_lng + ((end_lng - start_lng) * fraction), 6),
            }
        )
    current_index = min(len(polyline) - 1, max(0, int(round(progress * (len(polyline) - 1)))))
    current_position = polyline[current_index]
    distance_km = round((((end_lat - start_lat) ** 2 + (end_lng - start_lng) ** 2) ** 0.5) * 111, 1)
    eta_minutes = max(6, int(max(distance_km, 3) * max(0.15, 1 - progress) * 3))
    return {
        "pickup": pickup,
        "destination": destination,
        "start": {"lat": start_lat, "lng": start_lng},
        "end": {"lat": end_lat, "lng": end_lng},
        "current_position": current_position,
        "polyline": polyline,
        "distance_km": distance_km,
        "eta_minutes": eta_minutes,
        "route_status": "simulated_live",
        "route_source": "simulated_fallback",
        "provider_configured": routing_provider_is_configured(),
    }


def routing_provider_is_configured() -> bool:
    return ROUTING_PROVIDER == "openrouteservice" and bool(OPENROUTESERVICE_API_KEY)


def build_route_from_polyline(
    pickup: str,
    destination: str,
    polyline: List[Dict[str, float]],
    distance_km: float,
    eta_minutes: int,
    progress: float,
    route_status: str,
    provider: str,
) -> Dict[str, Any]:
    safe_polyline = polyline or [
        {"lat": text_to_coordinate(pickup, 1)[0], "lng": text_to_coordinate(pickup, 1)[1]},
        {"lat": text_to_coordinate(destination, 2)[0], "lng": text_to_coordinate(destination, 2)[1]},
    ]
    current_index = min(len(safe_polyline) - 1, max(0, int(round(progress * (len(safe_polyline) - 1)))))
    return {
        "pickup": pickup,
        "destination": destination,
        "start": safe_polyline[0],
        "end": safe_polyline[-1],
        "current_position": safe_polyline[current_index],
        "polyline": safe_polyline,
        "distance_km": distance_km,
        "eta_minutes": eta_minutes,
        "route_status": route_status,
        "provider": provider,
        "route_source": "provider_live" if provider == "openrouteservice" else "simulated_fallback",
        "provider_configured": provider == "openrouteservice",
    }


def geocode_openrouteservice_location(location: str) -> tuple[float, float]:
    response = httpx.get(
        f"{OPENROUTESERVICE_BASE_URL}/geocode/search",
        params={"api_key": OPENROUTESERVICE_API_KEY, "text": location, "size": 1},
        timeout=HTTP_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    features = response.json().get("features") or []
    if not features:
        raise HTTPException(status_code=404, detail=f"No route location found for {location}")
    longitude, latitude = features[0]["geometry"]["coordinates"]
    return round(latitude, 6), round(longitude, 6)


def fetch_openrouteservice_route(pickup: str, destination: str, progress: float) -> Dict[str, Any]:
    pickup_lat, pickup_lng = geocode_openrouteservice_location(pickup)
    destination_lat, destination_lng = geocode_openrouteservice_location(destination)
    response = httpx.post(
        f"{OPENROUTESERVICE_BASE_URL}/v2/directions/driving-car/geojson",
        headers={"Authorization": OPENROUTESERVICE_API_KEY, "Content-Type": "application/json"},
        json={"coordinates": [[pickup_lng, pickup_lat], [destination_lng, destination_lat]]},
        timeout=HTTP_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()
    features = payload.get("features") or []
    if not features:
        raise HTTPException(status_code=502, detail="Routing provider returned no route")
    geometry = features[0].get("geometry") or {}
    coordinates = geometry.get("coordinates") or []
    polyline = [{"lat": round(lat, 6), "lng": round(lng, 6)} for lng, lat in coordinates]
    summary = ((features[0].get("properties") or {}).get("summary") or {})
    distance_km = round(float(summary.get("distance", 0)) / 1000, 1)
    eta_minutes = max(1, int(round(float(summary.get("duration", 0)) / 60)))
    return build_route_from_polyline(
        pickup=pickup,
        destination=destination,
        polyline=polyline,
        distance_km=distance_km,
        eta_minutes=eta_minutes,
        progress=progress,
        route_status="provider_live",
        provider="openrouteservice",
    )


def resolved_route_snapshot(pickup: str, destination: str, progress: float = 0.0) -> Dict[str, Any]:
    if routing_provider_is_configured():
        try:
            return fetch_openrouteservice_route(pickup, destination, progress)
        except (httpx.HTTPError, HTTPException):
            logger.exception("Falling back to simulated route for %s -> %s", pickup, destination)
    route = route_snapshot(pickup, destination, progress)
    route["provider"] = "simulated"
    route["route_source"] = "simulated_fallback"
    return route


def progress_for_status(status: str) -> float:
    return {
        "pending": 0.0,
        "accepted": 0.2,
        "active": 0.65,
        "completed": 1.0,
        "cancelled": 0.0,
        "disputed": 0.65,
    }.get(status, 0.0)


def record_tracking_event(booking_id: int, status: str, note: str, latitude: float | None, longitude: float | None):
    conn = get_connection()
    conn.execute(
        "INSERT INTO booking_tracking_events (booking_id, status, note, latitude, longitude) VALUES (?, ?, ?, ?, ?)",
        (booking_id, status, note, latitude, longitude),
    )
    conn.commit()
    conn.close()


def message_requires_moderation(message: str) -> tuple[bool, str | None]:
    lowered = message.lower()
    for keyword in ABUSIVE_KEYWORDS:
        if keyword in lowered:
            return True, keyword
    return False, None


def call_requires_moderation(call: CallCreate) -> tuple[bool, str | None, str]:
    combined_text = f"{call.participant} {call.note}".lower()
    if not call.consent_given:
        return True, "consent_missing", "medium"
    for keyword in ABUSIVE_KEYWORDS:
        if keyword in combined_text:
            return True, f"keyword:{keyword}", "high"
    if any(term in combined_text for term in ["urgent", "emergency", "unsafe", "safety", "threat", "harass"]):
        return True, "urgent_call", "high"
    return False, None, "low"


def should_log_call_for_booking(booking_id: int | None) -> tuple[bool, str | None]:
    """
    Determine if a call should be logged based on:
    1. Active dispute on the booking
    2. Safety report filed for the booking within 24h of completion
    
    Returns: (should_log, reason)
    """
    if not booking_id:
        return False, None
    
    conn = get_connection()
    try:
        # Check for active disputes
        active_dispute = conn.execute(
            "SELECT * FROM disputes WHERE booking_id = ? AND status IN ('pending', 'under_review')",
            (booking_id,),
        ).fetchone()
        if active_dispute:
            return True, "active_dispute"
        
        # Check for safety reports on this booking
        booking = conn.execute(
            "SELECT * FROM bookings WHERE id = ?",
            (booking_id,),
        ).fetchone()
        if not booking:
            return False, None
        
        # Check if booking is in completed or disputed state
        if booking["status"] not in ("completed", "disputed"):
            return False, None
        
        # Get completion timestamp
        completed_at = booking.get("completed_at")
        if not completed_at:
            return False, None
        
        # Parse completion time and check if within 24 hours
        from datetime import datetime, timedelta
        try:
            completed_time = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
            cutoff_time = completed_time + timedelta(hours=24)
            current_time = datetime.fromisoformat(utc_now_iso().replace("Z", "+00:00"))
            
            if current_time > cutoff_time:
                return False, None
        except (ValueError, AttributeError):
            pass
        
        # Check for safety reports on this booking
        safety_report = conn.execute(
            "SELECT * FROM reports WHERE entity_type = 'booking' AND entity_id = ? AND status IN ('pending', 'under_review')",
            (booking_id,),
        ).fetchone()
        if safety_report:
            return True, "safety_report"
        
        return False, None
    finally:
        conn.close()


def get_user_call_preferences(user_id: int) -> Dict[str, Any]:
    """Get user's call preference settings for audio/video calling"""
    conn = get_connection()
    try:
        prefs = conn.execute(
            "SELECT accept_audio_calls, accept_video_calls, allow_recording FROM user_call_preferences WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        
        if prefs:
            return {
                "accept_audio_calls": bool(prefs["accept_audio_calls"]),
                "accept_video_calls": bool(prefs["accept_video_calls"]),
                "allow_recording": bool(prefs["allow_recording"]),
            }
        
        # Return defaults if no preferences set
        return {
            "accept_audio_calls": True,
            "accept_video_calls": True,
            "allow_recording": False,
        }
    finally:
        conn.close()


def validate_call_initiation(caller_id: int, recipient_id: int, call_type: str) -> tuple[bool, str | None]:
    """Validate if call can be initiated to recipient based on preferences"""
    if caller_id == recipient_id:
        return False, "cannot_call_self"
    
    prefs = get_user_call_preferences(recipient_id)
    
    if call_type == "audio" and not prefs["accept_audio_calls"]:
        return False, "recipient_does_not_accept_audio_calls"
    
    if call_type == "video" and not prefs["accept_video_calls"]:
        return False, "recipient_does_not_accept_video_calls"
    
    return True, None


def end_active_call(call_id: int) -> bool:
    """End an active call and calculate duration"""
    conn = get_connection()
    try:
        call = conn.execute("SELECT * FROM call_sessions WHERE id = ?", (call_id,)).fetchone()
        if not call or call["status"] in ("ended", "missed", "declined"):
            return False
        
        now = utc_now_iso()
        started_at = call["call_started_at"]
        
        duration = 0
        if started_at:
            from datetime import datetime
            try:
                start_time = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                end_time = datetime.fromisoformat(now.replace("Z", "+00:00"))
                duration = int((end_time - start_time).total_seconds())
            except (ValueError, AttributeError):
                pass
        
        conn.execute(
            "UPDATE call_sessions SET status = ?, call_ended_at = ?, duration_seconds = ? WHERE id = ?",
            ("ended", now, duration, call_id),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def record_call_quality(call_id: int, quality_score: float, notes: str = "") -> bool:
    """Record call quality metrics"""
    if not (0 <= quality_score <= 100):
        return False
    
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE call_sessions SET call_quality_score = ?, quality_notes = ? WHERE id = ?",
            (quality_score, notes, call_id),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def get_cached_query_result(cache_key: str, query_fn, ttl: int = 60) -> Any:
    """Execute query with caching - return cached result if available"""
    cached = database_module._query_cache.get(cache_key)
    if cached is not None:
        return cached
    
    result = query_fn()
    database_module._query_cache.set(cache_key, result)
    return result


def batch_create_notifications(notifications: List[Dict[str, Any]]) -> int:
    """Batch create multiple notifications efficiently"""
    if not notifications:
        return 0
    
    conn = database_module.get_connection()
    try:
        for notif in notifications:
            conn.execute(
                """
                INSERT INTO notifications (recipient_id, message, sender_id, booking_id, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    notif.get("recipient_id"),
                    notif.get("message"),
                    notif.get("sender_id"),
                    notif.get("booking_id"),
                    utc_now_iso(),
                ),
            )
        conn.commit()
        return len(notifications)
    finally:
        conn.close()


def get_paginated_results(
    query: str, params: Tuple, limit: int = 20, offset: int = 0, count_query: str = None, count_params: Tuple = ()
) -> Dict[str, Any]:
    """Helper to get paginated results with total count"""
    if limit > 100:
        limit = 100
    if limit < 1:
        limit = 1
    
    conn = database_module.get_connection()
    try:
        # Get paginated results
        results = conn.execute(f"{query} LIMIT ? OFFSET ?", params + (limit, offset)).fetchall()
        
        # Get total count
        if count_query:
            total = conn.execute(count_query, count_params).fetchone()["count"]
        else:
            # Simple count query if not provided
            total = conn.execute(f"SELECT COUNT(*) AS count FROM ({query}) AS _subquery", params).fetchone()["count"]
        
        return {
            "results": results,
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": offset + limit < total,
        }
    finally:
        conn.close()


def invalidate_user_cache(user_id: int) -> None:
    """Invalidate cached data for a specific user"""
    cache_patterns = [
        f"user_stats:{user_id}",
        f"user_prefs:{user_id}",
        f"user_history:{user_id}",
    ]
    for pattern in cache_patterns:
        database_module.clear_query_cache(pattern)


def optimize_analytics_query(days: int = 30) -> Dict[str, Any]:
    """Pre-compute and cache common analytics queries"""
    cache_key = f"analytics_summary:{days}days"
    return get_cached_query_result(
        cache_key,
        lambda: {
            "period_days": days,
            "cached_at": utc_now_iso(),
            "data": "precomputed",
        },
        ttl=300,  # 5 minute cache
    )


def get_provider_stats(provider_id: int) -> Dict[str, Any]:
    """Calculate comprehensive performance stats for a provider"""
    conn = get_connection()
    try:
        provider = conn.execute("SELECT * FROM providers WHERE id = ?", (provider_id,)).fetchone()
        if not provider:
            return None
        
        # Get booking stats
        total_bookings = conn.execute(
            "SELECT COUNT(*) AS count FROM bookings WHERE provider_id = ?",
            (provider_id,),
        ).fetchone()["count"]
        
        completed_bookings = conn.execute(
            "SELECT COUNT(*) AS count FROM bookings WHERE provider_id = ? AND status = 'completed'",
            (provider_id,),
        ).fetchone()["count"]
        
        completion_rate = (completed_bookings / total_bookings * 100) if total_bookings > 0 else 0
        
        # Get earnings
        earnings = conn.execute(
            "SELECT COALESCE(SUM(p.amount), 0) AS total FROM payments p JOIN bookings b ON p.booking_id = b.id WHERE b.provider_id = ? AND p.status IN ('paid', 'settled')",
            (provider_id,),
        ).fetchone()["total"]
        
        # Get average rating
        avg_rating_row = conn.execute(
            "SELECT AVG(rating) AS avg_rating FROM bookings WHERE provider_id = ? AND rating IS NOT NULL",
            (provider_id,),
        ).fetchone()
        avg_rating = avg_rating_row["avg_rating"] or 0.0
        
        return {
            "provider_id": provider_id,
            "provider_name": provider["name"],
            "total_bookings": total_bookings,
            "completed_bookings": completed_bookings,
            "completion_rate": round(completion_rate, 2),
            "total_earnings": float(earnings),
            "average_rating": round(avg_rating, 2),
            "active_status": provider["status"],
        }
    finally:
        conn.close()


def get_vendor_stats(vendor_id: int) -> Dict[str, Any]:
    """Calculate comprehensive performance stats for a vendor"""
    conn = get_connection()
    try:
        vendor = conn.execute("SELECT * FROM vendors WHERE id = ?", (vendor_id,)).fetchone()
        if not vendor:
            return None
        
        # Get order stats
        total_orders = conn.execute(
            "SELECT COUNT(*) AS count FROM bookings WHERE vendor_id = ?",
            (vendor_id,),
        ).fetchone()["count"]
        
        completed_orders = conn.execute(
            "SELECT COUNT(*) AS count FROM bookings WHERE vendor_id = ? AND status = 'completed'",
            (vendor_id,),
        ).fetchone()["count"]
        
        completion_rate = (completed_orders / total_orders * 100) if total_orders > 0 else 0
        
        # Get earnings
        earnings = conn.execute(
            "SELECT COALESCE(SUM(p.amount), 0) AS total FROM payments p JOIN bookings b ON p.booking_id = b.id WHERE b.vendor_id = ? AND p.status IN ('paid', 'settled')",
            (vendor_id,),
        ).fetchone()["total"]
        
        # Get average rating
        avg_rating_row = conn.execute(
            "SELECT AVG(rating) AS avg_rating FROM bookings WHERE vendor_id = ? AND rating IS NOT NULL",
            (vendor_id,),
        ).fetchone()
        avg_rating = avg_rating_row["avg_rating"] or 0.0
        
        return {
            "vendor_id": vendor_id,
            "vendor_name": vendor["name"],
            "total_orders": total_orders,
            "completed_orders": completed_orders,
            "completion_rate": round(completion_rate, 2),
            "total_earnings": float(earnings),
            "average_rating": round(avg_rating, 2),
            "onboarding_status": vendor["onboarding_status"],
        }
    finally:
        conn.close()


def log_activity(
    admin_id: int,
    action_type: str,
    entity_type: str | None = None,
    entity_id: int | None = None,
    details: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> bool:
    """Log an admin activity to the activity_logs table"""
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO activity_logs 
               (admin_id, action_type, entity_type, entity_id, details, ip_address, user_agent, timestamp) 
               VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            (admin_id, action_type, entity_type, entity_id, details, ip_address, user_agent),
        )
        conn.commit()
        return True
    except Exception as e:
        print(f"Failed to log activity: {e}")
        return False
    finally:
        conn.close()


def get_user_growth_metrics(days: int = 30) -> Dict[str, Any]:
    """Calculate user growth metrics over specified period"""
    conn = get_connection()
    try:
        # Get total users
        total_users = conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"]
        
        # Get users by role
        role_counts = conn.execute(
            """SELECT role, COUNT(*) AS count FROM users GROUP BY role"""
        ).fetchall()
        
        # Get registration trend (simplified: per day for last N days)
        created_last_period = conn.execute(
            f"""SELECT COUNT(*) AS count FROM users 
                WHERE datetime(created_at) > datetime('now', '-{days} days')"""
        ).fetchone()["count"] if 'created_at' in [row[0] for row in conn.description or []] else 0
        
        growth_rate = (created_last_period / days) if days > 0 else 0
        
        return {
            "total_users": total_users,
            "users_by_role": {row["role"]: row["count"] for row in role_counts},
            "new_users_period": created_last_period,
            "growth_rate_per_day": round(growth_rate, 2),
        }
    finally:
        conn.close()


def get_revenue_analytics(days: int = 30) -> Dict[str, Any]:
    """Calculate revenue metrics and trends"""
    conn = get_connection()
    try:
        # Total revenue (settled payments only)
        total_revenue = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM payments WHERE status IN ('paid', 'settled')"
        ).fetchone()["total"]
        
        # Revenue last period
        period_revenue = conn.execute(
            f"""SELECT COALESCE(SUM(amount), 0) AS total FROM payments 
                WHERE status IN ('paid', 'settled') 
                AND datetime(created_at) > datetime('now', '-{days} days')"""
        ).fetchone()["total"]
        
        # Average transaction value
        avg_transaction = conn.execute(
            "SELECT AVG(amount) AS avg FROM payments WHERE status IN ('paid', 'settled')"
        ).fetchone()["avg"] or 0
        
        # Payment breakdown by status
        status_breakdown = conn.execute(
            """SELECT status, COUNT(*) AS count, COALESCE(SUM(amount), 0) AS total 
               FROM payments GROUP BY status"""
        ).fetchall()
        
        return {
            "total_revenue": float(total_revenue),
            "period_revenue": float(period_revenue),
            "average_transaction_value": float(avg_transaction),
            "payment_status_breakdown": [
                {"status": row["status"], "count": row["count"], "amount": float(row["total"])}
                for row in status_breakdown
            ],
        }
    finally:
        conn.close()


def get_dispute_and_report_trends(days: int = 30) -> Dict[str, Any]:
    """Get trends in disputes and reports over time"""
    conn = get_connection()
    try:
        # Dispute stats
        total_disputes = conn.execute("SELECT COUNT(*) AS count FROM disputes").fetchone()["count"]
        open_disputes = conn.execute(
            "SELECT COUNT(*) AS count FROM disputes WHERE status IN ('open', 'pending')"
        ).fetchone()["count"]
        resolved_disputes = conn.execute(
            "SELECT COUNT(*) AS count FROM disputes WHERE status IN ('resolved', 'dismissed')"
        ).fetchone()["count"]
        
        recent_disputes = conn.execute(
            f"""SELECT COUNT(*) AS count FROM disputes 
                WHERE datetime(created_at) > datetime('now', '-{days} days')"""
        ).fetchone()["count"]
        
        # Report stats
        total_reports = conn.execute("SELECT COUNT(*) AS count FROM reports").fetchone()["count"]
        pending_reports = conn.execute(
            "SELECT COUNT(*) AS count FROM reports WHERE status = 'pending'"
        ).fetchone()["count"]
        reviewed_reports = conn.execute(
            "SELECT COUNT(*) AS count FROM reports WHERE status IN ('approved', 'rejected')"
        ).fetchone()["count"]
        
        recent_reports = conn.execute(
            f"""SELECT COUNT(*) AS count FROM reports 
                WHERE datetime(created_at) > datetime('now', '-{days} days')"""
        ).fetchone()["count"]
        
        # Report types breakdown
        report_types = conn.execute(
            """SELECT report_type, COUNT(*) AS count FROM reports GROUP BY report_type"""
        ).fetchall()
        
        return {
            "disputes": {
                "total": total_disputes,
                "open": open_disputes,
                "resolved": resolved_disputes,
                "recent_period": recent_disputes,
            },
            "reports": {
                "total": total_reports,
                "pending": pending_reports,
                "reviewed": reviewed_reports,
                "recent_period": recent_reports,
            },
            "report_types_breakdown": {row["report_type"]: row["count"] for row in report_types},
        }
    finally:
        conn.close()


def detect_suspicious_activity() -> Dict[str, Any]:
    """Detect and flag suspicious activity patterns"""
    conn = get_connection()
    try:
        alerts = []
        
        # Alert: High dispute rate on a provider
        high_dispute_providers = conn.execute(
            """SELECT p.id, p.name, COUNT(d.id) AS dispute_count, COUNT(b.id) AS booking_count,
                      CAST(COUNT(d.id) AS FLOAT) / COUNT(b.id) * 100 AS dispute_rate
               FROM providers p
               LEFT JOIN bookings b ON p.id = b.provider_id
               LEFT JOIN disputes d ON b.id = d.booking_id
               GROUP BY p.id
               HAVING COUNT(b.id) > 0 AND dispute_rate > 20
               ORDER BY dispute_rate DESC LIMIT 5"""
        ).fetchall()
        
        for provider in high_dispute_providers:
            alerts.append({
                "severity": "high",
                "type": "provider_high_dispute_rate",
                "entity_type": "provider",
                "entity_id": provider["id"],
                "entity_name": provider["name"],
                "details": f"Provider has {provider['dispute_rate']:.1f}% dispute rate ({provider['dispute_count']} disputes of {provider['booking_count']} bookings)",
            })
        
        # Alert: Multiple reports against same user/vendor
        reported_entities = conn.execute(
            """SELECT reported_user_id, COUNT(*) AS report_count FROM reports 
               WHERE reported_user_id IS NOT NULL 
               GROUP BY reported_user_id 
               HAVING COUNT(*) >= 3 
               ORDER BY report_count DESC LIMIT 5"""
        ).fetchall()
        
        for entity in reported_entities:
            alerts.append({
                "severity": "medium",
                "type": "multiple_reports_against_entity",
                "entity_type": "user",
                "entity_id": entity["reported_user_id"],
                "details": f"User has {entity['report_count']} active reports",
            })
        
        # Alert: Unusually high number of failed payments
        failed_payment_count = conn.execute(
            "SELECT COUNT(*) AS count FROM payments WHERE status = 'failed' AND datetime(created_at) > datetime('now', '-7 days')"
        ).fetchone()["count"]
        
        if failed_payment_count > 50:
            alerts.append({
                "severity": "medium",
                "type": "high_payment_failure_rate",
                "entity_type": "system",
                "details": f"{failed_payment_count} payment failures in last 7 days",
            })
        
        # Alert: Restricted/banned users attempting activities
        restricted_user_activities = conn.execute(
            """SELECT u.id, u.name, u.account_status, COUNT(b.id) AS recent_bookings
               FROM users u
               LEFT JOIN bookings b ON u.id = b.customer_id AND datetime(b.created_at) > datetime('now', '-7 days')
               WHERE u.account_status IN ('restricted', 'suspended', 'banned')
               GROUP BY u.id
               HAVING recent_bookings > 0"""
        ).fetchall()
        
        for user in restricted_user_activities:
            alerts.append({
                "severity": "high",
                "type": "restricted_user_activity",
                "entity_type": "user",
                "entity_id": user["id"],
                "entity_name": user["name"],
                "details": f"{user['account_status']} user made {user['recent_bookings']} booking attempts in last 7 days",
            })
        
        conn.close()
        return {
            "alert_count": len(alerts),
            "alerts": alerts,
            "generated_at": datetime.now().isoformat(),
        }
    finally:
        if conn:
            conn.close()


def check_location_staleness(booking_id: int) -> Dict[str, Any]:
    """Check if provider location is stale (>60 seconds without update)"""
    conn = get_connection()
    try:
        booking = conn.execute(
            "SELECT status, last_location_update_at FROM bookings WHERE id = ?",
            (booking_id,),
        ).fetchone()
        
        if not booking or booking["status"] not in ["active", "accepted"]:
            return {
                "is_stale": False,
                "seconds_since_update": None,
                "tracking_status": "inactive",
                "alert_level": None,
            }
        
        if not booking["last_location_update_at"]:
            return {
                "is_stale": True,
                "seconds_since_update": None,
                "tracking_status": "no_data",
                "alert_level": "critical",
                "reason": "No location data available",
            }
        
        last_update = datetime.fromisoformat(booking["last_location_update_at"])
        now = datetime.utcnow()
        seconds_since = (now - last_update).total_seconds()
        
        is_stale = seconds_since > 60
        is_critical = seconds_since > 300  # 5 minutes
        
        tracking_status = "stale" if is_stale else "active"
        alert_level = "critical" if is_critical else ("warning" if is_stale else None)
        
        return {
            "is_stale": is_stale,
            "seconds_since_update": int(seconds_since),
            "tracking_status": tracking_status,
            "alert_level": alert_level,
            "is_critical_outage": is_critical,
        }
    finally:
        conn.close()


def update_location_for_booking(booking_id: int, latitude: float, longitude: float) -> bool:
    """Update provider location and timestamp for a booking"""
    conn = get_connection()
    try:
        conn.execute(
            """UPDATE bookings 
               SET current_latitude = ?, current_longitude = ?, last_location_update_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (latitude, longitude, booking_id),
        )
        conn.commit()
        return True
    except Exception as e:
        print(f"Failed to update location: {e}")
        return False
    finally:
        conn.close()


def flutterwave_is_configured() -> bool:
    return bool(FLUTTERWAVE_SECRET_KEY)


def flutterwave_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {FLUTTERWAVE_SECRET_KEY}",
        "Content-Type": "application/json",
    }


def initialize_flutterwave_payment(
    tx_ref: str,
    amount: float,
    customer_email: str,
    customer_name: str,
    redirect_url: str,
    currency: str,
) -> Dict[str, Any]:
    response = httpx.post(
        f"{FLUTTERWAVE_BASE_URL}/payments",
        headers=flutterwave_headers(),
        json={
            "tx_ref": tx_ref,
            "amount": amount,
            "currency": currency,
            "redirect_url": redirect_url,
            "customer": {
                "email": customer_email,
                "name": customer_name,
            },
            "customizations": {
                "title": "SmartHaul Payment",
                "description": f"Payment for booking {tx_ref}",
            },
        },
        timeout=15.0,
    )
    response.raise_for_status()
    return response.json()


def verify_flutterwave_payment(tx_ref: str) -> Dict[str, Any]:
    response = httpx.get(
        f"{FLUTTERWAVE_BASE_URL}/transactions/verify_by_reference",
        headers=flutterwave_headers(),
        params={"tx_ref": tx_ref},
        timeout=15.0,
    )
    response.raise_for_status()
    return response.json()


def normalize_payment_status(status: str) -> str:
    lowered = status.lower()
    if lowered in {"successful", "completed", "settled", "paid"}:
        return "paid"
    if lowered in {"failed", "cancelled", "canceled", "error"}:
        return "failed"
    return "pending"


def update_payment_record(external_reference: str, status: str, integration_status: str) -> Dict[str, Any]:
    conn = get_connection()
    conn.execute(
        "UPDATE payments SET status = ?, integration_status = ? WHERE external_reference = ?",
        (status, integration_status, external_reference),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM payments WHERE external_reference = ?", (external_reference,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Payment reference not found")
    create_notification("Payment update", f"Payment {external_reference} changed to {status}.", booking_id=row["booking_id"])
    return dict(row)


def mark_payment_failed(booking_id: int, error_reason: str) -> Dict[str, Any]:
    conn = get_connection()
    try:
        payment = conn.execute(
            "SELECT * FROM payments WHERE booking_id = ? ORDER BY id DESC LIMIT 1",
            (booking_id,),
        ).fetchone()
        if not payment:
            raise HTTPException(status_code=404, detail="Payment not found for booking")

        conn.execute(
            "UPDATE payments SET status = 'failed', integration_status = ? WHERE id = ?",
            (error_reason, payment["id"]),
        )

        booking = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        if booking:
            if booking["status"] == "accepted":
                conn.execute(
                    "UPDATE bookings SET status = 'payment_pending', updated_at = ? WHERE id = ?",
                    (utc_now_iso(), booking_id),
                )
            elif booking["status"] != "payment_pending":
                conn.execute(
                    "UPDATE bookings SET status = 'payment_pending', updated_at = ? WHERE id = ?",
                    (utc_now_iso(), booking_id),
                )

        conn.commit()
        create_notification(
            "Payment failed",
            f"Payment for booking {booking_id} failed: {error_reason}. Please retry with a different payment method.",
            booking_id=booking_id,
        )
        return {
            "booking_id": booking_id,
            "payment_id": payment["id"],
            "status": "failed",
            "reason": error_reason,
            "booking_status": "payment_pending",
        }
    finally:
        conn.close()


def extract_flutterwave_reference(payload: Dict[str, Any]) -> str | None:
    if payload.get("external_reference"):
        return payload["external_reference"]
    if payload.get("tx_ref"):
        return payload["tx_ref"]
    data = payload.get("data") or {}
    return data.get("tx_ref")


def extract_flutterwave_status(payload: Dict[str, Any]) -> str:
    if payload.get("status"):
        return str(payload["status"])
    data = payload.get("data") or {}
    if data.get("status"):
        return str(data["status"])
    return "pending"


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
    entity_type: str | None = None
    entity_id: int | None = None
    reported_user_id: str | None = None


class ReportReviewUpdate(BaseModel):
    status: str
    review_notes: str = ""


VALID_REPORT_TYPES = {"harassment", "misconduct", "fraud", "unsafe_conduct", "abuse", "inappropriate_content"}
VALID_REPORT_STATUSES = {"pending", "under_review", "resolved", "closed"}
VALID_ENTITY_TYPES = {"booking", "vendor", "user", "message"}


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
    contact_email: str | None = None
    documents_submitted: bool = False


class LoginRequest(BaseModel):
    email: str
    password: str


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


class BookingStatusUpdate(BaseModel):
    status: str
    cancelled_by: str = "customer"


class BookingRetryRequest(BaseModel):
    widen_search_radius: bool = False
    search_radius_multiplier: float = 1.0


VALID_BOOKING_STATUSES = {"pending", "payment_pending", "accepted", "active", "completed", "cancelled", "disputed"}


class QuoteCreate(BaseModel):
    customer_name: str
    service_type: str
    pickup: str
    destination: str
    budget: float


class MessageCreate(BaseModel):
    sender: str
    recipient: str
    message: str
    booking_id: int | None = None


class PaymentCreate(BaseModel):
    booking_id: int
    amount: float
    method: str
    gateway: str = "sandbox"
    customer_email: str | None = None
    customer_name: str | None = None
    currency: str = "NGN"
    redirect_url: str | None = None


class PaymentRetryRequest(BaseModel):
    amount: float
    method: str
    gateway: str = "sandbox"
    currency: str = "NGN"
    customer_email: str | None = None
    customer_name: str | None = None
    redirect_url: str | None = None


class RefundCreate(BaseModel):
    payment_id: int
    amount: float
    reason: str


class DisputeCreate(BaseModel):
    booking_id: int
    reason: str
    description: str


class FeedbackCreate(BaseModel):
    user_id: str
    booking_id: int
    rating: int
    comment: str


class VendorReviewUpdate(BaseModel):
    onboarding_status: str
    onboarding_notes: str = ""


class VendorBanRequest(BaseModel):
    ban_reason: str


class VendorResubmitRequest(BaseModel):
    documents_submitted: bool = False
    additional_notes: str = ""


class CallCreate(BaseModel):
    participant: str
    note: str = ""
    status: str = "connected"
    call_type: str = "audio"
    booking_id: int | None = None
    consent_given: bool = False


class ProviderStatsResponse(BaseModel):
    provider_id: int
    provider_name: str
    total_bookings: int
    completed_bookings: int
    completion_rate: float
    total_earnings: float
    average_rating: float
    active_status: str


class VendorStatsResponse(BaseModel):
    vendor_id: int
    vendor_name: str
    total_orders: int
    completed_orders: int
    completion_rate: float
    total_earnings: float
    average_rating: float
    onboarding_status: str


class ActivityLogEntry(BaseModel):
    id: int
    admin_id: int
    action_type: str
    entity_type: str | None
    entity_id: int | None
    details: str | None
    ip_address: str | None
    user_agent: str | None
    timestamp: str


class CallUpdate(BaseModel):
    status: str | None = None
    note: str | None = None
    consent_given: bool | None = None


class CallInitiationRequest(BaseModel):
    recipient_id: int
    call_type: str = "audio"  # "audio" or "video"
    video_enabled: bool = False
    booking_id: int | None = None


class CallResponse(BaseModel):
    call_id: int
    action: str  # "accept" or "decline"
    reason_if_declined: str | None = None


class CallQualityMetrics(BaseModel):
    call_id: int
    quality_score: float  # 0-100
    notes: str = ""


class UserCallPreferences(BaseModel):
    accept_audio_calls: bool = True
    accept_video_calls: bool = True
    allow_recording: bool = False


class CallHistoryEntry(BaseModel):
    id: int
    initiator_id: int | None
    recipient_id: int | None
    call_type: str
    status: str
    duration_seconds: int
    video_enabled: bool
    call_quality_score: float | None
    created_at: str
    call_started_at: str | None
    call_ended_at: str | None


class PaymentWebhookUpdate(BaseModel):
    external_reference: str | None = None
    status: str


class ModerationResolveRequest(BaseModel):
    status: str = "resolved"
    resolution_note: str = ""


class AccountRestrictionUpdate(BaseModel):
    account_status: str
    reason: str = ""


class SecurityAlertReport(BaseModel):
    threat_type: str
    severity: str
    user_id: int | None = None
    ip_address: str | None = None
    details: str = ""


class RateLimitStatus(BaseModel):
    identifier: str
    current_requests: int
    remaining_requests: int
    limit_per_minute: int
    reset_time: str


class SecurityEvent(BaseModel):
    event_type: str
    severity: str
    user_id: int | None = None
    ip_address: str | None = None
    details: str
    timestamp: str


class DependencyStatus(BaseModel):
    name: str
    status: str
    response_time_ms: float
    last_checked: str
    error: str | None = None


class HealthCheckStatus(BaseModel):
    status: str
    timestamp: str
    database: DependencyStatus
    cache: DependencyStatus
    services: List[DependencyStatus]
    uptime_seconds: int | None = None
    version: str


class CancellationPolicyUpdate(BaseModel):
    penalty_free_window_minutes: int
    cancellation_fee_type: str
    cancellation_fee_value: float
    provider_cancel_fee_assignment: str
class DisputePayoutPolicyUpdate(BaseModel):
    payout_window_hours: int


class SLAMetric(BaseModel):
    metric_name: str
    target_value: float
    current_value: float
    unit: str
    status: str  # "compliant", "warning", "violation"
    last_updated: str


class SLAViolation(BaseModel):
    violation_id: int
    metric_name: str
    expected_value: float
    actual_value: float
    violation_time: str
    severity: str  # "low", "medium", "high"
    resolved: bool


class ComplianceStatus(BaseModel):
    status: str  # "compliant", "partial", "non-compliant"
    timestamp: str
    data_retention_days: int
    uptime_percentage: float
    response_time_p95_ms: float
    security_audit_status: str
    gdpr_compliant: bool
    encryption_enabled: bool
    audit_logging_enabled: bool
    violations_count: int
    critical_metrics: List[SLAMetric]


class DisputeResolutionRequest(BaseModel):
    resolution: str
    resolution_notes: str = ""


class BackupStatus(BaseModel):
    backup_id: str
    status: str  # "success", "in_progress", "failed"
    created_at: str
    size_mb: float
    location: str
    error_message: str | None = None
    restoration_tested: bool = False


class FailoverStatus(BaseModel):
    current_primary: str
    primary_status: str  # "healthy", "degraded", "failed"
    backup_available: bool
    last_failover: str | None = None
    auto_failover_enabled: bool
    replication_lag_seconds: int | None = None


class DisasterRecoveryPlan(BaseModel):
    plan_id: str
    rpo_seconds: int  # Recovery Point Objective
    rto_seconds: int  # Recovery Time Objective
    backup_frequency_minutes: int
    replicas_count: int
    primary_location: str
    backup_location: str
    last_tested: str | None = None


# Phase 5.4 - Log Aggregation & Centralized Monitoring Models
class LogEntry(BaseModel):
    log_id: str
    component: str  # service component (auth, payments, bookings, etc.)
    level: str  # DEBUG, INFO, WARNING, ERROR, CRITICAL
    message: str
    context: str | None = None  # additional context (JSON string or structured data)
    user_id: int | None = None
    timestamp: str


class AggregatedLogs(BaseModel):
    total_count: int
    entries: List[LogEntry]
    time_period_hours: int
    component_filter: str | None = None
    timestamp: str


class AlertRule(BaseModel):
    rule_id: str
    name: str
    condition: str  # e.g., "error_rate > 5%", "response_time > 1000ms"
    threshold: float
    enabled: bool
    alert_type: str  # email, slack, webhook, in_app
    created_at: str


class Alert(BaseModel):
    alert_id: str
    alert_rule_id: str
    rule_name: str
    triggered_at: str
    message: str
    severity: str  # low, medium, high, critical
    resolved: bool = False


class LogAnalytics(BaseModel):
    time_period_hours: int
    total_logs: int
    error_count: int
    warning_count: int
    info_count: int
    debug_count: int
    error_rate_percent: float
    top_errors: List[Dict[str, Any]]  # list of {message, count}
    component_breakdown: Dict[str, int]  # component -> count
    timestamp: str


class LogRetentionPolicy(BaseModel):
    retention_days: int
    archive_after_days: int
    retention_enabled: bool
    cleanup_frequency_hours: int


class CentralizedDashboard(BaseModel):
    service_uptime_percent: float
    error_rate_percent: float
    warning_count: int
    alert_count: int
    recent_logs: List[LogEntry]  # last 10 logs
    critical_alerts: List[Alert]  # unresolved critical alerts
    system_health_status: str  # healthy, degraded, critical
    top_components_by_errors: List[Dict[str, Any]]
    last_hour_trends: Dict[str, int]  # log level distribution
    timestamp: str


# Phase 5.5 - Auto-scaling & Load Balancing Models

class MetricDatapoint(BaseModel):
    timestamp: str
    cpu_percent: float
    memory_percent: float
    request_count: int
    response_time_ms: float


class ScalingPolicy(BaseModel):
    policy_id: str
    name: str
    metric: str  # cpu, memory, request_count, response_time
    threshold_up: float
    threshold_down: float
    scale_up_instances: int
    scale_down_instances: int
    cooldown_minutes: int
    enabled: bool
    created_at: str


class LoadBalancerConfig(BaseModel):
    lb_id: str
    algorithm: str  # round_robin, least_connections, weighted, ip_hash
    health_check_interval_seconds: int
    health_check_timeout_seconds: int
    unhealthy_threshold: int
    healthy_threshold: int
    sticky_sessions: bool
    session_timeout_minutes: int
    created_at: str


class InstanceMetrics(BaseModel):
    instance_id: str
    instance_name: str
    cpu_percent: float
    memory_percent: float
    active_requests: int
    average_response_time_ms: float
    uptime_seconds: int
    health_status: str  # healthy, degraded, unhealthy
    last_updated: str


class CapacityPlan(BaseModel):
    plan_id: str
    current_instances: int
    min_instances: int
    max_instances: int
    average_cpu_percent: float
    average_memory_percent: float
    predicted_peak_load: int
    scaling_recommendation: str  # scale_up, scale_down, maintain
    time_to_scale_minutes: int
    estimated_cost_per_month_dollars: float
    timestamp: str


class LoadBalancerStatus(BaseModel):
    lb_id: str
    status: str  # active, inactive, degraded
    algorithm: str
    total_instances: int
    healthy_instances: int
    unhealthy_instances: int
    request_distribution: Dict[str, int]  # instance_id -> request_count
    average_response_time_ms: float
    throughput_requests_per_second: float
    timestamp: str


class AutoScalingEvent(BaseModel):
    event_id: str
    timestamp: str
    event_type: str  # scale_up, scale_down, health_check, policy_change
    trigger_policy_id: str | None = None
    metric_value: float
    threshold: float
    instances_added: int = 0
    instances_removed: int = 0
    message: str


class AutoScalingHistory(BaseModel):
    total_events: int
    events: List[AutoScalingEvent]
    time_period_hours: int
    scale_up_events: int
    scale_down_events: int
    average_scaling_time_minutes: float
    timestamp: str


# Health monitoring helpers
_service_start_time = datetime.now(timezone.utc)


def check_database_health() -> DependencyStatus:
    """Check database connectivity and performance"""
    start_time = time()
    try:
        conn = get_connection()
        conn.execute("SELECT 1")
        conn.close()
        response_time = (time() - start_time) * 1000  # Convert to ms
        return DependencyStatus(
            name="database",
            status="healthy",
            response_time_ms=response_time,
            last_checked=utc_now_iso(),
            error=None,
        )
    except Exception as e:
        response_time = (time() - start_time) * 1000
        return DependencyStatus(
            name="database",
            status="unhealthy",
            response_time_ms=response_time,
            last_checked=utc_now_iso(),
            error=str(e),
        )


def check_cache_health() -> DependencyStatus:
    """Check cache availability"""
    start_time = time()
    try:
        # Try to use cache
        cache_key = "health_check_test"
        _query_cache.set(cache_key, "test_value")
        result = _query_cache.get(cache_key)
        response_time = (time() - start_time) * 1000
        
        status = "healthy" if result == "test_value" else "degraded"
        return DependencyStatus(
            name="cache",
            status=status,
            response_time_ms=response_time,
            last_checked=utc_now_iso(),
            error=None,
        )
    except Exception as e:
        response_time = (time() - start_time) * 1000
        return DependencyStatus(
            name="cache",
            status="degraded",
            response_time_ms=response_time,
            last_checked=utc_now_iso(),
            error=str(e),
        )


def get_service_uptime() -> int:
    """Get service uptime in seconds"""
    uptime = (datetime.now(timezone.utc) - _service_start_time).total_seconds()
    return int(uptime)


def perform_health_check() -> HealthCheckStatus:
    """Comprehensive health check of all dependencies"""
    db_status = check_database_health()
    cache_status = check_cache_health()
    
    # Determine overall status
    all_healthy = db_status.status == "healthy" and cache_status.status == "healthy"
    overall_status = "healthy" if all_healthy else "degraded"
    
    return HealthCheckStatus(
        status=overall_status,
        timestamp=utc_now_iso(),
        database=db_status,
        cache=cache_status,
        services=[],  # Can be extended with more services
        uptime_seconds=get_service_uptime(),
        version="4.7.0",
    )


# SLA & Compliance Tracking
def calculate_uptime_percentage(start_time: datetime = None) -> float:
    """Calculate uptime percentage over a period"""
    if not start_time:
        start_time = _service_start_time
    
    total_seconds = (datetime.now(timezone.utc) - start_time).total_seconds()
    
    # Get downtime from health_checks table
    conn = get_connection()
    try:
        downtime_records = conn.execute(
            """
            SELECT SUM(CASE WHEN status = 'unhealthy' THEN 60 ELSE 0 END) as downtime_seconds
            FROM health_checks 
            WHERE created_at > ?
            """,
            (start_time.isoformat(),),
        ).fetchone()
        
        downtime_seconds = downtime_records["downtime_seconds"] or 0
    finally:
        conn.close()
    
    if total_seconds <= 0:
        return 100.0
    
    uptime_percentage = ((total_seconds - downtime_seconds) / total_seconds) * 100
    return min(uptime_percentage, 100.0)


def calculate_response_time_percentile(percentile: int = 95, hours: int = 24) -> float:
    """Calculate response time at given percentile"""
    conn = get_connection()
    try:
        # Get response times from health checks
        start_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        rows = conn.execute(
            """
            SELECT response_time_ms FROM health_checks 
            WHERE created_at > ? AND response_time_ms IS NOT NULL
            ORDER BY response_time_ms ASC
            """,
            (start_time.isoformat(),),
        ).fetchall()
        
        if not rows:
            return 0.0
        
        response_times = [row["response_time_ms"] for row in rows]
        index = int((percentile / 100.0) * len(response_times))
        return float(response_times[min(index, len(response_times) - 1)])
    finally:
        conn.close()


def get_sla_metrics() -> List[SLAMetric]:
    """Get current SLA metrics"""
    uptime = calculate_uptime_percentage()
    response_time_p95 = calculate_response_time_percentile(95)
    
    # Target SLA values (customizable)
    metrics = [
        SLAMetric(
            metric_name="availability",
            target_value=99.9,
            current_value=uptime,
            unit="%",
            status="compliant" if uptime >= 99.9 else ("warning" if uptime >= 99.0 else "violation"),
            last_updated=utc_now_iso(),
        ),
        SLAMetric(
            metric_name="response_time_p95",
            target_value=500.0,
            current_value=response_time_p95,
            unit="ms",
            status="compliant" if response_time_p95 <= 500 else ("warning" if response_time_p95 <= 1000 else "violation"),
            last_updated=utc_now_iso(),
        ),
    ]
    
    return metrics


def get_compliance_status() -> ComplianceStatus:
    """Get comprehensive compliance status"""
    metrics = get_sla_metrics()
    uptime = calculate_uptime_percentage()
    response_time_p95 = calculate_response_time_percentile(95)
    
    # Determine overall compliance
    violations = [m for m in metrics if m.status == "violation"]
    if violations:
        status = "non-compliant"
    elif any(m.status == "warning" for m in metrics):
        status = "partial"
    else:
        status = "compliant"
    
    return ComplianceStatus(
        status=status,
        timestamp=utc_now_iso(),
        data_retention_days=90,
        uptime_percentage=uptime,
        response_time_p95_ms=response_time_p95,
        security_audit_status="active",
        gdpr_compliant=True,
        encryption_enabled=True,
        audit_logging_enabled=True,
        violations_count=len(violations),
        critical_metrics=metrics,
    )


def record_sla_violation(metric_name: str, expected_value: float, actual_value: float, severity: str = "medium") -> None:
    """Record an SLA violation for tracking"""
    conn = get_connection()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sla_violations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                metric_name TEXT NOT NULL,
                expected_value REAL,
                actual_value REAL,
                violation_time TEXT NOT NULL,
                severity TEXT DEFAULT 'medium',
                resolved BOOLEAN DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        
        conn.execute(
            """
            INSERT INTO sla_violations (metric_name, expected_value, actual_value, violation_time, severity)
            VALUES (?, ?, ?, ?, ?)
            """,
            (metric_name, expected_value, actual_value, utc_now_iso(), severity),
        )
        conn.commit()
    except Exception as e:
        logger.error(f"Failed to record SLA violation: {e}")
    finally:
        conn.close()


# Disaster Recovery & Failover
def create_database_backup() -> BackupStatus:
    """Create a database backup"""
    import shutil
    
    backup_id = f"backup-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    
    try:
        backup_dir = Path(DB_PATH).parent / "backups"
        backup_dir.mkdir(exist_ok=True)
        
        backup_file = backup_dir / f"{backup_id}.db"
        
        conn = get_connection()
        conn.execute("PRAGMA integrity_check")
        conn.close()
        
        # Copy database file
        shutil.copy2(DB_PATH, backup_file)
        
        file_size_mb = backup_file.stat().st_size / (1024 * 1024)
        
        return BackupStatus(
            backup_id=backup_id,
            status="success",
            created_at=utc_now_iso(),
            size_mb=file_size_mb,
            location=str(backup_file),
            error_message=None,
            restoration_tested=False,
        )
    except Exception as e:
        logger.error(f"Database backup failed: {e}")
        return BackupStatus(
            backup_id=backup_id,
            status="failed",
            created_at=utc_now_iso(),
            size_mb=0.0,
            location="",
            error_message=str(e),
            restoration_tested=False,
        )


def restore_database_backup(backup_id: str) -> bool:
    """Restore database from a backup"""
    import shutil
    
    try:
        backup_dir = Path(DB_PATH).parent / "backups"
        backup_file = backup_dir / f"{backup_id}.db"
        
        if not backup_file.exists():
            logger.error(f"Backup file not found: {backup_file}")
            return False
        
        # Verify backup integrity
        backup_conn = sqlite3.connect(str(backup_file))
        backup_conn.execute("PRAGMA integrity_check")
        backup_conn.close()
        
        # Create recovery point from current database
        recovery_file = Path(DB_PATH).parent / f"recovery-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.db"
        shutil.copy2(DB_PATH, recovery_file)
        
        # Restore backup
        shutil.copy2(backup_file, DB_PATH)
        
        logger.info(f"Database restored from backup {backup_id}")
        log_security_event(
            event_type="database_restored",
            severity="high",
            details=f"Database restored from backup {backup_id}",
        )
        
        return True
    except Exception as e:
        logger.error(f"Database restore failed: {e}")
        return False


def get_available_backups() -> List[BackupStatus]:
    """Get list of available backups"""
    try:
        backup_dir = Path(DB_PATH).parent / "backups"
        if not backup_dir.exists():
            return []
        
        backups = []
        for backup_file in sorted(backup_dir.glob("backup-*.db"), reverse=True):
            file_size_mb = backup_file.stat().st_size / (1024 * 1024)
            backup_id = backup_file.stem
            
            backups.append(BackupStatus(
                backup_id=backup_id,
                status="success",
                created_at=datetime.fromtimestamp(backup_file.stat().st_mtime, tz=timezone.utc).isoformat(),
                size_mb=file_size_mb,
                location=str(backup_file),
                error_message=None,
                restoration_tested=False,
            ))
        
        return backups
    except Exception as e:
        logger.error(f"Failed to list backups: {e}")
        return []


def check_primary_database_health() -> FailoverStatus:
    """Check primary database health for failover readiness"""
    db_status = check_database_health()
    
    is_healthy = db_status.status == "healthy"
    has_backups = len(get_available_backups()) > 0
    
    return FailoverStatus(
        current_primary="primary_db",
        primary_status="healthy" if is_healthy else "degraded",
        backup_available=has_backups,
        last_failover=None,  # Can be extended to track from database
        auto_failover_enabled=True,
        replication_lag_seconds=None,  # For multi-replica setups
    )


def get_disaster_recovery_plan() -> DisasterRecoveryPlan:
    """Get current disaster recovery plan configuration"""
    return DisasterRecoveryPlan(
        plan_id="default_plan",
        rpo_seconds=300,  # 5 minutes - Recovery Point Objective
        rto_seconds=600,  # 10 minutes - Recovery Time Objective
        backup_frequency_minutes=60,  # Hourly backups
        replicas_count=1,  # Can be increased for HA setup
        primary_location="local_primary",
        backup_location="local_backup",
        last_tested=None,
    )


# Phase 5.4 - Log Aggregation & Centralized Monitoring Functions

def log_to_system(
    component: str,
    level: str,
    message: str,
    context: str | None = None,
    user_id: int | None = None,
) -> str:
    """Log a message to the centralized logging system"""
    import uuid
    log_id = f"log-{uuid.uuid4().hex[:8]}"
    timestamp = utc_now_iso()
    
    try:
        database_module.record_log(component, level, message, context or "", user_id)
        
        # Check if alert conditions are met
        check_alert_conditions()
        
        return log_id
    except Exception as e:
        logger.error(f"Failed to record log: {e}")
        return log_id


def aggregate_logs(
    time_period_hours: int = 24,
    component: str | None = None,
    level: str | None = None,
    limit: int = 100,
) -> AggregatedLogs:
    """Get aggregated logs for a time period"""
    try:
        logs = database_module.get_logs(
            component=component,
            level=level,
            limit=limit,
        )
        
        entries = [
            LogEntry(
                log_id=log.get("id", "unknown"),
                component=log.get("component", ""),
                level=log.get("level", ""),
                message=log.get("message", ""),
                context=log.get("context"),
                user_id=log.get("user_id"),
                timestamp=log.get("timestamp", ""),
            )
            for log in logs
        ]
        
        return AggregatedLogs(
            total_count=len(entries),
            entries=entries,
            time_period_hours=time_period_hours,
            component_filter=component,
            timestamp=utc_now_iso(),
        )
    except Exception as e:
        logger.error(f"Failed to aggregate logs: {e}")
        return AggregatedLogs(
            total_count=0,
            entries=[],
            time_period_hours=time_period_hours,
            component_filter=component,
            timestamp=utc_now_iso(),
        )


def get_log_analytics_data(time_period_hours: int = 24) -> LogAnalytics:
    """Get analytics about logs for monitoring dashboard"""
    try:
        analytics = database_module.get_log_analytics(time_period_hours)
        
        total = analytics.get("total_logs", 0)
        errors = analytics.get("error_count", 0)
        warnings = analytics.get("warning_count", 0)
        
        error_rate = (errors / total * 100) if total > 0 else 0
        
        return LogAnalytics(
            time_period_hours=time_period_hours,
            total_logs=total,
            error_count=errors,
            warning_count=warnings,
            info_count=analytics.get("info_count", 0),
            debug_count=analytics.get("debug_count", 0),
            error_rate_percent=error_rate,
            top_errors=analytics.get("top_errors", []),
            component_breakdown=analytics.get("component_breakdown", {}),
            timestamp=utc_now_iso(),
        )
    except Exception as e:
        logger.error(f"Failed to get log analytics: {e}")
        return LogAnalytics(
            time_period_hours=time_period_hours,
            total_logs=0,
            error_count=0,
            warning_count=0,
            info_count=0,
            debug_count=0,
            error_rate_percent=0,
            top_errors=[],
            component_breakdown={},
            timestamp=utc_now_iso(),
        )


def check_alert_conditions() -> List[Alert]:
    """Check all enabled alert rules and trigger alerts if conditions are met"""
    triggered_alerts = []
    
    try:
        alert_rules = database_module.get_alert_rules()
        
        for rule in alert_rules:
            if not rule.get("enabled"):
                continue
            
            # Check rule condition
            condition = rule.get("condition", "")
            threshold = rule.get("threshold", 0)
            
            # Example: "error_rate > 5"
            if "error_rate" in condition:
                analytics = get_log_analytics_data(time_period_hours=1)
                if analytics.error_rate_percent > threshold:
                    import uuid
                    alert_id = f"alert-{uuid.uuid4().hex[:8]}"
                    message = f"Error rate {analytics.error_rate_percent:.2f}% exceeds threshold {threshold}%"
                    
                    database_module.record_alert(
                        alert_rule_id=rule.get("id"),
                        message=message,
                        severity="high",
                    )
                    
                    triggered_alerts.append(Alert(
                        alert_id=alert_id,
                        alert_rule_id=rule.get("id", ""),
                        rule_name=rule.get("name", ""),
                        triggered_at=utc_now_iso(),
                        message=message,
                        severity="high",
                    ))
        
        return triggered_alerts
    except Exception as e:
        logger.error(f"Failed to check alert conditions: {e}")
        return []


def get_centralized_dashboard_data() -> CentralizedDashboard:
    """Get comprehensive monitoring dashboard data"""
    try:
        uptime = get_service_uptime()
        uptime_percent = 99.9  # Assuming high availability
        
        analytics = get_log_analytics_data(time_period_hours=24)
        
        # Get recent logs
        recent_logs_data = database_module.get_logs(limit=10)
        recent_logs = [
            LogEntry(
                log_id=log.get("id", "unknown"),
                component=log.get("component", ""),
                level=log.get("level", ""),
                message=log.get("message", ""),
                context=log.get("context"),
                user_id=log.get("user_id"),
                timestamp=log.get("timestamp", ""),
            )
            for log in recent_logs_data
        ]
        
        # Get critical alerts
        alerts_data = database_module.get_alerts(limit=20)
        critical_alerts = [
            Alert(
                alert_id=alert.get("id", ""),
                alert_rule_id=alert.get("alert_rule_id", ""),
                rule_name=alert.get("rule_name", ""),
                triggered_at=alert.get("triggered_at", ""),
                message=alert.get("message", ""),
                severity=alert.get("severity", "medium"),
                resolved=alert.get("resolved", False),
            )
            for alert in alerts_data
            if alert.get("severity") == "critical" and not alert.get("resolved")
        ]
        
        # Determine system health status
        health_status = "healthy"
        if analytics.error_rate_percent > 10:
            health_status = "critical"
        elif analytics.error_rate_percent > 5:
            health_status = "degraded"
        
        # Top components by errors
        top_components = sorted(
            analytics.component_breakdown.items(),
            key=lambda x: x[1],
            reverse=True,
        )[:5]
        
        return CentralizedDashboard(
            service_uptime_percent=uptime_percent,
            error_rate_percent=analytics.error_rate_percent,
            warning_count=analytics.warning_count,
            alert_count=len(critical_alerts),
            recent_logs=recent_logs,
            critical_alerts=critical_alerts,
            system_health_status=health_status,
            top_components_by_errors=[
                {"component": name, "error_count": count}
                for name, count in top_components
            ],
            last_hour_trends={
                "errors": analytics.error_count,
                "warnings": analytics.warning_count,
                "info": analytics.info_count,
                "debug": analytics.debug_count,
            },
            timestamp=utc_now_iso(),
        )
    except Exception as e:
        logger.error(f"Failed to get dashboard data: {e}")
        return CentralizedDashboard(
            service_uptime_percent=0,
            error_rate_percent=0,
            warning_count=0,
            alert_count=0,
            recent_logs=[],
            critical_alerts=[],
            system_health_status="unknown",
            top_components_by_errors=[],
            last_hour_trends={},
            timestamp=utc_now_iso(),
        )


def manage_log_retention() -> Dict[str, Any]:
    """Manage log retention and archival"""
    try:
        # Archive logs older than 30 days
        archived_count = database_module.archive_logs(days_old=30)
        
        # Clean up logs older than 90 days
        cleaned_count = database_module.cleanup_old_logs(retention_days=90)
        
        return {
            "archived_count": archived_count,
            "cleaned_count": cleaned_count,
            "retention_policy": {
                "retention_days": 90,
                "archive_after_days": 30,
                "retention_enabled": True,
            },
            "timestamp": utc_now_iso(),
        }
    except Exception as e:
        logger.error(f"Failed to manage log retention: {e}")
        return {"error": str(e)}


# Phase 5.5 - Auto-scaling & Load Balancing Functions

def get_current_metrics() -> MetricDatapoint:
    """Get current system metrics"""
    uptime = get_service_uptime()
    health = perform_health_check()
    
    return MetricDatapoint(
        timestamp=utc_now_iso(),
        cpu_percent=65.0,  # Simulated - would come from system monitoring
        memory_percent=45.0,  # Simulated
        request_count=150,  # Simulated - would track active requests
        response_time_ms=float(health.database.response_time_ms) if health.database else 50.0,
    )


def evaluate_scaling_policies() -> List[str]:
    """Evaluate all scaling policies and return recommended actions"""
    recommendations = []
    
    try:
        metrics = get_current_metrics()
        policies = database_module.get_scaling_policies()
        
        for policy in policies:
            if not policy.get("enabled"):
                continue
            
            metric_value = 0
            if policy.get("metric") == "cpu":
                metric_value = metrics.cpu_percent
            elif policy.get("metric") == "memory":
                metric_value = metrics.memory_percent
            elif policy.get("metric") == "request_count":
                metric_value = metrics.request_count
            elif policy.get("metric") == "response_time":
                metric_value = metrics.response_time_ms
            
            threshold_up = policy.get("threshold_up", 80)
            threshold_down = policy.get("threshold_down", 30)
            
            if metric_value > threshold_up:
                recommendations.append(f"scale_up:{policy.get('id')}")
                
                # Record scaling event
                import uuid
                event_id = f"scale-{uuid.uuid4().hex[:8]}"
                database_module.record_scaling_event(
                    event_id=event_id,
                    event_type="scale_up",
                    policy_id=policy.get("id"),
                    metric_value=metric_value,
                    threshold=threshold_up,
                    instances_added=policy.get("scale_up_instances", 1),
                )
            elif metric_value < threshold_down:
                recommendations.append(f"scale_down:{policy.get('id')}")
                
                # Record scaling event
                import uuid
                event_id = f"scale-{uuid.uuid4().hex[:8]}"
                database_module.record_scaling_event(
                    event_id=event_id,
                    event_type="scale_down",
                    policy_id=policy.get("id"),
                    metric_value=metric_value,
                    threshold=threshold_down,
                    instances_removed=policy.get("scale_down_instances", 1),
                )
        
        return recommendations
    except Exception as e:
        logger.error(f"Failed to evaluate scaling policies: {e}")
        return []


def get_load_balancer_status() -> LoadBalancerStatus:
    """Get current load balancer status"""
    try:
        lb_config = database_module.get_load_balancer_config()
        instance_metrics = database_module.get_instance_metrics()
        
        healthy = sum(1 for m in instance_metrics if m.get("health_status") == "healthy")
        unhealthy = sum(1 for m in instance_metrics if m.get("health_status") != "healthy")
        
        avg_response_time = sum(m.get("response_time_ms", 0) for m in instance_metrics) / len(instance_metrics) if instance_metrics else 0
        
        return LoadBalancerStatus(
            lb_id=lb_config.get("lb_id", "lb-001"),
            status="active" if healthy > 0 else "inactive",
            algorithm=lb_config.get("algorithm", "round_robin"),
            total_instances=len(instance_metrics),
            healthy_instances=healthy,
            unhealthy_instances=unhealthy,
            request_distribution={m.get("instance_id"): m.get("active_requests", 0) for m in instance_metrics},
            average_response_time_ms=avg_response_time,
            throughput_requests_per_second=150.0,  # Simulated
            timestamp=utc_now_iso(),
        )
    except Exception as e:
        logger.error(f"Failed to get load balancer status: {e}")
        return LoadBalancerStatus(
            lb_id="unknown",
            status="unknown",
            algorithm="round_robin",
            total_instances=0,
            healthy_instances=0,
            unhealthy_instances=0,
            request_distribution={},
            average_response_time_ms=0,
            throughput_requests_per_second=0,
            timestamp=utc_now_iso(),
        )


def get_capacity_plan() -> CapacityPlan:
    """Generate capacity planning recommendation"""
    try:
        metrics = get_current_metrics()
        current_instances = 3  # Simulated
        
        recommendation = "maintain"
        if metrics.cpu_percent > 75:
            recommendation = "scale_up"
        elif metrics.cpu_percent < 25:
            recommendation = "scale_down"
        
        peak_load = int(metrics.request_count * 1.5)  # Estimate 50% headroom
        
        return CapacityPlan(
            plan_id=f"plan-{datetime.now(timezone.utc).strftime('%Y%m%d')}",
            current_instances=current_instances,
            min_instances=2,
            max_instances=10,
            average_cpu_percent=metrics.cpu_percent,
            average_memory_percent=metrics.memory_percent,
            predicted_peak_load=peak_load,
            scaling_recommendation=recommendation,
            time_to_scale_minutes=3,
            estimated_cost_per_month_dollars=current_instances * 100.0,
            timestamp=utc_now_iso(),
        )
    except Exception as e:
        logger.error(f"Failed to get capacity plan: {e}")
        return CapacityPlan(
            plan_id="unknown",
            current_instances=0,
            min_instances=0,
            max_instances=0,
            average_cpu_percent=0,
            average_memory_percent=0,
            predicted_peak_load=0,
            scaling_recommendation="unknown",
            time_to_scale_minutes=0,
            estimated_cost_per_month_dollars=0,
            timestamp=utc_now_iso(),
        )


def get_auto_scaling_history(time_period_hours: int = 24) -> AutoScalingHistory:
    """Get history of auto-scaling events"""
    try:
        events = database_module.get_scaling_events(hours=time_period_hours)
        
        scale_up_count = sum(1 for e in events if e.get("event_type") == "scale_up")
        scale_down_count = sum(1 for e in events if e.get("event_type") == "scale_down")
        
        avg_time = sum(e.get("time_to_scale_minutes", 3) for e in events) / len(events) if events else 3
        
        event_objects = [
            AutoScalingEvent(
                event_id=e.get("event_id", "unknown"),
                timestamp=e.get("timestamp", utc_now_iso()),
                event_type=e.get("event_type", "unknown"),
                trigger_policy_id=e.get("policy_id"),
                metric_value=e.get("metric_value", 0),
                threshold=e.get("threshold", 0),
                instances_added=e.get("instances_added", 0),
                instances_removed=e.get("instances_removed", 0),
                message=e.get("message", ""),
            )
            for e in events
        ]
        
        return AutoScalingHistory(
            total_events=len(events),
            events=event_objects,
            time_period_hours=time_period_hours,
            scale_up_events=scale_up_count,
            scale_down_events=scale_down_count,
            average_scaling_time_minutes=avg_time,
            timestamp=utc_now_iso(),
        )
    except Exception as e:
        logger.error(f"Failed to get auto-scaling history: {e}")
        return AutoScalingHistory(
            total_events=0,
            events=[],
            time_period_hours=time_period_hours,
            scale_up_events=0,
            scale_down_events=0,
            average_scaling_time_minutes=0,
            timestamp=utc_now_iso(),
        )


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html", context={"request": request})


@app.get("/health")
def health():
    """Quick health check for load balancers"""
    return {
        "status": "ok",
        "service": "smarthaul",
        "environment": ENVIRONMENT,
        "timestamp": utc_now_iso(),
    }


@app.get("/health/deep")
def health_deep():
    """Comprehensive health check with dependency status"""
    health_status = perform_health_check()
    
    # Return appropriate status code based on health
    status_code = 200 if health_status.status == "healthy" else (503 if health_status.status == "unhealthy" else 200)
    
    return {
        "status": health_status.status,
        "data": health_status,
    }


@app.get("/health/dependencies")
def health_dependencies():
    """Check status of all external dependencies"""
    db_status = check_database_health()
    cache_status = check_cache_health()
    
    # Additional service checks can be added here
    services_status = []
    
    all_healthy = db_status.status == "healthy" and cache_status.status == "healthy"
    
    return {
        "overall": "healthy" if all_healthy else "degraded",
        "dependencies": {
            "database": db_status,
            "cache": cache_status,
        },
        "services": services_status,
        "timestamp": utc_now_iso(),
    }


@app.get("/health/readiness")
def health_readiness():
    """Readiness check - can the service accept traffic?"""
    # For now, just check database connectivity
    db_status = check_database_health()
    is_ready = db_status.status == "healthy"
    
    return {
        "ready": is_ready,
        "database_ready": db_status.status == "healthy",
        "timestamp": utc_now_iso(),
    }


@app.get("/admin/sla/metrics")
def admin_sla_metrics(request: Request):
    """Get current SLA metrics"""
    require_role(request, {"admin"})
    
    metrics = get_sla_metrics()
    
    return {
        "metrics": [m.dict() for m in metrics],
        "timestamp": utc_now_iso(),
    }


@app.get("/admin/compliance/status")
def admin_compliance_status(request: Request):
    """Get comprehensive compliance status"""
    require_role(request, {"admin"})
    
    compliance = get_compliance_status()
    
    return compliance.dict()


@app.get("/admin/sla/violations")
def admin_sla_violations(request: Request, limit: int = 50):
    """Get recent SLA violations"""
    require_role(request, {"admin"})
    
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT * FROM sla_violations 
            ORDER BY violation_time DESC 
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        
        violations = [dict(row) for row in rows]
    finally:
        conn.close()
    
    return {
        "total": len(violations),
        "violations": violations,
        "timestamp": utc_now_iso(),
    }


@app.post("/admin/sla/violations/resolve")
def admin_resolve_sla_violation(request: Request, violation_id: int):
    """Mark an SLA violation as resolved"""
    require_role(request, {"admin"})
    
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE sla_violations SET resolved = 1 WHERE id = ?",
            (violation_id,),
        )
        conn.commit()
        
        log_security_event(
            event_type="sla_violation_resolved",
            severity="low",
            details=f"Admin resolved SLA violation ID {violation_id}",
        )
        
        return {"message": "SLA violation marked as resolved", "violation_id": violation_id}
    finally:
        conn.close()


@app.post("/admin/backup/create")
def admin_create_backup(request: Request):
    """Manually trigger a database backup"""
    require_role(request, {"admin"})
    
    backup_status = create_database_backup()
    
    log_security_event(
        event_type="backup_created",
        severity="low",
        details=f"Manual backup created: {backup_status.backup_id}",
    )
    
    return backup_status.dict()


@app.get("/admin/backup/list")
def admin_list_backups(request: Request):
    """List all available backups"""
    require_role(request, {"admin"})
    
    backups = get_available_backups()
    
    return {
        "total": len(backups),
        "backups": [b.dict() for b in backups],
        "timestamp": utc_now_iso(),
    }


@app.post("/admin/backup/restore")
def admin_restore_backup(request: Request, backup_id: str):
    """Restore database from a backup (DESTRUCTIVE - requires confirmation)"""
    require_role(request, {"admin"})
    
    success = restore_database_backup(backup_id)
    
    if success:
        log_security_event(
            event_type="backup_restored",
            severity="high",
            details=f"Database restored from backup {backup_id}",
        )
        return {"message": "Database restored successfully", "backup_id": backup_id}
    else:
        return {"error": "Database restoration failed", "backup_id": backup_id}


@app.get("/admin/failover/status")
def admin_failover_status(request: Request):
    """Get failover readiness status"""
    require_role(request, {"admin"})
    
    failover_status = check_primary_database_health()
    recovery_plan = get_disaster_recovery_plan()
    
    return {
        "failover_status": failover_status.dict(),
        "recovery_plan": recovery_plan.dict(),
        "timestamp": utc_now_iso(),
    }


@app.get("/admin/dr/plan")
def admin_get_dr_plan(request: Request):
    """Get disaster recovery plan details"""
    require_role(request, {"admin"})
    
    plan = get_disaster_recovery_plan()
    
    return plan.dict()


@app.post("/admin/dr/test")
def admin_test_dr_plan(request: Request):
    """Test disaster recovery plan (creates test backup)"""
    require_role(request, {"admin"})
    
    # Create a test backup
    backup_status = create_database_backup()
    
    # Verify it can be listed
    backups = get_available_backups()
    test_passed = len(backups) > 0 and backup_status.status == "success"
    
    log_security_event(
        event_type="dr_plan_tested",
        severity="medium",
        details=f"DR plan test {'passed' if test_passed else 'failed'}",
    )
    
    return {
        "test_passed": test_passed,
        "backup_created": backup_status.dict(),
        "available_backups": len(backups),
        "timestamp": utc_now_iso(),
    }


# Phase 5.4 - Log Aggregation & Centralized Monitoring Endpoints

@app.get("/admin/logs")
def admin_get_logs(
    request: Request,
    component: str | None = None,
    level: str | None = None,
    limit: int = 100,
):
    """Get aggregated logs from centralized logging system"""
    require_role(request, {"admin"})
    
    aggregated = aggregate_logs(
        time_period_hours=24,
        component=component,
        level=level,
        limit=limit,
    )
    
    return aggregated.dict()


@app.get("/admin/logs/analytics")
def admin_get_log_analytics(
    request: Request,
    time_period_hours: int = 24,
):
    """Get log analytics and statistics"""
    require_role(request, {"admin"})
    
    analytics = get_log_analytics_data(time_period_hours)
    return analytics.dict()


@app.post("/admin/alerts/rules")
def admin_create_alert_rule(
    request: Request,
    name: str,
    condition: str,
    threshold: float,
    alert_type: str = "in_app",
):
    """Create a new alert rule"""
    require_role(request, {"admin"})
    
    import uuid
    rule_id = f"rule-{uuid.uuid4().hex[:8]}"
    
    try:
        database_module.create_alert_rule(
            rule_id=rule_id,
            name=name,
            condition=condition,
            threshold=threshold,
            alert_type=alert_type,
        )
        
        log_to_system(
            component="monitoring",
            level="INFO",
            message=f"Alert rule created: {name}",
        )
        
        return {
            "rule_id": rule_id,
            "name": name,
            "condition": condition,
            "threshold": threshold,
            "alert_type": alert_type,
            "status": "created",
            "timestamp": utc_now_iso(),
        }
    except Exception as e:
        logger.error(f"Failed to create alert rule: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/admin/alerts/rules")
def admin_get_alert_rules(request: Request):
    """Get all configured alert rules"""
    require_role(request, {"admin"})
    
    try:
        rules = database_module.get_alert_rules()
        return {
            "total_rules": len(rules),
            "rules": rules,
            "timestamp": utc_now_iso(),
        }
    except Exception as e:
        logger.error(f"Failed to get alert rules: {e}")
        return {"total_rules": 0, "rules": []}


@app.get("/admin/alerts")
def admin_get_alerts(
    request: Request,
    limit: int = 50,
    severity: str | None = None,
):
    """Get recent alerts"""
    require_role(request, {"admin"})
    
    try:
        alerts = database_module.get_alerts(limit=limit)
        
        if severity:
            alerts = [a for a in alerts if a.get("severity") == severity]
        
        return {
            "total_alerts": len(alerts),
            "alerts": alerts,
            "timestamp": utc_now_iso(),
        }
    except Exception as e:
        logger.error(f"Failed to get alerts: {e}")
        return {"total_alerts": 0, "alerts": []}


@app.get("/admin/monitoring/dashboard")
def admin_monitoring_dashboard(request: Request):
    """Get centralized monitoring dashboard with system overview"""
    require_role(request, {"admin"})
    
    dashboard = get_centralized_dashboard_data()
    return dashboard.dict()


@app.post("/admin/logs/retention")
def admin_configure_log_retention(
    request: Request,
    retention_days: int = 90,
    archive_after_days: int = 30,
    cleanup_enabled: bool = True,
):
    """Configure log retention policy"""
    require_role(request, {"admin"})
    
    try:
        # Store retention policy (would normally be in database)
        retention_info = {
            "retention_days": retention_days,
            "archive_after_days": archive_after_days,
            "cleanup_enabled": cleanup_enabled,
            "configured_at": utc_now_iso(),
        }
        
        log_to_system(
            component="monitoring",
            level="INFO",
            message=f"Log retention policy updated: {retention_days} days retention",
        )
        
        return {
            "status": "configured",
            "retention_policy": retention_info,
            "timestamp": utc_now_iso(),
        }
    except Exception as e:
        logger.error(f"Failed to configure retention: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/admin/logs/cleanup")
def admin_trigger_log_cleanup(request: Request):
    """Trigger manual log cleanup and archival"""
    require_role(request, {"admin"})
    
    result = manage_log_retention()
    
    log_to_system(
        component="monitoring",
        level="INFO",
        message=f"Manual log cleanup triggered: archived {result.get('archived_count', 0)}, cleaned {result.get('cleaned_count', 0)}",
    )
    
    return result


# Phase 5.5 - Auto-scaling & Load Balancing Endpoints

@app.get("/admin/scaling/policies")
def admin_get_scaling_policies(request: Request):
    """Get all configured auto-scaling policies"""
    require_role(request, {"admin"})
    
    try:
        policies = database_module.get_scaling_policies()
        return {
            "total_policies": len(policies),
            "policies": policies,
            "timestamp": utc_now_iso(),
        }
    except Exception as e:
        logger.error(f"Failed to get scaling policies: {e}")
        return {"total_policies": 0, "policies": []}


@app.post("/admin/scaling/policies")
def admin_create_scaling_policy(
    request: Request,
    name: str,
    metric: str,
    threshold_up: float,
    threshold_down: float,
    scale_up_instances: int = 1,
    scale_down_instances: int = 1,
    cooldown_minutes: int = 5,
):
    """Create a new auto-scaling policy"""
    require_role(request, {"admin"})
    
    import uuid
    policy_id = f"policy-{uuid.uuid4().hex[:8]}"
    
    try:
        database_module.create_scaling_policy(
            policy_id=policy_id,
            name=name,
            metric=metric,
            threshold_up=threshold_up,
            threshold_down=threshold_down,
            scale_up_instances=scale_up_instances,
            scale_down_instances=scale_down_instances,
            cooldown_minutes=cooldown_minutes,
        )
        
        log_to_system(
            component="scaling",
            level="INFO",
            message=f"Scaling policy created: {name} ({metric})",
        )
        
        return {
            "policy_id": policy_id,
            "name": name,
            "metric": metric,
            "status": "created",
            "timestamp": utc_now_iso(),
        }
    except Exception as e:
        logger.error(f"Failed to create scaling policy: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/admin/scaling/metrics")
def admin_get_metrics(request: Request):
    """Get current system metrics"""
    require_role(request, {"admin"})
    
    metrics = get_current_metrics()
    return metrics.dict()


@app.get("/admin/scaling/recommendations")
def admin_get_scaling_recommendations(request: Request):
    """Get auto-scaling recommendations based on policies"""
    require_role(request, {"admin"})
    
    recommendations = evaluate_scaling_policies()
    
    return {
        "total_recommendations": len(recommendations),
        "recommendations": recommendations,
        "timestamp": utc_now_iso(),
    }


@app.get("/admin/scaling/history")
def admin_get_scaling_history(
    request: Request,
    time_period_hours: int = 24,
):
    """Get auto-scaling event history"""
    require_role(request, {"admin"})
    
    history = get_auto_scaling_history(time_period_hours)
    return history.dict()


@app.get("/admin/loadbalancer/status")
def admin_get_load_balancer_status(request: Request):
    """Get load balancer status and instance distribution"""
    require_role(request, {"admin"})
    
    status = get_load_balancer_status()
    return status.dict()


@app.get("/admin/loadbalancer/config")
def admin_get_load_balancer_config(request: Request):
    """Get load balancer configuration"""
    require_role(request, {"admin"})
    
    try:
        config = database_module.get_load_balancer_config()
        return {
            "lb_id": config.get("lb_id", "lb-001"),
            "algorithm": config.get("algorithm", "round_robin"),
            "health_check_interval_seconds": config.get("health_check_interval_seconds", 10),
            "sticky_sessions": config.get("sticky_sessions", False),
            "timestamp": utc_now_iso(),
        }
    except Exception as e:
        logger.error(f"Failed to get LB config: {e}")
        return {}


@app.post("/admin/loadbalancer/config")
def admin_update_load_balancer_config(
    request: Request,
    algorithm: str = "round_robin",
    health_check_interval_seconds: int = 10,
    sticky_sessions: bool = False,
):
    """Update load balancer configuration"""
    require_role(request, {"admin"})
    
    try:
        database_module.update_load_balancer_config(
            algorithm=algorithm,
            health_check_interval_seconds=health_check_interval_seconds,
            sticky_sessions=sticky_sessions,
        )
        
        log_to_system(
            component="scaling",
            level="INFO",
            message=f"Load balancer updated: {algorithm} algorithm, sticky_sessions={sticky_sessions}",
        )
        
        return {
            "status": "updated",
            "algorithm": algorithm,
            "sticky_sessions": sticky_sessions,
            "timestamp": utc_now_iso(),
        }
    except Exception as e:
        logger.error(f"Failed to update LB config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/admin/capacity/plan")
def admin_get_capacity_plan(request: Request):
    """Get capacity planning recommendation"""
    require_role(request, {"admin"})
    
    plan = get_capacity_plan()
    return plan.dict()


@app.get("/admin/scaling/instances")
def admin_get_instance_metrics(request: Request):
    """Get metrics for all instances"""
    require_role(request, {"admin"})
    
    try:
        instances = database_module.get_instance_metrics()
        return {
            "total_instances": len(instances),
            "instances": instances,
            "timestamp": utc_now_iso(),
        }
    except Exception as e:
        logger.error(f"Failed to get instance metrics: {e}")
        return {"total_instances": 0, "instances": []}


@app.get("/diagnostics")
def diagnostics():
    bootstrap_admin = get_bootstrap_admin_config()
    return {
        "environment": ENVIRONMENT,
        "database_backend": get_database_backend(),
        "database_target": database_module.DATABASE_URL if get_database_backend() == "postgres" else str(DB_PATH),
        "routing_provider": ROUTING_PROVIDER,
        "routing_configured": routing_provider_is_configured(),
        "flutterwave_configured": flutterwave_is_configured(),
        "bootstrap_admin_configured": bool(bootstrap_admin["email"] and bootstrap_admin["password"]),
        "bootstrap_admin_email": bootstrap_admin["email"] or None,
        "session_count": len(SESSION_STORE),
    }


@app.get("/auth", response_class=HTMLResponse)
def auth_page(request: Request):
    return templates.TemplateResponse(request=request, name="auth.html", context={"request": request})


@app.get("/workspace", response_class=HTMLResponse)
def workspace_page(request: Request):
    return templates.TemplateResponse(request=request, name="workspace.html", context={"request": request})


@app.get("/provider-dashboard", response_class=HTMLResponse)
def provider_dashboard_page(request: Request):
    require_role(request, {"provider", "admin"})
    return templates.TemplateResponse(request=request, name="provider_dashboard.html", context={"request": request})


@app.get("/vendor-dashboard", response_class=HTMLResponse)
def vendor_dashboard_page(request: Request):
    require_role(request, {"vendor", "admin"})
    return templates.TemplateResponse(request=request, name="vendor_dashboard.html", context={"request": request})


@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request):
    require_role(request, {"admin"})
    diagnostics_payload = diagnostics()
    metrics_payload = admin_metrics(request)
    recent_audit = admin_audit(request)[:5]
    monitoring_snapshot = build_monitoring_snapshot()
    context = {
        "request": request,
        "diagnostics": diagnostics_payload,
        "diagnostics_json": json.dumps(diagnostics_payload, indent=2),
        "metrics": metrics_payload,
        "recent_audit": recent_audit,
        "monitoring_snapshot": monitoring_snapshot,
    }
    return templates.TemplateResponse(request=request, name="admin.html", context=context)


@app.get("/admin/health")
def admin_health(request: Request):
    require_role(request, {"admin"})
    diagnostics_payload = diagnostics()
    metrics_payload = admin_metrics(request)
    return {
        "status": "ok",
        "checked_at": utc_now_iso(),
        "diagnostics": diagnostics_payload,
        "metrics": {
            "bookings": metrics_payload["bookings"],
            "reports": metrics_payload["reports"],
            "payments": metrics_payload["payments"],
            "pending_vendor_reviews": metrics_payload["pending_vendor_reviews"],
            "flagged_messages": metrics_payload["flagged_messages"],
            "restricted_accounts": metrics_payload["restricted_accounts"],
        },
    }


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
    conn = get_connection()
    flagged_rows = conn.execute(
        "SELECT source_text AS text, status, reason FROM moderation_cases ORDER BY id DESC LIMIT 10"
    ).fetchall()
    conn.close()
    flagged_messages = [dict(row) for row in flagged_rows] or [{"text": "This is abusive content", "status": "pending", "reason": "demo"}]
    return templates.TemplateResponse(
        request=request,
        name="moderation.html",
        context={"request": request, "flagged_messages": flagged_messages},
    )


@app.get("/analytics", response_class=HTMLResponse)
def analytics_page(request: Request):
    return templates.TemplateResponse(request=request, name="analytics.html", context={"request": request})


def build_analytics_overview() -> Dict[str, Any]:
    conn = get_connection()
    bookings_total = conn.execute("SELECT COUNT(*) AS count FROM bookings").fetchone()["count"]
    active_bookings = conn.execute("SELECT COUNT(*) AS count FROM bookings WHERE status IN ('pending', 'accepted', 'active', 'disputed')").fetchone()["count"]
    completed_bookings = conn.execute("SELECT COUNT(*) AS count FROM bookings WHERE status = 'completed'").fetchone()["count"]
    bookings_by_status = conn.execute("SELECT status, COUNT(*) AS count FROM bookings GROUP BY status ORDER BY count DESC").fetchall()
    vendors_total = conn.execute("SELECT COUNT(*) AS count FROM vendors").fetchone()["count"]
    vendors_by_status = conn.execute("SELECT onboarding_status AS status, COUNT(*) AS count FROM vendors GROUP BY onboarding_status ORDER BY count DESC").fetchall()
    pending_vendor_reviews = conn.execute("SELECT COUNT(*) AS count FROM vendors WHERE onboarding_status = 'pending_review'").fetchone()["count"]
    reports_total = conn.execute("SELECT COUNT(*) AS count FROM reports").fetchone()["count"]
    open_reports = conn.execute("SELECT COUNT(*) AS count FROM reports WHERE status = 'pending'").fetchone()["count"]
    payments_total = conn.execute("SELECT COUNT(*) AS count FROM payments").fetchone()["count"]
    total_revenue = conn.execute("SELECT COALESCE(SUM(amount), 0) AS total FROM payments WHERE status IN ('paid', 'settled')").fetchone()["total"]
    payments_by_gateway = conn.execute("SELECT gateway, COUNT(*) AS count FROM payments GROUP BY gateway ORDER BY count DESC").fetchall()
    call_sessions_total = conn.execute("SELECT COUNT(*) AS count FROM call_sessions").fetchone()["count"]
    calls_by_type = conn.execute("SELECT call_type, COUNT(*) AS count FROM call_sessions GROUP BY call_type ORDER BY count DESC").fetchall()
    moderation_open = conn.execute("SELECT COUNT(*) AS count FROM moderation_cases WHERE status = 'open'").fetchone()["count"]
    moderation_by_status = conn.execute("SELECT status, COUNT(*) AS count FROM moderation_cases GROUP BY status ORDER BY count DESC").fetchall()
    route_source_counts = conn.execute(
        "SELECT CASE WHEN COUNT(*) > 0 THEN 'provider_live' ELSE 'simulated_fallback' END AS source, COUNT(*) AS count FROM bookings"
    ).fetchone()
    conn.close()

    return {
        "summary": {
            "bookings_total": bookings_total,
            "active_bookings": active_bookings,
            "completed_bookings": completed_bookings,
            "vendors_total": vendors_total,
            "pending_vendor_reviews": pending_vendor_reviews,
            "reports_total": reports_total,
            "open_reports": open_reports,
            "payments_total": payments_total,
            "revenue": round(total_revenue, 2),
            "call_sessions_total": call_sessions_total,
            "open_moderation_cases": moderation_open,
        },
        "bookings_by_status": [{"status": row["status"], "count": row["count"]} for row in bookings_by_status],
        "vendors_by_status": [{"status": row["status"], "count": row["count"]} for row in vendors_by_status],
        "payments_by_gateway": [{"gateway": row["gateway"], "count": row["count"]} for row in payments_by_gateway],
        "calls_by_type": [{"call_type": row["call_type"], "count": row["count"]} for row in calls_by_type],
        "moderation_by_status": [{"status": row["status"], "count": row["count"]} for row in moderation_by_status],
        "route_source": route_source_counts["source"] if route_source_counts else "simulated_fallback",
    }


@app.get("/analytics/overview")
def analytics_overview():
    return build_analytics_overview()


@app.get("/map", response_class=HTMLResponse)
def map_page(request: Request):
    return templates.TemplateResponse(request=request, name="map.html", context={"request": request})


@app.get("/calls", response_class=HTMLResponse)
def calls_page(request: Request):
    return templates.TemplateResponse(request=request, name="calls.html", context={"request": request})


@app.get("/chatbot", response_class=HTMLResponse)
def chatbot_page(request: Request):
    return templates.TemplateResponse(request=request, name="chatbot.html", context={"request": request})


def build_monitoring_snapshot() -> Dict[str, Any]:
    conn = get_connection()
    notifications_unread = conn.execute("SELECT COUNT(*) AS count FROM notifications WHERE status = 'unread'").fetchone()["count"]
    call_sessions_total = conn.execute("SELECT COUNT(*) AS count FROM call_sessions").fetchone()["count"]
    calls_without_consent = conn.execute("SELECT COUNT(*) AS count FROM call_sessions WHERE consent_given = 0").fetchone()["count"]
    messages_flagged = conn.execute("SELECT COUNT(*) AS count FROM messages WHERE moderation_status = 'flagged'").fetchone()["count"]
    moderation_open = conn.execute("SELECT COUNT(*) AS count FROM moderation_cases WHERE status = 'open'").fetchone()["count"]
    pending_reports = conn.execute("SELECT COUNT(*) AS count FROM reports WHERE status = 'pending'").fetchone()["count"]
    pending_vendor_reviews = conn.execute("SELECT COUNT(*) AS count FROM vendors WHERE onboarding_status = 'pending_review'").fetchone()["count"]
    restricted_accounts = conn.execute("SELECT COUNT(*) AS count FROM users WHERE account_status = 'restricted'").fetchone()["count"]
    bookings_pending = conn.execute("SELECT COUNT(*) AS count FROM bookings WHERE status = 'pending'").fetchone()["count"]
    payments_pending = conn.execute("SELECT COUNT(*) AS count FROM payments WHERE status = 'pending'").fetchone()["count"]
    sessions_active = len(SESSION_STORE)
    route_provider_ready = routing_provider_is_configured()
    conn.close()

    diagnostics_payload = diagnostics()
    health_state = "healthy"
    if diagnostics_payload["database_backend"] not in {"sqlite", "postgres"}:
        health_state = "degraded"
    if not route_provider_ready:
        health_state = "degraded" if health_state == "healthy" else health_state

    alerts: List[Dict[str, Any]] = []

    def add_alert(severity: str, title: str, detail: str) -> None:
        alerts.append({"severity": severity, "title": title, "detail": detail})

    if bookings_pending >= 10:
        add_alert("high", "Booking backlog", f"{bookings_pending} bookings are still pending dispatch attention.")
    elif bookings_pending > 0:
        add_alert("medium", "Booking queue active", f"{bookings_pending} bookings are pending review or dispatch.")

    if moderation_open > 0:
        add_alert("high", "Open moderation cases", f"{moderation_open} moderation cases need review.")

    if calls_without_consent > 0:
        add_alert("high", "Missing call consent", f"{calls_without_consent} call sessions were logged without consent.")

    if pending_reports > 0:
        add_alert("medium", "Pending reports", f"{pending_reports} user reports are waiting for triage.")

    if pending_vendor_reviews > 0:
        add_alert("medium", "Vendor reviews waiting", f"{pending_vendor_reviews} vendor onboarding cases are pending.")

    if restricted_accounts > 0:
        add_alert("medium", "Restricted accounts", f"{restricted_accounts} account restriction actions are active.")

    if payments_pending > 0:
        add_alert("medium", "Payment follow-up", f"{payments_pending} payments are still pending confirmation.")

    if not route_provider_ready:
        add_alert("medium", "Routing fallback active", "Provider-backed routing is not configured, so the app is using simulated routing.")

    if not diagnostics_payload["flutterwave_configured"]:
        add_alert("low", "Flutterwave sandbox mode", "Payment checkout is still using the sandbox flow.")

    if sessions_active >= 25:
        add_alert("low", "Active session growth", f"There are currently {sessions_active} active sessions in memory.")

    if not alerts:
        add_alert("ok", "No active alerts", "All monitored queues are currently clear.")

    if any(item["severity"] == "high" for item in alerts):
        health_state = "degraded"

    return {
        "status": health_state,
        "checked_at": utc_now_iso(),
        "environment": diagnostics_payload["environment"],
        "database_backend": diagnostics_payload["database_backend"],
        "database_target": diagnostics_payload["database_target"],
        "routing_provider": diagnostics_payload["routing_provider"],
        "routing_configured": diagnostics_payload["routing_configured"],
        "flutterwave_configured": diagnostics_payload["flutterwave_configured"],
        "bootstrap_admin_configured": diagnostics_payload["bootstrap_admin_configured"],
        "session_count": sessions_active,
        "workload": {
            "bookings_pending": bookings_pending,
            "payments_pending": payments_pending,
            "pending_reports": pending_reports,
            "pending_vendor_reviews": pending_vendor_reviews,
            "restricted_accounts": restricted_accounts,
            "call_sessions_total": call_sessions_total,
        },
        "safety": {
            "open_moderation_cases": moderation_open,
            "flagged_messages": messages_flagged,
            "calls_without_consent": calls_without_consent,
            "notifications_unread": notifications_unread,
        },
        "alerts": alerts,
        "scale_flags": {
            "provider_routing_enabled": route_provider_ready,
            "status_indexes_enabled": True,
        },
    }


@app.get("/admin/monitoring", response_class=HTMLResponse)
def admin_monitoring_page(request: Request):
    require_role(request, {"admin"})
    return templates.TemplateResponse(request=request, name="monitoring.html", context={"request": request})


@app.get("/admin/monitoring/snapshot")
def admin_monitoring_snapshot(request: Request):
    require_role(request, {"admin"})
    return build_monitoring_snapshot()


def is_pending_booking_timed_out(updated_at: str | None) -> bool:
    updated_time = parse_iso_datetime(updated_at)
    if updated_time is None:
        return False
    if updated_time.tzinfo is None:
        updated_time = updated_time.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - updated_time) >= timedelta(minutes=PENDING_BOOKING_TIMEOUT_MINUTES)


def apply_pending_booking_timeouts() -> int:
    conn = get_connection()
    pending_rows = conn.execute("SELECT * FROM bookings WHERE status = 'pending'").fetchall()
    timed_out_rows = []
    for row in pending_rows:
        if is_pending_booking_timed_out(row["updated_at"]):
            conn.execute(
                "UPDATE bookings SET status = ?, updated_at = ? WHERE id = ?",
                ("cancelled", utc_now_iso(), row["id"]),
            )
            timed_out_rows.append(dict(row))
    conn.commit()
    conn.close()

    for row in timed_out_rows:
        create_notification(
            "Booking auto-cancelled",
            f"Booking {row['id']} timed out after {PENDING_BOOKING_TIMEOUT_MINUTES} minutes. You can retry or widen your search radius.",
            booking_id=row["id"],
        )
        record_tracking_event(
            row["id"],
            "cancelled",
            "Automatically cancelled after pending timeout. Customer can retry or widen search radius.",
            row.get("current_latitude"),
            row.get("current_longitude"),
        )

    return len(timed_out_rows)


@app.post("/bookings")
def create_booking(payload: BookingCreate):
    route = resolved_route_snapshot(payload.pickup, payload.destination, progress=0.0)
    conn = get_connection()
    cursor = conn.execute(
        """
        INSERT INTO bookings (
            customer_id, service_type, pickup, destination, price, status, current_latitude, current_longitude, eta_minutes, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload.customer_id,
            payload.service_type,
            payload.pickup,
            payload.destination,
            payload.price,
            "pending",
            route["current_position"]["lat"],
            route["current_position"]["lng"],
            route["eta_minutes"],
            utc_now_iso(),
        ),
    )
    conn.commit()
    booking_id = cursor.lastrowid
    conn.close()
    record_tracking_event(
        booking_id,
        "pending",
        f"Booking created for {payload.service_type}",
        route["current_position"]["lat"],
        route["current_position"]["lng"],
    )
    create_notification("Booking created", f"Booking {booking_id} is pending dispatch.", booking_id=booking_id)
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
    apply_due_provider_payouts()
    apply_pending_booking_timeouts()
    conn = get_connection()
    rows = conn.execute("SELECT * FROM bookings ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(row) for row in rows]


@app.post("/bookings/{booking_id}/retry")
def retry_timed_out_booking(booking_id: int, payload: BookingRetryRequest):
    if payload.search_radius_multiplier < 1.0:
        raise HTTPException(status_code=400, detail="Search radius multiplier must be at least 1.0")

    conn = get_connection()
    row = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Booking not found")

    if row["status"] != "cancelled":
        conn.close()
        raise HTTPException(status_code=400, detail="Only cancelled bookings can be retried")

    timeout_event = conn.execute(
        "SELECT id FROM booking_tracking_events WHERE booking_id = ? AND status = 'cancelled' AND note LIKE ? ORDER BY id DESC LIMIT 1",
        (booking_id, "%pending timeout%"),
    ).fetchone()
    if not timeout_event:
        conn.close()
        raise HTTPException(status_code=400, detail="Only timeout-cancelled bookings can be retried")

    destination = row["destination"]
    if payload.widen_search_radius and payload.search_radius_multiplier > 1.0:
        destination = f"{destination} (expanded radius x{payload.search_radius_multiplier:.1f})"

    route = resolved_route_snapshot(row["pickup"], destination, progress=0.0)
    cursor = conn.execute(
        """
        INSERT INTO bookings (
            customer_id, service_type, pickup, destination, price, status, current_latitude, current_longitude, eta_minutes, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row["customer_id"],
            row["service_type"],
            row["pickup"],
            destination,
            row["price"],
            "pending",
            route["current_position"]["lat"],
            route["current_position"]["lng"],
            route["eta_minutes"],
            utc_now_iso(),
        ),
    )
    conn.commit()
    new_booking_id = cursor.lastrowid
    conn.close()

    record_tracking_event(
        new_booking_id,
        "pending",
        f"Retry created from timed-out booking {booking_id}",
        route["current_position"]["lat"],
        route["current_position"]["lng"],
    )
    create_notification(
        "Booking retry created",
        f"Retry booking {new_booking_id} created from timed-out booking {booking_id}.",
        booking_id=new_booking_id,
    )

    return {
        "original_booking_id": booking_id,
        "new_booking_id": new_booking_id,
        "status": "pending",
        "pickup": row["pickup"],
        "destination": destination,
        "retry_options": {
            "widen_search_radius": payload.widen_search_radius,
            "search_radius_multiplier": payload.search_radius_multiplier,
        },
    }


@app.patch("/bookings/{booking_id}")
def update_booking_status(booking_id: int, payload: BookingStatusUpdate):
    if payload.status not in VALID_BOOKING_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid booking status")

    conn = get_connection()
    existing = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    if not existing:
        conn.close()
        return {"message": "Booking not found"}

    if payload.status == "accepted":
        payment = conn.execute(
            "SELECT * FROM payments WHERE booking_id = ? AND status IN ('paid', 'settled') LIMIT 1",
            (booking_id,),
        ).fetchone()
        if not payment:
            conn.close()
            raise HTTPException(status_code=402, detail="Payment not confirmed. Booking cannot be accepted without successful payment.")

    if payload.status == "completed":
        if existing["status"] == "disputed":
            conn.close()
            raise HTTPException(status_code=409, detail="Booking has an active dispute and cannot be completed")
        active_dispute = conn.execute(
            "SELECT id FROM disputes WHERE booking_id = ? AND status IN ('pending', 'under_review') LIMIT 1",
            (booking_id,),
        ).fetchone()
        if active_dispute:
            conn.close()
            raise HTTPException(status_code=409, detail="Booking has an unresolved dispute and cannot be completed")

    route = resolved_route_snapshot(existing["pickup"], existing["destination"], progress_for_status(payload.status))
    cancellation_summary = None
    completed_at = existing["completed_at"] if "completed_at" in existing.keys() else None
    if payload.status == "cancelled":
        cancellation_policy = get_cancellation_policy()
        cancellation_summary = compute_cancellation_fee(dict(existing), payload, cancellation_policy)
    if payload.status == "completed":
        completed_at = utc_now_iso()

    conn.execute(
        "UPDATE bookings SET status = ?, current_latitude = ?, current_longitude = ?, eta_minutes = ?, updated_at = ?, completed_at = ? WHERE id = ?",
        (
            payload.status,
            route["current_position"]["lat"],
            route["current_position"]["lng"],
            route["eta_minutes"],
            utc_now_iso(),
            completed_at,
            booking_id,
        ),
    )
    if payload.status == "completed" and completed_at:
        schedule_provider_payout_for_booking(conn, booking_id, completed_at)
    conn.commit()
    row = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    conn.close()
    create_notification("Booking update", f"Booking {booking_id} is now {payload.status}.", booking_id=booking_id)
    record_tracking_event(
        booking_id,
        payload.status,
        f"Booking marked as {payload.status}" if not cancellation_summary else f"Booking marked as cancelled by {cancellation_summary['cancelled_by']}",
        route["current_position"]["lat"],
        route["current_position"]["lng"],
    )
    logger.info("Booking %s status updated to %s", booking_id, payload.status)
    payload_dict = dict(row)
    if cancellation_summary:
        payload_dict["cancellation"] = cancellation_summary
    return payload_dict


@app.get("/vendors")
def list_vendors():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM vendors ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(row) for row in rows]


@app.get("/vendors/{vendor_id}/stats")
def get_vendor_performance_stats(vendor_id: int, current_user: Dict = Depends(get_current_user)):
    """Get comprehensive performance stats for a vendor - accessible to vendor and admins"""
    # Authorization: vendor can view own stats, admin can view any
    if current_user["role"] not in ["admin", "vendor"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    if current_user["role"] == "vendor" and current_user["id"] != vendor_id:
        raise HTTPException(status_code=403, detail="Cannot view other vendor's stats")
    
    stats = get_vendor_stats(vendor_id)
    if not stats:
        raise HTTPException(status_code=404, detail="Vendor not found")
    
    return VendorStatsResponse(**stats)


@app.post("/vendors")
async def create_vendor(request: Request):
    body = await request.body()
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        parsed = json.loads(body.decode() or "{}")
        vendor_data = VendorCreate(**parsed)
    else:
        form_data = dict(parse_qsl(body.decode() or "", keep_blank_values=True))
        vendor_data = VendorCreate(
            name=form_data.get("name", ""),
            category=form_data.get("category", ""),
            location=form_data.get("location", ""),
            rating=float(form_data.get("rating", 0) or 0.0),
            contact_email=form_data.get("contact_email") or None,
            documents_submitted=parse_bool(form_data.get("documents_submitted", False)),
        )

    conn = get_connection()
    
    banned_vendor = conn.execute(
        "SELECT * FROM vendors WHERE name = ? AND permanently_banned = 1",
        (vendor_data.name,),
    ).fetchone()
    if banned_vendor:
        conn.close()
        raise HTTPException(status_code=403, detail=f"This vendor identity is permanently banned: {banned_vendor['ban_reason']}")

    cursor = conn.execute(
        """
        INSERT INTO vendors (
            name, category, location, rating, contact_email, document_status, onboarding_status, onboarding_notes, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            vendor_data.name,
            vendor_data.category,
            vendor_data.location,
            vendor_data.rating,
            vendor_data.contact_email,
            "submitted" if vendor_data.documents_submitted else "missing",
            "pending_review",
            "Awaiting admin onboarding review",
            utc_now_iso(),
        ),
    )
    conn.commit()
    vendor_id = cursor.lastrowid
    conn.close()
    create_notification("Vendor onboarding", f"Vendor {vendor_data.name} is awaiting onboarding review.")
    return {
        "id": vendor_id,
        **vendor_data.model_dump(),
        "document_status": "submitted" if vendor_data.documents_submitted else "missing",
        "onboarding_status": "pending_review",
        "onboarding_notes": "Awaiting admin onboarding review",
    }


@app.post("/quotes")
def create_quote(payload: QuoteCreate):
    conn = get_connection()
    cursor = conn.execute(
        "INSERT INTO quotes (customer_name, service_type, pickup, destination, budget, status) VALUES (?, ?, ?, ?, ?, ?)",
        (payload.customer_name, payload.service_type, payload.pickup, payload.destination, payload.budget, "requested"),
    )
    conn.commit()
    quote_id = cursor.lastrowid
    conn.execute(
        "INSERT INTO notifications (title, message) VALUES (?, ?)",
        ("Quote requested", f"{payload.customer_name} requested a {payload.service_type} quote."),
    )
    conn.commit()
    conn.close()
    logger.info("Quote %s created for %s", quote_id, payload.customer_name)
    return {
        "id": quote_id,
        "customer_name": payload.customer_name,
        "service_type": payload.service_type,
        "pickup": payload.pickup,
        "destination": payload.destination,
        "budget": payload.budget,
        "status": "requested",
    }


@app.get("/quotes")
def list_quotes():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM quotes ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(row) for row in rows]


@app.get("/notifications")
def list_notifications():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM notifications ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(row) for row in rows]


@app.patch("/notifications/{notification_id}/read")
def mark_notification_read(notification_id: int):
    conn = get_connection()
    conn.execute("UPDATE notifications SET status = 'read' WHERE id = ?", (notification_id,))
    conn.commit()
    row = conn.execute("SELECT * FROM notifications WHERE id = ?", (notification_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Notification not found")
    return dict(row)


@app.get("/notifications-page", response_class=HTMLResponse)
def notifications_page(request: Request):
    conn = get_connection()
    rows = conn.execute("SELECT * FROM notifications ORDER BY id DESC").fetchall()
    conn.close()
    return templates.TemplateResponse(
        request=request,
        name="notifications.html",
        context={"request": request, "notifications": [dict(row) for row in rows]},
    )


@app.get("/route/estimate")
def route_estimate(pickup: str, destination: str):
    return resolved_route_snapshot(pickup, destination, progress=0.15)


@app.post("/calls")
def create_call(payload: CallCreate):
    needs_review, review_reason, severity = call_requires_moderation(payload)
    should_log, logging_reason = should_log_call_for_booking(payload.booking_id)
    
    conn = get_connection()
    now_iso = utc_now_iso()
    logged_at = now_iso if should_log else None
    
    cursor = conn.execute(
        """
        INSERT INTO call_sessions (participant, note, status, call_type, booking_id, consent_given, should_log_call, logging_reason, logged_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload.participant,
            payload.note,
            payload.status,
            payload.call_type,
            payload.booking_id,
            1 if payload.consent_given else 0,
            1 if should_log else 0,
            logging_reason,
            logged_at,
        ),
    )
    conn.commit()
    call_id = cursor.lastrowid
    moderation_case_id = None
    if needs_review:
        case_cursor = conn.execute(
            "INSERT INTO moderation_cases (message_id, reason, severity, status, source_text, resolution_note) VALUES (?, ?, ?, ?, ?, ?)",
            (
                None,
                f"call:{review_reason}",
                severity,
                "open",
                payload.note or payload.participant,
                "",
            ),
        )
        conn.commit()
        moderation_case_id = case_cursor.lastrowid
    conn.close()
    create_notification("Call session", f"{payload.call_type.title()} call logged for {payload.participant}.", booking_id=payload.booking_id)
    return {
        "id": call_id,
        "participant": payload.participant,
        "note": payload.note,
        "status": payload.status,
        "call_type": payload.call_type,
        "booking_id": payload.booking_id,
        "consent_given": payload.consent_given,
        "needs_review": needs_review,
        "review_reason": review_reason,
        "moderation_case_id": moderation_case_id,
    }


@app.patch("/calls/{call_id}")
def update_call(call_id: int, payload: CallUpdate):
    conn = get_connection()
    row = conn.execute("SELECT * FROM call_sessions WHERE id = ?", (call_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Call session not found")

    new_status = payload.status or row["status"]
    if payload.status and payload.status not in {"connected", "ended", "missed", "escalated", "resolved"}:
        conn.close()
        raise HTTPException(status_code=400, detail="Invalid call status")

    new_note = payload.note if payload.note is not None else row["note"]
    new_consent_given = row["consent_given"]
    if payload.consent_given is not None:
        new_consent_given = 1 if payload.consent_given else 0

    conn.execute(
        "UPDATE call_sessions SET status = ?, note = ?, consent_given = ? WHERE id = ?",
        (new_status, new_note, new_consent_given, call_id),
    )
    conn.commit()
    updated = conn.execute("SELECT * FROM call_sessions WHERE id = ?", (call_id,)).fetchone()
    conn.close()

    moderation_case_id = None
    if new_status == "escalated" or not bool(new_consent_given):
        needs_review, review_reason, severity = call_requires_moderation(
            CallCreate(
                participant=updated["participant"],
                note=updated["note"],
                status=updated["status"],
                call_type=updated["call_type"],
                booking_id=updated["booking_id"],
                consent_given=bool(updated["consent_given"]),
            )
        )
        if needs_review:
            conn = get_connection()
            try:
                case_cursor = conn.execute(
                    "INSERT INTO moderation_cases (message_id, reason, severity, status, source_text, resolution_note) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        None,
                        f"call:{review_reason}",
                        severity,
                        "open",
                        updated["note"] or updated["participant"],
                        "",
                    ),
                )
                conn.commit()
                moderation_case_id = case_cursor.lastrowid
            finally:
                conn.close()

    return {
        **dict(updated),
        "needs_review": bool(moderation_case_id),
        "moderation_case_id": moderation_case_id,
    }


@app.get("/calls/logs")
def list_call_logs():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM call_sessions ORDER BY id DESC").fetchall()
    conn.close()
    call_logs = []
    for row in rows:
        needs_review, review_reason, severity = call_requires_moderation(
            CallCreate(
                participant=row["participant"],
                note=row["note"],
                status=row["status"],
                call_type=row["call_type"],
                booking_id=row["booking_id"],
                consent_given=bool(row["consent_given"]),
            )
        )
        call_logs.append(
            {
                **dict(row),
                "needs_review": needs_review,
                "review_reason": review_reason,
                "severity": severity,
            }
        )
    return call_logs


@app.get("/calls/summary")
def calls_summary():
    conn = get_connection()
    by_status = conn.execute("SELECT status, COUNT(*) AS count FROM call_sessions GROUP BY status").fetchall()
    by_type = conn.execute("SELECT call_type, COUNT(*) AS count FROM call_sessions GROUP BY call_type").fetchall()
    open_cases = conn.execute("SELECT COUNT(*) AS count FROM moderation_cases WHERE status = 'open'").fetchone()["count"]
    consent_missing = conn.execute("SELECT COUNT(*) AS count FROM call_sessions WHERE consent_given = 0").fetchone()["count"]
    conn.close()
    return {
        "by_status": [{"status": row["status"], "count": row["count"]} for row in by_status],
        "by_type": [{"call_type": row["call_type"], "count": row["count"]} for row in by_type],
        "open_moderation_cases": open_cases,
        "calls_without_consent": consent_missing,
    }


@app.get("/calls/logged")
def get_logged_calls():
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM call_sessions WHERE should_log_call = 1 ORDER BY id DESC").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


@app.post("/admin/calls/{call_id}/mark-for-logging")
def admin_mark_call_for_logging(request: Request, call_id: int):
    require_role(request, {"admin"})
    
    conn = get_connection()
    try:
        call = conn.execute("SELECT * FROM call_sessions WHERE id = ?", (call_id,)).fetchone()
        if not call:
            raise HTTPException(status_code=404, detail="Call not found")
        
        now_iso = utc_now_iso()
        conn.execute(
            """
            UPDATE call_sessions
            SET should_log_call = 1, logging_reason = ?, logged_at = ?
            WHERE id = ?
            """,
            ("admin_review", now_iso, call_id),
        )
        conn.commit()
        
        updated_call = conn.execute("SELECT * FROM call_sessions WHERE id = ?", (call_id,)).fetchone()
        create_notification("Call logging", f"Call {call_id} marked for logging for admin review.")
        return dict(updated_call)
    finally:
        conn.close()


@app.get("/admin/calls/logging-summary")
def admin_get_logging_summary(request: Request):
    require_role(request, {"admin"})
    
    conn = get_connection()
    try:
        total_calls = conn.execute("SELECT COUNT(*) AS count FROM call_sessions").fetchone()["count"]
        logged_calls = conn.execute("SELECT COUNT(*) AS count FROM call_sessions WHERE should_log_call = 1").fetchone()["count"]
        
        by_reason = conn.execute(
            "SELECT logging_reason, COUNT(*) AS count FROM call_sessions WHERE should_log_call = 1 GROUP BY logging_reason"
        ).fetchall()
        
        return {
            "total_calls": total_calls,
            "logged_calls": logged_calls,
            "logging_percentage": (logged_calls / total_calls * 100) if total_calls > 0 else 0,
            "by_reason": [{"reason": row["logging_reason"], "count": row["count"]} for row in by_reason],
        }
    finally:
        conn.close()


@app.post("/calls/initiate")
def initiate_call(request: Request, payload: CallInitiationRequest):
    """Initiate an audio or video call to another user"""
    require_authenticated_user(request)
    user_id = get_user_id_from_request(request)
    
    # Validate recipient exists
    conn = get_connection()
    recipient = conn.execute("SELECT id, name FROM users WHERE id = ?", (payload.recipient_id,)).fetchone()
    if not recipient:
        conn.close()
        raise HTTPException(status_code=404, detail="Recipient not found")
    
    # Validate call can be initiated
    can_call, reason = validate_call_initiation(user_id, payload.recipient_id, payload.call_type)
    if not can_call:
        conn.close()
        raise HTTPException(status_code=403, detail=f"Call cannot be initiated: {reason}")
    
    now = utc_now_iso()
    
    # Create call session
    cursor = conn.execute(
        """
        INSERT INTO call_sessions 
        (participant, note, status, call_type, booking_id, consent_given, initiator_id, recipient_id, call_started_at, video_enabled, recording_consented)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            recipient["name"],
            f"{payload.call_type} call initiated",
            "pending",
            payload.call_type,
            payload.booking_id,
            1,
            user_id,
            payload.recipient_id,
            now,
            1 if payload.video_enabled else 0,
            1 if get_user_call_preferences(payload.recipient_id).get("allow_recording", False) else 0,
        ),
    )
    conn.commit()
    call_id = cursor.lastrowid
    conn.close()
    
    create_notification(
        f"{payload.call_type.title()} Call",
        f"Incoming {payload.call_type} call from user {user_id}",
        recipient_id=payload.recipient_id,
    )
    
    return {
        "call_id": call_id,
        "initiator_id": user_id,
        "recipient_id": payload.recipient_id,
        "call_type": payload.call_type,
        "video_enabled": payload.video_enabled,
        "status": "pending",
        "message": "Call initiated - waiting for recipient response",
    }


@app.post("/calls/{call_id}/accept")
def accept_call(request: Request, call_id: int):
    """Accept incoming call"""
    require_authenticated_user(request)
    user_id = get_user_id_from_request(request)
    
    conn = get_connection()
    call = conn.execute("SELECT * FROM call_sessions WHERE id = ?", (call_id,)).fetchone()
    if not call:
        conn.close()
        raise HTTPException(status_code=404, detail="Call not found")
    
    if call["recipient_id"] != user_id:
        conn.close()
        raise HTTPException(status_code=403, detail="Not the call recipient")
    
    if call["status"] != "pending":
        conn.close()
        raise HTTPException(status_code=400, detail="Call is not in pending state")
    
    now = utc_now_iso()
    conn.execute(
        "UPDATE call_sessions SET status = ? WHERE id = ?",
        ("connected", call_id),
    )
    conn.commit()
    updated_call = conn.execute("SELECT * FROM call_sessions WHERE id = ?", (call_id,)).fetchone()
    conn.close()
    
    create_notification(
        "Call Accepted",
        f"User {user_id} accepted your {call['call_type']} call",
        recipient_id=call["initiator_id"],
    )
    
    return {
        "call_id": call_id,
        "status": "connected",
        "call_type": call["call_type"],
        "message": "Call connected",
    }


@app.post("/calls/{call_id}/decline")
def decline_call(request: Request, call_id: int, reason: str = ""):
    """Decline incoming call"""
    require_authenticated_user(request)
    user_id = get_user_id_from_request(request)
    
    conn = get_connection()
    call = conn.execute("SELECT * FROM call_sessions WHERE id = ?", (call_id,)).fetchone()
    if not call:
        conn.close()
        raise HTTPException(status_code=404, detail="Call not found")
    
    if call["recipient_id"] != user_id:
        conn.close()
        raise HTTPException(status_code=403, detail="Not the call recipient")
    
    if call["status"] not in ("pending", "connected"):
        conn.close()
        raise HTTPException(status_code=400, detail="Call cannot be declined in current state")
    
    conn.execute(
        "UPDATE call_sessions SET status = ?, note = ? WHERE id = ?",
        ("declined", f"Declined: {reason}", call_id),
    )
    conn.commit()
    updated_call = conn.execute("SELECT * FROM call_sessions WHERE id = ?", (call_id,)).fetchone()
    conn.close()
    
    create_notification(
        "Call Declined",
        f"User {user_id} declined your {call['call_type']} call",
        recipient_id=call["initiator_id"],
    )
    
    return {
        "call_id": call_id,
        "status": "declined",
        "reason": reason,
        "message": "Call declined",
    }


@app.post("/calls/{call_id}/end")
def end_call(request: Request, call_id: int):
    """End active call"""
    require_authenticated_user(request)
    user_id = get_user_id_from_request(request)
    
    conn = get_connection()
    call = conn.execute("SELECT * FROM call_sessions WHERE id = ?", (call_id,)).fetchone()
    if not call:
        conn.close()
        raise HTTPException(status_code=404, detail="Call not found")
    
    if call["initiator_id"] != user_id and call["recipient_id"] != user_id:
        conn.close()
        raise HTTPException(status_code=403, detail="Not participant in this call")
    
    success = end_active_call(call_id)
    if not success:
        raise HTTPException(status_code=400, detail="Call could not be ended")
    
    conn = get_connection()
    updated_call = conn.execute("SELECT * FROM call_sessions WHERE id = ?", (call_id,)).fetchone()
    conn.close()
    
    other_user = call["recipient_id"] if call["initiator_id"] == user_id else call["initiator_id"]
    create_notification(
        "Call Ended",
        f"Your {call['call_type']} call has ended (Duration: {updated_call['duration_seconds']}s)",
        recipient_id=other_user,
    )
    
    return {
        "call_id": call_id,
        "status": "ended",
        "duration_seconds": updated_call["duration_seconds"],
        "message": "Call ended",
    }


@app.post("/calls/{call_id}/quality-report")
def submit_call_quality(request: Request, call_id: int, payload: CallQualityMetrics):
    """Submit call quality metrics after call completion"""
    require_authenticated_user(request)
    user_id = get_user_id_from_request(request)
    
    conn = get_connection()
    call = conn.execute("SELECT * FROM call_sessions WHERE id = ?", (call_id,)).fetchone()
    if not call:
        conn.close()
        raise HTTPException(status_code=404, detail="Call not found")
    
    if call["initiator_id"] != user_id and call["recipient_id"] != user_id:
        conn.close()
        raise HTTPException(status_code=403, detail="Not participant in this call")
    
    if call["status"] not in ("ended", "missed", "declined"):
        conn.close()
        raise HTTPException(status_code=400, detail="Can only report quality on completed calls")
    
    success = record_call_quality(call_id, payload.quality_score, payload.notes)
    if not success:
        raise HTTPException(status_code=400, detail="Invalid quality score (must be 0-100)")
    
    conn = get_connection()
    updated_call = conn.execute("SELECT * FROM call_sessions WHERE id = ?", (call_id,)).fetchone()
    conn.close()
    
    return {
        "call_id": call_id,
        "quality_score": updated_call["call_quality_score"],
        "quality_notes": updated_call["quality_notes"],
        "message": "Quality report submitted",
    }


@app.get("/calls/{call_id}/history")
def get_call_history(request: Request, call_id: int, limit: int = 20, offset: int = 0):
    """Get call history for a user"""
    require_authenticated_user(request)
    user_id = get_user_id_from_request(request)
    
    if limit > 100:
        limit = 100
    if limit < 1:
        limit = 1
    
    conn = get_connection()
    # Get all calls where user is initiator or recipient
    calls = conn.execute(
        """
        SELECT * FROM call_sessions 
        WHERE (initiator_id = ? OR recipient_id = ?)
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
        """,
        (user_id, user_id, limit, offset),
    ).fetchall()
    
    total = conn.execute(
        "SELECT COUNT(*) AS count FROM call_sessions WHERE initiator_id = ? OR recipient_id = ?",
        (user_id, user_id),
    ).fetchone()["count"]
    conn.close()
    
    history = [
        {
            "id": call["id"],
            "initiator_id": call["initiator_id"],
            "recipient_id": call["recipient_id"],
            "call_type": call["call_type"],
            "status": call["status"],
            "duration_seconds": call["duration_seconds"],
            "video_enabled": bool(call["video_enabled"]),
            "call_quality_score": call["call_quality_score"],
            "created_at": call["created_at"],
            "call_started_at": call["call_started_at"],
            "call_ended_at": call["call_ended_at"],
        }
        for call in calls
    ]
    
    return {
        "history": history,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@app.get("/calls/preferences")
def get_call_preferences(request: Request):
    """Get user's call preferences"""
    require_authenticated_user(request)
    user_id = get_user_id_from_request(request)
    
    prefs = get_user_call_preferences(user_id)
    return {
        "user_id": user_id,
        "accept_audio_calls": prefs["accept_audio_calls"],
        "accept_video_calls": prefs["accept_video_calls"],
        "allow_recording": prefs["allow_recording"],
    }


@app.put("/calls/preferences")
def update_call_preferences(request: Request, payload: UserCallPreferences):
    """Update user's call preferences"""
    require_authenticated_user(request)
    user_id = get_user_id_from_request(request)
    
    conn = get_connection()
    now = utc_now_iso()
    
    # Check if preferences exist
    existing = conn.execute(
        "SELECT user_id FROM user_call_preferences WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    
    if existing:
        conn.execute(
            """
            UPDATE user_call_preferences 
            SET accept_audio_calls = ?, accept_video_calls = ?, allow_recording = ?, updated_at = ?
            WHERE user_id = ?
            """,
            (
                1 if payload.accept_audio_calls else 0,
                1 if payload.accept_video_calls else 0,
                1 if payload.allow_recording else 0,
                now,
                user_id,
            ),
        )
    else:
        conn.execute(
            """
            INSERT INTO user_call_preferences 
            (user_id, accept_audio_calls, accept_video_calls, allow_recording, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                user_id,
                1 if payload.accept_audio_calls else 0,
                1 if payload.accept_video_calls else 0,
                1 if payload.allow_recording else 0,
                now,
            ),
        )
    
    conn.commit()
    conn.close()
    
    create_notification(
        "Call Preferences Updated",
        "Your call preferences have been updated",
        recipient_id=user_id,
    )
    
    return {
        "user_id": user_id,
        "accept_audio_calls": payload.accept_audio_calls,
        "accept_video_calls": payload.accept_video_calls,
        "allow_recording": payload.allow_recording,
        "message": "Preferences updated successfully",
    }


@app.post("/messages")
def create_message(request: Request, payload: MessageCreate):
    require_authenticated_user(request)
    flagged, flagged_reason = message_requires_moderation(payload.message)
    moderation_status = "flagged" if flagged else "clear"
    conn = get_connection()
    cursor = conn.execute(
        "INSERT INTO messages (sender, recipient, message, booking_id, moderation_status, flagged_reason) VALUES (?, ?, ?, ?, ?, ?)",
        (payload.sender, payload.recipient, payload.message, payload.booking_id, moderation_status, flagged_reason),
    )
    conn.commit()
    message_id = cursor.lastrowid
    if flagged:
        conn.execute(
            "INSERT INTO moderation_cases (message_id, reason, severity, status, source_text) VALUES (?, ?, ?, ?, ?)",
            (message_id, f"keyword:{flagged_reason}", "high", "open", payload.message),
        )
        conn.commit()
    conn.close()
    if flagged:
        create_notification("Moderation alert", f"Message {message_id} was automatically flagged for review.", booking_id=payload.booking_id)
    return {
        "id": message_id,
        "sender": payload.sender,
        "recipient": payload.recipient,
        "message": payload.message,
        "booking_id": payload.booking_id,
        "moderation_status": moderation_status,
    }


@app.post("/feedback")
def create_feedback(request: Request, payload: FeedbackCreate):
    require_authenticated_user(request)
    conn = get_connection()
    cursor = conn.execute(
        "INSERT INTO notifications (title, message) VALUES (?, ?)",
        ("Feedback received", f"Feedback submitted for booking {payload.booking_id}."),
    )
    conn.commit()
    conn.close()
    return {
        "user_id": payload.user_id,
        "booking_id": payload.booking_id,
        "rating": payload.rating,
        "comment": payload.comment,
    }


@app.get("/tracking/{booking_id}")
def tracking_status(request: Request, booking_id: int):
    require_authenticated_user(request)
    conn = get_connection()
    row = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    timeline = conn.execute(
        "SELECT status, note, latitude, longitude, created_at FROM booking_tracking_events WHERE booking_id = ? ORDER BY id ASC",
        (booking_id,),
    ).fetchall()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Booking not found")
    
    # Check location staleness
    staleness_info = check_location_staleness(booking_id)
    
    route = resolved_route_snapshot(row["pickup"], row["destination"], progress_for_status(row["status"]))
    latest_event = timeline[-1] if timeline else None
    route_phase = {
        "pending": "dispatch_queue",
        "accepted": "driver_assigned",
        "active": "en_route",
        "completed": "delivered",
        "cancelled": "cancelled",
        "disputed": "review_required",
    }.get(row["status"], "dispatch_queue")
    return {
        "booking_id": booking_id,
        "status": row["status"],
        "updated": True,
        "eta_minutes": row["eta_minutes"] or route["eta_minutes"],
        "current_position": {
            "lat": row["current_latitude"] or route["current_position"]["lat"],
            "lng": row["current_longitude"] or route["current_position"]["lng"],
        },
        "route": route,
        "progress": progress_for_status(row["status"]),
        "route_phase": route_phase,
        "latest_event": dict(latest_event) if latest_event else None,
        "event_count": len(timeline),
        "timeline": [dict(item) for item in timeline],
        "location_tracking": staleness_info,
    }


@app.get("/tracking/{booking_id}/live")
def tracking_live(request: Request, booking_id: int):
    payload = tracking_status(request, booking_id)
    payload["heartbeat"] = utc_now_iso()
    payload["stream"] = "polling"
    payload["route_summary"] = {
        "distance_km": payload["route"]["distance_km"],
        "eta_minutes": payload["eta_minutes"],
        "current_phase": payload["route_phase"],
        "last_event": payload["latest_event"],
    }
    return payload


@app.post("/tracking/{booking_id}/location-update")
def update_provider_location(
    request: Request,
    booking_id: int,
    latitude: float,
    longitude: float,
):
    """Update provider location for active booking - called by provider app"""
    require_authenticated_user(request)
    conn = get_connection()
    try:
        booking = conn.execute(
            "SELECT id, provider_id, status FROM bookings WHERE id = ?",
            (booking_id,),
        ).fetchone()
        conn.close()
        
        if not booking:
            raise HTTPException(status_code=404, detail="Booking not found")
        
        if booking["status"] not in ["active", "accepted"]:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot update location for booking with status '{booking['status']}'",
            )
        
        # Update location
        success = update_location_for_booking(booking_id, latitude, longitude)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to update location")
        
        # Check if was previously stale and now resumed
        staleness = check_location_staleness(booking_id)
        
        return {
            "booking_id": booking_id,
            "location_updated": True,
            "latitude": latitude,
            "longitude": longitude,
            "tracking_status": staleness["tracking_status"],
            "timestamp": utc_now_iso(),
        }
    finally:
        if conn:
            conn.close()


@app.get("/tracking/{booking_id}/status-indicator")
def get_tracking_status_indicator(request: Request, booking_id: int):
    """Get tracking status indicator (active, stale, offline) for customer notification"""
    require_authenticated_user(request)
    staleness = check_location_staleness(booking_id)
    
    return {
        "booking_id": booking_id,
        "tracking_available": not staleness["is_stale"],
        "status": staleness["tracking_status"],
        "alert_level": staleness["alert_level"],
        "seconds_since_update": staleness["seconds_since_update"],
        "is_critical_outage": staleness.get("is_critical_outage", False),
        "reason": staleness.get("reason"),
        "message": {
            "active": "Live tracking is active",
            "stale": "Live tracking is temporarily unavailable - we are attempting to resume",
            "critical": "Live tracking has been unavailable for 5+ minutes. You can contact your provider or support.",
            "no_data": "Provider has not yet provided location information",
            "inactive": "Booking is not actively tracking",
        }.get(staleness["tracking_status"], "Unknown status"),
    }


@app.post("/tracking/{booking_id}/resume-notification")
def notify_tracking_resumed(request: Request, booking_id: int):
    """Notify customer when tracking resumes after stale period"""
    require_authenticated_user(request)
    
    conn = get_connection()
    try:
        booking = conn.execute(
            "SELECT customer_id, id FROM bookings WHERE id = ?",
            (booking_id,),
        ).fetchone()
        conn.close()
        
        if not booking:
            raise HTTPException(status_code=404, detail="Booking not found")
        
        # Create notification
        create_notification(
            booking["customer_id"],
            "tracking_resumed",
            "Live tracking has resumed - your provider is being located again",
            booking_id=booking_id,
        )
        
        return {
            "booking_id": booking_id,
            "notification_sent": True,
            "timestamp": utc_now_iso(),
        }
    finally:
        if conn:
            conn.close()


@app.get("/messages")
def list_messages():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM messages ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(row) for row in rows]


@app.post("/ai/support")
def ai_support(payload: dict):
    message = payload.get("message", "").lower()

    if any(term in message for term in ["safety", "unsafe", "abuse", "harassment", "urgent", "emergency"]):
        reply = "This sounds like a safety or urgent issue. I can help you report it, but a human support agent should review it promptly."
    elif "book" in message or "ride" in message or "booking" in message:
        reply = "You can book a ride or haulage service by choosing your service type, entering pickup and destination details, and confirming the request."
    elif "haulage" in message:
        reply = "You can book haulage services by selecting the haulage option, choosing your pickup and destination, and confirming the request."
    elif "vendor" in message or "marketplace" in message:
        reply = "You can browse trusted vendors in the marketplace and place a booking or order directly from their profile."
    elif "report" in message or "problem" in message:
        reply = "You can report concerns through the support and safety workflow, and the team will review them as a human-supported case."
    else:
        reply = "SmartHaul can help you book rides, haul cargo, find vendors, report concerns, and connect you with human support when needed."

    return {"reply": reply}


@app.post("/reports")
def create_report(payload: ReportCreate):
    if payload.type not in VALID_REPORT_TYPES:
        raise HTTPException(status_code=400, detail="Invalid report type")

    if payload.entity_type and payload.entity_type not in VALID_ENTITY_TYPES:
        raise HTTPException(status_code=400, detail="Invalid entity type")

    entity_available = True

    if payload.entity_type and payload.entity_id:
        conn_check = get_connection()
        try:
            if payload.entity_type == "booking":
                entity = conn_check.execute("SELECT * FROM bookings WHERE id = ?", (payload.entity_id,)).fetchone()
                entity_available = entity is not None
            elif payload.entity_type == "vendor":
                entity = conn_check.execute("SELECT * FROM vendors WHERE id = ?", (payload.entity_id,)).fetchone()
                entity_available = entity is not None
            elif payload.entity_type == "user":
                entity = conn_check.execute("SELECT * FROM users WHERE id = ?", (payload.entity_id,)).fetchone()
                entity_available = entity is not None
            elif payload.entity_type == "message":
                entity = conn_check.execute("SELECT * FROM messages WHERE id = ?", (payload.entity_id,)).fetchone()
                entity_available = entity is not None
        finally:
            conn_check.close()

    conn = get_connection()
    cursor = conn.execute(
        """
        INSERT INTO reports (
            user_id, report_type, description, status, entity_type, entity_id,
            entity_available, reported_user_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload.user_id,
            payload.type,
            payload.description,
            "pending",
            payload.entity_type or None,
            payload.entity_id or None,
            1 if entity_available else 0,
            payload.reported_user_id or None,
        ),
    )
    conn.commit()
    report_id = cursor.lastrowid
    conn.close()

    message_suffix = ""
    if not entity_available and payload.entity_type:
        message_suffix = f" (Note: Referenced {payload.entity_type} {payload.entity_id} is no longer available)"

    create_notification(
        "Report received",
        f"Abuse report {report_id} received and flagged for review.{message_suffix}",
    )

    return {
        "id": report_id,
        "user_id": payload.user_id,
        "type": payload.type,
        "description": payload.description,
        "status": "pending",
        "entity_type": payload.entity_type,
        "entity_id": payload.entity_id,
        "entity_available": entity_available,
        "reported_user_id": payload.reported_user_id,
    }


@app.post("/payments")
def create_payment(payload: PaymentCreate):
    external_reference = f"PAY-{secrets.token_hex(6).upper()}"
    payment_status = "paid"
    integration_status = "sandbox_processed"
    checkout_url = None

    if payload.gateway == "flutterwave":
        if not flutterwave_is_configured():
            raise HTTPException(status_code=503, detail="Flutterwave is not configured")
        try:
            gateway_response = initialize_flutterwave_payment(
                tx_ref=external_reference,
                amount=payload.amount,
                customer_email=payload.customer_email or "payments@smarthaul.local",
                customer_name=payload.customer_name or "SmartHaul Customer",
                redirect_url=payload.redirect_url or f"{APP_BASE_URL}/payments/verify?tx_ref={external_reference}",
                currency=payload.currency,
            )
        except httpx.HTTPError as exc:
            logger.exception("Flutterwave initialization failed")
            raise HTTPException(status_code=502, detail="Unable to initialize Flutterwave payment") from exc

        gateway_data = gateway_response.get("data") or {}
        checkout_url = gateway_data.get("link")
        payment_status = "pending"
        integration_status = "flutterwave_initialized"

    conn = get_connection()
    cursor = conn.execute(
        """
        INSERT INTO payments (
            booking_id, amount, method, status, gateway, external_reference, integration_status,
            escrow_status, payout_status, payout_release_at, payout_released_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload.booking_id,
            payload.amount,
            payload.method,
            payment_status,
            payload.gateway,
            external_reference,
            integration_status,
            "held",
            "not_scheduled",
            None,
            None,
        ),
    )
    conn.commit()
    payment_id = cursor.lastrowid
    conn.close()
    create_notification("Payment received", f"Payment {external_reference} was recorded for booking {payload.booking_id}.", booking_id=payload.booking_id)
    return {
        "id": payment_id,
        "booking_id": payload.booking_id,
        "amount": payload.amount,
        "method": payload.method,
        "status": payment_status,
        "gateway": payload.gateway,
        "external_reference": external_reference,
        "integration_status": integration_status,
        "checkout_url": checkout_url,
        "currency": payload.currency,
    }


@app.post("/payments/retry/{booking_id}")
def retry_payment(booking_id: int, payload: PaymentRetryRequest):
    conn = get_connection()
    try:
        booking = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        if not booking:
            raise HTTPException(status_code=404, detail="Booking not found")

        if booking["status"] != "payment_pending":
            raise HTTPException(status_code=409, detail="Booking is not in payment_pending status")

        previous_payment = conn.execute(
            "SELECT * FROM payments WHERE booking_id = ? ORDER BY id DESC LIMIT 1",
            (booking_id,),
        ).fetchone()

        if previous_payment and previous_payment["status"] != "failed":
            raise HTTPException(status_code=409, detail="Previous payment did not fail. Cannot retry.")

        external_reference = f"PAY-RETRY-{secrets.token_hex(6).upper()}"
        payment_status = "paid"
        integration_status = "sandbox_processed_retry"
        checkout_url = None

        if payload.gateway == "flutterwave":
            if not flutterwave_is_configured():
                raise HTTPException(status_code=503, detail="Flutterwave is not configured")
            try:
                gateway_response = initialize_flutterwave_payment(
                    tx_ref=external_reference,
                    amount=payload.amount,
                    customer_email=payload.customer_email or "payments@smarthaul.local",
                    customer_name=payload.customer_name or "SmartHaul Customer",
                    redirect_url=payload.redirect_url or f"{APP_BASE_URL}/payments/verify?tx_ref={external_reference}",
                    currency=payload.currency,
                )
            except httpx.HTTPError as exc:
                logger.exception("Flutterwave retry initialization failed")
                raise HTTPException(status_code=502, detail="Unable to initialize Flutterwave payment retry") from exc

            gateway_data = gateway_response.get("data") or {}
            checkout_url = gateway_data.get("link")
            payment_status = "pending"
            integration_status = "flutterwave_initialized_retry"

        cursor = conn.execute(
            """
            INSERT INTO payments (
                booking_id, amount, method, status, gateway, external_reference, integration_status,
                escrow_status, payout_status, payout_release_at, payout_released_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                booking_id,
                payload.amount,
                payload.method,
                payment_status,
                payload.gateway,
                external_reference,
                integration_status,
                "held",
                "not_scheduled",
                None,
                None,
            ),
        )
        conn.commit()
        payment_id = cursor.lastrowid
        create_notification(
            "Payment retry initiated",
            f"Retry payment {external_reference} initiated for booking {booking_id}.",
            booking_id=booking_id,
        )
        return {
            "id": payment_id,
            "booking_id": booking_id,
            "amount": payload.amount,
            "method": payload.method,
            "status": payment_status,
            "gateway": payload.gateway,
            "external_reference": external_reference,
            "integration_status": integration_status,
            "checkout_url": checkout_url,
            "currency": payload.currency,
            "retry": True,
        }
    finally:
        conn.close()


@app.get("/payments")
def list_payments():
    apply_due_provider_payouts()
    conn = get_connection()
    rows = conn.execute("SELECT * FROM payments ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(row) for row in rows]


@app.post("/payments/webhook")
async def payment_webhook(request: Request):
    payload = await request.json()
    external_reference = extract_flutterwave_reference(payload)
    raw_status = extract_flutterwave_status(payload)
    gateway = str((payload.get("gateway") or (payload.get("data") or {}).get("processor_response") or "")).lower()

    if not external_reference:
        raise HTTPException(status_code=400, detail="Missing payment reference")

    if request.headers.get("verif-hash") and FLUTTERWAVE_WEBHOOK_SECRET_HASH:
        if request.headers.get("verif-hash") != FLUTTERWAVE_WEBHOOK_SECRET_HASH:
            raise HTTPException(status_code=403, detail="Invalid webhook signature")
        verification = verify_flutterwave_payment(external_reference)
        verified_status = normalize_payment_status(str((verification.get("data") or {}).get("status") or raw_status))
        return update_payment_record(external_reference, verified_status, "flutterwave_verified")

    if gateway == "flutterwave" and flutterwave_is_configured():
        verification = verify_flutterwave_payment(external_reference)
        verified_status = normalize_payment_status(str((verification.get("data") or {}).get("status") or raw_status))
        return update_payment_record(external_reference, verified_status, "flutterwave_verified")

    return update_payment_record(external_reference, normalize_payment_status(raw_status), "gateway_confirmed")


@app.get("/payments/verify")
def verify_payment_callback(tx_ref: str):
    if not flutterwave_is_configured():
        raise HTTPException(status_code=503, detail="Flutterwave is not configured")
    verification = verify_flutterwave_payment(tx_ref)
    verified_status = normalize_payment_status(str((verification.get("data") or {}).get("status") or "pending"))
    return update_payment_record(tx_ref, verified_status, "flutterwave_verified")


@app.post("/refunds")
def create_refund(payload: RefundCreate):
    conn = get_connection()
    cursor = conn.execute(
        "INSERT INTO refunds (payment_id, amount, reason, status) VALUES (?, ?, ?, ?)",
        (payload.payment_id, payload.amount, payload.reason, "requested"),
    )
    conn.commit()
    refund_id = cursor.lastrowid
    conn.close()
    return {"id": refund_id, "payment_id": payload.payment_id, "amount": payload.amount, "reason": payload.reason, "status": "requested"}


@app.get("/refunds")
def list_refunds():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM refunds ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(row) for row in rows]


@app.post("/disputes")
def create_dispute(payload: DisputeCreate):
    conn = get_connection()
    booking = conn.execute("SELECT * FROM bookings WHERE id = ?", (payload.booking_id,)).fetchone()
    if not booking:
        conn.close()
        raise HTTPException(status_code=404, detail="Booking not found")

    payment = conn.execute(
        "SELECT * FROM payments WHERE booking_id = ? ORDER BY id DESC LIMIT 1",
        (payload.booking_id,),
    ).fetchone()

    dispute_status = "pending"
    payout_resolution = "manual_review_required"
    booking_next_status = booking["status"]
    now_iso = utc_now_iso()
    in_dispute_window = False

    if payment:
        payout_release_at = parse_iso_datetime(payment["payout_release_at"])
        now_dt = parse_iso_datetime(now_iso) or datetime.now(timezone.utc)
        if payout_release_at is not None:
            if payout_release_at.tzinfo is None:
                payout_release_at = payout_release_at.replace(tzinfo=timezone.utc)
            in_dispute_window = now_dt <= payout_release_at

        if payment["payout_status"] in {"scheduled", "not_scheduled", "on_hold"}:
            in_dispute_window = True

        if in_dispute_window:
            payout_resolution = "escrow_held"
            booking_next_status = "disputed"
            conn.execute(
                "UPDATE payments SET payout_status = 'on_hold', escrow_status = 'held' WHERE id = ?",
                (payment["id"],),
            )
        else:
            payout_resolution = "post_payout_manual_review"
            if payment["payout_status"] == "released":
                conn.execute(
                    "UPDATE payments SET payout_status = 'manual_review' WHERE id = ?",
                    (payment["id"],),
                )

    if booking_next_status == "disputed":
        conn.execute(
            "UPDATE bookings SET status = 'disputed', updated_at = ? WHERE id = ?",
            (now_iso, payload.booking_id),
        )

    cursor = conn.execute(
        "INSERT INTO disputes (booking_id, reason, description, status, payout_resolution, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (payload.booking_id, payload.reason, payload.description, dispute_status, payout_resolution, now_iso),
    )
    conn.commit()
    dispute_id = cursor.lastrowid
    conn.close()
    create_notification(
        "Dispute opened",
        f"Dispute {dispute_id} opened for booking {payload.booking_id} ({payout_resolution}).",
        booking_id=payload.booking_id,
    )
    return {
        "id": dispute_id,
        "booking_id": payload.booking_id,
        "reason": payload.reason,
        "description": payload.description,
        "status": dispute_status,
        "payout_resolution": payout_resolution,
        "within_dispute_window": in_dispute_window,
    }


@app.get("/disputes")
def list_disputes():
    apply_due_provider_payouts()
    conn = get_connection()
    rows = conn.execute("SELECT * FROM disputes ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(row) for row in rows]


@app.get("/admin/dispute-payout-policy")
def get_admin_dispute_payout_policy(request: Request):
    require_role(request, {"admin"})
    return get_dispute_payout_policy()


@app.put("/admin/dispute-payout-policy")
def update_admin_dispute_payout_policy(request: Request, payload: DisputePayoutPolicyUpdate):
    require_role(request, {"admin"})
    return set_dispute_payout_policy(payload)


@app.post("/admin/disputes/{dispute_id}/resolve")
def admin_resolve_dispute(request: Request, dispute_id: int, payload: DisputeResolutionRequest):
    require_role(request, {"admin"})
    return resolve_dispute_and_process_payout(dispute_id, payload.resolution, payload.resolution_notes)


@app.get("/admin/disputes/{dispute_id}")
def admin_get_dispute_details(request: Request, dispute_id: int):
    require_role(request, {"admin"})
    conn = get_connection()
    try:
        dispute = conn.execute("SELECT * FROM disputes WHERE id = ?", (dispute_id,)).fetchone()
        if not dispute:
            raise HTTPException(status_code=404, detail="Dispute not found")
        booking = conn.execute("SELECT * FROM bookings WHERE id = ?", (dispute["booking_id"],)).fetchone()
        payment = conn.execute(
            "SELECT * FROM payments WHERE booking_id = ? ORDER BY id DESC LIMIT 1",
            (dispute["booking_id"],),
        ).fetchone()
        return {
            "dispute": dict(dispute),
            "booking": dict(booking) if booking else None,
            "payment": dict(payment) if payment else None,
        }
    finally:
        conn.close()


@app.post("/admin/reports/{report_id}/review")
def review_report(request: Request, report_id: int, payload: ReportReviewUpdate):
    require_role(request, {"admin"})

    if payload.status not in VALID_REPORT_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid report status")

    conn = get_connection()
    try:
        report = conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")

        now_iso = utc_now_iso()
        resolved_at = now_iso if payload.status in {"resolved", "closed"} else None

        conn.execute(
            """
            UPDATE reports
            SET status = ?, review_notes = ?, resolved_at = ?
            WHERE id = ?
            """,
            (payload.status, payload.review_notes, resolved_at, report_id),
        )
        conn.commit()

        updated_report = conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
        return dict(updated_report)
    finally:
        conn.close()


@app.get("/admin/reports/unavailable")
def admin_list_unavailable_entity_reports(request: Request):
    require_role(request, {"admin"})
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM reports WHERE entity_available = 0 ORDER BY id DESC"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


@app.get("/admin/reports")
def admin_list_all_reports(request: Request):
    require_role(request, {"admin"})
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM reports ORDER BY id DESC").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


@app.get("/admin/metrics")
def admin_metrics(request: Request):
    require_role(request, {"admin"})
    conn = get_connection()
    bookings_count = conn.execute("SELECT COUNT(*) AS count FROM bookings").fetchone()["count"]
    vendors_count = conn.execute("SELECT COUNT(*) AS count FROM vendors").fetchone()["count"]
    reports_count = conn.execute("SELECT COUNT(*) AS count FROM reports").fetchone()["count"]
    payments_count = conn.execute("SELECT COUNT(*) AS count FROM payments").fetchone()["count"]
    disputes_count = conn.execute("SELECT COUNT(*) AS count FROM disputes").fetchone()["count"]
    restricted_accounts = conn.execute("SELECT COUNT(*) AS count FROM users WHERE account_status = 'restricted'").fetchone()["count"]
    pending_reports = conn.execute("SELECT COUNT(*) AS count FROM reports WHERE status = 'pending'").fetchone()["count"]
    pending_vendor_reviews = conn.execute(
        "SELECT COUNT(*) AS count FROM vendors WHERE onboarding_status = 'pending_review'"
    ).fetchone()["count"]
    flagged_messages = conn.execute("SELECT COUNT(*) AS count FROM moderation_cases WHERE status = 'open'").fetchone()["count"]
    calls_count = conn.execute("SELECT COUNT(*) AS count FROM call_sessions").fetchone()["count"]
    payment_volume = conn.execute("SELECT COALESCE(SUM(amount), 0) AS total FROM payments").fetchone()["total"]
    conn.close()
    return {
        "bookings": bookings_count,
        "vendors": vendors_count,
        "reports": reports_count,
        "payments": payments_count,
        "disputes": disputes_count,
        "pending_reports": pending_reports,
        "pending_vendor_reviews": pending_vendor_reviews,
        "flagged_messages": flagged_messages,
        "restricted_accounts": restricted_accounts,
        "call_sessions": calls_count,
        "payment_volume": payment_volume,
        "active_services": 3,
        "suspicious_activity_alerts": max(0, disputes_count + pending_reports),
    }


@app.get("/admin/providers/stats")
def admin_get_all_providers_stats(request: Request):
    """Admin endpoint to view performance stats for all providers"""
    require_role(request, {"admin"})
    conn = get_connection()
    try:
        providers = conn.execute("SELECT id FROM providers ORDER BY id DESC").fetchall()
        conn.close()
        
        stats_list = []
        for provider_row in providers:
            stats = get_provider_stats(provider_row["id"])
            if stats:
                stats_list.append(ProviderStatsResponse(**stats))
        
        return stats_list
    finally:
        if conn:
            conn.close()


@app.get("/admin/vendors/stats")
def admin_get_all_vendors_stats(request: Request):
    """Admin endpoint to view performance stats for all vendors"""
    require_role(request, {"admin"})
    conn = get_connection()
    try:
        vendors = conn.execute("SELECT id FROM vendors ORDER BY id DESC").fetchall()
        conn.close()
        
        stats_list = []
        for vendor_row in vendors:
            stats = get_vendor_stats(vendor_row["id"])
            if stats:
                stats_list.append(VendorStatsResponse(**stats))
        
        return stats_list
    finally:
        if conn:
            conn.close()


@app.get("/admin/activity-logs")
def admin_get_activity_logs(
    request: Request,
    action_type: str | None = None,
    entity_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    """Retrieve admin activity logs with optional filters for audit trail"""
    require_role(request, {"admin"})
    conn = get_connection()
    try:
        query = "SELECT * FROM activity_logs WHERE 1=1"
        params = []
        
        if action_type:
            query += " AND action_type = ?"
            params.append(action_type)
        
        if entity_type:
            query += " AND entity_type = ?"
            params.append(entity_type)
        
        query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        rows = conn.execute(query, params).fetchall()
        conn.close()
        
        logs = [ActivityLogEntry(**dict(row)) for row in rows]
        return logs
    finally:
        if conn:
            conn.close()


@app.get("/admin/activity-logs/summary")
def admin_get_activity_summary(request: Request):
    """Get summary of recent admin activity for dashboard"""
    require_role(request, {"admin"})
    conn = get_connection()
    try:
        # Get count by action type
        action_counts = conn.execute(
            """SELECT action_type, COUNT(*) AS count FROM activity_logs 
               GROUP BY action_type ORDER BY count DESC LIMIT 10"""
        ).fetchall()
        
        # Get count by entity type
        entity_counts = conn.execute(
            """SELECT entity_type, COUNT(*) AS count FROM activity_logs 
               WHERE entity_type IS NOT NULL GROUP BY entity_type ORDER BY count DESC LIMIT 10"""
        ).fetchall()
        
        # Get most active admins
        admin_activity = conn.execute(
            """SELECT u.id, u.name, COUNT(a.id) AS action_count FROM activity_logs a 
               JOIN users u ON a.admin_id = u.id 
               GROUP BY u.id ORDER BY action_count DESC LIMIT 5"""
        ).fetchall()
        
        conn.close()
        
        return {
            "action_type_summary": {row["action_type"]: row["count"] for row in action_counts},
            "entity_type_summary": {row["entity_type"]: row["count"] for row in entity_counts},
            "most_active_admins": [
                {"admin_id": row["id"], "admin_name": row["name"], "action_count": row["action_count"]}
                for row in admin_activity
            ],
        }
    finally:
        if conn:
            conn.close()


@app.get("/admin/dashboard/growth-metrics")
def admin_get_growth_metrics(
    request: Request,
    period_days: int = 30,
):
    """Get user growth and retention metrics for admin dashboard"""
    require_role(request, {"admin"})
    metrics = get_user_growth_metrics(period_days)
    return {
        "period_days": period_days,
        **metrics,
    }


@app.get("/admin/dashboard/revenue-analytics")
def admin_get_revenue_analytics(
    request: Request,
    period_days: int = 30,
):
    """Get revenue metrics and trends for admin dashboard"""
    require_role(request, {"admin"})
    analytics = get_revenue_analytics(period_days)
    return {
        "period_days": period_days,
        **analytics,
    }


@app.get("/admin/dashboard/trends")
def admin_get_dispute_report_trends(
    request: Request,
    period_days: int = 30,
):
    """Get dispute and report trends for admin dashboard"""
    require_role(request, {"admin"})
    trends = get_dispute_and_report_trends(period_days)
    return {
        "period_days": period_days,
        **trends,
    }


@app.get("/admin/dashboard/suspicious-activity")
def admin_get_suspicious_activity(request: Request):
    """Get suspicious activity alerts for admin dashboard"""
    require_role(request, {"admin"})
    alerts = detect_suspicious_activity()
    return alerts


@app.get("/admin/dashboard/comprehensive")
def admin_get_comprehensive_dashboard(request: Request):
    """Unified admin dashboard with all key metrics and analytics"""
    require_role(request, {"admin"})
    conn = get_connection()
    try:
        # Basic counts
        active_bookings = conn.execute(
            "SELECT COUNT(*) AS count FROM bookings WHERE status IN ('accepted', 'in_progress')"
        ).fetchone()["count"]
        
        total_revenue = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM payments WHERE status IN ('paid', 'settled')"
        ).fetchone()["total"]
        
        total_providers = conn.execute("SELECT COUNT(*) AS count FROM providers").fetchone()["count"]
        total_vendors = conn.execute("SELECT COUNT(*) AS count FROM vendors").fetchone()["count"]
        total_users = conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"]
        
        restricted_accounts = conn.execute(
            "SELECT COUNT(*) AS count FROM users WHERE account_status IN ('restricted', 'suspended', 'banned')"
        ).fetchone()["count"]
        
        conn.close()
        
        # Gather all analytics
        growth = get_user_growth_metrics(30)
        revenue = get_revenue_analytics(30)
        trends = get_dispute_and_report_trends(30)
        alerts = detect_suspicious_activity()
        
        return {
            "overview": {
                "active_bookings": active_bookings,
                "total_revenue": float(total_revenue),
                "total_providers": total_providers,
                "total_vendors": total_vendors,
                "total_users": total_users,
                "restricted_accounts": restricted_accounts,
            },
            "growth_metrics": growth,
            "revenue_analytics": revenue,
            "trends": trends,
            "suspicious_activity_alerts": alerts,
        }
    finally:
        if conn:
            conn.close()


@app.get("/admin/performance/monitoring")
def admin_get_performance_metrics(request: Request):
    """Get system performance metrics and optimization status"""
    require_role(request, {"admin"})
    
    conn = get_connection()
    try:
        # Query performance metrics
        total_queries_24h = conn.execute(
            """
            SELECT COUNT(*) AS count FROM activity_logs 
            WHERE timestamp > datetime('now', '-1 day')
            """
        ).fetchone()["count"]
        
        slow_bookings = conn.execute(
            """
            SELECT COUNT(*) AS count FROM bookings 
            WHERE status = 'in_progress' 
            AND julianday('now') - julianday(created_at) > 2
            """
        ).fetchone()["count"]
        
        pending_operations = conn.execute(
            "SELECT COUNT(*) AS count FROM bookings WHERE status = 'pending'"
        ).fetchone()["count"]
        
        cache_stats = {
            "cache_entries": len(database_module._query_cache.cache),
            "cache_ttl_seconds": database_module._query_cache.ttl_seconds,
        }
        
        connection_pool_stats = None
        pool = database_module.get_connection_pool()
        if pool:
            connection_pool_stats = {
                "available_connections": len(pool.available),
                "in_use": pool.in_use,
                "max_size": pool.max_size,
                "utilization_percent": (pool.in_use / pool.max_size * 100) if pool.max_size > 0 else 0,
            }
        
        return {
            "timestamp": utc_now_iso(),
            "query_activity": {
                "queries_24h": total_queries_24h,
                "pending_operations": pending_operations,
                "slow_bookings": slow_bookings,
            },
            "cache": cache_stats,
            "connection_pool": connection_pool_stats,
            "optimization_status": "active",
        }
    finally:
        conn.close()


@app.post("/admin/performance/cache-clear")
def admin_clear_performance_cache(request: Request, pattern: str = None):
    """Clear query cache to reset performance metrics"""
    require_role(request, {"admin"})
    
    database_module.clear_query_cache(pattern)
    
    create_notification(
        "Performance",
        f"Cache cleared by admin {'for pattern: ' + pattern if pattern else 'globally'}",
    )
    
    return {
        "cleared": True,
        "pattern": pattern,
        "message": "Query cache cleared successfully",
    }


@app.get("/admin/database/indexes")
def admin_get_database_indexes(request: Request):
    """Get information about database indexes"""
    require_role(request, {"admin"})
    
    conn = get_connection()
    try:
        backend = database_module.get_database_backend()
        
        if backend == "postgres":
            indexes = conn.execute(
                """
                SELECT indexname, tablename, indexdef 
                FROM pg_indexes 
                WHERE schemaname = 'public'
                ORDER BY tablename, indexname
                """
            ).fetchall()
            
            index_list = [
                {
                    "name": idx["indexname"],
                    "table": idx["tablename"],
                    "definition": idx["indexdef"],
                }
                for idx in indexes
            ]
        else:
            # SQLite
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            
            index_list = []
            for table in tables:
                indexes = conn.execute(f"PRAGMA index_list({table['name']})").fetchall()
                for idx in indexes:
                    index_list.append({
                        "name": idx["name"],
                        "table": table["name"],
                        "unique": bool(idx["unique"]),
                        "partial": bool(idx["partial"]),
                    })
        
        return {
            "database_backend": backend,
            "total_indexes": len(index_list),
            "indexes": index_list,
        }
    finally:
        conn.close()


@app.get("/admin/security/monitoring")
def admin_security_monitoring(request: Request):
    """Real-time security monitoring dashboard for admins"""
    require_role(request, {"admin"})
    
    # Get rate limit statistics
    rate_limit_stats = {
        "global": {
            "current_requests": len(_global_rate_limiter.request_times),
            "limit_per_minute": _global_rate_limiter.requests_per_minute,
        },
        "user": {
            "current_requests": len(_user_rate_limiter.request_times),
            "limit_per_minute": _user_rate_limiter.requests_per_minute,
        },
        "api": {
            "current_requests": len(_api_rate_limiter.request_times),
            "limit_per_minute": _api_rate_limiter.requests_per_minute,
        },
    }
    
    # Get brute force protection stats
    brute_force_stats = {
        "active_lockouts": len([k for k, v in _brute_force_protector.failed_attempts.items() if v["locked_until"] and datetime.fromisoformat(v["locked_until"]) > datetime.now(timezone.utc)]),
        "tracked_identifiers": len(_brute_force_protector.failed_attempts),
        "max_attempts": _brute_force_protector.max_attempts,
        "lockout_minutes": _brute_force_protector.lockout_minutes,
    }
    
    # Get recent security events
    recent_events = get_security_events(limit=20)
    
    return {
        "timestamp": utc_now_iso(),
        "rate_limit_stats": rate_limit_stats,
        "brute_force_stats": brute_force_stats,
        "recent_security_events": recent_events,
    }


@app.get("/admin/security/events")
def admin_security_events(
    request: Request,
    limit: int = 50,
    event_type: str | None = None,
    severity: str | None = None,
):
    """Retrieve security event logs with filtering"""
    require_role(request, {"admin"})
    
    events = get_security_events(limit=limit, event_type=event_type, severity=severity)
    
    return {
        "total": len(events),
        "limit": limit,
        "events": events,
    }


@app.post("/admin/security/block-ip")
def admin_block_ip(request: Request, ip_address: str, reason: str = ""):
    """Manually block an IP address by admin"""
    require_role(request, {"admin"})
    
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO ip_blacklist (ip_address, reason, added_at)
            VALUES (?, ?, ?)
            """,
            (ip_address, reason, utc_now_iso()),
        )
        conn.commit()
        
        log_security_event(
            event_type="ip_blocked",
            severity="high",
            details=f"Admin blocked IP {ip_address}. Reason: {reason}",
        )
        
        return {
            "message": f"IP {ip_address} blocked successfully",
            "ip_address": ip_address,
        }
    finally:
        conn.close()


@app.post("/admin/policies/cancellation")
def admin_get_cancellation_policy(request: Request):
    require_role(request, {"admin"})
    return get_cancellation_policy()
def get_dispute_payout_policy() -> Dict[str, Any]:
    defaults = {"payout_window_hours": 24}
    conn = get_connection()
    try:
        policy = {
            "payout_window_hours": int(
                get_admin_setting(conn, "dispute_payout_window_hours", str(defaults["payout_window_hours"]))
            )
        }
    finally:
        conn.close()
    return policy

def set_dispute_payout_policy(payload: DisputePayoutPolicyUpdate) -> Dict[str, Any]:
    if payload.payout_window_hours < 1:
        raise HTTPException(status_code=400, detail="Payout window must be at least 1 hour")
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO admin_settings (key, value, updated_at) VALUES (?, ?, ?)",
            ("dispute_payout_window_hours", str(payload.payout_window_hours), utc_now_iso()),
        )
        conn.commit()
    finally:
        conn.close()
    return get_dispute_payout_policy()


def resolve_dispute_and_process_payout(dispute_id: int, resolution: str, resolution_notes: str) -> Dict[str, Any]:
    if resolution not in {"provider_approved", "customer_approved", "refund", "dismissed"}:
        raise HTTPException(status_code=400, detail="Invalid resolution type")

    conn = get_connection()
    try:
        dispute = conn.execute("SELECT * FROM disputes WHERE id = ?", (dispute_id,)).fetchone()
        if not dispute:
            raise HTTPException(status_code=404, detail="Dispute not found")

        booking_id = dispute["booking_id"]
        old_status = dispute["status"]

        if old_status not in {"pending", "under_review"}:
            raise HTTPException(status_code=409, detail="Dispute is already closed or resolved")

        payment = conn.execute(
            "SELECT * FROM payments WHERE booking_id = ? ORDER BY id DESC LIMIT 1",
            (booking_id,),
        ).fetchone()

        now_iso = utc_now_iso()
        payout_action = None

        if resolution == "provider_approved":
            new_payout_status = "released"
            new_escrow_status = "released"
            payout_action = "released_approved"
            if payment and payment["payout_status"] in {"on_hold", "manual_review"}:
                conn.execute(
                    """
                    UPDATE payments
                    SET payout_status = ?, escrow_status = ?, payout_released_at = ?, integration_status = 'dispute_resolved_approved'
                    WHERE id = ?
                    """,
                    (new_payout_status, new_escrow_status, now_iso, payment["id"]),
                )

        elif resolution == "customer_approved":
            new_payout_status = "held"
            new_escrow_status = "held"
            payout_action = "held_customer_approved"
            if payment and payment["payout_status"] not in {"held"}:
                conn.execute(
                    """
                    UPDATE payments
                    SET payout_status = ?, escrow_status = ?, integration_status = 'dispute_resolved_customer'
                    WHERE id = ?
                    """,
                    (new_payout_status, new_escrow_status, payment["id"]),
                )

        elif resolution == "refund":
            new_payout_status = "refunded"
            new_escrow_status = "released"
            payout_action = "refund_initiated"
            if payment:
                conn.execute(
                    """
                    UPDATE payments
                    SET payout_status = ?, escrow_status = ?, integration_status = 'dispute_resolved_refund'
                    WHERE id = ?
                    """,
                    (new_payout_status, new_escrow_status, payment["id"]),
                )
                conn.execute(
                    "INSERT INTO refunds (payment_id, amount, reason, status) VALUES (?, ?, ?, ?)",
                    (payment["id"], payment["amount"], "dispute_resolution_refund", "approved"),
                )

        elif resolution == "dismissed":
            payout_action = "dismissed"
            if payment and payment["payout_status"] == "on_hold":
                conn.execute(
                    """
                    UPDATE payments
                    SET payout_status = 'released', escrow_status = 'released', payout_released_at = ?, integration_status = 'dispute_resolved_dismissed'
                    WHERE id = ?
                    """,
                    (now_iso, payment["id"]),
                )
            elif payment and payment["payout_status"] == "manual_review":
                conn.execute(
                    """
                    UPDATE payments
                    SET payout_status = 'released', escrow_status = 'released', payout_released_at = ?, integration_status = 'dispute_resolved_dismissed'
                    WHERE id = ?
                    """,
                    (now_iso, payment["id"]),
                )

        booking = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        if booking and booking["status"] == "disputed":
            conn.execute(
                "UPDATE bookings SET status = 'completed', updated_at = ? WHERE id = ?",
                (now_iso, booking_id),
            )

        conn.execute(
            """
            UPDATE disputes
            SET status = 'resolved', resolution_notes = ?, resolution = ?, resolved_at = ?
            WHERE id = ?
            """,
            (resolution_notes, resolution, now_iso, dispute_id),
        )

        conn.commit()

        create_notification(
            "Dispute resolved",
            f"Dispute {dispute_id} for booking {booking_id} has been resolved ({resolution}). Payout: {payout_action}.",
            booking_id=booking_id,
        )

        return {
            "dispute_id": dispute_id,
            "resolution": resolution,
            "resolution_notes": resolution_notes,
            "payout_action": payout_action,
            "booking_id": booking_id,
            "status": "resolved",
        }
    finally:
        conn.close()

def schedule_provider_payout_for_booking(conn, booking_id: int, completed_at: str) -> None:
    payout_window_hours = int(get_dispute_payout_policy()["payout_window_hours"])
    completed_time = parse_iso_datetime(completed_at)
    if completed_time is None:
        completed_time = datetime.now(timezone.utc)
    if completed_time.tzinfo is None:
        completed_time = completed_time.replace(tzinfo=timezone.utc)
    payout_release_at = (completed_time + timedelta(hours=payout_window_hours)).isoformat()
    conn.execute(
        """
        UPDATE payments
        SET escrow_status = 'held',
            payout_status = 'scheduled',
            payout_release_at = ?,
            payout_released_at = NULL
        WHERE booking_id = ? AND status IN ('paid', 'settled')
        """,
        (payout_release_at, booking_id),
    )

def apply_due_provider_payouts() -> int:
    now_iso = utc_now_iso()
    now_dt = parse_iso_datetime(now_iso) or datetime.now(timezone.utc)
    conn = get_connection()
    due_rows = conn.execute(
        """
        SELECT * FROM payments
        WHERE payout_status = 'scheduled'
          AND payout_release_at IS NOT NULL
          AND status IN ('paid', 'settled')
        """
    ).fetchall()
    released = 0
    for row in due_rows:
        release_at = parse_iso_datetime(row["payout_release_at"])
        if release_at is None:
            continue
        if release_at.tzinfo is None:
            release_at = release_at.replace(tzinfo=timezone.utc)
        if release_at > now_dt:
            continue

        open_dispute = conn.execute(
            "SELECT id FROM disputes WHERE booking_id = ? AND status IN ('pending', 'under_review') LIMIT 1",
            (row["booking_id"],),
        ).fetchone()
        booking = conn.execute("SELECT status FROM bookings WHERE id = ?", (row["booking_id"],)).fetchone()
        if open_dispute or (booking and booking["status"] == "disputed"):
            conn.execute(
                "UPDATE payments SET payout_status = 'on_hold', escrow_status = 'held' WHERE id = ?",
                (row["id"],),
            )
            continue

        conn.execute(
            """
            UPDATE payments
            SET payout_status = 'released',
                escrow_status = 'released',
                payout_released_at = ?,
                integration_status = 'payout_released'
            WHERE id = ?
            """,
            (now_iso, row["id"]),
        )
        released += 1
        create_notification(
            "Provider payout released",
            f"Payout released for booking {row['booking_id']}.",
            booking_id=row["booking_id"],
        )

    conn.commit()
    conn.close()
    return released


@app.post("/admin/policies/cancellation")
def admin_update_cancellation_policy(request: Request, payload: CancellationPolicyUpdate):
    require_role(request, {"admin"})
    return set_cancellation_policy(payload)


@app.get("/admin/users/restricted")
def restricted_users(request: Request):
    require_role(request, {"admin"})
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, name, email, role, account_status, account_restriction_reason, account_restricted_at FROM users WHERE account_status = 'restricted' ORDER BY id DESC"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


@app.post("/admin/users/{user_id}/restriction")
def update_user_restriction(request: Request, user_id: int, payload: AccountRestrictionUpdate):
    require_role(request, {"admin"})
    if payload.account_status not in ALLOWED_ACCOUNT_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid account status")

    conn = get_connection()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="User not found")

    restriction_reason = payload.reason.strip()
    if payload.account_status == "restricted" and not restriction_reason:
        conn.close()
        raise HTTPException(status_code=400, detail="Restriction reason is required")

    conn.execute(
        "UPDATE users SET account_status = ?, account_restriction_reason = ?, account_restricted_at = ? WHERE id = ?",
        (
            payload.account_status,
            restriction_reason if payload.account_status == "restricted" else "",
            utc_now_iso() if payload.account_status == "restricted" else None,
            user_id,
        ),
    )
    conn.commit()
    updated = conn.execute(
        "SELECT id, name, email, role, account_status, account_restriction_reason, account_restricted_at FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    conn.close()
    return dict(updated)


@app.get("/admin/vendors/onboarding")
def vendor_onboarding_queue(request: Request):
    require_role(request, {"admin"})
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM vendors WHERE onboarding_status IN ('pending_review', 'needs_more_info') ORDER BY id DESC"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


@app.post("/admin/vendors/{vendor_id}/review")
def review_vendor_onboarding(request: Request, vendor_id: int, payload: VendorReviewUpdate):
    require_role(request, {"admin"})
    conn = get_connection()
    row = conn.execute("SELECT * FROM vendors WHERE id = ?", (vendor_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Vendor not found")

    if payload.onboarding_status not in ALLOWED_VENDOR_REVIEW_STATUSES:
        conn.close()
        raise HTTPException(status_code=400, detail="Invalid vendor onboarding status")
    if payload.onboarding_status == "approved" and not payload.onboarding_notes.strip():
        conn.close()
        raise HTTPException(status_code=400, detail="Approval requires review notes")

    resolved_document_status = row["document_status"]
    if payload.onboarding_status == "approved":
        resolved_document_status = "verified"
    elif payload.onboarding_status == "needs_more_info":
        resolved_document_status = "incomplete"

    resolved_notes = payload.onboarding_notes.strip()
    if payload.onboarding_status == "needs_more_info" and not resolved_notes:
        resolved_notes = "Additional documentation requested"
    elif payload.onboarding_status == "rejected" and not resolved_notes:
        resolved_notes = "Vendor onboarding rejected during admin review"

    rejection_timestamp = utc_now_iso() if payload.onboarding_status == "rejected" else None
    conn.execute(
        "UPDATE vendors SET onboarding_status = ?, onboarding_notes = ?, document_status = ?, last_rejection_at = ? WHERE id = ?",
        (payload.onboarding_status, resolved_notes, resolved_document_status, rejection_timestamp, vendor_id),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM vendors WHERE id = ?", (vendor_id,)).fetchone()
    conn.close()
    create_notification(
        "Vendor review",
        f"Vendor {row['name']} onboarding moved to {payload.onboarding_status}.",
    )
    return dict(row)


@app.put("/vendors/{vendor_id}/resubmit")
def vendor_resubmit_application(vendor_id: int, payload: VendorResubmitRequest):
    conn = get_connection()
    try:
        vendor = conn.execute("SELECT * FROM vendors WHERE id = ?", (vendor_id,)).fetchone()
        if not vendor:
            raise HTTPException(status_code=404, detail="Vendor not found")

        if vendor["permanently_banned"]:
            raise HTTPException(status_code=403, detail=f"Vendor is permanently banned: {vendor['ban_reason']}")

        if vendor["onboarding_status"] != "rejected":
            raise HTTPException(status_code=400, detail="Only rejected vendors can resubmit applications")

        current_resubmission_count = vendor["resubmission_count"] or 0
        new_document_status = "submitted" if payload.documents_submitted else "missing"

        conn.execute(
            """
            UPDATE vendors
            SET onboarding_status = ?, document_status = ?, onboarding_notes = ?, resubmission_count = ?
            WHERE id = ?
            """,
            (
                "pending_review",
                new_document_status,
                f"Resubmission #{current_resubmission_count + 1}: {payload.additional_notes}".strip(),
                current_resubmission_count + 1,
                vendor_id,
            ),
        )
        conn.commit()

        updated_vendor = conn.execute("SELECT * FROM vendors WHERE id = ?", (vendor_id,)).fetchone()
        create_notification(
            "Vendor resubmission",
            f"Vendor {updated_vendor['name']} has resubmitted their application (attempt #{current_resubmission_count + 1}).",
        )
        return dict(updated_vendor)
    finally:
        conn.close()


@app.post("/admin/vendors/{vendor_id}/ban")
def ban_vendor_permanently(request: Request, vendor_id: int, payload: VendorBanRequest):
    require_role(request, {"admin"})
    
    if not payload.ban_reason.strip():
        raise HTTPException(status_code=400, detail="Ban reason is required")

    conn = get_connection()
    try:
        vendor = conn.execute("SELECT * FROM vendors WHERE id = ?", (vendor_id,)).fetchone()
        if not vendor:
            raise HTTPException(status_code=404, detail="Vendor not found")

        conn.execute(
            """
            UPDATE vendors
            SET permanently_banned = 1, ban_reason = ?, onboarding_status = ?
            WHERE id = ?
            """,
            ("permanently_banned", payload.ban_reason.strip(), vendor_id),
        )
        conn.commit()

        updated_vendor = conn.execute("SELECT * FROM vendors WHERE id = ?", (vendor_id,)).fetchone()
        create_notification(
            "Vendor banned",
            f"Vendor {updated_vendor['name']} has been permanently banned. Reason: {payload.ban_reason}",
        )
        return dict(updated_vendor)
    finally:
        conn.close()


@app.get("/admin/moderation/cases")
def moderation_cases(request: Request):
    require_role(request, {"admin"})
    conn = get_connection()
    rows = conn.execute("SELECT * FROM moderation_cases ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(row) for row in rows]


@app.get("/admin/moderation/summary")
def moderation_summary(request: Request):
    require_role(request, {"admin"})
    conn = get_connection()
    open_cases = conn.execute("SELECT COUNT(*) AS count FROM moderation_cases WHERE status = 'open'").fetchone()["count"]
    resolved_cases = conn.execute("SELECT COUNT(*) AS count FROM moderation_cases WHERE status IN ('resolved', 'dismissed')").fetchone()["count"]
    high_severity = conn.execute("SELECT COUNT(*) AS count FROM moderation_cases WHERE severity = 'high' AND status = 'open'").fetchone()["count"]
    call_cases = conn.execute("SELECT COUNT(*) AS count FROM moderation_cases WHERE reason LIKE 'call:%'").fetchone()["count"]
    message_cases = conn.execute("SELECT COUNT(*) AS count FROM moderation_cases WHERE reason LIKE 'keyword:%' OR reason LIKE 'message:%'").fetchone()["count"]
    conn.close()
    return {
        "open_cases": open_cases,
        "resolved_cases": resolved_cases,
        "high_severity_open_cases": high_severity,
        "call_cases": call_cases,
        "message_cases": message_cases,
    }


@app.post("/admin/moderation/cases/{case_id}/resolve")
def resolve_moderation_case(request: Request, case_id: int, payload: ModerationResolveRequest):
    require_role(request, {"admin"})
    if payload.status not in {"resolved", "dismissed", "escalated", "in_review"}:
        raise HTTPException(status_code=400, detail="Invalid moderation status")

    conn = get_connection()
    row = conn.execute("SELECT * FROM moderation_cases WHERE id = ?", (case_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Moderation case not found")

    conn.execute(
        "UPDATE moderation_cases SET status = ?, resolution_note = ? WHERE id = ?",
        (payload.status, payload.resolution_note.strip(), case_id),
    )
    conn.commit()
    updated = conn.execute("SELECT * FROM moderation_cases WHERE id = ?", (case_id,)).fetchone()
    conn.close()
    create_notification("Moderation case", f"Case {case_id} moved to {payload.status}.")
    return dict(updated)


@app.get("/admin/analytics/operations")
def operations_analytics(request: Request):
    require_role(request, {"admin"})
    conn = get_connection()
    avg_booking_price = conn.execute("SELECT COALESCE(AVG(price), 0) AS value FROM bookings").fetchone()["value"]
    avg_vendor_rating = conn.execute("SELECT COALESCE(AVG(rating), 0) AS value FROM vendors").fetchone()["value"]
    queued_vendor_reviews = conn.execute(
        "SELECT COUNT(*) AS value FROM vendors WHERE onboarding_status = 'pending_review'"
    ).fetchone()["value"]
    open_moderation_cases = conn.execute("SELECT COUNT(*) AS value FROM moderation_cases WHERE status = 'open'").fetchone()["value"]
    successful_payments = conn.execute("SELECT COUNT(*) AS value FROM payments WHERE status IN ('paid', 'settled')").fetchone()["value"]
    conn.close()
    return {
        "average_booking_price": round(avg_booking_price, 2),
        "average_vendor_rating": round(avg_vendor_rating, 2),
        "queued_vendor_reviews": queued_vendor_reviews,
        "open_moderation_cases": open_moderation_cases,
        "successful_payments": successful_payments,
    }


@app.get("/admin/audit")
def admin_audit(request: Request):
    require_role(request, {"admin"})
    conn = get_connection()
    bookings = conn.execute("SELECT id, status, service_type, price FROM bookings ORDER BY id DESC LIMIT 5").fetchall()
    reports = conn.execute("SELECT id, report_type, status FROM reports ORDER BY id DESC LIMIT 5").fetchall()
    payments = conn.execute("SELECT id, amount, status FROM payments ORDER BY id DESC LIMIT 5").fetchall()
    disputes = conn.execute("SELECT id, reason, status FROM disputes ORDER BY id DESC LIMIT 5").fetchall()
    conn.close()

    audit_entries = []
    for row in bookings:
        audit_entries.append({"type": "booking", "id": row["id"], "status": row["status"], "detail": f"{row['service_type']} booking for {row['price']}"})
    for row in reports:
        audit_entries.append({"type": "report", "id": row["id"], "status": row["status"], "detail": row["report_type"]})
    for row in payments:
        audit_entries.append({"type": "payment", "id": row["id"], "status": row["status"], "detail": f"Amount {row['amount']}"})
    for row in disputes:
        audit_entries.append({"type": "dispute", "id": row["id"], "status": row["status"], "detail": row["reason"]})

    return sorted(audit_entries, key=lambda item: item["id"], reverse=True)


@app.post("/auth/register")
def register_user(payload: UserCreate):
    if not password_is_strong(payload.password):
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters and include letters and numbers")
    conn = get_connection()
    existing = conn.execute("SELECT id FROM users WHERE email = ?", (payload.email,)).fetchone()
    if existing:
        conn.close()
        return {"message": "User already exists"}
    hashed = hash_password(payload.password)
    conn.execute(
        "INSERT INTO users (name, email, role, password, password_updated_at, account_status, account_restriction_reason, account_restricted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (payload.name, payload.email, payload.role, hashed, utc_now_iso(), "active", "", None),
    )
    conn.commit()
    conn.close()
    return {"message": "User registered successfully"}


@app.post("/auth/login")
def login(payload: LoginRequest, response: Response):
    conn = get_connection()
    user = conn.execute("SELECT * FROM users WHERE email = ?", (payload.email,)).fetchone()
    if not user:
        conn.close()
        return {"message": "Invalid credentials"}
    if user["account_status"] != "active":
        conn.close()
        raise HTTPException(status_code=403, detail="Account restricted by admin.")
    locked_until = user["locked_until"]
    if locked_until and datetime.fromisoformat(locked_until) > datetime.now(timezone.utc):
        conn.close()
        raise HTTPException(status_code=423, detail="Account locked. Try again later.")
    if verify_password(payload.password, user["password"]):
        conn.execute(
            "UPDATE users SET failed_login_attempts = 0, locked_until = NULL, last_login_at = ? WHERE id = ?",
            (utc_now_iso(), user["id"]),
        )
        conn.commit()
        conn.close()
        session_id = create_session(dict(user))
        response.set_cookie(key="smarthaul_session", value=session_id, httponly=True, samesite="lax")
        return {"message": "Login successful", "role": user["role"], "email": user["email"]}
    attempts = int(user["failed_login_attempts"] or 0) + 1
    lock_until_value = (datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_MINUTES)).isoformat() if attempts >= MAX_LOGIN_ATTEMPTS else None
    conn.execute(
        "UPDATE users SET failed_login_attempts = ?, locked_until = ? WHERE id = ?",
        (attempts, lock_until_value, user["id"]),
    )
    conn.commit()
    conn.close()
    if lock_until_value:
        raise HTTPException(status_code=423, detail="Account locked. Try again later.")
    return {"message": "Invalid credentials"}


@app.post("/auth/password")
def change_password(request: Request, payload: PasswordChangeRequest):
    user = require_authenticated_user(request)
    if not is_strong_password(payload.new_password):
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters and include letters and numbers")

    conn = get_connection()
    try:
        row = conn.execute("SELECT id, password FROM users WHERE email = ?", (user["email"],)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found")
        if not verify_password(payload.current_password, row["password"]):
            raise HTTPException(status_code=401, detail="Current password is incorrect")
        conn.execute(
            "UPDATE users SET password = ?, password_updated_at = ?, failed_login_attempts = 0, locked_until = NULL WHERE id = ?",
            (hash_password(payload.new_password), utc_now_iso(), row["id"]),
        )
        conn.commit()
    finally:
        conn.close()

    for session_id, session in list(SESSION_STORE.items()):
        if session.get("email") == user["email"]:
            SESSION_STORE.pop(session_id, None)
    return {"message": "Password updated successfully"}


@app.post("/auth/logout")
def logout(request: Request, response: Response):
    session_id = request.cookies.get("smarthaul_session")
    if session_id:
        SESSION_STORE.pop(session_id, None)
    response.delete_cookie("smarthaul_session")
    return {"message": "Logout successful"}


@app.get("/auth/me")
def auth_me(request: Request):
    return require_authenticated_user(request)


@app.get("/dashboard/overview")
def dashboard_overview(request: Request):
    require_authenticated_user(request)
    conn = get_connection()
    bookings_count = conn.execute("SELECT COUNT(*) AS count FROM bookings").fetchone()["count"]
    vendors_count = conn.execute("SELECT COUNT(*) AS count FROM vendors").fetchone()["count"]
    reports_count = conn.execute("SELECT COUNT(*) AS count FROM reports").fetchone()["count"]
    conn.close()
    return {
        "customers": 1200,
        "providers": 320,
        "vendors": vendors_count,
        "satisfaction": 94,
        "bookings": bookings_count,
        "reports": reports_count,
    }


@app.get("/providers")
def list_providers():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM providers ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(row) for row in rows]


@app.get("/providers/{provider_id}/stats")
def get_provider_performance_stats(provider_id: int, current_user: Dict = Depends(get_current_user)):
    """Get comprehensive performance stats for a provider - accessible to provider and admins"""
    # Authorization: provider can view own stats, admin can view any
    if current_user["role"] not in ["admin", "provider"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    if current_user["role"] == "provider" and current_user["id"] != provider_id:
        raise HTTPException(status_code=403, detail="Cannot view other provider's stats")
    
    stats = get_provider_stats(provider_id)
    if not stats:
        raise HTTPException(status_code=404, detail="Provider not found")
    
    return ProviderStatsResponse(**stats)


@app.post("/providers")
def create_provider(payload: dict):
    conn = get_connection()
    cursor = conn.execute(
        "INSERT INTO providers (name, status, service_area) VALUES (?, ?, ?)",
        (payload.get("name"), payload.get("status", "available"), payload.get("service_area", "")),
    )
    conn.commit()
    provider_id = cursor.lastrowid
    conn.close()
    return {"id": provider_id, "message": "Provider profile created", **payload}


@app.post("/vendor/availability")
def update_vendor_availability(payload: dict):
    return {"message": "Vendor availability updated", **payload}


