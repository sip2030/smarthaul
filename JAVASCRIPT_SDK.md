# SmartHaul JavaScript SDK

Production-ready JavaScript client library for SmartHaul API (v1.0.0)

## Installation

### NPM
```bash
npm install @smarthaul/sdk
```

### Yarn
```bash
yarn add @smarthaul/sdk
```

### CDN
```html
<script src="https://cdn.smarthaul.ng/sdk/v1/smarthaul.min.js"></script>
```

---

## Quick Start

```javascript
import SmartHaul from '@smarthaul/sdk';

// Initialize client
const client = new SmartHaul({
  baseUrl: 'https://your-app.onrender.com',
  apiKey: 'your_jwt_token'
});

// Create booking
const booking = await client.bookings.create({
  customerId: 10,
  vendorId: 3,
  pickup: 'Lagos Island',
  destination: 'Victoria Island',
  itemDescription: 'Electronics',
  weightKg: 25
});

console.log(`Booking created: ${booking.id}`);
```

---

## Authentication

### Login
```javascript
const client = new SmartHaul({
  baseUrl: 'https://your-app.onrender.com'
});

// Login and get token
const authResponse = await client.auth.login({
  email: 'user@example.com',
  password: 'password123'
});

console.log(`Token: ${authResponse.token}`);
console.log(`Expires in: ${authResponse.expiresIn} seconds`);

// Token is automatically stored and used for subsequent requests
```

### Register
```javascript
// Register new user
const user = await client.auth.register({
  email: 'newuser@example.com',
  password: 'securepass123',
  fullName: 'John Doe',
  phone: '+234801234567',
  role: 'customer' // or 'provider', 'vendor', 'admin'
});

console.log(`User registered: ${user.userId}`);
```

### Using Token
```javascript
// Direct initialization with token
const client = new SmartHaul({
  baseUrl: 'https://your-app.onrender.com',
  apiKey: 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...'
});

// Or set token after initialization
client.setToken('new_token');
```

### Logout
```javascript
await client.auth.logout();
```

---

## Booking Management

### Create Booking
```javascript
const booking = await client.bookings.create({
  customerId: 10,
  vendorId: 3,
  pickup: 'Lagos Island',
  destination: 'Victoria Island',
  scheduledTime: '2026-07-02T14:00:00Z',
  itemDescription: 'Electronic equipment',
  weightKg: 25,
  estimatedDistanceKm: 15
});

console.log(`Booking ID: ${booking.id}`);
console.log(`Status: ${booking.status}`);
console.log(`Tracking Token: ${booking.bookingToken}`);
```

### List Bookings
```javascript
// Get all bookings
const bookings = await client.bookings.list();

// Filter by status
const pending = await client.bookings.list({ status: 'pending', limit: 10 });

// Paginate through results
const page1 = await client.bookings.list({ limit: 20, offset: 0 });
page1.items.forEach(booking => {
  console.log(`${booking.id}: ${booking.status}`);
});
```

### Get Booking Details
```javascript
const booking = await client.bookings.get(150);

console.log(`Customer: ${booking.customerId}`);
console.log(`Provider: ${booking.providerId}`);
console.log(`Status: ${booking.status}`);
console.log(`Amount: ${booking.amount} NGN`);
console.log(`Tracking: ${booking.trackingUrl}`);
```

### Update Booking
```javascript
const booking = await client.bookings.update(150, {
  status: 'accepted',
  notes: 'Driver confirmed pickup'
});

console.log(`Updated status: ${booking.status}`);
```

### Cancel Booking
```javascript
const result = await client.bookings.cancel(150, {
  reason: 'Changed my mind',
  refundMethod: 'wallet'
});

console.log(`Refund amount: ${result.refundAmount}`);
console.log(`Refund status: ${result.refundStatus}`);
```

---

## Provider Management

### Register as Provider
```javascript
const provider = await client.providers.register({
  userId: 20,
  businessName: 'Swift Transport Services',
  vehicleType: 'truck',
  vehicleRegistration: 'LG-123-ABC',
  licenseNumber: 'DL-2023-456789',
  insuranceProvider: 'AAA Insurance',
  insuranceExpiry: '2027-12-31'
});

console.log(`Provider ID: ${provider.providerId}`);
console.log(`Status: ${provider.status}`);
```

### List Providers
```javascript
// Get available providers
const providers = await client.providers.list({
  available: true,
  category: 'truck'
});

providers.items.forEach(provider => {
  console.log(`${provider.name}: ${provider.rating}/5`);
});
```

### Get Provider Details
```javascript
const provider = await client.providers.get(5);

console.log(`Name: ${provider.name}`);
console.log(`Rating: ${provider.rating}`);
console.log(`Total bookings: ${provider.totalBookings}`);
console.log(`Response time: ${provider.responseTimeMinutes} min`);
```

---

## Vendor Management

### Register as Vendor
```javascript
const vendor = await client.vendors.register({
  userId: 30,
  businessName: 'Premium Logistics Ltd',
  category: 'haulage',
  serviceArea: 'Lagos, Ogun',
  contactEmail: 'contact@premiumlogistics.com',
  phone: '+234801234567',
  documents: {
    businessRegistration: 'BRN-2023-789',
    taxCertificate: 'TIN-2023-456'
  }
});

console.log(`Vendor ID: ${vendor.vendorId}`);
```

### List Vendors
```javascript
const vendors = await client.vendors.list({ limit: 20 });

vendors.items.forEach(vendor => {
  console.log(`${vendor.name}: ${vendor.rating}/5`);
});
```

---

## Payment Processing

### List Payments
```javascript
const payments = await client.payments.list({ status: 'completed', limit: 20 });

payments.items.forEach(payment => {
  console.log(`Transaction ${payment.id}: ${payment.amount} ${payment.currency}`);
});
```

### Initiate Payment
```javascript
const payment = await client.payments.initiate({
  bookingId: 150,
  amount: 5000.00,
  currency: 'NGN',
  paymentMethod: 'card',
  returnUrl: 'https://your-app/bookings/150/success'
});

console.log(`Payment URL: ${payment.paymentUrl}`);
console.log(`Transaction ID: ${payment.transactionId}`);

// Redirect user to payment URL
window.location.href = payment.paymentUrl;
```

### Verify Payment
```javascript
const payment = await client.payments.verify('txn_abc123def456');

if (payment.status === 'completed') {
  console.log(`Payment verified! Amount: ${payment.amount}`);
} else {
  console.log(`Payment status: ${payment.status}`);
}
```

---

## Real-time Tracking

### Get Tracking Information
```javascript
// Using booking ID (requires authentication)
const tracking = await client.tracking.getByBooking(150);

console.log(`Location: ${tracking.location.latitude}, ${tracking.location.longitude}`);
console.log(`Estimated arrival: ${tracking.estimatedArrival}`);
console.log(`Provider phone: ${tracking.providerPhone}`);
```

### Public Tracking (No Auth Required)
```javascript
// Using public booking token
const tracking = await client.tracking.getByToken('bk_xpq9k2v8z3m1n5');

console.log(`Driver location: ${tracking.location.latitude}, ${tracking.location.longitude}`);
```

### Update Location (Provider)
```javascript
const result = await client.tracking.updateLocation('bk_xpq9k2v8z3m1n5', {
  latitude: 6.5010,
  longitude: 3.5890,
  accuracy: 12
});

console.log(`Location updated: ${result.status}`);
```

### Real-time Location Streaming
```javascript
// Subscribe to real-time location updates
const unsubscribe = client.tracking.onLocationUpdate(bookingToken, (location) => {
  console.log(`New location: ${location.latitude}, ${location.longitude}`);
  
  // Update map, UI, etc.
  updateMapMarker(location);
});

// Stop listening
// unsubscribe();
```

---

## Messaging

### Get Messages
```javascript
const messages = await client.messages.list({ bookingId: 150, limit: 50 });

messages.items.forEach(message => {
  console.log(`${message.senderName}: ${message.message}`);
});
```

### Send Message
```javascript
const message = await client.messages.send({
  bookingId: 150,
  recipientId: 5,
  message: "What's your current location?"
});

console.log(`Message sent: ${message.messageId}`);
```

### Real-time Messages
```javascript
// Subscribe to new messages
const unsubscribe = client.messages.onNewMessage(bookingId, (message) => {
  console.log(`${message.senderName}: ${message.message}`);
  
  // Update UI with new message
  addMessageToChat(message);
});

// Stop listening
// unsubscribe();
```

---

## Admin Operations

### Health Checks
```javascript
// Quick health check
const health = await client.admin.health();
console.log(`Status: ${health.status}`);

// Deep health check with dependencies
const deepHealth = await client.admin.healthDeep();
console.log(`Database: ${deepHealth.database.status}`);
console.log(`Cache: ${deepHealth.cache.status}`);
```

### System Logs
```javascript
const logs = await client.admin.getLogs({
  component: 'app',
  level: 'error',
  limit: 50
});

logs.items.forEach(log => {
  console.log(`[${log.level}] ${log.message}`);
});
```

### Monitoring Dashboard
```javascript
const dashboard = await client.admin.monitoringDashboard();

console.log(`Active bookings: ${dashboard.activeBookings}`);
console.log(`Daily revenue: ${dashboard.dailyRevenue}`);
console.log(`Uptime: ${dashboard.uptimePercent}%`);
console.log(`Error rate: ${dashboard.errorRate}%`);
```

### Database Backups
```javascript
// Create backup
const backup = await client.admin.backupCreate();
console.log(`Backup created: ${backup.backupId}`);

// List backups
const backups = await client.admin.backupList();
backups.items.forEach(backup => {
  console.log(`${backup.backupId}: ${backup.sizeMb}MB`);
});

// Restore from backup
const result = await client.admin.backupRestore('backup-20260701-180000');
console.log(`Restore status: ${result.status}`);
```

### SLA Metrics
```javascript
const sla = await client.admin.slaMetrics();

console.log(`Uptime: ${sla.uptimePercentage}%`);
console.log(`Response time P95: ${sla.responseTimeP95}ms`);
console.log(`Error rate: ${sla.errorRate}%`);
```

### Alerts Management
```javascript
// Get active alerts
const alerts = await client.admin.getAlerts();
alerts.items.forEach(alert => {
  console.log(`[${alert.severity}] ${alert.message}`);
});

// Create alert rule
const rule = await client.admin.createAlertRule({
  name: 'High Error Rate',
  condition: 'error_rate > 1',
  threshold: 0.01,
  alertType: 'critical'
});
```

### Scaling Management
```javascript
// Get scaling policies
const policies = await client.admin.getScalingPolicies();

// Create scaling policy
const policy = await client.admin.createScalingPolicy({
  name: 'CPU Scale Policy',
  metric: 'cpu',
  thresholdUp: 80.0,
  thresholdDown: 30.0,
  scaleUpInstances: 2
});

// Get recommendations
const recommendations = await client.admin.getCapacityPlan();
```

---

## Error Handling

```javascript
import { 
  SmartHaulError, 
  AuthenticationError, 
  ValidationError, 
  NotFoundError, 
  RateLimitError 
} from '@smarthaul/sdk';

try {
  const booking = await client.bookings.create({
    customerId: 10,
    vendorId: 3,
    pickup: 'Lagos',
    destination: 'Ibadan'
  });
} catch (error) {
  if (error instanceof AuthenticationError) {
    console.log('Please login first');
  } else if (error instanceof ValidationError) {
    console.log(`Validation error: ${error.details}`);
  } else if (error instanceof NotFoundError) {
    console.log('Resource not found');
  } else if (error instanceof RateLimitError) {
    console.log(`Rate limited - retry after ${error.retryAfter}s`);
  } else if (error instanceof SmartHaulError) {
    console.log(`Error: ${error.message}`);
  }
}
```

---

## Advanced Usage

### Custom Headers
```javascript
client.setHeaders({
  'X-Custom-Header': 'value',
  'User-Agent': 'MyApp/1.0'
});
```

### Request Timeout
```javascript
const client = new SmartHaul({
  baseUrl: 'https://your-app.onrender.com',
  timeout: 30000 // 30 seconds
});
```

### Request Interceptors
```javascript
// Add request interceptor
client.interceptors.request.use((config) => {
  config.headers['X-Request-ID'] = generateRequestId();
  return config;
});

// Add response interceptor
client.interceptors.response.use(
  (response) => response,
  (error) => {
    console.error('API Error:', error);
    return Promise.reject(error);
  }
);
```

### Retry Logic
```javascript
const client = new SmartHaul({
  baseUrl: 'https://your-app.onrender.com',
  retry: {
    maxAttempts: 3,
    backoffFactor: 0.5
  }
});
```

### Debug Logging
```javascript
// Enable debug mode
client.enableDebug();

// Or use environment variable
// SMARTHAUL_DEBUG=true
```

### Batch Operations
```javascript
// Create multiple bookings
const bookings = await Promise.all([
  client.bookings.create({ customerId: 10, vendorId: 3, ... }),
  client.bookings.create({ customerId: 11, vendorId: 4, ... }),
  client.bookings.create({ customerId: 12, vendorId: 5, ... })
]);

console.log(`Created ${bookings.length} bookings`);
```

### Event Listeners
```javascript
// Listen to auth state changes
client.on('auth:login', (user) => {
  console.log(`User logged in: ${user.email}`);
});

client.on('auth:logout', () => {
  console.log('User logged out');
});

client.on('auth:token-refresh', () => {
  console.log('Token refreshed');
});

// Listen to API errors
client.on('error', (error) => {
  console.error('API Error:', error);
});
```

---

## React Integration Example

```javascript
import { useEffect, useState } from 'react';
import SmartHaul from '@smarthaul/sdk';

const BookingComponent = () => {
  const [bookings, setBookings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const client = new SmartHaul({
      baseUrl: 'https://your-app.onrender.com',
      apiKey: localStorage.getItem('token')
    });

    // Fetch bookings
    client.bookings.list()
      .then(result => {
        setBookings(result.items);
        setLoading(false);
      })
      .catch(err => {
        setError(err.message);
        setLoading(false);
      });

    // Subscribe to real-time updates
    const unsubscribe = client.on('booking:update', (booking) => {
      setBookings(prev => 
        prev.map(b => b.id === booking.id ? booking : b)
      );
    });

    return () => unsubscribe();
  }, []);

  if (loading) return <div>Loading...</div>;
  if (error) return <div>Error: {error}</div>;

  return (
    <div>
      {bookings.map(booking => (
        <div key={booking.id}>
          <h3>{booking.pickup} → {booking.destination}</h3>
          <p>Status: {booking.status}</p>
        </div>
      ))}
    </div>
  );
};

export default BookingComponent;
```

---

## Vue Integration Example

```javascript
<template>
  <div>
    <div v-if="loading">Loading...</div>
    <div v-else-if="error">Error: {{ error }}</div>
    <div v-else>
      <div v-for="booking in bookings" :key="booking.id">
        <h3>{{ booking.pickup }} → {{ booking.destination }}</h3>
        <p>Status: {{ booking.status }}</p>
      </div>
    </div>
  </div>
</template>

<script>
import SmartHaul from '@smarthaul/sdk';

export default {
  data() {
    return {
      bookings: [],
      loading: true,
      error: null
    };
  },
  async mounted() {
    const client = new SmartHaul({
      baseUrl: 'https://your-app.onrender.com',
      apiKey: localStorage.getItem('token')
    });

    try {
      const result = await client.bookings.list();
      this.bookings = result.items;
    } catch (err) {
      this.error = err.message;
    } finally {
      this.loading = false;
    }
  }
};
</script>
```

---

## TypeScript Support

```typescript
import SmartHaul, { Booking, Payment, User } from '@smarthaul/sdk';

const client: SmartHaul = new SmartHaul({
  baseUrl: 'https://your-app.onrender.com',
  apiKey: 'token'
});

// Type-safe API calls
const booking: Booking = await client.bookings.get(150);
const payments: Payment[] = (await client.payments.list()).items;
const user: User = await client.auth.getCurrentUser();
```

---

## Browser Compatibility

- Chrome 90+
- Firefox 88+
- Safari 14+
- Edge 90+
- Mobile browsers (iOS Safari, Chrome Mobile)

---

## Support

- Documentation: https://docs.smarthaul.ng
- GitHub: https://github.com/smarthaul/sdk-javascript
- Email: dev@smarthaul.ng

---

## License

MIT License - See LICENSE file for details

