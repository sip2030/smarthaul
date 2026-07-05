# SmartHaul

SmartHaul is a launch-ready MVP prototype for a future-ready mobility, haulage, marketplace, and AI support platform.

The verified backend path in this workspace is the Django/DRF app in [django_smarthaul/](django_smarthaul/), which was tested locally on `http://localhost:8001/`.

## Current MVP features
- Booking flow for rides and haulage with lifecycle states
- Session-based authentication with password policy, lockout protection, password rotation, stale-session invalidation, and protected dashboard access
- Provider and vendor dashboard pages
- Payments, refunds, Flutterwave payment initialization and verification, and dispute handling
- AI support assistant with escalation guidance
- Reports, richer notifications, quotes, live tracking snapshots, messaging, and provider-backed route previews
- Vendor onboarding review queue with status-aware approval and document state updates, admin operations analytics, automated moderation cases, and moderation resolution tools
- Advanced analytics dashboard, admin monitoring snapshot, and performance-oriented database indexing for scaling the dashboards
- Live call logging with consent tracking and moderation flagging for support escalations
- Admin metrics and an audit activity feed
- Responsive UI pages for workspace, admin, monitoring, and support views
- Automated test coverage for core product flows

## Run locally

### Backend
```bash
python -m pip install -r requirements.txt
python django_smarthaul/manage.py runserver 0.0.0.0:8001
```

Then open:
- http://127.0.0.1:8001/api/auth/health/ for the API health check
- http://127.0.0.1:8001/api/auth/register/ for registration
- http://127.0.0.1:8001/api/auth/login/ for login
- http://127.0.0.1:8001/api/bookings/ for booking APIs
- http://127.0.0.1:8001/admin for the Django admin site

## Free-tier deployment
Use the verified Django dependency file [django_smarthaul/requirements.txt](django_smarthaul/requirements.txt) for deployment.
See [README_DEPLOY.md](README_DEPLOY.md) for hosting instructions.

### Tests
```bash
pytest -q
```

Generated local cache folders such as `.pytest_cache/` and `__pycache__/` are ignored by Git and may reappear after running tests or Python modules locally.

### Flutterwave setup
Configure these environment variables to enable real payment initialization and verification:

- `FLUTTERWAVE_SECRET_KEY`
- `FLUTTERWAVE_WEBHOOK_SECRET_HASH`
- `APP_BASE_URL` for the payment verification callback URL

If these variables are not set, the app continues using the existing sandbox payment flow.

### Routing setup
Configure these environment variables to enable provider-backed route estimation and live tracking:

- `ROUTING_PROVIDER=openrouteservice`
- `OPENROUTESERVICE_API_KEY`
- `OPENROUTESERVICE_BASE_URL` if you need a non-default endpoint

If these variables are not set, the app continues using the simulated route engine.

### PostgreSQL setup
To move persistence off SQLite, set `DATABASE_URL` to a PostgreSQL connection string. When `DATABASE_URL` starts with `postgres://` or `postgresql://`, the app automatically uses PostgreSQL and ignores `DATABASE_PATH`.

### Admin diagnostics
Authenticated admins can use `/admin` for the Django admin site. The Django API also exposes `/api/auth/health/` for a public healthcheck and `/api/auth/me/` for authenticated profile inspection.

For deeper operational visibility, continue using the deployment docs in [README_DEPLOY.md](README_DEPLOY.md).

If you want to verify a deployment from the command line, use `verify_deploy.py` with the real public base URL and optional admin credentials.

### Admin bootstrap
For first-time deployment, you can set `BOOTSTRAP_ADMIN_EMAIL` and `BOOTSTRAP_ADMIN_PASSWORD` to seed an initial admin account automatically during startup. `BOOTSTRAP_ADMIN_NAME` is optional.

If you prefer a one-shot manual step instead of startup seeding, run:

```bash
python manage_admin.py --email admin@example.com --password StrongAdmin123 --name "SmartHaul Admin"
```

To rotate an existing admin password, add `--update-existing`.

### Verified status
The Django backend has been verified locally with auth, booking, vendor, provider, and payment flows.

### Launch decisions
The current recommended launch path is documented in [SMARTHAUL_DECISIONS_DRAFT.md](SMARTHAUL_DECISIONS_DRAFT.md). In short:

- Launch in Lagos, Nigeria first.
- Focus on ride requests, haulage, and vendor marketplace flows.
- Ship the responsive web app first.
- Use Flutterwave for production payments.
- Keep the launch compliance baseline on account verification, session security, moderation, and dispute handling.
