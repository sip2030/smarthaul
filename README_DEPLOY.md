# SmartHaul Django Deployment Guide

This guide matches the verified Django/DRF backend in [django_smarthaul/](django_smarthaul/).

For local validation during this assignment, the Django server was confirmed working on `http://localhost:8001/` with the API root at `http://localhost:8001/api/`.

## Recommended free hosting options
- Render
- Railway
- Fly.io
- Azure App Service free tier where available

## What is included for free deployment
- Django 4.2 + Django REST Framework backend
- SQLite database for local and starter deployments
- Auth, bookings, vendors, providers, and payments APIs
- Provider and vendor dashboard pages
- Django admin site and protected API endpoints

## Deploy steps
1. Push the project to GitHub.
2. Create a PostgreSQL service first in Render and keep the `DATABASE_URL` handy.
3. Create a new web service on Render from `sip2030/smarthaul`.
4. Render will use [render.yaml](render.yaml) automatically.
5. Set required env vars: `SECRET_KEY`, `DEBUG=False`, `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `APP_BASE_URL`, `DATABASE_URL`.
6. Optional: set `FLUTTERWAVE_SECRET_KEY` and `FLUTTERWAVE_WEBHOOK_SECRET_HASH` to enable real payment collection.
7. Optional: set `ROUTING_PROVIDER=openrouteservice` and add `OPENROUTESERVICE_API_KEY` to enable provider-backed routing.
8. Deploy and wait for migration + gunicorn startup logs.
9. Verify with `python verify_deploy.py --base-url https://your-real-service.onrender.com`.

### One-shot admin creation
If you do not want to leave bootstrap admin credentials in deployment environment variables, create an admin once with:

```bash
python manage_admin.py --email admin@example.com --password StrongAdmin123 --name "SmartHaul Admin"
```

### Manual Render settings
- Build command: `pip install -r django_smarthaul/requirements.txt && python django_smarthaul/manage.py collectstatic --noinput && python django_smarthaul/manage.py migrate --noinput`
- Start command: `gunicorn --chdir django_smarthaul config.wsgi:application --bind 0.0.0.0:$PORT --workers 4 --timeout 120`
- Required env vars: `SECRET_KEY`, `DEBUG=False`, `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `APP_BASE_URL`, `DATABASE_URL`
- Optional database env var: `DATABASE_PATH=/var/data/smarthaul.db` when you have persistent disk storage available
- Optional payment env vars: `FLUTTERWAVE_SECRET_KEY`, `FLUTTERWAVE_WEBHOOK_SECRET_HASH`
- Optional routing env vars: `ROUTING_PROVIDER=openrouteservice`, `OPENROUTESERVICE_API_KEY`

### Recommended Render env values
- `DEBUG=False`
- `ALLOWED_HOSTS=.onrender.com,smarthaul.onrender.com`
- `CORS_ALLOWED_ORIGINS=https://your-frontend-domain.com`
- `APP_BASE_URL=https://your-real-service.onrender.com`

## Post-deploy verification
1. Confirm `/api/auth/health/` returns `200`.
2. Confirm `/api/auth/register/` and `/api/auth/login/` are reachable.
3. Confirm `/api/bookings/`, `/api/vendors/`, `/api/providers/`, and `/api/payments/` are reachable.
4. Confirm the Django admin site is reachable at `/admin/`.
5. Confirm `/api/auth/me/` returns authenticated profile data when a valid bearer token is supplied.

### Command-line verification
Use the deployment verifier with the real public URL:

```bash
python verify_deploy.py --base-url https://your-app.onrender.com
```

To include the admin login/profile verification in the same run:

```bash
python verify_deploy.py --base-url https://your-app.onrender.com --admin-email admin@example.com --admin-password StrongAdmin123
```

On Windows, use `py` if `python` is not available on your `PATH`:

```powershell
py verify_deploy.py --base-url https://your-real-service.onrender.com
```

## Notes
- SQLite is suitable for prototype and local testing.
- Render free web services do not provide durable local filesystem storage across rebuilds or instance replacement, so SQLite data should be treated as ephemeral there.
- If you need persistent production data, prefer PostgreSQL.
- `manage_admin.py` provides a safer one-shot alternative when you want to create an admin without keeping bootstrap credentials in long-lived environment variables.
- The Django implementation has been verified locally on `http://localhost:8001/` with auth, bookings, vendors, providers, and payments flows.
