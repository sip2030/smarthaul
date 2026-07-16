"""Test provider unresponsiveness and provider-initiated cancellation after escrow capture."""
from datetime import timedelta
from decimal import Decimal
from django.test import TestCase
from django.utils.timezone import now
from rest_framework.test import APIClient
from rest_framework import status
from apps.analytics.models import ActivityLog
from apps.auth.models import CustomUser
from apps.bookings.models import Booking, CallLog
from apps.payments.models import Payment


class ProviderUnresponsivenesAndCancellationTest(TestCase):
    """Test 7.2 provider unresponsiveness and 7.5 provider cancellation logic."""

    def setUp(self):
        """Set up test users, bookings, and payments."""
        self.client = APIClient()

        # Create users
        self.customer = CustomUser.objects.create_user(
            username='customer',
            email='customer@test.com',
            password='testpass123',
            role='customer'
        )
        self.provider = CustomUser.objects.create_user(
            username='provider',
            email='provider@test.com',
            password='testpass123',
            role='provider'
        )
        self.admin = CustomUser.objects.create_user(
            username='admin',
            email='admin@test.com',
            password='testpass123',
            role='admin'
        )

    def test_provider_heartbeat_updates_ping_timestamp(self):
        """Test that provider_heartbeat action updates provider_last_ping_at."""
        booking = Booking.objects.create(
            customer=self.customer,
            provider=self.provider,
            service_type='transport',
            pickup='Location A',
            destination='Location B',
            price=Decimal('50.00'),
            status='accepted'
        )

        self.client.force_authenticate(user=self.provider)
        response = self.client.post(f'/api/bookings/{booking.id}/provider_heartbeat/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        booking.refresh_from_db()
        self.assertIsNotNone(booking.provider_last_ping_at)

    def test_provider_cannot_send_heartbeat_for_others_booking(self):
        """Test provider cannot heartbeat a booking assigned to another provider."""
        other_provider = CustomUser.objects.create_user(
            username='other_provider',
            email='other@test.com',
            password='testpass123',
            role='provider'
        )
        booking = Booking.objects.create(
            customer=self.customer,
            provider=other_provider,
            service_type='transport',
            pickup='Location A',
            destination='Location B',
            price=Decimal('50.00'),
            status='accepted'
        )

        self.client.force_authenticate(user=self.provider)
        response = self.client.post(f'/api/bookings/{booking.id}/provider_heartbeat/')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_check_unresponsive_providers_escalates_stale_bookings(self):
        """Test that check_unresponsive_providers escalates accepted bookings with no ping for 15+ min."""
        # Create an old accepted booking with no provider ping
        booking_old = Booking.objects.create(
            customer=self.customer,
            provider=self.provider,
            service_type='transport',
            pickup='Location A',
            destination='Location B',
            price=Decimal('50.00'),
            status='accepted',
            accepted_at=now() - timedelta(minutes=20)
        )

        # Create a recent accepted booking (should not be escalated)
        booking_recent = Booking.objects.create(
            customer=self.customer,
            provider=self.provider,
            service_type='transport',
            pickup='Location C',
            destination='Location D',
            price=Decimal('60.00'),
            status='accepted'
        )

        self.client.force_authenticate(user=self.admin)
        response = self.client.post('/api/bookings/check_unresponsive_providers/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn(booking_old.id, data['escalated_bookings'])
        self.assertNotIn(booking_recent.id, data['escalated_bookings'])

        booking_old.refresh_from_db()
        self.assertEqual(booking_old.status, 'admin_review')

    def test_provider_cancellation_after_escrow_auto_refunds(self):
        """Test that provider cancelling after escrow is captured auto-refunds customer."""
        booking = Booking.objects.create(
            customer=self.customer,
            provider=self.provider,
            service_type='transport',
            pickup='Location A',
            destination='Location B',
            price=Decimal('100.00'),
            status='accepted',
            accepted_at=now() - timedelta(minutes=30)
        )

        # Create payment with held escrow
        payment = Payment.objects.create(
            booking=booking,
            amount=Decimal('100.00'),
            status='completed',
            escrow_status='held'
        )

        # Provider cancels
        self.client.force_authenticate(user=self.provider)
        response = self.client.post(f'/api/bookings/{booking.id}/cancel_booking/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        booking.refresh_from_db()
        payment.refresh_from_db()

        self.assertEqual(booking.status, 'cancelled')
        self.assertEqual(booking.cancelled_by, 'provider')
        self.assertIsNotNone(booking.cancellation_fee_owed)
        self.assertIsNotNone(booking.cancellation_fee_logged_at)

        # Check auto-refund
        self.assertEqual(payment.status, 'refunded')
        self.assertEqual(payment.escrow_status, 'refunded')

        # Check fee calculation (10% default)
        expected_fee = (Decimal('100.00') * (booking.cancellation_fee_percent / Decimal('100'))).quantize(Decimal('0.01'))
        self.assertEqual(booking.cancellation_fee_owed, expected_fee)
        self.assertEqual(booking.cancellation_fee_paid_by, 'provider')

    def test_provider_cancellation_without_escrow_does_not_refund(self):
        """Test that provider cancellation without held escrow doesn't trigger refund logic."""
        booking = Booking.objects.create(
            customer=self.customer,
            provider=self.provider,
            service_type='transport',
            pickup='Location A',
            destination='Location B',
            price=Decimal('100.00'),
            status='pending'
        )

        # No payment exists
        self.client.force_authenticate(user=self.provider)
        response = self.client.post(f'/api/bookings/{booking.id}/cancel_booking/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'cancelled')
        self.assertEqual(booking.cancelled_by, 'provider')
        # Fee should not be logged without payment
        self.assertIsNone(booking.cancellation_fee_owed)

    def test_cancelled_by_field_tracks_who_cancelled(self):
        """Test that cancelled_by field is set correctly for different roles."""
        customer_booking = Booking.objects.create(
            customer=self.customer,
            provider=self.provider,
            service_type='transport',
            pickup='Location A',
            destination='Location B',
            price=Decimal('50.00'),
            status='pending'
        )

        self.client.force_authenticate(user=self.customer)
        response = self.client.post(f'/api/bookings/{customer_booking.id}/cancel_booking/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        customer_booking.refresh_from_db()
        self.assertEqual(customer_booking.cancelled_by, 'customer')
        self.assertTrue(ActivityLog.objects.filter(action='booking_cancelled', target_id=str(customer_booking.id)).exists())

    def test_customer_cancellation_after_window_applies_fee(self):
        booking = Booking.objects.create(
            customer=self.customer,
            provider=self.provider,
            service_type='transport',
            pickup='Location A',
            destination='Location B',
            price=Decimal('100.00'),
            status='accepted',
            accepted_at=now() - timedelta(minutes=30)
        )

        self.client.force_authenticate(user=self.customer)
        response = self.client.post(f'/api/bookings/{booking.id}/cancel_booking/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        booking.refresh_from_db()
        self.assertEqual(booking.cancelled_by, 'customer')
        self.assertIsNotNone(booking.cancellation_fee_owed)
        self.assertEqual(booking.cancellation_fee_paid_by, 'customer')

    def test_customer_cancellation_within_window_auto_refunds_payment(self):
        booking = Booking.objects.create(
            customer=self.customer,
            provider=self.provider,
            service_type='transport',
            pickup='Location A',
            destination='Location B',
            price=Decimal('100.00'),
            status='accepted',
            accepted_at=now() - timedelta(minutes=5)
        )

        payment = Payment.objects.create(
            booking=booking,
            amount=Decimal('100.00'),
            status='completed',
            escrow_status='held'
        )

        self.client.force_authenticate(user=self.customer)
        response = self.client.post(f'/api/bookings/{booking.id}/cancel_booking/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        booking.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(booking.cancelled_by, 'customer')
        self.assertIsNone(booking.cancellation_fee_owed)
        self.assertEqual(payment.status, 'refunded')
        self.assertEqual(payment.escrow_status, 'refunded')

    def test_cancellation_within_window_is_fee_free(self):
        booking = Booking.objects.create(
            customer=self.customer,
            provider=self.provider,
            service_type='transport',
            pickup='Location A',
            destination='Location B',
            price=Decimal('100.00'),
            status='accepted',
            accepted_at=now() - timedelta(minutes=5)
        )

        self.client.force_authenticate(user=self.provider)
        response = self.client.post(f'/api/bookings/{booking.id}/cancel_booking/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        booking.refresh_from_db()
        self.assertIsNone(booking.cancellation_fee_owed)
        self.assertEqual(booking.cancellation_fee_paid_by, '')


class PendingBookingTimeoutTest(TestCase):
    """Test timeout-based auto-cancellation for pending bookings."""

    def setUp(self):
        self.client = APIClient()
        self.customer = CustomUser.objects.create_user(
            username='timeout_customer',
            email='timeout_customer@test.com',
            password='testpass123',
            role='customer'
        )
        self.provider = CustomUser.objects.create_user(
            username='timeout_provider',
            email='timeout_provider@test.com',
            password='testpass123',
            role='provider'
        )
        self.admin = CustomUser.objects.create_user(
            username='timeout_admin',
            email='timeout_admin@test.com',
            password='testpass123',
            role='admin'
        )

    def test_pending_booking_gets_timeout_when_list_is_accessed(self):
        booking = Booking.objects.create(
            customer=self.customer,
            service_type='transport',
            pickup='Location A',
            destination='Location B',
            price=Decimal('80.00'),
            status='pending',
        )
        booking.pending_expires_at = now() - timedelta(minutes=1)
        booking.save(update_fields=['pending_expires_at'])

        self.client.force_authenticate(user=self.customer)
        response = self.client.get('/api/bookings/my_bookings/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'cancelled')
        self.assertEqual(booking.cancelled_by, 'system')

    def test_provider_cannot_accept_expired_booking(self):
        booking = Booking.objects.create(
            customer=self.customer,
            service_type='transport',
            pickup='Location A',
            destination='Location B',
            price=Decimal('80.00'),
            status='pending',
        )
        booking.pending_expires_at = now() - timedelta(minutes=1)
        booking.save(update_fields=['pending_expires_at'])

        self.client.force_authenticate(user=self.provider)
        response = self.client.post(f'/api/bookings/{booking.id}/accept_booking/')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'cancelled')
        self.assertEqual(booking.cancelled_by, 'system')

    def test_admin_can_run_pending_timeout_check_and_notify_customer(self):
        booking = Booking.objects.create(
            customer=self.customer,
            service_type='transport',
            pickup='Location A',
            destination='Location B',
            price=Decimal('80.00'),
            status='pending',
        )
        booking.pending_expires_at = now() - timedelta(minutes=1)
        booking.save(update_fields=['pending_expires_at'])

        self.client.force_authenticate(user=self.admin)
        response = self.client.post('/api/bookings/check_pending_timeouts/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn(booking.id, data['expired_bookings'])
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'cancelled')
        self.assertEqual(booking.cancelled_by, 'system')


class BookingRescheduleTest(TestCase):
    """Test reschedule request and response flow."""

    def setUp(self):
        self.client = APIClient()
        self.customer = CustomUser.objects.create_user(
            username='reschedule_customer',
            email='reschedule_customer@test.com',
            password='testpass123',
            role='customer'
        )
        self.provider = CustomUser.objects.create_user(
            username='reschedule_provider',
            email='reschedule_provider@test.com',
            password='testpass123',
            role='provider'
        )

    def test_customer_can_request_reschedule(self):
        booking = Booking.objects.create(
            customer=self.customer,
            provider=self.provider,
            service_type='transport',
            pickup='Location A',
            destination='Location B',
            price=Decimal('80.00'),
            status='accepted',
        )

        self.client.force_authenticate(user=self.customer)
        response = self.client.post(f'/api/bookings/{booking.id}/reschedule_booking/', {
            'decision': 'request',
            'proposed_for_at': '2026-07-16T10:00:00Z',
            'reason': 'Need a later pickup time',
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        booking.refresh_from_db()
        self.assertEqual(booking.reschedule_status, 'pending')
        self.assertEqual(booking.reschedule_requested_by, 'customer')
        self.assertIsNotNone(booking.reschedule_proposed_for_at)
        self.assertEqual(booking.scheduled_for_at.isoformat(), '2026-07-16T10:00:00+00:00')

    def test_provider_can_accept_reschedule_request(self):
        booking = Booking.objects.create(
            customer=self.customer,
            provider=self.provider,
            service_type='transport',
            pickup='Location A',
            destination='Location B',
            price=Decimal('80.00'),
            status='accepted',
        )

        self.client.force_authenticate(user=self.customer)
        self.client.post(f'/api/bookings/{booking.id}/reschedule_booking/', {
            'decision': 'request',
            'proposed_for_at': '2026-07-16T10:00:00Z',
            'reason': 'Need a later pickup time',
        }, format='json')

        self.client.force_authenticate(user=self.provider)
        response = self.client.post(f'/api/bookings/{booking.id}/reschedule_booking/', {
            'decision': 'accept'
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        booking.refresh_from_db()
        self.assertEqual(booking.reschedule_status, 'accepted')
        self.assertIsNotNone(booking.reschedule_response_at)

    def test_requester_cannot_respond_to_own_reschedule_request(self):
        booking = Booking.objects.create(
            customer=self.customer,
            provider=self.provider,
            service_type='transport',
            pickup='Location A',
            destination='Location B',
            price=Decimal('80.00'),
            status='accepted',
        )

        self.client.force_authenticate(user=self.customer)
        self.client.post(f'/api/bookings/{booking.id}/reschedule_booking/', {
            'decision': 'request',
            'proposed_for_at': '2026-07-16T10:00:00Z',
            'reason': 'Need a later pickup time',
        }, format='json')

        response = self.client.post(f'/api/bookings/{booking.id}/reschedule_booking/', {
            'decision': 'accept'
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class CallLoggingTest(TestCase):
    """Test call logging scoped to booking-level disputes and safety reports."""

    def setUp(self):
        """Set up test users and bookings."""
        self.client = APIClient()

        self.customer = CustomUser.objects.create_user(
            username='customer_call',
            email='customer_call@test.com',
            password='testpass123',
            role='customer'
        )
        self.provider = CustomUser.objects.create_user(
            username='provider_call',
            email='provider_call@test.com',
            password='testpass123',
            role='provider'
        )
        self.admin = CustomUser.objects.create_user(
            username='admin_call',
            email='admin_call@test.com',
            password='testpass123',
            role='admin'
        )

        self.booking = Booking.objects.create(
            customer=self.customer,
            provider=self.provider,
            service_type='transport',
            pickup='Location A',
            destination='Location B',
            price=Decimal('100.00'),
            status='in_progress'
        )

    def test_call_not_logged_without_dispute_or_report(self):
        """Test that calls are NOT logged when booking has no dispute or safety report."""
        self.client.force_authenticate(user=self.customer)

        response = self.client.post(f'/api/bookings/{self.booking.id}/start_call/', {
            'caller_id': self.customer.id,
            'recipient_id': self.provider.id,
            'call_type': 'outbound',
            'call_medium': 'audio',
            'consent_acknowledged': True,
        })

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertFalse(data['call_should_be_logged'])
        self.assertIn('reason_for_logging', data)

    def test_call_logged_when_dispute_active(self):
        """Test that calls ARE logged when booking has an active dispute."""
        # Admin marks dispute as active
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(f'/api/bookings/{self.booking.id}/file_dispute_or_report/', {
            'dispute_active': True
        })

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.booking.refresh_from_db()
        self.assertTrue(self.booking.has_active_dispute)

        # Now customer initiates a call
        self.client.force_authenticate(user=self.customer)
        response = self.client.post(f'/api/bookings/{self.booking.id}/start_call/', {
            'caller_id': self.customer.id,
            'recipient_id': self.provider.id,
            'call_type': 'outbound',
            'call_medium': 'video',
            'consent_acknowledged': True,
        })

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertTrue(data['call_should_be_logged'])
        self.assertEqual(data['reason_for_logging'], 'dispute_active')

    def test_call_logged_when_safety_report_filed(self):
        """Test that calls ARE logged when a safety report has been filed."""
        # Admin files a safety report
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(f'/api/bookings/{self.booking.id}/file_dispute_or_report/', {
            'safety_report_filed': True
        })

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.booking.refresh_from_db()
        self.assertIsNotNone(self.booking.safety_report_filed_at)

        # Now a call is made
        self.client.force_authenticate(user=self.customer)
        response = self.client.post(f'/api/bookings/{self.booking.id}/start_call/', {
            'caller_id': self.customer.id,
            'recipient_id': self.provider.id,
            'call_type': 'inbound',
            'call_medium': 'audio',
            'consent_acknowledged': True,
        })

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertTrue(data['call_should_be_logged'])
        self.assertEqual(data['reason_for_logging'], 'safety_report_filed')

    def test_call_log_records_duration(self):
        """Test that call logs record duration when ended."""
        self.client.force_authenticate(user=self.customer)

        # Start a call
        response = self.client.post(f'/api/bookings/{self.booking.id}/start_call/', {
            'caller_id': self.customer.id,
            'recipient_id': self.provider.id,
            'call_type': 'outbound',
            'call_medium': 'audio',
            'consent_acknowledged': True,
        })

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        call_id = response.json()['id']

        # End the call (wait a bit to ensure duration > 0)
        response = self.client.post(f'/api/bookings/{self.booking.id}/calls/{call_id}/end/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIsNotNone(data['ended_at'])
        self.assertIsNotNone(data['duration_seconds'])
        self.assertGreaterEqual(data['duration_seconds'], 0)

    def test_call_requires_explicit_consent(self):
        self.client.force_authenticate(user=self.customer)

        response = self.client.post(f'/api/bookings/{self.booking.id}/start_call/', {
            'caller_id': self.customer.id,
            'recipient_id': self.provider.id,
            'call_type': 'outbound',
            'call_medium': 'audio',
        })

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Consent must be acknowledged', response.json()['error'])

    def test_only_authorized_users_can_view_call_logs(self):
        """Test that only customer, provider, and admin can view call logs."""
        other_user = CustomUser.objects.create_user(
            username='other_user',
            email='other@test.com',
            password='testpass123',
            role='customer'
        )

        # Create a call log
        CallLog = Booking.objects.first().call_logs.model
        CallLog.objects.create(
            booking=self.booking,
            caller=self.customer,
            recipient=self.provider,
            call_type='outbound',
            consent_acknowledged=True,
            call_should_be_logged=False
        )

        # Other user cannot view
        self.client.force_authenticate(user=other_user)
        response = self.client.get(f'/api/bookings/{self.booking.id}/call_logs/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # Customer can view
        self.client.force_authenticate(user=self.customer)
        response = self.client.get(f'/api/bookings/{self.booking.id}/call_logs/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Provider can view
        self.client.force_authenticate(user=self.provider)
        response = self.client.get(f'/api/bookings/{self.booking.id}/call_logs/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Admin can view
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(f'/api/bookings/{self.booking.id}/call_logs/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
