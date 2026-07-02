# SmartHaul Admin Walkthrough Guide

**Version:** 1.0.0  
**Updated:** 2026-07-02  
**Audience:** System Administrators, DevOps Engineers, Operations Team

---

## Table of Contents
1. [Initial Setup](#initial-setup)
2. [Daily Operations](#daily-operations)
3. [Monitoring Dashboard](#monitoring-dashboard)
4. [User & Vendor Management](#user--vendor-management)
5. [Financial Management](#financial-management)
6. [System Health](#system-health)
7. [Security & Compliance](#security--compliance)
8. [Troubleshooting](#troubleshooting)

---

## Initial Setup

### Step 1: First Login
After deployment, navigate to your SmartHaul instance:
```
https://your-app.onrender.com
```

### Step 2: Create Admin Account
**Option A: Bootstrap Admin (Automatic)**
- If you set `BOOTSTRAP_ADMIN_EMAIL` and `BOOTSTRAP_ADMIN_PASSWORD` environment variables
- These are created automatically on first startup
- **Remember to remove these env vars after first login for security**

**Option B: Manual Creation**
```bash
python manage_admin.py --email admin@smarthaul.ng --password StrongPassword123 --name "Admin User"
```

### Step 3: Access Admin Panel
After login with admin credentials:
```
https://your-app.onrender.com/admin
```

You should see the **Admin Dashboard** with system status overview.

---

## Daily Operations

### Morning Checklist (5 minutes)

**1. Check System Status**
```
Admin → Monitoring Dashboard
```

Look for:
- ✅ Total Users: Growing steadily?
- ✅ Active Bookings: Expected volume?
- ✅ Daily Revenue: On track?
- ✅ System Uptime: 99%+?

**2. Review Overnight Logs**
```
Admin → Logs → Filter: Last 8 hours, Level: ERROR
```

**3. Check Active Alerts**
```
Admin → Alerts
```

Expected: 0 alerts or only warnings (not critical)

**4. Verify Backups**
```
Admin → Backups → View List
```

Expected: Latest backup within last 2 hours

### Hourly Monitoring (Quick Check)

```
Admin → Health → Quick Check
```

Expected response (all "healthy"):
```json
{
  "status": "healthy",
  "database": "healthy",
  "cache": "healthy",
  "storage": "healthy"
}
```

### End of Day (5 minutes)

**1. Export Daily Report**
```
Admin → Reports → Generate Daily Summary
```

Download and save for records.

**2. Verify Backup**
```
Admin → Backups → List
```

Confirm today's backup is present and complete.

**3. Note Any Issues**
```
Admin → Logs → Export Error Log (Last 24h)
```

Save for review/escalation if needed.

---

## Monitoring Dashboard

### Dashboard Overview

**Location:** `Admin → Monitoring → Dashboard`

#### Key Sections

**Summary Cards (Top)**
```
┌─────────────────┬──────────────────┬──────────────┬─────────────┐
│  Total Users    │  Active Bookings │ Daily Revenue│ Uptime %    │
│     2,450       │       142        │  ₦285,000    │   99.95%    │
└─────────────────┴──────────────────┴──────────────┴─────────────┘
```

**What to look for:**
- **Total Users:** Should increase daily (healthy growth)
- **Active Bookings:** Should vary by time (peak hours expected)
- **Daily Revenue:** Track for revenue targets
- **Uptime %:** Must be ≥ 99% (target: 99.95%)

**Real-time Metrics**
```
Request Rate:             250 req/s (normal)
Error Rate:              0.5% (acceptable, alert at > 1%)
Avg Response Time:       145ms (good, alert at > 500ms)
Active Connections:       85 (normal)
Database Connections:    12/20 (pool usage 60%, alert at 80%)
Requests in Queue:        5 (normal, alert at > 100)
```

**What to watch:**
- Error rate creeping up? Investigate logs
- Response time increasing? Check database
- High queue depth? Consider scaling up

**Alert Summary**
```
Total Alerts:     3
  Critical:       0 ✅
  Warning:        3 ⚠
  Info:           0
```

### Real-time Graphs (if available)

**1. Request Volume**
- Shows requests per minute over last hour
- Should show clear patterns (peaks/valleys expected)

**2. Error Rate**
- Shows % errors over time
- Should stay below 1%
- Spike = investigate logs immediately

**3. Response Time**
- Shows P50, P95, P99 latencies
- P95 should be < 500ms
- P99 should be < 2 seconds

**4. Database Performance**
- Connection pool usage
- Query response times
- Should be stable

---

## User & Vendor Management

### Managing Users

**View All Users**
```
Admin → Users → List
```

**User Details Panel**
```
Name, Email, Role, Status, Created Date, Last Login
```

**Common Actions:**

**1. View User Bookings**
- Click user → Bookings tab
- See all bookings by this user

**2. Check User Activity**
- Click user → Activity tab
- See login history, actions performed

**3. Reset User Password**
- Click user → Settings
- "Force Password Reset"
- Email sent to user automatically

**4. Disable/Ban User**
- Click user → Security
- "Restrict Account" (temporary)
- "Permanently Ban" (if needed)

### Managing Vendors

**View All Vendors**
```
Admin → Vendors → List
```

**Vendor Verification Workflow**

**Status: Pending Review** (new vendor)
1. Check documents uploaded
2. Verify business registration
3. Check insurance validity
4. Review business details
5. Approve or Request Changes

**Approving Vendor**
```
Vendor Details → "Approve Vendor"
- Set commission rate (default: 15%)
- Set service area boundaries
- Define operating hours
- Click "Confirm Approval"
```

**Status: Verified** (active vendor)
- Monitor performance metrics
- Track delivery times
- Monitor customer ratings
- Handle disputes

**Suspending Vendor**
```
Vendor Details → "Actions" → "Suspend"
- Reason (select or custom)
- Duration (temporary) or permanent
- Notify vendor via email
```

### Managing Providers (Drivers)

**View All Providers**
```
Admin → Providers → List
```

**Provider Quality Metrics**
- Average rating (target: 4.0+)
- Completion rate (target: 95%+)
- Response time
- Customer reviews

**Actions:**

**1. Encourage High Performers**
- Rating > 4.8: Consider for "Top Provider" badge
- Completion rate > 99%: Send incentive bonus

**2. Help Low Performers**
- Rating < 3.0: Send training materials
- Many cancellations: Investigate issues
- Consistent delays: Offer support

**3. Investigate Issues**
- Click provider → Disputes tab
- Review customer feedback
- Check incident history

---

## Financial Management

### Payment Monitoring

**Payment Dashboard**
```
Admin → Payments → Overview
```

**What to Monitor:**

**1. Payment Success Rate**
```
Target: > 98%
Warning: < 97%
Critical: < 95%
```

**2. Transaction Types**
- Card payments
- Wallet payments
- Promotional/discount usage

**3. Average Transaction Value**
- Track for trends
- Identify peak value times

### Processing Refunds

**Refund Request Flow**
```
Admin → Disputes → Pending Refunds
```

**To Process Refund:**
1. Click dispute → View details
2. Verify reason for refund
3. Check booking status
4. Approve refund
5. Select refund method:
   - Wallet (instant)
   - Card (1-3 days)
   - Bank transfer (2-5 days)

**Approval Criteria:**
- Customer complaint verified
- Provider issue documented
- Amount reasonable
- Within refund window (typically 30 days)

### Revenue Tracking

**Daily Revenue Report**
```
Admin → Reports → Daily Revenue
```

**Columns:**
- Date
- Total Transactions
- Total Amount
- Commission Earned
- Processing Fees
- Net Revenue

**What to Track:**
- Week-over-week growth (target: 5-10%)
- Vendor profitability
- Commission optimization

---

## System Health

### Health Check Dashboard

**Quick Health Check**
```
Admin → Health → Quick Check
```

Should show all "healthy":
- API: ✅ Responsive
- Database: ✅ Connected
- Cache: ✅ Available
- Storage: ✅ Available

### Deep Health Check

**Detailed Diagnostics**
```
Admin → Health → Deep Diagnostics
```

**Sections:**

**1. Database Health**
```
Status: Connected ✅
Response time: 15ms
Disk usage: 45%
Connection pool: 12/20
Backup status: Current ✅
```

**2. Cache Health**
```
Status: Available ✅
Hit rate: 78% (good)
Memory usage: 125MB/500MB
TTL: 60 seconds
```

**3. Storage Health**
```
Free space: 5.2GB
Used space: 4.8GB
Disk usage: 48%
Alert threshold: 80%
```

**4. Service Dependencies**
```
Flutterwave API: ✅ Connected
Email Service: ✅ Available
Routing Service: ✅ Available (if configured)
```

### SLA Metrics

**View SLA Status**
```
Admin → Compliance → SLA Metrics
```

**Key Metrics:**

**1. Uptime Percentage**
```
Target: 99.95%
Current: 99.97% ✅
Last 30 days: 99.93% ✅
```

**2. Response Times**
```
P50 (Median): 145ms
P95: 245ms (good, target: < 500ms)
P99: 512ms (good, target: < 2000ms)
```

**3. Error Rate**
```
Current: 0.05% ✅
Target: < 0.1%
```

**4. Violations This Month**
```
SLA Violations: 0 ✅
Near-violations: 0 ✅
```

---

## Security & Compliance

### Security Monitoring

**Security Dashboard**
```
Admin → Security → Monitoring
```

**Watch For:**

**1. Failed Login Attempts**
```
Normal: 5-10 per day
Warning: > 50 per day
Critical: > 200 per day (might indicate attack)
```

**2. Rate Limit Violations**
```
Normal: 0-5 per hour
Warning: > 20 per hour
```

**3. IP Blacklist**
```
View blocked IPs
See reasons for blocking
```

**Action:** If suspicious activity detected:
```
Admin → Security → Block IP
- Enter IP address
- Select reason (suspicious, attack, spam)
- Confirm block
```

### User Compliance

**Permissions by Role**

| Feature | Customer | Provider | Vendor | Admin |
|---------|----------|----------|--------|-------|
| View Bookings | Own only | Own only | All | All |
| Create Booking | ✅ | ✅ | ✅ | ✅ |
| Manage Vendors | ❌ | ❌ | ✅ | ✅ |
| Process Payments | ✅ | ✅ | ✅ | ✅ |
| View Reports | ❌ | Own only | ✅ | ✅ |
| Admin Panel | ❌ | ❌ | Limited | Full |

### Data Retention Policy

**Configure Retention**
```
Admin → Settings → Data Retention
```

**Current Policy:**
- **User data:** Retained indefinitely (GDPR compliance)
- **Booking history:** 7 years (tax compliance)
- **Payment records:** 7 years (financial compliance)
- **Logs:** 90 days (operational, then archived)
- **Error logs:** 30 days (debugging)
- **Backup history:** 7 days (recovery window)

---

## Troubleshooting

### Issue: High Error Rate

**Symptoms:**
- Error rate > 1%
- Alert triggered
- Users reporting issues

**Investigation Steps:**

**1. Check Logs**
```
Admin → Logs → Filter:
- Level: ERROR
- Last 1 hour
- Component: app
```

**2. Identify Pattern**
- Which endpoint failing?
- Which user affected?
- When did it start?

**3. Check System Health**
```
Admin → Health → Deep Check
```

**4. Resolution**

| Problem | Solution |
|---------|----------|
| Database connection timeout | Check DB health, restart if needed |
| Memory issues | Check memory usage, restart service |
| Rate limiting triggered | Temporary, should resolve itself |
| Payment service error | Check Flutterwave status |
| Email service error | Check email configuration |

### Issue: Slow Response Times

**Symptoms:**
- Response time > 500ms
- P95 increasing
- Users complaining of slowness

**Investigation Steps:**

**1. Check Database**
```
Admin → Health → Database
- Check response time
- Check query performance
- Check connection pool usage
```

**2. Check Load**
```
Admin → Monitoring → Real-time Metrics
- Request rate high?
- Queue depth high?
```

**3. Resolution**

**Option 1: Scale Up (if CPU/memory high)**
```
Admin → Scaling → Create New Policy
- Metric: cpu
- Threshold: 70%
- Action: Add 2 instances
```

**Option 2: Database Optimization (if DB slow)**
```
Admin → Database → Optimize
- Rebuild indexes
- Analyze query plans
- Clear cache
```

**Option 3: Cache Optimization**
```
Admin → Cache → Settings
- Increase TTL (but monitor freshness)
- Clear stale entries
```

### Issue: Disk Space Low

**Symptoms:**
- Storage > 80%
- Alert "Low Disk Space"
- Potential service disruption

**Investigation:**

```
Admin → Storage → Usage
```

**What's Using Space:**
- Backup files
- Log files
- User uploads
- Database

**Resolution:**

**1. Archive Old Logs**
```
Admin → Logs → Archive
- Select date range (older than 30 days)
- Click Archive
```

**2. Delete Old Backups**
```
Admin → Backups → Management
- Keep at least 3 recent backups
- Delete backups older than 7 days
- Free up space
```

**3. Optimize Database**
```
Admin → Database → Maintenance
- VACUUM database
- Rebuild indexes
- Analyze tables
```

### Issue: Database Connection Errors

**Symptoms:**
- API returns 503 Service Unavailable
- Connection pool exhausted
- Users can't access platform

**Investigation:**

**1. Check Database Connection**
```
curl https://your-app/admin/health/dependencies
```

Expected: `"database": "healthy"`

**2. Check Pool Usage**
```
Admin → Database → Connection Pool
- Current: X / 20
- If X = 20: pool exhausted
```

**3. Resolution**

**Option 1: Restart Service**
```
Admin → Service → Restart
- Service will restart
- Connections reset
- Usually resolves hanging connections
```

**Option 2: Increase Pool Size**
```
Admin → Database → Settings
- Max connections: 20 → 30
- Requires service restart
```

**Option 3: Investigate Long Queries**
```
Admin → Database → Slow Queries
- Find queries taking > 5 seconds
- Optimize queries
- Add indexes if needed
```

---

## Quick Command Reference

### Health Checks
```bash
# Quick health
curl https://your-app/health

# Deep health
curl https://your-app/admin/health/deep \
  -H "Authorization: Bearer YOUR_TOKEN"

# Dependencies
curl https://your-app/admin/health/dependencies
```

### Backup Operations
```bash
# Create backup
curl -X POST https://your-app/admin/backup/create \
  -H "Authorization: Bearer YOUR_TOKEN"

# List backups
curl https://your-app/admin/backup/list

# Restore backup
curl -X POST https://your-app/admin/backup/restore \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"backup_id": "backup-20260701-120000"}'
```

### Logs
```bash
# View errors
curl "https://your-app/admin/logs?level=error&limit=50"

# Get analytics
curl https://your-app/admin/logs/analytics

# Cleanup
curl -X POST https://your-app/admin/logs/cleanup
```

### Alerts
```bash
# Get active alerts
curl https://your-app/admin/alerts

# Create alert rule
curl -X POST https://your-app/admin/alerts/rules \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{...}'
```

---

## Support & Escalation

### Common Escalation Paths

**Issue: Performance Degradation**
1. Check health dashboard
2. Review error logs
3. Contact: dev@smarthaul.ng

**Issue: Data Integrity**
1. Run backup
2. Check database
3. Contact: devops@smarthaul.ng

**Issue: Security Concern**
1. Check security events
2. Block suspicious IPs
3. Contact: security@smarthaul.ng

**Issue: User Complaint**
1. Review booking details
2. Check conversation/messages
3. Process refund if appropriate
4. Contact: support@smarthaul.ng

### Emergency Contacts

| Scenario | Contact | Number |
|----------|---------|--------|
| System Down | On-call DevOps | +234-XXX-XXX |
| Security Breach | Security Team | security@smarthaul.ng |
| Data Loss | Database Admin | devops@smarthaul.ng |
| Payment Issue | Payment Lead | payments@smarthaul.ng |

---

## Best Practices

### Daily
- ✅ Check dashboard every 2 hours
- ✅ Review error logs hourly
- ✅ Monitor active alerts
- ✅ Verify backup completion

### Weekly
- ✅ Review performance metrics
- ✅ Analyze user growth trends
- ✅ Check vendor/provider ratings
- ✅ Review payment success rate

### Monthly
- ✅ Run DR test
- ✅ Optimize database
- ✅ Review and adjust alert thresholds
- ✅ Cleanup old logs
- ✅ Capacity planning

### Quarterly
- ✅ Security audit
- ✅ Performance audit
- ✅ Compliance review
- ✅ Update documentation
- ✅ Plan infrastructure upgrades

---

## Conclusion

You now have all the tools and knowledge to manage SmartHaul effectively. The platform is designed to be self-healing with automated monitoring and alerts. Your role is to:

1. **Monitor** - Watch the dashboards
2. **Respond** - Act on alerts
3. **Optimize** - Improve based on metrics
4. **Escalate** - Know when to call for help

For detailed information on any topic, refer to:
- API Documentation: API_DOCUMENTATION.md
- Deployment Guide: README_DEPLOY.md
- Runbooks: README_DEPLOY.md (Runbooks section)

Good luck managing SmartHaul! 🚀

