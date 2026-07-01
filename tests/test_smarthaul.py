import pytest
from fastapi.testclient import TestClient

from app import app


client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_root_serves_frontend():
    response = client.get("/")
    assert response.status_code == 200
    assert "SmartHaul" in response.text


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
    metrics = client.get("/admin/metrics")
    assert metrics.status_code == 200
    payload = metrics.json()
    assert payload["reports"] >= 1


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
