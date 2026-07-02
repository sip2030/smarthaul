# SmartHaul API Documentation

Complete API reference for SmartHaul platform (Production Ready - Phase 6)

## OpenAPI Specification

### Base URL
```
https://your-app.onrender.com
```

### Authentication
All protected endpoints require Bearer token authentication:
```
Authorization: Bearer YOUR_JWT_TOKEN
```

### API Version
Version: 1.0.0  
Last Updated: 2026-07-02  
Production Ready: ✅

---

## Authentication Endpoints

### POST /auth/login
Login and receive authentication token

**Request:**
```json
{
  "email": "user@example.com",
  "password": "password123"
}
```

**Response (200):**
```json
{
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "user_id": 1,
  "role": "customer",
  "expires_in": 86400
}
```

**Error Responses:**
- `401`: Invalid credentials
- `429`: Too many login attempts (brute force protection)

---

### POST /auth/logout
Logout and invalidate token

**Request:** No body

**Response (200):**
```json
{
  "message": "Logged out successfully"
}
```

---

### POST /auth/register
Register new user account

**Request:**
```json
{
  "email": "newuser@example.com",
  "password": "securepass123",
  "full_name": "John Doe",
  "phone": "+234801234567",
  "role": "customer"
}
```

**Response (201):**
```json
{
  "user_id": 42,
  "email": "newuser@example.com",
  "role": "customer",
  "message": "Registration successful"
}
```

**Error Responses:**
- `400`: Email already exists or invalid input
- `422`: Validation error

---

## Booking Management

### GET /bookings
Get list of bookings

**Query Parameters:**
- `status` (optional): `pending`, `accepted`, `in_transit`, `completed`, `cancelled`
- `limit` (optional, default: 20): Maximum results
- `offset` (optional, default: 0): Pagination offset

**Response (200):**
```json
{
  "bookings": [
    {
      "id": 1,
      "customer_id": 10,
      "provider_id": 5,
      "status": "in_transit",
      "pickup": "Lagos Island",
      "destination": "Victoria Island",
      "amount": 5000.00,
      "created_at": "2026-07-02T10:30:00Z",
      "updated_at": "2026-07-02T11:15:00Z"
    }
  ],
  "total": 42,
  "limit": 20,
  "offset": 0
}
```

**Requires:** Authentication

---

### POST /bookings
Create new booking

**Request:**
```json
{
  "customer_id": 10,
  "vendor_id": 3,
  "pickup": "Lagos Island",
  "destination": "Victoria Island",
  "scheduled_time": "2026-07-02T14:00:00Z",
  "item_description": "Electronic equipment",
  "weight_kg": 25,
  "estimated_distance_km": 15
}
```

**Response (201):**
```json
{
  "id": 150,
  "status": "pending",
  "booking_token": "bk_xpq9k2v8z3m1n5",
  "message": "Booking created successfully"
}
```

**Requires:** Authentication

---

### GET /bookings/{id}
Get booking details

**Response (200):**
```json
{
  "id": 150,
  "customer_id": 10,
  "provider_id": 5,
  "status": "in_transit",
  "pickup": "Lagos Island",
  "destination": "Victoria Island",
  "amount": 5000.00,
  "tracking_url": "https://your-app/tracking/bk_xpq9k2v8z3m1n5",
  "provider_phone": "+234809876543",
  "created_at": "2026-07-02T10:30:00Z"
}
```

**Error Responses:**
- `404`: Booking not found
- `403`: Unauthorized access

---

### PUT /bookings/{id}
Update booking

**Request:**
```json
{
  "status": "accepted",
  "notes": "Driver is on the way"
}
```

**Response (200):**
```json
{
  "id": 150,
  "status": "accepted",
  "updated_at": "2026-07-02T11:00:00Z"
}
```

---

### POST /bookings/{id}/cancel
Cancel booking

**Request:**
```json
{
  "reason": "Changed my mind",
  "refund_method": "wallet"
}
```

**Response (200):**
```json
{
  "id": 150,
  "status": "cancelled",
  "refund_amount": 5000.00,
  "refund_status": "processing"
}
```

**Error Responses:**
- `400`: Booking cannot be cancelled (already in transit)
- `404`: Booking not found

---

## Provider Management

### GET /providers
Get list of providers

**Query Parameters:**
- `category` (optional): `truck`, `bike`, `van`
- `available` (optional): `true`, `false`
- `limit` (optional): 20

**Response (200):**
```json
{
  "providers": [
    {
      "id": 5,
      "name": "John's Transport",
      "vehicle_type": "truck",
      "availability": true,
      "rating": 4.8,
      "total_bookings": 342,
      "response_time_minutes": 12,
      "created_at": "2026-01-15T08:30:00Z"
    }
  ],
  "total": 156
}
```

---

### POST /providers
Register as provider

**Request:**
```json
{
  "user_id": 20,
  "business_name": "Swift Transport Services",
  "vehicle_type": "truck",
  "vehicle_registration": "LG-123-ABC",
  "license_number": "DL-2023-456789",
  "insurance_provider": "AAA Insurance",
  "insurance_expiry": "2027-12-31"
}
```

**Response (201):**
```json
{
  "provider_id": 156,
  "status": "pending_verification",
  "message": "Provider application submitted"
}
```

---

### GET /providers/{id}
Get provider details

**Response (200):**
```json
{
  "id": 5,
  "name": "John's Transport",
  "vehicle_type": "truck",
  "rating": 4.8,
  "total_bookings": 342,
  "completed_bookings": 335,
  "response_time_minutes": 12,
  "service_area": "Lagos",
  "verified": true
}
```

---

## Vendor Management

### GET /vendors
Get vendor list

**Response (200):**
```json
{
  "vendors": [
    {
      "id": 3,
      "name": "Urban Logistics Hub",
      "category": "haulage",
      "location": "Lagos",
      "rating": 4.8,
      "total_orders": 1250,
      "verification_status": "verified",
      "contact_email": "info@urbanlogistics.com"
    }
  ],
  "total": 45
}
```

---

### POST /vendors
Register as vendor

**Request:**
```json
{
  "user_id": 30,
  "business_name": "Premium Logistics Ltd",
  "category": "haulage",
  "service_area": "Lagos, Ogun",
  "contact_email": "contact@premiumlogistics.com",
  "phone": "+234801234567",
  "documents": {
    "business_registration": "BRN-2023-789",
    "tax_certificate": "TIN-2023-456"
  }
}
```

**Response (201):**
```json
{
  "vendor_id": 46,
  "status": "pending_review",
  "message": "Vendor registration submitted for review"
}
```

---

## Payment Endpoints

### GET /payments
Get payment history

**Query Parameters:**
- `status` (optional): `pending`, `completed`, `failed`
- `limit` (optional): 20

**Response (200):**
```json
{
  "payments": [
    {
      "id": 1,
      "booking_id": 150,
      "amount": 5000.00,
      "currency": "NGN",
      "status": "completed",
      "gateway": "flutterwave",
      "timestamp": "2026-07-02T11:30:00Z"
    }
  ],
  "total": 28
}
```

**Requires:** Authentication

---

### POST /payments/initiate
Initiate payment

**Request:**
```json
{
  "booking_id": 150,
  "amount": 5000.00,
  "currency": "NGN",
  "payment_method": "card",
  "return_url": "https://your-app/bookings/150/success"
}
```

**Response (200):**
```json
{
  "transaction_id": "txn_abc123def456",
  "payment_url": "https://checkout.flutterwave.com/v3/hosted/...",
  "expires_in": 3600
}
```

---

### POST /payments/{id}/verify
Verify payment status

**Response (200):**
```json
{
  "transaction_id": "txn_abc123def456",
  "status": "completed",
  "amount": 5000.00,
  "reference": "ref_123456",
  "verified_at": "2026-07-02T11:35:00Z"
}
```

---

## Tracking & Location

### GET /tracking/{booking_token}
Get real-time location tracking

**Response (200):**
```json
{
  "booking_id": 150,
  "booking_token": "bk_xpq9k2v8z3m1n5",
  "status": "in_transit",
  "current_location": {
    "latitude": 6.4969,
    "longitude": 3.5833,
    "timestamp": "2026-07-02T11:45:00Z",
    "accuracy_meters": 15
  },
  "estimated_arrival": "2026-07-02T12:15:00Z",
  "provider_phone": "+234809876543",
  "route_url": "https://maps.openrouteservice.org/..."
}
```

**No authentication required** (booking_token is one-time use)

---

### POST /tracking/{booking_token}/update-location
Submit location update (Provider endpoint)

**Request:**
```json
{
  "latitude": 6.5010,
  "longitude": 3.5890,
  "accuracy": 12
}
```

**Response (200):**
```json
{
  "status": "updated",
  "message": "Location updated successfully"
}
```

---

## Messaging & Communication

### GET /messages
Get messages for current user

**Query Parameters:**
- `booking_id` (optional): Filter by booking
- `limit` (optional): 50

**Response (200):**
```json
{
  "messages": [
    {
      "id": 1,
      "booking_id": 150,
      "sender_id": 10,
      "sender_name": "John Doe",
      "message": "I'll be there in 10 minutes",
      "timestamp": "2026-07-02T11:50:00Z",
      "moderation_status": "clear"
    }
  ],
  "total": 15
}
```

**Requires:** Authentication

---

### POST /messages
Send message

**Request:**
```json
{
  "booking_id": 150,
  "recipient_id": 5,
  "message": "What's your current location?"
}
```

**Response (201):**
```json
{
  "message_id": 16,
  "timestamp": "2026-07-02T11:51:00Z",
  "status": "sent"
}
```

---

## Admin Endpoints

### GET /admin/health
Quick health check

**Response (200):**
```json
{
  "status": "healthy",
  "timestamp": "2026-07-02T12:00:00Z",
  "uptime_seconds": 86400
}
```

**Requires:** Admin authentication

---

### GET /admin/health/deep
Deep health check with dependencies

**Response (200):**
```json
{
  "status": "healthy",
  "timestamp": "2026-07-02T12:00:00Z",
  "database": {
    "status": "healthy",
    "response_time_ms": 15
  },
  "cache": {
    "status": "healthy",
    "response_time_ms": 5
  },
  "storage": {
    "status": "healthy",
    "free_space_mb": 5240
  }
}
```

---

### GET /admin/logs
Get system logs

**Query Parameters:**
- `component` (optional): `app`, `database`, `cache`, `security`
- `level` (optional): `debug`, `info`, `warning`, `error`, `critical`
- `limit` (optional): 50
- `offset` (optional): 0

**Response (200):**
```json
{
  "logs": [
    {
      "id": 1,
      "component": "app",
      "level": "error",
      "message": "Database connection timeout",
      "context": {"retry_count": 3},
      "timestamp": "2026-07-02T11:55:00Z"
    }
  ],
  "total": 428
}
```

---

### GET /admin/monitoring/dashboard
Get centralized monitoring dashboard

**Response (200):**
```json
{
  "timestamp": "2026-07-02T12:00:00Z",
  "summary": {
    "total_users": 2450,
    "active_bookings": 142,
    "daily_revenue": 285000.00,
    "uptime_percent": 99.95
  },
  "metrics": {
    "request_rate": 250,
    "error_rate": 0.5,
    "avg_response_time_ms": 145,
    "active_connections": 85
  },
  "alerts": {
    "total": 3,
    "critical": 0,
    "warnings": 3
  }
}
```

---

### POST /admin/backup/create
Create database backup

**Response (200):**
```json
{
  "backup_id": "backup-20260702-120000",
  "status": "completed",
  "size_mb": 245,
  "timestamp": "2026-07-02T12:00:00Z"
}
```

---

### GET /admin/backup/list
List available backups

**Response (200):**
```json
{
  "backups": [
    {
      "backup_id": "backup-20260702-120000",
      "status": "completed",
      "size_mb": 245,
      "created_at": "2026-07-02T12:00:00Z",
      "location": "s3://backups/smarthaul/..."
    }
  ],
  "total": 14,
  "retention_days": 7
}
```

---

### POST /admin/backup/restore
Restore from backup

**Request:**
```json
{
  "backup_id": "backup-20260701-180000"
}
```

**Response (200):**
```json
{
  "status": "restore_started",
  "backup_id": "backup-20260701-180000",
  "estimated_duration_seconds": 120
}
```

---

### GET /admin/sla/metrics
Get SLA metrics

**Response (200):**
```json
{
  "uptime_percentage": 99.95,
  "response_time_p95": 245,
  "response_time_p99": 512,
  "error_rate": 0.05,
  "violations": 0,
  "measurement_period_days": 30
}
```

---

### GET /admin/alerts
Get active alerts

**Response (200):**
```json
{
  "alerts": [
    {
      "id": 1,
      "rule_name": "High Error Rate",
      "severity": "high",
      "message": "Error rate exceeded 1%",
      "triggered_at": "2026-07-02T11:55:00Z",
      "resolved": false
    }
  ],
  "total": 3
}
```

---

### POST /admin/alerts/rules
Create alert rule

**Request:**
```json
{
  "name": "Database Connection Pool",
  "condition": "connection_pool > 80",
  "threshold": 0.8,
  "alert_type": "warning"
}
```

**Response (201):**
```json
{
  "rule_id": "rule-12345",
  "name": "Database Connection Pool",
  "enabled": true
}
```

---

## Rate Limiting

All API endpoints are rate limited:

- **Global rate limit:** 300 requests/minute
- **Per-user rate limit:** 60 requests/minute
- **API-specific limits:** 100 requests/minute

**Rate limit headers in response:**
```
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 45
X-RateLimit-Reset: 1656777600
```

**Error response (429):**
```json
{
  "error": "Rate limit exceeded",
  "retry_after_seconds": 60
}
```

---

## Error Handling

### Standard Error Response Format
```json
{
  "error": "Descriptive error message",
  "error_code": "INVALID_REQUEST",
  "details": {
    "field": "email",
    "issue": "Invalid email format"
  },
  "timestamp": "2026-07-02T12:00:00Z"
}
```

### Common HTTP Status Codes

| Status | Meaning |
|--------|---------|
| 200 | Success |
| 201 | Created |
| 400 | Bad Request |
| 401 | Unauthorized |
| 403 | Forbidden |
| 404 | Not Found |
| 422 | Validation Error |
| 429 | Rate Limited |
| 500 | Server Error |
| 503 | Service Unavailable |

---

## WebSocket Endpoints (Real-time)

### Connect to real-time updates
```
wss://your-app.onrender.com/ws/bookings/{booking_id}?token=YOUR_JWT_TOKEN
```

**Messages received:**
```json
{
  "type": "location_update",
  "data": {
    "latitude": 6.5010,
    "longitude": 3.5890,
    "timestamp": "2026-07-02T12:05:00Z"
  }
}
```

**Message types:** `location_update`, `status_change`, `message_received`, `provider_arrival`

---

## Webhook Events (For external integrations)

Configure webhook URL in admin dashboard at `/admin/webhooks`

**Webhook events:**
- `booking.created`
- `booking.accepted`
- `booking.completed`
- `payment.completed`
- `dispute.created`
- `alert.triggered`

**Webhook payload:**
```json
{
  "event": "booking.completed",
  "timestamp": "2026-07-02T12:10:00Z",
  "data": {
    "booking_id": 150,
    "status": "completed",
    "amount": 5000.00
  }
}
```

---

## Pagination

List endpoints support pagination using `limit` and `offset` parameters:

```
GET /bookings?limit=20&offset=40
```

**Response includes:**
```json
{
  "items": [...],
  "total": 425,
  "limit": 20,
  "offset": 40,
  "has_more": true
}
```

---

## Data Models

### Booking
```json
{
  "id": 150,
  "customer_id": 10,
  "provider_id": 5,
  "vendor_id": 3,
  "status": "in_transit",
  "pickup": "Lagos Island",
  "destination": "Victoria Island",
  "amount": 5000.00,
  "distance_km": 15.5,
  "estimated_duration_minutes": 30,
  "created_at": "2026-07-02T10:30:00Z",
  "updated_at": "2026-07-02T11:45:00Z"
}
```

### User
```json
{
  "id": 10,
  "email": "user@example.com",
  "full_name": "John Doe",
  "phone": "+234801234567",
  "role": "customer",
  "avatar_url": "https://example.com/avatar.jpg",
  "created_at": "2026-01-15T08:30:00Z",
  "account_status": "active"
}
```

### Payment
```json
{
  "id": 1,
  "booking_id": 150,
  "amount": 5000.00,
  "currency": "NGN",
  "status": "completed",
  "gateway": "flutterwave",
  "reference": "ref_123456",
  "created_at": "2026-07-02T11:30:00Z"
}
```

---

## Support & Integration

For technical support, contact: `support@smarthaul.ng`

For integration assistance: `dev@smarthaul.ng`

API Status Page: `https://status.smarthaul.ng`

