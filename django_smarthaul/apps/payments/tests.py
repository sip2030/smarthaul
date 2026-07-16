from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils.timezone import now
from rest_framework import status
from rest_framework.test import APIClient

from apps.analytics.models import ActivityLog
from apps.auth.models import CustomUser
from apps.bookings.models import Booking
from apps.payments.models import Payment


class PaymentEscrowWindowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.customer = CustomUser.objects.create_user(
            username='payment_customer',
            email='payment_customer@test.com',
            password='testpass123',
            role='customer',
        )
        self.admin = CustomUser.objects.create_user(
            username='payment_admin',
            email='payment_admin@test.com',
            password='testpass123',
            role='admin',
        )
        self.booking = Booking.objects.create(
            customer=self.customer,
            service_type='transport',
            pickup='Yaba',
            destination='Lekki',
            price=Decimal('1000.00'),
            status='pending',
        )

    def test_verify_payment_schedules_payout_release(self):
        payment = Payment.objects.create(
            booking=self.booking,
            amount=Decimal('1000.00'),
            gateway='flutterwave',
        )
        self.client.force_authenticate(user=self.customer)
        response = self.client.post(f'/api/payments/{payment.id}/verify_payment/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'completed')
        self.assertEqual(payment.escrow_status, 'held')
        self.assertEqual(payment.payout_status, 'pending')
        self.assertIsNotNone(payment.payout_release_at)
        self.assertGreater(payment.payout_release_at, payment.completed_at)
        self.assertTrue(ActivityLog.objects.filter(action='payment_verified', target_id=str(payment.id)).exists())

    def test_release_payout_rejected_before_dispute_window_expires(self):
        payment = Payment.objects.create(
            booking=self.booking,
            amount=Decimal('1000.00'),
            status='completed',
            escrow_status='held',
            payout_status='pending',
            completed_at=now(),
            payout_release_at=now() + timedelta(hours=24),
        )

        self.client.force_authenticate(user=self.admin)
        response = self.client.post(f'/api/payments/{payment.id}/release_payout/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        payment.refresh_from_db()
        self.assertEqual(payment.payout_status, 'pending')
        self.assertEqual(payment.escrow_status, 'held')

    def test_process_due_payouts_releases_completed_payments_after_window(self):
        payment = Payment.objects.create(
            booking=self.booking,
            amount=Decimal('1000.00'),
            status='completed',
            escrow_status='held',
            payout_status='pending',
            completed_at=now() - timedelta(hours=25),
            payout_release_at=now() - timedelta(hours=1),
        )

        self.client.force_authenticate(user=self.admin)
        response = self.client.post('/api/payments/process_due_payouts/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn(payment.id, data['released_payments'])
        payment.refresh_from_db()
        self.assertEqual(payment.payout_status, 'released')
        self.assertEqual(payment.escrow_status, 'released')
        self.assertIsNotNone(payment.payout_released_at)

    def test_disputed_booking_blocks_payout_release(self):
        self.booking.has_active_dispute = True
        self.booking.status = 'disputed'
        self.booking.save(update_fields=['has_active_dispute', 'status'])

        payment = Payment.objects.create(
            booking=self.booking,
            amount=Decimal('1000.00'),
            status='completed',
            escrow_status='held',
            payout_status='pending',
            completed_at=now() - timedelta(hours=25),
            payout_release_at=now() - timedelta(hours=1),
        )

        self.client.force_authenticate(user=self.admin)
        response = self.client.post(f'/api/payments/{payment.id}/release_payout/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        payment.refresh_from_db()
        self.assertEqual(payment.payout_status, 'pending')
