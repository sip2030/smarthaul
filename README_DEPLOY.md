# SmartHaul Free Deployment Guide

This project is designed to run as a free-tier starter using open-source tools and low-cost or free hosting options.

## Recommended free hosting options
- Render
- Railway
- Fly.io
- GitHub Pages for static assets only
- Azure App Service free tier where available

## What is included for free deployment
- Python/FastAPI backend
- Jinja templates for frontend views
- SQLite database for lightweight persistence
- Booking, vendor, quote, report, notification, messaging, payment, refund, and dispute flows
- Provider and vendor dashboard pages
- Admin metrics, audit visibility, deployment diagnostics, and a protected admin healthcheck
- No paid API dependency required for the starter experience

## Deploy steps
1. Push the project to GitHub.
2. Create a new web service on Render.
3. Render will use the included [render.yaml](render.yaml) configuration automatically.
4. In Render, set `APP_BASE_URL` to your public app URL.
5. Preferred for durable production data: attach a managed PostgreSQL database and set `DATABASE_URL`.
6. Optional: set `FLUTTERWAVE_SECRET_KEY` and `FLUTTERWAVE_WEBHOOK_SECRET_HASH` to enable real payment collection.
7. Optional: set `ROUTING_PROVIDER=openrouteservice` and add `OPENROUTESERVICE_API_KEY` to enable provider-backed routing.
8. Optional: set `DATABASE_PATH` only if you attach persistent storage or move to an external database-backed setup.
9. Optional: set `BOOTSTRAP_ADMIN_EMAIL` and `BOOTSTRAP_ADMIN_PASSWORD` to create an initial admin account automatically on first startup.
10. Deploy.

### One-shot admin creation
If you do not want to leave bootstrap admin credentials in deployment environment variables, you can create an admin account once with:

```bash
python manage_admin.py --email admin@example.com --password StrongAdmin123 --name "SmartHaul Admin"
```

If the admin already exists and you want to rotate the password or reassert admin access, run:

```bash
python manage_admin.py --email admin@example.com --password StrongAdmin123 --name "SmartHaul Admin" --update-existing
```

The command also supports `BOOTSTRAP_ADMIN_NAME`, `BOOTSTRAP_ADMIN_EMAIL`, and `BOOTSTRAP_ADMIN_PASSWORD` as defaults.

### Manual Render settings
- Build command: `pip install -r requirements-free.txt`
- Start command: `uvicorn app:app --host 0.0.0.0 --port $PORT`
- Required env var: `APP_BASE_URL=https://your-public-domain`
- Preferred database env var: `DATABASE_URL=postgresql://...`
- Optional database env var: `DATABASE_PATH=/var/data/smarthaul.db` when you have persistent disk storage available
- Optional payment env vars: `FLUTTERWAVE_SECRET_KEY`, `FLUTTERWAVE_WEBHOOK_SECRET_HASH`
- Optional routing env vars: `ROUTING_PROVIDER=openrouteservice`, `OPENROUTESERVICE_API_KEY`
- Optional bootstrap admin env vars: `BOOTSTRAP_ADMIN_NAME`, `BOOTSTRAP_ADMIN_EMAIL`, `BOOTSTRAP_ADMIN_PASSWORD`

## Post-deploy verification
1. Sign in with an admin account.
2. Open `/admin` to verify the browser-facing deployment status table.
3. Confirm the expected values for database backend, routing configuration, Flutterwave configuration, and the operational alert summary.
4. Confirm whether the bootstrap admin env vars are still present so they can be removed after first startup.
5. Open `/admin/health` while authenticated as an admin to retrieve the protected JSON healthcheck payload.
6. Open `/admin/monitoring` or `/admin/monitoring/snapshot` to inspect queue depth, safety signals, and alert severity in detail.

### Command-line verification
You can also verify a deployed instance from the command line:

```bash
python verify_deploy.py --base-url https://your-app.onrender.com
```

The script prints the target first and then a short reminder to use the real public Render URL for the deployed SmartHaul service.

The script now prints the exact target first, for example:

```text
verifying deployment at https://your-real-service.onrender.com
```

```text
tip: use the real public Render URL for the deployed SmartHaul service
```

Replace `https://your-app.onrender.com` with the real public URL shown in your Render dashboard. Do not run the placeholder example URL literally.

On Windows, use `py` if `python` is not available on your `PATH`:

```powershell
py verify_deploy.py --base-url https://your-real-service.onrender.com
```

To include the protected admin healthcheck in the same run:

```bash
python verify_deploy.py --base-url https://your-app.onrender.com --admin-email admin@example.com --admin-password StrongAdmin123
```

Windows example:

```powershell
py verify_deploy.py --base-url https://your-real-service.onrender.com --admin-email admin@example.com --admin-password StrongAdmin123
```

## Notes
- SQLite is suitable for prototype and local testing.
- Render free web services do not provide durable local filesystem storage across rebuilds or instance replacement, so SQLite data should be treated as ephemeral there.
- If you need persistent production data, prefer PostgreSQL. Use `DATABASE_PATH` only when you are intentionally deploying on persistent disk storage.
- For maps and routing, set `ROUTING_PROVIDER=openrouteservice` and provide `OPENROUTESERVICE_API_KEY` to enable provider-backed route estimation and tracking.
- To enable real payment collection with Flutterwave, set `FLUTTERWAVE_SECRET_KEY`, `FLUTTERWAVE_WEBHOOK_SECRET_HASH`, and `APP_BASE_URL` in your deployment environment.
- The admin dashboard now includes a copyable deployment diagnostics block, and `/admin/health` exposes the same state in protected JSON form.
- The admin dashboard also surfaces the current operational alert summary, which mirrors the monitoring snapshot used by the deployment verifier.
- If `BOOTSTRAP_ADMIN_EMAIL` and `BOOTSTRAP_ADMIN_PASSWORD` are set, startup will create the initial admin account automatically if that email does not already exist.
- The admin diagnostics now also show whether the bootstrap admin credentials are still configured, which is useful as a post-deploy cleanup reminder.
- `manage_admin.py` provides a safer one-shot alternative when you want to create an admin without keeping bootstrap credentials in long-lived environment variables.
- The current app has been verified locally with 36 passing tests.

---

# Phase 5.6 - Production Deployment Checklist & Runbooks

## Pre-Launch Production Validation Checklist

### Security Pre-Deployment (Required ✓)
- [ ] Remove all bootstrap admin credentials from environment variables after first login
- [ ] Verify `FLUTTERWAVE_SECRET_KEY` is configured if accepting real payments
- [ ] Verify `FLUTTERWAVE_WEBHOOK_SECRET_HASH` matches Flutterwave dashboard
- [ ] Confirm HTTPS is enabled on deployment (Render enables by default)
- [ ] Verify CORS is restricted to known domains only
- [ ] Confirm rate limiting is enforced (`/admin/security/monitoring`)
- [ ] Verify brute-force protection is active (5 max attempts, 15-min lockout)
- [ ] Test IP blocking functionality at `/admin/security/block-ip`

### Database Pre-Deployment (Required ✓)
- [ ] PostgreSQL attached to production environment (preferred over SQLite)
- [ ] Database backups enabled and tested
- [ ] `DATABASE_URL` environment variable configured correctly
- [ ] Test database connectivity: `curl https://your-app/admin/health/dependencies`
- [ ] Verify automatic migration of schema on startup
- [ ] Confirm 19+ required tables exist in database
- [ ] Set backup retention to 7+ days minimum
- [ ] Test point-in-time recovery procedure

### Application Configuration (Required ✓)
- [ ] `APP_BASE_URL` matches exact domain (no trailing slash)
- [ ] `ROUTING_PROVIDER` set to `openrouteservice` if enabling maps
- [ ] `OPENROUTESERVICE_API_KEY` configured if using routing
- [ ] Health check endpoints responding: `/health`, `/health/deep`, `/health/readiness`
- [ ] Admin endpoints protected: `/admin/*` require authentication
- [ ] All required environment variables documented and set

### Monitoring & Alerting (Required ✓)
- [ ] Health monitoring dashboard accessible at `/admin/monitoring`
- [ ] Alert rules configured with appropriate thresholds
- [ ] Log aggregation working (`/admin/logs`)
- [ ] Centralized dashboard showing all metrics (`/admin/monitoring/dashboard`)
- [ ] SLA metrics visible at `/admin/sla/metrics`
- [ ] Compliance status tracked at `/admin/compliance/status`

### Load Testing & Performance (Recommended)
- [ ] Run load test: `ab -n 1000 -c 10 https://your-app/health`
- [ ] Verify scaling policies trigger appropriately
- [ ] Monitor memory usage under load
- [ ] Confirm response times stay under 500ms at P95
- [ ] Check database query performance under concurrent load

### Disaster Recovery (Required ✓)
- [ ] Backup creation tested: `POST /admin/backup/create`
- [ ] Restore procedure validated on staging
- [ ] Failover readiness confirmed: `GET /admin/failover/status`
- [ ] DR plan reviewed: `GET /admin/dr/plan`
- [ ] Backup retention policy set (minimum 7 days)
- [ ] Test DR drill completed successfully: `POST /admin/dr/test`

### Data Integrity (Required ✓)
- [ ] Database integrity check passes: `PRAGMA integrity_check`
- [ ] No orphaned records in related tables
- [ ] Payment data encrypted (if storing locally)
- [ ] User data privacy compliance verified
- [ ] GDPR compliance status confirmed at `/admin/compliance/status`

### Compliance & Audit (Required ✓)
- [ ] Audit logs enabled and retained
- [ ] Admin activity logged at `/admin/activity-logs`
- [ ] User consent tracking in place for data collection
- [ ] Payment provider terms reviewed and accepted
- [ ] Terms of Service and Privacy Policy linked on frontend

---

## Production Runbooks

### Runbook 1: Daily Operations

#### Morning Health Check (5 min)
```bash
curl https://your-app/admin/health/deep \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```
Expected: All dependencies show `"status": "healthy"`

**If anything fails:**
1. Check `/admin/monitoring` for alert details
2. Review recent logs: `GET /admin/logs?level=error&limit=50`
3. Verify database connection: `GET /admin/health/dependencies`

#### Hourly Metrics Review (Optional)
```bash
curl https://your-app/admin/monitoring/dashboard \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```
Monitor: Request rate, error rate, average response time

**If error rate > 1%:**
1. Check alert rules: `GET /admin/alerts/rules`
2. Review centralized logs: `GET /admin/logs/analytics`
3. Identify problematic component from logs

#### End-of-Day Backup Verification (2 min)
```bash
curl https://your-app/admin/backup/list \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```
Expected: Latest backup timestamp within 24 hours

---

### Runbook 2: Scaling Operations

#### Manual Scale-Up (When needed)
```bash
curl -X POST https://your-app/admin/scaling/policies \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Emergency Scale-Up",
    "metric": "cpu",
    "threshold_up": 70.0,
    "threshold_down": 40.0,
    "scale_up_instances": 3,
    "scale_down_instances": 1,
    "cooldown_minutes": 5
  }'
```

#### Check Scaling Status
```bash
curl https://your-app/admin/scaling/metrics \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

#### Get Capacity Recommendations
```bash
curl https://your-app/admin/capacity/plan \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

---

### Runbook 3: Incident Response

#### Alert Triggered: High Error Rate

**Step 1: Assess (2 min)**
```bash
# Get alert details
curl https://your-app/admin/alerts \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"

# Check error logs
curl "https://your-app/admin/logs?level=error" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Step 2: Isolate (5 min)**
- Identify affected component from logs
- Check if specific endpoint or database query is failing
- Review recent deployments or configuration changes

**Step 3: Recover (5-10 min)**
**Option A: Restart affected service**
```bash
# Deploy rollback via Render dashboard or:
# git revert <commit-hash>
# git push origin main
```

**Option B: Scale up temporarily**
```bash
curl -X POST https://your-app/admin/scaling/policies \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "Emergency Scale", "metric": "requests", "threshold_up": 500, "scale_up_instances": 5}'
```

**Option C: Enable read-only mode** (if database issue)
- Stop write operations
- Direct users to maintenance page
- Restore from backup if corruption detected

#### Alert Triggered: Database Down

**Step 1: Verify database connectivity**
```bash
curl https://your-app/admin/health/dependencies \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Step 2: Check failover status**
```bash
curl https://your-app/admin/failover/status \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Step 3: Restore from backup if needed**
```bash
curl -X POST https://your-app/admin/backup/restore \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"backup_id": "backup-20260702-120000"}'
```

---

### Runbook 4: Disaster Recovery Procedure

#### Test DR Readiness (Monthly)
```bash
# 1. Run DR test
curl -X POST https://your-app/admin/dr/test \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"

# 2. Verify recovery point objective (RPO)
curl https://your-app/admin/dr/plan \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

Expected response:
```json
{
  "rpo_seconds": 300,
  "rto_seconds": 600,
  "failover_status": "ready"
}
```

#### Full Disaster Recovery (When needed)

**Step 1: Create fresh backup**
```bash
curl -X POST https://your-app/admin/backup/create \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Step 2: Get available backups**
```bash
curl https://your-app/admin/backup/list \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Step 3: Restore to point-in-time**
```bash
curl -X POST https://your-app/admin/backup/restore \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"backup_id": "backup-20260701-180000"}'
```

**Step 4: Verify data integrity**
```bash
curl https://your-app/admin/health/deep \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

---

### Runbook 5: Log Management

#### View Recent Errors
```bash
curl "https://your-app/admin/logs?component=app&level=error&limit=20" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

#### Get Log Analytics
```bash
curl https://your-app/admin/logs/analytics \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

#### Configure Log Retention Policy
```bash
curl -X POST https://your-app/admin/logs/retention \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "retention_days": 90,
    "archive_after_days": 30
  }'
```

#### Manual Log Cleanup
```bash
curl -X POST https://your-app/admin/logs/cleanup \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

---

### Runbook 6: Load Balancer Management

#### Check Load Balancer Status
```bash
curl https://your-app/admin/loadbalancer/status \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

#### Update Load Balancing Algorithm
```bash
curl -X POST https://your-app/admin/loadbalancer/config \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "algorithm": "least_connections",
    "health_check_interval_seconds": 10,
    "sticky_sessions": false
  }'
```

Available algorithms:
- `round_robin` - Distribute evenly across instances
- `least_connections` - Route to instance with fewest active connections
- `weighted` - Route based on instance weight
- `ip_hash` - Route based on client IP (ensures session stickiness)

#### Get Instance Metrics
```bash
curl https://your-app/admin/scaling/instances \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

---

### Runbook 7: Security Management

#### Block Malicious IP
```bash
curl -X POST https://your-app/admin/security/block-ip \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "ip_address": "192.168.1.100",
    "reason": "Brute force attack detected"
  }'
```

#### View Security Events
```bash
curl https://your-app/admin/security/events \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

#### Check Rate Limiting Status
```bash
curl https://your-app/admin/security/monitoring \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

---

## Post-Incident Review Checklist

After resolving any production incident:

- [ ] Document incident timeline and root cause
- [ ] Review alert thresholds (were they too high/low?)
- [ ] Check if prevention was possible (e.g., pre-staging test)
- [ ] Update monitoring rules based on lessons learned
- [ ] Implement preventive measures for similar future incidents
- [ ] Archive incident logs for compliance audit trail
- [ ] Schedule post-incident meeting with team within 48 hours

---

## Monitoring Best Practices

### Recommended Alert Thresholds

| Metric | Warning | Critical |
|--------|---------|----------|
| CPU Usage | 70% | 90% |
| Memory Usage | 75% | 90% |
| Error Rate | 1% | 5% |
| Response Time P95 | 500ms | 2000ms |
| Database Connection Pool | 80% | 95% |
| Disk Usage | 80% | 95% |
| Request Queue Depth | 100 | 500 |

### Log Levels Reference

| Level | Usage |
|-------|-------|
| DEBUG | Development only, verbose troubleshooting |
| INFO | Normal operations, deployment events |
| WARNING | Degraded performance, threshold breaches |
| ERROR | Service failures, unrecoverable errors |
| CRITICAL | System down, data loss, security breach |

---

## Rollback Procedures

### Immediate Rollback (< 5 minutes)

```bash
# 1. SSH/Connect to Render or hosting provider
# 2. View deployment history
git log --oneline -5

# 3. Revert to previous working commit
git revert HEAD
git push origin main

# 4. Render will automatically redeploy
# 5. Verify health:
curl https://your-app/health
```

### Rollback with Database Changes

If the rollback includes database schema changes:

```bash
# 1. Create backup before rollback
curl -X POST https://your-app/admin/backup/create \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"

# 2. Revert code
git revert HEAD
git push origin main

# 3. Monitor for errors:
curl https://your-app/admin/logs?level=error

# 4. If database migration fails, restore from backup
curl -X POST https://your-app/admin/backup/restore \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"backup_id": "latest"}'
```

---

## Performance Optimization Checklist

- [ ] Enable query caching: TTL 60 seconds (default)
- [ ] Connection pool size optimized: 20 for PostgreSQL
- [ ] Database indexes verified for hot tables
- [ ] API response compression enabled (gzip)
- [ ] Static assets served from CDN if available
- [ ] Database slow query logging enabled
- [ ] Load balancer algorithm optimized for workload
- [ ] Auto-scaling policies tested under load

---

## Post-Deployment Monitoring (First 24 Hours)

| Time | Action |
|------|--------|
| T+0min | Verify all health checks pass |
| T+5min | Check error logs for startup issues |
| T+15min | Monitor request patterns for anomalies |
| T+1hr | Review error rate and response times |
| T+4hr | Check database size and connection usage |
| T+12hr | Verify nightly backups completed |
| T+24hr | Generate deployment metrics report |


