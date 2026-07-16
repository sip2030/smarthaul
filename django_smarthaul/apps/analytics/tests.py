from decimal import Decimal

from django.test import TestCase
from django.utils.timezone import now
from rest_framework import status
from rest_framework.test import APIClient

from apps.auth.models import CustomUser
from apps.analytics.models import log_activity
from apps.bookings.models import Booking
from apps.communications.models import SafetyReport, SupportCase
from apps.payments.models import Payment
from apps.providers.models import Provider
from apps.vendors.models import Vendor, VendorOrder, VendorListing


class AnalyticsEndpointTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = CustomUser.objects.create_user(
            username='analytics_admin',
            email='analytics_admin@test.com',
            password='testpass123',
            role='admin',
        )
        self.customer = CustomUser.objects.create_user(
            username='analytics_customer',
            email='analytics_customer@test.com',
            password='testpass123',
            role='customer',
        )
        self.provider_user = CustomUser.objects.create_user(
            username='analytics_provider',
            email='analytics_provider@test.com',
            password='testpass123',
            role='provider',
        )
        self.vendor_user = CustomUser.objects.create_user(
            username='analytics_vendor',
            email='analytics_vendor@test.com',
            password='testpass123',
            role='vendor',
        )
        Provider.objects.create(
            user=self.provider_user,
            service_area='Lagos',
            vehicle_type='Truck',
            license_number='LIC-001',
            rating=4.8,
            total_earnings=Decimal('120000.00'),
            total_bookings=12,
            completed_bookings=9,
        )
        self.vendor = Vendor.objects.create(
            user=self.vendor_user,
            name='Vendor One',
            category='Logistics',
            location='Lagos',
            rating=4.7,
            total_earnings=Decimal('80000.00'),
            total_orders=10,
            total_completed_orders=8,
            onboarding_status='approved',
            document_status='approved',
        )
        self.listing = VendorListing.objects.create(
            vendor=self.vendor,
            title='Moving boxes',
            description='Cardboard boxes for moving and storage',
            listing_type='product',
            category='Packaging',
            price=Decimal('12000.00'),
            quantity_available=10,
        )
        self.booking = Booking.objects.create(
            customer=self.customer,
            provider=self.provider_user,
            vendor=self.vendor,
            service_type='transport',
            pickup='Yaba',
            destination='Lekki',
            price=Decimal('5000.00'),
            status='completed',
        )
        VendorOrder.objects.create(
            customer=self.customer,
            vendor=self.vendor,
            listing=self.listing,
            quantity=1,
            unit_price=Decimal('12000.00'),
            total_amount=Decimal('12000.00'),
            status='cancelled',
            refund_status='pending_review',
            refund_amount=Decimal('12000.00'),
            refund_requested_by='vendor',
            refund_requested_at=now(),
        )
        Payment.objects.create(
            booking=self.booking,
            amount=Decimal('5000.00'),
            status='completed',
            escrow_status='held',
            payout_status='pending',
        )
        Payment.objects.create(
            booking=Booking.objects.create(
                customer=self.customer,
                provider=self.provider_user,
                vendor=self.vendor,
                service_type='transport',
                pickup='Yaba',
                destination='Lekki',
                price=Decimal('2500.00'),
                status='cancelled',
            ),
            amount=Decimal('2500.00'),
            status='refunded',
            escrow_status='refunded',
            payout_status='pending',
        )
        SupportCase.objects.create(
            user=self.customer,
            booking=self.booking,
            subject='Refund status',
            description='Need help with refund',
            status='open',
            priority='normal',
        )
        SafetyReport.objects.create(
            reporter=self.customer,
            booking=self.booking,
            report_type='harassment',
            target_type='booking',
            target_name='Booking incident',
            description='Unsafe behavior during the booking.',
        )
        log_activity(
            actor=self.admin,
            action='vendor_listing_removed',
            target_type='vendor_listing',
            target_id='42',
            summary='Removed a vendor listing for policy reasons.',
            metadata={'reason': 'policy_violation'},
        )
        log_activity(
            actor=self.admin,
            action='account_warned',
            target_type='user',
            target_id=str(self.customer.id),
            summary='Warned a customer account.',
            metadata={'reason': 'abusive_language'},
        )

    def test_summary_requires_admin_access(self):
        self.client.force_authenticate(user=self.customer)
        response = self.client.get('/api/analytics/summary/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_summary_returns_key_metrics_for_admin(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.get('/api/analytics/summary/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data['users']['total'], 4)
        self.assertEqual(data['bookings']['completed'], 1)
        self.assertEqual(data['payments']['completed'], 1)
        self.assertEqual(data['payments']['refunded'], 1)
        self.assertEqual(data['payments']['refunded_value'], Decimal('2500.00'))
        self.assertEqual(data['support']['cases_total'], 1)
        self.assertEqual(data['support']['safety_reports_total'], 1)
        self.assertEqual(data['marketplace']['vendor_orders']['cancelled'], 1)
        self.assertEqual(data['marketplace']['vendor_orders']['refund_reviews'], 1)
        self.assertEqual(data['marketplace']['vendor_orders']['statuses'][0]['status'], 'cancelled')
        self.assertEqual(data['activity']['warnings'], 1)
        self.assertEqual(data['activity']['audit_events_total'], 2)
        self.assertTrue(any(provider['id'] for provider in data['marketplace']['top_providers']))
        self.assertTrue(any(vendor['id'] for vendor in data['marketplace']['top_vendors']))

    def test_activity_returns_recent_objects_for_admin(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.get('/api/analytics/activity/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertTrue(data['recent_bookings'])
        self.assertTrue(data['recent_payments'])
        self.assertTrue(data['recent_support_cases'])
        self.assertTrue(data['recent_safety_reports'])
        self.assertTrue(data['recent_activity_logs'])

    def test_audit_returns_explicit_activity_logs_for_admin(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.get('/api/analytics/audit/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data['count'], 2)
        self.assertTrue(any(item['action'] == 'vendor_listing_removed' for item in data['results']))
        self.assertTrue(any(item['action'] == 'account_warned' for item in data['results']))
        listing_removal = next(item for item in data['results'] if item['action'] == 'vendor_listing_removed')
        self.assertEqual(listing_removal['metadata']['reason'], 'policy_violation')

    def test_dashboard_returns_trends_and_alerts_for_admin(self):
        self.client.force_authenticate(user=self.admin)
        self.customer.failed_login_attempts = 4
        self.customer.save(update_fields=['failed_login_attempts'])

        self.booking.status = 'admin_review'
        self.booking.has_active_dispute = True
        self.booking.dispute_started_at = self.booking.created_at
        self.booking.save(update_fields=['status', 'has_active_dispute', 'dispute_started_at'])

        response = self.client.get('/api/analytics/dashboard/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertIn('overview', data)
        self.assertIn('trends', data)
        self.assertIn('alerts', data)
        self.assertTrue(data['overview']['active_bookings'] >= 0)
        self.assertEqual(data['overview']['pending_vendor_refunds'], 1)
        self.assertEqual(data['overview']['refunded_value_7d'], Decimal('2500.00'))
        self.assertTrue(data['overview']['audit_events_7d'] >= 2)
        self.assertTrue(any(item['action'] == 'account_warned' for item in data['trends']['audit_action_breakdown']))
        self.assertTrue(any(item['status'] == 'cancelled' for item in data['trends']['vendor_order_status_breakdown']))
        self.assertTrue(any(item['refund_status'] == 'pending_review' for item in data['trends']['vendor_order_refund_breakdown']))
        self.assertTrue(data['trends']['refunded_payments_7d'])
        self.assertTrue(len(data['trends']['moderation_trend_7d']) >= 1)
        self.assertTrue(any(alert['type'] == 'booking_review' for alert in data['alerts']))
        self.assertTrue(any(alert['type'] == 'failed_logins' for alert in data['alerts']))
        self.assertTrue(any(alert['type'] == 'vendor_refund_reviews' for alert in data['alerts']))

    def test_alerts_endpoint_returns_alert_list_for_admin(self):
        self.client.force_authenticate(user=self.admin)
        self.booking.status = 'admin_review'
        self.booking.save(update_fields=['status'])

        response = self.client.get('/api/analytics/alerts/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertGreaterEqual(data['count'], 1)
        self.assertTrue(any(alert['type'] == 'booking_review' for alert in data['results']))
