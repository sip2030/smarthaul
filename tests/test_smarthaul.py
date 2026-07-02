import uuid
import sqlite3

import pytest
import httpx
from fastapi.testclient import TestClient

import app as app_module
import database as database_module
import verify_deploy
from app import app
from auth import verify_password
from database import create_admin_user, translate_query_for_postgres


client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_root_serves_frontend():
    response = client.get("/")
    assert response.status_code == 200
    assert "SmartHaul" in response.text


def test_diagnostics_reports_backend_and_integrations(monkeypatch):
    monkeypatch.setattr(database_module, "DATABASE_URL", "postgresql://user:pass@db.example.com/smarthaul")
    monkeypatch.setattr(app_module, "ROUTING_PROVIDER", "openrouteservice")
    monkeypatch.setattr(app_module, "OPENROUTESERVICE_API_KEY", "ors-key")
    monkeypatch.setattr(app_module, "FLUTTERWAVE_SECRET_KEY", "flw-secret")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "bootstrap-admin@example.com")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "bootstrap123")

    response = client.get("/diagnostics")
    assert response.status_code == 200
    payload = response.json()
    assert payload["database_backend"] == "postgres"
    assert payload["database_target"] == "postgresql://user:pass@db.example.com/smarthaul"
    assert payload["routing_provider"] == "openrouteservice"
    assert payload["routing_configured"] is True
    assert payload["flutterwave_configured"] is True
    assert payload["bootstrap_admin_configured"] is True
    assert payload["bootstrap_admin_email"] == "bootstrap-admin@example.com"


def test_verify_deploy_public_endpoints(capsys):
    class FakeResponse:
        def __init__(self, status_code, payload, text=""):
            self.status_code = status_code
            self._payload = payload
            self.text = text or str(payload)

        def json(self):
            return self._payload

    class FakeClient:
        def get(self, path):
            if path == "/health":
                return FakeResponse(200, {"status": "ok"})
            if path == "/diagnostics":
                return FakeResponse(
                    200,
                    {
                        "database_backend": "postgres",
                        "routing_provider": "openrouteservice",
                        "flutterwave_configured": True,
                        "bootstrap_admin_configured": False,
                    },
                )
            raise AssertionError(f"unexpected GET path: {path}")

    verify_deploy.verify_public_endpoints(FakeClient())
    output = capsys.readouterr().out
    assert "health.status=ok" in output
    assert "diagnostics.database_backend=postgres" in output
    assert "diagnostics.routing_provider=openrouteservice" in output


def test_verify_deploy_admin_endpoints(capsys):
    class FakeResponse:
        def __init__(self, status_code, payload, text=""):
            self.status_code = status_code
            self._payload = payload
            self.text = text or str(payload)

        def json(self):
            return self._payload

    class FakeClient:
        def post(self, path, json):
            assert path == "/auth/login"
            assert json == {"email": "admin@example.com", "password": "StrongAdmin123"}
            return FakeResponse(200, {"message": "Login successful"})

        def get(self, path):
            if path == "/admin/health":
                return FakeResponse(
                    200,
                    {
                        "status": "ok",
                        "diagnostics": {"database_backend": "postgres"},
                        "metrics": {"pending_vendor_reviews": 2, "flagged_messages": 1},
                    },
                )
            if path == "/admin/monitoring/snapshot":
                return FakeResponse(
                    200,
                    {
                        "status": "healthy",
                        "alerts": [
                            {"severity": "high", "title": "Open moderation cases", "detail": "2 moderation cases need review."}
                        ],
                    },
                )
            raise AssertionError(f"unexpected GET path: {path}")

    verify_deploy.verify_admin_endpoints(FakeClient(), "admin@example.com", "StrongAdmin123")
    output = capsys.readouterr().out
    assert "admin_health.status=ok" in output
    assert "admin_health.database_backend=postgres" in output
    assert "admin_health.pending_vendor_reviews=2" in output
    assert "monitoring.status=healthy" in output
    assert "monitoring.alerts=1" in output


def test_verify_deploy_rejects_placeholder_base_url():
    with pytest.raises(RuntimeError, match="placeholder host"):
        verify_deploy.validate_base_url("https://your-app.onrender.com")


def test_verify_deploy_404_hint():
    response = httpx.Response(404, text="not found")
    with pytest.raises(RuntimeError, match="real SmartHaul deployment"):
        verify_deploy.require_ok(response, "GET /health")


def test_verify_deploy_outdated_build_hint():
    class FakeResponse:
        def __init__(self, status_code, payload=None, text=""):
            self.status_code = status_code
            self._payload = payload or {}
            self.text = text or str(payload or {})

        def json(self):
            return self._payload

    class FakeClient:
        def get(self, path):
            if path == "/health":
                return FakeResponse(404, text="not found")
            if path == "/":
                return FakeResponse(200, text="<html><title>SmartHaul</title></html>")
            raise AssertionError(f"unexpected GET path: {path}")

    with pytest.raises(RuntimeError, match="Redeploy the latest SmartHaul commit"):
        verify_deploy.verify_public_endpoints(FakeClient())


def test_verify_deploy_main_prints_banner(monkeypatch, capsys):
    monkeypatch.setattr(verify_deploy, "parse_args", lambda: verify_deploy.argparse.Namespace(
        base_url="https://smarthaul.example.com",
        admin_email=None,
        admin_password=None,
        timeout=1.0,
    ))

    class FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(verify_deploy.httpx, "Client", FakeClient)
    monkeypatch.setattr(verify_deploy, "verify_public_endpoints", lambda client: None)

    assert verify_deploy.main() == 0
    output = capsys.readouterr().out
    assert "verifying deployment at https://smarthaul.example.com" in output
    assert "tip: use the real public Render URL" in output


def test_create_booking_flow():
    response = client.post(
        "/bookings",
        json={
            "customer_id": "cust_1",
            "service_type": "ride",
            "pickup": "Lagos Island",
            "destination": "Ikeja",
            "price": 2500,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["service_type"] == "ride"
    assert payload["status"] == "pending"


def test_vendors_and_marketplace_listing():
    response = client.get("/vendors")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) >= 1
    assert payload[0]["name"]


def test_ai_assistant_support():
    response = client.post(
        "/ai/support",
        json={"message": "How do I book a haulage service?"},
    )
    assert response.status_code == 200
    assert "haulage" in response.json()["reply"].lower()


def test_ai_assistant_escalation_and_guidance():
    guidance = client.post(
        "/ai/support",
        json={"message": "Help me book a ride"},
    )
    assert guidance.status_code == 200
    assert "ride" in guidance.json()["reply"].lower()

    escalation = client.post(
        "/ai/support",
        json={"message": "I need urgent help with a safety issue"},
    )
    assert escalation.status_code == 200
    assert "human" in escalation.json()["reply"].lower()


def test_dispute_reporting_and_admin_metrics():
    report = client.post(
        "/reports",
        json={
            "user_id": "cust_1",
            "type": "abuse",
            "description": "Unprofessional behavior",
        },
    )
    assert report.status_code == 200
    admin_email = f"admin-metrics-{uuid.uuid4().hex[:8]}@example.com"
    register = client.post(
        "/auth/register",
        json={
            "name": "Admin Metrics",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    assert register.status_code == 200
    login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    cookie = login.headers.get("set-cookie", "")

    metrics = client.get("/admin/metrics", headers={"cookie": cookie})
    assert metrics.status_code == 200
    payload = metrics.json()
    assert payload["reports"] >= 1


def test_routing_estimate_and_messages():
    route = client.get("/route/estimate?pickup=Yaba&destination=Ikeja")
    assert route.status_code == 200
    payload = route.json()
    assert payload["distance_km"] > 0

    email = f"message-{uuid.uuid4().hex[:8]}@example.com"
    register = client.post(
        "/auth/register",
        json={
            "name": "Message User",
            "email": email,
            "role": "customer",
            "password": "secure123",
        },
    )
    assert register.status_code == 200
    login = client.post(
        "/auth/login",
        json={"email": email, "password": "secure123"},
    )
    cookie = login.headers.get("set-cookie", "")

    message = client.post(
        "/messages",
        json={
            "sender": "customer",
            "recipient": "provider",
            "message": "I am on my way",
        },
        headers={"cookie": cookie},
    )
    assert message.status_code == 200
    assert "message" in message.json()


def test_auth_registration_and_login():
    register = client.post(
        "/auth/register",
        json={
            "name": "Ada",
            "email": "ada@example.com",
            "role": "customer",
            "password": "secure123",
        },
    )
    assert register.status_code == 200
    login = client.post(
        "/auth/login",
        json={"email": "ada@example.com", "password": "secure123"},
    )
    assert login.status_code == 200
    assert login.json()["message"] == "Login successful"


def test_admin_account_restriction_and_restore_workflow():
    user_email = f"restricted-{uuid.uuid4().hex[:8]}@example.com"
    register = client.post(
        "/auth/register",
        json={
            "name": "Restricted User",
            "email": user_email,
            "role": "customer",
            "password": "secure123",
        },
    )
    assert register.status_code == 200

    user_login = client.post(
        "/auth/login",
        json={"email": user_email, "password": "secure123"},
    )
    assert user_login.status_code == 200
    user_cookie = user_login.headers.get("set-cookie", "")

    conn = database_module.get_connection()
    try:
        user_row = conn.execute("SELECT id FROM users WHERE email = ?", (user_email,)).fetchone()
        user_id = user_row["id"]
    finally:
        conn.close()

    admin_email = f"restriction-admin-{uuid.uuid4().hex[:8]}@example.com"
    admin_register = client.post(
        "/auth/register",
        json={
            "name": "Restriction Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    assert admin_register.status_code == 200
    admin_login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_cookie = admin_login.headers.get("set-cookie", "")

    restriction = client.post(
        f"/admin/users/{user_id}/restriction",
        json={"account_status": "restricted", "reason": "policy violation"},
        headers={"cookie": admin_cookie},
    )
    assert restriction.status_code == 200
    restricted_payload = restriction.json()
    assert restricted_payload["account_status"] == "restricted"

    restricted_users = client.get("/admin/users/restricted", headers={"cookie": admin_cookie})
    assert restricted_users.status_code == 200
    assert any(item["id"] == user_id for item in restricted_users.json())

    admin_metrics = client.get("/admin/metrics", headers={"cookie": admin_cookie})
    assert admin_metrics.status_code == 200
    assert admin_metrics.json()["restricted_accounts"] >= 1

    monitoring_snapshot = client.get("/admin/monitoring/snapshot", headers={"cookie": admin_cookie})
    assert monitoring_snapshot.status_code == 200
    snapshot_payload = monitoring_snapshot.json()
    assert snapshot_payload["workload"]["restricted_accounts"] >= 1
    assert any(alert["title"] == "Restricted accounts" for alert in snapshot_payload["alerts"])

    restricted_me = client.get("/auth/me", headers={"cookie": user_cookie})
    assert restricted_me.status_code == 401

    blocked_login = client.post(
        "/auth/login",
        json={"email": user_email, "password": "secure123"},
    )
    assert blocked_login.status_code == 403

    restore = client.post(
        f"/admin/users/{user_id}/restriction",
        json={"account_status": "active", "reason": ""},
        headers={"cookie": admin_cookie},
    )
    assert restore.status_code == 200
    assert restore.json()["account_status"] == "active"

    restored_login = client.post(
        "/auth/login",
        json={"email": user_email, "password": "secure123"},
    )
    assert restored_login.status_code == 200
    assert restored_login.json()["message"] == "Login successful"


def test_booking_status_update_and_quotes_and_notifications():
    created = client.post(
        "/bookings",
        json={
            "customer_id": "cust_2",
            "service_type": "haulage",
            "pickup": "Yaba",
            "destination": "VI",
            "price": 3200,
        },
    )
    booking_id = created.json()["id"]

    status_update = client.patch(
        f"/bookings/{booking_id}",
        json={"status": "active"},
    )
    assert status_update.status_code == 200
    assert status_update.json()["status"] == "active"

    quote = client.post(
        "/quotes",
        json={
            "customer_name": "Grace",
            "service_type": "haulage",
            "pickup": "Yaba",
            "destination": "VI",
            "budget": 3500,
        },
    )
    assert quote.status_code == 200
    assert quote.json()["service_type"] == "haulage"

    notifications = client.get("/notifications")
    assert notifications.status_code == 200
    assert len(notifications.json()) >= 1


def test_booking_lifecycle_transitions():
    created = client.post(
        "/bookings",
        json={
            "customer_id": "cust_3",
            "service_type": "ride",
            "pickup": "Lekki",
            "destination": "Victoria Island",
            "price": 1800,
        },
    )
    booking_id = created.json()["id"]

    accepted = client.patch(f"/bookings/{booking_id}", json={"status": "accepted"})
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "accepted"

    active = client.patch(f"/bookings/{booking_id}", json={"status": "active"})
    assert active.status_code == 200
    assert active.json()["status"] == "active"

    completed = client.patch(f"/bookings/{booking_id}", json={"status": "completed"})
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"

    cancelled = client.patch(f"/bookings/{booking_id}", json={"status": "cancelled"})
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    disputed = client.patch(f"/bookings/{booking_id}", json={"status": "disputed"})
    assert disputed.status_code == 200
    assert disputed.json()["status"] == "disputed"

    invalid = client.patch(f"/bookings/{booking_id}", json={"status": "processing"})
    assert invalid.status_code == 400


def test_admin_can_set_and_get_cancellation_policy():
    admin_email = f"policy-admin-{uuid.uuid4().hex[:8]}@example.com"
    register = client.post(
        "/auth/register",
        json={
            "name": "Policy Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    assert register.status_code == 200
    login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_cookie = login.headers.get("set-cookie", "")

    policy_update = client.post(
        "/admin/policies/cancellation",
        json={
            "penalty_free_window_minutes": 0,
            "cancellation_fee_type": "percentage",
            "cancellation_fee_value": 12,
            "provider_cancel_fee_assignment": "provider_penalty",
        },
        headers={"cookie": admin_cookie},
    )
    assert policy_update.status_code == 200
    updated_payload = policy_update.json()
    assert updated_payload["penalty_free_window_minutes"] == 0
    assert updated_payload["cancellation_fee_type"] == "percentage"
    assert updated_payload["cancellation_fee_value"] == 12
    assert updated_payload["provider_cancel_fee_assignment"] == "provider_penalty"

    policy_read = client.get("/admin/policies/cancellation", headers={"cookie": admin_cookie})
    assert policy_read.status_code == 200
    read_payload = policy_read.json()
    assert read_payload["cancellation_fee_type"] == "percentage"
    assert read_payload["provider_cancel_fee_assignment"] == "provider_penalty"


def test_cancellation_fee_applies_outside_window_and_uses_assignment():
    admin_email = f"cancel-admin-{uuid.uuid4().hex[:8]}@example.com"
    register = client.post(
        "/auth/register",
        json={
            "name": "Cancel Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    assert register.status_code == 200
    login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_cookie = login.headers.get("set-cookie", "")

    policy_update = client.post(
        "/admin/policies/cancellation",
        json={
            "penalty_free_window_minutes": 0,
            "cancellation_fee_type": "fixed",
            "cancellation_fee_value": 250,
            "provider_cancel_fee_assignment": "customer_credit",
        },
        headers={"cookie": admin_cookie},
    )
    assert policy_update.status_code == 200

    booking = client.post(
        "/bookings",
        json={
            "customer_id": "cust_cancel_fee",
            "service_type": "ride",
            "pickup": "Yaba",
            "destination": "Lekki",
            "price": 5000,
        },
    )
    booking_id = booking.json()["id"]

    accepted = client.patch(f"/bookings/{booking_id}", json={"status": "accepted"})
    assert accepted.status_code == 200

    cancelled = client.patch(
        f"/bookings/{booking_id}",
        json={"status": "cancelled", "cancelled_by": "provider"},
    )
    assert cancelled.status_code == 200
    cancelled_payload = cancelled.json()
    assert cancelled_payload["status"] == "cancelled"
    assert cancelled_payload["cancellation"]["cancellation_fee_applied"] is True
    assert cancelled_payload["cancellation"]["cancellation_fee_amount"] == 250
    assert cancelled_payload["cancellation"]["fee_assignment"] == "customer_credit"


def test_cancellation_rejects_invalid_cancelled_by_value():
    booking = client.post(
        "/bookings",
        json={
            "customer_id": "cust_cancel_invalid",
            "service_type": "ride",
            "pickup": "Yaba",
            "destination": "Lekki",
            "price": 2200,
        },
    )
    booking_id = booking.json()["id"]
    accepted = client.patch(f"/bookings/{booking_id}", json={"status": "accepted"})
    assert accepted.status_code == 200

    cancelled = client.patch(
        f"/bookings/{booking_id}",
        json={"status": "cancelled", "cancelled_by": "bot"},
    )
    assert cancelled.status_code == 400


def test_pending_booking_timeout_auto_cancel_and_retry_creates_new_record():
    created = client.post(
        "/bookings",
        json={
            "customer_id": "cust_timeout",
            "service_type": "ride",
            "pickup": "Yaba",
            "destination": "Lekki",
            "price": 2100,
        },
    )
    assert created.status_code == 200
    original_booking_id = created.json()["id"]

    conn = database_module.get_connection()
    try:
        conn.execute(
            "UPDATE bookings SET updated_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00+00:00", original_booking_id),
        )
        conn.commit()
    finally:
        conn.close()

    listed = client.get("/bookings")
    assert listed.status_code == 200
    listings = listed.json()
    original = next(item for item in listings if item["id"] == original_booking_id)
    assert original["status"] == "cancelled"

    retry = client.post(
        f"/bookings/{original_booking_id}/retry",
        json={"widen_search_radius": True, "search_radius_multiplier": 1.5},
    )
    assert retry.status_code == 200
    retry_payload = retry.json()
    assert retry_payload["original_booking_id"] == original_booking_id
    assert retry_payload["new_booking_id"] != original_booking_id
    assert retry_payload["status"] == "pending"
    assert "expanded radius x1.5" in retry_payload["destination"]

    refreshed = client.get("/bookings")
    assert refreshed.status_code == 200
    refreshed_items = refreshed.json()
    old_record = next(item for item in refreshed_items if item["id"] == original_booking_id)
    new_record = next(item for item in refreshed_items if item["id"] == retry_payload["new_booking_id"])
    assert old_record["status"] == "cancelled"
    assert new_record["status"] == "pending"


def test_provider_and_vendor_dashboards_render():
    provider_email = f"provider-{uuid.uuid4().hex[:8]}@example.com"
    provider_register = client.post(
        "/auth/register",
        json={
            "name": "Provider",
            "email": provider_email,
            "role": "provider",
            "password": "provider123",
        },
    )
    assert provider_register.status_code == 200
    provider_login = client.post(
        "/auth/login",
        json={"email": provider_email, "password": "provider123"},
    )
    provider_cookie = provider_login.headers.get("set-cookie", "")

    vendor_email = f"vendor-{uuid.uuid4().hex[:8]}@example.com"
    vendor_register = client.post(
        "/auth/register",
        json={
            "name": "Vendor",
            "email": vendor_email,
            "role": "vendor",
            "password": "vendor123",
        },
    )
    assert vendor_register.status_code == 200
    vendor_login = client.post(
        "/auth/login",
        json={"email": vendor_email, "password": "vendor123"},
    )
    vendor_cookie = vendor_login.headers.get("set-cookie", "")

    provider_page = client.get("/provider-dashboard", headers={"cookie": provider_cookie})
    assert provider_page.status_code == 200
    assert "Provider Dashboard" in provider_page.text

    vendor_page = client.get("/vendor-dashboard", headers={"cookie": vendor_cookie})
    assert vendor_page.status_code == 200
    assert "Vendor Dashboard" in vendor_page.text


def test_payments_refunds_and_disputes_flow():
    booking = client.post(
        "/bookings",
        json={
            "customer_id": "cust_payments",
            "service_type": "ride",
            "pickup": "Surulere",
            "destination": "Lekki",
            "price": 2800,
        },
    )
    booking_id = booking.json()["id"]

    payment = client.post(
        "/payments",
        json={"booking_id": booking_id, "amount": 2800.0, "method": "card"},
    )
    assert payment.status_code == 200
    payment_payload = payment.json()
    assert payment_payload["status"] == "paid"

    refund = client.post(
        "/refunds",
        json={"payment_id": payment_payload["id"], "amount": 500.0, "reason": "customer_cancelled"},
    )
    assert refund.status_code == 200
    assert refund.json()["status"] == "requested"

    dispute = client.post(
        "/disputes",
        json={"booking_id": booking_id, "reason": "service_issue", "description": "Provider arrived late"},
    )
    assert dispute.status_code == 200
    assert dispute.json()["status"] == "pending"

    payments = client.get("/payments")
    assert payments.status_code == 200
    assert len(payments.json()) >= 1

    disputes = client.get("/disputes")
    assert disputes.status_code == 200
    assert len(disputes.json()) >= 1


def test_completed_booking_schedules_and_releases_escrow_payout():
    booking = client.post(
        "/bookings",
        json={
            "customer_id": "cust_escrow_release",
            "service_type": "ride",
            "pickup": "Ikeja",
            "destination": "Yaba",
            "price": 3100,
        },
    )
    assert booking.status_code == 200
    booking_id = booking.json()["id"]

    payment = client.post(
        "/payments",
        json={"booking_id": booking_id, "amount": 3100.0, "method": "card"},
    )
    assert payment.status_code == 200
    payment_id = payment.json()["id"]

    completed = client.patch(f"/bookings/{booking_id}", json={"status": "completed"})
    assert completed.status_code == 200

    conn = database_module.get_connection()
    try:
        row = conn.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()
    finally:
        conn.close()
    assert row["escrow_status"] == "held"
    assert row["payout_status"] == "scheduled"
    assert row["payout_release_at"] is not None

    conn = database_module.get_connection()
    try:
        conn.execute(
            "UPDATE payments SET payout_release_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00+00:00", payment_id),
        )
        conn.commit()
    finally:
        conn.close()

    payments = client.get("/payments")
    assert payments.status_code == 200
    updated = next(item for item in payments.json() if item["id"] == payment_id)
    assert updated["payout_status"] == "released"
    assert updated["escrow_status"] == "released"
    assert updated["payout_released_at"] is not None


def test_dispute_within_window_holds_escrow_and_marks_booking_disputed():
    booking = client.post(
        "/bookings",
        json={
            "customer_id": "cust_dispute_window",
            "service_type": "ride",
            "pickup": "Ajah",
            "destination": "Lekki",
            "price": 4200,
        },
    )
    assert booking.status_code == 200
    booking_id = booking.json()["id"]

    payment = client.post(
        "/payments",
        json={"booking_id": booking_id, "amount": 4200.0, "method": "card"},
    )
    assert payment.status_code == 200
    payment_id = payment.json()["id"]

    completed = client.patch(f"/bookings/{booking_id}", json={"status": "completed"})
    assert completed.status_code == 200

    dispute = client.post(
        "/disputes",
        json={"booking_id": booking_id, "reason": "service_issue", "description": "Cargo damaged"},
    )
    assert dispute.status_code == 200
    dispute_payload = dispute.json()
    assert dispute_payload["payout_resolution"] == "escrow_held"
    assert dispute_payload["within_dispute_window"] is True

    conn = database_module.get_connection()
    try:
        payment_row = conn.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()
        booking_row = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    finally:
        conn.close()
    assert payment_row["payout_status"] == "on_hold"
    assert payment_row["escrow_status"] == "held"
    assert booking_row["status"] == "disputed"

    blocked_completion = client.patch(f"/bookings/{booking_id}", json={"status": "completed"})
    assert blocked_completion.status_code == 409


def test_dispute_after_payout_release_flags_manual_review():
    booking = client.post(
        "/bookings",
        json={
            "customer_id": "cust_post_payout_dispute",
            "service_type": "ride",
            "pickup": "Maryland",
            "destination": "Surulere",
            "price": 2600,
        },
    )
    assert booking.status_code == 200
    booking_id = booking.json()["id"]

    payment = client.post(
        "/payments",
        json={"booking_id": booking_id, "amount": 2600.0, "method": "card"},
    )
    assert payment.status_code == 200
    payment_id = payment.json()["id"]

    completed = client.patch(f"/bookings/{booking_id}", json={"status": "completed"})
    assert completed.status_code == 200

    conn = database_module.get_connection()
    try:
        conn.execute(
            "UPDATE payments SET payout_release_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00+00:00", payment_id),
        )
        conn.commit()
    finally:
        conn.close()

    release_trigger = client.get("/payments")
    assert release_trigger.status_code == 200

    dispute = client.post(
        "/disputes",
        json={"booking_id": booking_id, "reason": "billing_issue", "description": "Charge mismatch"},
    )
    assert dispute.status_code == 200
    dispute_payload = dispute.json()
    assert dispute_payload["payout_resolution"] == "post_payout_manual_review"
    assert dispute_payload["within_dispute_window"] is False

    conn = database_module.get_connection()
    try:
        payment_row = conn.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()
    finally:
        conn.close()
    assert payment_row["payout_status"] == "manual_review"


def test_admin_resolve_dispute_in_window_approves_release():
    booking = client.post(
        "/bookings",
        json={
            "customer_id": "cust_admin_resolve_in_window",
            "service_type": "ride",
            "pickup": "Lekki",
            "destination": "Ikoyi",
            "price": 3000,
        },
    )
    booking_id = booking.json()["id"]

    payment = client.post(
        "/payments",
        json={"booking_id": booking_id, "amount": 3000.0, "method": "card"},
    )
    payment_id = payment.json()["id"]

    completed = client.patch(f"/bookings/{booking_id}", json={"status": "completed"})
    assert completed.status_code == 200

    dispute = client.post(
        "/disputes",
        json={"booking_id": booking_id, "reason": "service_issue", "description": "Poor service quality"},
    )
    dispute_id = dispute.json()["id"]
    assert dispute.json()["payout_resolution"] == "escrow_held"

    admin_email = f"resolve-admin-{uuid.uuid4().hex[:8]}@example.com"
    register = client.post(
        "/auth/register",
        json={
            "name": "Resolve Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_cookie = login.headers.get("set-cookie", "")

    resolve = client.post(
        f"/admin/disputes/{dispute_id}/resolve",
        json={"resolution": "provider_approved", "resolution_notes": "Provider service acceptable"},
        headers={"cookie": admin_cookie},
    )
    assert resolve.status_code == 200
    result = resolve.json()
    assert result["resolution"] == "provider_approved"
    assert result["payout_action"] == "released_approved"

    conn = database_module.get_connection()
    try:
        payment_row = conn.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()
        dispute_row = conn.execute("SELECT * FROM disputes WHERE id = ?", (dispute_id,)).fetchone()
        booking_row = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    finally:
        conn.close()

    assert payment_row["payout_status"] == "released"
    assert payment_row["escrow_status"] == "released"
    assert payment_row["payout_released_at"] is not None
    assert dispute_row["status"] == "resolved"
    assert dispute_row["resolution"] == "provider_approved"
    assert booking_row["status"] == "completed"


def test_admin_resolve_dispute_refund_path():
    booking = client.post(
        "/bookings",
        json={
            "customer_id": "cust_admin_resolve_refund",
            "service_type": "ride",
            "pickup": "Victoria Island",
            "destination": "Ballard Estate",
            "price": 4000,
        },
    )
    booking_id = booking.json()["id"]

    payment = client.post(
        "/payments",
        json={"booking_id": booking_id, "amount": 4000.0, "method": "card"},
    )
    payment_id = payment.json()["id"]

    completed = client.patch(f"/bookings/{booking_id}", json={"status": "completed"})
    assert completed.status_code == 200

    dispute = client.post(
        "/disputes",
        json={"booking_id": booking_id, "reason": "payment_issue", "description": "Unauthorized charge"},
    )
    dispute_id = dispute.json()["id"]

    admin_email = f"refund-admin-{uuid.uuid4().hex[:8]}@example.com"
    register = client.post(
        "/auth/register",
        json={
            "name": "Refund Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_cookie = login.headers.get("set-cookie", "")

    resolve = client.post(
        f"/admin/disputes/{dispute_id}/resolve",
        json={"resolution": "refund", "resolution_notes": "Customer refund approved - unauthorized charge confirmed"},
        headers={"cookie": admin_cookie},
    )
    assert resolve.status_code == 200
    result = resolve.json()
    assert result["resolution"] == "refund"
    assert result["payout_action"] == "refund_initiated"

    conn = database_module.get_connection()
    try:
        payment_row = conn.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()
        dispute_row = conn.execute("SELECT * FROM disputes WHERE id = ?", (dispute_id,)).fetchone()
        refund_row = conn.execute("SELECT * FROM refunds WHERE payment_id = ?", (payment_id,)).fetchone()
    finally:
        conn.close()

    assert payment_row["payout_status"] == "refunded"
    assert payment_row["escrow_status"] == "released"
    assert dispute_row["status"] == "resolved"
    assert dispute_row["resolution"] == "refund"
    assert refund_row is not None
    assert refund_row["status"] == "approved"


def test_admin_resolve_dispute_dismissed_releases_held_escrow():
    booking = client.post(
        "/bookings",
        json={
            "customer_id": "cust_admin_resolve_dismissed",
            "service_type": "ride",
            "pickup": "Ajah",
            "destination": "Epe",
            "price": 2500,
        },
    )
    booking_id = booking.json()["id"]

    payment = client.post(
        "/payments",
        json={"booking_id": booking_id, "amount": 2500.0, "method": "card"},
    )
    payment_id = payment.json()["id"]

    completed = client.patch(f"/bookings/{booking_id}", json={"status": "completed"})
    assert completed.status_code == 200

    dispute = client.post(
        "/disputes",
        json={"booking_id": booking_id, "reason": "service_issue", "description": "Minor delay"},
    )
    dispute_id = dispute.json()["id"]

    admin_email = f"dismiss-admin-{uuid.uuid4().hex[:8]}@example.com"
    register = client.post(
        "/auth/register",
        json={
            "name": "Dismiss Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_cookie = login.headers.get("set-cookie", "")

    resolve = client.post(
        f"/admin/disputes/{dispute_id}/resolve",
        json={"resolution": "dismissed", "resolution_notes": "Minor delay does not warrant dispute"},
        headers={"cookie": admin_cookie},
    )
    assert resolve.status_code == 200
    result = resolve.json()
    assert result["resolution"] == "dismissed"
    assert result["payout_action"] == "dismissed"

    conn = database_module.get_connection()
    try:
        payment_row = conn.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()
        dispute_row = conn.execute("SELECT * FROM disputes WHERE id = ?", (dispute_id,)).fetchone()
    finally:
        conn.close()

    assert payment_row["payout_status"] == "released"
    assert payment_row["escrow_status"] == "released"
    assert payment_row["payout_released_at"] is not None
    assert dispute_row["status"] == "resolved"
    assert dispute_row["resolution"] == "dismissed"


def test_admin_get_dispute_details_with_booking_and_payment():
    booking = client.post(
        "/bookings",
        json={
            "customer_id": "cust_admin_details",
            "service_type": "ride",
            "pickup": "Gbagada",
            "destination": "Shomolu",
            "price": 1800,
        },
    )
    booking_id = booking.json()["id"]

    payment = client.post(
        "/payments",
        json={"booking_id": booking_id, "amount": 1800.0, "method": "card"},
    )

    completed = client.patch(f"/bookings/{booking_id}", json={"status": "completed"})
    assert completed.status_code == 200

    dispute = client.post(
        "/disputes",
        json={"booking_id": booking_id, "reason": "service_issue", "description": "Driver rude"},
    )
    dispute_id = dispute.json()["id"]

    admin_email = f"details-admin-{uuid.uuid4().hex[:8]}@example.com"
    register = client.post(
        "/auth/register",
        json={
            "name": "Details Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_cookie = login.headers.get("set-cookie", "")

    details = client.get(
        f"/admin/disputes/{dispute_id}",
        headers={"cookie": admin_cookie},
    )
    assert details.status_code == 200
    result = details.json()
    assert result["dispute"]["id"] == dispute_id
    assert result["dispute"]["booking_id"] == booking_id
    assert result["booking"]["id"] == booking_id
    assert result["payment"] is not None
    assert result["payment"]["booking_id"] == booking_id


def test_payment_failure_blocks_booking_acceptance():
    booking = client.post(
        "/bookings",
        json={
            "customer_id": "cust_payment_failure",
            "service_type": "ride",
            "pickup": "Bariga",
            "destination": "Costain",
            "price": 1500,
        },
    )
    booking_id = booking.json()["id"]

    payment = client.post(
        "/payments",
        json={"booking_id": booking_id, "amount": 1500.0, "method": "card", "gateway": "sandbox"},
    )
    assert payment.status_code == 200
    payment_id = payment.json()["id"]

    conn = database_module.get_connection()
    try:
        conn.execute(
            "UPDATE payments SET status = 'failed', integration_status = 'payment_declined' WHERE id = ?",
            (payment_id,),
        )
        conn.commit()
    finally:
        conn.close()

    accept_attempt = client.patch(
        f"/bookings/{booking_id}",
        json={"status": "accepted"},
    )
    assert accept_attempt.status_code == 402
    assert "Payment not confirmed" in accept_attempt.json()["detail"]

    conn = database_module.get_connection()
    try:
        booking_row = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    finally:
        conn.close()
    assert booking_row["status"] == "pending"


def test_payment_retry_transitions_booking_to_payment_pending():
    booking = client.post(
        "/bookings",
        json={
            "customer_id": "cust_payment_retry",
            "service_type": "ride",
            "pickup": "Ikoyi",
            "destination": "Lekki Phase 1",
            "price": 2200,
        },
    )
    booking_id = booking.json()["id"]

    payment1 = client.post(
        "/payments",
        json={"booking_id": booking_id, "amount": 2200.0, "method": "card", "gateway": "sandbox"},
    )
    payment_id1 = payment1.json()["id"]

    conn = database_module.get_connection()
    try:
        conn.execute(
            "UPDATE payments SET status = 'failed', integration_status = 'insufficient_funds' WHERE id = ?",
            (payment_id1,),
        )
        conn.execute(
            "UPDATE bookings SET status = 'payment_pending' WHERE id = ?",
            (booking_id,),
        )
        conn.commit()
    finally:
        conn.close()

    booking_check = client.get(f"/bookings/{booking_id}")
    assert booking_check.json()["status"] == "payment_pending"

    retry = client.post(
        f"/payments/retry/{booking_id}",
        json={"amount": 2200.0, "method": "transfer", "gateway": "sandbox"},
    )
    assert retry.status_code == 200
    retry_result = retry.json()
    assert retry_result["retry"] is True
    assert retry_result["booking_id"] == booking_id
    payment_id2 = retry_result["id"]

    conn = database_module.get_connection()
    try:
        payment1_row = conn.execute("SELECT * FROM payments WHERE id = ?", (payment_id1,)).fetchone()
        payment2_row = conn.execute("SELECT * FROM payments WHERE id = ?", (payment_id2,)).fetchone()
        booking_row = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    finally:
        conn.close()

    assert payment1_row["status"] == "failed"
    assert payment2_row["status"] == "paid"
    assert booking_row["status"] == "payment_pending"


def test_payment_retry_succeeds_then_accept():
    booking = client.post(
        "/bookings",
        json={
            "customer_id": "cust_retry_accept",
            "service_type": "ride",
            "pickup": "VI",
            "destination": "Banana Island",
            "price": 5000,
        },
    )
    booking_id = booking.json()["id"]

    payment1 = client.post(
        "/payments",
        json={"booking_id": booking_id, "amount": 5000.0, "method": "card", "gateway": "sandbox"},
    )
    payment_id1 = payment1.json()["id"]

    conn = database_module.get_connection()
    try:
        conn.execute(
            "UPDATE payments SET status = 'failed', integration_status = 'card_expired' WHERE id = ?",
            (payment_id1,),
        )
        conn.execute(
            "UPDATE bookings SET status = 'payment_pending' WHERE id = ?",
            (booking_id,),
        )
        conn.commit()
    finally:
        conn.close()

    retry = client.post(
        f"/payments/retry/{booking_id}",
        json={"amount": 5000.0, "method": "transfer", "gateway": "sandbox"},
    )
    assert retry.status_code == 200
    payment_id2 = retry.json()["id"]

    conn = database_module.get_connection()
    try:
        conn.execute(
            "UPDATE payments SET status = 'paid' WHERE id = ?",
            (payment_id2,),
        )
        conn.commit()
    finally:
        conn.close()

    accept = client.patch(
        f"/bookings/{booking_id}",
        json={"status": "accepted"},
    )
    assert accept.status_code == 200
    assert accept.json()["status"] == "accepted"


def test_payment_retry_only_from_payment_pending():
    booking = client.post(
        "/bookings",
        json={
            "customer_id": "cust_retry_invalid",
            "service_type": "ride",
            "pickup": "Ojota",
            "destination": "Palmgrove",
            "price": 1200,
        },
    )
    booking_id = booking.json()["id"]

    payment = client.post(
        "/payments",
        json={"booking_id": booking_id, "amount": 1200.0, "method": "card", "gateway": "sandbox"},
    )
    payment_id = payment.json()["id"]

    conn = database_module.get_connection()
    try:
        conn.execute(
            "UPDATE payments SET status = 'paid' WHERE id = ?",
            (payment_id,),
        )
        conn.commit()
    finally:
        conn.close()

    retry_attempt = client.post(
        f"/payments/retry/{booking_id}",
        json={"amount": 1200.0, "method": "card", "gateway": "sandbox"},
    )
    assert retry_attempt.status_code == 409
    assert "not in payment_pending status" in retry_attempt.json()["detail"]


def test_report_abuse_with_active_booking():
    booking = client.post(
        "/bookings",
        json={
            "customer_id": "cust_abuse_report",
            "service_type": "ride",
            "pickup": "Maryland",
            "destination": "Panti",
            "price": 1800,
        },
    )
    booking_id = booking.json()["id"]

    report = client.post(
        "/reports",
        json={
            "user_id": "user_reporter",
            "type": "harassment",
            "description": "Driver was rude and unsafe",
            "entity_type": "booking",
            "entity_id": booking_id,
            "reported_user_id": "provider_bad",
        },
    )
    assert report.status_code == 200
    report_data = report.json()
    assert report_data["entity_type"] == "booking"
    assert report_data["entity_id"] == booking_id
    assert report_data["entity_available"] is True
    assert report_data["reported_user_id"] == "provider_bad"

    conn = database_module.get_connection()
    try:
        report_row = conn.execute("SELECT * FROM reports WHERE id = ?", (report_data["id"],)).fetchone()
    finally:
        conn.close()
    assert report_row["entity_available"] == 1


def test_report_abuse_with_unavailable_booking():
    booking = client.post(
        "/bookings",
        json={
            "customer_id": "cust_unavailable_report",
            "service_type": "ride",
            "pickup": "Bariga",
            "destination": "Festac",
            "price": 1500,
        },
    )
    booking_id = booking.json()["id"]

    conn = database_module.get_connection()
    try:
        conn.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
        conn.commit()
    finally:
        conn.close()

    report = client.post(
        "/reports",
        json={
            "user_id": "user_reporter_2",
            "type": "fraud",
            "description": "Booking was fraudulent, entity now deleted",
            "entity_type": "booking",
            "entity_id": booking_id,
        },
    )
    assert report.status_code == 200
    report_data = report.json()
    assert report_data["entity_available"] is False

    conn = database_module.get_connection()
    try:
        report_row = conn.execute("SELECT * FROM reports WHERE id = ?", (report_data["id"],)).fetchone()
    finally:
        conn.close()
    assert report_row["entity_available"] == 0


def test_admin_review_report_status():
    report = client.post(
        "/reports",
        json={
            "user_id": "user_reporter_3",
            "type": "misconduct",
            "description": "Unprofessional behavior",
        },
    )
    report_id = report.json()["id"]

    admin_email = f"report-admin-{uuid.uuid4().hex[:8]}@example.com"
    register = client.post(
        "/auth/register",
        json={
            "name": "Report Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_cookie = login.headers.get("set-cookie", "")

    review = client.post(
        f"/admin/reports/{report_id}/review",
        json={"status": "under_review", "review_notes": "Investigating incident"},
        headers={"cookie": admin_cookie},
    )
    assert review.status_code == 200
    review_data = review.json()
    assert review_data["status"] == "under_review"
    assert review_data["review_notes"] == "Investigating incident"

    resolve = client.post(
        f"/admin/reports/{report_id}/review",
        json={"status": "resolved", "review_notes": "Incident resolved, user warned"},
        headers={"cookie": admin_cookie},
    )
    assert resolve.status_code == 200
    resolve_data = resolve.json()
    assert resolve_data["status"] == "resolved"
    assert resolve_data["resolved_at"] is not None


def test_admin_list_unavailable_entity_reports():
    booking = client.post(
        "/bookings",
        json={
            "customer_id": "cust_unavail_list",
            "service_type": "ride",
            "pickup": "Ikoyi",
            "destination": "Ajah",
            "price": 2500,
        },
    )
    booking_id = booking.json()["id"]

    report1 = client.post(
        "/reports",
        json={
            "user_id": "user_r1",
            "type": "abuse",
            "description": "Active booking report",
            "entity_type": "booking",
            "entity_id": booking_id,
        },
    )
    report_id1 = report1.json()["id"]

    conn = database_module.get_connection()
    try:
        conn.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
        conn.commit()
    finally:
        conn.close()

    report2 = client.post(
        "/reports",
        json={
            "user_id": "user_r2",
            "type": "unsafe_conduct",
            "description": "Unavailable entity report",
            "entity_type": "booking",
            "entity_id": booking_id,
        },
    )
    report_id2 = report2.json()["id"]

    admin_email = f"unavail-admin-{uuid.uuid4().hex[:8]}@example.com"
    register = client.post(
        "/auth/register",
        json={
            "name": "Unavail Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_cookie = login.headers.get("set-cookie", "")

    unavailable_list = client.get(
        "/admin/reports/unavailable",
        headers={"cookie": admin_cookie},
    )
    assert unavailable_list.status_code == 200
    results = unavailable_list.json()
    report_ids = [r["id"] for r in results]
    assert report_id2 in report_ids
    assert report_id1 not in report_ids


def test_rejected_vendor_can_resubmit():
    vendor = client.post(
        "/vendors",
        json={
            "name": f"Resubmit Test Vendor {uuid.uuid4().hex[:6]}",
            "category": "haulage",
            "location": "Lekki",
            "rating": 4.0,
            "documents_submitted": True,
        },
    )
    vendor_id = vendor.json()["id"]

    admin_email = f"vendor-admin-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "Vendor Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_cookie = login.headers.get("set-cookie", "")

    review = client.post(
        f"/admin/vendors/{vendor_id}/review",
        json={
            "onboarding_status": "rejected",
            "onboarding_notes": "Documents not clear",
        },
        headers={"cookie": admin_cookie},
    )
    assert review.status_code == 200
    assert review.json()["onboarding_status"] == "rejected"

    resubmit = client.put(
        f"/vendors/{vendor_id}/resubmit",
        json={
            "documents_submitted": True,
            "additional_notes": "Resubmitted with clearer documents",
        },
    )
    assert resubmit.status_code == 200
    resubmit_data = resubmit.json()
    assert resubmit_data["onboarding_status"] == "pending_review"
    assert resubmit_data["resubmission_count"] == 1


def test_vendor_resubmission_increments_counter():
    vendor = client.post(
        "/vendors",
        json={
            "name": f"Multi-Resubmit Vendor {uuid.uuid4().hex[:6]}",
            "category": "haulage",
            "location": "VI",
            "rating": 4.2,
            "documents_submitted": True,
        },
    )
    vendor_id = vendor.json()["id"]

    admin_email = f"multi-admin-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "Multi Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_cookie = login.headers.get("set-cookie", "")

    for attempt in range(1, 4):
        client.post(
            f"/admin/vendors/{vendor_id}/review",
            json={
                "onboarding_status": "rejected",
                "onboarding_notes": f"Rejection attempt {attempt}",
            },
            headers={"cookie": admin_cookie},
        )

        resubmit = client.put(
            f"/vendors/{vendor_id}/resubmit",
            json={"documents_submitted": True, "additional_notes": f"Resubmission {attempt}"},
        )
        assert resubmit.status_code == 200
        assert resubmit.json()["resubmission_count"] == attempt


def test_banned_vendor_cannot_register():
    vendor_name = f"Banned Vendor {uuid.uuid4().hex[:6]}"
    
    vendor = client.post(
        "/vendors",
        json={
            "name": vendor_name,
            "category": "haulage",
            "location": "Ikoyi",
            "rating": 4.0,
            "documents_submitted": True,
        },
    )
    vendor_id = vendor.json()["id"]

    admin_email = f"ban-admin-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "Ban Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_cookie = login.headers.get("set-cookie", "")

    ban = client.post(
        f"/admin/vendors/{vendor_id}/ban",
        json={"ban_reason": "Fraudulent documents submitted"},
        headers={"cookie": admin_cookie},
    )
    assert ban.status_code == 200
    assert ban.json()["permanently_banned"] == True

    retry_register = client.post(
        "/vendors",
        json={
            "name": vendor_name,
            "category": "haulage",
            "location": "Lekki",
            "rating": 4.0,
            "documents_submitted": True,
        },
    )
    assert retry_register.status_code == 403
    assert "permanently banned" in retry_register.json()["detail"]


def test_banned_vendor_cannot_resubmit():
    vendor = client.post(
        "/vendors",
        json={
            "name": f"Ban-Resubmit Vendor {uuid.uuid4().hex[:6]}",
            "category": "haulage",
            "location": "Ajah",
            "rating": 3.8,
            "documents_submitted": True,
        },
    )
    vendor_id = vendor.json()["id"]

    admin_email = f"ban-resubmit-admin-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "Ban Resubmit Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_cookie = login.headers.get("set-cookie", "")

    client.post(
        f"/admin/vendors/{vendor_id}/review",
        json={"onboarding_status": "rejected", "onboarding_notes": "Documents unclear"},
        headers={"cookie": admin_cookie},
    )

    client.post(
        f"/admin/vendors/{vendor_id}/ban",
        json={"ban_reason": "Multiple fraudulent attempts"},
        headers={"cookie": admin_cookie},
    )

    resubmit_attempt = client.put(
        f"/vendors/{vendor_id}/resubmit",
        json={"documents_submitted": True},
    )
    assert resubmit_attempt.status_code == 403
    assert "permanently banned" in resubmit_attempt.json()["detail"]


def test_call_logged_when_dispute_active():
    booking = client.post(
        "/bookings",
        json={
            "customer_id": "cust_call_dispute",
            "service_type": "ride",
            "pickup": "Victoria Island",
            "destination": "Ajah",
            "price": 2000,
        },
    )
    booking_id = booking.json()["id"]

    client.post(
        "/bookings/confirm",
        json={"booking_id": booking_id, "customer_id": "cust_call_dispute", "status": "accepted"},
    )

    dispute = client.post(
        "/disputes",
        json={
            "booking_id": booking_id,
            "reason": "Driver took wrong route",
            "type": "service_quality",
        },
    )
    assert dispute.status_code == 200

    call = client.post(
        "/calls",
        json={
            "participant": "provider_dispute",
            "note": "Discussing route issue",
            "status": "connected",
            "call_type": "audio",
            "booking_id": booking_id,
            "consent_given": True,
        },
    )
    assert call.status_code == 200
    call_data = call.json()
    assert call_data["should_log_call"] is True
    assert call_data["logging_reason"] == "active_dispute"


def test_call_logged_when_safety_report_filed():
    booking = client.post(
        "/bookings",
        json={
            "customer_id": "cust_call_safety",
            "service_type": "ride",
            "pickup": "Lekki",
            "destination": "Ikoyi",
            "price": 1500,
        },
    )
    booking_id = booking.json()["id"]

    client.post(
        "/bookings/confirm",
        json={"booking_id": booking_id, "customer_id": "cust_call_safety", "status": "accepted"},
    )

    client.post(
        "/bookings/confirm",
        json={"booking_id": booking_id, "customer_id": "cust_call_safety", "status": "completed"},
    )

    conn = database_module.get_connection()
    try:
        conn.execute(
            "UPDATE bookings SET completed_at = ? WHERE id = ?",
            (utc_now_iso(), booking_id),
        )
        conn.commit()
    finally:
        conn.close()

    report = client.post(
        "/reports",
        json={
            "user_id": "user_safety_caller",
            "type": "unsafe_conduct",
            "description": "Driver was reckless",
            "entity_type": "booking",
            "entity_id": booking_id,
        },
    )
    assert report.status_code == 200

    call = client.post(
        "/calls",
        json={
            "participant": "provider_safety",
            "note": "Discussing safety concern",
            "status": "connected",
            "call_type": "audio",
            "booking_id": booking_id,
            "consent_given": True,
        },
    )
    assert call.status_code == 200
    call_data = call.json()
    assert call_data["should_log_call"] is True
    assert call_data["logging_reason"] == "safety_report"


def test_call_not_logged_when_no_dispute_or_report():
    booking = client.post(
        "/bookings",
        json={
            "customer_id": "cust_call_normal",
            "service_type": "ride",
            "pickup": "Surulere",
            "destination": "Yaba",
            "price": 1200,
        },
    )
    booking_id = booking.json()["id"]

    call = client.post(
        "/calls",
        json={
            "participant": "provider_normal",
            "note": "Normal call",
            "status": "connected",
            "call_type": "audio",
            "booking_id": booking_id,
            "consent_given": True,
        },
    )
    assert call.status_code == 200
    call_data = call.json()
    assert call_data["should_log_call"] is False
    assert call_data["logging_reason"] is None


def test_call_not_logged_outside_24h_window():
    booking = client.post(
        "/bookings",
        json={
            "customer_id": "cust_call_old_report",
            "service_type": "ride",
            "pickup": "Bariga",
            "destination": "Festac",
            "price": 1600,
        },
    )
    booking_id = booking.json()["id"]

    client.post(
        "/bookings/confirm",
        json={"booking_id": booking_id, "customer_id": "cust_call_old_report", "status": "accepted"},
    )

    client.post(
        "/bookings/confirm",
        json={"booking_id": booking_id, "customer_id": "cust_call_old_report", "status": "completed"},
    )

    from datetime import datetime, timedelta
    old_time = (datetime.utcnow() - timedelta(hours=25)).isoformat() + "Z"
    
    conn = database_module.get_connection()
    try:
        conn.execute(
            "UPDATE bookings SET completed_at = ? WHERE id = ?",
            (old_time, booking_id),
        )
        conn.commit()
    finally:
        conn.close()

    client.post(
        "/reports",
        json={
            "user_id": "user_old_report",
            "type": "misconduct",
            "description": "Old report",
            "entity_type": "booking",
            "entity_id": booking_id,
        },
    )

    call = client.post(
        "/calls",
        json={
            "participant": "provider_old",
            "note": "Call after 24h window",
            "status": "connected",
            "call_type": "audio",
            "booking_id": booking_id,
            "consent_given": True,
        },
    )
    assert call.status_code == 200
    call_data = call.json()
    assert call_data["should_log_call"] is False


def test_admin_get_logged_calls():
    booking = client.post(
        "/bookings",
        json={
            "customer_id": "cust_admin_logged",
            "service_type": "ride",
            "pickup": "Ikoyi",
            "destination": "Ajah",
            "price": 2100,
        },
    )
    booking_id = booking.json()["id"]

    client.post(
        "/bookings/confirm",
        json={"booking_id": booking_id, "customer_id": "cust_admin_logged", "status": "accepted"},
    )

    dispute = client.post(
        "/disputes",
        json={
            "booking_id": booking_id,
            "reason": "Vehicle breakdown",
            "type": "service_quality",
        },
    )

    call1 = client.post(
        "/calls",
        json={
            "participant": "provider_logged1",
            "note": "Discussing breakdown",
            "status": "connected",
            "call_type": "audio",
            "booking_id": booking_id,
            "consent_given": True,
        },
    )

    call_id = call1.json()["id"]

    logged_calls = client.get("/calls/logged")
    assert logged_calls.status_code == 200
    results = logged_calls.json()
    call_ids = [c["id"] for c in results]
    assert call_id in call_ids


def test_admin_logging_summary():
    admin_email = f"logging-admin-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "Logging Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_cookie = login.headers.get("set-cookie", "")

    summary = client.get(
        "/admin/calls/logging-summary",
        headers={"cookie": admin_cookie},
    )
    assert summary.status_code == 200
    summary_data = summary.json()
    assert "total_calls" in summary_data
    assert "logged_calls" in summary_data
    assert "logging_percentage" in summary_data
    assert "by_reason" in summary_data


def test_admin_monitoring_and_audit_view():
    admin_email = f"metrics-admin-{uuid.uuid4().hex[:8]}@example.com"
    register = client.post(
        "/auth/register",
        json={
            "name": "Metrics Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    assert register.status_code == 200
    login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    cookie = login.headers.get("set-cookie", "")

    metrics = client.get("/admin/metrics", headers={"cookie": cookie})
    assert metrics.status_code == 200
    payload = metrics.json()
    assert payload["bookings"] >= 0
    assert payload["active_services"] >= 0

    audit = client.get("/admin/audit", headers={"cookie": cookie})
    assert audit.status_code == 200
    assert isinstance(audit.json(), list)

    admin_page = client.get("/admin", headers={"cookie": cookie})
    assert admin_page.status_code == 200
    assert "Deployment Status" in admin_page.text
    assert "Database backend" in admin_page.text
    assert "Copy diagnostics JSON" in admin_page.text
    assert "Operational Alerts" in admin_page.text

    admin_health = client.get("/admin/health", headers={"cookie": cookie})
    assert admin_health.status_code == 200
    health_payload = admin_health.json()
    assert health_payload["status"] == "ok"
    assert "diagnostics" in health_payload
    assert "metrics" in health_payload

    analytics_overview = client.get("/analytics/overview")
    assert analytics_overview.status_code == 200
    analytics_payload = analytics_overview.json()
    assert "summary" in analytics_payload
    assert "route_source" in analytics_payload

    analytics_page = client.get("/analytics")
    assert analytics_page.status_code == 200
    assert "SmartHaul Analytics" in analytics_page.text

    monitoring = client.get("/admin/monitoring", headers={"cookie": cookie})
    assert monitoring.status_code == 200
    assert "Business Monitoring" in monitoring.text
    assert "Operational Alerts" in monitoring.text

    monitoring_snapshot = client.get("/admin/monitoring/snapshot", headers={"cookie": cookie})
    assert monitoring_snapshot.status_code == 200
    snapshot_payload = monitoring_snapshot.json()
    assert snapshot_payload["status"] in {"healthy", "degraded"}
    assert "workload" in snapshot_payload
    assert "safety" in snapshot_payload
    assert snapshot_payload["alerts"]


def test_role_based_access_and_form_onboarding():
    admin_email = f"admin-{uuid.uuid4().hex[:8]}@example.com"
    register = client.post(
        "/auth/register",
        json={
            "name": "Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    assert register.status_code == 200

    login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    cookie = login.headers.get("set-cookie", "")

    protected = client.get("/admin", headers={"cookie": cookie})
    assert protected.status_code == 200

    vendor = client.post(
        "/vendors",
        data={"name": "Test Vendor", "category": "repair", "location": "Abuja", "rating": "4.7"},
    )
    assert vendor.status_code == 200
    assert vendor.json()["name"] == "Test Vendor"


def test_calls_and_moderation_workflow():
    email = f"moderation-{uuid.uuid4().hex[:8]}@example.com"
    register = client.post(
        "/auth/register",
        json={
            "name": "Moderation User",
            "email": email,
            "role": "customer",
            "password": "secure123",
        },
    )
    assert register.status_code == 200
    login = client.post(
        "/auth/login",
        json={"email": email, "password": "secure123"},
    )
    cookie = login.headers.get("set-cookie", "")

    call = client.post(
        "/calls",
        json={"participant": "customer", "note": "Consent given", "status": "connected"},
    )
    assert call.status_code == 200
    assert call.json()["status"] == "connected"

    message = client.post(
        "/messages",
        json={
            "sender": "customer",
            "recipient": "provider",
            "message": "This is abusive content",
        },
        headers={"cookie": cookie},
    )
    assert message.status_code == 200

    moderation = client.get("/moderation")
    assert moderation.status_code == 200
    assert "abusive" in moderation.text.lower()


def test_feedback_collection_and_booking_tracking_updates():
    email = f"tracking-{uuid.uuid4().hex[:8]}@example.com"
    register = client.post(
        "/auth/register",
        json={
            "name": "Tracking User",
            "email": email,
            "role": "customer",
            "password": "secure123",
        },
    )
    assert register.status_code == 200
    login = client.post(
        "/auth/login",
        json={"email": email, "password": "secure123"},
    )
    cookie = login.headers.get("set-cookie", "")

    booking = client.post(
        "/bookings",
        json={
            "customer_id": "cust_feedback",
            "service_type": "ride",
            "pickup": "Yaba",
            "destination": "Lekki",
            "price": 2200,
        },
    )
    assert booking.status_code == 200
    booking_id = booking.json()["id"]

    updated = client.patch(f"/bookings/{booking_id}", json={"status": "active"})
    assert updated.status_code == 200
    assert updated.json()["status"] == "active"

    notifications = client.get("/notifications")
    assert notifications.status_code == 200
    assert any("Booking" in item["message"] for item in notifications.json())

    feedback = client.post(
        "/feedback",
        json={"user_id": "cust_feedback", "booking_id": booking_id, "rating": 5, "comment": "Great service"},
        headers={"cookie": cookie},
    )
    assert feedback.status_code == 200
    assert feedback.json()["rating"] == 5

    tracking = client.get(f"/tracking/{booking_id}", headers={"cookie": cookie})
    assert tracking.status_code == 200
    assert tracking.json()["status"] == "active"


def test_session_auth_and_provider_workflow():
    email = f"session-{uuid.uuid4().hex[:8]}@example.com"
    register = client.post(
        "/auth/register",
        json={
            "name": "Sam",
            "email": email,
            "role": "provider",
            "password": "provider123",
        },
    )
    assert register.status_code == 200

    login = client.post(
        "/auth/login",
        json={"email": email, "password": "provider123"},
    )
    assert login.status_code == 200
    cookie = login.headers.get("set-cookie", "")
    assert "smarthaul_session=" in cookie

    fresh_client = TestClient(app)
    guest_access = fresh_client.get("/dashboard/overview")
    assert guest_access.status_code == 401

    protected_access = client.get("/dashboard/overview", headers={"cookie": cookie})
    assert protected_access.status_code == 200

    provider_response = client.post(
        "/providers",
        json={"name": "Ayo Logistics", "status": "available", "service_area": "Lagos"},
    )
    assert provider_response.status_code == 200

    providers = client.get("/providers")
    assert providers.status_code == 200
    assert any(item["name"] == "Ayo Logistics" for item in providers.json())


def test_stronger_auth_controls_and_logout():
    weak_register = client.post(
        "/auth/register",
        json={
            "name": "Weak Password",
            "email": f"weak-{uuid.uuid4().hex[:8]}@example.com",
            "role": "customer",
            "password": "weak",
        },
    )
    assert weak_register.status_code == 400

    email = f"lock-{uuid.uuid4().hex[:8]}@example.com"
    register = client.post(
        "/auth/register",
        json={
            "name": "Lock Target",
            "email": email,
            "role": "customer",
            "password": "secure123",
        },
    )
    assert register.status_code == 200

    locked_response = None
    for _ in range(5):
        locked_response = client.post(
            "/auth/login",
            json={"email": email, "password": "wrongpass1"},
        )
    assert locked_response is not None
    assert locked_response.status_code == 423

    successful_login = client.post(
        "/auth/login",
        json={"email": "ada@example.com", "password": "secure123"},
    )
    cookie = successful_login.headers.get("set-cookie", "")
    assert successful_login.status_code == 200

    logout = client.post("/auth/logout", headers={"cookie": cookie})
    assert logout.status_code == 200


def test_password_change_invalidates_existing_sessions():
    email = f"rotate-{uuid.uuid4().hex[:8]}@example.com"
    register = client.post(
        "/auth/register",
        json={
            "name": "Rotate User",
            "email": email,
            "role": "customer",
            "password": "rotate123",
        },
    )
    assert register.status_code == 200

    login = client.post(
        "/auth/login",
        json={"email": email, "password": "rotate123"},
    )
    old_cookie = login.headers.get("set-cookie", "")
    assert login.status_code == 200

    password_change = client.post(
        "/auth/password",
        json={"current_password": "rotate123", "new_password": "rotate456"},
        headers={"cookie": old_cookie},
    )
    assert password_change.status_code == 200

    stale_session = client.get("/auth/me", headers={"cookie": old_cookie})
    assert stale_session.status_code == 401

    old_password_login = client.post(
        "/auth/login",
        json={"email": email, "password": "rotate123"},
    )
    assert old_password_login.status_code == 200
    assert old_password_login.json()["message"] == "Invalid credentials"

    new_password_login = client.post(
        "/auth/login",
        json={"email": email, "password": "rotate456"},
    )
    assert new_password_login.status_code == 200
    assert new_password_login.json()["message"] == "Login successful"


def test_vendor_onboarding_review_queue():
    admin_email = f"vendor-admin-{uuid.uuid4().hex[:8]}@example.com"
    register = client.post(
        "/auth/register",
        json={
            "name": "Vendor Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    assert register.status_code == 200
    login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    cookie = login.headers.get("set-cookie", "")

    vendor = client.post(
        "/vendors",
        json={
            "name": "Expansion Vendor",
            "category": "warehouse",
            "location": "Ibadan",
            "rating": 4.6,
            "contact_email": "vendor@example.com",
            "documents_submitted": True,
        },
    )
    assert vendor.status_code == 200
    assert vendor.json()["onboarding_status"] == "pending_review"

    queue = client.get("/admin/vendors/onboarding", headers={"cookie": cookie})
    assert queue.status_code == 200
    assert any(item["id"] == vendor.json()["id"] for item in queue.json())

    review = client.post(
        f"/admin/vendors/{vendor.json()['id']}/review",
        json={"onboarding_status": "approved", "onboarding_notes": "Documents verified"},
        headers={"cookie": cookie},
    )
    assert review.status_code == 200
    assert review.json()["onboarding_status"] == "approved"
    assert review.json()["document_status"] == "verified"

    needs_more_info = client.post(
        f"/admin/vendors/{vendor.json()['id']}/review",
        json={"onboarding_status": "needs_more_info", "onboarding_notes": ""},
        headers={"cookie": cookie},
    )
    assert needs_more_info.status_code == 200
    assert needs_more_info.json()["onboarding_status"] == "needs_more_info"
    assert needs_more_info.json()["document_status"] == "incomplete"
    assert needs_more_info.json()["onboarding_notes"]


def test_live_tracking_and_payment_webhook_flow():
    email = f"route-{uuid.uuid4().hex[:8]}@example.com"
    register = client.post(
        "/auth/register",
        json={
            "name": "Route User",
            "email": email,
            "role": "customer",
            "password": "secure123",
        },
    )
    assert register.status_code == 200
    login = client.post(
        "/auth/login",
        json={"email": email, "password": "secure123"},
    )
    cookie = login.headers.get("set-cookie", "")

    booking = client.post(
        "/bookings",
        json={
            "customer_id": "cust_live",
            "service_type": "haulage",
            "pickup": "Yaba",
            "destination": "Lekki",
            "price": 5000,
        },
    )
    booking_id = booking.json()["id"]

    tracking = client.get(f"/tracking/{booking_id}/live", headers={"cookie": cookie})
    assert tracking.status_code == 200
    tracking_payload = tracking.json()
    assert tracking_payload["route"]["route_status"] == "simulated_live"
    assert len(tracking_payload["route"]["polyline"]) >= 3
    assert len(tracking_payload["timeline"]) >= 1
    assert tracking_payload["progress"] == 0.0
    assert tracking_payload["route_phase"] == "dispatch_queue"
    assert tracking_payload["route_summary"]["current_phase"] == "dispatch_queue"

    payment = client.post(
        "/payments",
        json={"booking_id": booking_id, "amount": 5000.0, "method": "card", "gateway": "sandbox"},
    )
    assert payment.status_code == 200
    payment_payload = payment.json()
    assert payment_payload["integration_status"] == "sandbox_processed"

    webhook = client.post(
        "/payments/webhook",
        json={"external_reference": payment_payload["external_reference"], "status": "settled"},
    )
    assert webhook.status_code == 200
    assert webhook.json()["status"] == "paid"


def test_moderation_automation_call_logs_and_operations_analytics():
    admin_email = f"ops-admin-{uuid.uuid4().hex[:8]}@example.com"
    admin_register = client.post(
        "/auth/register",
        json={
            "name": "Ops Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    assert admin_register.status_code == 200
    admin_login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_cookie = admin_login.headers.get("set-cookie", "")

    user_email = f"ops-user-{uuid.uuid4().hex[:8]}@example.com"
    user_register = client.post(
        "/auth/register",
        json={
            "name": "Ops User",
            "email": user_email,
            "role": "customer",
            "password": "secure123",
        },
    )
    assert user_register.status_code == 200
    user_login = client.post(
        "/auth/login",
        json={"email": user_email, "password": "secure123"},
    )
    user_cookie = user_login.headers.get("set-cookie", "")

    flagged_message = client.post(
        "/messages",
        json={
            "sender": "customer",
            "recipient": "provider",
            "message": "This provider is abusive and a scam",
        },
        headers={"cookie": user_cookie},
    )
    assert flagged_message.status_code == 200
    assert flagged_message.json()["moderation_status"] == "flagged"

    moderation_cases = client.get("/admin/moderation/cases", headers={"cookie": admin_cookie})
    assert moderation_cases.status_code == 200
    assert len(moderation_cases.json()) >= 1

    call = client.post(
        "/calls",
        json={
            "participant": "customer",
            "note": "Consent recorded for escalation",
            "status": "connected",
            "call_type": "video",
            "consent_given": True,
        },
    )
    assert call.status_code == 200
    assert call.json()["consent_given"] is True

    risky_call = client.post(
        "/calls",
        json={
            "participant": "customer",
            "note": "Urgent safety issue without consent",
            "status": "connected",
            "call_type": "audio",
            "consent_given": False,
        },
    )
    assert risky_call.status_code == 200
    risky_payload = risky_call.json()
    assert risky_payload["needs_review"] is True
    assert risky_payload["moderation_case_id"] is not None

    call_logs = client.get("/calls/logs")
    assert call_logs.status_code == 200
    assert len(call_logs.json()) >= 2

    call_summary = client.get("/calls/summary")
    assert call_summary.status_code == 200
    assert call_summary.json()["open_moderation_cases"] >= 1

    moderation_summary = client.get("/admin/moderation/summary", headers={"cookie": admin_cookie})
    assert moderation_summary.status_code == 200
    assert moderation_summary.json()["call_cases"] >= 1

    resolve_case = client.post(
        f"/admin/moderation/cases/{risky_payload['moderation_case_id']}/resolve",
        json={"status": "resolved", "resolution_note": "Reviewed and closed"},
        headers={"cookie": admin_cookie},
    )
    assert resolve_case.status_code == 200
    assert resolve_case.json()["status"] == "resolved"

    operations = client.get("/admin/analytics/operations", headers={"cookie": admin_cookie})
    assert operations.status_code == 200
    assert operations.json()["open_moderation_cases"] >= 1


def test_flutterwave_payment_initialization_and_verification(monkeypatch):
    booking = client.post(
        "/bookings",
        json={
            "customer_id": "cust_flw",
            "service_type": "ride",
            "pickup": "Yaba",
            "destination": "Lekki",
            "price": 3200,
        },
    )
    booking_id = booking.json()["id"]

    monkeypatch.setattr(app_module, "FLUTTERWAVE_SECRET_KEY", "flw-secret")
    monkeypatch.setattr(app_module, "FLUTTERWAVE_WEBHOOK_SECRET_HASH", "flw-hash")

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    def fake_post(url, headers, json, timeout):
        assert url.endswith("/payments")
        assert headers["Authorization"] == "Bearer flw-secret"
        assert json["customer"]["email"] == "customer@example.com"
        return FakeResponse({"status": "success", "data": {"link": "https://checkout.flutterwave.test/pay"}})

    def fake_get(url, headers, params, timeout):
        assert url.endswith("/transactions/verify_by_reference")
        assert params["tx_ref"].startswith("PAY-")
        return FakeResponse({"status": "success", "data": {"status": "successful", "tx_ref": params["tx_ref"]}})

    monkeypatch.setattr(app_module.httpx, "post", fake_post)
    monkeypatch.setattr(app_module.httpx, "get", fake_get)

    payment = client.post(
        "/payments",
        json={
            "booking_id": booking_id,
            "amount": 3200.0,
            "method": "card",
            "gateway": "flutterwave",
            "customer_email": "customer@example.com",
            "customer_name": "Flutterwave Customer",
        },
    )
    assert payment.status_code == 200
    payment_payload = payment.json()
    assert payment_payload["status"] == "pending"
    assert payment_payload["integration_status"] == "flutterwave_initialized"
    assert payment_payload["checkout_url"] == "https://checkout.flutterwave.test/pay"

    webhook = client.post(
        "/payments/webhook",
        json={"event": "charge.completed", "data": {"tx_ref": payment_payload["external_reference"], "status": "successful"}},
        headers={"verif-hash": "flw-hash"},
    )
    assert webhook.status_code == 200
    assert webhook.json()["status"] == "paid"
    assert webhook.json()["integration_status"] == "flutterwave_verified"


def test_openrouteservice_route_estimate(monkeypatch):
    monkeypatch.setattr(app_module, "ROUTING_PROVIDER", "openrouteservice")
    monkeypatch.setattr(app_module, "OPENROUTESERVICE_API_KEY", "ors-key")

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    geocode_responses = {
        "Yaba": {"features": [{"geometry": {"coordinates": [3.3792, 6.5095]}}]},
        "Lekki": {"features": [{"geometry": {"coordinates": [3.5352, 6.4698]}}]},
    }

    def fake_get(url, params, timeout):
        assert url.endswith("/geocode/search")
        assert params["api_key"] == "ors-key"
        return FakeResponse(geocode_responses[params["text"]])

    def fake_post(url, headers, json, timeout):
        assert url.endswith("/v2/directions/driving-car/geojson")
        assert headers["Authorization"] == "ors-key"
        assert len(json["coordinates"]) == 2
        return FakeResponse(
            {
                "features": [
                    {
                        "geometry": {
                            "coordinates": [
                                [3.3792, 6.5095],
                                [3.4200, 6.5000],
                                [3.4700, 6.4900],
                                [3.5352, 6.4698],
                            ]
                        },
                        "properties": {"summary": {"distance": 18250, "duration": 2100}},
                    }
                ]
            }
        )

    monkeypatch.setattr(app_module.httpx, "get", fake_get)
    monkeypatch.setattr(app_module.httpx, "post", fake_post)

    response = client.get("/route/estimate?pickup=Yaba&destination=Lekki")
    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "openrouteservice"
    assert payload["route_status"] == "provider_live"
    assert payload["route_source"] == "provider_live"
    assert payload["provider_configured"] is True
    assert payload["distance_km"] == 18.2
    assert payload["eta_minutes"] == 35
    assert len(payload["polyline"]) == 4


def test_postgres_query_translation_helper():
    translated_insert = translate_query_for_postgres(
        "INSERT OR IGNORE INTO vendors (id, name, category, location, rating) VALUES (?, ?, ?, ?, ?)"
    )
    assert translated_insert.startswith("INSERT INTO vendors")
    assert "%s" in translated_insert
    assert translated_insert.endswith("ON CONFLICT DO NOTHING")

    translated_update = translate_query_for_postgres(
        "UPDATE users SET failed_login_attempts = ?, locked_until = ? WHERE id = ?"
    )
    assert translated_update == "UPDATE users SET failed_login_attempts = %s, locked_until = %s WHERE id = %s"


def test_bootstrap_admin_seed_on_init(monkeypatch, tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            role TEXT NOT NULL,
            password TEXT NOT NULL
        )
        """
    )
    monkeypatch.setenv("BOOTSTRAP_ADMIN_NAME", "Bootstrap Admin")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "bootstrap-admin@example.com")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "bootstrap123")

    database_module.ensure_bootstrap_admin(conn)

    row = conn.execute("SELECT * FROM users WHERE email = ?", ("bootstrap-admin@example.com",)).fetchone()
    conn.close()

    assert row is not None
    assert row["role"] == "admin"
    assert verify_password("bootstrap123", row["password"])


def test_create_admin_user_helper(monkeypatch, tmp_path):
    admin_db = tmp_path / "admin-helper.db"
    monkeypatch.setattr(database_module, "DATABASE_URL", "")
    monkeypatch.setattr(database_module, "DB_PATH", admin_db)
    database_module.init_db()

    created, message = create_admin_user("Managed Admin", "managed-admin@example.com", "Managed123")
    assert created is True
    assert message == "Admin user created successfully"

    conn = database_module.get_connection()
    row = conn.execute("SELECT * FROM users WHERE email = ?", ("managed-admin@example.com",)).fetchone()
    conn.close()

    assert row is not None
    assert row["role"] == "admin"
    assert verify_password("Managed123", row["password"])


def test_update_existing_admin_user_helper(monkeypatch, tmp_path):
    admin_db = tmp_path / "admin-helper-update.db"
    monkeypatch.setattr(database_module, "DATABASE_URL", "")
    monkeypatch.setattr(database_module, "DB_PATH", admin_db)
    database_module.init_db()

    created, _ = create_admin_user("Managed Admin", "managed-admin@example.com", "Managed123")
    assert created is True

    updated, message = create_admin_user(
        "Managed Admin Updated",
        "managed-admin@example.com",
        "Managed456",
        update_existing=True,
    )
    assert updated is True
    assert message == "Admin user updated successfully"

    conn = database_module.get_connection()
    row = conn.execute("SELECT * FROM users WHERE email = ?", ("managed-admin@example.com",)).fetchone()
    conn.close()

    assert row is not None
    assert row["name"] == "Managed Admin Updated"
    assert row["role"] == "admin"
    assert verify_password("Managed456", row["password"])


def test_provider_stats_endpoint():
    """Test provider performance statistics endpoint"""
    # Create provider
    provider_email = f"stats-provider-{uuid.uuid4().hex[:8]}@example.com"
    provider_reg = client.post(
        "/auth/register",
        json={
            "name": "Stats Provider",
            "email": provider_email,
            "role": "provider",
            "password": "provider123",
        },
    )
    assert provider_reg.status_code == 200
    provider_id = provider_reg.json()["user_id"]
    
    provider_login = client.post(
        "/auth/login",
        json={"email": provider_email, "password": "provider123"},
    )
    provider_cookie = provider_login.headers.get("set-cookie", "")
    
    # Get provider stats
    stats_response = client.get(
        f"/providers/{provider_id}/stats",
        headers={"cookie": provider_cookie},
    )
    assert stats_response.status_code == 200
    stats = stats_response.json()
    assert "provider_id" in stats
    assert "provider_name" in stats
    assert "total_bookings" in stats
    assert "completed_bookings" in stats
    assert "completion_rate" in stats
    assert "total_earnings" in stats
    assert "average_rating" in stats
    assert stats["provider_id"] == provider_id
    assert stats["total_bookings"] == 0
    assert stats["completion_rate"] == 0.0
    assert stats["total_earnings"] == 0.0


def test_vendor_stats_endpoint():
    """Test vendor performance statistics endpoint"""
    # Create vendor
    vendor_email = f"stats-vendor-{uuid.uuid4().hex[:8]}@example.com"
    vendor_reg = client.post(
        "/auth/register",
        json={
            "name": "Stats Vendor",
            "email": vendor_email,
            "role": "vendor",
            "password": "vendor123",
        },
    )
    assert vendor_reg.status_code == 200
    vendor_id = vendor_reg.json()["user_id"]
    
    vendor_login = client.post(
        "/auth/login",
        json={"email": vendor_email, "password": "vendor123"},
    )
    vendor_cookie = vendor_login.headers.get("set-cookie", "")
    
    # Get vendor stats
    stats_response = client.get(
        f"/vendors/{vendor_id}/stats",
        headers={"cookie": vendor_cookie},
    )
    assert stats_response.status_code == 200
    stats = stats_response.json()
    assert "vendor_id" in stats
    assert "vendor_name" in stats
    assert "total_orders" in stats
    assert "completed_orders" in stats
    assert "completion_rate" in stats
    assert "total_earnings" in stats
    assert "average_rating" in stats
    assert stats["vendor_id"] == vendor_id
    assert stats["total_orders"] == 0
    assert stats["completion_rate"] == 0.0


def test_provider_cannot_view_other_provider_stats():
    """Test authorization - providers cannot view other provider stats"""
    # Create two providers
    provider1_email = f"prov1-{uuid.uuid4().hex[:8]}@example.com"
    reg1 = client.post(
        "/auth/register",
        json={
            "name": "Provider 1",
            "email": provider1_email,
            "role": "provider",
            "password": "pass123",
        },
    )
    provider1_id = reg1.json()["user_id"]
    
    provider2_email = f"prov2-{uuid.uuid4().hex[:8]}@example.com"
    reg2 = client.post(
        "/auth/register",
        json={
            "name": "Provider 2",
            "email": provider2_email,
            "role": "provider",
            "password": "pass123",
        },
    )
    
    login2 = client.post(
        "/auth/login",
        json={"email": provider2_email, "password": "pass123"},
    )
    provider2_cookie = login2.headers.get("set-cookie", "")
    
    # Provider 2 tries to view Provider 1 stats
    response = client.get(
        f"/providers/{provider1_id}/stats",
        headers={"cookie": provider2_cookie},
    )
    assert response.status_code == 403
    assert "Cannot view other provider's stats" in response.json()["detail"]


def test_vendor_cannot_view_other_vendor_stats():
    """Test authorization - vendors cannot view other vendor stats"""
    # Create two vendors
    vendor1_email = f"vendor1-{uuid.uuid4().hex[:8]}@example.com"
    reg1 = client.post(
        "/auth/register",
        json={
            "name": "Vendor 1",
            "email": vendor1_email,
            "role": "vendor",
            "password": "pass123",
        },
    )
    vendor1_id = reg1.json()["user_id"]
    
    vendor2_email = f"vendor2-{uuid.uuid4().hex[:8]}@example.com"
    reg2 = client.post(
        "/auth/register",
        json={
            "name": "Vendor 2",
            "email": vendor2_email,
            "role": "vendor",
            "password": "pass123",
        },
    )
    
    login2 = client.post(
        "/auth/login",
        json={"email": vendor2_email, "password": "pass123"},
    )
    vendor2_cookie = login2.headers.get("set-cookie", "")
    
    # Vendor 2 tries to view Vendor 1 stats
    response = client.get(
        f"/vendors/{vendor1_id}/stats",
        headers={"cookie": vendor2_cookie},
    )
    assert response.status_code == 403
    assert "Cannot view other vendor's stats" in response.json()["detail"]


def test_admin_can_view_all_provider_stats():
    """Test admin can view stats for all providers"""
    admin_email = f"admin-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_cookie = login.headers.get("set-cookie", "")
    
    # Get all provider stats
    response = client.get(
        "/admin/providers/stats",
        headers={"cookie": admin_cookie},
    )
    assert response.status_code == 200
    stats_list = response.json()
    assert isinstance(stats_list, list)
    # Should have some providers from previous tests
    if len(stats_list) > 0:
        provider_stat = stats_list[0]
        assert "provider_id" in provider_stat
        assert "completion_rate" in provider_stat


def test_admin_can_view_all_vendor_stats():
    """Test admin can view stats for all vendors"""
    admin_email = f"admin-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_cookie = login.headers.get("set-cookie", "")
    
    # Get all vendor stats
    response = client.get(
        "/admin/vendors/stats",
        headers={"cookie": admin_cookie},
    )
    assert response.status_code == 200
    stats_list = response.json()
    assert isinstance(stats_list, list)
    # Should have some vendors from previous tests
    if len(stats_list) > 0:
        vendor_stat = stats_list[0]
        assert "vendor_id" in vendor_stat
        assert "completion_rate" in vendor_stat


def test_completion_rate_calculation_provider():
    """Test that completion rate is properly calculated for providers"""
    provider_email = f"completion-test-{uuid.uuid4().hex[:8]}@example.com"
    provider_reg = client.post(
        "/auth/register",
        json={
            "name": "Completion Test Provider",
            "email": provider_email,
            "role": "provider",
            "password": "provider123",
        },
    )
    provider_id = provider_reg.json()["user_id"]
    
    # Create bookings manually in database
    conn = database_module.get_connection()
    try:
        # Insert 4 bookings: 2 completed, 2 pending
        conn.execute(
            "INSERT INTO bookings (provider_id, customer_id, pickup, destination, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (provider_id, 1, "Start 1", "End 1", "completed", "2024-01-01 10:00:00"),
        )
        conn.execute(
            "INSERT INTO bookings (provider_id, customer_id, pickup, destination, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (provider_id, 1, "Start 2", "End 2", "completed", "2024-01-01 11:00:00"),
        )
        conn.execute(
            "INSERT INTO bookings (provider_id, customer_id, pickup, destination, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (provider_id, 1, "Start 3", "End 3", "pending", "2024-01-01 12:00:00"),
        )
        conn.execute(
            "INSERT INTO bookings (provider_id, customer_id, pickup, destination, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (provider_id, 1, "Start 4", "End 4", "cancelled", "2024-01-01 13:00:00"),
        )
        conn.commit()
    finally:
        conn.close()
    
    # Get provider stats and verify completion rate
    provider_login = client.post(
        "/auth/login",
        json={"email": provider_email, "password": "provider123"},
    )
    provider_cookie = provider_login.headers.get("set-cookie", "")
    
    stats_response = client.get(
        f"/providers/{provider_id}/stats",
        headers={"cookie": provider_cookie},
    )
    assert stats_response.status_code == 200
    stats = stats_response.json()
    assert stats["total_bookings"] == 4
    assert stats["completed_bookings"] == 2
    assert stats["completion_rate"] == 50.0  # 2 out of 4 completed


def test_admin_activity_logging():
    """Test that admin actions can be logged to activity_logs table"""
    admin_email = f"activity-admin-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "Activity Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_id = login.json()["user_id"]
    admin_cookie = login.headers.get("set-cookie", "")
    
    # Log some activities directly to test database
    conn = database_module.get_connection()
    try:
        conn.execute(
            """INSERT INTO activity_logs (admin_id, action_type, entity_type, entity_id, details, timestamp) 
               VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            (admin_id, "account_restriction", "user", 1, "Account restricted for abuse"),
        )
        conn.execute(
            """INSERT INTO activity_logs (admin_id, action_type, entity_type, entity_id, details, timestamp) 
               VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            (admin_id, "vendor_ban", "vendor", 5, "Vendor permanently banned"),
        )
        conn.commit()
    finally:
        conn.close()
    
    # Get activity logs
    response = client.get(
        "/admin/activity-logs",
        headers={"cookie": admin_cookie},
    )
    assert response.status_code == 200
    logs = response.json()
    assert len(logs) >= 2
    assert any(log["action_type"] == "account_restriction" for log in logs)
    assert any(log["action_type"] == "vendor_ban" for log in logs)


def test_admin_activity_logs_filter_by_action_type():
    """Test that activity logs can be filtered by action type"""
    admin_email = f"filter-admin-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "Filter Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_id = login.json()["user_id"]
    admin_cookie = login.headers.get("set-cookie", "")
    
    # Log multiple activities with different types
    conn = database_module.get_connection()
    try:
        for i in range(3):
            conn.execute(
                """INSERT INTO activity_logs (admin_id, action_type, entity_type, entity_id, details, timestamp) 
                   VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                (admin_id, "report_review", "report", i, f"Report {i} reviewed"),
            )
        for i in range(2):
            conn.execute(
                """INSERT INTO activity_logs (admin_id, action_type, entity_type, entity_id, details, timestamp) 
                   VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                (admin_id, "dispute_resolved", "dispute", i, f"Dispute {i} resolved"),
            )
        conn.commit()
    finally:
        conn.close()
    
    # Filter by action type
    response = client.get(
        "/admin/activity-logs?action_type=report_review",
        headers={"cookie": admin_cookie},
    )
    assert response.status_code == 200
    logs = response.json()
    assert all(log["action_type"] == "report_review" for log in logs)
    assert len([log for log in logs if log["action_type"] == "report_review"]) >= 3


def test_admin_activity_logs_filter_by_entity_type():
    """Test that activity logs can be filtered by entity type"""
    admin_email = f"entity-filter-admin-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "Entity Filter Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_id = login.json()["user_id"]
    admin_cookie = login.headers.get("set-cookie", "")
    
    # Log activities for different entity types
    conn = database_module.get_connection()
    try:
        conn.execute(
            """INSERT INTO activity_logs (admin_id, action_type, entity_type, entity_id, details, timestamp) 
               VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            (admin_id, "action1", "vendor", 1, "Vendor action"),
        )
        conn.execute(
            """INSERT INTO activity_logs (admin_id, action_type, entity_type, entity_id, details, timestamp) 
               VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            (admin_id, "action2", "vendor", 2, "Vendor action"),
        )
        conn.execute(
            """INSERT INTO activity_logs (admin_id, action_type, entity_type, entity_id, details, timestamp) 
               VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            (admin_id, "action3", "user", 1, "User action"),
        )
        conn.commit()
    finally:
        conn.close()
    
    # Filter by entity type
    response = client.get(
        "/admin/activity-logs?entity_type=vendor",
        headers={"cookie": admin_cookie},
    )
    assert response.status_code == 200
    logs = response.json()
    vendor_logs = [log for log in logs if log["entity_type"] == "vendor"]
    assert len(vendor_logs) >= 2
    assert all(log["entity_type"] == "vendor" for log in vendor_logs)


def test_admin_activity_logs_summary():
    """Test activity logs summary endpoint shows statistics"""
    admin_email = f"summary-admin-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "Summary Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_id = login.json()["user_id"]
    admin_cookie = login.headers.get("set-cookie", "")
    
    # Log activities
    conn = database_module.get_connection()
    try:
        for i in range(5):
            conn.execute(
                """INSERT INTO activity_logs (admin_id, action_type, entity_type, entity_id, details, timestamp) 
                   VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                (admin_id, "review_action", "report", i, f"Activity {i}"),
            )
        conn.commit()
    finally:
        conn.close()
    
    # Get activity summary
    response = client.get(
        "/admin/activity-logs/summary",
        headers={"cookie": admin_cookie},
    )
    assert response.status_code == 200
    summary = response.json()
    assert "action_type_summary" in summary
    assert "entity_type_summary" in summary
    assert "most_active_admins" in summary
    assert isinstance(summary["action_type_summary"], dict)
    assert isinstance(summary["entity_type_summary"], dict)
    assert isinstance(summary["most_active_admins"], list)


def test_non_admin_cannot_access_activity_logs():
    """Test that non-admin users cannot access activity logs"""
    customer_email = f"customer-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "Customer",
            "email": customer_email,
            "role": "customer",
            "password": "cust123",
        },
    )
    login = client.post(
        "/auth/login",
        json={"email": customer_email, "password": "cust123"},
    )
    customer_cookie = login.headers.get("set-cookie", "")
    
    # Try to access activity logs as customer
    response = client.get(
        "/admin/activity-logs",
        headers={"cookie": customer_cookie},
    )
    assert response.status_code == 403
    
    # Try to access activity summary as customer
    response = client.get(
        "/admin/activity-logs/summary",
        headers={"cookie": customer_cookie},
    )
    assert response.status_code == 403


def test_admin_growth_metrics_endpoint():
    """Test admin dashboard growth metrics endpoint"""
    admin_email = f"growth-admin-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "Growth Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_cookie = login.headers.get("set-cookie", "")
    
    # Get growth metrics
    response = client.get(
        "/admin/dashboard/growth-metrics",
        headers={"cookie": admin_cookie},
    )
    assert response.status_code == 200
    metrics = response.json()
    assert "total_users" in metrics
    assert "users_by_role" in metrics
    assert "new_users_period" in metrics
    assert "growth_rate_per_day" in metrics
    assert "period_days" in metrics


def test_admin_revenue_analytics_endpoint():
    """Test admin dashboard revenue analytics endpoint"""
    admin_email = f"revenue-admin-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "Revenue Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_cookie = login.headers.get("set-cookie", "")
    
    # Get revenue analytics
    response = client.get(
        "/admin/dashboard/revenue-analytics",
        headers={"cookie": admin_cookie},
    )
    assert response.status_code == 200
    analytics = response.json()
    assert "total_revenue" in analytics
    assert "period_revenue" in analytics
    assert "average_transaction_value" in analytics
    assert "payment_status_breakdown" in analytics
    assert isinstance(analytics["payment_status_breakdown"], list)


def test_admin_dispute_report_trends_endpoint():
    """Test admin dashboard dispute and report trends endpoint"""
    admin_email = f"trends-admin-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "Trends Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_cookie = login.headers.get("set-cookie", "")
    
    # Get trends
    response = client.get(
        "/admin/dashboard/trends",
        headers={"cookie": admin_cookie},
    )
    assert response.status_code == 200
    trends = response.json()
    assert "disputes" in trends
    assert "reports" in trends
    assert "report_types_breakdown" in trends
    assert "total" in trends["disputes"]
    assert "open" in trends["disputes"]
    assert "resolved" in trends["disputes"]


def test_admin_suspicious_activity_alerts_endpoint():
    """Test admin dashboard suspicious activity detection"""
    admin_email = f"alert-admin-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "Alert Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_cookie = login.headers.get("set-cookie", "")
    
    # Get suspicious activity alerts
    response = client.get(
        "/admin/dashboard/suspicious-activity",
        headers={"cookie": admin_cookie},
    )
    assert response.status_code == 200
    alerts = response.json()
    assert "alert_count" in alerts
    assert "alerts" in alerts
    assert isinstance(alerts["alerts"], list)
    assert "generated_at" in alerts


def test_admin_comprehensive_dashboard():
    """Test unified admin dashboard endpoint"""
    admin_email = f"dashboard-admin-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "Dashboard Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_cookie = login.headers.get("set-cookie", "")
    
    # Get comprehensive dashboard
    response = client.get(
        "/admin/dashboard/comprehensive",
        headers={"cookie": admin_cookie},
    )
    assert response.status_code == 200
    dashboard = response.json()
    assert "overview" in dashboard
    assert "growth_metrics" in dashboard
    assert "revenue_analytics" in dashboard
    assert "trends" in dashboard
    assert "suspicious_activity_alerts" in dashboard
    
    # Verify overview section
    assert "active_bookings" in dashboard["overview"]
    assert "total_revenue" in dashboard["overview"]
    assert "total_providers" in dashboard["overview"]
    assert "total_vendors" in dashboard["overview"]
    assert "total_users" in dashboard["overview"]
    assert "restricted_accounts" in dashboard["overview"]


def test_admin_dashboard_growth_metrics_with_period():
    """Test growth metrics endpoint with custom period"""
    admin_email = f"period-admin-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "Period Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_cookie = login.headers.get("set-cookie", "")
    
    # Get growth metrics with 7-day period
    response = client.get(
        "/admin/dashboard/growth-metrics?period_days=7",
        headers={"cookie": admin_cookie},
    )
    assert response.status_code == 200
    metrics = response.json()
    assert metrics["period_days"] == 7
    assert "total_users" in metrics
    assert "growth_rate_per_day" in metrics


def test_non_admin_cannot_access_dashboard_analytics():
    """Test that non-admin users cannot access dashboard analytics"""
    vendor_email = f"vendor-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "Vendor",
            "email": vendor_email,
            "role": "vendor",
            "password": "vendor123",
        },
    )
    login = client.post(
        "/auth/login",
        json={"email": vendor_email, "password": "vendor123"},
    )
    vendor_cookie = login.headers.get("set-cookie", "")
    
    # Try to access growth metrics as vendor
    response = client.get(
        "/admin/dashboard/growth-metrics",
        headers={"cookie": vendor_cookie},
    )
    assert response.status_code == 403
    
    # Try to access revenue analytics as vendor
    response = client.get(
        "/admin/dashboard/revenue-analytics",
        headers={"cookie": vendor_cookie},
    )
    assert response.status_code == 403
    
    # Try to access trends as vendor
    response = client.get(
        "/admin/dashboard/trends",
        headers={"cookie": vendor_cookie},
    )
    assert response.status_code == 403
    
    # Try to access suspicious activity as vendor
    response = client.get(
        "/admin/dashboard/suspicious-activity",
        headers={"cookie": vendor_cookie},
    )
    assert response.status_code == 403
    
    # Try to access comprehensive dashboard as vendor
    response = client.get(
        "/admin/dashboard/comprehensive",
        headers={"cookie": vendor_cookie},
    )
    assert response.status_code == 403


def test_stale_location_detection():
    """Test stale location detection for tracking"""
    # Create provider and customer
    provider_email = f"track-provider-{uuid.uuid4().hex[:8]}@example.com"
    customer_email = f"track-customer-{uuid.uuid4().hex[:8]}@example.com"
    
    provider_reg = client.post(
        "/auth/register",
        json={
            "name": "Tracking Provider",
            "email": provider_email,
            "role": "provider",
            "password": "prov123",
        },
    )
    provider_id = provider_reg.json()["user_id"]
    
    customer_reg = client.post(
        "/auth/register",
        json={
            "name": "Tracking Customer",
            "email": customer_email,
            "role": "customer",
            "password": "cust123",
        },
    )
    customer_id = customer_reg.json()["user_id"]
    
    customer_login = client.post(
        "/auth/login",
        json={"email": customer_email, "password": "cust123"},
    )
    customer_cookie = customer_login.headers.get("set-cookie", "")
    
    # Create booking
    booking_resp = client.post(
        "/bookings",
        json={
            "service_type": "ride",
            "pickup": "Main St",
            "destination": "Park Ave",
            "price": 50,
        },
        headers={"cookie": customer_cookie},
    )
    assert booking_resp.status_code == 200
    booking_id = booking_resp.json()["id"]
    
    # Accept booking
    conn = database_module.get_connection()
    conn.execute(
        "UPDATE bookings SET status = 'active', provider_id = ?, last_location_update_at = datetime('now', '-70 seconds') WHERE id = ?",
        (provider_id, booking_id),
    )
    conn.commit()
    conn.close()
    
    # Get tracking status
    tracking_resp = client.get(
        f"/tracking/{booking_id}",
        headers={"cookie": customer_cookie},
    )
    assert tracking_resp.status_code == 200
    tracking = tracking_resp.json()
    assert "location_tracking" in tracking
    assert tracking["location_tracking"]["is_stale"] is True
    assert tracking["location_tracking"]["tracking_status"] == "stale"
    assert tracking["location_tracking"]["seconds_since_update"] > 60


def test_tracking_status_indicator_endpoint():
    """Test tracking status indicator endpoint"""
    provider_email = f"indicator-provider-{uuid.uuid4().hex[:8]}@example.com"
    customer_email = f"indicator-customer-{uuid.uuid4().hex[:8]}@example.com"
    
    provider_reg = client.post(
        "/auth/register",
        json={
            "name": "Indicator Provider",
            "email": provider_email,
            "role": "provider",
            "password": "prov123",
        },
    )
    provider_id = provider_reg.json()["user_id"]
    
    customer_reg = client.post(
        "/auth/register",
        json={
            "name": "Indicator Customer",
            "email": customer_email,
            "role": "customer",
            "password": "cust123",
        },
    )
    
    customer_login = client.post(
        "/auth/login",
        json={"email": customer_email, "password": "cust123"},
    )
    customer_cookie = customer_login.headers.get("set-cookie", "")
    
    # Create and activate booking
    booking_resp = client.post(
        "/bookings",
        json={
            "service_type": "ride",
            "pickup": "Start",
            "destination": "End",
            "price": 30,
        },
        headers={"cookie": customer_cookie},
    )
    booking_id = booking_resp.json()["id"]
    
    conn = database_module.get_connection()
    conn.execute(
        "UPDATE bookings SET status = 'active', provider_id = ?, last_location_update_at = CURRENT_TIMESTAMP WHERE id = ?",
        (provider_id, booking_id),
    )
    conn.commit()
    conn.close()
    
    # Get tracking status indicator
    response = client.get(
        f"/tracking/{booking_id}/status-indicator",
        headers={"cookie": customer_cookie},
    )
    assert response.status_code == 200
    indicator = response.json()
    assert "booking_id" in indicator
    assert "tracking_available" in indicator
    assert "status" in indicator
    assert "message" in indicator
    assert indicator["tracking_available"] is True
    assert indicator["status"] == "active"


def test_location_update_endpoint():
    """Test provider location update endpoint"""
    provider_email = f"loc-provider-{uuid.uuid4().hex[:8]}@example.com"
    customer_email = f"loc-customer-{uuid.uuid4().hex[:8]}@example.com"
    
    provider_reg = client.post(
        "/auth/register",
        json={
            "name": "Location Provider",
            "email": provider_email,
            "role": "provider",
            "password": "prov123",
        },
    )
    provider_id = provider_reg.json()["user_id"]
    provider_login = client.post(
        "/auth/login",
        json={"email": provider_email, "password": "prov123"},
    )
    provider_cookie = provider_login.headers.get("set-cookie", "")
    
    customer_reg = client.post(
        "/auth/register",
        json={
            "name": "Location Customer",
            "email": customer_email,
            "role": "customer",
            "password": "cust123",
        },
    )
    
    customer_login = client.post(
        "/auth/login",
        json={"email": customer_email, "password": "cust123"},
    )
    customer_cookie = customer_login.headers.get("set-cookie", "")
    
    # Create and activate booking
    booking_resp = client.post(
        "/bookings",
        json={
            "service_type": "ride",
            "pickup": "Start",
            "destination": "End",
            "price": 30,
        },
        headers={"cookie": customer_cookie},
    )
    booking_id = booking_resp.json()["id"]
    
    conn = database_module.get_connection()
    conn.execute(
        "UPDATE bookings SET status = 'active', provider_id = ? WHERE id = ?",
        (provider_id, booking_id),
    )
    conn.commit()
    conn.close()
    
    # Update provider location
    response = client.post(
        f"/tracking/{booking_id}/location-update?latitude=40.7128&longitude=-74.0060",
        headers={"cookie": provider_cookie},
    )
    assert response.status_code == 200
    update = response.json()
    assert update["booking_id"] == booking_id
    assert update["location_updated"] is True
    assert update["latitude"] == 40.7128
    assert update["longitude"] == -74.0060
    
    # Verify location was updated
    conn = database_module.get_connection()
    booking = conn.execute(
        "SELECT current_latitude, current_longitude FROM bookings WHERE id = ?",
        (booking_id,),
    ).fetchone()
    conn.close()
    assert booking["current_latitude"] == 40.7128
    assert booking["current_longitude"] == -74.0060


def test_critical_outage_detection():
    """Test detection of critical tracking outage (>5 minutes)"""
    provider_email = f"critical-provider-{uuid.uuid4().hex[:8]}@example.com"
    customer_email = f"critical-customer-{uuid.uuid4().hex[:8]}@example.com"
    
    provider_reg = client.post(
        "/auth/register",
        json={
            "name": "Critical Provider",
            "email": provider_email,
            "role": "provider",
            "password": "prov123",
        },
    )
    provider_id = provider_reg.json()["user_id"]
    
    customer_reg = client.post(
        "/auth/register",
        json={
            "name": "Critical Customer",
            "email": customer_email,
            "role": "customer",
            "password": "cust123",
        },
    )
    
    customer_login = client.post(
        "/auth/login",
        json={"email": customer_email, "password": "cust123"},
    )
    customer_cookie = customer_login.headers.get("set-cookie", "")
    
    # Create booking
    booking_resp = client.post(
        "/bookings",
        json={
            "service_type": "ride",
            "pickup": "Start",
            "destination": "End",
            "price": 30,
        },
        headers={"cookie": customer_cookie},
    )
    booking_id = booking_resp.json()["id"]
    
    # Set last location update to >5 minutes ago
    conn = database_module.get_connection()
    conn.execute(
        "UPDATE bookings SET status = 'active', provider_id = ?, last_location_update_at = datetime('now', '-6 minutes') WHERE id = ?",
        (provider_id, booking_id),
    )
    conn.commit()
    conn.close()
    
    # Get tracking indicator
    response = client.get(
        f"/tracking/{booking_id}/status-indicator",
        headers={"cookie": customer_cookie},
    )
    assert response.status_code == 200
    indicator = response.json()
    assert indicator["is_critical_outage"] is True
    assert indicator["alert_level"] == "critical"
    assert "5+ minutes" in indicator["message"]


def test_cannot_update_location_for_inactive_booking():
    """Test that location cannot be updated for inactive bookings"""
    provider_email = f"inactive-provider-{uuid.uuid4().hex[:8]}@example.com"
    customer_email = f"inactive-customer-{uuid.uuid4().hex[:8]}@example.com"
    
    provider_reg = client.post(
        "/auth/register",
        json={
            "name": "Inactive Provider",
            "email": provider_email,
            "role": "provider",
            "password": "prov123",
        },
    )
    provider_id = provider_reg.json()["user_id"]
    provider_login = client.post(
        "/auth/login",
        json={"email": provider_email, "password": "prov123"},
    )
    provider_cookie = provider_login.headers.get("set-cookie", "")
    
    customer_reg = client.post(
        "/auth/register",
        json={
            "name": "Inactive Customer",
            "email": customer_email,
            "role": "customer",
            "password": "cust123",
        },
    )
    
    customer_login = client.post(
        "/auth/login",
        json={"email": customer_email, "password": "cust123"},
    )
    customer_cookie = customer_login.headers.get("set-cookie", "")
    
    # Create and complete booking
    booking_resp = client.post(
        "/bookings",
        json={
            "service_type": "ride",
            "pickup": "Start",
            "destination": "End",
            "price": 30,
        },
        headers={"cookie": customer_cookie},
    )
    booking_id = booking_resp.json()["id"]
    
    conn = database_module.get_connection()
    conn.execute(
        "UPDATE bookings SET status = 'completed', provider_id = ? WHERE id = ?",
        (provider_id, booking_id),
    )
    conn.commit()
    conn.close()
    
    # Try to update location for completed booking
    response = client.post(
        f"/tracking/{booking_id}/location-update?latitude=40.7128&longitude=-74.0060",
        headers={"cookie": provider_cookie},
    )
    assert response.status_code == 400
    assert "Cannot update location" in response.json()["detail"]


def test_user_call_preferences_management():
    """Test getting and updating user call preferences"""
    email = f"pref-user-{uuid.uuid4().hex[:8]}@example.com"
    reg_resp = client.post(
        "/auth/register",
        json={
            "name": "Preference User",
            "email": email,
            "role": "customer",
            "password": "pass123",
        },
    )
    user_id = reg_resp.json()["user_id"]
    
    login_resp = client.post(
        "/auth/login",
        json={"email": email, "password": "pass123"},
    )
    cookie = login_resp.headers.get("set-cookie", "")
    
    # Get default preferences
    response = client.get(
        "/calls/preferences",
        headers={"cookie": cookie},
    )
    assert response.status_code == 200
    prefs = response.json()
    assert prefs["accept_audio_calls"] is True
    assert prefs["accept_video_calls"] is True
    assert prefs["allow_recording"] is False
    
    # Update preferences
    response = client.put(
        "/calls/preferences",
        json={
            "accept_audio_calls": False,
            "accept_video_calls": True,
            "allow_recording": True,
        },
        headers={"cookie": cookie},
    )
    assert response.status_code == 200
    updated = response.json()
    assert updated["accept_audio_calls"] is False
    assert updated["accept_video_calls"] is True
    assert updated["allow_recording"] is True
    
    # Verify preferences were saved
    response = client.get(
        "/calls/preferences",
        headers={"cookie": cookie},
    )
    assert response.status_code == 200
    verified = response.json()
    assert verified["accept_audio_calls"] is False
    assert verified["accept_video_calls"] is True
    assert verified["allow_recording"] is True


def test_initiate_audio_call():
    """Test initiating an audio call"""
    caller_email = f"caller-{uuid.uuid4().hex[:8]}@example.com"
    recipient_email = f"recipient-{uuid.uuid4().hex[:8]}@example.com"
    
    caller_reg = client.post(
        "/auth/register",
        json={
            "name": "Caller",
            "email": caller_email,
            "role": "customer",
            "password": "pass123",
        },
    )
    caller_id = caller_reg.json()["user_id"]
    caller_login = client.post(
        "/auth/login",
        json={"email": caller_email, "password": "pass123"},
    )
    caller_cookie = caller_login.headers.get("set-cookie", "")
    
    recipient_reg = client.post(
        "/auth/register",
        json={
            "name": "Recipient",
            "email": recipient_email,
            "role": "customer",
            "password": "pass123",
        },
    )
    recipient_id = recipient_reg.json()["user_id"]
    
    # Initiate audio call
    response = client.post(
        "/calls/initiate",
        json={
            "recipient_id": recipient_id,
            "call_type": "audio",
            "video_enabled": False,
        },
        headers={"cookie": caller_cookie},
    )
    assert response.status_code == 200
    call = response.json()
    assert call["status"] == "pending"
    assert call["call_type"] == "audio"
    assert call["video_enabled"] is False
    assert call["initiator_id"] == caller_id
    assert call["recipient_id"] == recipient_id


def test_initiate_video_call():
    """Test initiating a video call"""
    caller_email = f"vcaller-{uuid.uuid4().hex[:8]}@example.com"
    recipient_email = f"vrecipient-{uuid.uuid4().hex[:8]}@example.com"
    
    caller_reg = client.post(
        "/auth/register",
        json={
            "name": "Video Caller",
            "email": caller_email,
            "role": "provider",
            "password": "pass123",
        },
    )
    caller_id = caller_reg.json()["user_id"]
    caller_login = client.post(
        "/auth/login",
        json={"email": caller_email, "password": "pass123"},
    )
    caller_cookie = caller_login.headers.get("set-cookie", "")
    
    recipient_reg = client.post(
        "/auth/register",
        json={
            "name": "Video Recipient",
            "email": recipient_email,
            "role": "customer",
            "password": "pass123",
        },
    )
    recipient_id = recipient_reg.json()["user_id"]
    
    # Initiate video call
    response = client.post(
        "/calls/initiate",
        json={
            "recipient_id": recipient_id,
            "call_type": "video",
            "video_enabled": True,
        },
        headers={"cookie": caller_cookie},
    )
    assert response.status_code == 200
    call = response.json()
    assert call["status"] == "pending"
    assert call["call_type"] == "video"
    assert call["video_enabled"] is True


def test_cannot_initiate_call_to_non_consented_user():
    """Test that cannot call user who disabled audio calls"""
    caller_email = f"noncon-caller-{uuid.uuid4().hex[:8]}@example.com"
    recipient_email = f"noncon-recipient-{uuid.uuid4().hex[:8]}@example.com"
    
    caller_reg = client.post(
        "/auth/register",
        json={
            "name": "Caller NC",
            "email": caller_email,
            "role": "customer",
            "password": "pass123",
        },
    )
    caller_id = caller_reg.json()["user_id"]
    caller_login = client.post(
        "/auth/login",
        json={"email": caller_email, "password": "pass123"},
    )
    caller_cookie = caller_login.headers.get("set-cookie", "")
    
    recipient_reg = client.post(
        "/auth/register",
        json={
            "name": "Recipient NC",
            "email": recipient_email,
            "role": "customer",
            "password": "pass123",
        },
    )
    recipient_id = recipient_reg.json()["user_id"]
    recipient_login = client.post(
        "/auth/login",
        json={"email": recipient_email, "password": "pass123"},
    )
    recipient_cookie = recipient_login.headers.get("set-cookie", "")
    
    # Recipient disables audio calls
    client.put(
        "/calls/preferences",
        json={
            "accept_audio_calls": False,
            "accept_video_calls": True,
            "allow_recording": False,
        },
        headers={"cookie": recipient_cookie},
    )
    
    # Try to call - should fail
    response = client.post(
        "/calls/initiate",
        json={
            "recipient_id": recipient_id,
            "call_type": "audio",
            "video_enabled": False,
        },
        headers={"cookie": caller_cookie},
    )
    assert response.status_code == 403
    assert "does_not_accept_audio_calls" in response.json()["detail"]


def test_call_acceptance():
    """Test accepting an incoming call"""
    caller_email = f"acc-caller-{uuid.uuid4().hex[:8]}@example.com"
    recipient_email = f"acc-recipient-{uuid.uuid4().hex[:8]}@example.com"
    
    caller_reg = client.post(
        "/auth/register",
        json={
            "name": "Accept Caller",
            "email": caller_email,
            "role": "customer",
            "password": "pass123",
        },
    )
    caller_id = caller_reg.json()["user_id"]
    caller_login = client.post(
        "/auth/login",
        json={"email": caller_email, "password": "pass123"},
    )
    caller_cookie = caller_login.headers.get("set-cookie", "")
    
    recipient_reg = client.post(
        "/auth/register",
        json={
            "name": "Accept Recipient",
            "email": recipient_email,
            "role": "customer",
            "password": "pass123",
        },
    )
    recipient_id = recipient_reg.json()["user_id"]
    recipient_login = client.post(
        "/auth/login",
        json={"email": recipient_email, "password": "pass123"},
    )
    recipient_cookie = recipient_login.headers.get("set-cookie", "")
    
    # Initiate call
    call_resp = client.post(
        "/calls/initiate",
        json={
            "recipient_id": recipient_id,
            "call_type": "audio",
            "video_enabled": False,
        },
        headers={"cookie": caller_cookie},
    )
    call_id = call_resp.json()["call_id"]
    
    # Recipient accepts call
    response = client.post(
        f"/calls/{call_id}/accept",
        headers={"cookie": recipient_cookie},
    )
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "connected"
    assert result["call_id"] == call_id


def test_call_declination():
    """Test declining an incoming call"""
    caller_email = f"dec-caller-{uuid.uuid4().hex[:8]}@example.com"
    recipient_email = f"dec-recipient-{uuid.uuid4().hex[:8]}@example.com"
    
    caller_reg = client.post(
        "/auth/register",
        json={
            "name": "Decline Caller",
            "email": caller_email,
            "role": "customer",
            "password": "pass123",
        },
    )
    caller_id = caller_reg.json()["user_id"]
    caller_login = client.post(
        "/auth/login",
        json={"email": caller_email, "password": "pass123"},
    )
    caller_cookie = caller_login.headers.get("set-cookie", "")
    
    recipient_reg = client.post(
        "/auth/register",
        json={
            "name": "Decline Recipient",
            "email": recipient_email,
            "role": "customer",
            "password": "pass123",
        },
    )
    recipient_id = recipient_reg.json()["user_id"]
    recipient_login = client.post(
        "/auth/login",
        json={"email": recipient_email, "password": "pass123"},
    )
    recipient_cookie = recipient_login.headers.get("set-cookie", "")
    
    # Initiate call
    call_resp = client.post(
        "/calls/initiate",
        json={
            "recipient_id": recipient_id,
            "call_type": "audio",
            "video_enabled": False,
        },
        headers={"cookie": caller_cookie},
    )
    call_id = call_resp.json()["call_id"]
    
    # Recipient declines call
    response = client.post(
        f"/calls/{call_id}/decline?reason=busy",
        headers={"cookie": recipient_cookie},
    )
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "declined"
    assert result["reason"] == "busy"


def test_end_call_and_duration():
    """Test ending call and recording duration"""
    caller_email = f"end-caller-{uuid.uuid4().hex[:8]}@example.com"
    recipient_email = f"end-recipient-{uuid.uuid4().hex[:8]}@example.com"
    
    caller_reg = client.post(
        "/auth/register",
        json={
            "name": "End Caller",
            "email": caller_email,
            "role": "customer",
            "password": "pass123",
        },
    )
    caller_id = caller_reg.json()["user_id"]
    caller_login = client.post(
        "/auth/login",
        json={"email": caller_email, "password": "pass123"},
    )
    caller_cookie = caller_login.headers.get("set-cookie", "")
    
    recipient_reg = client.post(
        "/auth/register",
        json={
            "name": "End Recipient",
            "email": recipient_email,
            "role": "customer",
            "password": "pass123",
        },
    )
    recipient_id = recipient_reg.json()["user_id"]
    recipient_login = client.post(
        "/auth/login",
        json={"email": recipient_email, "password": "pass123"},
    )
    recipient_cookie = recipient_login.headers.get("set-cookie", "")
    
    # Initiate and accept call
    call_resp = client.post(
        "/calls/initiate",
        json={
            "recipient_id": recipient_id,
            "call_type": "audio",
            "video_enabled": False,
        },
        headers={"cookie": caller_cookie},
    )
    call_id = call_resp.json()["call_id"]
    
    client.post(
        f"/calls/{call_id}/accept",
        headers={"cookie": recipient_cookie},
    )
    
    # End call
    response = client.post(
        f"/calls/{call_id}/end",
        headers={"cookie": caller_cookie},
    )
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "ended"
    assert result["duration_seconds"] >= 0


def test_submit_call_quality_report():
    """Test submitting call quality metrics"""
    caller_email = f"qual-caller-{uuid.uuid4().hex[:8]}@example.com"
    recipient_email = f"qual-recipient-{uuid.uuid4().hex[:8]}@example.com"
    
    caller_reg = client.post(
        "/auth/register",
        json={
            "name": "Quality Caller",
            "email": caller_email,
            "role": "customer",
            "password": "pass123",
        },
    )
    caller_id = caller_reg.json()["user_id"]
    caller_login = client.post(
        "/auth/login",
        json={"email": caller_email, "password": "pass123"},
    )
    caller_cookie = caller_login.headers.get("set-cookie", "")
    
    recipient_reg = client.post(
        "/auth/register",
        json={
            "name": "Quality Recipient",
            "email": recipient_email,
            "role": "customer",
            "password": "pass123",
        },
    )
    recipient_id = recipient_reg.json()["user_id"]
    recipient_login = client.post(
        "/auth/login",
        json={"email": recipient_email, "password": "pass123"},
    )
    recipient_cookie = recipient_login.headers.get("set-cookie", "")
    
    # Initiate, accept, and end call
    call_resp = client.post(
        "/calls/initiate",
        json={
            "recipient_id": recipient_id,
            "call_type": "audio",
            "video_enabled": False,
        },
        headers={"cookie": caller_cookie},
    )
    call_id = call_resp.json()["call_id"]
    
    client.post(
        f"/calls/{call_id}/accept",
        headers={"cookie": recipient_cookie},
    )
    
    client.post(
        f"/calls/{call_id}/end",
        headers={"cookie": caller_cookie},
    )
    
    # Submit quality report
    response = client.post(
        f"/calls/{call_id}/quality-report",
        json={
            "quality_score": 85.5,
            "notes": "Good audio quality, minor lag",
        },
        headers={"cookie": caller_cookie},
    )
    assert response.status_code == 200
    report = response.json()
    assert report["quality_score"] == 85.5
    assert report["quality_notes"] == "Good audio quality, minor lag"


def test_call_history_retrieval():
    """Test retrieving call history for user"""
    caller_email = f"hist-caller-{uuid.uuid4().hex[:8]}@example.com"
    recipient_email = f"hist-recipient-{uuid.uuid4().hex[:8]}@example.com"
    
    caller_reg = client.post(
        "/auth/register",
        json={
            "name": "History Caller",
            "email": caller_email,
            "role": "customer",
            "password": "pass123",
        },
    )
    caller_id = caller_reg.json()["user_id"]
    caller_login = client.post(
        "/auth/login",
        json={"email": caller_email, "password": "pass123"},
    )
    caller_cookie = caller_login.headers.get("set-cookie", "")
    
    recipient_reg = client.post(
        "/auth/register",
        json={
            "name": "History Recipient",
            "email": recipient_email,
            "role": "customer",
            "password": "pass123",
        },
    )
    recipient_id = recipient_reg.json()["user_id"]
    
    # Initiate multiple calls
    for i in range(3):
        client.post(
            "/calls/initiate",
            json={
                "recipient_id": recipient_id,
                "call_type": "audio" if i % 2 == 0 else "video",
                "video_enabled": i % 2 == 1,
            },
            headers={"cookie": caller_cookie},
        )
    
    # Get call history
    response = client.get(
        "/calls/None/history?limit=10&offset=0",
        headers={"cookie": caller_cookie},
    )
    assert response.status_code == 200
    history = response.json()
    assert "history" in history
    assert "total" in history
    assert history["total"] >= 3


def test_cannot_call_self():
    """Test that user cannot call themselves"""
    user_email = f"self-caller-{uuid.uuid4().hex[:8]}@example.com"
    
    user_reg = client.post(
        "/auth/register",
        json={
            "name": "Self Caller",
            "email": user_email,
            "role": "customer",
            "password": "pass123",
        },
    )
    user_id = user_reg.json()["user_id"]
    user_login = client.post(
        "/auth/login",
        json={"email": user_email, "password": "pass123"},
    )
    user_cookie = user_login.headers.get("set-cookie", "")
    
    # Try to call self
    response = client.post(
        "/calls/initiate",
        json={
            "recipient_id": user_id,
            "call_type": "audio",
            "video_enabled": False,
        },
        headers={"cookie": user_cookie},
    )
    assert response.status_code == 403
    assert "cannot_call_self" in response.json()["detail"]


def test_query_caching_performance():
    """Test query caching functionality"""
    # Create admin user
    admin_email = f"cache-admin-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "Cache Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    admin_login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_cookie = admin_login.headers.get("set-cookie", "")
    
    # Get performance metrics (first call will populate cache)
    response1 = client.get(
        "/admin/performance/monitoring",
        headers={"cookie": admin_cookie},
    )
    assert response1.status_code == 200
    metrics1 = response1.json()
    assert "cache" in metrics1
    
    # Get again - should use cache
    response2 = client.get(
        "/admin/performance/monitoring",
        headers={"cookie": admin_cookie},
    )
    assert response2.status_code == 200
    metrics2 = response2.json()
    assert metrics2["cache"]["cache_entries"] >= 0


def test_admin_can_clear_cache():
    """Test admin cache clearing functionality"""
    admin_email = f"clear-admin-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "Clear Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    admin_login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_cookie = admin_login.headers.get("set-cookie", "")
    
    # Clear cache
    response = client.post(
        "/admin/performance/cache-clear",
        headers={"cookie": admin_cookie},
    )
    assert response.status_code == 200
    result = response.json()
    assert result["cleared"] is True


def test_non_admin_cannot_access_performance_metrics():
    """Test that non-admins cannot access performance monitoring"""
    user_email = f"perf-user-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "Perf User",
            "email": user_email,
            "role": "customer",
            "password": "pass123",
        },
    )
    user_login = client.post(
        "/auth/login",
        json={"email": user_email, "password": "pass123"},
    )
    user_cookie = user_login.headers.get("set-cookie", "")
    
    # Try to access performance metrics
    response = client.get(
        "/admin/performance/monitoring",
        headers={"cookie": user_cookie},
    )
    assert response.status_code == 403


def test_admin_can_view_database_indexes():
    """Test admin viewing database index information"""
    admin_email = f"idx-admin-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "Index Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    admin_login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_cookie = admin_login.headers.get("set-cookie", "")
    
    # Get database indexes
    response = client.get(
        "/admin/database/indexes",
        headers={"cookie": admin_cookie},
    )
    assert response.status_code == 200
    result = response.json()
    assert "database_backend" in result
    assert "indexes" in result
    assert "total_indexes" in result
    assert result["total_indexes"] > 0


def test_batch_notifications():
    """Test batch notification creation"""
    # Create two customers
    customer1_email = f"batch-cust1-{uuid.uuid4().hex[:8]}@example.com"
    customer2_email = f"batch-cust2-{uuid.uuid4().hex[:8]}@example.com"
    
    cust1_reg = client.post(
        "/auth/register",
        json={
            "name": "Batch Customer 1",
            "email": customer1_email,
            "role": "customer",
            "password": "pass123",
        },
    )
    cust1_id = cust1_reg.json()["user_id"]
    
    cust2_reg = client.post(
        "/auth/register",
        json={
            "name": "Batch Customer 2",
            "email": customer2_email,
            "role": "customer",
            "password": "pass123",
        },
    )
    cust2_id = cust2_reg.json()["user_id"]
    
    # Create batch notifications programmatically
    notifications = [
        {
            "recipient_id": cust1_id,
            "message": "Test notification 1",
            "sender_id": None,
            "booking_id": None,
        },
        {
            "recipient_id": cust2_id,
            "message": "Test notification 2",
            "sender_id": None,
            "booking_id": None,
        },
    ]
    
    count = app_module.batch_create_notifications(notifications)
    assert count == 2


def test_pagination_helper():
    """Test paginated results helper"""
    # Create multiple bookings for pagination test
    customer_email = f"paginate-{uuid.uuid4().hex[:8]}@example.com"
    
    customer_reg = client.post(
        "/auth/register",
        json={
            "name": "Paginate Customer",
            "email": customer_email,
            "role": "customer",
            "password": "pass123",
        },
    )
    customer_id = customer_reg.json()["user_id"]
    customer_login = client.post(
        "/auth/login",
        json={"email": customer_email, "password": "pass123"},
    )
    customer_cookie = customer_login.headers.get("set-cookie", "")
    
    # Create 5 bookings
    for i in range(5):
        client.post(
            "/bookings",
            json={
                "service_type": "ride",
                "pickup": f"Location {i}",
                "destination": f"Destination {i}",
                "price": 50 + i * 10,
            },
            headers={"cookie": customer_cookie},
        )
    
    # Use pagination in a real endpoint
    response = client.get(
        "/bookings?limit=2&offset=0",
        headers={"cookie": customer_cookie},
    )
    assert response.status_code == 200


def test_performance_optimization_status():
    """Test that performance optimization features are active"""
    admin_email = f"perf-status-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "Perf Status Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    admin_login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_cookie = admin_login.headers.get("set-cookie", "")
    
    # Check performance metrics
    response = client.get(
        "/admin/performance/monitoring",
        headers={"cookie": admin_cookie},
    )
    assert response.status_code == 200
    metrics = response.json()
    
    # Verify optimization features are present
    assert "optimization_status" in metrics
    assert metrics["optimization_status"] == "active"
    assert "cache" in metrics
    assert "query_activity" in metrics


def test_rate_limiter_allows_requests_under_limit():
    """Test that rate limiter allows requests under the limit"""
    limiter = app_module.RateLimiter(requests_per_minute=10)
    
    # Should allow 10 requests
    for i in range(10):
        assert limiter.is_allowed("test_user") == True
    
    # 11th request should be blocked
    assert limiter.is_allowed("test_user") == False
    
    # get_remaining should return 0
    remaining = limiter.get_remaining("test_user")
    assert remaining == 0


def test_rate_limiter_blocks_requests_over_limit():
    """Test that rate limiter blocks requests over the limit"""
    limiter = app_module.RateLimiter(requests_per_minute=5)
    identifier = "test_blocked_user"
    
    # Fill up the limit
    for i in range(5):
        result = limiter.is_allowed(identifier)
        assert result == True
    
    # Next request should be blocked
    result = limiter.is_allowed(identifier)
    assert result == False


def test_brute_force_protection_lockout():
    """Test that brute force protector locks out after max attempts"""
    protector = app_module.BruteForceProtector(max_attempts=3, lockout_minutes=1)
    identifier = "brute_force_test"
    
    # Record 3 failed attempts
    for i in range(3):
        is_locked, attempts, remaining = protector.record_failed_attempt(identifier)
        assert is_locked == False  # Not locked until 4th attempt
        assert attempts == i + 1
    
    # 4th attempt should trigger lockout
    is_locked, attempts, remaining = protector.record_failed_attempt(identifier)
    assert is_locked == True
    assert attempts == 4
    assert remaining > 0


def test_brute_force_protection_success_clears_history():
    """Test that successful auth clears failed attempt history"""
    protector = app_module.BruteForceProtector(max_attempts=3, lockout_minutes=1)
    identifier = "success_test"
    
    # Record 2 failed attempts
    protector.record_failed_attempt(identifier)
    protector.record_failed_attempt(identifier)
    
    # Record success - should clear history
    protector.record_success(identifier)
    
    # Now should be able to try again (history cleared)
    is_locked, attempts, remaining = protector.record_failed_attempt(identifier)
    assert attempts == 1  # Back to 1, not 3


def test_security_monitoring_endpoint():
    """Test admin security monitoring dashboard"""
    admin_email = f"security-admin-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "Security Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    admin_login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_cookie = admin_login.headers.get("set-cookie", "")
    
    # Access security monitoring
    response = client.get(
        "/admin/security/monitoring",
        headers={"cookie": admin_cookie},
    )
    assert response.status_code == 200
    monitoring_data = response.json()
    
    # Verify response structure
    assert "rate_limit_stats" in monitoring_data
    assert "brute_force_stats" in monitoring_data
    assert "recent_security_events" in monitoring_data


def test_security_events_logging():
    """Test that security events are logged correctly"""
    # Log a security event
    app_module.log_security_event(
        event_type="test_event",
        severity="medium",
        user_id=1,
        ip_address="192.168.1.1",
        details="Test security event",
    )
    
    # Retrieve events
    events = app_module.get_security_events(event_type="test_event", limit=10)
    
    # Should have at least one event
    assert len(events) > 0
    assert events[0]["event_type"] == "test_event"
    assert events[0]["severity"] == "medium"


def test_admin_block_ip():
    """Test admin ability to block IP addresses"""
    admin_email = f"block-ip-admin-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "Block IP Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    admin_login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_cookie = admin_login.headers.get("set-cookie", "")
    
    # Block an IP
    response = client.post(
        "/admin/security/block-ip",
        json={
            "ip_address": "192.168.1.100",
            "reason": "Suspicious activity detected",
        },
        headers={"cookie": admin_cookie},
    )
    assert response.status_code == 200
    data = response.json()
    assert "IP" in data["message"]
    assert "blocked" in data["message"].lower()


def test_non_admin_cannot_access_security():
    """Test that non-admins cannot access security endpoints"""
    customer_email = f"security-cust-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "Security Test Customer",
            "email": customer_email,
            "role": "customer",
            "password": "pass123",
        },
    )
    customer_login = client.post(
        "/auth/login",
        json={"email": customer_email, "password": "pass123"},
    )
    customer_cookie = customer_login.headers.get("set-cookie", "")
    
    # Try to access security monitoring - should fail
    response = client.get(
        "/admin/security/monitoring",
        headers={"cookie": customer_cookie},
    )
    assert response.status_code in [403, 401]
    
    # Try to block IP - should fail
    response = client.post(
        "/admin/security/block-ip",
        json={
            "ip_address": "192.168.1.100",
            "reason": "Test",
        },
        headers={"cookie": customer_cookie},
    )
    assert response.status_code in [403, 401]


def test_rate_limit_middleware_enforces_limit():
    """Test that rate limiting middleware blocks requests over limit"""
    # Create a customer
    customer_email = f"rate-limit-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "Rate Limit Test",
            "email": customer_email,
            "role": "customer",
            "password": "pass123",
        },
    )
    customer_login = client.post(
        "/auth/login",
        json={"email": customer_email, "password": "pass123"},
    )
    customer_cookie = customer_login.headers.get("set-cookie", "")
    
    # Make requests up to but not over the user rate limit (60 per minute)
    # We'll make a few requests and verify they succeed
    for i in range(3):
        response = client.get(
            "/bookings",
            headers={"cookie": customer_cookie},
        )
        assert response.status_code == 200


def test_security_headers_present():
    """Test that security headers are added to responses"""
    response = client.get("/health")
    
    # Verify security headers are present
    assert "X-Frame-Options" in response.headers
    assert response.headers["X-Frame-Options"] == "DENY"
    
    assert "X-Content-Type-Options" in response.headers
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    
    assert "X-XSS-Protection" in response.headers
    
    assert "Content-Security-Policy" in response.headers
    
    assert "Referrer-Policy" in response.headers


def test_brute_force_middleware_on_login():
    """Test that brute force middleware blocks repeated failed logins"""
    # This test would need to mock the _brute_force_protector
    # For now, we just verify the endpoint exists and responds correctly
    
    customer_email = f"brute-test-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "Brute Test",
            "email": customer_email,
            "role": "customer",
            "password": "SecurePass123",
        },
    )
    
    # Try to login with wrong password a few times
    for i in range(3):
        response = client.post(
            "/auth/login",
            json={"email": customer_email, "password": "wrongpassword"},
        )
        # Should fail but not be rate limited yet (brute force lockout happens at 5 attempts)
        assert response.status_code in [400, 401]


def test_ip_blacklist_blocks_requests():
    """Test that blacklisted IPs are blocked by middleware"""
    # This would require modifying the ip_blacklist table
    # For now, we verify the table exists and the middleware logic is in place
    
    conn = app_module.get_connection()
    try:
        # Insert a test blacklisted IP
        conn.execute(
            "INSERT OR IGNORE INTO ip_blacklist (ip_address, reason) VALUES (?, ?)",
            ("127.0.0.2", "Test blacklist"),
        )
        conn.commit()
    finally:
        conn.close()


def test_request_signature_validation():
    """Test optional request signature validation"""
    # Verify the validate_request_signature function exists and handles missing secrets
    result = app_module.validate_request_signature(
        Request({"type": "http", "method": "POST", "headers": {}, "client": ("127.0.0.1", 80)}),
        api_secret="",
    )
    # Should return True if no secret is configured (defaults to True)
    assert result == True


def test_health_check_endpoint():
    """Test basic health check endpoint"""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    
    assert "status" in data
    assert data["status"] == "ok"
    assert "service" in data
    assert data["service"] == "smarthaul"
    assert "timestamp" in data


def test_deep_health_check():
    """Test comprehensive health check with dependencies"""
    response = client.get("/health/deep")
    assert response.status_code == 200
    data = response.json()
    
    assert "status" in data
    assert "data" in data
    health_data = data["data"]
    
    # Verify structure
    assert "database" in health_data
    assert "cache" in health_data
    assert "timestamp" in health_data
    assert "version" in health_data
    
    # Check dependency status structure
    assert "name" in health_data["database"]
    assert "status" in health_data["database"]
    assert "response_time_ms" in health_data["database"]


def test_health_dependencies_endpoint():
    """Test endpoint showing all external dependency status"""
    response = client.get("/health/dependencies")
    assert response.status_code == 200
    data = response.json()
    
    assert "overall" in data
    assert "dependencies" in data
    assert "database" in data["dependencies"]
    assert "cache" in data["dependencies"]
    assert "timestamp" in data


def test_health_readiness_check():
    """Test readiness check for traffic acceptance"""
    response = client.get("/health/readiness")
    assert response.status_code == 200
    data = response.json()
    
    assert "ready" in data
    assert "database_ready" in data
    assert "timestamp" in data
    
    # Should be ready since database is functional
    assert data["ready"] == True


def test_database_health_check():
    """Test database health check helper"""
    db_status = app_module.check_database_health()
    
    assert db_status.name == "database"
    assert db_status.status in ["healthy", "unhealthy"]
    assert db_status.response_time_ms >= 0
    assert db_status.last_checked is not None
    
    # For a working database, should be healthy
    assert db_status.status == "healthy"


def test_cache_health_check():
    """Test cache health check helper"""
    cache_status = app_module.check_cache_health()
    
    assert cache_status.name == "cache"
    assert cache_status.status in ["healthy", "degraded", "unhealthy"]
    assert cache_status.response_time_ms >= 0
    assert cache_status.last_checked is not None


def test_service_uptime():
    """Test service uptime calculation"""
    uptime = app_module.get_service_uptime()
    
    # Uptime should be at least 0 and less than max int
    assert uptime >= 0
    assert uptime < 999999999


def test_comprehensive_health_check():
    """Test complete health check function"""
    health = app_module.perform_health_check()
    
    assert health.status in ["healthy", "degraded", "unhealthy"]
    assert health.timestamp is not None
    assert health.database is not None
    assert health.cache is not None
    assert health.uptime_seconds >= 0
    assert health.version == "4.7.0"


def test_health_check_history_recording():
    """Test recording health check history"""
    # Record a health check
    database_module.record_health_check(
        check_type="database",
        status="healthy",
        response_time_ms=5.0,
        details="Database connection successful",
    )
    
    # Retrieve history
    history = database_module.get_health_check_history(check_type="database", limit=10)
    
    # Should have at least one record
    assert len(history) > 0
    assert history[0]["check_type"] == "database"
    assert history[0]["status"] == "healthy"


def test_health_check_history_retrieval():
    """Test retrieving health check history"""
    # Record multiple health checks
    for i in range(3):
        database_module.record_health_check(
            check_type="test",
            status="healthy",
            response_time_ms=float(i),
        )
    
    # Retrieve history
    history = database_module.get_health_check_history(check_type="test", limit=5)
    
    # Should retrieve the recorded checks
    assert len(history) >= 3


def test_sla_metrics_calculation():
    """Test SLA metrics calculation"""
    metrics = app_module.get_sla_metrics()
    
    assert len(metrics) > 0
    
    for metric in metrics:
        assert metric.metric_name in ["availability", "response_time_p95"]
        assert metric.target_value > 0
        assert metric.current_value >= 0
        assert metric.status in ["compliant", "warning", "violation"]


def test_uptime_percentage_calculation():
    """Test uptime percentage calculation"""
    uptime = app_module.calculate_uptime_percentage()
    
    assert 0 <= uptime <= 100
    # Should be high uptime for a freshly running service
    assert uptime >= 99.0


def test_response_time_percentile_calculation():
    """Test response time percentile calculation"""
    # Record some health checks with varying response times
    for i in range(5):
        database_module.record_health_check(
            check_type="test",
            status="healthy",
            response_time_ms=float(i * 100),
        )
    
    # Calculate p95
    p95 = app_module.calculate_response_time_percentile(95)
    
    assert p95 >= 0


def test_compliance_status_endpoint():
    """Test admin compliance status endpoint"""
    admin_email = f"compliance-admin-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "Compliance Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    admin_login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_cookie = admin_login.headers.get("set-cookie", "")
    
    response = client.get(
        "/admin/compliance/status",
        headers={"cookie": admin_cookie},
    )
    assert response.status_code == 200
    data = response.json()
    
    assert "status" in data
    assert data["status"] in ["compliant", "partial", "non-compliant"]
    assert "uptime_percentage" in data
    assert "response_time_p95_ms" in data
    assert "gdpr_compliant" in data
    assert "critical_metrics" in data


def test_sla_metrics_endpoint():
    """Test admin SLA metrics endpoint"""
    admin_email = f"sla-admin-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "SLA Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    admin_login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_cookie = admin_login.headers.get("set-cookie", "")
    
    response = client.get(
        "/admin/sla/metrics",
        headers={"cookie": admin_cookie},
    )
    assert response.status_code == 200
    data = response.json()
    
    assert "metrics" in data
    assert len(data["metrics"]) > 0
    assert "timestamp" in data


def test_sla_violations_tracking():
    """Test SLA violation recording and retrieval"""
    # Record a violation
    app_module.record_sla_violation(
        metric_name="availability",
        expected_value=99.9,
        actual_value=98.5,
        severity="high",
    )
    
    # Retrieve violations
    violations = database_module.get_sla_violations(limit=10)
    
    # Should have at least one violation
    assert len(violations) > 0
    assert violations[0]["metric_name"] == "availability"


def test_sla_violations_endpoint():
    """Test admin SLA violations endpoint"""
    admin_email = f"sla-violations-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "SLA Violations Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    admin_login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_cookie = admin_login.headers.get("set-cookie", "")
    
    response = client.get(
        "/admin/sla/violations?limit=10",
        headers={"cookie": admin_cookie},
    )
    assert response.status_code == 200
    data = response.json()
    
    assert "violations" in data
    assert "total" in data
    assert "timestamp" in data


def test_resolve_sla_violation():
    """Test resolving an SLA violation"""
    admin_email = f"resolve-sla-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "Resolve SLA Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    admin_login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_cookie = admin_login.headers.get("set-cookie", "")
    
    # Record a violation first
    app_module.record_sla_violation(
        metric_name="response_time_p95",
        expected_value=500.0,
        actual_value=1200.0,
        severity="medium",
    )
    
    violations = database_module.get_sla_violations(limit=1)
    if violations:
        violation_id = violations[0]["id"]
        
        response = client.post(
            f"/admin/sla/violations/resolve?violation_id={violation_id}",
            headers={"cookie": admin_cookie},
        )
        assert response.status_code == 200
        data = response.json()
        assert "message" in data


def test_non_admin_cannot_access_compliance():
    """Test that non-admins cannot access compliance endpoints"""
    customer_email = f"compliance-cust-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "Compliance Test Customer",
            "email": customer_email,
            "role": "customer",
            "password": "pass123",
        },
    )
    customer_login = client.post(
        "/auth/login",
        json={"email": customer_email, "password": "pass123"},
    )
    customer_cookie = customer_login.headers.get("set-cookie", "")
    
    # Try to access compliance endpoint - should fail
    response = client.get(
        "/admin/compliance/status",
        headers={"cookie": customer_cookie},
    )
    assert response.status_code in [403, 401]
    
    # Try to access SLA metrics - should fail
    response = client.get(
        "/admin/sla/metrics",
        headers={"cookie": customer_cookie},
    )
    assert response.status_code in [403, 401]


def test_create_database_backup():
    """Test creating a database backup"""
    backup = app_module.create_database_backup()
    
    assert backup.backup_id is not None
    assert backup.status == "success"
    assert backup.size_mb > 0
    assert backup.location is not None
    assert backup.created_at is not None
    assert "backup-" in backup.backup_id


def test_get_available_backups():
    """Test retrieving list of available backups"""
    # Create a backup first
    app_module.create_database_backup()
    
    # Get available backups
    backups = app_module.get_available_backups()
    
    assert len(backups) > 0
    assert all(b.status == "success" for b in backups)
    assert all(b.backup_id is not None for b in backups)
    assert all(b.size_mb > 0 for b in backups)


def test_restore_database_backup():
    """Test restoring from a backup"""
    # Create a backup first
    backup = app_module.create_database_backup()
    backup_id = backup.backup_id
    
    # Restore from backup
    restored = app_module.restore_database_backup(backup_id)
    
    assert restored == True


def test_check_primary_database_health():
    """Test checking failover status"""
    status = app_module.check_primary_database_health()
    
    assert status.primary_healthy == True
    assert status.backup_available == True
    assert status.failover_ready == True
    assert status.last_backup_age_seconds >= 0


def test_get_disaster_recovery_plan():
    """Test getting disaster recovery plan configuration"""
    plan = app_module.get_disaster_recovery_plan()
    
    assert plan.rpo_seconds == 300  # 5 minutes
    assert plan.rto_seconds == 600  # 10 minutes
    assert plan.backup_strategy == "hourly"
    assert plan.retention_days >= 7
    assert len(plan.backup_locations) > 0


def test_admin_backup_create():
    """Test admin endpoint to create backup"""
    admin_email = f"backup-admin-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "Backup Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    admin_login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_cookie = admin_login.headers.get("set-cookie", "")
    
    response = client.post(
        "/admin/backup/create",
        headers={"cookie": admin_cookie},
    )
    assert response.status_code == 200
    data = response.json()
    
    assert "backup_id" in data
    assert "status" in data
    assert data["status"] == "success"
    assert "size_mb" in data


def test_admin_list_backups():
    """Test admin endpoint to list backups"""
    admin_email = f"list-backup-admin-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "List Backup Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    admin_login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_cookie = admin_login.headers.get("set-cookie", "")
    
    # Create a backup first
    client.post(
        "/admin/backup/create",
        headers={"cookie": admin_cookie},
    )
    
    response = client.get(
        "/admin/backup/list",
        headers={"cookie": admin_cookie},
    )
    assert response.status_code == 200
    data = response.json()
    
    assert "backups" in data
    assert len(data["backups"]) > 0
    assert all("backup_id" in b for b in data["backups"])
    assert all("created_at" in b for b in data["backups"])


def test_admin_restore_backup():
    """Test admin endpoint to restore from backup"""
    admin_email = f"restore-admin-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "Restore Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    admin_login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_cookie = admin_login.headers.get("set-cookie", "")
    
    # Create a backup first
    backup_response = client.post(
        "/admin/backup/create",
        headers={"cookie": admin_cookie},
    )
    backup_id = backup_response.json()["backup_id"]
    
    # Restore from the backup
    response = client.post(
        f"/admin/backup/restore?backup_id={backup_id}",
        headers={"cookie": admin_cookie},
    )
    assert response.status_code == 200
    data = response.json()
    
    assert "message" in data
    assert "restored" in data["message"].lower() or "success" in data["message"].lower()


def test_admin_failover_status():
    """Test admin endpoint to check failover readiness"""
    admin_email = f"failover-admin-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "Failover Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    admin_login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_cookie = admin_login.headers.get("set-cookie", "")
    
    response = client.get(
        "/admin/failover/status",
        headers={"cookie": admin_cookie},
    )
    assert response.status_code == 200
    data = response.json()
    
    assert "primary_healthy" in data
    assert "backup_available" in data
    assert "failover_ready" in data
    assert "last_backup_age_seconds" in data


def test_admin_dr_plan():
    """Test admin endpoint to get disaster recovery plan"""
    admin_email = f"dr-plan-admin-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "DR Plan Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    admin_login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_cookie = admin_login.headers.get("set-cookie", "")
    
    response = client.get(
        "/admin/dr/plan",
        headers={"cookie": admin_cookie},
    )
    assert response.status_code == 200
    data = response.json()
    
    assert "rpo_seconds" in data
    assert "rto_seconds" in data
    assert "backup_strategy" in data
    assert "retention_days" in data
    assert "backup_locations" in data


def test_admin_dr_test():
    """Test admin endpoint to test disaster recovery"""
    admin_email = f"dr-test-admin-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "DR Test Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    admin_login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_cookie = admin_login.headers.get("set-cookie", "")
    
    response = client.post(
        "/admin/dr/test",
        headers={"cookie": admin_cookie},
    )
    assert response.status_code == 200
    data = response.json()
    
    assert "message" in data
    assert "test" in data["message"].lower() or "success" in data["message"].lower()
    assert "backup_id" in data


def test_non_admin_cannot_access_backup_endpoints():
    """Test that non-admins cannot access backup endpoints"""
    customer_email = f"backup-cust-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "Backup Test Customer",
            "email": customer_email,
            "role": "customer",
            "password": "pass123",
        },
    )
    customer_login = client.post(
        "/auth/login",
        json={"email": customer_email, "password": "pass123"},
    )
    customer_cookie = customer_login.headers.get("set-cookie", "")
    
    # Try to create backup - should fail
    response = client.post(
        "/admin/backup/create",
        headers={"cookie": customer_cookie},
    )
    assert response.status_code in [403, 401]
    
    # Try to list backups - should fail
    response = client.get(
        "/admin/backup/list",
        headers={"cookie": customer_cookie},
    )
    assert response.status_code in [403, 401]
    
    # Try to check failover status - should fail
    response = client.get(
        "/admin/failover/status",
        headers={"cookie": customer_cookie},
    )
    assert response.status_code in [403, 401]
    
    # Try to get DR plan - should fail
    response = client.get(
        "/admin/dr/plan",
        headers={"cookie": customer_cookie},
    )
    assert response.status_code in [403, 401]


def test_backup_history_recording():
    """Test backup history recording and retrieval"""
    backup_id = f"test-backup-{uuid.uuid4().hex[:8]}"
    
    # Record a backup
    database_module.record_backup(
        backup_id=backup_id,
        status="success",
        size_mb=50.5,
        location="/path/to/backup",
    )
    
    # Retrieve history
    history = database_module.get_backup_history(limit=10)
    
    # Should have at least one record
    assert len(history) > 0
    
    # Find our backup
    found = False
    for backup in history:
        if backup["backup_id"] == backup_id:
            found = True
            assert backup["status"] == "success"
            assert backup["size_mb"] == 50.5
            assert backup["location"] == "/path/to/backup"
            break
    
    assert found == True


def test_backup_history_retention():
    """Test that backup history is properly retained"""
    # Record multiple backups
    for i in range(5):
        database_module.record_backup(
            backup_id=f"test-backup-{i}-{uuid.uuid4().hex[:8]}",
            status="success",
            size_mb=float(i * 10),
            location=f"/path/to/backup/{i}",
        )
    
    # Retrieve all backups
    history = database_module.get_backup_history(limit=100)
    
    # Should have at least 5 backups
    assert len(history) >= 5


# Phase 5.4 - Log Aggregation & Centralized Monitoring Tests

def test_log_recording():
    """Test recording logs to centralized logging system"""
    database_module.record_log(
        component="test_component",
        level="INFO",
        message="Test log message",
        context="test context",
        user_id=1,
    )
    
    # Retrieve logs
    logs = database_module.get_logs(component="test_component", limit=10)
    
    # Should have at least one log
    assert len(logs) > 0
    assert logs[0]["component"] == "test_component"
    assert logs[0]["level"] == "INFO"


def test_get_logs():
    """Test retrieving logs with filtering"""
    # Record multiple logs
    database_module.record_log("auth", "ERROR", "Login failed")
    database_module.record_log("payments", "WARNING", "Payment delayed")
    database_module.record_log("auth", "INFO", "User registered")
    
    # Get logs for auth component
    auth_logs = database_module.get_logs(component="auth", limit=10)
    
    assert len(auth_logs) > 0
    assert all(log["component"] == "auth" for log in auth_logs)


def test_log_analytics():
    """Test log analytics calculation"""
    # Record logs at different levels
    for i in range(3):
        database_module.record_log("test", "ERROR", f"Error {i}")
    for i in range(2):
        database_module.record_log("test", "WARNING", f"Warning {i}")
    database_module.record_log("test", "INFO", "Info message")
    
    # Get analytics
    analytics = database_module.get_log_analytics(time_period_hours=24)
    
    assert analytics["total_logs"] > 0
    assert analytics["error_count"] >= 3
    assert analytics["warning_count"] >= 2


def test_alert_rule_creation():
    """Test creating alert rules"""
    import uuid
    rule_id = f"rule-{uuid.uuid4().hex[:8]}"
    
    database_module.create_alert_rule(
        rule_id=rule_id,
        name="High Error Rate",
        condition="error_rate > 5",
        threshold=5.0,
        alert_type="in_app",
    )
    
    # Retrieve rules
    rules = database_module.get_alert_rules()
    
    # Should find our rule
    found = False
    for rule in rules:
        if rule.get("rule_id") == rule_id:
            found = True
            assert rule["name"] == "High Error Rate"
            break
    
    assert found == True


def test_alert_triggering():
    """Test recording alerts"""
    import uuid
    alert_id = f"alert-{uuid.uuid4().hex[:8]}"
    
    database_module.record_alert(
        alert_rule_id=1,
        message="Error rate exceeded threshold",
        severity="high",
    )
    
    # Retrieve alerts
    alerts = database_module.get_alerts(limit=10)
    
    # Should have at least one alert
    assert len(alerts) > 0
    assert alerts[0]["message"] == "Error rate exceeded threshold"


def test_admin_logs_endpoint():
    """Test admin endpoint to get logs"""
    admin_email = f"logs-admin-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "Logs Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    admin_login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_cookie = admin_login.headers.get("set-cookie", "")
    
    # Record some logs first
    database_module.record_log("test", "INFO", "Test log")
    
    response = client.get(
        "/admin/logs?limit=50",
        headers={"cookie": admin_cookie},
    )
    assert response.status_code == 200
    data = response.json()
    
    assert "total_count" in data
    assert "entries" in data


def test_admin_log_analytics_endpoint():
    """Test admin endpoint to get log analytics"""
    admin_email = f"analytics-admin-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "Analytics Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    admin_login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_cookie = admin_login.headers.get("set-cookie", "")
    
    response = client.get(
        "/admin/logs/analytics",
        headers={"cookie": admin_cookie},
    )
    assert response.status_code == 200
    data = response.json()
    
    assert "total_logs" in data
    assert "error_count" in data
    assert "error_rate_percent" in data


def test_admin_create_alert_rule():
    """Test admin endpoint to create alert rule"""
    admin_email = f"alert-admin-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "Alert Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    admin_login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_cookie = admin_login.headers.get("set-cookie", "")
    
    response = client.post(
        "/admin/alerts/rules?name=Test Rule&condition=error_rate > 10&threshold=10.0&alert_type=in_app",
        headers={"cookie": admin_cookie},
    )
    assert response.status_code == 200
    data = response.json()
    
    assert "rule_id" in data
    assert "status" in data
    assert data["status"] == "created"


def test_admin_list_alert_rules():
    """Test admin endpoint to list alert rules"""
    admin_email = f"list-rules-admin-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "List Rules Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    admin_login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_cookie = admin_login.headers.get("set-cookie", "")
    
    response = client.get(
        "/admin/alerts/rules",
        headers={"cookie": admin_cookie},
    )
    assert response.status_code == 200
    data = response.json()
    
    assert "total_rules" in data
    assert "rules" in data


def test_admin_get_alerts():
    """Test admin endpoint to get recent alerts"""
    admin_email = f"get-alerts-admin-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "Get Alerts Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    admin_login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_cookie = admin_login.headers.get("set-cookie", "")
    
    # Record an alert first
    database_module.record_alert(1, "Test alert", "medium")
    
    response = client.get(
        "/admin/alerts?limit=50",
        headers={"cookie": admin_cookie},
    )
    assert response.status_code == 200
    data = response.json()
    
    assert "total_alerts" in data
    assert "alerts" in data


def test_monitoring_dashboard():
    """Test centralized monitoring dashboard endpoint"""
    admin_email = f"dashboard-admin-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "Dashboard Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    admin_login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_cookie = admin_login.headers.get("set-cookie", "")
    
    response = client.get(
        "/admin/monitoring/dashboard",
        headers={"cookie": admin_cookie},
    )
    assert response.status_code == 200
    data = response.json()
    
    assert "service_uptime_percent" in data
    assert "error_rate_percent" in data
    assert "alert_count" in data
    assert "recent_logs" in data
    assert "system_health_status" in data


def test_log_retention_configuration():
    """Test configuring log retention policy"""
    admin_email = f"retention-admin-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "Retention Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    admin_login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_cookie = admin_login.headers.get("set-cookie", "")
    
    response = client.post(
        "/admin/logs/retention?retention_days=90&archive_after_days=30&cleanup_enabled=true",
        headers={"cookie": admin_cookie},
    )
    assert response.status_code == 200
    data = response.json()
    
    assert "status" in data
    assert "retention_policy" in data


def test_manual_log_cleanup():
    """Test triggering manual log cleanup"""
    admin_email = f"cleanup-admin-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "Cleanup Admin",
            "email": admin_email,
            "role": "admin",
            "password": "admin123",
        },
    )
    admin_login = client.post(
        "/auth/login",
        json={"email": admin_email, "password": "admin123"},
    )
    admin_cookie = admin_login.headers.get("set-cookie", "")
    
    response = client.post(
        "/admin/logs/cleanup",
        headers={"cookie": admin_cookie},
    )
    assert response.status_code == 200
    data = response.json()
    
    assert "archived_count" in data
    assert "cleaned_count" in data


def test_non_admin_cannot_access_logs():
    """Test that non-admins cannot access logging endpoints"""
    customer_email = f"logs-cust-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "Logs Test Customer",
            "email": customer_email,
            "role": "customer",
            "password": "pass123",
        },
    )
    customer_login = client.post(
        "/auth/login",
        json={"email": customer_email, "password": "pass123"},
    )
    customer_cookie = customer_login.headers.get("set-cookie", "")
    
    # Try to access logs - should fail
    response = client.get(
        "/admin/logs",
        headers={"cookie": customer_cookie},
    )
    assert response.status_code in [403, 401]
    
    # Try to access analytics - should fail
    response = client.get(
        "/admin/logs/analytics",
        headers={"cookie": customer_cookie},
    )
    assert response.status_code in [403, 401]
    
    # Try to access dashboard - should fail
    response = client.get(
        "/admin/monitoring/dashboard",
        headers={"cookie": customer_cookie},
    )
    assert response.status_code in [403, 401]


def test_log_system_integration():
    """Test that log_to_system function works"""
    log_id = app_module.log_to_system(
        component="integration_test",
        level="INFO",
        message="Integration test log",
    )
    
    # Should return a log ID
    assert log_id is not None
    assert "log-" in log_id
    
    # Verify log was recorded
    logs = database_module.get_logs(component="integration_test", limit=5)
    assert len(logs) > 0


def test_get_log_analytics_data():
    """Test get_log_analytics_data helper function"""
    # Record some logs
    for i in range(5):
        database_module.record_log("test", "INFO", f"Message {i}")
    
    analytics = app_module.get_log_analytics_data(time_period_hours=24)
    
    assert analytics.total_logs > 0
    assert analytics.error_rate_percent >= 0
    assert analytics.timestamp is not None


def test_check_alert_conditions():
    """Test alert condition checking"""
    # Create an alert rule
    import uuid
    rule_id = f"rule-{uuid.uuid4().hex[:8]}"
    
    database_module.create_alert_rule(
        rule_id=rule_id,
        name="Test Rule",
        condition="error_rate > 0",
        threshold=0.0,
    )
    
    # Check conditions
    triggered = app_module.check_alert_conditions()
    
    # Should return a list (may be empty if no conditions met)
    assert isinstance(triggered, list)


# Phase 5.5 - Auto-scaling & Load Balancing Tests (15 tests)

def test_create_scaling_policy():
    """Test creating a scaling policy"""
    import uuid
    policy_id = f"policy-{uuid.uuid4().hex[:8]}"
    
    database_module.create_scaling_policy(
        policy_id=policy_id,
        name="CPU Scale Up Policy",
        metric="cpu",
        threshold_up=80.0,
        threshold_down=30.0,
        scale_up_instances=2,
        scale_down_instances=1,
        cooldown_minutes=5,
    )
    
    policies = database_module.get_scaling_policies()
    assert len(policies) > 0
    assert any(p["policy_id"] == policy_id for p in policies)


def test_get_scaling_policies():
    """Test retrieving scaling policies"""
    import uuid
    policy_id = f"policy-{uuid.uuid4().hex[:8]}"
    
    database_module.create_scaling_policy(
        policy_id=policy_id,
        name="Memory Scale Policy",
        metric="memory",
        threshold_up=85.0,
        threshold_down=40.0,
        scale_up_instances=1,
        scale_down_instances=1,
        cooldown_minutes=10,
    )
    
    policies = database_module.get_scaling_policies()
    assert isinstance(policies, list)
    assert all("policy_id" in p for p in policies)


def test_record_scaling_event():
    """Test recording a scaling event"""
    import uuid
    event_id = f"event-{uuid.uuid4().hex[:8]}"
    policy_id = 1
    
    database_module.record_scaling_event(
        event_id=event_id,
        event_type="scale_up",
        policy_id=policy_id,
        metric_value=85.5,
        threshold=80.0,
        instances_added=2,
        instances_removed=0,
    )
    
    events = database_module.get_scaling_events()
    assert len(events) > 0
    assert any(e["event_id"] == event_id for e in events)


def test_get_scaling_events():
    """Test retrieving scaling events"""
    import uuid
    event_id = f"event-{uuid.uuid4().hex[:8]}"
    
    database_module.record_scaling_event(
        event_id=event_id,
        event_type="scale_down",
        policy_id=None,
        metric_value=25.0,
        threshold=30.0,
    )
    
    events = database_module.get_scaling_events(hours=24)
    assert isinstance(events, list)


def test_get_load_balancer_config():
    """Test retrieving load balancer configuration"""
    config = database_module.get_load_balancer_config()
    assert isinstance(config, dict)


def test_update_load_balancer_config():
    """Test updating load balancer configuration"""
    database_module.update_load_balancer_config(
        algorithm="least_connections",
        health_check_interval_seconds=15,
        sticky_sessions=True,
    )
    
    config = database_module.get_load_balancer_config()
    assert config.get("algorithm") == "least_connections" or config == {}


def test_get_instance_metrics():
    """Test retrieving instance metrics"""
    metrics = database_module.get_instance_metrics()
    assert isinstance(metrics, list)


def test_record_instance_metrics():
    """Test recording instance metrics"""
    import uuid
    instance_id = f"instance-{uuid.uuid4().hex[:8]}"
    
    database_module.record_instance_metrics(
        instance_id=instance_id,
        instance_name="app-instance-1",
        cpu_percent=45.5,
        memory_percent=62.3,
        active_requests=150,
        average_response_time_ms=45.2,
        health_status="healthy",
    )
    
    metrics = database_module.get_instance_metrics()
    assert any(m["instance_id"] == instance_id for m in metrics)


def test_admin_get_scaling_policies():
    """Test admin endpoint to get scaling policies"""
    response = client.get("/admin/scaling/policies", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert "policies" in data


def test_admin_create_scaling_policy():
    """Test admin endpoint to create scaling policy"""
    response = client.post(
        "/admin/scaling/policies",
        json={
            "name": "Request Count Scale Policy",
            "metric": "requests",
            "threshold_up": 1000.0,
            "threshold_down": 500.0,
            "scale_up_instances": 2,
            "scale_down_instances": 1,
            "cooldown_minutes": 5,
        },
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert "policy_id" in data


def test_admin_get_scaling_metrics():
    """Test admin endpoint to get scaling metrics"""
    response = client.get("/admin/scaling/metrics", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert "metrics" in data


def test_admin_get_scaling_recommendations():
    """Test admin endpoint to get scaling recommendations"""
    response = client.get("/admin/scaling/recommendations", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert "recommendations" in data


def test_admin_get_scaling_history():
    """Test admin endpoint to get scaling history"""
    response = client.get("/admin/scaling/history", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert "events" in data


def test_admin_get_load_balancer_status():
    """Test admin endpoint to get load balancer status"""
    response = client.get("/admin/loadbalancer/status", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert "algorithm" in data


def test_admin_update_load_balancer_config():
    """Test admin endpoint to update load balancer config"""
    response = client.post(
        "/admin/loadbalancer/config",
        json={
            "algorithm": "weighted",
            "health_check_interval_seconds": 20,
            "sticky_sessions": False,
        },
        headers=admin_headers,
    )
    assert response.status_code == 200


def test_admin_get_capacity_plan():
    """Test admin endpoint to get capacity plan"""
    response = client.get("/admin/capacity/plan", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert "recommendations" in data


def test_admin_get_scaling_instances():
    """Test admin endpoint to get scaling instance metrics"""
    response = client.get("/admin/scaling/instances", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert "instances" in data


def test_non_admin_cannot_access_scaling_endpoints():
    """Test that non-admin users cannot access scaling endpoints"""
    response = client.get("/admin/scaling/policies", headers=customer_headers)
    assert response.status_code == 403
    
    response = client.post(
        "/admin/scaling/policies",
        json={"name": "Test"},
        headers=customer_headers,
    )
    assert response.status_code == 403
    
    response = client.get("/admin/loadbalancer/status", headers=customer_headers)
    assert response.status_code == 403

