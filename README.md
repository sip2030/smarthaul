# SmartHaul

SmartHaul is a launch-ready MVP prototype for a future-ready mobility, haulage, marketplace, and AI support platform.

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
uvicorn app:app --reload
```

Then open:
- http://127.0.0.1:8000/ for the landing experience
- http://127.0.0.1:8000/docs for the API docs
- http://127.0.0.1:8000/workspace for the workspace experience
- http://127.0.0.1:8000/notifications-page for the notifications view
- http://127.0.0.1:8000/admin for the admin dashboard, deployment status table, and copyable diagnostics block

## Free-tier deployment
Use the lightweight dependency file [requirements-free.txt](requirements-free.txt) if you want a simpler deployment target.
See [README_DEPLOY.md](README_DEPLOY.md) for hosting instructions.

### Tests
```bash
pytest -q
```

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
Authenticated admins can use `/admin` for a browser-facing deployment status view and `/admin/health` for a protected JSON healthcheck that reports the active backend and integration state.

For deeper operational visibility, `/admin/monitoring` and `/admin/monitoring/snapshot` expose queue depth, safety signals, and the active alert set.

If you want to verify a deployment from the command line, use `verify_deploy.py` with the real public base URL and optional admin credentials.

### Admin bootstrap
For first-time deployment, you can set `BOOTSTRAP_ADMIN_EMAIL` and `BOOTSTRAP_ADMIN_PASSWORD` to seed an initial admin account automatically during startup. `BOOTSTRAP_ADMIN_NAME` is optional.

If you prefer a one-shot manual step instead of startup seeding, run:

```bash
python manage_admin.py --email admin@example.com --password StrongAdmin123 --name "SmartHaul Admin"
```

To rotate an existing admin password, add `--update-existing`.

### Verified status
The current implementation has been verified with 36 passing tests.

### Launch decisions
The current recommended launch path is documented in [SMARTHAUL_DECISIONS_DRAFT.md](SMARTHAUL_DECISIONS_DRAFT.md). In short:

- Launch in Lagos, Nigeria first.
- Focus on ride requests, haulage, and vendor marketplace flows.
- Ship the responsive web app first.
- Use Flutterwave for production payments.
- Keep the launch compliance baseline on account verification, session security, moderation, and dispute handling.
