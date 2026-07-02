import argparse
import sys
from typing import Any
from urllib.parse import urlparse

import httpx


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify a deployed SmartHaul instance.")
    parser.add_argument("--base-url", required=True, help="Public base URL, for example https://smarthaul.onrender.com")
    parser.add_argument("--admin-email", help="Optional admin email for protected checks")
    parser.add_argument("--admin-password", help="Optional admin password for protected checks")
    parser.add_argument("--timeout", type=float, default=15.0, help="HTTP timeout in seconds")
    return parser.parse_args()


def validate_base_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    parsed = urlparse(normalized)
    hostname = (parsed.hostname or "").lower()
    placeholder_hosts = {"your-app.onrender.com", "example.com", "localhost"}

    if parsed.scheme not in {"http", "https"}:
        raise RuntimeError("--base-url must include http:// or https://")
    if hostname in placeholder_hosts or "your-app" in hostname:
        raise RuntimeError("--base-url is still using the placeholder host; replace it with your real deployed URL")
    return normalized


def require_ok(response: httpx.Response, label: str) -> dict[str, Any]:
    if response.status_code != 200:
        if response.status_code == 404:
            raise RuntimeError(
                f"{label} failed with status 404. Check that --base-url points to the real SmartHaul deployment and not a placeholder or different app."
            )
        raise RuntimeError(f"{label} failed with status {response.status_code}: {response.text[:200]}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"{label} did not return a JSON object")
    return payload


def verify_public_endpoints(client: httpx.Client) -> None:
    health_response = client.get("/health")
    if health_response.status_code == 404:
        root_response = client.get("/")
        if root_response.status_code == 200 and "SmartHaul" in root_response.text:
            raise RuntimeError(
                "GET /health returned 404 even though the app responds on /. Redeploy the latest SmartHaul commit so the health route is available."
            )
        raise RuntimeError(
            "GET /health returned 404. Check that --base-url points to the real SmartHaul deployment and not a placeholder or different app."
        )

    health = require_ok(health_response, "GET /health")
    diagnostics = require_ok(client.get("/diagnostics"), "GET /diagnostics")

    print(f"health.status={health.get('status')}")
    print(f"diagnostics.database_backend={diagnostics.get('database_backend')}")
    print(f"diagnostics.routing_provider={diagnostics.get('routing_provider')}")
    print(f"diagnostics.flutterwave_configured={diagnostics.get('flutterwave_configured')}")
    print(f"diagnostics.bootstrap_admin_configured={diagnostics.get('bootstrap_admin_configured')}")


def verify_admin_endpoints(client: httpx.Client, admin_email: str, admin_password: str) -> None:
    login = require_ok(
        client.post(
            "/auth/login",
            json={"email": admin_email, "password": admin_password},
        ),
        "POST /auth/login",
    )
    if login.get("message") != "Login successful":
        raise RuntimeError(f"POST /auth/login returned unexpected payload: {login}")

    admin_health = require_ok(client.get("/admin/health"), "GET /admin/health")
    diagnostics = admin_health.get("diagnostics") or {}
    metrics = admin_health.get("metrics") or {}
    monitoring = require_ok(client.get("/admin/monitoring/snapshot"), "GET /admin/monitoring/snapshot")
    alerts = monitoring.get("alerts") or []

    print(f"admin_health.status={admin_health.get('status')}")
    print(f"admin_health.database_backend={diagnostics.get('database_backend')}")
    print(f"admin_health.pending_vendor_reviews={metrics.get('pending_vendor_reviews')}")
    print(f"admin_health.flagged_messages={metrics.get('flagged_messages')}")
    print(f"monitoring.status={monitoring.get('status')}")
    print(f"monitoring.alerts={len(alerts)}")
    if alerts:
        first_alert = alerts[0]
        print(f"monitoring.top_alert={first_alert.get('severity')}:{first_alert.get('title')}")


def main() -> int:
    args = parse_args()
    base_url = validate_base_url(args.base_url)

    try:
        with httpx.Client(base_url=base_url, follow_redirects=True, timeout=args.timeout) as client:
            print(f"verifying deployment at {base_url}")
            print("tip: use the real public Render URL for the deployed SmartHaul service")
            verify_public_endpoints(client)
            if args.admin_email and args.admin_password:
                verify_admin_endpoints(client, args.admin_email, args.admin_password)
            else:
                print("admin checks skipped: provide --admin-email and --admin-password to verify /admin/health")
    except Exception as exc:
        print(f"deployment verification failed: {exc}", file=sys.stderr)
        return 1

    print("deployment verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())