"""Test provider unresponsiveness and provider-initiated cancellation after escrow capture."""
from datetime import timedelta
from decimal import Decimal
from django.test import TestCase
from django.utils.timezone import now
from rest_framework.test import APIClient
from rest_framework import status
from apps.auth.models import CustomUser
from apps.bookings.models import Booking
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
        self.assertAlmostEqual(
            (now() - booking.provider_last_ping_at).total_seconds(),
            0,
            delta=2  # Allow 2 seconds drift
        )

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
        stale_accepted_at = now() - timedelta(minutes=20)

        # Create an old accepted booking with no provider ping
        booking_old = Booking.objects.create(
            customer=self.customer,
            provider=self.provider,
            service_type='transport',
            pickup='Location A',
            destination='Location B',
            price=Decimal('50.00'),
            status='accepted',
        )
        # Use update() to bypass auto_now on updated_at and set accepted_at to the past
        Booking.objects.filter(pk=booking_old.pk).update(accepted_at=stale_accepted_at)
        booking_old.refresh_from_db()

        # Create a recent accepted booking (should not be escalated)
        booking_recent = Booking.objects.create(
            customer=self.customer,
            provider=self.provider,
            service_type='transport',
            pickup='Location C',
            destination='Location D',
            price=Decimal('60.00'),
            status='accepted',
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
        old_accepted_at = now() - timedelta(minutes=30)
        booking = Booking.objects.create(
            customer=self.customer,
            provider=self.provider,
            service_type='transport',
            pickup='Location A',
            destination='Location B',
            price=Decimal('100.00'),
            status='accepted',
        )
        # Push accepted_at outside the cancellation window so the fee applies
        Booking.objects.filter(pk=booking.pk).update(accepted_at=old_accepted_at)
        booking.refresh_from_db()

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
        expected_fee = (Decimal('100.00') * Decimal('0.10')).quantize(Decimal('0.01'))
        self.assertEqual(booking.cancellation_fee_owed, expected_fee)

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
