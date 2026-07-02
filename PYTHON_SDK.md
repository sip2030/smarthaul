# SmartHaul Python SDK

Production-ready Python client library for SmartHaul API (v1.0.0)

## Installation

```bash
pip install smarthaul-sdk
# or from source:
pip install git+https://github.com/smarthaul/sdk-python.git
```

## Quick Start

```python
from smarthaul import SmartHaul

# Initialize client
client = SmartHaul(
    base_url="https://your-app.onrender.com",
    api_key="your_jwt_token"
)

# Create booking
booking = client.bookings.create(
    customer_id=10,
    vendor_id=3,
    pickup="Lagos Island",
    destination="Victoria Island",
    item_description="Electronics",
    weight_kg=25
)

print(f"Booking created: {booking.id}")
print(f"Status: {booking.status}")
```

---

## Authentication

### Login
```python
from smarthaul import SmartHaul

client = SmartHaul(base_url="https://your-app.onrender.com")

# Login and get token
token = client.auth.login(
    email="user@example.com",
    password="password123"
)

# Token is automatically stored and used for subsequent requests
print(f"Token: {token.access_token}")
print(f"Expires in: {token.expires_in} seconds")
```

### Register
```python
# Register new user
user = client.auth.register(
    email="newuser@example.com",
    password="securepass123",
    full_name="John Doe",
    phone="+234801234567",
    role="customer"  # or "provider", "vendor", "admin"
)

print(f"User registered: {user.user_id}")
```

### Using API Key
```python
# Direct initialization with token
client = SmartHaul(
    base_url="https://your-app.onrender.com",
    api_key="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
)
```

---

## Booking Management

### Create Booking
```python
booking = client.bookings.create(
    customer_id=10,
    vendor_id=3,
    pickup="Lagos Island",
    destination="Victoria Island",
    scheduled_time="2026-07-02T14:00:00Z",
    item_description="Electronic equipment",
    weight_kg=25,
    estimated_distance_km=15
)

print(f"Booking ID: {booking.id}")
print(f"Status: {booking.status}")
print(f"Tracking Token: {booking.booking_token}")
```

### List Bookings
```python
# Get all bookings
bookings = client.bookings.list()

# Filter by status
pending_bookings = client.bookings.list(status="pending", limit=10)

# Paginate through results
for i in range(0, 100, 20):
    bookings = client.bookings.list(limit=20, offset=i)
    for booking in bookings.items:
        print(f"{booking.id}: {booking.status}")
```

### Get Booking Details
```python
booking = client.bookings.get(booking_id=150)

print(f"Customer: {booking.customer_id}")
print(f"Provider: {booking.provider_id}")
print(f"Status: {booking.status}")
print(f"Amount: {booking.amount} NGN")
print(f"Tracking: {booking.tracking_url}")
```

### Update Booking
```python
booking = client.bookings.update(
    booking_id=150,
    status="accepted",
    notes="Driver confirmed pickup"
)

print(f"Updated status: {booking.status}")
```

### Cancel Booking
```python
result = client.bookings.cancel(
    booking_id=150,
    reason="Changed my mind",
    refund_method="wallet"
)

print(f"Refund amount: {result.refund_amount}")
print(f"Refund status: {result.refund_status}")
```

---

## Provider Management

### Register as Provider
```python
provider = client.providers.register(
    user_id=20,
    business_name="Swift Transport Services",
    vehicle_type="truck",
    vehicle_registration="LG-123-ABC",
    license_number="DL-2023-456789",
    insurance_provider="AAA Insurance",
    insurance_expiry="2027-12-31"
)

print(f"Provider ID: {provider.provider_id}")
print(f"Status: {provider.status}")
```

### List Providers
```python
# Get available providers
providers = client.providers.list(available=True, category="truck")

for provider in providers.items:
    print(f"{provider.name}: {provider.rating}/5 ({provider.total_bookings} bookings)")
```

### Get Provider Details
```python
provider = client.providers.get(provider_id=5)

print(f"Name: {provider.name}")
print(f"Rating: {provider.rating}")
print(f"Total bookings: {provider.total_bookings}")
print(f"Response time: {provider.response_time_minutes} min")
```

---

## Vendor Management

### Register as Vendor
```python
vendor = client.vendors.register(
    user_id=30,
    business_name="Premium Logistics Ltd",
    category="haulage",
    service_area="Lagos, Ogun",
    contact_email="contact@premiumlogistics.com",
    phone="+234801234567",
    documents={
        "business_registration": "BRN-2023-789",
        "tax_certificate": "TIN-2023-456"
    }
)

print(f"Vendor ID: {vendor.vendor_id}")
print(f"Status: {vendor.status}")
```

### List Vendors
```python
vendors = client.vendors.list(limit=20)

for vendor in vendors.items:
    print(f"{vendor.name} ({vendor.category}): {vendor.rating}/5")
```

---

## Payment Processing

### List Payments
```python
payments = client.payments.list(status="completed", limit=20)

for payment in payments.items:
    print(f"Transaction {payment.id}: {payment.amount} {payment.currency}")
```

### Initiate Payment
```python
payment = client.payments.initiate(
    booking_id=150,
    amount=5000.00,
    currency="NGN",
    payment_method="card",
    return_url="https://your-app/bookings/150/success"
)

print(f"Payment URL: {payment.payment_url}")
print(f"Transaction ID: {payment.transaction_id}")
print(f"Expires in: {payment.expires_in} seconds")

# Direct user to payment URL for payment
```

### Verify Payment
```python
payment = client.payments.verify(payment_id="txn_abc123def456")

if payment.status == "completed":
    print(f"Payment verified! Amount: {payment.amount}")
else:
    print(f"Payment status: {payment.status}")
```

---

## Real-time Tracking

### Get Tracking Information
```python
# Using booking ID (requires authentication)
tracking = client.tracking.get_by_booking(booking_id=150)

print(f"Current location: {tracking.location.latitude}, {tracking.location.longitude}")
print(f"Estimated arrival: {tracking.estimated_arrival}")
print(f"Provider phone: {tracking.provider_phone}")

# Using public booking token (no auth required)
tracking = client.tracking.get_by_token("bk_xpq9k2v8z3m1n5")
```

### Update Location (Provider)
```python
result = client.tracking.update_location(
    booking_token="bk_xpq9k2v8z3m1n5",
    latitude=6.5010,
    longitude=3.5890,
    accuracy=12
)

print(f"Location updated: {result.status}")
```

---

## Messaging

### Get Messages
```python
messages = client.messages.list(booking_id=150, limit=50)

for message in messages.items:
    print(f"{message.sender_name}: {message.message}")
```

### Send Message
```python
message = client.messages.send(
    booking_id=150,
    recipient_id=5,
    message="What's your current location?"
)

print(f"Message sent: {message.message_id}")
```

---

## Admin Operations

### Health Checks
```python
# Quick health check
health = client.admin.health()
print(f"Status: {health.status}")

# Deep health check with dependencies
health = client.admin.health_deep()
print(f"Database: {health.database.status}")
print(f"Cache: {health.cache.status}")
print(f"Storage: {health.storage.status}")
```

### System Logs
```python
logs = client.admin.get_logs(
    component="app",
    level="error",
    limit=50
)

for log in logs.items:
    print(f"[{log.level}] {log.message}")
```

### Monitoring Dashboard
```python
dashboard = client.admin.monitoring_dashboard()

print(f"Active bookings: {dashboard.active_bookings}")
print(f"Daily revenue: {dashboard.daily_revenue}")
print(f"Uptime: {dashboard.uptime_percent}%")
print(f"Error rate: {dashboard.error_rate}%")
```

### Database Backups
```python
# Create backup
backup = client.admin.backup_create()
print(f"Backup created: {backup.backup_id}")

# List backups
backups = client.admin.backup_list()
for backup in backups.items:
    print(f"{backup.backup_id}: {backup.size_mb}MB")

# Restore from backup
result = client.admin.backup_restore(backup_id="backup-20260701-180000")
print(f"Restore status: {result.status}")
```

### SLA Metrics
```python
sla = client.admin.sla_metrics()

print(f"Uptime: {sla.uptime_percentage}%")
print(f"Response time (P95): {sla.response_time_p95}ms")
print(f"Response time (P99): {sla.response_time_p99}ms")
print(f"Error rate: {sla.error_rate}%")
```

### Alerts Management
```python
# Get active alerts
alerts = client.admin.get_alerts()
for alert in alerts.items:
    print(f"[{alert.severity}] {alert.message}")

# Create alert rule
rule = client.admin.create_alert_rule(
    name="High Error Rate",
    condition="error_rate > 1",
    threshold=0.01,
    alert_type="critical"
)

print(f"Rule created: {rule.rule_id}")
```

### Scaling Management
```python
# Get scaling policies
policies = client.admin.get_scaling_policies()

# Create scaling policy
policy = client.admin.create_scaling_policy(
    name="CPU Scale Policy",
    metric="cpu",
    threshold_up=80.0,
    threshold_down=30.0,
    scale_up_instances=2,
    cooldown_minutes=5
)

# Get scaling recommendations
recommendations = client.admin.get_capacity_plan()
print(f"Recommendations: {recommendations.recommendations}")

# Get scaling history
history = client.admin.get_scaling_history()
for event in history.events:
    print(f"Scaling event: {event.event_type}")
```

### Load Balancer Configuration
```python
# Get status
status = client.admin.get_load_balancer_status()
print(f"Algorithm: {status.algorithm}")
print(f"Healthy instances: {status.healthy_instances}")

# Update configuration
config = client.admin.update_load_balancer_config(
    algorithm="least_connections",
    health_check_interval_seconds=15,
    sticky_sessions=True
)

print(f"Updated: {config.updated_at}")
```

---

## Error Handling

```python
from smarthaul.exceptions import (
    SmartHaulError,
    AuthenticationError,
    ValidationError,
    NotFoundError,
    RateLimitError
)

try:
    booking = client.bookings.create(
        customer_id=10,
        vendor_id=3,
        pickup="Lagos",
        destination="Ibadan"
    )
except AuthenticationError:
    print("Please login first")
except ValidationError as e:
    print(f"Validation error: {e.details}")
except NotFoundError:
    print("Resource not found")
except RateLimitError:
    print("Rate limited - wait before retrying")
except SmartHaulError as e:
    print(f"Error: {e.message}")
```

---

## Advanced Usage

### Custom Request Headers
```python
client.set_headers({
    "X-Custom-Header": "value",
    "User-Agent": "MyApp/1.0"
})
```

### Request Timeout
```python
# Set timeout for all requests (in seconds)
client.set_timeout(30)
```

### Request Retry
```python
# Enable automatic retries
client.enable_retry(
    max_attempts=3,
    backoff_factor=0.5  # exponential backoff
)
```

### Logging
```python
import logging

# Enable debug logging
client.enable_debug_logging()

# Or use standard Python logging
logging.basicConfig(level=logging.DEBUG)
```

### Batch Operations
```python
# Create multiple bookings
bookings = client.bookings.batch_create([
    {
        "customer_id": 10,
        "vendor_id": 3,
        "pickup": "Lagos Island",
        "destination": "Victoria Island"
    },
    {
        "customer_id": 11,
        "vendor_id": 4,
        "pickup": "Lekki",
        "destination": "Ajah"
    }
])

for booking in bookings:
    print(f"Created: {booking.id}")
```

### Async/Await
```python
import asyncio

async def manage_bookings():
    # Initialize async client
    async_client = SmartHaul(
        base_url="https://your-app.onrender.com",
        api_key="token",
        async_mode=True
    )
    
    # Use async methods
    booking = await async_client.bookings.create(
        customer_id=10,
        vendor_id=3,
        pickup="Lagos Island",
        destination="Victoria Island"
    )
    
    return booking

# Run async code
booking = asyncio.run(manage_bookings())
```

---

## SDK Reference

### Available Resources

| Resource | Methods |
|----------|---------|
| `bookings` | `list()`, `create()`, `get()`, `update()`, `cancel()` |
| `providers` | `list()`, `register()`, `get()` |
| `vendors` | `list()`, `register()`, `get()` |
| `payments` | `list()`, `initiate()`, `verify()` |
| `tracking` | `get_by_booking()`, `get_by_token()`, `update_location()` |
| `messages` | `list()`, `send()` |
| `admin` | Various admin operations (see Admin Operations section) |
| `auth` | `login()`, `register()`, `logout()` |

---

## Support

- Documentation: https://docs.smarthaul.ng
- GitHub Issues: https://github.com/smarthaul/sdk-python/issues
- Email: dev@smarthaul.ng

---

## License

MIT License - See LICENSE file for details

