# SmartHaul Integration Guide

Practical examples and best practices for integrating SmartHaul API into applications

---

## Getting Started

### Prerequisites
- Active SmartHaul account or local development instance
- API credentials (email/password or API token)
- Python 3.8+ or Node.js 14+ (depending on SDK)

### Environment Setup

#### Python
```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install SDK
pip install smarthaul-sdk

# Create .env file
cat > .env << EOF
SMARTHAUL_BASE_URL=https://your-app.onrender.com
SMARTHAUL_EMAIL=admin@example.com
SMARTHAUL_PASSWORD=your_password
EOF
```

#### JavaScript/Node.js
```bash
# Initialize project
npm init -y

# Install SDK
npm install @smarthaul/sdk dotenv

# Create .env file
cat > .env << EOF
SMARTHAUL_BASE_URL=https://your-app.onrender.com
SMARTHAUL_EMAIL=admin@example.com
SMARTHAUL_PASSWORD=your_password
EOF
```

---

## Scenario 1: Customer Booking a Ride

### Python Implementation
```python
import os
from dotenv import load_dotenv
from smarthaul import SmartHaul

load_dotenv()

# Initialize client
client = SmartHaul(base_url=os.getenv("SMARTHAUL_BASE_URL"))

# Step 1: Login as customer
auth = client.auth.login(
    email="customer@example.com",
    password="password123"
)
print(f"Logged in as customer. Token: {auth.access_token}")

# Step 2: Search available vendors
vendors = client.vendors.list(limit=5)
print(f"Available vendors: {len(vendors.items)}")

for vendor in vendors.items:
    print(f"  - {vendor.name}: {vendor.rating}/5")

# Step 3: Check providers
providers = client.providers.list(available=True)
print(f"Available providers: {len(providers.items)}")

# Step 4: Create booking
booking = client.bookings.create(
    customer_id=10,
    vendor_id=vendors.items[0].id,
    pickup="Lagos Island",
    destination="Victoria Island",
    item_description="Fragile electronics",
    weight_kg=15,
    estimated_distance_km=12
)
print(f"Booking created: {booking.id}")
print(f"Booking token for tracking: {booking.booking_token}")
print(f"Status: {booking.status}")

# Step 5: Initiate payment
payment = client.payments.initiate(
    booking_id=booking.id,
    amount=5000.00,
    currency="NGN",
    payment_method="card",
    return_url="https://myapp.com/bookings/success"
)
print(f"Payment URL: {payment.payment_url}")

# Step 6: Track booking (after driver accepts)
import time
time.sleep(2)  # Wait for driver to accept

tracking = client.tracking.get_by_booking(booking.id)
print(f"Driver location: {tracking.current_location}")
```

### JavaScript Implementation
```javascript
import SmartHaul from '@smarthaul/sdk';
import dotenv from 'dotenv';

dotenv.config();

const client = new SmartHaul({
  baseUrl: process.env.SMARTHAUL_BASE_URL
});

async function bookRide() {
  try {
    // Step 1: Login
    const auth = await client.auth.login({
      email: 'customer@example.com',
      password: 'password123'
    });
    console.log('Logged in successfully');

    // Step 2: Search vendors
    const vendors = await client.vendors.list({ limit: 5 });
    console.log(`Found ${vendors.total} vendors`);

    // Step 3: Create booking
    const booking = await client.bookings.create({
      customerId: 10,
      vendorId: vendors.items[0].id,
      pickup: 'Lagos Island',
      destination: 'Victoria Island',
      itemDescription: 'Fragile electronics',
      weightKg: 15
    });
    console.log(`Booking created: ${booking.id}`);

    // Step 4: Initiate payment
    const payment = await client.payments.initiate({
      bookingId: booking.id,
      amount: 5000.00,
      currency: 'NGN',
      paymentMethod: 'card',
      returnUrl: 'https://myapp.com/bookings/success'
    });
    
    console.log(`Redirecting to payment: ${payment.paymentUrl}`);
    window.location.href = payment.paymentUrl;

  } catch (error) {
    console.error('Booking failed:', error.message);
  }
}

bookRide();
```

---

## Scenario 2: Real-time Tracking Dashboard

### Python Implementation
```python
from smarthaul import SmartHaul
import json
import time
from datetime import datetime

client = SmartHaul(base_url="https://your-app.onrender.com", api_key="token")

def monitor_booking(booking_id):
    """Monitor booking status and location in real-time"""
    
    print(f"Monitoring booking {booking_id}...")
    
    while True:
        try:
            # Get booking details
            booking = client.bookings.get(booking_id)
            
            # Get tracking info
            tracking = client.tracking.get_by_booking(booking_id)
            
            # Display dashboard
            print(f"\n{'='*60}")
            print(f"Booking Status: {booking.status}")
            print(f"Driver: {tracking.provider_phone}")
            print(f"Location: {tracking.current_location.latitude}, {tracking.current_location.longitude}")
            print(f"ETA: {tracking.estimated_arrival}")
            print(f"{'='*60}")
            
            # Check if delivery is complete
            if booking.status == "completed":
                print("Delivery completed!")
                break
            
            # Poll every 10 seconds
            time.sleep(10)
            
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)

# Usage
monitor_booking(150)
```

### JavaScript Implementation (React)
```javascript
import { useEffect, useState } from 'react';
import SmartHaul from '@smarthaul/sdk';

function TrackingDashboard({ bookingId }) {
  const [tracking, setTracking] = useState(null);
  const [booking, setBooking] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const client = new SmartHaul({
      baseUrl: 'https://your-app.onrender.com',
      apiKey: localStorage.getItem('token')
    });

    // Poll for updates every 5 seconds
    const interval = setInterval(async () => {
      try {
        const [bookingData, trackingData] = await Promise.all([
          client.bookings.get(bookingId),
          client.tracking.getByBooking(bookingId)
        ]);

        setBooking(bookingData);
        setTracking(trackingData);
        setLoading(false);

        // Stop polling if completed
        if (bookingData.status === 'completed') {
          clearInterval(interval);
        }
      } catch (error) {
        console.error('Tracking error:', error);
      }
    }, 5000);

    return () => clearInterval(interval);
  }, [bookingId]);

  if (loading) return <div>Loading tracking data...</div>;

  return (
    <div className="tracking-dashboard">
      <h2>Booking #{bookingId}</h2>
      <p>Status: {booking?.status}</p>
      
      <div className="location-info">
        <p>Driver: {tracking?.providerPhone}</p>
        <p>
          Location: {tracking?.currentLocation.latitude}, 
          {tracking?.currentLocation.longitude}
        </p>
        <p>ETA: {tracking?.estimatedArrival}</p>
      </div>

      <div id="map" style={{ height: '400px', width: '100%' }}>
        {/* Add map library here (Google Maps, Leaflet, etc.) */}
      </div>
    </div>
  );
}

export default TrackingDashboard;
```

---

## Scenario 3: Vendor Dashboard with Analytics

### Python Implementation
```python
from smarthaul import SmartHaul
from datetime import datetime, timedelta
import statistics

client = SmartHaul(base_url="https://your-app.onrender.com", api_key="admin_token")

def generate_vendor_analytics(vendor_id):
    """Generate comprehensive vendor analytics"""
    
    # Get all bookings for vendor
    bookings = client.bookings.list(limit=100)
    vendor_bookings = [b for b in bookings.items if b.vendor_id == vendor_id]
    
    if not vendor_bookings:
        print("No bookings found for this vendor")
        return
    
    # Calculate metrics
    total_bookings = len(vendor_bookings)
    completed = len([b for b in vendor_bookings if b.status == "completed"])
    cancelled = len([b for b in vendor_bookings if b.status == "cancelled"])
    
    total_revenue = sum(b.amount for b in vendor_bookings if b.status == "completed")
    
    # Average rating (would need to get from bookings with ratings)
    bookings_with_ratings = [b for b in vendor_bookings if hasattr(b, 'rating') and b.rating]
    avg_rating = statistics.mean([b.rating for b in bookings_with_ratings]) if bookings_with_ratings else 0
    
    # Print analytics
    print(f"\n{'='*60}")
    print(f"VENDOR ANALYTICS - Vendor {vendor_id}")
    print(f"{'='*60}")
    print(f"Total Bookings: {total_bookings}")
    print(f"Completed: {completed} ({100*completed/total_bookings:.1f}%)")
    print(f"Cancelled: {cancelled} ({100*cancelled/total_bookings:.1f}%)")
    print(f"Total Revenue: ₦{total_revenue:,.2f}")
    print(f"Average Rating: {avg_rating:.1f}/5")
    print(f"Completion Rate: {100*completed/total_bookings:.1f}%")
    print(f"{'='*60}\n")
    
    return {
        'total_bookings': total_bookings,
        'completed': completed,
        'cancelled': cancelled,
        'revenue': total_revenue,
        'rating': avg_rating
    }

# Usage
analytics = generate_vendor_analytics(3)
```

### JavaScript Implementation
```javascript
import SmartHaul from '@smarthaul/sdk';

const client = new SmartHaul({
  baseUrl: 'https://your-app.onrender.com',
  apiKey: adminToken
});

async function getVendorDashboard(vendorId) {
  try {
    // Fetch bookings
    const bookingsResponse = await client.bookings.list({ limit: 100 });
    const vendorBookings = bookingsResponse.items.filter(
      b => b.vendorId === vendorId
    );

    // Calculate metrics
    const total = vendorBookings.length;
    const completed = vendorBookings.filter(b => b.status === 'completed').length;
    const cancelled = vendorBookings.filter(b => b.status === 'cancelled').length;
    const revenue = vendorBookings
      .filter(b => b.status === 'completed')
      .reduce((sum, b) => sum + b.amount, 0);

    const analytics = {
      totalBookings: total,
      completed: completed,
      cancelled: cancelled,
      revenue: revenue,
      completionRate: (100 * completed / total).toFixed(1)
    };

    console.log('Vendor Analytics:', analytics);
    return analytics;

  } catch (error) {
    console.error('Failed to fetch analytics:', error);
  }
}

// Usage
getVendorDashboard(3);
```

---

## Scenario 4: Admin Health Monitoring

### Python Implementation
```python
from smarthaul import SmartHaul
import json
from datetime import datetime

client = SmartHaul(base_url="https://your-app.onrender.com", api_key="admin_token")

def health_check_routine():
    """Perform comprehensive health check"""
    
    print(f"Health Check at {datetime.now()}")
    print("="*60)
    
    try:
        # Quick health check
        health = client.admin.health()
        print(f"✓ API Status: {health.status}")
        
        # Deep health check
        deep_health = client.admin.health_deep()
        print(f"✓ Database: {deep_health.database.status} ({deep_health.database.response_time_ms}ms)")
        print(f"✓ Cache: {deep_health.cache.status} ({deep_health.cache.response_time_ms}ms)")
        
        # Get SLA metrics
        sla = client.admin.sla_metrics()
        print(f"✓ Uptime: {sla.uptime_percentage}%")
        print(f"✓ Response Time P95: {sla.response_time_p95}ms")
        
        # Get alerts
        alerts = client.admin.get_alerts()
        if alerts.items:
            print(f"⚠ Active Alerts: {len(alerts.items)}")
            for alert in alerts.items:
                print(f"   - [{alert.severity}] {alert.message}")
        else:
            print(f"✓ No Active Alerts")
        
        # Get logs (errors only)
        error_logs = client.admin.get_logs(level="error", limit=5)
        if error_logs.items:
            print(f"✗ Recent Errors: {len(error_logs.items)}")
            for log in error_logs.items:
                print(f"   - {log.message}")
        
        print("="*60)
        return True
        
    except Exception as e:
        print(f"✗ Health Check Failed: {e}")
        return False

# Run health check
health_check_routine()
```

### JavaScript Implementation
```javascript
import SmartHaul from '@smarthaul/sdk';

const client = new SmartHaul({
  baseUrl: 'https://your-app.onrender.com',
  apiKey: adminToken
});

async function healthCheckRoutine() {
  const timestamp = new Date().toISOString();
  console.log(`Health Check at ${timestamp}`);
  console.log('='.repeat(60));

  try {
    // Quick health check
    const health = await client.admin.health();
    console.log(`✓ API Status: ${health.status}`);

    // Deep health check
    const deepHealth = await client.admin.healthDeep();
    console.log(`✓ Database: ${deepHealth.database.status} (${deepHealth.database.responseTimeMs}ms)`);
    console.log(`✓ Cache: ${deepHealth.cache.status} (${deepHealth.cache.responseTimeMs}ms)`);

    // Get SLA metrics
    const sla = await client.admin.slaMetrics();
    console.log(`✓ Uptime: ${sla.uptimePercentage}%`);
    console.log(`✓ Response Time P95: ${sla.responseTimeP95}ms`);

    // Get active alerts
    const alerts = await client.admin.getAlerts();
    if (alerts.items.length > 0) {
      console.log(`⚠ Active Alerts: ${alerts.items.length}`);
      alerts.items.forEach(alert => {
        console.log(`   - [${alert.severity}] ${alert.message}`);
      });
    } else {
      console.log('✓ No Active Alerts');
    }

    // Get recent errors
    const logs = await client.admin.getLogs({ level: 'error', limit: 5 });
    if (logs.items.length > 0) {
      console.log(`✗ Recent Errors: ${logs.items.length}`);
      logs.items.forEach(log => {
        console.log(`   - ${log.message}`);
      });
    }

    console.log('='.repeat(60));
    return true;

  } catch (error) {
    console.error(`✗ Health Check Failed: ${error.message}`);
    return false;
  }
}

// Run health check
healthCheckRoutine();

// Schedule periodic health checks every 5 minutes
setInterval(healthCheckRoutine, 5 * 60 * 1000);
```

---

## Scenario 5: Message Exchange Between Users

### Python Implementation
```python
from smarthaul import SmartHaul

client = SmartHaul(base_url="https://your-app.onrender.com", api_key="token")

def message_conversation(booking_id):
    """Manage message exchange for a booking"""
    
    print(f"Messages for Booking {booking_id}")
    print("="*60)
    
    # Get existing messages
    messages = client.messages.list(booking_id=booking_id, limit=20)
    
    print(f"Total messages: {len(messages.items)}")
    
    for msg in messages.items:
        print(f"\n{msg.sender_name} ({msg.timestamp}):")
        print(f"  {msg.message}")
    
    # Send new message
    print("\nSending message...")
    new_msg = client.messages.send(
        booking_id=booking_id,
        recipient_id=5,
        message="I will be there in 10 minutes"
    )
    
    print(f"Message sent: {new_msg.message_id}")

# Usage
message_conversation(150)
```

### JavaScript Implementation
```javascript
import SmartHaul from '@smarthaul/sdk';

const client = new SmartHaul({
  baseUrl: 'https://your-app.onrender.com',
  apiKey: token
});

async function messageConversation(bookingId) {
  try {
    // Get existing messages
    const response = await client.messages.list({ 
      bookingId: bookingId, 
      limit: 20 
    });

    console.log(`Total messages: ${response.items.length}`);

    response.items.forEach(msg => {
      console.log(`\n${msg.senderName} (${msg.timestamp}):`);
      console.log(`  ${msg.message}`);
    });

    // Send new message
    const newMessage = await client.messages.send({
      bookingId: bookingId,
      recipientId: 5,
      message: 'I will be there in 10 minutes'
    });

    console.log(`Message sent: ${newMessage.messageId}`);

    // Subscribe to new messages
    client.messages.onNewMessage(bookingId, (message) => {
      console.log(`\nNew message from ${message.senderName}:`);
      console.log(message.message);
    });

  } catch (error) {
    console.error('Message error:', error);
  }
}

messageConversation(150);
```

---

## Best Practices

### 1. Error Handling
Always wrap API calls in try-catch blocks and handle specific error types:

```python
try:
    booking = client.bookings.create(...)
except ValidationError as e:
    # Handle invalid input
    print(f"Invalid input: {e.details}")
except RateLimitError:
    # Handle rate limiting with backoff
    time.sleep(60)
except SmartHaulError as e:
    # Handle other errors
    print(f"Error: {e.message}")
```

### 2. Token Management
Store and refresh tokens securely:

```python
# Never hardcode tokens
import os
token = os.getenv('SMARTHAUL_API_KEY')

# Refresh expired tokens
if client.is_token_expired():
    new_token = client.auth.refresh_token()
    os.environ['SMARTHAUL_API_KEY'] = new_token
```

### 3. Pagination
Always handle pagination for large result sets:

```python
offset = 0
limit = 20
all_bookings = []

while True:
    bookings = client.bookings.list(limit=limit, offset=offset)
    all_bookings.extend(bookings.items)
    
    if len(bookings.items) < limit:
        break
    
    offset += limit
```

### 4. Caching
Cache frequently accessed data to reduce API calls:

```python
from functools import lru_cache
import time

@lru_cache(maxsize=100)
def get_provider(provider_id):
    return client.providers.get(provider_id)

# Cache expires after 1 hour
class CachedClient:
    def __init__(self):
        self.cache = {}
        self.cache_ttl = 3600
    
    def get_vendor(self, vendor_id):
        if vendor_id in self.cache:
            cached_data, timestamp = self.cache[vendor_id]
            if time.time() - timestamp < self.cache_ttl:
                return cached_data
        
        data = client.vendors.get(vendor_id)
        self.cache[vendor_id] = (data, time.time())
        return data
```

### 5. Logging
Implement comprehensive logging:

```python
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    booking = client.bookings.create(...)
    logger.info(f"Booking created: {booking.id}")
except Exception as e:
    logger.error(f"Failed to create booking: {str(e)}")
```

### 6. Rate Limiting Handling
Respect rate limits and implement exponential backoff:

```python
import time
from random import random

def retry_with_backoff(func, max_attempts=3):
    for attempt in range(max_attempts):
        try:
            return func()
        except RateLimitError:
            wait_time = (2 ** attempt) + random()
            logger.warning(f"Rate limited. Waiting {wait_time:.2f}s...")
            time.sleep(wait_time)
    raise Exception("Max retries exceeded")

# Usage
booking = retry_with_backoff(
    lambda: client.bookings.create(...)
)
```

---

## Testing Integration

### Python Unit Test
```python
import unittest
from unittest.mock import Mock, patch
from smarthaul import SmartHaul

class TestSmartHaulIntegration(unittest.TestCase):
    def setUp(self):
        self.client = SmartHaul(
            base_url="https://your-app.onrender.com",
            api_key="test_token"
        )
    
    @patch('smarthaul.requests.post')
    def test_create_booking(self, mock_post):
        mock_post.return_value.json.return_value = {
            'id': 150,
            'status': 'pending'
        }
        
        booking = self.client.bookings.create(
            customer_id=10,
            vendor_id=3,
            pickup='Lagos',
            destination='Ibadan'
        )
        
        self.assertEqual(booking.id, 150)
        self.assertEqual(booking.status, 'pending')
```

### JavaScript Test
```javascript
import SmartHaul from '@smarthaul/sdk';

describe('SmartHaul Integration', () => {
  let client;

  beforeEach(() => {
    client = new SmartHaul({
      baseUrl: 'https://your-app.onrender.com',
      apiKey: 'test_token'
    });
  });

  test('should create booking', async () => {
    const booking = await client.bookings.create({
      customerId: 10,
      vendorId: 3,
      pickup: 'Lagos',
      destination: 'Ibadan'
    });

    expect(booking.id).toBe(150);
    expect(booking.status).toBe('pending');
  });
});
```

---

## Troubleshooting

### Common Issues

| Issue | Solution |
|-------|----------|
| 401 Unauthorized | Token expired or invalid. Re-login and get new token. |
| 429 Rate Limited | Wait and retry with exponential backoff. |
| 500 Server Error | Check health endpoint, server may be down. |
| Connection Timeout | Increase timeout, check network connectivity. |
| Invalid JSON Response | API may have changed. Check latest docs. |

---

## Support & Resources

- Documentation: https://docs.smarthaul.ng
- API Status: https://status.smarthaul.ng
- GitHub Issues: https://github.com/smarthaul/
- Email: dev@smarthaul.ng

