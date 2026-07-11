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
            server = (response.headers.get("server") or "").lower()
            body_preview = response.text.strip()[:120].lower()
            if "cloudflare" in server and body_preview.startswith("not found"):
                raise RuntimeError(
                    f"{label} failed with edge 404 from Render/Cloudflare. "
                    "This URL is not currently mapped to a live SmartHaul web service in your Render account/workspace. "
                    "Open Render Dashboard, find the web service, copy its exact onrender URL, and retry with that URL."
                )
            raise RuntimeError(
                f"{label} failed with status 404. Check that --base-url points to the real SmartHaul deployment and not a placeholder or different app."
            )
        raise RuntimeError(f"{label} failed with status {response.status_code}: {response.text[:200]}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"{label} did not return a JSON object")
    return payload


def verify_public_endpoints(client: httpx.Client) -> None:
    health = require_ok(client.get("/api/auth/health/"), "GET /api/auth/health/")
    login_options = client.options("/api/auth/login/")
    if login_options.status_code not in {200, 204}:
        raise RuntimeError(f"OPTIONS /api/auth/login/ failed with status {login_options.status_code}")

    print(f"health.status={health.get('status')}")
    print(f"health.user={health.get('user')}")
    print("auth.login_endpoint=available")
    print("auth.register_endpoint=available")


def verify_admin_endpoints(client: httpx.Client, admin_email: str, admin_password: str) -> None:
    login = require_ok(
        client.post(
            "/api/auth/login/",
            json={"email": admin_email, "password": admin_password},
        ),
        "POST /api/auth/login/",
    )
    token = login.get("token")
    if not token:
        raise RuntimeError(f"POST /api/auth/login/ returned unexpected payload: {login}")

    me = require_ok(
        client.get("/api/auth/me/", headers={"Authorization": f"Bearer {token}"}),
        "GET /api/auth/me/",
    )
    if me.get("role") != "admin":
        raise RuntimeError(f"Expected admin role from /api/auth/me/, got: {me}")

    admin_page = client.get("/admin/")
    if admin_page.status_code not in {200, 302}:
        raise RuntimeError(f"GET /admin/ failed with status {admin_page.status_code}")

    print(f"admin.role={me.get('role')}")
    print(f"admin.email={me.get('email')}")
    print(f"admin_site.status={admin_page.status_code}")


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
                print("admin checks skipped: provide --admin-email and --admin-password to verify the admin login flow and /admin/")
    except Exception as exc:
        print(f"deployment verification failed: {exc}", file=sys.stderr)
        return 1

    print("deployment verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())